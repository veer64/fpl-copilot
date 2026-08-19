# assembly.py
# E[points] assembly orchestrator. Imports the five component modules, joins their
# outputs through the crosswalk, applies the master equation (with playing-probability
# gating), and validates against actuals. See ASSEMBLY_LOG.md for the full story.
#
# Run: `python assembly.py` (retrains all components — a few minutes).
#
# CHANGE (2026-08): bonus.get_bonus_model() now returns a 4th value, bonus_mean —
# the recalibration constant, computed from cutoff-respecting data inside the bonus
# module. Previously assembly computed it from the FULL 2025-26 season, which is a
# leak in any walk-forward context. See LEAKAGE.md.

import pandas as pd
import numpy as np
from scipy.stats import spearmanr, poisson

from minutes import get_minutes
from attacking_rates import get_rates, assert_crosswalk_unique
from dixon_coles import get_fixtures
from defensive import get_dc_2526
from bonus import get_bonus_model

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
GOAL_PTS = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}
CS_PTS   = {"FWD": 0, "MID": 1, "DEF": 4, "GK": 4}
LEAGUE_AVG_LAMBDA = 1.40
# Odds-source name -> vaastav name. Audited 2026-08-17 across all ten seasons
# on disk: these three are the ONLY names that differ between the sources.
# "Sheffield United" was missing until then -- every Sheffield fixture join
# failed silently in their PL seasons (2019-20, 2020-21, 2023-24) and the
# players' e_points collapsed to 0.0 all season. See KNOWN_ISSUES #14.
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs",
            "Sheffield United": "Sheffield Utd"}
DC_BASE = {"DEF": 0.125, "MID": 0.136, "FWD": 0.058, "GK": 0.0}

# D1 scoring terms (saves, goals conceded, cards, penalty share). This flag both
# GATES the terms in _finish_equation and is STAMPED into every walk-forward file
# as `d1_terms_active`, so an artefact can never carry the terms silently. It
# exists because D1 landed here on 2026-08-14 BEFORE the margin-calibration
# measurements ran; every file rebuilt afterwards inherited the terms with
# nothing to reveal it, and "baseline" figures were measured on D1 files.
# See KNOWN_ISSUES.md #13 (same class as the availability footgun, #10).
D1_TERMS_ACTIVE = True

# Clean sheets and goals conceded from ONE expected-goals-against distribution
# (pts_cs = exp(-opp_lambda) instead of the 0.2-DC-blended p_cs). TESTED AND
# REVERTED 2026-08-17 -- a clean negative (GK investigation step 3,
# Logs/gk_investigation_log.md): GK margin beta moved FURTHER from baseline in
# all three seasons (-0.024/-0.005/-0.013) and CS Brier worsened +0.0011 to
# +0.0016. Mechanism: H1's diagnostic RESIDUALISED the conceded term against
# p_cs (removing shared information) and beta recovered; unification does the
# opposite -- it makes the two terms perfectly redundant instead of 94%
# redundant. Unification is the wrong operation for a double-count. The 0.2 CS
# blend is retained on the strength of this test, not its original 0.0005
# Brier margin. Gated and stamped as `cs_unified` (the #13 lesson); leave
# False unless the step-3 negative is re-litigated with new evidence.
CS_UNIFIED = False

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"

# --- per-fixture grain -------------------------------------------------------
# The master equation is evaluated once per PLAYER-FIXTURE and then summed to one
# row per player-gameweek. Everything downstream still sees (element, gw); the
# per-fixture grain is internal.
#
# Why this rather than multiplying a per-gameweek answer by a fixture count: the
# two fixtures of a double have DIFFERENT opponents, different goal expectations
# and different clean-sheet probabilities. Arsenal in GW26 played Brentford away
# and Wolves at home. A count multiplier would price both at whichever fixture
# happened to survive a drop_duplicates.
#
# Three independent defects are closed by the change of grain, all of which
# under-counted double gameweeks:
#   1. minutes_frac = (e_minutes/90).clip(0,1) capped the whole gameweek at one
#      fixture, so every term scaled by it was structurally limited to a single
#      match no matter what the minutes model returned.
#   2. The Dixon-Coles join used drop_duplicates(["team","gw"]), silently keeping
#      whichever fixture sorted first and discarding the second -- not the harder
#      one, not the easier one, an arbitrary one.
#   3. The defensive-contribution join took the MAX of the two per-match
#      probabilities via sort_values(...).drop_duplicates(["element","gw"]).
# Appearance points fall out for free: two fixtures now yield up to 4, not 2.
FIXTURE_KEY = ["element", "gw", "fixture"]

# Additive quantities: summed across a player's fixtures.
SUM_COLS = ["minutes", "actual_points", "e_minutes", "minutes_frac",
            "e_goals", "e_assists", "pts_goals", "pts_assists", "pts_appear",
            "pts_cs", "pts_dc", "pts_saves", "pts_conceded", "pts_cards",
            "e_points_core", "exp_bonus", "e_points"]

