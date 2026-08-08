# bonus.py
# Bonus (BPS) model — two pieces: LightGBM predicts BPS from components, then an
# empirical BPS->expected-bonus curve. Module form for assembly: get_bonus_model()
# returns (bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean) so assembly can predict
# BPS from its predicted components, map to expected bonus, and recalibrate.
#
# Deliberately simple per master plan §3.4. Final config (verified: MAE 4.19,
# R² 0.747 — trees beat linear due to positional interactions). Core-Insights BPS
# enrichment abandoned (Bug #8: corrupted values + grain mismatch); vaastav kept.
#
# WALK-FORWARD + LEAK FIXES (2026-08):
#   1. up_to_gw=k trains on prior seasons PLUS current-season GWs strictly < k.
#   2. The empirical BPS->bonus CURVE was previously built on ALL rows including
#      2025-26 (the `season <= 2024-25` filter applied only to the LightGBM model,
#      not the curve). Now the curve respects the same cutoff.
#   3. bonus_mean (used by assembly to recalibrate exp_bonus) was previously the
#      FULL-SEASON 2025-26 actual bonus mean — a leak in any walk-forward context.
#      It is now computed from the same cutoff data and returned by this module.

import pandas as pd
import numpy as np
import lightgbm as lgb

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
TRAIN_UNTIL_SEASON = "2024-25"
PREDICT_SEASON = "2025-26"

COMP = ["goals_scored", "assists", "clean_sheets", "minutes"]
EXTRA = ["saves", "yellow_cards", "red_cards", "goals_conceded", "penalties_missed", "own_goals"]
BPS_FEATURES = COMP + ["is_def", "is_mid", "is_gk"] + EXTRA


def _cutoff_mask(d, up_to_gw):
    """Rows usable for training/curve/mean: all seasons <= 2024-25, plus
    current-season gameweeks strictly before up_to_gw.
    up_to_gw=None -> prior seasons only (original intent)."""
    m = d["season"] <= TRAIN_UNTIL_SEASON
    if up_to_gw is not None:
        m = m | ((d["season"] == PREDICT_SEASON) & (d["GW"] < up_to_gw))
    return m


def get_bonus_model(up_to_gw=None):
    """Train the BPS predictor + build the BPS->bonus curve + the recalibration mean,
    all from data at or before the cutoff.
    Returns (bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean).
    """
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    d = df[(df["position"] != "AM") & (df["minutes"] >= 1)].copy()
    for c in ["bps", "bonus"] + COMP + EXTRA:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    # everything below is built from cutoff-eligible rows ONLY (leak fix #2 and #3)
    elig = d[_cutoff_mask(d, up_to_gw)].copy()

    # Piece 2: empirical BPS -> expected-bonus curve (bucket by 5, average bonus)
    elig["bps_bin"] = (elig["bps"] // 5) * 5
    curve = (elig.groupby("bps_bin").agg(exp_bonus=("bonus", "mean"), n=("bonus", "size")).reset_index())
    curve = curve[curve["n"] >= 30]
    _bins = curve["bps_bin"].values
    _exp = curve["exp_bonus"].values

    def bps_to_bonus(bps_values):
        b = np.clip(np.asarray(bps_values, dtype=float), _bins.min(), _bins.max())
        return np.interp(b, _bins, _exp)

    # Piece 1: LightGBM predicts BPS from components (+ position + extras)
    for col, pos in [("is_def", "DEF"), ("is_mid", "MID"), ("is_gk", "GK")]:
        elig[col] = (elig["position"] == pos).astype(int)
    tr = elig.dropna(subset=BPS_FEATURES + ["bps"])
    bps_model = lgb.LGBMRegressor(n_estimators=300, num_leaves=31, learning_rate=0.05,
                                  random_state=42, verbose=-1).fit(tr[BPS_FEATURES], tr["bps"])

    # Piece 3: recalibration mean — the mean actual bonus over ALL players (incl. non-
    # appearances) at the cutoff. assembly divides its predicted mean into this.
    # Computed over the full player-GW population of the cutoff window, matching how
    # assembly applies it (across every row it is scoring).
    dfa = df[df["position"] != "AM"].copy()
    dfa["bonus"] = pd.to_numeric(dfa["bonus"], errors="coerce")
    bonus_mean = dfa[_cutoff_mask(dfa, up_to_gw)]["bonus"].mean()

    return bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean


if __name__ == "__main__":
    bps_model, bps_to_bonus, feats, bonus_mean = get_bonus_model()
    print("Bonus model ready (prior seasons only).")
    print(f"Recalibration bonus_mean: {bonus_mean:.4f}")
    print("BPS -> expected bonus curve (key points):")
    for bps in [10, 20, 25, 30, 35, 45, 60]:
        print(f"  BPS {bps:3d} -> E[bonus] {bps_to_bonus(bps):.3f}")