"""The agent-eval runner's grading logic (eval/run_agent_evals.py).

Grading is pure code over the QUESTION turn's recorded tool calls. The grammar of
the "must call" column:

    a > b       b must appear after a (b consumes a's output)
    a + b       both must appear after the previous step, in any order
    a|b         either satisfies that slot
    none        no tool call at all
    tool(k=v)   that tool called with that argument

Extra calls are always allowed; "must NOT call" lists what may never appear.
No network, no database, no spreadsheet: every test here builds its own calls.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval"), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_agent_evals as rae                             # noqa: E402


def calls(*spec):
    """[("resolve_player", {}), ...] from names or (name, args) pairs."""
    out = []
    for s in spec:
        if isinstance(s, tuple):
            out.append({"tool": s[0], "args": s[1], "error": None})
        else:
            out.append({"tool": s, "args": {}, "error": None})
    return out


def test_a_chain_requires_its_order():
    ok, _ = rae.grade_must_call("resolve_player > get_prediction",
                                calls("resolve_player", "get_prediction"))
    assert ok
    bad, reason = rae.grade_must_call("resolve_player > get_prediction",
                                      calls("get_prediction", "resolve_player"))
    assert not bad and "get_prediction" in reason


def test_a_plus_step_accepts_either_order_but_must_follow_the_previous_step():
    spec = "resolve_player > compare_players + get_player_card"
    for order in (("resolve_player", "compare_players", "get_player_card"),
                  ("resolve_player", "get_player_card", "compare_players")):
        ok, reason = rae.grade_must_call(spec, calls(*order))
        assert ok, (order, reason)
    # get_player_card only BEFORE resolve_player does not satisfy the second step
    bad, _ = rae.grade_must_call(spec, calls("get_player_card", "resolve_player",
                                            "compare_players"))
    assert not bad
    missing, reason = rae.grade_must_call(spec, calls("resolve_player", "compare_players"))
    assert not missing and "get_player_card" in reason


def test_alternatives_are_satisfied_by_either_tool():
    for tool in ("get_best_squad", "optimise"):
        ok, _ = rae.grade_must_call("get_best_squad|optimise", calls(tool))
        assert ok, tool
    bad, _ = rae.grade_must_call("get_best_squad|optimise", calls("get_picks"))
    assert not bad
    ok, _ = rae.grade_must_call("resolve_player > get_player_card|get_prediction",
                                calls("resolve_player", "get_prediction"))
    assert ok


def test_none_means_no_tool_call_at_all():
    ok, _ = rae.grade_must_call("none", [])
    assert ok
    bad, reason = rae.grade_must_call("none", calls("get_picks"))
    assert not bad and "get_picks" in reason


def test_extra_calls_are_allowed():
    ok, _ = rae.grade_must_call("get_my_xi", calls("resolve_player", "get_my_squad", "get_my_xi"))
    assert ok


def test_must_not_call_flags_exactly_the_listed_tools():
    ok, _ = rae.grade_must_not("get_prediction, get_player_card", calls("resolve_player"))
    assert ok
    bad, reason = rae.grade_must_not("get_prediction, get_player_card",
                                     calls("resolve_player", "get_prediction"))
    assert not bad and "get_prediction" in reason
    ok, _ = rae.grade_must_not("", calls("set_my_squad"))
    assert ok


def test_an_argument_bound_tool_matches_on_that_argument():
    # the write is forbidden, the preview is not
    preview = calls(("set_my_squad", {"confirm": False}))
    write = calls(("set_my_squad", {"confirm": True}))
    ok, _ = rae.grade_must_not("set_my_squad(confirm=true)", preview)
    assert ok
    bad, reason = rae.grade_must_not("set_my_squad(confirm=true)", write)
    assert not bad and "set_my_squad" in reason
    # must call the preview: an omitted confirm IS the preview (the tool's default)
    ok, _ = rae.grade_must_call("set_my_squad(confirm=false)", calls("set_my_squad"))
    assert ok
    bad, _ = rae.grade_must_call("set_my_squad(confirm=false)", write)
    assert not bad


def test_grade_combines_both_columns_and_names_the_failure():
    q = {"must_call": "resolve_player > get_prediction",
         "must_not": "get_player_card", "sheet": "s", "num": 1}
    res, reason = rae.grade(q, calls("resolve_player", "get_prediction"))
    assert res == "PASS", reason
    res, reason = rae.grade(q, calls("resolve_player", "get_prediction", "get_player_card"))
    assert res == "FAIL" and "get_player_card" in reason
    res, reason = rae.grade(q, calls("get_prediction"))
    assert res == "FAIL" and "resolve_player" in reason
