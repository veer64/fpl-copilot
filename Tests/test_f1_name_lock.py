"""Prompt F1 B (18 Nov 2026; USER DECISION): the ambiguous-name lock.

Measured before: R3g's T2 run 2 (C:\\dev\\fpl-backups\\r3g_files\\trace_run2.json), "Tell me about Saka and Palmer.":
resolve_player("Palmer") was ambiguous (no ids, "ask the user which one"); the model wrote "I'll assume you mean Cole Palmer",
guessed id 448 (Dan Burn) for a card and a prediction, then looked up "Cole Palmer" with club "Chelsea" -- words the user never
wrote -- got ONE match (154) and answered about him without asking.

B1  THE LOOKUP TABLE (written before the code): (the name the model passed, its club, the turn's message, the earlier user messages)
    -> the player, or "ambiguous". A lookup whose ONE answer rests on words the user did not write -- a longer form of an ambiguous
    name ("Cole Palmer" after "Palmer"), a first name of one of its players ("Reece" for "James"), a club the user did not name --
    returns the ambiguous answer of the user's own words. The user's words (this message, or the earlier ones the chat carries)
    decide, a short reply ("Cole", "the Chelsea one", "Leeds", "the keeper") included; a clear name is answered as before;
B2  the hold: an ambiguous lookup of a name the user wrote holds it unsettled for the rest of the turn (every candidate's id); a
    lookup the user's words settle releases it; outside a turn, on a draft chat's turn, and for a name the user did not write
    nothing is held; the blocked lookup is the user's word's own ambiguous answer plus a trace note;
B3  on both engines: while a name is unsettled a call carrying one of its candidates' ids -- or an id no tool result has given,
    as text too -- is not run; its result names the candidates and says to ask; a clear name's calls run; captain_pick (which
    takes only the user's own fifteen) is not held; the note is never in the reply;
B4  search_news for a candidate under words the user did not write is not run; for the bare name, or a clear one, it runs;
B5  set_my_squad refuses an incoming candidate while his name is unsettled; a squad player kept is never held;
B6  the next message settles it: "Cole" after "Tell me about Palmer." -> the lookup returns Cole Palmer and his card runs;
B7  a draft chat's turn: nothing held, nothing blocked.
No model, no network: players_live and the web names are a fixed slice, as build 78 has them
(C:\\dev\\fpl-backups\\f1_files\\slice_names.txt)."""
import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import comparison_guard as cg                                              # noqa: E402
import model_tools as mt                                                   # noqa: E402
import payload_fixture as pf                                               # noqa: E402
import turn_context                                                        # noqa: E402

# (element, players_live name, web_name, position, club, price in tenths, status) -- build 78's own
# (C:\dev\fpl-backups\f1_files\slice_names.txt)
PLAYERS = [(154, "Cole Palmer", "Palmer", "MID", "Chelsea", 98, "a"),
           (301, "Alex Palmer", "Palmer", "GK", "Ipswich Town", 40, "a"),
           (12, "Bukayo Saka", "Saka", "MID", "Arsenal", 94, "i"),
           (185, "Tatsuhiro Sakamoto", "Sakamoto", "MID", "Coventry City", 48, "a"),
           (448, "Dan Burn", "Burn", "DEF", "Newcastle", 48, "a"),
           (142, "Reece James", "James", "DEF", "Chelsea", 52, "i"),
           (343, "Daniel James", "James", "MID", "Leeds", 49, "a"),
           (515, "James Maddison", "Maddison", "MID", "Spurs", 62, "a"),
           (60, "James Hill", "Hill", "DEF", "Bournemouth", 56, "a"),
           (28, "Emiliano Martínez Romero", "Martinez", "GK", "Chelsea", 49, "d"),
           (419, "Lisandro Martínez", "Martinez", "DEF", "Man Utd", 48, "a"),
           (411, "Erling Haaland", "Haaland", "FWD", "Man City", 158, "a"),
           (379, "Alexander Isak", "Isak", "FWD", "Liverpool", 93, "a"),
           (380, "Hugo Ekitiké", "Ekitiké", "FWD", "Liverpool", 74, "i"),
           (26, "Kai Havertz", "Havertz", "FWD", "Arsenal", 74, "a"),
           (427, "Bryan Mbeumo", "Mbeumo", "MID", "Man Utd", 79, "a"),
           (366, "Florian Wirtz", "Wirtz", "MID", "Liverpool", 72, "a"),
           (127, "Diego Gómez Amarilla", "Gomez", "MID", "Brighton", 50, "a"),
           (359, "Joe Gomez", "Gomez", "DEF", "Liverpool", 49, "a"),
           (102, "Yehor Yarmoliuk", "Yarmoliuk", "MID", "Brentford", 47, "a"),
           (4, "Gabriel dos Santos Magalhães", "Gabriel", "DEF", "Arsenal", 81, "a"),
           (27, "Gabriel Fernando de Jesus", "G.Jesus", "FWD", "Arsenal", 64, "u")]
