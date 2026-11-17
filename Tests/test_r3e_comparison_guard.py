"""Prompt R3e (16 Nov 2026; USER DECISION): the comparison guard -- code checks the model's route on a comparison of named players,
as R3d's limit check reads the user's own words.

Measured before (eval/reports/r3d_answers.md, Set D case 6, run 3): "Over the coming gameweeks, is Doku or Semenyo the better
pick?" -- the model resolved both players, opened ONE player card (Semenyo's) and wrote the comparison itself ("This is
clear-cut enough that I don't need to run the full comparison tool"). R3d's guard stops only a SECOND card.

The guard, normal turns only. In a turn where ALL of these hold:
  (a) the user's own message reads as a comparison -- the FIXED word list below;
  (b) it names two or more different players -- counted by code: its own exact name match on the message against the player
      list, or two different players already resolved in the turn;
  (c) compare_players has not run in this turn;
a single-player lookup (get_player_card, get_prediction) is not run and gets ONE app note pointing at compare_players; the
round counts toward the round cap like any other; R3d's second-card guard stays.

E1  the word list is the brief's, exactly;
E2  the FIRE / NO FIRE table (written before the code): each message, against a fixed player list, fires or not;
E3  (b) by players resolved in the turn: two different players resolved fire; one, or an ambiguous lookup, does not;
E4  on both engines: the comparison's first card is not run, the note goes back, the model calls compare_players, whose text
    is the reply; get_prediction likewise; the note is never in the reply;
E5  on both engines: a message that does not read as a comparison runs the card ("Is Salah fit, and when does Haaland play
    next?", "Should I keep Mbeumo or sell him?");
E6  once compare_players has run in the turn, a card runs;
E7  the guarded rounds count toward the round cap, and the cap's reply carries no note;
E8  a draft chat's turn is never guarded;
E9  the player list failing to load leaves (b) to the players resolved in the turn -- the turn never fails;
E10 R3d's second-card guard stays: two cards in a turn that is not a comparison -- the second is not run, R3d's note;
E11 the payload: the guard is code only -- the normal turn's request is byte-identical to fixture v9 (the system prompt and
    the tools), and the v9 / threads v5 fixture files are unchanged.
Offline: a scripted fake client (eval/payload_fixture.py), the tools and the player list replaced by fakes."""
import hashlib
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import comparison_guard as cg                                              # noqa: E402
import payload_fixture as pf                                               # noqa: E402

NOTE = "This compares named players: call compare_players with every player's id — it writes the comparison, flags included."
R3D_NOTE = "For two or more players, use compare_players — it writes the comparison."
DRAFT = {"user_id": 10001, "draft_key": 800_000_001}

# (element, players_live name, FPL's web_name) -- a fixed slice of the player list, as build 78 has them
PLAYERS = [(400, "Jérémy Doku", "Doku"), (397, "Antoine Semenyo", "Semenyo"), (12, "Bukayo Saka", "Saka"),
           (185, "Tatsuhiro Sakamoto", "Sakamoto"), (154, "Cole Palmer", "Palmer"), (301, "Alex Palmer", "A.Palmer"),
           (4, "Gabriel dos Santos Magalhães", "Gabriel"), (18, "Gabriel Martinelli Silva", "Martinelli"),
           (6, "William Saliba", "Saliba"), (411, "Erling Haaland", "Haaland"), (427, "Bryan Mbeumo", "Mbeumo"),
           (379, "Alexander Isak", "Isak"), (25, "Viktor Gyökeres", "Gyökeres"), (426, "Bruno Borges Fernandes", "B.Fernandes"),
           (223, "Jean-Philippe Mateta", "Mateta"), (464, "Yoane Wissa", "Wissa"), (13, "Declan Rice", "Rice"),
           (249, "Thierno Barry", "Barry"), (167, "Liam Delap", "Delap"), (900, "Mohamed Salah", "M.Salah")]
FORMS = cg.name_forms(PLAYERS)

