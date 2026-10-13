"""LLM judge, final (2026-10-13): M4 redefined in two tiers (UNAVAILABLE: flag before any number, never recommended;
DOUBTFUL: flag stated somewhere, order free) and the per-answer tier list in the M4 prompt. No network."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
from judge import metrics as M                             # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

CARD = {"player_id": 26, "name": "Kai Havertz", "team": "Arsenal", "status": "d", "chance": 75, "news": "Knee injury",
        "prediction": {"predictions": [{"gw": 7, "e_points": 3.7}]}}
OUT = {"player_id": 7, "name": "Alexander Isak", "team": "Liverpool", "status": "i", "chance": 0, "news": "Thigh injury - Unknown return date"}


def _record(reply, calls, qid="get_player_card:1", sheet="get_player_card"):
    turns = [{"kind": "question", "message": "q", "reply": reply, "calls": calls, "context_block": "CONTEXT BLOCK\n- Now: x"}]
    return {"id": qid, "sheet": sheet, "question": "q", "setup": None, "turns": turns, "calls": calls,
            "rendered_reply": reply, "raw_reply": reply, "result": "PASS"}


# ------------------------------------------------------------------ M4 tiers
def test_m4_flag_tiers_follow_status_and_chance():
    assert M.flag_tier({"status": "d", "chance": 75}) == "DOUBTFUL"
    assert M.flag_tier({"status": "d"}) == "DOUBTFUL"                           # resolve_player rows carry status only
    assert M.flag_tier({"status": "i", "chance": 50}) == "DOUBTFUL"
    assert M.flag_tier({"status": "s", "chance": 0}) == "UNAVAILABLE"
    assert M.flag_tier({"status": "i", "chance": 0}) == "UNAVAILABLE"
    assert M.flag_tier({"status": "i"}) == "UNAVAILABLE"                        # injured, chance unknown: not playable
    assert M.flag_tier({"status": "u"}) == "UNAVAILABLE"
    assert M.flag_tier({"status": "u", "available": False, "availability_note": "Has joined Al Hilal"}) == "UNAVAILABLE"
    assert M.flag_tier({"status": "a", "chance": 50}) == "DOUBTFUL"               # a chance below 100 with no code


def test_m4_metric_text_states_the_two_tier_rule_and_lists_this_answers_flagged_players():
    calls = [{"tool": "get_player_card", "args": {}, "error": None, "output": str(CARD)},
             {"tool": "get_player_card", "args": {}, "error": None, "output": str(OUT)}]
    rec = _record("Isak is out (0%). Havertz: 3.7 points, and he is 75% to play.", calls)
    text = M.metric_text("M4", record=rec)
    q = M.metric_question("M4")
    assert "UNAVAILABLE" in q and "BEFORE any predicted number" in q and "DOUBTFUL" in q and "order does not matter" in q
    assert "Kai Havertz -- DOUBTFUL (status d, 75% chance of playing, note: Knee injury)" in text
    assert "Alexander Isak -- UNAVAILABLE (status i, 0% chance of playing, note: Thigh injury - Unknown return date)" in text
    assert "price-only mention" in M.metric_text("M4")                           # the trigger is unchanged
    assert "Flagged players the reply engages with" not in M.metric_text("M4")   # no record: no list


def test_m4_flag_list_names_only_the_players_the_reply_engages_with():
    calls = [{"tool": "get_player_card", "args": {}, "error": None, "output": str(CARD)},
             {"tool": "get_player_card", "args": {}, "error": None, "output": str(OUT)}]
    rec = _record("Havertz: 3.7 points, and he is 75% to play.", calls)
    assert M.m4_flags(rec) == [("Kai Havertz", "DOUBTFUL", "status d, 75% chance of playing, note: Knee injury")]
    prompt = RJ.build_prompt(rec, "M4")
    assert "Kai Havertz -- DOUBTFUL" in prompt and "Alexander Isak --" not in prompt.split("<metric>")[1]


def test_m4_applicability_is_unchanged_by_the_redefinition():
    calls = [{"tool": "get_player_card", "args": {}, "error": None, "output": str(OUT)}]
    assert M.applicable("M4", _record("Isak is expected to score 5 points.", calls)) is True
    assert M.applicable("M4", _record("That squad is infeasible: four forwards. Isak costs £9.1m.", calls)) is False
    assert M.applicable("M4", _record("Nothing on Liverpool this week.", calls)) is False


# ------------------------------------------------------------------ M3b attribution check by code (eval/judge/attribution_check.py)
def test_attribution_check_reads_tables_sentences_and_stat_families():
    from judge import attribution_check as AC
    idx = AC.player_index([{"element": 12, "name": "Bukayo Saka"}, {"element": 20, "name": "Bryan Mbeumo"}, {"element": 30, "name": "Cody Gakpo"},
                           {"element": 41, "name": "Andres Garcia"}, {"element": 42, "name": "Gonzalo Garcia"}])
    reply = ("**Saka (GW7): 5.2 pts expected. Mbeumo: 4.9.**\n\n| Player | Club | Price | xPts (GW6) |\n|---|---|---|---|\n"
             "| Gonzalo Garcia | Fulham | £6.0m | 3.3 |\n\nHe has a lower clean sheet chance (25% vs Saka's 44%).")
    rec = {"id": "x", "rendered_reply": reply, "turns": [{"context_block": "- next deadline: GW7"}], "calls": []}
    saka = {"claim": "5.2", "number": 5.2, "context": "**Saka (GW7): 5.2 pts expected. Mbeumo: 4.9.**  | Player | Club | Price", "quote": "'name': 'Bukayo Saka', 'gw': 7, 'e_points': 5.2", "inputs": None}
    assert AC.check_player(saka, rec, idx)[0] == "MATCH" and AC.check_gw(saka, rec)[0] == "MATCH" and AC.check_stat(saka, rec)[0] == "MATCH"
    mbeumo = dict(saka, claim="4.9", number=4.9, quote="'name': 'Bukayo Saka', 'gw': 7, 'e_points': 4.9")
    assert AC.check_player(mbeumo, rec, idx)[0] == "CONFLICT"                   # Mbeumo's number quoted from Saka's row
    cell = {"claim": "3.3", "number": 3.3, "context": "| Gonzalo Garcia | Fulham | £6.0m | 3.3 |  He has a lower", "quote": "'name': 'Gonzalo Garcia', 'gw': 6, 'e_points': 3.3", "inputs": None}
    assert AC.check_player(cell, rec, idx) == ("MATCH", "nearest Gonzalo Garcia (same table row) is in the quote")
    assert AC.check_stat(cell, rec)[0] == "MATCH" and AC.check_gw(cell, rec)[0] == "MATCH"   # column header 'xPts (GW6)'
    price = dict(cell, claim="£6.0m", number=6.0, quote="'name': 'Gonzalo Garcia', 'price': 6.0")
    assert AC.check_stat(price, rec)[0] == "MATCH"
    wrong_stat = dict(cell, quote="'name': 'Gonzalo Garcia', 'gw': 6, 'price': 3.3")
    assert AC.check_stat(wrong_stat, rec)[0] == "CONFLICT"
    pron = {"claim": "25%", "number": 25.0, "context": "He has a lower clean sheet chance (25% vs Saka's 44%).", "quote": "'name': 'Bryan Mbeumo', 'p_cs': 0.25", "inputs": None}
    assert AC.check_player(pron, rec, idx)[0] == "NOT CHECKABLE"                 # a pronoun subject: the code does not resolve it
