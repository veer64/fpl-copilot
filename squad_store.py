# squad_store.py -- the user's squad as VERSIONED ROWS in Postgres
# (master plan section 1.4: "squad state as versioned rows, not a global";
# section 5.4: get_my_squad / set_my_squad read and write it).
#
# WHY THIS EXISTS
# Every solve the app has ever served was a free pick: the best fifteen from
# 100.0 as if from scratch. Nothing recorded what squad the user actually
# holds, so the six-week transfer MIP (squad/transfer_mip.py -- built,
# parity-proven, never run live), hit accounting, chip advice against a real
# squad, and lock/ban through a tool all had nothing to read. This table is
# that record. The squad is HYPOTHETICAL (not a real FPL entry) by decision
# taken 2026-09-12; it is seeded from the GW3 production solve (run_id 4)
# priced at GW4 and then carried forward by transfers.
#
# THE TABLE -- squad_versions -- IS APPEND-ONLY, BY CONSTRUCTION
#   * a change writes a NEW row and flips the previous row's is_active to
#     false; nothing else about an existing row ever changes;
#   * a trigger refuses DELETE and refuses any UPDATE that touches a column
#     other than is_active, or that turns is_active back ON. "Undo" is a new
#     row that copies an earlier squad_json (and says so in `note`) -- the
#     history stays linear and every state the user ever held is a row;
#   * a partial unique index allows at most ONE active row per user, so a
#     read is unambiguous or it raises -- never a guess between two candidates.
# The plan calls this the anti-rewrite insurance; it also gives undo and an
# audit trail for free. user_id exists from day one (always 1 for now);
# season is a column because gw alone is ambiguous across seasons.
#
# squad_json (JSONB) -- the document a row holds (SCHEMA_VERSION 1). Prices
# are in TENTHS of a million throughout (55 = 5.5m), the same unit as
# players_live.price_tenths and squad/squad_state.py. purchase_price is what
# was PAID, never the current price: FPL's sell rule (purchase + half the rise
# rounded down; falls in full) lives in squad_state.sell_price and is the only
# implementation -- this module converts documents to SquadState and back and
# never does money arithmetic itself.
#
#   {
#     "schema": 1,
#     "season": "2026-27",
#     "players": [                              -- exactly 15; 2 GK / 5 DEF / 5 MID / 3 FWD
#       {"element": 411, "name": "Erling Haaland", "position": "FWD",
#        "team": "Man City", "purchase_price": 155,
#        "role": "CAPTAIN",                     -- CAPTAIN | VICE | start | bench
#        "bench_order": null},                  -- 1..4 for bench rows, null otherwise
#       ...
#     ],
#     "bank": 4,                                -- tenths
#     "free_transfers": 1,
#     "total_points": 0,
#     "provenance": {...}                       -- free-form: where this version came from
#   }
#
# validate_document() is the ONE legality check (squad size, 2/5/5/3, club
# cap, roles, bench order, XI formation, non-negative bank) and every write
# path -- the seed and set_my_squad -- goes through it. An illegal document
# raises with every problem listed; nothing is coerced or silently dropped.
#
# The DDL below is the schema of record. It is applied to the server database
# by piping exactly this string through psql (`python squad_store.py
# --print-ddl`) or by ensure_schema(conn); the laptop has no Postgres, so only
# the pure-Python helpers are exercised locally (Tests/test_squad_store.py).

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

import db_write

_SQUAD_DIR = str(Path(__file__).resolve().parent / "squad")
if _SQUAD_DIR not in sys.path:
    sys.path.insert(0, _SQUAD_DIR)

from optimize import FORMATION, MAX_PER_CLUB, POSITION_LIMITS, SQUAD_SIZE, XI_SIZE  # noqa: E402
from squad_state import MAX_FREE_TRANSFERS, SquadState  # noqa: E402

SCHEMA_VERSION = 1
ROLES = ("CAPTAIN", "VICE", "start", "bench")
BENCH_SIZE = SQUAD_SIZE - XI_SIZE
PLAYER_COLS = ["element", "name", "position", "team", "purchase_price", "role", "bench_order"]

