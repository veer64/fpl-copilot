"""Prompt R3f (16 Nov 2026; USER DECISION): two name-handling fixes -- code reads a name the model shortened back from the user's
own words, and the model answers what is clear and asks only what is not.

Measured before (eval/reports/r3e_answers.md): Set B case 8, 3 runs of 3 -- "Ditch Ibrahim Sangare for Yarmoliuk." -> the model
looked up "Sangare" alone (two players: Ibrahim, Nott'm Forest; Mamadou, Brentford) and asked "which Sangaré do you mean?" though
the user had typed "Ibrahim"; Set C2 -- "Tell me about Saka and Palmer." -> asked which Palmer (right) but said nothing about
Saka, whose lookup had resolved.

N1  THE NAME TABLE (written before the code): (the name the model passed, the turn's own user message) -> the player the lookup
    returns, or "ambiguous". When the lookup matches more than one player and the message names EXACTLY ONE of them by a fuller
    form -- the players_live name, FPL's web_name, the web_name without its initial, or the first + last word of a longer name;
    accent- and case-folded, whole words, longest first -- that player is the match; when it names none of them, or more than
    one, nothing changes (an ambiguous lookup stays ambiguous: the 2026-10-09 lock);
N2  the resolution's shape: one player at the top with his id, ambiguous false, no "ask which" action or note, the tied
    candidates gone, and a trace note `resolved_from_message` ("resolved from the user's words", the words, the query);
N3  outside a turn (no message) and on a draft chat's turn nothing changes;
N4  on both engines, through the agent: the lookup the model shortened returns the user's player;
N5  the comparison guard counts a player resolved this way;
R1  the routing sentence -- answer for every player that resolved, ask only which of the ambiguous ones -- in resolve_player's
    description and the prompt's section 1c.
No model, no network, no database: players_live and the web names are a fixed slice, as build 78 has them."""
import ast
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
import model_tools as mt                                                   # noqa: E402
import payload_fixture as pf                                               # noqa: E402
import turn_context                                                        # noqa: E402

# (element, players_live name, web_name, position, club, price in tenths, status) -- build 78's own, plus two made-up rows
# (950, 951) for a shared surname with no display-name winner
PLAYERS = [(488, "Ibrahim Sangaré", "I.Sangaré", "MID", "Nott'm Forest", 47, "a"),
           (565, "Mamadou Sangaré", "M.Sangaré", "MID", "Brentford", 54, "a"),
           (154, "Cole Palmer", "Palmer", "MID", "Chelsea", 98, "a"),
           (301, "Alex Palmer", "Palmer", "GK", "Ipswich Town", 40, "a"),
           (12, "Bukayo Saka", "Saka", "MID", "Arsenal", 94, "i"),
           (185, "Tatsuhiro Sakamoto", "Sakamoto", "MID", "Coventry City", 50, "a"),
           (4, "Gabriel dos Santos Magalhães", "Gabriel", "DEF", "Arsenal", 62, "a"),
           (18, "Gabriel Martinelli Silva", "Martinelli", "MID", "Arsenal", 66, "u"),
           (27, "Gabriel Fernando de Jesus", "G.Jesus", "FWD", "Arsenal", 64, "u"),
           (6, "William Saliba", "Saliba", "DEF", "Arsenal", 60, "a"),
           (102, "Yehor Yarmoliuk", "Yarmoliuk", "MID", "Brentford", 47, "a"),
           (142, "Reece James", "James", "DEF", "Chelsea", 57, "a"),
           (343, "Daniel James", "James", "MID", "Leeds", 55, "a"),
           (950, "Bruno Borges Fernandes", "B.Fernandes", "MID", "Man Utd", 116, "a"),
           (951, "Matheus Fernandes", "M.Fernandes", "MID", "Southampton", 50, "a"),
           (109, "Bart Verbruggen", "Verbruggen", "GK", "Brighton", 47, "a")]

