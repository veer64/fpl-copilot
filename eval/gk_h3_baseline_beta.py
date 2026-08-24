"""Measures GK-investigation step 1 (H3 test): no-D1 _baseline vs Variant B margin beta and rho by position, three seasons, starter band. Result of record: Logs/gk_investigation_log.md §6. Same canonical-drift note as d1_clean_measure.py.

GK investigation step 1 (H3 test): baseline margin beta for all three
seasons, same methodology as every prior measurement -- step 0, starter band
(e_minutes >= 60), through-origin pairwise beta within (gw, position).

Provenance is verified before measuring; a stamp mismatch or non-zero D1 term
in a baseline file aborts.
"""
import sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]
PAIRS = {
    "2025-26": (r"\data\walkforward_h6_2526_baseline.parquet",
                r"\data\walkforward_h6_2025_26.parquet"),
    "2024-25": (r"\data\walkforward_h6_2024_25_baseline.parquet",
                r"\data\walkforward_h6_2024_25.parquet"),
    "2023-24": (r"\data\walkforward_h6_2023_24_baseline.parquet",
                r"\data\walkforward_h6_2023_24.parquet"),
}
STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling"]

def load_check(path, expect_d1):
    df = pd.read_parquet(BASE + path)
    stamps = {c: df[c].iloc[0] for c in STAMPS}
    gk = df[df["position"] == "GK"]
    nz = {c: int((gk[c].fillna(0) != 0).sum())
          for c in ("pts_saves", "pts_conceded", "pts_cards")}
    has_d1 = any(v > 0 for v in nz.values())
    if has_d1 != expect_d1:
        print(f"*** ABORT: {path} D1 status {has_d1} != expected {expect_d1} "
              f"(nonzero GK terms: {nz})")
        sys.exit(1)
    return df, stamps

def step0(df):
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

print("=== PROVENANCE ===")
data = {}
for season, (p0, pb) in PAIRS.items():
    d0, s0 = load_check(p0, expect_d1=False)
    db, sb = load_check(pb, expect_d1=True)
    mismatch = [c for c in STAMPS if str(s0[c]) != str(sb[c])]
    if mismatch:
        print(f"*** ABORT: {season} stamp mismatch on {mismatch}")
        sys.exit(1)
    print(f"{season}: stamps identical ({ {c: str(s0[c]) for c in STAMPS} }), "
          f"baseline D1-free, B carries D1, rows {len(d0)}/{len(db)}")
    data[season] = (step0(d0), step0(db))

print("\n=== STEP 0, STARTER BAND (e_minutes >= 60), through-origin beta ===")
print(f"{'season':8s} {'pos':4s} {'beta_base':>10s} {'beta_B':>8s} {'delta':>8s}"
      f" | {'rho_base':>9s} {'rho_B':>7s}")
for season, (d0, db) in data.items():
    st0 = d0[d0["e_minutes"] >= 60]
    stb = db[db["e_minutes"] >= 60]
    for pos in POSITIONS:
        g0 = st0[st0["position"] == pos]
        gb = stb[stb["position"] == pos]
        b0, bb = beta(g0), beta(gb)
        r0 = spearmanr(g0["e_points"], g0["actual_points"]).statistic
        rb = spearmanr(gb["e_points"], gb["actual_points"]).statistic
        print(f"{season:8s} {pos:4s} {b0:10.4f} {bb:8.4f} {bb-b0:+8.4f}"
              f" | {r0:9.4f} {rb:7.4f}")
