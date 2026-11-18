"""Prompt F2b (18 Nov 2026; USER DECISION): a return timing is sourced only by THAT player's sources.

Measured before: F2's gate, E3 runs 1 and 2 ("Is Semenyo worth keeping?"; C:\\dev\\fpl-backups\\f2_files\\gate\\results_L.json):
"...puts his earliest possible return somewhere around mid-to-late December" was left in both times, because the turn's news
carried an unrelated Man City line -- "Three Premier League games in December moved for TV coverage" -- and F2's check sourced a
month from ANY of the turn's news.

S1  F2's two E3 sentences, word for word, are replaced on both engines with the Man City headline in the turn's news;
S2  "covers GW11 through GW15 or so" is replaced with GW11 in a fixture list of the turn (and with FPL's own GW11 too: GW15 is in
    no source of his);
S3  kept: FPL's own "Expected back 03 Jan" for that player ("back on 3 January", "back in early January"); a news sentence naming
    him that says "back in early January"; a report's own date when it names him; the model's own prediction window;
S4  not kept: the same January in a sentence that does not name him; a gameweek outside a sentence about the model's predictions.
No model, no network, no database: the flags, the tools and the news are fixed fakes, as build 78 has them."""
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
UNKNOWN = "Knee injury - Unknown return date"


def _flags(news=UNKNOWN):
    return {397: {"name": "Antoine Semenyo", "web_name": "Semenyo", "status": "i", "chance": 0, "news": news, "updated_at": UPDATED},
            411: {"name": "Erling Haaland", "web_name": "Haaland", "status": "a", "chance": None, "news": "", "updated_at": UPDATED}}


FORMS = cg.name_forms([(e, f["name"], f["web_name"]) for e, f in _flags().items()])
# the club page F2's E3 search returned (shortened): his own line, and the unrelated December line
CITY = {"id": "c2001", "source": "Man City official site", "headline": "City ring the changes for AEK Athens clash",
        "url": "https://www.mancity.com/news/1", "date": "2026-10-20", "date_words": "Tue 20 Oct 2026", "date_basis": "publisher",
        "players": ["Semenyo"], "text": "[Man City official site | 2026-10-20] City ring the changes for AEK Athens clash\n"
        "Semenyo out for eight weeks, says Maresca\nThree Premier League games in December moved for TV coverage"}
MATCHDAY = {"id": "c2002", "source": "Man City official site", "headline": "Man City v AEK Athens - 20 Oct 2026", "url": "https://www.mancity.com/matchday",
            "date": "2026-10-21", "date_words": "Wed 21 Oct 2026", "date_basis": "publisher", "players": ["Semenyo"],
            "text": "Antoine Semenyo is unavailable for selection, facing eight weeks on the sidelines.\nThree Premier League games in "
                    "December moved for TV coverage"}


def _card(news=UNKNOWN):
    return {"name": "Antoine Semenyo", "player_id": 397, "status": "i", "chance": 0, "news": news,
            "availability": {"status": "i", "status_word": "injured", "news": news, "as_of_words": "Sun 15 Nov 2026 11:02 UTC",
                             "chance_gameweek": 11, "chance_words": "chance of playing in GW11: 0%, FPL as of Sun 15 Nov 2026"},
            "prediction": {"predictions": [{"gw": g, "horizon_step": g - 11, "e_points": 0.32} for g in range(11, 17)]}}


FIXTURES = {"fixtures": [{"team": "Man City", "gw": 11, "opponent": "Fulham"}], "direct_reply_error": "a fixture list: GW11 Fulham"}
E3_R1 = ("Eight weeks from that injury announcement puts his earliest possible return somewhere around mid-to-late December, which "
         "likely covers GW11 through GW15 or so.")
E3_R2 = ("The Man City official site reported on 21 Oct that he was facing **eight weeks on the sidelines** [c2002] — which, counting "
         "from that date, puts a return somewhere around mid-to-late December at the earliest.")
REPLY_R1 = ("**Sell him.** The case is pretty clear-cut.\n\n**The news:** Man City's manager said around 20 Oct that Semenyo was facing "
            f"**eight weeks on the sidelines** [c2001]. {E3_R1} With no return date confirmed and the model giving him a 1% chance of "
            "starting across every gameweek through GW16, he is contributing essentially nothing to your squad right now.")
REPLY_R2 = ('**No, Semenyo is not worth keeping — sell him.**\n\nFPL lists him as injured, "Knee injury - Unknown return date," as of '
            f"Sunday 15 Nov. His chance of playing in GW11 is 0%. {E3_R2} That is not a return date; it's the words the manager used.")
