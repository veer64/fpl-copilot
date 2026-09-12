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

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2.extras

import db_write

_SQUAD_DIR = str(Path(__file__).resolve().parent / "squad")
if _SQUAD_DIR not in sys.path:
    sys.path.insert(0, _SQUAD_DIR)

from optimize import FORMATION, MAX_PER_CLUB, POSITION_LIMITS, SQUAD_SIZE, XI_SIZE  # noqa: E402
from scoring import HIT_COST  # noqa: E402  -- FPL's real charge per paid transfer (4)
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


# ------------------------------------------------------------------ reads
class SquadStateError(RuntimeError):
    """No usable squad state: no active version for the user, more than one,
    or a stored document that fails validate_document. Callers surface it --
    the tool returns it as an explicit error, the MIP path lets it raise --
    and NOTHING falls back to a free pick."""


ACTIVE_SQL = """SELECT version_id, user_id, season, gw, created_at, is_active,
                       supersedes, note, squad_json
                FROM squad_versions
                WHERE user_id = %s AND is_active
                ORDER BY version_id"""


def active_from_rows(rows, user_id):
    """The active version record from the rows ACTIVE_SQL returned. Pure, so
    the three failure modes are testable without a database. Returns a dict
    with the row's columns and squad_json parsed + validated."""
    if len(rows) == 0:
        raise SquadStateError(
            f"no active squad version for user {user_id}: squad_versions has no "
            "is_active row. Seed one (eval/seed_squad_gw4.py); nothing falls back "
            "to a free pick.")
    if len(rows) > 1:
        ids = [r["version_id"] for r in rows]
        raise SquadStateError(
            f"{len(rows)} active squad versions for user {user_id} (version_ids "
            f"{ids}); the one-active index should make this impossible -- refusing "
            "to guess between them.")
    rec = dict(rows[0])
    doc = rec["squad_json"]
    if isinstance(doc, (str, bytes)):
        doc = json.loads(doc)
    try:
        validate_document(doc)
    except ValueError as e:
        raise SquadStateError(
            f"active squad version {rec['version_id']} holds an illegal document: {e}"
        ) from e
    rec["squad_json"] = doc
    return rec


