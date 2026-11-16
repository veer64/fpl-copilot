"""Prompt R3 (16 Nov 2026): on a NORMAL chat turn four answers are written by code and delivered as the reply itself -- the
ranking, the whole-squad review, the transfer plan and a squad's price moves (agent.DIRECT_TOOLS); a tool round the model
cannot have is answered with ONE app note and the turn goes on.

D1-D5  a turn whose model calls rank_players / review_my_squad / propose_transfers / get_price_movements ends after that ONE
       model call: the reply is the tool's text exactly, no fact check, no second call -- on the loop and on the graph; the
       history is valid for the next turn. (D3: offered on normal turns only; a draft turn sends the frozen 24 tools + its own.)
D6     a result WITHOUT the text (an error, a bug, General mode's market movers, a draft chat's free swaps) goes back to the
       model as it always did.
D7     several code-built answers in one response are all delivered, in order, with one closing question.
G1     more than 10 get_prediction calls in one response: none is run, ONE app note, the model continues (normal turns only).
C9     a response the reply cap cut INSIDE a tool round: none of its calls is run, ONE app note, the turn continues -- never
       the step-limit reply (R1's two non-answers, digest C3 / C4); a draft turn's note does not name rank_players.
C10    such a round counts toward MAX_TOOL_ROUNDS like any other.
Offline: a scripted fake client (eval/payload_fixture.py), the logs stubbed, the tools replaced by fakes."""
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
TEXTS = {
    "rank_players": "**Top 2 of 79 forwards by predicted points, GW11 (1 gameweek).**\n\n| # | Player |\n|---|---|\n| 1 | Haaland |\n\nWant me to compare any of these, or check one against your squad?",
    "review_my_squad": "**Your 15 players over GW11–13 (3 gameweeks): 127.44 predicted points between them.**\n\nWhich player would you like me to go into, or is there anyone you'd like to bring in?",
    "propose_transfers": "**Transfer plan for GW11–13 (3 gameweeks): 2 transfers for the GW11 deadline, 0 hits.**\n\nWant me to preview any of these moves?",
    "get_price_movements": "**Your 15 players: FPL's price-change progress, and what each sells for.**\n\nWant me to look at a replacement for any of them?",
}
INPUTS = {"rank_players": {"position": "FWD", "n": 2}, "review_my_squad": {"horizon": 3}, "propose_transfers": {"horizon": 3},
          "get_price_movements": {}}
QUESTIONS = {"rank_players": "Top two forwards this week?", "review_my_squad": "Review my squad for the next three gameweeks.",
             "propose_transfers": "What transfers should I make over the next 3 gameweeks?",
             "get_price_movements": "Are any of my players close to a price change?"}


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
    monkeypatch.setitem(agent.available_functions, "get_prediction", lambda **kw: calls.append(("get_prediction", kw)) or {"e_points": 1.0})
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
@pytest.mark.parametrize("tool", ["rank_players", "review_my_squad", "propose_transfers", "get_price_movements"])
def test_d1_to_d5_the_reply_is_the_tools_text_after_one_model_call(ag, monkeypatch, engine, tool):
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


def test_d1b_the_next_turn_sends_a_valid_history_that_carries_the_rows(ag, monkeypatch):
    _script(ag, monkeypatch, [_calls_resp([_use("rank_players")])])
    _answer, msgs = ag.run_agent(QUESTIONS["rank_players"], [])
    script = _script(ag, monkeypatch, [_reply("Haaland, by 2.1.")])
    answer, _ = ag.run_agent("Compare the first two", msgs)
    sent = script.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant", "user"] and answer == "Haaland, by 2.1."
    assert sent[3]["content"] == [{"type": "text", "text": TEXTS["rank_players"]}]
    assert "'player_id': 411" in sent[2]["content"][0]["content"]          # the ids a follow-up needs travel in the result


def test_d3_the_new_tools_are_offered_on_normal_turns_only(ag, monkeypatch):
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread=None)
    names = [t["name"] for t in script.calls[0]["tools"]]
    assert names == [t["name"] for t in ag.tools_schema] and names[-3:] == ["rank_players", "review_my_squad", "search_news"] and len(names) == 26
    assert script.calls[0]["system"][0]["text"].endswith(ag.SYSTEM_PROMPT) and "# 1c. Four answers are written by code" in ag.SYSTEM_PROMPT
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread={"draft": DRAFT})
    draft_names = [t["name"] for t in script.calls[0]["tools"]]
    assert draft_names == [t["name"] for t in ag.DRAFT_BASE_TOOLS] + ["explain_my_draft"] and len(draft_names) == 25
    assert "rank_players" not in draft_names and "review_my_squad" not in draft_names
    assert script.calls[0]["system"][0]["text"].endswith(ag.DRAFT_SYSTEM_PROMPT) and "# 1c." not in ag.DRAFT_SYSTEM_PROMPT
    for t in ("get_prediction", "propose_transfers", "get_price_movements"):   # a draft turn keeps the descriptions it had
        normal = next(x for x in ag.tools_schema if x["name"] == t)
        frozen = next(x for x in ag.DRAFT_BASE_TOOLS if x["name"] == t)
        assert normal != frozen and pf._strip(next(x for x in script.calls[0]["tools"] if x["name"] == t)) == frozen


