"""
FPL Copilot — Experiment runner (simulator + baselines + bootstrap, logged to MLflow)

One "experiment" here is one full season played under one configuration, scored
against every baseline, with a bootstrap confidence interval on the margin. That
whole package is logged as a single MLflow run.

WHY THIS IS A SEPARATE MODULE
-----------------------------
It cannot live in simulator.py: baselines.py already imports from simulator.py, so
putting the orchestration there would create a circular import. This module sits
above both and imports from each.

WHY MLFLOW HERE AND NOT IN THE OPTIMIZER
----------------------------------------
The optimizer is a deterministic solver -- same input, same answer, nothing
learned. Logging it would add rows with no information. A SEASON SIMULATION is a
real experiment: it has configuration, it produces an outcome, and the outcomes
are comparable across configurations. That is exactly what a tracking server is
for, and it is about to matter, because the transfer-MIP work will produce many
configurations (horizons, decay rates, chip policies) that need comparing.

WHAT COUNTS AS ONE RUN
----------------------
One run = one season under one config. Baselines are logged as METRICS on that
run rather than as separate runs, because the margin is the quantity of interest
and the baselines do not change between configurations. Logging them separately
would clutter the experiment list with 40 identical set-and-forget rows.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simulator import load_season, simulate_season
from baselines import set_and_forget, hindsight_set_and_forget, random_baseline
from bootstrap import compare_strategies, season_total_interval

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-simulator"

REPO_ROOT = Path(__file__).resolve().parent.parent


METRIC_GLOSSARY = """# Season simulation — what these metrics mean

One run here is one full 2025-26 season played under one configuration, scored
through the same code path as every baseline.

## The headline

**season_total** — points scored across the whole season. On its own this number
means nothing; it is only interpretable against the baselines below.

**points_per_gw** — season_total divided by gameweeks played. Useful for comparing
partial runs against full ones.

## The margins (this is what actually matters)

**margin_vs_set_and_forget** — points scored above a manager who picked the same
GW1 squad from the same predictions and then never transferred again.

THIS IS THE HEADLINE COMPARISON. It is the only clean isolation available: same
start, same predictions, same scoring code, and the ONLY difference is whether
transfers happen. So this number is attributable to the transfer machinery and
nothing else.

**saf_ci_low / saf_ci_high** — 95% confidence interval on that margin, from a
block bootstrap over gameweek blocks. If saf_ci_low is above zero, the edge is
real; if the interval straddles zero, luck cannot be ruled out.

**saf_loses_pct** — the share of resampled seasons in which the model scored WORSE
than set-and-forget. This is the number to quote in plain language: "we rebuilt the
season 2000 times and the model lost in X% of them."

**margin_vs_hindsight** — points below a squad chosen with full knowledge of every
player's final season total. Always negative; nobody can achieve the ceiling. It
measures what perfect foresight is worth, and no optimizer improvement can recover
it — only better prediction can.

**margin_vs_random** — points above the mean of many random legal squads.

**random_z_score** — how many standard deviations above the random mean. Beating
random by less than its own spread is not evidence of skill.

## Diagnostics

**cold_start_per_gw / post_cold_start_per_gw** — points per gameweek in GW1-7
versus GW8 onward. The walk-forward model has nothing in-season to learn from
early, and the minutes model cannot see team news, so the opening weeks
underperform. A large gap here points at the cold start, not the optimizer.

**transfers_made** — how many transfers the policy actually used.

**total_hits** — points paid for transfers beyond the free allowance. Zero under
the v1 policy, which never takes a hit by design.

**bench_points_left** — points scored by benched players. Not a loss exactly
(the bench exists for autosubs), but a large number means the bench weight is
mispriced.

**autosubs_used** — how often a blanked starter was replaced automatically.

