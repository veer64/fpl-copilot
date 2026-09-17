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

# --- Team-strength regularisation, pre-registered v2 (Logs/dc_shrinkage_threshold_prereg_2026-09-17.md,
# approved 2026-09-17). Two parts, each doing one job; both leave evidence-rich clubs at their
# exact maximum-likelihood values BY CONSTRUCTION -- the mechanism that falsified the first
# attempt (a Gaussian prior on EVERY club, k = 4: it compressed the strongest fixtures, where
# the top-30 slice lives; Logs/dc_shrinkage_log_2026-09-13.md) is this design's constraint.
#
#   (A) THE HINGE IS A PRIOR ABOUT EVIDENCE. Per club, tau_i = SHRINK_TAU0 * max(0, 1 - n_eff_i /
#       SHRINK_N), added as 0.5 * sum_i tau_i * (atk_i^2 + dfc_i^2) to the weighted NLL; n_eff_i is
#       the club's decay-weighted match count. tau0 = 5.6 (four league-average pseudo-matches at
#       zero evidence); N = 10 from the record's evidence table (a club in the league in either of
#       the last two seasons carries n_eff >= 25 at cutoff 1; a no-history club crosses 10 at
#       cutoff 12-13). Above N the penalty is exactly 0.0 -- when no club is below N the objective
#       is bit-for-bit the unregularised one.
#   (B) THE BOX IS A BOUND ABOUT FOOTBALL. atk_i, dfc_i in [-ATK_DFC_BOUND, +ATK_DFC_BOUND] = 0.25x
#       to 4x the league rate. On 21 record fits (cutoffs 2..38 of three seasons) clubs with
#       n_eff >= 10 span attack [-0.53, +0.90] and defence [-0.69, +0.51]: inside the box by at
#       least 0.49 in log on every side; the league's historical extremes (worst attack ~0.4x,
#       best defence ~0.3x) are inside it too. It is applied ONLY when the unbounded fit leaves the
#       box -- a one-sided record whose likelihood has no minimum -- so a cutoff that never needed
#       it takes the identical optimiser path (the structural bit-identity the prereg demands).
#       A club that hits the bound is recorded in LAST_FIT["at_bound"]; live_deadline reports it as
#       CLAMPED (the box working), which the fatal raise must never treat as a runaway.
#
# What a club with zero goals and no history gets (MAP under A, then B): 0.55x the league rate
# after 3 scoreless matches, 0.46x after 4, 0.31x after 6, 0.25x (the box) from 8 onward and
# forever -- lambda ~0.41 v an average defence, ~0.17 v the strongest defence the record has
# fitted. History: the k = 4 global prior of 2026-09-13 was FALSIFIED and removed; a different
# tau0 / N / bound is a NEW pre-registration, never a tuning of this one. SHRINK_N = 0 switches
# the hinge off and ATK_DFC_BOUND = None the box, each exactly (a revert, if the bar falsifies).
#
# IDENTIFIABILITY (found at implementation, 2026-09-17, before any endpoint number; recorded in
# the prereg log): the likelihood is invariant to atk + c / dfc - c, so "attack 0" means nothing
# on its own. The record's fits sit in the gauge sum(atk) = sum(dfc) (L-BFGS-B from zeros never
# moves along the flat direction), where the LEAGUE MEAN attack is about +0.09, not 0. A prior
# or a box written on the raw coordinates is therefore not what the prereg's words say ("the
# league rate") -- and worse, the optimiser can cheapen one club's penalty by shifting the WHOLE
# league along the flat direction, and a raw-coordinate box lets a scoreless club keep running
# off through that shift until some established club hits the opposite bound (seen on the
# synthetic test). Both parts therefore act on CENTRED parameters, atk_i - mean(atk) and
# dfc_i - mean(dfc) over the clubs in the fit: invariant to the gauge, so the fit stays in the
# record's gauge and "0.25x the league rate" means exactly that. The box becomes a linear
# constraint (SLSQP on the refit only; L-BFGS-B, the record's optimiser, everywhere else).
# The hinge applies to the clubs whose parameters are USED (the predict season's clubs,
# `prior_teams`): a club relegated two seasons earlier sits at n_eff ~ 9.5 in every fit, and a
# hinge on it would switch the penalty on at every cutoff and break the bit-identity promised.
SHRINK_TAU0 = 1.40 * 4                # 1.40 = LEAGUE_AVG_LAMBDA, the neutral fill's lambda; 4 pseudo-matches
SHRINK_N = 10                         # effective matches at which the hinge has fully released
ATK_DFC_BOUND = float(np.log(4.0))    # the plausibility box, +-ln 4 (0.25x .. 4x)

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


