"""Friday targeted fixes (2026-10-16), after the Friday fix gate's CONFIRMED regressions on the 15 Oct data.

F15 -- routing:6 "Haaland or Isak this week?" went to two player cards and never to compare_predictions (3/3; base
4/4 calls it): e57a069's get_player_card description sent EVERY availability-flavoured question to the card first. The
"call this FIRST" now covers a question about whether ONE named player can play; a comparison keeps its compare route.

F16 -- compare_runs:5 "Compare run 3 and run 9 for Isak in gameweek 5." stopped at get_prediction_history 3/3 (base
calls compare_runs 4/4): its no-breakdown text read as a full stop. It keeps "Our numbers don't show why this
changed.", points onward to compare_runs in tool-facing text, and lists the measured input moves of the two builds as
facts that our numbers don't attribute the move to.

F17 -- limits:2 "Should I triple captain Haaland this week?" said a 46% clean-sheet chance "lifts the floor" for a
forward: FPL gives forwards no clean-sheet points. Wherever a tool shows a clean-sheet chance for a forward (or a
midfielder's 1 point) the scoring fact sits beside it, at the source."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "squad"), str(ROOT / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import agent                                               # noqa: E402
import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402

NO_WHY = "Our numbers don't show why this changed."


def _desc(name):
    return {t["name"]: t["description"] for t in agent.tools_schema}[name]


# ---- F15 ------------------------------------------------------------------------------------------------
def test_f15_the_card_first_rule_covers_one_named_player_who_may_not_play():
    d = _desc("get_player_card")
    one = d.index("ONE named player")
    # date_aware:1 "Is Foden available next week?" / date_aware:6 "Is Foden available for GW7?" sit in this clause
    assert one < d.index("available, fit, injured or suspended") < d.index("call this FIRST")


def test_f15_a_comparison_keeps_its_compare_route():
    d = _desc("get_player_card")
    # routing:6 "Haaland or Isak this week?" is an "X or Y" comparison
    assert '"X or Y"' in d and '"who should I pick"' in d and "compare_predictions" in d
    assert d.index("ONE named player") < d.index('"X or Y"')


def test_f15_search_news_follows_the_card_only_for_one_player_who_may_not_play():
    d = _desc("search_news")
    assert "AFTER get_player_card" in d and "whether one named player can play" in d


# ---- F16 ------------------------------------------------------------------------------------------------
def _history(monkeypatch, recorded_first):
    rows = [{"run_id": 3, "kind": "deadline", "slot": None, "finished_at": datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
             "cutoff": 4, "horizon_step": 1, "e_points": 4.12, "p_start": 0.81, "e_minutes": 70.0, "terms_recorded": recorded_first},
            {"run_id": 9, "kind": "nightly", "slot": "nightly:2026-09-15", "finished_at": datetime(2026, 9, 15, 19, 0, tzinfo=timezone.utc),
             "cutoff": 5, "horizon_step": 0, "e_points": 3.71, "p_start": 0.62, "e_minutes": 55.0, "terms_recorded": True}]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: rows)
    monkeypatch.setattr(mt, "_player_name", lambda pid: "Alexander Isak")
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {379: {"position": "FWD", "team": "Liverpool"}})
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    return mt.get_prediction_history(379, 5)


def test_f16_no_breakdown_history_points_onward_to_compare_runs(monkeypatch):
    out = _history(monkeypatch, False)
    assert out["summary_plain"].startswith(NO_WHY)
    # "for a breakdown between two builds, use compare_runs" -- as a structured pointer (the tool name a field
    # value, like explain_with): Tests/test_tool_names_plain.py forbids tool names in the tools' prose
    assert out["next_step"]["for"] == "a breakdown between two builds" and out["next_step"]["tool"] == "compare_runs"
    assert "compare_runs" not in out["summary_plain"]                       # tool-facing, never shown to users


def test_f16_no_breakdown_history_lists_the_measured_input_moves_as_facts(monkeypatch):
    out = _history(monkeypatch, False)
    s = out["summary_plain"]
    assert "81%" in s and "62%" in s and "70" in s and "55" in s
    assert "our numbers don't attribute the move to them" in s
    assert out["input_moves"] == {"p_start": {"from": 0.81, "to": 0.62}, "e_minutes": {"from": 70.0, "to": 55.0}}


def test_f16_an_explainable_move_is_unchanged(monkeypatch):
    out = _history(monkeypatch, True)
    assert "next_step" not in out and "input_moves" not in out and "summary_plain" not in out
    assert out["biggest_move"]["explain_with"]["tool"] == "compare_runs"


# ---- F17 ------------------------------------------------------------------------------------------------
def _prediction(monkeypatch, position):
    run = {"run_id": 40, "gw": 7, "season": "2026-27", "status": "SUCCESS"}
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: dict(run))
    monkeypatch.setattr(mt, "_run_meta", lambda r, config=None: {"run_id": 40, "gw": 7})
    monkeypatch.setattr(mt, "_table_columns", lambda t, ttl=None: set())
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (7, 12))
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "_quantile_block", lambda rows: {"computed": False})

    def fake_q(sql, params=None):
        if "model_predictions" in sql:
            return [{"gw": 7, "e_points": 8.5, "horizon_step": 0, "p_cs": 0.4647}]
        return [{"name": "Erling Haaland", "team": "Man City", "position": position}]
    monkeypatch.setattr(mt, "_q", fake_q)
    return mt.get_prediction(411, gw=7)


def test_f17_a_forwards_clean_sheet_chance_says_it_scores_nothing(monkeypatch):
    row = _prediction(monkeypatch, "FWD")["predictions"][0]
    assert row["p_cs"] == 0.4647 and row["clean_sheet_points"] == "no clean-sheet points for forwards"
    keys = list(row)
    assert keys.index("clean_sheet_points") == keys.index("p_cs") + 1        # beside the chance it qualifies


def test_f17_a_midfielders_clean_sheet_is_one_point(monkeypatch):
    row = _prediction(monkeypatch, "MID")["predictions"][0]
    assert row["clean_sheet_points"] == "a clean sheet is worth 1 point for midfielders"


def test_f17_defenders_and_keepers_carry_no_label(monkeypatch):
    assert "clean_sheet_points" not in _prediction(monkeypatch, "DEF")["predictions"][0]
    assert "clean_sheet_points" not in _prediction(monkeypatch, "GK")["predictions"][0]


def test_f17_the_fixture_clean_sheet_chance_carries_fpl_scoring_by_position():
    d = ft._difficulty(1.8, 0.79, 0.4647)
    pts = d["defensive"]["clean_sheet_points"]
    assert "no clean-sheet points for forwards" in pts and "1 point for midfielders" in pts and "4 points" in pts
