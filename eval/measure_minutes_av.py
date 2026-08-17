#!/usr/bin/env python
"""
Gate 2: season simulation on the availability-aware walk-forward file.

Unlike the previous override experiment, nothing is rewritten after the fact — the
predictions themselves come from a minutes model that saw availability during
training. Both arms then run through the identical unmodified simulator.

Config: H=3, decay=0.3, mode=balanced, bench_weight=0.2, horizon_aware=True,
baseline 1984, three repeats per arm for determinism.

Usage:
    uv run python eval/measure_minutes_av.py --reps 3
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

# Lives in eval/, so the repo root is two levels up -- same convention as
# walkforward.py, which has always sat here.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

from bootstrap import compare_strategies  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
BASELINE_TOTAL = 1984
PATH_SD = 52.0
COLD = 7

ARMS = {
    "baseline": REPO / "data" / "walkforward_h6_2526.parquet",
    "availability": REPO / "data" / "walkforward_h6_2526_av.parquet",
}


def assembly_metrics():
    """Horizon-0 prediction quality, the house-standard three-band slice."""
    rows = []
    for arm, path in ARMS.items():
        d = pd.read_parquet(path)
        d = d[d.horizon_step == 0].dropna(subset=["e_points", "actual_points"])
        for label, sub in [("all rows", d),
                           ("played (mins>0)", d[d.minutes > 0]),
                           ("started 60+", d[d.minutes >= 60])]:
            rows.append({
                "arm": arm, "subset": label, "n": len(sub),
                "spearman": round(float(spearmanr(sub.e_points, sub.actual_points).statistic), 4),
                "mae": round(float((sub.e_points - sub.actual_points).abs().mean()), 4),
                "bias": round(float((sub.e_points - sub.actual_points).mean()), 4),
            })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--arms", nargs="*", default=list(ARMS))
    args = ap.parse_args()

    missing = [a for a in args.arms if not ARMS[a].exists()]
    if missing:
        raise SystemExit(f"missing walk-forward file(s) for: {missing}")

    print("=" * 88)
    print("ASSEMBLY METRICS, horizon step 0")
    print("=" * 88)
    print(assembly_metrics().to_string(index=False))

    results, logs = [], []
    for arm in args.arms:
        season = load_season(walkforward_path=ARMS[arm], horizon_aware=True)
        for rep in range(args.reps):
            state, log = simulate_season(season, **SIM_KW)
            pts = log["points"].values
            results.append({
                "arm": arm, "rep": rep, "total": int(state.total_points),
                "vs_baseline": int(state.total_points) - BASELINE_TOTAL,
                "gw1_7": float(pts[:COLD].sum()),
                "gw1_7_per_gw": round(float(pts[:COLD].mean()), 2),
                "gw8_plus_per_gw": round(float(pts[COLD:].mean()), 2),
                "transfers": int(log["transfer_in"].notna().sum()),
                "hits": float(log["hit"].sum()),
                "bench_points_left": float(log["bench_points"].sum()),
            })
            log = log.copy()
            log["arm"], log["rep"] = arm, rep
            logs.append(log)
            print(f"{arm:14s} rep{rep}  total={state.total_points:5d}  "
                  f"vs1984={results[-1]['vs_baseline']:+5d}  "
                  f"gw1-7={results[-1]['gw1_7_per_gw']:.1f}/gw  "
                  f"gw8+={results[-1]['gw8_plus_per_gw']:.1f}/gw", flush=True)

    res = pd.DataFrame(results)
    allog = pd.concat(logs)
    res.to_parquet(REPO / "data" / "minutes_av_measurement.parquet", index=False)
    allog.to_parquet(REPO / "data" / "minutes_av_measurement_logs.parquet", index=False)

    print("\n" + "=" * 88)
    print("SEASON TOTALS")
    print("=" * 88)
    print(res.to_string(index=False))
    stab = res.groupby("arm")["total"].agg(["nunique", "min", "max", "count"])
    print("\ndeterminism (nunique should be 1 per arm):")
    print(stab.to_string())

    if len(args.arms) == 2 and stab["nunique"].max() == 1:
        b = allog[(allog.arm == "baseline") & (allog.rep == 0)]["points"].values
        a = allog[(allog.arm == "availability") & (allog.rep == 0)]["points"].values
        r = compare_strategies(a, b, label="baseline")
        print("\n" + "=" * 88)
        print("PAIRED PER-GAMEWEEK BOOTSTRAP, availability vs baseline")
        print("=" * 88)
        print(f"  margin          : {r['observed_margin']:+.0f}")
        print(f"  95% interval    : [{r['ci_low']:+.0f}, {r['ci_high']:+.0f}]")
        print(f"  excludes zero   : {r['ci_excludes_zero']}")
        print(f"  loses in        : {100 * r['share_of_seasons_model_loses']:.1f}% of resampled seasons")
        print(f"  margin / path sd: {r['observed_margin'] / PATH_SD:+.2f}x  (path sd ~{PATH_SD:.0f})")
        print("\nThe bootstrap resamples gameweeks within ONE realised path per arm. It does")
        print("not sample the path lottery, so it understates uncertainty. A margin under")
        print("the path sd is not established by a single run.")

        w = allog[allog.rep == 0].pivot_table(index="gw", columns="arm", values="points")
        w["delta"] = w["availability"] - w["baseline"]
        print(f"\nGW1-7 delta: {w.delta[:COLD].sum():+.0f}   "
              f"GW8-38 delta: {w.delta[COLD:].sum():+.0f}   "
              f"better in {int((w.delta > 0).sum())} gw, worse in {int((w.delta < 0).sum())}")


if __name__ == "__main__":
    main()
