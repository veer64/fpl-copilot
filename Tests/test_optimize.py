"""
Property-based tests for the FPL squad optimizer (optimize.py).

The core idea: instead of testing a few hand-picked inputs, we assert a
PROPERTY that must hold for *any* input -- "the optimizer always returns a
legal FPL squad" -- and let Hypothesis throw many random player pools at it
trying to break that property.

Run:
    uv run pytest test_optimize.py -v

Notes on scale: each solve rebuilds the MIP from scratch (~0.5-0.8s), so the
example counts here are deliberately modest -- enough to catch structural
constraint bugs (which don't depend on rare values) while staying fast enough
to run in CI. Bumping max_examples to hundreds proves nothing extra and makes
the suite too slow to gate on.
"""

import sys
from pathlib import Path

# add squad/ to the path so we can import optimize
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "squad"))

import random

import pandas as pd
import pulp
import pytest
from hypothesis import given, settings, strategies as st

from optimize import (
    optimize_squad,
    optimize_by_names,
    get_team,
    POSITION_LIMITS,
    BUDGET,
    MAX_PER_CLUB,
    MODES,
)


# ---------------------------------------------------------------------------
# Random pool generator
# ---------------------------------------------------------------------------
def make_random_pool(seed):
    """Build a random-but-realistic player pool.

    Realistic matters: an earlier naive generator (uniform £4-14m prices,
    only 10 clubs) could randomly produce pools where NO legal squad fits
    under budget once max-3-per-club is also enforced -- Hypothesis found
    seed 122 doing exactly that. Real FPL always has plenty of cheap fodder
    spread across 20 clubs, so a legal squad always exists. We mirror that:
    20 teams, and ~70% of players priced as cheap £4.0-6.0m fodder.
    """
    random.seed(seed)

    positions = {"GK": 8, "DEF": 20, "MID": 20, "FWD": 12}
    teams = [f"Team{t}" for t in range(20)]

    rows = []
    element = 1
    for pos, count in positions.items():
        for _ in range(count):
            if random.random() < 0.7:
                price = random.randint(40, 60)     # cheap fodder
            else:
                price = random.randint(60, 140)    # pricier
            rows.append({
                "element": element,
                "name": f"Player{element}",
                "position": pos,
                "team": random.choice(teams),
                "value": price,
                "e_points": round(random.uniform(0, 10), 2),
            })
            element += 1
    return pd.DataFrame(rows).reset_index(drop=True)


# ---------------------------------------------------------------------------
# The property: a solved team obeys every FPL rule
# ---------------------------------------------------------------------------
def assert_legal_squad(df, sol):
    """Raise AssertionError if the solved team breaks any FPL rule."""
    team = get_team(df, sol)

    # 15 players
    assert len(team) == 15, f"squad size {len(team)} != 15"

    # exact position counts in the 15
    pos_counts = team["position"].value_counts().to_dict()
    for pos, n in POSITION_LIMITS.items():
        assert pos_counts.get(pos, 0) == n, f"{pos}: {pos_counts.get(pos, 0)} != {n}"

    # budget
    spent = team["value"].sum()
    assert spent <= BUDGET, f"spent {spent} > {BUDGET}"

    # max 3 per club
    max_club = team["team"].value_counts().max()
    assert max_club <= MAX_PER_CLUB, f"a club has {max_club} > {MAX_PER_CLUB}"

    # exactly 11 starters
    starters = team[team["role"] != "bench"]
    assert len(starters) == 11, f"{len(starters)} starters != 11"

    # exactly 1 captain, and the captain is a starter
    caps = team[team["role"] == "CAPTAIN"]
    assert len(caps) == 1, f"{len(caps)} captains != 1"

    # legal starting formation
    f = starters["position"].value_counts().to_dict()
    assert f.get("GK", 0) == 1, f"GK starting = {f.get('GK', 0)}, must be 1"
    assert 3 <= f.get("DEF", 0) <= 5, f"DEF starting = {f.get('DEF', 0)}, must be 3-5"
    assert 2 <= f.get("MID", 0) <= 5, f"MID starting = {f.get('MID', 0)}, must be 2-5"
    assert 1 <= f.get("FWD", 0) <= 3, f"FWD starting = {f.get('FWD', 0)}, must be 1-3"


