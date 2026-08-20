# measure_chip_d45.py
# P4 section-10: the H=6 / decay=0.45 chip package vs the sweep's d45
# baselines. Protocol in Logs/p4_chip_policy_log.md section 10.
#
# Two report rows per season from ONE sim each:
#   pkg2h     : WC1 + WC2 + FH2 + bench-aware BB2 (sim) with TC2 read off
#   all-chips : pkg2h plus TC1 (peak-predicted-captain rule) and BB1@GW10
#               (arbitrary, unoptimised) -- both exogenous reads, so the
#               season path is IDENTICAL to pkg2h by construction.
# Chip-inclusive total = sim final_total + exogenous adds (BB/TC points are
# not part of the simulator's scoring).
#
# Usage: uv run python eval/measure_chip_d45.py

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CHIPS, SWEEP = REPO / "data" / "chips", REPO / "data" / "sweep"
SEASONS = ["2023-24", "2024-25", "2025-26"]
ANCHORS = {  # season -> {chip: gw}
    "2023-24": {"WC1": 4, "FH2": 29, "WC2": 32, "BB2": 34},
    "2024-25": {"WC1": 4, "FH2": 29, "WC2": 31, "BB2": 33},
    "2025-26": {"WC1": 4, "WC2": 32, "BB2": 33, "FH2": 34},
}
BB1_GW = 10          # arbitrary, flagged unoptimised
AVG_CLAIMED = {"2023-24": 2038, "2024-25": 2154, "2025-26": 1895}
AVG_ONDISK = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}
WS = [1, 2, 3, 5]


def tc1_rule(season, log):
    """The GW1-19 week where the sim's own captain's PREDICTED points peak.
    Captain name -> element via vaastav; prediction = his step-0 e_points at
    that gameweek's own cutoff."""
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "e_points",
                                  "horizon_step"])
    wf = wf[wf["horizon_step"] == 0]
    va = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet",
                         columns=["season", "element", "name"])
    name2el = (va[va["season"] == season].drop_duplicates("name")
               .set_index("name")["element"])
    best = None
    for _, r in log[log["gw"] <= 19].iterrows():
        el = name2el.get(r["captain"])
        if el is None:
            continue
        row = wf[(wf["gw"] == r["gw"]) & (wf["element"] == el)]
        if len(row) == 0:
            continue
        pred = float(row["e_points"].iloc[0])
        if best is None or pred > best[2]:
            best = (int(r["gw"]), r["captain"], pred,
                    float(r["captain_bonus"]))
    return best   # (gw, name, predicted, actual capbonus)


def main():
    for season in SEASONS:
        tag = season.replace("-", "_")
        log = pd.read_parquet(CHIPS / f"chiplog_{tag}_pkg_d45.parquet")
        base = pd.read_parquet(SWEEP / f"simlog_{tag}_base_H6_d45.parquet")
        # prefix identity vs the SWEEP baseline (canary for code-path drift
        # since the sweep: thread cap, gate branch)
        pre_b = base[base["gw"] < 4].reset_index()["points"]
        pre_c = log[log["gw"] < 4].reset_index()["points"]
        assert pre_b.equals(pre_c), \
            f"{season}: pre-GW4 path differs from the sweep d45 baseline"
        bp = base.set_index("gw")["points"]
        cp = log.set_index("gw")["points"]
        lg = log.set_index("gw")

        a = ANCHORS[season]
        tot_sim = int(log["final_total"].iloc[0])
        tot_base = int(base["final_total"].iloc[0])
        bb2 = float(lg["bench_points"].loc[a["BB2"]])
        tc2 = float(lg["captain_bonus"].loc[a["BB2"]])
        bb1 = float(lg["bench_points"].loc[BB1_GW])
        tc1 = tc1_rule(season, log)

        pkg_total = tot_sim + bb2 + tc2
        all_total = pkg_total + bb1 + (tc1[3] if tc1 else 0)

        print(f"\n=== {season} (H=6, d=0.45; baseline = sweep base_H6_d45, "
              f"prefix-identity PASSED) ===")
        print(f"  sim total {tot_sim} vs baseline {tot_base} "
              f"(path delta {tot_sim - tot_base:+d})")
        print(f"  chip-inclusive totals: pkg2h {pkg_total:.0f} "
              f"(+BB2 {bb2:.0f} +TC2 {tc2:.0f}) | all-chips {all_total:.0f} "
              f"(+TC1 {tc1[3] if tc1 else 0:.0f} +BB1@{BB1_GW} {bb1:.0f} "
              f"[unoptimised])")
        for label, t in [("pkg2h", pkg_total), ("all-chips", all_total)]:
            print(f"  {label}: vs avg claimed {t - AVG_CLAIMED[season]:+.0f}, "
                  f"vs avg fplcache {t - AVG_ONDISK[season]:+.0f}")
        if tc1:
            print(f"  TC1 rule selects GW{tc1[0]} captain {tc1[1]!r} "
                  f"(predicted {tc1[2]:.2f}); he actually scored {tc1[3]:.0f}")
        print("  W-window paired deltas at chip anchors "
              "(windows overlap where anchors are < W apart -- NOT additive):")
        for chip, g in sorted(a.items(), key=lambda kv: kv[1]):
            row = f"    {chip}@GW{g}: "
            for W in WS:
                gws = [x for x in bp.index if g <= x < g + W]
                d = sum(cp[x] - bp[x] for x in gws) if len(gws) == W else None
                row += f"W{W} {d:+.0f}  " if d is not None else f"W{W} n/a  "
            print(row)
        near = [(c1, c2) for c1 in a for c2 in a
                if c1 < c2 and 0 < abs(a[c1] - a[c2]) < 5]
        print(f"  overlapping anchor pairs (within 5 gws): "
              f"{', '.join(f'{x}-{y}' for x, y in near)}")


if __name__ == "__main__":
    main()