def read_active(user_id=1, conn=None):
    """The user's active squad version, or SquadStateError. A missing table
    raises psycopg2's UndefinedTable -- also loud, also not a fallback."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(ACTIVE_SQL, (user_id,))
            rows = cur.fetchall()
    finally:
        if own:
            conn.close()
    return active_from_rows(rows, user_id)


ROLES_MEANING = ("the roles recorded WITH this version (captain, vice, XI, bench order) -- a record "
                 "of what was set when it was written, NOT a recommendation for the current "
                 "gameweek; get_my_xi computes that from the current model run")


# ------------------------------------------------- free transfers (lazy)
def free_transfers_at(record, gw):
    """Free transfers available at gameweek `gw`, DERIVED, never stored.

    FPL grants one free transfer per gameweek and banks them up to
    MAX_FREE_TRANSFERS (squad_state.end_gameweek is the same rule). A version
    stores `free_transfers` = the count remaining AFTER its own transfers, as
    of its own gw (the deadline it was set for). So at a later gameweek G:

        ft(G) = min(MAX_FREE_TRANSFERS, stored + (G - version.gw))

    Decision 1 of 2026-09-12 (Logs/squad_state_log.md section 10): a lazy
    derivation cannot go stale because nothing has to run; the one thing it
    depends on is that version.gw means the deadline the version was set for,
    which write paths enforce (set_my_squad refuses any other gw). Chips are
    not modelled yet (a wildcard week would spend nothing).

    Raises ValueError for a gw earlier than the version's -- there is no
    "count at a gameweek before the squad existed" to return.
    """
    k = int(record["gw"])
    if not _is_int(gw) or gw < k:
        raise ValueError(f"free transfers are defined from the version's gw {k} onward, got gw {gw!r}")
    stored = int(record["squad_json"]["free_transfers"])
    return min(MAX_FREE_TRANSFERS, stored + (gw - k))


def _dt(x):
    """A tz-aware datetime from a psycopg2 datetime or a Postgres-style string."""
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    s = str(x).strip().replace(" ", "T")
    if re.search(r"[+-]\d\d$", s):
        s += ":00"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def roles_status(record, latest_run):
    """Can the roles recorded with `record` stand for the current gameweek?
    They cannot if a model run has landed SINCE they were recorded, or the
    latest run is for a later gameweek. This is the bug of 2026-09-12 GW4:
    the seed's roles (copied from the GW3 solve, written 05:24Z) were read
    next to run 5's GW4 predictions (11:01Z) and presented as advice.

    latest_run: {run_id, gw, finished_at} of the latest SUCCESS run, or None."""
    out = {"as_of_gw": record["gw"], "recorded_at": str(record["created_at"]),
           "meaning": ROLES_MEANING}
    if not latest_run:
        out["status"] = "UNKNOWN"
        out["warning"] = "no successful model run to compare these roles against"
        return out
    out["latest_run"] = {"run_id": latest_run["run_id"], "gw": latest_run["gw"],
                         "built_at": str(latest_run["finished_at"])}
    if latest_run["gw"] > record["gw"] or _dt(latest_run["finished_at"]) > _dt(record["created_at"]):
        out["status"] = "STALE"
        out["warning"] = (
            f"these roles were recorded at {record['created_at']} for GW{record['gw']}; "
            f"model run {latest_run['run_id']} for GW{latest_run['gw']} was built at "
            f"{latest_run['finished_at']}, AFTER that. They are a record of what was set, "
            f"not a recommendation for GW{latest_run['gw']} -- call get_my_xi for that.")
    else:
        out["status"] = "current"
        out["warning"] = None
    return out


def summary(record, prices, latest_run=None, current_gw=None, current_gw_error=None):
    """What get_my_squad returns: the version's identity, the fifteen with
    purchase price, current price and SELL price, the totals, the RECORDED
    roles labelled as such (roles_status), and free transfers both as
    recorded (as of the version's gw) and as DERIVED for `current_gw` (the
    next deadline's gameweek). Money is presented in millions (one decimal);
    the document inside stays in tenths.

    prices: {element: current price_tenths} from players_live. The sell price
    is squad_state.sell_price via SquadState -- the one implementation of
    FPL's rule -- and a player with no current price is valued at what was
    paid (SquadState's rule: assuming a rise would invent money); such
    players are listed in prices_missing_for so the gap is visible.

    current_gw None: the derived count is reported as None with
    `free_transfers_error` = current_gw_error (e.g. bootstrap unreachable)
    -- unavailable and said so, never guessed."""
    doc = record["squad_json"]
    state = to_state(doc)
    if current_gw is not None:
        ft_now, ft_err = free_transfers_at(record, current_gw), None
    else:
        ft_now, ft_err = None, (current_gw_error or "current gameweek unknown")

    def m(tenths):
        return None if tenths is None else round(tenths / 10, 1)

    order = {"CAPTAIN": 0, "VICE": 1, "start": 2, "bench": 3}
    players = []
    for p in doc["players"]:
        e = p["element"]
        players.append({
            "player_id": e, "name": p["name"], "position": p["position"],
            "team": p["team"], "recorded_role": p["role"], "recorded_bench_order": p["bench_order"],
            "purchase_price": m(p["purchase_price"]),
            "current_price": m(prices.get(e)),
            "sell_price": m(state.element_sell_price(e, prices)),
        })
    players.sort(key=lambda r: (order[r["recorded_role"]], r["recorded_bench_order"] or 0,
                                -r["purchase_price"]))
    sell_value = state.sell_value(prices)
    purchase_cost = sum(p["purchase_price"] for p in doc["players"])
    return {
        "version_id": record["version_id"], "user_id": record["user_id"],
        "season": record["season"], "gw": record["gw"],
        "created_at": str(record["created_at"]), "supersedes": record["supersedes"],
        "note": record["note"],
        "hypothetical": bool((doc.get("provenance") or {}).get("hypothetical", False)),
        "roles": roles_status(record, latest_run),
        "recorded_captain": next((r["name"] for r in players if r["recorded_role"] == "CAPTAIN"), None),
        "recorded_vice": next((r["name"] for r in players if r["recorded_role"] == "VICE"), None),
        "recorded_xi": [r for r in players if r["recorded_role"] != "bench"],
        "recorded_bench_in_order": [r for r in players if r["recorded_role"] == "bench"],
        "purchase_cost": m(purchase_cost),
        "bank": m(doc["bank"]),
        "sell_value": m(sell_value),
        "budget_if_all_sold": m(sell_value + doc["bank"]),
        "free_transfers_recorded": doc["free_transfers"],
        "free_transfers_recorded_as_of_gw": record["gw"],
        "free_transfers_now": ft_now,
        "free_transfers_now_as_of_gw": current_gw,
        "free_transfers_error": ft_err,
        "total_points": doc["total_points"],
        "prices_missing_for": [p["element"] for p in doc["players"] if p["element"] not in prices],
        "squad_json": doc,
    }


# ------------------------------------------------------- the live XI solve
def xi_over_fifteen(pool, state, prices):
    """Best legal XI, captain, vice and bench order over the fifteen the user
    OWNS, from one gameweek's pool (optimize's shape: element, name, position,
    team, value, e_points [, p_play_any, p_60plus]). The same single-gameweek
    MIP the pipeline runs (gapRel=0), restricted to the owned fifteen by
    locking them and giving it only their rows. Owned players with no row in
    the pool (blank gameweek, or absent from the frame) are injected with
    e_points 0 by simulator._adjusted_pool -- the production rule -- and
    returned in `missing` so the gap is visible, never silent.

    Returns (team, missing): team is the 15-row frame with role and
    bench_order in the SCORING convention (0 = bench GK, 1..3 outfield)."""
    import pulp
    import simulator as sim
    from optimize import optimize_squad

    mine = set(state.elements)
    missing = sorted(mine - set(pool["element"]))
    adjusted = sim._adjusted_pool(pool, state, prices)
    p15 = adjusted[adjusted["element"].isin(mine)].reset_index(drop=True)
    if len(p15) != SQUAD_SIZE:
        raise RuntimeError(f"expected {SQUAD_SIZE} owned rows in the pool, got {len(p15)}")
    prob, sol = optimize_squad(p15, locked_elements=sorted(mine),
                               budget=int(p15["value"].sum()))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        raise RuntimeError(f"XI solve over the owned fifteen returned {status}")
    team = sim.solution_to_squad(p15, sol)
    return team, missing


def doc_bench_order(scoring_bench_order):
    """Scoring convention (0 = bench GK, 1..3 outfield) -> document / model_picks
    convention (1 = bench GK, 2..4 outfield)."""
    if scoring_bench_order is None or scoring_bench_order != scoring_bench_order:
        return None
    return int(scoring_bench_order) + 1


def roles_from_team(team):
    """{element: (role, bench_order in the DOCUMENT convention)} from a solved
    team frame."""
    out = {}
    for r in team.itertuples(index=False):
        bo = getattr(r, "bench_order", None)
        try:
            bo = None if pd.isna(bo) else bo
        except (TypeError, ValueError):
            pass
        out[int(r.element)] = (r.role, doc_bench_order(bo) if r.role == "bench" else None)
    return out


def _xi_points(roles, points):
    """XI e_points + the captain's again: the objective the weekly decision is
    ranked on (simulator.predicted_score), computed from a role map."""
    total = 0.0
    for e, (role, _) in roles.items():
        if role != "bench":
            total += points.get(e, 0.0)
        if role == "CAPTAIN":
            total += points.get(e, 0.0)
    return total


def compare_roles(doc_players, team):
    """The RECORDED roles against the roles the XI solve chose, on the same
    e_points: every changed role, the two predicted XI scores and the gain.
    Positive gain = the recorded roles were leaving points on the table."""
    recorded = {p["element"]: (p["role"], p["bench_order"]) for p in doc_players}
    optimal = roles_from_team(team)
    points = {int(r.element): float(r.e_points) for r in team.itertuples(index=False)}
    names = {p["element"]: p["name"] for p in doc_players}
    changes = []
    for e in sorted(recorded, key=lambda e: -points.get(e, 0.0)):
        if recorded[e] != optimal.get(e):
            changes.append({"player_id": e, "name": names[e], "e_points": round(points.get(e, 0.0), 2),
                            "recorded": _role_label(*recorded[e]),
                            "optimal": _role_label(*optimal[e])})
    rec_pts = _xi_points(recorded, points)
    opt_pts = _xi_points(optimal, points)
    return {"differ": bool(changes), "changes": changes,
            "recorded_xi_points": round(rec_pts, 2), "optimal_xi_points": round(opt_pts, 2),
            "expected_gain_vs_recorded": round(opt_pts - rec_pts, 2)}


def _role_label(role, bench_order):
    return f"bench {bench_order}" if role == "bench" else role


# ----------------------------------------------------------------- writes
def plan_change(active, player_ids, captain_id, vice_id, bench_order_ids, gw, live,
                priced_from=None, created_by=None, next_deadline_gw=None):
    """Pure. From the ACTIVE version and the requested fifteen + roles, build
    the NEW document and a change summary -- or raise ValueError. Nothing is
    clamped: an unaffordable, mis-shaped or mis-roled request is refused with
    the reason, and the active version is untouched.

    gw is the deadline the new version is set for and MUST equal
    next_deadline_gw (the next FPL deadline's gameweek): earlier is a deadline
    already passed, later would attribute transfers to a gameweek whose free
    transfer has not been granted. Free transfers available for the move are
    DERIVED by free_transfers_at(active, gw) -- the stored count rolled
    forward one per gameweek, capped -- never the stored count itself (the
    latent bug of 2026-09-12: a GW5 move on the GW4 seed saw 1, not 2).

    The caller never supplies money. The change is the set difference between
    the active fifteen and `player_ids`; it is applied through
    squad_state.SquadState.make_transfers, which values every outgoing player
    by squad_state.sell_price (purchase + half the rise rounded down, falls in
    full), prices every incoming player at his CURRENT price, pools the money
    across the set the way FPL settles it, and refuses if the bank would go
    negative. Purchase prices of retained players are carried unchanged; the
    incoming players' purchase_price is what was paid now. Free transfers are
    consumed first; transfers beyond them are hits at HIT_COST points each,
    reported, not deducted from total_points (no process scores the
    hypothetical squad yet).

    live: {element: {"name","position","team","price_tenths"}} from players_live
    for EVERY element involved (old and new). A missing or unpriced element
    is refused. gw must not be earlier than the active version's.

    Two money assertions are made after the move and raise RuntimeError if
    they fail (which would be a bug, not a bad request):
      bank_after == bank_before + proceeds - purchases, exactly;
      wealth (sell value at current prices + bank) is unchanged by the move.
    """
    old_doc = active["squad_json"]
    if not _is_int(gw) or gw < active["gw"]:
        raise ValueError(f"gw must be an int >= the active version's gw {active['gw']}, got {gw!r}")
    if not _is_int(next_deadline_gw):
        raise ValueError("next_deadline_gw is required (the next FPL deadline's gameweek); "
                         "refusing to attribute transfers to a gameweek by guesswork")
    if gw != next_deadline_gw:
        if gw < next_deadline_gw:
            raise ValueError(f"GW{gw}'s deadline has passed; a squad can only be set for the "
                             f"next deadline, GW{next_deadline_gw}")
        raise ValueError(f"GW{gw} is beyond the next deadline (GW{next_deadline_gw}); a squad is "
                         "set one deadline at a time so free transfers stay attributable")
    if not isinstance(player_ids, (list, tuple)) or not all(_is_int(x) for x in player_ids):
        raise ValueError("player_ids must be a list of ints")
    if len(player_ids) != SQUAD_SIZE or len(set(player_ids)) != SQUAD_SIZE:
        raise ValueError(f"player_ids must be {SQUAD_SIZE} distinct ids, got {len(player_ids)} "
                         f"({len(set(player_ids))} distinct)")
    new_ids = set(player_ids)
    old_ids = {p["element"] for p in old_doc["players"]}
    involved = sorted(old_ids | new_ids)
    unpriced = [e for e in involved
                if e not in live or not _is_int(live[e].get("price_tenths"))]
    if unpriced:
        raise ValueError(f"no current players_live row/price for element(s) {unpriced}; "
                         "cannot value the move")
    for e in new_ids:
        if live[e].get("position") not in POSITION_LIMITS:
            raise ValueError(f"element {e} has position {live[e].get('position')!r} in players_live")

    # roles
    for label, x in (("captain_id", captain_id), ("vice_id", vice_id)):
        if not _is_int(x) or x not in new_ids:
            raise ValueError(f"{label} {x!r} is not one of the fifteen")
    if captain_id == vice_id:
        raise ValueError("captain_id and vice_id must differ")
    if (not isinstance(bench_order_ids, (list, tuple)) or len(bench_order_ids) != BENCH_SIZE
            or len(set(bench_order_ids)) != BENCH_SIZE
            or not all(_is_int(x) and x in new_ids for x in bench_order_ids)):
        raise ValueError(f"bench_order_ids must be {BENCH_SIZE} distinct ids from the fifteen, "
                         f"in bench order, got {bench_order_ids!r}")
    if captain_id in bench_order_ids or vice_id in bench_order_ids:
        raise ValueError("captain and vice-captain must start, not sit on the bench")

    # the move
    state = to_state(old_doc)
    ft_recorded = state.free_transfers
    state.free_transfers = free_transfers_at(active, gw)      # rolled forward, not stored
    prices = {e: int(live[e]["price_tenths"]) for e in involved}
    bank_before = state.bank
    wealth_before = state.sell_value(prices) + bank_before
    outs = sorted(old_ids - new_ids)
    ins = sorted(new_ids - old_ids)
    old_pos = {p["element"]: p["position"] for p in old_doc["players"]}
    by_pos_out = {pos: [e for e in outs if old_pos[e] == pos] for pos in POSITION_LIMITS}
    by_pos_in = {pos: [e for e in ins if live[e]["position"] == pos] for pos in POSITION_LIMITS}
    mismatch = {pos: (len(by_pos_out[pos]), len(by_pos_in[pos])) for pos in POSITION_LIMITS
                if len(by_pos_out[pos]) != len(by_pos_in[pos])}
    if mismatch:
        raise ValueError("the fifteen must stay 2 GK / 5 DEF / 5 MID / 3 FWD: transfers out/in "
                         f"by position do not match {mismatch}")
    pairs = []
    for pos in POSITION_LIMITS:
        pairs.extend(zip(by_pos_out[pos], by_pos_in[pos]))
    in_rows = {e: pd.Series({"element": e, "name": live[e]["name"], "position": live[e]["position"],
                             "team": live[e]["team"], "value": prices[e]}) for e in ins}
    sold_for = {o: state.element_sell_price(o, prices) for o in outs}
    state.make_transfers(pairs, in_rows, prices)         # raises if unaffordable etc.
    proceeds = sum(sold_for.values())
    purchases = sum(prices[i] for i in ins)
    if state.bank != bank_before + proceeds - purchases:
        raise RuntimeError(f"money conservation violated: bank {state.bank} != {bank_before} + "
                           f"{proceeds} - {purchases}")
    wealth_after = state.sell_value(prices) + state.bank
    if wealth_after != wealth_before:
        raise RuntimeError(f"money conservation violated: wealth {wealth_before} -> {wealth_after}")

    ft_before = state.free_transfers
    paid = state.spend_transfers(len(pairs))
    hits = paid

    # roles onto the new frame
    frame = state.squad.copy()
    role = {}
    for e in new_ids:
        role[e] = "start"
    for i, e in enumerate(bench_order_ids, start=1):
        role[e] = ("bench", i)
    frame["role"] = [("bench" if isinstance(role[e], tuple) else role[e]) for e in frame["element"]]
    frame["bench_order"] = [(role[e][1] if isinstance(role[e], tuple) else None) for e in frame["element"]]
    frame.loc[frame["element"] == captain_id, "role"] = "CAPTAIN"
    frame.loc[frame["element"] == vice_id, "role"] = "VICE"

    transfers = [{"out": o, "out_name": old_names(old_doc)[o], "sold_for": sold_for[o],
                  "in": i, "in_name": live[i]["name"], "bought_for": prices[i]}
                 for o, i in pairs]
    old_prov = old_doc.get("provenance") or {}
    provenance = {
        "kind": "set_my_squad",
        "hypothetical": bool(old_prov.get("hypothetical", False)),
        "from_version": active["version_id"],
        "transfers": transfers,
        "free_transfers_used": len(pairs) - paid,
        "hits": hits, "hit_cost_points": hits * HIT_COST,
        "priced_from": priced_from,
        "created_by": created_by,
    }
    new_doc = document(frame, state.bank, state.free_transfers, old_doc["total_points"],
                       old_doc["season"], provenance)
    change = {
        "from_version": active["version_id"], "gw": gw,
        "transfers": transfers, "n_transfers": len(pairs),
        "free_transfers_recorded": ft_recorded,
        "free_transfers_recorded_as_of_gw": active["gw"],
        "gameweeks_rolled_forward": gw - active["gw"],
        "free_transfers_before": ft_before, "free_transfers_used": len(pairs) - paid,
        "free_transfers_after": state.free_transfers,
        "hits": hits, "hit_cost_points": hits * HIT_COST,
        "bank_before": bank_before, "proceeds": proceeds, "purchases": purchases,
        "bank_after": state.bank,
        "wealth_before": wealth_before, "wealth_after": wealth_after,
    }
    return new_doc, change


def old_names(doc):
    return {p["element"]: p["name"] for p in doc["players"]}


def write_version(active, new_doc, gw, note, confirm, conn=None, user_id=1):
    """Supersede `active` with `new_doc` in ONE transaction: flip the old row's
    is_active (the only update the trigger permits), then insert the new row
    with supersedes = the old version_id. If the old row is no longer active
    (superseded meanwhile) nothing is written and SquadStateError is raised.

    confirm=False runs the whole thing and ROLLS BACK -- a preview that
    exercises the real write path (trigger included) without changing state;
    the returned row says committed=False and its version_id is provisional
    (sequence values are consumed either way, so ids may have gaps)."""
    validate_document(new_doc)
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """UPDATE squad_versions SET is_active = FALSE
                   WHERE version_id = %s AND user_id = %s AND is_active
                   RETURNING version_id""",
                (active["version_id"], user_id))
            flipped = cur.fetchall()
            if len(flipped) != 1:
                raise SquadStateError(
                    f"version {active['version_id']} is no longer the active squad for user "
                    f"{user_id} (superseded meanwhile); re-read with get_my_squad and retry")
            cur.execute(
                """INSERT INTO squad_versions
                       (user_id, season, gw, squad_json, is_active, supersedes, note)
                   VALUES (%s, %s, %s, %s, TRUE, %s, %s)
                   RETURNING version_id, user_id, season, gw, created_at, is_active,
                             supersedes, note""",
                (user_id, new_doc["season"], gw, psycopg2.extras.Json(new_doc),
                 active["version_id"], note))
            row = dict(cur.fetchone())
        if confirm:
            conn.commit()
        else:
            conn.rollback()
        row["squad_json"] = new_doc
        row["committed"] = bool(confirm)
        return row
    except Exception:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


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
