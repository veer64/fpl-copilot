# attacking_rates.py
# Empirical-Bayes shrinkage of attacking rates (npxG/90, xA/90).
# Module form for assembly: get_rates() returns (rates, priors) in the exact
# shape assembly.py consumes.
#
# Full investigation (noise measurement, k-gridsearch, robustness tests, finishing
# & price-tier negatives) is in Shrinkage_log — stripped here.
#
# Final rule (verified against the log):
#   shrunk = w*raw + (1-w)*prior, w = n90/(n90+k), n90 = time/90
#   prior  = per-position average rate (over the pooled prior seasons)
#   k      = 2 for FWD npxG (most reliable), 10 for everything else
#   source = understat_season_aggregates.parquet, keyed on stable Understat id
#            (Bug #2: numeric cols are strings -> pd.to_numeric on load)
#
# LEAKAGE FIX (2026-08): rates for a predicted season are now built from PRIOR
# seasons only (pooled), never the season being predicted. The old
# get_rates_2526("2025") used 2025-26's OWN full-season totals to predict 2025-26
# gameweeks — future information leaking backward. The shrinkage method was always
# validated cross-season (Shrinkage_log §4.1: last season's rate predicts next
# season's), so prior-season rates are the design-correct, leak-free input.
# Counts are POOLED across prior seasons (more minutes -> steadier prior, log §8.1).
#
# NOTE: assembly uses the plain SHRUNK rate (npxg90 / xa90). The defender
# shot-volume adjustment (+0.081 for DEF) is a documented future improvement,
# not wired in. Time-decay across the pooled seasons is also future work.

import pandas as pd
import numpy as np

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
MIN_TIME = 450        # ~5 full matches of pooled time for a usable rate

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"

# Understat season label for the sealed test season, used for evaluation ONLY.
EVAL_SEASON = "2025"

# Map a predicted FPL season -> the Understat prior seasons that feed its rates.
# Understat labels by start-year: "2024" == 2024-25. Predicting 2025-26 uses
# 2022,2023,2024 (the three seasons before it).
PRIOR_SEASONS = {
    # Each season is predicted from the THREE Understat seasons before it, never
    # its own -- the leak fixed in LEAKAGE.md #4. Understat labels by start year.
    "2021-22": ["2018", "2019", "2020"],
    "2022-23": ["2019", "2020", "2021"],
    "2023-24": ["2020", "2021", "2022"],
    "2024-25": ["2021", "2022", "2023"],
    "2025-26": ["2022", "2023", "2024"],
}

_NUM_COLS = ["games", "time", "goals", "xG", "assists", "xA", "shots", "key_passes",
             "yellow_cards", "red_cards", "npg", "npxG", "xGChain", "xGBuildup"]


def _k_for(stat, pos_label):
    return 2 if (stat == "npxG" and pos_label == "F") else 10


def _load_understat():
    us = pd.read_parquet(BASE + r"\data\history\understat_season_aggregates.parquet")
    for c in _NUM_COLS:
        us[c] = pd.to_numeric(us[c])      # Bug #2
    return us


def _pool_prior_seasons(us, prior_seasons, pos_label):
    """Pool a player's counts across the prior seasons (one row per player).
    Summing counts (npxG, xA, time, ...) weights naturally by minutes played:
    a 3-season regular gets a stable rate, a one-season player a noisier one."""
    pool = us[(us["understat_season"].isin(prior_seasons))
              & (us["position"].str.contains(pos_label, na=False))].copy()
    if pool.empty:
        return pool
    # sum the count-like columns per player across the prior seasons
    agg = pool.groupby("id", as_index=False).agg(
        time=("time", "sum"),
        npxG=("npxG", "sum"),
        xA=("xA", "sum"),
    )
    return agg


def _shrunk_rate(pooled, pos_label, stat):
    """Per-position shrinkage of `stat`/90 on POOLED prior-season counts.
    Returns (frame[id, shrunk], prior)."""
    pool = pooled[pooled["time"] >= MIN_TIME].copy()
    if len(pool) < 10:
        return None, None
    prior = pool[stat].sum() / pool["time"].sum() * 90        # per-position pooled average
    raw = pool[stat] / pool["time"] * 90
    n90 = pool["time"] / 90
    w = n90 / (n90 + _k_for(stat, pos_label))
    pool["shrunk"] = w * raw + (1 - w) * prior
    return pool[["id", "shrunk"]], prior