def test_d3b_the_direct_tools_have_functions_phrases_and_matching_schemas(ag):
    import inspect

    import model_tools as mt
    assert ag.DIRECT_TOOLS == {"explain_my_draft", "rank_players", "review_my_squad", "propose_transfers", "get_price_movements"}
    for name, fn in (("rank_players", mt.rank_players), ("review_my_squad", mt.review_my_squad), ("get_prediction", mt.get_prediction)):
        schema = next(t for t in ag.tools_schema if t["name"] == name)["input_schema"]
        params = set(inspect.signature(fn).parameters) - {"user_id"}
        assert set(schema["properties"]) == params, name
        assert ag.TOOL_PLAIN_PHRASES[name]
    rank = next(t for t in ag.tools_schema if t["name"] == "rank_players")["input_schema"]["properties"]
    assert rank["position"]["enum"] == ["GK", "DEF", "MID", "FWD", "any"] and rank["sort"]["enum"] == ["points", "value"]
    assert ag.replace_tool_names("use rank_players or review_my_squad")[0] == "use the player ranking or the squad review"


@pytest.mark.parametrize("result", [{"error": "no club matches 'Narnia'"}, {"bug": True, "error": "VALUATION MISMATCH"},
                                    {"risers": [], "fallers": []}, {"direct_reply": None}, {"direct_reply": 12}])
def test_d6_a_result_without_the_text_goes_back_to_the_model(ag, monkeypatch, result):
    monkeypatch.setitem(ag.available_functions, "rank_players", lambda **kw: dict(result))
    script = _script(ag, monkeypatch, [_calls_resp([_use("rank_players")]), _reply("the model's answer")])
    answer, msgs = ag.run_agent("best forwards in Narnia?", [])
    assert answer == "the model's answer" and len(script.calls) == 2
    assert msgs[2]["content"][0]["content"] == str(result)


def test_d6b_in_the_draft_chat_the_plan_tool_is_the_drafts_own(ag, monkeypatch):
    monkeypatch.setitem(ag.available_functions, "propose_transfers", lambda **kw: {"swaps": [], "note": "the best free swaps"})
    script = _script(ag, monkeypatch, [_calls_resp([_use("propose_transfers")]), _reply("Two swaps stand out.")])
    answer, _ = ag.run_agent("any swaps?", [], thread={"draft": DRAFT})
    assert answer == "Two swaps stand out." and len(script.calls) == 2


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_d7_several_code_built_answers_in_one_response_are_all_delivered(ag, monkeypatch, engine):
    a = "**Top 2 of 79 forwards…**\n\n| table A |\n\nWant me to compare any of these, or check one against your squad?"
    b = "**Top 2 of 216 midfielders…**\n\n| table B |\n\nWant me to compare any of these, or check one against your squad?"
    replies = iter([a, b])
    monkeypatch.setitem(ag.available_functions, "rank_players", lambda **kw: {"direct_reply": next(replies)})
    script = _script(ag, monkeypatch, [_calls_resp([_use("rank_players", {"position": "FWD"}, "toolu_a"),
                                                    _use("rank_players", {"position": "MID"}, "toolu_b")])])
    answer, msgs = _turn(ag, engine, "Top forwards and top midfielders?", [])
    assert answer == ("**Top 2 of 79 forwards…**\n\n| table A |\n\n**Top 2 of 216 midfielders…**\n\n| table B |\n\n"
                      "Want me to compare any of these, or check one against your squad?")
    assert len(script.calls) == 1 and len(msgs[-2]["content"]) == 2
    assert ag._join_direct(["one"]) == "one" and ag._join_direct(["x\n\nQ1?", "y\n\nQ2?"]) == "x\n\nQ1?\n\ny\n\nQ2?"


# ---- G1: the fan-out guard ------------------------------------------------------------------------------------------------------

