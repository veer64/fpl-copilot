# horizon_minutes.py
# Horizon minutes prediction: ONE prediction per horizon step instead of the
# cutoff's step-0 frame copied to all six target gameweeks.
#
# WHY. eval/walkforward_season.py copies the cutoff's minutes frame to every
# target gameweek, so from cutoff c the prediction for c+5 is the prediction
# for c ("form as of c persists"). Measured cost (Logs/horizon_minutes_scoping_log.md
# section 2): the fresh-vs-stale E[min] MAE gap is +2.3 .. +7.0 minutes at
# k = 1 .. 5, with Spearman, Brier and AUC degrading the same way.
#
# SHAPE. The SAME decomposition as squad/minutes.py -- P(start), P(60+|start),
# P(came on|bench), E[min|start], E[min|sub], identical hyperparameters --
# fitted SEPARATELY for each horizon step k >= 1 on LAGGED PAIRS: features as
# of gameweek g, label at gameweek g+k. Each step therefore learns how much to
# trust features of that age. Step 0 is NOT re-implemented: it delegates to
# minutes.get_minutes() and is untouched by construction (verified exact,
# Logs/horizon_minutes_log.md section 1).
#
# WALK-FORWARD DISCIPLINE. For cutoff c and step k the training pairs are all
# prior-season pairs plus current-season pairs whose LABEL gameweek g+k <= c-1
# -- the label must already be known at the cutoff. Features are the cutoff-c
# row of the same frame the step-0 model uses (shift-then-roll history plus
# the as-of availability block), so nothing after the cutoff enters.
#
# GATE + PROVENANCE. HORIZON_MINUTES_ACTIVE is the single constant a writer
# consults; HORIZON_LEVERS names the enabled levers. Every row this module
# emits carries `horizon_minutes_active`, `horizon_levers`, `horizon_step`
# and the training-season list. The gate rests False: nothing in production
# consumes this until a lever passes the acceptance test (Logs/horizon_minutes_log.md).
#
# LEVERS (build order of record; one at a time, measured after each):
#   "refit"       -- step-aware refit, existing features only (this file).
#   "suspensions" -- derivable bans from cards, known-unavailable at the step.
#   "returns"     -- return dates parsed from asof_news, exposed at steps >= j.
#   "congestion"  -- fixture congestion (with the FINAL-calendar caveat).
# Only levers listed in HORIZON_LEVERS are applied; unknown names raise.

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression

import minutes as mm
import availability_features as avf

HORIZON_MINUTES_ACTIVE = False        # production gate; rests False
HORIZON_LEVERS = ("refit",)           # levers applied when active
KNOWN_LEVERS = ("refit", "suspensions", "returns", "congestion")

OUT_COLS = ["element", "gw", "horizon_step", "name", "position", "p_start", "p60",
            "p_sub", "min_start", "min_sub", "e_minutes"]


def _check_levers(levers):
    bad = set(levers) - set(KNOWN_LEVERS)
    if bad:
        raise ValueError(f"unknown horizon lever(s) {sorted(bad)}; known {KNOWN_LEVERS}")
    if levers and levers[0] != "refit":
        raise ValueError("'refit' is the base lever and must come first")


def _frames(availability, train_seasons, predict_season):
    """The step-0 model's own frames, built once per call: col (labels),
    csx (prediction/feature frame incl. cold-start and starter-history)."""
    from season_stack import load_stack
    df = load_stack()   # stack + forward skeleton: a LIVE cutoff's prediction rows
    col = mm._prepare(df)  # are its forward rows (2026-27 refit, 2026-08-31)
    AV = avf.FEATURES if availability else []
    if AV:
        col = avf.attach(col)
    cs, sd, bd = mm._build_frames(col)
    # `cs` carries the starter-history block as of each gameweek (minutes._build_frames,
    # LEAKAGE.md item 9): the refit's cutoff row is no longer selected on the
    # realised start at the cutoff. Same frame code as step 0 -- fixed once.
    csx = cs
    FP = mm.S1 + ["has_no_history", "prev_start_rate", "prev_avg_minutes", "prev_games", "transfer_status"]
    S2 = mm.S1 + mm.STARTER_HISTORY
    feats = dict(xFP=FP + AV, xS2=S2 + AV, xS1=mm.S1 + AV, xSUBF=mm.SUBF + AV, xSUBRF=mm.SUBRF + AV)
    labels = col[["season", "element", "GW", "starts", "minutes", "minutes_capped"]].copy()
    labels = labels[labels["starts"].notna()]   # forward-skeleton rows carry no label
    labels["played_60"] = (labels["minutes_capped"] >= 60).astype(int)
    labels["came_on"] = (labels["minutes"] > 0).astype(int)
    return csx, labels, feats


def _pairs(csx, labels, k):
    """Lagged pairs: features at GW g (csx row), label at GW g+k (labels row)."""
    lab = labels.rename(columns={"GW": "GW_label", "starts": "y_starts", "minutes": "y_minutes",
                                 "minutes_capped": "y_minutes_capped", "played_60": "y_played_60",
                                 "came_on": "y_came_on"})
    lab["GW"] = lab["GW_label"] - k
    return csx.merge(lab, on=["season", "element", "GW"], how="inner")


def _train_mask(pairs, up_to_gw, train_seasons, predict_season):
    """Prior seasons in full; current season only where the LABEL gameweek is
    strictly before the cutoff."""
    m = pairs["season"].isin(train_seasons)
    if up_to_gw is not None:
        m = m | ((pairs["season"] == predict_season) & (pairs["GW_label"] < up_to_gw))
    return m


