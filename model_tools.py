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


def _dispatch_state():
    """The scheduler's state file on the volume (eval/deadline_dispatcher.py);
    {} if it has never ticked here."""
    p = REPO / "data" / "live" / "dispatch_state.json"
    try:
        import json
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _dp():
    import sys
    if str(REPO / "eval") not in sys.path:
        sys.path.insert(0, str(REPO / "eval"))
    import dispatch_policy
    return dispatch_policy


def _freshness(run):
    """The sentence every answer carries (dispatch_policy.freshness): when the
    run was built, what it knew, what it predicts, and the next run the
    schedule promises."""
    k = run.get("knowledge")
    if isinstance(k, str):
        import json
        try:
            k = json.loads(k)
        except ValueError:
            k = None
    r = dict(run)
    r["knowledge"] = k
    return _dp().freshness(r, (_dispatch_state() or {}).get("expected_next"))


def _run_meta(run, config=PRODUCTION_CONFIG):
    exp = (_dispatch_state() or {}).get("expected_next")
    return {"run_id": run["run_id"], "gw": run["gw"],
            "model_version": _version(run, config),
            "built_at": str(run["finished_at"]),
            "kind": run.get("kind") or "deadline", "slot": run.get("slot"),
            "built": _freshness(run),
            "next_run_expected": exp,
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
# ---- reading a table whose newest columns may not exist yet ----------------------
# A READ MUST NOT DIE BECAUSE A WRITE HAS NOT HAPPENED. New columns are added by
# `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` inside db_write.ensure_schema, and ONLY the
# write paths call it -- so between deploying a column and the next build finishing, a read
# that names that column fails outright. That happened on 2026-09-18: the quantile columns
# were deployed at 23:09Z, the last write was run 15 at 17:21Z, and every get_prediction call
# raised UndefinedColumn until ensure_schema was run by hand.
#
# The fix is on the READ side deliberately, rather than making migrations stricter: a read
# that depends on a write having happened is fragile in a way that recurs with every new
# column. Optional columns are selected only if the live schema has them, and their absence
# reads the same as their being NULL -- "not computed", never zero.
PRED_BASE_COLS = ["gw", "horizon_step", "e_points", "e_minutes", "p_start", "p_60plus",
                  "e_goals", "e_assists", "p_cs", "exp_bonus"]
PRED_OPTIONAL_COLS = ["e_pen_goals", "penalty_share",
                      "q_p10", "q_p50", "q_p90", "q_sd", "q_degenerate", "q_distinct",
                      "q_resid_sampling", "q_resid_structural", "q_tolerance",
                      "q_method_version", "q_minutes_shape", "q_draws",
                      # INPUTS to the runaway flag, not outputs. Selected so the quantile
                      # block can run explain's bound check on the row it is describing --
                      # without them fixture_runaway() sees no lambdas and answers False on
                      # every live row, which is the flag being dead on arrival rather than
                      # absent. Stripped from `predictions` below: a raw strength parameter
                      # is not a prediction and must not read as one.
                      "team_lambda", "opp_lambda"]
PRED_INTERNAL_COLS = ("team_lambda", "opp_lambda")
_COLUMN_CACHE = {}
COLUMN_CACHE_TTL_S = 60.0          # short, so a migration is picked up without a restart


def _prediction_columns(available):
    """PURE. The base columns always; an optional column only when the schema has it.
    An empty/unknown `available` falls back to the base set -- the columns that have existed
    since before any of this, so the read still works when introspection itself fails."""
    if not available:
        return list(PRED_BASE_COLS)
    return list(PRED_BASE_COLS) + [c for c in PRED_OPTIONAL_COLS if c in available]


def _table_columns(table, ttl=COLUMN_CACHE_TTL_S):
    """The columns the LIVE table has. Cached briefly: long enough not to cost a round trip
    per call, short enough that a migration run by a build is picked up without restarting
    the API. Returns an empty set if it cannot tell, which _prediction_columns treats as
    "assume only the base columns"."""
    now = time.time()
    hit = _COLUMN_CACHE.get(table)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        rows = _q("SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                  (table,))
        cols = {r["column_name"] for r in rows}
    except Exception:                                   # noqa: BLE001 -- a read must not die here
        cols = set()
    _COLUMN_CACHE[table] = (now, cols)
    return cols


def get_prediction(player_id: int, gw: int = None):
    """The production model's view of one player: the target gw if given,
    else every gameweek in the latest run's six-week horizon."""
    run = _latest_run()
    if run is None:
        return {"error": "no successful pipeline run in the database yet"}
    cols = _prediction_columns(_table_columns("model_predictions"))
    sql = ("SELECT " + ", ".join(cols)
           + " FROM model_predictions"
           + " WHERE run_id = %s AND config = %s AND element = %s")
    params = [run["run_id"], PRODUCTION_CONFIG, player_id]
    if gw is not None:
        sql += " AND gw = %s"
        params.append(gw)
    rows = _q(sql + " ORDER BY gw", tuple(params))
    if not rows:
        return {"error": f"no prediction rows for player {player_id} in run "
                         f"{run['run_id']} (not in the pool at that cutoff)"}
    # The player's club, for naming a runaway own-team strength. model_predictions does not
    # carry it, and guessing a club by matching lambdas is the recorded mis-pairing trap. A
    # separate, guarded lookup: if it fails the club is simply not named, and the rest of the
    # answer is unaffected -- a cosmetic lookup must never be able to break a prediction read.
    club = None
    try:
        hit = _q("SELECT team FROM players_live WHERE element = %s LIMIT 1", (player_id,))
        club = hit[0]["team"] if hit else None
    except Exception:                                   # noqa: BLE001
        club = None
    for r in rows:
        r["team"] = club

    out = _run_meta(run)
    out["player_id"] = player_id
    out["team"] = club
    out["predictions"] = [{k: (float(v) if isinstance(v, float) else v)
                           for k, v in r.items()
                           if k not in PRED_INTERNAL_COLS and k != "team"} for r in rows]
    out["horizon_e_points_sum"] = round(sum(r["e_points"] or 0 for r in rows), 2)
    out["quantiles"] = _quantile_block(rows)
    return out


def _quantile_block(rows):
    """The quantile half of a prediction answer, or an explicit statement that this run did
    not compute them -- never silence, which a reader would take for an absence of
    uncertainty rather than an absence of a calculation.

    P90 is NOT presented as comparable in quality to P50: it is the number carrying the new
    information and the one the model's known defects corrupt most, so the fidelity block
    travels with it (quantiles.fidelity)."""
    import quantiles as qt
    from explain import fixture_runaway, runaway_side   # the DETECTION, not a second copy
    have = [r for r in rows if r.get("q_p50") is not None]
    if not have:
        return {"computed": False,
                "why": ("this run did not compute quantiles -- the t10 slot skips them "
                        "deliberately, because ~40 s on a 70-86 s build is a ~45% increase "
                        "on the one run that cannot be late. Ask after the next nightly, "
                        "t90 or t30 run. This is a missing CALCULATION, not an absence of "
                        "uncertainty."),
                "per_gw": []}
    per = []
    for r in have:
        ra = fixture_runaway(r)
        per.append({
            "gw": r["gw"],
            # Per gameweek, because a horizon usually mixes runaway and ordinary fixtures and
            # a single answer-level flag would either condemn the clean gameweeks or excuse
            # the broken one. When true, P10 is MANUFACTURED, not merely uncertain.
            "runaway": ra,
            "p10_unusable": ra,
            "runaway_sides": runaway_side(r) if ra else [],
            "p10": round(float(r["q_p10"]), 2), "p50": round(float(r["q_p50"]), 2),
            "p90": round(float(r["q_p90"]), 2), "sd": round(float(r["q_sd"] or 0), 3),
            "one_sided_bar": bool(r.get("q_degenerate")),
            "reconciles": qt.reconciles(r),
            "resid_sampling": round(float(r["q_resid_sampling"] or 0), 4),
            "resid_structural": round(float(r["q_resid_structural"] or 0), 4),
            "tolerance": round(float(r["q_tolerance"] or qt.TOL_FLOOR), 4),
        })
    # WHICH ROW SPEAKS FOR THE ANSWER. It was the largest-sampling-residual row, which was
    # arbitrary: sampling noise is the one part of this that is bounded and reported per row
    # anyway, so the noisiest row is not the most fragile one. Take fidelity from a row that
    # HAS the condition -- earliest affected gameweek, so it is deterministic -- and fall back
    # to the earliest gameweek when none does. The runaway gameweeks are listed either way,
    # so a caveat drawn from one row is scoped to the rows it is true of.
    runaways = [r for r in have if fixture_runaway(r)]
    by_gw = sorted(have, key=lambda r: int(r["gw"]))
    src = sorted(runaways, key=lambda r: int(r["gw"]))[0] if runaways else by_gw[0]
    fid = qt.fidelity(src)
    fid["source_gw"] = int(src["gw"])
    fid["source_rule"] = ("earliest gameweek whose fixture has a runaway strength"
                          if runaways else "earliest gameweek in the horizon (none is affected)")
    fid["runaway_in_horizon"] = bool(runaways)
    fid["runaway_gws"] = [int(r["gw"]) for r in sorted(runaways, key=lambda r: int(r["gw"]))]
    fid["p10_unusable_gws"] = list(fid["runaway_gws"])
    if runaways and len(runaways) < len(have):
        fid["p10_caveat"] = (f"Applies to GW{', GW'.join(str(g) for g in fid['runaway_gws'])} "
                             f"only, not the whole horizon. " + fid["p10_caveat"])
    return {
        "computed": True,
        "method_version": src.get("q_method_version"),
        "minutes_shape": src.get("q_minutes_shape"),
        "draws": src.get("q_draws"),
        "per_gw": per,
        "reconciliation": {
            "form": "two-part, deliberately",
            "sampling": "judged against max(0.02, 3*sd/sqrt(N)); a breach is a finding",
            "structural": ("reported as a value with NO pass bar -- it is a BIAS, not noise: "
                           "the model evaluates the saves and conceded terms at EXPECTED "
                           "minutes, so it does not shrink with more draws. Identically zero "
                           "for MID and FWD. A single combined bar would either hide it or "
                           "fail about 8% of rows forever."),
            "all_within_sampling_tolerance": all(p["reconciles"] for p in per),
        },
        "fidelity": fid,
    }


def compare_players(player_id_a: int, player_id_b: int):
    a, b = get_prediction(player_id_a), get_prediction(player_id_b)
    if "error" in a or "error" in b:
        return {"a": a, "b": b}
    names = {r["element"]: r["name"] for r in _q(
        "SELECT element, name FROM players_live WHERE element IN (%s, %s)",
        (player_id_a, player_id_b))}

    def brief(p):
        first = p["predictions"][0]
        # The first row is the RUN's own gameweek -- between deadlines that is the one just
        # played, not "next". The gameweek travels with the number (2026-09-14: an answer
        # called GW4's figures "next gameweek" while GW5 was the next deadline).
        return {"player_id": p["player_id"], "name": names.get(p["player_id"]),
                "first_gw": first["gw"],
                "first_gw_e_points": first["e_points"],
                "first_gw_p_start": first["p_start"],
                "horizon_e_points_sum": p["horizon_e_points_sum"],
                "horizon_gws": [r["gw"] for r in p["predictions"]]}
    out = {"model_version": a["model_version"], "built_at": a["built_at"], "built": a.get("built"),
           "next_run_expected": a.get("next_run_expected"),
           "recovered_post_deadline": a["recovered_post_deadline"],
           "a": brief(a), "b": brief(b),
           "verdict": "a" if a["horizon_e_points_sum"] >= b["horizon_e_points_sum"] else "b",
           "verdict_basis": "horizon_e_points_sum"}
    try:
        nxt = _current_gw()
    except RuntimeError:
        nxt = None
    if nxt is not None and out["a"]["first_gw"] < nxt:
        out["note_stale"] = (f"the first-gameweek figures are for GW{out['a']['first_gw']}, the run's own gameweek, "
                             f"which has been played; the next deadline is GW{nxt} -- for this week use "
                             f"compare_predictions / get_prediction with gw={nxt} (as seen from the GW{out['a']['first_gw']} cutoff)")
    return out


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
    scores = _q(squad_store.SCORES_LATEST_SQL, (user_id, record["season"]))
    return squad_store.summary(record, prices, latest_run=_latest_run(),
                               current_gw=current, current_gw_error=current_err,
                               scores=scores)


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
    except (FileNotFoundError, RuntimeError) as e:
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
        "frame_built_at": str(built), **_frame_built(cutoff),
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
                 gw: int = None, note: str = None, confirm: bool = False, user_id: int = 1,
                 proposal_id: int = None):
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
            next_deadline_gw=current,
            extra_provenance=({"proposal_id": int(proposal_id)} if proposal_id is not None else None))
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
def _load_frame():
    """The production frame on the model volume as the simulator's season
    frame -> (df, cutoff_gw, frame_built_at). Raises FileNotFoundError when the
    pipeline has not produced a build on this volume."""
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
    built = datetime.fromtimestamp(frame_p.stat().st_mtime, tz=timezone.utc)
    _check_sidecar(frame_p, cutoff)
    return df, cutoff, built


