# measure_p5.py
# Measurement for the P5 arms (eval/run_p5.py) against the full-system
# reference cell (fslog_{tag}_base_wc2). Read-only.
#
# The decision log does not persist the XI split, so each week is REPLAYED:
# XI = formation-legal argmax of own-cutoff step-0 (e_points + eps*p_60plus
# when the arm's XI tiebreak is on, eps = optimize.XI_TIEBREAK_WEIGHT);
# captain = argmax e_points within the XI; bench order via the production
# assign_bench_order with scoring.BENCH_ORDER_BY_PLAY set to the arm's gate.
# Fidelity is verified per week against raw_points / bench_points / n_subs /
# captain and reported -- autosub numbers are only quoted at the stated
# match rate.
#
# Reported per season, per arm (ref / bench / xi / both):
#   autosubs fired + points gained from them; final-XI zero-minute slots
#   with no usable sub; bench points left; path total vs the FPL average
#   manager and the chip-inclusive margin (BB1/BB2 bench + TC1/TC2 reads,
#   the measure_full_system convention -- TC2 shares BB2's week, both added,
#   optimistic by min(TC2, BB2 bench)); season total (STANDARD FRAMING);
#   and where each arm first diverged from the reference (squads / points).
#
# Usage: uv run python eval/measure_p5.py

import json
import lzma
import sys
from itertools import product
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
import optimize  # noqa: E402
import scoring  # noqa: E402
from scoring import assign_bench_order, score_gameweek  # noqa: E402

P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"
SEASONS = ["2023-24", "2024-25", "2025-26"]
ARMS = {"ref": (False, False), "bench": (True, False),
        "xi": (False, True), "both": (True, True)}
SNAP = {"2023-24": (2024, 5, 30), "2024-25": (2025, 5, 30),
        "2025-26": (2026, 5, 30)}
AVG_SUM_EXPECT = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}
FORMATIONS = [(d, m, f) for d, m, f in product(range(3, 6), range(2, 6),
                                               range(1, 4)) if d + m + f == 10]
EPS = optimize.XI_TIEBREAK_WEIGHT


def avg_total(season):
    y, m, d = SNAP[season]
    snap = sorted((CACHE / str(y) / str(m) / str(d)).glob("*.json.xz"))[-1]
    with lzma.open(snap) as f:
        events = json.load(f)["events"]
    assert len(events) == 38 and all(e["finished"] for e in events)
    total = sum(e["average_entry_score"] for e in events)
    assert total == AVG_SUM_EXPECT[season]
    return total


def build_squad_frame(elements, own_gw, pos, name, xi_on):
    ep = own_gw.set_index("element")["e_points"].to_dict()
    p60 = own_gw.set_index("element")["p_60plus"].to_dict() \
        if "p_60plus" in own_gw.columns else {}
    ppl = own_gw.set_index("element")["p_play_any"].to_dict() \
        if "p_play_any" in own_gw.columns else {}

    def f(d, e):
        v = d.get(e, 0.0)
        return 0.0 if pd.isna(v) else float(v)

    sq = pd.DataFrame([{"element": e, "position": pos[e],
                        "name": name.get(e, str(e)),
                        "e_points": f(ep, e),
                        "p_60plus": f(p60, e),
                        "p_play_any": f(ppl, e)} for e in elements])
    sq["_sel"] = sq["e_points"] + (EPS * sq["p_60plus"] if xi_on else 0.0)
    by = {p: sq[sq["position"] == p].sort_values("_sel", ascending=False)
          for p in ("GK", "DEF", "MID", "FWD")}
    best, best_v = None, -1e18
    for d, m, fw in FORMATIONS:
        if len(by["DEF"]) < d or len(by["MID"]) < m or len(by["FWD"]) < fw:
            continue
        xi = pd.concat([by["GK"].head(1), by["DEF"].head(d),
                        by["MID"].head(m), by["FWD"].head(fw)])
        if xi["_sel"].sum() > best_v:
            best, best_v = xi, xi["_sel"].sum()
    xi_e = set(best["element"])
    sq["role"] = sq["element"].map(lambda e: "start" if e in xi_e else "bench")
    st = sq[sq["role"] == "start"].sort_values("e_points", ascending=False)
    sq.loc[sq["element"] == st.iloc[0]["element"], "role"] = "CAPTAIN"
    sq.loc[sq["element"] == st.iloc[1]["element"], "role"] = "VICE"
    return assign_bench_order(sq.drop(columns="_sel"))


