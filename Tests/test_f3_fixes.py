"""Prompt F3 (24 Nov 2026): fix batch F3 -- fix E's side effects (E1) and the five logged model slips (S1-S5). Supply the fact;
never ban words.

E1  (handoff 23 Nov §2.3; the owner: "no swap when FPL's text is already in the reply; replace only the timing phrase"). Measured
    (C:\\dev\\fpl-backups\\f2b_files\\gate\\replies_L.md): Semenyo run 1's second replacement swallowed "...frees up a slot that is
    currently dead weight for at least the next month of fixtures" with its free-transfer advice and his line showed twice; run 2's
    line repeated the sentence before it; F2's smoke had "...a dead squad slot through December is significant" swapped for a
    second copy of the line. Now: FPL's words already in the reply (or his line already swapped in) -> only the timing goes
    (a later dash clause, a trailing ", which/so ..." clause, a time adjunct), or the sentence when the timing is all it says.
    FPL's words not there -> the swap, as before (F2's R4 tests pin it).
S1  "At £4.7m he's among the cheapest in the game" (R3f P4) -> the card's price_rank: how many players in the game and in his
    position cost less / more / the same, cheapest to dearest.
S2  "He's averaging about 4.0 pts/gw across the six gameweeks" (R3f P1) -> the prediction's average_per_gameweek.
S3  "The GW11 and GW13 fixtures look his strongest (4.19 and 4.69)" with GW16 4.34 above GW11 (F1 L8) -> gameweeks_best_first.
S4  "He sells for £8.2m (he was £8.4m at purchase based on the news ...)" for a player the user does not own (F2 smoke, user 1)
    -> the card's your_squad: in the squad with bought at / now / sells for, or not in it.
S5  "That eight-week window, if it ran from late October, would only be expiring around now" (F2 E2 r2) -> fix E reads
    "around now" as a return timing like any other anchor.
No model, no network, no database: the flags, the tools, the squad and the news are fixed fakes."""
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
FLAGS = {397: {"name": "Antoine Semenyo", "web_name": "Semenyo", "status": "i", "chance": 0, "news": UNKNOWN, "updated_at": UPDATED},
         12: {"name": "Bukayo Saka", "web_name": "Saka", "status": "i", "chance": 0, "news": "Thigh injury - Unknown return date",
              "updated_at": UPDATED},
         411: {"name": "Erling Haaland", "web_name": "Haaland", "status": "a", "chance": None, "news": "", "updated_at": UPDATED}}
FORMS = cg.name_forms([(e, f["name"], f["web_name"]) for e, f in FLAGS.items()])
ABSENT = {e for e, f in FLAGS.items() if f["status"] != "a"}
NONE = av.player_corpus([UNKNOWN, "GW11"], [], [])                         # FPL's words and its chance gameweek only


def _names(sentence):
    out = set()
    for _w, ids in cg._spans_words(sentence, FORMS):
        if len(ids) == 1:
            out |= set(ids)
    return out


def _corpus(element, sentence):
    """As the agent builds it: his FPL words, and the model's window GW11-16 for a sentence about the model's predictions."""
    about_model = av.MODEL_WORDS.search(sentence) or av.window_range(sentence, range(11, 17))
    return av.player_corpus([FLAGS[element]["news"], "GW11"], [], [], range(11, 17) if about_model else ())


def _check(reply):
    return av.check(reply, _names, ABSENT, _corpus, lambda e, s: f"<<line {e}>>", today=(18, 11), next_gw=11,
                    fpl_text=lambda e: FLAGS[e]["news"])


# ---- E1: the measured side effects, word for word --------------------------------------------------------------------------------
AVAIL = ('**FPL\'s availability flag (as of Sun 15 Nov 2026):** Semenyo is listed as injured — "Knee injury - Unknown return date" '
         "— with a **0% chance of playing in GW11**.")
R1_S1 = "Eight weeks from that announcement would take him to around mid-December, which at minimum covers GW11 through GW14 or 15."
R1_S2 = ("With **5 free transfers** available, using one to move him out costs you nothing and frees up a slot that is currently "
         "dead weight for at least the next month of fixtures.")
R1_S2_KEPT = ("With **5 free transfers** available, using one to move him out costs you nothing and frees up a slot that is "
              "currently dead weight.")
R2_S = ("Eight weeks from that report puts his return around mid-to-late December at the earliest — that is several gameweeks away, "
        "and no specific return date has been given.")
SMOKE_S = ("With 5 free transfers banked, there's no cost to moving him out, and the opportunity cost of a dead squad slot "
           "through December is significant.")                            # F2's smoke, word for word
REPORT = "The Man City official site reported on 21 Oct that he was facing **eight weeks on the sidelines** [c1314]."


