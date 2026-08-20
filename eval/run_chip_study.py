# run_chip_study.py
# P4 structural chip policy -- one sim per configuration, resumable.
# Protocol: Logs/p4_chip_policy_log.md (written before this ran).
#
# ONLY wildcard and free-hit configs need simulations: they change decisions.
# Bench Boost and Triple Captain are exogenous instruments (simulator
# docstring philosophy): they change no transfer, so BB's effect is exactly
# `bench_points` at the chip week and TC's is `captain_bonus`, both read off
# the relevant log by eval/measure_chip_study.py. The staged variant's BB
# increment reads bench_points off the WILDCARD run's log at BB week.
#
# Baseline runs FIRST per season; every chip run then asserts its pre-chip
# per-gameweek points equal the baseline's (deterministic prefix identity --
# the property that makes the paired window measurement valid).
#
# Usage: uv run python eval/run_chip_study.py --season 2025-26

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
import simulator  # noqa: E402

OUT = REPO / "data" / "chips"

# Phase 3 (log section 10): the H=6 / decay=0.45 chip package. Baselines are
# the sweep's base_H6_d45 runs (provenance verified in the log); prefix
# identity vs them is checked at measurement time. One sim per season -- the
# "all chips" variant is a derived read off the same log (TC and unoptimised
# BB change no decisions).
PHASE3_CONFIGS = {
    "2023-24": {"pkg_d45": {"wildcard_gws": [4, 32], "free_hit_gws": 29,
                            "bench_boost_gw": 34, "decay": 0.45}},
    "2024-25": {"pkg_d45": {"wildcard_gws": [4, 31], "free_hit_gws": 29,
                            "bench_boost_gw": 33, "decay": 0.45}},
    "2025-26": {"pkg_d45": {"wildcard_gws": [4, 32], "free_hit_gws": 34,
                            "bench_boost_gw": 33, "decay": 0.45}},
}

# Phase 2 (log section 8): bench-aware Bench Boost re-measure + combined chip
# runs. These flip transfer_mip.BENCH_BOOST_AWARE in-process (False on disk;
# the simulator stamps it per row). "decay" overrides the default for the
# cross-config combined run; totals across decay families are NOT comparable.
PHASE2_CONFIGS = {
    "2023-24": {
        "bbaware_wc33_bb34": {"wildcard_gws": 33, "bench_boost_gw": 34},
        "combined_d85": {"wildcard_gws": [4, 32], "free_hit_gws": 29,
                         "bench_boost_gw": 34},
        "combined_d60": {"wildcard_gws": [4, 32], "free_hit_gws": 29,
                         "bench_boost_gw": 34, "decay": 0.6},
    },
    "2024-25": {
        "bbaware_wc32_bb33": {"wildcard_gws": 32, "bench_boost_gw": 33},
        "combined_d85": {"wildcard_gws": [4, 31], "free_hit_gws": 29,
                         "bench_boost_gw": 33},
        "combined_d60": {"wildcard_gws": [4, 31], "free_hit_gws": 29,
                         "bench_boost_gw": 33, "decay": 0.6},
    },
    "2025-26": {
        "bbaware_wc32_bb33": {"wildcard_gws": 32, "bench_boost_gw": 33},
        "combined_d85": {"wildcard_gws": [4, 32], "free_hit_gws": 34,
                         "bench_boost_gw": 33},
        "combined_d60": {"wildcard_gws": [4, 32], "free_hit_gws": 34,
                         "bench_boost_gw": 33, "decay": 0.6},
    },
}
H, DECAY = 6, 0.85          # production defaults -- chip timing must be
                            # measured at the config that would play it

CONFIGS = {                 # name -> simulate_season chip kwargs
    "2023-24": {
        "baseline": {},
        "wc1_gw4": {"wildcard_gws": 4}, "wc1_gw5": {"wildcard_gws": 5},
        "wc1_gw6": {"wildcard_gws": 6},
        "fh1_gw17": {"free_hit_gws": 17},
        "fh2_gw29": {"free_hit_gws": 29},
        "wc2_swing_gw32": {"wildcard_gws": 32},
        "wc2_staged_gw33": {"wildcard_gws": 33},   # BB2=34 read off this log
    },
    "2024-25": {
        "baseline": {},
        "wc1_gw4": {"wildcard_gws": 4}, "wc1_gw5": {"wildcard_gws": 5},
        "wc1_gw6": {"wildcard_gws": 6},
        "fh1_gw15": {"free_hit_gws": 15},
        "fh2_gw29": {"free_hit_gws": 29},
        "wc2_swing_gw31": {"wildcard_gws": 31},
        "wc2_staged_gw32": {"wildcard_gws": 32},   # BB2=33 read off this log
    },
    "2025-26": {
        "baseline": {},
        "wc1_gw4": {"wildcard_gws": 4}, "wc1_gw5": {"wildcard_gws": 5},
        "wc1_gw6": {"wildcard_gws": 6},
        "fh2_gw34": {"free_hit_gws": 34},
        "wc2_swing_gw32": {"wildcard_gws": 32},
        # NOTE: 2025-26 swing and staged coincide at GW32 (BB2=33) -- one sim
        # serves both variants; measure reads it twice under both names.
    },
}


