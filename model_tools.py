# model_tools.py -- the app's typed reads over the MODEL's outputs, replacing
# the naive predict_naive tables the agent served since Phase 1.
#
# Contract (master plan serving section): the agent reads predictions and
# picks through these tools -- it never touches parquet or the solver
# internals directly. Every answer is traceable: rows carry run_id,
# model_version (git_sha/config) and built_at, and recovered runs say so.
#
# CONFIGS: config_roles.PRODUCTION_CONFIG ('baseline' since 2026-09-11,
# Logs/baseline_adoption_log.md) is what every user-facing default reads.
# config_roles.SHADOW_CONFIG (None since the same date) is reachable only where
# a tool takes an explicit shadow argument, so the two cannot be confused; with
# no shadow configured, shadow reads return an explicit error, never production.
#
# The one non-DB tool is optimise(): it solves from the latest frame on the
# model volume (data/live/_tmp_frame_{PRODUCTION_CONFIG}.parquet, written by
# each run) through squad/optimize.py -- the same MIP the pipeline uses, gapRel=0.

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from config_roles import CONFIGS, PRODUCTION_CONFIG, SHADOW_CONFIG
import squad_store

load_dotenv()
REPO = Path(__file__).resolve().parent
PROD_FRAME = REPO / "data" / "live" / f"_tmp_frame_{PRODUCTION_CONFIG}.parquet"


def _conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fpl"), user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""))


def _q(sql, params=()):
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _latest_run(gw=None, any_status=False):
    sql = "SELECT * FROM model_runs"
    conds, params = [], []
    if not any_status:
        conds.append("status = 'SUCCESS'")
    if gw is not None:
        conds.append("gw = %s")
        params.append(gw)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY finished_at DESC LIMIT 1"
    rows = _q(sql, tuple(params))
    return rows[0] if rows else None


def _version(run, config):
    return f"{(run.get('git_sha') or 'unknown')}/{config}"


def _run_meta(run, config=PRODUCTION_CONFIG):
    return {"run_id": run["run_id"], "gw": run["gw"],
            "model_version": _version(run, config),
            "built_at": str(run["finished_at"]),
            "recovered_post_deadline": run["recovered"]}


# ---------------------------------------------------------------- reference
def resolve_player(name: str):
    rows = _q("""SELECT element AS player_id, name, position, team, price_tenths,
                        status FROM players_live
                 WHERE name ILIKE %s ORDER BY name LIMIT 6""", (f"%{name}%",))
    for r in rows:
        r["price"] = (r.pop("price_tenths") or 0) / 10
    return rows or {"error": f"no current player matches '{name}'"}


def list_players(team: str = None, position: str = None):
    sql = """SELECT element AS player_id, name, position, team, price_tenths, status
             FROM players_live WHERE 1=1"""
    params = []
    if team:
        sql += " AND team ILIKE %s"
        params.append(f"%{team}%")
    if position:
        sql += " AND position ILIKE %s"
        params.append(f"%{position[:3]}%")
    rows = _q(sql + " ORDER BY price_tenths DESC NULLS LAST LIMIT 25", tuple(params))
    for r in rows:
        r["price"] = (r.pop("price_tenths") or 0) / 10
    return rows


def get_player_card(player_id: int):
    p = _q("SELECT * FROM players_live WHERE element = %s", (player_id,))
    if not p:
        return {"error": f"no player with id {player_id}"}
    card = p[0]
    card["price"] = (card.pop("price_tenths") or 0) / 10
    card["player_id"] = card.pop("element")
    pred = get_prediction(player_id)
    if "error" not in pred:
        card["prediction"] = pred
    return card


# -------------------------------------------------------------- predictions
def get_prediction(player_id: int, gw: int = None):
    """The production model's view of one player: the target gw if given,
    else every gameweek in the latest run's six-week horizon."""
    run = _latest_run()
    if run is None:
        return {"error": "no successful pipeline run in the database yet"}
    sql = """SELECT gw, horizon_step, e_points, e_minutes, p_start, p_60plus,
                    e_goals, e_assists, p_cs, exp_bonus
             FROM model_predictions
             WHERE run_id = %s AND config = %s AND element = %s"""
    params = [run["run_id"], PRODUCTION_CONFIG, player_id]
    if gw is not None:
        sql += " AND gw = %s"
        params.append(gw)
    rows = _q(sql + " ORDER BY gw", tuple(params))
    if not rows:
        return {"error": f"no prediction rows for player {player_id} in run "
                         f"{run['run_id']} (not in the pool at that cutoff)"}
    out = _run_meta(run)
    out["player_id"] = player_id
    out["predictions"] = [{k: (float(v) if isinstance(v, float) else v)
                           for k, v in r.items()} for r in rows]
    out["horizon_e_points_sum"] = round(sum(r["e_points"] or 0 for r in rows), 2)
    return out


