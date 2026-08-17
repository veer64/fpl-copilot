#!/usr/bin/env python
"""
Degradation test: does perturbation systematically flatter the sharper arm?

Runs baseline against deliberately blurred copies of ITSELF under shared perturbation
draws. Same features, same season, differing in sharpness alone.

PREDICTIONS, fixed before running (see squad/degrade.py for the reasoning):

  Explanation 2 (Instrument B is an artifact): amplification -- perturbed delta minus
  unperturbed delta -- is POSITIVE and INCREASES with lam, and baseline's lift rises
  toward zero as lam grows.

  Explanation 1 (the availability reversal is real): amplification ~0 at every lam.

Every arm sees the identical jitter draw, so the comparison is paired throughout.

Usage:
    uv run python eval/measure_degradation.py --draws 8 --eps 0.25 --shard 0 --nshards 3
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

# Lives in eval/, so the repo root is two levels up -- same convention as
# walkforward.py, which has always sat here.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import degrade  # noqa: E402
import perturb  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
BASE_WF = REPO / "data" / "walkforward_h6_2526.parquet"
LAMBDAS = [0.0, 0.25, 0.5, 0.75]
OUT = REPO / "data"


def run(df, table, tmp):
    perturb.apply_jitter(df, table).to_parquet(tmp, index=False)
    season = load_season(walkforward_path=tmp, horizon_aware=True)
    state, _ = simulate_season(season, **SIM_KW)
    tmp.unlink(missing_ok=True)
    return int(state.total_points)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--eps", type=float, default=0.25)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--unperturbed", action="store_true",
                    help="just the lam=... totals with no jitter, for the baselines")
    args = ap.parse_args()

    base = pd.read_parquet(BASE_WF)
    arms = {lam: degrade.degrade(base, lam) for lam in LAMBDAS}
    tmp = OUT / f".degrade_{args.shard}.parquet"

    if args.unperturbed:
        zero = perturb.jitter_table(list(arms.values()), 0.0, seed=0)
        rows = [{"lam": lam, "total": run(df, zero, tmp)} for lam, df in arms.items()]
        d = pd.DataFrame(rows)
        d.to_parquet(OUT / "degradation_unperturbed.parquet", index=False)
        print(d.to_string(index=False))
        return

    draws = list(range(args.draws))[args.shard::args.nshards]
    print(f"shard {args.shard}/{args.nshards}: draws {draws}", flush=True)

    rows = []
    for j in draws:
        t0 = time.time()
        # Same seed scheme as measure_perturbation, so a draw index means the same
        # noise here as there and the two studies are directly comparable.
        table = perturb.jitter_table(list(arms.values()), args.eps, seed=10_000 + j)
        totals = {lam: run(df, table, tmp) for lam, df in arms.items()}
        for lam, tot in totals.items():
            rows.append({"eps": args.eps, "draw": j, "lam": lam, "total": tot,
                         "delta_vs_base": tot - totals[0.0]})
        print(f"  draw {j}: " + "  ".join(f"lam{lam}={t}" for lam, t in totals.items())
              + f"  ({time.time()-t0:.0f}s)", flush=True)

    pd.DataFrame(rows).to_parquet(OUT / f"degradation_s{args.shard}.parquet", index=False)
    print(f"\nwrote degradation_s{args.shard}.parquet")


if __name__ == "__main__":
    main()
