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
#
# ODDS AVAILABILITY (2026-08): the above holds only for fixtures whose odds have
# actually been PUBLISHED. A rolling-horizon transfer planner standing at gameweek
# k wants goal expectations for k+3, and bookmakers have usually not priced that
# match yet. Two consequences, one per environment:
#
#   PROD      — the odds feed simply returns nothing for unpriced fixtures.
#   BACKTEST  — the historical file has every match, so using them is a mild leak:
#               those odds reflect team news the manager could not have had.
#
# Both are handled by the SAME mechanism, so there is no separate prod path to
# write later. Odds are used where they exist; Dixon-Coles fills the gap where they
# do not — precisely the job the DC fit was built for and has so far barely been
# used for. `odds_available_until` lets the backtest SIMULATE the prod constraint;
# leaving it None means "use whatever odds are present", which is what prod does
# naturally.

import pandas as pd
import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize

# D4 Phase 2: synthetic market-lambda for unpriced fixtures. The gate constant
# SYNTHETIC_LAMBDA_ACTIVE lives in synthetic_lambda.py (the owning module) and
# is stamped into every walk-forward artefact by both writers. Import is cheap:
# the module loads its data lazily.
import synthetic_lambda

BASE = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
PREDICT_SEASON = "2025-26"
HALF_LIFE_DAYS = 365

# --- Shrinkage on team strengths (pre-registered: Logs/dc_shrinkage_prereg_2026-09-13.md,
# change A). A Gaussian prior centred at 0 (= the league-average multiplier, the
# parameterisation's own centre and the unmatched-fixture fill's neutral point) on every
# attack and defence parameter, applied as 0.5 * SHRINK_TAU * sum(theta^2) on the weighted
# NLL -- the MAP estimate of the same model. Without it the likelihood of a club with no
# archive history and a one-sided record (no goals scored, or none conceded) is monotone
# in that parameter and L-BFGS-B stops at -6..-8 with `converged` False: the club's
# fixtures are priced at lambda ~0.001 (live 2026-27 GW5: Coventry City attack, Hull City
# defence; record: 2024-25 cutoff 2, Ipswich). The strength is stated in league-average
# pseudo-matches: per match the Fisher information of an attack/defence parameter is
# ~lambda ~1.40, so tau = 1.40 * k is worth k such matches and the posterior mode shrinks
# the MLE by n_eff / (n_eff + k), n_eff = the club's decay-weighted match count. k = 4 was
# fixed BEFORE any measurement and is not tuned on the endpoint: a scoreless promoted club
# after three matches sits at ~0.61x league attack instead of 0; a club with 20 effective
# matches keeps 83% of its MLE; an established club (n_eff ~60-70 at the 365-day half-life)
# keeps >= 94%. The prior releases as evidence accrues and never re-tightens.
#
# OUTCOME 2026-09-14 (Logs/dc_shrinkage_log_2026-09-13.md section 3): k = 4 was FALSIFIED on
# its pre-registered endpoint -- the steps-1-5 top-30 sliced Spearman fell by 0.0052 (2023-24)
# and 0.0065 (2024-25) against the bar of -0.005 -- so the prior is OFF: SHRINK_K = 0 makes the
# penalty term exactly 0.0 and the objective bit-identical to the pre-shrinkage fit (parity
# and the as-of guard verified on that). The machinery stays so the next pre-registration
# (a different k or form is a NEW prereg, never a tuning of this one) is one constant away.
# The runaway-parameter defect it was meant to bound (KNOWN_ISSUES #25, "exposed") is
# therefore still OPEN.
SHRINK_K = 0
SHRINK_TAU = 1.40 * SHRINK_K          # 1.40 = LEAGUE_AVG_LAMBDA, the neutral fill's lambda

