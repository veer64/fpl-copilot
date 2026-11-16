"""Prompt R3b (16 Nov 2026): on a NORMAL chat turn three more answers are written by code and delivered as the reply itself --
the best squad from scratch, a comparison of players, and the fixture grid for all clubs or more than five.

E1   a turn whose model calls best_squad_from_scratch / build_squad_from_scratch / compare_players / get_fixtures and gets a
     code-built text back ends after that ONE model call: the reply is the text exactly, no fact check, no second call --
     on the loop and on the graph; the history is valid for the next turn;
E2   a result WITHOUT the text (an error, a refusal, one club's fixtures, five clubs or fewer) goes back to the model as
     it always did;
E3   the nine code-built tools, their schemas and their functions agree; a draft chat's turn still sends the frozen tools;
E4   more than five single-club fixture calls in one response: none is run, ONE app note says to ask once, the model
     continues (normal turns only); five run as before; six calls for ONE club's gameweeks run as before;
E5   the routing rules are in the normal turn's prompt and not in the draft chat's.
Offline: a scripted fake client (eval/payload_fixture.py), the logs stubbed, the tools replaced by fakes."""
import importlib
import inspect
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
TEXTS = {
    "best_squad_from_scratch": "**Best 15 from scratch for GW11 on a £100.0m budget: the starting XI is predicted 63.25 points with the captain's points counted twice, 56.10 before that.**\n\nWant me to explain any of these picks?",
    "build_squad_from_scratch": "**Best 15 from scratch for GW13 on a £95.5m budget: the starting XI is predicted 58.02 points with the captain's points counted twice, 51.40 before that.**\n\nWant me to explain any of these picks?",
    "compare_players": "**Rice against Szoboszlai on predicted points, GW11–16 (6 gameweeks): Szoboszlai 19.63, Rice 18.88. Szoboszlai is ahead by 0.75.**\n\nWant me to check either of them against your squad?",
    "get_fixtures": "**Fixtures for all 20 clubs, GW11–15 (5 gameweeks).**\n\n| Club | GW11 |\n|---|---|\n| Arsenal | NEW (A): scoring very easy (9), clean sheet very easy (10) |\n\nWant me to rank the best players from any of these clubs?",
}
INPUTS = {"best_squad_from_scratch": {}, "build_squad_from_scratch": {"gw": 13, "budget": 95.5}, "compare_players": {"player_ids": [13, 368]},
          "get_fixtures": {"horizon": 5}}
QUESTIONS = {"best_squad_from_scratch": "Rebuild my team from scratch.", "build_squad_from_scratch": "Best squad for gameweek 13 on £95.5m?",
             "compare_players": "How do Rice and Szoboszlai compare over the coming gameweeks?",
             "get_fixtures": "Show me all twenty clubs' next five fixtures."}
NEW_DIRECT = sorted(TEXTS)


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
    for tool, text in TEXTS.items():
        monkeypatch.setitem(agent.available_functions, tool,
                            (lambda t, x: (lambda **kw: calls.append((t, kw)) or {"direct_reply": x, "rows": [{"player_id": 411}]}))(tool, text))
    monkeypatch.setitem(agent.available_functions, "get_my_squad", lambda **kw: calls.append(("get_my_squad", kw)) or {"bank": 0.0})
    agent._calls = calls
    return agent


def _script(ag, monkeypatch, responses):
    script = pf._Script(responses)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    return script


def _use(tool, input_=None, id_="toolu_1"):
    return pf._Block("tool_use", name=tool, input=INPUTS.get(tool, {}) if input_ is None else input_, id=id_)


def _calls_resp(blocks, stop="tool_use"):
    return pf._Resp(blocks, stop)


def _reply(text="ok", stop="end_turn"):
    return pf._Resp([pf._Block("text", text=text)], stop)


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


def _btype(b):
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", None)