# (the user's message, FIRE?) -- written before the code
TABLE = [
    # FIRE: reads as a comparison AND names two or more different players
    ("Over the coming gameweeks, is Doku or Semenyo the better pick?", True),
    ("is Doku or Semenyo the better pick?", True),
    ("Saka vs Palmer", True),
    ("who's better value, Gabriel or Saliba?", True),
    ("Saka vs. Palmer -- who's the better buy?", True),
    ("Saka versus Palmer over the next five", True),
    ("Compare Saka and Palmer.", True),
    ("How does Saka compare with Palmer?", True),
    ("How do Isak and Haaland stack up?", True),
    ("What's the difference between Salah and Saka?", True),
    ("Would you rather have Mbeumo or Palmer?", True),
    ("Which of Saka, Rice and Haaland should I buy?", True),
    ("Best of Gyökeres, Isak and Haaland for the run-in?", True),
    ("gyokeres or isak?", True),
    ("Is Bruno Fernandes better than Palmer?", True),
    ("Mateta or Wissa for my last forward spot?", True),
    ("Haaland or Isak for captain?", True),
    ("Comparison please: M.Salah and Doku", True),
    # NO FIRE: no comparison word, or one player (or none)
    ("Is Salah fit, and when does Haaland play next?", False),
    ("Tell me about Saka and Palmer", False),
    ("Should I keep Mbeumo or sell him?", False),
    ("How is Haaland looking?", False),
    ("Is Doku injured?", False),
    ("Is Saka better this week than last?", False),
    ("Who is better value, a premium defender or a cheap one?", False),
    ("Which of my players should I sell?", False),
    ("Compare my squad with the best possible squad.", False),
    ("What's the best of the cheap defenders?", False),
    ("Palmer: buy or wait?", False),
    ("Sell Barry and buy Delap.", False),
    ("Bring in Saka for Rice.", False),
    ("Saka and Haaland: who plays first this week?", False),
    ("Is Sakamoto any good?", False),
    ("Haaland or roll the armband?", False),
    ("Gabriel or Gabriel Magalhães, which one is it?", False),
]


@pytest.mark.parametrize("message,fires", TABLE, ids=[f"{i:02d}" for i in range(1, len(TABLE) + 1)])
def test_e2_the_fire_no_fire_table(message, fires):
    assert cg.fires(message, FORMS, resolved=()) is fires


def test_e2b_the_table_is_at_least_25_messages_both_ways():
    assert len(TABLE) >= 25 and sum(f for _m, f in TABLE) >= 10 and sum(not f for _m, f in TABLE) >= 10


def test_e1_the_word_list_is_the_briefs_exactly():
    assert cg.COMPARISON_WORDS == (" or ", "vs", "versus", "compare", "comparison", "better", "best of", "stack up",
                                   "difference between", "rather have", "which of")
    assert cg.reads_as_comparison("Doku OR Semenyo") and not cg.reads_as_comparison("Doku, Semenyo")
    assert not cg.reads_as_comparison("Should I sell Forden?") and not cg.reads_as_comparison("Who is the orchestrator?")
    assert not cg.reads_as_comparison(None) and not cg.reads_as_comparison("")


def test_e2c_the_name_count():
    assert cg.players_named("Doku or Semenyo", FORMS) == 2
    assert cg.players_named("Palmer or Palmer", FORMS) == 1                   # one name, said twice
    assert cg.players_named("Gabriel Magalhães or Gabriel", FORMS) == 1       # the full name and the short name: one player
    assert cg.players_named("Bruno Fernandes", FORMS) == 1                    # one span, not two
    assert cg.players_named("B.Fernandes or Fernandes", FORMS) == 1
    assert cg.players_named("Salah and M.Salah", FORMS) == 1
    assert cg.players_named("Sakamoto", FORMS) == 1 and cg.players_named("sakamoto saka", FORMS) == 2
    assert cg.players_named("", FORMS) == 0 and cg.players_named("Doku or Semenyo", {}) == 0


def _resolved(pid):
    return ("resolve_player", {"name": str(pid)}, {"matches": [{"player_id": pid}], "total_matches": 1, "ambiguous": False})


def test_e3_players_resolved_in_the_turn_count():
    two = [_resolved(400), _resolved(397)]
    assert cg.resolved_players(two) == {400, 397}
    assert cg.fires("Who's the better pick of the two?", {}, resolved=cg.resolved_players(two))
    assert not cg.fires("Who's the better pick of the two?", {}, resolved=cg.resolved_players(two[:1]))
    amb = ("resolve_player", {"name": "Palmer"}, {"matches": [{"name": "Cole Palmer"}, {"name": "Alex Palmer"}], "total_matches": 2,
                                                  "ambiguous": True})
    assert cg.resolved_players([two[0], amb]) == {400}                        # an ambiguous lookup resolves nobody
    assert cg.resolved_players([two[0], _resolved(400)]) == {400}             # the same player twice is one
    nothing = ("resolve_player", {"name": "Salah"}, {"matches": [], "total_matches": 0, "ambiguous": False})
    assert cg.resolved_players([nothing, "junk", (None, None, None)]) == set()
    assert not cg.fires("Is Doku fit, and is Semenyo?", FORMS, resolved=cg.resolved_players(two))   # (a) fails