METRIC_GLOSSARY = """# Attacking rates — what these metrics mean

This component has NO trained model and NO time dial. It is a shrinkage
calculation: a player's raw attacking rate is pulled toward the average for their
position, and how hard it is pulled depends on how many minutes they have played.
Few minutes -> trust the average. Many minutes -> trust the player.

The rates are built from PRIOR seasons only (2022-24) and used to predict 2025-26.
So the honest question is: do prior-season rates actually predict the next season?
That is what the correlation metrics below measure, scored on the sealed season.

**spearman_npxg** — rank correlation between the shrunk prior-season npxG/90 and
what the player ACTUALLY produced in 2025-26. 1.0 = perfect ordering, 0.0 = no
signal at all. Higher is better. This is the headline metric for this component.
It answers "if I rank players by last season, is that ranking still right?"

**spearman_xa** — the same thing for expected assists. Assists are noisier than
goals, so expect a lower number here. That is normal, not a bug.

**mae_npxg / mae_xa** — typical error in the rate itself, in units of the stat
per 90 minutes. An MAE of 0.05 on npxG/90 means predictions are off by about 0.05
expected non-penalty goals per full match. Lower is better.

**n_eval_players** — how many players had enough minutes in BOTH the prior seasons
and 2025-26 to be scored. Not a quality score. The correlations above are only as
trustworthy as this number is large.

**mean_shrinkage_weight** — the average w in `shrunk = w*raw + (1-w)*prior`.
Close to 1.0 means most players had enough minutes to be trusted on their own
record. Close to 0.0 means nearly everything collapsed to the position average.
Not a quality score, but if this ever crashes, the rates have gone generic.

**n_players / n_players_F / n_players_M / n_players_D** — how many players got a
rate, overall and by position. Tripwires: if these drop sharply, the Understat
join or the minimum-minutes filter broke.

**prior_npxg_F / prior_xa_F / ...** — the position-average fallback rates, one pair
per position. Not quality scores. These are what a player with too few minutes
gets assigned, so they are logged for lineage and sanity-checking.
"""


