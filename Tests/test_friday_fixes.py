"""Friday fixes (2026-10-16): the three regressions CONFIRMED by the Thursday gate on the 15 Oct production data.

R1 -- availability routing. "Is Foden available next week?" / "...for GW7?" went resolve_player > search_news on
HEAD (4/4 and 3/3) and on 1039c9f (3/3) while base 94ab874 called get_player_card 4/4: resolve_player's bare `status`
'a' stood in for FPL's flag, which get_player_card carries with the time FPL took it. The tool descriptions now say
get_player_card comes FIRST for a named player's availability, news after it, and that resolve_player's status is
not the flag.

R2 -- invented reasons (optimise:7, compare_runs:5: the judge's "a reason no tool gave"). When a tool has no
breakdown of why a number moved, it says so in summary_plain ("Our numbers don't show why this changed.") with
reasons_available False; a squad build's pick rows carry the only basis the build has (predicted points for the
planned gameweek, that gameweek's number of fixtures) and the result says no other reasons are available."""
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "squad"), str(ROOT / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import agent                                               # noqa: E402
import model_tools as mt                                   # noqa: E402

NO_WHY = "Our numbers don't show why this changed."
NO_TERMS = ("build 3 has no recorded terms (built 2026-09-04 18:00:00+00:00, before the term columns of 2026-09-14; "
            "they are never backfilled) -- only its totals can be read")


def _desc(name):
    return {t["name"]: t["description"] for t in agent.tools_schema}[name]


# ---- R1 ---------------------------------------------------------------------------------------------------
def test_r1_get_player_card_is_first_for_a_named_players_availability():
    d = _desc("get_player_card")
    assert "available, fit, injured or suspended" in d
    assert "call this FIRST" in d
    assert "resolve_player's `status` is not FPL's flag" in d


def test_r1_search_news_comes_after_the_card():
    d = _desc("search_news")
    assert "AFTER get_player_card" in d
    assert "resolve_player's `status` is not FPL's flag" in d


# ---- R2: no breakdown -> say so ---------------------------------------------------------------------------
def _no_terms_fakes(monkeypatch):
    def fake_from_run(run_id, player_id, gw):
        return None, None, {"error": NO_TERMS.replace("build 3", f"build {run_id}"), "error_kind": "no_recorded_terms"}
    monkeypatch.setattr(mt, "_explain_from_run", fake_from_run)
    monkeypatch.setattr(mt, "_player_name", lambda pid: "Alexander Isak")

    def fake_q(sql, params=None):
        assert "model_predictions" in sql
        return [{"run_id": 3, "e_points": 4.12, "finished_at": datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)},
                {"run_id": 9, "e_points": 3.71, "finished_at": datetime(2026, 9, 15, 19, 0, tzinfo=timezone.utc)}]
    monkeypatch.setattr(mt, "_q", fake_q)


def test_r2_compare_runs_without_a_breakdown_says_our_numbers_dont_show_why(monkeypatch):
    _no_terms_fakes(monkeypatch)
    out = mt.compare_runs(379, 5, 3, 9)
    assert out["reasons_available"] is False
    assert out["summary_plain"].startswith(NO_WHY)
    assert "4.1" in out["summary_plain"] and "3.7" in out["summary_plain"]           # the totals it does have
    assert "error" in out and "no recorded terms" in out["error"]                     # the error stays
    assert list(out)[0] == "summary_plain"


def test_r2_explain_prediction_of_an_old_build_says_so_too(monkeypatch):
    _no_terms_fakes(monkeypatch)
    out = mt.explain_prediction(379, gw=5, run_id=3)
    assert out["reasons_available"] is False and out["summary_plain"].startswith(NO_WHY)
    assert "error" in out and "no recorded terms" in out["error"] and "never backfilled" in out["error"]


