"""Prompt F4 (24 Nov 2026): two small fixes, owner-approved.

P   PINS. Kepa Arrizabalaga (element 2 -> Understat 5061) and Matthijs de Ligt (416 -> 7902), GW11 debutants absent from
    Understat's 2026 listing (frozen at GW8 by understat.com's outage), pinned in MANUAL["2026-27"] the way U1 pinned its four:
    each id from our own prior-season crosswalks with minutes agreeing (X, eval/reports/x_crosswalk_drift.md).
D   DEADLINE != RETURN DATE (F3's live check, C:\\dev\\fpl-backups\\f3_files\\gate\\replies_L.md; live since 18 Nov). Fix E read
    the next deadline's gameweek and date as a return timing: S4 run 2's bullet "You have **5 free transfers** available for
    GW12, so there's room to act." was swapped for Nathan Collins's line (the bullet before named him), and S5 run 1's "Worth
    checking back as the GW12 deadline approaches (Friday 27 Nov, 18:30 UTC) — ..." was dropped as Rico Henry's return. The
    owner's rule: a timing counts only in a sentence about that player, and the next deadline's GW and date never count.
    D1  a list item that names nobody and has no "he/his/him" is not about the player of the item before it (a new bullet is a
        new point, as a new paragraph already was);
    D2  the next deadline's gameweek and date -- as the turn's own context block told the model -- never count as a return
        timing, in any sentence;
    D3  a return timing that is not the deadline is still caught (F2's R4 and F2b's tests pin the rest, unedited);
    D4  on both engines, the deadline comes from the turn's context block; a block without one changes nothing.
No model, no network, no database: the players, their FPL flags and the news are fixed fakes, as production had them on 24 Nov."""
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

# ---- P: the pins ----------------------------------------------------------------------------------------------------------------
import build_crosswalk as bc                                               # noqa: E402

NEEDED = [REPO / "data" / "history" / "all_seasons_with_2026_27.parquet",
          REPO / "data" / "history" / "understat_season_aggregates_with_2026_27.parquet"]


def test_p1_the_two_pins_are_in_manual():
    m = bc.MANUAL["2026-27"]
    assert m[2][0] == "5061" and "Kepa" in m[2][1]
    assert m[416][0] == "7902" and "de Ligt" in m[416][1]
    for el in (2, 416):
        assert len(m[el][1]) > 80, f"pin for element {el} carries no evidence"


@pytest.mark.skipif(not all(p.exists() for p in NEEDED), reason="2026-27 combined ingestion files not on disk")
def test_p2_the_build_carries_them_as_manual():
    cw, _stats = bc.build("2026-27", verbose=False)
    for el, uid in ((2, "5061"), (416, "7902")):
        row = cw[cw["element"] == el]
        assert len(row) == 1, f"element {el} missing from the build"
        assert str(row["understat_id"].iloc[0]) == uid and row["match_type"].iloc[0] == "manual"
    assert not cw.duplicated("understat_id").any()


# ---- D: the deadline is not a return date -------------------------------------------------------------------------------------
UPDATED = datetime(2026, 11, 21, 9, 30, tzinfo=timezone.utc)
FLAGS = {84: {"name": "Nathan Collins", "web_name": "Collins", "status": "i", "chance": 0, "news": "Knee injury - Expected back 2 Dec",
              "updated_at": UPDATED},
         244: {"name": "Marc Guéhi", "web_name": "Guéhi", "status": "d", "chance": 75, "news": "Knock - 75% chance of playing",
               "updated_at": UPDATED},
         89: {"name": "Rico Henry", "web_name": "Henry", "status": "i", "chance": 0, "news": "Hip injury - Unknown return date",
              "updated_at": UPDATED},
         366: {"name": "Bruno Borges Fernandes", "web_name": "B.Fernandes", "status": "a", "chance": None, "news": "", "updated_at": UPDATED}}
FORMS = cg.name_forms([(e, f["name"], f["web_name"]) for e, f in FLAGS.items()])
ABSENT = {e for e, f in FLAGS.items() if f["status"] != "a"}
HENRY_SAID = ["Rico Henry ruled out through injury",
              "Rico Henry will be out for a period of weeks, probably until after the international break."]
