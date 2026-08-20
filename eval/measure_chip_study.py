# measure_chip_study.py
# P4 -- chip effects from the chip-study logs. Protocol and definitions:
# Logs/p4_chip_policy_log.md sections 4-5a (written before the sims ran).
#
#   sim chips (WC, FH) : W-window effect = paired per-gw points delta vs the
#                        shared baseline, summed over [g, g+W), W in {1,2,3,5}
#                        (prefix identity asserted at run time)
#   BB                 : bench_points at the chip week, read off the baseline
#                        log (alone) or the staged wildcard's log (staged)
#   TC                 : captain_bonus at the chip week, baseline log
#   staging increment  : staged-run bench_points@BBgw - baseline's
#
# NO intervals anywhere: n_active <= 3 per cell, below MIN_ACTIVE_FOR_CI = 8.
#
# Usage: uv run python eval/measure_chip_study.py

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CHIPS = REPO / "data" / "chips"
WS = [1, 2, 3, 5]
SEASONS = ["2023-24", "2024-25", "2025-26"]
BB2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}
BB1 = {"2023-24": 7}
TC2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}
TC1 = {"2023-24": 7}
STAGED = {"2023-24": "wc2_staged_gw33", "2024-25": "wc2_staged_gw32",
          "2025-26": "wc2_swing_gw32"}   # 2025-26: one sim serves both names


def load(season, config):
    p = CHIPS / f"chiplog_{season.replace('-', '_')}_{config}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def main():
    win_rows, single_rows, totals = [], [], []
    for season in SEASONS:
        base = load(season, "baseline")
        if base is None:
            print(f"{season}: no baseline yet"); continue
        bpts = base.set_index("gw")["points"]
        totals.append((season, "baseline", int(base["final_total"].iloc[0]),
                       -1))

        # --- simulated chips: windowed paired deltas -----------------------
        for p in sorted(CHIPS.glob(
                f"chiplog_{season.replace('-', '_')}_*.parquet")):
            config = p.stem.split("_", 3)[-1]
            if config == "baseline":
                continue
            log = load(season, config)
            g = int(log["chip_gw"].iloc[0])
            assert bool(log.get("prefix_identical", pd.Series([False])).iloc[0]), \
                f"{season} {config}: prefix identity was not asserted at run time"
            cpts = log.set_index("gw")["points"]
            totals.append((season, config, int(log["final_total"].iloc[0]), g))
            for W in WS:
                window = [x for x in bpts.index if g <= x < g + W]
                if len(window) < W:
                    continue
                eff = float(sum(cpts[x] - bpts[x] for x in window))
                win_rows.append({"season": season, "config": config,
                                 "chip_gw": g, "W": W, "effect": eff})

        # --- BB and TC: read off logs, single-week, same at every W --------
        for name, gw_map, col, src in [
                ("bb1", BB1, "bench_points", "baseline"),
                ("bb2_alone", BB2, "bench_points", "baseline"),
                ("tc1", TC1, "captain_bonus", "baseline"),
                ("tc2", TC2, "captain_bonus", "baseline")]:
            if season not in gw_map:
                continue
            g = gw_map[season]
            v = float(base.set_index("gw")[col].loc[g])
            single_rows.append({"season": season, "chip": name, "gw": g,
                                "effect": v})
        # staged BB: bench points at BB week on the wildcard-reshaped squad
        staged = load(season, STAGED[season])
        if staged is not None and season in BB2:
            g = BB2[season]
            sb = float(staged.set_index("gw")["bench_points"].loc[g])
            bb = float(base.set_index("gw")["bench_points"].loc[g])
            single_rows.append({"season": season, "chip": "bb2_staged",
                                "gw": g, "effect": sb})
            single_rows.append({"season": season, "chip": "bb2_staging_incr",
                                "gw": g, "effect": sb - bb})

    w = pd.DataFrame(win_rows)
    s = pd.DataFrame(single_rows)

    print("=== simulated chips: W-window paired effects (no intervals -- "
          "n_active <= 3 per cell, below the >=8 rule) ===")
    if len(w):
        piv = w.pivot_table(index=["season", "config", "chip_gw"],
                            columns="W", values="effect")
        print(piv.round(1).to_string())
        print("\nmean over active cells, by chip family x W:")
        w["family"] = w["config"].str.extract(r"^(wc1|wc2_swing|wc2_staged|fh1|fh2)")
        fam = w.groupby(["family", "W"])["effect"].agg(["mean", "count"])
        print(fam.round(2).to_string())

    print("\n=== BB / TC (read off logs; single-week, identical at every W) ===")
    if len(s):
        print(s.pivot_table(index="chip", columns="season",
                            values="effect").round(1).to_string())
        print("\nmean over seasons:")
        print(s.groupby("chip")["effect"].agg(["mean", "count"]).round(2)
              .to_string())

    print("\n=== season totals -- SANITY FRAMING ONLY ===")
    print("Identify configs. NOT evidence (M1 failed, path sd ~60), not")
    print("comparable to any earlier figure, no winner picked on them.")
    t = pd.DataFrame(totals, columns=["season", "config", "total", "chip_gw"])
    print(t.pivot_table(index="config", columns="season", values="total",
                        aggfunc="first").to_string())


if __name__ == "__main__":
    main()
