# measure_p1_opening.py
# P1 Step 1 measurement -- opening squad with a horizon (interim plan sec. 4).
# Reads the paired decision logs written by eval/run_p1_opening.py and reports,
# per season:
#   1. the GW1 fifteen before/after, with e_points at each horizon step
#   2. capture of the best-available 15 in GW1-7 (and later eras for shape)
#   3. points per gameweek GW1-7 vs the FPL average manager that week
#   4. survival of the GW1 fifteen to GW8 and GW15
#   5. season totals under the STANDARD FRAMING ONLY (identify, never evidence:
#      path sd ~60, M1 failed -- a total cannot rank arms)
#
# Capture definition (calibrated 2026-08-20 against Logs/coldstart_log.md,
# whose original script is lost): best-available 15 = raw top-15 by actual
# points that gameweek (reproduces the log's 174.3 / 180.1 exactly); capture =
# sum of the owned 15's actual points over the era / sum of the best-15's
# actual points over the era (the log's own 39.86/174.3 = 22.9% ~ "22.7%").
# The overlap-count variant lands at ~7% and is NOT the recorded metric.
#
# Average manager: per-gameweek events[].average_entry_score from a POST-SEASON
# fplcache snapshot picked by date window (too late reads the next season's
# zeroed bootstrap). Season sums are asserted against the season-totals index's
# fplcache-derived figures (2003 / 2008 / 1895) so a wrong snapshot fails loudly.
#
# Usage: uv run python eval/measure_p1_opening.py

import json
import lzma
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"

SEASONS = ["2023-24", "2024-25", "2025-26"]
SNAP = {"2023-24": (2024, 5, 30), "2024-25": (2025, 5, 30),
        "2025-26": (2026, 5, 30)}
AVG_SUM_EXPECT = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}
ERAS = [(1, 7), (8, 14), (15, 38)]


def avg_manager(season):
    y, m, d = SNAP[season]
    snap = sorted((CACHE / str(y) / str(m) / str(d)).glob("*.json.xz"))[-1]
    with lzma.open(snap) as f:
        events = json.load(f)["events"]
    assert len(events) == 38 and all(e["finished"] for e in events), \
        f"{season}: bad snapshot {snap}"
    per_gw = {e["id"]: e["average_entry_score"] for e in events}
    total = sum(per_gw.values())
    assert total == AVG_SUM_EXPECT[season], \
        f"{season}: avg-manager sum {total} != {AVG_SUM_EXPECT[season]}"
    return per_gw


def load_logs(season):
    tag = season.replace("-", "_")
    logs = {}
    for arm in ("base", "p1"):
        p = P1 / f"p1log_{tag}_{arm}.parquet"
        if not p.exists():
            raise FileNotFoundError(f"missing {p} -- run eval/run_p1_opening.py")
        d = pd.read_parquet(p)
        d["elements"] = d["elements"].map(json.loads)
        logs[arm] = d
    # the arms must differ ONLY on the P1 stamp
    for col in ("horizon", "decay", "bench_boost_aware", "wf_file"):
        vb, vp = logs["base"][col].unique(), logs["p1"][col].unique()
        assert len(vb) == 1 and len(vp) == 1 and vb[0] == vp[0], \
            f"{season}: arms differ on {col}: {vb} vs {vp}"
    assert logs["base"]["opening_horizon_active"].unique().tolist() == [False]
    assert logs["p1"]["opening_horizon_active"].unique().tolist() == [True]
    return logs


def actuals(season):
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["gw", "element", "actual_points"])
    act = wf.drop_duplicates(subset=["gw", "element"]).copy()
    act["actual_points"] = pd.to_numeric(act["actual_points"],
                                         errors="coerce").fillna(0)
    return act


def gw1_table(season, logs):
    tag = season.replace("-", "_")
    wf = pd.read_parquet(
        REPO / "data" / f"walkforward_h6_{tag}.parquet",
        columns=["cutoff", "gw", "element", "name", "position", "e_points"])
    c1 = wf[wf["cutoff"] == 1]
    steps = (c1.pivot_table(index=["element", "name", "position"],
                            columns="gw", values="e_points", aggfunc="sum")
               .rename(columns=lambda g: f"gw{g}").reset_index())
    sq = {arm: set(logs[arm].loc[logs[arm]["gw"] == 1, "elements"].iloc[0])
          for arm in ("base", "p1")}
    t = steps[steps["element"].isin(sq["base"] | sq["p1"])].copy()
    t["in"] = t["element"].map(
        lambda e: "both" if e in sq["base"] and e in sq["p1"]
        else ("base only" if e in sq["base"] else "P1 only"))
    gw_cols = [c for c in t.columns if c.startswith("gw")]
    t["h6_sum"] = t[gw_cols].sum(axis=1)
    order = {"both": 0, "base only": 1, "P1 only": 2}
    t = t.sort_values(["in", "position", "h6_sum"],
                      key=lambda s: s.map(order) if s.name == "in" else s,
                      ascending=[True, True, False])
    return t[["name", "position", "in"] + gw_cols + ["h6_sum"]], sq