def _check_sidecar(frame_p, cutoff):
    """The sidecar ties the file to a run; it must be the database's latest
    successful run for that gameweek or the two have drifted (a failed build
    that half-wrote, a restored volume) -- refuse rather than answer."""
    side_p = frame_p.with_suffix(".provenance.json")
    if side_p.exists():
        import json
        try:
            side = json.loads(side_p.read_text(encoding="utf-8"))
        except ValueError:
            side = {}
        latest = _latest_run(gw=cutoff)
        if side.get("run_id") is not None and latest and int(latest["run_id"]) != int(side["run_id"]):
            raise RuntimeError(
                f"the frame on the volume belongs to run {side['run_id']} but the database's latest "
                f"successful run for GW{cutoff} is {latest['run_id']} -- frame and database disagree; "
                "not answering from a frame of unknown provenance")


def _frame_raw():
    """The production frame on the model volume with EVERY column it was written
    with (the eight pts_* terms and their inputs), for the explain tools ->
    (df, cutoff_gw, frame_built_at). Same file, same sidecar check as _load_frame;
    not the simulator's shape (which drops the terms)."""
    import pandas as pd
    frame_p = PROD_FRAME
    if not frame_p.exists():
        raise FileNotFoundError("no frame on the model volume yet -- the pipeline has "
                                "not produced a build here")
    df = pd.read_parquet(frame_p)
    cutoff = int(df["cutoff"].min())
    built = datetime.fromtimestamp(frame_p.stat().st_mtime, tz=timezone.utc)
    _check_sidecar(frame_p, cutoff)
    return df, cutoff, built


def _explain_row(df, cutoff, player_id, target):
    """One (element, gw) row of the raw frame and its gameweek slice, or an error dict."""
    step = df[df["gw"] == int(target)]
    if step.empty:
        lo, hi = int(df["gw"].min()), int(df["gw"].max())
        return None, None, {"error": f"the frame on the volume has no predictions for GW{target}: it covers "
                                     f"GW{lo}-GW{hi} as seen from cutoff GW{cutoff}"}
    row = step[step["element"] == int(player_id)]
    if row.empty:
        return None, None, {"error": f"no row for player {player_id} in GW{target}: a blank gameweek for the "
                                     f"club, or the player was not in the frame at cutoff GW{cutoff}"}
    return row.iloc[0], step, None


def _stale_note(target, cutoff, built):
    if target == cutoff:
        return None
    nd = _next_deadline()
    return (f"the frame on the volume is GW{cutoff}'s (built {built:%Y-%m-%d %H:%M}Z); GW{target}'s "
            f"predictions here are as seen from cutoff GW{cutoff}, {target - cutoff} gameweek(s) stale. "
            f"A fresh frame lands when the pipeline runs at T-90 before the GW{target} deadline"
            + (f" ({nd[1]})" if nd else ""))


def _run_by_id(run_id):
    rows = _q("SELECT * FROM model_runs WHERE run_id = %s", (int(run_id),))
    return rows[0] if rows else None


def _rows_from_db(run, config, gw):
    """The gameweek slice of a STORED run as a frame-shaped DataFrame: every column
    explain.breakdown reads -- the terms and inputs from model_predictions (recorded
    from 2026-09-14), name / position / team from players_live, and the per-run frame
    stamps (bonus_mode, penalty_fix_active, ...) from model_runs.model_stamp. Raises
    ValueError when the run predates the term columns (they are NULL, never backfilled)."""
    import pandas as pd
    rows = _q("""SELECT p.*, l.name, l.position, l.team
                 FROM model_predictions p LEFT JOIN players_live l ON l.element = p.element
                 WHERE p.run_id = %s AND p.config = %s AND p.gw = %s""",
              (int(run["run_id"]), config, int(gw)))
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if df["pts_goals"].isna().all():
        raise ValueError(f"run {run['run_id']} has no recorded terms (built {run['finished_at']}, before the term "
                         "columns of 2026-09-14; they are never backfilled) -- only its totals can be read")
    stamp = run.get("model_stamp") or {}
    if isinstance(stamp, str):
        import json
        try:
            stamp = json.loads(stamp)
        except ValueError:
            stamp = {}
    for k, v in (stamp.get(config) or {}).items():
        df[k] = v
    df["understat_id"] = df["understat_id"].where(df["understat_id"].notna(), None)
    return df


def _explain_from_run(run_id, player_id, gw):
    """(breakdown, run, cutoff) for a stored run, or an error dict."""
    import explain
    run = _run_by_id(run_id)
    if run is None:
        return None, None, {"error": f"no run {run_id} in the database"}
    if run.get("status") != "SUCCESS":
        return None, None, {"error": f"run {run_id} is {run.get('status')}: it wrote no predictions"}
    try:
        step = _rows_from_db(run, PRODUCTION_CONFIG, gw)
    except ValueError as e:
        return None, None, {"error": str(e)}
    if step is None:
        return None, None, {"error": f"run {run_id} (GW{run['gw']}) has no rows for GW{gw}: outside its six-week horizon"}
    row = step[step["element"] == int(player_id)]
    if row.empty:
        return None, None, {"error": f"no row for player {player_id} in GW{gw} of run {run_id}"}
    return explain.breakdown(row.iloc[0], step), run, int(row.iloc[0]["cutoff"])


