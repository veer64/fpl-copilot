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


# ================================================================ G4 (tool sources)
def test_get_my_xi_names_the_recorded_captain_and_vice():
    doc = [{"element": 411, "name": "Erling Haaland", "role": "CAPTAIN", "bench_order": None},
           {"element": 379, "name": "Alexander Isak", "role": "VICE", "bench_order": None},
           {"element": 1, "name": "A", "role": "start", "bench_order": None}]
    r = mt._recorded_armband(doc)
    assert r == {"recorded_captain": "Erling Haaland", "recorded_vice": "Alexander Isak"}
    import inspect
    assert "_recorded_armband(doc" in inspect.getsource(mt.get_my_xi)


def _cal():
    k1, k2, k3 = datetime(2026, 10, 11, 15, 30, tzinfo=UTC), datetime(2026, 10, 12, 19, 0, tzinfo=UTC), datetime(2026, 10, 17, 14, 0, tzinfo=UTC)
    return {("Liverpool", 6): [{"opponent": "Man City", "home": True, "kickoff": k1.isoformat()}],
            ("Liverpool", 7): [{"opponent": "Brentford", "home": False, "kickoff": k3.isoformat()}],
            ("Spurs", 6): [{"opponent": "Fulham", "home": True, "kickoff": k2.isoformat()}]}


def test_fixtures_carry_a_status_against_the_clock_and_plain_score_meanings():
    cal = _cal()
    rows = [{"team": "Liverpool", "gw": 6, "team_lambda": 1.8, "opp_lambda": 1.1, "horizon_step": 0},
            {"team": "Liverpool", "gw": 7, "team_lambda": 1.6, "opp_lambda": 1.0, "horizon_step": 1},
            {"team": "Spurs", "gw": 6, "team_lambda": 1.2, "opp_lambda": 1.3, "horizon_step": 0}]
    now = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
    out = ft.build(rows, cal, 20, team="Liverpool", horizon=2, now=now)
    fx = {e["gw"]: e for e in out["fixtures"]}
    assert fx[6]["fixtures"][0]["status"] == "played" and fx[7]["fixtures"][0]["status"] == "to come"
    out2 = ft.build(rows, cal, 20, team="Spurs", gw=6, now=now)
    assert out2["fixtures"][0]["fixtures"][0]["status"] == "in progress"          # kicked off 60 min ago
    assert out["model_horizon"]["gameweeks_covered"] == [6, 7] and out["listed_gameweeks"] == [6, 7]
    assert "a score of 10 is not 'the easiest fixture'" in out["score_meaning"] and "k-th tenth" in out["score_meaning"]
    assert "status" in out["meanings"] and "to come" in out["meanings"]["status"]
    out3 = ft.build(rows, cal, 20, team="Liverpool", horizon=2)                   # no clock: no status claimed
    assert "status" not in out3["fixtures"][0]["fixtures"][0]
    assert fx[6]["fixtures"][0]["kickoff_day"] == "Sunday 11 Oct 2026, 15:30 UTC"      # the weekday comes from the tool
    assert ft.kickoff_day("2026-10-17T14:00:00Z") == "Saturday 17 Oct 2026, 14:00 UTC" and ft.kickoff_day(None) is None