# Per-fixture RATES and probabilities: averaged, never summed. A probability that
# summed past 1 would be meaningless. For the 97% of rows with one fixture the mean
# is that single value, so single-gameweek output is unchanged by construction.
MEAN_COLS = ["p_start", "p60", "p_60plus", "p_play_any", "npxg90", "xa90",
             "team_lambda", "opp_lambda", "p_cs", "fixture_scale", "p_dc_hit",
             "pred_bps", "saves_per_90", "yellow_per_90", "red_per_90",
             "penalty_share", "team_pen_rate"]

METRIC_GLOSSARY = """# Assembly — what these metrics mean

This is the PARENT run. The five component runs nested beneath it are the pieces;
this run scores what they produce once combined through the master equation.

Each component has its own glossary on its own run page. This one covers only the
final combined prediction: expected FPL points per player per gameweek.

**spearman** — rank correlation between predicted and actual points. 1.0 means the
ordering is perfect, 0.0 means no signal. Higher is better.
THIS IS THE HEADLINE METRIC, because the optimizer only needs the right ORDER of
players, not the exact point totals. Getting the ranking right is the whole job.

**pearson** — straight-line correlation between predicted and actual. Reported as
secondary. It is more sensitive to a few huge hauls than spearman is.

**mae** — typical error in predicted points, in actual FPL points. Lower is better.
Treat this as secondary too: a model that predicts 2.1 for everyone can win on MAE
while being useless for picking a squad.

**mae_fair_baseline** — the bar to beat. For each player it predicts their own
running average of past gameweeks. If `mae` is not below this, the model is adding
nothing over "just use their average so far."

**mean_predicted / mean_actual** — average predicted vs average real points.
Not quality scores. A calibration check: if predicted sits well above actual, the
model is systematically over-predicting, even if the ranking is fine.

**n_predictions** — player-gameweek rows produced. A tripwire: a full season is
about 29,338. A sharp drop means a join broke somewhere upstream.

**cal_pred_70plus / cal_actual_70plus** (and the other bands) — average predicted
vs average actual points, split by expected minutes. This is where over-prediction
hides. The 70+ band is the one that matters most: those are the players the
optimizer will actually pick. A gap there is a real, known issue.
"""


def _expected_floor_div(mu, divisor, max_k=40):
    """E[floor(X / divisor)] for X ~ Poisson(mu).
    Used for saves (//3) and goals conceded (//2) where we need the expectation
    of a floor operation, not the floor of an expectation."""
    mu = np.asarray(mu, dtype=float)
    ks = np.arange(max_k + 1)
    weights = np.floor(ks / divisor)
    pmf = poisson.pmf(ks[None, :], np.clip(mu, 0, None)[:, None])
    return (pmf * weights[None, :]).sum(axis=1)


def _calibration_table(a):
    """Predicted vs actual points, bucketed by expected minutes. The band table is
    where systematic over- or under-prediction shows up."""
    v = a.dropna(subset=["actual_points", "e_points"]).copy()
    v["band"] = pd.cut(v["e_minutes"], [0, 15, 45, 70, 90], labels=["<15", "15-45", "45-70", "70+"])
    t = (v.groupby("band", observed=True)
         .agg(pred=("e_points", "mean"), actual=("actual_points", "mean"), n=("e_points", "size"))
         .reset_index())
    return t.round(3)


def _eval_metrics(a):
    """Score the final combined prediction. See METRIC_GLOSSARY."""
    a = a.copy()
    a["actual_points"] = pd.to_numeric(a["actual_points"], errors="coerce")
    val = a.dropna(subset=["actual_points", "e_points"]).copy()

    m = {
        "spearman": float(spearmanr(val["e_points"], val["actual_points"]).correlation),
        "pearson": float(val["e_points"].corr(val["actual_points"])),
        "mae": float((val["e_points"] - val["actual_points"]).abs().mean()),
        "mean_predicted": float(val["e_points"].mean()),
        "mean_actual": float(val["actual_points"].mean()),
        "n_predictions": float(len(val)),
    }

    # The bar to beat: each player's own running average of past gameweeks.
    vs = val.sort_values(["element", "gw"])
    vs["fair"] = vs.groupby("element")["actual_points"].transform(lambda s: s.shift(1).expanding().mean())
    f = vs.dropna(subset=["fair"])
    if len(f):
        m["mae_fair_baseline"] = float((f["fair"] - f["actual_points"]).abs().mean())
        m["mae_on_baseline_rows"] = float((f["e_points"] - f["actual_points"]).abs().mean())

    # Calibration by minutes band, flattened so each band is its own metric.
    for _, r in _calibration_table(a).iterrows():
        tag = str(r["band"]).replace("-", "_").replace("<", "under").replace("+", "plus")
        m[f"cal_pred_{tag}"] = float(r["pred"])
        m[f"cal_actual_{tag}"] = float(r["actual"])

    return m