@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("tool", NEW_DIRECT)
def test_e1_the_reply_is_the_tools_text_after_one_model_call(ag, monkeypatch, engine, tool):
    script = _script(ag, monkeypatch, [_calls_resp([pf._Block("text", text="One moment."), _use(tool)])])
    answer, msgs = _turn(ag, engine, QUESTIONS[tool], [])
    assert answer == TEXTS[tool]                                           # the model's own words are not the reply
    assert len(script.calls) == 1 and ag._calls == [(tool, INPUTS[tool])]
    assert ag.LAST_FACT_CHECK.get("outcome") == "direct" and ag.LAST_TURN.get("calls") == 1 and ag.LAST_TURN.get("direct") is True
    assert ag.LAST_TURN.get("stop_reason") == "tool_use" and ag.LAST_TURN.get("truncated") is False
    assert msgs[-4] == {"role": "user", "content": QUESTIONS[tool]}
    assert msgs[-3]["role"] == "assistant" and any(_btype(b) == "tool_use" for b in msgs[-3]["content"])
    assert msgs[-2]["role"] == "user" and msgs[-2]["content"][0]["type"] == "tool_result"
    assert msgs[-1] == {"role": "assistant", "content": [{"type": "text", "text": TEXTS[tool]}]}


def test_e1b_the_next_turn_sends_a_valid_history(ag, monkeypatch):
    _script(ag, monkeypatch, [_calls_resp([_use("compare_players")])])
    _answer, msgs = ag.run_agent(QUESTIONS["compare_players"], [])
    script = _script(ag, monkeypatch, [_reply("Neither is in your squad.")])
    answer, _ = ag.run_agent("yes please", msgs)
    sent = script.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant", "user"] and answer == "Neither is in your squad."
    assert sent[3]["content"] == [{"type": "text", "text": TEXTS["compare_players"]}]


@pytest.mark.parametrize("tool,result", [
    ("best_squad_from_scratch", {"error": "no legal squad fits £60.0m: the cheapest legal squad costs £78.9m", "error_kind": "budget_infeasible"}),
    ("build_squad_from_scratch", {"error": "FPL allows at most 3 forwards; you asked to force 4", "error_kind": "squad_rule"}),
    ("compare_players", {"a": {"error": "player_id must be a number; look the player up by name first"}, "b": {"player_id": 13}}),
    ("get_fixtures", {"compact": False, "fixtures": [{"team": "Arsenal", "gw": 11}], "season_summary": {"team": "Arsenal"}}),
    ("get_fixtures", {"compact": True, "teams_requested": ["Arsenal", "Chelsea"], "fixtures": []}),
    ("get_fixtures", {"direct_reply": None, "fixtures": []})])
def test_e2_a_result_without_the_text_goes_back_to_the_model(ag, monkeypatch, tool, result):
    monkeypatch.setitem(ag.available_functions, tool, lambda **kw: dict(result))
    script = _script(ag, monkeypatch, [_calls_resp([_use(tool)]), _reply("the model's answer")])
    answer, msgs = ag.run_agent(QUESTIONS[tool], [])
    assert answer == "the model's answer" and len(script.calls) == 2
    assert msgs[2]["content"][0]["content"] == str(result)


def test_e3_the_code_built_tools_their_schemas_and_their_functions_agree(ag, monkeypatch):
    import model_tools as mt
    assert ag.DIRECT_TOOLS == {"explain_my_draft", "rank_players", "review_my_squad", "propose_transfers", "get_price_movements",
                               "best_squad_from_scratch", "build_squad_from_scratch", "compare_players", "get_fixtures",
                               "captain_pick", "set_my_squad", "get_league_table"}   # R3c: three more
    props = {t["name"]: t["input_schema"] for t in ag.tools_schema}
    assert set(props["compare_players"]["properties"]) == {"player_ids", "horizon"} and props["compare_players"]["required"] == ["player_ids"]
    assert props["compare_players"]["properties"]["player_ids"]["type"] == "array"
    assert set(props["get_fixtures"]["properties"]) == {"team", "teams", "my_players", "gw", "horizon"}
    assert props["get_fixtures"]["properties"]["teams"]["type"] == "array" and props["get_fixtures"]["properties"]["my_players"]["type"] == "boolean"
    assert set(props["propose_transfers"]["properties"]) == {"horizon", "lock_player_ids", "ban_player_ids", "max_transfers"}
    for name, fn in (("compare_players", mt.compare_players), ("get_fixtures", mt.get_fixtures), ("propose_transfers", mt.propose_transfers),
                     ("best_squad_from_scratch", mt.get_best_squad), ("build_squad_from_scratch", mt.optimise)):
        assert set(props[name]["properties"]) <= set(inspect.signature(fn).parameters), name
        assert ag.available_functions[name] is not None
    # the frozen draft tools still describe two ids for a comparison and no list of clubs
    frozen = {t["name"]: t for t in ag.DRAFT_BASE_TOOLS}
    assert set(frozen["compare_players"]["input_schema"]["properties"]) == {"player_id_a", "player_id_b"}
    assert set(frozen["get_fixtures"]["input_schema"]["properties"]) == {"team", "gw", "horizon"}
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread={"draft": DRAFT})
    assert [pf._strip(t) for t in script.calls[0]["tools"]][:24] == [pf._strip(t) for t in ag.DRAFT_BASE_TOOLS]
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread=None)
    assert [t["name"] for t in script.calls[0]["tools"]] == [t["name"] for t in ag.tools_schema] and len(script.calls[0]["tools"]) == 27   # R3c: + captain_pick


