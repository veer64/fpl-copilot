"""Prompt R3c (16 Nov 2026): on a NORMAL chat turn three more answers are written by code and delivered as the reply itself -- the
captain answer, the text sent with a squad-change preview, and the league table -- and two code-built answers gain the line their
question needs (R3b's NOT DETERMINED: "weigh my line-up against the best possible squad"; "which clubs have a double?").

R1  a turn whose model calls captain_pick / set_my_squad (a preview) / get_league_table and gets a code-built text back ends
    after that ONE model call, on the loop and on the graph; the history is valid for the next turn;
R2  a result without the text (a refusal, a committed write, one club's table) goes back to the model as it always did;
R3  the tool list: captain_pick is offered on normal turns before search_news, which stays last; its schema matches its
    function; a draft chat's turn still sends the frozen tools and none of the new arguments;
R4  the routing sentences are in the normal turn's prompt and not in the draft chat's;
R5  the best squad from scratch, for a user with a saved squad, compares itself with the user's own best XI (whole-pool query);
R6  the fixture grid for every club ends with the calendar's doubles and blanks, counted from the calendar itself.
Offline: a scripted fake client (eval/payload_fixture.py) and fakes; R5 / R6 on the seeded pool."""
import importlib
import inspect
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                                               # noqa: E402

DRAFT = {"user_id": 10001, "draft_key": 800_000_001}
TEXTS = {
    "captain_pick": "**Captain for GW11: Haaland, 7.15 predicted points; 14.30 with the armband (his points counted twice).**\n\nWant me to go into either of them?",
    "set_my_squad": "**Preview: Gakpo out, Ødegaard in.**\nNothing is saved until you say yes.\n\nShall I make this change? Yes or No",
    "get_league_table": "**Premier League table 2026-27, as of Sat 21 Nov 2026 12:30 UTC.**\n\n| Pos | Club |\n|---|---|\n| 1 | Arsenal |\n\nWant me to look at any of these clubs' fixtures?",
}
INPUTS = {"captain_pick": {}, "set_my_squad": {"player_ids": list(range(1, 16)), "captain_id": 1, "vice_id": 2, "bench_order_ids": [12, 13, 14, 15],
                                              "confirm": False},
          "get_league_table": {"after_gw": 10}}
QUESTIONS = {"captain_pick": "Who should I captain this week?", "set_my_squad": "Swap Gakpo for Odegaard.",
             "get_league_table": "What did the league table look like after gameweek 10?"}


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
                            (lambda t, x: (lambda **kw: calls.append((t, kw)) or {"direct_reply": x, "preview_ticket": "abc"}))(tool, text))
    agent._calls = calls
    return agent


def _script(ag, monkeypatch, responses):
    script = pf._Script(responses)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    return script


def _use(tool, input_=None, id_="toolu_1"):
    return pf._Block("tool_use", name=tool, input=INPUTS.get(tool, {}) if input_ is None else input_, id=id_)


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


@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("tool", sorted(TEXTS))
def test_r1_the_reply_is_the_tools_text_after_one_model_call(ag, monkeypatch, engine, tool):
    script = _script(ag, monkeypatch, [pf._Resp([pf._Block("text", text="One moment."), _use(tool)], "tool_use")])
    answer, msgs = _turn(ag, engine, QUESTIONS[tool], [])
    assert answer == TEXTS[tool] and len(script.calls) == 1 and ag._calls == [(tool, INPUTS[tool])]
    assert ag.LAST_FACT_CHECK.get("outcome") == "direct" and ag.LAST_TURN.get("direct") is True
    assert msgs[-1] == {"role": "assistant", "content": [{"type": "text", "text": TEXTS[tool]}]}
    assert msgs[-2]["role"] == "user" and msgs[-2]["content"][0]["type"] == "tool_result"


def test_r1b_the_next_turn_sends_a_valid_history(ag, monkeypatch):
    _script(ag, monkeypatch, [pf._Resp([_use("captain_pick")], "tool_use")])
    _answer, msgs = ag.run_agent(QUESTIONS["captain_pick"], [])
    script = _script(ag, monkeypatch, [_reply("Gabriel is your vice.")])
    ag.run_agent("And the vice?", msgs)
    sent = script.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant", "user"]
    assert sent[3]["content"] == [{"type": "text", "text": TEXTS["captain_pick"]}]


@pytest.mark.parametrize("tool,result", [
    ("set_my_squad", {"error": "refused: illegal squad", "refused": True}),
    ("set_my_squad", {"committed": True, "preview": False, "version_id": 7, "change": {"transfers": []}}),
    ("get_league_table", {"table": [{"team": "Arsenal"}], "form_detail": {"team": "Arsenal"}}),
    ("captain_pick", {"error": "player id(s) [147] are not in the user's squad", "not_in_squad": [147]})])
def test_r2_a_result_without_the_text_goes_back_to_the_model(ag, monkeypatch, tool, result):
    monkeypatch.setitem(ag.available_functions, tool, lambda **kw: dict(result))
    script = _script(ag, monkeypatch, [pf._Resp([_use(tool)], "tool_use"), _reply("the model's answer")])
    answer, msgs = ag.run_agent(QUESTIONS[tool], [])
    assert answer == "the model's answer" and len(script.calls) == 2 and msgs[2]["content"][0]["content"] == str(result)


