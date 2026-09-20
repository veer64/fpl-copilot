"""fill_e0_stats -- fill the live season's stat columns from football-data's E0 file.

Join, don't append; fill only nulls; never a score, a date or an odds column; stop on any
disagreement. No network: the E0 frame and the archive are synthetic.
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

import fill_e0_stats as fe                                 # noqa: E402
import team_map                                            # noqa: E402

NAT = float("nan")
SEASON = "2026-27"


def _archive():
    """The combined frame's shape: an archive-season row plus four live rows -- three with a
    result (one E0 will lag), one unplayed. Live rows: E0 spellings where they round-trip
    (Man United, Tottenham), FPL names for the promoted (Hull City), as fetch_fixtures writes."""
    rows = [
        # season, Date, Home, Away, FTHG, FTAG, HS, AS, HC, AC, HTHG, HTAG, HTR, Referee, B365H, B365D, B365A
        ("2025-26", "17/05/2026", "Arsenal", "Chelsea", 1.0, 0.0, 9.0, 4.0, 5.0, 2.0, 0.0, 0.0, "D", "A Ref", 1.9, 3.5, 4.0),
        (SEASON, "22/08/2026", "Hull City", "Man United", 2.0, 0.0, NAT, NAT, NAT, NAT, NAT, NAT, None, None, 2.1, 3.4, 3.5),
        (SEASON, "22/08/2026", "Arsenal", "Tottenham", 3.0, 0.0, NAT, NAT, NAT, NAT, NAT, NAT, None, None, 1.5, 4.2, 6.0),
        (SEASON, "29/08/2026", "Chelsea", "Hull City", 1.0, 1.0, NAT, NAT, NAT, NAT, NAT, NAT, None, None, 1.3, 5.0, 9.0),
        (SEASON, "05/09/2026", "Tottenham", "Chelsea", NAT, NAT, NAT, NAT, NAT, NAT, NAT, NAT, None, None, 2.4, 3.3, 3.0),
    ]
    cols = ["season", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HS", "AS", "HC", "AC",
            "HTHG", "HTAG", "HTR", "Referee", "B365H", "B365D", "B365A"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("HST", "AST", "HF", "AF", "HY", "AY", "HR", "AR"):
        df[c] = NAT
    return df


def _e0(rows=None):
    """The E0 file's shape for the same matches, E0 spellings throughout ("Hull")."""
    rows = rows if rows is not None else [
        ("22/08/2026", "Hull", "Man United", 2, 0, 11, 6, 5, 3, 1, 0, "H", "M Oliver", 2.2, 3.4, 3.4, 1.1, 1.3),
        ("22/08/2026", "Arsenal", "Tottenham", 3, 0, 15, 4, 7, 1, 2, 0, "H", "A Taylor", 1.55, 4.0, 6.0, 2.4, 0.5),
        ("05/09/2026", "Tottenham", "Chelsea", 2, 2, 12, 12, 4, 4, 1, 1, "D", "J Brooks", 2.5, 3.3, 2.9, 1.4, 1.5),
    ]
    cols = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HS", "AS", "HC", "AC", "HTHG", "HTAG",
            "HTR", "Referee", "B365H", "B365D", "B365A", "HxG", "AxG"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("HST", "AST", "HF", "AF", "HY", "AY", "HR", "AR"):
        df[c] = 1
    df["date_parsed"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    return df


# ------------------------------------------------------------------ the fill

def test_fills_only_null_stat_columns_on_matched_rows_with_an_agreed_result():
    arc = _archive()
    out, rep = fe.plan_fill(arc, _e0(), SEASON)
    hull = out[(out["HomeTeam"] == "Hull City") & (out["Date"] == "22/08/2026")].iloc[0]
    assert (hull["HS"], hull["AS"], hull["HC"], hull["AC"]) == (11.0, 6.0, 5.0, 3.0)
    assert hull["HTR"] == "H" and hull["Referee"] == "M Oliver" and hull["HTHG"] == 1.0
    assert rep["filled_per_column"]["HS"] == 2 and rep["filled_per_column"]["Referee"] == 2
    assert rep["joined"] == 3 and rep["joined_with_agreed_result"] == 2
    assert rep["unmapped_names"] == 0 and rep["score_disagreements"] == 0
    assert rep["cells_filled"] == 2 * len(fe.FILL_COLS)


def test_never_touches_scores_dates_or_any_odds_column():
    arc = _archive()
    out, _ = fe.plan_fill(arc, _e0(), SEASON)
    other = [c for c in arc.columns if c not in fe.FILL_COLS]
    assert out[other].equals(arc[other])
    # the E0 file's Bet365 prices differ from the archive's consensus prices and must NOT land
    assert out.loc[1, "B365H"] == 2.1 and out.loc[2, "B365H"] == 1.5
    assert "HxG" not in out.columns and "AxG" not in out.columns
    assert set(out.columns) == set(arc.columns) and len(out) == len(arc)


def test_the_archive_season_row_is_untouched():
    arc = _archive()
    out, _ = fe.plan_fill(arc, _e0(), SEASON)
    assert out.iloc[0].equals(arc.iloc[0])


def test_e0_ahead_of_the_archive_is_counted_and_not_filled():
    """The 5 Sep match has an E0 result but no archive result yet (ingest lag): stats would
    describe a match the archive thinks is unplayed. Skipped and counted, filled next run."""
    arc = _archive()
    out, rep = fe.plan_fill(arc, _e0(), SEASON)
    row = out[(out["HomeTeam"] == "Tottenham") & (out["Date"] == "05/09/2026")].iloc[0]
    assert pd.isna(row["HS"]) and pd.isna(row["FTHG"])
    assert rep["e0_ahead_of_archive"] == 1


def test_archive_ahead_of_e0_is_the_lag_reported_not_an_error():
    """The 29 Aug match has an archive result and no E0 row: their file lags by days."""
    arc = _archive()
    _, rep = fe.plan_fill(arc, _e0(), SEASON)
    assert rep["archive_ahead_of_e0"] == 1


def test_second_run_fills_nothing_and_changes_nothing():
    arc = _archive()
    once, rep1 = fe.plan_fill(arc, _e0(), SEASON)
    twice, rep2 = fe.plan_fill(once, _e0(), SEASON)
    assert rep1["cells_filled"] > 0 and rep2["cells_filled"] == 0
    assert twice.equals(once)


def test_an_existing_stat_value_is_never_overwritten():
    arc = _archive()
    arc.loc[1, "HS"] = 99.0                                   # already held; E0 says 11
    out, rep = fe.plan_fill(arc, _e0(), SEASON)
    assert out.loc[1, "HS"] == 99.0 and rep["filled_per_column"]["HS"] == 1


# ------------------------------------------------------------------ designed stops

def test_a_score_disagreement_stops_the_run():
    e0 = _e0()
    e0.loc[0, "FTAG"] = 1                                      # archive says 2-0
    with pytest.raises(fe.E0FillError) as ei:
        fe.plan_fill(_archive(), e0, SEASON)
    assert "DISAGREE" in str(ei.value) and "Hull City" in str(ei.value)


def test_an_unmapped_club_stops_the_run():
    e0 = _e0()
    e0.loc[0, "HomeTeam"] = "Hull Kingston Rovers"
    with pytest.raises(fe.E0FillError) as ei:
        fe.plan_fill(_archive(), e0, SEASON)
    assert "map to no" in str(ei.value)


def test_an_e0_match_with_no_archive_row_stops_the_run():
    e0 = _e0()
    e0.loc[0, "Date"] = "23/08/2026"                          # rescheduled in one source only
    e0["date_parsed"] = pd.to_datetime(e0["Date"], format="mixed", dayfirst=True)
    with pytest.raises(fe.E0FillError) as ei:
        fe.plan_fill(_archive(), e0, SEASON)
    assert "NO archive row" in str(ei.value)


def test_a_missing_season_stops_the_run():
    with pytest.raises(fe.E0FillError):
        fe.plan_fill(_archive(), _e0(), "2031-32")


# ------------------------------------------------------------------ names, dates, discovery

def test_names_go_through_team_map_and_the_promoted_alias_is_the_inverse_of_the_fits():
    import dixon_coles as dc
    src = inspect.getsource(fe)
    assert "from team_map import TEAM_MAP, e0_to_fpl" in src
    assert "TEAM_MAP = {" not in src, "a copy of the map"
    for fpl, e0 in dc.ARCHIVE_NAME_ALIAS.items():
        assert team_map.E0_PROMOTED_ALIAS[e0] == fpl, (e0, fpl)
    assert team_map.e0_to_fpl("Hull") == "Hull City" and team_map.e0_to_fpl("Coventry") == "Coventry City"
    assert team_map.e0_to_fpl("Man United") == "Man Utd" and team_map.e0_to_fpl("Arsenal") == "Arsenal"


def test_dates_are_parsed_with_the_fits_own_convention():
    import dixon_coles as dc
    convention = 'format="mixed", dayfirst=True'
    assert convention in inspect.getsource(dc._load_matches)
    assert convention in inspect.getsource(fe.parse_e0) and convention in inspect.getsource(fe.plan_fill)


def test_the_premier_league_href_is_read_under_the_seasons_heading_never_constructed():
    html = ('<h2>Season 2026/2027</h2><a href="mmz4281/2627/E0.csv">Premier League</a>'
            '<a href="mmz4281/2627/E1.csv">Championship</a>'
            '<h2>Season 2025/2026</h2><a href="mmz4281/2526/E0.csv">Premier League</a>')
    assert fe.find_premier_league_href(html, "2026-27") == "mmz4281/2627/E0.csv"
    assert fe.find_premier_league_href(html, "2025-26") == "mmz4281/2526/E0.csv"
    with pytest.raises(fe.E0FillError):
        fe.find_premier_league_href(html, "2027-28")
    with pytest.raises(fe.E0FillError):
        fe.find_premier_league_href('<h2>Season 2026/2027</h2><a href="x">Championship</a>', "2026-27")
    src = inspect.getsource(fe)
    assert "mmz4281" not in src, "the CSV path must come from the page, not the source"


def test_parse_e0_reads_a_bom_csv_and_drops_trailing_blank_rows():
    raw = ("﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
           "E0,21/08/2026,20:00,Arsenal,Coventry,3,0\n"
           ",,,,,,\n").encode("utf-8")
    df = fe.parse_e0(raw)
    assert len(df) == 1 and df.loc[0, "date_parsed"] == pd.Timestamp("2026-08-21")
    assert list(df.columns)[0] == "Div"


def test_fill_cols_hold_no_score_date_or_odds_column():
    for c in fe.FILL_COLS:
        assert c not in ("FTHG", "FTAG", "FTR", "Date", "Time", "Div", "HomeTeam", "AwayTeam", "season")
        assert not c.startswith("B365") and "H" != c and ">" not in c and "<" not in c
    assert set(fe.FILL_COLS) == {"HTHG", "HTAG", "HTR", "Referee", "HS", "AS", "HST", "AST",
                                 "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"}


def test_a_blocked_or_throttled_response_stops_without_retrying(monkeypatch):
    calls = []

    class R:
        status_code = 429
        text = ""
        content = b""
        headers = {}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return R()
    monkeypatch.setattr(fe.requests, "get", fake_get)
    with pytest.raises(fe.E0FillError) as ei:
        fe.fetch_e0("2026-27", log=lambda *a: None)
    assert "429" in str(ei.value) and len(calls) == 1
