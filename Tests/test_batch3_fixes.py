"""Fix batch 3 (2026-10-14): forced injured players built with a warning (F1), routing words (F3), every chance of
playing labelled with its gameweek and date (F4), flagged players' rows in squads and plans (F5), plain words at the
reply (F6), autosubs by name (F7), the one bonus sentence (F8), fixtures beyond the plan (F9), counts (F10).
The database, the deadlines and player names are faked: no network, no local data needed."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import agent                                               # noqa: E402
import explain                                             # noqa: E402
import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

UTC = timezone.utc
PROMPT = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
BONUS = "Our model doesn't account for bonus points; top-ranked players tend to pick up a few extra points from bonus."
DEADLINES = {5: "2026-09-18T17:30:00Z", 6: "2026-10-10T10:00:00Z", 7: "2026-10-17T10:00:00Z", 8: "2026-10-24T10:00:00Z"}
TAKEN = datetime(2026, 9, 29, 11, 1, 51, tzinfo=UTC)


def _desc(name):
    return next(t["description"] for t in agent.tools_schema if t["name"] == name)


@pytest.fixture()
def fake_live(monkeypatch):
    """players_live as four rows: Isak doubtful, Foden suspended, Watkins gone (u), Saka fit."""
    rows = {379: {"element": 379, "name": "Alexander Isak", "status": "d", "chance": 75, "news": "Thigh injury - 75% chance of playing", "updated_at": TAKEN},
            398: {"element": 398, "name": "Phil Foden", "status": "s", "chance": 0, "news": "Suspended until 17 Oct", "updated_at": TAKEN},
            55: {"element": 55, "name": "Ollie Watkins", "status": "u", "chance": None, "news": "Has joined Al Hilal permanently", "updated_at": TAKEN},
            12: {"element": 12, "name": "Bukayo Saka", "status": "a", "chance": None, "news": "", "updated_at": TAKEN}}

    def q(sql, params=None):
        ids = params[0] if params else []
        return [dict(rows[i]) for i in ids if i in rows]
    monkeypatch.setattr(mt, "_q", q)
    monkeypatch.setattr(mt, "_gw_deadline_times", lambda: dict(DEADLINES))
    return rows


# ------------------------------------------------------------------ F4: the chance names its gameweek and date
def test_chance_words_name_the_gameweek_and_the_date():
    assert mt.chance_words(75, TAKEN, 6) == "chance of playing in GW6: 75%, FPL as of 29 Sep 2026"
    assert mt.chance_words(0, "2026-10-13T18:32:17+00:00", 7) == "chance of playing in GW7: 0%, FPL as of 13 Oct 2026"
    assert mt.chance_words(None, TAKEN, 6) is None


def test_the_next_round_is_the_first_deadline_after_fpl_said_it():
    assert mt._next_round_gw(TAKEN, DEADLINES) == 6                         # taken 29 Sep: the next round was GW6
    assert mt._next_round_gw("2026-10-11T20:37:00Z", DEADLINES) == 7        # after GW6's deadline: GW7
    assert mt._next_round_gw("2026-11-30T00:00:00Z", DEADLINES) is None
    assert mt._next_round_gw(None, DEADLINES) is None


def test_the_player_card_says_which_gameweek_its_chance_is_for(fake_live, monkeypatch):
    rows = fake_live
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [dict(rows[398], price_tenths=69, position="MID", team="Man City")])
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: {"error": "not needed here"})
    card = mt.get_player_card(398)
    av = card["availability"]
    assert av["chance_gameweek"] == 6
    assert av["chance_words"] == "chance of playing in GW6: 0%, FPL as of 29 Sep 2026"
    assert card["chance_words"] == av["chance_words"]


def test_the_prompt_forbids_turning_a_date_into_a_return_gameweek():
    assert "never turn a date in FPL's note (\"until 17 Oct\") into a return gameweek" in PROMPT
    assert "`chance_words`" in PROMPT


# ------------------------------------------------------------------ F5: flagged players' rows carry word and chance
def test_flagged_rows_carry_status_word_and_chance_and_fit_players_are_untouched(fake_live):
    out = {"squad": [{"player_id": 379, "name": "Alexander Isak"}, {"player_id": 12, "name": "Bukayo Saka"}],
           "this_deadline": {"transfers": [{"out": "Bukayo Saka", "out_id": 12, "in": "Alexander Isak", "in_id": 379}]},
           "later_steps_indicative": [{"transfers": [{"out": "Phil Foden", "out_id": 398, "in": "Bukayo Saka", "in_id": 12}]}]}
    mt._with_flags(out)
    isak, saka = out["squad"]
    assert isak["status_word"] == "doubtful" and isak["chance"] == 75
    assert isak["chance_words"] == "chance of playing in GW6: 75%, FPL as of 29 Sep 2026"
    assert saka == {"player_id": 12, "name": "Bukayo Saka"}
    t = out["this_deadline"]["transfers"][0]
    assert t["status_word_in"] == "doubtful" and t["chance_in"] == 75 and "status_word_out" not in t
    t2 = out["later_steps_indicative"][0]["transfers"][0]
    assert t2["status_word_out"] == "suspended" and t2["chance_words_out"].startswith("chance of playing in GW6: 0%")


def test_with_flags_leaves_an_error_alone(fake_live):
    assert mt._with_flags({"error": "x", "player_id": 379}) == {"error": "x", "player_id": 379}


# ------------------------------------------------------------------ F1: a forced injured player is built, warned first
def test_the_forced_warning_names_player_status_chance_news_date_and_the_build(fake_live):
    flags = mt._flags_for([379, 398, 55, 12])
    w = mt.forced_availability_warning([379], flags)
    assert w.startswith("Alexander Isak is in because you forced him in, but FPL lists him as doubtful")
    for part in ("chance of playing in GW6: 75%", "FPL as of 29 Sep 2026", "Thigh injury", "The squad is built around him as you asked."):
        assert part in w, part
    assert "suspended" in mt.forced_availability_warning([398], flags)
    assert mt.forced_availability_warning([12], flags) is None                # fit: no warning
    assert mt.forced_availability_warning([55], flags) is None                # gone (u): refused elsewhere, never warned


def test_the_warning_comes_first_in_the_result(fake_live):
    out = mt._with_forced_warning({"gw": 6, "squad": [{"player_id": 379, "name": "Alexander Isak"}]}, [379])
    assert list(out)[0] == "forced_availability_warning"
    assert mt._with_forced_warning({"gw": 6}, [12]) == {"gw": 6}
    assert mt._with_forced_warning({"error": "x"}, [379]) == {"error": "x"}


def test_a_player_who_left_is_still_refused():
    assert mt.UNAVAILABLE_STATUSES == ("u", "n")
    assert "u" not in mt.FORCED_WARN_STATUSES and "n" not in mt.FORCED_WARN_STATUSES


def test_description_and_prompt_say_quote_the_warning_and_never_claim_a_refusal():
    d = _desc("build_squad_from_scratch")
    assert "forced_availability_warning" in d and "never say this build will refuse a player without calling it" in d
    assert "A squad rule outranks availability" in PROMPT
    assert "`forced_availability_warning` -- quote that warning first, then the squad" in PROMPT
    assert "Never say the build will refuse a player without calling it." in PROMPT


# ------------------------------------------------------------------ F3: squad value and the roll question
def test_squad_value_routes_to_the_squad_record_not_the_price_tool():
    assert "squad worth" not in _desc("get_price_movements")
    assert "use get_my_squad" in _desc("get_price_movements")
    assert "'what is my team worth'" in _desc("get_my_squad")


def test_the_roll_question_calls_the_planner_without_asking_permission():
    d = _desc("propose_transfers")
    assert "never ask the user's permission to run it" in d and "'Should I roll my free transfer?'" in d
    assert "never ask the user's permission to run it" in PROMPT
    assert "\"Should I roll my free transfer?\" is a transfer question: call it directly." in PROMPT


# ------------------------------------------------------------------ F6: plain words at the reply
@pytest.mark.parametrize("raw,want", [
    ("FPL lists him with status: d (75%)", "FPL lists him with status: doubtful (75%)"),
    ("(status: i, 0%)", "(status: injured, 0%)"),
    ("his status 's'.", "his status 'suspended'."),
    ("Status: S", "Status: suspended"),
    ("over this horizon.", "over this six-gameweek plan."),
    ("the full five-gameweek horizon in raw terms", "the full five-gameweek plan in raw terms"),
    ("Horizon totals", "Six-gameweek plan totals"),
    ("| Player | Club | Price | xPts |", "| Player | Club | Price | Expected points |"),
    ("Haaland (6.63 xPts)", "Haaland (6.63 expected points)"),
    ("a real solve using the model", "a real build using the model"),
    ("solved in 1.2 seconds", "built in 1.2 seconds"),
    ("the optimiser used exactly £100.0m", "the squad builder used exactly £100.0m"),
])
def test_plain_words_rewrites_status_letters_horizon_xpts_and_builder_words(raw, want):
    assert agent.plain_words(raw) == (want, 1)


@pytest.mark.parametrize("raw", ["the flag cites a hamstring injury", "his status is unclear", "status a doubt",
                                 "This won't solve the problem", "Gabriel (DEF, Arsenal)"])
def test_plain_words_leaves_ordinary_english_alone(raw):
    assert agent.plain_words(raw) == (raw, 0)


# ------------------------------------------------------------------ F7: autosubs by name, never ids
def test_the_score_row_names_players_and_carries_no_ids(monkeypatch):
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {int(e): {"name": f"Player {e}"} for e in ids})
    row = {"gw": 5, "version_id": 24, "points_net": 52, "points_raw": 52, "hit": 0, "captain_bonus": 9, "doubled": 21,
           "doubled_role": "vice", "transfers_made": 0, "free_transfers": 1, "final_xi": [1, 14, 21],
           "subs_made": [[13, 14]], "bench_points": 3}
    out = mt._plain_score_row(row)
    assert out["substitutions"] == [{"off": "Player 13", "on": "Player 14"}]
    assert out["final_xi"] == ["Player 1", "Player 14", "Player 21"] and out["doubled"] == "Player 21"
    assert "subs_made" not in out and "captain_bonus" not in out
    assert out["captain_doubled_added"] == 9


# ------------------------------------------------------------------ F8: the one bonus sentence
def test_the_bonus_sentence_is_the_same_everywhere():
    assert BONUS in PROMPT
    assert explain.CONSTANT_LABELS["bonus_off"] == BONUS
    assert ("prompt", BONUS) in RJ.REQUIRED_SENTENCES
    assert "never a claim that a specific player will or tends to get bonus" in PROMPT


# ------------------------------------------------------------------ F9: fixtures beyond the plan
SKEL = [
    (1, 6, "Newcastle", 7, True, "2026-10-10T14:00:00Z"),
    (2, 6, "Coventry City", 14, False, "2026-10-10T14:00:00Z"),
    (1, 7, "Newcastle", 3, False, "2026-10-17T14:00:00Z"),
    (1, 8, "Newcastle", 7, False, "2026-10-24T14:00:00Z"),
]


def _row(team, gw):
    return {"team": team, "gw": gw, "team_lambda": 1.6, "opp_lambda": 1.2, "p_cs": 0.3, "horizon_step": 0,
            "odds_horizon_gws": 1, "n_fixtures": 1}


def test_a_fixture_beyond_the_plan_is_scheduled_but_not_rated_yet(monkeypatch):
    monkeypatch.setattr(ft, "_team_names", lambda: {7: "Coventry City", 14: "Newcastle", 3: "Arsenal"})
    mapping, n = ft.calendar(df=pd.DataFrame(SKEL, columns=ft.SKELETON_COLS))
    out = ft.build([_row("Newcastle", 6), _row("Newcastle", 7)], mapping, n, team="Newcastle", horizon=3)
    by_gw = {e["gw"]: e for e in out["fixtures"]}
    gw8 = by_gw[8]["fixtures"][0]
    assert gw8["difficulty"] is None
    assert gw8["rating"].startswith("scheduled but not rated yet: GW8, ")
    assert "Oct 2026" in gw8["rating"]
    assert "rating" not in by_gw[6]["fixtures"][0]
    assert "scheduled but not rated yet" in out["model_horizon"]["note"] and "never 'not scheduled'" in out["model_horizon"]["note"]
    compact = ft.build([_row("Newcastle", 6), _row("Newcastle", 7)], mapping, n, team=None, horizon=3)
    rated = [r for r in compact["fixtures"] if r.get("gw") == 8 and r.get("opponent")]
    assert rated and all(r["rating"].startswith("scheduled but not rated yet") for r in rated)


def test_the_prompt_and_description_say_scheduled_but_not_rated_yet():
    assert "Say it is scheduled but not rated yet, with its gameweek and date" in PROMPT
    assert "never call it not scheduled" in PROMPT
    assert "scheduled but not rated yet" in _desc("get_fixtures")


# ------------------------------------------------------------------ F10: counts
def test_the_prompt_says_where_a_count_comes_from():
    assert "A count you state comes from a tool's count field or from the items you list in the same reply, nothing else." in PROMPT
