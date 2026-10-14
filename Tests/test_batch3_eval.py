"""Fix batch 3 (2026-10-14), the eval side: the club checker reads transfer entries (F2), the gate's regression rule
(F11), and the judge's M4 rule for players the USER forced in (F12). No network, no database."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_agent_evals as rae                              # noqa: E402
from judge import club_claims as CC                        # noqa: E402
from judge import metrics as M                             # noqa: E402

PLAYERS = [{"element": 533, "name": "Nordi Mukiele", "position": "DEF", "team": "Sunderland"},
           {"element": 327, "name": "Jaka Bijol", "position": "DEF", "team": "Leeds"}]


# ------------------------------------------------------------------ F2: transfer entries are sourced rows
def test_a_club_named_in_a_transfer_entry_is_sourced():
    plan = {"later_steps_indicative": [{"gw": 8, "transfers": [
        {"out": "Jaka Bijol", "out_id": 327, "in": "Nordi Mukiele", "in_id": 533, "team_out": "Leeds",
         "position_out": "DEF", "team_in": "Sunderland", "position_in": "DEF"}]}]}
    rec = {"rendered_reply": "- **GW8:** Bijol -> Mukiele (Sunderland), 1 hit", "calls": [{"tool": "propose_transfers", "output": str(plan)}]}
    rows = CC.check(rec, PLAYERS)
    muk = [r for r in rows if r["player"] == "Nordi Mukiele"]
    assert muk and muk[0]["status"] == "sourced_ok" and muk[0]["tool_club"] == "Sunderland"
    assert CC.summary(rows)["unsourced"] == 0


def test_rows_in_keeps_named_rows_and_adds_both_transfer_sides():
    out = []
    CC._rows_in({"squad": [{"name": "Bukayo Saka", "team": "Arsenal"}],
                 "transfers": [{"out": "A", "out_id": 1, "in": "B", "in_id": 2, "team_out": "X", "team_in": "Y"}]}, out)
    names = {r["name"]: r.get("team") for r in out}
    assert names == {"Bukayo Saka": "Arsenal", "A": "X", "B": "Y"}


# ------------------------------------------------------------------ F11: the regression rule
CTX = "CONTEXT BLOCK\n- Now: Tuesday 2026-10-13 00:44 UTC.\n- Gameweeks: GW5 is the last finished gameweek; GW6 is in progress."
CTX_LATER = CTX.replace("00:44", "00:51")
NO_DATA = "CONTEXT BLOCK\n- Now: Tuesday 2026-10-13 00:44 UTC.\n- Gameweeks: no gameweek has finished yet."


def _r(result, ctx):
    return {"result": result, "turns": [{"kind": "question", "context_block": ctx}]}


def test_the_context_signature_ignores_only_the_clock_line():
    assert rae.context_signature(CTX) == rae.context_signature(CTX_LATER)
    assert rae.context_signature(CTX) != rae.context_signature(NO_DATA)


def test_confirmed_needs_base_three_of_three_on_heads_data_and_head_failing_twice():
    base = [_r("PASS", CTX)] * 3
    v = rae.classify_regression(base, [_r("FAIL", CTX_LATER), _r("FAIL", CTX), _r("PASS", CTX)])
    assert v["verdict"] == "CONFIRMED" and v["base_pass"] == 3 and v["head_fail"] == 2
    assert rae.classify_regression(base, [_r("FAIL", CTX), _r("PASS", CTX), _r("PASS", CTX)])["verdict"] == "FLAKY"
    assert rae.classify_regression([_r("PASS", CTX), _r("FAIL", CTX), _r("PASS", CTX)],
                                   [_r("FAIL", CTX)] * 3)["verdict"] == "FLAKY"


def test_a_base_run_without_heads_data_does_not_count():
    v = rae.classify_regression([_r("PASS", NO_DATA)] * 3, [_r("FAIL", CTX)] * 3)
    assert v["verdict"] == "NOT DETERMINED" and v["base_excluded"] == 3 and v["base_counted"] == 0
    v = rae.classify_regression([_r("PASS", CTX)] * 2 + [_r("PASS", NO_DATA)], [_r("FAIL", CTX)] * 3)
    assert v["verdict"] == "NOT DETERMINED" and v["base_counted"] == 2


def test_head_runs_on_different_data_are_not_determined():
    assert rae.classify_regression([_r("PASS", CTX)] * 3, [_r("FAIL", CTX), _r("FAIL", NO_DATA), _r("FAIL", CTX)])["verdict"] == "NOT DETERMINED"


# ------------------------------------------------------------------ F12: M4 and a player the user forced in
def _forced_record(reply):
    squad = {"forced_availability_warning": "Alexander Isak is in because you forced him in, but FPL lists him as injured: "
                                            "chance of playing in GW7: 0%. The squad is built around him as you asked.",
             "squad": [{"player_id": 379, "name": "Alexander Isak", "status_word": "injured", "chance": 0, "e_points": 3.42, "role": "start"}]}
    calls = [{"tool": "build_squad_from_scratch", "args": {"start_player_ids": [379]}, "output": str(squad)}]
    return {"id": "forced_starters:9", "sheet": "forced_starters", "calls": calls, "rendered_reply": reply,
            "turns": [{"kind": "question", "calls": calls, "reply": reply, "context_block": "CONTEXT BLOCK"}]}


def test_a_status_word_alone_flags_a_player():
    assert M._is_flagged({"name": "Isak", "status_word": "injured"})
    assert not M._is_flagged({"name": "Saka", "status_word": "available"})


def test_m4_marks_a_player_the_user_forced_in():
    rec = _forced_record("Isak is injured (0% to play in GW7) -- you forced him in, so the squad starts him: 3.42 points.")
    flags = M.m4_flags(rec)
    assert flags and flags[0][0] == "Alexander Isak" and flags[0][1] == M.UNAVAILABLE_TIER
    assert flags[0][2].endswith("; forced in by the user")
    text = M.metric_text("M4", record=rec)
    assert "forced in by the user" in text and "says he was forced in at the user's request" in text


def test_m4_without_a_forced_player_has_no_marker():
    rec = _forced_record("Isak is injured (0%). 3.42 points.")
    rec["calls"][0]["args"] = {}
    rec["calls"][0]["output"] = str({"squad": [{"player_id": 379, "name": "Alexander Isak", "status_word": "injured", "chance": 0}]})
    flags = M.m4_flags(rec)
    assert flags and "forced in by the user" not in flags[0][2]
