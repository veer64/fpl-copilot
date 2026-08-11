"""
FPL Copilot — Decay sweep

Decay is the discount applied to predicted points further ahead in the plan: a
gameweek t steps out contributes decay^t of its predicted points to the objective.
At decay = 0.85 next week is worth 85%; at decay = 1.0 the model treats a point
five weeks away as worth exactly as much as a point this week.

WHY THIS NEEDS MEASURING RATHER THAN ASSUMING
---------------------------------------------
The default 0.85 came from the master plan, not from this data. Two pieces of
evidence from the project point in OPPOSITE directions, which is exactly the
situation a sweep is for.

Pointing towards LESS discounting (higher decay):
  The walk-forward decay table shows all-rows Spearman falling only from 0.715 at
  horizon step 0 to 0.617 at step 5 -- about 3% per step, not 15%. On that basis
  0.85 is far too pessimistic and the planner is ignoring usable information.

Pointing towards MORE discounting (lower decay):
  The horizon sweep found that longer horizons actively HURT: H=2 scored 1996 and
  H=6 scored 1939, while transfers rose from 46 to 57 and hit points from 32 to 76.
  The planner was paying real points to chase distant fixture runs. On that basis
  0.85 is not pessimistic enough.

The resolution is probably that the two measurements are about different things.
All-rows Spearman is dominated by separating "will play" from "will not play",
which stays predictable for weeks. Among STARTED players -- the only kind a squad
contains -- Spearman is 0.099 at step 0 and 0.068 at step 5. Both are near noise.
So the gentle all-rows decay is not evidence that distant predictions are useful
for the decision actually being made.

If that reading is right, LOW decay should win. The sweep will say.

WHAT IS SWEPT
-------------
Decay across several horizons, because the two interact: decay only has anything
to discount when the horizon is longer than one gameweek, and its effect should
grow with horizon. Testing decay at a single horizon would leave that confounded.
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simulator import load_season, simulate_season
from baselines import set_and_forget
from bootstrap import compare_strategies

DEFAULT_DECAYS = (0.5, 0.7, 0.85, 0.95, 1.0)
DEFAULT_HORIZONS = (2, 3)


def sweep_decay(decays=DEFAULT_DECAYS, horizons=DEFAULT_HORIZONS, mode="balanced",
                gws=None, n_boot=2000, log_mlflow=True, verbose=True,
                data_path=None, tag="odds"):
    """Run a full season at each (horizon, decay) pair. Returns a DataFrame.

    data_path : which prediction file to use. Passing an alternative harness
                output makes this an A/B: the same grid run against predictions
                built under different assumptions (for example with and without
                bookmaker odds) isolates what those assumptions are worth.
    tag       : short label recorded on every MLflow run so the two grids can be
                told apart in the UI.
    """
    season_h = load_season(walkforward_path=data_path, horizon_aware=True)

    if verbose:
        print("Computing baselines (once)...")
    saf_total, saf_log = set_and_forget(season_h, mode=mode, gws=gws)
    if verbose:
        print(f"  set-and-forget {saf_total}\n")

    rows = []
    for H in horizons:
        for d in decays:
            if verbose:
                print(f"H={H}, decay={d} ...", end=" ", flush=True)
            t0 = time.time()
            state, log = simulate_season(season_h, mode=mode, gws=gws,
                                         policy="mip", horizon=H, decay=d,
                                         verbose=False)
            elapsed = (time.time() - t0) / 60

            cmp = compare_strategies(log["points"].values, saf_log["points"].values,
                                     label="set_and_forget", n_boot=n_boot)
            row = {
                "horizon": H,
                "decay": d,
                "total": state.total_points,
                "margin": cmp["observed_margin"],
                "ci_low": round(cmp["ci_low"], 1),
                "ci_high": round(cmp["ci_high"], 1),
                "transfers": int(log["n_transfers"].sum()),
                "hits": int(log["hit"].sum()),
                "minutes": round(elapsed, 1),
            }
            rows.append(row)
            if verbose:
                print(f"{state.total_points}  ({cmp['observed_margin']:+.0f}), "
                      f"{row['transfers']} trf, {row['hits']} hit pts, "
                      f"{elapsed:.1f} min")

            if log_mlflow:
                _log_run(row, log, saf_total, mode, tag)

    table = pd.DataFrame(rows)
    if verbose:
        _report(table, saf_total)
    return table


VARIANT_NOTES = {
    "odds": (
        "FIXTURE DIFFICULTY SOURCE: Bet365 odds where published, Dixon-Coles "
        "beyond that.\n\n"
        "Built with ODDS_HORIZON_GWS = 2, so standing at gameweek k the goal "
        "expectations for k, k+1 and k+2 come from bookmaker odds, and k+3 onward "
        "fall back to the Dixon-Coles fit. This is the configuration a live system "
        "would have, since bookmakers do publish the next couple of matchweeks."
    ),
    "dconly": (
        "FIXTURE DIFFICULTY SOURCE: Dixon-Coles only, for every gameweek beyond "
        "the one being played.\n\n"
        "Built with ODDS_HORIZON_GWS = 0. Only the current gameweek uses bookmaker "
        "odds; every future gameweek in the plan is priced purely by the fitted "
        "Dixon-Coles team attack and defence strengths.\n\n"
        "This is the PESSIMISTIC production case: what the system scores if the "
        "odds feed covers only the imminent matchweek, or fails. Compare against "
        "the 'odds' variant at the same horizon and decay -- the gap is exactly "
        "what bookmaker odds are worth for forward planning, and nothing else "
        "differs between the two runs."
    ),
}


def _log_run(row, sim_log, saf_total, mode, tag="odds"):
    import mlflow
    from experiment import MLFLOW_URI, MLFLOW_EXPERIMENT, METRIC_GLOSSARY

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(
            run_name=f"sweep_{tag}_h{row['horizon']}_d{row['decay']}"):
        mlflow.set_tag("component", "simulator")
        mlflow.set_tag("sweep", "decay")
        mlflow.set_tag("data_variant", tag)
        variant_note = VARIANT_NOTES.get(
            tag, f"Prediction data variant: {tag} (no description registered)")
        mlflow.set_tag("mlflow.note.content",
                       f"## Data variant: {tag}\n\n{variant_note}\n\n---\n\n"
                       + METRIC_GLOSSARY)
        mlflow.set_tag("fixture_difficulty_source",
                       "bet365 odds + DC fallback" if tag == "odds"
                       else "dixon-coles only" if tag == "dconly" else tag)
        mlflow.log_params({
            "policy": "mip",
            "horizon": row["horizon"],
            "decay": row["decay"],
            "mode": mode,
            "predictions": f"walkforward_h6 ({tag})",
            "data_variant": tag,
        })
        mlflow.log_metrics({
            "season_total": float(row["total"]),
            "margin_vs_set_and_forget": float(row["margin"]),
            "saf_ci_low": float(row["ci_low"]),
            "saf_ci_high": float(row["ci_high"]),
            "transfers_made": float(row["transfers"]),
            "total_hits": float(row["hits"]),
            "solve_minutes": float(row["minutes"]),
            "baseline_set_and_forget": float(saf_total),
        })
        mlflow.log_text(sim_log.to_csv(index=False), "decision_log.csv")


def _report(table, saf_total):
    print("\n" + "=" * 74)
    print(f"set-and-forget {saf_total}")
    print("=" * 74)
    print(f"{'H':>3}{'decay':>8}{'total':>8}{'margin':>9}{'95% CI':>18}"
          f"{'trf':>6}{'hits':>6}{'min':>7}")
    print("-" * 74)
    for _, r in table.iterrows():
        ci = f"[{r['ci_low']:+.0f}, {r['ci_high']:+.0f}]"
        print(f"{r['horizon']:>3}{r['decay']:>8}{r['total']:>8}"
              f"{r['margin']:>+9.0f}{ci:>18}"
              f"{r['transfers']:>6}{r['hits']:>6}{r['minutes']:>7.1f}")

    best = table.loc[table["margin"].idxmax()]
    print(f"\nBest: horizon {int(best['horizon'])}, decay {best['decay']} "
          f"-> {best['total']} ({best['margin']:+.0f})")

    print("\nTransfers and hits by decay (higher decay = more trust in the future):")
    piv = table.pivot_table(index="decay", values=["transfers", "hits", "total"],
                            aggfunc="mean")
    print(piv.round(1).to_string())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--decays", type=str, default="0.5,0.7,0.85,0.95,1.0")
    ap.add_argument("--horizons", type=str, default="2,3")
    ap.add_argument("--no-mlflow", action="store_true")
    ap.add_argument("--data", type=str, default=None,
                    help="prediction parquet; default is the standard harness output")
    ap.add_argument("--tag", type=str, default="odds",
                    help="label for this data variant, e.g. 'odds' or 'dconly'")
    args = ap.parse_args()

    decays = [float(x) for x in args.decays.split(",")]
    horizons = [int(x) for x in args.horizons.split(",")]

    t0 = time.time()
    sweep_decay(decays=decays, horizons=horizons, log_mlflow=not args.no_mlflow,
                data_path=args.data, tag=args.tag)
    print(f"\nSweep took {(time.time() - t0) / 60:.1f} min")