# ---- the agent, on both engines ---------------------------------------------------------------------------------------------
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
    monkeypatch.setattr(agent, "_guard_names", lambda: FORMS)
    calls = []
    for name, out in (("get_player_card", lambda kw: {"player_id": kw.get("player_id"), "status_word": "injured"}),
                      ("get_prediction", lambda kw: {"player_id": kw.get("player_id"), "span": 1.0}),
                      ("resolve_player", lambda kw: {"matches": [{"player_id": {"Doku": 400, "Semenyo": 397}.get(kw.get("name"), 1)}],
                                                     "total_matches": 1, "ambiguous": False}),
                      ("compare_players", lambda kw: {"direct_reply": "**Doku against Semenyo …**"})):
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
    import turn_context
    st = ag._begin_turn(question, history, engine="graph", thread=thread)
    try:
        out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
    finally:
        tracing.close_open()
        turn_context.end()
    return out["rendered"], st["messages"]


D6 = "Over the coming gameweeks, is Doku or Semenyo the better pick?"


@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("lookup", ["get_player_card", "get_prediction"])
def test_e4_the_comparisons_single_player_lookup_is_not_run(ag, monkeypatch, engine, lookup):
    script = _script(ag, monkeypatch, [pf._Resp([_tool("resolve_player", "toolu_r1", name="Doku"), _tool("resolve_player", "toolu_r2", name="Semenyo")], "tool_use"),
                                       pf._Resp([_tool(lookup, "toolu_a", player_id=397)], "tool_use"),
                                       pf._Resp([_tool("compare_players", "toolu_c", player_ids=[400, 397])], "tool_use")])
    answer, msgs = _turn(ag, engine, D6, [])
    assert answer == "**Doku against Semenyo …**" and len(script.calls) == 3
    assert [n for n, _kw in ag._calls] == ["resolve_player", "resolve_player", "compare_players"]   # the lookup never ran
    assert msgs[4]["content"][0]["tool_use_id"] == "toolu_a" and msgs[4]["content"][0]["content"] == NOTE == ag.COMPARISON_NOTE
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "comparison", "calls": 1, "tools": [lookup]}]
    assert NOTE not in answer and R3D_NOTE not in answer


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_e4b_the_first_card_is_held_before_anything_is_resolved(ag, monkeypatch, engine):
    """(b) by the message alone: the model's very first call is a card."""
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_a", player_id=397)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Doku, clearly.")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Saka vs Palmer", [])
    assert ag._calls == [] and msgs[2]["content"][0]["content"] == NOTE
    assert answer == "Doku, clearly." and NOTE not in answer


@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("message", ["Is Salah fit, and when does Haaland play next?", "Should I keep Mbeumo or sell him?",
                                     "Tell me about Saka and Palmer"])
def test_e5_a_message_that_is_not_a_comparison_runs_the_card(ag, monkeypatch, engine, message):
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_a", player_id=411)], "tool_use"),
                              pf._Resp([pf._Block("text", text="He is fit.")], "end_turn")])
    answer, msgs = _turn(ag, engine, message, [])
    assert ag._calls == [("get_player_card", {"player_id": 411})] and answer == "He is fit."
    assert ag.LAST_TURN["skipped_rounds"] == [] and NOTE not in str(msgs)