def explain_prediction(player_id: int, gw: int = None, run_id: int = None):
    """LEVEL 1 (Logs/explain_prediction_design.md): the breakdown of one player's
    expected points for one gameweek into the nine lines the master equation
    sums -- appearance, goals (with the penalties sub-line), assists, clean
    sheet, defensive contribution, saves, goals conceded, cards, bonus -- each
    with the inputs it was made from and ONE of three source words: model
    (a fitted model for this player/fixture), constant (a fixed value standing
    in for a model the project has not built or has switched off), rule (FPL's
    scoring rule applied to a model output). Plus the fixture line, the two
    identities re-asserted on the row (a failure is a FINDING, not an answer),
    and one summary sentence. Read-only. run_id None = the production frame on
    the volume (the latest run); a run_id reads that run's STORED terms from the
    database (recorded from 2026-09-14; earlier runs answer with an error)."""
    import explain
    if run_id is not None:
        if gw is None:
            return {"error": "gw is required with run_id"}
        bd, run, cutoff = _explain_from_run(run_id, player_id, int(gw))
        if bd is None:
            return cutoff                      # the error dict
        m = _run_meta(run)
        return {**bd, "run_id": run["run_id"], "predictions_as_of_cutoff_gw": cutoff,
                "stale_by_gameweeks": int(gw) - cutoff, "built": m["built"], "model_version": m["model_version"],
                "source": "database (stored terms of that run)"}
    try:
        target = int(gw) if gw is not None else _current_gw()
    except RuntimeError as e:
        return {"error": str(e)}
    try:
        df, cutoff, built = _frame_raw()
    except (FileNotFoundError, RuntimeError) as e:
        return {"error": str(e)}
    row, step, err = _explain_row(df, cutoff, player_id, target)
    if err:
        return err
    bd = explain.breakdown(row, step)
    out = {**bd, "predictions_as_of_cutoff_gw": cutoff, "stale_by_gameweeks": target - cutoff,
           "frame_built_at": str(built), **_frame_built(cutoff)}
    note = _stale_note(target, cutoff, built)
    if note:
        out["note_stale"] = note
    return out


def compare_runs(player_id: int, gw: int, run_id_a: int, run_id_b: int):
    """WHY one player's expected points for one gameweek moved between two runs
    ("Tuesday said 8.5, Friday says 6.2"): both stored breakdowns (the terms
    recorded with each run), the per-term difference a - b ranked by size, the
    terms accounting for >= 80% of the gap, the constant-vs-model flags, and
    what each run knew (its `built` line). Runs before 2026-09-14 have no stored
    terms and answer with an error."""
    import explain
    a, run_a, cut_a = _explain_from_run(run_id_a, player_id, int(gw))
    if a is None:
        return cut_a
    b, run_b, cut_b = _explain_from_run(run_id_b, player_id, int(gw))
    if b is None:
        return cut_b
    c = explain.compare(a, b, label_a=f"run {run_a['run_id']}", label_b=f"run {run_b['run_id']}")
    ma, mb = _run_meta(run_a), _run_meta(run_b)
    return {**c, "player_id": int(player_id), "name": a["name"], "gw": int(gw),
            "run_a": {"run_id": run_a["run_id"], "kind": ma["kind"], "slot": ma["slot"], "built": ma["built"],
                      "predictions_as_of_cutoff_gw": cut_a, "total_e_points": a["total_e_points"]},
            "run_b": {"run_id": run_b["run_id"], "kind": mb["kind"], "slot": mb["slot"], "built": mb["built"],
                      "predictions_as_of_cutoff_gw": cut_b, "total_e_points": b["total_e_points"]},
            "breakdown_a": a, "breakdown_b": b, "source": "database (stored terms of both runs)"}


def compare_predictions(player_id_a: int, player_id_b: int, gw: int = None):
    """LEVEL 2: both breakdowns on the same gameweek at the same cutoff, the
    per-term difference (a - b) ranked by size, the terms that account for
    >= 80% of the gap, and a flag wherever a term is a constant on one side
    against a model value on the other. Same provenance and identity checks."""
    import explain
    try:
        target = int(gw) if gw is not None else _current_gw()
    except RuntimeError as e:
        return {"error": str(e)}
    try:
        df, cutoff, built = _frame_raw()
    except (FileNotFoundError, RuntimeError) as e:
        return {"error": str(e)}
    ra, step, err = _explain_row(df, cutoff, player_id_a, target)
    if err:
        return err
    rb, _, err = _explain_row(df, cutoff, player_id_b, target)
    if err:
        return err
    a, b = explain.breakdown(ra, step), explain.breakdown(rb, step)
    out = {**explain.compare(a, b), "breakdown_a": a, "breakdown_b": b,
           "predictions_as_of_cutoff_gw": cutoff, "stale_by_gameweeks": target - cutoff,
           "frame_built_at": str(built), **_frame_built(cutoff)}
    if not out["reconciles"]:
        out["finding"] = "at least one of the two rows does not reconcile -- see the breakdowns' `finding`; do not present the comparison as sound"
    note = _stale_note(target, cutoff, built)
    if note:
        out["note_stale"] = note
    return out


def _frame_built(cutoff):
    """{built, next_run_expected} for the frame-based tools, from the run the
    sidecar names (falls back to the latest run for the cutoff)."""
    run = _latest_run(gw=cutoff)
    if not run:
        return {"built": None, "next_run_expected": (_dispatch_state() or {}).get("expected_next")}
    m = _run_meta(run)
    return {"built": m["built"], "next_run_expected": m["next_run_expected"], "run_id": m["run_id"],
            "model_version": m["model_version"]}


def _load_pool(gw=None):
    """The production frame on the model volume, sliced to one gameweek in
    optimize's shape -> (pool, cutoff_gw, frame_built_at). gw None = the
    frame's own deadline gameweek (its cutoff); a later gw inside the horizon
    gives that gameweek AS SEEN FROM the cutoff (the stale-by-one case between
    deadlines) -- gw_slice raises ValueError beyond the horizon. Shared by
    optimise() and get_my_xi()."""
    import simulator as sim
    df, cutoff, built = _load_frame()
    pool = sim.gw_slice(df, cutoff if gw is None else int(gw), cutoff=cutoff)
    return pool, cutoff, built


