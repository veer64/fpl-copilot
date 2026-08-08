"""
Tests for squad state and sell-price accounting (squad_state.py).

Why this file is worth its length: the sell-price rule is the one piece of
accounting that compounds. A scoring bug costs you points in one gameweek; a
sell-price bug quietly inflates your budget EVERY week, and by GW38 the simulator
is fielding a squad you could never have afforded. That invalidates the headline
number, not a detail of it.

So the rule gets pinned three ways: worked examples from the FPL rules, property
tests over every price pair in a realistic range, and end-to-end checks that money
is conserved across transfers.

Run:
    uv run pytest Tests/test_squad_state.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "squad"))

import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from squad_state import (
    sell_price,
    SquadState,
    initial_squad_from_team,
    MAX_FREE_TRANSFERS,
    SQUAD_SIZE,
    STARTING_BUDGET,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_squad_frame(purchase=50):
    """A legal 15 (2 GK, 5 DEF, 5 MID, 3 FWD), elements 1..15, all bought at the
    same price so the arithmetic in tests stays easy to follow."""
    spec, elem = [], 1
    for pos, n in [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]:
        for _ in range(n):
            spec.append({"element": elem, "name": f"P{elem}", "position": pos,
                         "team": f"T{elem % 5}", "purchase_price": purchase})
            elem += 1
    return pd.DataFrame(spec)


def flat_prices(elements, price):
    return {e: price for e in elements}


# ===========================================================================
# THE SELL-PRICE RULE
# ===========================================================================

def test_sell_price_worked_examples():
    """The exact examples from the FPL rules, bought at £12.0m."""
    assert sell_price(120, 124) == 122      # rise 4 -> keep half
    assert sell_price(120, 123) == 121      # rise 3 -> floor(1.5) = 1
    assert sell_price(120, 122) == 121      # rise 2 -> keep 1
    assert sell_price(120, 121) == 120      # rise 1 -> floor(0.5) = 0, keep nothing
    assert sell_price(120, 120) == 120      # no change
    assert sell_price(120, 117) == 117      # fall -> full loss


def test_odd_rises_round_down_not_up():
    """The rounding direction matters: rounding UP would hand the manager free
    money on every odd-numbered rise, which across a season is real."""
    for bought in [40, 55, 78, 101, 145]:
        for rise in [1, 3, 5, 7, 9]:
            got = sell_price(bought, bought + rise)
            assert got == bought + rise // 2
            assert got < bought + rise / 2 + 1


@settings(max_examples=500, deadline=None)
@given(bought=st.integers(min_value=38, max_value=150),
       now=st.integers(min_value=38, max_value=150))
def test_sell_price_never_exceeds_current_price(bought, now):
    """You can never receive more than the player is currently worth."""
    assert sell_price(bought, now) <= now


@settings(max_examples=500, deadline=None)
@given(bought=st.integers(min_value=38, max_value=150),
       now=st.integers(min_value=38, max_value=150))
def test_sell_price_is_between_purchase_and_current(bought, now):
    """On a rise you get somewhere between what you paid and what he is worth.
    On a fall you get exactly the current price."""
    got = sell_price(bought, now)
    if now > bought:
        assert bought <= got <= now
    else:
        assert got == now


@settings(max_examples=500, deadline=None)
@given(bought=st.integers(min_value=38, max_value=150),
       now=st.integers(min_value=38, max_value=150))
def test_selling_immediately_is_break_even(bought, now):
    """Buying and selling at the same price must return exactly what you paid —
    no accidental profit, no accidental leak."""
    assert sell_price(bought, bought) == bought


@settings(max_examples=500, deadline=None)
@given(bought=st.integers(min_value=38, max_value=150),
       rise=st.integers(min_value=0, max_value=60))
def test_sell_price_is_monotonic_in_price(bought, rise):
    """A higher current price can never be worth less to you."""
    a = sell_price(bought, bought + rise)
    b = sell_price(bought, bought + rise + 1)
    assert b >= a


# ===========================================================================
# CONSTRUCTION AND GUARDS
# ===========================================================================

def test_squad_must_have_fifteen_players():
    frame = make_squad_frame().iloc[:14]
    with pytest.raises(ValueError):
        SquadState(frame)


def test_squad_must_carry_purchase_price():
    """Without purchase_price the sell-price rule cannot be applied at all, so
    this is refused at construction rather than discovered mid-season."""
    frame = make_squad_frame().drop(columns=["purchase_price"])
    with pytest.raises(ValueError):
        SquadState(frame)


def test_initial_squad_computes_bank_from_spend():
    team = make_squad_frame().rename(columns={"purchase_price": "value"})
    state = initial_squad_from_team(team)
    assert state.bank == STARTING_BUDGET - 15 * 50
    assert state.free_transfers == 1
    assert state.total_points == 0
    assert len(state.squad) == SQUAD_SIZE


# ===========================================================================
# VALUATION
# ===========================================================================

def test_sell_value_uses_the_rule_not_the_market_price():
    """The whole point: a squad that has risen is NOT worth its market value."""
    state = SquadState(make_squad_frame(purchase=50))
    prices = flat_prices(state.elements, 54)        # everyone rose 4

    assert state.sell_value(prices) == 15 * 52      # 50 + 4//2 = 52 each
    assert state.sell_value(prices) < 15 * 54       # strictly less than market


def test_sell_value_takes_full_loss_on_falls():
    state = SquadState(make_squad_frame(purchase=50))
    prices = flat_prices(state.elements, 46)
    assert state.sell_value(prices) == 15 * 46


def test_missing_price_falls_back_to_purchase_price():
    """A player with no row this gameweek must not be assumed to have risen —
    that would invent money out of missing data."""
    state = SquadState(make_squad_frame(purchase=50))
    prices = flat_prices(state.elements, 60)
    del prices[3]                                   # element 3 has no price row

    expected = 14 * 55 + 50                         # 14 risen, one at cost
    assert state.sell_value(prices) == expected


def test_budget_includes_the_bank():
    state = SquadState(make_squad_frame(purchase=50), bank=125)
    prices = flat_prices(state.elements, 50)
    assert state.budget(prices) == 15 * 50 + 125


def test_element_sell_price_rejects_a_player_you_do_not_own():
    state = SquadState(make_squad_frame())
    with pytest.raises(ValueError):
        state.element_sell_price(999, {})


# ===========================================================================
# TRANSFERS
# ===========================================================================

def incoming(element, position, value):
    return pd.Series({"element": element, "name": f"P{element}",
                      "position": position, "team": "TX", "value": value})


def test_transfer_updates_bank_by_the_difference():
    state = SquadState(make_squad_frame(purchase=50), bank=100)
    prices = flat_prices(state.elements, 50)

    state.make_transfer(3, 99, incoming(99, "DEF", 55), prices)

    assert state.bank == 100 + 50 - 55              # sold at 50, bought at 55
    assert 3 not in state.elements
    assert 99 in state.elements
    assert len(state.squad) == SQUAD_SIZE


def test_incoming_player_purchase_price_is_what_you_paid():
    """This is what makes NEXT season-week's sell price correct. If the incoming
    player inherited the outgoing player's purchase price, every subsequent sale
    would be wrong."""
    state = SquadState(make_squad_frame(purchase=50), bank=100)
    prices = flat_prices(state.elements, 50)

    state.make_transfer(3, 99, incoming(99, "DEF", 62), prices)

    row = state.squad[state.squad["element"] == 99].iloc[0]
    assert row["purchase_price"] == 62


def test_transfer_uses_sell_price_not_market_price():
    """Selling a risen player gives you the SELL price. Using market price here
    is the exact bug this module exists to prevent."""
    state = SquadState(make_squad_frame(purchase=50), bank=0)
    prices = flat_prices(state.elements, 58)        # everyone rose 8 -> sell at 54

    state.make_transfer(3, 99, incoming(99, "DEF", 54), prices)

    assert state.bank == 0 + 54 - 54                # exactly break even
    assert state.bank == 0


def test_unaffordable_transfer_raises():
    """A negative bank would silently corrupt every later gameweek, so it is
    refused at the point of the mistake."""
    state = SquadState(make_squad_frame(purchase=50), bank=0)
    prices = flat_prices(state.elements, 50)
    with pytest.raises(ValueError):
        state.make_transfer(3, 99, incoming(99, "DEF", 120), prices)


def test_position_mismatch_raises():
    """The 15 is fixed at 2/5/5/3 by FPL rule, so a DEF must replace a DEF."""
    state = SquadState(make_squad_frame(purchase=50), bank=500)
    prices = flat_prices(state.elements, 50)
    with pytest.raises(ValueError):
        state.make_transfer(3, 99, incoming(99, "FWD", 50), prices)


def test_cannot_buy_a_player_you_already_own():
    state = SquadState(make_squad_frame(purchase=50), bank=500)
    prices = flat_prices(state.elements, 50)
    with pytest.raises(ValueError):
        state.make_transfer(3, 4, incoming(4, "DEF", 50), prices)


def test_cannot_sell_a_player_you_do_not_own():
    state = SquadState(make_squad_frame(purchase=50), bank=500)
    prices = flat_prices(state.elements, 50)
    with pytest.raises(ValueError):
        state.make_transfer(999, 99, incoming(99, "DEF", 50), prices)


def test_failed_transfer_leaves_state_untouched():
    """A rejected transfer must not half-apply. If the squad changed but the bank
    did not, the season silently diverges from any legal FPL position."""
    state = SquadState(make_squad_frame(purchase=50), bank=0)
    prices = flat_prices(state.elements, 50)

    before_elements = list(state.elements)
    before_bank = state.bank

    with pytest.raises(ValueError):
        state.make_transfer(3, 99, incoming(99, "DEF", 999), prices)

    assert state.elements == before_elements
    assert state.bank == before_bank


# ===========================================================================
# FREE TRANSFERS AND ROLLING FORWARD
# ===========================================================================

def test_one_free_transfer_costs_nothing():
    state = SquadState(make_squad_frame(), free_transfers=1)
    assert state.spend_transfers(1) == 0
    assert state.free_transfers == 0


def test_extra_transfers_are_paid():
    state = SquadState(make_squad_frame(), free_transfers=1)
    assert state.spend_transfers(3) == 2            # 1 free, 2 paid
    assert state.free_transfers == 0


def test_free_transfers_accumulate_but_cap_at_five():
    state = SquadState(make_squad_frame(), free_transfers=1)
    for _ in range(10):
        state.end_gameweek(0)
    assert state.free_transfers == MAX_FREE_TRANSFERS


def test_end_gameweek_banks_points_and_earns_a_transfer():
    state = SquadState(make_squad_frame(), free_transfers=0, total_points=40)
    state.end_gameweek(57)
    assert state.total_points == 97
    assert state.free_transfers == 1


def test_free_transfers_never_go_negative():
    state = SquadState(make_squad_frame(), free_transfers=1)
    state.spend_transfers(4)
    assert state.free_transfers == 0


# ===========================================================================
# MONEY CONSERVATION — the property that matters most
# ===========================================================================

@settings(max_examples=200, deadline=None)
@given(purchase=st.integers(min_value=40, max_value=140),
       drift=st.integers(min_value=-15, max_value=15),
       buy_price=st.integers(min_value=40, max_value=90),
       start_bank=st.integers(min_value=0, max_value=200))
def test_transfer_conserves_money_exactly(purchase, drift, buy_price, start_bank):
    """Total wealth (squad sell value + bank) is UNCHANGED by a transfer.

    The four movements cancel exactly: the outgoing player's sell value leaves
    the squad and enters the bank; the incoming player's price leaves the bank
    and re-enters as squad value (he is worth what you just paid, since a player
    bought at the current price has no rise to share yet).

    A failure here means money is being created or destroyed — the single worst
    failure mode for a season simulation, because it compounds silently.
    """
    state = SquadState(make_squad_frame(purchase=purchase), bank=start_bank)
    current = max(38, purchase + drift)
    prices = flat_prices(state.elements, current)

    received = state.element_sell_price(3, prices)
    before = state.sell_value(prices) + state.bank

    if state.bank + received - buy_price < 0:
        return                                       # unaffordable; covered elsewhere

    state.make_transfer(3, 99, incoming(99, "DEF", buy_price), prices)

    prices[99] = buy_price
    after = state.sell_value(prices) + state.bank

    assert after == before, f"wealth changed by {after - before}"


@settings(max_examples=200, deadline=None)
@given(purchase=st.integers(min_value=40, max_value=140),
       rise=st.integers(min_value=1, max_value=30))
def test_you_never_profit_more_than_half_a_rise(purchase, rise):
    """The structural claim of the whole rule, stated as a property: however the
    price moves, your gain on a sale is at most half the rise."""
    state = SquadState(make_squad_frame(purchase=purchase))
    prices = flat_prices(state.elements, purchase + rise)
    gain = state.element_sell_price(3, prices) - purchase
    assert 0 <= gain <= rise / 2