HENRY_DATES = ["2026-10-27", "Tue 27 Oct 2026", "2026-11-05", "Thu 5 Nov 2026"]
DEADLINE = (12, (27, 11))                                     # GW12, Fri 27 Nov 2026 18:30 UTC -- the next deadline on 24 Nov
BLOCK = ("## Now\n- Gameweeks: GW10 is the last finished gameweek; GW11 is in progress (deadline passed, not yet final); "
         "next deadline GW12, Friday 2026-11-27 18:30 UTC.\n- Model updates: ...")

# S4 run 2, as the model wrote it (the second bullet is the one swapped for Collins's line)
S4_BULLET = "You have **5 free transfers** available for GW12, so there's room to act."
S4_R2 = ("Bruno Fernandes isn't in your squad — he's not among your 15. So \"should I hold on to him\" doesn't apply here; you don't "
         "own him.\n\nA quick look at your midfield: you have Bryan Mbeumo, Cody Gakpo, Phil Foden, and Ibrahim Sangaré. No Bruno.\n\n"
         "A couple of things worth flagging while we're here:\n\n"
         "- **Nathan Collins** is injured with a 0% chance of playing (FPL's flag as of Sat 21 Nov), and **Marc Guéhi** is doubtful "
         "at 75% — both flagged for GW11.\n"
         f"- {S4_BULLET}\n"
         "- The recorded roles (captain, bench order etc.) are **stale** — they were set for GW6 and haven't been updated for GW12.")
# S5 run 1, the paragraph that lost its second sentence
S5_DEADLINE = ("Worth checking back as the GW12 deadline approaches (Friday 27 Nov, 18:30 UTC) — the model refreshes at 17:00, 18:00 "
               "and 18:20 UTC that day, and any late Brentford team news would be the thing to watch.")
S5_R1 = ("**FPL's official flag (as of Sat 21 Nov 2026):** Rico Henry is listed as injured — \"Hip injury - Unknown return date\" — "
         "with a 0% chance of playing.\n\nThere's nothing in the latest news to suggest he's close to returning. " + S5_DEADLINE)


def _names(sentence):
    out = set()
    for _w, ids in cg._spans_words(sentence, FORMS):
        if len(ids) == 1:
            out |= set(ids)
    return out


def _corpus(element, sentence):
    """As the agent builds it: his FPL words (news, as-of day, the chance's gameweek GW11), the source sentences naming him with
    their dates, and the model's window GW11-16 for a sentence about the model's predictions."""
    f = FLAGS[element]
    said, dates = (HENRY_SAID, HENRY_DATES) if element == 89 else ([], [])
    about_model = av.MODEL_WORDS.search(sentence) or av.window_range(sentence, range(11, 17))
    return av.player_corpus([f["news"], "Sat 21 Nov 2026", "GW11"], said, dates, range(11, 17) if about_model else ())


def _check(reply, deadline=None):
    """av.check as the agent calls it on 24 Nov (today 24 Nov, the turn's next_gw 11 from FPL's chance gameweek); `deadline` is
    passed only where the code takes it, so a test against the old code fails on its behaviour, not on a TypeError."""
    kw = {"deadline": deadline} if deadline is not None and "deadline" in inspect.signature(av.check).parameters else {}
    return av.check(reply, _names, ABSENT, _corpus, lambda e, s: f"<<line {e}>>", today=(24, 11), next_gw=11,
                    fpl_text=lambda e: FLAGS[e]["news"], **kw)


def test_d1_a_new_list_item_is_not_about_the_player_of_the_one_before():
    assert _check(S4_R2) == (S4_R2, [])                                          # the bullet stays, even without the deadline
    later = S4_R2.replace("for GW12, so", "before GW13, so")                       # not the deadline's gameweek either
    assert _check(later) == (later, [])
    named = S4_R2.replace(S4_BULLET, "Collins should be back by GW13, so there's room to wait.")
    out, rep = _check(named, DEADLINE)                                           # a bullet that names him is still checked
    assert "<<line 84>>" in out and [r["timing"] for r in rep] == [["GW13"]]