def chip_gw(cfg):
    gws = []
    for k in ("wildcard_gws", "free_hit_gws", "bench_boost_gw"):
        v = cfg.get(k)
        if v is None:
            continue
        gws.extend(int(x) for x in (v if isinstance(v, (list, tuple)) else [v]))
    return min(gws) if gws else None


def run(season, name, cfg, df, baseline_log):
    cfg = dict(cfg)
    decay = cfg.pop("decay", DECAY)
    state, log = simulator.simulate_season(
        df, policy="mip", horizon=H, decay=decay, verbose=False, **cfg)
    log = log.copy()
    g = chip_gw(cfg)
    # Prefix identity only holds against a baseline of the SAME decay family:
    # a decay-overridden config diverges from the d=0.85 chip-study baseline
    # at GW1 by design. Those configs are checked at measurement time against
    # their own family's baseline (the sweep's base_H6_d60 run) instead.
    # Bench-awareness changes decisions as soon as the BB week ENTERS the
    # horizon -- bb_gw - (H-1) -- which is BEFORE the staging wildcard. That
    # early divergence is the mechanism working, not contamination, so the
    # identity boundary moves there; the measurement reports the
    # pre-positioning window [bb-H+1, wc) separately.
    ident_gw = g
    if cfg.get("bench_boost_gw"):
        ident_gw = min(ident_gw, int(cfg["bench_boost_gw"]) - (H - 1))
    if g is not None and baseline_log is not None and decay == DECAY:
        pre_b = baseline_log[baseline_log["gw"] < ident_gw].reset_index()["points"]
        pre_c = log[log["gw"] < ident_gw].reset_index()["points"]
        assert pre_b.equals(pre_c), (
            f"{season} {name}: pre-chip path DIVERGED from baseline -- the "
            f"paired window measurement is invalid for this run")
        log["prefix_identical"] = True
    else:
        log["prefix_identical"] = False
    log["all_transfers"] = log["all_transfers"].map(json.dumps)
    log["elements"] = log["elements"].map(json.dumps)
    log["season"], log["config"] = season, name
    log["chip_gw"] = g if g is not None else -1
    log["final_total"] = int(state.total_points)
    out = OUT / f"chiplog_{season.replace('-', '_')}_{name}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    log.to_parquet(tmp, index=False)
    tmp.replace(out)
    return int(state.total_points)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--only", nargs="*", default=None,
                    help="run only these config names (parallel workers on "
                         "disjoint subsets; baseline must already exist)")
    ap.add_argument("--phase2", action="store_true",
                    help="run the section-8 configs with BENCH_BOOST_AWARE "
                         "flipped on in-process")
    ap.add_argument("--phase3", action="store_true",
                    help="run the section-10 d=0.45 package configs "
                         "(also flips the gate on in-process)")
    a = ap.parse_args()
    if a.phase2 or a.phase3:
        import transfer_mip
        transfer_mip.BENCH_BOOST_AWARE = True
    season = a.season
    OUT.mkdir(parents=True, exist_ok=True)
    tag = season.replace("-", "_")
    df = simulator.load_season(
        walkforward_path=str(REPO / "data" / f"walkforward_h6_{tag}.parquet"),
        horizon_aware=True, season=season)

    base_path = OUT / f"chiplog_{tag}_baseline.parquet"
    if base_path.exists():
        baseline_log = pd.read_parquet(base_path)
        print(f"baseline exists ({baseline_log['final_total'].iloc[0]})",
              flush=True)
    else:
        t0 = time.time()
        total = run(season, "baseline", {}, df, None)
        baseline_log = pd.read_parquet(base_path)
        print(f"DONE baseline: {total} ({(time.time()-t0)/60:.1f} min)",
              flush=True)

    configs = (PHASE3_CONFIGS[season] if a.phase3
               else PHASE2_CONFIGS[season] if a.phase2 else CONFIGS[season])
    for name, cfg in configs.items():
        if name == "baseline":
            continue
        if a.only is not None and name not in a.only:
            continue
        out = OUT / f"chiplog_{tag}_{name}.parquet"
        if out.exists():
            print(f"skip existing {out.name}", flush=True)
            continue
        t0 = time.time()
        try:
            total = run(season, name, cfg, df, baseline_log)
            print(f"DONE {name}: {total} ({(time.time()-t0)/60:.1f} min)",
                  flush=True)
        except Exception as e:
            print(f"FAILED {name}: {type(e).__name__}: {e}", flush=True)
    print(f"CHIP STUDY COMPLETE {season}", flush=True)


if __name__ == "__main__":
    main()