def capture(act, squads_by_gw, lo, hi):
    num = den = 0.0
    for gw in range(lo, hi + 1):
        if gw not in squads_by_gw:
            continue
        g = act[act["gw"] == gw]
        best = g.nlargest(15, "actual_points")["actual_points"].sum()
        own = g[g["element"].isin(squads_by_gw[gw])]["actual_points"].sum()
        num += own
        den += best
    return num / den if den else float("nan")


def main():
    for season in SEASONS:
        print("=" * 78)
        print(f"SEASON {season}")
        print("=" * 78)
        logs = load_logs(season)
        act = actuals(season)
        avg = avg_manager(season)

        # 1 -- the GW1 fifteen
        t, sq = gw1_table(season, logs)
        changed = 15 - len(sq["base"] & sq["p1"])
        print(f"\nGW1 fifteen (changed players: {changed} of 15)  "
              "e_points by target gameweek, all from GW1's cutoff:")
        print(t.to_string(index=False,
                          float_format=lambda x: f"{x:.2f}"))

        # 2 -- capture of the best-available 15
        print("\ncapture of the best-available 15 "
              "(points-share; see header for definition):")
        for arm in ("base", "p1"):
            squads = {int(r.gw): set(r.elements)
                      for r in logs[arm].itertuples()}
            vals = "   ".join(
                f"GW{lo}-{hi} {capture(act, squads, lo, hi):.1%}"
                for lo, hi in ERAS)
            print(f"  {arm:5s} {vals}")

        # 3 -- points per gameweek GW1-7 vs the average manager
        print("\npoints per gameweek, GW1-7 (avg = FPL average manager):")
        print("  gw   base    p1   avg   base-avg  p1-avg")
        b7 = p7 = a7 = 0
        for gw in range(1, 8):
            b = int(logs["base"].loc[logs["base"]["gw"] == gw, "points"].iloc[0])
            p = int(logs["p1"].loc[logs["p1"]["gw"] == gw, "points"].iloc[0])
            a = avg[gw]
            b7, p7, a7 = b7 + b, p7 + p, a7 + a
            print(f"  {gw:2d}   {b:4d}  {p:4d}  {a:4d}   {b - a:+5d}    {p - a:+5d}")
        print(f"  sum  {b7:4d}  {p7:4d}  {a7:4d}   {b7 - a7:+5d}    {p7 - a7:+5d}"
              f"    (per-gw mean: base {b7/7:.1f}, p1 {p7/7:.1f}, avg {a7/7:.1f})")

        # 4 -- survival of the GW1 fifteen
        print("\nGW1 fifteen still held (of 15):")
        for arm in ("base", "p1"):
            row = {}
            for at in (8, 15):
                held = set(logs[arm].loc[logs[arm]["gw"] == at,
                                         "elements"].iloc[0])
                row[at] = len(sq[arm] & held)
            print(f"  {arm:5s} at GW8: {row[8]:2d}   at GW15: {row[15]:2d}")

        # transfer activity context (GW1-7)
        for arm in ("base", "p1"):
            d = logs[arm]
            e = d[(d["gw"] >= 2) & (d["gw"] <= 7)]
            print(f"  {arm:5s} transfers GW2-7: {int(e['n_transfers'].sum())} "
                  f"(hits {int(e['hit'].sum())}); season: "
                  f"{int(d['n_transfers'].sum())} (hits {int(d['hit'].sum())})")

        # 5 -- season totals, standard framing
        bt = int(logs["base"]["final_total"].iloc[0])
        pt = int(logs["p1"]["final_total"].iloc[0])
        print(f"\nseason totals (STANDARD FRAMING: one draw each from a "
              f"path-noise distribution with sd ~60;\nidentifies the config, "
              f"is NOT evidence between arms): base {bt}, p1 {pt}")
        print()


if __name__ == "__main__":
    main()
