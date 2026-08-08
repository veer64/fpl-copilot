# dixon_coles.py
# Dixon-Coles team-goals model: clean-sheet probabilities + fixture goal expectations.
# Module form for assembly: get_fixtures() fits DC on matches before a cutoff and
# returns 2025-26 fixture predictions (per fixture: lam_home/away, p_home/away_cs).
#
# Final config (verified):
#   MLE Poisson: lam_home = exp(atk[h]+def[a]+home_adv), lam_away = exp(atk[a]+def[h])
#   Time-decay : 1-year half-life (won the gridsearch)
#   Low-score  : DC rho correction (negligible, kept for completeness)
#   Blend      : goal expectations (lambda) use PURE MARKET (w=0, best WDL 53.7%);
#                clean sheets use w=0.2 (0.2*DC + 0.8*market, best CS Brier 0.1718)
#
# WALK-FORWARD (2026-08): get_fixtures(cutoff_date=d) fits the DC model on all
# matches strictly BEFORE d, so team strengths update as the season unfolds.
# cutoff_date=None reproduces the original (fit on all pre-2025-26 matches).
#
# SCOPE NOTE: because LAM_BLEND_W = 0.0, the goal expectations (lam_home/lam_away)
# come PURELY from Bet365 odds, which are inherently point-in-time — they carry no
# leak and are unaffected by the cutoff. The DC fit only influences CLEAN SHEETS,
# at 20% weight (CS_BLEND_W). So walk-forward here is a correctness fix with a
# deliberately small footprint.

import pandas as pd
import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
PREDICT_SEASON = "2025-26"
HALF_LIFE_DAYS = 365
LAM_BLEND_W = 0.0     # goal expectations: pure market (best WDL)
CS_BLEND_W = 0.2      # clean sheets: 0.2*DC + 0.8*market (best CS Brier)

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"


def _load_matches():
    odds = pd.read_parquet(BASE + r"\data\history\odds_all_seasons.parquet")
    m = odds[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "season",
              "B365H", "B365D", "B365A"]].copy()
    m.columns = ["date", "home", "away", "home_goals", "away_goals", "season",
                 "b365h", "b365d", "b365a"]
    m["date_parsed"] = pd.to_datetime(m["date"], format="mixed", dayfirst=True)
    return m


def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days):
    idx = {t: i for i, t in enumerate(all_teams)}
    nt = len(all_teams)
    h = train_matches["home"].map(idx).values
    a = train_matches["away"].map(idx).values
    hg = train_matches["home_goals"].values
    ag = train_matches["away_goals"].values
    age = (ref_date - train_matches["date_parsed"]).dt.days.values
    w = np.ones(len(age)) if half_life_days is None else np.exp(-(np.log(2) / half_life_days) * age)

    def nll(params):
        atk, dfc = params[:nt], params[nt:2 * nt]
        hadv, rho = params[-2], params[-1]
        lam_h = np.exp(atk[h] + dfc[a] + hadv)
        lam_a = np.exp(atk[a] + dfc[h])
        log_p = poisson.logpmf(hg, lam_h) + poisson.logpmf(ag, lam_a)
        tau = np.ones(len(hg))
        tau[(hg == 0) & (ag == 0)] = (1 - lam_h * lam_a * rho)[(hg == 0) & (ag == 0)]
        tau[(hg == 0) & (ag == 1)] = (1 + lam_h * rho)[(hg == 0) & (ag == 1)]
        tau[(hg == 1) & (ag == 0)] = (1 + lam_a * rho)[(hg == 1) & (ag == 0)]
        tau[(hg == 1) & (ag == 1)] = (1 - rho)
        log_p = log_p + np.log(np.clip(tau, 1e-10, None))
        return -(w * log_p).sum()

    x0 = np.zeros(2 * nt + 2); x0[-2] = 0.25
    res = minimize(nll, x0, method="L-BFGS-B")
    return res.x, idx, nt


def _outcomes(lam_h, lam_a, max_goals=10):
    hp = poisson.pmf(np.arange(max_goals + 1), lam_h)
    ap = poisson.pmf(np.arange(max_goals + 1), lam_a)
    M = np.outer(hp, ap)
    return np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()


def _implied_lambdas(pH, pD, pA):
    def mm(ll):
        lh, la = np.exp(ll)
        mH, mD, mA = _outcomes(lh, la)
        return (mH - pH) ** 2 + (mD - pD) ** 2 + (mA - pA) ** 2
    return np.exp(minimize(mm, [np.log(1.4), np.log(1.1)], method="Nelder-Mead").x)


