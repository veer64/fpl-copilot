"""Part D agent fixes (2026-10-12), locks at the source, failing test first:

  G2 get_actual_points lists only the events that scored, each with its points -- a forward's clean sheet is
     never a scoring event (production smoke q6 credited Haaland with one).
  G4 the fields the agent misread get plain names / meanings: get_my_xi says who the RECORDED captain and vice
     are; get_fixtures marks every fixture played / in progress / to come against the clock, says what a score
     of 10 or 1 means (a tenth, not the single easiest / hardest), and which gameweeks are listed vs covered.
  G5 a dated club-news search that returns nothing is retried once without dates (the date filter, not the
     query, returned 0 for arsenal.com and cpfc.co.uk on 8-9 Oct); the other clubs' requests are unchanged.
  G1 / G3 the prompt: rule precedence over availability; no pipeline words in the prompt's own prose.
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import actuals_tool                                        # noqa: E402
import club_news as cn                                     # noqa: E402
import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402

UTC = timezone.utc
PROMPT = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")


# ================================================================ G2
def _week(**kw):
    base = {"gw": 4, "n_fixtures": 1, "total_points": 0, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0,
            "goals_conceded": 0, "own_goals": 0, "penalties_saved": 0, "penalties_missed": 0, "yellow_cards": 0, "red_cards": 0,
            "saves": 0, "bonus": 0, "bps": 0, "starts": 1, "defensive_contribution": 0, "fixtures": [31]}
    base.update(kw)
    return base


def test_a_forwards_clean_sheet_is_never_a_scoring_event():
    w = _week(total_points=9, goals_scored=1, clean_sheets=1, bonus=3)
    ev = actuals_tool.scoring_events(w, "FWD")
    names = [e["event"] for e in ev["events"]]
    assert "clean sheet" not in " ".join(names)
    assert ev["events"] == [{"event": "played 60+ minutes", "points": 2}, {"event": "1 goal", "points": 4}, {"event": "bonus", "points": 3}]
    assert ev["events_total"] == 9 and ev["unexplained_points"] == 0
    assert "clean sheet kept but" in ev["note"] and "no clean-sheet points" in ev["note"]


def test_defender_and_midfielder_clean_sheets_score_and_a_goalkeepers_saves_count():
    d = actuals_tool.scoring_events(_week(total_points=12, clean_sheets=1, goals_scored=1, goals_conceded=0), "DEF")
    assert {"event": "clean sheet", "points": 4} in d["events"] and {"event": "1 goal", "points": 6} in d["events"] and d["unexplained_points"] == 0
    m = actuals_tool.scoring_events(_week(total_points=3, clean_sheets=1), "MID")
    assert {"event": "clean sheet", "points": 1} in m["events"] and m["unexplained_points"] == 0
    g = actuals_tool.scoring_events(_week(total_points=4, clean_sheets=0, goals_conceded=2, saves=6), "GK")
    assert {"event": "6 saves", "points": 2} in g["events"] and {"event": "2 goals conceded", "points": -1} in g["events"] and g["unexplained_points"] == 1
    assert "1 point" in g["note"] and "not explained" in g["note"]


def test_cards_pens_own_goals_and_a_short_appearance():
    w = _week(total_points=-5, minutes=30, yellow_cards=1, red_cards=1, own_goals=1, penalties_missed=0)
    ev = actuals_tool.scoring_events(w, "MID")
    assert ev["events"] == [{"event": "played 1-59 minutes", "points": 1}, {"event": "own goal", "points": -2},
                            {"event": "yellow card", "points": -1}, {"event": "red card", "points": -3}]
    assert ev["events_total"] == -5 and ev["unexplained_points"] == 0
    assert actuals_tool.scoring_events(_week(total_points=0, minutes=0), "FWD")["events"] == []


def test_get_actual_points_carries_the_scoring_events(monkeypatch):
    week = _week(total_points=9, goals_scored=1, clean_sheets=1, bonus=3)
    monkeypatch.setattr(mt, "_player_name", lambda e: "Erling Haaland")
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {411: {"name": "Erling Haaland", "position": "FWD", "team": "Man City"}})
    monkeypatch.setattr(mt, "_actuals_master", lambda: (pd.DataFrame({"element": [411], "GW": [4]}), {}))
    monkeypatch.setattr(actuals_tool, "gws_held", lambda m: [1, 2, 3, 4])
    monkeypatch.setattr(actuals_tool, "player_gameweek", lambda m, e, g: dict(week))
    monkeypatch.setattr(actuals_tool, "provisional_for", lambda prov, g: (False, "2026-10-01"))
    monkeypatch.setattr(mt, "_prediction_before", lambda e, g: None)
    monkeypatch.setattr(mt, "_season_label", lambda: "2026-27")
    out = mt.get_actual_points(411, gw=4)
    assert out["position"] == "FWD" and out["scoring_events"] == [{"event": "played 60+ minutes", "points": 2}, {"event": "1 goal", "points": 4}, {"event": "bonus", "points": 3}]
    assert "clean sheet" not in " ".join(e["event"] for e in out["scoring_events"])
    assert out["events_note"].startswith("scoring_events lists only what scored")
