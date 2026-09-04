# model_tools.py -- the app's typed reads over the MODEL's outputs, replacing
# the naive predict_naive tables the agent served since Phase 1.
#
# Contract (master plan serving section): the agent reads predictions and
# picks through these tools -- it never touches parquet or the solver
# internals directly. Every answer is traceable: rows carry run_id,
# model_version (git_sha/config) and built_at, and recovered runs say so.
#
# CONFIGS: 'combined' is production -- every user-facing default reads it.
# 'baseline' is the shadow; it is reachable only where a tool takes an
# explicit config/shadow argument, so the two cannot be confused.
#
# The one non-DB tool is optimise(): it solves from the latest frame on the
# model volume (data/live/_tmp_frame_combined.parquet, written by each run)
# through squad/optimize.py -- the same MIP the pipeline uses, gapRel=0.

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
REPO = Path(__file__).resolve().parent


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


def _run_meta(run, config="combined"):
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
             WHERE run_id = %s AND config = 'combined' AND element = %s"""
    params = [run["run_id"], player_id]
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
    config = "baseline" if shadow else "combined"
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
               WHERE run_id = %s AND config = 'combined'""", (run["run_id"],))}
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


# ---------------------------------------------------------------- the solve
def optimise(lock_player_ids: list = None, ban_player_ids: list = None,
             budget: float = None):
    """Run the production MIP (gapRel=0) on the latest frame from the model
    volume, with constraints. Returns the fifteen + XI + captain + vice.
    This is a real solve: it takes seconds and blocks this chat turn."""
    import sys
    for p in (str(REPO), str(REPO / "squad")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import pandas as pd
    import pulp
    import simulator as sim
    from optimize import optimize_squad as solve_mip

    frame_p = REPO / "data" / "live" / "_tmp_frame_combined.parquet"
    prices_p = REPO / "data" / "live" / "_tmp_prices_2026_27.parquet"
    if not frame_p.exists() or not prices_p.exists():
        return {"error": "no frame on the model volume yet -- the pipeline has "
                         "not produced a build here"}
    t0 = time.time()
    df = sim.load_season(walkforward_path=str(frame_p), history_path=str(prices_p),
                         horizon_aware=True, season=os.getenv("FPL_SEASON", "2026-27"))
    cutoff = int(df["cutoff"].min())
    pool = sim.gw_slice(df, cutoff, cutoff=cutoff)
    prob, sol = solve_mip(pool,
                          locked_elements=list(lock_player_ids or []),
                          banned_elements=list(ban_player_ids or []),
                          budget=None if budget is None else int(round(budget * 10)))
    if pulp.LpStatus[prob.status] != "Optimal":
        return {"error": f"solve status {pulp.LpStatus[prob.status]} -- the "
                         "constraints may be infeasible (e.g. budget too low)"}
    team = sim.solution_to_squad(pool, sol)
    frame_mtime = datetime.fromtimestamp(frame_p.stat().st_mtime, tz=timezone.utc)
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
                          for c in ("combined", "baseline")}

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
    frame_p = REPO / "data" / "live" / "_tmp_frame_combined.parquet"
    freshness["frame_on_volume"] = (
        str(datetime.fromtimestamp(frame_p.stat().st_mtime, tz=timezone.utc))
        if frame_p.exists() else None)

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
