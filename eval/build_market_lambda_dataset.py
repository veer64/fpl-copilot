# build_market_lambda_dataset.py
# D4 Phase 1 -- dataset for the market-lambda model (synthetic forward odds).
#
# TARGET: market_lambda, one row per TEAM per MATCH (7,600 rows over 10 seasons).
# Bet365 1X2 odds are inverted (1/odds, proportional overround removal), then the
# (lam_home, lam_away) whose Poisson scoreline matrix reproduces those
# probabilities is solved via squad.dixon_coles._implied_lambdas -- the SAME
# inversion production uses, so the target is defined exactly as the pipeline
# defines it.
#
# FEATURES (19), five blocks:
#   market history (team, 6)     : own/conceded market lambda, last-5 / last-10 /
#                                  season-to-date means
#   market history (opponent, 4) : own/conceded, last-5 / last-10 means
#   dixon-coles (3)              : dc_attack(team), dc_defence(opponent), is_home
#                                  -- refit per (season, gameweek) on matches
#                                  strictly before that gameweek's first match
#                                  date, 1-year half-life (production config)
#   schedule (4)                 : rest days + matches-in-last-14, team and opp
#                                  (EPL fixtures only -- cups/Europe invisible)
#   availability (2)             : count of each side's top-5-by-season-minutes
#                                  players flagged unavailable (asof_status in
#                                  i/s/u/n) at the gameweek deadline. 2021-22
#                                  onward; NaN before (LightGBM handles NaN).
#
# LEAKAGE RULE (binding): every feature strictly from information dated BEFORE
# the current match date. Every block writes an audit column carrying the max
# source date it consumed for each row; assert_no_leakage() then asserts
# max(source dates) < match_date on EVERY row. See leakage_audit_columns().
#
# TEAM NAMES: odds (football-data) and vaastav disagree on exactly three clubs.
# KNOWN_ISSUES #14 (Sheffield) is why the map below FAILS LOUDLY on any club it
# cannot account for, in either direction, rather than letting a join quietly
# drop a team.
#
# BURN-IN: rows where any of the 10 market-history features is undefined are
# FLAGGED (burn_in=True), not deleted -- the model script drops them, and the
# report quotes the counts. Availability NaN (pre-2021-22, GW1 ranking
# undefined, missing snapshot) is NOT burn-in; LightGBM handles those natively.
#
# Output: data/d4_market_lambda_dataset.parquet  (all 7,600 rows + burn_in flag)
# Cache : data/history/d4_dc_walkforward_params.parquet (380 per-GW DC fits)
#
# Usage: uv run python eval/build_market_lambda_dataset.py

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot")
sys.path.insert(0, str(BASE))

from squad.dixon_coles import _implied_lambdas, _fit_dc_decay  # noqa: E402

ODDS_PATH = BASE / "data" / "history" / "odds_all_seasons.parquet"
VAASTAV_PATH = BASE / "data" / "history" / "all_seasons_fixed.parquet"
OUT_PATH = BASE / "data" / "d4_market_lambda_dataset.parquet"
DC_CACHE = BASE / "data" / "history" / "d4_dc_walkforward_params.parquet"

HALF_LIFE_DAYS = 365          # matches squad/dixon_coles.py
UNAVAILABLE_STATUSES = {"i", "s", "u", "n"}   # 'd' (doubtful) deliberately NOT counted
AVAILABILITY_SEASONS = {      # coverage starts 2021-22; NaN before
    "2021-22": "availability_2122.parquet",
    "2022-23": "availability_2223.parquet",
    "2023-24": "availability_2324.parquet",
    "2024-25": "availability_2425.parquet",
    "2025-26": "availability_2526.parquet",
}

# odds-file name -> vaastav name. Same three entries as assembly.TEAM_MAP.
ALIAS = {"Man United": "Man Utd", "Sheffield United": "Sheffield Utd",
         "Tottenham": "Spurs"}