# --- Live club names vs the archive (prereg change B). The football-data archive names
# a returning club 'Hull' / 'Ipswich'; the live pull (and FPL) name it 'Hull City' /
# 'Ipswich Town'. Unmapped, a returning club has NO history in the fit. The alias is applied
# INSIDE the fit only (which rows belong to which club); fixture OUTPUT names are untouched,
# so assembly's TEAM_MAP join to the FPL-named frame is unchanged. Checked 2026-09-13
# (Logs/dc_fix_log_2026-09-13.md section 10): 17 of 20 live clubs join every archive season
# under their exact name; only the promoted three do not.
ARCHIVE_NAME_ALIAS = {"Hull City": "Hull", "Ipswich Town": "Ipswich"}
# Clubs of a predict season with ZERO prior-season rows in the archive under ANY name --
# genuinely new to the archive, declared per season so the guard below can tell a new
# promotion from an unmapped alias. Both directions are checked: an undeclared club with no
# history refuses the build (probably an alias nobody mapped), and a declared club that DOES
# have history refuses it too (a stale declaration). 2025-26's promoted three (Leeds,
# Burnley, Sunderland) all have archive rows, hence no entry.
NEW_TO_ARCHIVE = {"2023-24": {"Luton"}, "2024-25": {"Ipswich"}, "2026-27": {"Coventry City"}}


def canon_club(name):
    """Archive-canonical club name for the fit (see ARCHIVE_NAME_ALIAS)."""
    return ARCHIVE_NAME_ALIAS.get(name, name)


def check_new_clubs(matches_canon, predict_season):
    """The name guard (prereg change B): every club in the predict season's fixtures must
    have prior-season rows in the archive (under its canonical name) OR be declared in
    NEW_TO_ARCHIVE for that season -- and the declaration must be exact. Raises ValueError;
    a build must never quietly run a returning club as a stranger."""
    cur = matches_canon[matches_canon["season"] == predict_season]
    hist = matches_canon[matches_canon["season"] < predict_season]
    seen = set(hist["home"]) | set(hist["away"])
    clubs = set(cur["home"]) | set(cur["away"])
    declared = set(NEW_TO_ARCHIVE.get(predict_season, set()))
    no_history = {t for t in clubs if t not in seen}
    undeclared = sorted(no_history - declared)
    stale = sorted((declared & clubs) - no_history)
    if undeclared or stale:
        raise ValueError(
            f"Dixon-Coles club-name guard for {predict_season}: "
            + (f"clubs with NO prior-season archive rows and not declared new: {undeclared} "
               f"(an unmapped alias? see ARCHIVE_NAME_ALIAS / NEW_TO_ARCHIVE); " if undeclared else "")
            + (f"declared new but they DO have history: {stale}; " if stale else "")
            + "refusing to fit.")
    return no_history
LAM_BLEND_W = 0.0     # goal expectations: pure market (best WDL)
CS_BLEND_W = 0.2      # clean sheets: 0.2*DC + 0.8*market (best CS Brier)

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"


def _load_matches(predict_season=None):
    """The odds/fixture archive, resolved PER PREDICT SEASON: a season the frozen
    archive contains reads the archive verbatim (so historical builds stay
    byte-identical -- the 2025-26 parity gate); a season it does not contain
    (2026-27+) reads odds_all_seasons_with_{tag}.parquet, the archive plus the
    FPL-API fixture slice (eval/fetch_fixtures.py: fixture columns real, price
    columns null -> those fixtures take the pure-DC path, counted per fixture).
    Missing extension -> loud FileNotFoundError, never an empty universe."""
    from pathlib import Path as _P
    path = _P(BASE) / "data" / "history" / "odds_all_seasons.parquet"
    if predict_season is not None:
        seasons = set(pd.read_parquet(path, columns=["season"])["season"].unique())
        if predict_season not in seasons:
            ext = _P(BASE) / "data" / "history" / \
                f"odds_all_seasons_with_{predict_season.replace('-', '_')}.parquet"
            if not ext.exists():
                raise FileNotFoundError(
                    f"{predict_season} is in neither {path.name} nor {ext.name}. Run "
                    f"eval/fetch_fixtures.py --season {predict_season} then --combine first.")
            path = ext
    odds = pd.read_parquet(path)
    m = odds[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "season",
              "B365H", "B365D", "B365A"]].copy()
    m.columns = ["date", "home", "away", "home_goals", "away_goals", "season",
                 "b365h", "b365d", "b365a"]
    m["date_parsed"] = pd.to_datetime(m["date"], format="mixed", dayfirst=True)
    return m


