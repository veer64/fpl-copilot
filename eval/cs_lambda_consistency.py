"""Checks p_cs against exp(-opp_lambda) for GK/DEF starters (detects Dixon-Coles fallback rows exactly; sizes the pts_cs change unification would make), three seasons. Result of record: Logs/gk_investigation_log.md §8. Report only.

Consistency check: p_cs vs exp(-opp_lambda), per season, GK+DEF starters,
step 0, corrected files. REPORT ONLY.

From dixon_coles.py: p_cs = exp(-(0.2*dc_lam + 0.8*mkt_lam)) on odds-usable
fixtures, pure exp(-dc_lam) on fallback; opp_lambda = mkt_lam on odds-usable,
dc_lam on fallback. So on FALLBACK rows p_cs == exp(-opp_lambda) EXACTLY,
which gives a clean detector: |ln(p_cs) + opp_lambda| < 1e-9 -> fallback.
On market rows the gap is exp(0.2*(mkt-dc)) -- the 0.2 DC blend.
"""
import numpy as np
import pandas as pd

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
FILES = {
    "2025-26": r"\data\walkforward_h6_2025_26.parquet",
    "2024-25": r"\data\walkforward_h6_2024_25.parquet",
    "2023-24": r"\data\walkforward_h6_2023_24.parquet",
}
CS_PTS = {"GK": 4, "DEF": 4}

for season, path in FILES.items():
    df = pd.read_parquet(BASE + path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    d = d.dropna(subset=["e_points", "actual_points"])
    st = d[(d["e_minutes"] >= 60) & (d["position"].isin(["GK", "DEF"]))].copy()
    st["p_cs_pois"] = np.exp(-st["opp_lambda"])
    st["diff"] = st["p_cs"] - st["p_cs_pois"]
    st["fallback"] = (np.log(st["p_cs"].clip(lower=1e-12)) + st["opp_lambda"]).abs() < 1e-9

    print(f"\n=== {season} === GK+DEF starters, step 0, n={len(st)}")
    print(f"  DC-fallback rows (p_cs == exp(-opp_lambda) exactly): "
          f"{int(st['fallback'].sum())} ({st['fallback'].mean():.1%})")
    for pos in ("GK", "DEF"):
        g = st[st["position"] == pos]
        q = np.quantile(g["diff"], [0.05, 0.25, 0.5, 0.75, 0.95])
        print(f"  {pos}: corr {g['p_cs'].corr(g['p_cs_pois']):.4f}  "
              f"mean diff {g['diff'].mean():+.4f}  sd {g['diff'].std():.4f}")
        print(f"       diff quantiles 5/25/50/75/95%: "
              + " ".join(f"{v:+.4f}" for v in q)
              + f"  max|diff| {g['diff'].abs().max():.4f}")
        # pts_cs change if unified on exp(-opp_lambda)
        new_pts = g["p_cs_pois"] * CS_PTS[pos] * g["p_60plus"]
        old_pts = g["p_cs"] * CS_PTS[pos] * g["p_60plus"]
        print(f"       pts_cs if unified: mean {new_pts.mean():.4f} vs current "
              f"{old_pts.mean():.4f}  (mean change {new_pts.mean()-old_pts.mean():+.4f}, "
              f"mean |change| {(new_pts-old_pts).abs().mean():.4f})")

    # split by fallback vs market
    for lab, sub in (("market-priced", st[~st["fallback"]]),
                     ("DC-fallback", st[st["fallback"]])):
        if len(sub):
            print(f"  {lab:14s} n={len(sub):5d}  mean diff {sub['diff'].mean():+.4f}  "
                  f"sd {sub['diff'].std():.4f}  max|diff| {sub['diff'].abs().max():.4f}")

    # biggest disagreements
    top = st.reindex(st["diff"].abs().sort_values(ascending=False).index).head(8)
    cols = [c for c in ("gw", "team", "position", "p_cs", "opp_lambda", "diff",
                        "fallback") if c in top.columns]
    print("  largest disagreements:")
    print(top[cols].round(4).to_string(index=False))