LINE_CITY = ('Antoine Semenyo: FPL lists him as injured, "Knee injury - Unknown return date" (FPL, Sun 15 Nov 2026). Man City official '
             'site reported on Tue 20 Oct 2026: "Semenyo out for eight weeks, says Maresca" [c2001].')
LINE_MATCHDAY = ('Antoine Semenyo: FPL lists him as injured, "Knee injury - Unknown return date" (FPL, Sun 15 Nov 2026). Man City '
                 'official site reported on Wed 21 Oct 2026: "Antoine Semenyo is unavailable for selection, facing eight weeks on the '
                 'sidelines." [c2002].')


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
    monkeypatch.setattr(agent, "_player_flags", lambda: _flags())
    agent._fakes = {"resolve_player": lambda kw: {"matches": [{"player_id": 397, "name": "Antoine Semenyo", "status": "i"}],
                                                  "total_matches": 1, "ambiguous": False},
                    "get_player_card": lambda kw: _card(),
                    "search_news": lambda kw: {"results": [dict(CITY), dict(MATCHDAY)], "ambiguous_players": {}, "no_news_for": []},
                    "get_fixtures": lambda kw: dict(FIXTURES)}
    for name in agent._fakes:
        monkeypatch.setitem(agent.available_functions, name, (lambda n: (lambda **kw: agent._fakes[n](kw)))(name))
    return agent


def _script(ag, monkeypatch, responses):
    script = pf._Script(responses)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    return script


def _tool(tool, id_, **inp):
    return pf._Block("tool_use", name=tool, input=inp, id=id_)


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


def _semenyo_turn(ag, monkeypatch, engine, reply, extra=()):
    calls = [_tool("resolve_player", "toolu_r", name="Semenyo"), _tool("get_player_card", "toolu_c", player_id=397),
             _tool("search_news", "toolu_n", players=["Semenyo"], query="Semenyo injury")] + list(extra)
    _script(ag, monkeypatch, [pf._Resp(calls, "tool_use"), pf._Resp([pf._Block("text", text=reply)], "end_turn")])
    return _turn(ag, engine, "Is Semenyo worth keeping?", [])


# ---- S1 / S2: replaced ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("reply,slip,line", [(REPLY_R1, E3_R1, LINE_CITY), (REPLY_R2, E3_R2, LINE_MATCHDAY)], ids=["E3-r1", "E3-r2"])
def test_s1_f2s_e3_sentences_are_replaced_with_the_december_headline_present(ag, monkeypatch, engine, reply, slip, line):
    answer, msgs = _semenyo_turn(ag, monkeypatch, engine, reply)
    rep = ag.LAST_TURN["availability_replacements"]
    assert [(r["element"], r["sentence"], r["line"]) for r in rep] == [(397, slip, line)]
    assert "December" not in answer and slip not in msgs[-1]["content"][0]["text"] and line in msgs[-1]["content"][0]["text"]
    assert "Sell him" in answer or "not worth keeping" in answer                                # the question is still answered
    assert "With no return date confirmed and the model giving him a 1% chance" in answer or reply is REPLY_R2   # the model's window kept


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_s2_gw11_through_gw15_is_replaced_with_gw11_in_a_fixture_list(ag, monkeypatch, engine):
    slip = "Semenyo's layoff likely covers GW11 through GW15 or so."
    answer, _m = _semenyo_turn(ag, monkeypatch, engine, f"Semenyo is injured. {slip}", extra=[_tool("get_fixtures", "toolu_f", team="Man City")])
    rep = ag.LAST_TURN["availability_replacements"]
    assert [(r["sentence"], r["timing"]) for r in rep] == [(slip, ["GW15"])]   # GW11 is FPL's own chance gameweek; GW15 is in no source
    assert "GW15" not in answer


def test_s2b_the_pure_reading():
    fixture_blob = str(FIXTURES)                                      # GW11 in a fixture list: no source of his
    assert 11 in av.corpus(fixture_blob, [])["gw"]
    c = av.player_corpus([UNKNOWN, "Sun 15 Nov 2026"], av.name_sentences(CITY["text"], {"semenyo", "antoine"}), [CITY["date"]])
    assert 12 not in c["month"] and 11 not in c["gw"] and (20, 10) in c["date"] and (15, 11) in c["date"]
    names = lambda s: {397} if "Semenyo" in s or "Antoine" in s else set()               # noqa: E731
    out, rep = av.check("Semenyo's layoff likely covers GW11 through GW15 or so.", names, {397}, lambda e, s: c, lambda e, s: "<<line>>")
    assert out == "<<line>>" and rep[0]["timing"] == ["GW11", "GW15"]       # the fixture list's GW11 sources nothing for him