def _log_to_mlflow(rates, params, metrics, run_name):
    """Log one attacking-rates run. There is no fitted model object here — the
    output rates table IS the artifact."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name, nested=True):
        mlflow.set_tag("component", "attacking_rates")
        # Shows as the Description panel at the top of the run page in the UI.
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
        mlflow.log_text(rates.to_csv(index=False), "shrunk_rates.csv")


def _eval_metrics(rates, priors, us, eval_season, pos_counts, mean_w):
    """Score the shrunk prior-season rates against what actually happened in the
    sealed evaluation season. See METRIC_GLOSSARY for what each metric means."""
    from scipy.stats import spearmanr

    m = {"n_players": float(len(rates)), "mean_shrinkage_weight": float(mean_w)}
    for pos, n in pos_counts.items():
        m[f"n_players_{pos}"] = float(n)
    for pos, d in priors.items():
        m[f"prior_npxg_{pos}"] = float(d["npxg"])
        m[f"prior_xa_{pos}"] = float(d["xa"])

    # Actual production in the evaluation season, same MIN_TIME bar for stability.
    act = us[us["understat_season"] == eval_season].copy()
    if act.empty:
        return m
    act = act.groupby("id", as_index=False).agg(
        time=("time", "sum"), npxG=("npxG", "sum"), xA=("xA", "sum"))
    act = act[act["time"] >= MIN_TIME]
    act["actual_npxg90"] = act["npxG"] / act["time"] * 90
    act["actual_xa90"] = act["xA"] / act["time"] * 90

    j = rates.merge(act[["id", "actual_npxg90", "actual_xa90"]],
                    left_on="understat_id", right_on="id", how="inner")
    j = j.dropna(subset=["npxg90", "xa90", "actual_npxg90", "actual_xa90"])
    if len(j) < 10:
        return m

    m["n_eval_players"] = float(len(j))
    m["spearman_npxg"] = float(spearmanr(j["npxg90"], j["actual_npxg90"]).correlation)
    m["spearman_xa"] = float(spearmanr(j["xa90"], j["actual_xa90"]).correlation)
    m["mae_npxg"] = float(np.abs(j["npxg90"] - j["actual_npxg90"]).mean())
    m["mae_xa"] = float(np.abs(j["xa90"] - j["actual_xa90"]).mean())
    return m


def get_rates(predict_season="2025-26", prior_seasons=None, log_mlflow=False):
    """Produce the assembly inputs for the predicted season, built from PRIOR
    seasons only (leak-free). Returns:
      rates  : DataFrame[understat_id, npxg90, xa90]  (plain shrunk rates)
      priors : {pos_label: {'npxg': float, 'xa': float}}  position-average fallbacks
    log_mlflow=True logs params/metrics/rates as ONE MLflow run (default off, so
    assembly.py and the 38-GW walk-forward stay unchanged and fast).
    """
    if prior_seasons is None:
        prior_seasons = PRIOR_SEASONS[predict_season]

    us = _load_understat()
    npxg_rows, xa_rows, priors = [], [], {}
    pos_counts, w_all = {}, []
    for pos in ["F", "M", "D"]:
        pooled = _pool_prior_seasons(us, prior_seasons, pos)
        if pooled.empty:
            continue
        npxg, npxg_prior = _shrunk_rate(pooled, pos, "npxG")
        xa, xa_prior = _shrunk_rate(pooled, pos, "xA")
        if npxg is None:
            continue
        npxg_rows.append(npxg.rename(columns={"shrunk": "npxg90"}))
        xa_rows.append(xa.rename(columns={"shrunk": "xa90"}))
        priors[pos] = {"npxg": npxg_prior, "xa": xa_prior}
        pos_counts[pos] = len(npxg)
        # Recompute w purely for logging: w = n90 / (n90 + k)
        elig = pooled[pooled["time"] >= MIN_TIME]
        n90 = elig["time"] / 90
        w_all.append(n90 / (n90 + _k_for("npxG", pos)))

    npxg_tbl = pd.concat(npxg_rows)
    xa_tbl = pd.concat(xa_rows)
    rates = npxg_tbl.merge(xa_tbl, on="id", how="outer").rename(columns={"id": "understat_id"})

    if log_mlflow:
        mean_w = float(pd.concat(w_all).mean()) if w_all else 0.0
        _log_to_mlflow(
            rates=rates,
            params={
                "predict_season": predict_season,
                "prior_seasons": ",".join(prior_seasons),
                "eval_season": EVAL_SEASON,
                "min_time_minutes": MIN_TIME,
                "k_fwd_npxg": 2,
                "k_default": 10,
                "shrinkage_rule": "shrunk = w*raw + (1-w)*prior, w = n90/(n90+k)",
                "source": "understat_season_aggregates.parquet",
                "pooling": "counts summed across prior seasons",
            },
            metrics=_eval_metrics(rates, priors, us, EVAL_SEASON, pos_counts, mean_w),
            run_name=f"rates_{predict_season}",
        )

    return rates, priors


# Backward-compat shim: old callers used get_rates_2526("2025").
# Now leak-free — ignores the passed season and builds 2025-26 from prior seasons.
def get_rates_2526(season="2025"):
    return get_rates("2025-26")


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv
    rates, priors = get_rates("2025-26", log_mlflow=log)
    print(f"Attacking rates for 2025-26 (from prior seasons 2022-24): {len(rates)} players")
    print("Priors:", {p: {k: round(v, 3) for k, v in d.items()} for p, d in priors.items()})
    # sanity: top npxG should be elite forwards (rated on their PRIOR-season output)
    us = _load_understat()
    names = us[us["understat_season"].isin(["2022", "2023", "2024"])][["id", "player_name"]].drop_duplicates("id")
    chk = rates.merge(names, left_on="understat_id", right_on="id", how="left")
    print("\nTop npxG/90 (should be elite forwards):")
    print(chk.sort_values("npxg90", ascending=False).head(8)[
        ["player_name", "npxg90", "xa90"]].to_string(index=False))