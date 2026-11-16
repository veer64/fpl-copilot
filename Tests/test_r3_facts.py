"""Prompt R3 item 8 (16 Nov 2026): the targeted fixes -- a labelled fact or a ready sentence in a NORMAL turn's tool output, a
value computed by code, or code that drops what must not reach the user. Never a word ban, never a length rule. Each test
names the measured slip it answers (eval/reports/r3_evidence_digest.md).

F-fixture  every fixture carries `in_words`: whose scores they are, home or away, the tenth each score sits in
           (W1 "defence score just 1" read off the wrong side; M11 / M12 two home games written "@"; M4 a 9 called
           "the easiest tenth");
F-leak     the send-back's rewrite loses a lead-in that answers the automatic check (M2 "Here is the corrected version with
           only those two fixes applied:"), in the reply and in the history, on both engines;
F-clubs    a squad build lists each club's players with position and role (M5 "Brighton dominate the defence with three
           starters": two defenders and a midfielder);
F-xg       a breakdown says what each input is (M17 an expected-goals rate called a "shot rate"); the prompt no longer says
           "shot rate" itself;
F-sign     FPL's price figure says which way it points wherever it is carried (M18);
F-words    "horizon" is no longer rewritten to "six-gameweek plan" (digest 7.5 "the six-week six-gameweek plan"), and the
           planner's verdict no longer says "six-week" for a plan of any length (digest 4);
F-prompt   the normal turn's prompt routes the four answers to code and points at each labelled fact; a draft turn's does not.
A draft chat's tool results carry none of the additions."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                                   # noqa: E402
import turn_context                                                        # noqa: E402
from test_agent_graph import h, _both, ROUND                               # noqa: E402,F401  (h: the harness fixture)
from test_tracing import _text, _tool, RIGHT, WRONG                        # noqa: E402

DRAFT = {"user_id": 10001, "draft_key": 800_000_001}


def _in_draft(fn, *a, **k):
    turn_context.begin("f" * 32, thread_id="th_draft", draft=DRAFT)
    try:
        return fn(*a, **k)
    finally:
        turn_context.end()


# ---- F-fixture ------------------------------------------------------------------------------------------------------------------

def _club_fixtures():
    diff = lambda a, d: {"attacking": {"score": a, "value": 1.5}, "defensive": {"score": d, "value": 0.3}}   # noqa: E731
    return {"compact": False, "fixtures": [
        {"team": "Man City", "gw": 12, "fixtures": [{"opponent": "Arsenal", "home": False, "difficulty": diff(4, 1)}], "n_fixtures": 1},
        {"team": "Man City", "gw": 13, "fixtures": [{"opponent": "Leeds", "home": True, "difficulty": diff(9, 10)},
                                                    {"opponent": "Hull City", "home": True, "difficulty": diff(10, 8)}], "n_fixtures": 2},
        {"team": "Man City", "gw": 14, "fixtures": [], "blank_gameweek": True},
        {"team": "Man City", "gw": 20, "fixtures": [{"opponent": "Spurs", "home": False, "difficulty": None, "rating": "scheduled but not rated yet: GW20"}]}]}


def test_f_fixture_one_club_whose_scores_home_or_away_and_the_tenth():
    out = mt._with_fixture_words(_club_fixtures())
    fx = [f for row in out["fixtures"] for f in row["fixtures"]]
    assert fx[0]["in_words"] == ("GW12: Man City away at Arsenal; Man City's attack score 4 of 10 (a middle tenth (4 of 10) for scoring), "
                                 "Man City's defence score 1 of 10 (the hardest tenth for a clean sheet)")
    assert fx[1]["in_words"] == ("GW13: Man City at home to Leeds; Man City's attack score 9 of 10 (the second-easiest tenth for scoring), "
                                 "Man City's defence score 10 of 10 (the easiest tenth for a clean sheet)")
    assert fx[2]["in_words"].startswith("GW13: Man City at home to Hull City; Man City's attack score 10 of 10 (the easiest tenth for scoring)")
    assert fx[3]["in_words"] == "GW20: Man City away at Spurs"            # not rated yet: no score is put in words
    assert "9 of 10 (the easiest tenth" not in str(out)                    # M4: a 9 is never "the easiest tenth"


def test_f_fixture_all_clubs_each_compact_row_is_one_clubs_side():
    out = mt._with_fixture_words({"compact": True, "fixtures": [
        {"team": "Brentford", "gw": 12, "opponent": "Man Utd", "home": False, "attack_score": 3, "defence_score": 2},
        {"team": "Man Utd", "gw": 12, "opponent": "Brentford", "home": True, "attack_score": 8, "defence_score": 7},
        {"team": "Leeds", "gw": 13, "opponent": None, "home": None, "attack_score": None, "defence_score": None, "blank": True}]})
    a, b, blank = out["fixtures"]
    assert a["in_words"] == ("GW12: Brentford away at Man Utd; Brentford's attack score 3 of 10 (the third-hardest tenth for scoring), "
                             "Brentford's defence score 2 of 10 (the second-hardest tenth for a clean sheet)")
    assert b["in_words"].startswith("GW12: Man Utd at home to Brentford; Man Utd's attack score 8 of 10 (the third-easiest tenth for scoring)")
    assert "in_words" not in blank


@pytest.mark.parametrize("score,words", [(10, "the easiest tenth"), (9, "the second-easiest tenth"), (8, "the third-easiest tenth"),
                                         (7, "a middle tenth (7 of 10)"), (5, "a middle tenth (5 of 10)"), (4, "a middle tenth (4 of 10)"),
                                         (3, "the third-hardest tenth"), (2, "the second-hardest tenth"), (1, "the hardest tenth")])
def test_f_fixture_only_a_ten_is_the_easiest_tenth(score, words):
    assert mt._tenth_words(score) == words
    assert mt._tenth_words(None) is None


def test_f_fixture_a_draft_chat_and_an_error_are_left_alone():
    assert all("in_words" not in f for row in _in_draft(mt._with_fixture_words, _club_fixtures())["fixtures"] for f in row["fixtures"])
    assert mt._with_fixture_words({"error": "no calendar"}) == {"error": "no calendar"}


# ---- F-leak ---------------------------------------------------------------------------------------------------------------------

LEAD = "Here is the corrected version with only those two fixes applied:"


@pytest.mark.parametrize("rewrite,kept", [
    (f"{LEAD}\n\n---\n\n### Top 8 FWD\n\n| a |", "### Top 8 FWD\n\n| a |"),
    (f"{LEAD}\n\nHaaland starts.", "Haaland starts."),
    ("Here's the corrected answer:\nHaaland starts.", "Haaland starts."),
    ("I've fixed the two figures.\n\nHaaland starts.", "Haaland starts."),
    ("Updated answer with the fix applied:\n\n***\n\nHaaland starts.", "Haaland starts."),
])
def test_f_leak_a_lead_in_that_answers_the_check_is_dropped(rewrite, kept):
    import agent
    assert agent.drop_rewrite_lead_in(rewrite, "Haaland is benched.") == (kept, True)


@pytest.mark.parametrize("rewrite,original", [
    ("Haaland starts, and Saka is the vice-captain.", "Haaland starts, and Foden is the vice-captain."),
    ("Here is your corrected line-up:\n\nHaaland starts.", "Here is your corrected line-up:\n\nHaaland is benched."),   # the answer's own first line
    ("### Your fixed XI\n\nHaaland starts.", "x"), ("| Player | Pts |\n|---|---|\n| Haaland | 7.19 |", "x"),
    ("- Corrected: Haaland starts.", "x"), ("Haaland's fixture is unchanged: he starts.", "x"),
    (f"{LEAD}", "x"), ("", "x"),
])
def test_f_leak_nothing_else_is_ever_dropped(rewrite, original):
    import agent
    assert agent.drop_rewrite_lead_in(rewrite, original) == (rewrite, False)


def test_f_leak_the_delivered_rewrite_and_the_history_never_carry_it(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), _text(f"{LEAD}\n\n---\n\n{RIGHT}")],
              ROUND + ["call_model", "fact_check", "send_back", "recheck", "finalize"])
    assert s["last_fact_check"]["outcome"] == "fixed"
    assert s["answer"] == RIGHT and "corrected version" not in s["answer"]
    assert s["history"][-1] == {"role": "assistant", "content": [{"type": "text", "text": RIGHT}]}


def test_f_leak_a_rewrite_without_a_lead_in_is_delivered_as_written(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)],
              ROUND + ["call_model", "fact_check", "send_back", "recheck", "finalize"])
    assert s["answer"] == RIGHT and s["last_fact_check"]["outcome"] == "fixed"


# ---- F-clubs --------------------------------------------------------------------------------------------------------------------

def _build():
    def row(i, name, pos, club, role):
        return {"player_id": i, "name": name, "position": pos, "team": club, "role": role, "e_points": 4.0}
    return {"gw": 11, "captain": "Haaland",
            "xi": [row(1, "De Cuyper", "DEF", "Brighton", "start"), row(2, "Vušković", "DEF", "Brighton", "VICE"),
                   row(3, "Gómez", "MID", "Brighton", "start"), row(4, "Van Hecke", "DEF", "Spurs", "start"),
                   row(5, "Haaland", "FWD", "Man City", "CAPTAIN")],
            "bench_in_order": [row(6, "Verbruggen", "GK", "Brighton", "bench"), row(7, "Doku", "MID", "Man City", "bench")]}


def test_f_clubs_each_clubs_players_with_position_and_role():
    out = mt._with_club_counts(_build())
    assert out["clubs"] == [
        {"club": "Brighton", "players": 4, "who": "De Cuyper (DEF, starts), Vušković (DEF, starts), Gómez (MID, starts), Verbruggen (GK, bench)"},
        {"club": "Man City", "players": 2, "who": "Haaland (FWD, starts), Doku (MID, bench)"},
        {"club": "Spurs", "players": 1, "who": "Van Hecke (DEF, starts)"}]
    assert mt._with_club_counts(out)["clubs"] == out["clubs"]              # idempotent
    squad_form = mt._with_club_counts({"squad": _build()["xi"] + _build()["bench_in_order"]})
    assert [c["players"] for c in squad_form["clubs"]] == [4, 2, 1]        # the constrained build's shape too
    assert "clubs" not in _in_draft(mt._with_club_counts, _build())
    assert mt._with_club_counts({"error": "x"}) == {"error": "x"} and "clubs" not in mt._with_club_counts({"gw": 11})


# ---- F-xg -----------------------------------------------------------------------------------------------------------------------

def test_f_xg_a_breakdown_says_what_each_input_is():
    out = mt._with_input_meanings({"summary_plain": "A by 0.7", "detail": {}})
    assert out["input_meanings"]["npxg90"] == ("expected goals per 90 minutes, penalties not counted -- an expected-goals rate, never a "
                                               "shot count or a shot rate")
    assert set(out["input_meanings"]) == {"npxg90", "xa90", "minutes_frac", "fixture_scale_cal", "e_pen_goals"}
    assert "input_meanings" not in _in_draft(mt._with_input_meanings, {"summary_plain": "x"})
    assert mt._with_input_meanings({"error": "x"}) == {"error": "x"}
    import explain
    src = Path(explain.__file__).read_text(encoding="utf-8")
    assert '"npxg90"' in src and "shot rate" not in src.lower()            # the breakdown's own input; it never says "shot rate"


# ---- F-sign ---------------------------------------------------------------------------------------------------------------------

def test_f_sign_the_figure_says_which_way_it_points():
    assert mt.PRICE_FIGURE_SIGN == "above zero is progress toward a RISE in price; below zero is progress toward a FALL"
    import answers
    assert answers.progress_words(50.6) == "50.6% toward a rise" and answers.progress_words(-64.9) == "64.9% toward a fall"


# ---- F-words --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,plain", [
    ("over the six-week horizon", "over the six-week plan"),               # was "the six-week six-gameweek plan"
    ("a 3-gameweek horizon", "a 3-gameweek plan"), ("the six-gameweek horizon", "the six-gameweek plan"),
    ("the horizon total", "the plan total"), ("Horizon: GW11-13", "Plan: GW11-13"), ("both horizons", "both plan"),
])
def test_f_words_horizon_is_never_rewritten_to_six_gameweeks(text, plain):
    import agent
    assert agent.plain_words(text)[0] == plain and "six-gameweek plan" not in agent.plain_words("the horizon")[0]


def test_f_words_the_planners_verdict_names_no_fixed_length():
    src = (REPO / "model_tools.py").read_text(encoding="utf-8")
    assert "on the six-week objective" not in src and "This plan covers up to six gameweeks" not in src
    assert "over the next six gameweeks (weighted towards the nearer ones)" not in src
    hold = {"refused": True}
    assert mt._transfer_summary(11, {"n_transfers": 0}, hold, 1, span="GW11–16 (6 gameweeks)") == (
        "For GW11: hold, no transfer. The hold-versus-move gap is withheld this week. This plan covers GW11–16 (6 gameweeks); "
        "check back each week.")
    assert mt._transfer_summary(11, {"n_transfers": 0}, None, 1) == "For GW11: hold, no transfer. Check back each week."


# ---- F-prompt -------------------------------------------------------------------------------------------------------------------

def test_f_prompt_the_normal_prompt_routes_and_points_at_each_fact_and_the_draft_prompt_is_untouched():
    import agent
    p, d = agent.SYSTEM_PROMPT, agent.DRAFT_SYSTEM_PROMPT
    assert "# 1c. Seven answers are written by code, not by you" in p and "# 1c." not in d   # R3b: was "Four"
    assert p.split("\n")[10].startswith("- Every number you state") and p.split("\n")[:14] == d.split("\n")[:14]   # the head of the prompt is untouched
    for name in ("`rank_players`", "`review_my_squad`"):
        assert name in p and name not in d
    assert "Never rank, sort or add up players yourself" in p
    for fact in ("`in_words`", "`range_words`", "`span`", "`sign`", "`input_meanings`", "`clubs`"):
        assert fact in p and fact not in d, fact
    for gone in ("shot rate", "This plan covers up to six gameweeks", "what doing nothing scores over the same gameweeks",
                 "the six-week weighted objective"):
        assert gone not in p and gone in d, gone
    assert "making no transfer THIS gameweek only" in p
    for banned in ("keep it short", "be brief about", "do not use the word", "never use the word"):
        assert banned not in p.lower()                                     # no word ban and no length rule was added
