"""Prompt F1 D (18 Nov 2026; USER DECISION): the fixture grid's horizon from the user's words.

Measured before: R3f's A16 (eval/reports/r3f_answers.md): "Who has the easiest run of games for the next four?" -- get_fixtures was
called with no horizon and the grid showed its default five gameweeks (GW11-15).

D1  the count table: the numbers of gameweeks a message names (digits or one to ten; "next N", "N gameweeks / weeks / games /
    fixtures"); labels, points in time, ranks and counts of anything else never count;
D2  the horizon applied: named -> the user's number (the model's when it matches, corrected when not, filled when none was
    passed); not named -> as today; several -> the model's;
D3  through get_fixtures: "next four" -> the grid for 4, "next 3 gameweeks" -> 3 (the model's 5 corrected), "next two weeks" -> 2,
    "fixtures" -> the default 5; outside a turn as today.
No model, no network: the seeded clubs of Tests/test_fixture_grid.py."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                                             # noqa: E402
import model_tools as mt                                                   # noqa: E402
import turn_context                                                        # noqa: E402
from r3_seed import pool_db                                                # noqa: E402,F401  (the fixture)
from test_fixture_grid import fx                                           # noqa: E402,F401  (the fixture)

# ---- D: the fixture grid's horizon from the user's words ----------------------------------------------------------------------
COUNTS = [
    ("next four", [4]), ("next 3 gameweeks", [3]), ("next two weeks", [2]), ("fixtures", []),
    ("Who has the easiest run of games for the next four?", [4]), ("Show me fixtures for the next three gameweeks.", [3]),
    ("Arsenal's next 3 fixtures", [3]), ("over the coming 6 gameweeks", [6]), ("the next 5 GWs please", [5]),
    ("Who plays in the next ten weeks?", [10]), ("next 3 or 4 gameweeks", [3, 4]),
    ("GW12 fixtures", []), ("gameweek 12 fixtures", []), ("Who do Arsenal play in two weeks?", []), ("next 5 midfielders", []),
    ("top 5 fixtures this week", []), ("this week's fixtures", []), ("the next gameweek", []), ("£5m defenders with easy fixtures", []),
    ("make 2 transfers over the next 3 gameweeks", [3]),
]


@pytest.mark.parametrize("text,want", COUNTS, ids=[f"{i:02d}" for i in range(1, len(COUNTS) + 1)])
def test_d1_the_count_table(text, want):
    assert answers.gameweeks_named(text) == want


def test_d2_the_horizon_applied():
    assert answers.verified_fixture_horizon("next four", None) == (4, {"asked": None, "named": [4], "applied": 4, "why": "named, not passed"})
    assert answers.verified_fixture_horizon("next four", 5) == (4, {"asked": 5, "named": [4], "applied": 4, "why": "corrected"})
    assert answers.verified_fixture_horizon("next four", 4) == (4, {"asked": 4, "named": [4], "applied": 4, "why": "named"})
    assert answers.verified_fixture_horizon("fixtures", None) == (None, None)
    assert answers.verified_fixture_horizon("this week's fixtures", 1) == (1, None)
    assert answers.verified_fixture_horizon("next 3 or 4 gameweeks", 4) == (4, {"asked": 4, "named": [3, 4], "applied": 4, "why": "several named"})


def _grid(message, **kw):
    if message is None:
        return mt.get_fixtures(**kw)
    turn_context.begin("f1" + "d" * 30, user_message=message)
    try:
        return mt.get_fixtures(**kw)
    finally:
        turn_context.end()


@pytest.mark.parametrize("message,kw,n", [("Who has the easiest run of games for the next four?", {}, 4),
                                          ("Show me fixtures for the next three gameweeks.", {"horizon": 5}, 3),
                                          ("Fixtures for the next two weeks?", {}, 2),
                                          ("Show me the fixtures.", {}, 5), (None, {}, 5)])
def test_d3_through_get_fixtures(fx, message, kw, n):
    """The user's number gives exactly the grid the model passing horizon=n gets (the seeded calendar's GW13 blank for Bravo
    adds a column for every n, as it always has: the horizon counts each club's fixtures still to come)."""
    out = _grid(message, **kw)
    same = mt.get_fixtures(horizon=n)
    assert out["direct_reply"] == same["direct_reply"] and out["gameweeks"] == same["gameweeks"]
    if n != 5:
        assert out["horizon_check"]["applied"] == n and _grid(None, **kw)["gameweeks"] != out["gameweeks"]
    else:
        assert "horizon_check" not in out
