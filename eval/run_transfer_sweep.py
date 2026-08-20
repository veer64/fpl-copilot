# run_transfer_sweep.py
# Overnight stage 3 -- transfer sweep: H x decay x synthetic-lambda x season.
#
# One MIP season simulation per configuration, no chips (wildcard/TC/FH all
# None -- this measures TRANSFER policy, not chip policy). Each run's decision
# log is written to its own parquet under data/sweep/ as soon as it finishes,
# with the config stamped on every row, so a killed run loses at most the
# simulation in flight. Existing outputs are SKIPPED -- the sweep is resumable.
#
# Endpoints are computed separately by eval/measure_transfer_sweep.py; season
# totals are recorded under the standard framing (identify, never evidence).
#
# Usage: uv run python eval/run_transfer_sweep.py --season 2025-26

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import simulator  # noqa: E402

OUT_DIR = REPO / "data" / "sweep"
HORIZONS = [3, 4, 6]
DECAYS = [0.3, 0.45, 0.6]
FILES = {  # synth label -> walkforward file pattern
    "base": "walkforward_h6_{tag}.parquet",
    "synth": "walkforward_h6_{tag}_synth.parquet",
}


def run_one(season, variant, wf_path, H, decay, out_path):
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)
    state, log = simulator.simulate_season(
        df, policy="mip", horizon=H, decay=decay, verbose=False)
    log = log.copy()
    # lists do not survive parquet round-trips reliably -- store as JSON
    log["all_transfers"] = log["all_transfers"].map(json.dumps)
    log["elements"] = log["elements"].map(json.dumps)
    log["season"] = season
    log["variant"] = variant
    log["horizon"] = H
    log["decay"] = decay
    log["final_total"] = int(state.total_points)
    log.to_parquet(out_path, index=False)
    return int(state.total_points), int(log["n_transfers"].sum()), int(log["hit"].sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    args = ap.parse_args()
    season = args.season
    tag = season.replace("-", "_")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for variant, pattern in FILES.items():
        wf_path = REPO / "data" / pattern.format(tag=tag)
        if not wf_path.exists():
            print(f"SKIP {variant}: {wf_path} missing", flush=True)
            continue
        for H in HORIZONS:
            for decay in DECAYS:
                out = OUT_DIR / f"simlog_{tag}_{variant}_H{H}_d{int(decay*100)}.parquet"
                if out.exists():
                    print(f"skip existing {out.name}", flush=True)
                    continue
                t0 = time.time()
                try:
                    total, n_tr, hits = run_one(season, variant, wf_path, H,
                                                decay, out)
                    print(f"DONE {out.name}: total={total} transfers={n_tr} "
                          f"hits={hits} ({(time.time()-t0)/60:.1f} min)",
                          flush=True)
                except Exception as e:              # log and continue the sweep
                    print(f"FAILED {out.name}: {type(e).__name__}: {e}",
                          flush=True)
    print(f"SWEEP COMPLETE {season}", flush=True)


if __name__ == "__main__":
    main()
