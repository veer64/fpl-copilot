#!/usr/bin/env python
"""
Hit-margin sweep: require predicted gain > 4 + m before the MIP will pay a hit.

Implemented by raising the DECISION price of a hit in the objective
(`transfer_mip.HIT_COST`) while leaving the real FPL penalty alone --
`scoring.HIT_COST` is a separate constant, so every arm is still charged exactly 4
points per extra transfer when the gameweek is scored. Only the solver's willingness
to buy one changes.

WHY THIS IS NOT THE FAILED WILDCARD THRESHOLD — and where it still might be
--------------------------------------------------------------------------
The wildcard remedy put a minimum-gain floor on EVERY transfer, which killed the
low-gain budget-enabling legs of combination moves. This is a different constraint:
it prices the aggregate hit count, so combination moves that fit inside the free
allowance are untouched, and a combination move that needs a hit is priced as a
bundle rather than leg by leg.

That is not a complete escape. A two-transfer move costing one hit is still blocked
as a unit, and if the two legs were only jointly affordable, raising the price
removes both. `transfers` and `n_hit_moves` are reported per arm precisely so that
collapse is visible rather than inferred.

Usage:
    uv run python sweep_hit_margin.py --margins 0 1 2 4 8
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "squad"))

import scoring  # noqa: E402
import transfer_mip  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
BASELINE_TOTAL = 1984
PATH_SD = 52.0

ARMS = {
    "baseline": REPO / "data" / "walkforward_h6_2526.parquet",
    "availability": REPO / "data" / "walkforward_h6_2526_av.parquet",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--margins", type=float, nargs="*", default=[0, 1, 2, 4, 8])
    ap.add_argument("--arms", nargs="*", default=list(ARMS))
    args = ap.parse_args()

    assert scoring.HIT_COST == 4, "the real FPL penalty must stay at 4"
    original = transfer_mip.HIT_COST
    rows = []
    try:
        for arm in args.arms:
            season = load_season(walkforward_path=ARMS[arm], horizon_aware=True)
            for m in args.margins:
                transfer_mip.HIT_COST = 4.0 + m
                state, log = simulate_season(season, **SIM_KW)
                # Charged at the true rate regardless of the decision price.
                assert scoring.HIT_COST == 4
                pts = log["points"].values
                rows.append({
                    "arm": arm, "margin": m, "decision_price": 4.0 + m,
                    "total": int(state.total_points),
                    "vs_1984": int(state.total_points) - BASELINE_TOTAL,
                    "hit_points": float(log["hit"].sum()),
                    "n_hit_moves": int((log["hit"] > 0).sum()),
                    "transfers": int(log["n_transfers"].sum()),
                    "gw1_7": float(pts[:7].sum()),
                    "bench_points_left": float(log["bench_points"].sum()),
                })
                print(f"{arm:14s} m={m:<4g} total={rows[-1]['total']:5d}  "
                      f"hits={rows[-1]['hit_points']:5.0f}  "
                      f"transfers={rows[-1]['transfers']:3d}  "
                      f"hit_moves={rows[-1]['n_hit_moves']}", flush=True)
    finally:
        transfer_mip.HIT_COST = original

    df = pd.DataFrame(rows)
    df.to_parquet(REPO / "data" / "hit_margin_sweep.parquet", index=False)

    print("\n" + "=" * 92)
    print("HIT-MARGIN SWEEP (whole sweep, no cherry-picking)")
    print("=" * 92)
    print(df.to_string(index=False))

    print("\nspread within each arm, against path sd ~%.0f:" % PATH_SD)
    for arm, g in df.groupby("arm"):
        rng = g.total.max() - g.total.min()
        best = g.loc[g.total.idxmax()]
        print(f"  {arm:14s} range {rng:3d} pts ({rng / PATH_SD:.2f}x path sd), "
              f"best m={best.margin:g} at {best.total}, m=0 at "
              f"{int(g[g.margin == 0].total.iloc[0])}")


if __name__ == "__main__":
    main()
