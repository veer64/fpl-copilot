# bonus.py
# Bonus (BPS) model — two pieces: LightGBM predicts BPS from components, then an
# empirical BPS->expected-bonus curve. Module form for assembly: get_bonus_model()
# returns (bps_model, bps_to_bonus, BPS_FEATURES) so assembly can predict BPS from
# its predicted components and map to expected bonus.
#
# Deliberately simple per master plan §3.4. Final config (verified: MAE 4.19,
# R² 0.747 — trees beat linear due to positional interactions). Core-Insights BPS
# enrichment abandoned (Bug #8: corrupted values + grain mismatch); vaastav kept.

import pandas as pd
import numpy as np
import lightgbm as lgb

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"

COMP = ["goals_scored", "assists", "clean_sheets", "minutes"]
EXTRA = ["saves", "yellow_cards", "red_cards", "goals_conceded", "penalties_missed", "own_goals"]
BPS_FEATURES = COMP + ["is_def", "is_mid", "is_gk"] + EXTRA


def get_bonus_model():
    """Train the BPS predictor + build the BPS->bonus curve.
    Returns (bps_model, bps_to_bonus, BPS_FEATURES):
      bps_model    : fitted LightGBM, predicts BPS from BPS_FEATURES
      bps_to_bonus : fn(bps_values) -> expected bonus (interpolated empirical curve)
      BPS_FEATURES : the feature list the model expects
    """
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    d = df[(df["position"] != "AM") & (df["minutes"] >= 1)].copy()
    for c in ["bps", "bonus"] + COMP + EXTRA:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    # Piece 2: empirical BPS -> expected-bonus curve (bucket by 5, average bonus)
    d["bps_bin"] = (d["bps"] // 5) * 5
    curve = (d.groupby("bps_bin").agg(exp_bonus=("bonus", "mean"), n=("bonus", "size")).reset_index())
    curve = curve[curve["n"] >= 30]
    _bins = curve["bps_bin"].values
    _exp = curve["exp_bonus"].values

    def bps_to_bonus(bps_values):
        b = np.clip(np.asarray(bps_values, dtype=float), _bins.min(), _bins.max())
        return np.interp(b, _bins, _exp)

    # Piece 1: LightGBM predicts BPS from components (+ position + extras)
    d["is_def"] = (d["position"] == "DEF").astype(int)
    d["is_mid"] = (d["position"] == "MID").astype(int)
    d["is_gk"]  = (d["position"] == "GK").astype(int)
    mdf = d.dropna(subset=BPS_FEATURES + ["bps"]).copy()
    tr = mdf[mdf["season"] <= "2024-25"]     # all history for the live model
    bps_model = lgb.LGBMRegressor(n_estimators=300, num_leaves=31, learning_rate=0.05,
                                  random_state=42, verbose=-1).fit(tr[BPS_FEATURES], tr["bps"])

    return bps_model, bps_to_bonus, BPS_FEATURES


if __name__ == "__main__":
    bps_model, bps_to_bonus, feats = get_bonus_model()
    print("Bonus model ready.")
    print("BPS -> expected bonus curve (key points):")
    for bps in [10, 20, 25, 30, 35, 45, 60]:
        print(f"  BPS {bps:3d} -> E[bonus] {bps_to_bonus(bps):.3f}")