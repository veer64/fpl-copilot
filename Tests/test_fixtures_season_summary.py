"""The four features of 2026-10-08: past picks on get_picks (4a), get_prediction_history (4b),
get_wildcard_gap (4c) and get_fixtures' season summary of doubles and blanks (4d).

4a: get_picks with a played gameweek used to be told "already played" and sent elsewhere; now it
answers with the stored fifteen of the last run before that deadline and scores it through the
one scorer (scoring.score_gameweek on the stored actuals). 4b: one query over the stored runs,
oldest to newest, so "what changed overnight" never needs a run id. 4c: the same decayed-horizon
MIP propose_transfers runs, with its wildcard relief, against the current squad's best XI each
gameweek. 4d: the calendar already held every double and blank; the tool now says so for a club.

Pure except 4c, which runs one real small MIP on a synthetic horizon frame (~2 s). The IO helpers
are monkeypatched; nothing reads the database, the volume or the network.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402

UTC = timezone.utc


# ---------------------------------------------------------------- 4d
def test_a_clubs_doubles_and_blanks_are_summarised_from_the_loaded_calendar(monkeypatch):
    rows = [(1, 6, "Newcastle", 7, True, "2026-10-10T14:00:00Z"),
            (1, 6, "Newcastle", 9, False, "2026-10-13T19:00:00Z"),       # a double in GW6
            (2, 6, "Coventry City", 14, False, "2026-10-10T14:00:00Z"),
            (1, 8, "Newcastle", 3, False, "2026-10-24T14:00:00Z"),       # GW7 blank for Newcastle
            (2, 7, "Coventry City", 3, True, "2026-10-17T14:00:00Z"),
            (2, 8, "Coventry City", 9, True, "2026-10-24T14:00:00Z")]
    skel = pd.DataFrame(rows, columns=ft.SKELETON_COLS)
    monkeypatch.setattr(ft, "_team_names", lambda: {7: "Coventry City", 14: "Newcastle", 3: "Arsenal", 9: "Leeds"})
    cal, n = ft.calendar(df=skel)
    out = ft.build([{"team": "Newcastle", "gw": 6, "team_lambda": 1.5, "opp_lambda": 1.0, "p_cs": 0.3, "horizon_step": 0,
                     "odds_horizon_gws": 1, "n_fixtures": 2}], cal, n, team="Newcastle", gw=6)
    s = out["season_summary"]
    assert s["team"] == "Newcastle" and s["calendar_covers"] == [6, 8]
    assert s["double_gameweeks"] == [6] and s["blank_gameweeks"] == [7]
    assert "confirmed later in the season" in s["note"]
    cov = ft.build([], cal, n, team="Coventry City", gw=6)["season_summary"]
    assert cov["double_gameweeks"] == [] and cov["blank_gameweeks"] == []
    assert ft.build([], cal, n, gw=6).get("season_summary") is None           # no club asked for


def test_the_get_fixtures_description_mentions_the_season_summary():
    import agent
    gf = next(t for t in agent.tools_schema if t["name"] == "get_fixtures")
    assert "double" in gf["description"].lower() and "blank" in gf["description"].lower()


