# defensive.py
# Defensive Contribution: P(hit DC threshold) per player-match.
# Module form for assembly: get_dc_2526() runs the walk-forward over every gameweek
# and returns the full-season dc_out that assembly.py joins on (player_id, gw).
#
# Full investigation (within-vs-cross-season persistence, Bug #7, base-rate drift,
# 4-fix comparison, CDM investigation, team-style feature) is in the DC log.
#
# Final config (verified against the log):
#   source : core_insights_matchstats.parquet, PL-only (-prem-), 2025-26 only
#            (Bug #7: 2024-25 recording inconsistent — unusable)
#   DEF/MID: LightGBM (150/15, min_child 40), WALK-FORWARD retrained per gameweek
#            (base rate drifts unpredictably -> must retrain on recent data = live op)
#   FWD    : no model — 0.4% hit rate, flat FWD_BASE_RATE (log §9)
#   features: rolling within-season, shift-then-roll (no leakage)
#
# Output: DataFrame[season, player_id, gw, position, p_dc_hit, dc_hit]

import pandas as pd
import numpy as np
import lightgbm as lgb

BASE = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
SEASON = "2025-2026"
FWD_BASE_RATE = 0.005
FEATURES = ["roll_dc90_3c", "roll_dc90_5c", "roll_hit_5", "roll_mins_3"]

# COUNT SOURCE (gated). ADOPTED 2026-08-31: default "fpl_official" -- a
# JUDGEMENT CALL, not a passed pre-registration. The pre-registered test of
# this swap FAILED on unsliced Brier (Logs/dc_source_swap_prereg.md, commits
# cd199a3/8e653f2/24ec9c0); the exploratory re-measurement changed the
# endpoint after that fail and is not citable as a pass
# (Logs/dc_source_swap_exploratory_log.md). Adoption is on CORRECTNESS: FPL
# awards the points, and where the sources disagree core-insights is wrong by
# definition (the real discrepancy is FPL counting MORE tackles on 17.3% of
# matches; #21's original one-signed evidence was a goalkeeper artefact).
#   "fpl_official"  -- the native FPL defensive_contribution count from the
#                      season stack (the awarded count itself).
#   "core_insights" -- the pre-adoption source, retained so the frozen
#                      2025-26 records stay reproducible bit-for-bit.
DC_SOURCE = "fpl_official"

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"


def _mk():
    return lgb.LGBMClassifier(n_estimators=150, num_leaves=15, min_child_samples=40,
                              learning_rate=0.05, random_state=42, verbose=-1)


def _raw_rows_core():
    """The current source: core-insights matchstats, PL-only, 2025-26 only."""
    ms = pd.read_parquet(BASE + "/data/history/core_insights_matchstats.parquet")
    ms_pl = ms[ms["match_id"].str.contains("-prem-", na=False)].copy()
    for c in ["tackles", "interceptions", "recoveries", "blocks", "clearances", "minutes_played"]:
        ms_pl[c] = pd.to_numeric(ms_pl[c], errors="coerce")

    gwref = pd.read_parquet(BASE + "/data/history/core_insights_gameweek_stats.parquet")
    pos_map = gwref[["id", "position"]].drop_duplicates("id").set_index("id")["position"]
    ms_pl["position"] = ms_pl["player_id"].map(pos_map)

    ms_pl["cbit"]  = ms_pl["clearances"] + ms_pl["blocks"] + ms_pl["interceptions"] + ms_pl["tackles"]
    ms_pl["cbirt"] = ms_pl["cbit"] + ms_pl["recoveries"]
    ms_pl["dc_metric"] = np.where(ms_pl["position"] == "Defender", ms_pl["cbit"], ms_pl["cbirt"])
    ms_pl["dc_threshold"] = np.where(ms_pl["position"] == "Defender", 10, 12)
    ms_pl["dc_hit"] = (ms_pl["dc_metric"] >= ms_pl["dc_threshold"]).astype(int)
    played = ms_pl[ms_pl["minutes_played"] >= 1].copy()
    return played[played["season"] == SEASON]