# ------------------------------------------------------- the six-week MIP
def propose_transfers(horizon: int = 6, lock_player_ids: list = None, ban_player_ids: list = None,
                      user_id: int = 1, source: str = "chat"):
    """The six-week transfer plan for the user's OWN squad (transfer_mip via
    simulator.decide_gameweek_mip -- the production decision path; H=6,
    decay 0.45, HIT_COST 4; TWO real solves since 2026-09-18 -- the move plan and
    the hold baseline on the same pools -- typically twenty to sixty seconds,
    occasionally longer). Read through get_my_squad's store, never the table.

    Before any proposal: every one of the fifteen is valued by
    squad_state.sell_price two ways (the MIP's input price vs players_live)
    and the two must agree -- a mismatch is reported as a BUG, and the moved
    prices are listed. The proposal is then APPLIED through
    squad_store.plan_change (the same legality + money path set_my_squad
    uses) as a dry run; a proposal that could not be applied is reported as a
    BUG, not a suggestion. Every proposal is persisted (model_transfer_plans +
    model_transfers). Nothing is written to the squad: apply_with carries the
    set_my_squad arguments (preview first; confirm=true only on the user's
    say-so). Between deadlines the frame belongs to the last deadline: the
    plan drops the gameweek under way and labels predictions as of that
    cutoff (path = "stale-by-one").

    source: 'chat' (the agent; its tool schema has no such argument, so a
    user request is always 'chat') or 'proof' for a maintainer's verification
    run -- proof rows are marked so the track record never starts with
    synthetic entries."""
    if source not in ("chat", "proof", "deadline_run"):
        return {"error": f"source must be chat | proof | deadline_run, got {source!r}"}
    import db_write
    import simulator as sim
    from squad_state import sell_price
    from transfer_mip import DEFAULT_DECAY, HIT_COST

    t0 = time.time()
    try:
        record = squad_store.read_active(user_id)
    except squad_store.SquadStateError as e:
        return {"error": str(e)}
    try:
        current = _current_gw()
    except RuntimeError as e:
        return {"error": str(e)}
    try:
        df, cutoff, built = _load_frame()
    except (FileNotFoundError, RuntimeError) as e:
        return {"error": str(e)}
    all_gws = sorted(int(g) for g in df["gw"].unique())
    if current not in all_gws:
        return {"error": f"the frame on the volume (cutoff GW{cutoff}, gws {all_gws}) has no "
                         f"predictions for the next deadline GW{current}"}
    horizon = int(horizon or 6)
    if not (1 <= horizon <= 6):
        return {"error": f"horizon must be 1..6, got {horizon}"}
    lock = sorted({int(x) for x in (lock_player_ids or [])})
    ban = sorted({int(x) for x in (ban_player_ids or [])})

    doc = record["squad_json"]
    state = squad_store.to_state(doc)
    ft_before = squad_store.free_transfers_at(record, current)
    state.free_transfers = ft_before
    owned = [p["element"] for p in doc["players"]]
    live_rows = _q("""SELECT element, name, position, team, price_tenths, updated_at
                      FROM players_live WHERE element = ANY(%s)""", (owned + lock + ban,))
    live = {r["element"]: r for r in live_rows}
    unpriced = [e for e in owned if e not in live or live[e]["price_tenths"] is None]
    if unpriced:
        return {"error": f"owned element(s) {unpriced} have no current players_live price; "
                         "refusing to value the squad"}
    prices_live = {e: int(live[e]["price_tenths"]) for e in owned}
    names = {e: live[e]["name"] for e in live}
    names.update({p["element"]: p["name"] for p in doc["players"]})

    # ---- valuation assert on all fifteen, and the moved prices, BEFORE any solve
    pool0 = sim.gw_slice(df, current, cutoff=cutoff)
    pool_val = dict(zip(pool0["element"].astype(int), pool0["value"].astype(int)))
    moved, disagree = [], []
    for p in doc["players"]:
        e, bought = p["element"], int(p["purchase_price"])
        mip_in = pool_val.get(e, prices_live[e])          # the MIP's step-0 price (injected owned rows use players_live)
        mip_sell = sell_price(bought, int(mip_in))
        tool_sell = state.element_sell_price(e, prices_live)
        if mip_sell != tool_sell or int(mip_in) != prices_live[e]:
            disagree.append({"player_id": e, "name": p["name"], "purchase": bought,
                             "frame_price": int(mip_in), "players_live_price": prices_live[e],
                             "mip_sell": mip_sell, "tool_sell": tool_sell})
        if prices_live[e] != bought:
            moved.append({"player_id": e, "name": p["name"], "bought": round(bought / 10, 1),
                          "now": round(prices_live[e] / 10, 1), "sells_for": round(tool_sell / 10, 1)})
    if disagree:
        return {"error": "VALUATION MISMATCH -- a bug, not a suggestion: the MIP's input price and "
                         "players_live disagree for owned player(s); no proposal made",
                "bug": True, "details": disagree}

    # ---- the solve (production decision path)
    t1 = time.time()
    try:
        team, transfers, step, eff_h, plan = sim.decide_gameweek_mip(
            df, current, state, pool0, prices_live, all_gws, mode="balanced", horizon=horizon,
            decay=DEFAULT_DECAY, cutoff=cutoff, locked_elements=lock or None,
            banned_elements=ban or None, return_plan=True, hold_compare=True)
    except (RuntimeError, ValueError) as e:
        return {"error": f"the transfer MIP could not produce a plan: {e} (locks/bans infeasible or "
                         "unaffordable?)", "locked": lock, "banned": ban}
    solve_s = round(time.time() - t1, 1)

    # ---- apply through the SAME path set_my_squad uses (dry run, nothing written)
    req = squad_store.proposal_to_request(team)
    involved = sorted(set(owned) | set(req["player_ids"]))
    live2 = {r["element"]: r for r in _q(
        """SELECT element, name, position, team, price_tenths, updated_at
           FROM players_live WHERE element = ANY(%s)""", (involved,))}
    names.update({e: r["name"] for e, r in live2.items()})
    try:
        new_doc, change = squad_store.plan_change(
            record, req["player_ids"], req["captain_id"], req["vice_id"], req["bench_order_ids"],
            current, live2, priced_from=f"players_live as of {max(r['updated_at'] for r in live2.values())}",
            created_by="model_tools.propose_transfers (dry run)", next_deadline_gw=current)
    except ValueError as e:
        return {"error": f"PROPOSAL NOT APPLICABLE -- a bug, not a suggestion: {e}", "bug": True,
                "proposal": {"sells": [names.get(o, o) for o, _ in transfers],
                             "buys": [names.get(i, i) for _, i in transfers]}}
    if change["hits"] != int(step["hits"]) or change["n_transfers"] != int(step["transfers_made"]):
        return {"error": "PROPOSAL ACCOUNTING MISMATCH -- a bug, not a suggestion: the MIP counted "
                         f"{step['transfers_made']} transfer(s) / {step['hits']} hit(s), applying it "
                         f"gives {change['n_transfers']} / {change['hits']}", "bug": True}

    # ---- later steps (indicative: predictions as of the same cutoff, market prices)
    # ONE implementation, used for the move plan and for the hold baseline: two
    # copies of this pairing would be two chances to drift.
    def _later_steps(a_plan):
        out = []
        for st in a_plan[1:]:
            g = int(st["gw"])
            pool_g = sim.gw_slice(df, g, cutoff=cutoff)
            pos_g = dict(zip(pool_g["element"].astype(int), pool_g["position"]))
            val_g = dict(zip(pool_g["element"].astype(int), pool_g["value"].astype(int)))
            nm_g = dict(zip(pool_g["element"].astype(int), pool_g["name"]))
            names.update(nm_g)
            buys = list(int(b) for b in st["buys"])
            pairs = []
            for o in (int(s) for s in st["sells"]):
                m = next((b for b in buys if pos_g.get(b) == pos_g.get(o)), None)
                if m is not None:
                    buys.remove(m)
                pairs.append((o, m))
            out.append({"horizon_step": int(st["horizon_step"]), "gw": g, "hits": int(st["hits"]),
                        "free_transfers": int(st["free_transfers"]),
                        "transfers": [{"out": names.get(o, str(o)), "out_id": o,
                                       "in": names.get(i, str(i)) if i is not None else None, "in_id": i,
                                       "bought_for": (round(val_g[i] / 10, 1) if i in val_g else None)}
                                      for o, i in pairs],
                        "captain": names.get(int(st["captain"]), st["captain"]) if st["captain"] is not None else None})
        return out

    def _rows_for_later(steps):
        return [dict(horizon_step=st["horizon_step"], gw=st["gw"], element_out=t["out_id"],
                     name_out=t["out"], element_in=t["in_id"], name_in=t["in"], sold_for=None,
                     bought_for=(None if t["bought_for"] is None else int(round(t["bought_for"] * 10))),
                     executable=False)
                for st in steps for t in st["transfers"]]

    later = _later_steps(plan)

    # ---- the HOLD BASELINE (2026-09-18, Logs/hold_comparison_log_2026-09-18.md)
    # What doing nothing scores over the same horizon, so a reader can tell a
    # clear gain from a near-tie. "Hold" is THIS gameweek only -- steps 1-5 stay
    # free and the rolled free transfer is earned and spent inside the plan --
    # because nobody decides to stop transferring for six weeks; the question is
    # move now or wait. The XI is re-solved at every step in both plans (the MIP
    # carries a start[i,t] variable per step), so holding is not penalised by a
    # frozen lineup you would have fixed anyway.
    hold_obj = step.get("hold_objective")
    hold_plan = step.get("hold_plan")
    hold_team = step.get("hold_team")
    hold_margin = step.get("hold_margin")
    if hold_team is None and hold_plan is not None:
        # the move solve already held at step 0: the hold IS the move
        hold_team, hold_change, hold_req = team, change, req
    elif hold_plan is not None:
        hold_req = squad_store.proposal_to_request(hold_team)
        try:
            _, hold_change = squad_store.plan_change(
                record, hold_req["player_ids"], hold_req["captain_id"], hold_req["vice_id"],
                hold_req["bench_order_ids"], current, live2,
                priced_from=f"players_live as of {max(r['updated_at'] for r in live2.values())}",
                created_by="model_tools.propose_transfers (hold baseline, dry run)",
                next_deadline_gw=current)
        except ValueError as e:
            return {"error": f"HOLD BASELINE NOT APPLICABLE -- a bug, not a suggestion: {e}",
                    "bug": True}
        if hold_change["n_transfers"] != 0:
            return {"error": "HOLD BASELINE IS NOT A HOLD -- a bug, not a suggestion: applying it "
                             f"gives {hold_change['n_transfers']} transfer(s), expected 0",
                    "bug": True}
    else:
        hold_change = hold_req = None

    # ---- persist the proposal (append-only)
    run = _latest_run(gw=cutoff)
    hold = bool(step.get("hold_applied"))
    xi_pts = squad_store.compare_roles(new_doc["players"], team)["optimal_xi_points"]
    hold_xi_pts = (squad_store.compare_roles(doc["players"], hold_team)["optimal_xi_points"]
                   if hold_team is not None and hold_plan is not None else None)
    header = dict(
        source=source, user_id=user_id, season=record["season"], gw=current,
        squad_version_id=record["version_id"], run_id=(run["run_id"] if run else None),
        config=PRODUCTION_CONFIG, frame_cutoff_gw=cutoff, stale_by_gameweeks=current - cutoff,
        horizon=horizon, effective_horizon=int(eff_h), decay=float(DEFAULT_DECAY), hit_bar=float(HIT_COST),
        locked=lock, banned=ban, status="Optimal", objective=float(step["objective"]),
        n_transfers=change["n_transfers"], hits=change["hits"], hit_cost_points=change["hit_cost_points"],
        free_transfers_before=change["free_transfers_before"], free_transfers_after=change["free_transfers_after"],
        bank_before=change["bank_before"], bank_after=change["bank_after"],
        captain=req["captain_id"], vice=req["vice_id"], predicted_xi_points=float(xi_pts),
        hold_applied=hold, solve_seconds=solve_s, git_sha=db_write.git_sha(),
        note=("stale-by-one: frame cutoff GW%d, plan from GW%d" % (cutoff, current)) if current != cutoff else "fresh frame")
    rows = [dict(horizon_step=0, gw=current, element_out=t["out"], name_out=t["out_name"],
                 element_in=t["in"], name_in=t["in_name"], sold_for=t["sold_for"],
                 bought_for=t["bought_for"], executable=True) for t in change["transfers"]]
    rows += _rows_for_later(later)

    # The HOLD is written FIRST so the move can point at it and nothing is ever
    # UPDATEd -- the table stays append-only. The hold carries NO step-0 row (a
    # hold makes no move this week) and its steps 1-5 as executable=false, the
    # same convention the move plan uses for its later steps.
    hold_later, hold_pid = [], None
    if hold_plan is not None and hold_change is not None:
        hold_later = _later_steps(hold_plan)
        hold_header = dict(
            header, status=str(step.get("hold_status") or "Optimal"),
            objective=(None if hold_obj is None else float(hold_obj)),
            n_transfers=0, hits=0, hit_cost_points=0,
            free_transfers_before=hold_change["free_transfers_before"],
            free_transfers_after=hold_change["free_transfers_after"],
            bank_before=hold_change["bank_before"], bank_after=hold_change["bank_after"],
            captain=hold_req["captain_id"], vice=hold_req["vice_id"],
            predicted_xi_points=(None if hold_xi_pts is None else float(hold_xi_pts)),
            hold_applied=True, solve_seconds=step.get("hold_seconds"),
            plan_kind="hold", paired_proposal_id=None,
            note=("hold baseline for the move proposal written next: hold THIS gameweek only "
                  "(step 0 forced to zero transfers, steps 1-5 free, the rolled free transfer "
                  "earned and spent inside the plan). " + header["note"]
                  + ("; not re-solved -- the move solve already held at step 0, so the forced hold "
                     "is the same plan and the gap is exactly zero"
                     if not step.get("hold_solved", True) else "")))
        hold_pid = db_write.write_proposal(hold_header, _rows_for_later(hold_later))

    header["plan_kind"] = "move"
    header["paired_proposal_id"] = hold_pid
    if step.get("hold_seconds") is not None:
        header["solve_seconds"] = round(max(solve_s - float(step["hold_seconds"]), 0.0), 1)
    proposal_id = db_write.write_proposal(header, rows)

    # ---- the comparison, and the one condition under which it is REFUSED
    # The gap is not merely uncertain while a strength has run off: it is biased,
    # and biased in a known direction. Holding earns a second free transfer at
    # the next gameweek, and if a runaway club sits inside the horizon the hold
    # plan can spend that extra transfer on exactly the fixtures the model has
    # mispriced. So the hold's objective is inflated and the gap understates the
    # case for moving. Reporting it with a caveat would be a warning with the
    # answer attached; the answer is withheld instead. Both plans are still
    # computed and stored -- the record survives, only the verdict waits.
    degraded = _model_degraded_reasons(run) if run else []
    gap_obj = None if hold_obj is None else round(float(step["objective"]) - float(hold_obj), 3)
    gap_this = (None if hold_xi_pts is None else round(float(xi_pts) - float(hold_xi_pts), 2))
    hold_comparison = {
        "stored_as_proposal_id": hold_pid,
        "basis": "hold THIS gameweek only: step 0 forced to zero transfers, steps 1-5 free, the "
                 "rolled free transfer earned and spent inside the plan; the XI is re-solved at "
                 "every step in both plans",
        "move_objective": round(float(step["objective"]), 3),
        "hold_objective": None if hold_obj is None else round(float(hold_obj), 3),
        "move_predicted_xi_points": round(float(xi_pts), 2),
        "hold_predicted_xi_points": None if hold_xi_pts is None else round(float(hold_xi_pts), 2),
        "hold_re_solved": bool(step.get("hold_solved", False)),
        "hold_solve_seconds": step.get("hold_seconds"),
        "refused": bool(degraded),
        "gap_objective": None if degraded else gap_obj,
        "gap_this_gw": None if degraded else gap_this,
    }
    if degraded:
        hold_comparison["refusal"] = (
            "The hold-vs-move gap cannot be measured honestly right now, so it is not reported. "
            "Holding earns a second free transfer at the next gameweek, and a club whose "
            "Dixon-Coles strength has run off sits inside this horizon, so the hold plan can spend "
            "that transfer on fixtures the model has mispriced. The gap is therefore biased IN "
            "FAVOUR OF HOLDING by an unknown amount (KNOWN_ISSUES #25). Both plans were computed "
            "and stored; only the comparison is withheld. Ask again once the model-degraded "
            "condition clears.")
        hold_comparison["condition"] = degraded
    elif gap_obj is None:
        hold_comparison["verdict"] = "no hold baseline: the hold solve returned no plan"
    else:
        hold_comparison["verdict"] = (
            f"moving scores {gap_obj:+.3f} on the six-week objective against holding"
            if gap_obj else "moving and holding score the same on the six-week objective")

    # The rolled-transfer offer: only when the recommendation IS to hold, and
    # never while the detector fires -- that exploration is priced on precisely
    # the gameweek the runaway contaminates.
    if change["n_transfers"] != 0:
        rolled_offer = None
    elif degraded:
        rolled_offer = {
            "offered": False, "refused": True,
            "reason": ("Not while the model is degraded. Exploring what a second free transfer "
                       "opens up next gameweek means pricing that gameweek, and that is exactly "
                       "where the runaway strength sits (KNOWN_ISSUES #25). Ask again once the "
                       "condition clears."),
            "condition": degraded}
    else:
        rolled_offer = {
            "offered": True,
            "question": (f"You are holding, so a second free transfer rolls to GW{current + 1}. "
                         f"Shall I explore what two free transfers at GW{current + 1} opens up?")}

    def m(t):
        return None if t is None else round(t / 10, 1)

    roles = squad_store.roles_from_team(team)
    order = {"CAPTAIN": 0, "VICE": 1, "start": 2, "bench": 3}
    squad_rows = sorted(
        [{"player_id": e, "name": names.get(e, str(e)), "role": r, "bench_order": bo,
          "e_points": round(float(team.loc[team["element"] == e, "e_points"].iloc[0]), 2)}
         for e, (r, bo) in roles.items()],
        key=lambda x: (order[x["role"]], x["bench_order"] or 0, -x["e_points"]))
    return {
        "proposal_id": proposal_id, "source": source,
        "wait_note": "two real MIP solves (the move plan and the hold baseline): typically twenty to sixty seconds, occasionally longer",
        "gw": current, "path": header["note"], "predictions_as_of_cutoff_gw": cutoff,
        "stale_by_gameweeks": current - cutoff, "frame_built_at": str(built), **_frame_built(cutoff),
        "run_id": header["run_id"], "model_version": (_version(run, PRODUCTION_CONFIG) if run else None),
        "squad_version_id": record["version_id"],
        "horizon": horizon, "effective_horizon": int(eff_h), "decay": float(DEFAULT_DECAY),
        "locked": [names.get(e, str(e)) for e in lock], "banned": [names.get(e, str(e)) for e in ban],
        "solve_seconds": solve_s, "total_seconds": round(time.time() - t0, 1),
        "objective": round(float(step["objective"]), 3), "hold_applied": hold,
        "hold_comparison": hold_comparison, "rolled_transfer": rolled_offer,
        "valuation_check": {"all_fifteen_agree": True, "moved_prices": moved,
                            "sell_value": m(state.sell_value(prices_live)), "bank": m(state.bank)},
        "this_deadline": {
            "verdict": ("HOLD -- no transfer" if change["n_transfers"] == 0 else
                        f"{change['n_transfers']} transfer(s), {change['hits']} hit(s)"),
            "transfers": [{"out": t["out_name"], "out_id": t["out"], "sold_for": m(t["sold_for"]),
                           "in": t["in_name"], "in_id": t["in"], "bought_for": m(t["bought_for"])}
                          for t in change["transfers"]],
            "hits": change["hits"], "hit_cost_points": change["hit_cost_points"],
            "free_transfers_before": change["free_transfers_before"],
            "free_transfers_after": change["free_transfers_after"],
            "bank_before": m(change["bank_before"]), "bank_after": m(change["bank_after"]),
            "captain": names.get(req["captain_id"]), "vice": names.get(req["vice_id"]),
            "xi": [r for r in squad_rows if r["role"] != "bench"],
            "bench_in_order": [r for r in squad_rows if r["role"] == "bench"],
            "predicted_xi_points": round(float(xi_pts), 2),
        },
        "later_steps_indicative": later,
        "applied_check": "passed squad_store.plan_change (legality + money conservation) as a dry run",
        "apply_with": {**req, "gw": current, "proposal_id": proposal_id, "confirm": True},
    }


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
    except (FileNotFoundError, RuntimeError) as e:
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
            "frame_built_at": str(frame_mtime), **_frame_built(cutoff),
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