def knowable_before(matches, cutoff):
    """RULE R (Logs/dc_fix_prereg_2026-09-13.md): a match RESULT is knowable at
    `cutoff` iff the match FINISHED before the cutoff DAY began -- dated
    strictly before that day, with both goals present.

    This is the ONE definition of the as-of boundary for match results. It
    is used in exactly two places, deliberately: the training filter in
    get_fixtures (selects the rows it admits) and the as-of guard's
    truncation in eval/asof_reconstruction.py (nulls the rows it excludes).
    Before 2026-09-13 the two were aligned by accident -- both compared the
    archive's DAY-stamped dates against a cutoff WITH time of day, so every
    match on the cutoff day counted as "before the cutoff" on both sides:
    the record's fit trained on that day's results (a leak) and the live fit
    trained on that day's UNPLAYED fixtures (NaN goals -> the optimiser
    returned its starting point, silently). Day granularity is exact here:
    the cutoff is the gameweek's first kickoff, so no match of that day has
    finished at it. The goals clause excludes a postponed fixture still
    carrying its original date. Sharing this function is what lets the two
    sides DISAGREE: loosen either and the guard fails.
    """
    day = pd.Timestamp(cutoff).normalize()
    return ((matches["date_parsed"] < day)
            & matches["home_goals"].notna() & matches["away_goals"].notna())


LAST_FIT = {}   # summary of the most recent fit, for the runner's KNOWLEDGE block / provenance


def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days):
    # The assertion behind the rule: a NaN goal in the training set turns the
    # likelihood NaN and L-BFGS-B returns its INITIAL parameters without any
    # error (observed live on every 2026-27 build until 2026-09-13). Under
    # knowable_before this cannot fire; it exists so that any path that
    # bypasses the rule fails loudly instead of returning the starting point.
    n_nan = int(train_matches[["home_goals", "away_goals"]].isna().any(axis=1).sum())
    if n_nan:
        raise ValueError(
            f"Dixon-Coles training set contains {n_nan} match(es) without a result (NaN goals) -- "
            "refusing to fit: the optimiser would silently return its starting point. Filter the "
            "training rows with dixon_coles.knowable_before(matches, cutoff).")
    if len(train_matches) == 0:
        raise ValueError("Dixon-Coles training set is empty -- refusing to fit")
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
        # the Gaussian prior at 0 on team strengths (SHRINK_TAU; home_adv and rho free)
        return -(w * log_p).sum() + 0.5 * SHRINK_TAU * (np.sum(atk ** 2) + np.sum(dfc ** 2))

    x0 = np.zeros(2 * nt + 2); x0[-2] = 0.25
    res = minimize(nll, x0, method="L-BFGS-B")
    # decay-weighted match count per club: the evidence the prior is weighed against
    n_eff = np.zeros(nt)
    np.add.at(n_eff, h, w); np.add.at(n_eff, a, w)
    i_min = int(np.argmin(n_eff))
    LAST_FIT.clear()
    LAST_FIT.update(n_train=int(len(train_matches)), n_teams=int(nt), iterations=int(res.nit),
                    converged=bool(res.success), max_abs_attack=float(np.abs(res.x[:nt]).max()),
                    max_abs_defence=float(np.abs(res.x[nt:2 * nt]).max()),
                    home_adv=float(res.x[-2]), rho=float(res.x[-1]),
                    ref_date=str(pd.Timestamp(ref_date)),
                    shrink_k=int(SHRINK_K), shrink_tau=float(SHRINK_TAU),
                    n_eff_min=float(n_eff[i_min]), n_eff_min_club=str(all_teams[i_min]))
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


def _odds_are_usable(df, odds_available_until):
    """Which fixtures may use market odds.

    A fixture qualifies only if its odds are BOTH present in the data and, when a
    horizon is given, published by then. Everything else falls back to the DC fit.
    """
    present = df[["b365h", "b365d", "b365a"]].notna().all(axis=1)
    if odds_available_until is None:
        return present
    limit = pd.to_datetime(odds_available_until)
    return present & (df["date_parsed"] <= limit)


