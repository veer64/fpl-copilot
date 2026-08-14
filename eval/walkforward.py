"""
FPL Copilot — Walk-forward harness (horizon-aware)

Distilled from Notebooks/walk_forward_eval.ipynb, which is where the original
strict harness was built. Clears the owed item in the walk-forward log ("distil
the notebook to a .py", master plan section 6.1) and extends it to produce the
multi-gameweek predictions the transfer MIP needs.

WHAT WALK-FORWARD MEANS HERE
----------------------------
At gameweek k: train on everything strictly before k, predict, roll forward. Each
gameweek is predicted the way it would have been predicted live.

The original harness predicted ONLY gameweek k at each step, which is all a
single-gameweek optimizer needs. A rolling-horizon transfer MIP standing at
gameweek k needs predictions for k..k+H-1 as well -- and crucially, those must be
predictions makeable AT k, not predictions that quietly used k+1 and k+2.

THE HORIZON LEAK, AND HOW IT IS AVOIDED
---------------------------------------
Getting this wrong is subtle and would invalidate the whole backtest.

`walkforward_2526.parquet` holds, for each gameweek k, the prediction made with
cutoff k. Handing gameweek k+3's row from that file to a planner standing at
gameweek k looks harmless but is not: that row was produced with cutoff k+3, so
its rolling features (avg_min_last3, starts_last5, and so on) are built from
gameweeks k+1 and k+2 -- which have not been played yet.

The fix is FEATURE FREEZING. At cutoff k, the components are run exactly once, for
gameweek k, and that prediction is carried forward across the horizon. This is not
a shortcut around the leak; it IS the honest answer to "what does the manager know
about gameweek k+3 right now?" -- namely, current form, projected forward.

The assumption is worth stating plainly rather than burying: FORM AS OF GAMEWEEK k
PERSISTS ACROSS THE HORIZON. It is what a human manager implicitly assumes when
planning transfers, and it is the standard approach in rolling-horizon forecasting.
It is also conservative: it cannot invent knowledge, only fail to anticipate change.

WHAT STILL VARIES ACROSS THE HORIZON
------------------------------------
Fixtures. Opponents, home/away and blank gameweeks are all published far in
advance, so a manager at gameweek k genuinely knows who his players face at k+3.
Those come through per-gameweek and correctly drive fixture_scale and clean sheets.

ODDS AVAILABILITY (closed, not merely documented)
-------------------------------------------------
Goal expectations normally come from Bet365 closing odds, but odds for a gameweek
k+3 match are not published at gameweek k. Using them would be a second leak, and
separately would not work in production at all, because a live odds feed simply
returns nothing for fixtures nobody has priced yet.

Both problems have the same answer: use odds where they exist, fall back to the
Dixon-Coles fit where they do not. That is the job the DC model was built for and
has so far barely been used for -- with LAM_BLEND_W = 0.0 it currently influences
only clean sheets, at 20% weight. For unpriced fixtures the blend weight collapses
to pure DC automatically.

ODDS_HORIZON_GWS controls how far ahead odds are assumed available. Prod needs no
equivalent switch: an empty odds feed triggers the same fallback path.

OUTPUT
------
One row per (cutoff, gameweek, player). The `cutoff` column is what makes this
usable by a planner: filter to cutoff == k to get exactly what was knowable at
gameweek k.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "squad"))

import minutes as minutes_mod
import bonus as bonus_mod
import dixon_coles as dc_mod
import attacking_rates as rates_mod
import defensive as def_mod
import assembly

BASE = str(REPO_ROOT)
DEFAULT_HORIZON = 6

# How many gameweeks ahead bookmakers are assumed to have priced. Beyond this the
# harness falls back to the pure Dixon-Coles fit, which is exactly what PROD does
# naturally when an odds feed returns nothing for an unpriced fixture -- so there
# is no separate production path to write later.
#
# Set to None to use every odd present in the historical file. That is faster and
# harmless at horizon 1, but for a multi-gameweek horizon it is a mild leak: odds
# for a gameweek k+3 match are not published at gameweek k, and they encode team
# news the manager could not have had.
#
# The exact number varies by bookmaker and is not worth guessing at precisely --
# it is a parameter so the ablation sweep can measure what the odds are actually
# worth versus the DC fallback.
ODDS_HORIZON_GWS = 0

GOAL_PTS = assembly.GOAL_PTS
CS_PTS = assembly.CS_PTS
LEAGUE_AVG_LAMBDA = assembly.LEAGUE_AVG_LAMBDA
TEAM_MAP = assembly.TEAM_MAP
DC_BASE = assembly.DC_BASE


# ---------------------------------------------------------------------------
# Assembly with components supplied by the caller
# ---------------------------------------------------------------------------
def assemble(df, cw, mins_out, rates, priors, fixtures, dc_out,
             bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean, gws=None):
    """assembly.build_predictions() with the component calls lifted out, so the
    harness can supply per-cutoff components. Logic is otherwise identical."""
    v = df[(df["season"] == "2025-26") & (df["position"] != "AM")].copy()
    skel = v[["element", "GW", "name", "position", "team", "minutes", "total_points"]].copy()
    skel["element"] = pd.to_numeric(skel["element"], errors="coerce").astype(int)
    skel = skel.rename(columns={"GW": "gw", "total_points": "actual_points"})
    if gws is not None:
        skel = skel[skel["gw"].isin(gws)]
    skel = skel.merge(cw[["element", "player_id", "understat_id"]], on="element", how="left")
    asm = (skel.sort_values(["element", "gw"]).groupby(["element", "gw"], as_index=False)
           .agg({"name": "first", "position": "first", "team": "first", "minutes": "sum",
                 "actual_points": "sum", "player_id": "first", "understat_id": "first"}))

    asm = asm.merge(mins_out[["element", "gw", "p_start", "p60", "e_minutes"]],
                    on=["element", "gw"], how="left")

    rates_clean = rates.sort_values("npxg90", ascending=False).drop_duplicates(
        "understat_id", keep="first").copy()
    asm["understat_id_num"] = pd.to_numeric(asm["understat_id"], errors="coerce")
    rates_clean["understat_id"] = pd.to_numeric(rates_clean["understat_id"], errors="coerce")
    asm = asm.merge(rates_clean, left_on="understat_id_num", right_on="understat_id",
                    how="left", suffixes=("", "_r"))
    pos_lab = {"FWD": "F", "MID": "M", "DEF": "D", "GK": "D"}

    def fb(row, stat):
        return priors.get(pos_lab.get(row["position"], "M"), priors["M"])[stat]

    nn = asm["npxg90"].isna()
    nx = asm["xa90"].isna()
    if nn.any():
        asm.loc[nn, "npxg90"] = asm[nn].apply(lambda r: fb(r, "npxg"), axis=1)
    if nx.any():
        asm.loc[nx, "xa90"] = asm[nx].apply(lambda r: fb(r, "xa"), axis=1)
    assert asm.duplicated(["element", "gw"]).sum() == 0

    fx = fixtures.copy()
    fx["home"] = fx["home"].map(lambda t: TEAM_MAP.get(t, t))
    fx["away"] = fx["away"].map(lambda t: TEAM_MAP.get(t, t))
    home = fx[["home", "match_date", "lam_home", "lam_away", "p_home_cs"]].copy()
    home.columns = ["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]
    away = fx[["away", "match_date", "lam_away", "lam_home", "p_away_cs"]].copy()
    away.columns = ["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]
    tf = pd.concat([home, away], ignore_index=True)
    vv = df[df["season"] == "2025-26"].copy()
    vv["match_date"] = pd.to_datetime(vv["kickoff_time"]).dt.date
    tgd = vv[["team", "GW", "match_date"]].drop_duplicates().rename(columns={"GW": "gw"})
    tf["match_date"] = pd.to_datetime(tf["match_date"]).dt.date
    tgd["match_date"] = pd.to_datetime(tgd["match_date"]).dt.date
    tf = tf.merge(tgd, on=["team", "match_date"], how="left")
    asm = asm.merge(
        tf[["team", "gw", "team_lambda", "opp_lambda", "p_cs"]].drop_duplicates(["team", "gw"]),
        on=["team", "gw"], how="left")

    asm = asm.merge(dc_out[["player_id", "gw", "p_dc_hit"]], on=["player_id", "gw"], how="left")
    need = asm["p_dc_hit"].isna()
    asm.loc[need, "p_dc_hit"] = asm.loc[need, "position"].map(DC_BASE).fillna(0.10)
    asm = (asm.sort_values("p_dc_hit", ascending=False)
           .drop_duplicates(["element", "gw"], keep="first")
           .sort_values(["element", "gw"]).reset_index(drop=True))

    a = asm.copy()
    a["minutes_frac"] = (a["e_minutes"] / 90.0).clip(0, 1)
    a["fixture_scale"] = (a["team_lambda"] / LEAGUE_AVG_LAMBDA).fillna(1.0).clip(0.5, 2.0)
    a["e_goals"] = a["npxg90"] * a["minutes_frac"] * a["fixture_scale"]
    a["e_assists"] = a["xa90"] * a["minutes_frac"] * a["fixture_scale"]
    a["pts_goals"] = a["e_goals"] * a["position"].map(GOAL_PTS)
    a["pts_assists"] = a["e_assists"] * 3
    a["p_60plus"] = a["p_start"] * a["p60"]
    a["p_play_any"] = a["p_start"] + (1 - a["p_start"]) * 0.30
    a["pts_appear"] = a["p_60plus"] * 2 + (a["p_play_any"] - a["p_60plus"]).clip(lower=0) * 1
    a["pts_cs"] = a["p_cs"] * a["position"].map(CS_PTS) * a["p_60plus"]
    a["pts_dc"] = a["p_dc_hit"] * 2 * a["minutes_frac"]
    a["e_points_core"] = (a["pts_appear"] + a["pts_goals"] + a["pts_assists"]
                          + a["pts_cs"] + a["pts_dc"])

    bps_input = pd.DataFrame({
        "goals_scored": a["e_goals"], "assists": a["e_assists"],
        "clean_sheets": a["p_cs"] * a["p_60plus"], "minutes": a["e_minutes"],
        "is_def": (a["position"] == "DEF").astype(int),
        "is_mid": (a["position"] == "MID").astype(int),
        "is_gk": (a["position"] == "GK").astype(int),
        "saves": 0, "yellow_cards": 0, "red_cards": 0, "goals_conceded": 0,
        "penalties_missed": 0, "own_goals": 0})
    a["pred_bps"] = bps_model.predict(bps_input[BPS_FEATURES])
    a["exp_bonus"] = bps_to_bonus(a["pred_bps"].values) * a["minutes_frac"]

    # Normalised PER GAMEWEEK -- must match assembly.py exactly, and matters far
    # more here. Scaling by the mean across the whole assembled batch would make
    # gameweek k's prediction depend on which of k+1..k+5 were computed alongside
    # it, so the same gameweek would score differently at different horizons.
    gw_mean = a.groupby("gw")["exp_bonus"].transform("mean")
    a["exp_bonus"] = np.where(gw_mean > 0,
                              a["exp_bonus"] * bonus_mean / gw_mean,
                              a["exp_bonus"])
    a["e_points"] = a["e_points_core"] + a["exp_bonus"]
    return a


# ---------------------------------------------------------------------------
# Feature freezing
# ---------------------------------------------------------------------------
def _freeze_forward(pred_at_k, target_gws, key_cols, value_cols):
    """Carry a gameweek-k prediction forward across the horizon.

    THIS IS THE LEAK FIX. Rolling features for gameweek k+3 would be built from
    gameweeks k+1 and k+2, which have not been played at cutoff k. Rather than
    recompute them (impossible without seeing the future) the gameweek-k values
    are projected forward, which encodes the explicit assumption that form as of
    gameweek k persists.

    Conservative by construction: it cannot invent knowledge, only fail to
    anticipate change.
    """
    frames = []
    for g in target_gws:
        f = pred_at_k[key_cols + value_cols].copy()
        f["gw"] = g
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------
def walk_forward(cutoffs=None, horizon=1, verbose=True, save_path=None):
    """Run the walk-forward harness.

    horizon=1 reproduces the original strict harness exactly: at each cutoff k,
    predict only gameweek k.

    horizon=H additionally predicts gameweeks k+1..k+H-1 with features FROZEN at
    k, which is what a rolling-horizon transfer planner standing at k can honestly
    know. The extra gameweeks are nearly free -- the expensive part is retraining
    the components once per cutoff, which happens either way.

    Returns a frame with a `cutoff` column: filter to cutoff == k for the view a
    planner had at gameweek k.
    """
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    cw = pd.read_csv(BASE + r"\data\history\player_id_crosswalk_final.csv")

    v25 = df[df["season"] == "2025-26"].copy()
    v25["kick"] = pd.to_datetime(v25["kickoff_time"])
    # Two different boundaries, and confusing them is a real bug.
    #   gw_start = FIRST kickoff of a gameweek -> the moment the manager must have
    #              decided, so it is the training cutoff.
    #   gw_end   = LAST kickoff of a gameweek -> the moment every match in it has
    #              begun, so it is the right edge for "odds are published through
    #              gameweek N".
    # Using gw_start for the odds edge silently excluded every Saturday and Sunday
    # fixture of the target gameweek, because the boundary landed on its Friday
    # night kickoff.
    gw_start = v25.groupby("GW")["kick"].min().sort_index()
    gw_end = v25.groupby("GW")["kick"].max().sort_index()
    all_gws = sorted(gw_start.index.astype(int))

    if cutoffs is None:
        cutoffs = all_gws

    # Constant across cutoffs: prior-season rates do not vary by gameweek.
    rates, priors = rates_mod.get_rates("2025-26")

    # Defensive is internally walk-forward and produces every gameweek in one
    # call. Its gameweek-k row trains only on gameweeks before k, so the k rows
    # are honest; future gameweeks get k's value via freezing below.
    dc_all = def_mod.get_dc_2526()

    out = []
    for k in cutoffs:
        t0 = time.time()
        cutoff_date = gw_start.loc[k].tz_localize(None)
        targets = [g for g in all_gws if k <= g < k + horizon]

        # Components trained/refit with cutoff k.
        m_k = minutes_mod.get_minutes(up_to_gw=k, predict_gws=[k])
        bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = \
            bonus_mod.get_bonus_model(up_to_gw=k)
        # Odds are treated as published only ODDS_HORIZON_GWS gameweeks ahead of
        # the cutoff; beyond that the fixture falls back to pure Dixon-Coles.
        if ODDS_HORIZON_GWS is None:
            odds_until = None
        else:
            last_priced = min(k + ODDS_HORIZON_GWS, max(all_gws))
            # gw_end, not gw_start: "priced through gameweek N" must include every
            # match IN gameweek N, not just its earliest kickoff.
            odds_until = gw_end.loc[last_priced].tz_localize(None)

        f_k = dc_mod.get_fixtures(cutoff_date=cutoff_date,
                                  odds_available_until=odds_until)

        # Freeze minutes and defensive forward across the horizon.
        if len(targets) > 1:
            m_k = _freeze_forward(
                m_k, targets,
                key_cols=["element", "name", "position"],
                value_cols=["p_start", "p60", "e_minutes"])
            dc_k = _freeze_forward(
                dc_all[dc_all["gw"] == k], targets,
                key_cols=["player_id", "position"],
                value_cols=["p_dc_hit"])
        else:
            dc_k = dc_all[dc_all["gw"] == k]

        a_k = assemble(df, cw, m_k, rates, priors, f_k, dc_k,
                       bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean,
                       gws=targets)
        a_k["cutoff"] = k
        a_k["horizon_step"] = a_k["gw"] - k
        out.append(a_k)

        if verbose:
            print(f"  cutoff GW{k:2d}: {len(a_k):5d} rows across "
                  f"{len(targets)} gameweeks, {time.time() - t0:.1f}s")

    result = pd.concat(out, ignore_index=True)

    # Provenance stamp. minutes.py defaults to availability=True since 2026-08-13, and
    # rebuilding this file with that default silently moves the season baseline from
    # 1984 to 1938 with nothing erroring -- the same shape as the stale-odds incident,
    # where source read ODDS_HORIZON_GWS = 0 while the parquet had been built at 2.
    # Stamping it means a file always describes how it was made. Absence of the column
    # means the file predates the stamp, hence pre-adoption. See KNOWN_ISSUES.md #10.
    result["minutes_availability"] = bool(
        getattr(minutes_mod, "AVAILABILITY_DEFAULT", True))

    if save_path:
        result.to_parquet(save_path, index=False)
        if verbose:
            print(f"\nSaved -> {save_path}")

    return result


def validate(wf):
    """Report the house-standard three-band slice on the horizon-0 rows.

    Only horizon_step == 0 is comparable to the original harness: those are the
    genuine as-of predictions. Later steps are frozen projections and will score
    worse by construction, which is itself worth measuring.
    """
    from scipy.stats import spearmanr

    v = wf.dropna(subset=["actual_points", "e_points"]).copy()
    v["actual_points"] = pd.to_numeric(v["actual_points"], errors="coerce")

    print("=== By horizon step ===")
    print(f"{'step':<6}{'N':>8}{'Spearman':>10}{'MAE':>8}")
    print("-" * 32)
    for step in sorted(v["horizon_step"].unique()):
        s = v[v["horizon_step"] == step]
        print(f"{step:<6}{len(s):>8}"
              f"{spearmanr(s['e_points'], s['actual_points']).correlation:>10.3f}"
              f"{(s['e_points'] - s['actual_points']).abs().mean():>8.2f}")

    base = v[v["horizon_step"] == 0]
    print(f"\n=== Horizon step 0 (comparable to the strict harness) ===")
    print(f"Rows: {len(base)}   (strict harness: 29,338)")
    print(f"Spearman: {spearmanr(base['e_points'], base['actual_points']).correlation:.3f}"
          f"   (strict: 0.715)")
    print(f"MAE:      {(base['e_points'] - base['actual_points']).abs().mean():.2f}"
          f"   (strict: 1.15)")

    print("\n=== Three-band slice (house standard, step 0) ===")
    bands = {
        "All rows": base["actual_points"].notna(),
        "Played (>0 min)": base["minutes"] > 0,
        "Started (60+)": base["minutes"] >= 60,
    }
    print(f"{'Slice':<18}{'N':>7}{'Spearman':>10}{'MAE':>8}")
    print("-" * 43)
    for label, m in bands.items():
        s = base[m]
        print(f"{label:<18}{len(s):>7}"
              f"{spearmanr(s['e_points'], s['actual_points']).correlation:>10.3f}"
              f"{(s['e_points'] - s['actual_points']).abs().mean():>8.2f}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    ap.add_argument("--cutoffs", type=str, default=None,
                    help="comma-separated gameweeks, e.g. 10,20,30 (default: all)")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    cutoffs = None
    if args.cutoffs:
        cutoffs = [int(x) for x in args.cutoffs.split(",")]

    out = args.out
    if out is None and cutoffs is None:
        out = BASE + rf"\data\walkforward_h{args.horizon}_2526.parquet"

    t0 = time.time()
    wf = walk_forward(cutoffs=cutoffs, horizon=args.horizon, save_path=out)
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min — {len(wf)} rows")
    validate(wf)