def _assert_names_reconcile(odds_names, vaastav_names):
    """KNOWN_ISSUES #14: an unmapped club silently zeroes a whole season.
    Fail loudly, naming the club, if the two sources do not reconcile exactly."""
    mapped = {ALIAS.get(n, n) for n in odds_names}
    only_odds = mapped - set(vaastav_names)
    only_vaastav = set(vaastav_names) - mapped
    if only_odds or only_vaastav:
        raise AssertionError(
            f"Team-name reconciliation FAILED (KNOWN_ISSUES #14 class). "
            f"odds-side unmatched: {sorted(only_odds)}; "
            f"vaastav-side unmatched: {sorted(only_vaastav)}. "
            f"Extend ALIAS explicitly -- do not let a join drop a club.")


# ---------------------------------------------------------------- target ----

def load_matches():
    o = pd.read_parquet(ODDS_PATH)
    m = o[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "season",
           "B365H", "B365D", "B365A"]].copy()
    m.columns = ["date", "home", "away", "home_goals", "away_goals", "season",
                 "b365h", "b365d", "b365a"]
    m["match_date"] = pd.to_datetime(m["date"], format="mixed", dayfirst=True)
    m["home"] = m["home"].map(lambda t: ALIAS.get(t, t))
    m["away"] = m["away"].map(lambda t: ALIAS.get(t, t))
    m = m.sort_values("match_date").reset_index(drop=True)
    m["match_id"] = np.arange(len(m))
    assert len(m) == 3800, f"expected 3,800 matches, got {len(m)}"
    assert m[["b365h", "b365d", "b365a"]].notna().all().all(), "missing B365 odds"
    # one match per (team, date) -- what makes (team, date) a valid key later
    long_check = pd.concat([m[["home", "match_date"]].rename(columns={"home": "team"}),
                            m[["away", "match_date"]].rename(columns={"away": "team"})])
    assert not long_check.duplicated().any(), "a team appears twice on one date"
    return m


def invert_odds(m):
    """1/odds -> proportional overround removal -> Poisson-implied lambdas."""
    inv = 1.0 / m[["b365h", "b365d", "b365a"]].values
    probs = inv / inv.sum(axis=1, keepdims=True)
    t0 = time.time()
    lams = np.array([_implied_lambdas(*p) for p in probs])
    print(f"  inverted {len(m)} matches in {time.time()-t0:.0f}s")
    m = m.copy()
    m["mkt_lam_home"], m["mkt_lam_away"] = lams[:, 0], lams[:, 1]
    assert m["mkt_lam_home"].between(0.1, 6).all(), "home lambda out of range"
    assert m["mkt_lam_away"].between(0.1, 6).all(), "away lambda out of range"
    return m


# ---------------------------------------------------- gameweek mapping ----

def map_gameweeks(m):
    """Attach vaastav's GW to every odds match via (season, team, kickoff date).
    Needed only for the DC refit grid and the availability deadline lookup."""
    va = pd.read_parquet(VAASTAV_PATH,
                         columns=["season", "team", "kickoff_time", "GW"])
    va = va.dropna(subset=["team", "kickoff_time"])
    va["kick_date"] = pd.to_datetime(va["kickoff_time"], utc=True).dt.date
    fx = (va.drop_duplicates(["season", "team", "kick_date"])
            [["season", "team", "kick_date", "GW"]]
            .rename(columns={"GW": "gw"}))
    assert not fx.duplicated(["season", "team", "kick_date"]).any()

    _assert_names_reconcile(set(m["home"]) | set(m["away"]), set(fx["team"]))

    m = m.copy()
    m["kick_date"] = m["match_date"].dt.date
    for side in ("home", "away"):
        m = m.merge(fx.rename(columns={"team": side, "gw": f"gw_{side}"}),
                    on=["season", side, "kick_date"], how="left")
    n_miss = m["gw_home"].isna().sum() + m["gw_away"].isna().sum()
    if n_miss:
        bad = m[m["gw_home"].isna() | m["gw_away"].isna()]
        raise AssertionError(
            f"{n_miss} side(s) failed the odds->vaastav date join; first rows:\n"
            f"{bad[['season', 'home', 'away', 'kick_date']].head(10)}")
    disagree = m["gw_home"] != m["gw_away"]
    assert not disagree.any(), f"home/away GW disagree on {disagree.sum()} matches"
    m["gw"] = m["gw_home"].astype(int)
    return m.drop(columns=["gw_home", "gw_away"])