def _fit_step(pairs, feats):
    """The five sub-models of minutes.get_minutes, identical configs, fitted on
    lagged pairs."""
    xFP, xS2, xS1, xSUBF, xSUBRF = (feats[c] for c in ("xFP", "xS2", "xS1", "xSUBF", "xSUBRF"))
    m_ps = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                              random_state=42, verbose=-1).fit(pairs[xFP], pairs["y_starts"])
    st = pairs[pairs["y_starts"] == 1]
    m_p60 = lgb.LGBMClassifier(n_estimators=100, num_leaves=7, min_child_samples=100, reg_lambda=1.0,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(st[xS2], st["y_played_60"])
    bn = pairs[pairs["y_starts"] == 0].dropna(subset=mm.SUBF)
    m_sub = lgb.LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=50,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(bn[xSUBF], bn["y_came_on"])
    iso = IsotonicRegression(out_of_bounds="clip").fit(m_sub.predict_proba(bn[xSUBF])[:, 1], bn["y_came_on"])
    st1 = st.dropna(subset=mm.S1)
    m_mins = lgb.LGBMRegressor(n_estimators=200, num_leaves=15, min_child_samples=50,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(st1[xS1], st1["y_minutes_capped"])
    sb = bn[bn["y_came_on"] == 1].dropna(subset=mm.SUBRF)
    m_msub = lgb.LGBMRegressor(n_estimators=100, num_leaves=7, min_child_samples=100, reg_lambda=1.0,
                               learning_rate=0.05, random_state=42, verbose=-1).fit(sb[xSUBRF], sb["y_minutes_capped"])
    return dict(p_start=m_ps, p60=m_p60, p_sub=m_sub, iso=iso, min_start=m_mins, min_sub=m_msub)


def _predict(models, pf, feats):
    xFP, xS2, xS1, xSUBF, xSUBRF = (feats[c] for c in ("xFP", "xS2", "xS1", "xSUBF", "xSUBRF"))
    out = pf.copy()
    out["p_start"] = models["p_start"].predict_proba(pf[xFP])[:, 1]
    out["p60"] = models["p60"].predict_proba(pf[xS2])[:, 1]
    out["p_sub"] = models["iso"].predict(models["p_sub"].predict_proba(pf[xSUBF])[:, 1])
    out["min_start"] = models["min_start"].predict(pf[xS1])
    out["min_sub"] = models["min_sub"].predict(pf[xSUBRF])
    out["e_minutes"] = out["p_start"] * out["min_start"] + (1 - out["p_start"]) * out["p_sub"] * out["min_sub"]
    return out


def get_minutes_horizon(up_to_gw, steps=range(0, 6), availability=None, train_seasons=None,
                        predict_season=None, levers=None, per_fixture=True, verbose=False):
    """Per-step minutes predictions from cutoff `up_to_gw` for gameweeks
    up_to_gw + k, k in steps. Step 0 is minutes.get_minutes() verbatim.
    Returns DataFrame[OUT_COLS + provenance stamps]."""
    levers = tuple(HORIZON_LEVERS if levers is None else levers)
    _check_levers(levers)
    train_seasons = mm.TRAIN_SEASONS if train_seasons is None else list(train_seasons)
    predict_season = mm.PREDICT_SEASON if predict_season is None else predict_season
    availability = mm.AVAILABILITY_DEFAULT if availability is None else availability
    frames = []
    steps = list(steps)
    if 0 in steps:
        m0 = mm.get_minutes(up_to_gw=up_to_gw, predict_gws=[up_to_gw], per_fixture=per_fixture,
                            availability=availability, train_seasons=train_seasons,
                            predict_season=predict_season)
        f0 = mm.get_minutes.last_frame[["element", "GW", "name", "position", "p_start", "p60",
                                        "p_sub", "min_start", "min_sub", "e_minutes"]].rename(columns={"GW": "gw"})
        # the returned frame and last_frame are the same rows; assert it
        assert len(f0) == len(m0) and np.allclose(f0["e_minutes"].values, m0["e_minutes"].values)
        f0["horizon_step"] = 0
        frames.append(f0[OUT_COLS])
    ks = [k for k in steps if k >= 1]
    if ks:
        csx, labels, feats = _frames(availability, train_seasons, predict_season)
        pf = csx[(csx["season"] == predict_season) & (csx["GW"] == up_to_gw)] \
            .dropna(subset=mm.SUBF + mm.S1).copy()
        if per_fixture:
            pf["is_double_gw"] = 0
        for k in ks:
            pairs = _pairs(csx, labels, k)
            tr = pairs[_train_mask(pairs, up_to_gw, train_seasons, predict_season)]
            tr = tr.dropna(subset=mm.SUBF + mm.S1)
            models = _fit_step(tr, feats)
            fk = _predict(models, pf, feats)
            fk["gw"] = up_to_gw + k
            fk["horizon_step"] = k
            if verbose:
                print(f"    step {k}: {len(tr):,} training pairs -> {len(fk)} predictions")
            frames.append(fk[OUT_COLS])
    out = pd.concat(frames, ignore_index=True)
    out["cutoff"] = up_to_gw
    out["horizon_minutes_active"] = True
    out["horizon_levers"] = ",".join(levers)
    out["minutes_availability"] = bool(availability)
    out["train_seasons"] = ",".join(train_seasons)
    out["predict_season"] = predict_season
    return out