def test_e1a_fpls_words_in_the_reply_only_the_timing_goes_and_the_advice_stays():
    reply = f"{AVAIL}\n\nHe sells for £8.2m. {R1_S2}"
    out, rep = _check(reply)
    assert out == f"{AVAIL}\n\nHe sells for £8.2m. {R1_S2_KEPT}"
    assert rep == [{"element": 397, "sentence": R1_S2, "timing": ["next month"], "line": None, "kept": R1_S2_KEPT}]


def test_e1b_a_sentence_that_is_only_the_timing_goes_and_no_line_is_added():
    out, rep = _check(f"{AVAIL} {REPORT} {R1_S1}")
    assert out == f"{AVAIL} {REPORT}" and "<<line" not in out
    assert rep[0]["line"] is None and rep[0]["kept"] == "" and rep[0]["sentence"] == R1_S1


def test_e1c_run_2_the_line_no_longer_repeats_the_sentence_before_it():
    top = "**No — Semenyo is worth selling.**\n\n**Availability:** FPL lists him as injured — \"Knee injury - Unknown return date\" [1]."
    out, rep = _check(f"{top} {REPORT} {R2_S}\n\n**Predictions:** tiny.")
    assert out == f"{top} {REPORT}\n\n**Predictions:** tiny."
    assert [(r["line"], r["kept"]) for r in rep] == [(None, "")]


def test_e1d_fpls_words_not_there_the_first_slip_gets_the_line_once_and_later_ones_only_lose_their_timing():
    out, rep = _check(f"Semenyo is injured. {R1_S1}\n\nHe sells for £8.2m. {R1_S2} {SMOKE_S}")
    assert out == ("Semenyo is injured. <<line 397>>\n\nHe sells for £8.2m. "
                   f"{R1_S2_KEPT} With 5 free transfers banked, there's no cost to moving him out, and the opportunity cost of a "
                   "dead squad slot is significant.")
    assert out.count("<<line 397>>") == 1
    assert [r["line"] for r in rep] == ["<<line 397>>", None, None]


@pytest.mark.parametrize("slip,kept", [
    # a later dash clause (F2b E3-r2's shape)
    ("The Man City official site reported on 21 Oct that he was facing **eight weeks on the sidelines** [c2002] — which, counting "
     "from that date, puts a return somewhere around mid-to-late December at the earliest.",
     "The Man City official site reported on 21 Oct that he was facing **eight weeks on the sidelines** [c2002]."),
    # a trailing ", so ..." clause
    ("The model gives him a 0% chance of starting across all six gameweeks it covers (GW11–16), so there is no sign of an expected "
     "return within the next month or so.",
     "The model gives him a 0% chance of starting across all six gameweeks it covers (GW11–16)."),
    # a trailing ", but ..." clause (F2's smoke, word for word)
    ("That report's words are a duration, not a return date, but eight weeks from mid-October puts his return around mid-to-late "
     "December at the earliest.", "That report's words are a duration, not a return date."),
    # the timing IS the sentence: it goes whole -- never "He won't be back." or "He'll miss every game."
    ("He won't be back until December.", ""),
    ("He'll miss every game through December.", ""),
    ("Eight weeks from 23 Oct points well into December — so there is a real chance he misses GW11 and several weeks beyond.", "")])
def test_e1e_what_is_trimmed_and_what_goes_whole(slip, kept):
    out, rep = _check(f"{AVAIL} {slip}")
    assert out == (f"{AVAIL} {kept}" if kept else AVAIL)
    assert rep[0]["kept"] == kept and rep[0]["line"] is None


def test_e1c2_a_line_that_would_add_a_report_the_reply_cites_nowhere_else_is_still_swapped_in():
    """The narrowing: F2b's E3-r2 (pinned, both engines) -- FPL's words are there, but the report the line brings ([c2002]) is
    cited only inside the slip, so the line still comes in; run 2's shape -- the report ([c1314]) cited in the sentence before --
    gets no line."""
    slip = ("The club reported on 21 Oct that he was facing **eight weeks on the sidelines** [c2002] — which puts a return around "
            "mid-December.")
    lines = lambda e, s: "<<line with [c2002]>>"                                         # noqa: E731
    reply = f"{AVAIL} {slip}"
    out, rep = av.check(reply, _names, ABSENT, _corpus, lines, today=(18, 11), next_gw=11, fpl_text=lambda e: FLAGS[e]["news"])
    assert out == f"{AVAIL} <<line with [c2002]>>" and rep[0]["line"] == "<<line with [c2002]>>"
    lines = lambda e, s: "<<line with [c1314]>>"                                         # noqa: E731
    out, rep = av.check(f"{AVAIL} {REPORT} {R2_S}", _names, ABSENT, _corpus, lines, today=(18, 11), next_gw=11,
                        fpl_text=lambda e: FLAGS[e]["news"])
    assert out == f"{AVAIL} {REPORT}" and rep[0]["line"] is None