# ------------------------------------------------------------ dc features ----

def dc_walkforward(m):
    """One DC fit per (season, gw): trained on matches strictly before that
    gameweek's FIRST match date (more conservative than per-date -- a Sunday
    match never sees Saturday results from its own GW). 1-year half-life,
    production model form. Returns per-match dc columns + audit dates.
    Cached: refits only (season, gw) cells missing from the cache."""
    teams = sorted(set(m["home"]) | set(m["away"]))
    cells = (m.groupby(["season", "gw"])["match_date"].min()
              .rename("cutoff").reset_index())

    cache = pd.read_parquet(DC_CACHE) if DC_CACHE.exists() else pd.DataFrame(
        columns=["season", "gw", "team", "attack", "defence", "hadv"])
    have = set(zip(cache["season"], cache["gw"]))
    todo = cells[~cells.apply(lambda r: (r["season"], r["gw"]) in have, axis=1)]
    print(f"  DC walk-forward: {len(cells)} cells, {len(todo)} to fit")

    rows = []
    t0 = time.time()
    for i, (_, c) in enumerate(todo.iterrows(), 1):
        # _fit_dc_decay expects production's internal column name `date_parsed`
        train = (m[m["match_date"] < c["cutoff"]]
                 .rename(columns={"match_date": "date_parsed"}))
        if len(train) == 0:      # very first gameweek of 2016-17: no history at
            params = np.zeros(2 * len(teams) + 2)   # all -> neutral strengths
        else:
            params, _, _ = _fit_dc_decay(train, teams, c["cutoff"], HALF_LIFE_DAYS)
        nt = len(teams)
        for j, t in enumerate(teams):
            rows.append({"season": c["season"], "gw": c["gw"], "team": t,
                         "attack": params[j], "defence": params[nt + j],
                         "hadv": params[-2],
                         "train_max_date": train["date_parsed"].max()
                         if len(train) else pd.NaT,
                         "cutoff": c["cutoff"]})
        if i % 20 == 0:
            el = time.time() - t0
            print(f"    {i}/{len(todo)} fits, {el:.0f}s elapsed "
                  f"(~{el/i:.1f}s/fit)", flush=True)
        if i % 25 == 0:      # incremental flush: a killed run resumes from here
            snap = pd.concat([cache, pd.DataFrame(rows)], ignore_index=True)
            DC_CACHE.parent.mkdir(parents=True, exist_ok=True)
            snap.to_parquet(DC_CACHE, index=False)
    if rows:
        cache = pd.concat([cache, pd.DataFrame(rows)], ignore_index=True)
        DC_CACHE.parent.mkdir(parents=True, exist_ok=True)
        cache.to_parquet(DC_CACHE, index=False)
    return cache


def attach_dc(long, dc):
    """dc_attack for the team, dc_defence for the opponent, plus the DC-alone
    lambda prediction (baseline column, NOT a feature)."""
    own = dc[["season", "gw", "team", "attack", "hadv", "cutoff",
              "train_max_date"]].rename(columns={"attack": "dc_attack",
                                                 "cutoff": "dc_cutoff",
                                                 "train_max_date": "dc_train_max"})
    opp = dc[["season", "gw", "team", "defence"]].rename(
        columns={"team": "opponent", "defence": "dc_defence_opp"})
    long = long.merge(own, on=["season", "gw", "team"], how="left")
    long = long.merge(opp, on=["season", "gw", "opponent"], how="left")
    assert long["dc_attack"].notna().all() and long["dc_defence_opp"].notna().all()
    long["dc_lambda_pred"] = np.exp(long["dc_attack"] + long["dc_defence_opp"]
                                    + long["hadv"] * long["is_home"])
    return long.drop(columns=["hadv"])


# ---------------------------------------------------------- long grain ----

