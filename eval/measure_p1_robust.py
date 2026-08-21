# measure_p1_robust.py
# P1 Step 2 measurement -- three-arm comparison on the data/p1/ decision logs:
#   base : single-gameweek GW1 seed          (opening_horizon F, robust F)
#   p1   : Step-1 horizon GW1 seed           (opening_horizon T, robust F)
#   p2   : Step-2 scenario-robust GW1 seed   (opening_horizon F, robust T)
# The base and p1 logs are REUSED from the Step-1 runs, not re-simulated.
#
# Stamp discipline: p2 vs base must differ ONLY on opening_robust_active.
# p2 vs p1 differs on both opening stamps by construction (each arm is one
# strategy); that is inherent to a three-way design and is asserted exactly.
#
# Capture metric and average-manager source: identical to
# eval/measure_p1_opening.py (see its header for the calibration note).
# Fodder metric: squad-gameweeks holding a player with own-cutoff step-0
# e_minutes < 10, as in the P1 log section 5 analysis.
#
# Usage: uv run python eval/measure_p1_robust.py

import json
import lzma
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"

SEASONS = ["2023-24", "2024-25", "2025-26"]
ARMS = ["base", "p1", "p2"]
SNAP = {"2023-24": (2024, 5, 30), "2024-25": (2025, 5, 30),
        "2025-26": (2026, 5, 30)}
AVG_SUM_EXPECT = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}
ERAS = [(1, 7), (8, 14), (15, 38)]
STAMPS = {"base": (False, False), "p1": (True, False), "p2": (False, True)}


def avg_manager(season):
    y, m, d = SNAP[season]
    snap = sorted((CACHE / str(y) / str(m) / str(d)).glob("*.json.xz"))[-1]
    with lzma.open(snap) as f:
        events = json.load(f)["events"]
    assert len(events) == 38 and all(e["finished"] for e in events)
    per_gw = {e["id"]: e["average_entry_score"] for e in events}
    assert sum(per_gw.values()) == AVG_SUM_EXPECT[season]
    return per_gw


def load_logs(season):
    tag = season.replace("-", "_")
    logs = {}
    for arm in ARMS:
        p = P1 / f"p1log_{tag}_{arm}.parquet"
        if not p.exists():
            raise FileNotFoundError(f"missing {p}")
        d = pd.read_parquet(p)
        d["elements"] = d["elements"].map(json.loads)
        logs[arm] = d
    for col in ("horizon", "decay", "bench_boost_aware", "wf_file"):
        vals = {arm: logs[arm][col].unique() for arm in ARMS}
        assert all(len(v) == 1 for v in vals.values()) and \
            len({v[0] for v in vals.values()}) == 1, f"{season}: {col} {vals}"
    for arm in ARMS:
        h = logs[arm]["opening_horizon_active"].unique().tolist()
        r = (logs[arm]["opening_robust_active"].unique().tolist()
             if "opening_robust_active" in logs[arm].columns else [False])
        assert (h, r) == ([STAMPS[arm][0]], [STAMPS[arm][1]]), \
            f"{season} {arm}: stamps horizon={h} robust={r}"
    return logs


def wf_frames(season):
    tag = season.replace("-", "_")
    wf = pd.read_parquet(
        REPO / "data" / f"walkforward_h6_{tag}.parquet",
        columns=["cutoff", "gw", "element", "name", "position",
                 "e_points", "e_minutes", "actual_points"])
    act = wf.drop_duplicates(subset=["gw", "element"]).copy()
    act["actual_points"] = pd.to_numeric(act["actual_points"],
                                         errors="coerce").fillna(0)
    own = wf[wf["cutoff"] == wf["gw"]].copy()
    return wf, act, own


def capture(act, squads, lo, hi):
    num = den = 0.0
    for gw in range(lo, hi + 1):
        if gw not in squads:
            continue
        g = act[act["gw"] == gw]
        den += g.nlargest(15, "actual_points")["actual_points"].sum()
        num += g[g["element"].isin(squads[gw])]["actual_points"].sum()
    return num / den if den else float("nan")