def _raw_rows_official(season="2025-26"):
    """The ADOPTED source (2026-08-31, judgement call -- see DC_SOURCE): the NATIVE
    FPL defensive_contribution count from the season stack -- the awarded count
    itself, not a reconstruction, because FPL being definitionally right is the
    premise. Per (player, GW, fixture) rows; element == core player_id; same
    thresholds, GKs excluded exactly as the core pipeline excludes them (the
    model never predicts goalkeepers). Season-parametric: the writers' season
    format ("2025-26", "2026-27")."""
    from season_stack import stack_path
    df = pd.read_parquet(stack_path(), columns=["season", "element", "GW", "fixture",
                                                "position", "minutes", "defensive_contribution"])
    d = df[df["season"] == season].copy()
    d["position"] = d["position"].map({"DEF": "Defender", "MID": "Midfielder", "FWD": "Forward"})
    d = d[d["position"].notna()]                       # GK out, as in the core pipeline
    d = d.rename(columns={"element": "player_id", "GW": "gw", "minutes": "minutes_played"})
    d["dc_metric"] = pd.to_numeric(d["defensive_contribution"], errors="coerce")
    d["dc_threshold"] = np.where(d["position"] == "Defender", 10, 12)
    d["dc_hit"] = (d["dc_metric"] >= d["dc_threshold"]).astype(int)
    return d[d["minutes_played"] >= 1].copy()


def _build_features(season="2025-26"):
    """Raw per-match rows from the gated source, then the SHARED target +
    rolling-feature construction (identical code either way). `season` is in
    the writers' format; the core path serves 2025-26 only (its files cover
    nothing else -- defensive.SEASON), the official path any stack season."""
    if DC_SOURCE == "core_insights":
        assert season == "2025-26", \
            f"core_insights DC features exist for 2025-26 only, not {season!r} (Bug #7 / file coverage)"
        played = _raw_rows_core()
    elif DC_SOURCE == "fpl_official":
        played = _raw_rows_official(season)
    else:
        raise ValueError(f"unknown DC_SOURCE {DC_SOURCE!r}")

    d = played.sort_values(["player_id", "gw"]).reset_index(drop=True)
    d["dc_per90"] = d["dc_metric"] / d["minutes_played"].clip(lower=1) * 90
    grp = d.groupby("player_id")
    rp = lambda c, w, h: grp[c].transform(lambda s: s.shift(1).rolling(w, min_periods=1).agg(h))
    d["roll_dc90_3"] = rp("dc_per90", 3, "mean")
    d["roll_dc90_5"] = rp("dc_per90", 5, "mean")
    d["roll_hit_5"]  = rp("dc_hit", 5, "mean")
    d["roll_mins_3"] = rp("minutes_played", 3, "mean")
    d["roll_dc90_3c"] = d["roll_dc90_3"].clip(upper=30)
    d["roll_dc90_5c"] = d["roll_dc90_5"].clip(upper=30)
    return d


def _predict_gw(frame, target_gw, recency_weight=False):
    """Walk-forward P(DC hit) for one gameweek, trained on all prior gameweeks."""
    out = []
    for pos in ["Defender", "Midfielder", "Forward"]:
        te = frame[(frame["gw"] == target_gw) & (frame["position"] == pos)].dropna(subset=FEATURES).copy()
        if len(te) == 0:
            continue
        if pos == "Forward":
            te["p_dc_hit"] = FWD_BASE_RATE
        else:
            prior = frame[(frame["gw"] < target_gw) & (frame["position"] == pos)].dropna(subset=FEATURES)
            if len(prior) < 150:
                te["p_dc_hit"] = prior["dc_hit"].mean() if len(prior) else 0.13
            else:
                m = _mk()
                if recency_weight:
                    w = 0.9 ** (target_gw - prior["gw"].values)
                    m.fit(prior[FEATURES], prior["dc_hit"], sample_weight=w)
                else:
                    m.fit(prior[FEATURES], prior["dc_hit"])
                te["p_dc_hit"] = m.predict_proba(te[FEATURES])[:, 1]
        out.append(te)
    if not out:                       # early gameweeks: no rolling features yet
        return None
    return pd.concat(out)[["season", "player_id", "gw", "position", "p_dc_hit", "dc_hit"]]


