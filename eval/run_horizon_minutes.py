"""Builds the per-step horizon minutes predictions for one season, every cutoff, steps 0-5, with the lever set stamped per row (squad/horizon_minutes.py). Writes data/horizon/hmin_{season}_{levers}.parquet atomically; skip-if-exists. Component-level only -- no assembly, no simulation. Result of record: Logs/horizon_minutes_log.md.

Usage: uv run python eval/run_horizon_minutes.py --season 2024-25 --levers refit
"""
import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
import horizon_minutes as hm  # noqa: E402
import walkforward_season as wfs_mod  # noqa: E402  (train_seasons_for, LABELLED)

OUT = REPO / "data" / "horizon"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--levers", default="refit", help="comma-separated, e.g. refit,suspensions")
    ap.add_argument("--cutoffs", default=None, help="comma-separated subset (default: all)")
    a = ap.parse_args()
    levers = tuple(a.levers.split(","))
    tr = wfs_mod.train_seasons_for(a.season)
    if not tr:
        raise SystemExit(f"{a.season}: no prior labelled season (KNOWN_ISSUES #11)")
    OUT.mkdir(parents=True, exist_ok=True)
    tag = a.season.replace("-", "_")
    out = OUT / f"hmin_{tag}_{'+'.join(levers)}.parquet"
    if out.exists():
        print(f"skip existing {out.name}")
        return
    df = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "GW"])
    gws = sorted(int(g) for g in df.loc[df["season"] == a.season, "GW"].unique())
    cutoffs = gws if a.cutoffs is None else [int(x) for x in a.cutoffs.split(",")]
    print(f"{a.season}: train on {tr}, levers {levers}, cutoffs {cutoffs[0]}..{cutoffs[-1]} ({len(cutoffs)})", flush=True)
    frames = []
    t_all = time.time()
    for k in cutoffs:
        t0 = time.time()
        f = hm.get_minutes_horizon(up_to_gw=k, steps=range(0, 6), availability=True,
                                   train_seasons=tr, predict_season=a.season, levers=levers)
        frames.append(f)
        print(f"  cutoff GW{k:2d}: {len(f):5d} rows ({f['horizon_step'].nunique()} steps) "
              f"{time.time() - t0:5.1f}s", flush=True)
    res = pd.concat(frames, ignore_index=True)
    res["season"] = a.season
    tmp = out.with_suffix(".tmp.parquet")
    res.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    print(f"DONE {out.name}: {len(res):,} rows in {(time.time() - t_all) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
