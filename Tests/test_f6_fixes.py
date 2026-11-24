"""Prompt F6 (24 Nov 2026): two availability-check refinements (evidence: eval/reports/f4_fixes.md section 1 and findings 2-3).

R1  DEADLINE IN A RETURN CLAIM. F4 exempted the next deadline's gameweek and date everywhere. They count again inside a return claim
    about the player: a sentence that names him or says he/his/him, where a return word (back / return / fit / available /
    recover / ready ...) leads into "for" / "by" / "in time for" and then the deadline. Must catch "He'll be back for GW12" and
    "Sesko should be fit by 27 Nov". Must keep "You have 5 free transfers available for GW12", "Monitor him as the GW12 deadline
    approaches (Friday 27 Nov)" and F4 D2 r1's "The freshest update covering GW12 lands no later than Friday 27 Nov ...".
    - A negated or hedged claim ("won't be fit for GW12", "unlikely to be back by the 27 Nov deadline", "might be back for the GW12
      deadline") stays exempt: it gives no return timing, and F4's test_d2 / test_d3 pin exactly those.
    - Inside a claim, the deadline is sourced only by his own source words (FPL's news text, the reports naming him). Since run 91
      FPL's chance gameweek IS the deadline's (GW12), so "GW12" sits in every flagged player's corpus and would source every
      "back for GW12".
R2  "HE" IN A SOURCE. A source sentence with he/his/him and no player named counts as about him when the nearest earlier sentence
    of the same source that names a player names him alone. F4 D2 r2: "He'll not necessarily be on the pitch next week" [c1852]
    follows "On Sarr, it'll be touch and go ..." by five sentences that name nobody, so it sources Sarr's "next week" and the
    quoting sentence stays.
No model, no network, no database: the players, their FPL flags and the news are fixed fakes, as the laptop DB has them (build 86);
web names as FPL gives them ("Sarr", "Šeško") -- an initial such as "I.Sarr" would add the word "i" to his name words."""
import importlib
import inspect
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

UPDATED = datetime(2026, 11, 21, 10, 51, tzinfo=timezone.utc)
FLAGS = {439: {"name": "Benjamin Sesko", "web_name": "Šeško", "status": "i", "chance": 0, "news": "Shin injury - Unknown return date",
               "updated_at": UPDATED},
         208: {"name": "Ismaïla Sarr", "web_name": "Sarr", "status": "i", "chance": 0, "news": "Groin injury - Expected back 29 Nov",
               "updated_at": UPDATED},
         84: {"name": "Nathan Collins", "web_name": "Collins", "status": "i", "chance": 0, "news": "Knee injury - Expected back 2 Dec",
              "updated_at": UPDATED},
         206: {"name": "Takehiro Tomiyasu", "web_name": "Tomiyasu", "status": "i", "chance": 0, "news": "Knee injury - Unknown return date",
               "updated_at": UPDATED},
         223: {"name": "Jean-Philippe Mateta", "web_name": "Mateta", "status": "s", "chance": 0, "news": "Suspended until 2 Dec",
               "updated_at": UPDATED},
         600: {"name": "Pape Matar Sarr", "web_name": "P.M.Sarr", "status": "a", "chance": None, "news": "", "updated_at": UPDATED}}
FORMS = cg.name_forms([(e, f["name"], f["web_name"]) for e, f in FLAGS.items()])
ABSENT = {e for e, f in FLAGS.items() if f["status"] != "a"}
DEADLINE = (12, (27, 11))                                     # GW12, Fri 27 Nov 2026 18:30 UTC -- the next deadline on 24 Nov
BLOCK = ("## Now\n- Gameweeks: GW11 is the last finished gameweek; no gameweek is in progress; next deadline GW12, Friday "
         "2026-11-27 18:30 UTC.\n- Model updates: ...")