**vice_rescues** — gameweeks where the captain blanked and the vice was doubled
instead. A high count says something about the captaincy picks, not the vice logic.
"""


def _cold_start_split(log, boundary=8):
    """Points per gameweek before and after the model has in-season data.

    The boundary is 8 because that is where the observed break sits, not because
    of anything principled -- it is a diagnostic, not a hypothesis test.
    """
    early = log[log["gw"] < boundary]["points"]
    late = log[log["gw"] >= boundary]["points"]
    return (float(early.mean()) if len(early) else 0.0,
            float(late.mean()) if len(late) else 0.0)


def run_experiment(season_df=None, mode="balanced", bench_weight=None,
                   gws=None, n_random=50, n_boot=2000, block_length=5,
                   policy="single", horizon=1, decay=0.85,
                   run_name=None, notes="", log_mlflow=True, verbose=True):
    """Run one full experiment: simulate, baseline, bootstrap, log.

    policy  : "single" (v1 search, one transfer, never a hit) or "mip"
              (multi-gameweek transfer MIP).
    horizon : gameweeks planned ahead. Only meaningful for policy="mip".
    decay   : per-gameweek discount on future predicted points.

    Returns (state, sim_log, results dict). Setting log_mlflow=False runs
    everything and skips only the logging, which is useful when iterating.
    """
    if season_df is None:
        season_df = load_season(horizon_aware=(policy == "mip"))

    if policy == "mip" and "cutoff" not in season_df.columns:
        raise ValueError(
            "policy='mip' needs a horizon-aware frame. Load with "
            "load_season(horizon_aware=True) -- otherwise every future gameweek "
            "in the plan would be read from its OWN cutoff, which is a leak."
        )

    if verbose:
        print(f"Running model (policy={policy}, horizon={horizon})...")
    state, sim_log = simulate_season(season_df, mode=mode, gws=gws, verbose=False,
                                     policy=policy, horizon=horizon, decay=decay)

    if verbose:
        print("Running baselines...")
    saf_total, saf_log = set_and_forget(season_df, mode=mode, gws=gws)
    hind_total, hind_log = hindsight_set_and_forget(season_df, mode=mode, gws=gws)
    rand_totals, _ = random_baseline(season_df, n_runs=n_random, gws=gws)

    if verbose:
        print("Bootstrapping...")
    saf_cmp = compare_strategies(sim_log["points"].values, saf_log["points"].values,
                                 label="set_and_forget",
                                 block_length=block_length, n_boot=n_boot)
    hind_cmp = compare_strategies(sim_log["points"].values, hind_log["points"].values,
                                  label="hindsight",
                                  block_length=block_length, n_boot=n_boot)
    total_ci = season_total_interval(sim_log["points"].values,
                                     block_length=block_length, n_boot=n_boot)

    cold, post = _cold_start_split(sim_log)
    n_gw = len(sim_log)

    metrics = {
        "season_total": float(state.total_points),
        "points_per_gw": float(state.total_points) / n_gw,

        "margin_vs_set_and_forget": saf_cmp["observed_margin"],
        "saf_ci_low": saf_cmp["ci_low"],
        "saf_ci_high": saf_cmp["ci_high"],
        "saf_loses_pct": 100 * saf_cmp["share_of_seasons_model_loses"],

        "margin_vs_hindsight": hind_cmp["observed_margin"],
        "hindsight_ci_low": hind_cmp["ci_low"],
        "hindsight_ci_high": hind_cmp["ci_high"],

        "total_ci_low": total_ci["ci_low"],
        "total_ci_high": total_ci["ci_high"],

        "baseline_set_and_forget": float(saf_total),
        "baseline_hindsight": float(hind_total),

        "cold_start_per_gw": cold,
        "post_cold_start_per_gw": post,

        "transfers_made": float(sim_log["transfer_in"].notna().sum()),
        "total_hits": float(sim_log["hit"].sum()),
        "bench_points_left": float(sim_log["bench_points"].sum()),
        "autosubs_used": float(sim_log["n_subs"].sum()),
        "vice_rescues": float((sim_log["doubled_role"] == "vice").sum()),
        "n_gameweeks": float(n_gw),
    }

    if len(rand_totals):
        sd = rand_totals.std() or 1.0
        metrics["baseline_random_mean"] = float(rand_totals.mean())
        metrics["baseline_random_sd"] = float(rand_totals.std())
        metrics["margin_vs_random"] = float(state.total_points - rand_totals.mean())
        metrics["random_z_score"] = float((state.total_points - rand_totals.mean()) / sd)

    params = {
        "mode": mode,
        "bench_weight": "from mode" if bench_weight is None else bench_weight,
        "predictions": "walkforward_2526 (as-of)",
        "transfer_policy": ("single transfer per GW, never takes a hit"
                            if policy == "single"
                            else "multi-GW transfer MIP; solver chooses count and hits"),
        "policy": policy,
        "horizon": horizon if policy == "mip" else 1,
        "decay": decay if policy == "mip" else "n/a",
        "chips_used": "none",
        "sell_price_rule": "exact FPL (half of rise, rounded down)",
        "blank_gw_handling": "owned players injected at e_points=0",
        "gameweeks": "all" if gws is None else f"{min(gws)}-{max(gws)}",
        "n_random_baselines": n_random,
        "bootstrap_resamples": n_boot,
        "bootstrap_block_length": block_length,
        "notes": notes,
    }

    if log_mlflow:
        _log(params, metrics, sim_log, saf_log, hind_log,
             run_name or f"{policy}_h{horizon}_d{decay}")

    if verbose:
        _report(metrics)

    return state, sim_log, {"metrics": metrics, "params": params,
                            "saf_cmp": saf_cmp, "hind_cmp": hind_cmp,
                            "random_totals": rand_totals}


def _log(params, metrics, sim_log, saf_log, hind_log, run_name):
    """Log one experiment to MLflow: config, outcome, and the decision log."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tag("component", "simulator")
        # Shows as the Description panel at the top of the run page in the UI.
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")

        # The decision log is what makes a season total auditable rather than a
        # number to be taken on trust: one row per gameweek, with the squad,
        # the transfer, the captain and the points.
        mlflow.log_text(sim_log.to_csv(index=False), "decision_log.csv")
        mlflow.log_text(saf_log.to_csv(index=False), "baseline_set_and_forget.csv")
        mlflow.log_text(hind_log.to_csv(index=False), "baseline_hindsight.csv")

        # Per-gameweek margin, so a reader can see WHERE the edge came from
        # rather than only that it exists.
        margin = pd.DataFrame({
            "gw": sim_log["gw"].values,
            "model": sim_log["points"].values,
            "set_and_forget": saf_log["points"].values,
            "margin": sim_log["points"].values - saf_log["points"].values,
        })
        mlflow.log_text(margin.to_csv(index=False), "margin_by_gameweek.csv")


