"""Measures GK-investigation step 2 (H1 test): p_cs / opp_lambda double-counting diagnostic -- corr, R^2, and margin-beta recovery from a residualised conceded term, GK/DEF starters, three seasons. Result of record: Logs/gk_investigation_log.md §7.

GK investigation step 2 -- H1 test: does the conceded term double-count
clean-sheet information?

Per season, starter band (e_minutes >= 60), step 0, GK and DEF:
  1. Pearson corr(p_cs, opp_lambda)
  2. R^2 of OLS pts_conceded ~ p_cs (how much of the conceded term's variance
     clean sheets already explain)
  3. Margin beta with the shipped conceded term (Variant B) vs a variant whose
     conceded term is rebuilt from RESIDUALISED opp_lambda:
        lam_resid = mean(opp_lambda) + [opp_lambda - (a + b*p_cs)]
     (fitted per season-position on this band, in-sample -- this is a
     DIAGNOSTIC of shared information, not a model proposal), clipped at 0,
     then passed through the same E[floor(X/2)] Poisson computation.
  Recovery = (beta_H1 - beta_B) / (beta_base - beta_B): the share of the
  baseline->B beta loss that residualising recovers. H1 predicts recovery > 0
  in all three seasons.
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson, spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
PAIRS = {
    "2025-26": (r"\data\walkforward_h6_2526_baseline.parquet",
                r"\data\walkforward_h6_2025_26.parquet"),
    "2024-25": (r"\data\walkforward_h6_2024_25_baseline.parquet",
                r"\data\walkforward_h6_2024_25.parquet"),
    "2023-24": (r"\data\walkforward_h6_2023_24_baseline.parquet",
                r"\data\walkforward_h6_2023_24.parquet"),
}

def expected_floor_div(mu, divisor, max_k=40):
    mu = np.asarray(mu, dtype=float)
    ks = np.arange(max_k + 1)
    weights = np.floor(ks / divisor)
    pmf = poisson.pmf(ks[None, :], np.clip(mu, 0, None)[:, None])
    return (pmf * weights[None, :]).sum(axis=1)

def step0(path):
    df = pd.read_parquet(BASE + path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

def beta(g, pred_col="e_points"):
    num = den = 0.0
    for _, grp in g.groupby("gw"):
        n = len(grp)
        if n < 2:
            continue
        x = grp[pred_col].to_numpy(float)
        y = grp["actual_points"].to_numpy(float)
        num += n * (x * y).sum() - x.sum() * y.sum()
        den += n * (x * x).sum() - x.sum() ** 2
    return num / den if den > 0 else np.nan

print(f"{'season':8s} {'pos':4s} {'corr':>7s} {'R2':>6s} | "
      f"{'b_base':>7s} {'b_B':>7s} {'b_H1':>7s} | {'loss':>7s} {'recov':>7s} {'recov%':>7s}")
for season, (p0, pb) in PAIRS.items():
    d0 = step0(p0)
    db = step0(pb)
    st0 = d0[d0["e_minutes"] >= 60]
    stb = db[db["e_minutes"] >= 60].copy()
    for pos in ("GK", "DEF"):
        g0 = st0[st0["position"] == pos]
        gb = stb[stb["position"] == pos].copy()
        n_before = len(gb)
        gb = gb.dropna(subset=["p_cs", "opp_lambda", "pts_conceded", "minutes_frac"])
        if len(gb) < n_before:
            print(f"  note: {season} {pos} dropped {n_before - len(gb)} rows "
                  f"with NaN p_cs/opp_lambda/pts_conceded")

        corr = gb["p_cs"].corr(gb["opp_lambda"])
        # R^2 of pts_conceded ~ p_cs
        a1, b1 = np.polyfit(gb["p_cs"], gb["pts_conceded"], 1)[::-1]
        fit = a1 + b1 * gb["p_cs"]
        ss_res = ((gb["pts_conceded"] - fit) ** 2).sum()
        ss_tot = ((gb["pts_conceded"] - gb["pts_conceded"].mean()) ** 2).sum()
        r2 = 1 - ss_res / ss_tot

        # residualise opp_lambda against p_cs, rebuild conceded term
        a2, b2 = np.polyfit(gb["p_cs"], gb["opp_lambda"], 1)[::-1]
        lam_resid = (gb["opp_lambda"].mean()
                     + (gb["opp_lambda"] - (a2 + b2 * gb["p_cs"]))).clip(lower=0)
        mu = lam_resid * gb["minutes_frac"]
        pts_conc_resid = -expected_floor_div(mu.values, 2)
        gb["e_h1"] = gb["e_points"] - gb["pts_conceded"] + pts_conc_resid

        # Same population for all three betas: restrict baseline to the rows
        # that survived the NaN drop on the B file.
        g0m = g0.merge(gb[["element", "gw"]], on=["element", "gw"], how="inner")
        b_base = beta(g0m)
        b_b = beta(gb)
        b_h1 = beta(gb, "e_h1")
        loss = b_base - b_b
        recov = b_h1 - b_b
        pct = recov / loss if abs(loss) > 1e-9 else np.nan
        print(f"{season:8s} {pos:4s} {corr:7.3f} {r2:6.3f} | "
              f"{b_base:7.4f} {b_b:7.4f} {b_h1:7.4f} | "
              f"{loss:+7.4f} {recov:+7.4f} {pct:7.1%}")