FORMS = cg.name_forms([(e, n, w) for e, n, w, *_r in PLAYERS])
DRAFT = {"user_id": 10001, "draft_key": 800_000_001}
AMB = "ambiguous"


@pytest.fixture
def players(monkeypatch):
    live = [{"element": e, "name": n, "position": pos, "team": club, "price_tenths": pr, "status": st}
            for e, n, _w, pos, club, pr, st in PLAYERS]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: live)
    monkeypatch.setattr(mt, "_web_names", lambda: {e: w for e, _n, w, *_r in PLAYERS})
    monkeypatch.setattr(mt, "_club_short_names", lambda: {"Chelsea": "CHE", "Leeds": "LEE", "Ipswich Town": "IPS", "Arsenal": "ARS",
                                                          "Man Utd": "MUN", "Liverpool": "LIV", "Spurs": "TOT"})
    return live


def _begin(message, earlier=(), draft=None):
    kw = {"user_message": message, "earlier_messages": list(earlier)}
    if draft:
        kw["draft"] = draft
    turn_context.begin("f1" + "t" * 30, **kw)


def _resolve(name, message, club=None, earlier=(), draft=None):
    _begin(message, earlier, draft)
    try:
        return mt.resolve_player(name, club=club) if club else mt.resolve_player(name)
    finally:
        turn_context.end()


def _picked(out):
    return AMB if out["ambiguous"] else out["matches"][0]["player_id"]


SAKA_PALMER = "How's Saka looking, and what about Palmer?"
# (the name the model passed, its club, the turn's own message, the earlier user messages, the answer) -- written before the code
TABLE = [
    ("Cole Palmer", None, SAKA_PALMER, (), AMB),                               # R3g's longer lookup: "Cole" is not the user's
    ("Cole Palmer", "Chelsea", "Tell me about Saka and Palmer.", (), AMB),     # R3g run 2, word for word
    ("Palmer", "Chelsea", "Tell me about Palmer.", (), AMB),                   # a club the user did not name
    ("Palmer", "Chelsea", "Tell me about Palmer, the Chelsea one.", (), 154),  # a club the user did name
    ("Cole Palmer", None, "Tell me about Cole Palmer and Saka.", (), 154),     # L7: written in full
    ("Reece James", None, "Tell me about James.", (), AMB),
    ("James Maddison", None, "Tell me about James.", (), AMB),                 # a lower-ranked match of the same name
    ("Reece", None, "Tell me about James.", (), AMB),                          # a first name of one of them
    ("Cole", None, "Tell me about Palmer.", (), AMB),
    ("Emiliano Martinez", None, "Is Martinez worth a punt, and how's Haaland doing?", (), AMB),
    ("Erling Haaland", None, "Is Martinez worth a punt, and how's Haaland doing?", (), 411),   # a clear name: unchanged
    ("Bukayo Saka", None, SAKA_PALMER, (), 12),
    ("Hugo Ekitike", None, "Ekitike or Havertz?", (), 380),
    ("Cole Palmer", None, "Who is the best Chelsea midfielder?", (), 154),     # no word of the lookup is the user's: unchanged
    ("Gabriel Jesus", None, "Is Gabriel fit?", (), 27),                         # "Gabriel" is one display-name match: unchanged
    ("Diego Gomez", None, "Ditch Diego Gomez for Yarmoliuk.", (), 127),
    ("Cole Palmer", None, "Cole", ("Tell me about Palmer.",), 154),            # L8 turn 2: the user's words across the chat
    ("Palmer", None, "Cole", ("Tell me about Palmer.",), 154),                 # the reply settles the bare name
    ("Palmer", None, "The Chelsea one", ("Tell me about Palmer.",), 154),
    ("James", None, "Leeds", ("Tell me about James.",), 343),
    ("Martinez", None, "the keeper", ("Is Martinez worth a punt?",), 28),
    ("Palmer", None, "Palmer?", ("Tell me about Palmer.",), AMB),
    ("Palmer", None, "Tell me about Palmer.", (), AMB),                         # unchanged
    ("Haaland", None, "Is Haaland fit?", (), 411),                              # unchanged
]