DDL = """
CREATE TABLE IF NOT EXISTS squad_versions (
    version_id  SERIAL PRIMARY KEY,
    user_id     INT         NOT NULL DEFAULT 1,
    season      TEXT        NOT NULL,
    gw          INT         NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    squad_json  JSONB       NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    supersedes  INT         REFERENCES squad_versions(version_id),
    note        TEXT
);

-- at most one active squad per user: a read is unambiguous or it raises
CREATE UNIQUE INDEX IF NOT EXISTS ux_squad_versions_one_active
    ON squad_versions (user_id) WHERE is_active;

-- append-only, enforced: no DELETE; the only UPDATE allowed is is_active
-- true -> false on the row being superseded. Undo = a new row.
CREATE OR REPLACE FUNCTION squad_versions_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'squad_versions is append-only: DELETE refused'
            USING DETAIL = 'version_id ' || OLD.version_id;
    END IF;
    IF NEW.version_id IS DISTINCT FROM OLD.version_id
       OR NEW.user_id    IS DISTINCT FROM OLD.user_id
       OR NEW.season     IS DISTINCT FROM OLD.season
       OR NEW.gw         IS DISTINCT FROM OLD.gw
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.squad_json IS DISTINCT FROM OLD.squad_json
       OR NEW.supersedes IS DISTINCT FROM OLD.supersedes
       OR NEW.note       IS DISTINCT FROM OLD.note THEN
        RAISE EXCEPTION 'squad_versions is append-only: only is_active may change'
            USING DETAIL = 'version_id ' || OLD.version_id;
    END IF;
    IF NOT OLD.is_active AND NEW.is_active THEN
        RAISE EXCEPTION 'squad_versions: a superseded version cannot be re-activated; write a new row'
            USING DETAIL = 'version_id ' || OLD.version_id;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_squad_versions_append_only ON squad_versions;
CREATE TRIGGER trg_squad_versions_append_only
    BEFORE UPDATE OR DELETE ON squad_versions
    FOR EACH ROW EXECUTE FUNCTION squad_versions_append_only();
"""


def ensure_schema(conn):
    """Create squad_versions, its one-active index and its append-only trigger
    if they do not exist. Idempotent. Call with NO query parameters (the DDL
    contains no psycopg2 placeholders and must not be interpolated)."""
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


# ------------------------------------------------------------- the document
def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def validate_document(doc):
    """Raise ValueError listing EVERY problem if `doc` is not a legal squad
    document; return None if it is. This is the one legality check: the seed
    and set_my_squad both go through it, so an illegal squad cannot reach the
    table by any path.

    Checks: schema version; exactly SQUAD_SIZE players with unique elements;
    position counts exactly POSITION_LIMITS (2/5/5/3); at most MAX_PER_CLUB
    per team; purchase_price a positive int; roles exactly one CAPTAIN, one
    VICE, BENCH_SIZE bench rows carrying bench_order 1..BENCH_SIZE, everyone
    else 'start' with bench_order null; the XI (everyone not on the bench)
    within FORMATION; bank a non-negative int; free_transfers an int in
    0..MAX_FREE_TRANSFERS; total_points a non-negative int; season a string.
    """
    problems = []
    if not isinstance(doc, dict):
        raise ValueError("squad document must be a dict")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema must be {SCHEMA_VERSION}, got {doc.get('schema')!r}")
    if not isinstance(doc.get("season"), str) or not doc.get("season"):
        problems.append("season must be a non-empty string")
    for key in ("bank", "total_points"):
        v = doc.get(key)
        if not _is_int(v) or v < 0:
            problems.append(f"{key} must be a non-negative int, got {v!r}")
    ft = doc.get("free_transfers")
    if not _is_int(ft) or not (0 <= ft <= MAX_FREE_TRANSFERS):
        problems.append(f"free_transfers must be an int in 0..{MAX_FREE_TRANSFERS}, got {ft!r}")

    players = doc.get("players")
    if not isinstance(players, list):
        problems.append("players must be a list")
        raise ValueError("illegal squad document: " + "; ".join(problems))
    if len(players) != SQUAD_SIZE:
        problems.append(f"squad has {len(players)} players, must be {SQUAD_SIZE}")

    elements, positions, teams, roles = [], Counter(), Counter(), Counter()
    bench_orders = []
    xi_positions = Counter()
    for i, p in enumerate(players):
        if not isinstance(p, dict):
            problems.append(f"players[{i}] is not an object")
            continue
        e = p.get("element")
        if not _is_int(e) or e <= 0:
            problems.append(f"players[{i}].element must be a positive int, got {e!r}")
        else:
            elements.append(e)
        pos = p.get("position")
        if pos not in POSITION_LIMITS:
            problems.append(f"players[{i}] ({e}) position {pos!r} not in {sorted(POSITION_LIMITS)}")
        else:
            positions[pos] += 1
        for key in ("name", "team"):
            if not isinstance(p.get(key), str) or not p.get(key):
                problems.append(f"players[{i}] ({e}) {key} must be a non-empty string")
        teams[p.get("team")] += 1
        pp = p.get("purchase_price")
        if not _is_int(pp) or pp <= 0:
            problems.append(f"players[{i}] ({e}) purchase_price must be a positive int in tenths, got {pp!r}")
        role = p.get("role")
        if role not in ROLES:
            problems.append(f"players[{i}] ({e}) role {role!r} not in {ROLES}")
            continue
        roles[role] += 1
        bo = p.get("bench_order")
        if role == "bench":
            if not _is_int(bo) or not (1 <= bo <= BENCH_SIZE):
                problems.append(f"players[{i}] ({e}) is bench but bench_order is {bo!r}")
            else:
                bench_orders.append(bo)
        else:
            if bo is not None:
                problems.append(f"players[{i}] ({e}) is {role} but carries bench_order {bo!r}")
            if pos in POSITION_LIMITS:
                xi_positions[pos] += 1

    dupes = [e for e, n in Counter(elements).items() if n > 1]
    if dupes:
        problems.append(f"duplicate elements: {sorted(dupes)}")
    for pos, want in POSITION_LIMITS.items():
        if positions[pos] != want:
            problems.append(f"{pos}: {positions[pos]} in squad, must be exactly {want}")
    for team, n in teams.items():
        if n > MAX_PER_CLUB:
            problems.append(f"{team}: {n} players, max {MAX_PER_CLUB} per club")
    if roles["CAPTAIN"] != 1:
        problems.append(f"{roles['CAPTAIN']} captains, must be exactly 1")
    if roles["VICE"] != 1:
        problems.append(f"{roles['VICE']} vice-captains, must be exactly 1")
    if roles["bench"] != BENCH_SIZE:
        problems.append(f"{roles['bench']} bench players, must be exactly {BENCH_SIZE}")
    elif sorted(bench_orders) != list(range(1, BENCH_SIZE + 1)):
        problems.append(f"bench_order must be exactly 1..{BENCH_SIZE}, got {sorted(bench_orders)}")
    n_xi = sum(roles[r] for r in ("CAPTAIN", "VICE", "start"))
    if n_xi != XI_SIZE:
        problems.append(f"{n_xi} in the XI, must be {XI_SIZE}")
    for pos, (lo, hi) in FORMATION.items():
        if not (lo <= xi_positions[pos] <= hi):
            problems.append(f"XI has {xi_positions[pos]} {pos}, formation allows {lo}..{hi}")
    if problems:
        raise ValueError("illegal squad document: " + "; ".join(problems))


