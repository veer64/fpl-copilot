"""get_league_table -- the table AS-OF a cutoff, through the agent's own entry.

The one rule that matters (FEATURE_IDEAS "league table and team form as a tool"): every
match filter goes through dixon_coles.knowable_before, the function the fit's training
filter and the as-of guard already share (KNOWN_ISSUES #25). A table that silently includes
the cutoff day's matches would be that bug in a new hat. So the tests hold that harder than
the arithmetic: the rule is monkeypatched and the OUTPUT must move, the sources are asserted
to contain no second date comparison, and the cutoff is exercised at three gameweeks.

The section-14 rule: these drive agent.call_tool("get_league_table", ...) and
model_tools.get_league_table -- the entry the model reaches -- with the IO helpers
monkeypatched, not the pure builder alone.
"""
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dixon_coles as dc                                   # noqa: E402

SEASON = "2026-27"
NAT = float("nan")

# ------------------------------------------------------------------ the synthetic season
# Four clubs. Names in the archive's spelling where it differs ("Tottenham" -> "Spurs") so
# the name bridge is exercised. Dates are DAY-stamped like the odds archive.
#   GW1  22 Aug   A v B 2-0          C v D 1-1
#   GW2  29 Aug   B v C 0-1 (NO ODDS) D v A 3-2      31 Aug  A v C 1-0   <- double for A and C
#   GW3   5 Sep   B v D 2-2          6 Sep  C v A 0-3
#        2 Sep   D v B postponed: dated before GW3's cutoff, no result
#   GW4  12 Sep   A v D, C v B unplayed
ARCHIVE = [
    # date,        home,        away,        hg,  ag,  b365h, b365d, b365a
    ("22/08/2026", "Arsenal",   "Tottenham", 2.0, 0.0, 2.0,   3.5,   3.8),
    ("22/08/2026", "Chelsea",   "Everton",   1.0, 1.0, 2.5,   3.2,   2.9),
    ("29/08/2026", "Tottenham", "Chelsea",   0.0, 1.0, NAT,   NAT,   NAT),
    ("29/08/2026", "Everton",   "Arsenal",   3.0, 2.0, 2.2,   3.4,   3.3),
    ("31/08/2026", "Arsenal",   "Chelsea",   1.0, 0.0, 1.8,   3.6,   4.5),
    ("05/09/2026", "Tottenham", "Everton",   2.0, 2.0, 2.4,   3.3,   3.0),
    ("06/09/2026", "Chelsea",   "Arsenal",   0.0, 3.0, 3.0,   3.3,   2.4),
    ("02/09/2026", "Everton",   "Tottenham", NAT, NAT, 2.1,   3.4,   3.5),
    ("12/09/2026", "Arsenal",   "Everton",   NAT, NAT, 1.9,   3.5,   4.0),
    ("12/09/2026", "Chelsea",   "Tottenham", NAT, NAT, 2.6,   3.3,   2.7),
]
# one earlier-season row so "the archive's first match" is a real, earlier date
OLDER = [("13/08/2016", "Arsenal", "Chelsea", 1.0, 2.0, 2.0, 3.5, 3.6)]

IDS = {"Arsenal": 1, "Spurs": 2, "Chelsea": 3, "Everton": 4}
CAL = [
    # fixture, GW, home,       away,      kickoff
    (1, 1, "Arsenal", "Spurs",   "2026-08-22T14:00:00Z"),
    (2, 1, "Chelsea", "Everton", "2026-08-22T16:30:00Z"),
    (3, 2, "Spurs",   "Chelsea", "2026-08-29T14:00:00Z"),
    (4, 2, "Everton", "Arsenal", "2026-08-29T14:00:00Z"),
    (5, 2, "Arsenal", "Chelsea", "2026-08-31T19:00:00Z"),
    (6, 3, "Spurs",   "Everton", "2026-09-05T14:00:00Z"),
    (7, 3, "Chelsea", "Arsenal", "2026-09-06T15:00:00Z"),
    (8, 4, "Arsenal", "Everton", "2026-09-12T14:00:00Z"),
    (9, 4, "Chelsea", "Spurs",   "2026-09-12T16:30:00Z"),
]
GW_FIRST_KICKOFF = {1: "2026-08-22 14:00", 2: "2026-08-29 14:00", 3: "2026-09-05 14:00",
                    4: "2026-09-12 14:00"}


