"""Prompt R3b item 4 (16 Nov 2026): the transfer plan honours a stated number of transfers.

Measured before (eval/reports/r3_answers.md, Set A): "What's the best squad I can reach from here with two transfers?" got
the full five-move plan three times out of three, with no mention of "two" -- the planner had no way to be told.

X1   no limit named: the plan is the plan it always was (the same squad, the same moves, the same objective);
X2   a limit is the most transfers the WHOLE plan makes, across every gameweek of it -- the move plan and the hold baseline;
X3   a limit of 0 makes no transfer at all; a limit the kept / left-out players cannot fit is said as such, never ignored;
X4   propose_transfers checks the number before anything is read and passes it to the planner; a draft chat is untouched;
X5   the answer states the limit in words in its header, says how many transfers the plan makes, and says the baseline was
     held to the same limit; with no limit the text is what it was;
X6   the tool's schema takes max_transfers and its description tells the model to pass any number the user names;
X8   ONE transfer: the two statements handed to the solver (the buy is funded by the same gameweek's sale of a player of
     his position; a dominated player is never the one bought) change no optimum -- the same objective with and without
     them, over several pools, banks and plan lengths, with a kept and a left-out player;
X7   a pencilled-in gameweek's free transfers follow FPL's rule from the gameweek before it (what was left, plus one, at most
     five) -- never the planner's own counter, which read "0 available" in a gameweek with no move.
Synthetic pools and real solves (HiGHS in process); the seeded pool for the text; no model, no network."""
import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
import simulator                                            # noqa: E402
import transfer_mip                                         # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)
from simulator import decide_gameweek_mip                   # noqa: E402
from squad_state import SquadState                          # noqa: E402
from test_optimize import make_random_pool                  # noqa: E402
from test_plan_answer import _result                        # noqa: E402
from test_transfer_mip import a_squad, squad_frame          # noqa: E402
from transfer_mip import build_and_solve                    # noqa: E402


def _pool(seed_=3):
    pool = make_random_pool(seed_)
    for c, v in (("p_play_any", 0.9), ("p_60plus", 0.8)):
        if c not in pool.columns:
            pool[c] = v
    return pool


def _setup(T=3):
    pool = _pool()
    squad = a_squad(pool)
    pools = {11 + t: pool for t in range(T)}
    purchase = {e: int(pool.loc[pool["element"] == e, "value"].iloc[0]) for e in squad}
    return pool, squad, pools, purchase


def _solve(pools, squad, purchase, **kw):
    status, plan = build_and_solve(pools, current_squad=squad, purchase_prices=purchase, bank=20, free_transfers=5, **kw)
    assert status == "Optimal", status
    return plan


def _made(plan):
    return sum(int(st["transfers_made"]) for st in plan)


def test_x1_no_limit_is_the_plan_it_always_was():
    _pool_, squad, pools, purchase = _setup()
    a = _solve(pools, squad, purchase)
    b = _solve(pools, squad, purchase, max_transfers=None)
    assert a[0]["objective"] == pytest.approx(b[0]["objective"], abs=1e-9)
    assert [(st["squad"], st["buys"], st["sells"], st["hits"]) for st in a] == [(st["squad"], st["buys"], st["sells"], st["hits"]) for st in b]
    assert _made(a) > 2                                                      # the free plan makes more than two moves: the limit below bites


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_x2_a_limit_is_the_most_transfers_the_whole_plan_makes(limit):
    _pool_, squad, pools, purchase = _setup()
    free = _solve(pools, squad, purchase)
    capped = _solve(pools, squad, purchase, max_transfers=limit)
    assert _made(capped) <= limit < _made(free)
    assert _made(capped) == limit                                            # worth making: the limit is used, not merely respected
    assert capped[0]["objective"] <= free[0]["objective"] + 1e-9
    for st in capped:
        assert len(st["squad"]) == 15 and len(st["buys"]) == len(st["sells"]) == st["transfers_made"]


def test_x2b_the_limit_counts_every_gameweek_of_the_plan_not_each_one():
    _pool_, squad, pools, purchase = _setup(T=3)
    capped = _solve(pools, squad, purchase, max_transfers=2)
    assert sum(len(st["buys"]) for st in capped) <= 2
    one = _solve({11: pools[11]}, squad, purchase, max_transfers=2)
    assert _made(one) <= 2


