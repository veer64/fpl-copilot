#!/usr/bin/env python
"""
Cold start: which component is actually failing in GW1-7?

The headline is 43.0 pts/gw against 54.3 from GW8. But a raw gap could just mean
early gameweeks score less, so the first thing here is the control -- what the
baselines did over the same split. They say the opposite: a hindsight squad scores
MORE early (73.9 vs 65.7), so the available points are higher in GW1-7 and the
model's deficit is worse than the headline suggests.

Then the points model is taken apart. `e_points` is a sum of components, each with a
realised counterpart, so predicted and actual can be compared component by component
and split by cold start. Ranking quality is reported alongside bias because selection
is by rank: a component can be badly biased and still pick the right players, and a
component can be unbiased and still rank them wrongly.

Usage:
    uv run python eval/analyse_coldstart.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# Lives in eval/, so the repo root is two levels up -- same convention as
# walkforward.py, which has always sat here.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

WF = REPO / "data" / "walkforward_h6_2526.parquet"
HIST = REPO / "data" / "history" / "all_seasons_fixed.parquet"
SEASON = "2025-26"
COLD = 7

GOAL_PTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}


def actuals():
    h = pd.read_parquet(HIST)
    h = h[h.season == SEASON].copy()
    h["minutes"] = pd.to_numeric(h.minutes, errors="coerce").fillna(0)
    num = ["goals_scored", "assists", "clean_sheets", "bonus", "total_points",
           "defensive_contribution"]
    for c in num:
        h[c] = pd.to_numeric(h.get(c), errors="coerce").fillna(0)
    g = (h.groupby(["GW", "element"], as_index=False)
           .agg(minutes=("minutes", "sum"), goals=("goals_scored", "sum"),
                assists=("assists", "sum"), cs=("clean_sheets", "sum"),
                bonus=("bonus", "sum"), dc=("defensive_contribution", "sum"),
                total=("total_points", "sum"), position=("position", "first"))
           .rename(columns={"GW": "gw"}))
    pos = g.position.map(lambda p: p if p in GOAL_PTS else "MID")
    g["a_appear"] = np.where(g.minutes >= 60, 2.0, np.where(g.minutes > 0, 1.0, 0.0))
    g["a_goals"] = g.goals * pos.map(GOAL_PTS).astype(float)
    g["a_assists"] = g.assists * 3.0
    # A clean sheet only pays if the player was on for 60+.
    g["a_cs"] = np.where(g.minutes >= 60, g.cs * pos.map(CS_PTS).astype(float), 0.0)
    g["a_dc"] = g.dc * 2.0
    g["a_bonus"] = g.bonus
    return g


COMPONENTS = [
    ("appearance", "pts_appear", "a_appear"),
    ("goals", "pts_goals", "a_goals"),
    ("assists", "pts_assists", "a_assists"),
    ("clean sheets", "pts_cs", "a_cs"),
    ("def contribution", "pts_dc", "a_dc"),
    ("bonus", "exp_bonus", "a_bonus"),
]


def main():
    wf = pd.read_parquet(WF)
    d = wf[wf.horizon_step == 0].merge(actuals(), on=["gw", "element"], how="inner",
                                       suffixes=("", "_act"))
    d["era"] = np.where(d.gw <= COLD, "GW1-7", "GW8-38")
    print(f"rows: {len(d):,}  ({(d.era == 'GW1-7').sum():,} cold / "
          f"{(d.era == 'GW8-38').sum():,} warm)")

    print("\n" + "=" * 104)
    print("COMPONENT DECOMPOSITION — predicted vs realised, cold vs warm")
    print("=" * 104)
    rows = []
    for name, pcol, acol in COMPONENTS:
        for era, g in d.groupby("era"):
            p, a = g[pcol].astype(float), g[acol].astype(float)
            rows.append({
                "component": name, "era": era,
                "pred_mean": round(float(p.mean()), 3),
                "act_mean": round(float(a.mean()), 3),
                "bias": round(float((p - a).mean()), 3),
                "mae": round(float((p - a).abs().mean()), 3),
                "spearman": round(float(spearmanr(p, a).statistic), 4),
            })
    t = pd.DataFrame(rows).pivot(index="component", columns="era")
    t = t.reindex([c[0] for c in COMPONENTS])
    print(t.to_string())

    print("\ndelta (cold minus warm) — negative spearman delta = worse ranking early:")
    delta = pd.DataFrame({
        "d_bias": t[("bias", "GW1-7")] - t[("bias", "GW8-38")],
        "d_mae": t[("mae", "GW1-7")] - t[("mae", "GW8-38")],
        "d_spearman": t[("spearman", "GW1-7")] - t[("spearman", "GW8-38")],
        "warm_spearman": t[("spearman", "GW8-38")],
    }).round(4)
    print(delta.to_string())

    print("\n" + "=" * 104)
    print("MINUTES AND THE TOTAL")
    print("=" * 104)
    for era, g in d.groupby("era"):
        played = g[g.minutes > 0]
        print(f"{era}: e_minutes {g.e_minutes.mean():5.1f} vs actual "
              f"{g.minutes.clip(upper=90).mean():5.1f}  |  "
              f"e_points {g.e_points.mean():.3f} vs actual {g.total.mean():.3f}  |  "
              f"spearman(e_points, actual) all {spearmanr(g.e_points, g.total).statistic:.4f}  "
              f"played {spearmanr(played.e_points, played.total).statistic:.4f}")

    print("\n" + "=" * 104)
    print("TOP-N SELECTION QUALITY — what the optimiser actually relies on")
    print("=" * 104)
    for era, g in d.groupby("era"):
        out = []
        for n in (15, 30, 50):
            picked = g.groupby("gw", group_keys=False).apply(
                lambda x: x.nlargest(n, "e_points"), include_groups=False)
            best = g.groupby("gw", group_keys=False).apply(
                lambda x: x.nlargest(n, "total"), include_groups=False)
            out.append(f"top{n}: captured {picked.total.sum() / best.total.sum():.1%}")
        print(f"{era}: " + "   ".join(out))


if __name__ == "__main__":
    main()