@pytest.mark.parametrize("name,club,message,earlier,want", TABLE, ids=[f"{i:02d}" for i in range(1, len(TABLE) + 1)])
def test_b1_the_lookup_table(players, name, club, message, earlier, want):
    assert _picked(_resolve(name, message, club=club, earlier=earlier)) == want


def test_b1b_outside_a_turn_and_on_a_draft_turn_the_longer_lookup_is_unchanged(players, monkeypatch):
    assert turn_context.user_message() is None and _picked(mt.resolve_player("Cole Palmer")) == 154
    import draft_tools
    monkeypatch.setattr(draft_tools, "resolve_in_draft", lambda d, name, cands, out: out)
    assert _picked(_resolve("Cole Palmer", SAKA_PALMER, draft=DRAFT)) == 154


def test_b2_the_hold(players):
    plain = mt.resolve_player("Palmer")                                      # no turn
    _begin(SAKA_PALMER)
    try:
        amb = mt.resolve_player("Palmer")
        assert amb == plain                                                  # the ambiguous answer itself is unchanged
        held = turn_context.unsettled()
        assert list(held) == ["palmer"] and {154, 301} <= set(held["palmer"]["ids"])
        longer = mt.resolve_player("Cole Palmer", club="Chelsea")            # R3g run 2's lookup
        assert longer["ambiguous"] is True and all("player_id" not in m for m in longer["matches"])
        assert {k: v for k, v in longer.items() if k != "unsettled_lookup"} == {k: v for k, v in amb.items()}
        assert longer["unsettled_lookup"]["unwritten"] == ["cole"] and longer["unsettled_lookup"]["query"] == "Cole Palmer"
        assert list(turn_context.unsettled()) == ["palmer"]                 # still held
        assert mt.resolve_player("Saka")["matches"][0]["player_id"] == 12    # a clear name, as ever
    finally:
        turn_context.end()
    _begin("Tell me about Palmer, the Chelsea one.")
    try:
        mt.resolve_player("Palmer")
        assert list(turn_context.unsettled()) == ["palmer"]
        assert _picked(mt.resolve_player("Palmer", club="Chelsea")) == 154
        assert turn_context.unsettled() == {}                                # the user's words settled it
    finally:
        turn_context.end()
    _begin("Who is the best keeper?")
    try:
        assert mt.resolve_player("Palmer")["ambiguous"] is True and turn_context.unsettled() == {}   # not a name the user wrote
    finally:
        turn_context.end()
    assert turn_context.unsettled() == {}                                    # outside a turn


def test_b2b_a_draft_turn_holds_nothing(players, monkeypatch):
    import draft_tools
    monkeypatch.setattr(draft_tools, "resolve_in_draft", lambda d, name, cands, out: out)
    _begin(SAKA_PALMER, draft=DRAFT)
    try:
        assert mt.resolve_player("Palmer")["ambiguous"] is True and turn_context.unsettled() == {}
    finally:
        turn_context.end()


def test_b2c_the_pure_readings():
    assert cg.words_of("How's Saka looking?", "Tell me about PALMER.") >= {"saka", "palmer", "how", "s"}
    cands = [(154, {"cole", "palmer", "chelsea", "mid", "midfielder"}), (301, {"alex", "palmer", "ipswich", "town", "gk", "keeper"})]
    assert cg.reply_names_one("Cole", cands) == (154, "cole")
    assert cg.reply_names_one("the Chelsea one please", cands) == (154, "chelsea")
    assert cg.reply_names_one("Alex", cands) == (301, "alex")
    assert cg.reply_names_one("Palmer?", cands) is None                      # both of them
    assert cg.reply_names_one("Tell me about Palmer.", cands) is None        # not a reply made of one player's words
    assert cg.reply_names_one("Cole " * 8, cands) is None                    # too long to be a short reply
    assert cg.reply_names_one("", cands) is None and cg.reply_names_one(None, cands) is None


