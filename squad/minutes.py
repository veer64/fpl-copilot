# minutes.py
# Minutes model: E[minutes] per player-gameweek via law of total expectation over
# {start / sub / no-play}. Module form for assembly: get_minutes() trains on prior
# seasons (+ optionally the current season up to a cutoff) and predicts.
#
# Full investigation + metrics in minutes_model_log.md. Final component configs
# (verified: Brier 0.0890 / 0.0607 / 0.0870, RMSE 11.99 / 13.68, composed 22.97):
#   P(start)          : LightGBM 300/31, 11 feats + cold-start (has_no_history, prior-season)
#   P(60+|started)    : LightGBM constrained (100/7, min_child 100, lambda 1) + starter-rate feats
#   P(came on|benched): LightGBM 200/15 + isotonic
#   E[min|started]    : LightGBM 200/15 universal feats
#   E[min|sub]        : LightGBM constrained 100/7
#
# WALK-FORWARD (2026-08): get_minutes(up_to_gw=k) trains on prior seasons PLUS
# current-season gameweeks strictly BEFORE k, then predicts. This mirrors live
# operation (the weekly_retrain DAG) and is what the walk-forward harness calls.
# up_to_gw=None reproduces the original behaviour (prior seasons only, predict all).
# Features were already leakage-safe (shift-then-roll); this changes TRAINING data.

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
TRAIN_SEASONS = ["2022-23", "2023-24", "2024-25"]
PREDICT_SEASON = "2025-26"


def _prepare(df):
    """Build the collapsed player-GW frame + all engineered features.
    Pure feature engineering — no training, no season filtering."""
    df = df[df["position"] != "AM"].copy()
    model_df = df[df["starts"].notna()].copy()

    key = ["season", "element", "GW"]
    model_df = model_df.sort_values(key).reset_index(drop=True)
    model_df["is_double_gw"] = (model_df.groupby(key)["minutes"].transform("size") > 1).astype(int)
    agg = {"minutes": "sum", "total_points": "sum", "starts": "max", "is_double_gw": "max"}
    for c in model_df.columns:
        if c not in key and c not in agg:
            agg[c] = "first"
    col = model_df.groupby(key, as_index=False).agg(agg)
    col = col.sort_values(["season", "element", "GW"]).reset_index(drop=True)
    col["minutes_capped"] = col["minutes"].clip(upper=90)
    grp = col.groupby(["season", "element"])
    rp = lambda c, w, h: grp[c].transform(lambda s: s.shift(1).rolling(w, min_periods=1).agg(h))

    col["started_last_gw"] = grp["starts"].shift(1)
    col["starts_last3"] = rp("starts", 3, "sum"); col["starts_last5"] = rp("starts", 5, "sum")
    col["avg_min_last3"] = rp("minutes_capped", 3, "mean"); col["avg_min_last5"] = rp("minutes_capped", 5, "mean")

    def zrun(s):
        p = s.shift(1); z = (p == 0).astype(float)
        return z.groupby((z == 0).cumsum()).cumsum()
    col["consec_zero_mins"] = grp["minutes"].transform(zrun)

    def gss(s):
        p = s.shift(1); return p.groupby((p == 1).cumsum()).cumcount()
    col["gws_since_last_start"] = grp["starts"].transform(gss)

    col["minutes_trend_3"] = grp["minutes_capped"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean() - s.shift(1).rolling(8, min_periods=2).mean())
    col["position_code"] = col["position"].astype("category").cat.codes
    return col


S1 = ["started_last_gw", "starts_last3", "starts_last5", "avg_min_last3", "avg_min_last5",
      "is_double_gw", "consec_zero_mins", "gws_since_last_start", "position_code", "value", "minutes_trend_3"]
SUBF = ["avg_min_last3", "avg_min_last5", "minutes_trend_3", "consec_zero_mins", "gws_since_last_start",
        "starts_last3", "starts_last5", "started_last_gw", "position_code", "value", "is_double_gw"]
SUBRF = ["avg_min_last3", "avg_min_last5", "minutes_trend_3", "consec_zero_mins", "gws_since_last_start",
         "position_code", "value", "is_double_gw"]


