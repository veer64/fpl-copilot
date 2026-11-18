"""Prompt F2 E (18 Nov 2026; USER DECISION): return dates -- supply the fact, then check the reply.

Measured before: R3g's prompt sentence ("Never turn a reported absence ... into a return date or month") did not hold -- of the four
runs of F1's gate that quoted Saka's "up to eight weeks" (BBC, 23 Oct), two turned it into a month (F1 L1 run 2 "around late
December", L7 run 2 "well into December"; C:\\dev\\fpl-backups\\f1_files\\gate\\results_L.json), and R3f's T2 did it twice
(C:\\dev\\fpl-backups\\r3f_files\\gate\\results_B.json).

R1  the timings a sentence carries: months, dates, gameweeks, calendar anchors; "may" the verb is no month;
R2  the sources: gameweeks and day-and-month dates from any tool result of the turn; a month or an anchor only from the source's own
    words (FPL's news, a report's headline or text) -- "as of Sun 15 Nov" never sources "November";
R3  the availability line: FPL's status and news verbatim with its day, plus the used report's own sentence and date -- nothing
    worked out; a report's sentence is its own words (its search tag dropped);
R4  THE SLIPS (written before the code): the exact sentences of F1 L1 run 2, F1 L7 run 2 and R3f T2 runs 2 and 3 are each replaced
    by Saka's availability line; the brief's anchors ("over Christmas", "the new year", "next month", "by GW15") too;
R5  LEFT UNTOUCHED: "Saka is out for up to eight weeks." (the source's duration); "Saka's December fixtures look kind." (not about
    his return); a return date the source itself gives (FPL's "Expected back 03 Jan"); a fit player; a reply with no absence;
    gameweeks the tools carry; a table row; "he" after another player is named;
R6  on both engines: the delivered reply carries the line (its citation rendered), the replacement is logged (LAST_TURN), the
    history keeps exactly what is sent, no second model call; a code-built reply is never checked; a draft turn is never checked;
R7  the supply: search_news' result carries a flagged player's availability line; the player card carries FPL's half.
No model, no network, no database: the players, their FPL flags and the news are fixed fakes, as build 78 has them."""
import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import availability_check as av                                            # noqa: E402
import comparison_guard as cg                                              # noqa: E402
import payload_fixture as pf                                               # noqa: E402
import turn_context                                                        # noqa: E402

UPDATED = datetime(2026, 11, 15, 11, 2, 15, tzinfo=timezone.utc)
# element -> FPL's flag as players_live holds it on build 78 (Saka, Semenyo, Reece James injured; Haaland, Cole Palmer fit)
FLAGS = {12: {"name": "Bukayo Saka", "web_name": "Saka", "status": "i", "chance": 0, "news": "Thigh injury - Unknown return date", "updated_at": UPDATED},
         397: {"name": "Antoine Semenyo", "web_name": "Semenyo", "status": "i", "chance": 0, "news": "Knee injury - Unknown return date", "updated_at": UPDATED},
         142: {"name": "Reece James", "web_name": "James", "status": "i", "chance": 0, "news": "Knee injury - Unknown return date", "updated_at": UPDATED},
         411: {"name": "Erling Haaland", "web_name": "Haaland", "status": "a", "chance": None, "news": "", "updated_at": UPDATED},
         154: {"name": "Cole Palmer", "web_name": "Palmer", "status": "a", "chance": None, "news": "", "updated_at": UPDATED}}
FORMS = cg.name_forms([(e, f["name"], f["web_name"]) for e, f in FLAGS.items()])
ABSENT = {e for e, f in FLAGS.items() if f["status"] != "a"}
BBC = {"id": "c1418", "source": "BBC Sport", "headline": "Arsenal fear Saka could be out for two months", "url": "https://www.bbc.co.uk/sport/1",
       "date": "2026-10-23", "date_words": "Fri 23 Oct 2026", "date_basis": "publisher", "age": "25 days ago", "about_requested_player": True,
       "players": ["Saka"], "text": "[BBC Sport | 2026-10-23 14:09Z] Arsenal fear Saka could be out for two months\nArsenal fear Bukayo "
       "Saka could be out for up to eight weeks with a quadriceps injury."}