def compare_players(player_id_a: int, player_id_b: int):
    a, b = get_prediction(player_id_a), get_prediction(player_id_b)
    if "error" in a or "error" in b:
        return {"a": a, "b": b}
    names = {r["element"]: r["name"] for r in _q(
        "SELECT element, name FROM players_live WHERE element IN (%s, %s)",
        (player_id_a, player_id_b))}

    def brief(p):
        first = p["predictions"][0]
        return {"player_id": p["player_id"], "name": names.get(p["player_id"]),
                "next_gw_e_points": first["e_points"],
                "next_gw_p_start": first["p_start"],
                "horizon_e_points_sum": p["horizon_e_points_sum"]}
    return {"model_version": a["model_version"], "built_at": a["built_at"],
            "recovered_post_deadline": a["recovered_post_deadline"],
            "a": brief(a), "b": brief(b),
            "verdict": "a" if a["horizon_e_points_sum"] >= b["horizon_e_points_sum"] else "b"}


# -------------------------------------------------------------------- picks
def get_picks(gw: int = None, shadow: bool = False):
    """The solved squad of the latest successful run (optionally for a given
    gw): XI, captain, vice, bench in order. shadow=True returns the baseline
    config's squad and how it differs -- the season-long comparison."""
    run = _latest_run(gw=gw)
    if run is None:
        return {"error": f"no successful pipeline run{f' for GW{gw}' if gw else ''} "
                         "in the database yet"}
    if shadow and SHADOW_CONFIG is None:
        return {"error": "no shadow configuration is run (production = "
                         f"{PRODUCTION_CONFIG} since 2026-09-11; config_roles.py)"}
    config = SHADOW_CONFIG if shadow else PRODUCTION_CONFIG
    rows = _q("""SELECT element AS player_id, name, position, team, role,
                        bench_order, price_tenths, e_points
                 FROM model_picks WHERE run_id = %s AND config = %s
                 ORDER BY CASE role WHEN 'CAPTAIN' THEN 0 WHEN 'VICE' THEN 1
                          WHEN 'start' THEN 2 ELSE 3 END, bench_order NULLS FIRST,
                          e_points DESC""", (run["run_id"], config))
    for r in rows:
        r["price"] = (r.pop("price_tenths") or 0) / 10
        r["e_points"] = float(r["e_points"])
    out = _run_meta(run, config)
    out["config"] = config + (" (shadow)" if shadow else " (production)")
    out["captain"] = next((r["name"] for r in rows if r["role"] == "CAPTAIN"), None)
    out["vice"] = next((r["name"] for r in rows if r["role"] == "VICE"), None)
    out["xi"] = [r for r in rows if r["role"] != "bench"]
    out["bench_in_order"] = sorted((r for r in rows if r["role"] == "bench"),
                                   key=lambda r: r["bench_order"] or 9)
    out["squad_cost"] = round(sum(r["price"] for r in rows), 1)
    if shadow:
        prod = {r["player_id"] for r in _q(
            """SELECT element AS player_id FROM model_picks
               WHERE run_id = %s AND config = %s""", (run["run_id"], PRODUCTION_CONFIG))}
        here = {r["player_id"] for r in rows}
        out["differs_from_production_by"] = sorted(here ^ prod)
    return out


def get_best_squad(budget: float = None):
    """The optimal fifteen. At the full 100.0 budget this is the STORED
    production solve (a database read); a custom budget runs the real MIP
    against the latest frame (seconds, not instant)."""
    if budget is None or abs(budget - 100.0) < 1e-9:
        return get_picks()
    return optimise(budget=budget)


# -------------------------------------------------------------- my squad
def _current_gw():
    """The next FPL deadline's gameweek -- what "now" means for squad state:
    free transfers are derived to it and a version can only be set for it.
    Raises RuntimeError if the bootstrap is unreachable; never guessed."""
    nd = _next_deadline()
    if nd is None:
        raise RuntimeError("cannot determine the current gameweek: the FPL bootstrap is "
                           "unreachable (result cached 10 min); retry shortly")
    return int(nd[0])