def test_x2c_the_hold_baseline_is_held_to_the_same_limit():
    pool, squad, pools, _purchase = _setup()
    df = pd.concat([pool.assign(gw=g, cutoff=11) for g in (11, 12, 13)], ignore_index=True)
    prices = dict(zip(pool["element"], pool["value"]))
    state = SquadState(squad_frame(pool, squad), bank=20, free_transfers=5)
    _team, transfers, step, _eff, plan = decide_gameweek_mip(df, 11, state, pool, prices, [11, 12, 13], horizon=3, cutoff=11,
                                                              return_plan=True, hold_compare=True, max_transfers=2)
    assert len(transfers) <= 2 and _made(plan) <= 2
    hold = step["hold_plan"]
    assert hold is not None and int(hold[0]["transfers_made"]) == 0 and _made(hold) <= 2
    free = decide_gameweek_mip(df, 11, SquadState(squad_frame(pool, squad), bank=20, free_transfers=5), pool, prices, [11, 12, 13],
                               horizon=3, cutoff=11, return_plan=True, hold_compare=True)
    assert _made(free[4]) > 2 and len(free) == 5                              # the default is what it was


def test_x3_zero_makes_no_transfer_and_an_impossible_limit_is_not_ignored():
    pool, squad, pools, purchase = _setup()
    none = _solve(pools, squad, purchase, max_transfers=0)
    assert _made(none) == 0 and all(sorted(st["squad"]) == sorted(squad) for st in none)
    out = pool[~pool["element"].isin(squad)]
    locks = [int(out[out["position"] == pos].sort_values("value")["element"].iloc[0]) for pos in ("DEF", "MID", "FWD")]
    status, plan = build_and_solve(pools, current_squad=squad, purchase_prices=purchase, bank=200, free_transfers=5,
                                   locked_elements=locks, max_transfers=2)
    assert plan is None and status != "Optimal"                              # three players to bring in, two transfers: no plan, said as such


def test_x4_the_tool_checks_the_number_first_and_passes_it_on(monkeypatch):
    for bad in (-1, 16, 2.5, "two", True):
        out = mt.propose_transfers(max_transfers=bad, user_id=424242)
        assert out == {"error": f"max_transfers must be a whole number from 0 to 15, got {bad!r}"}, bad
    assert mt._plan_transfer_limit(None) == (None, None) and mt._plan_transfer_limit("2") == (2, None) and mt._plan_transfer_limit(2.0) == (2, None)

    pool = _pool()
    squad = a_squad(pool)
    rows = []
    by_pos = {pos: [e for e in squad if pool.loc[pool["element"] == e, "position"].iloc[0] == pos] for pos in ("GK", "DEF", "MID", "FWD")}
    bench = [by_pos["GK"][1], by_pos["DEF"][4], by_pos["MID"][4], by_pos["FWD"][2]]
    for e in squad:
        r = pool[pool["element"] == e].iloc[0]
        role = "bench" if e in bench else "CAPTAIN" if e == by_pos["FWD"][0] else "VICE" if e == by_pos["MID"][0] else "start"
        rows.append({"element": int(e), "name": r["name"], "position": r["position"], "team": r["team"], "purchase_price": int(r["value"]),
                     "role": role, "bench_order": bench.index(e) + 1 if e in bench else None})
    import squad_store
    doc = squad_store.document(pd.DataFrame(rows), 20, 1, 0, "2026-27", {"kind": "test"})
    record = {"squad_json": doc, "season": "2026-27", "gw": 11, "version_id": 7, "created_at": "2026-11-10T00:00:00Z"}
    df = pd.concat([pool.assign(gw=g, cutoff=11) for g in (11, 12, 13)], ignore_index=True)
    live = [{"element": int(r.element), "name": r.name, "position": r.position, "team": r.team, "price_tenths": int(r.value), "updated_at": None}
            for r in pool.itertuples()]
    monkeypatch.setattr(mt, "_draft_turn", lambda: None)
    monkeypatch.setattr(mt, "_squad_owner", lambda user_id: user_id)
    monkeypatch.setattr(mt, "_read_active", lambda user_id: record)
    monkeypatch.setattr(mt, "_current_gw", lambda: 11)
    monkeypatch.setattr(mt, "_load_frame", lambda: (df, 11, None))
    monkeypatch.setattr(mt.squad_store, "free_transfers_at", lambda rec, gw: 5)
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [r for r in live if r["element"] in set(params[0])])
    seen = {}

    def stop(*a, **kw):
        seen.update(kw)
        raise RuntimeError("stopped by the test")

    monkeypatch.setattr(simulator, "decide_gameweek_mip", stop)
    out = mt.propose_transfers(horizon=3, max_transfers=2, user_id=424242)
    assert seen["max_transfers"] == 2 and seen["horizon"] == 3 and seen["hold_compare"] is True
    assert "error" in out and "a limit of 2 transfers was set" in out["error"]
    seen.clear()
    out = mt.propose_transfers(horizon=3, user_id=424242)
    assert seen["max_transfers"] is None and "a limit of" not in out["error"]  # no number named: today's call