BACKUP_STALE_HOURS = 30.0        # nightly at 03:43Z: one missed run is already a reason


def _backup_status(reasons):
    """The off-site backup's status file (data/live/BACKUP_STATUS.json on the volume,
    written by eval/backup_b2.py on the host). Appends to `reasons` on FAILURE and on
    SILENCE.

    Silence matters as much as failure here, and more than it does for most checks: a
    backup that stopped three weeks ago is indistinguishable from a working one until the
    day it is needed. So a missing file, or a last success older than BACKUP_STALE_HOURS,
    is a reason in its own right -- not merely an absent field. The standing question for
    any alarm is what failure would leave it looking fine, and for a backup the answer is
    'it quietly stopped running', which is exactly what this catches."""
    p = REPO / "data" / "live" / "BACKUP_STATUS.json"
    if not p.exists():
        reasons.append("off-site backup has NEVER run on this volume "
                       "(data/live/BACKUP_STATUS.json missing -- cron not installed?)")
        return None
    import json
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reasons.append("off-site backup status file is unreadable "
                       "(data/live/BACKUP_STATUS.json)")
        return None
    now = datetime.now(timezone.utc)
    out = {k: s.get(k) for k in
           ("status", "started_at", "finished_at", "last_success_at", "duration_s",
            "dump_bytes", "data_bytes", "dump_tables", "dump_key", "data_key",
            "bucket", "row_counts", "error")}
    if s.get("status") == "FAILED":
        reasons.append("off-site backup FAILED: " + str(s.get("error"))[:160] +
                       " (data/live/BACKUP_STATUS.json)")
    last = s.get("last_success_at")
    if not last:
        reasons.append("off-site backup has never SUCCEEDED (only failed attempts recorded)")
    else:
        try:
            age_h = (now - datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                     ).total_seconds() / 3600
            out["last_success_age_hours"] = round(age_h, 1)
            if age_h > BACKUP_STALE_HOURS:
                reasons.append(f"off-site backup has not succeeded for {age_h:.0f}h "
                               f"(nightly expected; over {BACKUP_STALE_HOURS:.0f}h is a "
                               f"stopped backup, not a slow one)")
        except ValueError:
            reasons.append("off-site backup: last_success_at is unparseable")
    return out