def get_fixtures(predict_season=None, cutoff_date=None, predict_dates=None,
                 odds_available_until=None,
                 log_mlflow=False):
    """Fit DC on matches strictly before cutoff_date, return fixture predictions.

    `predict_season` defaults to PREDICT_SEASON (2025-26) so existing callers are
    unchanged. It must be threaded through the BODY, not just declared: a
    parameter that is accepted and ignored is worse than no parameter, because the
    caller believes it took effect. This one silently returned 2025-26 fixtures for
    a 2023-24 request, which made every fixture-dependent term NaN and, after the
    groupby-sum in collapse_to_gameweek, an apparently harmless 0.0.
      cutoff_date   : datetime/date. None -> fit on all pre-2025-26 matches (original).
      predict_dates : optional iterable of dates to restrict the returned fixtures to.
      odds_available_until : date beyond which market odds are treated as UNPUBLISHED,
                      so those fixtures fall back to the pure Dixon-Coles fit. None
                      means "use whatever odds are present" — exactly what prod does,
                      since an odds feed returns nothing for unpriced games. The
                      backtest passes a date to simulate that same constraint.
      log_mlflow    : True logs params/metrics/strengths as ONE MLflow run (default off,
                      so assembly.py and the 38-GW walk-forward stay unchanged and fast).
    Returns DataFrame[season, home, away, match_date, lam_home, lam_away,
                      p_home_cs, p_away_cs].
    lam_* use pure market (best WDL); p_*_cs use the 0.2 DC blend (best CS Brier)."""
    predict_season = PREDICT_SEASON if predict_season is None else predict_season
    matches = _load_matches(predict_season)
    # Club identity for the FIT is the archive-canonical name (prereg change B); the
    # fixture rows keep their own names for the output. `matches` (names as loaded) is
    # what the output is built from; `mc` is what the fit is trained on.
    mc = matches.assign(home=matches["home"].map(canon_club), away=matches["away"].map(canon_club))
    check_new_clubs(mc, predict_season)
    teams = sorted(set(mc["home"]) | set(mc["away"]))

    if cutoff_date is None:
        train_m = mc[mc["season"] < predict_season].copy()
        ref = mc[mc["season"] == predict_season]["date_parsed"].min()
    else:
        cutoff = pd.to_datetime(cutoff_date)
        # RULE R: results knowable at the cutoff = finished before the cutoff
        # DAY (see knowable_before). Was `date_parsed < cutoff` -- a timed
        # cutoff against day-stamped dates admitted the cutoff day's matches:
        # their results in the backtest (LEAKAGE.md item 7), their unplayed
        # NaN goals live (the degenerate fit, Logs/dc_degenerate_fit_finding
        # _2026-09-13.md). Fixed 2026-09-13; the record was rebuilt.
        train_m = mc[knowable_before(mc, cutoff)].copy()
        ref = cutoff

    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS)
    atk, dfc, hadv, rho = params[:nt], params[nt:2 * nt], params[-2], params[-1]

    df = matches[matches["season"] == predict_season].copy()
    df = df[df["home"].map(canon_club).isin(idx) & df["away"].map(canon_club).isin(idx)].copy()
    if predict_dates is not None:
        want = set(pd.to_datetime(list(predict_dates)).date)
        df = df[df["date_parsed"].dt.date.isin(want)].copy()
    if len(df) == 0:
        return pd.DataFrame(columns=["season", "home", "away", "match_date",
                                     "lam_home", "lam_away", "p_home_cs", "p_away_cs",
                                     "odds_used"])

    # Dixon-Coles goal expectations: always computable, no odds required. This is
    # the fallback for any fixture the market has not priced.
    hi = df["home"].map(canon_club).map(idx).values; ai = df["away"].map(canon_club).map(idx).values
    df["dc_lam_h"] = np.exp(atk[hi] + dfc[ai] + hadv)
    df["dc_lam_a"] = np.exp(atk[ai] + dfc[hi])

    # Market-implied goal expectations, only where odds are usable.
    usable = _odds_are_usable(df, odds_available_until)
    df["odds_used"] = usable
    df["mkt_lam_h"] = np.nan
    df["mkt_lam_a"] = np.nan
    df["p_H"] = np.nan; df["p_D"] = np.nan; df["p_A"] = np.nan

    if usable.any():
        sub = df.loc[usable]
        inv = 1 / sub[["b365h", "b365d", "b365a"]].values
        probs = inv / inv.sum(axis=1, keepdims=True)
        df.loc[usable, ["p_H", "p_D", "p_A"]] = probs
        lp = np.array([_implied_lambdas(*row) for row in probs])
        df.loc[usable, "mkt_lam_h"] = lp[:, 0]
        df.loc[usable, "mkt_lam_a"] = lp[:, 1]

    # D4 Phase 2: where odds are NOT usable and the gate is on, fill the market
    # lambdas from the synthetic model instead of collapsing to pure DC. The
    # synthetic value stands in for the market it approximates, so the ordinary
    # tuned weights apply to it (lambda pure synthetic, CS 0.2*DC + 0.8*synth).
    # lambda_source makes the fill verifiable per fixture: odds | synthetic | dc.
    df["lambda_source"] = np.where(usable, "odds", "dc")
    synth_filled = pd.Series(False, index=df.index)
    if (synthetic_lambda.SYNTHETIC_LAMBDA_ACTIVE and cutoff_date is not None
            and (~usable).any()):
        syn = synthetic_lambda.get_synthetic(
            predict_season, cutoff,
            df.loc[~usable, ["home", "away", "date_parsed"]])
        got = syn["syn_lam_h"].notna() & syn["syn_lam_a"].notna()
        ii = syn.index[got]
        df.loc[ii, "mkt_lam_h"] = syn.loc[ii, "syn_lam_h"]
        df.loc[ii, "mkt_lam_a"] = syn.loc[ii, "syn_lam_a"]
        synth_filled.loc[ii] = True
        df.loc[ii, "lambda_source"] = "synthetic"

    # Blend per fixture. Where a market value exists (real or synthetic) the
    # tuned weights apply; where neither does, the weight collapses to pure DC.
    # Writing it as a per-row weight rather than two code paths keeps the tuned
    # configuration in exactly one place.
    priced = usable.values | synth_filled.values
    lam_w = np.where(priced, LAM_BLEND_W, 1.0)
    cs_w = np.where(priced, CS_BLEND_W, 1.0)
    mkt_h = df["mkt_lam_h"].fillna(df["dc_lam_h"])
    mkt_a = df["mkt_lam_a"].fillna(df["dc_lam_a"])

    df["lam_home"] = lam_w * df["dc_lam_h"] + (1 - lam_w) * mkt_h
    df["lam_away"] = lam_w * df["dc_lam_a"] + (1 - lam_w) * mkt_a
    cs_lh = cs_w * df["dc_lam_h"] + (1 - cs_w) * mkt_h
    cs_la = cs_w * df["dc_lam_a"] + (1 - cs_w) * mkt_a
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
                "predict_season": predict_season,
                "half_life_days": HALF_LIFE_DAYS,
                "lam_blend_w": LAM_BLEND_W,
                "cs_blend_w": CS_BLEND_W,
                "n_teams": nt,
                "optimizer": "L-BFGS-B on weighted Poisson NLL",
                "odds_source": "Bet365 closing (B365H/D/A; football-data archive seasons). "
                               "2026-27+: the-odds-api uk h2h, de-margined MEDIAN CONSENSUS "
                               "over a fixed 12-book panel, pre-deadline snapshot -- NOT "
                               "Bet365, NOT closing; the B365* columns carry it because they "
                               "are the only price columns the model reads "
                               "(eval/fetch_live_odds.py provenance has the per-pull detail)",
                "odds_available_until": str(odds_available_until),
                "odds_coverage_pct": round(100 * float(usable.mean()), 1),
            },
            metrics=_eval_metrics(df, n_train=len(train_m), hadv=hadv, rho=rho),
            run_name=f"dc_{cutoff_date}" if cutoff_date else "dc_static",
        )

    return df[["season", "home", "away", "match_date",
               "lam_home", "lam_away", "p_home_cs", "p_away_cs", "odds_used",
               "lambda_source"]]


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