def test_x4b_a_draft_chat_is_untouched(monkeypatch):
    import draft_tools
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    monkeypatch.setattr(draft_tools, "free_swaps", lambda d: {"draft": True, "swaps": []})
    assert mt.propose_transfers(max_transfers="nonsense") == {"draft": True, "swaps": []}


def _text(res):
    out = mt._with_plan_answer(res)
    assert "direct_reply_error" not in out, out.get("direct_reply_error")
    return out["direct_reply"]


def test_x5_the_answer_states_the_limit_in_words(pool_db):
    res = _result()                                                          # 2 moves now, 1 at GW12, 2 at GW13: five in all
    plain = _text(copy.deepcopy(res))
    assert plain.split("\n")[0] == "**Transfer plan for GW11–13 (3 gameweeks): 2 transfers for the GW11 deadline, 0 hits.**"
    assert "at most" not in plain and "limit" not in plain                   # no number named: the text it always was
    capped = copy.deepcopy(res)
    capped["max_transfers"] = 2
    capped["later_steps_indicative"] = []
    text = _text(capped)
    lines = text.split("\n")
    assert lines[0] == "**Transfer plan for GW11–13 (3 gameweeks), using at most 2 transfers: 2 transfers for the GW11 deadline, 0 hits.**"
    assert lines[1] == ("Using at most 2 transfers across the whole plan, as you asked: the plan makes 2 (2 for the GW11 deadline, 0 pencilled in "
                        "for later gameweeks).")
    assert ("**Against making no transfer this gameweek only** (the same 15 kept for GW11; later gameweeks still free to transfer, within the "
            "same limit of 2 transfers): ") in text
    three = copy.deepcopy(res)
    three["max_transfers"] = 3
    three["later_steps_indicative"] = three["later_steps_indicative"][:1]
    lines = _text(three).split("\n")
    assert lines[0] == "**Transfer plan for GW11–13 (3 gameweeks), using at most 3 transfers: 2 transfers for the GW11 deadline, 0 hits.**"
    assert lines[1] == ("Using at most 3 transfers across the whole plan, as you asked: the plan makes 3 (2 for the GW11 deadline, 1 pencilled in "
                        "for later gameweeks).")
    one = copy.deepcopy(res)
    one.update(max_transfers=1, horizon=1, effective_horizon=1, later_steps_indicative=[])
    one["this_deadline"]["transfers"] = one["this_deadline"]["transfers"][:1]
    lines = _text(one).split("\n")
    assert lines[0] == "**Transfer plan for GW11 (1 gameweek), using at most 1 transfer: 1 transfer for the GW11 deadline, 0 hits.**"
    assert lines[1] == "Using at most 1 transfer across the whole plan, as you asked: the plan makes 1."
    zero = copy.deepcopy(res)
    zero.update(max_transfers=0, later_steps_indicative=[])
    zero["this_deadline"].update(transfers=[], free_transfers_after=3, bank_after=0.4)
    lines = _text(zero).split("\n")
    assert lines[0] == "**Transfer plan for GW11–13 (3 gameweeks), making no transfers: no transfer for the GW11 deadline.**"
    assert lines[1] == "Making no transfers across the whole plan, as you asked."


def test_x6_the_schema_takes_the_number_and_the_description_says_when_to_pass_it():
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    tool = next(t for t in agent.tools_schema if t["name"] == "propose_transfers")
    assert tool["input_schema"]["properties"]["max_transfers"]["type"] == "integer" and "max_transfers" not in tool["input_schema"]["required"]
    assert "pass it whenever the user names a number of transfers" in tool["description"]
    assert "with two transfers" in tool["description"]
    draft = next(t for t in agent.DRAFT_BASE_TOOLS if t["name"] == "propose_transfers")
    assert "max_transfers" not in draft["input_schema"]["properties"]        # a draft chat's tools are the frozen ones
    import inspect
    assert "max_transfers" in inspect.signature(mt.propose_transfers).parameters
    assert inspect.signature(transfer_mip.build_and_solve).parameters["max_transfers"].default is None
    assert inspect.signature(simulator.decide_gameweek_mip).parameters["max_transfers"].default is None


