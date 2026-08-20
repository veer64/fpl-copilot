# measure_chip_phase2.py
# P4 section-8 measurement: bench-aware Bench Boost + combined chip runs.
# Protocol: Logs/p4_chip_policy_log.md section 8 (written before the sims).
#
#   BB package effect at window W = paired per-gw path delta vs baseline over
#   [wc_gw, wc_gw+W) PLUS bench_points at the BB week on the new path.
#   Old estimate for comparison: baseline bench_points at the BB week (+2.3
#   mean, section 6).
#
#   Combined runs are read ONLY against their own decay family's baseline:
#   d85 -> chip-study baseline; d60 -> transfer sweep base_H6_d60 log.
#   CROSS-CONFIG TOTALS ARE NOT COMPARABLE.
#
# Bench COMPOSITION is reported as the squad delta of the staging wildcard
# plus bench_points; the XI/bench split is not persisted in the decision log,
# stated rather than reconstructed.
#
# Usage: uv run python eval/measure_chip_phase2.py

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CHIPS = REPO / "data" / "chips"
SWEEP = REPO / "data" / "sweep"
SEASONS = ["2023-24", "2024-25", "2025-26"]
BB = {"2023-24": 34, "2024-25": 33, "2025-26": 33}
WC_STAGE = {"2023-24": 33, "2024-25": 32, "2025-26": 32}
BBAWARE = {"2023-24": "bbaware_wc33_bb34", "2024-25": "bbaware_wc32_bb33",
           "2025-26": "bbaware_wc32_bb33"}
WS = [1, 2, 3, 5]


def load(season, config):
    p = CHIPS / f"chiplog_{season.replace('-', '_')}_{config}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_d60_baseline(season):
    p = SWEEP / f"simlog_{season.replace('-', '_')}_base_H6_d60.parquet"
    return pd.read_parquet(p) if p.exists() else None


def names(elements, season):
    va = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet",
                         columns=["season", "element", "name"])
    m = va[va["season"] == season].drop_duplicates("element").set_index(
        "element")["name"]
    return [str(m.get(e, e)).encode("ascii", "replace").decode() for e in elements]


def window_delta(chip_log, base_log, g, W):
    b = base_log.set_index("gw")["points"]
    c = chip_log.set_index("gw")["points"]
    gws = [x for x in b.index if g <= x < g + W]
    return float(sum(c[x] - b[x] for x in gws)) if len(gws) == W else None


def main():
    print("=== 1. bench-aware Bench Boost re-measure (H=6, d=0.85) ===")
    for season in SEASONS:
        base, aware = load(season, "baseline"), load(season, BBAWARE[season])
        if aware is None:
            print(f"{season}: pending"); continue
        assert bool(aware["bench_boost_aware"].iloc[0]), \
            f"{season}: bench_boost_aware stamp missing/False in aware run"
        g_bb, g_wc = BB[season], WC_STAGE[season]
        bb_old = float(base.set_index("gw")["bench_points"].loc[g_bb])
        bb_new = float(aware.set_index("gw")["bench_points"].loc[g_bb])
        base_sq = set(json.loads(base.set_index("gw")["elements"].loc[g_bb]))
        new_sq = set(json.loads(aware.set_index("gw")["elements"].loc[g_bb]))
        print(f"\n{season}: wildcard@GW{g_wc} + bench-aware BB@GW{g_bb}")
        # pre-positioning: divergence begins when BB enters the H=6 horizon
        g0 = g_bb - 5
        pre = window_delta(aware, base, g0, g_wc - g0)
        print(f"  pre-positioning delta GW{g0}..GW{g_wc - 1}: {pre:+.0f}"
              if pre is not None else "  pre-positioning: n/a")
        print(f"  bench_points at BB week: {bb_old:.0f} -> {bb_new:.0f}")
        print(f"  squad delta at BB week: {len(new_sq - base_sq)} in / "
              f"{len(base_sq - new_sq)} out")
        print(f"    in : {', '.join(names(sorted(new_sq - base_sq), season)[:8])}")
        print(f"    out: {', '.join(names(sorted(base_sq - new_sq), season)[:8])}")
        for W in WS:
            d = window_delta(aware, base, g_wc, W)
            if d is None:
                continue
            covers = g_wc <= g_bb < g_wc + W
            pkg = d + (bb_new if covers else 0.0)
            old = bb_old if covers else 0.0
            print(f"  W={W}: path delta {d:+.0f}"
                  + (f", package (path + boosted bench) {pkg:+.0f} "
                     f"vs old exogenous estimate {old:+.0f}" if covers else
                     "  (window ends before the BB week)"))

    print("\n=== 2. combined chip runs ===")
    print("Each config read ONLY against its own decay family's baseline;")
    print("cross-config totals are NOT comparable.")
    for season in SEASONS:
        for cfg, base_src in [("combined_d85", "chipstudy"),
                              ("combined_d60", "sweep_d60")]:
            log = load(season, cfg)
            base = load(season, "baseline") if base_src == "chipstudy" \
                else load_d60_baseline(season)
            if log is None or base is None:
                print(f"{season} {cfg}: pending/missing"); continue
            # d60 prefix identity is checked HERE against its own family's
            # baseline (the driver can only assert against the d85 one)
            if base_src == "sweep_d60":
                pre_b = base[base["gw"] < 4].reset_index()["points"]
                pre_c = log[log["gw"] < 4].reset_index()["points"]
                assert pre_b.equals(pre_c), (
                    f"{season} {cfg}: pre-chip path differs from the d60 "
                    f"sweep baseline -- pairing invalid")
            g_bb = BB[season]
            tc = float(log.set_index("gw")["captain_bonus"].loc[g_bb])
            bbp = float(log.set_index("gw")["bench_points"].loc[g_bb])
            chip_gws = sorted(set(
                x for x in [4, WC_STAGE[season], g_bb]
                + json.loads("[" + str(log["chip_gw"].iloc[0]) + "]")))
            parts = []
            for g in [4, WC_STAGE[season], g_bb]:
                d3 = window_delta(log, base, g, 3)
                parts.append(f"GW{g}: {d3:+.0f}" if d3 is not None else f"GW{g}: n/a")
            tot_c = int(log["final_total"].iloc[0])
            tot_b = int(base["final_total"].iloc[0]) if "final_total" in base \
                else int(base["total_points"].iloc[-1])
            print(f"{season} {cfg}: W=3 deltas at chip anchors [{'; '.join(parts)}] "
                  f"+ BB bench {bbp:.0f} + TC capbonus {tc:.0f} | "
                  f"totals {tot_b} -> {tot_c} (sanity framing only)")


if __name__ == "__main__":
    main()