CANARY_MAX_MS = 2000.0        # a read this slow is itself a finding


def _tool_surface_check(reasons):
    """Does the agent's own tool surface actually WORK? Reachability and model state were
    both green on 2026-09-18 while every get_prediction call raised UndefinedColumn for
    ~35 minutes, because /health never called a tool. Nothing would have told us; the
    outage was found by a person asking a question.

    So: pick a canary row from the latest run and CALL get_prediction on it -- the same
    entry point the agent uses, not a query that resembles it. ~3 queries, milliseconds,
    no solve and no model load, which is cheap enough for a five-minute probe.

    WHAT FAILURE WOULD LEAVE *THIS* SAYING OK -- answered here, not after:
      * Any other tool. This exercises get_prediction ONLY. set_my_squad, get_my_xi,
        explain_prediction and compare_* are untouched, and propose_transfers cannot be
        probed at all (a 20-40 s solve has no place in a health endpoint).
      * The agent itself. run_agent, the Anthropic call and agent.py's tool dispatch are
        not exercised: a malformed tool SCHEMA would break every conversation while this
        stays green. Catching that needs a real /chat call, which costs money and belongs
        in a separate, much lower-frequency check.
      * The HTTP layer. This runs INSIDE the app process, so a broken route or a
        misconfigured key gate is invisible here (the external monitor covers reachability,
        but not /chat specifically).
      * Correctness. It proves a number came back, never that the number is right.
      * "No row" is partly circular: the canary is chosen FROM the predictions table, so
        an empty table shows up as a missing canary rather than as a missing row. Both are
        reasons, so the case is covered -- but by the first branch, not the second.
      * Staleness. It reads the latest run whatever its age; freshness is last_run's job.
    """
    try:
        run = _latest_run()
        if run is None:
            return {"ok": None, "why": "no successful run yet"}       # last_run already says so
        row = _q("""SELECT element, gw FROM model_predictions
                    WHERE run_id = %s AND config = %s AND e_points IS NOT NULL
                    ORDER BY e_points DESC LIMIT 1""", (run["run_id"], PRODUCTION_CONFIG))
        if not row:
            reasons.append(f"tool surface: run {run['run_id']} has NO usable prediction rows "
                           f"for config {PRODUCTION_CONFIG} -- the agent cannot answer anything")
            return {"ok": False, "why": "no canary row"}
        el, gw = int(row[0]["element"]), int(row[0]["gw"])
        t0 = time.time()
        out = get_prediction(el, gw=gw)
        ms = round((time.time() - t0) * 1000, 1)
        if "error" in out:
            reasons.append(f"tool surface: get_prediction({el}, gw={gw}) returned an error -- "
                           f"{str(out['error'])[:140]}")
            return {"ok": False, "element": el, "gw": gw, "ms": ms, "error": out["error"][:200]}
        preds = out.get("predictions") or []
        if not preds:
            reasons.append(f"tool surface: get_prediction({el}, gw={gw}) returned no prediction "
                           f"row, though the row exists in the table")
            return {"ok": False, "element": el, "gw": gw, "ms": ms}
        ep = preds[0].get("e_points")
        if ep is None or ep != ep:
            reasons.append(f"tool surface: get_prediction({el}, gw={gw}) returned a row whose "
                           f"e_points is not a number")
            return {"ok": False, "element": el, "gw": gw, "ms": ms}
        if ms > CANARY_MAX_MS:
            reasons.append(f"tool surface: get_prediction took {ms:.0f} ms (over "
                           f"{CANARY_MAX_MS:.0f} ms) -- the agent's reads are degrading")
        return {"ok": True, "element": el, "gw": gw, "ms": ms,
                "e_points": round(float(ep), 3),
                "quantiles_computed": bool((out.get("quantiles") or {}).get("computed")),
                "covers": "get_prediction only -- not the agent, not /chat, not other tools"}
    except Exception as e:                                    # noqa: BLE001
        # A probe that crashes the endpoint it probes is worse than no probe, so this is
        # converted into a REASON and never allowed to escape. Swallowing it silently would
        # recreate the exact failure this check exists for.
        reasons.append(f"tool surface: get_prediction RAISED {type(e).__name__}: "
                       f"{str(e).strip()[:160]} -- the agent cannot answer prediction questions")
        return {"ok": False, "raised": f"{type(e).__name__}: {str(e).strip()[:200]}"}


MODEL_DEGRADED_PREFIX = "MODEL DEGRADED:"


def _model_degraded_reasons(run):
    """The MODEL DEGRADED findings of a run (its strict_findings, per config) as health
    reasons: "model degraded (run N, config): <finding>". Pure; the JSONB may arrive as a
    dict or a string; anything unreadable is ignored (no finding, no reason)."""
    sf = run.get("strict_findings")
    if isinstance(sf, str):
        import json
        try:
            sf = json.loads(sf)
        except ValueError:
            return []
    if not isinstance(sf, dict):
        return []
    out = []
    for config, notes in sf.items():
        for n in (notes or []):
            if isinstance(n, str) and n.startswith(MODEL_DEGRADED_PREFIX):
                out.append(f"model degraded (run {run.get('run_id')}, {config}): {n[len(MODEL_DEGRADED_PREFIX):].strip()}")
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

    # the off-site backup (eval/backup_b2.py, host cron 03:43Z): failure AND silence
    # both become reasons, so the existing probe and ntfy path carry them and there is
    # no second alert channel to keep alive.
    freshness["backup"] = _backup_status(reasons)

    # the agent's own tool surface: reachability and model state can both be green
    # while every tool call raises (2026-09-18). This CALLS get_prediction.
    freshness["tool_surface"] = _tool_surface_check(reasons)

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

    # multi-run schedule (decision 5 + the promise check): the dispatcher's
    # state file says what was promised and what landed. A lone nightly
    # failure is visible but not a reason; two consecutive give-ups, any
    # deadline-day give-up, a promised run that did not land, or a dispatcher
    # that stopped ticking all degrade.
    state = _dispatch_state()
    now = datetime.now(timezone.utc)
    if state:
        reasons.extend(_dp().health_reasons(now, state, next_gw=nd[0] if nd else None))
        cur_gw = nd[0] if nd else None
        freshness["schedule"] = {
            "last_tick": state.get("last_tick"),
            "expected_next": state.get("expected_next"),
            "consecutive_nightly_failures": state.get("consecutive_nightly_failures"),
            "last_success": state.get("last_success"),
            "slots_this_gameweek": {sid: {k: v for k, v in s.items() if k in ("kind", "status", "attempts", "run_id", "finished_at")}
                                    for sid, s in (state.get("slots") or {}).items()
                                    if cur_gw is None or int(s.get("gw") or 0) == cur_gw},
        }
    else:
        freshness["schedule"] = None

    # a served build whose model is DEGRADED (a loud, non-fatal detector finding in the
    # run's notes -- live_deadline.MODEL_DEGRADED) degrades health, so the alert probe
    # pushes it with the club and the lambda named (user decision 2026-09-16)
    if last:
        reasons.extend(_model_degraded_reasons(last))

    if last_any and last_any["status"] != "SUCCESS":
        lk = last_any.get("kind") or "deadline"
        if lk in ("nightly", "post_ingest"):
            # decision 5: a single nightly failure logs, does not degrade; the
            # state file's consecutive counter is what degrades
            freshness.setdefault("last_attempt", {})
            freshness["last_attempt"] = {"run_id": last_any["run_id"], "kind": lk, "slot": last_any.get("slot"),
                                         "status": "FAILED", "finished_at": str(last_any["finished_at"])}
        else:
            reasons.append(f"most recent run FAILED (GW{last_any['gw']}, {lk}, "
                           f"{last_any['finished_at']}): {last_any.get('note') or 'see status file'}")

    last_block = None
    if last:
        k = last.get("knowledge")
        if isinstance(k, str):
            import json
            try:
                k = json.loads(k)
            except ValueError:
                k = None
        last_block = dict(run_id=last["run_id"], gw=last["gw"], status=last["status"],
                          recovered=last["recovered"], finished_at=str(last["finished_at"]),
                          kind=last.get("kind") or "deadline", slot=last.get("slot"),
                          build_duration_s=(k or {}).get("duration_s"),
                          freshness=_freshness(last),
                          next_run_expected=(state or {}).get("expected_next"))

    return {"status": "ok" if db_ok and not reasons else "degraded",
            "git_sha": sha, "model_versions": model_versions,
            "data_freshness_by_source": freshness, "db_ok": db_ok,
            "last_run": last_block,
            "reasons": reasons}


