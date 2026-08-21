# measure_full_system.py
# Measurement for the full-system grid (eval/run_full_system.py). Tolerates a
# partial grid. Read-only.
#
# Per cell (season, opening, wc1):
#   - PATH season total + delta vs the opening's own no-chip baseline
#   - chip-inclusive total = path + bench@BB1 + bench@BB2 + captain_bonus@TC1
#     + captain_bonus@TC2 (exogenous reads, the P4 convention). TC2 = the
#     biggest-DGW week, which COINCIDES with BB2's week in all three seasons;
#     P4 added both reads and so does this -- caveat stated, a real manager
#     could play only one of the two that week.
#   - GW1-10 path points vs the FPL average manager (chip reads excluded)
#   - full-season margin: chip-inclusive total - fplcache season average
#   - W=3 path deltas at each chip anchor vs the no-chip baseline. After the
#     first chip the path has diverged, so later anchors are NOT
#     path-controlled (P4 section 7 caveat), and WC2/BB2/FH2 sit 1-2 gws
#     apart -- windows overlap and must never be added.
#   - THE BB1 QUESTION: fslog vs the SAME (season, opening, wc1) cell of the
#     isolated wildcard grid (wclog_*) differ ONLY by Bench Boost scheduling
#     before GW28 (WC2/FH2/BB2 all sit at GW28+; BB2 enters the horizon at
#     bb2-5 >= 26). Prefix identity up to bb1-5 is asserted. BB1's path cost
#     = sum(fs - wc points) over [bb1-5, min(bb1+5, 27)]; BB1's gain =
#     bench@bb1 in the fs run. Net = gain + cost.
#
# TC1 per cell: argmax over GW1-19 (minus that cell's chip weeks) of the
# played captain's own-cutoff predicted points, read from the cell's own log.
#
# Usage: uv run python eval/measure_full_system.py

import json
import lzma
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"

SEASONS = ["2023-24", "2024-25", "2025-26"]
OPENINGS = ["base", "p1"]
WC1S = [2, 4, 6, 8]
SNAP = {"2023-24": (2024, 5, 30), "2024-25": (2025, 5, 30),
        "2025-26": (2026, 5, 30)}
AVG_SUM_EXPECT = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}


def avg_manager(season):
    y, m, d = SNAP[season]
    snap = sorted((CACHE / str(y) / str(m) / str(d)).glob("*.json.xz"))[-1]
    with lzma.open(snap) as f:
        events = json.load(f)["events"]
    assert len(events) == 38 and all(e["finished"] for e in events)
    per_gw = {e["id"]: e["average_entry_score"] for e in events}
    assert sum(per_gw.values()) == AVG_SUM_EXPECT[season]
    return per_gw


def load(path):
    d = pd.read_parquet(path)
    d["elements"] = d["elements"].map(json.loads)
    assert int(d["horizon"].iloc[0]) == 6
    assert float(d["decay"].iloc[0]) == 0.45
    return d.set_index("gw")


def window(dlog, blog, a, W=3):
    gws = [g for g in range(a, a + W) if g in dlog.index and g in blog.index]
    return int(dlog.loc[gws, "points"].sum() - blog.loc[gws, "points"].sum())


