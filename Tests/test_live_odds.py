"""Tests for the live odds pull (eval/fetch_live_odds.py)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "squad"))

import fetch_live_odds as flo  # noqa: E402


def _event(books):
    return dict(home_team="Arsenal", away_team="Chelsea",
                commence_time="2026-09-04T19:00:00Z",
                bookmakers=[dict(key=k, last_update="2026-09-04T17:00:00Z",
                                 markets=[dict(key="h2h", outcomes=[
                                     dict(name="Arsenal", price=h),
                                     dict(name="Draw", price=d),
                                     dict(name="Chelsea", price=a)])])
                            for k, (h, d, a) in books.items()])


def test_unmapped_club_fails_loudly():
    with pytest.raises(flo.ClubNameError):
        flo.map_club("Wigan Athletic")
    # every mapped target and all 20 sources resolve
    assert len(flo.NAME_MAP) == 20
    assert flo.map_club("Nottingham Forest") == "Nott'm Forest"


def test_demargin_correct_on_known_example():
    """A margin-free book (2, 4, 4) and a uniformly-margined book (1.8, 3.6, 3.6)
    de-margin to the SAME (0.5, 0.25, 0.25); the consensus odds must be (2, 4, 4)."""
    ev = _event({"skybet": (2.0, 4.0, 4.0), "betway": (1.8, 3.6, 3.6),
                 "leovegas": (2.0, 4.0, 4.0), "casumo": (1.8, 3.6, 3.6),
                 "grosvenor": (2.0, 4.0, 4.0)})
    c = flo.consensus(ev)
    assert c is not None and c["n_books"] == 5
    assert abs(c["h"] - 2.0) < 1e-6 and abs(c["d"] - 4.0) < 1e-6 and abs(c["a"] - 4.0) < 1e-6
    # de-margined probabilities sum to 1
    assert abs(1 / c["h"] + 1 / c["d"] + 1 / c["a"] - 1.0) < 1e-9


def test_missing_book_degrades_countably_never_silently():
    """A panel book missing from an event: consensus over the REMAINING panel
    members with n_books recorded; below MIN_BOOKS the fixture is UNPRICED
    (None), never thinly priced; non-panel books never enter."""
    five = {k: (2.0, 4.0, 4.0) for k in flo.PANEL[:5]}
    c = flo.consensus(_event(five))
    assert c is not None and c["n_books"] == 5      # exactly at the floor: priced, counted
    four = {k: (2.0, 4.0, 4.0) for k in flo.PANEL[:4]}
    assert flo.consensus(_event(four)) is None      # below the floor: unpriced, not thin
    # a non-panel book cannot rescue it (the panel IS the source)
    four_plus_outsider = dict(four, bet365=(2.0, 4.0, 4.0))
    assert flo.consensus(_event(four_plus_outsider)) is None