def _club_calls(clubs, extra=None, **kw):
    return [_use("get_fixtures", {"team": c, **kw}, f"toolu_f{i}") for i, c in enumerate(clubs)] + (extra or [])


TWELVE = ["Man City", "Liverpool", "Arsenal", "Man Utd", "Nott'm Forest", "Bournemouth", "Brentford", "Leeds", "Newcastle", "Aston Villa",
          "Coventry City", "Everton"]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_e4_more_than_five_single_club_fixture_calls_in_one_response_run_none(ag, monkeypatch, engine):
    script = _script(ag, monkeypatch, [_calls_resp(_club_calls(TWELVE, gw=11)),
                                       _calls_resp([_use("get_fixtures", {"my_players": True, "gw": 11})])])
    answer, msgs = _turn(ag, engine, "When's the next deadline, and who do my players face?", [])
    assert answer == TEXTS["get_fixtures"] and len(script.calls) == 2
    assert ag._calls == [("get_fixtures", {"my_players": True, "gw": 11})]   # none of the twelve calls ran
    results = msgs[2]["content"]
    assert len(results) == 12 and results[0]["content"] == ag.FIXTURE_FAN_OUT_NOTE
    assert results[0]["content"] == ("That is more than five clubs — ask for them in ONE get_fixtures call: no team for every club, "
                                     "teams=[...] for a list of clubs, or my_players=true for the user's own players")
    assert {r["content"] for r in results[1:]} == {"Not run."}             # ONE app note
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "fixtures_fan_out", "calls": 12, "tools": ["get_fixtures"]}]


def test_e4b_five_clubs_run_six_gameweeks_of_one_club_run_and_a_draft_turn_is_never_guarded(ag, monkeypatch):
    monkeypatch.setitem(ag.available_functions, "get_fixtures", lambda **kw: ag._calls.append(("get_fixtures", kw)) or {"compact": False, "fixtures": []})
    script = _script(ag, monkeypatch, [_calls_resp(_club_calls(TWELVE[:5])), _reply("done")])
    answer, _ = ag.run_agent("Five clubs please.", [])
    assert answer == "done" and len(ag._calls) == 5 and len(script.calls) == 2 and ag.LAST_TURN["skipped_rounds"] == []
    ag._calls.clear()
    one_club = [_use("get_fixtures", {"team": "Arsenal", "gw": g}, f"toolu_g{g}") for g in range(11, 17)]
    script = _script(ag, monkeypatch, [_calls_resp(one_club), _reply("done")])
    answer, _ = ag.run_agent("Arsenal, gameweek by gameweek.", [])
    assert answer == "done" and len(ag._calls) == 6                        # six calls, ONE club: not a several-club request
    ag._calls.clear()
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft", lambda **kw: {"direct_reply": "x"})
    script = _script(ag, monkeypatch, [_calls_resp(_club_calls(TWELVE)), _reply("done")])
    answer, _ = ag.run_agent("Twelve clubs please.", [], thread={"draft": DRAFT})
    assert answer == "done" and len(ag._calls) == 12                       # the guard is a normal turn's (its note names arguments a draft chat lacks)
    assert ag.MAX_FIXTURE_CLUBS == 5


def test_e5_the_routing_rules_are_the_normal_turns(ag):
    p = ag.SYSTEM_PROMPT
    assert "# 1c. Ten answers are written by code, not by you" in p   # R3c: was "Seven"
    for needle in ("`best_squad_from_scratch`", "`compare_players`", "`get_fixtures`", "`max_transfers`", "`my_players`"):
        assert needle in p[p.index("# 1c."):p.index("# 2. What you do not know")], needle
    assert "# 1c." not in ag.DRAFT_SYSTEM_PROMPT and "max_transfers" not in ag.DRAFT_SYSTEM_PROMPT