def _matches(rows=None, older=True):
    rows = list(rows if rows is not None else ARCHIVE)
    recs = [dict(date=d, home=h, away=a, home_goals=hg, away_goals=ag, season=SEASON,
                 b365h=bh, b365d=bd, b365a=ba) for d, h, a, hg, ag, bh, bd, ba in rows]
    if older:
        recs += [dict(date=d, home=h, away=a, home_goals=hg, away_goals=ag, season="2016-17",
                      b365h=bh, b365d=bd, b365a=ba) for d, h, a, hg, ag, bh, bd, ba in OLDER]
    m = pd.DataFrame(recs)
    m["date_parsed"] = pd.to_datetime(m["date"], format="mixed", dayfirst=True)
    return m


def _cal(rows=None):
    """Stack-shaped: two player-like rows per fixture (one per side), as load_stack yields."""
    out = []
    for fx, gw, home, away, kick in (rows or CAL):
        for team, opp, was_home in ((home, away, True), (away, home, False)):
            for element in (10 * IDS[team], 10 * IDS[team] + 1):         # two "players" a side
                out.append(dict(season=SEASON, GW=gw, team=team, opponent_team=IDS[opp],
                                was_home=was_home, kickoff_time=kick, fixture=fx, element=element))
    return pd.DataFrame(out)


RUN = {"run_id": 9, "gw": 3, "season": SEASON, "finished_at": "2026-09-04 17:00:00+00:00",
       "recovered": False, "git_sha": "abc", "kind": "t10", "slot": None, "knowledge": None}


