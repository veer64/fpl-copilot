# run_p3.py
# P3 -- early hit tolerance under the FULL adopted system.
#
# Sweep the solver's effective hit bar in GW2-7 at {3, 2, 1} (bar 4 = the
# current behaviour = the existing full-system reference runs, REUSED, not
# re-simulated), under two wildcard placements so the P2 substitution is
# visible:
#   wc1=2 : the adopted rule's week -- the wildcard already clears dead
#           weight before most early hits could
#   wc1=6 : the wildcard arrives late -- GW2-5 hits act where nothing else
#           is clearing dead weight (the contrast that answers the question)
#
# Chip config otherwise identical to eval/run_full_system.py (base opening,
# WC2/FH2/BB1+BB2 per season). Gates flipped in-process
# (transfer_mip.EARLY_HIT_DISCOUNT_ACTIVE / EARLY_HIT_BAR, both stamped).
# Scoring always charges FPL's real 4 -- only the solver's willingness moves.
#
# One parquet per cell, atomic, skip-if-exists.
# Usage: uv run python eval/run_p3.py --season 2025-26 --wc1 2

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import simulator  # noqa: E402
import transfer_mip  # noqa: E402

OUT = REPO / "data" / "p1"
H, DECAY = 6, 0.45
BARS = [3, 2, 1]
WC2 = {"2023-24": 32, "2024-25": 31, "2025-26": 32}
FH2 = {"2023-24": 29, "2024-25": 29, "2025-26": 34}
BB1 = {"2023-24": 7, "2024-25": 7, "2025-26": 10}
BB2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--wc1", type=int, required=True, choices=[2, 6])
    a = ap.parse_args()
    season, wc1 = a.season, a.wc1
    tag = season.replace("-", "_")

    ref = pd.read_parquet(OUT / f"fslog_{tag}_base_wc{wc1}.parquet")

    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)

    for bar in BARS:
        out = OUT / f"p3log_{tag}_wc{wc1}_bar{bar}.parquet"
        if out.exists():
            print(f"skip existing {out.name}", flush=True)
            continue
        transfer_mip.EARLY_HIT_DISCOUNT_ACTIVE = True
        transfer_mip.EARLY_HIT_BAR = float(bar)
        t0 = time.time()
        try:
            state, log = simulator.simulate_season(
                df, policy="mip", horizon=H, decay=DECAY,
                wildcard_gws=[wc1, WC2[season]], free_hit_gws=FH2[season],
                bench_boost_gw=[BB1[season], BB2[season]], verbose=False)
            log = log.copy()
            assert log["early_hit_discount_active"].unique().tolist() == [True]
            assert log["early_hit_bar"].unique().tolist() == [float(bar)]
            # GW1 must match the reference (the discount starts at GW2)
            assert int(log.loc[log["gw"] == 1, "points"].iloc[0]) == \
                int(ref.loc[ref["gw"] == 1, "points"].iloc[0]), \
                "GW1 diverged from the reference -- the gate leaked into GW1"
            log["all_transfers"] = log["all_transfers"].map(json.dumps)
            log["elements"] = log["elements"].map(json.dumps)
            log["season"], log["wc1_week"], log["bar"] = season, wc1, bar
            log["wf_file"] = wf_path.name
            log["final_total"] = int(state.total_points)
            tmp = out.with_suffix(".tmp.parquet")
            log.to_parquet(tmp, index=False)
            tmp.replace(out)
            early = log[(log["gw"] >= 2) & (log["gw"] <= 7)]
            print(f"DONE {out.name}: total={int(state.total_points)} "
                  f"(ref {int(ref['final_total'].iloc[0])}) "
                  f"early hits GW2-7: {int(early['hit'].sum())} pts "
                  f"({(time.time() - t0) / 60:.1f} min)", flush=True)
        except Exception as e:
            print(f"FAILED {out.name}: {type(e).__name__}: {e}", flush=True)
        finally:
            transfer_mip.EARLY_HIT_DISCOUNT_ACTIVE = False
            transfer_mip.EARLY_HIT_BAR = 4.0
    print(f"P3 WORKER COMPLETE {season} wc{wc1}", flush=True)


if __name__ == "__main__":
    main()