def test_r3_the_tool_list_and_the_schemas(ag, monkeypatch):
    import model_tools as mt
    names = [t["name"] for t in ag.tools_schema]
    assert names[-2:] == ["captain_pick", "search_news"] and len(names) == 27 and names.count("captain_pick") == 1
    assert ag.DIRECT_TOOLS >= {"captain_pick", "set_my_squad", "get_league_table"} and len(ag.DIRECT_TOOLS) == 12
    props = {t["name"]: t["input_schema"] for t in ag.tools_schema}
    assert set(props["captain_pick"]["properties"]) == {"player_ids", "gw"} and props["captain_pick"]["required"] == []
    assert set(props["captain_pick"]["properties"]) <= set(inspect.signature(mt.captain_pick).parameters)
    assert "after_gw" in props["get_league_table"]["properties"] and "after_gw" in inspect.signature(mt.get_league_table).parameters
    assert ag.TOOL_PLAIN_PHRASES["captain_pick"] == "the captain pick" and ag.captain_pick is mt.captain_pick   # (the fixture fakes the table's entry)
    frozen = {t["name"]: t for t in ag.DRAFT_BASE_TOOLS}
    assert "captain_pick" not in frozen and "after_gw" not in frozen["get_league_table"]["input_schema"]["properties"]
    script = _script(ag, monkeypatch, [_reply()])
    ag.run_agent("hello", [], thread={"draft": DRAFT})
    assert [t["name"] for t in script.calls[0]["tools"]] == [t["name"] for t in ag.DRAFT_BASE_TOOLS] + ["explain_my_draft"]


def test_r4_the_routing_rules_are_the_normal_turns(ag):
    p, d = ag.SYSTEM_PROMPT, ag.DRAFT_SYSTEM_PROMPT
    sec = p[p.index("# 1c."):p.index("# 2. What you do not know")]
    assert sec.startswith("# 1c. Ten answers are written by code, not by you")
    for needle in ("`captain_pick`", "`get_league_table`", "`after_gw`", "preview"):
        assert needle in sec, needle
    assert "captain_pick" not in d and "after_gw" not in d
    xi = next(t for t in ag.tools_schema if t["name"] == "get_my_xi")["description"]
    assert "captain" in xi and "captain_pick" in xi                          # the line-up tool sends armband questions on


# ---- R5 / R6 on the seeded pool -----------------------------------------------------------------------------------------------

import model_tools as mt                                                   # noqa: E402
import r3_seed as seed                                                     # noqa: E402
from r3_seed import pool_db                                                # noqa: E402,F401  (the fixture)
from test_best_squad_answer import BENCH, XI, _stored, _sum               # noqa: E402

OWN_STARTERS = [101, 102, 110, 118, 126, 105, 113, 121, 129, 123, 131]      # the user's own line-up pick; 131 the captain


def test_r5_the_best_squad_compares_itself_with_the_users_own_xi(pool_db, monkeypatch):
    own = {"gw": 11, "xi": [{"player_id": e, "role": "CAPTAIN" if e == 131 else "start"} for e in OWN_STARTERS],
           "bench_in_order": [{"player_id": e, "role": "bench"} for e in (109, 134, 137, 139)]}
    starters = list(OWN_STARTERS)
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: own)
    text = mt._with_squad_answer(_stored())["direct_reply"]
    once = _sum(pool_db, starters)
    doubled = once + _sum(pool_db, [131])
    best = _sum(pool_db, XI) + _sum(pool_db, [107])
    d = best - doubled
    rel = f"{abs(d):.2f} fewer than" if d > 0 else (f"{abs(d):.2f} more than" if d < 0 else "the same as")
    assert (f"**Against your own squad:** the best XI from your 15 for GW11 is predicted {doubled:.2f} points with the captain's points "
            f"counted twice ({once:.2f} before that): {rel} this squad's XI.") in text
    monkeypatch.setattr(mt, "_has_saved_squad", lambda user_id: False)
    assert "Against your own squad" not in mt._with_squad_answer(_stored())["direct_reply"]
    monkeypatch.setattr(mt, "_has_saved_squad", lambda user_id: True)
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: {"error": "no frame"})
    assert "Against your own squad" not in mt._with_squad_answer(_stored())["direct_reply"]


def test_r6_the_grid_ends_with_the_calendars_doubles_and_blanks():
    import answers
    cal = seed.calendar()
    clubs = sorted({c for c, _g in cal})
    line = answers.doubles_and_blanks(cal, clubs, 11)
    assert line == ("**Double and blank gameweeks in the loaded calendar, GW11–16:** doubles: Alpha GW12. Blanks: Bravo GW13. Doubles and "
                    "blanks are usually confirmed later in the season, as cup ties and postponements settle.")
    none = {(c, g): [{"opponent": "X", "home": True}] for c in clubs for g in range(11, 39)}
    assert "doubles: none. Blanks: none." in answers.doubles_and_blanks(none, clubs, 11)
    text = answers.fixture_grid(clubs, [11, 12], {(c, g): None for c in clubs for g in (11, 12)}, calendar_note=line)
    lines = text.split("\n")
    assert line in lines and lines.index(line) < lines.index("Any Premier League side can beat anyone.")
