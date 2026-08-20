# synthetic_lambda.py
# D4 Phase 2 -- synthetic market-lambda for fixtures the market has not priced.
#
# At ODDS_HORIZON_GWS = 0 the walk-forward (and prod) have real odds only for
# the current gameweek; horizon steps 1+ fall back to the pure Dixon-Coles fit.
# Phase 1 (Logs/d4_market_lambda_log.md) measured that a LightGBM on market
# history + DC + schedule + availability reproduces market lambda at R2
# 0.82-0.91 vs 0.60-0.84 for DC alone, and that the edge holds ~+0.10 across
# horizon staleness steps 1-6. This module serves that model inside the
# pipeline: dixon_coles.get_fixtures fills unpriced fixtures' mkt_lam_h/a from
# here when the gate below is on, and the ordinary tuned blend weights then
# apply (lambda pure synthetic, clean sheets 0.2*DC + 0.8*synthetic) -- the
# synthetic value stands in for the market it approximates.
#
# DESIGN (fixed by the Phase 1 horizon study, section 10 of the log):
#   ONE fresh-trained model, refit per cutoff, fed per-horizon FROZEN features.
#   Training on stale features (one model per step) measured WORSE at every
#   step -- do not rebuild that here.
#
# Freeze semantics at a cutoff date:
#   market history : windows over the team's matches strictly before the cutoff
#   dixon-coles    : the cached per-gameweek walk-forward fit at the cutoff gw
#                    (data/history/d4_dc_walkforward_params.parquet)
#   availability   : top-5-by-minutes ranking from minutes strictly before the
#                    cutoff; statuses at the CUTOFF gameweek's deadline (asof_*)
#   schedule/home  : from the target fixture's calendar row (public in advance)
#
# BACKTEST SCOPE: features come from data/d4_market_lambda_dataset.parquet
# (2016-17..2025-26). Live 2026-27 use needs that dataset extended first.
#
# This flag GATES the fill in dixon_coles.get_fixtures AND is STAMPED into
# every walk-forward file as `synthetic_lambda_active` by both writers -- the
# KNOWN_ISSUES #13 lesson: an equation-input change must be visible in the
# artefact. False restores the pure-DC fallback everywhere.
#
# False is the RESTING STATE after the Phase 2 measurement (2026-08-19,
# Logs/d4_market_lambda_log.md sec 12): the lambda-level edge did NOT
# translate into e_points accuracy or selection gains -- aggregate rho flat to
# slightly negative, top-k at chance across three seasons; the one consistent
# structural effect is margin beta MID/FWD toward 1 and GK/DEF away, at every
# step in every season. NOT adopted. The *_synth.parquet artefacts reproduce
# the measurement; flip to True only with new evidence and a new protocol.
SYNTHETIC_LAMBDA_ACTIVE = False

from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot")
DATASET = BASE / "data" / "d4_market_lambda_dataset.parquet"
DC_CACHE = BASE / "data" / "history" / "d4_dc_walkforward_params.parquet"
VAASTAV = BASE / "data" / "history" / "all_seasons_fixed.parquet"
AV_FILES = {"2021-22": "availability_2122.parquet",
            "2022-23": "availability_2223.parquet",
            "2023-24": "availability_2324.parquet",
            "2024-25": "availability_2425.parquet",
            "2025-26": "availability_2526.parquet"}
UNAVAILABLE = {"i", "s", "u", "n"}
# odds-file name -> vaastav/d4 name. dixon_coles works in odds names; the d4
# dataset (and DC cache) use vaastav names. Same three entries as the Phase 1
# builder; applied internally in get_synthetic.
ALIAS = {"Man United": "Man Utd", "Sheffield United": "Sheffield Utd",
         "Tottenham": "Spurs"}

# PRE-REGISTERED Phase 1 config (Logs/d4_market_lambda_log.md section 6).
MODEL_CFG = {"num_leaves": 15, "learning_rate": 0.03, "n_estimators": 300,
             "min_child_samples": 20}
FIXED = {"objective": "l2", "verbosity": -1, "n_jobs": -1, "seed": 42,
         "deterministic": True, "force_row_wise": True}