def _fan_out(n, extra=None):
    return [_use("get_prediction", {"player_id": 100 + i}, f"toolu_p{i}") for i in range(n)] + (extra or [])


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_g1_more_than_ten_prediction_calls_in_one_response_run_none(ag, monkeypatch, engine):
    script = _script(ag, monkeypatch, [_calls_resp(_fan_out(11, [_use("get_my_squad", {}, "toolu_s")])),
                                       _calls_resp([_use("rank_players")])])
    answer, msgs = _turn(ag, engine, "Rank every forward by expected points.", [])
    assert answer == TEXTS["rank_players"] and len(script.calls) == 2
    assert ag._calls == [("rank_players", INPUTS["rank_players"])]         # none of the twelve calls ran
    results = msgs[2]["content"]
    assert len(results) == 12 and [r["tool_use_id"] for r in results][:2] == ["toolu_p0", "toolu_p1"]
    assert results[0]["content"] == "Your last request was cut off — ask for fewer players at once, or use rank_players"
    assert {r["content"] for r in results[1:]} == {"Not run."}             # ONE app note
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "fan_out", "calls": 12, "tools": ["get_my_squad", "get_prediction"]}]
    second = script.calls[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["content"] == ag.CUT_ROUND_NOTE


def test_g1b_ten_prediction_calls_run_and_a_draft_turn_is_never_guarded(ag, monkeypatch):
    script = _script(ag, monkeypatch, [_calls_resp(_fan_out(10)), _reply("done")])
    answer, msgs = ag.run_agent("Ten players please.", [])
    assert answer == "done" and len(ag._calls) == 10 and len(script.calls) == 2 and ag.LAST_TURN["skipped_rounds"] == []
    ag._calls.clear()
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft", lambda **kw: {"direct_reply": "x"})
    script = _script(ag, monkeypatch, [_calls_resp(_fan_out(14)), _reply("done")])
    answer, _ = ag.run_agent("Fourteen players please.", [], thread={"draft": DRAFT})
    assert answer == "done" and len(ag._calls) == 14                       # the guard is a normal turn's (its note names rank_players)
    assert ag.MAX_PREDICTION_CALLS == 10


# ---- C9 / C10: a tool round cut by the reply cap --------------------------------------------------------------------------------

@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("lead_in", [None, "Good, I have your 15. Now let me pull predictions for every player simultaneously."])
def test_c9_a_cut_tool_round_runs_nothing_gets_one_note_and_the_turn_continues(ag, monkeypatch, engine, lead_in):
    blocks = ([pf._Block("text", text=lead_in)] if lead_in else []) + _fan_out(4)
    script = _script(ag, monkeypatch, [_calls_resp(blocks, stop="max_tokens"), _calls_resp([_use("review_my_squad")])])
    answer, msgs = _turn(ag, engine, QUESTIONS["review_my_squad"], [])
    assert answer == TEXTS["review_my_squad"]                              # R1 gave the lead-in, or the step-limit reply
    assert answer != ag.ROUND_CAP_REPLY and (lead_in is None or lead_in not in answer)
    assert len(script.calls) == 2 and ag._calls == [("review_my_squad", INPUTS["review_my_squad"])]   # no cut call was run
    results = msgs[2]["content"]
    assert [r["content"] for r in results] == [ag.CUT_ROUND_NOTE, "Not run.", "Not run.", "Not run."]
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "cut", "calls": 4, "tools": ["get_prediction"]}]
    assert ag.LAST_TURN["truncated"] is False                              # the DELIVERED reply was not cut


def test_c9b_a_single_cut_call_is_not_run_either_and_a_draft_note_names_no_ranking_tool(ag, monkeypatch):
    script = _script(ag, monkeypatch, [_calls_resp([_use("get_my_squad", {}, "toolu_s")], stop="max_tokens"), _reply("Here it is.")])
    answer, msgs = ag.run_agent("my squad?", [])
    assert answer == "Here it is." and ag._calls == [] and msgs[2]["content"][0]["content"] == ag.CUT_ROUND_NOTE
    script = _script(ag, monkeypatch, [_calls_resp(_fan_out(3), stop="max_tokens"), _reply("Shorter then.")])
    answer, msgs = ag.run_agent("explain all", [], thread={"draft": DRAFT})
    assert answer == "Shorter then." and ag._calls == []
    assert msgs[2]["content"][0]["content"] == "Your last request was cut off — ask for fewer players at once" == ag.CUT_ROUND_NOTE_DRAFT
    assert "rank_players" not in ag.CUT_ROUND_NOTE_DRAFT and len(script.calls) == 2


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_c10_a_cut_round_counts_toward_the_round_cap(ag, monkeypatch, engine):
    cut = [_calls_resp(_fan_out(2), stop="max_tokens") for _ in range(ag.MAX_TOOL_ROUNDS)]
    script = _script(ag, monkeypatch, cut)
    answer, msgs = _turn(ag, engine, "keep trying", [])
    assert answer == ag.ROUND_CAP_REPLY and len(script.calls) == ag.MAX_TOOL_ROUNDS == 12
    assert ag._calls == [] and len(ag.LAST_TURN["skipped_rounds"]) == ag.MAX_TOOL_ROUNDS - 1
    assert ag.LAST_TURN["round_cap"]["rounds"] == 12 and ag.LAST_TURN["truncated"] is True
    assert msgs[-1] == {"role": "assistant", "content": [{"type": "text", "text": ag.ROUND_CAP_REPLY}]}
