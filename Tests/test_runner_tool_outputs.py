"""The eval runner saves what the model saw (2026-10-11, LLM judge Part 0).

Until now a recorded tool call held {tool, args, error}; the tool's OUTPUT -- the exact string agent.py
hands the model as the tool_result content, str(result) -- was not saved, and neither was the context
block prepended to that turn's system prompt. An answer-quality judge needs both. The runner's
wrappers now record them; grading reads only tool and args, so a record with the new fields grades
exactly as before. No network, no database: the wrapped "agent" is a stub.
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_agent_evals as rae  # noqa: E402


def _stub_agent(result, block="CONTEXT BLOCK\n- Now: Saturday"):
    ag = types.SimpleNamespace()
    ag.call_tool = lambda name, args: result
    ag.context_block = lambda: block
    return ag


def test_every_recorded_call_carries_the_output_the_model_saw():
    result = {"players": [{"name": "Erling Haaland", "price": 15.6}], "total_matches": 79, "not_shown": 54, "note": None}
    ag = _stub_agent(result)
    rec = rae.Recorder()
    rae.wrap_dispatcher(ag, rec)
    out = ag.call_tool("list_players", {"position": "FWD"})
    assert out is result                                             # the agent still gets the real object
    call = rec.dump()[0]
    assert set(call) == {"tool", "args", "error", "output"}
    assert call["output"] == str(result)                             # exactly agent.py's tool_result content
    assert call["error"] is None and call["args"] == {"position": "FWD"}


def test_an_error_result_keeps_the_error_and_the_full_output():
    result = {"error": "player id 999999 matches no player; look the player up by name first", "error_kind": "unknown_player_id"}
    ag = _stub_agent(result)
    rec = rae.Recorder()
    rae.wrap_dispatcher(ag, rec)
    ag.call_tool("get_player_card", {"player_id": 999999})
    call = rec.dump()[0]
    assert call["error"].startswith("player id 999999 matches no player")
    assert call["output"] == str(result)


def test_the_context_block_of_the_turn_is_captured():
    ag = _stub_agent({}, block="CONTEXT BLOCK\n- Now: Saturday 2026-10-11 10:00 UTC.")
    rae.wrap_context(ag)
    assert ag.LAST_CONTEXT == {}                                     # nothing until the agent builds a turn
    text = ag.context_block()
    assert text.startswith("CONTEXT BLOCK")
    assert ag.LAST_CONTEXT["text"] == text


def test_a_failing_context_block_is_recorded_as_none_and_still_raises():
    ag = types.SimpleNamespace()

    def boom():
        raise RuntimeError("no snapshot")
    ag.context_block = boom
    rae.wrap_context(ag)
    try:
        ag.context_block()
    except RuntimeError:
        pass
    else:
        raise AssertionError("the wrapper must re-raise")
    assert ag.LAST_CONTEXT["text"] is None


def test_grading_ignores_the_new_field():
    q = {"must_call": "resolve_player > get_player_card", "must_not": "set_my_squad(confirm=true)"}
    calls = [{"tool": "resolve_player", "args": {"name": "Foden"}, "error": None},
             {"tool": "get_player_card", "args": {"player_id": 1}, "error": None}]
    with_output = [dict(c, output="{'player_id': 1, 'status': 's'}") for c in calls]
    assert rae.grade(q, with_output) == rae.grade(q, calls) == ("PASS", "")
