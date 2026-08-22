# measure_teamnews_knowable.py
# Team-news STEP 5 measurement: arms A (step-0 oracle), B (structurally
# knowable), C (Guardian-reported) vs the full-system reference, alongside
# the step-4 full-horizon oracle. Read-only; all runs reused from disk.
# Usage: uv run python eval/measure_teamnews_knowable.py

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
TN = REPO / "data" / "teamnews"
P1 = REPO / "data" / "p1"
SEASONS = ["2023-24", "2024-25", "2025-26"]
AVG = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}
ARMS = [("full (step 4)", "oraclelog_{t}.parquet"),
        ("A step0-only", "oraclelog_{t}_A.parquet"),
        ("B knowable", "oraclelog_{t}_B.parquet"),
        ("C reported", "oraclelog_{t}_C.parquet")]


def load(path):
    d = pd.read_parquet(path)
    d["elements"] = d["elements"].map(json.loads)
    d["all_transfers"] = d["all_transfers"].map(
        lambda x: json.loads(x) if isinstance(x, str) else x)
    return d.set_index("gw")


def chip_incl(d, bb1, bb2, wc1, cap_pred):
    """Chip-inclusive total, the standing read convention (BB1+BB2 bench,
    TC2 at the BB2 week, TC1 at the predicted-captain peak). cap_pred is the
    BASE model's own-cutoff predictions for every arm, so the convention is
    uniform across arms."""
    total = int(d["final_total"].iloc[0])
    tc1_gw, v = None, -1
    for gw in range(1, 20):
        if gw in (wc1, bb1) or gw not in d.index:
            continue
        p = cap_pred.get((gw, d.loc[gw, "captain"]), 0)
        if p > v:
            tc1_gw, v = gw, p
    return (total + int(d.loc[bb1, "bench_points"])
            + int(d.loc[bb2, "bench_points"])
            + int(d.loc[bb2, "captain_bonus"])
            + (int(d.loc[tc1_gw, "captain_bonus"]) if tc1_gw else 0))


def main():
    cases = pd.read_parquet(TN / "case_list.parquet")
    full_delta = {}
    print(f"{'season':8s} {'arm':14s} {'path':>5s} {'Δref':>5s} "
          f"{'chip':>5s} {'Δref':>5s} {'vsAvg':>5s} "
          f"{'%of4':>5s} {'med':>4s} {'q25/q75':>9s} {'+wk':>4s} "
          f"{'trf≠':>4s} {'E2':>5s} {'capΔ':>4s} {'capval':>6s} "
          f"{'52own':>5s}")
    for season in SEASONS:
        tag = season.replace("-", "_")
        r = load(P1 / f"fslog_{tag}_base_wc2.parquet")
        rt = int(r["final_total"].iloc[0])
        bb1, bb2 = int(r["bb1"].iloc[0]), int(r["bb2"].iloc[0])
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "name",
                                      "e_points", "actual_points"])
        cap_pred = {(int(x.gw), x.name): float(x.e_points or 0)
                    for x in wf[wf["cutoff"] == wf["gw"]].itertuples()}
        rc = chip_incl(r, bb1, bb2, 2, cap_pred)
        act = wf.drop_duplicates(subset=["gw", "element"]).copy()
        act["actual_points"] = pd.to_numeric(act["actual_points"],
                                             errors="coerce").fillna(0)
        pts = act.set_index(["gw", "element"])["actual_points"]
        nm2el = wf.drop_duplicates("element").set_index("name")["element"].to_dict()
        cs = cases[cases["season"] == season]
        for label, patt in ARMS:
            p = TN / patt.format(t=tag)
            if not p.exists():
                print(f"{season:8s} {label:14s} MISSING {p.name}")
                continue
            d = load(p)
            t = int(d["final_total"].iloc[0])
            gws = sorted(set(d.index) & set(r.index))
            diffs = np.array([int(d.loc[g, "points"] - r.loc[g, "points"])
                              for g in gws])
            n_tr, e2 = 0, 0.0
            for g in gws:
                ot = {tuple(x) for x in d.loc[g, "all_transfers"]}
                rtr = {tuple(x) for x in r.loc[g, "all_transfers"]}
                for oe, ie in ot - rtr:
                    n_tr += 1
                    e2 += sum(float(pts.get((gg, ie), 0))
                              - float(pts.get((gg, oe), 0))
                              for gg in range(g, min(g + 3, 39)))
            cap_n, cap_v = 0, 0.0
            for g in gws:
                co, cr = d.loc[g, "captain"], r.loc[g, "captain"]
                if co != cr:
                    cap_n += 1
                    cap_v += float(pts.get((g, nm2el.get(co, -1)), 0)) \
                        - float(pts.get((g, nm2el.get(cr, -1)), 0))
            avoided = sum(1 for _, c in cs.iterrows()
                          if int(c["gw"]) in d.index
                          and int(c["element"])
                          not in set(d.loc[int(c["gw"]), "elements"]))
            tc = chip_incl(d, bb1, bb2, 2, cap_pred)
            if label.startswith("full"):
                full_delta[season] = tc - rc
            frac = (100 * (tc - rc) / full_delta[season]
                    if full_delta.get(season) else float("nan"))
            q = np.percentile(diffs, [25, 50, 75])
            print(f"{season:8s} {label:14s} {t:5d} {t - rt:+5d} "
                  f"{tc:5d} {tc - rc:+5d} {tc - AVG[season]:+5d} "
                  f"{frac:4.0f}% {q[1]:+4.0f} {q[0]:+4.0f}/{q[2]:+4.0f} "
                  f"{int((diffs > 0).sum()):3d} {n_tr:4d} {e2:+5.0f} "
                  f"{cap_n:4d} {cap_v:+6.0f} {avoided:4d}/{len(cs)}")
        print(f"{season:8s} {'reference':14s} {rt:5d} {'':>5s} {rc:5d} "
              f"{'':>5s} {rc - AVG[season]:+5d}")
        print()
    print("Columns: Δref = path delta vs reference; %of4 = share of the "
          "step-4 full-oracle delta surviving;\nmed & q25/q75 = per-gw "
          "paired delta distribution; +wk = positive weeks of 38; trf≠/E2 = "
          "differing\ntransfers and their gross 3-gw value (overlapping, "
          "not additive); capΔ/capval = changed armbands\nand realized "
          "value; 52own = of the season's cases not owned at the case week."
          "\nFraming: single draws; the distributions are the evidence.")


if __name__ == "__main__":
    main()
