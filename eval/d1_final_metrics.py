"""Measures the adopted Variant B component metrics (aggregate rho/MAE, starter-band rho and margin beta by position) and top-k realised points vs _baseline, three seasons. Result of record: Logs/d1_log.md §8 (metrics) and §4 (top-k). Same canonical-drift note as d1_clean_measure.py.

Final component metrics for the adopted Variant B build, all three seasons.

Per season, step 0 only:
  - provenance stamps (must show d1_terms_active=True)
  - aggregate Spearman and MAE (all step-0 rows)
  - starter-band (e_minutes >= 60) Spearman by position
  - pairwise margin beta by position, through-origin, starter band
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]
SEASONS = {
    "2025-26": BASE + r"\data\walkforward_h6_2025_26.parquet",
    "2024-25": BASE + r"\data\walkforward_h6_2024_25.parquet",
    "2023-24": BASE + r"\data\walkforward_h6_2023_24.parquet",
}
STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling",
          "d1_terms_active", "dc_rule_active"]

def margin_beta(g):
    num = den = 0.0
    npairs = 0
    for _, grp in g.groupby("gw"):
        n = len(grp)
        if n < 2:
            continue
        x = grp["e_points"].to_numpy(float)
        y = grp["actual_points"].to_numpy(float)
        num += n * (x * y).sum() - x.sum() * y.sum()
        den += n * (x * x).sum() - x.sum() ** 2
        npairs += n * (n - 1) // 2
    return (num / den if den > 0 else np.nan), npairs

for season, path in SEASONS.items():
    df = pd.read_parquet(path)
    print(f"\n=== {season} === ({path.split(chr(92))[-1]}, {len(df)} rows)")
    for col in STAMPS:
        v = df[col].dropna().unique() if col in df.columns else ["ABSENT"]
        print(f"  {col}: {v[0] if len(v) == 1 else list(v)}")
    gk = df[df["position"] == "GK"]
    print(f"  data check: GK rows with pts_saves!=0: "
          f"{int((gk['pts_saves'].fillna(0) != 0).sum())} of {len(gk)}; "
          f"pts_cards!=0 (all pos): {int((df['pts_cards'].fillna(0) != 0).sum())}")

    d0 = df[df["horizon_step"] == 0].copy()
    d0["actual_points"] = pd.to_numeric(d0["actual_points"], errors="coerce")
    d0 = d0.dropna(subset=["e_points", "actual_points"])
    rho = spearmanr(d0["e_points"], d0["actual_points"]).statistic
    mae = (d0["e_points"] - d0["actual_points"]).abs().mean()
    print(f"  aggregate (n={len(d0)}): Spearman {rho:.4f}  MAE {mae:.4f}")

    st = d0[d0["e_minutes"] >= 60]
    print(f"  starter band (n={len(st)}):")
    print(f"    {'pos':4s} {'n':>5s} {'spearman':>9s} {'beta':>8s} {'pairs':>7s}")
    for pos in POSITIONS:
        p = st[st["position"] == pos]
        r = spearmanr(p["e_points"], p["actual_points"]).statistic
        b, npairs = margin_beta(p)
        print(f"    {pos:4s} {len(p):5d} {r:9.4f} {b:8.4f} {npairs:7d}")

# ---------------------------------------------------------------------------
# Top-k realised points, Variant B vs baseline, per season. Both pools.
# ---------------------------------------------------------------------------
BASELINES = {
    "2025-26": BASE + r"\data\walkforward_h6_2526_baseline.parquet",
    "2024-25": BASE + r"\data\walkforward_h6_2024_25_baseline.parquet",
    "2023-24": BASE + r"\data\walkforward_h6_2023_24_baseline.parquet",
}
KS = [1, 3, 5]

def step0(path):
    df = pd.read_parquet(path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

def topk_per_gw(d):
    """{(pos, k, pool): Series indexed by gw of mean realised pts of top-k picks}"""
    out = {}
    for (gw, pos), g in d.groupby(["gw", "position"]):
        if pos not in POSITIONS:
            continue
        started = g[g["minutes"] >= 60]
        for k in KS:
            out.setdefault((pos, k, "all"), {})[gw] = (
                g.nlargest(k, "e_points")["actual_points"].mean())
            sp = started.nlargest(min(k, len(started)), "e_points")
            out.setdefault((pos, k, "started"), {})[gw] = (
                sp["actual_points"].mean() if len(sp) else np.nan)
    return {key: pd.Series(v) for key, v in out.items()}

print("\n\n=== TOP-K REALISED POINTS: Variant B vs baseline ===")
print("mean (SD across gameweeks); delta = paired per-gw mean [2*SE]; "
      "RES iff |mean delta| > 2*SE")
n_res, n_tot = 0, 0
for season in SEASONS:
    tk_b = topk_per_gw(step0(SEASONS[season]))
    tk_0 = topk_per_gw(step0(BASELINES[season]))
    for pool in ("all", "started"):
        print(f"\n{season}, pool={pool}:")
        print(f"  {'pos':4s} {'k':>2s} {'baseline':>15s} {'variant_B':>15s} "
              f"{'delta [2SE]':>18s}")
        for pos in POSITIONS:
            for k in KS:
                s0 = tk_0[(pos, k, pool)]
                sb = tk_b[(pos, k, pool)]
                delta = (sb - s0).dropna()
                se2 = 2 * delta.std() / np.sqrt(len(delta))
                res = abs(delta.mean()) > se2
                n_tot += 1
                n_res += int(res)
                tag = "RES" if res else "  ."
                print(f"  {pos:4s} {k:2d} {s0.mean():7.3f} ({s0.std():5.3f}) "
                      f"{sb.mean():7.3f} ({sb.std():5.3f}) "
                      f"{delta.mean():+7.3f} [{se2:5.3f}] {tag}")
print(f"\nresolved cells: {n_res} of {n_tot}")