CARD = {"name": "Bukayo Saka", "player_id": 12, "status": "i", "chance": 0, "news": "Thigh injury - Unknown return date",
        "availability": {"status": "i", "status_word": "injured", "news": "Thigh injury - Unknown return date",
                         "as_of_words": "Sun 15 Nov 2026 11:02 UTC", "chance_words": "chance of playing in GW11: 0%, FPL as of Sun 15 Nov 2026"}}
SAKA_LINE = ('Bukayo Saka: FPL lists him as injured, "Thigh injury - Unknown return date" (FPL, Sun 15 Nov 2026). BBC Sport reported on '
             'Fri 23 Oct 2026: "Arsenal fear Saka could be out for two months" [c1418].')


def _names(sentence):
    out = set()
    for _w, ids in cg._spans_words(sentence, FORMS):
        if len(ids) == 1:
            out |= set(ids)
    return out


def _corpus(all_text=None, source_words=None):
    return av.corpus(str([CARD, {"results": [BBC]}]) if all_text is None else all_text,
                     [CARD["news"], BBC["headline"], BBC["text"]] if source_words is None else source_words)


def _check(reply, c=None):
    return av.check(reply, _names, ABSENT, c or _corpus(), lambda e, s: f"<<line {e}>>")


# ---- R1 / R2 / R3 --------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    ("back in late December", [("month", 12)]), ("by GW15", [("gw", 15)]), ("GW11–16", [("gw", 11), ("gw", 16)]),
    ("on 3 January", [("date", (3, 1))]), ("Expected back 03 Jan", [("date", (3, 1))]), ("January 3rd", [("date", (3, 1))]),
    ("over Christmas", [("anchor", "christmas")]), ("in the new year", [("anchor", "new year")]), ("next month", [("anchor", "next month")]),
    ("he may return soon", []), ("in May", [("month", 5)]), ("2026-10-23", [("date", (23, 10))]), ("up to eight weeks", []),
    ("gameweek 14", [("gw", 14)])])
def test_r1_the_timings_a_sentence_carries(text, want):
    assert [(k, key) for k, key, _w in av.timings(text)] == want


def test_r2_the_sources():
    c = _corpus()
    assert 11 in c["gw"] and (15, 11) in c["date"] and (23, 10) in c["date"]
    assert 11 not in c["month"] and 12 not in c["month"]                     # "as of Sun 15 Nov" sources no month
    c2 = av.corpus("", ["Hamstring injury - Expected back 03 Jan"])
    assert (3, 1) in c2["date"] and 1 in c2["month"]                          # a source's own date sources its month
    assert av.unsourced("back in late December", c) == [("month", 12, "December")]


def test_r3_the_availability_line():
    report = {"source": "BBC Sport", "date_words": "Fri 23 Oct 2026", "id": "c1418",
              "words": av.report_sentence(BBC["text"], BBC["headline"], {"saka", "bukayo"})}
    assert report["words"] == "Arsenal fear Saka could be out for two months"               # its own words, its tag dropped
    assert av.availability_line("Bukayo Saka", "injured", "Thigh injury - Unknown return date", "Sun 15 Nov 2026", report) == (
        'Bukayo Saka: FPL lists him as injured, "Thigh injury - Unknown return date" (FPL, Sun 15 Nov 2026). BBC Sport reported on '
        'Fri 23 Oct 2026: "Arsenal fear Saka could be out for two months" [c1418].')
    assert av.availability_line("Reece James", "injured", "Knee injury - Unknown return date", "Sun 15 Nov 2026") == (
        'Reece James: FPL lists him as injured, "Knee injury - Unknown return date" (FPL, Sun 15 Nov 2026).')
    assert av.report_sentence("Nothing about him.", "Arsenal round-up", {"saka"}) is None


# ---- R4: the slips, word for word -----------------------------------------------------------------------------------------------
F1_L1_R2 = ("Eight weeks from that report would put him around late December, though that's the report's words as of 23 Oct — there's "
            "been no more recent update to go on.")