def test_x7_pencilled_in_free_transfers_follow_fpls_rule_not_the_planners_counter(pool_db):
    import answers
    import squad_state
    assert answers.MAX_FREE_TRANSFERS == squad_state.MAX_FREE_TRANSFERS == 5
    res = _result()
    res.update(max_transfers=2, horizon=6, effective_horizon=6)
    res["this_deadline"].update(free_transfers_before=5, free_transfers_after=3)     # two moves now, three free transfers left
    res["later_steps_indicative"] = [{"horizon_step": k, "gw": 11 + k, "hits": 0, "free_transfers": 0, "transfers": [], "captain": "x"}
                                     for k in range(1, 6)]                              # the planner's counter reads 0 where it limits nothing
    text = _text(res)
    lines = text.split("\n")
    assert "Free transfers: 5 available, 2 used, 3 left. Hits: 0 (0 points). Bank: £0.4m before, £0.1m after." in text
    after = {g: lines[lines.index(f"**GW{g}, pencilled in** (decided again that week, on that week's predictions and prices):") + 2] for g in range(12, 17)}
    assert after[12] == "Free transfers: 4 available, 0 used, 4 left. Hits: 0 (0 points)."
    assert after[13] == after[14] == after[15] == after[16] == "Free transfers: 5 available, 0 used, 5 left. Hits: 0 (0 points)."   # banked up to five
    assert "0 available" not in text
    steps = answers.plan_steps(res)
    assert [(s["ft_before"], s["ft_used"], s["ft_after"]) for s in steps] == [(5, 2, 3), (4, 0, 4), (5, 0, 5), (5, 0, 5), (5, 0, 5), (5, 0, 5)]
    # a pencilled-in gameweek that pays for a move: one free transfer available, two moves, one hit
    paid = _result()
    paid["this_deadline"].update(free_transfers_before=2, free_transfers_after=0)
    paid["later_steps_indicative"][0].update(hits=1, transfers=paid["later_steps_indicative"][0]["transfers"] + paid["later_steps_indicative"][1]["transfers"][1:])
    paid["later_steps_indicative"] = paid["later_steps_indicative"][:1]
    t2 = _text(paid)
    assert "Free transfers: 2 available, 2 used, 0 left. Hits: 0 (0 points). Bank: £0.4m before, £0.1m after." in t2
    assert "Free transfers: 1 available, 1 used, 0 left. Hits: 1 (4 points)." in t2


def test_x7b_a_real_plans_hits_agree_with_the_free_transfers_derived_by_the_rule():
    pool, squad, _pools, _purchase = _setup()
    df = pd.concat([pool.assign(gw=g, cutoff=11) for g in (11, 12, 13)], ignore_index=True)
    prices = dict(zip(pool["element"], pool["value"]))
    for ft0, limit in ((1, None), (2, None), (5, 2), (1, 4)):
        state = SquadState(squad_frame(pool, squad), bank=20, free_transfers=ft0)
        _team, _tr, _step, _eff, plan = decide_gameweek_mip(df, 11, state, pool, prices, [11, 12, 13], horizon=3, cutoff=11,
                                                            return_plan=True, max_transfers=limit)
        ft = ft0
        for st in plan:
            made = int(st["transfers_made"])
            assert int(st["hits"]) == max(0, made - ft), (ft0, limit, st["gw"], made, ft, st["hits"])
            ft = min(5, max(0, ft - made) + 1)


@pytest.mark.parametrize("seed_,T,bank,ft", [(3, 3, 20, 5), (0, 2, 0, 1), (7, 3, 5, 1), (11, 4, 0, 2), (5, 1, 3, 1), (2, 3, 60, 1)])
def test_x8_one_transfer_the_cuts_change_no_optimum(monkeypatch, seed_, T, bank, ft):
    pool = _pool(seed_)
    squad = a_squad(pool)
    rng = __import__("random").Random(seed_)
    pools = {}
    for t in range(T):                                                       # each gameweek its own points, so the timing of the move matters
        p = pool.copy()
        p["e_points"] = [round(max(0.0, v + rng.uniform(-2.5, 2.5)), 2) for v in p["e_points"]]
        pools[11 + t] = p
    purchase = {e: int(pool.loc[pool["element"] == e, "value"].iloc[0]) for e in squad}
    out = pool[~pool["element"].isin(squad)]
    lock = int(out[out["position"] == "MID"].sort_values("value")["element"].iloc[0])
    cases = [{}, {"force_hold": True}, {"banned_elements": [squad[3]]}, {"locked_elements": [lock]}]
    for kw in cases:
        got = {}
        for cuts in (True, False):
            monkeypatch.setattr(transfer_mip, "ONE_TRANSFER_CUTS", cuts)
            status, plan = build_and_solve(pools, current_squad=squad, purchase_prices=purchase, bank=bank, free_transfers=ft,
                                           max_transfers=1, **kw)
            got[cuts] = (status, None if plan is None else plan[0]["objective"], None if plan is None else _made(plan))
        assert got[True][0] == got[False][0], (kw, got)
        if got[True][1] is not None:
            assert got[True][1] == pytest.approx(got[False][1], abs=1e-6), (kw, got)
            assert got[True][2] <= 1 and got[False][2] <= 1
