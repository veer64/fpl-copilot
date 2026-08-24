"""Measures the CS/conceded unification: _preunify (before) vs the preserved _csunified builds (after) -- CS Brier, margin beta, rho, mean pts_cs / pts_conceded, starter band, three seasons. Result of record: Logs/gk_investigation_log.md §8 (clean NEGATIVE, reverted; CS_UNIFIED=False). PATH NOTE (2026-08-24 rescue): 'after' originally read the canonical file, which WAS the unified build at the time; canonical was reverted (cs_unified=False), so 'after' now reads the preserved _csunified files, which carry cs_unified=True.

CS/conceded unification: before (preunify) vs after (unified), per season.
Step 0, starter band (e_minutes >= 60).

Brier: predicted p_cs vs realised clean sheet from vaastav, restricted to
rows with realised minutes >= 60 (matching FPL's award condition) AND
n_fixtures == 1 (so the stored per-fixture-mean p_cs corresponds to exactly
one outcome; doubles excluded from Brier only).
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]
SEASONS = ["2025-26", "2024-25", "2023-24"]
BASELINE_BETA = {"2025-26": {"GK": 0.847, "DEF": 1.074},
                 "2024-25": {"GK": 0.760, "DEF": 1.019},
                 "2023-24": {"GK": 0.833, "DEF": 1.100}}

vaast = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet",
                        columns=["season", "element", "GW", "clean_sheets",
                                 "minutes"])
vaast = vaast.rename(columns={"GW": "gw"})
cs_actual = (vaast.groupby(["season", "element", "gw"])
             .agg(cs=("clean_sheets", "max"), rmin=("minutes", "sum"))
             .reset_index())

def step0(path):
    df = pd.read_parquet(path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

def beta(g):
    num = den = 0.0
    for _, grp in g.groupby("gw"):
        n = len(grp)
        if n < 2:
            continue
        x = grp["e_points"].to_numpy(float)
        y = grp["actual_points"].to_numpy(float)
        num += n * (x * y).sum() - x.sum() * y.sum()
        den += n * (x * x).sum() - x.sum() ** 2
    return num / den if den > 0 else np.nan

for season in SEASONS:
    tag = season.replace("-", "_")
    files = {"before": BASE + rf"\data\walkforward_h6_{tag}_preunify.parquet",
             "after":  BASE + rf"\data\walkforward_h6_{tag}_csunified.parquet"}
    print(f"\n================ {season} ================")
    res = {}
    for name, path in files.items():
        d = step0(path)
        stamp = d["cs_unified"].iloc[0] if "cs_unified" in d.columns else "ABSENT"
        st = d[d["e_minutes"] >= 60].copy()
        st = st.merge(cs_actual[cs_actual["season"] == season],
                      on=["element", "gw"], how="left")
        res[name] = (d, st)
        print(f"  {name}: rows {len(d)}, cs_unified stamp = {stamp}")

    print(f"\n  {'metric':34s} {'pos':4s} {'before':>9s} {'after':>9s} {'delta':>9s}")
    for pos in ("GK", "DEF"):
        vals = {}
        for name in files:
            st = res[name][1]
            g = st[(st["position"] == pos) & (st["rmin"] >= 60)]
            if "n_fixtures" in st.columns:
                g = g[g["n_fixtures"] == 1]
            vals[name] = float(((g["p_cs"] - g["cs"]) ** 2).mean())
        print(f"  {'CS Brier (rmin>=60, singles)':34s} {pos:4s} "
              f"{vals['before']:9.4f} {vals['after']:9.4f} "
              f"{vals['after']-vals['before']:+9.4f}")
    for metric in ("beta", "rho", "pts_cs", "pts_conceded"):
        for pos in POSITIONS:
            vals = {}
            for name in files:
                st = res[name][1]
                g = st[st["position"] == pos]
                if metric == "beta":
                    vals[name] = beta(g)
                elif metric == "rho":
                    vals[name] = spearmanr(g["e_points"], g["actual_points"]).statistic
                else:
                    vals[name] = float(g[metric].mean())
            extra = ""
            if metric == "beta" and pos in BASELINE_BETA[season]:
                extra = f"   (no-D1 baseline: {BASELINE_BETA[season][pos]:.3f})"
            print(f"  {('margin ' + metric if metric == 'beta' else metric):34s} "
                  f"{pos:4s} {vals['before']:9.4f} {vals['after']:9.4f} "
                  f"{vals['after']-vals['before']:+9.4f}{extra}")
