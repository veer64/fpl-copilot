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


# ---------------------------------------------------------------- 4b
@pytest.fixture
def history_db(monkeypatch):
    rows = [{"run_id": 20, "kind": "nightly", "slot": "nightly:2026-09-25", "finished_at": datetime(2026, 9, 25, 11, 1, tzinfo=UTC),
             "cutoff": 6, "horizon_step": 0, "e_points": 6.1, "p_start": 0.9, "e_minutes": 80.0, "terms_recorded": True},
            {"run_id": 22, "kind": "nightly", "slot": "nightly:2026-09-27", "finished_at": datetime(2026, 9, 27, 11, 1, tzinfo=UTC),
             "cutoff": 6, "horizon_step": 0, "e_points": 4.4, "p_start": 0.6, "e_minutes": 55.0, "terms_recorded": True},
            {"run_id": 24, "kind": "nightly", "slot": "nightly:2026-09-29", "finished_at": datetime(2026, 9, 29, 11, 1, tzinfo=UTC),
             "cutoff": 6, "horizon_step": 0, "e_points": 4.9, "p_start": 0.7, "e_minutes": 62.0, "terms_recorded": True}]

    def fake_q(sql, params=None):
        if "JOIN model_runs" in sql:
            return [dict(r) for r in rows] if params[0] == 411 and params[1] == 6 else []
        if "min(gw)" in sql:
            return [{"lo": 3, "hi": 6}]
        if "FROM players_live" in sql and "name" in sql:
            return [{"name": "Erling Haaland"}] if params[0] == 411 else []
        raise AssertionError(sql)
    monkeypatch.setattr(mt, "_q", fake_q)
    monkeypatch.setattr(mt, "_web_names", lambda: {411: "Haaland"})
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    return rows


def test_history_is_oldest_to_newest_with_the_biggest_move_and_the_runs_to_explain_it(history_db):
    out = mt.get_prediction_history(411, 6)
    assert "error" not in out, out
    assert out["name"] == "Haaland" and out["gw"] == 6 and out["runs"] == 3
    assert [h["run_id"] for h in out["history"]] == [20, 22, 24]
    assert out["history"][0]["built"].startswith("nightly run built Fri 25 Sep 11:01Z")
    assert out["history"][0]["e_points"] == 6.1 and out["latest_e_points"] == 4.9
    assert out["latest_minus_first"] == -1.2
    b = out["biggest_move"]
    assert b["from_run_id"] == 20 and b["to_run_id"] == 22 and b["change"] == -1.7
    assert b["explain_with"] == {"tool": "compare_runs", "player_id": 411, "gw": 6, "run_id_a": 20, "run_id_b": 22}
    assert "run id" not in out["note"].lower() or "compare_runs" in out["note"]


def test_history_refuses_bad_ids_and_gameweeks_and_says_when_nothing_is_stored(history_db):
    assert mt.get_prediction_history("Haaland", 6)["error_kind"] == "invalid_player_id"
    assert mt.get_prediction_history(411, 0)["error_kind"] == "invalid_gw"
    out = mt.get_prediction_history(411, 20)
    assert out["error_kind"] == "no_predictions" and "GW20" in out["error"] and "GW3" in out["error"]


def test_a_move_across_a_run_without_terms_is_named_as_not_explainable(history_db):
    history_db[0]["terms_recorded"] = False
    out = mt.get_prediction_history(411, 6)
    assert out["biggest_move"]["explain_with"] is None and "no recorded terms" in out["biggest_move"]["explain_note"]


