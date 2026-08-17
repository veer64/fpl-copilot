"""
ev_surface.py -- a hindsight-informed expected-value surface, for EVALUATION ONLY.

WHAT THIS IS
------------
For every player-fixture in a season, this computes the expected FPL points that
player-fixture was WORTH, rather than the points it happened to return. The
scoring terms and constants are exactly those of `squad/scoring.py` -- verified
term by term against 2025-26, where the reconstruction reproduces `total_points`
on 29,757 of 29,757 rows -- but the volatile inputs are replaced by smoothed
expectations.

WHY IT EXISTS
-------------
Realized season points cannot distinguish prediction quality. Measured on this
project: path noise sd = 60.0 points, and a model whose predictions are shrunk
75% toward the positional mean scores INDISTINGUISHABLY from the full model. The
variance is the haul/blank realization lottery of the 15 owned players, and it
swamps every effect worth measuring.

This surface removes that lottery while preserving the decisions. Two arms are
scored against the same fixed EV surface, so the difference between them is the
difference in the squads they chose -- not in whether those squads' strikers
happened to convert that week.

WHAT IS DELIBERATELY *NOT* SMOOTHED
-----------------------------------
MINUTES. Appearance points and the 60-minute gate come from realized minutes, and
every rate term is scaled by realized minutes. This is the single most important
design decision in the file: a policy that avoided a player who was benched or
injured MUST be credited for it, because lineup and availability judgement is the
main thing prediction quality can actually buy here. Smoothing minutes would
delete exactly the skill being measured. A player who did not play scores ~0 EV,
as he should.

Realized fixture and opponent are likewise used as-is -- the schedule is known in
advance and carries no luck.

HINDSIGHT IS EXPLICITLY PERMITTED
---------------------------------
This is an EVALUATOR, not a predictor. It may freely use information that was not
available at the deadline: full-season rates, the realized fixture list, closing
odds, and the season's own BPS-to-bonus curve. That is legitimate here for the
same reason a poker equity calculator may look at both hands -- it is scoring a
decision after the fact, against a yardstick that is identical for every arm.

    NOTHING IN THIS FILE MAY EVER BE IMPORTED BY `squad/`.

Doing so would leak full-season hindsight into the prediction path and silently
invalidate every walk-forward result in the project. This module reads data and
returns a frame; it must stay downstream of everything that makes decisions.
`squad/` may be imported BY an evaluation script that also imports this, but the
dependency must never point the other way.

METHOD, TERM BY TERM
--------------------
    appearance   realized minutes -> 2 (>=60) / 1 (>0) / 0            NOT smoothed
    goals        EB-shrunk xG per 90 x minutes x fixture_scale x GOAL_PTS[pos]
    assists      EB-shrunk xA per 90 x minutes x fixture_scale x 3
    clean sheet  market-implied P(CS) x CS_PTS[pos], gated on minutes >= 60
    saves        E[floor(S/3)], S ~ Poisson(shrunk saves rate x minutes)
    conceded     -E[floor(C/2)], C ~ Poisson(shrunk conceded rate x minutes),
                 GK/DEF only
    yellow/red   EB-shrunk card rates per 90 x minutes, x -1 / -3
    own goals    EB-shrunk rate per 90 x minutes x -2
    pens missed  EB-shrunk rate per 90 x minutes x -2
    pens saved   EB-shrunk rate per 90 x minutes x +5
    defensive    EB-shrunk P(hit threshold) per 90 x minutes x 2, GK ineligible
    bonus        EB-shrunk BPS per 90 x minutes -> curve fit on EXPECTED bps

THREE ESTIMATOR CHOICES THAT MATTER
-----------------------------------
Each was measured against the verified realized decomposition, and each was worth
hundreds to thousands of points of level error before being corrected.

1. The scoring rule FLOORS (`saves // 3`, `conceded // 2`). The expectation of a
   floor is not the floor of an expectation, so `mu / divisor` is biased -- up
   for saves, down for conceded. Both terms take the expectation over a Poisson
   count instead. Worth ~1,250 points combined.

2. The bonus curve is fit on EXPECTED bps, not realized bps. Fitting on realized
   values and then evaluating at a smoothed input under-counts bonus roughly
   tenfold, because the curve is convex where bonus is won and the smoothed input
   has far less spread. See `_bonus_curve`. Worth ~2,200 points.

3. Goals and assists carry a single scalar LEVEL calibration each, because xG/xA
   measure a different quantity from the scoring event (FPL assists include
   deflections and won penalties that xA never models). A scalar cannot alter
   the cross-sectional ranking, which is where the signal lives.

Goals conceded uses the player's own smoothed rate rather than the fixture's
market lambda, as specified. This is mildly inconsistent with the clean-sheet
term, which is fixture-derived; the term is small and the inconsistency is
documented rather than silently reconciled.

ERA-CORRECTNESS
---------------
Seasons before 2025-26 had no defensive-contribution rule, so `ev_dc` is zero for
them by construction. Seasons before 2022-23 have no xG columns, so the goals and
assists terms fall back to realized season goals/assists per 90. Both fallbacks
are reported by `build_ev_surface` in its returned attrs.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import poisson

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY = REPO_ROOT / "data" / "history"
ALL_SEASONS = HISTORY / "all_seasons_fixed.parquet"
ODDS = HISTORY / "odds_all_seasons.parquet"

# --- scoring constants: identical to squad/scoring.py and the verified 100% fit ---
GOAL_PTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
DC_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}  # GK ineligible
SAVES_PER_POINT = 3
CONCEDED_PER_PENALTY = 2
YELLOW_PTS, RED_PTS, OG_PTS, PEN_MISS_PTS, PEN_SAVE_PTS = -1, -3, -2, -2, 5
DC_PTS = 2

# Football-data.co.uk uses a third naming convention; only two clubs differ.
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs"}

# Empirical-Bayes half-trust constants, in 90-minute blocks. Deliberately coarse:
# the evaluator's job is variance reduction, not rate precision, and the project
# has already established (Shrinkage log 4.6) that fine per-cell k tuning is false
# precision. Rare events get a large k so they shrink hard toward the position
# prior rather than tracking one freak occurrence.
SHRINK_K = {
    "goals": 10.0, "assists": 10.0, "saves": 5.0, "conceded": 5.0,
    "yellow": 10.0, "red": 30.0, "og": 30.0, "penmiss": 30.0,
    "pensave": 30.0, "dc": 5.0, "bps": 5.0,
}

FIXTURE_SCALE_CLIP = (0.5, 2.0)
MAX_GOALS = 15          # truncation for the Poisson scoreline grid
DEFAULT_TOTAL_GOALS = 2.75   # fallback match total when over/under odds are absent


# ---------------------------------------------------------------------------
# Market inversion: odds -> per-team goal expectations -> P(clean sheet)
# ---------------------------------------------------------------------------
def _devig(probs):
    """Strip the bookmaker margin by normalising implied probabilities to 1."""
    s = sum(probs)
    return [p / s for p in probs] if s > 0 else probs


def _p_over_25(total):
    """P(more than 2.5 goals) for a match total ~ Poisson(total)."""
    return 1.0 - poisson.cdf(2, total)


def _p_home_win(lam_h, lam_a):
    """P(home win) under independent Poisson scorelines."""
    i = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(i, lam_h)
    pa = poisson.pmf(i, lam_a)
    # lower triangle: home goals strictly greater than away goals
    return float(np.sum(np.outer(ph, pa) * np.greater.outer(i, i)))


def _solve_lambdas(p_home, p_away, p_over):
    """Recover (lam_home, lam_away) from devigged 1X2 and over/under-2.5 prices.

    Two nested one-dimensional root finds rather than a 2-D solve, because each
    is monotone and therefore cannot fail to bracket:
      1. the match TOTAL is pinned by P(over 2.5), monotone increasing;
      2. the SUPREMACY is then pinned by P(home win) at that total, also monotone.
    """
    try:
        total = brentq(lambda L: _p_over_25(L) - p_over, 0.05, 12.0)
    except ValueError:
        total = DEFAULT_TOTAL_GOALS

    eps = 1e-6
    lo, hi = -total + eps, total - eps

    def f(sup):
        return _p_home_win((total + sup) / 2.0, (total - sup) / 2.0) - p_home

    try:
        sup = brentq(f, lo, hi)
    except ValueError:
        # Target outside the achievable range at this total: clamp to the
        # nearer bound rather than inventing a solution.
        sup = lo if abs(f(lo)) < abs(f(hi)) else hi

    return (total + sup) / 2.0, (total - sup) / 2.0


def _pick_odds_columns(odds):
    """Prefer CLOSING prices, fall back to opening, then to the market average.

    Closing odds are the sharpest estimate available and this is an evaluator, so
    using them is legitimate. Older seasons predate the C-suffixed columns.
    """
    for h, d, a, ov, un in [
        ("B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5"),
        ("B365H", "B365D", "B365A", "B365>2.5", "B365<2.5"),
        ("AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5"),
    ]:
        if all(c in odds.columns for c in (h, d, a)):
            has_ou = ov in odds.columns and un in odds.columns
            return h, d, a, (ov if has_ou else None), (un if has_ou else None)
    raise ValueError("no usable 1X2 odds columns found in the odds file")


def market_fixture_strength(season, odds_path=ODDS):
    """One row per (team, match_date): goal expectations and P(clean sheet).

    Returns columns [team, match_date, team_lambda, opp_lambda, p_cs], where
    p_cs = exp(-opp_lambda) -- the Poisson probability the opponent fails to
    score. Team names are mapped into vaastav's convention.
    """
    odds = pd.read_parquet(odds_path)
    odds = odds[odds["season"] == season].copy()
    if odds.empty:
        return pd.DataFrame(columns=["team", "match_date", "team_lambda",
                                     "opp_lambda", "p_cs"])

    ch, cd, ca, cov, cun = _pick_odds_columns(odds)
    odds["match_date"] = pd.to_datetime(
        odds["Date"], format="mixed", dayfirst=True).dt.date

    # Over/under column names contain '>' and '<', which itertuples silently
    # renames to positional _N. Rename to safe identifiers before iterating.
    rename = {ch: "o_h", cd: "o_d", ca: "o_a"}
    if cov is not None:
        rename[cov] = "o_over"
        rename[cun] = "o_under"
    m = odds[["HomeTeam", "AwayTeam", "match_date"] + list(rename)].rename(
        columns=rename)

    rows = []
    for r in m.itertuples(index=False):
        h, d, a = r.o_h, r.o_d, r.o_a
        if not all(pd.notna(x) and x > 0 for x in (h, d, a)):
            continue
        p_h, _p_d, p_a = _devig([1 / h, 1 / d, 1 / a])

        p_over = _p_over_25(DEFAULT_TOTAL_GOALS)
        if cov is not None:
            ov, un = r.o_over, r.o_under
            if pd.notna(ov) and pd.notna(un) and ov > 0 and un > 0:
                p_over = _devig([1 / ov, 1 / un])[0]

        lam_h, lam_a = _solve_lambdas(p_h, p_a, p_over)
        home = TEAM_MAP.get(r.HomeTeam, r.HomeTeam)
        away = TEAM_MAP.get(r.AwayTeam, r.AwayTeam)
        rows.append((home, r.match_date, lam_h, lam_a, math.exp(-lam_a)))
        rows.append((away, r.match_date, lam_a, lam_h, math.exp(-lam_h)))

    return pd.DataFrame(rows, columns=["team", "match_date", "team_lambda",
                                       "opp_lambda", "p_cs"])


# ---------------------------------------------------------------------------
# Empirical-Bayes shrinkage
# ---------------------------------------------------------------------------
def _shrink(totals, n90, prior_rate, k):
    """shrunk = w * own_rate + (1 - w) * prior, with w = n90 / (n90 + k).

    Little evidence -> lean on the position prior; a full season of minutes ->
    trust the player. `totals` and `n90` are season sums, so this is the
    hindsight-informed rate the player actually sustained.
    """
    n90 = np.asarray(n90, dtype=float)
    own = np.divide(np.asarray(totals, dtype=float), n90,
                    out=np.zeros_like(n90), where=n90 > 0)
    w = n90 / (n90 + k)
    return w * own + (1.0 - w) * prior_rate


def _expected_floor_div(mu, divisor, max_k=40):
    """E[floor(X / divisor)] for X ~ Poisson(mu), elementwise over mu.

    The scoring rule floors (saves // 3, conceded // 2), and the expectation of
    a floor is NOT the floor of an expectation. Using mu / divisor is biased --
    upward for saves, downward for goals conceded -- and on a full season that
    bias is worth hundreds of points. Taking the expectation over the count
    distribution is the unbiased estimator and costs one small matrix.
    """
    mu = np.asarray(mu, dtype=float)
    ks = np.arange(max_k + 1)
    weights = np.floor(ks / divisor)
    pmf = poisson.pmf(ks[None, :], np.clip(mu, 0, None)[:, None])
    return (pmf * weights[None, :]).sum(axis=1)


def _bonus_curve(expected_bps, realized_bonus, n_bins=40, min_per_bin=25):
    """Map EXPECTED BPS -> E[bonus], calibrated on realized bonus.

    The obvious construction -- bucket REALIZED bps, average realized bonus --
    is wrong for this surface, and badly so: it under-counts bonus by roughly
    an order of magnitude. The curve is convex through the 20-40 BPS zone where
    bonus is won, so feeding it a SMOOTHED bps (which has far less spread than
    the realized values the curve was fit on) lands everyone on the flat part
    near zero. That is Jensen's inequality, not a coding error, and it cost
    ~2,200 points of level when measured.

    Fitting the curve on the same quantity it will be evaluated at -- expected
    BPS -- removes the bias by construction: each bucket answers "players whose
    smoothed rate implies this much BPS actually averaged this much bonus."

    Quantile bins rather than fixed width, because expected BPS is dense at the
    low end and sparse at the top.
    """
    x = np.asarray(expected_bps, dtype=float)
    y = np.asarray(realized_bonus, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < min_per_bin * 2:
        return lambda q: np.zeros_like(np.asarray(q, dtype=float))

    edges = np.unique(np.quantile(x, np.linspace(0, 1, n_bins + 1)))
    idx = np.clip(np.digitize(x, edges[1:-1]), 0, len(edges) - 2)

    centres, means = [], []
    for b in np.unique(idx):
        m = idx == b
        if m.sum() >= min_per_bin:
            centres.append(x[m].mean())
            means.append(y[m].mean())

    if len(centres) < 2:
        return lambda q: np.zeros_like(np.asarray(q, dtype=float))

    centres = np.asarray(centres, dtype=float)
    means = np.clip(np.asarray(means, dtype=float), 0.0, 3.0)
    order = np.argsort(centres)
    centres, means = centres[order], means[order]
    # np.interp clamps outside the fitted range, which is what we want: flat at
    # the low end, flat at the plateau (bonus caps at 3).
    return lambda q: np.interp(np.asarray(q, dtype=float), centres, means)


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------
TERM_COLUMNS = [
    "ev_appear", "ev_goals", "ev_assists", "ev_cs", "ev_saves", "ev_conceded",
    "ev_yellow", "ev_red", "ev_og", "ev_penmiss", "ev_pensave", "ev_dc",
    "ev_bonus",
]


def build_ev_surface(season="2025-26", all_seasons_path=ALL_SEASONS,
                     odds_path=ODDS):
    """Build the EV surface for one season.

    Returns a DataFrame keyed on (element, gw, fixture) carrying `ev_points`,
    one column per scoring term (see TERM_COLUMNS), and context columns
    (name, position, team, opponent_team, was_home, minutes, total_points).

    `minutes` and `total_points` are the REALIZED values, carried through so the
    surface can be compared against reality without a second join.

    Pure apart from reading the two parquet files; writes nothing.
    """
    df = pd.read_parquet(all_seasons_path)
    d = df[(df["season"] == season) & (df["position"] != "AM")].copy()
    if d.empty:
        raise ValueError(f"no rows for season {season!r}")

    # Elements 100 and 391 carry byte-identical duplicate rows in 2025-26 (a
    # known double-recording, not a double gameweek -- doubles have distinct
    # fixture ids). Dropping them is what makes (element, gw, fixture) a key;
    # summing would double-count those players' points.
    n_before = len(d)
    d = d.drop_duplicates(subset=["element", "GW", "fixture"], keep="first")
    n_dupes = n_before - len(d)
    # Contiguous index from here on. The frame is re-indexed by every merge
    # below, so a Series captured before one and used in an index-aligned
    # expression after it would silently align to nothing and yield all-NaN.
    d = d.reset_index(drop=True)

    d = d.rename(columns={"GW": "gw"})
    d["minutes"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0).astype(int)
    d["n90"] = d["minutes"] / 90.0
    pos = d["position"]

    # -- which era are we in? both fallbacks are era-correct, not degradations --
    has_xg = ("expected_goals" in d.columns
              and d["expected_goals"].notna().any()
              and d["expected_goals"].fillna(0).abs().sum() > 0)
    has_dc_rule = ("defensive_contribution" in d.columns
                   and d["defensive_contribution"].fillna(0).abs().sum() > 0)

    goal_src = "expected_goals" if has_xg else "goals_scored"
    assist_src = "expected_assists" if has_xg else "assists"

    # -- realized per-fixture DC hit, used only to build the player's rate --
    if has_dc_rule:
        thr = pos.map(DC_THRESHOLD)
        d["dc_hit"] = np.where(
            pos.isin(["DEF", "MID", "FWD"])
            & (d["defensive_contribution"].fillna(0) >= thr), 1.0, 0.0)
    else:
        d["dc_hit"] = 0.0

    # -- season aggregates per player (this is the hindsight) --
    agg_src = {
        "goals": goal_src, "assists": assist_src, "saves": "saves",
        "conceded": "goals_conceded", "yellow": "yellow_cards",
        "red": "red_cards", "og": "own_goals", "penmiss": "penalties_missed",
        "pensave": "penalties_saved", "dc": "dc_hit", "bps": "bps",
    }
    per_player = d.groupby("element").agg(
        n90_season=("n90", "sum"),
        position=("position", "first"),
        **{f"tot_{k}": (v, "sum") for k, v in agg_src.items()},
    ).reset_index()

    # -- position priors: minutes-weighted league rate per 90, per position --
    priors = {}
    for stat in agg_src:
        by_pos = per_player.groupby("position").apply(
            lambda g, s=stat: (g[f"tot_{s}"].sum() / g["n90_season"].sum()
                               if g["n90_season"].sum() > 0 else 0.0),
            include_groups=False)
        priors[stat] = by_pos.to_dict()

    # -- shrink every rate toward its position prior --
    for stat in agg_src:
        prior_vec = per_player["position"].map(priors[stat]).fillna(0.0).to_numpy()
        per_player[f"rate_{stat}"] = _shrink(
            per_player[f"tot_{stat}"], per_player["n90_season"],
            prior_vec, SHRINK_K[stat])

    d = d.merge(per_player[["element"] + [f"rate_{s}" for s in agg_src]],
                on="element", how="left")

    # -- fixture strength and clean-sheet probability from the market --
    strength = market_fixture_strength(season, odds_path=odds_path)
    d["match_date"] = pd.to_datetime(d["kickoff_time"]).dt.date
    if not strength.empty:
        strength = strength.drop_duplicates(["team", "match_date"])
        d = d.merge(strength, on=["team", "match_date"], how="left")
    else:
        d["team_lambda"] = np.nan
        d["opp_lambda"] = np.nan
        d["p_cs"] = np.nan

    odds_coverage = float(d["team_lambda"].notna().mean())
    league_lambda = float(d["team_lambda"].mean(skipna=True)) if odds_coverage else 1.40
    league_p_cs = float(d["p_cs"].mean(skipna=True)) if odds_coverage else 0.25

    d["fixture_scale"] = (d["team_lambda"] / league_lambda).fillna(1.0).clip(
        *FIXTURE_SCALE_CLIP)
    d["p_cs"] = d["p_cs"].fillna(league_p_cs)

    # -- the terms --
    # Re-bind `pos` from the merged frame: the one captured above belongs to the
    # pre-merge index and would misalign in any index-aligned expression.
    d = d.reset_index(drop=True)
    pos = d["position"]
    mins = d["minutes"].to_numpy()
    n90 = d["n90"].to_numpy()
    scale = d["fixture_scale"].to_numpy()

    # Appearance: realized minutes, NOT smoothed. See module docstring.
    d["ev_appear"] = np.where(mins >= 60, 2.0, np.where(mins > 0, 1.0, 0.0))

    # Goals and assists get a LEVEL-ONLY calibration factor. xG and xA measure a
    # different quantity from the scoring event: FPL awards assists for
    # deflections, rebounds and won penalties that xA never models (realized
    # assists run ~30% above xA), and season xG sits slightly above goals. Left
    # uncorrected the surface would systematically undervalue creative players,
    # which is a bias in the yardstick itself. The factor is a single scalar per
    # term, so it moves the level and cannot touch the cross-sectional ranking --
    # which is the part carrying the signal.
    raw_goals = (d["rate_goals"].to_numpy() * n90 * scale
                 * pos.map(GOAL_PTS).to_numpy())
    raw_assists = d["rate_assists"].to_numpy() * n90 * scale * 3.0
    real_goal_pts = float((d["goals_scored"] * pos.map(GOAL_PTS)).sum())
    real_assist_pts = float((d["assists"] * 3).sum())
    cal_goals = real_goal_pts / raw_goals.sum() if raw_goals.sum() > 0 else 1.0
    cal_assists = (real_assist_pts / raw_assists.sum()
                   if raw_assists.sum() > 0 else 1.0)
    d["ev_goals"] = raw_goals * cal_goals
    d["ev_assists"] = raw_assists * cal_assists

    # Clean sheet: market-implied, hard-gated on the realized 60-minute threshold.
    d["ev_cs"] = (d["p_cs"].to_numpy() * pos.map(CS_PTS).to_numpy()
                  * (mins >= 60).astype(float))

    # Saves and conceded: expectation OF the floor, not floor of the expectation.
    d["ev_saves"] = _expected_floor_div(
        d["rate_saves"].to_numpy() * n90, SAVES_PER_POINT)
    d["ev_conceded"] = np.where(
        pos.isin(["GK", "DEF"]).to_numpy(),
        -_expected_floor_div(d["rate_conceded"].to_numpy() * n90,
                             CONCEDED_PER_PENALTY), 0.0)

    d["ev_yellow"] = YELLOW_PTS * d["rate_yellow"].to_numpy() * n90
    d["ev_red"] = RED_PTS * d["rate_red"].to_numpy() * n90
    d["ev_og"] = OG_PTS * d["rate_og"].to_numpy() * n90
    d["ev_penmiss"] = PEN_MISS_PTS * d["rate_penmiss"].to_numpy() * n90
    d["ev_pensave"] = PEN_SAVE_PTS * d["rate_pensave"].to_numpy() * n90

    d["ev_dc"] = np.where(pos.isin(["DEF", "MID", "FWD"]).to_numpy(),
                          DC_PTS * d["rate_dc"].to_numpy() * n90, 0.0)

    exp_bps = d["rate_bps"].to_numpy() * n90
    played = mins > 0
    curve = _bonus_curve(exp_bps[played], d.loc[played, "bonus"].to_numpy())
    d["ev_bonus"] = curve(exp_bps)
    # A player who did not appear cannot place in the top three for bonus.
    d.loc[d["minutes"] == 0, "ev_bonus"] = 0.0

    d["ev_points"] = d[TERM_COLUMNS].sum(axis=1)

    keep = (["element", "gw", "fixture", "name", "position", "team",
             "opponent_team", "was_home", "minutes", "total_points",
             "fixture_scale", "p_cs"] + TERM_COLUMNS + ["ev_points"])
    out = (d[keep].sort_values(["element", "gw", "fixture"])
           .reset_index(drop=True))

    out.attrs["season"] = season
    out.attrs["goal_source"] = goal_src
    out.attrs["assist_source"] = assist_src
    out.attrs["dc_rule_active"] = has_dc_rule
    out.attrs["odds_coverage"] = odds_coverage
    out.attrs["league_lambda"] = league_lambda
    out.attrs["duplicate_rows_dropped"] = n_dupes
    out.attrs["cal_goals"] = cal_goals
    out.attrs["cal_assists"] = cal_assists
    return out


if __name__ == "__main__":
    surface = build_ev_surface("2025-26")

    print(f"season               {surface.attrs['season']}")
    print(f"rows                 {len(surface):,}")
    print(f"unique keys          "
          f"{surface.duplicated(['element', 'gw', 'fixture']).sum()} duplicates")
    print(f"goal/assist source   {surface.attrs['goal_source']} / "
          f"{surface.attrs['assist_source']}")
    print(f"DC rule active       {surface.attrs['dc_rule_active']}")
    print(f"odds coverage        {surface.attrs['odds_coverage']:.4f}")
    print(f"league mean lambda   {surface.attrs['league_lambda']:.3f}")
    print(f"duplicate rows dropped {surface.attrs['duplicate_rows_dropped']}")
    print(f"level calibration    goals x{surface.attrs['cal_goals']:.4f}  "
          f"assists x{surface.attrs['cal_assists']:.4f}")
    print()

    ev, actual = surface["ev_points"], surface["total_points"]
    print(f"mean ev_points       {ev.mean():.4f}")
    print(f"mean total_points    {actual.mean():.4f}")
    print(f"sum  ev_points       {ev.sum():,.0f}")
    print(f"sum  total_points    {actual.sum():,.0f}")
    print(f"pearson  ev vs real  {ev.corr(actual):.4f}")
    print(f"spearman ev vs real  {ev.corr(actual, method='spearman'):.4f}")
    print()

    print("mean of each term:")
    for c in TERM_COLUMNS:
        print(f"  {c:<14} {surface[c].mean():+.4f}")
    print(f"  {'ev_points':<14} {ev.mean():+.4f}")
    print()

    played = surface[surface["minutes"] > 0]
    starters = surface[surface["minutes"] >= 60]
    print(f"played (>0 min)   n={len(played):,}  "
          f"mean ev {played['ev_points'].mean():.3f}  "
          f"mean actual {played['total_points'].mean():.3f}  "
          f"corr {played['ev_points'].corr(played['total_points']):.4f}")
    print(f"started (60+ min) n={len(starters):,}  "
          f"mean ev {starters['ev_points'].mean():.3f}  "
          f"mean actual {starters['total_points'].mean():.3f}  "
          f"corr {starters['ev_points'].corr(starters['total_points']):.4f}")
    print(f"zero minutes      n={(surface['minutes'] == 0).sum():,}  "
          f"mean ev {surface.loc[surface['minutes'] == 0, 'ev_points'].mean():.4f}")