def test_e1f_fpls_words_as_the_model_wrote_them_count():
    assert av.fpl_text_in('FPL lists him as injured: *"Thigh injury — unknown return date"*', "Thigh injury - Unknown return date")
    assert av.fpl_text_in("FPL says: unknown return date.", "Thigh injury - Unknown return date")
    assert not av.fpl_text_in("FPL lists him as injured.", "Thigh injury - Unknown return date")
    assert not av.fpl_text_in("anything", "")


# ---- E1 on both engines -----------------------------------------------------------------------------------------------------------
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
    card = {"name": "Antoine Semenyo", "player_id": 397, "status": "i", "chance": 0, "news": UNKNOWN,
            "availability": {"status": "i", "status_word": "injured", "news": UNKNOWN, "as_of_words": "Sun 15 Nov 2026 11:02 UTC",
                             "chance_gameweek": 11}}
    fakes = {"resolve_player": lambda kw: {"matches": [{"player_id": 397, "name": "Antoine Semenyo", "status": "i"}],
                                           "total_matches": 1, "ambiguous": False},
             "get_player_card": lambda kw: dict(card)}
    for name, f in fakes.items():
        monkeypatch.setitem(agent.available_functions, name, (lambda fn: (lambda **kw: fn(kw)))(f))
    return agent


def _turn(ag, monkeypatch, engine, reply):
    script = pf._Script([pf._Resp([pf._Block("tool_use", name="resolve_player", input={"name": "Semenyo"}, id="toolu_r"),
                                   pf._Block("tool_use", name="get_player_card", input={"player_id": 397}, id="toolu_c")], "tool_use"),
                         pf._Resp([pf._Block("text", text=reply)], "end_turn")])
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    if engine == "loop":
        answer, msgs = ag.run_agent("Is Semenyo worth keeping?", [])
    else:
        import agent_graph
        import tracing
        st = ag._begin_turn("Is Semenyo worth keeping?", [], engine="graph")
        try:
            out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
        finally:
            tracing.close_open()
            turn_context.end()
        answer, msgs = out["rendered"], st["messages"]
    return answer, msgs, len(script.calls)


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_e1g_the_delivered_reply_keeps_the_advice_and_says_fpls_words_once(ag, monkeypatch, engine):
    reply = f"**No -- sell him.**\n\n{AVAIL} {R1_S1}\n\nHe sells for £8.2m. {R1_S2}"
    answer, msgs, n = _turn(ag, monkeypatch, engine, reply)
    assert n == 2                                                                    # no second model call
    assert "December" not in answer and "next month" not in answer
    assert answer.count("Unknown return date") == 1 and R1_S2_KEPT in answer and "Antoine Semenyo: FPL lists him" not in answer
    rep = ag.LAST_TURN["availability_replacements"]
    assert [(r["sentence"], r["line"], r["kept"]) for r in rep] == [(R1_S1, None, ""), (R1_S2, None, R1_S2_KEPT)]
    assert msgs[-1]["content"][0]["text"] == f"**No -- sell him.**\n\n{AVAIL}\n\nHe sells for £8.2m. {R1_S2_KEPT}"


# ---- S5: "around now" ------------------------------------------------------------------------------------------------------------
S5 = ("That eight-week window, if it ran from late October, would only be expiring around now — but there is no update since 23 Oct, "
      "and FPL still shows no return date.")


def test_s5_around_now_is_a_return_timing():
    assert ("anchor", "around now") in [(k, key) for k, key, _w in av.timings(S5)]
    lead = '**He is out.** FPL lists him as injured: *"Thigh injury — unknown return date"*. Saka was hurt against Bayern.'
    out, rep = _check(f"{lead} {S5}")
    assert out == lead and rep[0]["timing"] == ["around now"]                      # FPL's words there: the sentence goes
    out, rep = _check(f"Saka is injured. {S5}")
    assert out == "Saka is injured. <<line 12>>"                                    # not there: his line, as before
    assert _check("Saka is injured and out for up to eight weeks.") == ("Saka is injured and out for up to eight weeks.", [])


# ---- S2 / S3: the prediction's average and its gameweeks best first -------------------------------------------------------------
L8 = {11: 4.19, 12: 4.0, 13: 4.69, 14: 3.81, 15: 3.29, 16: 4.34}               # F1 L8: Cole Palmer, build 78 (total 24.32)


def _pred(rows, span=None):
    out = {"player_id": 154, "predictions": [{"gw": g, "horizon_step": g - 11, "e_points": v} for g, v in rows.items()]}
    if span:
        out["span"] = span
    return out