def to_team_match(m):
    """7,600 team-match rows: each match contributes a home row and an away row.
    market_lambda = that team's implied goals; conceded = the opponent's."""
    home = m[["match_id", "season", "gw", "match_date", "home", "away",
              "mkt_lam_home", "mkt_lam_away"]].copy()
    home.columns = ["match_id", "season", "gw", "match_date", "team", "opponent",
                    "market_lambda", "market_lambda_conceded"]
    home["is_home"] = 1
    away = m[["match_id", "season", "gw", "match_date", "away", "home",
              "mkt_lam_away", "mkt_lam_home"]].copy()
    away.columns = home.columns[:-1]
    away["is_home"] = 0
    long = (pd.concat([home, away], ignore_index=True)
              .sort_values(["match_date", "match_id", "is_home"])
              .reset_index(drop=True))
    assert len(long) == 2 * len(m)
    return long


# ------------------------------------------------- market history rolls ----

def market_history(long):
    """Per team, ordered by date: last-5 / last-10 / season-to-date means of own
    and conceded market lambda. shift(1) excludes the current match; windows
    require the FULL window (min_periods=window) so a partial window is NaN,
    not a quietly noisier mean. Rolls cross season boundaries; season-to-date
    resets. prev_date is the audit column: the date of the most recent match
    any of these features consumed."""
    long = long.sort_values(["team", "match_date"]).copy()
    g = long.groupby("team", sort=False)
    for col, tag in [("market_lambda", "own"), ("market_lambda_conceded", "conc")]:
        s = g[col].shift(1)
        sg = s.groupby(long["team"], sort=False)
        long[f"mh_{tag}_l5"] = sg.rolling(5, min_periods=5).mean().droplevel(0)
        long[f"mh_{tag}_l10"] = sg.rolling(10, min_periods=10).mean().droplevel(0)
    # season-to-date: expanding mean of the shifted series within (team, season)
    for col, tag in [("market_lambda", "own"), ("market_lambda_conceded", "conc")]:
        s = long.groupby(["team", "season"], sort=False)[col].shift(1)
        long[f"mh_{tag}_s2d"] = (s.groupby([long["team"], long["season"]], sort=False)
                                  .expanding().mean().droplevel([0, 1]))
    long["mh_prev_date"] = g["match_date"].shift(1)   # audit: newest source date
    return long.sort_values(["match_date", "match_id", "is_home"]).reset_index(drop=True)


def attach_opponent_history(long):
    """The opponent's own last-5/last-10 pairs, joined from the opponent's row
    of the SAME match -- their features already only read matches before it."""
    opp = long[["match_id", "team", "mh_own_l5", "mh_own_l10",
                "mh_conc_l5", "mh_conc_l10", "mh_prev_date"]].copy()
    opp.columns = ["match_id", "opponent", "mh_opp_own_l5", "mh_opp_own_l10",
                   "mh_opp_conc_l5", "mh_opp_conc_l10", "mh_opp_prev_date"]
    out = long.merge(opp, on=["match_id", "opponent"], how="left")
    assert len(out) == len(long)
    return out


# ------------------------------------------------------------- schedule ----

def schedule(long):
    """Rest days since the previous EPL match and matches in the strictly-prior
    14 days, for the team; opponent versions joined from the opponent's row.
    EPL fixtures only -- cup/European congestion is invisible to this block."""
    long = long.sort_values(["team", "match_date"]).copy()
    prev = long.groupby("team", sort=False)["match_date"].shift(1)
    long["sch_rest_days"] = (long["match_date"] - prev).dt.days

    counts = []
    for _, grp in long.groupby("team", sort=False):
        d = grp["match_date"]
        # count of the team's matches in [date-14, date) -- current match excluded
        counts.append(pd.Series(
            np.searchsorted(d.values, d.values) -
            np.searchsorted(d.values, d.values - np.timedelta64(14, "D")),
            index=grp.index))
    long["sch_m14"] = pd.concat(counts)

    long = long.sort_values(["match_date", "match_id", "is_home"]).reset_index(drop=True)
    opp = long[["match_id", "team", "sch_rest_days", "sch_m14"]].copy()
    opp.columns = ["match_id", "opponent", "sch_rest_days_opp", "sch_m14_opp"]
    out = long.merge(opp, on=["match_id", "opponent"], how="left")
    assert len(out) == len(long)
    return out


