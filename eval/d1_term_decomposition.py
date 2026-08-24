"""Measures the D1 term-by-term decomposition (saves / conceded / cards / penalty share + bonus residual) on starter-band Spearman and margin beta, 2025-26 step 0. Result of record: Logs/d1_log.md §3; Logs/gk_investigation_log.md §2. Same canonical-drift note as d1_clean_measure.py.

D1 term-by-term decomposition on the two verified files. Step 0 only.

Variants are built from the BASELINE e_points plus one D1 term at a time, taken
from the with-D1 file's own columns after a per-row join on (element, gw):
  saves    = pts_saves (D1 file)
  conceded = pts_conceded (D1 file)
  cards    = pts_cards (D1 file)
  penalty  = pts_goals(D1) - pts_goals(baseline)   [penalty share's only path]
Residual = e_points(D1) - e_points(base) - the four terms = the bonus-input
change that shipped with D1. Reported so the sum check can close exactly.

Population held fixed across variants: baseline starter mask (e_minutes >= 60).
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]

def step0(path):
    df = pd.read_parquet(path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

b = step0(BASE + r"\data\walkforward_h6_2526_baseline.parquet")
d = step0(BASE + r"\data\walkforward_h6_2025_26.parquet")

# --- join integrity ---
for name, x in (("baseline", b), ("with_d1", d)):
    assert not x.duplicated(["element", "gw"]).any(), f"{name}: dup (element,gw)"
cols_d1 = ["element", "gw", "e_points", "pts_saves", "pts_conceded", "pts_cards",
           "pts_goals", "exp_bonus"]
m = b.merge(d[cols_d1], on=["element", "gw"], suffixes=("", "_d1"), how="inner")
print(f"join: baseline {len(b)}, with_d1 {len(d)}, matched {len(m)}")

# --- per-row terms ---
m["t_saves"]    = m["pts_saves_d1"]
m["t_conceded"] = m["pts_conceded_d1"]
m["t_cards"]    = m["pts_cards_d1"]
m["t_penalty"]  = m["pts_goals_d1"] - m["pts_goals"]
m["t_bonus"]    = m["exp_bonus_d1"] - m["exp_bonus"]

total = m["e_points_d1"] - m["e_points"]
four = m[["t_saves", "t_conceded", "t_cards", "t_penalty"]].sum(axis=1)
resid = total - four - m["t_bonus"]
print(f"sum check: max |total - four_terms - bonus_delta| = {resid.abs().max():.2e}")
print(f"           mean bonus_delta = {m['t_bonus'].mean():+.4f}, "
      f"max |bonus_delta| = {m['t_bonus'].abs().max():.4f}")

# mean term size on GK starters, for scale
gk_st = m[(m["position"] == "GK") & (m["e_minutes"] >= 60)]
print("\nGK starter mean term contribution (pts):")
for t in ("t_saves", "t_conceded", "t_cards", "t_penalty", "t_bonus"):
    print(f"  {t:11s} mean {gk_st[t].mean():+.4f}  sd {gk_st[t].std():.4f}")

# --- variants ---
variants = {
    "baseline":       m["e_points"],
    "+saves":         m["e_points"] + m["t_saves"],
    "+conceded":      m["e_points"] + m["t_conceded"],
    "+cards":         m["e_points"] + m["t_cards"],
    "+penalty":       m["e_points"] + m["t_penalty"],
    "+all_four":      m["e_points"] + four,
    "full_d1_file":   m["e_points_d1"],
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
    rho_row, beta_row = {}, {}
    for pos in POSITIONS:
        mask = starters & (m["position"] == pos)
        g = m[mask]
        rho_row[pos] = spearmanr(pred[mask], g["actual_points"]).statistic
        beta_row[pos] = margin_beta(g, pred)
    rho_tab[vname], beta_tab[vname] = rho_row, beta_row

def show(tab, title):
    print(f"\n{title}")
    print(f"  {'variant':14s} " + " ".join(f"{p:>8s}" for p in POSITIONS))
    for vname, row in tab.items():
        print(f"  {vname:14s} " + " ".join(f"{row[p]:8.4f}" for p in POSITIONS))
    print(f"  {'-- deltas vs baseline --':14s}")
    base = tab["baseline"]
    for vname, row in tab.items():
        if vname == "baseline":
            continue
        print(f"  {vname:14s} " + " ".join(f"{row[p]-base[p]:+8.4f}" for p in POSITIONS))

show(rho_tab, "Starter-band Spearman by position (step 0):")
show(beta_tab, "Pairwise margin beta, through-origin, starter band (step 0):")
