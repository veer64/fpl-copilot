"""Draft teams (Prompt W11, 2026-11-12): "Build a team" for people without an FPL team -- one draft per account, built from
the best picks, changed in chat for free within £100.0m and FPL's squad rules, never entered in FPL by us.

THE PLAN OF RECORD: eval/reports/w11_checkpoint1.md, approved by the owner on 12 Nov with the six defaults and three
additions (draft chips under the latest answer; predicted points always from the LATEST predictions; "Newer predictions:
rebuild?" when the draft's run is older than the latest).

BEST PICKS (O1) -- exactly what the agent answers "best team" with: best_squad_from_scratch -> model_tools.get_best_squad(),
the stored production solve of the latest run (squad/optimize.optimize_squad at its defaults: one gameweek, bench weight 0.2,
the solver's captain and vice, gapRel 0). When the latest run is not for the next deadline's gameweek, get_picks(gw) -- the
same tool for that gameweek, computed by the same solver. The fifteen are priced at CURRENT prices (current_prices); when
they no longer fit £100.0m the same optimiser is re-run on the same frame with current prices (step "re-solved"). Same
predictions + same prices -> the same draft. At most BUILD_CONCURRENCY builds compute at once (a process semaphore; the routes
are sync, so FastAPI runs them off the event loop).

CURRENT PRICES (O8) -- the price the team card shows: FPL's now_cost from the cached bootstrap (fpl_import, 10 min), else
players_live. One source for the build, the card, Home and every change check. Prices are never stored: value and money left
are always computed now.

THE TABLE -- user_drafts (DDL; ensure_schema, idempotent): one row per account (user_id PRIMARY KEY); draft_key (its own
sequence from 800,000,001: a number no user, team or squad key can have) is chat_threads.owner_key of the draft's chats;
version_id (its own sequence) is NEW on every write -- build, change, rebuild -- and every write is compare-and-set on the old
one, so a preview made against one version is never applied to another (squad_previews.base_version_id). No history rows: the
table holds exactly the current fifteen ("we keep its 15 players until you delete it or your account"). Writes take the user's
advisory lock (fpl_teams.LOCK_SPACE -- the lock every team change and every delete takes). Draft code never writes
squad_versions, squad_scores or user_fpl_teams, and a draft chat never activates or deactivates a team.

DELETION: deletion.delete_draft (the draft, its chats, their tickets) and deletion.delete_account (every guest exit included:
End guest, leave, idle, the reaper, the switch-off -- O7) remove the row. Off mode: every route is 404 and nothing here is read.
"""
import hashlib
import json
import os
import threading
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

import db_write

BUDGET = 1000                                   # tenths: £100.0m
FIRST_KEY = 800_000_001
BUILD_CONCURRENCY = 2                           # O9: at most two optimiser runs at once
BUILD_WAIT_S = 15                               # a third waits this long, then Busy (503)
BUILDS_PER_HOUR = 10                            # O9: build + rebuild, per user (users.draft_builds_limited)
OPENING_TEXT = ("Here's your starting 15, built from our predictions. Does it sound good to you? Suggest any changes "
                "you'd like, or ask me why I picked a player.")      # O2, fixed text, $0
