"""Preview tickets for squad writes (Prompt E, 2026-10-27).

THE RULE. A squad write through the agent (model_tools.set_my_squad with confirm=true) needs a ticket that a
preview (confirm=false) issued in an EARLIER turn for the SAME change against the SAME active version; otherwise
nothing is written. Measured need: the sonnet-5 gate of 27 Oct (eval/reports/agent_sonnet5_gate_v1.md, L1) saw the
model call set_my_squad(confirm=true) in the turn after "Swap Mbeumo for Wirtz" without the user ever saying yes,
and the squad was written. The system prompt's two-turn rule was the only lock; this one is in code.

THE TICKET (table squad_previews, created by ensure_schema -- idempotent, the project's pattern; no migration tool):
id (random, unguessable), user_id, turn_id and turn_started_at (the turn the preview was shown in, from the loop's
own channel turn_context -- never from the model), change_fingerprint (sha256 of a canonical JSON of the requested
change: the fifteen as a set, captain, vice, bench order, gameweek), base_version_id (the active version previewed
against), created_at, expires_at (+30 min), used_at, cancelled_at. A new preview cancels the user's older open tickets;
/reset cancels them all; a write marks its ticket used IN THE SAME TRANSACTION as the version row (consume runs on the
caller's connection and commits nothing: squad_store.write_version commits both or rolls both back).

THE CHECKS, in the order the refusal names them: missing (no ticket given, no such row, or another user's),
same_turn (issued in this turn, or in a turn that started no earlier than this one), used, cancelled, expired,
different_change (fingerprint), squad_changed (the active version is no longer the one previewed against).
The refusal text is one fixed sentence naming the reason; the preview's message names the ticket and how to spend it.

Usage: python squad_previews.py --init  (ensure the table on the configured database) | --print-ddl"""
import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

import config_roles
import db_write

TTL = timedelta(minutes=30)
REASONS = ("missing", "same_turn", "different_change", "squad_changed", "used", "cancelled", "expired")

DDL = """
CREATE TABLE IF NOT EXISTS squad_previews (
    id                  TEXT        PRIMARY KEY,
    user_id             INT         NOT NULL,
    turn_id             TEXT        NOT NULL,
    turn_started_at     TIMESTAMPTZ NOT NULL,
    change_fingerprint  TEXT        NOT NULL,
    base_version_id     INT         NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    used_at             TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_squad_previews_user_open
    ON squad_previews (user_id) WHERE used_at IS NULL AND cancelled_at IS NULL;
"""


def ensure_schema(conn):
    """Create squad_previews and its index if they do not exist. Idempotent; no query parameters."""
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def clock():
    return datetime.now(timezone.utc)


def new_id():
    return secrets.token_urlsafe(18)


def fingerprint(player_ids, captain_id, vice_id, bench_order_ids, gw, **_ignored):
    """sha256 of the canonical JSON of the requested change: the fifteen as a sorted set, captain, vice, the bench
    IN ORDER, the gameweek. A note or a proposal id is not the change. Extra keywords are ignored so a tool's whole
    argument set can be passed."""
    def _i(x):
        return None if x is None else int(x)
    canon = {"players": sorted(_i(x) for x in (player_ids or [])), "captain": _i(captain_id), "vice": _i(vice_id),
             "bench": [_i(x) for x in (bench_order_ids or [])], "gw": _i(gw)}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def refusal(reason):
    return f"No valid preview for this change (reason: {reason}). Show the user a preview first."


def ticket_sentence(ticket_id):
    return (f"Preview ticket {ticket_id}. To apply it after the user says yes in their next message, call this tool "
            f"again with the same changes, confirm=true and preview_ticket={ticket_id}.")


def issue(conn, user_id, turn, fp, base_version_id, now=None):
    """Cancel the user's older open tickets and insert a new one; commits. Returns {"id", "expires_at",
    "cancelled_older"}."""
    now = now or clock()
    ticket_id = new_id()
    with conn.cursor() as cur:
        cur.execute("UPDATE squad_previews SET cancelled_at = %s "
                    "WHERE user_id = %s AND used_at IS NULL AND cancelled_at IS NULL", (now, user_id))
        cancelled = cur.rowcount
        cur.execute("INSERT INTO squad_previews (id, user_id, turn_id, turn_started_at, change_fingerprint, "
                    "base_version_id, created_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (ticket_id, int(user_id), str(turn["turn_id"]), turn["started_at"], fp, int(base_version_id),
                     now, now + TTL))
    conn.commit()
    return {"id": ticket_id, "expires_at": now + TTL, "cancelled_older": cancelled}


def check(row, user_id, turn, fp, active_version_id, now):
    """Pure. The reason a ticket row cannot be spent now, or None when it can."""
    if row is None or int(row["user_id"]) != int(user_id):
        return "missing"
    if row["turn_id"] == turn["turn_id"] or row["turn_started_at"] >= turn["started_at"]:
        return "same_turn"
    if row["used_at"] is not None:
        return "used"
    if row["cancelled_at"] is not None:
        return "cancelled"
    if now >= row["expires_at"]:
        return "expired"
    if row["change_fingerprint"] != fp:
        return "different_change"
    if int(row["base_version_id"]) != int(active_version_id):
        return "squad_changed"
    return None


def consume(conn, user_id, ticket_id, turn, fp, active_version_id, now=None):
    """Inside the caller's transaction: lock the ticket row, check it, mark it used. Returns the reason it was
    refused, or None when it was marked used. Commits NOTHING -- the caller's write commits (or rolls back) both."""
    now = now or clock()
    if not ticket_id:
        return "missing"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM squad_previews WHERE id = %s AND user_id = %s FOR UPDATE",
                    (str(ticket_id), int(user_id)))
        row = cur.fetchone()
        reason = check(dict(row) if row else None, user_id, turn, fp, active_version_id, now)
        if reason:
            return reason
        cur.execute("UPDATE squad_previews SET used_at = %s WHERE id = %s AND used_at IS NULL", (now, row["id"]))
        if cur.rowcount != 1:
            return "used"
    return None


def cancel_for_user(conn, user_id, now=None):
    """Cancel every open ticket of the user; commits. Returns how many."""
    now = now or clock()
    with conn.cursor() as cur:
        cur.execute("UPDATE squad_previews SET cancelled_at = %s "
                    "WHERE user_id = %s AND used_at IS NULL AND cancelled_at IS NULL", (now, int(user_id)))
        n = cur.rowcount
    conn.commit()
    return n


def cancel_for_default_user():
    """/reset's hook: cancel the default user's open tickets. A database failure is printed, never raised (a
    conversation reset must not depend on the ticket table); returns the count, or None on failure."""
    try:
        conn = db_write.connect()
        try:
            ensure_schema(conn)
            return cancel_for_user(conn, config_roles.DEFAULT_USER_ID())
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 -- reported, never fatal to /reset
        print(f"  [preview tickets not cancelled: {type(e).__name__}: {str(e)[:200]}]")
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--print-ddl"]:
        sys.stdout.write(DDL)
        return 0
    if argv == ["--init"]:
        conn = db_write.connect()
        try:
            ensure_schema(conn)
        finally:
            conn.close()
        print("squad_previews schema ensured")
        return 0
    print("usage: python squad_previews.py --print-ddl | --init", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