def to_state(doc):
    """A validated document as a squad_state.SquadState -- the object the
    simulator, the transfer MIP and the sell-price rule all consume. The
    frame carries PLAYER_COLS so roles survive a round trip."""
    validate_document(doc)
    frame = pd.DataFrame(doc["players"])[PLAYER_COLS]
    frame["bench_order"] = frame["bench_order"].astype("object").where(frame["bench_order"].notna(), None)
    return SquadState(frame, bank=doc["bank"], free_transfers=doc["free_transfers"],
                      total_points=doc["total_points"])


def document(players, bank, free_transfers, total_points, season, provenance):
    """Build and validate a document from a players frame (or list of dicts)
    with PLAYER_COLS, plus the three scalars. numpy scalars are converted to
    plain Python so the result is JSON-serialisable as-is."""
    if isinstance(players, pd.DataFrame):
        rows = players[PLAYER_COLS].to_dict("records")
    else:
        rows = [dict(p) for p in players]

    def _py(v):
        if v is None:
            return None
        if isinstance(v, float) and v != v:            # NaN -> null (bench_order)
            return None
        if hasattr(v, "item"):                          # numpy scalar
            return v.item()
        return v

    out_players = []
    for r in rows:
        rec = {c: _py(r.get(c)) for c in PLAYER_COLS}
        for c in ("element", "purchase_price"):
            if rec[c] is not None and isinstance(rec[c], float) and rec[c].is_integer():
                rec[c] = int(rec[c])
        if rec["bench_order"] is not None and isinstance(rec["bench_order"], float):
            rec["bench_order"] = int(rec["bench_order"])
        out_players.append(rec)
    doc = {
        "schema": SCHEMA_VERSION,
        "season": season,
        "players": out_players,
        "bank": _py(bank),
        "free_transfers": _py(free_transfers),
        "total_points": _py(total_points),
        "provenance": provenance,
    }
    validate_document(doc)
    return doc


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
        print("squad_versions schema ensured")
        return 0
    print("usage: python squad_store.py --print-ddl | --init", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