def test_s2_s3_average_and_best_first():
    import model_tools as mt
    out = mt._with_prediction_words(_pred(L8))
    assert out["average_per_gameweek"] == "4.05 predicted points a gameweek on average: 24.32 over GW11–16 divided by its 6 gameweeks"
    assert out["gameweeks_best_first"] == "GW13 4.69, GW16 4.34, GW11 4.19, GW12 4.00, GW14 3.81, GW15 3.29"
    level = mt._with_prediction_words(_pred({11: 2.0, 12: 3.0, 13: 2.0}))
    assert level["gameweeks_best_first"] == "GW12 3.00, GW11 2.00, GW13 2.00"     # level figures: the earlier gameweek first


def test_s2b_a_span_with_a_blank_divides_by_its_gameweeks_and_one_gameweek_gets_neither():
    import model_tools as mt
    out = mt._with_prediction_words(_pred({11: 3.0, 13: 3.0}, span={"gameweeks": [11, 12, 13]}))
    assert out["average_per_gameweek"].startswith("2.00 predicted points a gameweek on average: 6.00 over GW11–13 divided by its 3")
    one = mt._with_prediction_words(_pred({11: 3.0}))
    assert "average_per_gameweek" not in one and "gameweeks_best_first" not in one


def test_s2c_a_draft_turn_gets_neither(monkeypatch):
    import model_tools as mt
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    out = mt._with_prediction_words(_pred(L8))
    assert "average_per_gameweek" not in out and "gameweeks_best_first" not in out


# ---- S1: where his price sits --------------------------------------------------------------------------------------------------
POOL = [{"position": "MID", "price_tenths": p} for p in (40, 43, 45, 47, 47, 60, 145)] + \
       [{"position": "DEF", "price_tenths": p} for p in (39, 44, 50)]


def test_s1_price_rank_words(monkeypatch):
    import model_tools as mt
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [dict(r) for r in POOL])
    assert mt._price_rank_words(4.7, "MID") == (
        "£4.7m: 5 of the 10 players in the game cost less, 3 cost more and 2 cost the same (from £3.9m to £14.5m); "
        "3 of the 7 midfielders cost less, 2 cost more and 2 cost the same (from £4.0m to £14.5m) (him included).")
    assert mt._price_rank_words(None, "MID") is None


# ---- S4: is he in the user's squad -----------------------------------------------------------------------------------------------
SQUAD = {"squad_json": {"players": [{"element": 411, "purchase_price": 155}, {"element": 26, "purchase_price": 75}]}}


@pytest.fixture
def squad(monkeypatch):
    import model_tools as mt
    monkeypatch.setattr(mt, "DEFAULT_USER_ID", lambda: 1)
    monkeypatch.setattr(mt, "_squad_owner", lambda uid: uid)
    monkeypatch.setattr(mt, "_read_active", lambda uid: SQUAD)
    return mt


def test_s4_your_squad_in_and_out(squad):
    assert squad._your_squad_words(411, 15.8) == ("In your squad: you bought him at £15.5m; he costs £15.8m now and sells for "
                                                   "£15.6m (FPL's selling rule).")
    assert squad._your_squad_words(26, 7.4).endswith("sells for £7.4m (FPL's selling rule).")          # a fall: the full fall
    assert squad._your_squad_words(397, 8.2) == ("Not in your squad: you have no purchase or selling price for him -- £8.2m is "
                                                  "his price now; a price in a news item is that item's own.")


def test_s4b_no_saved_squad_says_nothing(monkeypatch):
    import model_tools as mt
    import squad_store

    def none(uid):
        raise squad_store.NoSquadError("no squad")
    monkeypatch.setattr(mt, "DEFAULT_USER_ID", lambda: 1)
    monkeypatch.setattr(mt, "_squad_owner", lambda uid: uid)
    monkeypatch.setattr(mt, "_read_active", none)
    assert mt._your_squad_words(397, 8.2) is None


def test_s1_s4_on_the_card_in_a_normal_turn_and_not_in_a_draft_turn(squad, monkeypatch):
    mt = squad
    row = {"element": 397, "name": "Antoine Semenyo", "web_name": "Semenyo", "team": "Man City", "position": "MID", "status": "i",
           "chance": 0, "news": UNKNOWN, "price_tenths": 82, "updated_at": UPDATED}
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [dict(row)] if "WHERE element" in sql else [dict(r) for r in POOL])
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "_snapshot_news", lambda *a, **k: {})
    monkeypatch.setattr(mt, "_next_round_gw", lambda *a, **k: 11)
    monkeypatch.setattr(mt, "fpl_figure_note", lambda gw: None)
    monkeypatch.setattr(mt, "get_prediction", lambda *a, **k: {"error": "not in this test"})
    card = mt.get_player_card(397)
    assert card["your_squad"].startswith("Not in your squad") and card["price_rank"].startswith("£8.2m: 9 of the 10 players")
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    card = mt.get_player_card(397)
    assert "your_squad" not in card and "price_rank" not in card