F1_L7_R2 = "Eight weeks from 23 Oct points well into December — so there is a real chance he misses GW11 and several weeks beyond."
R3F_T2_R2 = ("BBC Sport reported on 23 Oct [c1440] that Arsenal feared he could be sidelined for up to eight weeks with a quadriceps injury "
             "sustained against Bayern Munich — if that timeline holds, he could be approaching a return in mid-to-late December, but FPL "
             "has not updated their flag to reflect any return window.")
R3F_T2_R3 = ("Eight weeks from that date would take us into late December, so there's no near-term return in sight — though that "
             "estimate is now 24 days old and there's been no update since.")
LEAD = "**Saka is injured.** BBC Sport reported on 23 Oct that he could be sidelined for **up to eight weeks** [c1418]."


@pytest.mark.parametrize("slip", [F1_L1_R2, F1_L7_R2, R3F_T2_R2, R3F_T2_R3], ids=["F1-L1-r2", "F1-L7-r2", "R3f-T2-r2", "R3f-T2-r3"])
def test_r4_the_slips_are_replaced(slip):
    reply = f"{LEAD} {slip}\n\nThe model gives him 0.34 expected points for GW11."
    out, rep = _check(reply)
    assert slip not in out and "December" not in out and out == f"{LEAD} <<line 12>>\n\nThe model gives him 0.34 expected points for GW11."
    assert rep == [{"element": 12, "sentence": slip, "timing": [w for _k, _key, w in av.unsourced(slip, _corpus())], "line": "<<line 12>>"}]


@pytest.mark.parametrize("slip", ["Saka could return over Christmas.", "He might be back in the new year.", "Saka could be back next month.",
                                  "Saka should be back by GW15.", "Saka is expected back on 12 December."])
def test_r4b_the_briefs_anchors(slip):
    out, rep = _check(f"Saka is injured. {slip}")
    assert out == "Saka is injured. <<line 12>>" and len(rep) == 1


# ---- R5: left untouched ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("reply", [
    "Saka is out for up to eight weeks.",
    "Saka's December fixtures look kind.",
    "FPL lists him as injured with a 0% chance of playing in GW11, as of Sun 15 Nov. Saka is injured.",
    "Saka is injured. BBC Sport reported on 23 Oct that he could be out for up to eight weeks [c1418].",
    "Haaland could be back to his best by December.",
    "Haaland is fine and plays Fulham in GW11.",
    "Saka is injured. Haaland is fit. He could be back in December.",
    "| Saka | back in late December |",
    "Saka is injured; the model carries the injury forward through GW11–16 with no return date."])
def test_r5_left_untouched(reply):
    c = _corpus(all_text=str([CARD, {"results": [BBC]}, {"horizon_gws": [11, 12, 13, 14, 15, 16]}]))
    assert _check(reply, c) == (reply, [])


def test_r5b_a_return_date_the_source_gives():
    c = av.corpus(str({"news": "Hamstring injury - Expected back 03 Jan"}), ["Hamstring injury - Expected back 03 Jan"])
    for reply in ("FPL expects Saka back on 3 January.", "Saka should return in early January, FPL says."):
        assert _check(reply, c) == (reply, [])


# ---- R6: the agent, on both engines ----------------------------------------------------------------------------------------------
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
    monkeypatch.setattr(agent, "_player_flags", lambda: FLAGS)
    calls = []
    fakes = {"resolve_player": lambda kw: {"matches": [{"player_id": 12, "name": "Bukayo Saka", "status": "i"}], "total_matches": 1, "ambiguous": False},
             "get_player_card": lambda kw: dict(CARD),
             "search_news": lambda kw: {"results": [dict(BBC)], "ambiguous_players": {}, "no_news_for": []},
             "compare_players": lambda kw: {"direct_reply": "**Saka could be back in late December, by code.**"}}
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


