# measure_teamnews_oracle.py
# Team-news STEP 4 measurement: oracle-minutes run vs the full-system
# reference (fslog_{tag}_base_wc2, reused). Read-only.
#
# Per season:
#   - season total vs reference; margins vs the average manager (path and
#     chip-inclusive, the usual read conventions)
#   - per-gameweek paired delta distribution (the totals may exceed path
#     noise here -- the distribution is the evidence, not the total alone)
#   - transfers differing from the reference, each valued by the E2
#     convention (realized in-vs-out over the next 3 gws) -- attribution
#     after divergence is approximate, stated
#   - captaincy changes and their value (extra armband copy, realized)
#   - how many of the 52 cases the oracle avoided (not owned at that gw /
#     owned but kept out of the XI), and the step-3 per-case value of those
#   - decomposition: per-gw deltas on identical-squad weeks = selection
#     hygiene; differing-squad weeks = the transfer channel; the 52-case
#     channel quoted from the avoidance line. Channels interact -- this is
#     an honest approximation, not an exact accounting.
#
# Usage: uv run python eval/measure_teamnews_oracle.py

import json
import lzma
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
from oracle_minutes import apply_oracle_minutes  # noqa: E402

TN = REPO / "data" / "teamnews"
P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"
SEASONS = ["2023-24", "2024-25", "2025-26"]
SNAP = {"2023-24": (2024, 5, 30), "2024-25": (2025, 5, 30),
        "2025-26": (2026, 5, 30)}
AVG = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}
FORMATIONS = [(d, m, f) for d, m, f in product(range(3, 6), range(2, 6),
                                               range(1, 4)) if d + m + f == 10]


def load(path):
    d = pd.read_parquet(path)
    d["elements"] = d["elements"].map(json.loads)
    d["all_transfers"] = d["all_transfers"].map(
        lambda x: json.loads(x) if isinstance(x, str) else x)
    return d.set_index("gw")


def chip_incl(d, bb1, bb2, wc1, own_cap_pred):
    total = int(d["final_total"].iloc[0])
    tc1_gw, v = None, -1
    for gw in range(1, 20):
        if gw in (wc1, bb1) or gw not in d.index:
            continue
        p = own_cap_pred.get((gw, d.loc[gw, "captain"]), 0)
        if p > v:
            tc1_gw, v = gw, p
    return (total + int(d.loc[bb1, "bench_points"])
            + int(d.loc[bb2, "bench_points"])
            + int(d.loc[bb2, "captain_bonus"])
            + (int(d.loc[tc1_gw, "captain_bonus"]) if tc1_gw else 0))


