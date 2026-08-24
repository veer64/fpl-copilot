"""Re-measures 2023-24 _baseline and Variant B after the Sheffield Utd join-failure fix, printing the contaminated figures alongside. Result of record: Logs/d1_log.md §8 and Logs/gk_investigation_log.md §6 (2023-24 rows corrected 2026-08-17).

Re-measure 2023-24 after the Sheffield fix. Both files, all house metrics,
with the previously reported (contaminated) figures alongside.
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]
FILES = {
    "baseline": BASE + r"\data\walkforward_h6_2023_24_baseline.parquet",
    "variant_B": BASE + r"\data\walkforward_h6_2023_24.parquet",
}
# Previously reported (contaminated by 1,429 Sheffield zero rows):
OLD = {
    "baseline": {"beta": {"GK": 0.5597, "DEF": 0.7944, "MID": 0.7757, "FWD": 0.4929},
                 "rho":  {"GK": 0.2104, "DEF": 0.3287, "MID": 0.3164, "FWD": 0.1998}},
    "variant_B": {"agg_rho": 0.6681, "agg_mae": 1.0605,
                  "beta": {"GK": 0.4786, "DEF": 0.8700, "MID": 0.7909, "FWD": 0.4849},
                  "rho":  {"GK": 0.2041, "DEF": 0.3404, "MID": 0.3125, "FWD": 0.1869}},
}

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

for name, path in FILES.items():
    df = pd.read_parquet(path)
    d1stamp = df["d1_terms_active"].iloc[0] if "d1_terms_active" in df.columns else "ABSENT"
    gk = df[df["position"] == "GK"]
    d1_data = int((gk["pts_saves"].fillna(0) != 0).sum()) if "pts_saves" in df.columns else -1
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    d = d.dropna(subset=["e_points", "actual_points"])
    n_null = int((d["p_cs"].isna() | d["opp_lambda"].isna()).sum())
    sheff_zero = int(((d["team"] == "Sheffield Utd") & (d["e_points"] == 0)
                      & (d["e_minutes"] >= 60)).sum()) if "team" in d.columns else -1
    print(f"\n=== {name} === rows {len(df)}, d1_terms_active={d1stamp}, "
          f"GK pts_saves nonzero={d1_data}")
    print(f"  null-market step-0 rows: {n_null}  "
          f"(Sheffield starter rows at e_points==0: {sheff_zero})")

    agg_rho = spearmanr(d["e_points"], d["actual_points"]).statistic
    agg_mae = (d["e_points"] - d["actual_points"]).abs().mean()
    old = OLD[name]
    if "agg_rho" in old:
        print(f"  aggregate: rho {agg_rho:.4f} (was {old['agg_rho']:.4f}, "
              f"{agg_rho-old['agg_rho']:+.4f}), MAE {agg_mae:.4f} "
              f"(was {old['agg_mae']:.4f}, {agg_mae-old['agg_mae']:+.4f})")
    else:
        print(f"  aggregate: rho {agg_rho:.4f}, MAE {agg_mae:.4f}")

    st = d[d["e_minutes"] >= 60]
    print(f"  starter band (n={len(st)}):  pos   rho (was, delta)      beta (was, delta)")
    for pos in POSITIONS:
        g = st[st["position"] == pos]
        r = spearmanr(g["e_points"], g["actual_points"]).statistic
        b = beta(g)
        ro, bo = old["rho"][pos], old["beta"][pos]
        print(f"    {pos:4s} {r:7.4f} ({ro:.4f}, {r-ro:+.4f})   "
              f"{b:7.4f} ({bo:.4f}, {b-bo:+.4f})")