def build_fixture_predictions(log_mlflow=False, availability=None):
    """The master equation at PLAYER-FIXTURE grain. Use build_predictions() unless
    you specifically need the per-fixture rows.

    `availability` is passed straight through to the minutes model. It exists so
    the provenance of a generated file can be pinned explicitly rather than
    inherited from whatever minutes.py happens to default to -- the exact trap
    recorded as KNOWN_ISSUES #10, where regenerating an artefact silently moved the
    reference from 1984 to 1938. None keeps minutes.py's own default."""
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    cw = pd.read_csv(BASE + r"\data\history\player_id_crosswalk_final.csv")

    # --- run the five components (each logs a NESTED child run if enabled) ---
    print("Running components...")
    # per_fixture=True: ask the minutes model about ONE ordinary fixture, so the
    # answer can be applied to each of a doubled player's fixtures without
    # double-counting the capped-sum training artefact. See minutes.get_minutes.
    mins_out = get_minutes(up_to_gw=None, log_mlflow=log_mlflow, per_fixture=True,
                           availability=availability)
    rates, priors = get_rates("2025-26", log_mlflow=log_mlflow)
    fixtures = get_fixtures(cutoff_date=None, log_mlflow=log_mlflow)
    dc_out = get_dc_2526(log_mlflow=log_mlflow)
    bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = get_bonus_model(log_mlflow=log_mlflow)

    return assemble_fixtures(df, cw, mins_out, rates, priors, fixtures, dc_out,
                             bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean)


