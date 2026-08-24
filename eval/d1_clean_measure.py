"""Measures D1 before/after (no-D1 _baseline vs the D1 build): step-0 aggregate Spearman/MAE, starter-band Spearman and through-origin margin beta by position, provenance-checked. Result of record: Logs/d1_log.md §2-3. NOTE: canonical 'after' now also carries the rate blend and the #15 rebuild; the logged figures are the pre-blend record (d1_log §8 note).

Clean D1 before/after on the two verified files. Step 0 only.

Provenance is checked first; measurement aborts on any mismatch beyond
d1_terms_active. Margin beta uses exact all-pairs moments per (gw, position):
sum over pairs of (xi-xj)(yi-yj) = n*Sxy - Sx*Sy, likewise for squares.
"""
import sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
FILES = {
    "baseline": BASE + r"\data\walkforward_h6_2526_baseline.parquet",
    "with_d1":  BASE + r"\data\walkforward_h6_2025_26.parquet",
}
STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling"]
POSITIONS = ["GK", "DEF", "MID", "FWD"]

dfs = {}
print("=== PROVENANCE CHECK ===")
stamp_vals = {}
for name, path in FILES.items():
    df = pd.read_parquet(path)
    dfs[name] = df
    vals = {}
    for col in STAMPS + ["d1_terms_active"]:
        if col in df.columns:
            u = df[col].dropna().unique()
            vals[col] = u[0] if len(u) == 1 else f"MIXED:{list(u)[:4]}"
        else:
            vals[col] = "ABSENT"
    # Establish D1 status from the data as well (KNOWN_ISSUES #13)
    gk = df[df["position"] == "GK"]
    for c in ("pts_saves", "pts_conceded", "pts_cards"):
        if c in df.columns:
            vals[f"data:{c}!=0 (GK rows)"] = int((gk[c].fillna(0) != 0).sum())
        else:
            vals[f"data:{c}"] = "COLUMN ABSENT"
    vals["rows"] = len(df)
    stamp_vals[name] = vals
    print(f"\n{name}: {path}")
    for k, v in vals.items():
        print(f"  {k}: {v}")

mismatch = [c for c in STAMPS
            if str(stamp_vals["baseline"][c]) != str(stamp_vals["with_d1"][c])]
if mismatch:
    print(f"\n*** STOP: files differ on {mismatch} -- not comparable. ***")
    sys.exit(1)
print("\nShared stamps identical:", {c: stamp_vals['baseline'][c] for c in STAMPS})

def step0(df):
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

def margin_beta(d):
    """Through-origin beta of actual margin on predicted margin, all pairs
    within each gw. Exact via moments; n_pairs = sum n*(n-1)/2."""
    num = den = 0.0
    n_pairs = 0
    for _, g in d.groupby("gw"):
        n = len(g)
        if n < 2:
            continue
        x, y = g["e_points"].to_numpy(float), g["actual_points"].to_numpy(float)
        num += n * (x * y).sum() - x.sum() * y.sum()
        den += n * (x * x).sum() - x.sum() ** 2
        n_pairs += n * (n - 1) // 2
    return (num / den if den > 0 else np.nan), n_pairs

rows = []
for name in FILES:
    d0 = step0(dfs[name])
    starters = d0[d0["e_minutes"] >= 60]
    agg_rho = spearmanr(d0["e_points"], d0["actual_points"]).statistic
    agg_mae = (d0["e_points"] - d0["actual_points"]).abs().mean()
    rec = {"file": name, "agg_spearman": agg_rho, "agg_mae": agg_mae,
           "n_step0": len(d0), "n_starters": len(starters)}
    for pos in POSITIONS:
        p = starters[starters["position"] == pos]
        rec[f"{pos}_rho"] = spearmanr(p["e_points"], p["actual_points"]).statistic
        rec[f"{pos}_n"] = len(p)
        b, npairs = margin_beta(p)
        rec[f"{pos}_beta"] = b
        rec[f"{pos}_pairs"] = npairs
    rows.append(rec)

r0, r1 = rows  # baseline, with_d1
print("\n=== STEP 0, STARTER BAND (e_minutes >= 60) ===")
print(f"rows step0: baseline {r0['n_step0']}, with_d1 {r1['n_step0']}; "
      f"starters: {r0['n_starters']} vs {r1['n_starters']}")

print("\nAggregate (all step-0 rows):")
print(f"  {'':10s} {'baseline':>10s} {'with_d1':>10s} {'delta':>9s}")
print(f"  {'Spearman':10s} {r0['agg_spearman']:10.4f} {r1['agg_spearman']:10.4f} "
      f"{r1['agg_spearman']-r0['agg_spearman']:+9.4f}")
print(f"  {'MAE':10s} {r0['agg_mae']:10.4f} {r1['agg_mae']:10.4f} "
      f"{r1['agg_mae']-r0['agg_mae']:+9.4f}")

print("\nStarter-band Spearman by position:")
print(f"  {'pos':4s} {'n':>5s} {'baseline':>10s} {'with_d1':>10s} {'delta':>9s}")
for pos in POSITIONS:
    print(f"  {pos:4s} {r0[f'{pos}_n']:5d} {r0[f'{pos}_rho']:10.4f} "
          f"{r1[f'{pos}_rho']:10.4f} {r1[f'{pos}_rho']-r0[f'{pos}_rho']:+9.4f}")

print("\nPairwise margin beta (through-origin), starter band, by position:")
print(f"  {'pos':4s} {'pairs':>7s} {'baseline':>10s} {'with_d1':>10s} {'delta':>9s}")
for pos in POSITIONS:
    print(f"  {pos:4s} {r0[f'{pos}_pairs']:7d} {r0[f'{pos}_beta']:10.4f} "
          f"{r1[f'{pos}_beta']:10.4f} {r1[f'{pos}_beta']-r0[f'{pos}_beta']:+9.4f}")