def main():
    cases = pd.read_parquet(TN / "case_list.parquet")
    vals = pd.read_parquet(TN / "case_values.parquet")
    case_val = vals.set_index(["season", "gw", "player"])["value"]
    for season in SEASONS:
        tag = season.replace("-", "_")
        o = load(TN / f"oraclelog_{tag}.parquet")
        r = load(P1 / f"fslog_{tag}_base_wc2.parquet")
        bb1, bb2 = int(r["bb1"].iloc[0]), int(r["bb2"].iloc[0])
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "name",
                                      "position", "e_points", "e_minutes",
                                      "minutes", "actual_points", "pts_appear",
                                      "pts_goals", "pts_assists", "pts_cs",
                                      "pts_dc", "pts_saves", "pts_conceded",
                                      "pts_cards", "exp_bonus", "p_cs",
                                      "p_dc_hit"])
        act = wf.drop_duplicates(subset=["gw", "element"]).copy()
        act["actual_points"] = pd.to_numeric(act["actual_points"],
                                             errors="coerce").fillna(0)
        pts = act.set_index(["gw", "element"])["actual_points"]
        nm2el = wf.drop_duplicates("element").set_index("name")["element"].to_dict()
        cap_pred = {(int(x.gw), x.name): float(x.e_points or 0)
                    for x in wf[wf["cutoff"] == wf["gw"]].itertuples()}
        owf = apply_oracle_minutes(wf)
        oown = owf[owf["cutoff"] == owf["gw"]]

        gws = sorted(set(o.index) & set(r.index))
        diffs = pd.Series({g: int(o.loc[g, "points"] - r.loc[g, "points"])
                           for g in gws})
        same_squad = {g: set(o.loc[g, "elements"]) == set(r.loc[g, "elements"])
                      for g in gws}
        sel_hyg = sum(v for g, v in diffs.items() if same_squad[g])
        tr_chan = sum(v for g, v in diffs.items() if not same_squad[g])

        # transfers differing, valued (E2: realized in-vs-out over next 3 gws)
        n_diff, tr_val, examples = 0, 0.0, []
        for g in gws:
            ot = {tuple(t) for t in o.loc[g, "all_transfers"]}
            rt = {tuple(t) for t in r.loc[g, "all_transfers"]}
            for out_e, in_e in ot - rt:
                gain = sum(float(pts.get((gg, in_e), 0))
                           - float(pts.get((gg, out_e), 0))
                           for gg in range(g, min(g + 3, 39)))
                n_diff += 1
                tr_val += gain
                examples.append((g, out_e, in_e, gain))

        # captaincy changes
        cap_n, cap_val = 0, 0.0
        for g in gws:
            co, cr = o.loc[g, "captain"], r.loc[g, "captain"]
            if co != cr:
                cap_n += 1
                cap_val += float(pts.get((g, nm2el.get(co, -1)), 0)) \
                    - float(pts.get((g, nm2el.get(cr, -1)), 0))

        # 52-case avoidance: not owned, or owned-but-out-of-oracle-XI
        cs = cases[cases["season"] == season]
        avoided_own, avoided_xi, held_started, aval = 0, 0, 0, 0.0
        for _, c in cs.iterrows():
            g, e = int(c["gw"]), int(c["element"])
            if g not in o.index:
                continue
            squad = set(o.loc[g, "elements"])
            if e not in squad:
                avoided_own += 1
                aval += float(case_val.get((season, g, c["player"]), 0))
                continue
            og = oown[oown["gw"] == g].set_index("element")
            ep = {x: float(og.loc[x, "e_points"]) if x in og.index else 0.0
                  for x in squad}
            posmap = wf.drop_duplicates("element").set_index("element")["position"]
            sq = pd.DataFrame([{"element": x, "position": posmap[x],
                                "e_points": ep[x]} for x in squad])
            by = {p: sq[sq["position"] == p].sort_values("e_points",
                                                         ascending=False)
                  for p in ("GK", "DEF", "MID", "FWD")}
            best, bv = None, -1e18
            for dd, mm, ff in FORMATIONS:
                if len(by["DEF"]) < dd or len(by["MID"]) < mm \
                        or len(by["FWD"]) < ff:
                    continue
                xi = pd.concat([by["GK"].head(1), by["DEF"].head(dd),
                                by["MID"].head(mm), by["FWD"].head(ff)])
                if xi["e_points"].sum() > bv:
                    best, bv = xi, xi["e_points"].sum()
            if e in set(best["element"]):
                held_started += 1
            else:
                avoided_xi += 1
                aval += float(case_val.get((season, g, c["player"]), 0))

        ot_, rt_ = int(o["final_total"].iloc[0]), int(r["final_total"].iloc[0])
        oc = chip_incl(o, bb1, bb2, 2, cap_pred)
        rc = chip_incl(r, bb1, bb2, 2, cap_pred)
        q = np.percentile(diffs.values, [0, 25, 50, 75, 100])
        print("=" * 92)
        print(f"SEASON {season}")
        print("=" * 92)
        print(f"  totals: oracle {ot_} vs ref {rt_}  (delta {ot_ - rt_:+d}); "
              f"chip-incl {oc} vs {rc}; margins vs avg "
              f"{oc - AVG[season]:+d} vs {rc - AVG[season]:+d}")
        print(f"  per-gw delta: min {q[0]:+.0f} q25 {q[1]:+.0f} med "
              f"{q[2]:+.0f} q75 {q[3]:+.0f} max {q[4]:+.0f}; "
              f"positive weeks {int((diffs > 0).sum())}/{len(diffs)}, "
              f"negative {int((diffs < 0).sum())}")
        print(f"  transfers differing (oracle-only): {n_diff}, E2 value "
              f"{tr_val:+.0f}; captain changed {cap_n} wks, value "
              f"{cap_val:+.0f}")
        print(f"  52-case: avoided-by-ownership {avoided_own}, "
              f"avoided-in-XI {avoided_xi}, still started {held_started}; "
              f"step-3 value of avoided {aval:+.1f}")
        print(f"  decomposition of path delta {ot_ - rt_:+d}: identical-"
              f"squad weeks (selection hygiene) {sel_hyg:+d}, differing-"
              f"squad weeks (squad/transfer channel) {tr_chan:+d}")
        top = sorted(examples, key=lambda x: -abs(x[3]))[:5]
        nmmap = wf.drop_duplicates("element").set_index("element")["name"]
        for g, oe, ie, gain in top:
            print(f"    GW{g}: {nmmap.get(oe, oe)} -> {nmmap.get(ie, ie)} "
                  f"({gain:+.0f} over 3 gws)")
        print()


if __name__ == "__main__":
    main()
