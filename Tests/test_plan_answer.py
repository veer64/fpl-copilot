"""Prompt R3 (16 Nov 2026; USER DECISION "go"): the transfer plan is written by code from the planner's own result.

Measured before (eval/reports/r3_evidence_digest.md, R1's case B2, 0 of 3): the hold baseline -- "no transfer THIS gameweek
only" in the tool's own words -- was described as "doing nothing over the same 3 gameweeks" (M1) and "vs. Holding (doing
nothing)" (M14); the line-up's total, which counts the captain twice, was labelled "before captain doubling" (M23); and a
three-gameweek plan ended "This plan covers up to six gameweeks" (M24).

T1  the hold sentence says exactly what it covers and its three numbers are the planner's hold_comparison;
T2  the line-up total with the captain's points counted twice is the planner's figure; the total before that is the eleven's
    points from a whole-pool query;
T3  the header and every sentence name the plan's OWN gameweeks -- never "six";
T4  every move's predicted gain equals a whole-pool query over exactly the gameweeks shown beside it (from the move until the
    plan sells the incoming player again, or the end of the plan);
T5  free transfers used and left, hits, hit points and the bank are the planner's this_deadline / later steps;
T6  a plan that makes no transfer: no comparison paragraph, and the closing question is the planner's rolled-transfer one;
T7  a withheld comparison is said as withheld, with no gap;
T8  an error, a bug and a result without a plan carry no code-built text (the model reports them);
T9  kept / left-out players, the forced-player warning and FPL's flags are carried in;
T10 the closing question (USER DECISION), and the summary line names its own span.
Seeded pool (Tests/r3_seed.py); the planner's result is a fixture shaped like the real one; no solve, no model."""
import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

ROW = {p[0]: p for p in seed.PLAYERS}
XI = [101, 102, 103, 110, 105, 113, 121, 129, 107, 115, 123]          # after the moves; 107 the captain, 102 the vice
BENCH = [109, 118, 137, 126]


def _move(out, inn, sold=None, bought=None):
    m = {"out": ROW[out][1], "out_id": out, "in": ROW[inn][1], "in_id": inn, "bought_for": bought if bought is not None else ROW[inn][4] / 10,
         "team_out": ROW[out][3], "position_out": ROW[out][2], "team_in": ROW[inn][3], "position_in": ROW[inn][2]}
    if sold is not None:
        m["sold_for"] = sold
    return m


def _result():
    """A propose_transfers result (3 gameweeks): two moves now, one pencilled in for GW12 and one for GW13 that sells again
    a player bought now (106 in for 104 at GW11, 106 out for 122 at GW13)."""
    xi_rows = [{"player_id": e, "name": ROW[e][1], "position": ROW[e][2], "team": ROW[e][3],
                "role": "CAPTAIN" if e == 107 else "VICE" if e == 102 else "start", "bench_order": None,
                "e_points": round(seed.e_points(e, 11), 2)} for e in XI]
    return {
        "summary_plain": "…", "proposal_id": 501, "source": "chat", "gw": 11, "run_id": seed.RUN_ID, "horizon": 3, "effective_horizon": 3,
        "locked": [], "banned": [], "hold_applied": False, "rolled_transfer": None,
        "hold_comparison": {"basis": "hold THIS gameweek only: step 0 forced to zero transfers, steps 1-5 free", "move_objective": 99.804,
                            "hold_objective": 86.365, "move_predicted_xi_points": 60.75, "hold_predicted_xi_points": 48.56,
                            "refused": False, "gap_objective": 13.439, "gap_this_gw": 12.19},
        "this_deadline": {"verdict": "2 transfer(s), 0 hit(s)",
                          "transfers": [_move(104, 106, sold=5.2), _move(116, 108, sold=7.3)],
                          "hits": 0, "hit_cost_points": 0, "free_transfers_before": 3, "free_transfers_after": 1,
                          "bank_before": 0.4, "bank_after": 0.1, "captain": ROW[107][1], "vice": ROW[102][1],
                          "xi": xi_rows, "bench_in_order": [], "predicted_xi_points": 60.75},
        "later_steps_indicative": [
            {"horizon_step": 1, "gw": 12, "hits": 0, "free_transfers": 2, "transfers": [_move(109, 117)], "captain": ROW[107][1]},
            {"horizon_step": 2, "gw": 13, "hits": 0, "free_transfers": 2, "transfers": [_move(106, 122), _move(118, 119)], "captain": ROW[107][1]}],
        "apply_with": {"player_ids": XI + BENCH, "captain_id": 107, "vice_id": 102, "bench_order_ids": BENCH, "gw": 11, "proposal_id": 501, "confirm": True},
    }