POSITION_LIMITS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATION = {"GK": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
MAX_PER_CLUB = 3
SQUAD_SIZE, BENCH_SIZE = 15, 4
POS_WORDS = {"GK": "goalkeepers", "DEF": "defenders", "MID": "midfielders", "FWD": "forwards"}
POS_ONE = {"GK": "goalkeeper", "DEF": "defender", "MID": "midfielder", "FWD": "forward"}
RULES_WORDS = "2 GK, 5 DEF, 5 MID, 3 FWD; at most 3 players from one club; a legal XI (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD)"

DDL = f"""
CREATE SEQUENCE IF NOT EXISTS user_drafts_key_seq START WITH {FIRST_KEY} MINVALUE {FIRST_KEY};
CREATE SEQUENCE IF NOT EXISTS user_drafts_version_seq START WITH {FIRST_KEY} MINVALUE {FIRST_KEY};
CREATE TABLE IF NOT EXISTS user_drafts (
    user_id     INT         PRIMARY KEY,
    draft_key   INT         NOT NULL UNIQUE DEFAULT nextval('user_drafts_key_seq'),
    version_id  INT         NOT NULL UNIQUE DEFAULT nextval('user_drafts_version_seq'),
    season      TEXT        NOT NULL,
    gw          INT         NOT NULL,
    squad_json  JSONB       NOT NULL,
    built_from  JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    built_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_changes   INT         NOT NULL DEFAULT 0
);
ALTER SEQUENCE user_drafts_key_seq OWNED BY user_drafts.draft_key;
ALTER SEQUENCE user_drafts_version_seq OWNED BY user_drafts.version_id;
"""

_SCHEMA_READY = set()
_BUILD_SEM = threading.BoundedSemaphore(BUILD_CONCURRENCY)


class NoDraft(Exception):
    """The user has no draft."""


class BuildFailed(Exception):
    """The best picks could not be built (nothing was saved)."""


class Busy(Exception):
    """BUILD_CONCURRENCY builds are already running and none finished within BUILD_WAIT_S."""


class Changed(Exception):
    """The draft's version moved between the read and the write (compare-and-set refused)."""


class Refused(ValueError):
    """A requested draft is illegal or unaffordable: `kind` names the rule, `details` the numbers."""

    def __init__(self, kind, message, **details):
        super().__init__(message)
        self.kind, self.details = kind, details


def clock():
    return datetime.now(timezone.utc)


def _db_key():
    return tuple(os.getenv(k, "") for k in ("DB_HOST", "DB_PORT", "DB_NAME"))


def ensure_schema(conn=None):
    """user_drafts + its sequences; chat_threads (+ owner_key) and squad_previews, which draft chats use. Idempotent."""
    import threads
    own = conn is None
    conn = conn or db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
        threads.ensure_schema(conn)
        _SCHEMA_READY.add(_db_key())
    finally:
        if own:
            conn.close()


def _conn():
    conn = db_write.connect()
    if _db_key() not in _SCHEMA_READY:
        ensure_schema(conn)
    return conn


def _table_exists(cur):
    cur.execute("SELECT to_regclass('public.user_drafts') IS NOT NULL AS present")
    row = cur.fetchone()
    return bool(row["present"] if isinstance(row, dict) else row[0])


def read(user_id, conn=None):
    """The user's draft row (dict), or None. Never creates the table (a database without it has no drafts)."""
    own = conn is None
    conn = conn or db_write.connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if not _table_exists(cur):
                return None
            cur.execute("SELECT * FROM user_drafts WHERE user_id = %s", (int(user_id),))
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()
        else:
            conn.rollback()


def draft_threads(user_id, draft_key, conn=None):
    """The draft's chats, most recently active first: [(thread_id, created_at)] (the newest checkpoint, else creation)."""
    own = conn is None
    conn = conn or db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.checkpoints') IS NOT NULL")
            cps = cur.fetchone()[0]
            last = ("(SELECT max(c.checkpoint ->> 'ts') FROM checkpoints c WHERE c.thread_id = t.thread_id AND c.checkpoint_ns = '')"
                    if cps else "NULL::text")
            cur.execute(f"SELECT t.thread_id, t.created_at, {last} AS last_ts FROM chat_threads t "
                        "WHERE t.user_id = %s AND t.owner_key = %s", (int(user_id), int(draft_key)))
            rows = cur.fetchall()
        rows.sort(key=lambda r: (str(r[2] or ""), r[1].isoformat() if r[1] else ""), reverse=True)
        return [(r[0], r[1]) for r in rows]
    finally:
        if own:
            conn.close()
        else:
            conn.rollback()


def turn_draft(user_id, thread_id):
    """W11: {"user_id", "draft_key"} when `thread_id` is the user's draft chat, else None. Clerk mode only -- off mode never
    reads user_drafts (byte-identical). Read by agent_graph.run_thread_turn; the turn channel carries it to the tools."""
    import auth
    if auth.mode() != "clerk" or thread_id is None:
        return None
    conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            if not _table_exists(cur):
                return None
            cur.execute("SELECT d.draft_key FROM user_drafts d JOIN chat_threads t ON t.owner_key = d.draft_key "
                        "AND t.user_id = d.user_id WHERE d.user_id = %s AND t.thread_id = %s", (int(user_id), str(thread_id)))
            row = cur.fetchone()
        return {"user_id": int(user_id), "draft_key": int(row[0])} if row else None
    finally:
        conn.rollback()
        conn.close()


def draft_key_of(user_id, conn=None):
    row = read(user_id, conn=conn)
    return None if row is None else int(row["draft_key"])


# ---- current prices and player facts --------------------------------------------------------------------------------------

def context(allow_fetch=True):
    """team_card's Context (bootstrap + fixtures, cached) with the latest predictions loaded -- the card's own facts."""
    import team_card
    return team_card.gather(allow_fetch=allow_fetch).load_predictions()


def _live(elements):
    import team_card
    return team_card._live_rows(elements)


def current_prices(elements, ctx=None, allow_fetch=True):
    """{element: price in tenths} at current prices: FPL's now_cost (the cached bootstrap), else players_live. An element
    with neither is absent (the caller refuses it)."""
    ctx = ctx or context(allow_fetch=allow_fetch)
    ids = sorted({int(e) for e in elements})
    live = _live([e for e in ids if (ctx.elements.get(e) or {}).get("now_cost") is None])
    out = {}
    for e in ids:
        el = ctx.elements.get(e) or {}
        if el.get("now_cost") is not None:
            out[e] = int(el["now_cost"])
        elif (live.get(e) or {}).get("price_tenths") is not None:
            out[e] = int(live[e]["price_tenths"])
    return out


def player_meta(elements, ctx=None, allow_fetch=True):
    """{element: {"name", "position", "team"}} -- the bootstrap first (club NAME, as squad documents store it), else
    players_live. Unknown elements are absent."""
    import team_card
    ctx = ctx or context(allow_fetch=allow_fetch)
    ids = sorted({int(e) for e in elements})
    live = _live([e for e in ids if e not in ctx.elements])
    out = {}
    for e in ids:
        el = ctx.elements.get(e)
        if el:
            name = " ".join(x for x in ((el.get("first_name") or "").strip(), (el.get("second_name") or "").strip()) if x)
            club = (ctx.teams.get(int(el["team"])) or {}).get("name") if el.get("team") is not None else None
            out[e] = {"name": name or el.get("web_name") or f"Player {e}", "position": team_card.POSITIONS.get(el.get("element_type")),
                      "team": club, "web_name": el.get("web_name")}
        elif e in live:
            r = live[e]
            out[e] = {"name": r.get("name"), "position": r.get("position"), "team": r.get("team"), "web_name": r.get("name")}
    return out


# ---- the rules (pure) ----------------------------------------------------------------------------------------------------

def money(tenths):
    return None if tenths is None else round(int(tenths) / 10, 1)


def value_of(doc, prices):
    """(value in tenths, the elements without a price)."""
    ids = [int(p["element"]) for p in doc["players"]]
    missing = [e for e in ids if e not in prices]
    return sum(int(prices[e]) for e in ids if e in prices), missing


def _names(players):
    return ", ".join(p["name"] for p in players)


def check_squad(players, captain_id, vice_id, bench_order_ids):
    """Pure. Raise Refused naming the FIRST broken rule (position counts, the club cap, roles, the bench, the XI's formation).
    `players`: 15 dicts with element, name, position, team."""
    ids = [int(p["element"]) for p in players]
    if len(ids) != SQUAD_SIZE or len(set(ids)) != SQUAD_SIZE:
        raise Refused("squad_size", f"a squad is {SQUAD_SIZE} different players; this request has {len(set(ids))}",
                      rule="15 players")
    counts = {pos: sum(1 for p in players if p["position"] == pos) for pos in POSITION_LIMITS}
    bad = {pos: n for pos, n in counts.items() if n != POSITION_LIMITS[pos]}
    if bad:
        have = ", ".join(f"{counts[pos]} {POS_WORDS[pos]}" for pos in POSITION_LIMITS)
        raise Refused("position", f"FPL's squad must be 2 goalkeepers, 5 defenders, 5 midfielders and 3 forwards; this "
                                  f"one would have {have}. A player can only be swapped for one in the same position",
                      rule="2 GK, 5 DEF, 5 MID, 3 FWD", counts=counts)
    clubs = {}
    for p in players:
        clubs.setdefault(p["team"], []).append(p)
    over = {c: ps for c, ps in clubs.items() if len(ps) > MAX_PER_CLUB}
    if over:
        club, ps = sorted(over.items(), key=lambda kv: -len(kv[1]))[0]
        raise Refused("club_cap", f"FPL allows at most {MAX_PER_CLUB} players from one club; this squad would have "
                                  f"{len(ps)} from {club} ({_names(ps)})",
                      rule="at most 3 players from one club", club=club, n=len(ps))
    for label, x in (("captain", captain_id), ("vice-captain", vice_id)):
        if x is None or int(x) not in ids:
            raise Refused("roles", f"the {label} must be one of the fifteen", rule="captain and vice from the fifteen")
    if int(captain_id) == int(vice_id):
        raise Refused("roles", "the captain and the vice-captain must be different players", rule="two different players")
    bench = [int(x) for x in (bench_order_ids or [])]
    if len(bench) != BENCH_SIZE or len(set(bench)) != BENCH_SIZE or any(b not in ids for b in bench):
        raise Refused("bench", f"the bench is {BENCH_SIZE} different players from the fifteen, in order", rule="a bench of 4")
    if int(captain_id) in bench or int(vice_id) in bench:
        raise Refused("roles", "the captain and the vice-captain must start, not sit on the bench", rule="captain and vice start")
    xi = [p for p in players if int(p["element"]) not in bench]
    for pos, (lo, hi) in FORMATION.items():
        n = sum(1 for p in xi if p["position"] == pos)
        if not lo <= n <= hi:
            want = f"exactly {lo}" if lo == hi else f"{lo} to {hi}"
            raise Refused("formation", f"a starting XI needs {want} {POS_WORDS[pos]}; this one would start {n}",
                          rule="1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD")


def document(players, captain_id, vice_id, bench_order_ids, season):
    """The draft's squad document: 15 x {element, name, position, team, role, bench_order}, XI then bench. No prices."""
    bench = [int(x) for x in bench_order_ids]
    out = []
    for p in players:
        e = int(p["element"])
        role = "CAPTAIN" if e == int(captain_id) else "VICE" if e == int(vice_id) else "bench" if e in bench else "start"
        out.append({"element": e, "name": p["name"], "position": p["position"], "team": p["team"], "role": role,
                    "bench_order": bench.index(e) + 1 if e in bench else None})
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    out.sort(key=lambda r: (r["role"] == "bench", r["bench_order"] or 0, order.get(r["position"], 9)))
    return {"schema": 1, "season": season, "players": out}


def roles_of(doc):
    """(captain_id, vice_id, bench_order_ids) of a document."""
    c = next(int(p["element"]) for p in doc["players"] if p["role"] == "CAPTAIN")
    v = next(int(p["element"]) for p in doc["players"] if p["role"] == "VICE")
    bench = [int(p["element"]) for p in sorted((p for p in doc["players"] if p["role"] == "bench"), key=lambda p: p["bench_order"])]
    return c, v, bench


def validate_document(doc, prices=None):
    """Pure. A stored draft document is legal (and, with prices, within £100.0m); raises Refused."""
    c, v, bench = roles_of(doc)
    check_squad(doc["players"], c, v, bench)
    if prices is not None:
        value, missing = value_of(doc, prices)
        if missing:
            raise Refused("unpriced", f"no current price for player(s) {missing}", missing=missing)
        if value > BUDGET:
            raise Refused("over_budget", f"the fifteen cost £{money(value):.1f}m, over £100.0m", value=money(value))


def fingerprint(player_ids, captain_id, vice_id, bench_order_ids):
    """The preview ticket's change fingerprint for a DRAFT write: squad_previews' canonical form, prefixed "draft:" and
    hashed again -- a draft ticket can never match a real-squad write (and vice versa)."""
    import squad_previews
    fp = squad_previews.fingerprint(player_ids, captain_id, vice_id, bench_order_ids, None)
    return hashlib.sha256(("draft:" + fp).encode("utf-8")).hexdigest()


def plan_change(old_doc, player_ids, captain_id, vice_id, bench_order_ids, meta, prices):
    """Pure. The new document and the change summary, or Refused. Changes are free and unlimited: no free transfers, hits or
    bank. The only limits: the squad rules (check_squad) and £100.0m at current prices -- a fifteen that ends over £100.0m is
    refused when it costs MORE than the draft does now (owner default, checkpoint Q3: after price rises a captain change or a
    cheaper swap is still allowed)."""
    if not isinstance(player_ids, (list, tuple)) or not all(isinstance(x, int) and not isinstance(x, bool) for x in player_ids):
        raise Refused("squad_size", "player_ids must be a list of 15 player ids", rule="15 players")
    new_ids = [int(x) for x in player_ids]
    unknown = [e for e in new_ids if e not in meta]
    if unknown:
        raise Refused("unknown_player", f"player id(s) {', '.join(map(str, unknown))} match no player; look the player up "
                                        "by name first", ids=unknown)
    unpriced = sorted({e for e in new_ids + [int(p["element"]) for p in old_doc["players"]] if e not in prices})
    if unpriced:
        raise Refused("unpriced", f"no current price for player id(s) {unpriced}", ids=unpriced)
    old = {int(p["element"]): p for p in old_doc["players"]}
    players = [old[e] if e in old else {"element": e, "name": meta[e]["name"], "position": meta[e]["position"],
                                        "team": meta[e]["team"]} for e in new_ids]
    check_squad(players, captain_id, vice_id, bench_order_ids)
    before, _ = value_of(old_doc, prices)
    after = sum(int(prices[e]) for e in new_ids)
    if after > BUDGET and after > before:
        over = after - BUDGET
        raise Refused("over_budget", f"this fifteen would cost £{money(after):.1f}m at current prices: £{money(over):.1f}m "
                                     "over the £100.0m limit", value_after=money(after), over_by=money(over), budget=100.0,
                      value_before=money(before))
    outs = [e for e in old if e not in set(new_ids)]
    ins = [e for e in new_ids if e not in old]
    transfers = []
    for pos in POSITION_LIMITS:
        po = [e for e in outs if old[e]["position"] == pos]
        pi = [e for e in ins if meta[e]["position"] == pos]
        for o, i in zip(po, pi):
            transfers.append({"out": old[o]["name"], "out_id": o, "out_price": money(prices[o]),
                              "in": meta[i]["name"], "in_id": i, "in_price": money(prices[i])})
    new_doc = document(players, captain_id, vice_id, bench_order_ids, old_doc.get("season"))
    oc, ov, ob = roles_of(old_doc)
    change = {"transfers": transfers, "n_transfers": len(transfers),
              "captain_changed": int(captain_id) != oc, "vice_changed": int(vice_id) != ov,
              "bench_changed": [int(x) for x in bench_order_ids] != ob,
              "value_before": money(before), "value_after": money(after),
              "left_after": money(max(0, BUDGET - after)), "over_after": money(max(0, after - BUDGET)),
              "no_change": not transfers and int(captain_id) == oc and int(vice_id) == ov and [int(x) for x in bench_order_ids] == ob}
    return new_doc, change


# ---- best picks ----------------------------------------------------------------------------------------------------------

def _rows_to_players(rows):
    """get_best_squad / get_picks / optimise rows -> (players, captain, vice, bench order)."""
    players, bench, cap, vice = [], [], None, None
    for r in rows:
        e = int(r["player_id"])
        players.append({"element": e, "name": r["name"], "position": r["position"], "team": str(r.get("team"))})
        if r["role"] == "CAPTAIN":
            cap = e
        elif r["role"] == "VICE":
            vice = e
        elif r["role"] == "bench":
            bench.append(e)
    return players, cap, vice, bench


def _resolve(prices_fn):
    """The same optimiser (optimize_squad at its defaults) on the production frame for the next deadline's gameweek, every
    price set to the current one -- the re-solve when the stored fifteen no longer fit £100.0m."""
    import pulp
    import model_tools as mt
    import simulator as sim
    from optimize import optimize_squad
    gw = mt._current_gw()
    pool, cutoff, built = mt._load_pool(gw=gw)
    prices = prices_fn([int(e) for e in pool["element"]])
    pool = pool.copy()
    pool["value"] = [int(prices.get(int(e), int(v))) for e, v in zip(pool["element"], pool["value"])]
    prob, sol = optimize_squad(pool)
    if pulp.LpStatus[prob.status] != "Optimal":
        raise BuildFailed(f"the re-solve at current prices returned {pulp.LpStatus[prob.status]}")
    team = sim.solution_to_squad(pool, sol)
    rows = [{"player_id": int(r["element"]), "name": r["name"], "position": r["position"], "team": str(r["team"]),
             "role": r["role"]} for _, r in team.iterrows()]
    return rows, gw, built


def best_picks(prices_fn=None):
    """{"gw", "players", "captain", "vice", "bench", "built_from"} -- the build's fifteen (see the module docstring)."""
    import model_tools as mt
    prices_fn = prices_fn or (lambda ids: current_prices(ids))
    if not _BUILD_SEM.acquire(timeout=BUILD_WAIT_S):
        raise Busy("too many drafts are being built right now")
    try:
        run = mt._latest_run()
        if run is None:
            raise BuildFailed("no successful pipeline run yet")
        gw = mt._current_gw()
        got = mt.get_best_squad() if int(run.get("gw") or -1) == gw else mt.get_picks(gw=gw)
        if not isinstance(got, dict) or "error" in got:
            raise BuildFailed(f"the best picks are unavailable: {(got or {}).get('error')}")
        rows = list(got.get("xi") or []) + list(got.get("bench_in_order") or [])
        step = "stored" if got.get("stored", True) and not got.get("computed") else "computed"
        players, cap, vice, bench = _rows_to_players(rows)
        prices = prices_fn([p["element"] for p in players])
        value = sum(int(prices.get(p["element"], 10 ** 6)) for p in players)
        built = got.get("built") or got.get("frame_built")
        if value > BUDGET or any(p["element"] not in prices for p in players):
            rows, gw, built = _resolve(prices_fn)
            players, cap, vice, bench = _rows_to_players(rows)
            step = "re-solved"
        return {"gw": int(gw), "players": players, "captain": cap, "vice": vice, "bench": bench,
                "built_from": {"run_id": run.get("run_id"), "run_gw": run.get("gw"), "config": got.get("config"),
                               "predictions_built_at": str(built) if built is not None else str(run.get("finished_at")),
                               "step": step, "git": db_write.git_sha()}}
    except (Busy, BuildFailed):
        raise
    except Exception as e:                              # noqa: BLE001 -- any failure is "couldn't build", nothing saved
        raise BuildFailed(f"{type(e).__name__}: {str(e)[:300]}") from e
    finally:
        _BUILD_SEM.release()


def _season():
    import model_tools as mt
    try:
        return mt._season_label()
    except Exception:                                   # noqa: BLE001
        return os.getenv("FPL_SEASON", "2026-27")


def _picks_doc(picks, prices_fn=None):
    """The picks as a legal draft document, checked at current prices (BuildFailed otherwise -- never saved)."""
    prices_fn = prices_fn or (lambda ids: current_prices(ids))
    doc = document(picks["players"], picks["captain"], picks["vice"], picks["bench"], _season())
    try:
        validate_document(doc, prices_fn([p["element"] for p in doc["players"]]))
    except Refused as e:
        raise BuildFailed(f"the built fifteen broke a rule: {e}") from e
    return doc


# ---- writes --------------------------------------------------------------------------------------------------------------

def _lock(cur, user_id):
    import fpl_teams
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (fpl_teams.LOCK_SPACE, int(user_id)))