def test_r2_prediction_history_with_an_unexplainable_move_says_so(monkeypatch):
    rows = [{"run_id": 3, "kind": "deadline", "slot": None, "finished_at": datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
             "cutoff": 4, "horizon_step": 1, "e_points": 4.12, "p_start": 0.81, "e_minutes": 70.0, "terms_recorded": False},
            {"run_id": 9, "kind": "nightly", "slot": "nightly:2026-09-15", "finished_at": datetime(2026, 9, 15, 19, 0, tzinfo=timezone.utc),
             "cutoff": 5, "horizon_step": 0, "e_points": 3.71, "p_start": 0.62, "e_minutes": 55.0, "terms_recorded": True}]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: rows)
    monkeypatch.setattr(mt, "_player_name", lambda pid: "Alexander Isak")
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {379: {"position": "FWD", "team": "Liverpool"}})
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    out = mt.get_prediction_history(379, 5)
    assert out["reasons_available"] is False
    assert out["summary_plain"].startswith(NO_WHY)
    assert out["biggest_move"]["explainable"] is False and out["biggest_move"]["reasons_available"] is False


def test_r2_prediction_history_with_an_explainable_move_points_at_compare_runs(monkeypatch):
    rows = [{"run_id": 7, "kind": "post_ingest", "slot": None, "finished_at": datetime(2026, 9, 15, 18, 30, tzinfo=timezone.utc),
             "cutoff": 4, "horizon_step": 1, "e_points": 4.12, "p_start": 0.81, "e_minutes": 70.0, "terms_recorded": True},
            {"run_id": 9, "kind": "nightly", "slot": "nightly:2026-09-15", "finished_at": datetime(2026, 9, 15, 19, 0, tzinfo=timezone.utc),
             "cutoff": 5, "horizon_step": 0, "e_points": 3.71, "p_start": 0.62, "e_minutes": 55.0, "terms_recorded": True}]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: rows)
    monkeypatch.setattr(mt, "_player_name", lambda pid: "Alexander Isak")
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {379: {"position": "FWD", "team": "Liverpool"}})
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    out = mt.get_prediction_history(379, 5)
    assert out["reasons_available"] is True and "summary_plain" not in out
    assert out["biggest_move"]["explain_with"]["tool"] == "compare_runs"


# ---- R2: a squad build's picks carry their basis ----------------------------------------------------------
def test_r2_pick_basis_rows_and_the_no_other_reasons_line():
    out = {"gw": 10, "squad": [{"player_id": 1, "name": "A", "e_points": 4.6, "role": "start"},
                               {"player_id": 2, "name": "B", "e_points": 7.9, "role": "start"},
                               {"player_id": 3, "name": "C", "e_points": 0.0, "role": "bench"}]}
    res = mt._with_pick_basis(out, 10, {1: 1, 2: 2, 3: 0})
    rows = {r["player_id"]: r for r in res["squad"]}
    assert rows[1]["fixtures"] == 1 and rows[1]["basis"] == "4.6 predicted points for GW10, from 1 fixture"
    assert rows[2]["fixtures"] == 2 and rows[2]["basis"] == "7.9 predicted points for GW10, from 2 fixtures (a double gameweek)"
    assert rows[3]["fixtures"] == 0 and rows[3]["basis"] == "0.0 predicted points for GW10, from no fixture (a blank gameweek)"
    assert res["reasons_available"] is False
    assert res["basis"].endswith("No other reasons are available.")
    assert "predicted points for GW10" in res["basis"] and "number of GW10 fixtures" in res["basis"]


def test_r2_pick_basis_without_fixture_counts_still_states_the_points():
    res = mt._with_pick_basis({"gw": 7, "squad": [{"player_id": 1, "name": "A", "e_points": 5.0, "role": "start"}]}, 7, {})
    assert "fixtures" not in res["squad"][0]
    assert res["squad"][0]["basis"] == "5.0 predicted points for GW7"
    assert res["reasons_available"] is False and res["basis"].endswith("No other reasons are available.")


def test_r2_optimise_carries_the_basis_on_every_pick():
    try:
        out = mt.optimise(gw=None)
    except Exception as e:                       # noqa: BLE001 -- no frame on this machine
        pytest.skip(f"no production frame: {e}")
    if "error" in out:
        pytest.skip(f"no production frame: {out['error'][:80]}")
    assert out["reasons_available"] is False and out["basis"].endswith("No other reasons are available.")
    assert all("basis" in r and "predicted points for GW" in r["basis"] for r in out["squad"])
    assert all(isinstance(r.get("fixtures"), int) for r in out["squad"])
