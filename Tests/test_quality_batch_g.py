"""Prompt G quality batch (2026-10-29; eval/reports/quality_batch_v1.md).

Part 1  weekdays in every date a tool hands the model: ONE formatter (datewords.when_words / day_words, "Fri 23 Oct 2026
        17:21 UTC" / "Fri 23 Oct 2026"), the weekday checked against the calendar; the ISO fields code reads stay.
Part 2  (the vague-question lock) was REVERTED after two red gate attempts (eval/reports/quality_batch_v1.md, R3): its tests
        went with it; agent.py is production's.
Part 3  the preview-from-memory nudge on get_my_squad and get_my_xi: one line, pinned.
Pure: the squad read, the frame and the solve are monkeypatched as in test_lineup_followup; no database, no network."""
import calendar
import inspect
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import datewords as dw                                      # noqa: E402
import fixtures_tool as ft                                  # noqa: E402
import model_tools as mt                                    # noqa: E402
import news_search as nsr                                   # noqa: E402
import squad_store                                          # noqa: E402
from test_squad_store import legal_doc, _row                # noqa: E402

UTC = timezone.utc
NUDGE = "To change the squad, call set_my_squad with confirm=false; only its preview can be confirmed."


# ---------------------------------------------------------------- Part 1: the one formatter
def test_when_words_and_day_words_carry_the_calendar_weekday():
    t = datetime(2026, 10, 23, 17, 21, 5, tzinfo=UTC)
    assert dw.when_words(t) == "Fri 23 Oct 2026 17:21 UTC"
    assert dw.day_words(t) == "Fri 23 Oct 2026"
    assert calendar.day_abbr[t.weekday()] == "Fri"
    # a single-digit day is not zero-padded; the year is always there
    assert dw.day_words(date(2026, 11, 1)) == "Sun 1 Nov 2026"
    assert dw.when_words("2026-10-25T14:30:00Z") == "Sun 25 Oct 2026 14:30 UTC"
    assert dw.when_words("2026-10-23 17:21:24.538259+00:00") == "Fri 23 Oct 2026 17:21 UTC"
    assert dw.when_words(pd.Timestamp("2026-10-10T09:51:00")) == "Sat 10 Oct 2026 09:51 UTC"


def test_the_weekday_matches_the_calendar_on_every_day_of_a_year():
    d = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for _ in range(365):
        words = dw.when_words(d)
        assert words.split()[0] == calendar.day_abbr[d.weekday()], words
        assert words.endswith(f"{d.day} {d:%b %Y} {d:%H:%M} UTC")
        d += timedelta(days=1)


def test_the_formatter_reads_every_input_shape_and_never_raises():
    naive = datetime(2026, 10, 23, 17, 21)                          # naive = UTC by the project's rule
    assert dw.when_words(naive) == "Fri 23 Oct 2026 17:21 UTC"
    assert dw.when_words(datetime(2026, 10, 23, 19, 21, tzinfo=timezone(timedelta(hours=2)))) == "Fri 23 Oct 2026 17:21 UTC"
    assert dw.when_words(None) is None and dw.day_words(None) is None
    assert dw.when_words("not a date") is None and dw.when_words("") is None and dw.when_words(0) is None


# ---------------------------------------------------------------- Part 1: the sites
def test_as_of_words_and_the_flag_sentences_carry_the_weekday():
    assert mt._as_of_words("2026-09-29T14:00:00+00:00") == "Tue 29 Sep 2026"
    assert mt.chance_words(75, "2026-09-29T14:00:00+00:00", 6) == "chance of playing in GW6: 75%, FPL as of Tue 29 Sep 2026"
    assert mt.latest_flag_words(75, "2026-10-15T09:51:00Z", 7) == "latest FPL flag (for GW7, as of Thu 15 Oct 2026): chance of playing 75%"
    words = mt.flag_dates_words("2026-10-13T18:32:17+00:00", "2026-10-17T09:51:00Z", True, gw=7)
    assert "Tue 13 Oct 2026" in words and "Sat 17 Oct 2026" in words


def test_fixture_kickoffs_use_the_formatter():
    assert ft.kickoff_day("2026-10-11T15:30:00Z") == "Sun 11 Oct 2026 15:30 UTC"
    assert ft.kickoff_day("2026-10-17T14:00:00Z") == "Sat 17 Oct 2026 14:00 UTC"
    assert ft.kickoff_day(None) is None


def test_news_results_carry_the_date_words_beside_the_iso_date():
    row = {"id": 914, "source": "club", "club": "Arsenal", "headline": "Team news", "url": "https://x", "published_at": datetime(2026, 10, 27, 9, 0, tzinfo=UTC),
           "fetched_at": datetime(2026, 10, 27, 15, 7, tzinfo=UTC), "date_source": "page", "players": ["Saka"], "player_ids": [1], "chunk_text": "t"}
    r = nsr._result(row, datetime(2026, 10, 28, 12, 0, tzinfo=UTC), True)
    assert r["date"] == "2026-10-27"                                  # the ISO field code reads (the Sources line) stays
    assert r["date_words"] == "Tue 27 Oct 2026"