def _report(m):
    print(f"\n=== SEASON: {m['season_total']:.0f} points "
          f"({m['points_per_gw']:.1f}/gw) ===")
    print(f"  vs set-and-forget : {m['margin_vs_set_and_forget']:+.0f}  "
          f"[{m['saf_ci_low']:+.0f}, {m['saf_ci_high']:+.0f}]  "
          f"loses {m['saf_loses_pct']:.1f}%")
    print(f"  vs hindsight      : {m['margin_vs_hindsight']:+.0f}  "
          f"[{m['hindsight_ci_low']:+.0f}, {m['hindsight_ci_high']:+.0f}]")
    if "margin_vs_random" in m:
        print(f"  vs random         : {m['margin_vs_random']:+.0f}  "
              f"({m['random_z_score']:.1f} sd)")
    print(f"  cold start GW1-7  : {m['cold_start_per_gw']:.1f}/gw  "
          f"vs {m['post_cold_start_per_gw']:.1f}/gw after")
    print(f"  transfers {m['transfers_made']:.0f}, hits {m['total_hits']:.0f}, "
          f"bench {m['bench_points_left']:.0f}, "
          f"autosubs {m['autosubs_used']:.0f}, "
          f"vice rescues {m['vice_rescues']:.0f}")


if __name__ == "__main__":
    import sys as _sys
    log = "--no-mlflow" not in _sys.argv
    run_experiment(log_mlflow=log,
                   run_name="baseline_v1_single_transfer",
                   notes="v1 policy: 1 transfer/gw, horizon 1, no chips, no hits")