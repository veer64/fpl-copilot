"""
Tests for the gameweek scoring function (scoring.py).

Two layers, on purpose:

HAND-BUILT CASES — tiny squads where the right answer is obvious by inspection.
These pin the FPL rules themselves: who replaces whom, when the vice takes the
armband, when a substitution is refused. If a rule is wrong, one of these fails
with a name that says which rule.

PROPERTY TESTS — random squads and random minutes, asserting invariants that must
hold for ANY input: exactly 11 players score, a substitute always played, the
formation stays legal, a hit never increases points. These catch the cases nobody
thought to hand-write.

Run:
    uv run pytest Tests/test_scoring.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "squad"))

import random

import pandas as pd
from hypothesis import given, settings, strategies as st

from scoring import (
    assign_bench_order,
    apply_autosubs,
    resolve_captain,
    score_gameweek,
    MIN_FORMATION,
    HIT_COST,
    XI_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers for building small, readable squads
# ---------------------------------------------------------------------------
def make_squad(spec):
    """Build a squad frame from a compact spec.

    spec: list of (element, position, role, e_points). Bench order is assigned
    automatically, exactly as the simulator would do it.
    """
    df = pd.DataFrame(spec, columns=["element", "position", "role", "e_points"])
    return assign_bench_order(df)


def standard_squad(formation=(1, 4, 4, 2)):
    """A legal 15 in a given XI formation, elements numbered predictably.

    Starters are 1..11, bench is 12..15. Element numbers ascend by position so
    the tests can refer to specific players without a lookup table.
    """
    n_gk, n_def, n_mid, n_fwd = formation
    assert n_gk + n_def + n_mid + n_fwd == XI_SIZE

    spec, elem = [], 1
    # starters
    for pos, n in [("GK", n_gk), ("DEF", n_def), ("MID", n_mid), ("FWD", n_fwd)]:
        for _ in range(n):
            spec.append((elem, pos, "start", 10.0 - elem * 0.1))
            elem += 1
    # bench fills the squad back up to 2/5/5/3
    bench_needed = {"GK": 2 - n_gk, "DEF": 5 - n_def, "MID": 5 - n_mid, "FWD": 3 - n_fwd}
    for pos, n in bench_needed.items():
        for _ in range(n):
            spec.append((elem, pos, "bench", 5.0 - elem * 0.1))
            elem += 1

    df = pd.DataFrame(spec, columns=["element", "position", "role", "e_points"])
    # promote two starters to captain and vice
    df.loc[df["element"] == 7, "role"] = "CAPTAIN"     # a midfielder
    df.loc[df["element"] == 8, "role"] = "VICE"        # another midfielder
    return assign_bench_order(df)


def actuals_from(minutes_map, points_map):
    """Build an actuals frame from two {element: value} dicts."""
    elements = sorted(set(minutes_map) | set(points_map))
    return pd.DataFrame({
        "element": elements,
        "minutes": [minutes_map.get(e, 0) for e in elements],
        "total_points": [points_map.get(e, 0) for e in elements],
    })


def all_played(squad, minutes=90, points=2):
    """Everyone in the squad played and scored the same."""
    elems = list(squad["element"])
    return actuals_from({e: minutes for e in elems}, {e: points for e in elems})


# ===========================================================================
# HAND-BUILT CASES — the FPL rules, pinned one at a time
# ===========================================================================

def test_no_blanks_means_no_subs():
    """Nothing to fix: the final XI is the XI that was picked."""
    squad = standard_squad()
    acts = all_played(squad)
    res = score_gameweek(squad, acts)

    assert res["subs_made"] == []
    assert set(res["final_xi"]) == set(squad[squad["role"] != "bench"]["element"])


def test_blanked_starter_is_replaced():
    """A starter who played 0 minutes comes off for a bench player who played."""
    squad = standard_squad()
    elems = list(squad["element"])
    minutes = {e: 90 for e in elems}
    minutes[5] = 0                              # a defender blanks
    acts = actuals_from(minutes, {e: 2 for e in elems})

    res = score_gameweek(squad, acts)

    assert len(res["subs_made"]) == 1
    out, _ = res["subs_made"][0]
    assert out == 5
    assert 5 not in res["final_xi"]
    assert len(res["final_xi"]) == XI_SIZE


def test_bench_player_who_also_blanked_cannot_come_on():
    """A substitute must have played. If the whole bench blanked, no substitution
    happens and the blanked starter simply STAYS in the XI scoring zero — FPL does
    not remove him, and it does not conjure points from players who did not appear.
    """
    squad = standard_squad()
    elems = list(squad["element"])
    minutes = {e: 90 for e in elems}
    minutes[5] = 0                              # starter blanks
    for e in squad[squad["role"] == "bench"]["element"]:
        minutes[e] = 0                          # so does the entire bench
    acts = actuals_from(minutes, {e: 2 for e in elems})

    res = score_gameweek(squad, acts)

    assert res["subs_made"] == []
    assert 5 in res["final_xi"]                 # still there, scoring nothing
    assert len(res["final_xi"]) == XI_SIZE


def test_only_a_keeper_can_replace_a_keeper():
    """The bench goalkeeper is a like-for-like slot. An outfielder can never
    fill the GK position, and the bench GK never replaces an outfielder."""
    squad = standard_squad()
    elems = list(squad["element"])
    minutes = {e: 90 for e in elems}
    minutes[1] = 0                              # the starting keeper blanks
    acts = actuals_from(minutes, {e: 2 for e in elems})

    res = score_gameweek(squad, acts)

    assert len(res["subs_made"]) == 1
    out, came_on = res["subs_made"][0]
    assert out == 1
    pos_of = dict(zip(squad["element"], squad["position"]))
    assert pos_of[came_on] == "GK"


def test_sub_refused_when_it_would_break_the_formation():
    """Playing 3 at the back: if a defender blanks, no outfielder can come on
    without dropping below the 3-defender minimum — unless he is a defender.
    Here the only bench outfielders are non-defenders, so no sub happens."""
    spec, elem = [], 1
    spec.append((elem, "GK", "start", 5.0)); elem += 1
    for _ in range(3):                                   # exactly 3 defenders
        spec.append((elem, "DEF", "start", 5.0)); elem += 1
    for _ in range(5):
        spec.append((elem, "MID", "start", 5.0)); elem += 1
    for _ in range(2):
        spec.append((elem, "FWD", "start", 5.0)); elem += 1
    # bench: 1 GK, 2 DEF, 0 MID, 1 FWD -> but make the DEFs unavailable below
    spec.append((elem, "GK", "bench", 3.0)); elem += 1
    bench_defs = []
    for _ in range(2):
        spec.append((elem, "DEF", "bench", 3.0)); bench_defs.append(elem); elem += 1
    spec.append((elem, "FWD", "bench", 3.0)); bench_fwd = elem; elem += 1

    df = pd.DataFrame(spec, columns=["element", "position", "role", "e_points"])
    df.loc[df["element"] == 6, "role"] = "CAPTAIN"
    df.loc[df["element"] == 7, "role"] = "VICE"
    squad = assign_bench_order(df)

    elems = list(squad["element"])
    minutes = {e: 90 for e in elems}
    minutes[2] = 0                              # a defender blanks
    for d in bench_defs:
        minutes[d] = 0                          # both bench defenders also blanked
    acts = actuals_from(minutes, {e: 2 for e in elems})

    res = score_gameweek(squad, acts)

    # The bench forward played, but bringing him on would leave only 2 defenders.
    assert res["subs_made"] == []
    assert bench_fwd not in res["final_xi"]


def test_captain_doubles():
    squad = standard_squad()
    elems = list(squad["element"])
    points = {e: 2 for e in elems}
    points[7] = 12                              # the captain hauls
    acts = actuals_from({e: 90 for e in elems}, points)

    res = score_gameweek(squad, acts)

    assert res["doubled"] == 7
    assert res["doubled_role"] == "captain"
    assert res["captain_bonus"] == 12


def test_vice_takes_over_when_captain_blanks():
    squad = standard_squad()
    elems = list(squad["element"])
    minutes = {e: 90 for e in elems}
    minutes[7] = 0                              # captain does not play
    points = {e: 2 for e in elems}
    points[7] = 0
    points[8] = 9                               # vice hauls instead
    acts = actuals_from(minutes, points)

    res = score_gameweek(squad, acts)

    assert res["doubled"] == 8
    assert res["doubled_role"] == "vice"
    assert res["captain_bonus"] == 9


def test_nobody_doubles_when_captain_and_vice_both_blank():
    squad = standard_squad()
    elems = list(squad["element"])
    minutes = {e: 90 for e in elems}
    minutes[7] = 0
    minutes[8] = 0
    acts = actuals_from(minutes, {e: 2 for e in elems})

    res = score_gameweek(squad, acts)

    assert res["doubled"] is None
    assert res["doubled_role"] == "none"
    assert res["captain_bonus"] == 0


def test_hit_is_deducted():
    """Three transfers with one free = two hits = 8 points."""
    squad = standard_squad()
    acts = all_played(squad)

    free = score_gameweek(squad, acts, transfers_made=1, free_transfers=1)
    hit = score_gameweek(squad, acts, transfers_made=3, free_transfers=1)

    assert free["hit"] == 0
    assert hit["hit"] == 2 * HIT_COST
    assert hit["points"] == hit["raw_points"] - 2 * HIT_COST
    assert free["raw_points"] == hit["raw_points"]      # only the hit differs


def test_unused_free_transfers_are_not_refunded():
    """Making fewer transfers than you have free is not worth points."""
    squad = standard_squad()
    acts = all_played(squad)
    res = score_gameweek(squad, acts, transfers_made=0, free_transfers=5)
    assert res["hit"] == 0
    assert res["points"] == res["raw_points"]


def test_bench_points_are_not_scored():
    """Bench points are reported as a diagnostic, never added to the total."""
    squad = standard_squad()
    elems = list(squad["element"])
    points = {e: 0 for e in elems}
    for e in squad[squad["role"] == "bench"]["element"]:
        points[e] = 15                          # a huge bench haul
    acts = actuals_from({e: 90 for e in elems}, points)

    res = score_gameweek(squad, acts)

    assert res["bench_points"] == 60
    assert res["raw_points"] == 0               # none of it counted


def test_missing_player_counts_as_zero_minutes():
    """A player absent from actuals has no fixture (blank gameweek). He is
    treated as having played 0, not silently skipped — so an autosub fires."""
    squad = standard_squad()
    elems = [e for e in squad["element"] if e != 5]   # element 5 has no row at all
    acts = actuals_from({e: 90 for e in elems}, {e: 2 for e in elems})

    res = score_gameweek(squad, acts)

    assert len(res["subs_made"]) == 1
    out, _ = res["subs_made"][0]
    assert out == 5
    assert 5 not in res["final_xi"]


# ===========================================================================
# PROPERTY TESTS — invariants that must hold for any input
# ===========================================================================

def random_scenario(seed):
    """A standard squad plus random minutes and points."""
    random.seed(seed)
    formations = [(1, 3, 5, 2), (1, 4, 4, 2), (1, 5, 3, 2), (1, 3, 4, 3), (1, 4, 5, 1)]
    squad = standard_squad(random.choice(formations))

    elems = list(squad["element"])
    minutes, points = {}, {}
    for e in elems:
        # ~25% of players blank, which is roughly realistic and makes autosubs fire
        minutes[e] = 0 if random.random() < 0.25 else random.randint(1, 90)
        points[e] = 0 if minutes[e] == 0 else random.randint(0, 15)
    return squad, actuals_from(minutes, points), minutes


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_final_xi_never_exceeds_eleven(seed):
    squad, acts, _ = random_scenario(seed)
    res = score_gameweek(squad, acts)
    assert len(res["final_xi"]) <= XI_SIZE


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_final_xi_has_no_duplicates(seed):
    squad, acts, _ = random_scenario(seed)
    res = score_gameweek(squad, acts)
    assert len(set(res["final_xi"])) == len(res["final_xi"])


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_every_substitute_actually_played(seed):
    """The core autosub rule. A player who did not appear can never be subbed on."""
    squad, acts, minutes = random_scenario(seed)
    res = score_gameweek(squad, acts)
    for _, came_on in res["subs_made"]:
        assert minutes.get(came_on, 0) > 0, f"sub {came_on} played 0 minutes"


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_every_subbed_out_player_blanked(seed):
    """The mirror rule: nobody who played is ever removed."""
    squad, acts, minutes = random_scenario(seed)
    res = score_gameweek(squad, acts)
    for out, _ in res["subs_made"]:
        assert minutes.get(out, 0) == 0, f"player {out} was subbed out but played"


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_formation_stays_legal(seed):
    """Autosubs must never produce an illegal shape. Note the XI is ALWAYS 11:
    a blanked starter with no available replacement stays in the side scoring
    zero, exactly as FPL does it."""
    squad, acts, _ = random_scenario(seed)
    res = score_gameweek(squad, acts)

    pos_of = dict(zip(squad["element"], squad["position"]))
    counts = {}
    for e in res["final_xi"]:
        p = pos_of[e]
        counts[p] = counts.get(p, 0) + 1

    assert len(res["final_xi"]) == XI_SIZE
    assert counts.get("GK", 0) == 1, "the XI must contain exactly one goalkeeper"
    for pos, floor in MIN_FORMATION.items():
        assert counts.get(pos, 0) >= floor, \
            f"{pos}={counts.get(pos, 0)} below floor {floor}"


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_substitutes_come_from_the_bench(seed):
    """A substitute must have been on the bench. Nobody appears from nowhere."""
    squad, acts, _ = random_scenario(seed)
    res = score_gameweek(squad, acts)
    bench = set(squad[squad["role"] == "bench"]["element"])
    for _, came_on in res["subs_made"]:
        assert came_on in bench


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000),
       transfers=st.integers(min_value=0, max_value=6))
def test_hits_never_increase_points(seed, transfers):
    """More transfers can only ever cost points, never add them."""
    squad, acts, _ = random_scenario(seed)
    none = score_gameweek(squad, acts, transfers_made=0, free_transfers=1)
    many = score_gameweek(squad, acts, transfers_made=transfers, free_transfers=1)
    assert many["points"] <= none["points"]
    assert many["hit"] >= 0


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_doubled_player_is_in_the_final_xi(seed):
    """You cannot double someone who is not playing."""
    squad, acts, _ = random_scenario(seed)
    res = score_gameweek(squad, acts)
    if res["doubled"] is not None:
        assert res["doubled"] in res["final_xi"]


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=100_000))
def test_points_equal_xi_plus_bonus_minus_hit(seed):
    """The arithmetic itself: the returned total must reconcile exactly with the
    parts it reports. This is what catches a silent double-count."""
    squad, acts, _ = random_scenario(seed)
    res = score_gameweek(squad, acts, transfers_made=2, free_transfers=1)

    pts = dict(zip(acts["element"], acts["total_points"]))
    xi_total = sum(pts.get(e, 0) for e in res["final_xi"])

    assert res["raw_points"] == xi_total + res["captain_bonus"]
    assert res["points"] == res["raw_points"] - res["hit"]