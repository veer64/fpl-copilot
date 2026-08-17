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

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
TRAIN_UNTIL_SEASON = "2024-25"
PREDICT_SEASON = "2025-26"

COMP = ["goals_scored", "assists", "clean_sheets", "minutes"]
EXTRA = ["saves", "yellow_cards", "red_cards", "goals_conceded", "penalties_missed", "own_goals"]
BPS_FEATURES = COMP + ["is_def", "is_mid", "is_gk"] + EXTRA


def _cutoff_mask(d, up_to_gw, train_until=None, predict_season=None):
    """Rows usable for training/curve/mean: all seasons <= 2024-25, plus
    current-season gameweeks strictly before up_to_gw.
    up_to_gw=None -> prior seasons only (original intent)."""
    train_until = TRAIN_UNTIL_SEASON if train_until is None else train_until
    predict_season = PREDICT_SEASON if predict_season is None else predict_season
    m = d["season"] <= train_until
    if up_to_gw is not None:
        m = m | ((d["season"] == predict_season) & (d["GW"] < up_to_gw))
    return m


METRIC_GLOSSARY = """# Bonus model — what these metrics mean

Two pieces are being scored: a LightGBM that predicts BPS from a player's
components, and an empirical curve that maps BPS to expected bonus points.

All metrics are on HELD-OUT rows only — everything the cutoff excluded from
training. So they are honest out-of-sample numbers, not training scores.

**mae_bps** — typical error when predicting a player's BPS, in BPS units.
An MAE of 4.2 means predictions are off by about 4 BPS on average. Lower is better.

**r2_bps** — how much of the variation in BPS the model explains. 1.0 is perfect,
0.0 means it does no better than always guessing the average. Higher is better.

**mae_exp_bonus** — typical error in predicted bonus points, in actual FPL points.
This is the number that matters for the final prediction. Lower is better.
Bonus is usually 0, so a small MAE here is expected and not impressive on its own.

**bonus_mean** — average bonus points per player-gameweek at the cutoff.
Not a quality score. Assembly uses it to recalibrate, so it is logged for lineage.

**n_curve_bins** — how many BPS buckets survived the 30-row minimum.
A tripwire: if this drops sharply, the curve got thin and unreliable.

**n_train_bps** — rows the BPS model trained on. Another tripwire.

**n_held_out** — rows the metrics above were scored on. Another tripwire.
"""


def _log_to_mlflow(model, params, metrics, run_name):
    """Log one bonus run: params, metrics, the fitted BPS model, and the glossary."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name, nested=True):
        mlflow.set_tag("component", "bonus")
        # Shows as the Description panel at the top of the run page in the UI.
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
        mlflow.lightgbm.log_model(model, name="bonus_bps_model")


def _eval_metrics(bps_model, bps_to_bonus, held_out, n_curve_bins, n_train, bonus_mean):
    """Score on HELD-OUT rows — everything the cutoff kept OUT of training.
    See METRIC_GLOSSARY for what each metric means in plain English."""
    m = {"bonus_mean": float(bonus_mean),
         "n_curve_bins": float(n_curve_bins),
         "n_train_bps": float(n_train)}

    ho = held_out.dropna(subset=BPS_FEATURES + ["bps", "bonus"])
    if len(ho):
        pred_bps = bps_model.predict(ho[BPS_FEATURES])

        # Typical error predicting BPS itself.
        m["mae_bps"] = float(np.abs(pred_bps - ho["bps"]).mean())

        # Share of BPS variation explained. 1.0 perfect, 0.0 no better than the mean.
        ss_res = float(((ho["bps"] - pred_bps) ** 2).sum())
        ss_tot = float(((ho["bps"] - ho["bps"].mean()) ** 2).sum())
        m["r2_bps"] = float(1 - ss_res / ss_tot) if ss_tot else 0.0

        # End-to-end: BPS prediction pushed through the curve, vs actual bonus points.
        m["mae_exp_bonus"] = float(np.abs(bps_to_bonus(pred_bps) - ho["bonus"]).mean())

        m["n_held_out"] = float(len(ho))

    return m


def get_bonus_model(up_to_gw=None, log_mlflow=False, train_until=None,
                    predict_season=None):
    """Train the BPS predictor + build the BPS->bonus curve + the recalibration mean,
    all from data at or before the cutoff.
    Returns (bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean).
    log_mlflow=True logs params/metrics/model as ONE MLflow run (default off, so
    assembly.py and the 38-GW walk-forward stay unchanged and fast).
    """
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    d = df[(df["position"] != "AM") & (df["minutes"] >= 1)].copy()
    for c in ["bps", "bonus"] + COMP + EXTRA:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    # everything below is built from cutoff-eligible rows ONLY (leak fix #2 and #3)
    elig = d[_cutoff_mask(d, up_to_gw, train_until, predict_season)].copy()

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
    bonus_mean = dfa[_cutoff_mask(dfa, up_to_gw, train_until, predict_season)]["bonus"].mean()

    if log_mlflow:
        # Held-out = everything the cutoff EXCLUDED from training. The honest future.
        held_out = d[~_cutoff_mask(d, up_to_gw, train_until, predict_season)].copy()
        for col, pos in [("is_def", "DEF"), ("is_mid", "MID"), ("is_gk", "GK")]:
            held_out[col] = (held_out["position"] == pos).astype(int)
        _log_to_mlflow(
            model=bps_model,
            params={
                "up_to_gw": up_to_gw,
                "train_until_season": TRAIN_UNTIL_SEASON,
                "predict_season": PREDICT_SEASON,
                "bps_model_cfg": "lgbm 300/31 lr0.05",
                "curve_bin_width": 5,
                "curve_min_rows_per_bin": 30,
                "n_features": len(BPS_FEATURES),
                "features": ",".join(BPS_FEATURES),
            },
            metrics=_eval_metrics(bps_model, bps_to_bonus, held_out,
                                  n_curve_bins=len(curve), n_train=len(tr),
                                  bonus_mean=bonus_mean),
            run_name=f"bonus_gw{up_to_gw}" if up_to_gw else "bonus_static",
        )

    return bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv
    bps_model, bps_to_bonus, feats, bonus_mean = get_bonus_model(log_mlflow=log)
    print("Bonus model ready (prior seasons only).")
    print(f"Recalibration bonus_mean: {bonus_mean:.4f}")
    print("BPS -> expected bonus curve (key points):")
    for bps in [10, 20, 25, 30, 35, 45, 60]:
        print(f"  BPS {bps:3d} -> E[bonus] {bps_to_bonus(bps):.3f}")