# ---- S3 / S4: kept, and not kept ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("engine", ["loop", "graph"])
@pytest.mark.parametrize("reply", ["FPL expects Semenyo back on 3 January.", "Semenyo should be back in early January, FPL says."])
def test_s3_fpls_own_expected_back_date_is_kept(ag, monkeypatch, engine, reply):
    monkeypatch.setattr(ag, "_player_flags", lambda: _flags("Knee injury - Expected back 03 Jan"))
    ag._fakes["get_player_card"] = lambda kw: _card("Knee injury - Expected back 03 Jan")
    answer, _m = _semenyo_turn(ag, monkeypatch, engine, reply)
    assert answer == reply and ag.LAST_TURN["availability_replacements"] == []


def test_s3b_a_news_sentence_naming_him_sources_its_own_timing_and_one_that_does_not_name_him_does_not():
    said = av.name_sentences("Semenyo could be back in early January, the club said.\nThree games in January moved for TV.", {"semenyo"})
    assert said == ["Semenyo could be back in early January, the club said."]
    names = lambda s: {397} if "Semenyo" in s else set()                                 # noqa: E731
    mine = av.player_corpus([UNKNOWN], said, ["2026-11-05"])
    reply = "Semenyo could be back in early January, the club said."
    assert av.check(reply, names, {397}, lambda e, s: mine, lambda e, s: "<<line>>") == (reply, [])
    other = av.player_corpus([UNKNOWN], [], [])                                          # January only in a line not naming him
    assert av.check(reply, names, {397}, lambda e, s: other, lambda e, s: "<<line>>")[0] == "<<line>>"


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_s3c_a_reports_own_date_and_the_models_window_are_kept_and_a_bare_gameweek_is_not(ag, monkeypatch, engine):
    reply = ("Semenyo is injured. The club reported on 20 Oct that he was out for eight weeks [c2001]. The model gives him a 1% chance "
             "of starting through GW16, so he is out of the reckoning. He should be back by GW15.")
    answer, _m = _semenyo_turn(ag, monkeypatch, engine, reply)
    rep = ag.LAST_TURN["availability_replacements"]
    assert [r["sentence"] for r in rep] == ["He should be back by GW15."]
    assert "The club reported on 20 Oct that he was out for eight weeks" in answer and "through GW16, so he is out" in answer


# ---- S5: what the replay over every saved reply showed (f2b_files\replay_check*.txt): kept, as they are no return timing ----------
def test_s5_a_timing_before_now_is_no_return_timing():
    names = lambda s: {397} if "Semenyo" in s or " he" in s else set()                   # noqa: E731
    none = av.player_corpus([UNKNOWN], [], [])
    for reply in ("Semenyo was ruled out before the GW9 match against Everton.",
                  "At 0% and with a two-month window reported in late October, Semenyo is out.",
                  "Semenyo has been out since 21 Oct."):
        assert av.check(reply, names, {397}, lambda e, s: none, lambda e, s: "<<line>>", today=(18, 11), next_gw=11) == (reply, [])
    assert av.check("Semenyo could be back in late December.", names, {397}, lambda e, s: none, lambda e, s: "<<line>>",
                    today=(18, 11), next_gw=11)[0] == "<<line>>"                          # a future month still is one
    assert av.is_past("date", (3, 1), today=(18, 11)) is False and av.is_past("month", 10, today=(18, 11)) is True


def test_s5b_a_time_of_day_is_no_date():
    assert [(k, key) for k, key, _w in av.timings("as of Sunday 15 Nov 11:02 UTC")] == [("date", (15, 11))]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_s5c_the_prediction_window_and_fpls_next_round_are_kept(ag, monkeypatch, engine):
    reply = ("Semenyo is injured. Across GW11–16, the total is around 0.3 points, driven by the slim chance he recovers. "
             "With a two-month layoff he is a significant doubt for GW11 at minimum.")
    ag._fakes["get_player_card"] = lambda kw: {**_card(), "availability": {}}            # no chance gameweek of his: the rows say GW11
    answer, _m = _semenyo_turn(ag, monkeypatch, engine, reply)
    assert ag.LAST_TURN["availability_replacements"] == [] and "Across GW11–16, the total" in answer


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_s4_a_fit_player_is_never_checked(ag, monkeypatch, engine):
    ag._fakes["resolve_player"] = lambda kw: {"matches": [{"player_id": 411, "name": "Erling Haaland", "status": "a"}], "total_matches": 1, "ambiguous": False}
    _script(ag, monkeypatch, [pf._Resp([_tool("resolve_player", "toolu_r", name="Haaland")], "tool_use"),
                              pf._Resp([pf._Block("text", text="Haaland is worth every penny; expect a big December run.")], "end_turn")])
    answer, _m = _turn(ag, engine, "Is Haaland worth his price?", [])
    assert answer == "Haaland is worth every penny; expect a big December run." and ag.LAST_TURN["availability_replacements"] == []
