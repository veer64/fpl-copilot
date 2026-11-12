"""Deleting what a user owns (Prompt W5, 2026-11-10): the account (DELETE /me), one imported team (DELETE /me/teams/{id})
and one chat (DELETE /threads/{id}). Clerk mode only; main.py checks the token and the read window, this module does the
rows.

THE RULE (overrides everything): every statement here is scoped to the signed-in user -- `user_id = u` in the WHERE, or an
id (thread, squad key, turn) that was first SELECTED under `user_id = u` -- never by an id from the request alone; each
request is ONE transaction under the user's advisory lock (fpl_teams.LOCK_SPACE, the lock every team change takes), the
thread turn locks of the threads it removes (a running turn finishes first; nothing of a deleted thread is written after).
Any failure rolls the whole transaction back: nothing is deleted.

THE DELETION MAP (as approved at the W5 checkpoint, corrections C1-C3):
  account  app_users, user_fpl_teams, squad_versions + squad_scores (every version under the teams' squad keys AND the
           user's own record), squad_previews, chat_threads + the LangGraph checkpoint rows (checkpoints, checkpoint_blobs,
           checkpoint_writes), chat_messages (+ feedback), the turns' check rows (fact_checks, citation_checks,
           numeric_checks -- by the turn ids chat_usage and chat_messages carry for the user), model_transfer_plans +
           model_transfers, cap_hits: DELETED. chat_usage: ANONYMISED (user_id NULL, turn_id 'deleted' -- the message link;
           model, tokens and usd kept, so every spend total is unchanged). Clerk: the user deleted INSIDE the open
           transaction (200 or 404 = gone; else rollback, ClerkDeleteFailed). A commit that fails after Clerk said deleted is
           printed loudly and raised as CommitFailedAfterClerk (the user can no longer sign in; our rows remain).
  team     the team row, its squad versions + scores ONLY under that team's squad key (C1: never the user's own record),
           the user's preview tickets issued against those versions, the user's transfer plans solved from them, and its
           chats (as below). The active team removed -> no team active (General mode).
  draft    (Prompt W11, 2026-11-12) the user's user_drafts row, its chats (every thread whose owner_key is the draft's
           draft_key, as below) and their tickets -- the same treatment Delete team gives a team's chats. Real teams, their
           squads and their chats are untouched. Delete account removes the draft too (guests included: every guest exit is
           delete_account).
  chat     the chat_threads row, its checkpoint rows, its chat_messages (+ feedback), the check rows of its turns (the
           message ids; answers from before W4 have none and keep theirs until the account goes), its preview tickets.
           chat_usage has no thread column: nothing changes there (the daily limit is unchanged).
  kept     search_log, llm_calls, tavily_calls, embedding_calls, the news and model tables (not per user); Langfuse (per
           its plan); backups (outside a request's reach).

squad_versions is append-only by trigger; the deletes here run with SET LOCAL fpl.account_delete = 'on' (+ the transaction
id), the one exception the trigger allows (squad_store.DDL)."""
import db_write
import fpl_teams
import threads
import users

CHECK_TABLES = ("fact_checks", "citation_checks", "numeric_checks")
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")   # children first (no FKs, but keep the order)


class NotDeletable(Exception):
    """The owner or a reserved account: refused before any write."""


class CommitFailedAfterClerk(Exception):
    """Clerk deleted the sign-in account but our commit failed: the rows remain, the user cannot sign in again."""


def _exists(cur, table):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    return bool(cur.fetchone()[0])


def _commit(conn):
    conn.commit()


def _allow_squad_deletes(cur):
    """The trigger's switch, for this transaction only."""
    cur.execute("SET LOCAL fpl.account_delete = 'on'")
    cur.execute("SELECT set_config('fpl.account_delete_txn', txid_current()::text, true)")


def _ensure(conn):
    """The tables a delete reads must exist (the project's idempotent DDLs; each commits on its own before the transaction)."""
    import chat_messages
    threads.checkpointer()                               # the checkpoint tables (set up once per process)
    threads.ensure_schema(conn)                          # chat_threads (+ owner_key) and squad_previews
    chat_messages.ensure_schema(conn)
    if _exists_conn(conn, "user_fpl_teams") is False:
        fpl_teams.ensure_schema(conn)