# ---------------------------------------------------------------------------
# get_fixtures / get_price_movements (master plan 5.4). Both are ON DEMAND and
# neither runs inside a build: measured 60 ms and 73 ms respectively on the
# droplet. The work is in the pure modules; these are the read paths that feed
# them, and they are what the agent actually calls -- so they are what the
# tests drive (the section 14 rule, three entries deep now).
# ---------------------------------------------------------------------------
# The columns this read needs, split the way the 2026-09-18 incident requires: a READ must
# not assume a column exists. odds_horizon_gws is the case in point -- it is a FRAME column
# and is NOT in db_write.PRED_INSERT_COLS, so it has never existed on model_predictions, and
# naming it unconditionally made every get_fixtures call raise UndefinedColumn. Caught by the
# live dead-on-arrival check, which is the third time in three days for this class.
#
# Its absence is harmless to the meaning: explain.market_priced defaults the horizon to 0, so
# step 0 reads market-priced and steps 1-5 read pure Dixon-Coles -- which is the truth this
# season, and the same default explain.breakdown already applies. The payload says the split
# came from horizon_step rather than implying a column we do not store.
FIXTURE_REQUIRED_COLS = ("element", "gw", "team_lambda", "opp_lambda")
FIXTURE_OPTIONAL_COLS = ("horizon_step", "p_cs", "n_fixtures", "odds_horizon_gws")

FIXTURE_TEAM_ALIASES = {"spurs": "Spurs", "tottenham": "Spurs", "man utd": "Man Utd",
                        "man united": "Man Utd", "manchester united": "Man Utd",
                        "man city": "Man City", "manchester city": "Man City",
                        "forest": "Nott'm Forest", "nottingham forest": "Nott'm Forest",
                        "wolves": "Wolves", "newcastle": "Newcastle", "spurs fc": "Spurs"}


def _resolve_team(name, known):
    """Match a club the way a person types it, or say it is unknown. Never a fuzzy
    best-effort: naming the wrong club's fixtures is worse than declining."""
    if name is None:
        return None, None
    raw = str(name).strip()
    for k in known:
        if k.lower() == raw.lower():
            return k, None
    alias = FIXTURE_TEAM_ALIASES.get(raw.lower())
    if alias and alias in known:
        return alias, None
    hits = [k for k in known if raw.lower() in k.lower()]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, f"{raw!r} matches {sorted(hits)} -- name one"
    return None, f"{raw!r} is not a club in this season's calendar"


