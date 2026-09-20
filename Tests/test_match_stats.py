"""get_match_stats -- ONE STAT, ONE SOURCE; grain stated, never inferred; the one as-of rule.

The registry is the spine: every stat resolves to exactly one source, grain and column, and
nothing outside the registry decides where a number comes from. Per-match rows pass through
dixon_coles.knowable_before once (the fourth caller); FBref season aggregates have no date and
are labelled, never widened or narrowed into a window. Synthetic frames throughout; the IO
helpers are monkeypatched. Two tests read the real FBref folder on disk (names, provenance).
"""
import inspect
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dixon_coles as dc                                   # noqa: E402

NAT = float("nan")

# ------------------------------------------------------------------ the synthetic world
# Archive spellings ("Tottenham"); seasons 2025-26 (complete, small) and 2026-27 (live).
ARCHIVE = [
    # season,   Date,         home,        away,        hg,  ag,  HS,  AS,  HST, AST, HC,  AC,  HF, AF, HY, AY, HR, AR
    ("2025-26", "16/08/2025", "Arsenal",   "Tottenham", 2.0, 0.0, 15., 6.,  7.,  2.,  8.,  3.,  9., 12., 1., 2., 0., 0.),
    ("2025-26", "23/08/2025", "Everton",   "Arsenal",   1.0, 1.0, 9.,  14., 3.,  5.,  4.,  7.,  11., 8., 2., 1., 0., 0.),
    ("2025-26", "30/08/2025", "Tottenham", "Everton",   3.0, 1.0, 12., 10., 6.,  4.,  5.,  5.,  10., 10., 1., 1., 0., 1.),
    ("2025-26", "13/09/2025", "Arsenal",   "Everton",   4.0, 0.0, 20., 4.,  9.,  1.,  10., 2.,  7., 13., 0., 3., 0., 0.),
    ("2025-26", "20/09/2025", "Tottenham", "Arsenal",   1.0, 2.0, 8.,  13., 2.,  6.,  3.,  6.,  12., 9., 3., 1., 1., 0.),
    ("2026-27", "22/08/2026", "Arsenal",   "Tottenham", 3.0, 0.0, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT),
    ("2026-27", "29/08/2026", "Everton",   "Arsenal",   3.0, 2.0, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT),
    ("2026-27", "05/09/2026", "Tottenham", "Everton",   2.0, 2.0, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT),
    ("2026-27", "12/09/2026", "Arsenal",   "Everton",   NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT),
    ("2026-27", "19/09/2026", "Everton",   "Tottenham", NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT),
]
ARCHIVE_COLS = ["season", "Date", "home", "away", "home_goals", "away_goals",
                "HS", "AS", "HST", "AST", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]