def main():
    for season in SEASONS:
        print("=" * 78)
        print(f"SEASON {season}")
        print("=" * 78)
        logs = load_logs(season)
        wf, act, own = wf_frames(season)
        avg = avg_manager(season)
        nm = wf.drop_duplicates("element").set_index("element")["name"]

        sq = {arm: set(logs[arm].loc[logs[arm]["gw"] == 1, "elements"].iloc[0])
              for arm in ARMS}
        c1 = wf[wf["cutoff"] == 1]
        steps = (c1.pivot_table(index=["element", "name", "position"],
                                columns="gw", values="e_points",
                                aggfunc="sum")
                   .rename(columns=lambda g: f"gw{g}").reset_index())
        gw_cols = [c for c in steps.columns if c.startswith("gw")]
        steps["h6_sum"] = steps[gw_cols].sum(axis=1)

        print(f"\nGW1 fifteen -- p2 vs base: shares {len(sq['p2'] & sq['base'])}"
              f"/15;  p2 vs p1: shares {len(sq['p2'] & sq['p1'])}/15")
        allsq = sq["base"] | sq["p1"] | sq["p2"]
        t = steps[steps["element"].isin(allsq)].copy()
        t["arms"] = t["element"].map(
            lambda e: "".join(a[0].upper() if e in sq[a] else "-"
                              for a in ARMS))
        t = t.sort_values(["arms", "position", "h6_sum"],
                          ascending=[False, True, False])
        print("(arms column: B=base, P=p1, 2=p2)")
        print(t[["name", "position", "arms"] + gw_cols + ["h6_sum"]]
              .to_string(index=False, float_format=lambda x: f"{x:.2f}"))

        print("\ncapture of the best-available 15 (points-share):")
        for arm in ARMS:
            squads = {int(r.gw): set(r.elements)
                      for r in logs[arm].itertuples()}
            print(f"  {arm:5s} " + "   ".join(
                f"GW{lo}-{hi} {capture(act, squads, lo, hi):.1%}"
                for lo, hi in ERAS))

        print("\npoints per gameweek GW1-7 (avg = FPL average manager):")
        print("  gw   base    p1    p2   avg    b-avg  p1-avg  p2-avg")
        tot = {arm: 0 for arm in ARMS}
        a7 = 0
        for gw in range(1, 8):
            pts = {arm: int(logs[arm].loc[logs[arm]["gw"] == gw,
                                          "points"].iloc[0]) for arm in ARMS}
            a = avg[gw]
            a7 += a
            for arm in ARMS:
                tot[arm] += pts[arm]
            print(f"  {gw:2d}   {pts['base']:4d}  {pts['p1']:4d}  "
                  f"{pts['p2']:4d}  {a:4d}   {pts['base']-a:+5d}  "
                  f"{pts['p1']-a:+5d}  {pts['p2']-a:+5d}")
        print(f"  sum  {tot['base']:4d}  {tot['p1']:4d}  {tot['p2']:4d}  "
              f"{a7:4d}   {tot['base']-a7:+5d}  {tot['p1']-a7:+5d}  "
              f"{tot['p2']-a7:+5d}")

        print("\nGW1 fifteen still held / bench:")
        for arm in ARMS:
            held = {}
            for at in (8, 15):
                h = set(logs[arm].loc[logs[arm]["gw"] == at,
                                      "elements"].iloc[0])
                held[at] = len(sq[arm] & h)
            fod = 0
            for r in logs[arm].itertuples():
                em = own[own["gw"] == r.gw].set_index("element")["e_minutes"]
                fod += sum(1 for e in r.elements
                           if float(em.get(e, 0) if pd.notna(em.get(e, 0))
                                    else 0) < 10)
            bp = int(logs[arm]["bench_points"].sum())
            print(f"  {arm:5s} at GW8: {held[8]:2d}  at GW15: {held[15]:2d}  "
                  f"| fodder squad-gameweeks: {fod:3d}  "
                  f"season bench points: {bp}")

        totals = {arm: int(logs[arm]["final_total"].iloc[0]) for arm in ARMS}
        print(f"\nseason totals (STANDARD FRAMING: one draw each, path sd ~60;"
              f" identifies the config,\nis NOT evidence between arms): "
              + "  ".join(f"{arm} {totals[arm]}" for arm in ARMS))
        print()


if __name__ == "__main__":
    main()
