#!/usr/bin/env python
"""
Instrument B runner: paired season comparison under prediction perturbation.

Each (eps, draw) is one job: jitter both arms with the SAME draw, simulate both,
record the paired difference. Shardable so several processes can share the work --
`--shard i --nshards n` takes every n-th job, which keeps the split deterministic and
independent of how far any other shard has got.

Usage:
    uv run python eval/measure_perturbation.py --draws 25 --eps 0.25
    uv run python eval/measure_perturbation.py --draws 8 --eps 0.001 0.1 0.5 --shard 0 --nshards 3
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

import perturb  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
ARMS = {
    "baseline": REPO / "data" / "walkforward_h6_2526.parquet",
    "availability": REPO / "data" / "walkforward_h6_2526_av.parquet",
}
OUT = REPO / "data"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draws", type=int, default=25)
    ap.add_argument("--eps", type=float, nargs="*", default=[0.25])
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    raw = {k: pd.read_parquet(p) for k, p in ARMS.items()}
    frames = list(raw.values())

    jobs = [(e, j) for e in args.eps for j in range(args.draws)]
    jobs = jobs[args.shard::args.nshards]
    print(f"shard {args.shard}/{args.nshards}: {len(jobs)} jobs", flush=True)

    rows = []
    for i, (eps, draw) in enumerate(jobs):
        t0 = time.time()
        # Seed depends on the draw index only, so shard boundaries cannot change
        # which noise a draw sees, and both arms share it.
        table = perturb.jitter_table(frames, eps, seed=10_000 + draw)
        totals = {}
        for arm, df in raw.items():
            jittered = perturb.apply_jitter(df, table)
            path = OUT / f".perturb_{arm}_{args.shard}.parquet"
            jittered.to_parquet(path, index=False)
            season = load_season(walkforward_path=path, horizon_aware=True)
            state, _log = simulate_season(season, **SIM_KW)
            totals[arm] = int(state.total_points)
            path.unlink(missing_ok=True)
        rows.append({"eps": eps, "draw": draw,
                     "arm_a": totals["baseline"], "arm_b": totals["availability"],
                     "delta": totals["availability"] - totals["baseline"]})
        print(f"  [{i+1}/{len(jobs)}] eps={eps:<6g} draw={draw:<3d} "
              f"A={totals['baseline']:5d} B={totals['availability']:5d} "
              f"D={rows[-1]['delta']:+5d}  ({time.time()-t0:.0f}s)", flush=True)

    tag = args.tag or f"s{args.shard}"
    out = OUT / f"perturbation_{tag}.parquet"
    pd.DataFrame(rows).to_parquet(out, index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
