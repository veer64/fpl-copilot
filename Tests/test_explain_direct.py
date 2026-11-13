"""Prompt W11g (2026-11-13): long explanations of a draft are written by CODE -- the model routes to explain_my_draft and the
tool's text IS the reply (G1); log lines can never crash a turn (G6).

1. A draft turn whose model calls explain_my_draft ends after that ONE model call: the reply is the tool's text exactly, no
   fact check, no second call -- on the loop and on the graph. The history ends user (question) / assistant (tool_use) /
   user (tool_result) / assistant (the text), so the next turn's request is valid (roles alternate) and carries the text.
2. explain_my_draft is offered on draft turns only (the last tool of a draft request); a non-draft request has the 24 tools of
   v5. Outside a draft turn the tool does not exist: a call to it is an error result and the turn goes on as usual.
3. Only explain_my_draft can end a turn this way: another tool returning a "direct_reply" key never does; an
   explain_my_draft error (no direct_reply) goes back to the model as usual.
4. G6: a console that cannot encode a character (Windows cp1252, "Vušković") never raises inside a turn -- the W11f eval's
   case 7 crashed in agent._run_tools' "[tool error: ...]" print.
5. The draft tool schema matches its function, and the tool-name lock knows it.
Offline: a scripted fake client (eval/payload_fixture.py), the logs stubbed."""
import importlib
import inspect
import io
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
TEXT = "How the 15 were picked: ...\n\n- **Vušković** (Brighton, £5.3m, starting): 4.97 predicted points.\n\nWant me to go into any player?"
Q = "Talk me through my squad player by player"


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
    monkeypatch.setitem(agent.DRAFT_FUNCTIONS, "explain_my_draft",
                        lambda detail="summary", player=None: calls.append((detail, player)) or {"direct_reply": TEXT, "detail": detail})
    agent._explain_calls = calls
    return agent


def _script(ag, monkeypatch, responses):
    script = pf._Script(responses)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    return script


def _explain_call(detail="each_player", text_first=None):
    blocks = ([pf._Block("text", text=text_first)] if text_first else []) + [
        pf._Block("tool_use", name="explain_my_draft", input={"detail": detail}, id="toolu_x1")]
    return pf._Resp(blocks, "tool_use")


def _reply(text="ok"):
    return pf._Resp([pf._Block("text", text=text)], "end_turn")


def _graph_turn(ag, question, history, thread):
    import agent_graph
    import tracing
    import turn_context
    st = ag._begin_turn(question, history, engine="graph", thread=thread)
    try:
        out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 50, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
    finally:
        tracing.close_open()
        turn_context.end()
    return out["rendered"], st["messages"]


def _block_type(b):
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", None)


def _check_history(msgs):
    assert msgs[-4]["role"] == "user" and msgs[-4]["content"] == Q
    assert msgs[-3]["role"] == "assistant" and any(_block_type(b) == "tool_use" for b in msgs[-3]["content"])
    assert msgs[-2]["role"] == "user" and msgs[-2]["content"][0]["type"] == "tool_result"
    assert msgs[-1] == {"role": "assistant", "content": [{"type": "text", "text": TEXT}]}


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_1_a_draft_turn_that_calls_explain_my_draft_ends_with_its_text_after_one_model_call(ag, monkeypatch, engine):
    script = _script(ag, monkeypatch, [_explain_call(text_first="Let me pull that together.")])
    thread = {"draft": DRAFT}
    if engine == "loop":
        answer, msgs = ag.run_agent(Q, [], thread=thread)
    else:
        answer, msgs = _graph_turn(ag, Q, [], thread)
    assert answer == TEXT                                                  # the model's own words are not the reply
    assert len(script.calls) == 1 and ag._explain_calls == [("each_player", None)]
    assert ag.LAST_FACT_CHECK.get("outcome") == "direct" and ag.LAST_TURN.get("calls") == 1
    _check_history(msgs)


def test_1b_the_next_turn_after_a_direct_reply_sends_a_valid_history(ag, monkeypatch):
    _script(ag, monkeypatch, [_explain_call()])
    _answer, msgs = ag.run_agent(Q, [], thread={"draft": DRAFT})
    script = _script(ag, monkeypatch, [_reply("Sure.")])
    answer, msgs2 = ag.run_agent("Thanks", msgs, thread={"draft": DRAFT})
    sent = script.calls[0]["messages"]
    roles = [m["role"] for m in sent]
    assert roles == ["user", "assistant", "user", "assistant", "user"], roles
    assert sent[3]["content"] == [{"type": "text", "text": TEXT}] and answer == "Sure."


