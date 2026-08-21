# measure_p1_wc_grid.py
# Measurement for the WC1 x opening grid (eval/run_p1_wc_grid.py).
# Tolerates a partial grid: missing cells are reported, not fatal, so this
# can run mid-grid for an incremental view.
#
# Per cell (season, opening, wc week):
#   - W-window paired delta at the wildcard anchor vs that opening's own
#     no-wildcard baseline (data/p1/p1log_{tag}_{opening}.parquet), W in
#     {1,2,3,5} -- the P4 log section 4 convention (prefix identity was
#     asserted per run at simulation time).
#   - points GW1-10 vs the FPL average manager (fplcache post-season
#     snapshot, sums asserted vs the season-totals index figures)
#   - survival of that run's GW1 fifteen at GW8 and GW15
#   - season total (STANDARD FRAMING: identifies the config, never evidence)
# Then the two study questions: best week consistency across seasons, and
# whether the best week differs between the two openings.
#
# No intervals anywhere: n_active per (week, W) cell is <= 3 seasons,
# below the >= 8 rule.
#
# Usage: uv run python eval/measure_p1_wc_grid.py

import json
import lzma
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"

SEASONS = ["2023-24", "2024-25", "2025-26"]
OPENINGS = ["base", "p1"]
WEEKS = [2, 3, 4, 5, 6, 7, 8]
WINDOWS = [1, 2, 3, 5]
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


def load(path, opening=None):
    d = pd.read_parquet(path)
    d["elements"] = d["elements"].map(json.loads)
    if opening is not None:
        assert d["opening_horizon_active"].unique().tolist() == \
            [opening == "p1"], f"{path.name}: wrong opening stamp"
    assert int(d["horizon"].iloc[0]) == 6
    assert float(d["decay"].iloc[0]) == 0.45
    return d.set_index("gw")


def main():
    missing = []
    best = {}          # (season, opening) -> {W: (best delta, best week)}
    for season in SEASONS:
        tag = season.replace("-", "_")
        avg = avg_manager(season)
        a10 = sum(avg[g] for g in range(1, 11))
        print("=" * 96)
        print(f"SEASON {season}")
        print("=" * 96)
        for opening in OPENINGS:
            baseline = load(P1 / f"p1log_{tag}_{opening}.parquet", opening)
            b_total = int(baseline["final_total"].iloc[0])
            b10 = int(baseline.loc[1:10, "points"].sum())
            rows = []
            for wc in WEEKS:
                p = P1 / f"wclog_{tag}_{opening}_wc{wc}.parquet"
                if not p.exists():
                    missing.append(p.name)
                    continue
                d = load(p, opening)
                gws = sorted(d.index)
                deltas = {}
                for W in WINDOWS:
                    win = [g for g in range(wc, wc + W) if g in gws]
                    deltas[W] = int(d.loc[win, "points"].sum()
                                    - baseline.loc[win, "points"].sum())
                g1 = set(d.loc[1, "elements"])
                surv8 = len(g1 & set(d.loc[8, "elements"]))
                surv15 = len(g1 & set(d.loc[15, "elements"]))
                p10 = int(d.loc[1:10, "points"].sum())
                rows.append({"wc": wc, **{f"W{W}": deltas[W]
                                          for W in WINDOWS},
                             "gw1_10_vs_avg": p10 - a10,
                             "surv8": surv8, "surv15": surv15,
                             "total": int(d["final_total"].iloc[0])})
            if not rows:
                print(f"\n  opening={opening}: no cells on disk yet")
                continue
            t = pd.DataFrame(rows)
            print(f"\n  opening={opening}  (baseline: total {b_total}, "
                  f"GW1-10 vs avg {b10 - a10:+d}, no wildcard)")
            print("  " + t.to_string(index=False).replace("\n", "\n  "))
            for W in WINDOWS:
                i = t[f"W{W}"].idxmax()
                best.setdefault((season, opening), {})[W] = \
                    (int(t.loc[i, f"W{W}"]), int(t.loc[i, "wc"]))
        print()

    print("=" * 96)
    print("QUESTION 1 -- is any wildcard week best consistently across "
          "seasons?  (best week @ each W, delta in brackets)")
    print("=" * 96)
    for opening in OPENINGS:
        print(f"\n  opening={opening}")
        print("  season     " + "   ".join(f"W={W}" for W in WINDOWS))
        for season in SEASONS:
            b = best.get((season, opening), {})
            cells = "   ".join(
                f"GW{b[W][1]} ({b[W][0]:+d})" if W in b else "--"
                for W in WINDOWS)
            print(f"  {season}  {cells}")

    print()
    print("=" * 96)
    print("QUESTION 2 -- does the best week differ between openings? "
          "(W=3 argmax per cell)")
    print("=" * 96)
    for season in SEASONS:
        cells = []
        for opening in OPENINGS:
            b = best.get((season, opening), {}).get(3)
            cells.append(f"{opening}: " + (f"GW{b[1]} ({b[0]:+d})"
                                           if b else "--"))
        print(f"  {season}   " + "    ".join(cells))

    if missing:
        print(f"\nPARTIAL GRID: {len(missing)} cells missing: "
              + ", ".join(missing))
    print("\nFraming: paired W-window deltas vs each opening's own baseline; "
          "n per cell <= 3 seasons, no intervals\n(>=8 rule). Season totals "
          "identify configs only; path sd ~60 -- never evidence between arms.")


if __name__ == "__main__":
    main()