# ---- the agent, on both engines ---------------------------------------------------------------------------------------------
@pytest.fixture
def ag(monkeypatch, players):
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
    fakes = {"get_player_card": lambda kw: {"player_id": kw.get("player_id"), "status_word": "available"},
             "get_prediction": lambda kw: {"player_id": kw.get("player_id"), "span": 1.0},
             "search_news": lambda kw: {"results": [], "ambiguous_players": {}, "no_news_for": []},
             "compare_predictions": lambda kw: {"summary_plain": "A vs B for GW11", "gw": 11},
             "compare_players": lambda kw: {"direct_reply": "**Compared by code.**"},
             "set_my_squad": lambda kw: {"direct_reply": "**Preview.** Shall I make this change? Yes or No"}}
    for name, out in fakes.items():
        monkeypatch.setitem(agent.available_functions, name, (lambda n, f: (lambda **kw: calls.append((n, kw)) or f(kw)))(name, out))
    real = agent.available_functions["resolve_player"]
    monkeypatch.setitem(agent.available_functions, "resolve_player", lambda **kw: calls.append(("resolve_player", kw)) or real(**kw))
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
    """{tool_use_id: the tool result's content} over the turn's messages."""
    out = {}
    for m in msgs:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out[b["tool_use_id"]] = b["content"]
    return out