C1852 = {"id": "c1852", "source": "Crystal Palace official site", "headline": "Team news: Frank gives first update as Palace Manager",
         "date": "2026-11-19", "date_words": "Thu 19 Nov 2026", "players": ["Tomiyasu", "Sarr", "Mateta"],
         "text": ("[Crystal Palace official site | 2026-11-19] Team news: Frank gives first update as Palace Manager\nFrank confirmed that "
                  "Takehiro Tomiyasu and Ismaïla Sarr will be unable to return for the trip to the CBS Arena, but said the pair are both "
                  "working towards fitness.\n\"I can say that Tomiyasu will be back training next week,\" Frank said in his pre-match "
                  "press conference.\n\"On Sarr, it'll be touch and go when he can start training. It's a groin injury so you need to be "
                  "careful.\n\"You need to be aware with those injuries about how much you push. That could take a little longer time. "
                  "You need to make sure that you don't take two steps forward, to then take two steps back.\n\"This could take a little "
                  "longer. He'll not necessarily be on the pitch next week.\"\nForward Jean-Philippe Mateta also remains suspended for "
                  "Saturday's trip to the CBS Arena.")}
SARR_WORDS = {"sarr", "ismaila"}
HE_SENTENCE = "He'll not necessarily be on the pitch next week.\""
# F4 D2 r2, the sentence the check swapped for Sarr's line (C:\dev\fpl-backups\f4_files\gate\results_L.json, the raw model text)
D2_R2_QUOTE = ("Crystal Palace's manager Thomas Frank said on Thursday 19 Nov that Sarr \"will not necessarily be on the pitch next week\" "
               "and that the groin injury requires careful handling — \"you could take two steps forward, then two steps back\" [c1852].")
D2_R2 = ("**FPL's official flag** (as of Sat 21 Nov): Sarr is injured with a groin problem, 0% chance of playing, with an expected return "
         "date of **29 November** — two days *after* Friday's GW12 deadline [c1840].\n\nThe news backs this up. " + D2_R2_QUOTE +
         " There is no more recent update suggesting that has changed.")
# F4 D2 r1, the deadline-day sentence F4 kept (must stay)
D2_R1_UPDATE = ("**My advice: use that free transfer elsewhere.** The freshest update covering GW12 lands no later than Friday 27 Nov at "
                "17:00 UTC (90 mins before the deadline), with two further updates at 18:00 and 18:20 UTC — keep an eye on those in case "
                "FPL updates his flag before you submit, but don't plan around his return for this gameweek.")


SEEN = {208, 439, 84}                                         # the players the turn resolved (the agent's `seen`)


def _names(sentence):
    """As the agent's names(): exactly-one matches, or the one a turn resolved among several ("Sarr" -> Ismaila Sarr)."""
    out = set()
    for _w, ids in cg._spans_words(sentence, FORMS):
        if len(ids) == 1:
            out |= set(ids)
        elif len(set(ids) & SEEN) == 1:
            out |= set(ids) & SEEN
    return out


def _kw(fn, **kw):
    """Only the keywords `fn` takes -- so against the old code a test fails on what the check does, not on a TypeError."""
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kw.items() if k in params}


def _sentences_of(text, words, element):
    return av.name_sentences(text, words, **_kw(av.name_sentences, names=_names, element=element))


def _said(element):
    return _sentences_of(f"{C1852['headline']}\n{C1852['text']}", SARR_WORDS, 208) if element == 208 else []


def _corpus_for(chance_gw):
    def corpus(element, sentence):
        """As the agent builds it: his FPL words (news, as-of day, the chance's gameweek), the source sentences naming him and their
        dates, and the model's window GW11-16 for a sentence about the model's predictions."""
        f = FLAGS[element]
        about_model = av.MODEL_WORDS.search(sentence) or av.window_range(sentence, range(11, 17))
        return av.player_corpus([f["news"], "Sat 21 Nov 2026", f"GW{chance_gw}"], _said(element),
                                [C1852["date"], C1852["date_words"]] if element == 208 else [], range(11, 17) if about_model else ())
    return corpus


def _own_words(element):
    return av.player_corpus([FLAGS[element]["news"]], _said(element), ())


def _check(reply, chance_gw=11, news=None):
    flags = {e: dict(f, news=news) if news and e == 439 else f for e, f in FLAGS.items()}
    own = (lambda e: av.player_corpus([flags[e]["news"]], _said(e), ()))
    corpus = _corpus_for(chance_gw)
    if news:
        def corpus(element, sentence, base=corpus):                       # noqa: E306 -- his FPL news as the flag would carry it
            c = base(element, sentence)
            for k, key, _w in av.timings(news):
                c[k].add(key)
            return c
    return av.check(reply, _names, ABSENT, corpus, lambda e, s: f"<<line {e}>>", today=(24, 11), next_gw=chance_gw,
                    fpl_text=lambda e: flags[e]["news"], deadline=DEADLINE, **_kw(av.check, own_words=own))