# --------------------------------------------------------- availability ----

def availability(long):
    """Count of the side's top-5-by-minutes players flagged unavailable at the
    gameweek deadline (asof_* columns -- point-in-time by construction).

    top-5 = by CUMULATIVE minutes this season from vaastav rows whose kickoff is
    strictly before the match date. GW1 has no prior minutes -> ranking
    undefined -> NaN. A (season, gw) with NO availability rows at all -> NaN,
    never 0 -- a silent 'everyone fit' is the KNOWN_ISSUES #14 family.
    Pre-2021-22 seasons have no availability files -> NaN (LightGBM handles)."""
    va = pd.read_parquet(VAASTAV_PATH,
                         columns=["season", "team", "element", "minutes",
                                  "kickoff_time"])
    va = va.dropna(subset=["team"])
    va["kick_date"] = pd.to_datetime(va["kickoff_time"], utc=True).dt.date

    av_frames = []
    for season, fname in AVAILABILITY_SEASONS.items():
        p = BASE / "data" / fname
        if not p.exists():
            raise AssertionError(f"availability file missing: {p}")
        a = pd.read_parquet(p, columns=["gw", "element", "asof_status",
                                        "deadline_time", "season"])
        av_frames.append(a)
    av = pd.concat(av_frames, ignore_index=True)
    av_gws = av.groupby(["season", "gw"]).size()          # empty-GW tripwire
    av_idx = av.set_index(["season", "gw", "element"])["asof_status"]
    deadline = (pd.to_datetime(av.groupby(["season", "gw"])["deadline_time"].first(),
                               utc=True).dt.date)

    # Every NaN must carry its reason -- 'missing rows' and 'nobody flagged'
    # are different facts and must never be conflated (the #14 lesson again).
    #   av_top5_out    : flagged count among top-5 players WITH availability rows
    #                    (NaN when the whole gw has no snapshot, when the minutes
    #                    ranking is undefined, or when none of the top-5 has a row)
    #   av_top5_found  : how many of the top-5 had an availability row (audit;
    #                    <5 means av_top5_out is a lower bound for that row)
    #   av_missing_reason : why av_top5_out is NaN, when it is
    out_team, out_found, out_deadline, out_reason = {}, {}, {}, {}
    for (season, team), grp in long.groupby(["season", "team"], sort=False):
        if season not in AVAILABILITY_SEASONS:
            for idx in grp.index:
                out_reason[idx] = "season_precoverage"
            continue
        vt = va[(va["season"] == season) & (va["team"] == team)]
        mins = vt.groupby(["kick_date", "element"])["minutes"].sum().reset_index()
        for idx, row in grp.iterrows():
            mdate, gw = row["match_date"].date(), row["gw"]
            if (season, gw) not in av_gws.index:
                out_reason[idx] = "gw_snapshot_missing"
                continue
            prior = mins[mins["kick_date"] < mdate]
            if len(prior) == 0:
                out_reason[idx] = "no_prior_minutes"     # GW1: ranking undefined
                continue
            top5 = (prior.groupby("element")["minutes"].sum()
                         .sort_values(ascending=False).head(5).index)
            statuses = [av_idx.get((season, gw, e), None) for e in top5]
            found = [s for s in statuses if isinstance(s, str)]
            out_found[idx] = len(found)
            if not found:
                out_reason[idx] = "top5_rows_missing"
                continue
            out_team[idx] = sum(1 for s in found if s in UNAVAILABLE_STATUSES)
            out_deadline[idx] = deadline.get((season, gw), pd.NaT)

    long = long.copy()
    long["av_top5_out"] = pd.Series(out_team)
    long["av_top5_found"] = pd.Series(out_found)
    long["av_missing_reason"] = pd.Series(out_reason)
    long["av_deadline_date"] = pd.Series(out_deadline)    # audit column
    opp = long[["match_id", "team", "av_top5_out"]].copy()
    opp.columns = ["match_id", "opponent", "av_top5_out_opp"]
    out = long.merge(opp, on=["match_id", "opponent"], how="left")
    assert len(out) == len(long)
    return out


