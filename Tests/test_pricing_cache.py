"""pricing.py with prompt-cache rates (2026-10-19, from the Claude docs read 19 Oct 2026): a cache write costs 1.25x
the base input price; a cache read 0.1x, except 0.05x for claude-opus-5-5 and claude-sonnet-5-5 and 0.025x for
claude-fable-5-1 / claude-mythos-5-1. turn_usd = uncached input + 1.25 x write + read multiplier x read + output."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pricing                                             # noqa: E402


def test_the_multipliers_are_the_documented_ones():
    assert pricing.CACHE_WRITE_MULT == 1.25
    assert pricing.cache_read_multiplier("claude-sonnet-4-6") == 0.10
    assert pricing.cache_read_multiplier("claude-haiku-5-5") == 0.10            # the default for a model not listed
    assert pricing.cache_read_multiplier("claude-opus-5-5") == 0.05
    assert pricing.cache_read_multiplier("claude-sonnet-5-5") == 0.05
    assert pricing.cache_read_multiplier("claude-fable-5-1") == 0.025
    assert pricing.cache_read_multiplier("claude-mythos-5-1") == 0.025


def test_turn_usd_on_hand_made_cases():
    # sonnet-4-6: $3 in / $15 out; 1000 uncached in + 100 out, no cache = the old price
    assert pricing.turn_usd("claude-sonnet-4-6", 1000, 100) == pytest.approx(0.0045)
    assert pricing.turn_usd("claude-sonnet-4-6", 1000, 100) == pricing.usd("claude-sonnet-4-6", 1000, 100)
    # + 2000 written (x1.25 = $7.5/M -> 0.0075) + 10000 read (x0.10 = $0.3/M -> 0.003)
    assert pricing.turn_usd("claude-sonnet-4-6", 1000, 100, cache_read=10000, cache_write=2000) == pytest.approx(0.015)
    # a turn served entirely from cache: 0 uncached input
    assert pricing.turn_usd("claude-sonnet-4-6", 0, 10, cache_read=20000) == pytest.approx(20000 / 1e6 * 0.3 + 10 / 1e6 * 15)
    # None tokens count as 0, as usd() always did
    assert pricing.turn_usd("claude-sonnet-4-6", None, None, cache_read=None, cache_write=None) == 0.0


def test_a_model_without_a_price_row_prices_to_none():
    assert pricing.turn_usd("claude-opus-5-5", 1000, 100, cache_read=10) is None
    assert pricing.usd("claude-opus-5-5", 1000, 100) is None
