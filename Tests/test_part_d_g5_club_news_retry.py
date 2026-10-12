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


# ================================================================ G5
class _DatedEmpty:
    """A Tavily that returns nothing for a dated search on arsenal.com and results without dates."""
    def __init__(self):
        self.requests = []

    def search(self, query, domain, start_date=None, end_date=None):
        self.requests.append(cn.search_request(query, [domain], start_date, end_date))
        if domain == "arsenal.com" and start_date:
            return {"results": []}
        return {"results": [{"url": f"https://www.{domain}/news/team-news-x", "title": "Team news", "content": "x", "score": 0.5}]}

    def extract(self, urls):
        return {"results": [], "failed_results": list(urls)}


def test_a_dated_search_with_no_results_is_retried_once_without_dates_and_others_are_untouched():
    tv = _DatedEmpty()
    plan = cn.search_plan(tv, "Arsenal team news injury update", "arsenal.com", "2026-10-13", "2026-10-14")
    assert [(r.get("start_date"), r.get("end_date")) for r in tv.requests] == [("2026-10-13", "2026-10-14"), (None, None)]
    assert plan["retried_without_dates"] is True and plan["credits"] == 2 and len(plan["results"]) == 1
    tv2 = _DatedEmpty()
    plan2 = cn.search_plan(tv2, "Chelsea team news injury update", "chelseafc.com", "2026-10-13", "2026-10-14")
    assert len(tv2.requests) == 1 and plan2["retried_without_dates"] is False and plan2["credits"] == 1
    assert cn.planned_credits(9) == 9 * cn.SEARCH_CREDITS * 2 + cn.extract_credits(cn.MAX_RESULTS * 9)   # the guard plans for the retries