# ---- R1: the deadline inside a return claim -------------------------------------------------------------------------------------
@pytest.mark.parametrize("chance_gw", [11, 12], ids=["chance-GW11 (laptop, build 86)", "chance-GW12 (production since run 91)"])
def test_r1_a_return_claim_for_the_deadline_is_caught(chance_gw):
    out, rep = _check("Benjamin Sesko is injured. He'll be back for GW12.", chance_gw)
    assert out == "Benjamin Sesko is injured. <<line 439>>" and [r["timing"] for r in rep] == [["GW12"]]
    out, rep = _check("Sesko should be fit by 27 Nov.", chance_gw)
    assert out == "<<line 439>>" and [r["timing"] for r in rep] == [["27 Nov"]]
    out, rep = _check("Sesko (shin) should be fit by 27 Nov.", chance_gw)                 # brackets do not split the clause
    assert out == "<<line 439>>" and [r["timing"] for r in rep] == [["27 Nov"]]
    for s in ("He should be available in time for the GW12 deadline.", "He'll be back for Friday 27 Nov.",
              "There is no update since 29 Oct, but he'll be fit for GW12."):
        out, rep = _check(f"Benjamin Sesko is injured. {s}", chance_gw)
        assert out == "Benjamin Sesko is injured. <<line 439>>" and len(rep) == 1, s


def test_r1b_the_claim_is_left_when_his_own_source_says_it():
    news = "Shin injury - Expected back 27 Nov"
    assert _check("Sesko should be fit by 27 Nov.", 12, news=news) == ("Sesko should be fit by 27 Nov.", [])


@pytest.mark.parametrize("reply", [
    "Nathan Collins is injured. You have 5 free transfers available for GW12, so there's room to act.",
    "- **Nathan Collins** is injured (0%).\n- You have **5 free transfers** available for GW12, so there's room to act.",
    "Benjamin Sesko is injured. Monitor him as the GW12 deadline approaches (Friday 27 Nov).",
    f"Ismaïla Sarr is injured, FPL expects him back on 29 Nov. {D2_R1_UPDATE}",
    "Benjamin Sesko is injured. He won't be back for GW12.",
    "Benjamin Sesko is injured. He is unlikely to be fit by 27 Nov.",
    "Benjamin Sesko is injured. He might be back for the GW12 deadline.",
    # found by the replay of F2 / F2b's saved replies (C:\dev\fpl-backups\f6_files\replay), deadline moved to GW12:
    "Benjamin Sesko is injured. In short: no return date has been given publicly, and nothing in the available information suggests "
    "he'll be back for GW12.",                                                       # F2 E4 r1: negated by "nothing"
    "Benjamin Sesko is injured. **The case for selling:** You have 5 free transfers available for GW12, so moving him costs "
    "nothing."])                                                                     # F2b E1 r2: "him" is in another clause
@pytest.mark.parametrize("chance_gw", [11, 12])
def test_r1c_everything_else_stays_exempt(reply, chance_gw):
    assert _check(reply, chance_gw) == (reply, [])


# ---- R2: "he" in a source -------------------------------------------------------------------------------------------------------
def test_r2_a_he_sentence_after_his_named_sentence_is_his():
    said = _said(208)
    assert HE_SENTENCE in said and any(s.startswith("\"On Sarr") for s in said)
    assert not any("Tomiyasu will be back training" in s for s in said)              # names another player, never his
    assert not any("Mateta" in s for s in said)
    assert av.name_sentences(f"{C1852['headline']}\n{C1852['text']}", SARR_WORDS) == [  # without `names`: exactly as before (F2b)
        s for s in said if set(av._fold(s).split()) & SARR_WORDS]


@pytest.mark.parametrize("text", [
    "Sarr and Tomiyasu are out. He will be back next week.",                         # the anchor names another player too
    "Sarr is out. Tomiyasu trained today. He will be back next week.",               # the last player named is another
    "Sarr is out. He and Mateta will be back next week.",                            # the he-sentence names another player
    "He will be back next week."])                                                   # nothing before it in this source
def test_r2b_otherwise_a_he_sentence_is_nobodys(text):
    assert not any("next week" in s for s in _sentences_of(text, SARR_WORDS, 208))


