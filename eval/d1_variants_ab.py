"""Measures D1 Variant A (no cards) vs Variant B (position-prior cards) reconstructed per row with bonus brackets, 2025-26 step 0. Result of record: Logs/d1_log.md §3 (why Variant B was adopted). Same canonical-drift note as d1_clean_measure.py.

D1 variants A and B, reconstructed per-row from the two verified files.

A: saves + conceded + penalty, cards disabled.
B: saves + conceded + penalty + cards-as-position-prior. The per-player rolling
   card rate is replaced by a position-level base rate computed from PRIOR
   seasons only (realised cards per 90 by position, seasons < 2025-26), applied
   as -(ybar_pos + 3*rbar_pos) * minutes_frac.

Bonus: exp_bonus cannot be recomputed without the BPS model, so each variant is
measured at two brackets: _lo uses the baseline file's exp_bonus, _hi adds the
D1 file's exp_bonus delta (whose inputs include cards). The true variant bonus
lies between. Brackets agreeing => bonus treatment immaterial.

Canonical files are read only. Nothing is written outside the scratchpad.
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]

def step0(p):
    df = pd.read_parquet(p)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

b = step0(BASE + r"\data\walkforward_h6_2526_baseline.parquet")
d = step0(BASE + r"\data\walkforward_h6_2025_26.parquet")
m = b.merge(
    d[["element", "gw", "e_points", "pts_saves", "pts_conceded", "pts_cards",
       "pts_goals", "exp_bonus", "yellow_per_90", "red_per_90", "minutes_frac"]],
    on=["element", "gw"], suffixes=("", "_d1"), how="inner")
print(f"matched rows: {len(m)} of {len(b)}")

# --- verify the stored card identity: pts_cards == -(y + 3r) * minutes_frac ---
recon = -(m["yellow_per_90_d1"] + 3.0 * m["red_per_90_d1"]) * m["minutes_frac_d1"]
gap = (recon - m["pts_cards_d1"]).abs()
print(f"card identity check: max |recon - stored| = {gap.max():.2e} "
      f"(rows >1e-9: {int((gap > 1e-9).sum())})")

# --- position card base rates from PRIOR seasons only ---
hist = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
prior = hist[(hist["season"] < "2025-26") & (hist["position"] != "AM")]
prior = prior[prior["minutes"] > 0]
rate = prior.groupby("position").apply(
    lambda g: pd.Series({
        "y90": 90.0 * g["yellow_cards"].sum() / g["minutes"].sum(),
        "r90": 90.0 * g["red_cards"].sum() / g["minutes"].sum(),
    }), include_groups=False)
print("\nPosition card base rates (prior seasons, realised per 90):")
print(rate.round(4))

m["y_pos"] = m["position"].map(rate["y90"])
m["r_pos"] = m["position"].map(rate["r90"])
m["t_cards_prior"] = -(m["y_pos"] + 3.0 * m["r_pos"]) * m["minutes_frac_d1"]

# --- terms ---
m["t_saves"]    = m["pts_saves_d1"]
m["t_conceded"] = m["pts_conceded_d1"]
m["t_penalty"]  = m["pts_goals_d1"] - m["pts_goals"]
m["t_bonus"]    = m["exp_bonus_d1"] - m["exp_bonus"]
core = m["e_points"] + m["t_saves"] + m["t_conceded"] + m["t_penalty"]

variants = {
    "baseline":    m["e_points"],
    "A_lo":        core,
    "A_hi":        core + m["t_bonus"],
    "B_lo":        core + m["t_cards_prior"],
    "B_hi":        core + m["t_cards_prior"] + m["t_bonus"],
    "full_d1":     m["e_points_d1"],
}

starters = m["e_minutes"] >= 60

def margin_beta(g, pred):
    num = den = 0.0
    for _, grp in g.groupby("gw"):
        n = len(grp)
        if n < 2:
            continue
        x = pred.loc[grp.index].to_numpy(float)
        y = grp["actual_points"].to_numpy(float)
        num += n * (x * y).sum() - x.sum() * y.sum()
        den += n * (x * x).sum() - x.sum() ** 2
    return num / den if den > 0 else np.nan

rho_tab, beta_tab = {}, {}
for vname, pred in variants.items():
    rho_tab[vname] = {}
    beta_tab[vname] = {}
    for pos in POSITIONS:
        mask = starters & (m["position"] == pos)
        g = m[mask]
        rho_tab[vname][pos] = spearmanr(pred[mask], g["actual_points"]).statistic
        beta_tab[vname][pos] = margin_beta(g, pred)

def show(tab, title):
    print(f"\n{title}")
    print(f"  {'variant':10s} " + " ".join(f"{p:>8s}" for p in POSITIONS))
    for vname, row in tab.items():
        print(f"  {vname:10s} " + " ".join(f"{row[p]:8.4f}" for p in POSITIONS))
    base = tab["baseline"]
    print("  -- deltas vs baseline --")
    for vname, row in tab.items():
        if vname == "baseline":
            continue
        print(f"  {vname:10s} " + " ".join(f"{row[p]-base[p]:+8.4f}" for p in POSITIONS))

show(rho_tab, "Starter-band Spearman by position (step 0):")
show(beta_tab, "Pairwise margin beta, through-origin, starter band (step 0):")

print("\nCard-term contribution on starters, mean (SD), by position:")
print(f"  {'pos':4s} {'B: position prior':>22s} {'D1: per-player rolling':>26s}")
for pos in POSITIONS:
    mask = starters & (m["position"] == pos)
    bp = m.loc[mask, "t_cards_prior"]
    dp = m.loc[mask, "pts_cards_d1"]
    print(f"  {pos:4s} {bp.mean():+12.4f} ({bp.std():.4f}) {dp.mean():+14.4f} ({dp.std():.4f})")
