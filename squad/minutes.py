# minutes.py
# Minutes model: E[minutes] per player-gameweek via law of total expectation over
# {start / sub / no-play}. Module form for assembly: get_minutes_2526() trains on
# all prior seasons and returns mins_out for the live season.
#
# Full investigation + metrics in minutes_model_log.md. Final component configs
# (verified: Brier 0.0890 / 0.0607 / 0.0870, RMSE 11.99 / 13.68, composed 22.97):
#   P(start)          : LightGBM 300/31, 11 feats + cold-start (has_no_history, prior-season)
#   P(60+|started)    : LightGBM constrained (100/7, min_child 100, lambda 1) + starter-rate feats
#   P(came on|benched): LightGBM 200/15 + isotonic
#   E[min|started]    : LightGBM 200/15 universal feats
#   E[min|sub]        : LightGBM constrained 100/7
#
# For assembly we TRAIN on all prior seasons (2022-25) and predict the live 2025-26
# season. 2025-26 is the sealed test season — predicted, never tuned against.

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
TRAIN_SEASONS = ["2022-23", "2023-24", "2024-25"]
PREDICT_SEASON = "2025-26"


def get_minutes_2526():
    """Train all minutes components on 2022-25, predict 2025-26.
    Returns mins_out: DataFrame[element, gw, name, position, p_start, p60, e_minutes]."""
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
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

    s1 = ["started_last_gw", "starts_last3", "starts_last5", "avg_min_last3", "avg_min_last5",
          "is_double_gw", "consec_zero_mins", "gws_since_last_start", "position_code", "value", "minutes_trend_3"]

    # prior-season fallback (mapped to next season) + cold start
    sa = (col.groupby(["season", "name"]).agg(prev_start_rate=("starts", "mean"),
          prev_avg_minutes=("minutes_capped", "mean"), prev_games=("starts", "size")).reset_index())
    order = ["2022-23", "2023-24", "2024-25", "2025-26"]
    pm = {order[i]: order[i - 1] for i in range(1, len(order))}
    sa["season"] = sa["season"].map({v: k for k, v in pm.items()}); sa = sa.dropna(subset=["season"])

    cs = col.copy()
    cs["has_no_history"] = cs[["started_last_gw", "avg_min_last3"]].isna().any(axis=1).astype(int)
    cs[s1] = cs[s1].fillna(0)
    cs = cs.merge(sa, on=["season", "name"], how="left")
    cs["transfer_status"] = np.where(cs["prev_start_rate"].isna(), 2, 0)
    cs[["prev_start_rate", "prev_avg_minutes", "prev_games"]] = cs[["prev_start_rate", "prev_avg_minutes", "prev_games"]].fillna(0)
    fp = s1 + ["has_no_history", "prev_start_rate", "prev_avg_minutes", "prev_games", "transfer_status"]

    # starter-only feats for p60
    sd = col[col["starts"] == 1].copy().sort_values(["season", "element", "GW"]).reset_index(drop=True)
    sd["played_60"] = (sd["minutes_capped"] >= 60).astype(int)
    g2 = sd.groupby(["season", "element"])
    sd["past60_rate_3"] = g2["played_60"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    sd["past60_rate_5"] = g2["played_60"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    sd["last_start_minutes"] = g2["minutes_capped"].shift(1)
    s2 = s1 + ["past60_rate_3", "past60_rate_5", "last_start_minutes"]

    # train components on 2022-25
    trc = cs[cs["season"].isin(TRAIN_SEASONS)]
    m_ps = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1).fit(trc[fp], trc["starts"])
    tr2 = sd[sd["season"].isin(TRAIN_SEASONS)]
    m_p60 = lgb.LGBMClassifier(n_estimators=100, num_leaves=7, min_child_samples=100, reg_lambda=1.0, learning_rate=0.05, random_state=42, verbose=-1).fit(tr2[s2], tr2["played_60"])
    bd = col[col["starts"] == 0].copy(); bd["came_on"] = (bd["minutes"] > 0).astype(int)
    subf = ["avg_min_last3", "avg_min_last5", "minutes_trend_3", "consec_zero_mins", "gws_since_last_start",
            "starts_last3", "starts_last5", "started_last_gw", "position_code", "value", "is_double_gw"]
    tr3 = bd[bd["season"].isin(TRAIN_SEASONS)].dropna(subset=subf)
    m_sub = lgb.LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=50, learning_rate=0.05, random_state=42, verbose=-1).fit(tr3[subf], tr3["came_on"])
    iso = IsotonicRegression(out_of_bounds="clip").fit(m_sub.predict_proba(tr3[subf])[:, 1], tr3["came_on"])
    tr4 = sd[sd["season"].isin(TRAIN_SEASONS)].dropna(subset=s1)
    m_mins = lgb.LGBMRegressor(n_estimators=200, num_leaves=15, min_child_samples=50, learning_rate=0.05, random_state=42, verbose=-1).fit(tr4[s1], tr4["minutes_capped"])
    subs = bd[bd["came_on"] == 1].copy()
    subrf = ["avg_min_last3", "avg_min_last5", "minutes_trend_3", "consec_zero_mins", "gws_since_last_start", "position_code", "value", "is_double_gw"]
    tr5 = subs[subs["season"].isin(TRAIN_SEASONS)].dropna(subset=subrf)
    m_msub = lgb.LGBMRegressor(n_estimators=100, num_leaves=7, min_child_samples=100, reg_lambda=1.0, learning_rate=0.05, random_state=42, verbose=-1).fit(tr5[subrf], tr5["minutes_capped"])

    # predict 2025-26
    sr = sd[["season", "element", "GW", "past60_rate_3", "past60_rate_5", "last_start_minutes"]]
    csx = cs.merge(sr, on=["season", "element", "GW"], how="left")
    csx[["past60_rate_3", "past60_rate_5", "last_start_minutes"]] = csx[["past60_rate_3", "past60_rate_5", "last_start_minutes"]].fillna(0)
    pf = csx[csx["season"] == PREDICT_SEASON].dropna(subset=subf + s1).copy()
    pf["p_start"] = m_ps.predict_proba(pf[fp])[:, 1]
    pf["p60"] = m_p60.predict_proba(pf[s2])[:, 1]
    pf["p_sub"] = iso.predict(m_sub.predict_proba(pf[subf])[:, 1])
    pf["min_start"] = m_mins.predict(pf[s1])
    pf["min_sub"] = m_msub.predict(pf[subrf])
    pf["e_minutes"] = pf["p_start"] * pf["min_start"] + (1 - pf["p_start"]) * pf["p_sub"] * pf["min_sub"]

    return pf[["element", "GW", "name", "position", "p_start", "p60", "e_minutes"]].rename(columns={"GW": "gw"})


if __name__ == "__main__":
    mins_out = get_minutes_2526()
    print(f"Minutes predicted for 2025-26: {len(mins_out)} player-GWs")
    print(f"Mean e_minutes: {mins_out['e_minutes'].mean():.1f}")
    print("\nTop e_minutes (should be nailed players):")
    print(mins_out.sort_values("e_minutes", ascending=False).head(6).to_string(index=False))