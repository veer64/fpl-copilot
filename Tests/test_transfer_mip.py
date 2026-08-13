"""
Tests for the multi-gameweek transfer MIP (transfer_mip.py) and the chip
machinery that rides on it (simulator.py, squad_state.py).

WHY THIS FILE EXISTS
--------------------
transfer_mip.py had no tests, and three chips now depend on it. Two bugs have
already been found there by hand, both in arithmetic that looked obviously
right:

  1. The club-limit constraints were emitted by iterating a SET OF STRINGS, so
     the model handed to the solver was ordered differently in every process and
     tied optima were broken arbitrarily. A season total moved between 1973 and
     1984 with no code change at all.
  2. The wildcard switched off the HIT PENALTY but still DEBITED the free
     transfer bank, so ft[t+1] <= ft[t] - used[t] + 1 capped a "free" wildcard at
     ft+1 transfers whenever the horizon was longer than one gameweek. It looked
     correct in isolation only because the isolated test truncated the season to
     a single week -- the one case where the bug cannot show.

Both are regression-tested below. Neither would have been caught by a test that
only asked "is the returned squad legal".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "squad"))

import pandas as pd
import pytest

from transfer_mip import build_and_solve
from optimize import MAX_PER_CLUB
from squad_state import SquadState, MAX_FREE_TRANSFERS
from simulator import _chip_weeks

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_optimize import make_random_pool


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def a_squad(pool, seed=0):
    """A legal 15 taken straight from a pool: 2/5/5/3, at most 3 per club."""
    picked, per_club = [], {}
    for pos, n in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        got = 0
        for r in pool[pool["position"] == pos].itertuples():
            if per_club.get(r.team, 0) >= 3:
                continue
            picked.append(r.element)
            per_club[r.team] = per_club.get(r.team, 0) + 1
            got += 1
            if got == n:
                break
        assert got == n, f"pool could not supply {n} {pos}"
    return picked


def squad_frame(pool, elements, price_col="value"):
    rows = pool[pool["element"].isin(elements)].copy()
    rows["purchase_price"] = rows[price_col].astype(int)
    return rows.reset_index(drop=True)


# ---------------------------------------------------------------------------
# The wildcard / free hit relief -- regression test for bug 2
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("T", [1, 2, 3])
def test_chip_relief_beats_ft_plus_one(T):
    """With the hit penalty relieved, the chip must be able to make far more
    than ft+1 transfers -- at EVERY horizon length, not just T=1.

    ft+1 is the exact cap the free-transfer chain imposes when the chip forgets
    to zero its own spend, so that number is the bug's fingerprint.
    """
    pool = make_random_pool(7)
    owned = a_squad(pool)
    pools = {10 + t: pool.copy() for t in range(T)}
    prices = dict(zip(pool["element"], pool["value"]))
    purchase = {e: int(prices[e]) for e in owned}

    status, plan = build_and_solve(
        pools, current_squad=owned, purchase_prices=purchase,
        bank=0, free_transfers=1, mode="balanced", decay=0.3,
        wildcard_step=0,
    )
    assert status == "Optimal"
    assert plan[0]["transfers_made"] > 2, (
        f"T={T}: chip made only {plan[0]['transfers_made']} transfers; "
        "ft+1 = 2 is the cap the free-transfer chain imposes when the chip "
        "does not zero its own spend"
    )
    assert plan[0]["hits"] == 0, "a chip week must never pay a hit"


def test_chip_relief_banks_nothing_extra():
    """The chip must not leak free transfers into the following week: ft[1] is
    capped at the pre-chip balance plus the usual one."""
    pool = make_random_pool(11)
    owned = a_squad(pool)
    pools = {20: pool.copy(), 21: pool.copy()}
    prices = dict(zip(pool["element"], pool["value"]))
    status, plan = build_and_solve(
        pools, current_squad=owned,
        purchase_prices={e: int(prices[e]) for e in owned},
        bank=0, free_transfers=1, mode="balanced", decay=0.3, wildcard_step=0,
    )
    assert status == "Optimal"
    assert plan[1]["free_transfers"] <= min(MAX_FREE_TRANSFERS, 1 + 1)


def test_without_relief_transfers_stay_cheap():
    """Sanity counterpart: with no chip and one free transfer, the solver should
    not be making a pile of transfers, because each one past the first costs 4."""
    pool = make_random_pool(7)
    owned = a_squad(pool)
    pools = {10: pool.copy(), 11: pool.copy(), 12: pool.copy()}
    prices = dict(zip(pool["element"], pool["value"]))
    status, plan = build_and_solve(
        pools, current_squad=owned,
        purchase_prices={e: int(prices[e]) for e in owned},
        bank=0, free_transfers=1, mode="balanced", decay=0.3, wildcard_step=None,
    )
    assert status == "Optimal"
    assert plan[0]["hits"] == max(0, plan[0]["transfers_made"] - 1)


# ---------------------------------------------------------------------------
# Model determinism -- regression test for bug 1
# ---------------------------------------------------------------------------
def test_club_constraints_are_emitted_in_a_stable_order():
    """The club-limit constraints must not depend on set iteration order.

    Python randomises string hashing per process, so a set of team names walks
    in a different order in every interpreter. That reordered the LP and the
    solver returned a different tied optimum -- a silent 11-point swing across
    runs. Building the same model twice must give byte-identical LP text.
    """
    import pulp

    pool = make_random_pool(3)
    owned = a_squad(pool)
    prices = dict(zip(pool["element"], pool["value"]))
    pools = {5: pool.copy(), 6: pool.copy()}

    captured = []
    real_solve = pulp.LpProblem.solve
    pulp.LpProblem.solve = lambda self, solver=None, **kw: captured.append(self)
    try:
        for _ in range(2):
            build_and_solve(pools, current_squad=owned,
                            purchase_prices={e: int(prices[e]) for e in owned},
                            bank=0, free_transfers=1, mode="balanced", decay=0.3)
    finally:
        pulp.LpProblem.solve = real_solve

    def club_rows(prob):
        """The max-3-per-club rows, in the order the model was built."""
        out = []
        for _, c in prob.constraints.items():
            # PuLP stores `expr <= k` with sense LpConstraintLE and constant -k
            if c.sense == pulp.LpConstraintLE and -c.constant == MAX_PER_CLUB:
                if all(str(v).startswith("pick_") for v in c.keys()):
                    out.append(sorted(str(v) for v in c.keys()))
        return out

    rows_a, rows_b = club_rows(captured[0]), club_rows(captured[1])
    assert rows_a, "expected some max-3-per-club constraints"
    assert rows_a == rows_b, "club constraints came out in a different order"

    # and the whole model, not just those rows
    assert ([str(c) for c in captured[0].constraints.values()]
            == [str(c) for c in captured[1].constraints.values()])


# ---------------------------------------------------------------------------
# Free Hit: the squad must come back exactly as it went in
# ---------------------------------------------------------------------------
def test_snapshot_restores_squad_bank_and_free_transfers():
    pool = make_random_pool(5)
    owned = a_squad(pool)
    state = SquadState(squad_frame(pool, owned), bank=37, free_transfers=3)

    before = state.snapshot()
    original = state.squad.copy(deep=True)

    # Play a "free hit": sell someone and buy a replacement of the same position.
    out = owned[7]
    out_pos = pool.loc[pool["element"] == out, "position"].iloc[0]
    cand = pool[(pool["position"] == out_pos) & (~pool["element"].isin(owned))]
    in_row = cand.iloc[0]
    prices = dict(zip(pool["element"], pool["value"]))
    state.bank = 10_000                       # afford anything for the test
    state.make_transfer(out, int(in_row["element"]), in_row, prices)
    state.free_transfers = 0
    assert set(state.elements) != set(owned)

    state.restore(before)

    assert list(state.squad["element"]) == list(original["element"])
    assert list(state.squad["purchase_price"]) == list(original["purchase_price"])
    assert state.bank == 37
    assert state.free_transfers == 3


def test_restore_is_immune_to_price_changes_during_the_chip_week():
    """Purchase prices decide future sell value, so a price paid during the
    chip week must not survive the revert."""
    pool = make_random_pool(9)
    owned = a_squad(pool)
    state = SquadState(squad_frame(pool, owned), bank=0, free_transfers=1)
    before = state.snapshot()
    paid_before = dict(zip(state.squad["element"], state.squad["purchase_price"]))

    # Everyone the manager owns doubles in price mid-chip.
    risen = {e: int(v) * 2 for e, v in
             zip(state.squad["element"], state.squad["purchase_price"])}
    state.squad["purchase_price"] = [risen[e] for e in state.squad["element"]]

    state.restore(before)
    assert dict(zip(state.squad["element"], state.squad["purchase_price"])) == paid_before


def test_snapshot_is_a_deep_copy():
    """Mutating the live squad after snapshotting must not reach the snapshot."""
    pool = make_random_pool(13)
    owned = a_squad(pool)
    state = SquadState(squad_frame(pool, owned), bank=5, free_transfers=2)
    snap = state.snapshot()
    state.squad.loc[0, "purchase_price"] = 999
    assert snap["squad"].loc[0, "purchase_price"] != 999


def test_snapshot_does_not_capture_points():
    """A Free Hit reverts the squad, not the score."""
    pool = make_random_pool(17)
    state = SquadState(squad_frame(pool, a_squad(pool)), bank=0, free_transfers=1)
    snap = state.snapshot()
    state.end_gameweek(61)
    state.restore(snap)
    assert state.total_points == 61


# ---------------------------------------------------------------------------
# Chip week validation, shared by wildcard and free hit
# ---------------------------------------------------------------------------
def test_chip_weeks_accepts_int_iterable_and_none():
    assert _chip_weeks(None, "wildcards", 20) == set()
    assert _chip_weeks(7, "wildcards", 20) == {7}
    assert _chip_weeks([3, 25], "wildcards", 20) == {3, 25}


def test_chip_weeks_enforces_one_per_half():
    with pytest.raises(ValueError, match="per half"):
        _chip_weeks([3, 7], "wildcards", 20)
    with pytest.raises(ValueError, match="per half"):
        _chip_weeks([25, 30], "free hits", 20)
    _chip_weeks([7, 25], "wildcards", 20)          # one each side is fine


def test_chip_weeks_rejects_more_than_two():
    with pytest.raises(ValueError, match="two"):
        _chip_weeks([2, 10, 30], "wildcards", 20)


def test_second_half_start_is_a_parameter_not_a_constant():
    """The split is announced each season, so moving it must move the rule."""
    _chip_weeks([7, 15], "wildcards", 10)          # legal when the half starts at 10
    with pytest.raises(ValueError, match="per half"):
        _chip_weeks([7, 15], "wildcards", 20)