METRIC_GLOSSARY = """# Dixon-Coles model — what these metrics mean

This component predicts two things per fixture: how many goals each side is
expected to score (lam_home / lam_away), and each side's chance of a clean sheet.

IMPORTANT SCOPE NOTE. LAM_BLEND_W = 0.0, so the goal expectations come PURELY
from Bet365 odds — the Dixon-Coles fit contributes nothing to them. The DC fit
only influences CLEAN SHEETS, and only at 20% weight (CS_BLEND_W = 0.2).
So the lambda metrics below are really scoring the betting market, not this model.
The clean-sheet metrics are the ones where DC actually has a say.

**brier_cs** — how good the clean-sheet probabilities are.
Take the predicted chance, subtract what happened (1 = clean sheet, 0 = conceded),
square it, average over every team-fixture. 0 is perfect. Lower is better.
This is the headline metric for this component.

**cs_base_rate** — how often a clean sheet actually happened, as a fraction.
Not a quality score. A reference point: always guessing this number would give a
Brier of roughly rate x (1 - rate). If brier_cs isn't clearly below that, the model
is adding nothing over a naive guess.

**wdl_accuracy** — share of fixtures where the most likely result (home win / draw /
away win) was correct. Higher is better. Note this scores the market, not DC.

**mae_goals** — typical error in expected goals per team per match, in goals.
Lower is better. Also scores the market, not DC.

**n_fixtures** — fixtures predicted. A tripwire: a full season is 380.
If this drops, a join or date filter broke.

**n_train_matches** — matches the DC fit learned from. Another tripwire.

**home_advantage** — the fitted home-advantage term, on a log scale.
Not a quality score. exp(home_advantage) is the multiplier on home goals, so
roughly 0.25 means home teams score about 28% more. Logged for lineage and sanity.

**rho** — the Dixon-Coles low-score correction. Known to be negligible here;
kept for completeness. Logged so you can confirm it stays near zero.
"""


def _team_strengths_table(teams, atk, dfc):
    """Human-readable attack/defence strengths, sorted. Logged as a CSV artifact.
    Higher attack = scores more. LOWER defence = concedes fewer (it is a log-scale
    term added to the opponent's goal expectation)."""
    t = pd.DataFrame({"team": teams, "attack": atk, "defence": dfc})
    return t.sort_values("attack", ascending=False).reset_index(drop=True)