def _archive():
    df = pd.DataFrame(ARCHIVE, columns=ARCHIVE_COLS)
    df["date_parsed"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    return df


# Understat team-match sums, already in FPL spelling (the IO layer bridges), keyed like the
# archive on (date, home, away). 2025-26 only for the first three matches; nothing for 2026-27.
UNDERSTAT = [
    ("2025-26", "2025-08-16", "Arsenal", "Spurs",   2.10, 0.45, 1.80, 0.45),
    ("2025-26", "2025-08-23", "Everton", "Arsenal", 0.90, 1.70, 0.90, 1.70),
    ("2025-26", "2025-08-30", "Spurs",   "Everton", 1.60, 1.10, 1.60, 0.35),
]


def _understat():
    df = pd.DataFrame(UNDERSTAT, columns=["season", "date", "home", "away", "xg_home", "xg_away",
                                         "npxg_home", "npxg_away"])
    df["date_parsed"] = pd.to_datetime(df["date"])
    return df


def _fbref():
    """{season: {category: {"for": df, "against": df}}} in FPL spelling, as the CSVs hold."""
    def std(season, poss, games):
        return pd.DataFrame({"season": season, "team": ["Arsenal", "Spurs", "Everton"],
                             "possession": poss, "games": games})
    def misc(season, crosses, pens):
        return pd.DataFrame({"season": season, "team": ["Arsenal", "Spurs", "Everton"],
                             "crosses": crosses, "offsides": [40, 55, 61], "pens_won": pens,
                             "pens_conceded": pens})
    return {
        "2025-26": {"standard": {"for": std("2025-26", [58.1, 52.0, 44.9], [38, 38, 38]),
                                 "against": std("2025-26", [41.9, 48.0, 55.1], [38, 38, 38])},
                    "misc": {"for": misc("2025-26", [600, 540, 480], [""] * 3),
                             "against": misc("2025-26", [420, 500, 610], [""] * 3)}},
        "2026-27": {"standard": {"for": std("2026-27", [61.0, 49.5, 43.0], [4, 4, 4]),
                                 "against": std("2026-27", [39.0, 50.5, 57.0], [4, 4, 4])},
                    "misc": {"for": misc("2026-27", [70, 60, 50], [""] * 3),
                             "against": misc("2026-27", [45, 55, 66], [""] * 3)}},
    }


def _fbref_provenance(seasons=("2025-2026", "2026-2027"), saved_at="2026-09-20T20:17:23+00:00"):
    return {
        "root": {"source": "FBref (fbref.com), MANUAL browser saves by the human -- no request made by code",
                 "seasons_on_disk": list(seasons),
                 "coverage_statement": ("Coverage starts at 2016-17 (stack season key), the first season the "
                                        "vaastav stack holds, because a club name can only be verified ..."),
                 "files_refused": []},
        "seasons": {s: {"season": s, "saved_at": saved_at,
                        "statement": ("SEASON AGGREGATES, NOT PER-MATCH. xG is UNAVAILABLE on these pages "
                                      "(FBref lost its Opta licence in early 2026) ... POSSESSION is sourced "
                                      "from the Standard table's `possession` column ..."),
                        "tables": {"stats_squads_misc_for": {"all_null_columns": ["pens_won", "pens_conceded"]},
                                   "stats_squads_misc_against": {"all_null_columns": ["pens_won", "pens_conceded"]},
                                   "stats_squads_standard_for": {"all_null_columns": []}}}
                    for s in seasons},
    }


RUN = {"run_id": 15, "gw": 5, "season": "2026-27", "finished_at": "2026-09-18 17:21:29+00:00",
       "recovered": False, "git_sha": "abc", "kind": "t10", "slot": None, "knowledge": None}
CUTOFF = "2026-09-12T14:00:00"          # GW4's first kickoff in the synthetic calendar


def _cal():
    rows = []
    for gw, kick in ((1, "2026-08-22T14:00:00Z"), (2, "2026-08-29T14:00:00Z"),
                     (3, "2026-09-05T14:00:00Z"), (4, "2026-09-12T14:00:00Z"), (5, "2026-09-18T19:00:00Z")):
        rows.append(dict(season="2026-27", GW=gw, team="Arsenal", was_home=True, kickoff_time=kick, fixture=gw))
    return pd.DataFrame(rows)


@pytest.fixture()
def mt(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools
    monkeypatch.setattr(model_tools, "_latest_run", lambda gw=None, any_status=False: dict(RUN))
    monkeypatch.setattr(model_tools, "_run_meta", lambda run, config=None: {"run_id": 15, "gw": 5})
    monkeypatch.setattr(model_tools, "_league_calendar", lambda season: _cal())
    monkeypatch.setattr(model_tools, "_ms_archive", lambda seasons: _archive())
    monkeypatch.setattr(model_tools, "_ms_understat", lambda seasons: _understat())
    monkeypatch.setattr(model_tools, "_ms_fbref", lambda seasons: (_fbref(), _fbref_provenance()))
    monkeypatch.setattr(model_tools, "_ms_club_sets", lambda: {
        "2025-26": {"Arsenal", "Spurs", "Everton"}, "2026-27": {"Arsenal", "Spurs", "Everton"}})
    return model_tools


def _stat(out, name):
    return out["stats"][name]


# ------------------------------------------------------------------ the registry

def test_every_registry_stat_resolves_to_exactly_one_source_and_one_grain():
    import match_stats as ms
    seen_sources = set()
    for name, spec in ms.REGISTRY.items():
        assert isinstance(spec.source, (str, type(None))), name
        assert spec.source in (None, "odds_archive", "understat", "fbref"), (name, spec.source)
        assert spec.grain in (None, "per_match", "season_aggregate"), (name, spec.grain)
        assert (spec.source is None) == (spec.grain is None), name
        assert not hasattr(spec, "fallback") and not hasattr(spec, "sources")
        if spec.source:
            seen_sources.add(spec.source)
    assert seen_sources == {"odds_archive", "understat", "fbref"}
    # the spec's table, pinned: one origin per stat
    assert ms.REGISTRY["shots"].source == "odds_archive" and ms.REGISTRY["xg"].source == "understat"
    assert ms.REGISTRY["possession"].source == "fbref" and ms.REGISTRY["possession"].grain == "season_aggregate"
    assert ms.REGISTRY["goals"].grain == "per_match"
    for held_nowhere in ("big_chances", "woodwork", "passing", "aerials"):
        assert ms.REGISTRY[held_nowhere].source is None


def test_an_unknown_stat_is_an_error_naming_the_valid_ones(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["possesion"])
    assert "error" in out and "possesion" in out["error"]
    assert "possession" in out["valid_stats"] and "shots" in out["valid_stats"]
    assert "unknown_stats" in out and out["unknown_stats"] == ["possesion"]


def test_the_tool_accepts_no_query_string(mt):
    import inspect as _i
    sig = _i.signature(mt.get_match_stats)
    assert "sql" not in sig.parameters and "query" not in sig.parameters
    src = _i.getsource(mt.get_match_stats)
    assert "SELECT" not in src and "model_predictions" not in src


# ------------------------------------------------------------------ grain

def test_possession_with_a_form_window_is_a_grain_refusal_with_the_season_figure_labelled(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["possession", "goals"], last_n_matches=5, seasons=2)
    p = _stat(out, "possession")
    assert p["grain"] == "season_aggregate" and p["source"] == "fbref"
    assert p["window"] is None and "season-level" in p["window_refusal"]
    assert "5-match window is not available" in p["window_refusal"]
    assert p["by_season"]["2025-26"]["value"] == 58.1 and p["by_season"]["2026-27"]["value"] == 61.0
    g = _stat(out, "goals")
    assert g["grain"] == "per_match" and g["window"]["matches_counted"] == 5


def test_every_returned_stat_carries_grain_and_coverage(mt):
    out = mt.get_match_stats(team="Arsenal")
    for name, s in out["stats"].items():
        assert s["grain"] in ("per_match", "season_aggregate", None), name
        assert "coverage" in s and "source" in s, name


def test_a_venue_or_opponent_asked_of_a_season_aggregate_is_refused_by_name(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["possession"], venue="home")
    assert "no home/away split" in _stat(out, "possession")["venue_refusal"]
    out = mt.get_match_stats(team="Arsenal", opponent="Spurs", stats=["possession", "goals"], seasons=2)
    assert "head-to-head" in _stat(out, "possession")["opponent_refusal"]
    assert _stat(out, "goals")["window"]["matches_counted"] == 3           # the H2H still answers


def test_the_current_seasons_aggregate_is_flagged_as_including_post_cutoff_matches(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["possession"], seasons=2)
    cur = _stat(out, "possession")["by_season"]["2026-27"]
    assert cur["includes_post_cutoff"] is True and cur["matches_after_cutoff_in_aggregate"] >= 0
    assert "after the cutoff" in cur["statement"]
    past = _stat(out, "possession")["by_season"]["2025-26"]
    assert past["includes_post_cutoff"] is False


# ------------------------------------------------------------------ the as-of rule

def test_knowable_before_is_the_only_date_filter_and_monkeypatching_it_moves_the_output(mt, monkeypatch):
    real = mt.get_match_stats(team="Everton", stats=["goals"], as_of="2026-09-05T14:00:00")
    assert _stat(real, "goals")["window"]["matches_counted"] == 1          # 29 Aug only

    def old_timed_rule(matches, cutoff):
        return ((matches["date_parsed"] < pd.Timestamp(cutoff))
                & matches["home_goals"].notna() & matches["away_goals"].notna())
    monkeypatch.setattr(dc, "knowable_before", old_timed_rule)
    leaky = mt.get_match_stats(team="Everton", stats=["goals"], as_of="2026-09-05T14:00:00")
    assert _stat(leaky, "goals")["window"]["matches_counted"] == 2          # the cutoff-day match leaked in


def test_the_pure_module_contains_no_date_comparison_and_the_tool_calls_the_rule():
    import match_stats as ms
    import model_tools
    src_pure = inspect.getsource(ms)
    for forbidden in ('date_parsed"] <', 'date_parsed"] >', "date_parsed <", "date_parsed >",
                      "< cutoff", "<= cutoff", "> cutoff", ">= cutoff", ".normalize()", "knowable_before("):
        assert forbidden not in src_pure, forbidden
    src_tool = inspect.getsource(model_tools.get_match_stats)
    assert "dc.knowable_before(" in src_tool
    for forbidden in ('date_parsed"] <', 'date_parsed"] >', "< cutoff", "<= cutoff", "> cutoff", ">= cutoff"):
        assert forbidden not in src_tool, forbidden


def test_the_default_cutoff_is_the_runs_gameweek_first_kickoff(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["goals"])
    assert out["as_of"]["cutoff"] == "2026-09-18 19:00:00" and "GW5" in out["as_of"]["source"]
    assert _stat(out, "goals")["window"]["matches_counted"] == 2           # 12 Sep is unplayed


# ------------------------------------------------------------------ the arithmetic

def test_head_to_head_is_hand_checked_against_the_known_results(mt):
    out = mt.get_match_stats(team="Arsenal", opponent="Tottenham", stats=["goals", "shots"], seasons=2, side="both")
    g = _stat(out, "goals")
    # Arsenal v Spurs: 2-0 H (16/8/25), 2-1 A (20/9/25), 3-0 H (22/8/26) -> 3 meetings, 3 wins
    assert g["window"]["matches_counted"] == 3
    assert g["for"]["total"] == 7 and g["against"]["total"] == 1
    assert out["head_to_head"]["record"] == {"won": 3, "drawn": 0, "lost": 0}
    meetings = out["head_to_head"]["meetings"]
    assert [(m["date"], m["venue"], m["score"]) for m in meetings] == [
        ("2026-08-22", "H", "3-0"), ("2025-09-20", "A", "2-1"), ("2025-08-16", "H", "2-0")]
    s = _stat(out, "shots")
    assert s["window"]["matches_counted"] == 2                             # 2026-27 has no shots
    assert s["for"]["total"] == 28 and s["against"]["total"] == 14


def test_zero_meetings_is_a_stated_answer_not_an_empty_one(mt):
    out = mt.get_match_stats(team="Arsenal", opponent="Everton", stats=["goals"], seasons=1,
                             as_of="2026-08-25T00:00:00")
    assert out["head_to_head"]["meetings"] == [] and "no meeting" in out["head_to_head"]["statement"]
    assert _stat(out, "goals")["window"]["matches_counted"] == 0


def test_home_plus_away_sums_to_both_on_every_counter(mt):
    kw = dict(team="Arsenal", stats=["goals", "shots", "corners"], seasons=2, side="both")
    both = mt.get_match_stats(**kw)
    home = mt.get_match_stats(venue="home", **kw)
    away = mt.get_match_stats(venue="away", **kw)
    for name in ("goals", "shots", "corners"):
        for side in ("for", "against"):
            assert _stat(home, name)[side]["total"] + _stat(away, name)[side]["total"] == _stat(both, name)[side]["total"], (name, side)
        assert _stat(home, name)["window"]["matches_counted"] + _stat(away, name)["window"]["matches_counted"] \
            == _stat(both, name)["window"]["matches_counted"]


def test_a_partial_window_reports_matches_counted(mt):
    out = mt.get_match_stats(team="Everton", stats=["goals"], last_n_matches=10, seasons=1)
    w = _stat(out, "goals")["window"]
    assert w["requested"] == 10 and w["matches_counted"] == 2 and w["complete"] is False


def test_side_for_against_both(mt):
    f = mt.get_match_stats(team="Arsenal", stats=["shots"], seasons=2, side="for")
    a = mt.get_match_stats(team="Arsenal", stats=["shots"], seasons=2, side="against")
    b = mt.get_match_stats(team="Arsenal", stats=["shots"], seasons=2, side="both")
    assert "against" not in _stat(f, "shots") and "for" not in _stat(a, "shots")
    # Arsenal's four 2025-26 matches: HS/AS 15/6 (H), 9/14 (A), 20/4 (H), 8/13 (A) -> for 62, against 27
    assert _stat(b, "shots")["for"]["total"] == 62 and _stat(b, "shots")["against"]["total"] == 27


def test_fbref_against_differs_from_for_so_a_wrong_table_join_is_caught(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["possession", "crosses"], seasons=1, side="both")
    p = _stat(out, "possession")["by_season"]["2026-27"]
    assert p["value"] == 61.0 and p["against"] == 39.0
    c = _stat(out, "crosses")["by_season"]["2026-27"]
    assert c["value"] == 70 and c["against"] == 45


def test_xg_comes_from_understat_and_joins_onto_the_filtered_archive_rows(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["xg", "goals"], seasons=2, side="both")
    x = _stat(out, "xg")
    assert x["source"] == "understat" and x["grain"] == "per_match"
    assert x["window"]["matches_counted"] == 2                             # two of Arsenal's matches have xG
    assert abs(x["for"]["total"] - (2.10 + 1.70)) < 1e-9 and abs(x["against"]["total"] - (0.45 + 0.90)) < 1e-9
    assert _stat(out, "goals")["window"]["matches_counted"] == 6           # goals count every played match


# ------------------------------------------------------------------ designed refusals

def test_a_stat_outside_its_measured_season_range_is_a_stated_refusal_not_a_number(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["corners"], seasons=1)   # 2026-27: archive corners all null
    c = _stat(out, "corners")
    assert c["window"]["matches_counted"] == 0 and c["for"]["total"] is None
    assert "2025-26" in c["coverage"]["seasons"] and "2026-27" not in c["coverage"]["seasons"]
    assert "not covered" in c["coverage_note"] and "2026-27" in c["coverage_note"]


def test_pens_won_is_null_with_a_reason_never_zero(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["pens_won"], seasons=1)
    p = _stat(out, "pens_won")["by_season"]["2026-27"]
    assert p["value"] is None and "empty" in p["reason"] and "not zero" in p["reason"]


def test_stats_held_nowhere_are_refused_by_name_not_approximated(mt):
    out = mt.get_match_stats(team="Arsenal", stats=["big_chances", "woodwork", "goals"])
    for name in ("big_chances", "woodwork"):
        s = _stat(out, name)
        assert s["source"] is None and "no source on the volume" in s["refusal"]
        assert "value" not in s and "for" not in s
    assert _stat(out, "goals")["window"]["matches_counted"] == 2


def test_unknown_club_names_the_known_ones_and_aliases_resolve(mt):
    out = mt.get_match_stats(team="Wigan")
    assert "error" in out and "not a club" in out["error"] and "Spurs" in out["known_teams"]
    assert mt.get_match_stats(team="tottenham", stats=["goals"])["team"] == "Spurs"
    assert mt.get_match_stats(team="Arsenal", opponent="spurs", stats=["goals"])["opponent"] == "Spurs"


def test_a_seasons_fpl_spelling_that_is_the_archives_is_bridged_through_the_fits_alias(mt, monkeypatch):
    """Understat says "Ipswich", the map says "Ipswich Town", the 2024-25 stack says "Ipswich":
    dixon_coles.ARCHIVE_NAME_ALIAS closes it per season -- no new map, no unmapped error.
    Found on real data 2026-09-20: the first live run refused every 2024-25 question on it."""
    u = _understat()
    u.loc[0, "home"] = "Ipswich Town"
    u.loc[0, "season"] = "2024-25"
    u.loc[0, "date_parsed"] = pd.Timestamp("2024-08-17")
    arc = _archive()
    arc.loc[len(arc)] = ["2024-25", "17/08/2024", "Ipswich", "Tottenham", 0.0, 2.0] + [5.0] * 12 + [pd.Timestamp("2024-08-17")]
    monkeypatch.setattr(mt, "_ms_understat", lambda seasons: u)
    monkeypatch.setattr(mt, "_ms_archive", lambda seasons: arc)
    monkeypatch.setattr(mt, "_ms_club_sets", lambda: {
        "2024-25": {"Ipswich", "Spurs", "Arsenal", "Everton"}, "2025-26": {"Arsenal", "Spurs", "Everton"},
        "2026-27": {"Arsenal", "Spurs", "Everton"}})
    out = mt.get_match_stats(team="ipswich", stats=["goals", "xg"], seasons=3, side="both")
    assert "error" not in out and out["team"] == "Ipswich"
    assert _stat(out, "goals")["window"]["matches_counted"] == 1
    assert _stat(out, "xg")["window"]["matches_counted"] == 1 and _stat(out, "xg")["for"]["total"] == 2.1


def test_an_unmapped_source_club_fails_loudly(mt, monkeypatch):
    bad = _understat()
    bad.loc[0, "home"] = "Arsenal FC"
    monkeypatch.setattr(mt, "_ms_understat", lambda seasons: bad)
    out = mt.get_match_stats(team="Arsenal", stats=["xg"], seasons=2)
    assert "error" in out and "unmapped" in out["error"].lower() and "Arsenal FC" in out["error"]


# ------------------------------------------------------------------ attribution from provenance

def test_attribution_and_coverage_come_from_the_sidecars_and_flip_with_them(mt, monkeypatch):
    out = mt.get_match_stats(team="Arsenal", stats=["possession"], seasons=1)
    a = out["sources"]["fbref"]
    assert "MANUAL browser" in a["attribution"] and "Coverage starts at 2016-17" in a["coverage_statement"]
    assert "xG is UNAVAILABLE" in a["statement"] and a["seasons_on_disk"] == ["2025-2026", "2026-2027"]
    flipped = _fbref_provenance()
    flipped["root"]["coverage_statement"] = "Coverage starts at 2019-20 (test flip)"
    flipped["root"]["seasons_on_disk"] = ["2026-2027"]
    monkeypatch.setattr(mt, "_ms_fbref", lambda seasons: (_fbref(), flipped))
    out2 = mt.get_match_stats(team="Arsenal", stats=["possession"], seasons=1)
    assert "2019-20 (test flip)" in out2["sources"]["fbref"]["coverage_statement"]
    assert out2["sources"]["fbref"]["seasons_on_disk"] == ["2026-2027"]
    src = inspect.getsource(mt.get_match_stats)
    assert "Coverage starts at 2016-17" not in src, "hardcoded coverage"


def test_no_field_presents_a_price_probability_or_forecast(mt):
    out = mt.get_match_stats(team="Arsenal", opponent="Spurs", seasons=2)
    text = str(out).lower()
    # betting content, not the archive's NAME ("odds archive" is the source's name, not a price)
    for word in ("probability", "implied", "b365", "forecast", "predict", "expected_points",
                 "e_points", "stake", " bet ", "value_bet", "edge"):
        assert word not in text, word
    assert "price" not in text.replace("no price", "")


# ------------------------------------------------------------------ the real FBref folder

def test_zero_unmapped_fbref_names_across_every_season_on_disk():
    import json
    root = REPO / "data" / "fbref"
    assert (root / "provenance.json").exists(), "the FBref export has not been run on this machine"
    from season_stack import load_stack
    df = load_stack(columns=["season", "team"]).dropna()
    clubs = {s: set(g["team"]) for s, g in df.groupby("season")}
    seasons = json.loads((root / "provenance.json").read_text(encoding="utf-8"))["seasons_on_disk"]
    assert len(seasons) == 11
    for season in seasons:
        key = f"{season[:4]}-{season[-2:]}"
        for side in ("for", "against"):
            t = pd.read_csv(root / season / "standard" / f"stats_squads_standard_{side}.csv", encoding="utf-8")
            assert set(t["team"]) <= clubs[key], (season, side, set(t["team"]) - clubs[key])
            assert len(t) == 20


# ------------------------------------------------------------------ surface + prompt

def test_the_agent_entry_point_is_registered_and_dispatches(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent
    names = [t["name"] for t in agent.tools_schema]
    assert "get_match_stats" in names and len(names) == 19
    assert set(names) == set(agent.available_functions)
    fn = agent.available_functions["get_match_stats"]
    assert (fn.__module__, fn.__qualname__) == ("model_tools", "get_match_stats")
    schema = next(t for t in agent.tools_schema if t["name"] == "get_match_stats")
    assert set(schema["input_schema"]["properties"]) == {"team", "opponent", "stats", "seasons",
                                                         "last_n_matches", "venue", "side", "as_of"}
    assert schema["input_schema"]["required"] == ["team"]
    monkeypatch.setitem(agent.available_functions, "get_match_stats", lambda **k: {"ok": True, "got": k})
    assert agent.call_tool("get_match_stats", {"team": "Liverpool", "stats": ["possession"]}) == \
        {"ok": True, "got": {"team": "Liverpool", "stats": ["possession"]}}


def test_the_prompt_puts_match_stats_in_scope_and_keeps_the_betting_line(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent
    p = agent.SYSTEM_PROMPT
    assert "get_match_stats" in p and "# 2d." in p
    assert "I don't give betting advice or assess bets" in p
    assert "combined" not in p.lower()
    scope = p.split("# 6. Scope")[1].split("# 7.")[0]
    assert "match stats" in scope.lower() or "team stats" in scope.lower()
    assert "season aggregate" in p.lower() or "season-level" in p.lower()
