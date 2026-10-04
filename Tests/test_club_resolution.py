"""Club names (B23, measured 2026-10-04).

_resolve_team took the stored FPL short name, a 12-entry alias table, or a substring. So
"Manchester United" and "Nottingham Forest" worked (they are in the table) while
"Tottenham Hotspur", "Wolverhampton Wanderers" and "Brighton and Hove Albion" were all
"not a club in this season's calendar" -- the same sentence a typo gets, and the same sentence
Wolves get, although Wolves are a real club that is simply not in this division.

The accepted names now come from three measured sources, with no new alias table: the stored
club names, the bootstrap snapshot's `name` and `short_name` for every club in the league, and
the existing FIXTURE_TEAM_ALIASES -- matched on player_names.norm words, so a longer name whose
words contain a known one resolves ("brighton and hove albion" contains "brighton"). A club
known to the archives but not in this division says so, and an unknown name offers close names
through difflib, as resolve_player does.

No database and no network: the two lookups are monkeypatched.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402

KNOWN = ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea",
         "Coventry City", "Crystal Palace", "Everton", "Fulham", "Hull City", "Ipswich Town",
         "Leeds", "Liverpool", "Man City", "Man Utd", "Newcastle", "Nott'm Forest", "Spurs",
         "Sunderland"]
SHORTS = {"Arsenal": "ARS", "Brighton": "BHA", "Man City": "MCI", "Man Utd": "MUN",
          "Newcastle": "NEW", "Nott'm Forest": "NFO", "Spurs": "TOT", "Leeds": "LEE"}
HISTORY = {"Wolves", "West Ham", "Burnley", "Leicester", "Southampton", "Wolves"}


@pytest.fixture(autouse=True)
def sources(monkeypatch):
    monkeypatch.setattr(mt, "_club_short_names", lambda: dict(SHORTS))
    monkeypatch.setattr(mt, "_clubs_known_to_history", lambda: set(HISTORY))
    monkeypatch.setattr(mt, "_season_label", lambda: "2026-27")


@pytest.mark.parametrize("typed,want", [
    ("Spurs", "Spurs"), ("Tottenham", "Spurs"), ("Tottenham Hotspur", "Spurs"),
    ("tottenham hotspur fc", "Spurs"),
    ("Brighton and Hove Albion", "Brighton"), ("Brighton & Hove Albion", "Brighton"),
    ("Manchester United", "Man Utd"), ("Man Utd", "Man Utd"), ("MUN", "Man Utd"),
    ("Manchester City", "Man City"), ("MCI", "Man City"),
    ("Nottingham Forest", "Nott'm Forest"), ("NFO", "Nott'm Forest"),
    ("Newcastle United", "Newcastle"), ("Leeds United", "Leeds"),
    ("Arsenal FC", "Arsenal"), ("ars", "Arsenal"),
])
def test_the_names_people_type_resolve(typed, want):
    got, err = mt._resolve_team(typed, KNOWN)
    assert err is None, (typed, err)
    assert got == want, (typed, got)


def test_a_real_club_outside_this_division_says_so():
    got, err = mt._resolve_team("Wolves", KNOWN)
    assert got is None
    assert err == "Wolves is not in the 2026-27 Premier League", err
    got, err = mt._resolve_team("West Ham", KNOWN)
    assert "not in the 2026-27 Premier League" in err


def test_an_unknown_name_offers_close_clubs():
    got, err = mt._resolve_team("Tottenhm", KNOWN)
    assert got is None
    assert "Spurs" in err or "Tottenham" in err, err
    got, err = mt._resolve_team("Arsnal", KNOWN)
    assert "Arsenal" in err, err
    got, err = mt._resolve_team("Zzzzz Town", KNOWN)
    assert got is None and err


def test_an_ambiguous_fragment_still_names_the_candidates():
    got, err = mt._resolve_team("Man", KNOWN)
    assert got is None
    assert "Man City" in err and "Man Utd" in err, err


def test_the_stored_name_wins_over_everything():
    for club in KNOWN:
        got, err = mt._resolve_team(club, KNOWN)
        assert (got, err) == (club, None), (club, got, err)
