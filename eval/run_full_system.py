# run_full_system.py
# Overnight FULL-SYSTEM grid: 2 openings x WC1 {2,4,6,8} x 3 seasons, ALL
# supportable chips on one path (P4 rules of record + the P1 opening gate).
#
# Per cell: WC1 (variable under test) + WC2 at the pre-DGW-cluster swing week
# + FH2 at the largest blank (>=4 floor -- all three seasons qualify) + BB1
# and BB2 both SCHEDULED bench-aware (the simulator now takes one boost per
# half). TC1/TC2 and the BB bench readings stay exogenous reads at
# measurement time, per the P4 convention -- they change no decisions.
# FH1 EXCLUDED (measured -20 at token blanks).
#
# Chip weeks (P4 log section 2; BB1 selection 2026-08-21, stated rule:
# 2023-24 = the only first-half double; elsewhere argmax of the baseline
# squad's predicted bench points over GW3-19 minus the WC1 grid weeks):
#   WC2 32/31/32, FH2 29/29/34, BB2 34/33/33
#   BB1 2023-24: 7/7   2024-25: base 7, p1 9   2025-26: 10/10
#
# Baselines REUSED from data/p1/p1log_{tag}_{opening}.parquet (no-chip runs).
# Prefix identity asserted per cell up to min(wc1, bb1-5) -- bench-awareness
# diverges when the boost enters the H=6 window (the P4 boundary rule).
#
# One parquet per cell (fslog_*), atomic, skip-if-exists -- resumable.
#
# Usage: uv run python eval/run_full_system.py --season 2025-26 --opening p1

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
WC1S = [2, 4, 6, 8]
WC2 = {"2023-24": 32, "2024-25": 31, "2025-26": 32}
FH2 = {"2023-24": 29, "2024-25": 29, "2025-26": 34}
BB2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}
BB1 = {("2023-24", "base"): 7, ("2023-24", "p1"): 7,
       ("2024-25", "base"): 7, ("2024-25", "p1"): 9,
       ("2025-26", "base"): 10, ("2025-26", "p1"): 10}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--opening", required=True, choices=["base", "p1"])
    a = ap.parse_args()
    season, opening = a.season, a.opening
    tag = season.replace("-", "_")

    simulator.OPENING_HORIZON_ACTIVE = (opening == "p1")

    baseline = pd.read_parquet(OUT / f"p1log_{tag}_{opening}.parquet")
    assert baseline["opening_horizon_active"].unique().tolist() == \
        [opening == "p1"]
    assert int(baseline["horizon"].iloc[0]) == H
    assert float(baseline["decay"].iloc[0]) == DECAY

    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)

    bb1, bb2 = BB1[(season, opening)], BB2[season]
    for wc1 in WC1S:
        out = OUT / f"fslog_{tag}_{opening}_wc{wc1}.parquet"
        if out.exists():
            print(f"skip existing {out.name}", flush=True)
            continue
        t0 = time.time()
        try:
            state, log = simulator.simulate_season(
                df, policy="mip", horizon=H, decay=DECAY,
                wildcard_gws=[wc1, WC2[season]],
                free_hit_gws=FH2[season],
                bench_boost_gw=[bb1, bb2],
                verbose=False)
            log = log.copy()
            assert log["opening_horizon_active"].unique().tolist() == \
                [opening == "p1"], "opening gate did not take effect"
            assert log["bench_boost_gws"].unique().tolist() == \
                [f"{bb1},{bb2}"], "bench boost schedule not stamped"
            boundary = min(wc1, bb1 - (H - 1))
            if boundary > 1:
                pre_b = baseline[baseline["gw"] < boundary] \
                    .reset_index()["points"]
                pre_c = log[log["gw"] < boundary].reset_index()["points"]
                assert pre_b.equals(pre_c), (
                    f"{season} {opening} wc{wc1}: pre-chip path DIVERGED "
                    f"from baseline before GW{boundary}")
            log["all_transfers"] = log["all_transfers"].map(json.dumps)
            log["elements"] = log["elements"].map(json.dumps)
            log["season"], log["opening"] = season, opening
            log["wc1"], log["wc2"] = wc1, WC2[season]
            log["fh2"], log["bb1"], log["bb2"] = FH2[season], bb1, bb2
            log["wf_file"] = wf_path.name
            log["final_total"] = int(state.total_points)
            tmp = out.with_suffix(".tmp.parquet")
            log.to_parquet(tmp, index=False)
            tmp.replace(out)
            print(f"DONE {out.name}: total={int(state.total_points)} "
                  f"({(time.time() - t0) / 60:.1f} min)", flush=True)
        except Exception as e:
            print(f"FAILED {out.name}: {type(e).__name__}: {e}", flush=True)
    print(f"FULL-SYSTEM WORKER COMPLETE {season} {opening}", flush=True)


if __name__ == "__main__":
    main()