def test_r2c_f4_d2_r2s_quote_is_sourced():
    out, rep = _check(D2_R2)
    assert out == D2_R2 and rep == []
    old = av.check(D2_R2, _names, ABSENT,                                              # F4's sourcing: the he-sentence is not his
                   lambda e, s: av.player_corpus([FLAGS[e]["news"], "Sat 21 Nov 2026", "GW11"],
                                                 av.name_sentences(f"{C1852['headline']}\n{C1852['text']}", SARR_WORDS),
                                                 [C1852["date"], C1852["date_words"]]),
                   lambda e, s: f"<<line {e}>>", today=(24, 11), next_gw=11, fpl_text=lambda e: FLAGS[e]["news"], deadline=DEADLINE)
    assert [r["timing"] for r in old[1]] == [["next week"]]


# ---- both engines -----------------------------------------------------------------------------------------------------------------
@pytest.fixture
def ag(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AGENT_ENGINE", "loop")
    import agent
    importlib.reload(agent)
    for name in ("record_chat_usage", "_citation_check", "_numeric_check", "_fact_check_log"):
        monkeypatch.setattr(agent, name, lambda *a, **k: None)
    monkeypatch.setattr(agent, "_note_turn", lambda st, raw=None: None)
    monkeypatch.setattr(agent, "context_block", lambda now=None: BLOCK)
    monkeypatch.setattr(agent, "_guard_names", lambda: FORMS)
    monkeypatch.setattr(agent, "_player_flags", lambda: FLAGS)
    card = {"name": "Ismaïla Sarr", "player_id": 208, "status": "i", "chance": 0, "news": FLAGS[208]["news"],
            "availability": {"status": "i", "status_word": "injured", "news": FLAGS[208]["news"], "as_of_words": "Tue 24 Nov 2026 21:20 UTC",
                             "chance_gameweek": 12, "chance_words": "chance of playing in GW12: 0%, FPL as of Tue 24 Nov 2026"}}
    fakes = {"resolve_player": lambda kw: {"matches": [{"player_id": 208, "name": "Ismaïla Sarr", "status": "i"}],
                                           "total_matches": 1, "ambiguous": False},
             "get_player_card": lambda kw: dict(card),
             "search_news": lambda kw: {"results": [dict(C1852)], "ambiguous_players": {}, "no_news_for": []}}
    for name, f in fakes.items():
        monkeypatch.setitem(agent.available_functions, name, (lambda fn: (lambda **kw: fn(kw)))(f))
    return agent


def _turn(ag, monkeypatch, engine, reply):
    script = pf._Script([pf._Resp([pf._Block("tool_use", name="resolve_player", input={"name": "Ismaïla Sarr"}, id="toolu_r"),
                                   pf._Block("tool_use", name="get_player_card", input={"player_id": 208}, id="toolu_c"),
                                   pf._Block("tool_use", name="search_news", input={"players": ["Ismaïla Sarr"], "query": "Sarr fit"},
                                             id="toolu_n")], "tool_use"),
                         pf._Resp([pf._Block("text", text=reply)], "end_turn")])
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    question = "Will Ismaïla Sarr be fit for the deadline?"
    if engine == "loop":
        answer, _m = ag.run_agent(question, [])
    else:
        import agent_graph
        import tracing
        st = ag._begin_turn(question, [], engine="graph")
        try:
            out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
        finally:
            tracing.close_open()
            turn_context.end()
        answer = out["rendered"]
    return answer


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_r3_on_both_engines(ag, monkeypatch, engine):
    answer = _turn(ag, monkeypatch, engine, D2_R2)                                     # R2: the quote stays
    assert "will not necessarily be on the pitch next week" in answer and ag.LAST_TURN["availability_replacements"] == []
    answer = _turn(ag, monkeypatch, engine, "Ismaïla Sarr is injured. He'll be back for GW12.")   # R1, chance gameweek GW12
    assert "back for GW12" not in answer and [r["timing"] for r in ag.LAST_TURN["availability_replacements"]] == [["GW12"]]
    answer = _turn(ag, monkeypatch, engine, f"Ismaïla Sarr is injured. {D2_R1_UPDATE}")       # the deadline-day sentence stays
    assert "The freshest update covering GW12" in answer and ag.LAST_TURN["availability_replacements"] == []
