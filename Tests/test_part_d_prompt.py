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


# ================================================================ G1 / G3 (prompt)
def test_the_prompt_states_rule_precedence_over_availability():
    assert "A squad rule outranks availability" in PROMPT
    assert "name the broken rule in your first sentence" in PROMPT
    assert "still call the squad build" in PROMPT


JARGON = re.compile(r"\b(ingest(?:ed|ion|s)?|post-ingest|horizon|cutoff|solve[sd]?|solver|optimi[sz]er|frame)\b|\bthe run\b|\brun's\b", re.I)


def test_the_prompts_own_prose_carries_no_pipeline_words_outside_backticks():
    prose = re.sub(r"`[^`]*`", "", PROMPT)                                   # field names and tool names are references
    exempt = ("say it in plain words", "Never mention tool names")             # the two lines that list the words to avoid
    hits = [(i + 1, JARGON.search(l).group(0)) for i, l in enumerate(prose.splitlines()) if JARGON.search(l) and not any(x in l for x in exempt)]
    assert hits == [], hits


def test_a_stored_promise_with_the_old_wording_is_said_in_todays_words():
    import dispatch_policy as dp
    import now_context as nc
    legacy = {"kind": "post_ingest", "at": None, "condition": "GW6 confirmed by FPL and ingested (ticks 00:17/06:17/12:17/18:17Z)"}
    assert nc.next_run_words(legacy) == "once GW6 confirmed by FPL and loaded (checked at 00:17/06:17/12:17/18:17Z)"
    run = {"run_id": 5, "gw": 7, "kind": "t10", "finished_at": "2026-10-10T09:51:00+00:00", "knowledge": None}
    assert dp.freshness(run, legacy).endswith("next update once GW6 confirmed by FPL and loaded (checked at 00:17/06:17/12:17/18:17Z)")
    assert dp.plain_condition(None) is None


def test_the_prompt_forbids_invented_reasons_for_a_squad_and_reads_scores_as_tenths():
    assert "says nothing about why they were chosen" in PROMPT and "never \"the easiest\", \"the hardest\" or \"the easiest possible\"" in PROMPT
    assert "Weekdays come from the tool's `kickoff_day`" in PROMPT