def get_my_squad(user_id: int = 1):
    """The user's OWN squad -- the active row of squad_versions (master plan
    1.4 / 5.4), NOT the model's free-pick solve. The fifteen with role,
    purchase price, current price and sell price (squad_state's rule), bank,
    free transfers, points, and the version id.

    If there is no active version (or more than one, or the stored document
    is illegal) this returns {"error": ...} naming the condition -- the
    convention the other tools use so the model reports it -- and never a
    substitute squad. squad_store.read_active is the raising form for code
    paths (the transfer MIP) that must not proceed without state."""
    try:
        record = squad_store.read_active(user_id)
    except squad_store.SquadStateError as e:
        return {"error": str(e)}
    elements = [p["element"] for p in record["squad_json"]["players"]]
    prices = {r["element"]: r["price_tenths"] for r in _q(
        "SELECT element, price_tenths FROM players_live "
        "WHERE element = ANY(%s) AND price_tenths IS NOT NULL", (elements,))}
    try:
        current, current_err = _current_gw(), None
    except RuntimeError as e:
        current, current_err = None, str(e)
    return squad_store.summary(record, prices, latest_run=_latest_run(),
                               current_gw=current, current_gw_error=current_err)


def get_my_xi(user_id: int = 1):
    """THIS WEEK's best XI, captain, vice and bench order over the fifteen the
    user owns, solved from the current production frame on the model volume
    (the frame the latest deadline run wrote) -- the same single-gameweek MIP
    as optimise(), gapRel=0, restricted to the owned fifteen. Contrast with
    get_my_squad, whose roles are what was RECORDED with the version.

    Also compares against the recorded roles: which roles differ and how many
    expected points the recorded XI leaves on the table. Owned players absent
    from the frame are injected at e_points 0 (the production blank-week
    rule) and listed. Nothing is written: to adopt the XI, call set_my_squad
    with adopt_with and confirm=true."""
    try:
        record = squad_store.read_active(user_id)
    except squad_store.SquadStateError as e:
        return {"error": str(e)}
    try:
        target = _current_gw()
    except RuntimeError as e:
        return {"error": str(e)}
    try:
        pool, cutoff, built = _load_pool(gw=target)
    except FileNotFoundError as e:
        return {"error": str(e)}
    except ValueError as e:
        return {"error": f"the frame on the volume has no predictions for GW{target}: {e}"}
    doc = record["squad_json"]
    state = squad_store.to_state(doc)
    elements = [p["element"] for p in doc["players"]]
    prices = {r["element"]: r["price_tenths"] for r in _q(
        "SELECT element, price_tenths FROM players_live "
        "WHERE element = ANY(%s) AND price_tenths IS NOT NULL", (elements,))}
    t0 = time.time()
    team, missing = squad_store.xi_over_fifteen(pool, state, prices)
    roles = squad_store.roles_from_team(team)
    run = _latest_run(gw=cutoff)
    comparison = squad_store.compare_roles(doc["players"], team)
    rows = []
    for r in team.itertuples(index=False):
        role, bo = roles[int(r.element)]
        rows.append({"player_id": int(r.element), "name": r.name, "position": r.position,
                     "team": str(r.team), "role": role, "bench_order": bo,
                     "e_points": round(float(r.e_points), 2),
                     "p_play_any": (round(float(r.p_play_any), 2)
                                    if hasattr(r, "p_play_any") and r.p_play_any == r.p_play_any else None)})
    order = {"CAPTAIN": 0, "VICE": 1, "start": 2, "bench": 3}
    rows.sort(key=lambda r: (order[r["role"]], r["bench_order"] or 0, -r["e_points"]))
    xi = [r for r in rows if r["role"] != "bench"]
    bench = [r for r in rows if r["role"] == "bench"]
    nd = _next_deadline()
    out = {
        "gw": target, "predictions_as_of_cutoff_gw": cutoff, "stale_by_gameweeks": target - cutoff,
        "frame_built_at": str(built),
        "run_id": run["run_id"] if run else None,
        "model_version": _version(run, PRODUCTION_CONFIG) if run else None,
        "squad_version_id": record["version_id"],
        "solve_seconds": round(time.time() - t0, 1),
        "captain": next(r["name"] for r in xi if r["role"] == "CAPTAIN"),
        "vice": next(r["name"] for r in xi if r["role"] == "VICE"),
        "xi": xi, "bench_in_order": bench,
        "predicted_xi_points": comparison["optimal_xi_points"],
        "missing_from_frame": missing,
        "recorded_roles": {"as_of_gw": record["gw"], "recorded_at": str(record["created_at"]),
                           **comparison},
        "adopt_with": {"player_ids": sorted(elements),
                       "captain_id": next(r["player_id"] for r in xi if r["role"] == "CAPTAIN"),
                       "vice_id": next(r["player_id"] for r in xi if r["role"] == "VICE"),
                       "bench_order_ids": [r["player_id"] for r in bench],
                       "gw": target, "confirm": True},
    }
    if missing:
        out["note_missing"] = (f"{len(missing)} owned player(s) have no row for GW{target} in the "
                               f"frame (blank gameweek or absent at cutoff GW{cutoff}) and were "
                               "solved at 0 expected points, per the production blank-week rule")
    if target != cutoff:
        out["note_stale"] = (f"the frame on the volume is GW{cutoff}'s (built {built:%Y-%m-%d %H:%M}Z); "
                             f"GW{target}'s predictions here are as seen from cutoff GW{cutoff}, "
                             f"{target - cutoff} gameweek(s) stale. A fresh frame lands when the "
                             f"pipeline runs at T-90 before the GW{target} deadline"
                             + (f" ({nd[1]})" if nd else ""))
    return out


