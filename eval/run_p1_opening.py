# run_p1_opening.py
# P1 Step 1 -- give the opening squad a horizon (interim plan section 4).
#
# Two arms per season, differing ONLY on simulator.OPENING_HORIZON_ACTIVE
# (flipped in-process, exactly the run_chip_study --phase2 pattern; the
# constant on disk stays False -- NOT ADOPTED, this is a measurement):
#
#   base : opening squad from the single-gameweek optimize_squad (status quo)
#   p1   : opening squad from build_and_solve over H=6 / decay=0.45 at GW1's
#          own cutoff -- the adopted standard config, policy=mip, no chips
#
# One decision log per (season, arm) under data/p1/, config stamped on every
# row (including the simulator's own `opening_horizon_active` stamp), written
# atomically on completion, skipped if it already exists. Season totals are
# recorded under the standard framing: they identify the config, never rank it.
#
# Usage: uv run python eval/run_p1_opening.py --season 2025-26 --arm p1

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import simulator  # noqa: E402

OUT = REPO / "data" / "p1"
H, DECAY = 6, 0.45   # the adopted standard config (P4 log section 13)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--arm", required=True, choices=["base", "p1"])
    a = ap.parse_args()
    season, arm = a.season, a.arm
    tag = season.replace("-", "_")
    OUT.mkdir(parents=True, exist_ok=True)

    out = OUT / f"p1log_{tag}_{arm}.parquet"
    if out.exists():
        print(f"skip existing {out.name}", flush=True)
        return

    simulator.OPENING_HORIZON_ACTIVE = (arm == "p1")

    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)

    t0 = time.time()
    state, log = simulator.simulate_season(
        df, policy="mip", horizon=H, decay=DECAY, verbose=False)
    log = log.copy()
    # the simulator's own stamp must agree with the arm we asked for --
    # a disagreement means the gate never took effect (silent-fallback check)
    stamped = log["opening_horizon_active"].unique().tolist()
    assert stamped == [arm == "p1"], (
        f"{season} {arm}: opening_horizon_active stamped {stamped}, "
        f"expected [{arm == 'p1'}] -- the gate did not take effect")
    # lists do not survive parquet round-trips reliably -- store as JSON
    log["all_transfers"] = log["all_transfers"].map(json.dumps)
    log["elements"] = log["elements"].map(json.dumps)
    log["season"] = season
    log["arm"] = arm
    log["wf_file"] = wf_path.name
    log["final_total"] = int(state.total_points)
    tmp = out.with_suffix(".tmp.parquet")
    log.to_parquet(tmp, index=False)
    tmp.replace(out)
    print(f"DONE {out.name}: total={int(state.total_points)} "
          f"transfers={int(log['n_transfers'].sum())} "
          f"hits={int(log['hit'].sum())} "
          f"({(time.time() - t0) / 60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