def _new_thread(cur, user_id, draft_key):
    import threads
    tid = threads.new_thread_id()
    cur.execute("INSERT INTO chat_threads (thread_id, user_id, is_default, owner_key) VALUES (%s, %s, FALSE, %s)",
                (tid, int(user_id), int(draft_key)))
    return tid


def write_opening(thread_id):
    """O2: the fixed opening message as the thread's FIRST stored message (assistant), $0 -- the agent sees it on every later
    turn (the API accepts a history that opens with the assistant's turn; checked 12 Nov on the agent model)."""
    import agent_graph
    g = agent_graph.thread_graph()
    g.update_state(agent_graph._thread_config(thread_id), {"messages": [{"role": "assistant", "content": OPENING_TEXT}]},
                   as_node="finalize")


def build(user_id, picks_fn=None, prices_fn=None, limited=None, opening=True):
    """POST /me/draft: the existing draft (existing True, nothing written, no build counted), else a new one from the best
    picks with its first chat and the opening message. limited(): the O9 window, asked only when a build will run (True ->
    the caller's 429). Returns {"row", "existing", "thread_id"}; raises BuildFailed / Busy (nothing saved) or Limited."""
    uid = int(user_id)
    row = read(uid)
    if row is not None:
        return {"row": row, "existing": True, "thread_id": None}
    if limited is not None and limited():
        raise Limited()
    picks = (picks_fn or best_picks)()
    doc = _picks_doc(picks, prices_fn)
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _lock(cur, uid)
            cur.execute("SELECT * FROM user_drafts WHERE user_id = %s", (uid,))
            again = cur.fetchone()
            if again is not None:                       # a concurrent build won: keep it, write nothing
                conn.rollback()
                return {"row": dict(again), "existing": True, "thread_id": None}
            cur.execute("INSERT INTO user_drafts (user_id, season, gw, squad_json, built_from) VALUES (%s, %s, %s, %s, %s) "
                        "RETURNING *", (uid, doc["season"], int(picks["gw"]), psycopg2.extras.Json(doc),
                                        psycopg2.extras.Json(picks["built_from"])))
            row = dict(cur.fetchone())
            tid = _new_thread(cur, uid, row["draft_key"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    if opening:
        try:
            write_opening(tid)
        except Exception as e:                          # noqa: BLE001 -- the draft stands; the chat opens without it
            print(f"  [draft of user {uid}: opening message not stored: {type(e).__name__}: {str(e)[:200]}]")
    return {"row": row, "existing": False, "thread_id": tid}


class Limited(Exception):
    """O9: more than BUILDS_PER_HOUR builds + rebuilds in the last hour."""


def rebuild(user_id, picks_fn=None, prices_fn=None, limited=None):
    """POST /me/draft/rebuild: a fresh fifteen from the best picks replaces the draft (a new version; its chats continue; the
    change count resets). NoDraft without one."""
    uid = int(user_id)
    row = read(uid)
    if row is None:
        raise NoDraft(str(uid))
    if limited is not None and limited():
        raise Limited()
    picks = (picks_fn or best_picks)()
    doc = _picks_doc(picks, prices_fn)
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _lock(cur, uid)
            cur.execute("UPDATE user_drafts SET squad_json = %s, built_from = %s, gw = %s, season = %s, "
                        "version_id = nextval('user_drafts_version_seq'), built_at = now(), updated_at = now(), n_changes = 0 "
                        "WHERE user_id = %s RETURNING *",
                        (psycopg2.extras.Json(doc), psycopg2.extras.Json(picks["built_from"]), int(picks["gw"]), doc["season"], uid))
            out = cur.fetchone()
            if out is None:
                conn.rollback()
                raise NoDraft(str(uid))
        conn.commit()
        return dict(out)
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_change(conn, user_id, base_version_id, new_doc, kind="change", built_from=None, gw=None):
    """Inside the caller's transaction (the preview ticket is consumed on the same connection): compare-and-set the draft from
    base_version_id to new_doc under a NEW version. kind "rebuild" (the fifteen and roles of today's best picks, previewed in
    chat) resets the change count and the build stamp. Changed when the version moved. Commits NOTHING."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        _lock(cur, user_id)
        if kind == "rebuild":
            cur.execute("UPDATE user_drafts SET squad_json = %s, built_from = COALESCE(%s, built_from), gw = COALESCE(%s, gw), "
                        "version_id = nextval('user_drafts_version_seq'), built_at = now(), updated_at = now(), n_changes = 0 "
                        "WHERE user_id = %s AND version_id = %s RETURNING *",
                        (psycopg2.extras.Json(new_doc), None if built_from is None else psycopg2.extras.Json(built_from), gw,
                         int(user_id), int(base_version_id)))
        else:
            cur.execute("UPDATE user_drafts SET squad_json = %s, version_id = nextval('user_drafts_version_seq'), "
                        "updated_at = now(), n_changes = n_changes + 1 WHERE user_id = %s AND version_id = %s RETURNING *",
                        (psycopg2.extras.Json(new_doc), int(user_id), int(base_version_id)))
        row = cur.fetchone()
    if row is None:
        raise Changed("the draft changed meanwhile; read it again and retry")
    return dict(row)


def new_chat(user_id):
    """POST /threads {"draft": true}: a new chat bound to the draft (no opening message: the empty state's draft chips).
    NoDraft without one."""
    uid = int(user_id)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT draft_key FROM user_drafts WHERE user_id = %s", (uid,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise NoDraft(str(uid))
            tid = _new_thread(cur, uid, row[0])
        conn.commit()
        return tid
    finally:
        conn.close()


# ---- the card (GET /me/draft; build and rebuild answer with it) -----------------------------------------------------------

def _xi_points(doc, pool):
    """Predicted points of the XI with the captain counted twice, from `pool` ({element: e_points}); None without it."""
    if pool is None:
        return None
    pts = 0.0
    for p in doc["players"]:
        if p["role"] == "bench":
            continue
        x = float(pool.get(int(p["element"]), 0.0))
        pts += 2 * x if p["role"] == "CAPTAIN" else x
    return round(pts, 1)


def newer_predictions(row):
    """True when the latest successful run is newer than the run the draft was built from (the owner's checkpoint-1 line:
    "Newer predictions: rebuild?"). Never automatic."""
    import model_tools as mt
    try:
        run = mt._latest_run()
    except Exception:                                   # noqa: BLE001
        return False
    built = (row.get("built_from") or {}).get("run_id")
    return bool(run and built is not None and int(run["run_id"]) != int(built))


def card(user_id, row=None, ctx=None, allow_fetch=True):
    """{"draft": None} or {"draft": {...}}: the team card's player objects (pitch, tokens, hover card unchanged) plus the Home
    summary. Predicted points always come from the LATEST predictions for the next deadline (team_card's own pool), never
    from the build (owner, checkpoint 1)."""
    import team_card
    uid = int(user_id)
    row = row if row is not None else read(uid)
    if row is None:
        return {"draft": None}
    doc = row["squad_json"]
    ctx = ctx or context(allow_fetch=allow_fetch)
    players = team_card.players_of(ctx, doc)
    prices = current_prices([p["element"] for p in doc["players"]], ctx=ctx)
    value, missing = value_of(doc, prices)
    cap = next((p for p in players if p["role"] == "C"), None)
    vice = next((p for p in players if p["role"] == "VC"), None)
    tids = draft_threads(uid, row["draft_key"])
    built = row.get("built_from") or {}
    return {"draft": {
        "version_id": int(row["version_id"]), "formation": team_card.formation(doc),
        "captain": None if cap is None else {"id": cap["id"], "short_name": cap["short_name"], "full_name": cap["full_name"]},
        "vice": None if vice is None else {"id": vice["id"], "short_name": vice["short_name"], "full_name": vice["full_name"]},
        "predicted_xi_points": _xi_points(doc, ctx.pool), "predictions_gw": ctx.next_gw if ctx.pool is not None else None,
        "predictions_updated_at": team_card._iso(ctx.built) if ctx.built is not None else None,
        "value": None if missing else money(value), "budget": 100.0,
        "left": None if missing else money(max(0, BUDGET - value)), "over": None if missing else money(max(0, value - BUDGET)),
        "built_at": team_card._iso(row["built_at"]), "built_from_predictions_at": built.get("predictions_built_at"),
        "built_from_run_id": built.get("run_id"), "newer_predictions": newer_predictions(row),
        "n_changes": int(row["n_changes"]), "updated_at": team_card._iso(row["updated_at"]),
        "thread_id": tids[0][0] if tids else None, "thread_ids": [t for t, _ in tids],
        "next_gw": ctx.next_gw, "next_deadline": ctx.deadline, "fpl_live": bool(ctx.boot_live and ctx.fixtures_live),
        "players": players}}


def as_json(x):
    return json.loads(json.dumps(x, default=str))