AMB = "ambiguous"
# (the name the model passed, the turn's own user message, the player returned -- or AMB) -- written before the code
TABLE = [
    ("Sangare", "Ditch Ibrahim Sangare for Yarmoliuk.", 488),               # R3e's B8
    ("Palmer", "Tell me about Saka and Palmer.", AMB),                     # R3e's C2: the message names no Palmer in full
    ("Palmer", "Is Cole Palmer fit?", 154),
    ("Palmer", "Alex Palmer or Verbruggen?", 301),
    ("Sangaré", "mamadou sangare", 565),                                   # accents and case folded
    ("Sangare", "Ibrahim Sangare and Mamadou Sangare", AMB),               # both named: still ambiguous
    ("Gabriel", "Is Gabriel fit?", 4),                                     # the display-name winner, unchanged
    ("Gabriel", "Gabriel or Saliba?", 4),                                  # unchanged
    ("Gabriel", "Is Gabriel Jesus fit?", 27),                              # first + last word of "Gabriel Fernando de Jesus"
    ("Palmer", "Tell me about Palmer.", AMB),
    ("Palmer", "Is A.Palmer worth a punt?", AMB),                          # both web names are "Palmer": an initial is no form
    ("Sangare", "Is I.Sangaré fit?", 488),
    ("Sangare", "Sangare out, Yarmoliuk in.", AMB),                        # the surname alone
    ("Palmer", "COLE PALMER vs Saka", 154),
    ("Palmer", "Is Colepalmer fit?", AMB),                                 # whole words only
    ("Palmer", "Cole Palmer or Alex Palmer?", AMB),
    ("Palmer", "Is Ibrahim Sangare fit?", AMB),                            # names neither candidate
    ("Sangare", "Ibrahim Sangaré", 488),
    ("James", "Is Daniel James fit?", 343),                                # both are "James" on FPL: the full name decides
    ("James", "Is Reece James fit?", 142),
    ("Fernandes", "Is Bruno Fernandes fit?", 950),                         # first + last word of "Bruno Borges Fernandes"
    ("Fernandes", "Fernandes this week?", AMB),
    ("Saka", "Tell me about Saka and Palmer.", 12),                        # one best match: unchanged
    ("Saka", "Is Sakamoto better than Saka?", 12),                         # both named: unchanged (the best match)
    ("Palmer", "Is Palmer as good as Cole Palmer's numbers say?", 154),    # one full form, one bare surname
]


@pytest.fixture
def players(monkeypatch):
    live = [{"element": e, "name": n, "position": pos, "team": club, "price_tenths": pr, "status": st}
            for e, n, _w, pos, club, pr, st in PLAYERS]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: live)
    monkeypatch.setattr(mt, "_web_names", lambda: {e: w for e, _n, w, *_r in PLAYERS})
    return live


def _resolve(name, message, draft=None):
    turn_context.begin("r3f" + "t" * 29, user_message=message, draft=draft) if draft else turn_context.begin("r3f" + "t" * 29, user_message=message)
    try:
        return mt.resolve_player(name)
    finally:
        turn_context.end()


def _picked(out):
    if out["ambiguous"]:
        return AMB
    return out["matches"][0]["player_id"]


@pytest.mark.parametrize("name,message,want", TABLE, ids=[f"{i:02d}" for i in range(1, len(TABLE) + 1)])
def test_n1_the_name_table(players, name, message, want):
    assert _picked(_resolve(name, message)) == want


def test_n1b_the_table_is_at_least_15_rows_both_ways():
    assert len(TABLE) >= 15 and sum(1 for *_x, w in TABLE if w == AMB) >= 5 and sum(1 for *_x, w in TABLE if w != AMB) >= 5


