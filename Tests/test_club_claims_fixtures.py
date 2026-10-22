"""Fix batch #4 close, PART A (2026-10-22), failing tests first: the club checker fires only on a CLUB CLAIM about a
player (the player tied to a club as his own club) and never on a FIXTURE line.

DEFINITION (written before the code change): unsourced / wrong clubs fire only on a CLUB CLAIM about a player: the
player tied to a club as his own club -- "Isak (FWD, Newcastle)", "Newcastle's Isak", "Isak, who plays for Newcastle",
"Isak at Newcastle" used as his club. A fixture is NOT a club claim: "Haaland at Aston Villa (away, Sat 24 Oct)",
"Haaland vs Arsenal", "away at X", "home to X", "X (H)/(A)".

The known positive: the follow-up gate's limits:2 HEAD F11 round-2 line "**GW8: Haaland at Aston Villa (away, Saturday
24 Oct)**" fired as a wrong club (the tool says Man City). Under the definition it is a fixture: must PASS."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from judge import club_claims as CC  # noqa: E402

PLAYERS = [{"element": 379, "name": "Alexander Isak", "position": "FWD", "team": "Liverpool"},
           {"element": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City"},
           {"element": 1, "name": "Bukayo Saka", "position": "MID", "team": "Arsenal"},
           {"element": 2, "name": "Cole Palmer", "position": "MID", "team": "Chelsea"},
           {"element": 3, "name": "Nick Pope", "position": "GK", "team": "Newcastle"},
           {"element": 4, "name": "Ollie Watkins", "position": "FWD", "team": "Aston Villa"},
           {"element": 5, "name": "Son Heung-min", "position": "MID", "team": "Spurs"}]
TOOL = json.dumps({"matches": [{"name": "Alexander Isak", "team": "Liverpool", "position": "FWD", "player_id": 379},
                               {"name": "Erling Haaland", "team": "Man City", "position": "FWD", "player_id": 411}]})


def hits(text):
    rows = CC.check({"rendered_reply": text, "calls": [{"output": TOOL}]}, PLAYERS)
    s = CC.summary(rows)
    return s["unsourced"] + s["wrong_vs_table"], [(r["player_text"], r["club_text"], r["status"]) for r in rows]


@pytest.mark.parametrize("text", [
    "Isak (FWD, Newcastle) is the pick.",                       # the definition's first form (position before the club)
    "Isak (Newcastle) is the pick.",
    "Newcastle's Isak is the pick.",
    "Isak, who plays for Newcastle, is the pick.",
    "Isak who plays for Newcastle is the pick.",
    "Isak at Newcastle has been superb this season.",           # 'at' used as his club: still a claim
    "Isak of Newcastle is the pick.",
    "Isak (Newcastle, FWD) is the pick.",
])
def test_a_club_claim_about_a_player_still_fires_against_the_tools_club(text):
    n, rows = hits(text)
    assert n == 1, (text, rows)
    assert rows[0][2] == "sourced_wrong" and rows[0][1].lower().startswith("newcastle"), rows


@pytest.mark.parametrize("text", [
    "**GW8: Haaland at Aston Villa (away, Saturday 24 Oct)**",  # the follow-up's limits:2 line, the known false positive
    "Haaland at Aston Villa, away, Saturday 24 Oct, looks good.",
    "Haaland vs Arsenal this week.",
    "Haaland away at Spurs on Saturday.",
    "Haaland, home to Chelsea on Sunday.",
    "Haaland faces Arsenal (H) then Spurs (A).",
    "| 8 | at Aston Villa | 6 |",
    "Haaland at Aston Villa (A) on Saturday.",
    "Haaland at Aston Villa (a) then Arsenal (h).",
])
def test_a_fixture_line_is_not_a_club_claim(text):
    n, rows = hits(text)
    assert n == 0, (text, rows)


def test_the_sourced_ok_club_still_passes_and_a_table_claim_still_fires():
    n, rows = hits("Haaland (Man City) is the captain.")
    assert n == 0 and rows[0][2] == "sourced_ok"
    n, rows = hits("| Player | Club |\n|---|---|\n| Haaland | Arsenal |")
    assert n == 1 and rows[0][2] == "sourced_wrong"