def _build_frames(col):
    """Cold-start frame (cs), starter-only frame (sd), bench frame (bd)."""
    sa = (col.groupby(["season", "name"]).agg(prev_start_rate=("starts", "mean"),
          prev_avg_minutes=("minutes_capped", "mean"), prev_games=("starts", "size")).reset_index())
    order = ["2022-23", "2023-24", "2024-25", "2025-26"]
    pm = {order[i]: order[i - 1] for i in range(1, len(order))}
    sa["season"] = sa["season"].map({v: k for k, v in pm.items()}); sa = sa.dropna(subset=["season"])

    cs = col.copy()
    cs["has_no_history"] = cs[["started_last_gw", "avg_min_last3"]].isna().any(axis=1).astype(int)
    cs[S1] = cs[S1].fillna(0)
    cs = cs.merge(sa, on=["season", "name"], how="left")
    cs["transfer_status"] = np.where(cs["prev_start_rate"].isna(), 2, 0)
    cs[["prev_start_rate", "prev_avg_minutes", "prev_games"]] = \
        cs[["prev_start_rate", "prev_avg_minutes", "prev_games"]].fillna(0)

    sd = col[col["starts"] == 1].copy().sort_values(["season", "element", "GW"]).reset_index(drop=True)
    sd["played_60"] = (sd["minutes_capped"] >= 60).astype(int)
    g2 = sd.groupby(["season", "element"])
    sd["past60_rate_3"] = g2["played_60"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    sd["past60_rate_5"] = g2["played_60"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    sd["last_start_minutes"] = g2["minutes_capped"].shift(1)

    bd = col[col["starts"] == 0].copy()
    bd["came_on"] = (bd["minutes"] > 0).astype(int)
    return cs, sd, bd


def _train_mask(frame, up_to_gw):
    """Rows eligible for TRAINING: all prior seasons, plus current-season GWs < up_to_gw.
    up_to_gw=None -> prior seasons only (original behaviour)."""
    m = frame["season"].isin(TRAIN_SEASONS)
    if up_to_gw is not None:
        m = m | ((frame["season"] == PREDICT_SEASON) & (frame["GW"] < up_to_gw))
    return m


# What each logged metric means, in plain English. Logged with every run so the
# numbers are never orphaned from their explanation.
METRIC_GLOSSARY = """# Minutes model — what these metrics mean

**brier_p_start** — how good the "will they start?" probability is.
Take the predicted chance, subtract what actually happened (1 = started, 0 = didn't),
square it, average over every row. 0 is perfect, 0.25 is a coin flip. Lower is better.

**brier_p60** — same idea, for "given they started, did they reach 60 minutes?"
Scored only on rows where the player actually started. Lower is better.

**rmse_e_minutes** — typical error in expected minutes, in minutes.
An RMSE of 23 means predictions are off by roughly 23 minutes on average.
Lower is better. This one is in real units, so it's the easiest to sanity-check.

**mean_e_minutes** — average predicted minutes across all rows.
Not a quality score. A sanity check: if this drifts far from the actual average,
the model is systematically over- or under-predicting playing time.

**n_predicted** — how many player-gameweek rows got a prediction.
Not a quality score. A tripwire: if this suddenly drops, something broke silently
(a bad join, a dropped feature, a filter gone wrong). Expected: 29,338 for a full season.
"""


def _log_to_mlflow(models, params, metrics, run_name):
    """Log one component run: params, metrics, fitted sub-models, and a plain-English
    glossary so the metrics are self-explaining in the UI."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name):
        mlflow.set_tag("component", "minutes")
        # Shows as the Description panel at the top of the run page in the UI.
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
        for name, model in models.items():
            if name == "iso_sub":
                mlflow.sklearn.log_model(model, name=f"minutes_{name}")
            else:
                mlflow.lightgbm.log_model(model, name=f"minutes_{name}")


def _eval_metrics(pf):
    """Evaluation metrics for this run, scored on the sealed 2025-26 season.
    See METRIC_GLOSSARY for what each one means in plain English."""
    m = {}

    # "Will they start?" — predicted probability vs actual 0/1. Lower = better.
    m["brier_p_start"] = float(((pf["p_start"] - pf["starts"]) ** 2).mean())

    # "Did a starter reach 60 mins?" — only scored on rows where they started.
    st = pf[pf["starts"] == 1]
    if len(st):
        actual_60 = (st["minutes_capped"] >= 60).astype(float)
        m["brier_p60"] = float(((st["p60"] - actual_60) ** 2).mean())

    # Typical error in expected minutes, in real minutes. Lower = better.
    m["rmse_e_minutes"] = float(np.sqrt(((pf["e_minutes"] - pf["minutes_capped"]) ** 2).mean()))

    # Sanity checks, not quality scores.
    m["mean_e_minutes"] = float(pf["e_minutes"].mean())
    m["n_predicted"] = float(len(pf))

    return m


def get_minutes(up_to_gw=None, predict_gws=None, log_mlflow=False):
    """Train on prior seasons (+ current season before up_to_gw), predict.
    Returns mins_out: DataFrame[element, gw, name, position, p_start, p60, e_minutes].
    log_mlflow=True logs params/metrics/models as ONE MLflow run (default off, so
    assembly.py and the 38-GW walk-forward stay unchanged and fast)."""
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    col = _prepare(df)
    cs, sd, bd = _build_frames(col)

    FP = S1 + ["has_no_history", "prev_start_rate", "prev_avg_minutes", "prev_games", "transfer_status"]
    S2 = S1 + ["past60_rate_3", "past60_rate_5", "last_start_minutes"]

    trc = cs[_train_mask(cs, up_to_gw)]
    m_ps = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                              random_state=42, verbose=-1).fit(trc[FP], trc["starts"])

    tr2 = sd[_train_mask(sd, up_to_gw)]
    m_p60 = lgb.LGBMClassifier(n_estimators=100, num_leaves=7, min_child_samples=100, reg_lambda=1.0,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(tr2[S2], tr2["played_60"])

    tr3 = bd[_train_mask(bd, up_to_gw)].dropna(subset=SUBF)
    m_sub = lgb.LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=50,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(tr3[SUBF], tr3["came_on"])
    iso = IsotonicRegression(out_of_bounds="clip").fit(m_sub.predict_proba(tr3[SUBF])[:, 1], tr3["came_on"])

    tr4 = sd[_train_mask(sd, up_to_gw)].dropna(subset=S1)
    m_mins = lgb.LGBMRegressor(n_estimators=200, num_leaves=15, min_child_samples=50,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(tr4[S1], tr4["minutes_capped"])

    subs = bd[bd["came_on"] == 1].copy()
    tr5 = subs[_train_mask(subs, up_to_gw)].dropna(subset=SUBRF)
    m_msub = lgb.LGBMRegressor(n_estimators=100, num_leaves=7, min_child_samples=100, reg_lambda=1.0,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(tr5[SUBRF], tr5["minutes_capped"])

    # predict
    sr = sd[["season", "element", "GW", "past60_rate_3", "past60_rate_5", "last_start_minutes"]]
    csx = cs.merge(sr, on=["season", "element", "GW"], how="left")
    csx[["past60_rate_3", "past60_rate_5", "last_start_minutes"]] = \
        csx[["past60_rate_3", "past60_rate_5", "last_start_minutes"]].fillna(0)
    pf = csx[csx["season"] == PREDICT_SEASON].dropna(subset=SUBF + S1).copy()
    if predict_gws is not None:
        pf = pf[pf["GW"].isin(predict_gws)]
    if len(pf) == 0:
        return pd.DataFrame(columns=["element", "gw", "name", "position", "p_start", "p60", "e_minutes"])

    pf["p_start"] = m_ps.predict_proba(pf[FP])[:, 1]
    pf["p60"] = m_p60.predict_proba(pf[S2])[:, 1]
    pf["p_sub"] = iso.predict(m_sub.predict_proba(pf[SUBF])[:, 1])
    pf["min_start"] = m_mins.predict(pf[S1])
    pf["min_sub"] = m_msub.predict(pf[SUBRF])
    pf["e_minutes"] = pf["p_start"] * pf["min_start"] + (1 - pf["p_start"]) * pf["p_sub"] * pf["min_sub"]

    if log_mlflow:
        _log_to_mlflow(
            models={"p_start": m_ps, "p60": m_p60, "p_sub": m_sub,
                    "iso_sub": iso, "min_start": m_mins, "min_sub": m_msub},
            params={
                "up_to_gw": up_to_gw,
                "predict_gws": "all" if predict_gws is None else str(predict_gws),
                "train_seasons": ",".join(TRAIN_SEASONS),
                "predict_season": PREDICT_SEASON,
                "n_train_p_start": len(trc),
                "n_train_p60": len(tr2),
                "n_train_p_sub": len(tr3),
                "n_train_min_start": len(tr4),
                "n_train_min_sub": len(tr5),
                "p_start_cfg": "lgbm 300/31 lr0.05",
                "p60_cfg": "lgbm 100/7 mcs100 l2=1",
                "p_sub_cfg": "lgbm 200/15 + isotonic",
                "min_start_cfg": "lgbm 200/15",
                "min_sub_cfg": "lgbm 100/7 mcs100 l2=1",
            },
            metrics=_eval_metrics(pf),
            run_name=f"minutes_gw{up_to_gw}" if up_to_gw else "minutes_static",
        )

    return pf[["element", "GW", "name", "position", "p_start", "p60", "e_minutes"]].rename(columns={"GW": "gw"})


# Backward-compat shim: original behaviour (prior seasons only, predict all of 2025-26)
def get_minutes_2526():
    return get_minutes(up_to_gw=None)


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv
    mins_out = get_minutes(up_to_gw=None, log_mlflow=log)
    print(f"Minutes predicted for 2025-26: {len(mins_out)} player-GWs")
    print(f"Mean e_minutes: {mins_out['e_minutes'].mean():.1f}")
    print("\nTop e_minutes (should be nailed players):")
    print(mins_out.sort_values("e_minutes", ascending=False).head(6).to_string(index=False))