def _exists_conn(conn, table):
    with conn.cursor() as cur:
        return _exists(cur, table)


def _delete_turn_checks(cur, turn_ids):
    n = 0
    if not turn_ids:
        return 0
    for t in CHECK_TABLES:
        if _exists(cur, t):
            cur.execute(f"DELETE FROM {t} WHERE turn_id = ANY(%s)", (list(turn_ids),))
            n += cur.rowcount
    return n


def _delete_thread_rows(cur, user_id, thread_ids):
    """The chats of `user_id` named by `thread_ids` (already selected under user_id = u): messages, check rows, checkpoint
    rows, tickets, the thread rows. Returns {chats, messages, check_rows, previews}; `chats` counts the threads that had a
    turn (what /threads lists -- an empty default thread goes too but is not a chat the user ever saw)."""
    out = {"chats": 0, "messages": 0, "check_rows": 0, "previews": 0}
    if not thread_ids:
        return out
    tids = list(thread_ids)
    cur.execute("SELECT count(DISTINCT thread_id) FROM checkpoints WHERE thread_id = ANY(%s)", (tids,))
    out["chats"] = int(cur.fetchone()[0])
    cur.execute("SELECT message_id FROM chat_messages WHERE user_id = %s AND thread_id = ANY(%s)", (int(user_id), tids))
    turns = [r[0] for r in cur.fetchall()]
    out["check_rows"] = _delete_turn_checks(cur, turns)
    cur.execute("DELETE FROM chat_messages WHERE user_id = %s AND thread_id = ANY(%s)", (int(user_id), tids))
    out["messages"] = cur.rowcount
    for t in CHECKPOINT_TABLES:
        cur.execute(f"DELETE FROM {t} WHERE thread_id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM squad_previews WHERE user_id = %s AND thread_id = ANY(%s)", (int(user_id), tids))
    out["previews"] = cur.rowcount
    cur.execute("DELETE FROM chat_threads WHERE user_id = %s AND thread_id = ANY(%s)", (int(user_id), tids))
    return out


def _delete_squads(cur, owners):
    """Every version and score under `owners` (squad keys selected under user_id = u, or the user's own id)."""
    if not owners:
        return 0, 0
    _allow_squad_deletes(cur)
    cur.execute("DELETE FROM squad_scores WHERE user_id = ANY(%s)", (list(owners),))
    scores = cur.rowcount
    cur.execute("DELETE FROM squad_versions WHERE user_id = ANY(%s)", (list(owners),))
    return cur.rowcount, scores


def _delete_plans(cur, user_id, version_ids=None):
    """The user's transfer plans (all of them, or those solved from `version_ids`), transfers first (FK)."""
    if not _exists(cur, "model_transfer_plans"):
        return 0
    if version_ids is None:
        cur.execute("SELECT proposal_id FROM model_transfer_plans WHERE user_id = %s", (int(user_id),))
    else:
        if not version_ids:
            return 0
        cur.execute("SELECT proposal_id FROM model_transfer_plans WHERE user_id = %s AND squad_version_id = ANY(%s)",
                    (int(user_id), list(version_ids)))
    pids = [r[0] for r in cur.fetchall()]
    if not pids:
        return 0
    cur.execute("DELETE FROM model_transfers WHERE proposal_id = ANY(%s)", (pids,))
    cur.execute("DELETE FROM model_transfer_plans WHERE user_id = %s AND proposal_id = ANY(%s)", (int(user_id), pids))
    return cur.rowcount


class _Locks:
    """The thread turn locks of the threads about to go, taken in order and released after the transaction."""

    def __init__(self, thread_ids):
        self.locks = [threads.turn_lock(t) for t in sorted(thread_ids)]

    def __enter__(self):
        for lk in self.locks:
            lk.acquire()
        return self

    def __exit__(self, *exc):
        for lk in reversed(self.locks):
            lk.release()


# ---- B4: one chat ------------------------------------------------------------------------------------------------------------

