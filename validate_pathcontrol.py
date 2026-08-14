#!/usr/bin/env python
"""
Validation targets for the path-controlled harness: re-measure two things we already
have season-total answers for, and see whether the intervals tighten.

  availability  season -46, CI [-123, +28]. This is a pure decision-quality (Q1)
                change: better predictions, identical machinery, exposure of only 27
                of 570 squad slots. PREDICTION: a small positive at W=1 with a tight
                interval. A LARGE positive here would be evidence the harness is
                inflating, not that the feature is good.

  wildcard      local +12.3 (W3), season -26.2. Mostly a local (Q2) effect with a
                real compounding tail. PREDICTION: W=3 reproduces roughly +12 with a
                tighter interval than the original sweep.

Run falsify_pathcontrol.py first. Numbers from an unfalsified harness are worthless.

Usage:
    uv run python validate_pathcontrol.py --target availability
    uv run python validate_pathcontrol.py --target wildcard --wildcard-gw 4
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "squad"))

import pathcontrol as pc  # noqa: E402
from simulator import load_season  # noqa: E402

BASE_WF = REPO / "data" / "walkforward_h6_2526.parquet"
AV_WF = REPO / "data" / "walkforward_h6_2526_av.parquet"
ARM_KW = dict(mode="balanced", horizon=3, decay=0.3)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=["availability", "wildcard"], required=True)
    ap.add_argument("--windows", type=int, nargs="*", default=[1, 2, 3, 5])
    ap.add_argument("--wildcard-gw", type=int, default=4,
                    help="wildcard week for the wildcard target (GW2-5 were the "
                         "strongest in the original sweep)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    base_season = load_season(walkforward_path=BASE_WF, horizon_aware=True)
    arm_a = pc.Arm("baseline", base_season, **ARM_KW)

    if args.target == "availability":
        if not AV_WF.exists():
            raise SystemExit(f"missing {AV_WF}")
        arm_b = pc.Arm("availability",
                       load_season(walkforward_path=AV_WF, horizon_aware=True),
                       **ARM_KW)
        expectation = ("season -46, CI [-123, +28]; expect a SMALL positive at W=1. "
                       "A large positive would indict the harness.")
    else:
        arm_b = pc.Arm(f"wildcard_gw{args.wildcard_gw}", base_season,
                       wildcard_gws=[args.wildcard_gw], **ARM_KW)
        expectation = (f"wildcard at GW{args.wildcard_gw}: local +12.3 (W3), "
                       "season -26.2; expect W=3 near +12, tighter.")

    print(f"target: {args.target}\nprior:  {expectation}\n", flush=True)

    print("building reference trajectories...", flush=True)
    log_a, states_a = pc.trajectory(arm_a)
    log_b, states_b = pc.trajectory(arm_b)
    print(f"  {arm_a.name}: {int(log_a.points.sum())}   "
          f"{arm_b.name}: {int(log_b.points.sum())}   "
          f"season delta {int(log_b.points.sum() - log_a.points.sum()):+d}", flush=True)

    frames = []
    for W in args.windows:
        print(f"windowed W={W}...", flush=True)
        frames.append(pc.windowed(arm_a, arm_b, W=W,
                                  ref_log_a=log_a, states_a=states_a,
                                  ref_log_b=log_b, states_b=states_b, verbose=False))
    rows = pd.concat(frames, ignore_index=True)

    out = args.out or REPO / "data" / f"pathcontrol_{args.target}.parquet"
    rows.to_parquet(out, index=False)

    print("\n" + "=" * 96)
    print(f"CROSSOVER WINDOWED COMPARISON — {arm_b.name} vs {arm_a.name}")
    print("=" * 96)
    summary = pc.summarise(rows)
    print(summary.to_string(index=False))
    print("\nmean_delta_per_window is in points per W-gameweek window, so it is NOT")
    print("comparable across W. A season-scale figure would be mean * (38/W), but")
    print("only W=38 actually licenses that extrapolation — see the module docstring.")

    if args.target == "wildcard":
        w3 = summary[summary.W == 3]
        if len(w3):
            print(f"\nW=3 chip-window effect: {w3.mean_delta_per_window.iloc[0]:+.1f} "
                  f"[{w3.ci_low.iloc[0]:+.1f}, {w3.ci_high.iloc[0]:+.1f}] "
                  f"vs original sweep +12.3")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
