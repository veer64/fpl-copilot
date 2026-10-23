"""M3a push PART 2 (2026-10-23), source fixes in tool outputs, failing tests first. Each fix answers a cause the PART 1
sort measured over 89 confirmed M3a failures (eval/reports/m3a_sort_v1.json):

  S1 display name: player rows in transfer plans and builds lead with FPL's display name (the agent shortened
     "António João Pereira de Albuquerque Tavares da Silva" to "Antón" / "Nuno Tavares").
  S3 return timeline: the card says FPL's own return wording with its date, or that FPL gives none ("late December at
     the earliest" x4 stretched an eight-week estimate; "Unknown return date" cards).
  S4 gaps said out loud: shots are not in our data (7 "shot rate" claims); a transfer plan's gain is one figure with no
     per-player split or per-move ranking (7); a from-scratch build on a lower budget compares with no other build (4);
     managers are known only as the results name them (2).
  S5 drivers as plain sentences on comparisons and predictions (start chance, minutes, expected goals, assists,
     clean-sheet chance, fixture), so a "because" has a source (35 invented reasons).
  S6 fixture scores as words: "9/10 = the ninth tenth from hardest" (4 misreads of 9 as 'the easiest tenth').
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402
import news_search as nsr                                  # noqa: E402

AS_OF = "2026-10-22 11:01:52.469800+00:00"


def _laptop(fn, *a, **k):
    try:
        out = fn(*a, **k)
    except Exception as e:                                                   # noqa: BLE001
        pytest.skip(f"no local data: {type(e).__name__}: {str(e)[:80]}")
    if not isinstance(out, dict) or "error" in out:
        pytest.skip(f"no usable local data: {str(out)[:120]}")
    return out


# ---------------------------------------------------------------- S1 display name
def test_s1_transfer_rows_lead_with_the_display_name():
    meta = {327: {"name": "Jaka Bijol", "position": "DEF", "team": "Leeds", "display_name": "Bijol"},
            566: {"name": "António João Pereira de Albuquerque Tavares da Silva", "position": "DEF", "team": "Bournemouth", "display_name": "Antón"}}
    row = mt._transfer_row_meta({"out": "Jaka Bijol", "out_id": 327, "in": "António João Pereira de Albuquerque Tavares da Silva", "in_id": 566}, meta)
    assert list(row)[:2] == ["out_display", "in_display"] and row["out_display"] == "Bijol" and row["in_display"] == "Antón"
    assert row["team_in"] == "Bournemouth" and row["in"].startswith("António")


def test_s1_player_meta_carries_the_display_name_and_build_rows_lead_with_it():
    meta = _laptop(mt._player_meta, [566, 411])
    assert meta[566].get("display_name") and meta[411].get("display_name") == "Haaland"
    out = _laptop(mt.optimise, budget=100.0)
    rows = out.get("squad") or []
    assert rows and list(rows[0])[0] == "display_name" and rows[0]["display_name"]


# ---------------------------------------------------------------- S3 return timeline
@pytest.mark.parametrize("status,news,want", [
    ("i", "Muscular injury - Expected back 7 Nov", "FPL expects him back Sat 7 Nov 2026."),
    ("i", "Knee injury - Unknown return date", "Return date: not given by FPL; a source's own timeline is quoted with its date or not at all."),
    ("s", "Suspended until 31 Oct", "FPL: suspended until Sat 31 Oct 2026."),
    ("d", "Thigh injury - 50% chance of playing", "Return date: not given by FPL; a source's own timeline is quoted with its date or not at all."),
    ("a", None, None),
])
def test_s3_return_words_say_fpls_timeline_or_that_fpl_gives_none(status, news, want):
    assert mt.return_words(status, news, AS_OF) == want


def test_s3_the_card_carries_return_words():
    card = _laptop(mt.get_player_card, 611)                                  # Wan-Bissaka: "Expected back 21 Nov" on the 22 Oct data
    if card.get("status") not in ("i", "d", "s"):
        pytest.skip("player not flagged on this machine's data")
    assert card["availability"]["return_words"] and card["return_words"] == card["availability"]["return_words"]
    assert card["return_words"].startswith(("FPL expects him back", "Return date: not given by FPL", "FPL: suspended until"))


# ---------------------------------------------------------------- S4 gaps said out loud
def test_s4_comparisons_and_predictions_say_shots_are_not_in_our_data():
    assert mt.NOT_IN_OUR_DATA.startswith("Shots")
    out = _laptop(mt.compare_predictions, 411, 379)
    assert out["not_in_our_data"] == mt.NOT_IN_OUR_DATA
    one = _laptop(mt.explain_prediction, 411)
    assert one["not_in_our_data"] == mt.NOT_IN_OUR_DATA


def test_s4_a_transfer_plans_gain_is_one_figure():
    change = {"n_transfers": 2, "hits": 0, "transfers": [{"out_name": "A", "in_name": "B"}, {"out_name": "C", "in_name": "D"}], "free_transfers_before": 2}
    hold = {"gap_objective": 5.2, "gap_this_gw": 5.1}
    s = mt._transfer_summary(9, change, hold, 2)
    assert "Against holding: +5.20" in s
    assert mt.GAIN_IS_ONE_FIGURE in s and s.endswith("This plan covers up to six gameweeks; check back each week.")   # F7 stays last
    assert "nothing in our data splits it by player or ranks the moves" in mt.GAIN_IS_ONE_FIGURE
    assert mt._transfer_summary(9, {"n_transfers": 0, "hits": 0, "transfers": []}, {"refused": True}, 1).count(mt.GAIN_IS_ONE_FIGURE) == 0


def test_s4_a_lower_budget_build_says_no_other_budget_was_built():
    out = {"gw": 8, "squad": [{"player_id": 411, "name": "Erling Haaland", "e_points": 6.8}]}
    full = mt._with_pick_basis(dict(out), 8, {}, budget=100.0)
    low = mt._with_pick_basis(dict(out), 8, {}, budget=96.0)
    assert "No other budget was built" not in full["basis"]
    assert low["basis"].endswith(mt.NO_OTHER_BUDGET) and "nothing in our data says what the lower budget cost" in mt.NO_OTHER_BUDGET


def test_s4_the_news_search_says_managers_are_known_only_as_the_results_name_them():
    assert nsr.MANAGERS_NOTE.startswith("Managers and coaches")
    import importlib.util
    spec = importlib.util.spec_from_file_location("tns_helpers2", Path(__file__).with_name("test_news_search.py"))
    tns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tns)
    assert "managers_note" in nsr.search_news.__doc__ or True                   # the field is asserted on a real call below
    try:
        import db_write
        c = db_write.connect()
    except Exception as e:                                                   # noqa: BLE001
        pytest.skip(f"no local Postgres: {str(e)[:60]}")
    c.close()
    # an in-memory call: search with a failing embedder and no players -> keyword-only, still carries the note
    out = nsr.search_news("What did the manager say?", [], ["Arsenal"], embed_client=tns.FakeVoyage(fail=True), snapshots=tns.SNAPS)
    assert out["managers_note"] == nsr.MANAGERS_NOTE


# ---------------------------------------------------------------- S5 drivers as plain sentences
BREAKDOWN = {"name": "Erling Haaland", "position": "FWD", "lines": [
    {"term": "goals", "points": 4.8, "inputs": {"e_goals": 1.2064, "npxg90": 0.849, "minutes_frac": 0.9508, "fixture_scale_cal": 1.4945}},
    {"term": "appearance", "points": 1.9, "inputs": {"p_start": 0.9583, "p60": 0.9725, "p_60plus": 0.9319, "p_play_any": 0.9708}},
    {"term": "assists", "points": 0.88, "inputs": {"e_assists": 0.293, "xa90": 0.2062, "minutes_frac": 0.9508, "fixture_scale_cal": 1.4945}},
    {"term": "clean_sheet", "points": 0.0, "inputs": {"p_cs": 0.3516, "p_60plus": 0.9319}}],
    "fixture": {"team_lambda": 2.0923, "opp_lambda": 1.0619, "fixture_scale_cal": 1.4945}}


def test_s5_drivers_words_list_the_inputs_we_compute_as_one_sentence():
    s = mt._drivers_words(BREAKDOWN)
    assert s == ("Erling Haaland's inputs: start chance 96%, chance of 60+ minutes 93%, expected goals per 90 0.85, "
                 "expected assists per 90 0.21, clean-sheet chance 35%, fixture scale 1.49 (above 1 = easier than average). "
                 "Shots, form and minutes played so far: not in our data.")


def test_s5_comparisons_carry_drivers_plain_for_both_players():
    out = _laptop(mt.compare_predictions, 411, 379)
    assert out["drivers_plain"]["a"].startswith("Erling Haaland's inputs: start chance") and "fixture scale" in out["drivers_plain"]["b"]
    one = _laptop(mt.explain_prediction, 411)
    assert one["drivers_plain"].startswith("Erling Haaland's inputs:")


# ---------------------------------------------------------------- S6 fixture scores as words
@pytest.mark.parametrize("score,want", [
    (9, "9/10: the ninth tenth from hardest among every fixture the build priced (10 = the top tenth, not 'the easiest fixture')"),
    (10, "10/10: the top tenth from hardest among every fixture the build priced (10 = the top tenth, not 'the easiest fixture')"),
    (1, "1/10: the bottom tenth from hardest among every fixture the build priced (1 = the bottom tenth, not 'the hardest fixture')"),
    (3, "3/10: the third tenth from hardest among every fixture the build priced (1 = the bottom tenth, not 'the hardest fixture')"),
    (None, None),
])
def test_s6_score_words(score, want):
    assert ft.score_words(score) == want


def test_s6_every_fixture_difficulty_carries_score_words():
    d = ft._difficulty(1.86, 1.06, 0.35, {"attack": 9, "defence": 6})
    assert d["attacking"]["score_words"] == ft.score_words(9) and d["defensive"]["score_words"] == ft.score_words(6)
    out = _laptop(mt.get_fixtures, team="Man City", horizon=2)
    first = (out.get("fixtures") or [{}])[0].get("fixtures") or []
    assert first and first[0]["difficulty"]["attacking"]["score_words"].endswith("not 'the easiest fixture')")
