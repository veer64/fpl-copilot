# run_teamnews_oracle.py
# Team-news STEP 4 -- the oracle-minutes upper bound. ONE sim per season
# under the full adopted system (base opening, WC1@GW2, WC2/FH2/BB1+BB2 as
# eval/run_p5.py's reference config), with squad/oracle_minutes.py flipped
# on IN-PROCESS (deliberate leakage -- measuring instrument, never adopt;
# see that module's warning). References REUSED: fslog_{tag}_base_wc2.
#
# Output: data/teamnews/oraclelog_{tag}.parquet, stamped
# oracle_minutes_active=True on every row.
# Usage: uv run python eval/run_teamnews_oracle.py --season 2025-26

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import oracle_minutes  # noqa: E402
import simulator  # noqa: E402

OUT = REPO / "data" / "teamnews"
H, DECAY = 6, 0.45
WC1 = 2
WC2 = {"2023-24": 32, "2024-25": 31, "2025-26": 32}
FH2 = {"2023-24": 29, "2024-25": 29, "2025-26": 34}
BB1 = {"2023-24": 7, "2024-25": 7, "2025-26": 10}
BB2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    a = ap.parse_args()
    season = a.season
    tag = season.replace("-", "_")
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"oraclelog_{tag}.parquet"
    if out.exists():
        print(f"skip existing {out.name}", flush=True)
        return

    oracle_minutes.ORACLE_MINUTES_ACTIVE = True
    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)
    t0 = time.time()
    state, log = simulator.simulate_season(
        df, policy="mip", horizon=H, decay=DECAY,
        wildcard_gws=[WC1, WC2[season]], free_hit_gws=FH2[season],
        bench_boost_gw=[BB1[season], BB2[season]], verbose=False)
    log = log.copy()
    assert log["oracle_minutes_active"].unique().tolist() == [True]
    log["all_transfers"] = log["all_transfers"].map(json.dumps)
    log["elements"] = log["elements"].map(json.dumps)
    log["season"] = season
    log["wf_file"] = wf_path.name
    log["final_total"] = int(state.total_points)
    tmp = out.with_suffix(".tmp.parquet")
    log.to_parquet(tmp, index=False)
    tmp.replace(out)
    print(f"DONE {out.name}: total={int(state.total_points)} "
          f"({(time.time() - t0) / 60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