def main():
    for season in SEASONS:
        tag = season.replace("-", "_")
        avg = avg_total(season)
        wf = pd.read_parquet(
            REPO / "data" / f"walkforward_h6_{tag}.parquet",
            columns=["cutoff", "gw", "element", "name", "position",
                     "e_points", "p_60plus", "p_play_any",
                     "actual_points", "minutes"])
        own = wf[wf["cutoff"] == wf["gw"]]
        act = wf.drop_duplicates(subset=["gw", "element"]).copy()
        act["actual_points"] = pd.to_numeric(act["actual_points"],
                                             errors="coerce").fillna(0)
        act["minutes"] = pd.to_numeric(act["minutes"],
                                       errors="coerce").fillna(0)
        pos = wf.drop_duplicates("element").set_index("element")["position"].to_dict()
        name = wf.drop_duplicates("element").set_index("element")["name"].to_dict()

        print("=" * 96)
        print(f"SEASON {season}   (FPL average manager total {avg})")
        print("=" * 96)
        for arm, (bench_on, xi_on) in ARMS.items():
            p = (P1 / f"fslog_{tag}_base_wc2.parquet" if arm == "ref"
                 else P1 / f"p5log_{tag}_{arm}.parquet")
            if not p.exists():
                print(f"  {arm}: MISSING {p.name}")
                continue
            d = pd.read_parquet(p)
            d["elements"] = d["elements"].map(json.loads)
            d = d.set_index("gw")
            if arm != "ref":
                assert d["bench_order_by_play"].unique().tolist() == [bench_on]
                assert d["xi_tiebreak_p60"].unique().tolist() == [xi_on]
            bb1, bb2 = int(d["bb1"].iloc[0]) if "bb1" in d.columns else None, \
                int(d["bb2"].iloc[0]) if "bb2" in d.columns else None
            if bb1 is None:      # p5 logs carry the schedule in bench_boost_gws
                bb1, bb2 = [int(x) for x in
                            d["bench_boost_gws"].iloc[0].split(",")]
            # replay
            scoring.BENCH_ORDER_BY_PLAY = bench_on
            fid = {"raw": 0, "bench": 0, "subs": 0, "cap": 0}
            subs_n = sub_pts = holes = 0
            try:
                for gw in sorted(d.index):
                    row = d.loc[gw]
                    own_gw = own[own["gw"] == gw]
                    sq = build_squad_frame(list(row["elements"]), own_gw,
                                           pos, name, xi_on)
                    a = act[act["gw"] == gw][["element", "minutes",
                                              "actual_points"]] \
                        .rename(columns={"actual_points": "total_points"})
                    res = score_gameweek(sq, a, transfers_made=0,
                                         free_transfers=15)
                    fid["raw"] += int(res["raw_points"] == row["raw_points"])
                    fid["bench"] += int(res["bench_points"] == row["bench_points"])
                    fid["subs"] += int(len(res["subs_made"]) == row["n_subs"])
                    cap_name = sq.loc[sq["role"] == "CAPTAIN", "name"].iloc[0]
                    fid["cap"] += int(cap_name == row["captain"])
                    mins = dict(zip(a["element"], a["minutes"]))
                    pts = dict(zip(a["element"], a["total_points"]))
                    subs_n += len(res["subs_made"])
                    sub_pts += sum(pts.get(i, 0) for _, i in res["subs_made"])
                    holes += len([e for e in res["final_xi"]
                                  if mins.get(e, 0) == 0])
            finally:
                scoring.BENCH_ORDER_BY_PLAY = False
            total = int(d["final_total"].iloc[0])
            bench_left = int(d["bench_points"].sum())
            chip = total + int(d.loc[bb1, "bench_points"]) \
                + int(d.loc[bb2, "bench_points"]) \
                + int(d.loc[bb2, "captain_bonus"])
            # TC1: argmax predicted captain pts GW1-19 excl chip weeks (2, bb1)
            cap_pred = {}
            for r in own.itertuples():
                cap_pred[(int(r.gw), r.name)] = float(r.e_points or 0)
            tc1_gw, tc1_v = None, -1
            for gw in range(1, 20):
                if gw in (2, bb1) or gw not in d.index:
                    continue
                v = cap_pred.get((gw, d.loc[gw, "captain"]), 0)
                if v > tc1_v:
                    tc1_gw, tc1_v = gw, v
            chip += int(d.loc[tc1_gw, "captain_bonus"]) if tc1_gw else 0
            div_sq = int(d["first_squad_divergence"].iloc[0]) \
                if "first_squad_divergence" in d.columns else 0
            div_pt = int(d["first_points_divergence"].iloc[0]) \
                if "first_points_divergence" in d.columns else 0
            div = (f"  div: squads GW{div_sq if div_sq > 0 else '-'} "
                   f"points GW{div_pt if div_pt > 0 else '-'}"
                   if arm != "ref" else "")
            print(f"  {arm:5s} subs fired {subs_n:2d}, sub pts {sub_pts:3.0f}"
                  f", dead-XI slots {holes}, bench left {bench_left:3d} | "
                  f"path {total} (vs avg {total - avg:+d}), chip-incl {chip}"
                  f" (vs avg {chip - avg:+d})"
                  f" | fidelity {fid['raw']}/38 {fid['bench']}/38 "
                  f"{fid['subs']}/38 {fid['cap']}/38{div}")
        print()
    print("Framing: totals are single draws (sd ~60), identify only. The "
          "bench arm shares the reference's\nsquad path exactly (asserted at "
          "run time), so its deltas are noise-free autosub resolution.\n"
          "The xi/both arms may diverge at tied decisions -- deltas after "
          "the divergence gw carry path noise.")


if __name__ == "__main__":
    main()