def set_my_squad(player_ids: list, captain_id: int, vice_id: int, bench_order_ids: list,
                 gw: int = None, note: str = None, confirm: bool = False, user_id: int = 1):
    """Write a NEW version of the user's squad (and supersede the active one).
    The caller states the fifteen and the roles; the money is derived: the
    change is the difference from the active fifteen, outgoing players are
    valued by FPL's sell rule (squad_state.sell_price), incoming players cost
    their current players_live price, free transfers are consumed first and
    hits (4 points each) are reported. Illegal, unaffordable or mis-roled
    squads are refused with the reason -- never adjusted.

    confirm=False (default) is a PREVIEW: the write runs and is rolled back;
    the response shows exactly what confirm=True would record. gw defaults
    to the next deadline's gameweek."""
    try:
        active = squad_store.read_active(user_id)
    except squad_store.SquadStateError as e:
        return {"error": str(e)}
    try:
        current = _current_gw()
    except RuntimeError as e:
        return {"error": f"{e} -- refusing to write a squad version without knowing the gameweek"}
    if gw is None:
        gw = current
    involved = sorted({p["element"] for p in active["squad_json"]["players"]} | set(player_ids or []))
    rows = _q("""SELECT element, name, position, team, price_tenths, updated_at
                 FROM players_live WHERE element = ANY(%s)""", (involved,))
    live = {r["element"]: r for r in rows}
    priced_from = f"players_live as of {max((r['updated_at'] for r in rows), default=None)}"
    import db_write
    try:
        new_doc, change = squad_store.plan_change(
            active, player_ids, captain_id, vice_id, bench_order_ids, gw, live,
            priced_from=priced_from,
            created_by=f"model_tools.set_my_squad @ {db_write.git_sha() or 'unknown'}",
            next_deadline_gw=current)
    except ValueError as e:
        return {"error": f"refused: {e}", "refused": True, "active_version": active["version_id"]}
    try:
        row = squad_store.write_version(active, new_doc, gw, note, confirm, user_id=user_id)
    except squad_store.SquadStateError as e:
        return {"error": str(e)}

    def m(t):
        return None if t is None else round(t / 10, 1)

    prices = {e: live[e]["price_tenths"] for e in involved}
    latest = _latest_run()
    return {
        "committed": row["committed"],
        "preview": not row["committed"],
        "message": ("version written and now active" if row["committed"] else
                    "PREVIEW ONLY -- nothing was written; call again with confirm=true "
                    "to record this squad"),
        "version_id": row["version_id"], "supersedes": row["supersedes"], "gw": row["gw"],
        "change": {
            "transfers": [{"out": t["out_name"], "out_id": t["out"], "sold_for": m(t["sold_for"]),
                           "in": t["in_name"], "in_id": t["in"], "bought_for": m(t["bought_for"])}
                          for t in change["transfers"]],
            "n_transfers": change["n_transfers"],
            "free_transfers_recorded": change["free_transfers_recorded"],
            "free_transfers_recorded_as_of_gw": change["free_transfers_recorded_as_of_gw"],
            "gameweeks_rolled_forward": change["gameweeks_rolled_forward"],
            "free_transfers_before": change["free_transfers_before"],
            "free_transfers_used": change["free_transfers_used"],
            "free_transfers_after": change["free_transfers_after"],
            "hits": change["hits"], "hit_cost_points": change["hit_cost_points"],
            "bank_before": m(change["bank_before"]), "proceeds": m(change["proceeds"]),
            "purchases": m(change["purchases"]), "bank_after": m(change["bank_after"]),
        },
        "squad": squad_store.summary(row, prices, latest_run=latest, current_gw=current),
    }