ASK = "Saka is out injured. Which Palmer do you mean: Cole Palmer (Chelsea) or Alex Palmer (Ipswich Town)?"


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_b3_while_palmer_is_unsettled_his_candidates_and_guesses_are_not_run(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r1", name="Saka"), _tool("resolve_player", "toolu_r2", name="Palmer")], "tool_use"),
        pf._Resp([_tool("get_player_card", "toolu_c1", player_id=12), _tool("get_prediction", "toolu_p1", player_id=154),
                  _tool("get_prediction", "toolu_p2", player_id=448)], "tool_use"),
        pf._Resp([_tool("resolve_player", "toolu_r3", name="Cole Palmer", club="Chelsea")], "tool_use"),
        pf._Resp([_tool("compare_players", "toolu_cp", player_ids=[12, 154])], "tool_use"),
        pf._Resp([pf._Block("text", text=ASK)], "end_turn")])
    answer, msgs = _turn(ag, engine, SAKA_PALMER, [])
    assert answer == ASK
    ran = [(n, kw) for n, kw in ag._calls]
    assert ("get_player_card", {"player_id": 12}) in ran                     # the clear name is answered
    assert not any(n in ("get_prediction", "compare_players") for n, _kw in ran)
    res = _results(msgs)
    for tid in ("toolu_p1", "toolu_p2", "toolu_cp"):
        note = res[tid]
        assert note.startswith("Not run: the user has not said which Palmer they mean") and "Ask the user which one" in note
        assert "Cole Palmer (Chelsea" in note and "Alex Palmer (Ipswich Town" in note
        assert note not in answer
    third = ast.literal_eval(res["toolu_r3"])
    assert third["ambiguous"] is True and third["unsettled_lookup"]["unwritten"] == ["cole"]
    assert [s for s in ag.LAST_TURN["skipped_rounds"] if s["why"] == "unsettled"] == [
        {"why": "unsettled", "calls": 1, "tools": ["get_prediction"]}, {"why": "unsettled", "calls": 1, "tools": ["get_prediction"]},
        {"why": "unsettled", "calls": 1, "tools": ["compare_players"]}]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_b3b_a_known_id_runs_and_an_unsettled_name_in_another_message_holds_nothing(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r1", name="Martinez"), _tool("resolve_player", "toolu_r2", name="Haaland")], "tool_use"),
        pf._Resp([_tool("get_player_card", "toolu_c1", player_id=411)], "tool_use"),
        pf._Resp([_tool("get_prediction", "toolu_p1", player_id=411)], "tool_use"),
        pf._Resp([pf._Block("text", text="Haaland is fine. Which Martinez do you mean?")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Is Martinez worth a punt, and how's Haaland doing?", [])
    assert [n for n, _kw in ag._calls] == ["resolve_player", "resolve_player", "get_player_card", "get_prediction"]
    assert not [s for s in ag.LAST_TURN["skipped_rounds"] if s["why"] == "unsettled"]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_b3c_an_id_as_text_is_held_and_captain_pick_reads_the_squad_itself(ag, monkeypatch, engine):
    monkeypatch.setitem(ag.available_functions, "captain_pick", lambda **kw: ag._calls.append(("captain_pick", kw)) or {"direct_reply": "**Captain by code.**"})
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r1", name="Palmer"), _tool("resolve_player", "toolu_r2", name="Haaland")], "tool_use"),
        pf._Resp([_tool("get_prediction", "toolu_p1", player_id="154")], "tool_use"),
        pf._Resp([_tool("captain_pick", "toolu_cp", player_ids=[154, 411])], "tool_use")])
    answer, msgs = _turn(ag, engine, "Palmer or Haaland for captain?", [])
    assert _results(msgs)["toolu_p1"].startswith("Not run: the user has not said which Palmer they mean")
    assert answer == "**Captain by code.**" and ("captain_pick", {"player_ids": [154, 411]}) in ag._calls


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_b4_news_for_a_candidate_under_words_the_user_did_not_write_is_not_run(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r1", name="Palmer")], "tool_use"),
        pf._Resp([_tool("search_news", "toolu_n1", players=["Cole Palmer"], query="Cole Palmer fitness availability GW11"),
                  _tool("search_news", "toolu_n2", players=["Palmer"], query="Palmer news"),
                  _tool("search_news", "toolu_n3", players=["Saka"], query="Saka injury fitness update")], "tool_use"),
        pf._Resp([pf._Block("text", text="Which Palmer do you mean?")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Tell me about Saka and Palmer.", [])
    news = [kw for n, kw in ag._calls if n == "search_news"]
    assert [kw["players"] for kw in news] == [["Palmer"], ["Saka"]]
    assert _results(msgs)["toolu_n1"].startswith("Not run: the user has not said which Palmer they mean")


def test_b5_set_my_squad_refuses_an_incoming_candidate_and_never_a_kept_one(players, monkeypatch):
    import squad_store
    squad = [12, 26, 411, 427, 366, 154, 4, 102, 343, 60, 28, 380, 515, 379, 185]
    monkeypatch.setattr(mt, "_squad_owner", lambda uid: uid)
    monkeypatch.setattr(squad_store, "read_active", lambda owner, conn=None: {"version_id": 1, "squad_json": {"players": [{"element": e} for e in squad]}})
    monkeypatch.setattr(mt, "_current_gw", lambda: (_ for _ in ()).throw(RuntimeError("stop here: the check ran first")))
    _begin("Swap Barry for Palmer, and is Martinez worth it?")
    try:
        mt.resolve_player("Palmer")
        mt.resolve_player("Martinez")
        incoming = [e for e in squad if e != 185] + [301]                        # Sakamoto out, Alex Palmer in
        out = mt.set_my_squad(player_ids=incoming, captain_id=411, vice_id=12, bench_order_ids=[28, 60, 343, 185])
        assert out["error"].startswith("Not run: the user has not said which Palmer they mean") and out["unsettled_name"] == "Palmer"
        kept = [e for e in squad if e != 185] + [448]                            # Cole Palmer (154) and Martinez (28) are kept
        out = mt.set_my_squad(player_ids=kept, captain_id=154, vice_id=12, bench_order_ids=[28, 60, 343, 448])
        assert "the check ran first" in out["error"] and "unsettled_name" not in out   # past the check, to the gameweek read
    finally:
        turn_context.end()


HISTORY = [{"role": "user", "content": "Tell me about Palmer."},
           {"role": "assistant", "content": [{"type": "text", "text": "Which Palmer do you mean: Cole Palmer (Chelsea) or Alex Palmer (Ipswich Town)?"}]}]


@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("lookup", ["Palmer", "Cole Palmer"])
def test_b6_the_next_message_settles_it(ag, monkeypatch, engine, lookup):
    _script(ag, monkeypatch, [pf._Resp([_tool("resolve_player", "toolu_r1", name=lookup)], "tool_use"),
                              pf._Resp([_tool("get_player_card", "toolu_c1", player_id=154)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Cole Palmer is fit.")], "end_turn")])
    answer, msgs = _turn(ag, engine, "Cole", [dict(m) for m in HISTORY])
    res = _results(msgs)
    first = ast.literal_eval(res["toolu_r1"])
    assert first["ambiguous"] is False and first["matches"][0]["player_id"] == 154
    assert ("get_player_card", {"player_id": 154}) in ag._calls and answer == "Cole Palmer is fit."


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_b7_a_draft_turn_holds_and_blocks_nothing(ag, monkeypatch, engine):
    import draft_tools
    monkeypatch.setattr(draft_tools, "resolve_in_draft", lambda d, name, cands, out: out)
    _script(ag, monkeypatch, [pf._Resp([_tool("resolve_player", "toolu_r1", name="Palmer")], "tool_use"),
                              pf._Resp([_tool("get_prediction", "toolu_p1", player_id=154)], "tool_use"),
                              pf._Resp([pf._Block("text", text="ok")], "end_turn")])
    _turn(ag, engine, "Tell me about Palmer.", [], thread={"draft": DRAFT})
    assert ("get_prediction", {"player_id": 154}) in ag._calls