# ------------------------------------------------------- leakage audit ----

FEATURES = [
    "mh_own_l5", "mh_own_l10", "mh_own_s2d",
    "mh_conc_l5", "mh_conc_l10", "mh_conc_s2d",
    "mh_opp_own_l5", "mh_opp_own_l10", "mh_opp_conc_l5", "mh_opp_conc_l10",
    "dc_attack", "dc_defence_opp", "is_home",
    "sch_rest_days", "sch_m14", "sch_rest_days_opp", "sch_m14_opp",
    "av_top5_out", "av_top5_out_opp",
]


def assert_no_leakage(long):
    """The binding rule: every feature strictly from before the match date.
    Each block carried the max source date it consumed; assert it per row.
      - market history / schedule: mh_prev_date (team) and mh_opp_prev_date
        (opponent) are the NEWEST match either block could have read (shift(1)).
      - DC: the fit's training set max date, and the cutoff itself.
      - availability: the gameweek deadline (always before every match it gates).
    """
    md = long["match_date"]
    checks = {
        "mh_prev_date": long["mh_prev_date"] < md,
        "mh_opp_prev_date": long["mh_opp_prev_date"] < md,
        "dc_train_max": long["dc_train_max"] < md,
        "dc_cutoff": long["dc_cutoff"] <= md,
        "av_deadline": (pd.to_datetime(long["av_deadline_date"])
                        <= md),
    }
    for name, ok in checks.items():
        col = {"mh_prev_date": "mh_prev_date", "mh_opp_prev_date": "mh_opp_prev_date",
               "dc_train_max": "dc_train_max", "dc_cutoff": "dc_cutoff",
               "av_deadline": "av_deadline_date"}[name]
        applicable = long[col].notna()
        bad = applicable & ~ok
        assert not bad.any(), (
            f"LEAKAGE: {name} on/after match_date for {bad.sum()} rows:\n"
            f"{long.loc[bad, ['season', 'gw', 'team', 'match_date', col]].head()}")
        print(f"  leakage check [{name}]: {applicable.sum()} applicable rows, all strict")


# --------------------------------------------------------------- main ----

def main():
    print("[1/7] load + invert odds")
    m = load_matches()
    m = invert_odds(m)
    print(f"  league-average market lambda: {np.mean([m.mkt_lam_home.mean(), m.mkt_lam_away.mean()]):.3f}")

    print("[2/7] gameweek mapping (odds -> vaastav)")
    m = map_gameweeks(m)

    print("[3/7] team-match grain")
    long = to_team_match(m)

    print("[4/7] Dixon-Coles walk-forward refits")
    dc = dc_walkforward(m)
    long = attach_dc(long, dc)

    print("[5/7] market-history + schedule features")
    long = market_history(long)
    long = attach_opponent_history(long)
    long = schedule(long)

    print("[6/7] availability features")
    long = availability(long)

    print("[7/7] leakage audit + burn-in flag + save")
    assert_no_leakage(long)
    mh_cols = [c for c in FEATURES if c.startswith("mh_")]
    long["burn_in"] = long[mh_cols].isna().any(axis=1)
    missing = [c for c in FEATURES if c not in long.columns]
    assert not missing, f"feature columns missing: {missing}"

    long.to_parquet(OUT_PATH, index=False)
    print(f"\nsaved {len(long)} rows -> {OUT_PATH}")
    print(f"burn-in rows: {long['burn_in'].sum()}  usable: {(~long['burn_in']).sum()}")
    print("burn-in by season:")
    print(long.groupby('season')['burn_in'].agg(['sum', 'count']).to_string())
    print("availability join coverage by season (missing != nobody-flagged):")
    cov = long.groupby("season").agg(
        rows=("av_top5_out", "size"),
        with_count=("av_top5_out", "count"),
        mean_found=("av_top5_found", "mean"),
        mean_out=("av_top5_out", "mean"))
    print(cov.to_string())
    print("NaN reasons:")
    print(long[long["av_top5_out"].isna()]
          .groupby(["season", "av_missing_reason"], dropna=False)
          .size().to_string())


if __name__ == "__main__":
    main()
