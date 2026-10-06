"""get_fixtures: a gameweek the calendar does not hold, and the size of a 20-club answer
(B21, B25, measured 2026-10-04).

B21 -- the loaded calendar covers GW6-38 (20 clubs x 33 gameweeks, 660 keys, no blank and no
double anywhere in it). GW3, GW5, GW39 and GW100 all came back as
`blank_gameweek: true, "no fixture for this team in this gameweek (a blank)"`, which reads as
"Arsenal are not playing" when the truth is "that gameweek is not in the file". A real blank
does not exist in this data, so it is pinned here with a calendar built by hand.

B25 -- with no team the answer was 100 entries and **190,162 characters**, every one carrying
the same four paragraphs of prose about why there are two difficulty numbers. One club is
10,715. The 20-club answer is now compact rows and the prose is said once.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402

TEAMS = ["Arsenal", "Chelsea", "Spurs"]
GWS = [6, 7, 8]


def cal_of(skip=()):
    """(team, gw) -> fixtures, for a small league; pairs in `skip` are left out (a real blank)."""
    out = {}
    for g in GWS:
        for i, t in enumerate(TEAMS):
            if (t, g) in skip:
                continue
            out[(t, g)] = [{"opponent": TEAMS[(i + 1) % len(TEAMS)], "opponent_id": i + 1,
                            "home": g % 2 == 0, "kickoff": f"2026-10-{10 + g}T14:00:00Z"}]
    return out


def rows_of():
    return [{"team": t, "gw": g, "team_lambda": 1.8, "opp_lambda": 0.9, "p_cs": 0.33,
             "horizon_step": g - GWS[0]}
            for g in GWS for t in TEAMS]


# ---- B21 -------------------------------------------------------------------------------
@pytest.mark.parametrize("gw", [9, 39, 100, 0])
def test_a_gameweek_the_calendar_does_not_hold_is_out_of_range(gw):
    """After the loaded range, or not a gameweek at all."""
    out = ft.build(rows_of(), cal_of(), 3, team="Arsenal", gw=gw)
    assert out.get("error_kind") == "out_of_range", (gw, out)
    assert "fixtures loaded cover GW6-8" in out["error"], out["error"]
    assert "fixtures" not in out or not out["fixtures"]


@pytest.mark.parametrize("gw", [1, 5])
def test_a_gameweek_before_the_loaded_range_says_it_was_played(gw):
    """Same words get_prediction uses for a gameweek behind the run's horizon."""
    out = ft.build(rows_of(), cal_of(), 3, team="Arsenal", gw=gw)
    assert out.get("error_kind") == "already_played", (gw, out)
    assert out["error"] == (f"GW{gw} has already been played; fixtures loaded cover GW6-8. "
                            "For what happened, use get_actual_points for a player, or "
                            "get_my_points for the team.")


def test_a_real_blank_inside_the_range_stays_a_blank():
    out = ft.build(rows_of(), cal_of(skip=[("Arsenal", 7)]), 3, team="Arsenal", gw=7)
    entry = out["fixtures"][0]
    assert entry["blank_gameweek"] is True
    assert "blank" in entry["note"]
    assert out.get("error_kind") is None


def test_a_gameweek_inside_the_range_is_unchanged():
    out = ft.build(rows_of(), cal_of(), 3, team="Arsenal", gw=6)
    entry = out["fixtures"][0]
    assert entry.get("blank_gameweek") is None and entry["n_fixtures"] == 1
    assert entry["fixtures"][0]["difficulty"]["attacking"]["value"] is not None


# ---- B25 -------------------------------------------------------------------------------
def test_no_team_returns_compact_rows_and_says_the_prose_once():
    out = ft.build(rows_of(), cal_of(), 3, horizon=3)
    assert out.get("compact") is True
    rows = out["fixtures"]
    assert len(rows) == len(TEAMS) * len(GWS)
    for r in rows:
        assert sorted(r) == ["attacking", "defensive", "gw", "home", "opponent", "team"], sorted(r)
    # the two-numbers rule is stated ONCE, at the top, not in every row
    body = json.dumps(rows)
    assert "averaged" not in body and "FDR" not in body
    assert "must not be averaged" in out["difficulty_is_two_numbers"]


def test_one_team_keeps_the_detailed_answer():
    out = ft.build(rows_of(), cal_of(), 3, team="Arsenal", horizon=3)
    assert out.get("compact") in (None, False)
    assert "provenance" in out["fixtures"][0]["fixtures"][0]


def test_a_compact_blank_still_says_blank():
    out = ft.build(rows_of(), cal_of(skip=[("Chelsea", 8)]), 3, horizon=3)
    blank = [r for r in out["fixtures"] if r["team"] == "Chelsea" and r["gw"] == 8]
    assert len(blank) == 1 and blank[0].get("blank") is True
    assert blank[0]["opponent"] is None