# ---------------------------------------------------------------- the solve
def _load_pool(gw=None):
    """The production frame on the model volume, sliced to one gameweek in
    optimize's shape -> (pool, cutoff_gw, frame_built_at). gw None = the
    frame's own deadline gameweek (its cutoff); a later gw inside the horizon
    gives that gameweek AS SEEN FROM the cutoff (the stale-by-one case between
    deadlines) -- gw_slice raises ValueError beyond the horizon. Shared by
    optimise() and get_my_xi(). Raises FileNotFoundError when the pipeline has
    not produced a build on this volume."""
    import sys
    for p in (str(REPO), str(REPO / "squad")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import simulator as sim

    frame_p = PROD_FRAME
    prices_p = REPO / "data" / "live" / "_tmp_prices_2026_27.parquet"
    if not frame_p.exists() or not prices_p.exists():
        raise FileNotFoundError("no frame on the model volume yet -- the pipeline has "
                                "not produced a build here")
    df = sim.load_season(walkforward_path=str(frame_p), history_path=str(prices_p),
                         horizon_aware=True, season=os.getenv("FPL_SEASON", "2026-27"))
    cutoff = int(df["cutoff"].min())
    pool = sim.gw_slice(df, cutoff if gw is None else int(gw), cutoff=cutoff)
    built = datetime.fromtimestamp(frame_p.stat().st_mtime, tz=timezone.utc)
    return pool, cutoff, built


def optimise(lock_player_ids: list = None, ban_player_ids: list = None,
             budget: float = None):
    """Run the production MIP (gapRel=0) on the latest frame from the model
    volume, with constraints. Returns the fifteen + XI + captain + vice.
    This is a real solve: it takes seconds and blocks this chat turn."""
    import pulp
    import simulator as sim
    from optimize import optimize_squad as solve_mip

    t0 = time.time()
    try:
        pool, cutoff, frame_mtime = _load_pool()
    except FileNotFoundError as e:
        return {"error": str(e)}
    prob, sol = solve_mip(pool,
                          locked_elements=list(lock_player_ids or []),
                          banned_elements=list(ban_player_ids or []),
                          budget=None if budget is None else int(round(budget * 10)))
    if pulp.LpStatus[prob.status] != "Optimal":
        return {"error": f"solve status {pulp.LpStatus[prob.status]} -- the "
                         "constraints may be infeasible (e.g. budget too low)"}
    team = sim.solution_to_squad(pool, sol)
    return {"gw": cutoff, "solve_seconds": round(time.time() - t0, 1),
            "frame_built_at": str(frame_mtime),
            "constraints": {"locked": lock_player_ids or [], "banned": ban_player_ids or [],
                            "budget": budget or 100.0},
            "captain": team.loc[team["role"] == "CAPTAIN", "name"].iloc[0],
            "vice": team.loc[team["role"] == "VICE", "name"].iloc[0],
            "squad": [{"player_id": int(r["element"]), "name": r["name"],
                       "position": r["position"], "price": r["value"] / 10,
                       "e_points": round(float(r["e_points"]), 2), "role": r["role"]}
                      for _, r in team.iterrows()],
            "squad_cost": round(team["value"].sum() / 10, 1)}


# ------------------------------------------------------------------- health
_DEADLINE_CACHE = {"at": 0.0, "value": None}


def _next_deadline():
    """(gw, deadline_dt) from bootstrap, cached 10 minutes; None on failure."""
    if time.time() - _DEADLINE_CACHE["at"] < 600:
        return _DEADLINE_CACHE["value"]
    try:
        import requests
        events = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/",
                              timeout=5).json()["events"]
        now = datetime.now(timezone.utc)
        val = None
        for e in events:
            dl = datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))
            if dl > now:
                val = (e["id"], dl)
                break
    except Exception:
        val = None
    _DEADLINE_CACHE.update(at=time.time(), value=val)
    return val


