"""Bar item 6 (direction) and the 'deadlines changed' count, as Logs/asof_rebuild_log.md section 9
did: rebuilt armlogs vs the preserved _pre_dcfix ones, same gameweek -- executed transfer set
differing, first divergence, path totals (ex-chip reads), transfers / hits. Plus the rank
endpoint on the ARM frames (both / hmin), new vs _pre_dcfix, at the same definitions as
rank_endpoint.py, to see whether frame-level moves are of the canonical's size."""
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

REPO = Path(r"C:\dev\fpl-copilot")
ARMS = REPO / "data" / "arms"
LOGS = [("2023-24", "gap0_tc2"), ("2023-24", "hmin_gap0"),
        ("2024-25", "gap0_tc2"), ("2024-25", "hmin_gap0"), ("2024-25", "both_gap0"),
        ("2025-26", "gap0_tc2"), ("2025-26", "hmin_gap0_tc2"), ("2025-26", "both_gap0_tc2")]


def tset(v):
    try:
        return tuple(sorted(int(x) for x in v)) if v is not None and len(v) else ()
    except TypeError:
        return (str(v),)


print("season arm | path total pre -> new (delta) | gws with a different executed transfer set (first) | captain differs | transfers/hits pre -> new")
for season, arm in LOGS:
    tag = season.replace("-", "_")
    new = pd.read_parquet(ARMS / f"armlog_{tag}_{arm}.parquet").set_index("gw")
    old = pd.read_parquet(ARMS / f"armlog_{tag}_{arm}_pre_dcfix.parquet").set_index("gw")
    gws = sorted(set(new.index) & set(old.index))
    diff = [g for g in gws if tset(new.loc[g, "transfer_out"]) != tset(old.loc[g, "transfer_out"])
            or tset(new.loc[g, "transfer_in"]) != tset(old.loc[g, "transfer_in"])]
    cap = [g for g in gws if new.loc[g, "captain"] != old.loc[g, "captain"]]
    pt_new, pt_old = int(new["points"].sum()), int(old["points"].sum())
    tr = lambda d: (int(d["n_transfers"].sum()), int(d["hit"].sum()))
    print(f"{season} {arm:14s} | {pt_old} -> {pt_new} ({pt_new - pt_old:+d}) | {len(diff)} of {len(gws)} (first GW{diff[0] if diff else '-'}) | {len(cap)} | {tr(old)} -> {tr(new)}")

print("\nARM FRAMES, rank endpoint new vs _pre_dcfix (top-30 = old frame's top 30 by e_points; starters p_start >= .75):")
for season, arm in [("2025-26", "both"), ("2025-26", "hmin"), ("2024-25", "both"), ("2024-25", "hmin"), ("2023-24", "hmin")]:
    tag = season.replace("-", "_")
    new = pd.read_parquet(REPO / "data" / "arms_gap0" / f"walkforward_h6_{tag}_{arm}.parquet")
    old = pd.read_parquet(REPO / "data" / "arms_gap0" / f"walkforward_h6_{tag}_{arm}_pre_dcfix.parquet")
    key = ["element", "gw", "cutoff"]
    m = old.merge(new[key + ["e_points"]], on=key, suffixes=("_old", "_new"))
    m["d"] = (m["e_points_new"] - m["e_points_old"]).abs()
    m["step"] = m["gw"] - m["cutoff"]
    rows = []
    for (k, st), g in m.groupby(["cutoff", "step"]):
        top = g.nlargest(30, "e_points_old")
        starters = g[g["p_start"] >= 0.75]
        rho = float(spearmanr(top["e_points_old"], top["e_points_new"]).correlation) if len(top) > 2 else float("nan")
        rows.append(dict(cutoff=k, step=st, rho=rho, top30_mean=top["d"].mean(),
                         starters_mean=(starters["d"].mean() if len(starters) else float("nan"))))
    r = pd.DataFrame(rows)
    s0, s1 = r[r["step"] == 0], r[r["step"] >= 1]
    print(f"{season} {arm}: rows {len(old):,}/{len(new):,} matched {len(m):,}; "
          f"step0 rho min {s0['rho'].min():.4f}, starters mean|d| max {s0['starters_mean'].max():.4f}; "
          f"steps1-5 rho min {s1['rho'].min():.4f} (at cutoff {int(s1.loc[s1['rho'].idxmin(), 'cutoff'])} step {int(s1.loc[s1['rho'].idxmin(), 'step'])}), "
          f"starters mean|d| max {s1['starters_mean'].max():.4f}, top30 mean|d| max {s1['top30_mean'].max():.4f}")
