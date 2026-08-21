# run_p1_wc_grid.py
# Overnight WC1 x opening grid (2 openings x 7 wildcard weeks x 3 seasons).
#
# Two open questions (P4 log section 12; P1 log): WC1's best week was never
# resolvable from three seasons, and the horizon opening (P1 Step 1) may
# change the answer -- a squad that survives longer has less to escape from.
#
# Arms per season:
#   opening=base : status-quo single-gameweek GW1 seed
#   opening=p1   : simulator.OPENING_HORIZON_ACTIVE flipped in-process
# x wildcard_gws in {2..8}. H=6, decay=0.45, policy=mip, no other chips.
#
# BASELINES ARE REUSED, NOT RE-RUN: data/p1/p1log_{tag}_{base,p1}.parquet.
# Each wildcard run asserts PRE-CHIP PREFIX IDENTITY vs its own opening's
# baseline (per-gw points equal for gw < wc) -- the P4 run() convention; a
# divergence means code drift and voids the paired window measurement.
#
# One parquet per cell under data/p1/ (wclog_{tag}_{opening}_wc{N}.parquet),
# atomic write, skip-if-exists -- the grid is resumable and partial output
# survives interruption. Config stamped on every row.
#
# Usage (one worker per season x opening; 6 workers total):
#   uv run python eval/run_p1_wc_grid.py --season 2025-26 --opening p1

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import simulator  # noqa: E402

OUT = REPO / "data" / "p1"
H, DECAY = 6, 0.45
WEEKS = [2, 3, 4, 5, 6, 7, 8]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--opening", required=True, choices=["base", "p1"])
    a = ap.parse_args()
    season, opening = a.season, a.opening
    tag = season.replace("-", "_")

    simulator.OPENING_HORIZON_ACTIVE = (opening == "p1")

    base_path = OUT / f"p1log_{tag}_{opening}.parquet"
    baseline = pd.read_parquet(base_path)
    # the reused baseline must be the right arm and config
    assert baseline["opening_horizon_active"].unique().tolist() == \
        [opening == "p1"], f"baseline {base_path.name} is the wrong arm"
    assert int(baseline["horizon"].iloc[0]) == H
    assert float(baseline["decay"].iloc[0]) == DECAY

    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)

    for wc in WEEKS:
        out = OUT / f"wclog_{tag}_{opening}_wc{wc}.parquet"
        if out.exists():
            print(f"skip existing {out.name}", flush=True)
            continue
        t0 = time.time()
        try:
            state, log = simulator.simulate_season(
                df, policy="mip", horizon=H, decay=DECAY,
                wildcard_gws=wc, verbose=False)
            log = log.copy()
            assert log["opening_horizon_active"].unique().tolist() == \
                [opening == "p1"], "opening gate did not take effect"
            pre_b = baseline[baseline["gw"] < wc].reset_index()["points"]
            pre_c = log[log["gw"] < wc].reset_index()["points"]
            assert pre_b.equals(pre_c), (
                f"{season} {opening} wc{wc}: pre-chip path DIVERGED from "
                "the reused baseline -- paired measurement invalid")
            log["all_transfers"] = log["all_transfers"].map(json.dumps)
            log["elements"] = log["elements"].map(json.dumps)
            log["season"] = season
            log["opening"] = opening
            log["wc_gw"] = wc
            log["wf_file"] = wf_path.name
            log["final_total"] = int(state.total_points)
            tmp = out.with_suffix(".tmp.parquet")
            log.to_parquet(tmp, index=False)
            tmp.replace(out)
            print(f"DONE {out.name}: total={int(state.total_points)} "
                  f"({(time.time() - t0) / 60:.1f} min)", flush=True)
        except Exception as e:
            print(f"FAILED {out.name}: {type(e).__name__}: {e}", flush=True)
    print(f"GRID WORKER COMPLETE {season} {opening}", flush=True)


if __name__ == "__main__":
    main()
