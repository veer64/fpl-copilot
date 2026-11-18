"""Prompt F2 F (18 Nov 2026; USER DECISION): player ids must come from the tools.

Measured before: F1's L8 traces, laptop and production (C:\\dev\\fpl-backups\\f1_files\\gate\\results_L.json, smoke\\item_L8.json):
after "Tell me about Palmer." (an ambiguous lookup, no ids) and the user's "Cole", the model's FIRST call was get_player_card(328) --
Pascal Struijk -- before any lookup; R3g's run 2 guessed 448 (Dan Burn) the same way. F1's lock held a guess only while a name was
unsettled in the same turn.

I1  F1's L8 sequence on both engines: card(328) after "Cole" is not run, its result says to look the player up first; the lookup's
    id then runs; the note is never in the reply;
I2  an id resolve_player returned in the turn runs; an id an earlier turn of the chat returned runs (one in a list too);
I3  the user's own fifteen (the squad context code reads) runs, with a lookup in the chat: a card, review_my_squad, captain_pick, the
    transfer plan's locks and bans, the swap preview (its kept players and its looked-up incoming one); a swap preview bringing in
    an id no tool gave is not run;
I4  the scope: a chat with no lookup yet runs as before (every existing scripted test); a draft chat's turn is never held;
    resolve_player and search_news take names and are never held.
No model, no network, no database: the tools and the squad are fakes."""
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
import turn_context                                                        # noqa: E402

IDS = {"Cole Palmer": 154, "Saka": 12, "Haaland": 411, "Yarmoliuk": 102, "Dean Henderson": 198}
SQUAD = {26, 411, 427, 366, 367, 4, 102, 343, 60, 28, 380, 515, 379, 185, 40}       # the user's fifteen (a fake)
AMB_PALMER = {"matches": [{"name": "Cole Palmer", "team": "Chelsea", "position": "MID", "price": 9.8, "web_name": "Palmer"},
                          {"name": "Alex Palmer", "team": "Ipswich Town", "position": "GK", "price": 4.0, "web_name": "Palmer"}],
              "total_matches": 2, "ambiguous": True, "action": "ask the user which one",
              "note": "2 players answer to that name -- ask which: Cole Palmer (Chelsea); Alex Palmer (Ipswich Town)"}