def test_d2_the_next_deadlines_gameweek_and_date_never_count():
    assert _check(S5_R1, DEADLINE) == (S5_R1, [])                                 # S5 run 1: the deadline sentence stays
    s4_prose = S4_R2.replace(f"GW11.\n- {S4_BULLET}", f"GW11. {S4_BULLET}")        # the same sentence inside Collins's bullet
    assert _check(s4_prose, DEADLINE) == (s4_prose, [])
    for s in ("Henry won't be fit for GW12.", "Henry is unlikely to be back by the 27 Nov deadline.",
              "He'll miss Friday 27 November's deadline for sure."):
        reply = f"Rico Henry is injured. {s}"
        assert _check(reply, DEADLINE) == (reply, []), s


def test_d3_a_return_timing_that_is_not_the_deadline_is_still_caught():
    for s, timing in (("Henry should be back by GW13.", ["GW13"]), ("Henry could return on 4 December.", ["4 December"]),
                      ("He might be back for the GW12 deadline or by GW14.", ["GW14"])):
        out, rep = _check(f"Rico Henry is injured. {s}", DEADLINE)
        assert out == "Rico Henry is injured. <<line 89>>" and [r["timing"] for r in rep] == [timing], s
    out, rep = _check(S5_R1.replace("Friday 27 Nov", "Saturday 5 Dec"), DEADLINE)   # another date in the same sentence: not the deadline
    assert [r["timing"] for r in rep] == [["5 Dec"]]


# ---- D4: on both engines, the deadline comes from the turn's context block -----------------------------------------------------
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
    card = {"name": "Rico Henry", "player_id": 89, "status": "i", "chance": 0, "news": FLAGS[89]["news"],
            "availability": {"status": "i", "status_word": "injured", "news": FLAGS[89]["news"],
                             "as_of_words": "Sat 21 Nov 2026 09:30 UTC", "chance_gameweek": 11}}
    fakes = {"resolve_player": lambda kw: {"matches": [{"player_id": 89, "name": "Rico Henry", "status": "i"}],
                                           "total_matches": 1, "ambiguous": False},
             "get_player_card": lambda kw: dict(card)}
    for name, f in fakes.items():
        monkeypatch.setitem(agent.available_functions, name, (lambda fn: (lambda **kw: fn(kw)))(f))
    return agent


def _turn(ag, monkeypatch, engine, reply):
    script = pf._Script([pf._Resp([pf._Block("tool_use", name="resolve_player", input={"name": "Rico Henry"}, id="toolu_r"),
                                   pf._Block("tool_use", name="get_player_card", input={"player_id": 89}, id="toolu_c")], "tool_use"),
                         pf._Resp([pf._Block("text", text=reply)], "end_turn")])
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=script))
    if engine == "loop":
        answer, _msgs = ag.run_agent("Is Rico Henry nearly back from his hip injury?", [])
    else:
        import agent_graph
        import tracing
        st = ag._begin_turn("Is Rico Henry nearly back from his hip injury?", [], engine="graph")
        try:
            out = agent_graph.GRAPH.invoke(st, config={"recursion_limit": 80, "configurable": {"agent_run": {"node_s": 0.0, "path": []}}})
        finally:
            tracing.close_open()
            turn_context.end()
        answer = out["rendered"]
    return answer


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_d4_the_agent_reads_the_deadline_from_the_turns_context_block(ag, monkeypatch, engine):
    answer = _turn(ag, monkeypatch, engine, S5_R1)
    assert S5_DEADLINE in answer and ag.LAST_TURN["availability_replacements"] == []
    answer = _turn(ag, monkeypatch, engine, "Rico Henry is injured. He should be back by GW14.")
    assert "GW14" not in answer and [r["timing"] for r in ag.LAST_TURN["availability_replacements"]] == [["GW14"]]


@pytest.mark.parametrize("engine", ["loop", "graph"])
def test_d4b_a_block_without_a_deadline_changes_nothing(ag, monkeypatch, engine):
    monkeypatch.setattr(ag, "context_block", lambda now=None: "ctx")
    answer = _turn(ag, monkeypatch, engine, "Rico Henry is injured. He won't be fit for GW12.")
    assert "GW12" not in answer and [r["timing"] for r in ag.LAST_TURN["availability_replacements"]] == [["GW12"]]


def test_d5_the_deadline_words_parse():
    import agent
    assert agent._deadline_told({"system": BLOCK + "\n\nprompt"}) == DEADLINE
    assert agent._deadline_told({"system": "ctx\n\nprompt"}) is None
    assert agent._deadline_told({}) is None