def delete_thread(user_id, thread_id):
    """The user's own thread (else threads.ThreadRefused -- an unknown id and another user's answer alike). Returns
    {thread_id, deleted, removed_messages, was_default}."""
    uid, tid = int(user_id), str(thread_id)
    conn = db_write.connect()
    try:
        _ensure(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT is_default FROM chat_threads WHERE thread_id = %s AND user_id = %s FOR UPDATE", (tid, uid))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise threads.ThreadRefused(tid)
            with _Locks([tid]):
                out = _delete_thread_rows(cur, uid, [tid])
                _commit(conn)
        return {"thread_id": tid, "deleted": True, "removed_messages": out["messages"], "was_default": bool(row[0])}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- B3: one imported team ---------------------------------------------------------------------------------------------------

def delete_team(user_id, fpl_team_id):
    """The user's own team (else fpl_teams.TeamNotFound): its row, its squad versions and scores (its squad key only --
    checkpoint C1), its chats, the user's tickets against its versions and plans solved from them. Returns {fpl_team_id,
    removed_chats, removed_squad_versions, removed_previews, removed_plans, active_team_id}."""
    uid, fid = int(user_id), int(fpl_team_id)
    conn = db_write.connect()
    try:
        _ensure(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (fpl_teams.LOCK_SPACE, uid))
            cur.execute("SELECT id, squad_key, is_active FROM user_fpl_teams WHERE user_id = %s AND fpl_team_id = %s FOR UPDATE",
                        (uid, fid))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise fpl_teams.TeamNotFound(str(fid))
            team_row_id, key, was_active = int(row[0]), int(row[1]), bool(row[2])
            cur.execute("SELECT thread_id FROM chat_threads WHERE user_id = %s AND owner_key = %s", (uid, key))
            tids = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT version_id FROM squad_versions WHERE user_id = %s", (key,))
            versions = [r[0] for r in cur.fetchall()]
            with _Locks(tids):
                chats = _delete_thread_rows(cur, uid, tids)
                previews = 0
                if versions:
                    cur.execute("DELETE FROM squad_previews WHERE user_id = %s AND base_version_id = ANY(%s)", (uid, versions))
                    previews = cur.rowcount
                plans = _delete_plans(cur, uid, versions)
                n_versions, _ = _delete_squads(cur, [key])
                cur.execute("DELETE FROM user_fpl_teams WHERE user_id = %s AND id = %s", (uid, team_row_id))
                assert cur.rowcount == 1
                cur.execute("SELECT fpl_team_id FROM user_fpl_teams WHERE user_id = %s AND is_active", (uid,))
                active = cur.fetchone()
                _commit(conn)
        return {"fpl_team_id": fid, "removed_chats": chats["chats"], "removed_squad_versions": n_versions,
                "removed_previews": chats["previews"] + previews, "removed_plans": plans,
                "active_team_id": None if (was_active or active is None) else int(active[0])}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- W11: the draft ---------------------------------------------------------------------------------------------------------

def delete_draft(user_id):
    """The user's draft (else drafts.NoDraft): its row, its chats (owner_key = its draft_key, selected under user_id = u) with
    their checkpoints, messages, check rows and tickets. One transaction under the user's lock; real teams untouched.
    Returns {deleted, removed_chats, removed_previews}."""
    import drafts
    uid = int(user_id)
    conn = db_write.connect()
    try:
        _ensure(conn)
        drafts.ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (fpl_teams.LOCK_SPACE, uid))
            cur.execute("SELECT draft_key, version_id FROM user_drafts WHERE user_id = %s FOR UPDATE", (uid,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise drafts.NoDraft(str(uid))
            key, version = int(row[0]), int(row[1])
            cur.execute("SELECT thread_id FROM chat_threads WHERE user_id = %s AND owner_key = %s", (uid, key))
            tids = [r[0] for r in cur.fetchall()]
            with _Locks(tids):
                chats = _delete_thread_rows(cur, uid, tids)
                cur.execute("DELETE FROM squad_previews WHERE user_id = %s AND base_version_id = %s", (uid, version))
                previews = chats["previews"] + cur.rowcount
                cur.execute("DELETE FROM user_drafts WHERE user_id = %s", (uid,))
                assert cur.rowcount == 1
                _commit(conn)
        return {"deleted": True, "removed_chats": chats["chats"], "removed_previews": previews}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- B2: the account --------------------------------------------------------------------------------------------------------

def delete_account(user, clerk_delete=None, guest=False, guest_reason=None):
    """Everything of `user` (an app_users row dict) per the module docstring, then the Clerk user, then the commit. Returns
    {deleted, user_id, removed {...}, cost_rows_anonymised, clerk: deleted | already_gone}. NotDeletable for the owner or a
    reserved id (nothing touched); users.ClerkDeleteFailed after a rollback; CommitFailedAfterClerk when the commit fails
    after Clerk succeeded (printed loudly first). Prompt W9: guest=True marks the anonymised cost rows 'deleted-guest'
    (Admin shows guests apart; today's rows keep counting against the guest budget) and closes the guest_starts row with
    guest_reason ('left', 'idle', 'switch_off', else 'ended')."""
    if not users.deletable(user):
        raise NotDeletable(str(user.get("user_id")))
    uid = int(user["user_id"])
    marker = "deleted-guest" if guest else "deleted"
    clerk_delete = clerk_delete or users.delete_clerk_user
    conn = db_write.connect()
    clerk_status = None
    try:
        _ensure(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (fpl_teams.LOCK_SPACE, uid))
            cur.execute("SELECT clerk_user_id FROM app_users WHERE user_id = %s FOR UPDATE", (uid,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise NotDeletable(str(uid))
            clerk_user_id = row[0]
            cur.execute("SELECT squad_key FROM user_fpl_teams WHERE user_id = %s", (uid,))
            keys = [int(r[0]) for r in cur.fetchall()]
            cur.execute("SELECT thread_id FROM chat_threads WHERE user_id = %s", (uid,))
            tids = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT turn_id FROM chat_usage WHERE user_id = %s", (uid,))
            turns = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT message_id FROM chat_messages WHERE user_id = %s", (uid,))
            turns |= {r[0] for r in cur.fetchall()}
            with _Locks(tids):
                removed = {"teams": 0, "chats": 0, "messages": 0, "squad_versions": 0, "scores": 0, "previews": 0, "plans": 0,
                           "check_rows": 0, "cap_hits": 0, "drafts": 0}
                removed["check_rows"] = _delete_turn_checks(cur, turns)
                chats = _delete_thread_rows(cur, uid, tids)
                removed.update(chats=chats["chats"], messages=chats["messages"])
                cur.execute("DELETE FROM squad_previews WHERE user_id = %s", (uid,))
                removed["previews"] = chats["previews"] + cur.rowcount
                removed["plans"] = _delete_plans(cur, uid)
                removed["squad_versions"], removed["scores"] = _delete_squads(cur, keys + [uid])
                cur.execute("DELETE FROM user_fpl_teams WHERE user_id = %s", (uid,))
                removed["teams"] = cur.rowcount
                if _exists(cur, "user_drafts"):          # Prompt W11: the draft (its chats went with the user's threads above)
                    cur.execute("DELETE FROM user_drafts WHERE user_id = %s", (uid,))
                    removed["drafts"] = cur.rowcount
                if _exists(cur, "cap_hits"):
                    cur.execute("DELETE FROM cap_hits WHERE user_id = %s", (uid,))
                    removed["cap_hits"] = cur.rowcount
                cur.execute("UPDATE chat_usage SET user_id = NULL, turn_id = %s WHERE user_id = %s", (marker, uid))
                anonymised = cur.rowcount
                if guest and _exists(cur, "guest_starts"):
                    cur.execute("UPDATE guest_starts SET ended_at = now(), end_reason = %s WHERE user_id = %s AND ended_at IS NULL",
                                (guest_reason or "ended", uid))
                cur.execute("DELETE FROM app_users WHERE user_id = %s", (uid,))
                assert cur.rowcount == 1
                clerk_status = clerk_delete(clerk_user_id) if clerk_user_id else "already_gone"
                try:
                    _commit(conn)
                except Exception as e:                   # noqa: BLE001 -- the loud case: Clerk said deleted, we did not commit
                    print(f"  [ACCOUNT DELETE: Clerk user {clerk_user_id} deleted ({clerk_status}) but the database commit "
                          f"FAILED for user {uid}: {type(e).__name__}: {str(e)[:200]} -- the rows remain; the user cannot "
                          f"sign in again]", flush=True)
                    raise CommitFailedAfterClerk(str(e)) from e
        return {"deleted": True, "user_id": uid, "removed": removed, "cost_rows_anonymised": anonymised, "clerk": clerk_status}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