def assemble_fixtures(df, cw, mins_out, rates, priors, fixtures, dc_out,
                      bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean, gws=None,
                      season="2025-26", dc_enabled=True):
    """The master equation at PLAYER-FIXTURE grain, with components SUPPLIED.

    THIS IS THE SINGLE SOURCE OF TRUTH FOR THE EQUATION. It previously existed
    twice -- here and again in eval/walkforward.py, which carried its own copy so
    the harness could feed per-cutoff components. The two drifted, and all three
    double-gameweek defects survived a fix in one place because the other copy
    still had them. Nothing may reimplement this; callers that need to supply
    their own components call this function instead.

    `gws` restricts the skeleton to a subset of gameweeks, which is what the
    walk-forward harness needs when it assembles a horizon window at one cutoff.

    `season` and `dc_enabled` exist for the multi-season port (M2). Defensive
    contribution is a 2025-26 SCORING RULE -- it did not exist before, and neither
    did the stat behind it. Passing dc_enabled=False zeroes the term rather than
    falling back to a position base rate, because a base rate would award points
    under a rule that was not in force. Verified against 2023-24: reconstructing
    total_points WITHOUT the DC term reconciles on 29,725 of 29,725 rows.
    """
    # KNOWN_ISSUES #3 guard: the crosswalk is about to be joined against
    # understat-keyed rates; a duplicate id claim would silently give two
    # players the same rate row. Cheap (841 rows), runs on every assembly.
    assert_crosswalk_unique(cw)

    v = df[(df["season"] == season) & (df["position"] != "AM")].copy()
    skel = v[["element", "GW", "fixture", "name", "position", "team", "opponent_team",
              "was_home", "kickoff_time", "minutes", "total_points"]].copy()
    skel["element"] = pd.to_numeric(skel["element"], errors="coerce").astype(int)
    skel = skel.rename(columns={"GW": "gw", "total_points": "actual_points"})
    if gws is not None:
        skel = skel[skel["gw"].isin(gws)]

    # Elements 100 and 391 carry byte-identical rows repeating the SAME fixture id.
    # That is a recording defect, not a double gameweek -- doubles have two
    # DISTINCT fixture ids. Deduplicated, never summed: summing would double those
    # players' minutes and points out of thin air.
    n_before = len(skel)
    skel = skel.drop_duplicates(FIXTURE_KEY, keep="first")
    n_exact_dupes = n_before - len(skel)

    cwx = cw.copy()
    if "player_id" not in cwx.columns:
        # Core-Insights ids exist for 2025-26 only. They are used solely for the
        # defensive join, which is off in every earlier season, so element stands
        # in and the join degrades to a no-op rather than failing.
        cwx["player_id"] = cwx["element"]
    skel = skel.merge(cwx[["element", "player_id", "understat_id"]], on="element", how="left")
    skel["match_date"] = pd.to_datetime(skel["kickoff_time"]).dt.date
    # Order a player's fixtures within the gameweek by kickoff, so the per-match
    # defensive-contribution rows can be lined up against them below.
    skel["fix_rank"] = (skel.sort_values("kickoff_time")
                        .groupby(["element", "gw"]).cumcount())
    asm = skel.sort_values(FIXTURE_KEY).reset_index(drop=True)

    # --- 2. minutes (per-fixture semantics; same value for each of a player's fixtures) ---
    asm = asm.merge(mins_out[["element", "gw", "p_start", "p60", "e_minutes"]], on=["element", "gw"], how="left")

    # --- 3. attacking rates (dedupe + fallback) ---
    rates_clean = rates.sort_values("npxg90", ascending=False).drop_duplicates("understat_id", keep="first")
    asm["understat_id_num"] = pd.to_numeric(asm["understat_id"], errors="coerce")
    rates_clean["understat_id"] = pd.to_numeric(rates_clean["understat_id"], errors="coerce")
    asm = asm.merge(rates_clean, left_on="understat_id_num", right_on="understat_id", how="left", suffixes=("", "_r"))
    pos_lab = {"FWD": "F", "MID": "M", "DEF": "D", "GK": "D"}
    def fb(row, stat):
        return priors.get(pos_lab.get(row["position"], "M"), priors["M"])[stat]
    nn = asm["npxg90"].isna(); nx = asm["xa90"].isna()
    asm.loc[nn, "npxg90"] = asm[nn].apply(lambda r: fb(r, "npxg"), axis=1)
    asm.loc[nx, "xa90"]   = asm[nx].apply(lambda r: fb(r, "xa"), axis=1)
    assert asm.duplicated(FIXTURE_KEY).sum() == 0

    # --- 4. Dixon-Coles fixtures (team-name map + date bridge) ---
    fixtures["home"] = fixtures["home"].map(lambda t: TEAM_MAP.get(t, t))
    fixtures["away"] = fixtures["away"].map(lambda t: TEAM_MAP.get(t, t))
    home = fixtures[["home", "match_date", "lam_home", "lam_away", "p_home_cs"]].copy()
    home.columns = ["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]
    away = fixtures[["away", "match_date", "lam_away", "lam_home", "p_away_cs"]].copy()
    away.columns = ["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]
    tf = pd.concat([home, away], ignore_index=True)
    tf["match_date"] = pd.to_datetime(tf["match_date"]).dt.date

    # Joined on (team, MATCH DATE), not (team, gameweek). A team cannot play twice
    # on one day, so the date identifies the fixture uniquely -- which is what lets
    # each half of a double carry its own opponent, lambda and clean-sheet
    # probability instead of one of them being dropped.
    asm = asm.merge(tf[["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]]
                    .drop_duplicates(["team", "match_date"]),
                    on=["team", "match_date"], how="left")
    assert asm.duplicated(FIXTURE_KEY).sum() == 0

    # A fixture join that matches nothing is SILENT without this. team_lambda and
    # p_cs go NaN, which makes pts_cs and therefore e_points NaN -- and the
    # groupby-sum in collapse_to_gameweek turns a column of NaN into a clean 0.0.
    # The result is a file full of zero predictions that looks structurally fine.
    # This is exactly how a `predict_season` argument that was declared but never
    # used inside dixon_coles.get_fixtures went unnoticed: it returned 2025-26
    # fixtures for a 2023-24 request and the season silently scored zero.
    matched_frac = asm["team_lambda"].notna().mean()
    if matched_frac < 0.90:
        raise AssertionError(
            f"fixture join matched only {matched_frac:.1%} of player-fixtures for "
            f"season {season!r}. The Dixon-Coles fixtures are probably for a "
            "different season, or the team-name map is stale. Refusing to build "
            "predictions that would silently collapse to zero.")

    # PER-TEAM guard. The global 90% check cannot see a single-team failure:
    # one team of twenty is ~5% of rows, so Sheffield Utd's entire 2023-24
    # season sailed under it with every fixture unmatched (KNOWN_ISSUES #14).
    # Threshold 0.5, teams with >= 3 fixture rows: a stale name mapping fails
    # ~100% of a team's joins, so 50% separates that failure class cleanly
    # from the occasional genuinely unpriced fixture without tripping on it.
    team_match = asm.groupby("team")["team_lambda"].agg(["size", "count"])
    bad = team_match[(team_match["size"] >= 3)
                     & (team_match["count"] / team_match["size"] < 0.5)]
    if len(bad):
        raise AssertionError(
            "fixture join failed for specific team(s) in season "
            f"{season!r}: "
            + ", ".join(f"{t} ({r['count']}/{r['size']} matched)"
                        for t, r in bad.iterrows())
            + ". Almost certainly a team-name mismatch between the odds source "
            "and vaastav -- check TEAM_MAP. Refusing to build: these players' "
            "predictions would silently collapse to 0.0 for every affected "
            "gameweek (KNOWN_ISSUES #14).")

    # Residual unmatched fixtures (isolated, guard-passing) get NEUTRAL market
    # values instead of NaN. Without this, NaN p_cs makes pts_cs and therefore
    # e_points_core NaN per fixture, and the per-gameweek collapse SUMS an
    # all-NaN column into a clean 0.0 -- a starter predicted 0.0 that looks
    # structurally valid. Neutral here means a league-average fixture: lambda
    # 1.40 both ways (fixture_scale then ~1.0) and the Poisson-consistent
    # clean-sheet probability exp(-1.40) ~= 0.25. The player keeps his
    # minutes/rates-based prediction under a neutral fixture assumption.
    asm["team_lambda"] = asm["team_lambda"].fillna(LEAGUE_AVG_LAMBDA)
    asm["opp_lambda"] = asm["opp_lambda"].fillna(LEAGUE_AVG_LAMBDA)
    asm["p_cs"] = asm["p_cs"].fillna(float(np.exp(-LEAGUE_AVG_LAMBDA)))

    # --- 5. defensive contribution (per fixture + fallback) ---
    # dc_out is already per-MATCH: a doubled player has two rows for the gameweek.
    # They are lined up against his fixtures by order rather than by match id.
    #
    # That ordering is arbitrary but provably harmless: expected DC points are
    # p_dc_hit * 2 * minutes_frac, and minutes_frac is identical across a player's
    # fixtures (the minutes model returns one value per player-gameweek), so the
    # SUM over fixtures is invariant to which probability lands on which fixture.
    # Threading match_id through defensive.py would need a Core-Insights-slug to
    # vaastav team-name map -- a new fuzzy-matching surface, for no change in the
    # answer. A player with only one DC row keeps the position base rate on his
    # other fixture, exactly as an unmatched single-gameweek row does today.
    if not dc_enabled:
        # No DC rule this season. The D1 features below are still built: this
        # path previously returned early with them zeroed, which silently made
        # prior-season walk-forward files "D1 conceded-only" -- a third state
        # that no stamp distinguished. See Logs/d1_log.md.
        asm["p_dc_hit"] = 0.0
        asm = asm.sort_values(FIXTURE_KEY).reset_index(drop=True)
    else:
        dc = dc_out[["player_id", "gw", "p_dc_hit"]].copy()
        dc["fix_rank"] = dc.groupby(["player_id", "gw"]).cumcount()
        own = dc.groupby(["player_id", "gw"])["p_dc_hit"].mean().rename("p_dc_own")
        asm = asm.merge(dc, on=["player_id", "gw", "fix_rank"], how="left")
        asm = asm.merge(own, on=["player_id", "gw"], how="left")
        # A fixture with no DC row of its own inherits the PLAYER'S OWN estimate for
        # that gameweek before falling back to the position base rate. This matters
        # under the walk-forward harness: at cutoff k the defensive component supplies
        # one row per player, so the second half of a future double would otherwise
        # collapse to a position average despite the player's own propensity being
        # known. No effect on single-fixture rows, which always match their own row.
        asm["p_dc_hit"] = asm["p_dc_hit"].fillna(asm["p_dc_own"])
        asm = asm.drop(columns=["p_dc_own"])
        need = asm["p_dc_hit"].isna()
        asm.loc[need, "p_dc_hit"] = asm.loc[need, "position"].map(DC_BASE).fillna(0.10)
        asm = asm.sort_values(FIXTURE_KEY).reset_index(drop=True)
        assert asm.duplicated(FIXTURE_KEY).sum() == 0

    # --- D1: missing scoring terms (saves, cards, conceded, penalty share) ---
    # Variant B (adopted 2026-08-17; see Logs/d1_log.md). Saves keep the
    # per-player rolling rate. CARDS ARE A POSITION PRIOR ONLY: the per-player
    # rolling card rate was measured to cause most of the GK margin-beta
    # collapse (0.847 -> 0.425 at step 0). Cards are rare, so a 5-gw rolling
    # rate is a spike detector -- its per-row variance (SD 0.72 pts on GK
    # starters) swamped its mean (-0.13) and was anti-correlated with realised
    # points. The position rate keeps the mean deduction at per-row SD ~0.02.
    v_full = df[(df["season"] == season) & (df["position"] != "AM")].copy()
    v_full = v_full.rename(columns={"GW": "gw"})
    v_full["saves_per_90"] = (v_full["saves"] / (v_full["minutes"] + 1)) * 90.0

    # Saves: rolling average (last 5 gameweeks, with fallback to position prior)
    # Grouped by season and element to avoid leakage across seasons
    v_full["saves_per_90_roll"] = (v_full.sort_values(["element", "gw"])
                                   .groupby(["season", "element"])["saves_per_90"]
                                   .transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean()))
    v_full["saves_per_90_roll"] = v_full["saves_per_90_roll"].fillna(0)
    saves_prior = v_full.groupby("position")["saves_per_90"].mean()
    saves_prior_shrunk = saves_prior * 0.3  # shrink 70% toward zero, rare events
    v_full["saves_per_90"] = v_full.apply(
        lambda r: r["saves_per_90_roll"] if r["saves_per_90_roll"] > 0
                  else saves_prior_shrunk.get(r["position"], 0), axis=1)

    # Cards: position-level base rate from PRIOR SEASONS ONLY -- never derived
    # from the season being predicted. Realised cards per 90 by position, no
    # per-player component at all. GKP is an alternate label for GK in
    # all_seasons_fixed (101 rows, 2021-22) and is folded in before the rate is
    # computed so those rows are not silently excluded.
    hist = df[(df["season"] < season) & (df["position"] != "AM")].copy()
    hist["position"] = hist["position"].replace({"GKP": "GK"})
    hist = hist[hist["minutes"] > 0]
    card_mins = hist.groupby("position")["minutes"].sum()
    card_y90 = 90.0 * hist.groupby("position")["yellow_cards"].sum() / card_mins
    card_r90 = 90.0 * hist.groupby("position")["red_cards"].sum() / card_mins
    pos_norm = v_full["position"].replace({"GKP": "GK"})
    v_full["yellow_per_90"] = pos_norm.map(card_y90).fillna(0.0)
    v_full["red_per_90"] = pos_norm.map(card_r90).fillna(0.0)

    # Penalty share: from Understat historical (goals - npg) / games
    # Computed per player per season, with fallback to position/league average
    us = pd.read_parquet(BASE + r"\data\history\understat_season_aggregates.parquet")
    us["games_numeric"] = pd.to_numeric(us["games"], errors="coerce")
    us["goals_numeric"] = pd.to_numeric(us["goals"], errors="coerce")
    us["npg_numeric"] = pd.to_numeric(us["npg"], errors="coerce")
    us["pen_goals"] = (us["goals_numeric"] - us["npg_numeric"]).clip(lower=0)
    us["penalty_share"] = (us["pen_goals"] / (us["games_numeric"] + 1)).fillna(0)
    us["understat_id_num"] = pd.to_numeric(us["id"], errors="coerce")

    # For each season in v_full, map to the prior-season Understat penalty share
    # E.g., 2025-26 players look up their 2024-25 Understat record
    us_map = us[["understat_id_num", "understat_season", "penalty_share"]].copy()
    us_map["understat_season"] = pd.to_numeric(us_map["understat_season"], errors="coerce").astype(int)

    # Add understat_id from crosswalk to v_full
    v_full = v_full.merge(cw[["element", "understat_id"]], on="element", how="left")
    v_full["understat_id_num"] = pd.to_numeric(v_full["understat_id"], errors="coerce")
    v_full["season_year"] = pd.to_numeric(v_full["season"].str[:4], errors="coerce").astype(int)

    # Join penalty share from prior season (e.g., 2024-25 data for 2025-26 prediction)
    v_full = v_full.merge(us_map,
                          left_on=["understat_id_num", "season_year"],
                          right_on=["understat_id_num", "understat_season"],
                          how="left", suffixes=("", "_us"))
    # For missing matches, use position-based fallback
    pen_share_prior = us.groupby("position")["penalty_share"].mean()
    v_full["penalty_share"] = v_full["penalty_share"].fillna(
        v_full["position"].map(pen_share_prior).fillna(0.05))  # conservative default

    # Team penalty rate: expected pens per match for each team-season
    # Compute from the full season data: realized penalties / (38 matches or actual gameweek count)
    team_pen_rate = (v_full.groupby(["season", "team"])
                     .agg(total_pens=("penalties_missed", "sum"),
                          gw_count=("gw", "nunique"))
                     .reset_index())
    team_pen_rate["team_pen_rate"] = team_pen_rate["total_pens"] / team_pen_rate["gw_count"].clip(lower=1)
    team_pen_rate = team_pen_rate[["season", "team", "team_pen_rate"]]

    v_full = v_full.merge(team_pen_rate, on=["season", "team"], how="left")
    v_full["team_pen_rate"] = v_full["team_pen_rate"].fillna(0.08)  # league average

    # Keep only the needed columns for merge
    d1_features = v_full[["element", "gw", "fixture", "saves_per_90", "yellow_per_90",
                          "red_per_90", "penalty_share", "team_pen_rate"]].copy()

    asm = asm.merge(d1_features, on=["element", "gw", "fixture"], how="left")
    asm["saves_per_90"] = asm["saves_per_90"].fillna(0)
    # Card columns are position constants: a row that misses the merge still
    # gets its position rate rather than silently dropping the deduction.
    asm["yellow_per_90"] = asm["yellow_per_90"].fillna(
        asm["position"].map(card_y90)).fillna(0)
    asm["red_per_90"] = asm["red_per_90"].fillna(
        asm["position"].map(card_r90)).fillna(0)
    asm["penalty_share"] = asm["penalty_share"].fillna(0.05)
    asm["team_pen_rate"] = asm["team_pen_rate"].fillna(0.08)

    return _finish_equation(asm, bps_model, bps_to_bonus, BPS_FEATURES,
                            bonus_mean, n_exact_dupes)


def _finish_equation(asm, bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean,
                     n_exact_dupes=0):
    # --- 6. master equation, EVALUATED PER FIXTURE ---
    # (every performance term still GATED by playing probability)
    #
    # The formulas are byte-for-byte the ones that reconciled against realized
    # total_points on 29,757 of 29,757 rows. Only the grain they are evaluated at
    # has changed. The clip(0,1) on minutes_frac is now correct rather than
    # damaging: it bounds ONE fixture at 90 minutes, which is the real limit,
    # instead of bounding an entire double gameweek at 90.
    a = asm.copy()
    a["minutes_frac"] = (a["e_minutes"] / 90.0).clip(0, 1)
    a["fixture_scale"] = (a["team_lambda"] / LEAGUE_AVG_LAMBDA).fillna(1.0).clip(0.5, 2.0)
    a["e_goals"]   = a["npxg90"] * a["minutes_frac"] * a["fixture_scale"]
    a["e_assists"] = a["xa90"]   * a["minutes_frac"] * a["fixture_scale"]
    a["pts_goals"]   = a["e_goals"]   * a["position"].map(GOAL_PTS)
    a["pts_assists"] = a["e_assists"] * 3
    a["p_60plus"]   = a["p_start"] * a["p60"]
    a["p_play_any"] = a["p_start"] + (1 - a["p_start"]) * 0.30
    a["pts_appear"] = a["p_60plus"] * 2 + (a["p_play_any"] - a["p_60plus"]).clip(lower=0) * 1
    if CS_UNIFIED:
        # One expected-goals-against distribution for BOTH defensive terms:
        # P(clean sheet) = P(0 goals) under Poisson(opp_lambda), replacing the
        # separately-blended p_cs. Overwritten (not shadowed) so every
        # downstream consumer -- pts_cs here, the BPS input, the persisted
        # p_cs column -- sees the same distribution the conceded term uses.
        a["p_cs"] = np.exp(-a["opp_lambda"])
    a["pts_cs"] = a["p_cs"] * a["position"].map(CS_PTS) * a["p_60plus"]
    a["pts_dc"] = a["p_dc_hit"] * 2 * a["minutes_frac"]

    # --- D1: missing scoring terms ---
    # Gated on D1_TERMS_ACTIVE, which is also stamped into every walk-forward
    # file as `d1_terms_active` -- flipping one without the other is impossible.
    if D1_TERMS_ACTIVE:
        # Saves: +1 per 3 (GK only)
        # E[floor(S/3)] where S ~ Poisson(saves_per_90 * minutes_frac)
        saves_mu = a["saves_per_90"] * a["minutes_frac"]
        a["pts_saves"] = np.where(
            a["position"] == "GK",
            _expected_floor_div(saves_mu.values, 3),
            0.0
        )

        # Goals conceded: -1 per 2 (GK/DEF only)
        # E[floor(C/2)] where C ~ Poisson(opp_lambda * minutes_frac)
        conceded_mu = a["opp_lambda"] * a["minutes_frac"]
        a["pts_conceded"] = np.where(
            a["position"].isin(["GK", "DEF"]),
            -_expected_floor_div(conceded_mu.values, 2),
            0.0
        )

        # Cards: -1 yellow, -3 red (all positions)
        a["pts_cards"] = -(a["yellow_per_90"] * 1 + a["red_per_90"] * 3) * a["minutes_frac"]

        # Penalty share: add to E[goals]
        # E[goals] = npxg90 * minutes_frac * fixture_scale + pen_share * team_pen_rate * minutes_frac
        a["e_goals"] = (a["npxg90"] * a["minutes_frac"] * a["fixture_scale"] +
                        a["penalty_share"] * a["team_pen_rate"] * a["minutes_frac"])

        # Recalculate pts_goals with updated e_goals
        a["pts_goals"] = a["e_goals"] * a["position"].map(GOAL_PTS)
    else:
        a["pts_saves"] = 0.0
        a["pts_conceded"] = 0.0
        a["pts_cards"] = 0.0

    a["e_points_core"] = (a["pts_appear"] + a["pts_goals"] + a["pts_assists"] +
                          a["pts_cs"] + a["pts_dc"] + a["pts_saves"] +
                          a["pts_conceded"] + a["pts_cards"])

    # --- 7. bonus (gated + recalibrated) ---
    # Pass predicted values for defensive/GK features instead of zeros.
    # The BPS model was trained on these; feeding zeros creates train/serve skew.
    bps_input = pd.DataFrame({
        "goals_scored": a["e_goals"], "assists": a["e_assists"],
        "clean_sheets": a["p_cs"] * a["p_60plus"], "minutes": a["e_minutes"],
        "is_def": (a["position"] == "DEF").astype(int), "is_mid": (a["position"] == "MID").astype(int),
        "is_gk": (a["position"] == "GK").astype(int),
        "saves": a["saves_per_90"] * a["minutes_frac"],
        "yellow_cards": a["yellow_per_90"] * a["minutes_frac"],
        "red_cards": a["red_per_90"] * a["minutes_frac"],
        "goals_conceded": a["opp_lambda"] * a["minutes_frac"],
        "penalties_missed": a["penalty_share"] * 0.1 * a["minutes_frac"],
        "own_goals": 0})
    a["pred_bps"] = bps_model.predict(bps_input[BPS_FEATURES])
    a["exp_bonus"] = bps_to_bonus(a["pred_bps"].values) * a["minutes_frac"]

    # Recalibration constant comes from bonus.py (cutoff-respecting, no leak).
    #
    # NORMALISED PER GAMEWEEK, not across the whole frame. Scaling by the mean of
    # everything assembled together makes a gameweek's prediction depend on WHICH
    # OTHER GAMEWEEKS happened to be in the same batch -- harmless when the batch
    # is always the full season, but indefensible under walk-forward, where the
    # harness assembles a rolling window. It showed up as gameweek k's prediction
    # shifting by ~0.03 points depending on what k+1..k+5 contained.
    #
    # Per-gameweek normalisation makes each gameweek self-contained: bonus points
    # are a fixed per-match quantity (three per fixture: 3, 2, 1), so the mean is
    # a per-gameweek property in the first place. This is the more correct
    # normalisation on its own terms, not merely the more convenient one.
    # Grain note for the per-fixture change: `bonus_mean` is the mean of vaastav's
    # `bonus` column, and vaastav rows are one per player-FIXTURE. So normalising
    # over per-fixture rows matches the grain the constant was always computed on;
    # the previous per-player-gameweek normalisation was the mismatched one.
    #
    # Consequence, accepted deliberately: in GW26, GW33 and GW36 the gameweek mean
    # is now taken over more rows, and doubled players' own inputs have changed, so
    # the shared constant moves and single-fixture players in those three
    # gameweeks shift very slightly. Bit-exact in the other 35. This is measured
    # and reported rather than hidden.
    gw_mean = a.groupby("gw")["exp_bonus"].transform("mean")
    a["exp_bonus"] = np.where(gw_mean > 0,
                              a["exp_bonus"] * bonus_mean / gw_mean,
                              a["exp_bonus"])
    a["e_points"] = a["e_points_core"] + a["exp_bonus"]
    a.attrs["n_exact_duplicate_rows_dropped"] = n_exact_dupes
    return a


def collapse_to_gameweek(af):
    """Per-fixture frame -> one row per (element, gw), which is the grain every
    consumer expects: predictions_2526.parquet, the optimizer, the simulator.

    Additive terms sum; rates average. For a single-fixture player both reduce to
    the value itself, so single-gameweek output is unchanged by construction.
    """
    sums = [c for c in SUM_COLS if c in af.columns]
    means = [c for c in MEAN_COLS if c in af.columns]
    firsts = [c for c in ["name", "position", "team", "player_id", "understat_id"]
              if c in af.columns]

    agg = {c: "sum" for c in sums}
    agg.update({c: "mean" for c in means})
    agg.update({c: "first" for c in firsts})

    out = (af.sort_values(FIXTURE_KEY).groupby(["element", "gw"], as_index=False)
           .agg(agg))
    out["n_fixtures"] = (af.groupby(["element", "gw"])["fixture"].nunique()
                         .reset_index(drop=True).values)
    out.attrs.update(af.attrs)
    return out


def build_predictions(log_mlflow=False, availability=None):
    """E[points] per player-gameweek. Computed per fixture, then summed.

    Return grain is unchanged -- one row per (element, gw) -- so predictions_2526,
    the optimizer and the simulator are unaffected apart from doubles finally
    being counted."""
    return collapse_to_gameweek(
        build_fixture_predictions(log_mlflow=log_mlflow, availability=availability))


def validate(a):
    a["actual_points"] = pd.to_numeric(a["actual_points"], errors="coerce")
    val = a.dropna(subset=["actual_points", "e_points"]).copy()
    print("\n=== VALIDATION ===")
    print(f"Spearman (rank): {spearmanr(val['e_points'], val['actual_points']).correlation:.3f}")
    print(f"Pearson:         {val['e_points'].corr(val['actual_points']):.3f}")
    print(f"MAE:             {(val['e_points'] - val['actual_points']).abs().mean():.2f}")
    print(f"Mean pred / actual: {val['e_points'].mean():.2f} / {val['actual_points'].mean():.2f}")
    vs = val.sort_values(["element", "gw"])
    vs["fair"] = vs.groupby("element")["actual_points"].transform(lambda s: s.shift(1).expanding().mean())
    f = vs.dropna(subset=["fair"])
    print(f"MAE model {(f['e_points']-f['actual_points']).abs().mean():.2f} vs fair baseline {(f['fair']-f['actual_points']).abs().mean():.2f}")
    val["band"] = pd.cut(val["e_minutes"], [0, 15, 45, 70, 90], labels=["<15", "15-45", "45-70", "70+"])
    print("\nCalibration by minutes band:")
    print(val.groupby("band", observed=True).agg(pred=("e_points", "mean"), actual=("actual_points", "mean")).round(2))


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv

    PRED_COLS = ["element", "player_id", "understat_id", "gw", "name", "position", "team",
                 "e_minutes", "e_points", "e_points_core", "exp_bonus",
                 "pts_goals", "pts_assists", "pts_cs", "pts_dc", "pts_appear",
                 "pts_saves", "pts_conceded", "pts_cards",
                 "n_fixtures"]
    out_path = BASE + r"\data\predictions_2526.parquet"

    if log:
        # Open the PARENT run FIRST, so every component run nests inside it.
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        with mlflow.start_run(run_name="assembly_static") as parent:
            mlflow.set_tag("component", "assembly")
            mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
            mlflow.log_params({
                "predict_season": "2025-26",
                "league_avg_lambda": LEAGUE_AVG_LAMBDA,
                "goal_pts": str(GOAL_PTS),
                "cs_pts": str(CS_PTS),
                "dc_base_fallback": str(DC_BASE),
                "p_sub_appearance_assumption": 0.30,
                "fixture_scale_clip": "0.5 to 2.0",
                "gating": "all performance terms multiplied by playing probability",
            })

            a = build_predictions(log_mlflow=True)
            predictions = a[PRED_COLS].copy()
            print(f"\nFinal predictions: {len(predictions)} player-gameweeks")
            validate(a)
            predictions.to_parquet(out_path, index=False)
            print(f"\nSaved -> {out_path}")

            mlflow.log_metrics(_eval_metrics(a))
            mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
            mlflow.log_text(_calibration_table(a).to_csv(index=False), "calibration_by_band.csv")
            print(f"\nMLflow parent run: {parent.info.run_id}")
    else:
        a = build_predictions(log_mlflow=False)
        predictions = a[PRED_COLS].copy()
        print(f"\nFinal predictions: {len(predictions)} player-gameweeks")
        validate(a)
        predictions.to_parquet(out_path, index=False)
        print(f"\nSaved -> {out_path}")

    print("\nTop distinct players by peak E[points]:")
    print(predictions.sort_values("e_points", ascending=False).drop_duplicates("element")
          .head(10)[["name", "position", "team", "e_points"]].to_string(index=False))