def test_e6_once_compare_players_has_run_a_card_runs(ag, monkeypatch):
    monkeypatch.setitem(ag.available_functions, "compare_players",
                        lambda **kw: ag._calls.append(("compare_players", kw)) or {"error": "player 1 not found"})
    _script(ag, monkeypatch, [pf._Resp([_tool("compare_players", "toolu_c", player_ids=[400, 1])], "tool_use"),
                              pf._Resp([_tool("get_player_card", "toolu_a", player_id=400)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Doku.")], "end_turn")])
    answer, _msgs = ag.run_agent(D6, [])
    assert [n for n, _kw in ag._calls] == ["compare_players", "get_player_card"] and answer == "Doku."


def test_e7_the_guarded_rounds_count_toward_the_round_cap(ag, monkeypatch):
    cards = [pf._Resp([_tool("get_player_card", f"toolu_{k}", player_id=400 + k)], "tool_use") for k in range(ag.MAX_TOOL_ROUNDS)]
    script = _script(ag, monkeypatch, cards)
    answer, _msgs = ag.run_agent(D6, [])
    assert answer == ag.ROUND_CAP_REPLY and len(script.calls) == ag.MAX_TOOL_ROUNDS
    assert ag._calls == [] and NOTE not in answer                              # no card ran; the cap's reply has no note


def test_e8_a_draft_chats_turn_is_never_guarded(ag, monkeypatch):
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft", lambda **kw: {"direct_reply": "x"})
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_a", player_id=400)], "tool_use"),
                              pf._Resp([pf._Block("text", text="done")], "end_turn")])
    answer, msgs = ag.run_agent(D6, [], thread={"draft": DRAFT})
    assert answer == "done" and ag._calls == [("get_player_card", {"player_id": 400})] and NOTE not in str(msgs)


def test_e9_a_player_list_that_fails_to_load_leaves_the_resolved_players(ag, monkeypatch):
    def boom():
        raise RuntimeError("no database")
    monkeypatch.setattr(ag, "_guard_names", boom)
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_a", player_id=400)], "tool_use"),
                              pf._Resp([_tool("resolve_player", "toolu_r1", name="Doku"), _tool("resolve_player", "toolu_r2", name="Semenyo")], "tool_use"),
                              pf._Resp([_tool("get_player_card", "toolu_b", player_id=397)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Doku.")], "end_turn")])
    answer, msgs = ag.run_agent(D6, [])
    assert answer == "Doku." and [n for n, _kw in ag._calls] == ["get_player_card", "resolve_player", "resolve_player"]
    assert msgs[6]["content"][0]["content"] == NOTE                            # held once two players were resolved


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_e10_r3ds_second_card_guard_stays(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_a", player_id=400), _tool("get_player_card", "toolu_b", player_id=397)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Both fit.")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Tell me about Doku and Semenyo.", [])
    assert ag._calls == [("get_player_card", {"player_id": 400})] and answer == "Both fit."
    assert msgs[2]["content"][1]["content"] == R3D_NOTE == ag.SECOND_CARD_NOTE
    assert ag.LAST_TURN["skipped_rounds"] == [{"why": "second_card", "calls": 1, "tools": ["get_player_card"]}]


FIX = REPO / "Tests" / "fixtures"


def test_e11_the_guard_is_code_only_the_request_is_v9_byte_for_byte(ag, monkeypatch):
    # R3f: the request of NOW is fixture v10 (R3f's routing sentence, Tests/test_agent_payload_equivalence.py); R3e's own claim
    # -- the guard changed no request -- stays proved by the v9 / threads v5 records pinned below and the v9 tests. The guarded
    # turn is compared with the request of now. Was: v9 = the v9 fixture, compared with tools_schema and SYSTEM_PROMPT.
    v9 = json.loads((FIX / "agent_payloads_v11.json").read_text(encoding="utf-8"))   # R3g: the request of now is v11 (was v10 in R3f)
    assert [pf._strip(t) for t in ag.tools_schema] == v9["shared"]["tools"]
    assert "".join(b["text"] for b in v9["shared"]["system"]) == f"{v9['context_text']}\n\n{ag.SYSTEM_PROMPT}"
    sha = {n: hashlib.sha256((FIX / n).read_bytes()).hexdigest()[:16] for n in ("agent_payloads_v9.json", "agent_payloads_threads_v5.json")}
    assert sha == {"agent_payloads_v9.json": "179e0a75bdfd8594", "agent_payloads_threads_v5.json": "8d2e106a13022b76"}
    # a guarded turn's requests: the first is v9's shape; the second differs only by the tool_result's text (the note)
    turn = pf.capture(ag, D6, [pf._Resp([_tool("get_player_card", "toolu_a", player_id=397)], "tool_use"),
                               pf._Resp([pf._Block("text", text="ok")], "end_turn")], v9["context_text"], now=v9["frozen_now"])
    assert len(turn) == 2
    for req in turn:
        assert {k: req[k] for k in req if k != "messages"} == v9["shared"]
    assert turn[1]["messages"][2]["content"][0]["content"] == NOTE