def main():
    missing = []
    for season in SEASONS:
        tag = season.replace("-", "_")
        avg = avg_manager(season)
        a10 = sum(avg[g] for g in range(1, 11))
        wf = pd.read_parquet(
            REPO / "data" / f"walkforward_h6_{tag}.parquet",
            columns=["cutoff", "gw", "element", "name", "e_points"])
        own = wf[wf["cutoff"] == wf["gw"]]
        cap_pred = {}          # (gw, name) -> predicted points that week
        for gw, g in own.groupby("gw"):
            for r in g.itertuples():
                cap_pred[(int(gw), r.name)] = float(r.e_points or 0)
        print("=" * 100)
        print(f"SEASON {season}")
        print("=" * 100)
        for opening in OPENINGS:
            baseline = load(P1 / f"p1log_{tag}_{opening}.parquet")
            b_total = int(baseline["final_total"].iloc[0])
            for wc1 in WC1S:
                p = P1 / f"fslog_{tag}_{opening}_wc{wc1}.parquet"
                if not p.exists():
                    missing.append(p.name)
                    continue
                d = load(p)
                wc2 = int(d["wc2"].iloc[0])
                fh2 = int(d["fh2"].iloc[0])
                bb1 = int(d["bb1"].iloc[0])
                bb2 = int(d["bb2"].iloc[0])
                path_total = int(d["final_total"].iloc[0])
                bench_bb1 = int(d.loc[bb1, "bench_points"])
                bench_bb2 = int(d.loc[bb2, "bench_points"])
                # TC picks off this cell's own log
                chipweeks = {wc1, bb1}
                tc1_gw, tc1_pred = None, -1
                for gw in range(1, 20):
                    if gw in chipweeks or gw not in d.index:
                        continue
                    v = cap_pred.get((gw, d.loc[gw, "captain"]), 0)
                    if v > tc1_pred:
                        tc1_gw, tc1_pred = gw, v
                tc1 = int(d.loc[tc1_gw, "captain_bonus"]) if tc1_gw else 0
                tc2 = int(d.loc[bb2, "captain_bonus"])   # biggest DGW = bb2 wk
                chip_total = path_total + bench_bb1 + bench_bb2 + tc1 + tc2
                p10 = int(d.loc[1:10, "points"].sum())
                # anchor deltas vs no-chip baseline (post-WC1 not path-controlled)
                aw = {lbl: window(d, baseline, a) for lbl, a in
                      [("WC1", wc1), ("WC2", wc2), ("FH2", fh2), ("BB2", bb2)]}
                # BB1 question vs the isolated wildcard cell
                wcp = P1 / f"wclog_{tag}_{opening}_wc{wc1}.parquet"
                bb1_cost = bb1_note = None
                if wcp.exists():
                    w = load(wcp)
                    bnd = bb1 - 5
                    pre_f = d.loc[[g for g in d.index if g < bnd], "points"]
                    pre_w = w.loc[[g for g in w.index if g < bnd], "points"]
                    ident = pre_f.reset_index(drop=True).equals(
                        pre_w.reset_index(drop=True))
                    hi = min(bb1 + 5, 27)
                    gws = [g for g in range(bnd, hi + 1)]
                    bb1_cost = int(d.loc[gws, "points"].sum()
                                   - w.loc[gws, "points"].sum())
                    bb1_note = ("prefix-identical" if ident else
                                "PREFIX DIVERGED -- not a clean pair")
                print(f"\n  opening={opening} wc1=GW{wc1}  "
                      f"[wc2={wc2} fh2={fh2} bb1={bb1} bb2={bb2} "
                      f"tc1=GW{tc1_gw} tc2=GW{bb2}]")
                print(f"    path total {path_total} ({path_total - b_total:+d}"
                      f" vs own no-chip baseline {b_total})")
                print(f"    chip reads: BB1 bench +{bench_bb1}  BB2 bench "
                      f"+{bench_bb2}  TC1 +{tc1}  TC2 +{tc2}  -> "
                      f"chip-inclusive {chip_total}  "
                      f"(margin vs fplcache avg {chip_total - AVG_SUM_EXPECT[season]:+d})")
                print(f"    GW1-10 path vs avg manager: {p10 - a10:+d}  "
                      f"(baseline {int(baseline.loc[1:10, 'points'].sum()) - a10:+d})")
                print(f"    W=3 anchor deltas vs no-chip baseline "
                      f"(post-WC1 anchors NOT path-controlled; windows "
                      f"overlap -- never add): "
                      + "  ".join(f"{k} {v:+d}" for k, v in aw.items()))
                if bb1_cost is not None:
                    print(f"    BB1 vs isolated-wildcard pair ({bb1_note}): "
                          f"path cost over [GW{bb1 - 5},GW{min(bb1 + 5, 27)}] "
                          f"{bb1_cost:+d}, bench gain +{bench_bb1}, "
                          f"net {bb1_cost + bench_bb1:+d}")
        print()
    if missing:
        print(f"PARTIAL GRID: {len(missing)} cells missing: "
              + ", ".join(missing))
    print("\nFraming: path totals and chip-inclusive totals are single draws "
          "(sd ~60) -- they identify configs.\nDecisions ride on the paired "
          "windows; n <= 3 seasons per cell, no intervals (>=8 rule).\n"
          "TC2 and BB2 share a week in all three seasons (biggest DGW): both "
          "reads are added per the P4\nconvention, but a real manager plays "
          "only one -- the chip-inclusive figure is optimistic by "
          "min(TC2, BB2 bench).")


if __name__ == "__main__":
    main()