def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days, prior_teams=None):
    """Fit the DC model on `train_matches` (canonical names). `prior_teams`: the clubs the
    hinge prior may touch (the predict season's clubs); None = every club in the fit.
    Refuses (raises) a training set with unplayed matches or no rows -- see knowable_before."""
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
    hg = train_matches["home_goals"].values.astype(float)
    ag = train_matches["away_goals"].values.astype(float)
    age = (ref_date - train_matches["date_parsed"]).dt.days.values
    w = np.ones(len(age)) if half_life_days is None else np.exp(-(np.log(2) / half_life_days) * age)

    # (A) evidence per club (decay-weighted match count) and the hinge precision it earns
    n_eff = np.zeros(nt)
    np.add.at(n_eff, h, w); np.add.at(n_eff, a, w)
    in_prior = np.ones(nt, dtype=bool) if prior_teams is None else np.array([t in set(prior_teams) for t in all_teams])
    tau_i = np.zeros(nt)
    if SHRINK_N:
        tau_i[in_prior] = SHRINK_TAU0 * np.clip(1.0 - n_eff[in_prior] / SHRINK_N, 0.0, None)
    hinge_on = bool((tau_i > 0).any())
    # "The league rate" is the mean over the LEAGUE -- the predict season's clubs (prior_teams) --
    # not over every club the archive has ever held. The fit's team list spans every archive
    # season, so it carries clubs with little or NO training evidence (a club promoted in a later
    # season has zero rows: a phantom whose parameters nothing anchors). A mean over all of them
    # hands the optimiser a free slack variable: it moved a phantom's defence to +26 to shift the
    # mean and cheapen one hinged club's penalty, and the box then clamped the phantom at both
    # bounds (first reference build, 2023-24 cutoffs 2-10; Logs/dc_shrinkage_v2_log_2026-09-17.md
    # section 1(d)). Centring and the box are therefore over `in_prior` only; every other club is
    # the plain MLE (or the starting point, for a phantom), exactly as on the record.
    pri = np.where(in_prior)[0]

    def centred(p):
        atk, dfc = p[:nt], p[nt:2 * nt]
        return np.concatenate([atk - atk[pri].mean(), dfc - dfc[pri].mean()])

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
        val = -(w * log_p).sum()
        if hinge_on:
            # (A) the hinge prior on the evidence-poor clubs' CENTRED parameters (gauge-invariant)
            c = centred(params)
            val = val + 0.5 * float(np.sum(tau_i * (c[:nt] ** 2 + c[nt:] ** 2)))
        return val

    x0 = np.zeros(2 * nt + 2); x0[-2] = 0.25
    res = minimize(nll, x0, method="L-BFGS-B")                     # the unbounded fit, the record's optimiser
    method, boxed_refit = "L-BFGS-B", False
    B = ATK_DFC_BOUND
    c0 = centred(res.x)
    if B is not None and float(max(np.abs(c0[pri]).max(), np.abs(c0[nt + pri]).max())) > B:
        # (B) the box, ONLY because the unbounded fit left it: for the league's clubs,
        # |atk_i - mean(atk)| <= B and the same for defence, as linear inequality constraints
        # A p + B >= 0 (rows: +-(e_i - 1/n_league over the league's clubs))
        npri = len(pri)
        C = np.zeros((2 * npri, 2 * nt + 2))
        for r, i in enumerate(pri):
            C[r, pri] = -1.0 / npri;            C[r, i] += 1.0
            C[npri + r, nt + pri] = -1.0 / npri; C[npri + r, nt + i] += 1.0
        A = np.vstack([C, -C])
        cons = [{"type": "ineq", "fun": lambda p, A=A, B=B: A @ p + B, "jac": lambda p, A=A: A}]
        res = minimize(nll, x0, method="SLSQP", constraints=cons, options={"maxiter": 1000})
        method, boxed_refit = "SLSQP", True
    x = res.x
    c = centred(x)
    at_bound = {}
    if B is not None:
        for i in pri:
            t = all_teams[i]
            hit = [nm for nm, v in (("attack", c[i]), ("defence", c[nt + i])) if abs(abs(v) - B) < 1e-5]
            if hit:
                at_bound[str(t)] = hit
    # gate (e) of the prereg: how close the nearest ESTABLISHED club (in the league, n_eff >= N,
    # not at a bound) sits to the box; and the evidence of the league's poorest club
    est = [i for i in pri if n_eff[i] >= (SHRINK_N or 0) and str(all_teams[i]) not in at_bound]
    margins = [(B - abs(c[i]), str(all_teams[i]), "attack") for i in est] + \
              [(B - abs(c[nt + i]), str(all_teams[i]), "defence") for i in est] if B is not None else []
    m_min = min(margins) if margins else (None, None, None)
    i_min = int(min(pri, key=lambda i: n_eff[i]))
    LAST_FIT.clear()
    LAST_FIT.update(n_train=int(len(train_matches)), n_teams=int(nt), iterations=int(res.nit),
                    converged=bool(res.success), method=method, boxed_refit=boxed_refit,
                    max_abs_attack=float(np.abs(x[:nt]).max()), max_abs_defence=float(np.abs(x[nt:2 * nt]).max()),
                    max_abs_centred_attack=float(np.abs(c[pri]).max()), max_abs_centred_defence=float(np.abs(c[nt + pri]).max()),
                    league_mean_attack=float(x[pri].mean()), league_mean_defence=float(x[nt + pri].mean()),
                    n_league=int(len(pri)),
                    home_adv=float(x[-2]), rho=float(x[-1]),
                    ref_date=str(pd.Timestamp(ref_date)),
                    shrink_tau0=float(SHRINK_TAU0), shrink_n=int(SHRINK_N or 0),
                    bound=(None if B is None else float(B)),
                    n_eff_min=float(n_eff[i_min]), n_eff_min_club=str(all_teams[i_min]),
                    clubs_below_n={str(all_teams[i]): {"n_eff": round(float(n_eff[i]), 2), "tau": round(float(tau_i[i]), 3)}
                                   for i in range(nt) if tau_i[i] > 0},
                    at_bound=at_bound,
                    min_margin_to_bound=(None if m_min[0] is None else round(float(m_min[0]), 4)),
                    min_margin_club=(None if m_min[0] is None else f"{m_min[1]} {m_min[2]}"))
    return x, idx, nt


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

    cur = mc[mc["season"] == predict_season]
    prior_teams = sorted(set(cur["home"]) | set(cur["away"]))      # the clubs whose parameters are USED
    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS, prior_teams=prior_teams)
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