def test_the_frame_fields_say_when_the_predictions_were_built_even_without_a_run_record(monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    monkeypatch.setattr(mt, "_next_run", lambda: {"expected": None, "words": None, "deadline_day_runs": None})
    built = pd.Timestamp("2026-10-23T17:21:00")
    out = mt._frame_fields(8, built)
    assert out["frame_built_at"] == str(built)                       # the ISO field stays
    assert out["frame_built"] == "Fri 23 Oct 2026 17:21 UTC"
    assert out["built"] is not None and "Fri 23 Oct 2026 17:21 UTC" in out["built"]
    assert mt.KEY_MEANINGS["frame_built"]


def test_the_frame_fields_keep_the_run_sentence_when_a_run_exists(monkeypatch):
    monkeypatch.setattr(mt, "_frame_built", lambda c: {"built": "built Fri 23 Oct 17:21Z (deadline)", "run_id": 7})
    out = mt._frame_fields(8, pd.Timestamp("2026-10-23T17:21:00"))
    assert out["built"] == "built Fri 23 Oct 17:21Z (deadline)" and out["run_id"] == 7
    assert out["frame_built"] == "Fri 23 Oct 2026 17:21 UTC"


def test_stale_note_and_the_squad_record_carry_the_weekday(monkeypatch):
    monkeypatch.setattr(mt, "_next_deadline", lambda: None)
    note = mt._stale_note(8, 7, pd.Timestamp("2026-10-23T17:21:00"))
    assert "built Fri 23 Oct 2026 17:21 UTC" in note
    rec = _row(legal_doc(), version_id=2, gw=6, user_id=9001)
    rec["created_at"] = datetime(2026, 9, 18, 16, 21, 45, tzinfo=UTC)
    out = squad_store.summary(rec, {})
    assert out["created_at"] == str(rec["created_at"])
    assert out["created_at_words"] == "Fri 18 Sep 2026 16:21 UTC"
    assert out["roles"]["recorded_at_words"] == "Fri 18 Sep 2026 16:21 UTC"
    stale = squad_store.roles_status(rec, {"run_id": 9, "gw": 7, "finished_at": datetime(2026, 10, 23, 17, 21, tzinfo=UTC)})
    assert stale["status"] == "STALE" and "Fri 18 Sep 2026 16:21 UTC" in stale["warning"] and "Fri 23 Oct 2026 17:21 UTC" in stale["warning"]
    assert stale["latest_run"]["built_at_words"] == "Fri 23 Oct 2026 17:21 UTC"


def test_points_and_prices_and_league_dates_go_through_the_formatter():
    assert mt._fetched_words("2026-10-27T11:02:01+00:00") == "Tue 27 Oct 2026 11:02 UTC"
    import prices_tool as pt
    assert pt.observed_words("2026-09-12T10:00:00Z") == "Sat 12 Sep 2026 10:00 UTC"
    src = inspect.getsource(mt)
    for site in ("fetched_at_words", "cutoff_words", "priced_from_words", "preview_expires_words", "observed_from_words"):
        assert site in src or site in inspect.getsource(pt), site


# ---------------------------------------------------------------- Part 3: the preview-from-memory nudge
def _team(doc):
    rows = []
    for p in doc["players"]:
        rows.append({"element": p["element"], "name": p["name"], "position": p["position"], "team": p["team"],
                     "value": p["purchase_price"], "e_points": 2.0 + p["element"] / 10, "role": p["role"],
                     "bench_order": (p["bench_order"] - 1) if p["role"] == "bench" else float("nan"), "p_play_any": 0.9})
    return pd.DataFrame(rows)


@pytest.fixture
def xi_env(monkeypatch):
    doc = legal_doc()
    record = _row(doc, version_id=2, gw=6, user_id=9001)
    team = _team(doc)
    monkeypatch.setattr(mt.squad_store, "read_active", lambda user_id=None, conn=None: record)
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "_load_pool", lambda gw=None: (pd.DataFrame(), 6, pd.Timestamp("2026-10-10T09:51:00")))
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [{"element": p["element"], "price_tenths": p["purchase_price"]} for p in doc["players"]])
    monkeypatch.setattr(mt.squad_store, "xi_over_fifteen", lambda pool, state, prices: (team, []))
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: {"run_id": 37, "gw": 6, "season": "2026-27", "status": "SUCCESS", "finished_at": "2026-10-10T09:51:00+00:00", "recovered": False, "knowledge": None})
    monkeypatch.setattr(mt, "_version", lambda run, config: "x/baseline")
    monkeypatch.setattr(mt, "_frame_built", lambda c: {"built": "x"})
    monkeypatch.setattr(mt, "_next_deadline", lambda: None)
    monkeypatch.setattr(mt, "_flags_for", lambda elements: {})
    return doc, team


def test_get_my_xi_carries_the_nudge_and_the_weekday_fields(xi_env):
    out = mt.get_my_xi()
    assert "error" not in out, out
    assert out["to_change"] == NUDGE
    assert out["frame_built"] == "Sat 10 Oct 2026 09:51 UTC" and out["frame_built_at"] == str(pd.Timestamp("2026-10-10T09:51:00"))
    assert out["recorded_roles"]["recorded_at_words"].split()[0] in calendar.day_abbr


def test_get_my_squad_carries_the_nudge(monkeypatch):
    doc = legal_doc()
    record = _row(doc, version_id=2, gw=6, user_id=9001)
    monkeypatch.setattr(mt.squad_store, "read_active", lambda user_id=None, conn=None: record)
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [])
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    monkeypatch.setattr(mt, "_flags_for", lambda elements: {})
    out = mt.get_my_squad()
    assert "error" not in out, out
    assert out["to_change"] == NUDGE and squad_store.TO_CHANGE == NUDGE
    assert "to_change" not in mt.LINEUP_NEXT_STEP                      # no description or prompt change: the line is data