def _points(conn, e, gws):
    return seed.q(conn, "SELECT round(COALESCE(sum(e_points::float8), 0)::numeric, 2) FROM model_predictions WHERE run_id = 1 "
                        "AND config = 'baseline' AND element = %s AND gw = ANY(%s)", (e, list(gws)))[0][0]


def _text(res):
    out = mt._with_plan_answer(res)
    assert "direct_reply_error" not in out, out.get("direct_reply_error")
    return out["direct_reply"]


def test_t1_the_hold_sentence_says_what_it_covers_and_its_numbers_are_the_planners(pool_db):
    text = _text(_result())
    assert ("**Against making no transfer this gameweek only** (the same 15 kept for GW11; later gameweeks still free to transfer): "
            "this plan's line-up scores 60.75 predicted points for GW11 against 48.56 without the moves (+12.19, captain counted twice "
            "in both). On the plan's weighted total over GW11–13, where each later gameweek counts for less, it is +13.44.") in text
    low = text.lower()
    for wrong in ("doing nothing", "over the same", "before captain doubling", "six gameweeks", "six-week"):
        assert wrong not in low                                              # the four R1 descriptions cannot be produced
    neg = _result()
    neg["hold_comparison"].update(gap_objective=-0.213, gap_this_gw=-1.5, move_predicted_xi_points=47.06)
    assert "against 48.56 without the moves (−1.50, captain counted twice in both)" in _text(neg) and "it is −0.21." in _text(neg)


def test_t2_the_line_up_total_both_ways(pool_db):
    text = _text(_result())
    once = seed.q(pool_db, "SELECT round(sum(e_points::float8)::numeric, 2) FROM model_predictions WHERE run_id = 1 AND gw = 11 "
                           "AND element = ANY(%s)", (XI,))[0][0]
    assert (f"Line-up after these moves: 60.75 predicted points for GW11 with the captain's points counted twice ({once:.2f} before "
            f"that). Captain {ROW[107][1]}, vice-captain {ROW[102][1]}.") in text


@pytest.mark.parametrize("k", [1, 3, 6])
def test_t3_the_header_names_the_plans_own_gameweeks(pool_db, k):
    res = _result()
    res["effective_horizon"] = res["horizon"] = k
    res["later_steps_indicative"] = [s for s in res["later_steps_indicative"] if s["gw"] < 11 + k]
    head = _text(res).split("\n")[0]
    span = "GW11 (1 gameweek)" if k == 1 else f"GW11–{10 + k} ({k} gameweeks)"
    assert head == f"**Transfer plan for {span}: 2 transfers for the GW11 deadline, 0 hits.**"
    assert _text(res).split("\n")[1] == f"Predictions from the update of Wed 11 Nov 2026, 11:01 UTC. Next update: {seed.NEXT_UPDATE}."
    assert mt._plan_span_words(11, k) == span