@pytest.fixture()
def mt(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools
    monkeypatch.setattr(model_tools, "_latest_run", lambda gw=None, any_status=False: dict(RUN))
    monkeypatch.setattr(model_tools, "_run_meta", lambda run, config=None: {"run_id": 9, "gw": 3})
    monkeypatch.setattr(model_tools, "_league_matches", lambda season: _matches())
    monkeypatch.setattr(model_tools, "_league_calendar", lambda season: _cal())
    monkeypatch.setattr(model_tools, "_odds_provenance", lambda season: None)   # an archive season
    return model_tools


def _row(out, club):
    hits = [r for r in out["table"] if r["team"] == club]
    assert len(hits) == 1, (club, [r["team"] for r in out["table"]])
    return hits[0]


# ------------------------------------------------------------------ the entry the model reaches

def test_the_agent_entry_point_is_registered_and_dispatches(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent
    names = [t["name"] for t in agent.tools_schema]
    assert "get_league_table" in names
    assert set(names) == set(agent.available_functions), "schema and dispatch map disagree"
    fn = agent.available_functions["get_league_table"]
    assert (fn.__module__, fn.__qualname__) == ("model_tools", "get_league_table")
    schema = next(t for t in agent.tools_schema if t["name"] == "get_league_table")
    assert set(schema["input_schema"]["properties"]) == {"as_of", "team", "form_last_n",
                                                         "include_odds_xpts"}
    monkeypatch.setitem(agent.available_functions, "get_league_table",
                        lambda **k: {"ok": True, "got": k})
    out = agent.call_tool("get_league_table", {"team": "Arsenal", "form_last_n": 3})
    assert out == {"ok": True, "got": {"team": "Arsenal", "form_last_n": 3}}


def test_a_tool_exception_becomes_an_error_result_not_a_500(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent

    def boom(**k):
        raise RuntimeError("archive gone")
    monkeypatch.setitem(agent.available_functions, "get_league_table", boom)
    out = agent.call_tool("get_league_table", {})
    assert "error" in out and "archive gone" in out["error"]


# ------------------------------------------------------------------ THE rule: one date filter

def test_knowable_before_is_the_only_date_filter_and_monkeypatching_it_moves_the_output(mt, monkeypatch):
    """The cutoff-day match (Spurs v Everton, 5 Sep) is excluded under the real rule. Swap in
    the OLD timed comparison -- the one that leaked (KNOWN_ISSUES #25) -- and it must appear.
    If a second copy of the rule ever lands in the tool, this stops moving and fails."""
    real = mt.get_league_table(as_of="2026-09-05T14:00:00")
    assert _row(real, "Spurs")["played"] == 2 and _row(real, "Everton")["played"] == 2

    def old_timed_rule(matches, cutoff):
        return ((matches["date_parsed"] < pd.Timestamp(cutoff))
                & matches["home_goals"].notna() & matches["away_goals"].notna())
    monkeypatch.setattr(dc, "knowable_before", old_timed_rule)
    leaky = mt.get_league_table(as_of="2026-09-05T14:00:00")
    assert _row(leaky, "Spurs")["played"] == 3 and _row(leaky, "Everton")["played"] == 3
    assert real["n_matches_in_table"] == 5 and leaky["n_matches_in_table"] == 6


def test_the_sources_contain_no_second_date_comparison(mt):
    import league_table as lt
    src_tool = inspect.getsource(mt.get_league_table)
    src_pure = inspect.getsource(lt)
    assert "dc.knowable_before(" in src_tool, "the tool must call the fit's own rule"
    # a ROW filter on the match dates, in any spelling, is the thing that must not exist twice
    for forbidden in ('date_parsed"] <', 'date_parsed"] >', "date_parsed'] <", "date_parsed'] >",
                      "date_parsed <", "date_parsed >", "< cutoff", "<= cutoff", "> cutoff",
                      ">= cutoff", "< day", "<= day", "> day", ">= day"):
        assert forbidden not in src_tool, f"a second cutoff comparison in the tool: {forbidden!r}"
        assert forbidden not in src_pure, f"a date comparison in the pure module: {forbidden!r}"
    assert ".normalize()" not in src_pure
    assert "knowable_before(" not in src_pure, "the pure module must not carry its own copy"


def test_cutoff_day_excluded_and_day_before_included_at_three_gameweeks(mt):
    """A check on one horizon step is not a check on the model: three cutoffs, three answers."""
    gw2 = mt.get_league_table(as_of="2026-08-29T14:00:00")           # GW2's first kickoff
    assert gw2["n_matches_in_table"] == 2
    assert all(_row(gw2, c)["played"] == 1 for c in ("Arsenal", "Spurs", "Chelsea", "Everton"))

    gw3 = mt.get_league_table(as_of="2026-09-05T14:00:00")
    assert gw3["n_matches_in_table"] == 5
    assert _row(gw3, "Arsenal")["played"] == 3 and _row(gw3, "Spurs")["played"] == 2

    gw4 = mt.get_league_table(as_of="2026-09-12T14:00:00")
    assert gw4["n_matches_in_table"] == 7                              # 5 Sep and 6 Sep now count
    assert _row(gw4, "Arsenal")["played"] == 4 and _row(gw4, "Everton")["played"] == 3

    # the day AFTER the 6 Sep match, one second past midnight: it counts (day-granular rule)
    assert mt.get_league_table(as_of="2026-09-07T00:00:01")["n_matches_in_table"] == 7
    # 23:59:59 on 6 Sep: it does not
    assert mt.get_league_table(as_of="2026-09-06T23:59:59")["n_matches_in_table"] == 6


def test_the_default_cutoff_is_the_runs_gameweek_first_kickoff(mt):
    """as_of=None -> the latest run's gameweek, cut at its first kickoff -- derived the way the
    walk-forward derives cutoff_date, from the same calendar."""
    default = mt.get_league_table()
    explicit = mt.get_league_table(as_of="2026-09-05T14:00:00")
    assert default["as_of"]["cutoff"] == "2026-09-05 14:00:00"
    assert default["as_of"]["cutoff"] == explicit["as_of"]["cutoff"]
    assert default["table"] == explicit["table"]
    assert "first kickoff" in default["as_of"]["source"] and "GW3" in default["as_of"]["source"]
    assert "cutoff DAY" in default["as_of"]["rule"] and "knowable_before" in default["as_of"]["rule"]


def test_the_default_cutoff_derivation_matches_the_walk_forward_on_the_real_calendar():
    """eval/walkforward_season.py: gw_start = v.groupby("GW")["kick"].min(); cutoff_date =
    gw_start.loc[k].tz_localize(None). Same expression, same file, every gameweek."""
    import league_table as lt
    from season_stack import load_stack
    df = load_stack(columns=["season", "GW", "kickoff_time", "team", "opponent_team",
                             "was_home", "fixture"])
    v = df[df["season"] == "2026-27"].copy()
    assert len(v) > 0, "the laptop's stack has no 2026-27 rows -- sync data down first"
    v["kick"] = pd.to_datetime(v["kickoff_time"])
    gw_start = v.groupby("GW")["kick"].min().sort_index()
    ours = lt.first_kickoff_by_gw(v)
    assert set(ours) == set(int(g) for g in gw_start.index)
    for k in gw_start.index:
        assert ours[int(k)] == gw_start.loc[k].tz_localize(None), k


def test_a_timezone_aware_as_of_is_read_as_utc(mt):
    a = mt.get_league_table(as_of="2026-09-05T14:00:00Z")
    b = mt.get_league_table(as_of="2026-09-05T15:00:00+01:00")
    assert a["as_of"]["cutoff"] == b["as_of"]["cutoff"] == "2026-09-05 14:00:00"


def test_an_unparseable_as_of_is_an_error(mt):
    out = mt.get_league_table(as_of="next tuesday-ish")
    assert "error" in out and "as_of" in out["error"]


# ------------------------------------------------------------------ the arithmetic

def test_points_and_goal_difference_reconcile_with_the_hand_built_results(mt):
    out = mt.get_league_table(as_of="2026-09-05T14:00:00")
    a, s, c, e = (_row(out, x) for x in ("Arsenal", "Spurs", "Chelsea", "Everton"))
    assert (a["played"], a["won"], a["drawn"], a["lost"], a["gf"], a["ga"], a["gd"], a["points"]) == (3, 2, 0, 1, 5, 3, 2, 6)
    assert (s["played"], s["won"], s["drawn"], s["lost"], s["gf"], s["ga"], s["gd"], s["points"]) == (2, 0, 0, 2, 0, 3, -3, 0)
    assert (c["played"], c["won"], c["drawn"], c["lost"], c["gf"], c["ga"], c["gd"], c["points"]) == (3, 1, 1, 1, 2, 2, 0, 4)
    assert (e["played"], e["won"], e["drawn"], e["lost"], e["gf"], e["ga"], e["gd"], e["points"]) == (2, 1, 1, 0, 4, 3, 1, 4)
    # positions: points, then GD (Everton +1 over Chelsea 0), then GF, then name
    assert [r["team"] for r in out["table"]] == ["Arsenal", "Everton", "Chelsea", "Spurs"]
    assert [r["position"] for r in out["table"]] == [1, 2, 3, 4]
    assert a["ppg"] == 2.0 and c["gf_per_game"] == round(2 / 3, 3) and s["ga_per_game"] == 1.5
    assert "goal difference" in out["tiebreak"]


def test_home_plus_away_splits_sum_to_the_table(mt):
    out = mt.get_league_table(as_of="2026-09-12T14:00:00")
    for r in out["table"]:
        for k in ("played", "won", "drawn", "lost", "gf", "ga", "gd", "points"):
            assert r["home"][k] + r["away"][k] == r[k], (r["team"], k)
    a = _row(out, "Arsenal")
    assert a["home"]["played"] == 2 and a["home"]["won"] == 2 and a["home"]["ga"] == 0
    assert a["away"]["played"] == 2 and a["away"]["won"] == 1 and a["away"]["lost"] == 1


def test_form_string_is_most_recent_last_and_capped_at_n(mt):
    out = mt.get_league_table(as_of="2026-09-12T14:00:00", form_last_n=3)
    a = _row(out, "Arsenal")                       # W(22/8) L(29/8) W(31/8) W(6/9)
    assert a["form_string"] == "LWW" and a["form_points"] == 6 and a["form_gf"] == 6 and a["form_ga"] == 3
    assert out["form"]["direction"].startswith("most recent LAST")
    full = mt.get_league_table(as_of="2026-09-12T14:00:00", form_last_n=5)
    assert _row(full, "Arsenal")["form_string"] == "WLWW"
    assert _row(full, "Arsenal")["form_n"] == 4                     # fewer than N played: say so


def test_streaks_and_counts(mt):
    out = mt.get_league_table(as_of="2026-09-05T14:00:00")
    a, s, c, e = (_row(out, x) for x in ("Arsenal", "Spurs", "Chelsea", "Everton"))
    assert (a["unbeaten_run"], a["winless_run"]) == (1, 0)          # W L W
    assert (s["unbeaten_run"], s["winless_run"]) == (0, 2)          # L L
    assert (c["unbeaten_run"], c["winless_run"]) == (0, 1)          # D W L
    assert (e["unbeaten_run"], e["winless_run"]) == (2, 0)          # D W
    assert a["clean_sheets"] == 2 and s["games_failed_to_score"] == 2
    assert a["one_goal_games"] == 2 and e["one_goal_games"] == 1 and s["one_goal_games"] == 1


# ------------------------------------------------------------------ odds-expected points

def _implied(h, d, a):
    raw = np.array([1 / h, 1 / d, 1 / a])
    return raw / raw.sum(), raw.sum()


def test_overround_normalised_probabilities_sum_to_one_and_the_overround_is_visible():
    import league_table as lt
    p = lt.implied_probabilities(2.0, 3.5, 3.8)
    assert abs(p["p_home"] + p["p_draw"] + p["p_away"] - 1.0) < 1e-12
    assert abs(p["overround"] - (1 / 2.0 + 1 / 3.5 + 1 / 3.8)) < 1e-12 and p["overround"] > 1.0
    assert lt.implied_probabilities(2.0, float("nan"), 3.8) is None      # never impute
    assert lt.implied_probabilities(None, 3.5, 3.8) is None
    assert lt.implied_probabilities(0.9, 3.5, 3.8) is None               # a price below evens-of-certainty is corrupt


def test_xpts_is_three_times_win_plus_draw_summed_over_counted_matches(mt):
    out = mt.get_league_table(as_of="2026-09-05T14:00:00")
    a = _row(out, "Arsenal")
    exp = 0.0
    for h, d, aa, home in ((2.0, 3.5, 3.8, True), (2.2, 3.4, 3.3, False), (1.8, 3.6, 4.5, True)):
        p, _ = _implied(h, d, aa)
        exp += 3 * (p[0] if home else p[2]) + p[1]
    assert a["odds_xpts"] == round(exp, 4)                            # the payload is 4 dp
    assert a["xpts_matches_counted"] == 3 == a["played"] and a["xpts_complete"] is True
    assert a["xpts_diff"] == round(6 - exp, 4)
    assert a["mean_overround"] > 1.0
    assert "Bet365" in out["odds_xpts"]["attribution"]
    assert "not a forecast" in out["odds_xpts"]["not_a_forecast"].lower() or \
           "never a forecast" in out["odds_xpts"]["not_a_forecast"].lower()
    assert "overround" in out["odds_xpts"]["method"]


def test_a_club_missing_odds_on_one_match_reports_fewer_counted_than_played(mt):
    """Chelsea's 29 Aug match carries no odds. It is excluded from the sum, the count says so,
    and xpts_diff compares points over the SAME counted matches -- a partial sum against a full
    points total would be exactly the masquerade the count exists to prevent."""
    out = mt.get_league_table(as_of="2026-09-05T14:00:00")
    c = _row(out, "Chelsea")
    assert c["played"] == 3 and c["xpts_matches_counted"] == 2 and c["xpts_complete"] is False
    p1, _ = _implied(2.5, 3.2, 2.9)                    # Chelsea home, drew   -> 1 pt
    p2, _ = _implied(1.8, 3.6, 4.5)                    # Chelsea away, lost   -> 0 pt
    exp = (3 * p1[0] + p1[1]) + (3 * p2[2] + p2[1])
    assert c["odds_xpts"] == round(exp, 4)
    assert c["xpts_points_basis"] == 1 and c["xpts_diff"] == round(1 - exp, 4)
    assert "counted" in c["xpts_note"]


def test_the_odds_are_attributed_from_the_provenance_never_from_the_column_name(mt, monkeypatch):
    """Measured 2026-09-19: the 2026-27 rows of the B365-named columns hold a de-margined
    twelve-book consensus (odds_live_pull_2026_27.provenance.json: "NOT Bet365"), overround
    1.0000 against about 1.05 for every archive season. The label must follow the sidecar."""
    archive = mt.get_league_table(as_of="2026-09-05T14:00:00", team="Arsenal")
    assert archive["odds_xpts"]["source_kind"] == "bet365"
    assert archive["odds_xpts"]["attribution"].startswith("Bet365")
    assert archive["form_detail"]["odds_attribution"].startswith("Bet365")

    prov = {"construction": "de-margined median consensus, fixed 12-book panel, min 5",
            "panel": ["betfair_ex_uk", "betway", "skybet", "williamhill"] * 3,
            "source_note": "NOT Bet365, NOT closing -- pre-deadline snapshot",
            "pulled_at": "2026-09-11T22:09:16+00:00"}
    monkeypatch.setattr(mt, "_odds_provenance", lambda season: prov)
    live = mt.get_league_table(as_of="2026-09-05T14:00:00", team="Arsenal")
    a = live["odds_xpts"]["attribution"]
    assert live["odds_xpts"]["source_kind"] == "consensus"
    assert not a.startswith("Bet365") and "NOT Bet365" in a and "consensus" in a and "12 books" in a
    assert "overround of about 1.0" in live["odds_xpts"]["method"]
    assert live["form_detail"]["odds_attribution"] == a
    # the numbers themselves do not change -- only who is credited with them
    assert _row(live, "Arsenal")["odds_xpts"] == _row(archive, "Arsenal")["odds_xpts"]


def test_include_odds_xpts_false_omits_every_odds_field(mt):
    out = mt.get_league_table(as_of="2026-09-05T14:00:00", include_odds_xpts=False)
    assert "odds_xpts" not in out
    for r in out["table"]:
        assert not any(k.startswith("xpts") or k == "odds_xpts" or k == "mean_overround" for k in r)


def test_no_field_presents_the_odds_as_a_forecast(mt):
    out = mt.get_league_table(as_of="2026-09-05T14:00:00")
    text = str(out).lower()
    for word in ("forecast_", "predicted_points", "projected", "value_bet", "edge"):
        assert word not in text, word


# ------------------------------------------------------------------ designed refusals

def test_a_club_with_no_knowable_matches_is_nulls_with_a_reason_not_zeros(mt):
    out = mt.get_league_table(as_of="2026-08-22T14:00:00")           # GW1's first kickoff
    assert out["n_matches_in_table"] == 0
    for r in out["table"]:
        assert r["position"] is None and r["played"] is None and r["points"] is None
        assert r["no_matches"] is True and "before the cutoff day" in r["reason"]
    assert len(out["table"]) == 4                                     # every club still listed


def test_as_of_before_the_archives_first_match_is_stated_not_truncated(mt):
    out = mt.get_league_table(as_of="2015-01-01")
    assert out["as_of"]["status"] == "before_first_match"
    assert "2016-08-13" in out["as_of"]["statement"] and out["table"] == []
    assert "error" not in out


def test_as_of_after_the_latest_result_is_stated_and_the_gap_is_listed(mt):
    """The archive's latest result is 6 Sep. Ask for 20 Sep: the 12 Sep fixtures are dated
    before the cutoff day with no result, so the table is INCOMPLETE as of that date, and it
    says so, naming them. Never silently the 6 Sep table wearing a 20 Sep label."""
    out = mt.get_league_table(as_of="2026-09-20T12:00:00")
    assert out["as_of"]["status"] == "after_latest_result"
    assert "2026-09-06" in out["as_of"]["statement"] and "2026-09-20" in out["as_of"]["statement"]
    missing = out["results_missing_before_cutoff"]
    pairs = {(m["home"], m["away"]) for m in missing["matches"]}
    assert ("Arsenal", "Everton") in pairs and ("Chelsea", "Spurs") in pairs
    assert ("Everton", "Spurs") in pairs                              # the 2 Sep postponement too
    assert missing["n"] == 3 and "incomplete" in missing["note"]
    assert out["n_matches_in_table"] == 7                             # they are NOT in the table


def test_a_postponed_match_dated_before_the_cutoff_is_listed_not_counted(mt):
    """2 Sep Everton v Spurs: dated before GW3's cutoff, no result (the goals clause). It must
    neither count nor vanish -- and it must be found with the SAME function, goals forced
    present, not with a second date comparison."""
    out = mt.get_league_table(as_of="2026-09-05T14:00:00")
    assert out["as_of"]["status"] == "ok"
    m = out["results_missing_before_cutoff"]
    assert m["n"] == 1 and (m["matches"][0]["home"], m["matches"][0]["away"]) == ("Everton", "Spurs")
    assert m["matches"][0]["gw"] is None                              # not in the calendar
    assert _row(out, "Everton")["played"] == 2


def test_the_season_follows_as_of_and_says_so_when_it_is_not_the_runs(mt):
    older = mt.get_league_table(as_of="2016-09-01")
    assert older["season"] == "2016-17" and older["n_matches_in_table"] == 1
    assert "2016-17" in older["season_note"] and "2026-27" in older["season_note"]
    cur = mt.get_league_table(as_of="2026-09-05T14:00:00")
    assert cur["season"] == "2026-27" and cur.get("season_note") is None


# ------------------------------------------------------------------ gameweeks, doubles, one club

def test_team_gives_that_clubs_row_and_results_grouped_by_gameweek(mt):
    out = mt.get_league_table(as_of="2026-09-05T14:00:00", team="Arsenal")
    assert [r["team"] for r in out["table"]] == ["Arsenal"]
    detail = out["form_detail"]
    assert detail["team"] == "Arsenal" and detail["position"] == 1
    by_gw = {g["gw"]: g["matches"] for g in detail["results_by_gw"]}
    assert set(by_gw) == {1, 2}
    assert len(by_gw[1]) == 1 and by_gw[1][0]["opponent"] == "Spurs" and by_gw[1][0]["venue"] == "H"
    assert by_gw[1][0]["score"] == "2-0" and by_gw[1][0]["result"] == "W"
    m = by_gw[1][0]["odds"]
    assert m is not None and abs(m["p_win"] + m["p_draw"] + m["p_loss"] - 1.0) < 1e-12
    assert m["overround"] > 1.0 and "Bet365" in detail["odds_attribution"]


def test_a_double_gameweek_returns_both_matches(mt):
    """Arsenal play twice in GW2 (29 Aug at Everton, 31 Aug v Chelsea). drop_duplicates on
    (team, gw) would hide the second leg -- the exact bug caught in get_fixtures."""
    out = mt.get_league_table(as_of="2026-09-05T14:00:00", team="Arsenal")
    gw2 = next(g for g in out["form_detail"]["results_by_gw"] if g["gw"] == 2)
    assert gw2["double_gameweek"] is True and len(gw2["matches"]) == 2
    assert [m["opponent"] for m in gw2["matches"]] == ["Everton", "Chelsea"]
    assert [m["result"] for m in gw2["matches"]] == ["L", "W"]


def test_gameweek_labels_come_from_the_calendar_by_fixture_pairing_never_by_date(mt, monkeypatch):
    """Remove the calendar: every match still counts, every gw is None, the count says so."""
    out = mt.get_league_table(as_of="2026-09-05T14:00:00", team="Arsenal")
    assert out["gameweek_labels"]["unmapped"] == 0
    monkeypatch.setattr(mt, "_league_calendar", lambda season: _cal().iloc[0:0])
    bare = mt.get_league_table(as_of="2026-09-05T14:00:00", team="Arsenal")
    assert _row(bare, "Arsenal")["played"] == 3                       # the table never depends on it
    assert bare["gameweek_labels"]["unmapped"] == 5
    assert [g["gw"] for g in bare["form_detail"]["results_by_gw"]] == [None]
    assert "error" not in bare and "no calendar" in bare["gameweek_labels"]["note"]


def test_team_resolution_uses_fpl_spellings_and_declines_the_unknown(mt):
    assert _row(mt.get_league_table(team="tottenham"), "Spurs")["team"] == "Spurs"
    assert _row(mt.get_league_table(team="spurs"), "Spurs")["team"] == "Spurs"
    out = mt.get_league_table(team="Wigan")
    assert "error" in out and "not a club" in out["error"] and set(out["known_teams"]) == set(IDS)


def test_a_missing_archive_is_an_error_not_an_empty_table(mt, monkeypatch):
    def boom(season):
        raise FileNotFoundError("odds_all_seasons_with_2026_27.parquet")
    monkeypatch.setattr(mt, "_league_matches", boom)
    out = mt.get_league_table()
    assert "error" in out and "missing FILE" in out["error"]


def test_no_run_is_an_error_before_anything_else(mt, monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    assert "error" in mt.get_league_table()


# ------------------------------------------------------------------ purity, the read layer, the prompt

def _unpatched_model_tools(monkeypatch):
    """The module as it is on disk. The `mt` fixture swaps the IO helpers for lambdas, so a
    source inspection through it would read the lambda and pass for nothing."""
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools
    for name in ("_league_matches", "_league_calendar", "get_league_table"):
        assert inspect.getsourcefile(getattr(model_tools, name)).endswith("model_tools.py"), name
    return model_tools


def test_the_tool_reads_no_prediction_table_so_the_select_rule_is_moot_by_construction(monkeypatch):
    """Rule 2 (a read must never depend on a write): this tool touches model_predictions not at
    all. If that ever changes, the SELECT-vs-PRED_INSERT_COLS test must come with it."""
    real = _unpatched_model_tools(monkeypatch)
    import league_table as lt
    for src in (inspect.getsource(real.get_league_table), inspect.getsource(real._league_matches),
                inspect.getsource(real._league_calendar), inspect.getsource(lt)):
        assert "model_predictions" not in src and "SELECT" not in src


def test_the_pure_module_imports_no_part_of_the_model_stack():
    import league_table as lt
    src = inspect.getsource(lt)
    for forbidden in ("import dixon_coles", "from dixon_coles", "import assembly", "from assembly",
                      "import scipy", "from scipy", "import sklearn", "import lightgbm",
                      "import model_tools", "import psycopg2"):
        assert forbidden not in src, forbidden


def test_the_tool_imports_the_rule_lazily_and_the_match_loader_is_the_fits_own(monkeypatch):
    real = _unpatched_model_tools(monkeypatch)
    src = inspect.getsource(real.get_league_table) + inspect.getsource(real._league_matches)
    assert "import dixon_coles as dc" in src
    assert "_load_matches(" in src, "the archive must be read by the fit's own loader"


def test_knowable_before_docstring_counts_its_callers():
    doc = dc.knowable_before.__doc__
    assert "three places" in doc and "get_league_table" in doc


def test_the_prompt_puts_the_table_in_scope_and_keeps_the_betting_line(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent
    p = agent.SYSTEM_PROMPT
    assert "get_league_table" in p
    assert "# 2c." in p
    assert "Bet365" in p and "not a forecast" in p
    assert "I don't give betting advice or assess bets" in p          # section 5 intact
    assert "combined" not in p.lower()
    scope = p.split("# 6. Scope")[1].split("# 7.")[0]
    assert "league table" in scope.lower() and "form" in scope.lower()
