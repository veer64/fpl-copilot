"""
Bench-aware Bench Boost (transfer_mip.BENCH_BOOST_AWARE, P4 follow-up).

P4 measured the bench-UNaware Bench Boost at +2.3 points against the plan's
+22 estimate: the MIP optimises the XI and benches cheap fodder, so doubling
the bench doubles almost nothing. Under the gate, a scheduled Bench Boost
step's bench weight becomes 1.0 -- all fifteen score that week.

The gate was ADOPTED True on 2026-08-20 (P4 log sections 12-13). It is inert
unless a Bench Boost is actually scheduled inside the horizon, and the
gate-off behaviour is still tested so older runs stay reproducible.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "squad"))

import pytest

import transfer_mip
from transfer_mip import build_and_solve

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_optimize import make_random_pool
from test_transfer_mip import a_squad


@pytest.fixture
def gate():
    """Ensure the gate is on for a test, always restore the resting state.
    (The gate has been ADOPTED True since 2026-08-20; the fixture keeps the
    tests valid under either resting state.)"""
    old = transfer_mip.BENCH_BOOST_AWARE
    transfer_mip.BENCH_BOOST_AWARE = True
    yield
    transfer_mip.BENCH_BOOST_AWARE = old


def _solve(pool, owned, bench_boost_step, wildcard_step=None, T=1):
    pools = {10 + t: pool.copy() for t in range(T)}
    prices = dict(zip(pool["element"], pool["value"]))
    purchase = {e: int(prices[e]) for e in owned}
    status, plan = build_and_solve(
        pools, current_squad=owned, purchase_prices=purchase,
        bank=100, free_transfers=1, mode="balanced", decay=0.85,
        wildcard_step=wildcard_step, bench_boost_step=bench_boost_step)
    assert status == "Optimal"
    return plan


def _bench_pts(plan_step, pool):
    pts = dict(zip(pool["element"], pool["e_points"]))
    bench = set(plan_step["squad"]) - set(plan_step["starters"])
    return sum(pts[e] for e in bench)


def test_gate_off_step_is_ignored():
    """With the gate OFF, passing bench_boost_step must change nothing: same
    squad, same starters. (Resting state is True since the 2026-08-20
    adoption; the off behaviour must still hold to reproduce older runs.)"""
    old = transfer_mip.BENCH_BOOST_AWARE
    transfer_mip.BENCH_BOOST_AWARE = False
    try:
        pool = make_random_pool(11)
        owned = a_squad(pool)
        p_off = _solve(pool, owned, bench_boost_step=None, wildcard_step=0)
        p_bb = _solve(pool, owned, bench_boost_step=0, wildcard_step=0)
    finally:
        transfer_mip.BENCH_BOOST_AWARE = old
    assert sorted(p_off[0]["squad"]) == sorted(p_bb[0]["squad"])
    assert sorted(p_off[0]["starters"]) == sorted(p_bb[0]["starters"])


def test_gate_on_none_step_matches_gate_off(gate):
    """Gate on but no Bench Boost scheduled: behaviour is untouched."""
    pool = make_random_pool(13)
    owned = a_squad(pool)
    with_gate = _solve(pool, owned, bench_boost_step=None, wildcard_step=0)
    transfer_mip.BENCH_BOOST_AWARE = False
    without = _solve(pool, owned, bench_boost_step=None, wildcard_step=0)
    transfer_mip.BENCH_BOOST_AWARE = True
    assert sorted(with_gate[0]["squad"]) == sorted(without[0]["squad"])


@pytest.mark.parametrize("seed", [3, 17, 29])
def test_boost_week_bench_never_worse(gate, seed):
    """The defining property: on the boost step, with a wildcard providing
    transfer freedom, the aware solve's bench predicted points must be >= the
    unaware solve's. (Equality is legal -- some pools leave no bench upgrade
    worth its price -- but a DECREASE would mean the weight went the wrong
    way.)"""
    pool = make_random_pool(seed)
    owned = a_squad(pool)
    aware = _solve(pool, owned, bench_boost_step=0, wildcard_step=0)
    transfer_mip.BENCH_BOOST_AWARE = False
    unaware = _solve(pool, owned, bench_boost_step=None, wildcard_step=0)
    transfer_mip.BENCH_BOOST_AWARE = True
    assert _bench_pts(aware[0], pool) >= _bench_pts(unaware[0], pool) - 1e-9


def test_boost_weight_is_local_to_its_step(gate):
    """Two-step horizon, boost at step 1: step 0's bench must not be inflated
    -- its weight is still the tuned 0.2. Verified by comparing step-0 bench
    value against a no-boost solve of the same problem: any difference must
    come from planning TOWARD step 1, so step 0's bench may only change if
    step 1's bench improved."""
    pool = make_random_pool(23)
    owned = a_squad(pool)
    boosted = _solve(pool, owned, bench_boost_step=1, wildcard_step=0, T=2)
    transfer_mip.BENCH_BOOST_AWARE = False
    plain = _solve(pool, owned, bench_boost_step=None, wildcard_step=0, T=2)
    transfer_mip.BENCH_BOOST_AWARE = True
    s0_moved = _bench_pts(boosted[0], pool) != _bench_pts(plain[0], pool)
    s1_gain = _bench_pts(boosted[1], pool) - _bench_pts(plain[1], pool)
    assert (not s0_moved) or s1_gain > 0, (
        "step-0 bench changed without any step-1 bench improvement -- the "
        "boost weight leaked out of its step")