def test_t4_every_gain_equals_a_whole_pool_query_over_the_gameweeks_shown(pool_db):
    text = _text(_result())
    tabs = seed.tables(text)
    assert [h for h, _ in tabs] == [["Out", "Sells for", "In", "Costs", "Predicted gain", "Counted over"],
                                    ["Out", "In", "Costs", "Predicted gain", "Counted over"],
                                    ["Out", "In", "Costs", "Predicted gain", "Counted over"]]
    #       (out, in, the gameweeks the incoming player is in the plan's squad)
    want = [[(104, 106, [11, 12]), (116, 108, [11, 12, 13])],                # 106 is sold again at GW13: counted GW11-12 only
            [(109, 117, [12, 13])],
            [(106, 122, [13]), (118, 119, [13])]]
    for (head, rows), moves in zip(tabs, want):
        assert len(rows) == len(moves)
        for cells, (o, i, gws) in zip(rows, moves):
            a, b = _points(pool_db, i, gws), _points(pool_db, o, gws)
            gain = a - b
            sign = "+" if gain > 0 else "−" if gain < 0 else ""
            assert cells[head.index("Predicted gain")] == f"{sign}{abs(gain):.2f} ({a:.2f} against {b:.2f})", (o, i)
            assert cells[head.index("Counted over")] == ("GW13" if gws == [13] else f"GW{gws[0]}–{gws[-1]}")
            assert cells[0] == f"{ROW[o][1]} ({ROW[o][2]}, {ROW[o][3]})" and cells[head.index("In")] == f"{ROW[i][1]} ({ROW[i][2]}, {ROW[i][3]})"
            assert cells[head.index("Costs")] == f"£{ROW[i][4] / 10:.1f}m"
    assert tabs[0][1][0][1] == "£5.2m" and tabs[0][1][1][1] == "£7.3m"         # what each sells for: the planner's figure
    assert ("Predicted gain = the incoming player's predicted points minus the outgoing player's, added over the gameweeks shown beside "
            "it (from the move until the plan sells him again, or the end of the plan).") in text


def test_t4b_a_sale_with_no_paired_buy_still_ends_the_count_and_is_shown(pool_db):
    res = _result()
    lone = {"out": ROW[106][1], "out_id": 106, "in": None, "in_id": None, "bought_for": None, "team_out": ROW[106][3], "position_out": ROW[106][2]}
    res["later_steps_indicative"][1]["transfers"] = [lone]                 # 106, bought at GW11, leaves at GW13 with no named buy
    text = _text(res)
    tabs = seed.tables(text)
    first = tabs[0][1][0]
    a, b = _points(pool_db, 106, [11, 12]), _points(pool_db, 104, [11, 12])
    assert first[4] == f"{'+' if a > b else '−' if a < b else ''}{abs(a - b):.2f} ({a:.2f} against {b:.2f})" and first[5] == "GW11–12"
    assert tabs[2][1] == [[f"{ROW[106][1]} ({ROW[106][2]}, {ROW[106][3]})", "—", "—", "—", "—"]]   # shown, nothing to compare


def test_t5_free_transfers_hits_and_the_bank_are_the_planners(pool_db):
    text = _text(_result())
    assert "Free transfers: 3 available, 2 used, 1 left. Hits: 0 (0 points). Bank: £0.4m before, £0.1m after." in text
    assert "Free transfers: 2 available, 1 used, 1 left. Hits: 0 (0 points)." in text            # GW12
    assert "Free transfers: 2 available, 2 used, 0 left. Hits: 0 (0 points)." in text            # GW13: the one left over plus the one earned (R3b: by FPL's rule, was "1 available ... Hits: 1" from a fixture no plan can produce)
    hit = _result()
    hit["this_deadline"].update(hits=1, hit_cost_points=4, free_transfers_before=1, free_transfers_after=0)
    t = _text(hit)
    assert t.split("\n")[0] == "**Transfer plan for GW11–13 (3 gameweeks): 2 transfers for the GW11 deadline, 1 hit.**"
    assert "Free transfers: 1 available, 1 used, 0 left. Hits: 1 (4 points). Bank: £0.4m before, £0.1m after." in t
    lines = text.split("\n")
    assert "**GW11, this deadline** (the moves you can make now):" in lines
    assert "**GW12, pencilled in** (decided again that week, on that week's predictions and prices):" in lines
    assert "**GW13, pencilled in** (decided again that week, on that week's predictions and prices):" in lines


def test_t6_a_plan_that_holds(pool_db):
    res = _result()
    res["this_deadline"].update(transfers=[], free_transfers_before=1, free_transfers_after=1, bank_after=0.4, verdict="HOLD -- no transfer")
    res["hold_comparison"].update(gap_objective=0.0, gap_this_gw=0.0)
    res["rolled_transfer"] = {"offered": True, "question": "You are holding, so a second free transfer rolls to GW12. Shall I explore what two free transfers at GW12 opens up?"}
    text = _text(res)
    lines = text.split("\n")
    assert lines[0] == "**Transfer plan for GW11–13 (3 gameweeks): no transfer for the GW11 deadline.**"
    assert "No transfer." in lines and "Against making no transfer" not in text
    assert "Free transfers: 1 available, 0 used, 1 left. Hits: 0 (0 points). Bank: £0.4m before, £0.4m after." in text
    assert "Line-up as it stands: 60.75 predicted points for GW11 with the captain's points counted twice" in text
    assert lines[-1] == res["rolled_transfer"]["question"]
    res["rolled_transfer"] = {"offered": False, "refused": True, "reason": "Not while the model is degraded."}
    assert _text(res).split("\n")[-1] == answers.PLAN_FOLLOW_UP