FEATURES = [
    "mh_own_l5", "mh_own_l10", "mh_own_s2d",
    "mh_conc_l5", "mh_conc_l10", "mh_conc_s2d",
    "mh_opp_own_l5", "mh_opp_own_l10", "mh_opp_conc_l5", "mh_opp_conc_l10",
    "dc_attack", "dc_defence_opp", "is_home",
    "sch_rest_days", "sch_m14", "sch_rest_days_opp", "sch_m14_opp",
    "av_top5_out", "av_top5_out_opp",
]

_CACHE = {}          # module-level: dataset, dc cache, vaastav, availability
_MODELS = {}         # (season, cutoff_date) -> fitted LGBMRegressor


def _data():
    if "ds" not in _CACHE:
        _CACHE["ds"] = pd.read_parquet(DATASET)
        _CACHE["dc"] = pd.read_parquet(DC_CACHE)
        va = pd.read_parquet(VAASTAV, columns=["season", "team", "element",
                                               "minutes", "kickoff_time"])
        va = va.dropna(subset=["team"])
        va["kick"] = (pd.to_datetime(va["kickoff_time"], utc=True)
                      .dt.tz_localize(None))
        _CACHE["va"] = va
        av = pd.concat([pd.read_parquet(BASE / "data" / f,
                                        columns=["season", "gw", "element",
                                                 "asof_status"])
                        for f in AV_FILES.values()], ignore_index=True)
        _CACHE["av"] = av.set_index(["season", "gw", "element"])["asof_status"]
    return _CACHE


def _model_for(season, cutoff_date):
    """One fresh-trained model per cutoff: Phase 1 features and config, trained
    on every non-burn-in row with match_date strictly before the cutoff --
    prior seasons plus the predicted season to date."""
    key = (season, pd.Timestamp(cutoff_date))
    if key not in _MODELS:
        import lightgbm as lgb
        ds = _data()["ds"]
        tr = ds[(~ds["burn_in"]) & (ds["match_date"] < pd.Timestamp(cutoff_date))]
        mdl = lgb.LGBMRegressor(**FIXED, **MODEL_CFG)
        mdl.fit(tr[FEATURES], tr["market_lambda"])
        _MODELS[key] = mdl
    return _MODELS[key]


def _cutoff_gw(season, cutoff_date):
    """The cached DC fit whose cutoff is the latest one at or before the
    walk-forward cutoff. The d4 cache's cutoff is the midnight date of a
    gameweek's first match; the writers pass that day's first KICKOFF, so the
    right cell is the max cache cutoff <= cutoff_date."""
    dc = _data()["dc"]
    cells = (dc[dc["season"] == season][["gw", "cutoff"]]
             .drop_duplicates().sort_values("cutoff"))
    ok = cells[cells["cutoff"] <= pd.Timestamp(cutoff_date)]
    if len(ok) == 0:       # cutoff before the season's first match -> gw 1 fit
        return int(cells.iloc[0]["gw"])
    return int(ok.iloc[-1]["gw"])


def _frozen_team_stats(season, cutoff_date, teams):
    """Market-history windows and availability count per team, frozen at the
    cutoff. Mirrors the Phase 1 horizon-study freeze exactly."""
    d = _data()
    ds, av_idx, va = d["ds"], d["av"], d["va"]
    gw_c = _cutoff_gw(season, cutoff_date)
    C = pd.Timestamp(cutoff_date)

    out = {}
    for team in teams:
        th = ds[(ds["team"] == team) & (ds["match_date"] < C)]
        th = th.sort_values("match_date")
        own, conc = th["market_lambda"], th["market_lambda_conceded"]
        sown = th[th["season"] == season]
        rec = {
            "mh_own_l5": own.tail(5).mean() if len(own) >= 5 else np.nan,
            "mh_own_l10": own.tail(10).mean() if len(own) >= 10 else np.nan,
            "mh_conc_l5": conc.tail(5).mean() if len(conc) >= 5 else np.nan,
            "mh_conc_l10": conc.tail(10).mean() if len(conc) >= 10 else np.nan,
            "mh_own_s2d": sown["market_lambda"].mean() if len(sown) else np.nan,
            "mh_conc_s2d": (sown["market_lambda_conceded"].mean()
                            if len(sown) else np.nan),
        }
        if season in AV_FILES:
            vt = va[(va["season"] == season) & (va["team"] == team)
                    & (va["kick"] < C)]
            if len(vt):
                top5 = (vt.groupby("element")["minutes"].sum()
                          .sort_values(ascending=False).head(5).index)
                sts = [av_idx.get((season, gw_c, e)) for e in top5]
                found = [s for s in sts if isinstance(s, str)]
                rec["av_top5_out"] = (float(sum(1 for s in found
                                               if s in UNAVAILABLE))
                                      if found else np.nan)
            else:
                rec["av_top5_out"] = np.nan
        else:
            rec["av_top5_out"] = np.nan
        out[team] = rec
    return out, gw_c