# ---------------------------------------------------------------------------
# Property test 1: default mode always yields a legal squad
# ---------------------------------------------------------------------------
@settings(max_examples=30, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_default_mode_always_legal(seed):
    pool = make_random_pool(seed)
    prob, sol = optimize_squad(pool, mode="balanced")
    assert pulp.LpStatus[prob.status] == "Optimal", \
        f"seed {seed}: status {pulp.LpStatus[prob.status]}"
    assert_legal_squad(pool, sol)


# ---------------------------------------------------------------------------
# Property test 2: every named mode stays legal
# ---------------------------------------------------------------------------
@settings(max_examples=10, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_all_modes_legal(seed):
    pool = make_random_pool(seed)
    for mode in MODES:
        prob, sol = optimize_squad(pool, mode=mode)
        assert pulp.LpStatus[prob.status] == "Optimal", \
            f"seed {seed}, mode {mode}: status {pulp.LpStatus[prob.status]}"
        assert_legal_squad(pool, sol)


# ---------------------------------------------------------------------------
# Unit test: locking forces players in, result still legal
# ---------------------------------------------------------------------------
def test_locking_forces_players_in():
    pool = make_random_pool(seed=7)
    # lock the two highest-scoring players (by element)
    top_two = pool.nlargest(2, "e_points")["element"].tolist()

    prob, sol = optimize_squad(pool, mode="balanced", locked_elements=top_two)
    assert pulp.LpStatus[prob.status] == "Optimal"

    team = get_team(pool, sol)
    for elem in top_two:
        assert elem in team["element"].values, f"locked element {elem} not in squad"

    assert_legal_squad(pool, sol)


# ---------------------------------------------------------------------------
# Unit test: banning forces players out, result still legal
# ---------------------------------------------------------------------------
def test_banning_forces_players_out():
    pool = make_random_pool(seed=7)
    # Ban the two highest-scoring players. These are exactly the players the
    # optimizer WANTS most, so if the ban is ignored they will show up.
    top_two = pool.nlargest(2, "e_points")["element"].tolist()

    prob, sol = optimize_squad(pool, mode="balanced", banned_elements=top_two)
    assert pulp.LpStatus[prob.status] == "Optimal"

    team = get_team(pool, sol)
    for elem in top_two:
        assert elem not in team["element"].values, f"banned element {elem} in squad"

    assert_legal_squad(pool, sol)


# ---------------------------------------------------------------------------
# Unit test: banning a player genuinely costs points (the ban actually binds)
# ---------------------------------------------------------------------------
def test_banning_reduces_objective():
    """A legal-squad check alone would pass even if bans silently did nothing.
    This asserts the ban CHANGES the answer: removing the best player from the
    pool must make the optimal squad worse, never better."""
    pool = make_random_pool(seed=7)
    best = pool.nlargest(1, "e_points")["element"].tolist()

    prob_free, _ = optimize_squad(pool, mode="balanced")
    prob_banned, _ = optimize_squad(pool, mode="balanced", banned_elements=best)

    assert pulp.LpStatus[prob_free.status] == "Optimal"
    assert pulp.LpStatus[prob_banned.status] == "Optimal"
    assert pulp.value(prob_banned.objective) < pulp.value(prob_free.objective)


# ---------------------------------------------------------------------------
# Unit test: locking and banning the same player is a caller bug, not a coin flip
# ---------------------------------------------------------------------------
def test_lock_and_ban_clash_raises():
    pool = make_random_pool(seed=7)
    elem = pool.iloc[0]["element"]
    with pytest.raises(ValueError):
        optimize_squad(pool, mode="balanced",
                       locked_elements=[elem], banned_elements=[elem])


# ---------------------------------------------------------------------------
# Unit test: banning an element that isn't in the pool is a no-op, not an error
# ---------------------------------------------------------------------------
def test_banning_missing_element_is_noop():
    """Deliberate asymmetry with locking. A banned player may simply have no
    fixture this gameweek, which already achieves the ban -- erroring would be
    wrong. A missing LOCKED player is still an error (see optimize.py)."""
    pool = make_random_pool(seed=7)
    prob, sol = optimize_squad(pool, mode="balanced", banned_elements=[999_999])
    assert pulp.LpStatus[prob.status] == "Optimal"
    assert_legal_squad(pool, sol)


# ---------------------------------------------------------------------------
# Property test: bans hold across every named mode and any random pool
# ---------------------------------------------------------------------------
@settings(max_examples=10, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_banning_holds_across_modes(seed):
    pool = make_random_pool(seed)
    banned = pool.nlargest(3, "e_points")["element"].tolist()
    for mode in MODES:
        prob, sol = optimize_squad(pool, mode=mode, banned_elements=banned)
        assert pulp.LpStatus[prob.status] == "Optimal", \
            f"seed {seed}, mode {mode}: status {pulp.LpStatus[prob.status]}"
        team = get_team(pool, sol)
        for elem in banned:
            assert elem not in team["element"].values, \
                f"seed {seed}, mode {mode}: banned {elem} in squad"
        assert_legal_squad(pool, sol)


# ---------------------------------------------------------------------------
# Unit test: an impossible pool is reported Infeasible, not a wrong answer
# ---------------------------------------------------------------------------
def test_infeasible_pool_reports_infeasible():
    # every player is maximum price -> no legal squad fits under £100m
    positions = {"GK": 8, "DEF": 20, "MID": 20, "FWD": 12}
    teams = [f"Team{t}" for t in range(20)]
    rows = []
    element = 1
    random.seed(0)
    for pos, count in positions.items():
        for _ in range(count):
            rows.append({
                "element": element, "name": f"Player{element}",
                "position": pos, "team": random.choice(teams),
                "value": 140, "e_points": 5.0,     # everyone £14.0m
            })
            element += 1
    pool = pd.DataFrame(rows).reset_index(drop=True)

    prob, sol = optimize_squad(pool, mode="balanced")
    assert pulp.LpStatus[prob.status] == "Infeasible"


# ---------------------------------------------------------------------------
# Unit test: raw bench_weight overrides the named mode
# ---------------------------------------------------------------------------
def test_bench_weight_overrides_mode():
    from optimize import resolve_bench_weight
    # raw weight wins even when a mode is also given
    assert resolve_bench_weight(mode="best_11", bench_weight=0.42) == 0.42
    # mode is used when no raw weight
    assert resolve_bench_weight(mode="balanced") == MODES["balanced"]
    # unknown mode raises
    with pytest.raises(ValueError):
        resolve_bench_weight(mode="not_a_mode")