def _weekly_ingest_status(reasons):
    """First line + age of the weekly ingest's two status files (data/live on the
    volume). Appends to `reasons` on FAILED, ACTION REQUIRED, or a dead cron."""
    live = REPO / "data" / "live"
    out = {}
    now = datetime.now(timezone.utc)
    for key, name in (("last_run", "INGEST_STATUS.txt"), ("last_tick", "INGEST_TICK.txt")):
        p = live / name
        if not p.exists():
            out[key] = None
            continue
        try:
            first = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except (OSError, IndexError):
            first = "?"
        age_h = (now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600
        out[key] = {"first_line": first, "age_hours": round(age_h, 1)}
    lr, lt = out.get("last_run"), out.get("last_tick")
    if lr and lr["first_line"].startswith("FAILED"):
        reasons.append("weekly ingest FAILED -- the next deadline would build on stale history "
                       "(data/live/INGEST_STATUS.txt)")
    for s in (lr, lt):
        if s and "ACTION REQUIRED" in s["first_line"]:
            reasons.append("weekly ingest needs a human: " + s["first_line"] +
                           " (data/live/INGEST_STATUS.txt / INGEST_TICK.txt)")
            break
    if lt is None:
        reasons.append("weekly ingest has never ticked on this volume (cron not installed?)")
    elif lt["age_hours"] > 13.0:
        reasons.append(f"weekly ingest cron has not ticked for {lt['age_hours']:.0f}h (every 6h expected)")
    return out


def health():
    """{status, git_sha, model_versions, data_freshness_by_source, db_ok,
    last_run} -- the master plan's health contract. `status` degrades when
    the DB is down, the last run FAILED, no run exists, or the pipeline is
    late for the next deadline (inside T-90 with no run for that gw)."""
    reasons = []
    db_ok = True
    last = last_any = None
    try:
        last = _latest_run()
        last_any = _latest_run(any_status=True)
    except Exception as e:
        db_ok = False
        reasons.append(f"database unreachable: {type(e).__name__}")

    import db_write
    sha = db_write.git_sha()

    model_versions = None
    if last:
        model_versions = {c: f"{last.get('git_sha') or 'unknown'}/{c}"
                          for c in CONFIGS}

    freshness = {}
    if db_ok:
        if last:
            age_h = (datetime.now(timezone.utc) - last["finished_at"]).total_seconds() / 3600
            freshness["model_run"] = {"gw": last["gw"], "built_at": str(last["finished_at"]),
                                      "age_hours": round(age_h, 1),
                                      "recovered": last["recovered"]}
        else:
            freshness["model_run"] = None
            reasons.append("no successful pipeline run recorded at all")
        try:
            pl = _q("SELECT MAX(updated_at) AS u, COUNT(*) AS n FROM players_live")
            freshness["players_live"] = {"rows": pl[0]["n"], "updated_at": str(pl[0]["u"])}
        except Exception:
            freshness["players_live"] = None
    frame_p = PROD_FRAME
    freshness["frame_on_volume"] = (
        str(datetime.fromtimestamp(frame_p.stat().st_mtime, tz=timezone.utc))
        if frame_p.exists() else None)

    # the weekly ingest (eval/run_weekly_ingest.py, server cron every 6h): its
    # status files on the volume. A FAILED ingest, a standing ACTION REQUIRED
    # (an element with minutes and no Understat id -- the Cherki class) and a
    # cron that has stopped ticking all degrade health, because otherwise the
    # next deadline builds on stale history and nobody is told.
    freshness["weekly_ingest"] = _weekly_ingest_status(reasons)

    nd = _next_deadline()
    if nd:
        gw, dl = nd
        freshness["next_deadline"] = {"gw": gw, "deadline": str(dl)}
        if db_ok:
            mins_to = (dl - datetime.now(timezone.utc)).total_seconds() / 60
            if mins_to <= 90 and (last is None or last["gw"] < gw):
                reasons.append(f"pipeline has not run for GW{gw} and its deadline "
                               f"is {max(mins_to, 0):.0f} min away (fires at T-90)")
    else:
        freshness["next_deadline"] = None

    if last_any and last_any["status"] != "SUCCESS":
        reasons.append(f"most recent run FAILED (GW{last_any['gw']}, "
                       f"{last_any['finished_at']}): {last_any.get('note') or 'see status file'}")

    return {"status": "ok" if db_ok and not reasons else "degraded",
            "git_sha": sha, "model_versions": model_versions,
            "data_freshness_by_source": freshness, "db_ok": db_ok,
            "last_run": (dict(run_id=last["run_id"], gw=last["gw"],
                              status=last["status"], recovered=last["recovered"],
                              finished_at=str(last["finished_at"])) if last else None),
            "reasons": reasons}