def _team_gw_rows(run_id, skel):
    """The per-(team, gameweek) model row. team is not a column on model_predictions, so the
    club comes from the SKELETON's own (element, gw) -> team -- the as-of club the frame was
    built with, not players_live's current club, which would mis-attribute a transferred
    player. The lambdas are constant within (team, gw), so one row per group is exact."""
    available = _table_columns("model_predictions")
    missing_required = [c for c in FIXTURE_REQUIRED_COLS if available and c not in available]
    if missing_required:
        return [], {}
    cols = list(FIXTURE_REQUIRED_COLS) + [c for c in FIXTURE_OPTIONAL_COLS
                                          if not available or c in available]
    rows = _q("SELECT " + ", ".join(cols) + " FROM model_predictions "
              "WHERE run_id = %s AND config = %s", (run_id, PRODUCTION_CONFIG))
    if not rows:
        return [], {}
    team_of = {(int(r["element"]), int(r["GW"])): str(r["team"])
               for r in skel[["element", "GW", "team"]].drop_duplicates().to_dict("records")}
    seen, out, by_gw = set(), [], {}
    for r in rows:
        t = team_of.get((int(r["element"]), int(r["gw"])))
        if t is None:
            continue
        by_gw.setdefault(int(r["gw"]), []).append({"team": t, "team_lambda": r["team_lambda"]})
        key = (t, int(r["gw"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "team": t})
    import pandas as pd
    step_rows = {g: pd.DataFrame(v) for g, v in by_gw.items()}
    return out, step_rows


def get_fixtures(team: str = None, gw: int = None, horizon: int = 5):
    """Fixtures with difficulty from OUR model, as TWO numbers -- not FPL's FDR.

    Difficulty is never one composite: attacking difficulty (how easy is it to score here) and
    defensive difficulty (how easy is a clean sheet) are reported separately, because they
    routinely disagree and the disagreement is the information FDR throws away. The raw
    lambdas travel alongside so nothing is hidden, labelled as PRODUCTS rather than opponent
    ratings, with provenance saying whether each is market-priced or pure Dixon-Coles and a
    runaway warning on any fixture touching a club whose strength ran off.
    """
    import fixtures_tool as ft
    run = _latest_run()
    if run is None:
        return {"error": "no successful pipeline run in the database yet"}
    try:
        import pandas as pd
        skel = pd.read_parquet(ft.SKELETON, columns=ft.SKELETON_COLS)
        age_h = round((time.time() - ft.SKELETON.stat().st_mtime) / 3600.0, 1)
    except Exception as e:                              # noqa: BLE001
        return {"error": f"the fixture calendar ({ft.SKELETON.name}) could not be read: "
                         f"{type(e).__name__}: {str(e)[:200]}. No fixtures can be listed; "
                         "this is a missing FILE, not an empty schedule."}
    cal, n_names = ft.calendar(df=skel)
    if not cal:
        return {"error": "the fixture calendar parsed to nothing; refusing to report fixtures"}
    if n_names == 0:
        return {"error": "no bootstrap snapshot to resolve team ids to names; refusing to "
                         "list fixtures rather than naming opponents by id alone"}
    known = sorted({k[0] for k in cal})
    resolved = None
    if team is not None:
        resolved, err = _resolve_team(team, known)
        if err:
            return {"error": err, "known_teams": known}
    rows, step_rows = _team_gw_rows(run["run_id"], skel)
    if not rows:
        return {"error": f"run {run['run_id']} has no per-team fixture rows to price "
                         "(the prediction table is missing a required column, or the run "
                         "wrote nothing). No difficulty can be reported.",
                "required_columns": list(FIXTURE_REQUIRED_COLS)}
    out = _run_meta(run)
    out.update(ft.build(rows, cal, n_names, team=resolved, gw=gw, horizon=horizon,
                        step_rows_by_gw=step_rows, skeleton_age_hours=age_h))
    return out


def get_price_movements(window_days: int = 7, user_id: int = 1, include_squad: bool = True):
    """Risers and fallers from the poller's stored snapshots, and what your own players sell
    for right now under the asymmetric rule (purchase plus half the rise rounded down; falls
    in full), via squad_state.sell_price -- the same function the transfer MIP uses.

    It reports what HAS happened. The snapshots are burst-sampled rather than daily, so the
    unit is net change between two observations, and both timestamps travel with the answer.
    It does not forecast and must not be read as forecasting.
    """
    import prices_tool as pt
    squad = None
    if include_squad:
        try:
            record = squad_store.read_active(user_id)
            squad = record["squad_json"] if isinstance(record, dict) else None
        except Exception:                               # noqa: BLE001 -- movers still answerable
            squad = None
    try:
        out = pt.movements(window_days=window_days, squad=squad)
    except Exception as e:                              # noqa: BLE001
        return {"error": f"price snapshots could not be read: {type(e).__name__}: "
                         f"{str(e)[:200]}"}
    if include_squad and squad is None and "error" not in out:
        out["my_squad_unavailable"] = ("no active squad version, so only market movers are "
                                       "shown -- selling prices need your purchase prices")
    return out


# ---------------------------------------------------------------- league table (as-of)
LEAGUE_STACK_COLS = ["season", "GW", "team", "was_home", "kickoff_time", "fixture"]
AS_OF_RULE = ("a result counts only if the match finished before the cutoff DAY began -- "
              "dixon_coles.knowable_before, the fit's own training filter and the as-of "
              "guard's truncation, applied unchanged (KNOWN_ISSUES #25)")


def _league_matches(season):
    """The odds archive as the FIT reads it: dixon_coles._load_matches -- the same file
    resolution (the season extension when the frozen archive lacks the season), the same nine
    columns, the same date parser. Not a second reader. Lazy import: dixon_coles brings scipy
    (about 1.4 s once per process) and nothing else of the model stack -- mlflow stays out."""
    import dixon_coles as dc
    return dc._load_matches(predict_season=season)


def _league_calendar(season):
    """That season's rows of the stack + forward skeleton (season_stack.load_stack): the calendar
    the walk-forward derives its cutoff from, and the fixture ids that label gameweeks. An empty
    frame when the season has none."""
    import season_stack
    df = season_stack.load_stack(columns=LEAGUE_STACK_COLS)
    return df[df["season"] == season]


def _odds_provenance(season):
    """The odds pull's provenance sidecar for a season (odds_live_pull_<tag>.provenance.json),
    or None for an archive season priced by football-data's Bet365 columns. Read so the table
    can say WHO priced the matches: for a live season the same B365-named columns hold a
    de-margined multi-book consensus, and the column name alone would attribute it to a
    bookmaker that is not even in the panel."""
    p = REPO / "data" / "history" / f"odds_live_pull_{season.replace('-', '_')}.provenance.json"
    try:
        import json
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def get_league_table(as_of: str = None, team: str = None, form_last_n: int = 5,
                     include_odds_xpts: bool = True):
    """The league table AS OF a cutoff, from match results already on the volume.

    The cutoff is the latest run's by default -- the deadline gameweek's first kickoff, derived
    the way the walk-forward derives it -- so the table holds exactly the results the model knew.
    Every match admitted passes dixon_coles.knowable_before, the one as-of rule (a result counts
    only if the match FINISHED before the cutoff DAY began); fixtures dated before the cutoff
    day that carry no result are named in `results_missing_before_cutoff`, never silently
    dropped and never counted. Per club: position, played/won/drawn/lost, goals, goal
    difference, points, per-game rates, form (most recent LAST), home/away splits, streaks, and
    Bet365's odds-implied expected points over the matches already played -- Bet365's number,
    attributed as such, descriptive only and never a forecast. With `team`, that club's row and
    its results grouped by gameweek (a double is two entries). A club with no admitted result
    comes back null with a reason, not 0-0-0.
    """
    import pandas as pd
    import league_table as lt
    import dixon_coles as dc                    # the ONE rule; lazy, see _league_matches
    run = _latest_run()
    if run is None:
        return {"error": "no successful pipeline run in the database yet"}
    try:
        ms = _league_matches(run["season"])
    except Exception as e:                              # noqa: BLE001
        return {"error": f"the match archive could not be read: {type(e).__name__}: "
                         f"{str(e)[:200]}. No table can be built; this is a missing FILE, not "
                         "an empty season."}
    cal, cal_note = None, None
    try:
        cal = _league_calendar(run["season"])
    except Exception as e:                              # noqa: BLE001 -- labels degrade, table does not
        cal_note = f"the calendar could not be read ({type(e).__name__}: {str(e)[:120]})"

    # -- the cutoff
    if as_of is None:
        cutoff = lt.first_kickoff_by_gw(cal).get(int(run["gw"]))
        if cutoff is None:
            return {"error": f"the calendar has no first kickoff for GW{run['gw']}, so the latest "
                             f"run's cutoff cannot be derived"
                             f"{(' -- ' + cal_note) if cal_note else ''}. Pass as_of explicitly."}
        source = (f"the latest run's cutoff: GW{run['gw']}'s first kickoff, derived from the "
                  f"stack + forward skeleton the way the walk-forward derives cutoff_date")
    else:
        cutoff, err = lt.parse_as_of(as_of)
        if err:
            return {"error": err}
        source = "as_of, as given (read as UTC)"

    # -- the season: the latest one with a fixture dated ON or before the cutoff day. That is
    # the same rule asked one day later, with goals forced present so only its DATE clause acts.
    forced_all = ms.assign(home_goals=0.0, away_goals=0.0)
    dated_by_cutoff_day = dc.knowable_before(forced_all, cutoff + pd.Timedelta(days=1))
    archive_first = ms["date_parsed"].min()
    stamp = f"{cutoff:%Y-%m-%d %H:%M:%S}"
    if not dated_by_cutoff_day.any():
        out = _run_meta(run)
        out.update({"season": None, "table": [], "n_matches_in_table": 0,
                    "as_of": {"cutoff": stamp, "source": source, "rule": AS_OF_RULE,
                              "status": "before_first_match",
                              "archive_first_match": f"{archive_first:%Y-%m-%d}",
                              "statement": (f"as_of {stamp} is before the archive's first match "
                                            f"({archive_first:%Y-%m-%d}); there is no table to "
                                            f"report for that date")}})
        return out
    season = str(ms.loc[dated_by_cutoff_day, "season"].max())
    ms_s = ms[ms["season"] == season]

    # -- THE rule, applied once to admit and once (goals forced present) to name the excluded
    known_mask = dc.knowable_before(ms_s, cutoff)
    dated_mask = dc.knowable_before(ms_s.assign(home_goals=0.0, away_goals=0.0), cutoff)
    known = ms_s[known_mask]
    missing = ms_s[dated_mask & ~known_mask]

    # -- gameweek labels: pair fixture sides in that season's calendar; label only, never filter
    if cal is not None and season != run["season"]:
        try:
            cal = _league_calendar(season)
        except Exception as e:                          # noqa: BLE001
            cal, cal_note = None, f"the calendar could not be read ({type(e).__name__})"
    index = lt.gameweek_index(cal)
    known_l, n_unmapped = lt.label_matches(known, index)
    missing_l, _ = lt.label_matches(missing, index)
    long = lt.long_form(known_l)

    clubs = sorted({lt.fpl_name(x) for x in set(ms_s["home"]) | set(ms_s["away"])})
    resolved = None
    if team is not None:
        resolved, err = _resolve_team(team, clubs)
        if err:
            return {"error": err, "known_teams": clubs}
    n_form = max(1, min(int(form_last_n), lt.MAX_FORM_N))
    rows = lt.table(long, clubs, n_form, include_odds_xpts)

    # -- what the archive knows relative to the cutoff (a statement, never a silent truncation)
    with_result = ms_s[ms_s["home_goals"].notna() & ms_s["away_goals"].notna()]
    latest_result = with_result["date_parsed"].max() if len(with_result) else None
    n_missing = int(len(missing))
    if latest_result is None:
        status = "ok"
        statement = f"no result of {season} is in the archive yet; every club's row is null"
    elif cutoff.normalize() > latest_result + pd.Timedelta(days=1):
        status = "after_latest_result"
        statement = (f"the archive's latest result is dated {latest_result:%Y-%m-%d} and the "
                     f"cutoff is {stamp}; "
                     + (f"{n_missing} fixture(s) dated before the cutoff day carry no result "
                        f"(results_missing_before_cutoff) -- the table is INCOMPLETE as of that "
                        f"date, not merely older" if n_missing else
                        "no fixture is dated between them, so the table is complete as of that "
                        "date"))
    else:
        status = "ok"
        statement = (f"the archive's latest result is dated {latest_result:%Y-%m-%d}; "
                     + (f"{n_missing} fixture(s) dated before the cutoff day carry no result "
                        f"(postponed, or not yet ingested) -- see results_missing_before_cutoff"
                        if n_missing else
                        "every fixture dated before the cutoff day has a result"))

    out = _run_meta(run)
    out.update({
        "season": season,
        "as_of": {"cutoff": stamp, "source": source, "rule": AS_OF_RULE, "status": status,
                  "statement": statement,
                  "archive_first_match": f"{archive_first:%Y-%m-%d}",
                  "season_first_fixture": f"{ms_s['date_parsed'].min():%Y-%m-%d}",
                  "latest_result": None if latest_result is None else f"{latest_result:%Y-%m-%d}"},
        "table": rows if resolved is None else [r for r in rows if r["team"] == resolved],
        "clubs": clubs,
        "n_matches_in_table": int(len(known)),
        "results_missing_before_cutoff": {
            "n": n_missing, "matches": lt.missing_list(missing_l),
            "note": ("fixtures dated before the cutoff day with no result in the archive: "
                     "postponed and still carrying the original date, or played but not yet "
                     "ingested. Not counted. If any is listed, the table is incomplete as of "
                     "this cutoff." if n_missing else
                     "none: every fixture dated before the cutoff day has a result")},
        "gameweek_labels": {
            "source": "the stack + forward skeleton, pairing the two sides of each fixture id",
            "unmapped": n_unmapped,
            "note": (("no calendar rows for this season; every gw is null" + (
                          f" ({cal_note})" if cal_note else "")) if not index else
                     ("labels only: the table's arithmetic never depends on them" +
                      (f"; {n_unmapped} match(es) the calendar could not pair carry gw null"
                       if n_unmapped else "")))},
        "form": {"last_n": n_form, "direction": lt.FORM_DIRECTION},
        "tiebreak": lt.TIEBREAK,
    })
    if season != run["season"]:
        out["season_note"] = (f"as_of falls in {season}, not the latest run's {run['season']}: "
                              f"this is the {season} table")
    odds_meta = lt.odds_attribution(_odds_provenance(season)) if include_odds_xpts else None
    if include_odds_xpts:
        out["odds_xpts"] = odds_meta
    if resolved is not None:
        pos = next((r["position"] for r in rows if r["team"] == resolved), None)
        out["form_detail"] = lt.form_detail(long, resolved, pos, include_odds_xpts,
                                            attribution=odds_meta)
    return out