def test_t7_a_withheld_comparison_is_said_as_withheld(pool_db):
    res = _result()
    res["hold_comparison"].update(refused=True, gap_objective=None, gap_this_gw=None, refusal="…")
    text = _text(res)
    assert ("**Against making no transfer:** this comparison is withheld this week. A club's team-strength estimate has run off inside "
            "these gameweeks, so the gap cannot be measured honestly.") in text
    assert "+13.44" not in text and "+12.19" not in text and "this gameweek only" not in text


@pytest.mark.parametrize("res", [{"error": "the transfer MIP could not produce a plan"},
                                 {"error": "VALUATION MISMATCH -- a bug, not a suggestion", "bug": True},
                                 {"bug": True, "this_deadline": {}}, {"no_squad": True, "note": "no squad saved yet"}])
def test_t8_an_error_or_a_bug_carries_no_code_built_text(pool_db, res):
    assert mt._with_plan_answer(dict(res)) == res


def test_t8b_a_failure_while_writing_leaves_the_result_for_the_model(pool_db):
    res = _result()
    del res["this_deadline"]["free_transfers_before"]
    out = mt._with_plan_answer(res)
    assert "direct_reply" not in out and out["direct_reply_error"].startswith("KeyError") and out["proposal_id"] == 501


def test_t9_kept_left_out_warning_and_flags(pool_db):
    res = _result()
    res["locked"], res["banned"] = [ROW[107][1]], [ROW[130][1], ROW[140][1]]
    res = {"forced_availability_warning": f"{ROW[106][1]} is flagged doubtful by FPL; he was kept in because you asked.", **res}
    text = _text(res)
    assert text.split("\n")[1] == res["forced_availability_warning"]
    assert f"Kept in the squad: {ROW[107][1]}. Left out: {ROW[130][1]}, {ROW[140][1]}." in text
    assert (f'Flags: {ROW[106][1]}: Doubtful — FPL: "Knock - 75% chance of playing" (as of Wed 11 Nov); '
            f'{ROW[109][1]}: Doubtful — FPL: 50% chance of playing (as of Wed 11 Nov).') in text      # every flagged player of a move
    assert "Flags:" not in _text({**_result(), "this_deadline": {**_result()["this_deadline"], "transfers": [_move(116, 108, sold=7.3)]},
                                  "later_steps_indicative": []})


def test_t10_the_closing_question_and_the_summary_line(pool_db):
    lines = _text(_result()).split("\n")
    assert lines[-1] == "Want me to preview any of these moves?" and lines[-2] == "" and lines[-3] == answers.BONUS_NOTE
    assert lines[-4] == ("GW11 is priced off the betting market. GW12–13 are longer-range estimates from team strengths, with no odds, "
                         "lineups or team news yet, so these will move before then.")
    change = {"n_transfers": 2, "hits": 0, "transfers": [{"out_name": "A", "in_name": "B"}, {"out_name": "C", "in_name": "D"}]}
    hc = {"refused": False, "gap_objective": 13.439, "gap_this_gw": 12.19}
    assert mt._transfer_summary(11, change, hc, 3, span="GW11–13 (3 gameweeks)") == (
        "For GW11: 2 transfers, 0 hits (A out, B in, C out, D in). Against making no transfer this gameweek only: +13.44 on the plan's "
        "weighted total over GW11–13 (later gameweeks count for less), +12.19 predicted line-up points for this deadline alone. "
        "This plan covers GW11–13 (3 gameweeks); check back each week.")


def test_t11_the_result_keeps_what_a_follow_up_needs(pool_db):
    res = _result()
    out = mt._with_plan_answer(copy.deepcopy(res))
    assert {k: v for k, v in out.items() if k != "direct_reply"} == res      # nothing of the planner's result is changed
    assert out["apply_with"]["proposal_id"] == 501