def get_synthetic(predict_season, cutoff_date, fixtures):
    """Synthetic lambda for unpriced fixtures.

    fixtures: DataFrame with columns home, away, date_parsed (vaastav-mapped
    team names, as inside dixon_coles.get_fixtures after TEAM_MAP is NOT yet
    applied there -- names here are the ODDS-file names run through the d4
    alias map, which produces the same vaastav names the d4 dataset uses).

    Returns a frame indexed like `fixtures` with syn_lam_h, syn_lam_a.
    Rows whose calendar entry is missing from the d4 dataset come back NaN
    (caller falls back to DC for those, loudly countable via lambda_source).
    """
    ds = _data()["ds"]
    dc = _data()["dc"]
    fixtures = fixtures.copy()
    fixtures["home"] = fixtures["home"].map(lambda t: ALIAS.get(t, t))
    fixtures["away"] = fixtures["away"].map(lambda t: ALIAS.get(t, t))
    teams = sorted(set(fixtures["home"]) | set(fixtures["away"]))
    stats, gw_c = _frozen_team_stats(predict_season, cutoff_date, teams)
    dcc = dc[(dc["season"] == predict_season) & (dc["gw"] == gw_c)]
    atk = dcc.set_index("team")["attack"]
    dfc = dcc.set_index("team")["defence"]

    # target-side calendar rows (is_home, schedule) from the d4 dataset
    cal = ds[ds["season"] == predict_season][
        ["team", "opponent", "match_date", "is_home",
         "sch_rest_days", "sch_m14", "sch_rest_days_opp", "sch_m14_opp"]]
    cal = cal.set_index(["team", "opponent", "match_date"])

    mdl = _model_for(predict_season, cutoff_date)
    res = pd.DataFrame(index=fixtures.index,
                       columns=["syn_lam_h", "syn_lam_a"], dtype=float)
    feat_rows, row_meta = [], []
    for idx, fx in fixtures.iterrows():
        md = pd.Timestamp(fx["date_parsed"]).normalize()
        for team, opp, out_col in [(fx["home"], fx["away"], "syn_lam_h"),
                                   (fx["away"], fx["home"], "syn_lam_a")]:
            try:
                c = cal.loc[(team, opp, md)]
            except KeyError:
                continue                      # not in dataset -> stays NaN
            t, o = stats[team], stats[opp]
            feat_rows.append({
                "mh_own_l5": t["mh_own_l5"], "mh_own_l10": t["mh_own_l10"],
                "mh_own_s2d": t["mh_own_s2d"], "mh_conc_l5": t["mh_conc_l5"],
                "mh_conc_l10": t["mh_conc_l10"], "mh_conc_s2d": t["mh_conc_s2d"],
                "mh_opp_own_l5": o["mh_own_l5"], "mh_opp_own_l10": o["mh_own_l10"],
                "mh_opp_conc_l5": o["mh_conc_l5"],
                "mh_opp_conc_l10": o["mh_conc_l10"],
                "dc_attack": atk.get(team, 0.0),
                "dc_defence_opp": dfc.get(opp, 0.0),
                "is_home": c["is_home"],
                "sch_rest_days": c["sch_rest_days"], "sch_m14": c["sch_m14"],
                "sch_rest_days_opp": c["sch_rest_days_opp"],
                "sch_m14_opp": c["sch_m14_opp"],
                "av_top5_out": t["av_top5_out"],
                "av_top5_out_opp": o["av_top5_out"],
            })
            row_meta.append((idx, out_col))
    if feat_rows:
        preds = mdl.predict(pd.DataFrame(feat_rows)[FEATURES])
        # market lambdas live in ~[0.4, 4.5]; clip only guards pathology
        preds = np.clip(preds, 0.2, 5.0)
        for (idx, col), p in zip(row_meta, preds):
            res.loc[idx, col] = p
    return res