def test_n2_the_resolutions_shape(players):
    before = mt.resolve_player("Sangare")                                  # no turn: R3e's answer
    assert before["ambiguous"] is True and before.get("action") == "ask the user which one"
    assert all("player_id" not in m for m in before["matches"]) and "resolved_from_message" not in before
    out = _resolve("Sangare", "Ditch Ibrahim Sangare for Yarmoliuk.")
    assert out["ambiguous"] is False and "action" not in out
    assert [m["player_id"] for m in out["matches"]] == [488] and out["matches"][0]["name"] == "Ibrahim Sangaré"
    assert out["resolved_from_message"] == {"why": "resolved from the user's words", "words": "ibrahim sangare", "query": "Sangare",
                                            "candidates": 2}
    assert "ask which" not in (out["note"] or "") and out["total_matches"] == 1
    jesus = _resolve("Gabriel", "Is Gabriel Jesus fit?")
    assert jesus["matches"][0]["player_id"] == 27 and 4 not in [m.get("player_id") for m in jesus["matches"]]
    assert jesus["resolved_from_message"]["words"] == "gabriel jesus"
    same = _resolve("Gabriel", "Is Gabriel fit?")                         # the user's player was already the answer
    assert "resolved_from_message" not in same and same == mt.resolve_player("Gabriel")
    amb = _resolve("Palmer", "Tell me about Saka and Palmer.")
    assert amb == mt.resolve_player("Palmer")                              # nothing changes at all


def test_n3_outside_a_turn_and_on_a_draft_turn_nothing_changes(players, monkeypatch):
    assert turn_context.user_message() is None
    assert mt.resolve_player("Sangare")["ambiguous"] is True
    import draft_tools
    monkeypatch.setattr(draft_tools, "resolve_in_draft", lambda d, name, cands, out: out)
    out = _resolve("Sangare", "Ditch Ibrahim Sangare for Yarmoliuk.", draft={"user_id": 10001, "draft_key": 800_000_001})
    assert out["ambiguous"] is True and "resolved_from_message" not in out


def test_n5_the_comparison_guard_counts_a_player_resolved_this_way(players):
    out = _resolve("Palmer", "Is Cole Palmer or Saka the better pick?")
    assert cg.resolved_players([("resolve_player", {"name": "Palmer"}, out)]) == {154}


def test_n6_the_pure_reading():
    ps = [(e, n, w) for e, n, w, *_r in PLAYERS if e in (488, 565)]
    assert cg.named_one("Ditch Ibrahim Sangare for Yarmoliuk.", ps) == (488, "ibrahim sangare")
    assert cg.named_one("Sangare out", ps) is None and cg.named_one("", ps) is None and cg.named_one(None, ps) is None
    assert cg.named_one("Ibrahim Sangare and Mamadou Sangare", ps) is None


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
    monkeypatch.setattr(agent, "_guard_names", lambda: {})
    return agent


def _turn(ag, engine, question, history):
    if engine == "loop":
        return ag.run_agent(question, history)
    import agent_graph
    import tracing
    st = ag._begin_turn(question, history, engine="graph")
    try:
        out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
    finally:
        tracing.close_open()
        turn_context.end()
    return out["rendered"], st["messages"]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_n4_the_lookup_the_model_shortened_returns_the_users_player(ag, monkeypatch, engine):
    script = pf._Script([pf._Resp([pf._Block("tool_use", name="resolve_player", input={"name": "Sangare"}, id="toolu_r1")], "tool_use"),
                         pf._Resp([pf._Block("text", text="Got him.")], "end_turn")])
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    answer, msgs = _turn(ag, engine, "Ditch Ibrahim Sangare for Yarmoliuk.", [])
    res = ast.literal_eval(msgs[2]["content"][0]["content"])              # the agent sends str(result)
    assert answer == "Got him." and res["ambiguous"] is False and res["matches"][0]["player_id"] == 488
    assert res["resolved_from_message"]["why"] == "resolved from the user's words"


SENTENCE = ("When some of the names the user gives resolve and others are ambiguous, answer for every player that resolved and, in "
            "the same reply, ask only which of the ambiguous ones the user means.")


def test_r1_answer_what_is_clear_ask_only_what_is_not(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    importlib.reload(agent)
    d = next(t for t in agent.tools_schema if t["name"] == "resolve_player")["description"]
    assert d.count(SENTENCE) == 1
    p = agent.SYSTEM_PROMPT
    sec = p[p.index("# 1c."):p.index("# 2. What you do not know")]
    assert sec.count(SENTENCE) == 1
    assert agent.DRAFT_SYSTEM_PROMPT.count(SENTENCE) == 0                 # a draft chat's frozen prompt is untouched
