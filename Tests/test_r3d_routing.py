"""Prompt R3d items 2 and 3 (16 Nov 2026; USER DECISION): comparisons go to the code-built comparison, and a swap instruction is
previewed at once.

Measured before (eval/reports/r3c_answers.md): Set B case 6, runs 2 and 3 -- "Over the coming gameweeks, is Doku or Semenyo the
better pick?" with Semenyo injured was answered from player cards, one run with an estimate ("averaging around 4.6-5.2 per
gameweek"); case 9, run 1 -- "Sell Barry and buy Delap." was argued against ("The model prefers keeping Barry ... Want me to
preview the swap?") with a wrong figure ("saves you £0.4m" for £0.3m), and previewed only after "continue".

G1  compare_players' description LEADS with what it is for -- any comparison of two or more named players, injured or flagged
    players included -- and puts the armband exclusion second; the prompt's routing sentence says the same;
G2  a second get_player_card call in the same normal turn is not run: it gets ONE app note pointing at compare_players and the
    model continues; the round counts toward the round cap -- on the loop and on the graph; the first card runs;
G3  a draft chat's turn is never guarded;
G4  a swap instruction is previewed at once: set_my_squad's description and the prompt's routing section say so.
Offline: a scripted fake client (eval/payload_fixture.py), the tools replaced by fakes."""
import importlib
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                                               # noqa: E402

DRAFT = {"user_id": 10001, "draft_key": 800_000_001}
NOTE = "For two or more players, use compare_players — it writes the comparison."


@pytest.fixture
def ag(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AGENT_ENGINE", "loop")
    import agent
    importlib.reload(agent)
    for name in ("record_chat_usage", "_citation_check", "_numeric_check", "_fact_check_log"):
        monkeypatch.setattr(agent, name, lambda *a, **k: None)
    monkeypatch.setattr(agent, "_note_turn", lambda st, raw=None: None)
    monkeypatch.setattr(agent, "context_block", lambda now=None: "ctx")
    calls = []
    monkeypatch.setitem(agent.available_functions, "get_player_card",
                        lambda **kw: calls.append(("get_player_card", kw)) or {"player_id": kw.get("player_id"), "status_word": "injured"})
    monkeypatch.setitem(agent.available_functions, "compare_players",
                        lambda **kw: calls.append(("compare_players", kw)) or {"direct_reply": "**Doku against Semenyo …**"})
    agent._calls = calls
    return agent


def _script(ag, monkeypatch, responses):
    script = pf._Script(responses)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    return script


def _card(pid, id_):
    return pf._Block("tool_use", name="get_player_card", input={"player_id": pid}, id=id_)


def _turn(ag, engine, question, history, thread=None):
    if engine == "loop":
        return ag.run_agent(question, history, thread=thread)
    import agent_graph
    import tracing
    import turn_context
    st = ag._begin_turn(question, history, engine="graph", thread=thread)
    try:
        out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
    finally:
        tracing.close_open()
        turn_context.end()
    return out["rendered"], st["messages"]


def test_g1_compare_players_leads_with_what_it_is_for(ag):
    d = next(t for t in ag.tools_schema if t["name"] == "compare_players")["description"]
    first = d.split(". ")[0]
    assert "two or more named players" in first and "Not for the armband" not in first
    for needle in ("'X or Y'", "'who is the better pick'", "'how do they stack up'", "injured", "flag"):
        assert needle in d[:600], needle
    assert d.index("two or more named players") < d.index("Not for the armband")
    for kept in ("the route for comparing two players over the coming weeks", "needs no player card", "six-gameweek",
                 "'X or Y this week' prefer compare_predictions"):
        assert kept in d, kept                                                 # Friday gate v2 F19's sentences stay
    p = ag.SYSTEM_PROMPT
    sec = p[p.index("# 1c."):p.index("# 2. What you do not know")]
    assert "injured or flagged players included" in sec and "never compare players from their player cards" in sec


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_g2_a_second_card_in_the_turn_is_not_run_and_gets_one_note(ag, monkeypatch, engine):
    script = _script(ag, monkeypatch, [pf._Resp([_card(400, "toolu_a"), _card(397, "toolu_b")], "tool_use"),
                                       pf._Resp([pf._Block("tool_use", name="compare_players", input={"player_ids": [400, 397]}, id="toolu_c")],
                                                "tool_use")])
    answer, msgs = _turn(ag, engine, "Over the coming gameweeks, is Doku or Semenyo the better pick?", [])
    assert answer == "**Doku against Semenyo …**" and len(script.calls) == 2
    assert ag._calls == [("get_player_card", {"player_id": 400}), ("compare_players", {"player_ids": [400, 397]})]
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_a", "toolu_b"]
    assert results[1]["content"] == NOTE == ag.SECOND_CARD_NOTE and results[0]["content"] != NOTE
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "second_card", "calls": 1, "tools": ["get_player_card"]}]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_g2b_a_card_in_a_later_round_of_the_same_turn_is_not_run_either(ag, monkeypatch, engine):
    script = _script(ag, monkeypatch, [pf._Resp([_card(400, "toolu_a")], "tool_use"), pf._Resp([_card(397, "toolu_b")], "tool_use"),
                                       pf._Resp([pf._Block("text", text="Doku.")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Doku or Semenyo?", [])
    assert answer == "Doku." and len(script.calls) == 3 and ag._calls == [("get_player_card", {"player_id": 400})]
    assert msgs[4]["content"][0]["content"] == NOTE


def test_g2c_the_guarded_rounds_count_toward_the_round_cap(ag, monkeypatch):
    cards = [pf._Resp([_card(400 + k, f"toolu_{k}")], "tool_use") for k in range(ag.MAX_TOOL_ROUNDS)]
    script = _script(ag, monkeypatch, cards)
    answer, _msgs = ag.run_agent("cards please", [])
    assert answer == ag.ROUND_CAP_REPLY and len(script.calls) == ag.MAX_TOOL_ROUNDS
    assert ag._calls == [("get_player_card", {"player_id": 400})]             # only the first card ran


def test_g3_a_draft_chats_turn_is_never_guarded(ag, monkeypatch):
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft", lambda **kw: {"direct_reply": "x"})
    script = _script(ag, monkeypatch, [pf._Resp([_card(400, "toolu_a"), _card(397, "toolu_b")], "tool_use"),
                                       pf._Resp([pf._Block("text", text="done")], "end_turn")])
    answer, msgs = ag.run_agent("two cards", [], thread={"draft": DRAFT})
    assert answer == "done" and len(ag._calls) == 2 and NOTE not in str(msgs)


def test_g4_a_swap_instruction_is_previewed_at_once(ag):
    d = next(t for t in ag.tools_schema if t["name"] == "set_my_squad")["description"]
    assert "is an instruction" in d and "preview it at once" in d and "never argue or ask first" in d
    p = ag.SYSTEM_PROMPT
    sec = p[p.index("# 1c."):p.index("# 2. What you do not know")]
    for needle in ("sell / buy", "swap", "replace", "\"X out, Y in\"", "\"bring in X for Y\"", "is an instruction",
                   "never argue or ask first", "the code-built preview shows the predicted gain"):
        assert needle in sec, needle
    frozen = {t["name"]: t for t in ag.DRAFT_BASE_TOOLS}
    assert "is an instruction" not in frozen["set_my_squad"]["description"]   # a draft chat's tools are the frozen ones
