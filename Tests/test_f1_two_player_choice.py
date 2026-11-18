"""Prompt F1 C (18 Nov 2026; USER DECISION): two-player choices are always code-built.

Measured before: the 17 Nov deploy smoke, item 7 (eval/reports/deploy_17nov.md; C:\\dev\\fpl-backups\\deploy_17nov_files\\smoke\\
item_7a.json): "Is Ekitike or Havertz the better pick?" -- both lookups resolved, so R3e's guard read a comparison of two named
players; the model called compare_predictions, which the guard did not hold (it held get_player_card and get_prediction only),
and wrote the answer itself (skipped_rounds empty). The missing accent and the bare "A or B" were read right.

C1  the guard reads "Ekitike or Havertz?", "Ekitiké or Havertz", "Havertz vs Ekitike" and the smoke's own turn as comparisons of
    two named players; "Ditch Diego Gomez for Yarmoliuk." is not one;
C2  on both engines: on such a turn compare_predictions is not run, the comparison note goes back, compare_players' text is the
    reply (also when compare_predictions is the model's first call); an armband question still reaches compare_predictions; a
    swap still previews.
No model, no network: the player slice and the scripted agent of Tests/test_f1_name_lock.py."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import comparison_guard as cg                                              # noqa: E402
import payload_fixture as pf                                               # noqa: E402
from test_f1_name_lock import FORMS, _results, _script, _tool, _turn       # noqa: E402
from test_f1_name_lock import ag, players                                  # noqa: E402,F401  (the fixtures)

# ---- C: two-player choices are always code-built ------------------------------------------------------------------------------
C_MESSAGES = ["Ekitike or Havertz?", "Ekitiké or Havertz", "Havertz vs Ekitike", "Is Ekitike or Havertz the better pick?"]


@pytest.mark.parametrize("message", C_MESSAGES)
def test_c1_the_guard_reads_them_as_comparisons(message):
    assert cg.fires(message, FORMS) is True


def test_c1b_the_smokes_own_turn_and_the_swap():
    assert cg.fires("Is Ekitike or Havertz the better pick?", {}, resolved={380, 26}) is True      # deploy smoke item 7's calls
    assert cg.fires("Ditch Diego Gomez for Yarmoliuk.", FORMS) is False


@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("message", C_MESSAGES)
def test_c2_compare_predictions_is_held_and_the_code_built_comparison_is_the_reply(ag, monkeypatch, engine, message):
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r1", name="Ekitike"), _tool("resolve_player", "toolu_r2", name="Havertz")], "tool_use"),
        pf._Resp([_tool("compare_predictions", "toolu_cp", player_id_a=380, player_id_b=26)], "tool_use"),
        pf._Resp([_tool("compare_players", "toolu_c", player_ids=[380, 26])], "tool_use")])
    answer, msgs = _turn(ag, engine, message, [])
    assert answer == "**Compared by code.**"
    assert [n for n, _kw in ag._calls] == ["resolve_player", "resolve_player", "compare_players"]
    assert _results(msgs)["toolu_cp"] == ag.COMPARISON_NOTE
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "comparison", "calls": 1, "tools": ["compare_predictions"]}]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_c2b_compare_predictions_first_before_any_lookup_is_held_too(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("compare_predictions", "toolu_cp", player_id_a=380, player_id_b=26)], "tool_use"),
                              pf._Resp([_tool("compare_players", "toolu_c", player_ids=[380, 26])], "tool_use")])
    answer, _msgs = _turn(ag, engine, "Ekitike or Havertz?", [])
    assert answer == "**Compared by code.**" and [n for n, _kw in ag._calls] == ["compare_players"]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_c2c_an_armband_question_still_reaches_compare_predictions(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("compare_predictions", "toolu_cp", player_id_a=411, player_id_b=379)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Haaland.")], "end_turn")])
    answer, _msgs = _turn(ag, engine, "Haaland or Isak for captain?", [])
    assert [n for n, _kw in ag._calls] == ["compare_predictions"] and answer == "Haaland."


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_c2d_a_swap_still_previews(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r1", name="Diego Gomez"), _tool("resolve_player", "toolu_r2", name="Yarmoliuk")], "tool_use"),
        pf._Resp([_tool("set_my_squad", "toolu_s", player_ids=list(range(1, 16)), captain_id=1, vice_id=2, bench_order_ids=[12, 13, 14, 15])],
                 "tool_use")])
    answer, _msgs = _turn(ag, engine, "Ditch Diego Gomez for Yarmoliuk.", [])
    assert answer == "**Preview.** Shall I make this change? Yes or No"
    assert [n for n, _kw in ag._calls] == ["resolve_player", "resolve_player", "set_my_squad"]
    assert ag.LAST_TURN["skipped_rounds"] == []