METRIC_GLOSSARY = """# Defensive Contribution model — what these metrics mean

This component predicts the chance a player hits the defensive-contribution
threshold in a match (CBIT >= 10 for defenders, CBIRT >= 12 for midfielders and
forwards), which is worth 2 FPL points.

This component is ALREADY walk-forward. It retrains per gameweek on all prior
gameweeks of the season, because the base rate drifts unpredictably. So one run
here covers the whole 38-gameweek sweep, not a single fit.

Metrics are reported BY POSITION on purpose. Forwards get no model at all — they
receive a flat 0.5% rate, because they essentially never hit the threshold.
Pooling all positions together would flatter the model by mixing in that easy,
almost-always-zero group. Defenders and midfielders are where the real work is.

**brier_def / brier_mid** — how good the probabilities are for that position.
Take the predicted chance, subtract what happened (1 = hit, 0 = missed), square it,
average. 0 is perfect. Lower is better. These are the headline metrics.

**base_rate_def / base_rate_mid / base_rate_fwd** — how often the threshold was
ACTUALLY hit, as a fraction. Not quality scores. These are the bar to beat:
always guessing the base rate scores a Brier of about rate x (1 - rate). If a
brier_* is not clearly below its matching base-rate benchmark, the model is adding
nothing over a naive constant.

**benchmark_brier_def / benchmark_brier_mid** — that naive bar, computed for you.
Compare brier_def against benchmark_brier_def directly. Lower than it = real skill.

**brier_fwd** — included for completeness only. Forwards use a flat constant, so
this measures nothing about the model.

**n_predicted** — player-gameweek rows predicted. A tripwire: if this drops
sharply, the Core-Insights join or the rolling-feature filter broke.

**n_gameweeks** — how many gameweeks produced predictions. Expect fewer than 38:
the earliest gameweeks have no rolling history yet and are dropped by design.

**n_def / n_mid / n_fwd** — rows per position. More tripwires.
"""


def _per_gw_table(dc_out):
    """Per-gameweek Brier and actual hit rate. Logged as a CSV artifact because the
    base-rate DRIFT across the season is the whole reason this component retrains."""
    dc_out = dc_out.copy()
    dc_out["sq_err"] = (dc_out["p_dc_hit"] - dc_out["dc_hit"]) ** 2
    t = (dc_out.groupby(["gw", "position"], as_index=False)
         .agg(brier=("sq_err", "mean"), hit_rate=("dc_hit", "mean"), n=("dc_hit", "size")))
    return t.sort_values(["gw", "position"]).reset_index(drop=True)


