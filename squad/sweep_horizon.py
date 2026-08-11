"""
FPL Copilot — Horizon sweep

Runs a full season at several planning horizons and reports what each is worth.
Every configuration goes through the same baselines, the same bootstrap, and logs
to the same MLflow experiment, so the numbers are directly comparable.

WHY SWEEP AT ALL
----------------
The horizon is a guess until it is measured, and there is a specific reason to
doubt that longer is better here. The walk-forward decay table shows that among
STARTED players -- the only players a squad actually contains -- Spearman is 0.099
at horizon step 0 and 0.068 at step 5. Both are close to noise.

So the horizon is almost certainly NOT buying better player-ranking. If it earns
anything, it earns it through FIXTURE DIFFICULTY, which is stable and knowable
weeks ahead, and through banking transfers rather than spending them every week.

That is a different mechanism than "predict further ahead", and it is worth
knowing which one is actually operating.

COST
----
Solve time scales badly with horizon: roughly 3s at H=1 rising to 31s at H=6, so a
season costs about 2 minutes at H=1 and 20 minutes at H=6. The full sweep is
around 40 minutes of solving. Baselines are computed ONCE and reused, since they
do not depend on the policy.

READING THE RESULT
------------------
Look for the plateau. If H=3 matches H=6, use 3 -- it is six times faster for the
same points. If the margin keeps climbing to H=6, the horizon is doing real work
and it is worth testing H=8.

Compare margins, not season totals. Both are reported, but the margin over
set-and-forget is the quantity with a confidence interval attached.
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simulator import load_season, simulate_season
from baselines import set_and_forget, hindsight_set_and_forget
from bootstrap import compare_strategies
from experiment import run_experiment

DEFAULT_HORIZONS = (1, 2, 3, 4, 6)


def sweep_horizons(horizons=DEFAULT_HORIZONS, decay=0.85, mode="balanced",
                   gws=None, n_boot=2000, log_mlflow=True, verbose=True):
    """Run a full season at each horizon. Returns a comparison DataFrame.

    H=1 is run under the MIP policy too, not the single-transfer search, so the
    comparison isolates the HORIZON rather than confounding it with the change of
    policy. The single-transfer baseline is reported separately.
    """
    season_h = load_season(horizon_aware=True)

    # Baselines do not depend on the policy, so compute them once.
    if verbose:
        print("Computing baselines (once, shared across all horizons)...")
    saf_total, saf_log = set_and_forget(season_h, mode=mode, gws=gws)
    hind_total, hind_log = hindsight_set_and_forget(season_h, mode=mode, gws=gws)
    if verbose:
        print(f"  set-and-forget {saf_total}, hindsight ceiling {hind_total}\n")

    # The v1 policy, for reference. It reads only cutoff == gw rows, so the
    # horizon-aware frame gives it exactly the same view as the original file.
    if verbose:
        print("Running single-transfer policy (reference)...")
    t0 = time.time()
    s_single, log_single = simulate_season(season_h, mode=mode, gws=gws,
                                           policy="single", verbose=False)
    cmp_single = compare_strategies(log_single["points"].values,
                                    saf_log["points"].values,
                                    label="set_and_forget", n_boot=n_boot)
    rows = [{
        "policy": "single",
        "horizon": 1,
        "total": s_single.total_points,
        "margin": cmp_single["observed_margin"],
        "ci_low": round(cmp_single["ci_low"], 1),
        "ci_high": round(cmp_single["ci_high"], 1),
        "loses_pct": round(100 * cmp_single["share_of_seasons_model_loses"], 1),
        "transfers": int(log_single["n_transfers"].sum()),
        "hits": int(log_single["hit"].sum()),
        "solve_minutes": round((time.time() - t0) / 60, 1),
    }]
    if verbose:
        print(f"  single: {s_single.total_points} "
              f"({cmp_single['observed_margin']:+.0f} vs set-and-forget), "
              f"{rows[0]['solve_minutes']} min\n")

    for H in horizons:
        if verbose:
            print(f"Running MIP horizon {H}...")
        t0 = time.time()
        state, log = simulate_season(season_h, mode=mode, gws=gws, policy="mip",
                                     horizon=H, decay=decay, verbose=False)
        elapsed = (time.time() - t0) / 60

        cmp = compare_strategies(log["points"].values, saf_log["points"].values,
                                 label="set_and_forget", n_boot=n_boot)
        rows.append({
            "policy": "mip",
            "horizon": H,
            "total": state.total_points,
            "margin": cmp["observed_margin"],
            "ci_low": round(cmp["ci_low"], 1),
            "ci_high": round(cmp["ci_high"], 1),
            "loses_pct": round(100 * cmp["share_of_seasons_model_loses"], 1),
            "transfers": int(log["n_transfers"].sum()),
            "hits": int(log["hit"].sum()),
            "solve_minutes": round(elapsed, 1),
        })
        if verbose:
            print(f"  H={H}: {state.total_points} "
                  f"({cmp['observed_margin']:+.0f} vs set-and-forget), "
                  f"{log['n_transfers'].sum()} transfers, "
                  f"{log['hit'].sum()} hit points, {elapsed:.1f} min\n")

        if log_mlflow:
            _log_sweep_run(rows[-1], log, saf_total, hind_total, decay, mode)

    table = pd.DataFrame(rows)
    if verbose:
        _report(table, saf_total, hind_total)
    return table


def _log_sweep_run(row, sim_log, saf_total, hind_total, decay, mode):
    """Log one sweep configuration to MLflow."""
    import mlflow
    from experiment import MLFLOW_URI, MLFLOW_EXPERIMENT, METRIC_GLOSSARY

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=f"sweep_mip_h{row['horizon']}"):
        mlflow.set_tag("component", "simulator")
        mlflow.set_tag("sweep", "horizon")
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params({
            "policy": row["policy"],
            "horizon": row["horizon"],
            "decay": decay,
            "mode": mode,
            "predictions": "walkforward_h6_2526 (as-of, form frozen at cutoff)",
        })
        mlflow.log_metrics({
            "season_total": float(row["total"]),
            "margin_vs_set_and_forget": float(row["margin"]),
            "saf_ci_low": float(row["ci_low"]),
            "saf_ci_high": float(row["ci_high"]),
            "saf_loses_pct": float(row["loses_pct"]),
            "transfers_made": float(row["transfers"]),
            "total_hits": float(row["hits"]),
            "solve_minutes": float(row["solve_minutes"]),
            "baseline_set_and_forget": float(saf_total),
            "baseline_hindsight": float(hind_total),
        })
        mlflow.log_text(sim_log.to_csv(index=False), "decision_log.csv")


def _report(table, saf_total, hind_total):
    print("=" * 78)
    print(f"set-and-forget {saf_total}   hindsight ceiling {hind_total}")
    print("=" * 78)
    print(f"{'policy':<8}{'H':>3}{'total':>8}{'margin':>9}"
          f"{'95% CI':>18}{'loses':>8}{'trf':>6}{'hits':>6}{'min':>7}")
    print("-" * 78)
    for _, r in table.iterrows():
        ci = f"[{r['ci_low']:+.0f}, {r['ci_high']:+.0f}]"
        print(f"{r['policy']:<8}{r['horizon']:>3}{r['total']:>8}"
              f"{r['margin']:>+9.0f}{ci:>18}{r['loses_pct']:>7.1f}%"
              f"{r['transfers']:>6}{r['hits']:>6}{r['solve_minutes']:>7.1f}")

    mip = table[table["policy"] == "mip"]
    if len(mip) > 1:
        best = mip.loc[mip["margin"].idxmax()]
        print(f"\nBest horizon: {int(best['horizon'])} "
              f"({best['margin']:+.0f} vs set-and-forget)")
        cheapest = mip[mip["margin"] >= best["margin"] - 20]
        if len(cheapest):
            c = cheapest.loc[cheapest["solve_minutes"].idxmin()]
            if int(c["horizon"]) != int(best["horizon"]):
                print(f"Within 20 points of best but faster: horizon "
                      f"{int(c['horizon'])} ({c['margin']:+.0f}, "
                      f"{c['solve_minutes']:.1f} min vs {best['solve_minutes']:.1f})")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", type=str, default="1,2,3,4,6")
    ap.add_argument("--decay", type=float, default=0.85)
    ap.add_argument("--gws", type=str, default=None,
                    help="e.g. 1-12 to sweep on a subset first")
    ap.add_argument("--no-mlflow", action="store_true")
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",")]
    gws = None
    if args.gws:
        lo, hi = args.gws.split("-")
        gws = list(range(int(lo), int(hi) + 1))

    t0 = time.time()
    table = sweep_horizons(horizons=horizons, decay=args.decay, gws=gws,
                           log_mlflow=not args.no_mlflow)
    print(f"\nSweep took {(time.time() - t0) / 60:.1f} min")