def _log_to_mlflow(strengths, params, metrics, run_name):
    """Log one DC run. There is no sklearn/LightGBM object here — the fitted 'model'
    is the parameter vector, so the team strengths table IS the artifact."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name, nested=True):
        mlflow.set_tag("component", "dixon_coles")
        # Shows as the Description panel at the top of the run page in the UI.
        mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
        mlflow.log_text(strengths.to_csv(index=False), "team_strengths.csv")


def _eval_metrics(df, n_train, hadv, rho):
    """Score the predicted fixtures against actual results.
    See METRIC_GLOSSARY — the lambda metrics score the market, not the DC fit."""
    m = {"n_fixtures": float(len(df)),
         "n_train_matches": float(n_train),
         "home_advantage": float(hadv),
         "rho": float(rho)}

    d = df.dropna(subset=["home_goals", "away_goals"])
    if len(d) == 0:
        return m

    # Clean sheets: a home clean sheet means the AWAY side failed to score.
    actual_home_cs = (d["away_goals"] == 0).astype(float)
    actual_away_cs = (d["home_goals"] == 0).astype(float)
    pred = np.concatenate([d["p_home_cs"].values, d["p_away_cs"].values])
    actual = np.concatenate([actual_home_cs.values, actual_away_cs.values])
    m["brier_cs"] = float(((pred - actual) ** 2).mean())
    m["cs_base_rate"] = float(actual.mean())

    # Result accuracy, from the market-implied probabilities.
    if {"p_H", "p_D", "p_A"}.issubset(d.columns):
        pick = d[["p_H", "p_D", "p_A"]].values.argmax(axis=1)
        truth = np.where(d["home_goals"] > d["away_goals"], 0,
                         np.where(d["home_goals"] == d["away_goals"], 1, 2))
        m["wdl_accuracy"] = float((pick == truth).mean())

    # Expected goals vs actual goals, both sides pooled.
    err = np.concatenate([(d["lam_home"] - d["home_goals"]).values,
                          (d["lam_away"] - d["away_goals"]).values])
    m["mae_goals"] = float(np.abs(err).mean())

    return m


def get_fixtures(cutoff_date=None, predict_dates=None, log_mlflow=False):
    """Fit DC on matches strictly before cutoff_date, return 2025-26 fixture predictions.
      cutoff_date   : datetime/date. None -> fit on all pre-2025-26 matches (original).
      predict_dates : optional iterable of dates to restrict the returned fixtures to.
      log_mlflow    : True logs params/metrics/strengths as ONE MLflow run (default off,
                      so assembly.py and the 38-GW walk-forward stay unchanged and fast).
    Returns DataFrame[season, home, away, match_date, lam_home, lam_away,
                      p_home_cs, p_away_cs].
    lam_* use pure market (best WDL); p_*_cs use the 0.2 DC blend (best CS Brier)."""
    matches = _load_matches()
    teams = sorted(set(matches["home"]) | set(matches["away"]))

    if cutoff_date is None:
        train_m = matches[matches["season"] < PREDICT_SEASON].copy()
        ref = matches[matches["season"] == PREDICT_SEASON]["date_parsed"].min()
    else:
        cutoff = pd.to_datetime(cutoff_date)
        train_m = matches[matches["date_parsed"] < cutoff].copy()
        ref = cutoff

    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS)
    atk, dfc, hadv, rho = params[:nt], params[nt:2 * nt], params[-2], params[-1]

    df = matches[matches["season"] == PREDICT_SEASON].copy()
    df = df[df["home"].isin(idx) & df["away"].isin(idx)].copy()
    if predict_dates is not None:
        want = set(pd.to_datetime(list(predict_dates)).date)
        df = df[df["date_parsed"].dt.date.isin(want)].copy()
    if len(df) == 0:
        return pd.DataFrame(columns=["season", "home", "away", "match_date",
                                     "lam_home", "lam_away", "p_home_cs", "p_away_cs"])

    inv = 1 / df[["b365h", "b365d", "b365a"]].values
    df[["p_H", "p_D", "p_A"]] = inv / inv.sum(axis=1, keepdims=True)
    lp = np.array([_implied_lambdas(r.p_H, r.p_D, r.p_A) for r in df.itertuples()])
    df["mkt_lam_h"], df["mkt_lam_a"] = lp[:, 0], lp[:, 1]
    hi = df["home"].map(idx).values; ai = df["away"].map(idx).values
    df["dc_lam_h"] = np.exp(atk[hi] + dfc[ai] + hadv)
    df["dc_lam_a"] = np.exp(atk[ai] + dfc[hi])

    df["lam_home"] = LAM_BLEND_W * df["dc_lam_h"] + (1 - LAM_BLEND_W) * df["mkt_lam_h"]
    df["lam_away"] = LAM_BLEND_W * df["dc_lam_a"] + (1 - LAM_BLEND_W) * df["mkt_lam_a"]
    cs_lh = CS_BLEND_W * df["dc_lam_h"] + (1 - CS_BLEND_W) * df["mkt_lam_h"]
    cs_la = CS_BLEND_W * df["dc_lam_a"] + (1 - CS_BLEND_W) * df["mkt_lam_a"]
    df["p_home_cs"] = np.exp(-cs_la)
    df["p_away_cs"] = np.exp(-cs_lh)

    # keep the source Date so assembly can build the (team, gw) date bridge
    df["match_date"] = df["date_parsed"].dt.date

    if log_mlflow:
        _log_to_mlflow(
            strengths=_team_strengths_table(teams, atk, dfc),
            params={
                "cutoff_date": str(cutoff_date),
                "predict_dates": "all" if predict_dates is None else f"{len(df)} dates",
                "predict_season": PREDICT_SEASON,
                "half_life_days": HALF_LIFE_DAYS,
                "lam_blend_w": LAM_BLEND_W,
                "cs_blend_w": CS_BLEND_W,
                "n_teams": nt,
                "optimizer": "L-BFGS-B on weighted Poisson NLL",
                "odds_source": "Bet365 (B365H/D/A)",
            },
            metrics=_eval_metrics(df, n_train=len(train_m), hadv=hadv, rho=rho),
            run_name=f"dc_{cutoff_date}" if cutoff_date else "dc_static",
        )

    return df[["season", "home", "away", "match_date",
               "lam_home", "lam_away", "p_home_cs", "p_away_cs"]]


# Backward-compat shim: original behaviour (fit on all pre-2025-26 matches)
def get_fixtures_2526():
    return get_fixtures(cutoff_date=None)


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv
    fx = get_fixtures(cutoff_date=None, log_mlflow=log)
    print(f"2025-26 fixture predictions: {len(fx)}")
    print("\nStrongest home clean-sheet fixtures:")
    print(fx.sort_values("p_home_cs", ascending=False).head(6)[
        ["home", "away", "lam_home", "lam_away", "p_home_cs"]].to_string(index=False))