def _log_to_mlflow(dc_out, params, metrics, run_name):
    """Log one DC run. There is no single fitted model — this component trains one
    model per position per gameweek — so the per-gameweek table IS the artifact."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name, nested=True):
        mlflow.set_tag("component", "defensive")
        # Shows as the Description panel at the top of the run page in the UI.
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
        mlflow.log_text(_per_gw_table(dc_out).to_csv(index=False), "per_gameweek_brier.csv")


def _eval_metrics(dc_out):
    """Score by position. See METRIC_GLOSSARY — pooling positions would flatter the
    model, because forwards are a near-constant zero group with no model at all."""
    m = {"n_predicted": float(len(dc_out)),
         "n_gameweeks": float(dc_out["gw"].nunique())}

    short = {"Defender": "def", "Midfielder": "mid", "Forward": "fwd"}
    for pos, tag in short.items():
        p = dc_out[dc_out["position"] == pos]
        if len(p) == 0:
            continue
        m[f"n_{tag}"] = float(len(p))
        m[f"brier_{tag}"] = float(((p["p_dc_hit"] - p["dc_hit"]) ** 2).mean())

        # The naive bar: always guess the base rate. Brier = rate * (1 - rate).
        rate = float(p["dc_hit"].mean())
        m[f"base_rate_{tag}"] = rate
        if tag in ("def", "mid"):
            m[f"benchmark_brier_{tag}"] = rate * (1 - rate)

    return m


def get_dc_2526(recency_weight=False, log_mlflow=False, season="2025-26"):
    """Run the walk-forward over every gameweek and return the full-season DC table.
    Returns DataFrame[season, player_id, gw, position, p_dc_hit, dc_hit].
    (Name kept for its call sites; season-parametric since the 2026-08-31
    adoption.) log_mlflow=True logs params/metrics/per-gameweek table as ONE
    MLflow run (default off, so assembly.py stays unchanged and fast)."""
    d = _build_features(season)
    preds = [_predict_gw(d, g, recency_weight) for g in sorted(d["gw"].unique())]
    preds = [p for p in preds if p is not None]      # drop early gameweeks with no features
    if not preds:
        # A live season with no feature-bearing gameweek yet (rolling features
        # are shift(1)-based, so GW1 alone predicts nothing): the honest cold
        # start is the EMPTY typed frame -- assembly then prices DC at the
        # position base rates, and live postflight reports it.
        return pd.DataFrame(columns=["season", "player_id", "gw", "position", "p_dc_hit", "dc_hit"])
    dc_out = pd.concat(preds, ignore_index=True)

    if log_mlflow:
        _log_to_mlflow(
            dc_out=dc_out,
            params={
                "season": SEASON,
                "recency_weight": recency_weight,
                "model_cfg": "lgbm 150/15 mcs40 lr0.05",
                "positions_modelled": "Defender, Midfielder",
                "fwd_treatment": f"flat {FWD_BASE_RATE} base rate, no model",
                "min_prior_rows_for_model": 150,
                "features": ",".join(FEATURES),
                "walk_forward": "yes — retrained per gameweek on all prior gameweeks",
                "thresholds": "CBIT>=10 (DEF), CBIRT>=12 (MID/FWD)",
                "source": "core_insights_matchstats.parquet (PL only)",
            },
            metrics=_eval_metrics(dc_out),
            run_name="defensive_walkforward",
        )

    return dc_out


# --- shared walk-forward DC-hits path (2026-08-19, KNOWN_ISSUES #15) --------
# Both walk-forward writers MUST get their p_dc_hit frames from here. Before
# this existed, walkforward.py wired get_dc_2526() while walkforward_season.py
# passed an EMPTY frame -- so the canonical files (built by the season writer)
# silently priced defensive contribution at position BASE RATES (max 0.136)
# instead of the per-player model (max ~0.80). Fourth member of the
# silent-fallback family (#10, #13, #14).
#
# NAMING TRAP: "DC" is overloaded in this repo. p_dc_hit / this module =
# DEFENSIVE CONTRIBUTION (the 2025-26 scoring rule). dixon_coles.py = the
# team-GOALS model. The two are unrelated; read "DC" in logs with care.

# Seasons the defensive-contribution rule exists for (2025-26 onward). The
# writers' season format ("2025-26"), not this module's SEASON constant.
# 2026-27 added at the 2026-08-31 adoption -- the rule is in force this
# season; leaving it out zeroed every defender's DC term.
DC_RULE_SEASONS = {"2025-26", "2026-27"}
_DC_HITS_CACHE = {}


def _asof_rows(hist):
    """One feature row per player AS OF a cutoff: the statistics a row at the
    cutoff gameweek would carry under the shift-then-roll construction --
    means over the player's last 3 / 5 PLAYED rows strictly before the cutoff.
    Position is the player's most recent row. Stable sort on (player, gw[,
    fixture]) so the window is deterministic through a double gameweek."""
    keys = ["player_id", "gw"] + (["fixture"] if "fixture" in hist.columns else [])
    h = hist.sort_values(keys, kind="stable")
    g = h.groupby("player_id", sort=False)
    last = g.tail(1)[["player_id", "position"]].set_index("player_id")
    t3 = (g.tail(3).groupby("player_id")
          .agg(roll_dc90_3=("dc_per90", "mean"), roll_mins_3=("minutes_played", "mean")))
    t5 = (g.tail(5).groupby("player_id")
          .agg(roll_dc90_5=("dc_per90", "mean"), roll_hit_5=("dc_hit", "mean")))
    out = last.join(t3).join(t5).reset_index()
    out["roll_dc90_3c"] = out["roll_dc90_3"].clip(upper=30)
    out["roll_dc90_5c"] = out["roll_dc90_5"].clip(upper=30)
    return out


def _score_cutoff(d, cutoff_gw, recency_weight=False):
    """P(DC hit) for EVERY player with a played row before `cutoff_gw`, scored on
    his as-of feature row. Training is exactly _predict_gw's: per position, all
    feature-bearing rows with gw < cutoff_gw; the < 150-row cold start and the
    forward constant are unchanged. Only the SCORED POPULATION differs from the
    pre-2026-09-11 path: it is no longer the rows that PLAYED the cutoff gameweek."""
    hist = d[d["gw"] < cutoff_gw]
    if hist.empty:
        return None
    feats = _asof_rows(hist)
    out = []
    for pos in ["Defender", "Midfielder", "Forward"]:
        te = feats[feats["position"] == pos].copy()
        if te.empty:
            continue
        if pos == "Forward":
            te["p_dc_hit"] = FWD_BASE_RATE
        else:
            prior = hist[hist["position"] == pos].dropna(subset=FEATURES)
            if len(prior) < 150:
                te["p_dc_hit"] = prior["dc_hit"].mean() if len(prior) else 0.13
            else:
                m = _mk()
                if recency_weight:
                    m.fit(prior[FEATURES], prior["dc_hit"], sample_weight=0.9 ** (cutoff_gw - prior["gw"].values))
                else:
                    m.fit(prior[FEATURES], prior["dc_hit"])
                te["p_dc_hit"] = m.predict_proba(te[FEATURES])[:, 1]
        out.append(te)
    if not out:
        return None
    return pd.concat(out, ignore_index=True)[["player_id", "position", "p_dc_hit"]]


def get_dc_hits(season, cutoff_gw, target_gws):
    """p_dc_hit rows for one walk-forward cutoff, frozen across the horizon.

    Returns DataFrame[player_id, position, p_dc_hit, gw] -- the player's
    estimate AS OF `cutoff_gw` repeated for each target gameweek (form as of
    the cutoff persists; the same freeze the other components use).

    AS-OF SCORING (2026-09-11, KNOWN_ISSUES #22 / LEAKAGE.md item 6). Until then
    this read `get_dc_2526()[gw == cutoff_gw]`: rows that exist only for
    players who PLAYED the cutoff gameweek (the source keeps minutes >= 1 rows).
    In the backtest that selected the model rows on the realised appearance;
    live, the cutoff gameweek is unplayed and the lookup was EMPTY at every
    deadline, so production priced every row at DC_BASE. Now every player with
    a played row before the cutoff is scored on his as-of feature row
    (_score_cutoff); the label never enters and no cutoff-gameweek count does.
    THIS IS A MODEL CHANGE, NOT A REPAIR: the old backtest term was conditioned
    on an outcome a deadline cannot know, so the fixed term will not reproduce
    the record files built before this date. get_dc_2526 / _predict_gw remain
    as the component-evaluation (MLflow) path and the legacy static build.

    Empty for a cutoff with no played rows yet (GW1): assembly then falls back
    to position base rates, the honest cold start. Pre-rule seasons return the
    empty-but-typed frame; the caller also zeroes the term via dc_enabled."""
    cols = ["player_id", "position", "p_dc_hit", "gw"]
    if season not in DC_RULE_SEASONS:
        return pd.DataFrame(columns=cols)
    # Caches keyed by (source, season[, cutoff]) -- the season-less key defect
    # flagged in #21 was fixed at the 2026-08-31 adoption; the cutoff key is new
    # with as-of scoring. eval/asof_reconstruction.py clears this dict around a
    # truncated build, so both kinds of key live in the one dict.
    fk = ("features", DC_SOURCE, season)
    if fk not in _DC_HITS_CACHE:
        _DC_HITS_CACHE[fk] = _build_features(season)
    hk = ("hits", DC_SOURCE, season, int(cutoff_gw))
    if hk not in _DC_HITS_CACHE:
        _DC_HITS_CACHE[hk] = _score_cutoff(_DC_HITS_CACHE[fk], int(cutoff_gw))
    at_k = _DC_HITS_CACHE[hk]
    if at_k is None or len(at_k) == 0:
        return pd.DataFrame(columns=cols)
    frames = [at_k.assign(gw=g) for g in target_gws]
    return pd.concat(frames, ignore_index=True)[cols]


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv
    dc_out = get_dc_2526(log_mlflow=log)
    print(f"DC predictions for 2025-26: {len(dc_out)} player-gameweeks")
    print("\nTop P(DC hit) — should be defensive specialists:")
    print(dc_out.sort_values("p_dc_hit", ascending=False).head(6).to_string(index=False))