# F1 L8 turn 1, as the stored thread holds it: the ambiguous lookup, its result (no ids), the question
PALMER_TURN = [{"role": "user", "content": "Tell me about Palmer."},
               {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_h1", "name": "resolve_player", "input": {"name": "Palmer"}}]},
               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_h1", "content": str(AMB_PALMER)}]},
               {"role": "assistant", "content": [{"type": "text", "text": "Which Palmer do you mean: Cole Palmer (Chelsea) or Alex Palmer (Ipswich Town)?"}]}]


def _haaland_turn():
    return [{"role": "user", "content": "How's Haaland?"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_h2", "name": "resolve_player", "input": {"name": "Haaland"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_h2",
                                          "content": str({"matches": [{"player_id": 411, "name": "Erling Haaland"}], "ambiguous": False})}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Haaland is fine."}]}]


@pytest.fixture
def ag(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AGENT_ENGINE", "loop")
    import agent
    import model_tools
    importlib.reload(agent)
    for name in ("record_chat_usage", "_citation_check", "_numeric_check", "_fact_check_log"):
        monkeypatch.setattr(agent, name, lambda *a, **k: None)
    monkeypatch.setattr(agent, "_note_turn", lambda st, raw=None: None)
    monkeypatch.setattr(agent, "context_block", lambda now=None: "ctx")
    monkeypatch.setattr(agent, "_guard_names", lambda: {})
    monkeypatch.setattr(agent, "_player_flags", lambda: {}, raising=False)       # F2 E's flags: none needed here
    monkeypatch.setattr(model_tools, "squad_ids_for_guard", lambda user_id=None: set(SQUAD), raising=False)
    calls = []
    fakes = {"resolve_player": lambda kw: {"matches": [{"player_id": IDS[kw["name"]], "name": kw["name"]}], "total_matches": 1,
                                           "ambiguous": False},
             "get_player_card": lambda kw: {"player_id": kw.get("player_id"), "status_word": "available"},
             "get_prediction": lambda kw: {"player_id": kw.get("player_id"), "span": 1.0},
             "compare_players": lambda kw: {"rows": kw.get("player_ids")},
             "review_my_squad": lambda kw: {"rows": "the fifteen"},
             "captain_pick": lambda kw: {"rows": kw.get("player_ids")},
             "propose_transfers": lambda kw: {"rows": "a plan"},
             "set_my_squad": lambda kw: {"rows": "a preview"},
             "search_news": lambda kw: {"results": [], "ambiguous_players": {}, "no_news_for": []}}
    for name, out in fakes.items():
        monkeypatch.setitem(agent.available_functions, name, (lambda n, f: (lambda **kw: calls.append((n, kw)) or f(kw)))(name, out))
    agent._calls = calls
    return agent


def _script(ag, monkeypatch, responses):
    script = pf._Script(responses)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    return script


def _tool(tool, id_, **inp):
    return pf._Block("tool_use", name=tool, input=inp, id=id_)


def _turn(ag, engine, question, history, thread=None):
    if engine == "loop":
        return ag.run_agent(question, history, thread=thread)
    import agent_graph
    import tracing
    st = ag._begin_turn(question, history, engine="graph", thread=thread)
    try:
        out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
    finally:
        tracing.close_open()
        turn_context.end()
    return out["rendered"], st["messages"]


def _results(msgs):
    out = {}
    for m in msgs:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out[b["tool_use_id"]] = b["content"]
    return out


def _unknown(ag):
    return [s for s in ag.LAST_TURN["skipped_rounds"] if s["why"] == "unknown_id"]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_i1_f1_l8s_guess_after_cole_is_not_run(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_g", player_id=328)], "tool_use"),
                              pf._Resp([_tool("resolve_player", "toolu_r", name="Cole Palmer")], "tool_use"),
                              pf._Resp([_tool("get_player_card", "toolu_c", player_id=154)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Cole Palmer is fit.")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Cole", [dict(m) for m in PALMER_TURN])
    assert [(n, kw) for n, kw in ag._calls] == [("resolve_player", {"name": "Cole Palmer"}), ("get_player_card", {"player_id": 154})]
    assert _results(msgs)["toolu_g"] == ag.UNKNOWN_ID_NOTE and "resolve_player" in ag.UNKNOWN_ID_NOTE
    assert _unknown(ag) == [{"why": "unknown_id", "calls": 1, "tools": ["get_player_card"]}]
    assert answer == "Cole Palmer is fit." and ag.UNKNOWN_ID_NOTE not in answer


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_i2_ids_from_the_tools_run(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("resolve_player", "toolu_r", name="Saka")], "tool_use"),
                              pf._Resp([_tool("get_player_card", "toolu_c", player_id=12)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Saka is out.")], "end_turn")])
    _turn(ag, engine, "How's Saka?", [])
    assert ("get_player_card", {"player_id": 12}) in ag._calls and not _unknown(ag)
    ag._calls.clear()
    _script(ag, monkeypatch, [pf._Resp([_tool("get_prediction", "toolu_p", player_id=411)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Haaland has an easy one.")], "end_turn")])
    _turn(ag, engine, "And his fixtures?", _haaland_turn())                       # the id came back in an earlier turn
    assert ag._calls == [("get_prediction", {"player_id": 411})] and not _unknown(ag)


def test_i2b_an_id_in_an_earlier_results_list_runs(ag, monkeypatch):
    history = _haaland_turn() + [
        {"role": "user", "content": "Top two midfielders?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_h3", "name": "rank_players", "input": {"position": "MID"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_h3", "content": str({"player_ids": [999, 998]})}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Two names."}]}]
    _script(ag, monkeypatch, [pf._Resp([_tool("compare_players", "toolu_cp", player_ids=[999, 998])], "tool_use"),
                              pf._Resp([pf._Block("text", text="Compared.")], "end_turn")])
    ag.run_agent("Compare them", history)
    assert ag._calls == [("compare_players", {"player_ids": [999, 998]})]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_i3_the_users_own_fifteen_runs(ag, monkeypatch, engine):
    swap = sorted((SQUAD - {185}) | {12})                                            # Sakamoto out, the looked-up Saka in
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r", name="Saka")], "tool_use"),
        pf._Resp([_tool("get_player_card", "toolu_c", player_id=380), _tool("review_my_squad", "toolu_rv"),
                  _tool("captain_pick", "toolu_cp", player_ids=[411, 26]),
                  _tool("propose_transfers", "toolu_pt", lock_player_ids=[411], ban_player_ids=[185]),
                  _tool("set_my_squad", "toolu_s", player_ids=swap, captain_id=411, vice_id=26, bench_order_ids=[28, 60, 343, 185])],
                 "tool_use"),
        pf._Resp([pf._Block("text", text="Done.")], "end_turn")])
    _turn(ag, engine, "Swap Sakamoto for Saka, and review my squad.", [])
    assert [n for n, _kw in ag._calls] == ["resolve_player", "get_player_card", "review_my_squad", "captain_pick", "propose_transfers",
                                           "set_my_squad"] and not _unknown(ag)


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_i3b_the_swap_preview_gets_the_chats_ids(ag, monkeypatch, engine):
    """The agent hands set_my_squad the ids the chat's tools gave (its kept players are the squad, which the tool reads)."""
    seen = []
    monkeypatch.setitem(ag.available_functions, "set_my_squad", lambda **kw: seen.append(turn_context.known_ids()) or {"rows": "a preview"})
    guess = sorted((SQUAD - {185}) | {777})
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r", name="Yarmoliuk")], "tool_use"),
        pf._Resp([_tool("set_my_squad", "toolu_s", player_ids=guess, captain_id=411, vice_id=26, bench_order_ids=[28, 60, 343, 102])],
                 "tool_use"),
        pf._Resp([pf._Block("text", text="Preview.")], "end_turn")])
    _turn(ag, engine, "Swap Sakamoto for Yarmoliuk.", [])
    assert len(seen) == 1 and 102 in seen[0] and 777 not in seen[0] and turn_context.known_ids() is None


def test_i3c_set_my_squad_refuses_an_incoming_guess_and_never_a_kept_player(monkeypatch):
    import model_tools as mt
    import squad_store
    monkeypatch.setattr(mt, "_squad_owner", lambda uid: uid)
    monkeypatch.setattr(squad_store, "read_active", lambda owner, conn=None: {"version_id": 1, "squad_json": {"players": [{"element": e} for e in SQUAD]}})
    monkeypatch.setattr(mt, "_current_gw", lambda: (_ for _ in ()).throw(RuntimeError("stop here: the checks ran first")))
    turn_context.begin("f2" + "i" * 30, user_message="Swap Sakamoto for Yarmoliuk.")
    try:
        turn_context.set_known_ids({102})
        out = mt.set_my_squad(player_ids=sorted((SQUAD - {185}) | {777}), captain_id=411, vice_id=26, bench_order_ids=[28, 60, 343, 26])
        assert out == {"error": mt.UNKNOWN_INCOMING_NOTE, "unknown_ids": [777]}
        out = mt.set_my_squad(player_ids=sorted((SQUAD - {185}) | {102}), captain_id=411, vice_id=26, bench_order_ids=[28, 60, 343, 26])
        assert "stop here" in out["error"]                                           # kept players and the looked-up one: past the check
        turn_context.set_known_ids(None)
        out = mt.set_my_squad(player_ids=sorted((SQUAD - {185}) | {777}), captain_id=411, vice_id=26, bench_order_ids=[28, 60, 343, 26])
        assert "stop here" in out["error"]                                           # no check handed: as before
    finally:
        turn_context.end()


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_i4_the_scope(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_c", player_id=411)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Haaland is fine.")], "end_turn")])
    _turn(ag, engine, "How's Haaland?", [])                                          # no lookup in the chat yet: as before
    assert ag._calls == [("get_player_card", {"player_id": 411})] and not _unknown(ag)
    ag._calls.clear()
    _script(ag, monkeypatch, [pf._Resp([_tool("search_news", "toolu_n", players=["Cole Palmer"], query="Cole Palmer news"),
                                        _tool("resolve_player", "toolu_r", name="Dean Henderson")], "tool_use"),
                              pf._Resp([pf._Block("text", text="News.")], "end_turn")])
    _turn(ag, engine, "Cole", [dict(m) for m in PALMER_TURN])                         # names, never ids: never held
    assert [n for n, _kw in ag._calls] == ["search_news", "resolve_player"] and not _unknown(ag)


def test_i4b_a_draft_chats_turn_is_never_held(ag, monkeypatch):
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft", lambda **kw: {"direct_reply": "x"})
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_g", player_id=328)], "tool_use"),
                              pf._Resp([pf._Block("text", text="done")], "end_turn")])
    ag.run_agent("Cole", [dict(m) for m in PALMER_TURN], thread={"draft": {"user_id": 10001, "draft_key": 800_000_001}})
    assert ag._calls == [("get_player_card", {"player_id": 328})]