SLIP_REPLY = f"{LEAD} {F1_L1_R2}"


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_r6_the_delivered_reply_carries_the_line_and_the_replacement_is_logged(ag, monkeypatch, engine):
    script = _script(ag, monkeypatch, [
        pf._Resp([_tool("resolve_player", "toolu_r", name="Saka")], "tool_use"),
        pf._Resp([_tool("get_player_card", "toolu_c", player_id=12), _tool("search_news", "toolu_n", players=["Saka"], query="Saka injury")], "tool_use"),
        pf._Resp([pf._Block("text", text=SLIP_REPLY)], "end_turn")])
    answer, msgs = _turn(ag, engine, "When's Saka back?", [])
    assert len(script.calls) == 3                                                    # no second model call
    assert "December" not in answer and F1_L1_R2 not in answer
    assert SAKA_LINE.replace("[c1418]", "[1]") in answer and "\n\nSources\n[1] BBC Sport" in answer
    assert answer.count("[1]") == 3                                                  # the lead's, the line's, the Sources entry
    rep = ag.LAST_TURN["availability_replacements"]
    assert [(r["element"], r["sentence"], r["line"]) for r in rep] == [(12, F1_L1_R2, SAKA_LINE)]
    assert msgs[-1] == {"role": "assistant", "content": [{"type": "text", "text": f"{LEAD} {SAKA_LINE}"}]}   # the history: what was sent


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_r6b_a_clean_reply_and_a_code_built_one_are_untouched(ag, monkeypatch, engine):
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_c", player_id=12)], "tool_use"),
                              pf._Resp([pf._Block("text", text="Saka is out for up to eight weeks, BBC reported.")], "end_turn")])
    answer, _m = _turn(ag, engine, "When's Saka back?", [])
    assert answer == "Saka is out for up to eight weeks, BBC reported." and ag.LAST_TURN["availability_replacements"] == []
    _script(ag, monkeypatch, [pf._Resp([_tool("compare_players", "toolu_cp", player_ids=[12, 411])], "tool_use")])
    answer, _m = _turn(ag, engine, "Saka or Haaland?", [])
    assert answer == "**Saka could be back in late December, by code.**"            # code-built: never checked


def test_r6c_a_draft_turn_is_never_checked(ag, monkeypatch):
    monkeypatch.setitem(ag.DRAFT_FUNCTIONS, "explain_my_draft", lambda **kw: {"direct_reply": "x"})
    _script(ag, monkeypatch, [pf._Resp([_tool("get_player_card", "toolu_c", player_id=12)], "tool_use"),
                              pf._Resp([pf._Block("text", text=f"Saka is injured. {F1_L7_R2}")], "end_turn")])
    answer, _m = ag.run_agent("When's Saka back?", [], thread={"draft": {"user_id": 10001, "draft_key": 800_000_001}})
    assert F1_L7_R2 in answer


# ---- R7: the supply --------------------------------------------------------------------------------------------------------------
def test_r7_search_news_carries_a_flagged_players_line(ag, monkeypatch):
    monkeypatch.setattr(ag, "_search_news", lambda q, players, clubs: {"results": [dict(BBC)], "ambiguous_players": {}, "no_news_for": []})
    turn_context.begin("f2" + "e" * 30, user_message="When's Saka back, and how's Haaland?")
    try:
        out = ag.search_news("Saka injury", players=["Saka", "Haaland"])
    finally:
        turn_context.end()
    assert out["availability_lines"] == {"Saka": SAKA_LINE} and "a reported duration is not a return date" in out["availability_lines_note"]
    plain = ag.search_news("Saka injury", players=["Saka"])                          # outside a turn: the same supply
    assert plain["availability_lines"] == {"Saka": SAKA_LINE}


def test_r7b_the_player_card_carries_fpls_half(monkeypatch):
    import model_tools as mt
    row = {"element": 12, "name": "Bukayo Saka", "web_name": "Saka", "team": "Arsenal", "position": "MID", "status": "i", "chance": 0,
           "news": "Thigh injury - Unknown return date", "price_tenths": 94, "updated_at": UPDATED}
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [dict(row)])
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "_snapshot_news", lambda *a, **k: {})
    monkeypatch.setattr(mt, "_next_round_gw", lambda *a, **k: 11)
    monkeypatch.setattr(mt, "fpl_figure_note", lambda gw: None)
    monkeypatch.setattr(mt, "get_prediction", lambda *a, **k: {"error": "not in this test"})
    card = mt.get_player_card(12)
    assert card["availability"]["availability_line"] == 'Bukayo Saka: FPL lists him as injured, "Thigh injury - Unknown return date" (FPL, Sun 15 Nov 2026).'
