# run_p1_robust.py
# P1 Step 2 -- scenario-robust opening squad (interim plan section 4).
#
# ONE new arm per season ("p2"): simulator.OPENING_ROBUST_ACTIVE flipped
# in-process (False on disk -- NOT ADOPTED). The base and Step-1 arms already
# exist in data/p1/ and are NOT re-simulated. Everything else identical to
# eval/run_p1_opening.py: H=6, decay=0.45, policy=mip, no chips, canonical
# walk-forward files, atomic write, skip-if-exists.
#
# The GW1 robust solve's runtime and candidate diagnostics are printed and the
# scenario config (K, seed) is stamped on every row.
#
# Usage: uv run python eval/run_p1_robust.py --season 2025-26

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import opening_robust  # noqa: E402
import simulator  # noqa: E402

OUT = REPO / "data" / "p1"
H, DECAY = 6, 0.45


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    a = ap.parse_args()
    season = a.season
    tag = season.replace("-", "_")
    OUT.mkdir(parents=True, exist_ok=True)

    out = OUT / f"p1log_{tag}_p2.parquet"
    if out.exists():
        print(f"skip existing {out.name}", flush=True)
        return

    simulator.OPENING_ROBUST_ACTIVE = True

    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)

    t0 = time.time()
    state, log = simulator.simulate_season(
        df, policy="mip", horizon=H, decay=DECAY, verbose=True)
    log = log.copy()
    stamped_r = log["opening_robust_active"].unique().tolist()
    stamped_h = log["opening_horizon_active"].unique().tolist()
    assert stamped_r == [True] and stamped_h == [False], (
        f"{season}: stamps robust={stamped_r} horizon={stamped_h} -- "
        "the gate did not take effect as intended")
    log["all_transfers"] = log["all_transfers"].map(json.dumps)
    log["elements"] = log["elements"].map(json.dumps)
    log["season"] = season
    log["arm"] = "p2"
    log["wf_file"] = wf_path.name
    log["robust_k"] = opening_robust.K_DEFAULT
    log["robust_seed"] = opening_robust.SEED
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