def test_2_the_tool_is_offered_on_draft_turns_only(ag, monkeypatch):
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread={"draft": DRAFT})
    draft_tools_sent = script.calls[0]["tools"]
    assert [t["name"] for t in draft_tools_sent] == [t["name"] for t in ag.tools_schema] + ["explain_my_draft"]
    assert draft_tools_sent[-1] == pf._strip(ag.DRAFT_TOOLS[0])
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread=None)
    assert [t["name"] for t in script.calls[0]["tools"]] == [t["name"] for t in ag.tools_schema] and len(ag.tools_schema) == 24


def test_2b_outside_a_draft_turn_the_tool_does_not_exist(ag, monkeypatch):
    script = _script(ag, monkeypatch, [_explain_call(), _reply("fine")])
    answer, msgs = ag.run_agent(Q, [], thread=None)
    assert answer == "fine" and len(script.calls) == 2 and ag._explain_calls == []
    result = msgs[2]["content"][0]["content"]
    assert "explain_my_draft is not available" in result


def test_3_only_explain_my_draft_ends_a_turn_with_its_text(ag, monkeypatch):
    monkeypatch.setitem(ag.available_functions, "get_my_squad", lambda **k: {"direct_reply": "NOT A REPLY"})
    script = _script(ag, monkeypatch, [pf._Resp([pf._Block("tool_use", name="get_my_squad", input={}, id="toolu_s")], "tool_use"),
                                       _reply("the model's answer")])
    answer, _ = ag.run_agent("my squad?", [], thread={"draft": DRAFT})
    assert answer == "the model's answer" and len(script.calls) == 2


def test_3b_an_explain_error_goes_back_to_the_model(ag, monkeypatch):
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft",
                        lambda detail="summary", player=None: {"error": "Nobody is not one of the draft's 15 players."})
    script = _script(ag, monkeypatch, [_explain_call(), _reply("Which player did you mean?")])
    answer, _ = ag.run_agent("why Nobody?", [], thread={"draft": DRAFT})
    assert answer == "Which player did you mean?" and len(script.calls) == 2


def test_4_a_console_that_cannot_encode_a_name_never_crashes_a_turn(ag, monkeypatch):
    """G6: the W11f crash -- a tool error naming Vušković printed to a cp1252 console raised UnicodeEncodeError in the turn."""
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setitem(ag.available_functions, "set_my_squad",
                        lambda **k: {"error": "refused: a 4th Brighton player (De Cuyper, Vušković, Gómez already)"})
    _script(ag, monkeypatch, [pf._Resp([pf._Block("tool_use", name="set_my_squad", input={"player_ids": [1]}, id="toolu_c")], "tool_use"),
                              _reply("Refused: at most 3 per club.")])
    answer, _ = ag.run_agent("Let's get Kostoulas in and Evanilson out", [], thread={"draft": DRAFT})
    assert answer == "Refused: at most 3 per club."
    out = raw.getvalue().decode("cp1252")
    assert "Vuškovi?" in out and "[tool error: set_my_squad" in out           # ć is not in cp1252: replaced, never raised


def test_4b_every_log_line_in_the_agent_goes_through_the_safe_printer(ag):
    src = inspect.getsource(ag)
    body = src[: src.index('if __name__ == "__main__":')]
    assert 'print(f"  [' not in body and "print(\"  [" not in body


def test_5_the_draft_tool_schema_matches_its_function_and_the_lock_knows_it(ag):
    import model_tools as mt
    assert [t["name"] for t in ag.DRAFT_TOOLS] == list(ag.DRAFT_FUNCTIONS) == ["explain_my_draft"]
    schema = ag.DRAFT_TOOLS[0]["input_schema"]
    params = inspect.signature(mt.explain_my_draft).parameters
    assert set(schema["properties"]) == set(params) and schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["enum"] == ["summary", "each_player", "captain"]          # W11h H1
    assert ag.TOOL_PLAIN_PHRASES["explain_my_draft"] and "explain_my_draft" in ag.DIRECT_TOOLS
    assert ag.replace_tool_names("call explain_my_draft")[1] == 1
