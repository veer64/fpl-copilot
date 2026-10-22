"""Club resolver to its definition (2026-10-22), failing tests first.

DEFINITION: a player named in a reply is matched FIRST against the player rows in that turn's tool outputs: full name,
FPL display name, first or last name, accent-folded; a reply name that is a whole token or a token prefix of exactly
one tool row's name (e.g. 'Antón' ~ 'António ... Tavares da Silva') resolves to that row. Only when no tool row
matches is the players table used. A name that matches more than one player at either step is not resolved (no club
claim is scored).

The known positive: the closing gate's optimise:5 HEAD row "- **GW9:** Bijol -> Antón (Bournemouth, DEF)" with the
tool row in_id 566 "António João Pereira de Albuquerque Tavares da Silva" (Bournemouth) resolved to Anton Stach
(Leeds) through the players table: must PASS (sourced_ok)."""
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
           {"element": 335, "name": "Anton Stach", "position": "MID", "team": "Leeds"},
           {"element": 566, "name": "António João Pereira de Albuquerque Tavares da Silva", "position": "DEF", "team": "Bournemouth"},
           {"element": 1, "name": "Gabriel dos Santos Magalhães", "position": "DEF", "team": "Arsenal"},
           {"element": 2, "name": "Gabriel Martinelli Silva", "position": "MID", "team": "Arsenal"},
           {"element": 3, "name": "Bukayo Saka", "position": "MID", "team": "Arsenal"},
           {"element": 4, "name": "Nick Pope", "position": "GK", "team": "Newcastle"},          # the clubs named in claims
           {"element": 5, "name": "Son Heung-min", "position": "MID", "team": "Spurs"}]        # must exist in the players table
PLAN = json.dumps({"later_steps_indicative": [{"gw": 9, "transfers": [
    {"out": "Jaka Bijol", "out_id": 327, "in": "António João Pereira de Albuquerque Tavares da Silva", "in_id": 566,
     "team_out": "Leeds", "position_out": "DEF", "team_in": "Bournemouth", "position_in": "DEF"}]}]})
ISAK = json.dumps({"matches": [{"name": "Alexander Isak", "team": "Liverpool", "position": "FWD", "player_id": 379, "web_name": "Isak"}]})
TWO_GABRIELS = json.dumps({"rows": [{"name": "Gabriel dos Santos Magalhães", "team": "Arsenal", "position": "DEF"},
                                     {"name": "Gabriel Martinelli Silva", "team": "Arsenal", "position": "MID"}]})


def check(text, tool):
    rows = CC.check({"rendered_reply": text, "calls": [{"output": tool}]}, PLAYERS)
    s = CC.summary(rows)
    return s["unsourced"] + s["wrong_vs_table"], [(r["player_text"], r["club_text"], r["player"], r["resolved_by"], r["status"]) for r in rows]


def test_the_closing_gate_row_resolves_to_the_tool_row_and_passes():
    n, rows = check("- **GW9:** Bijol → Antón (Bournemouth, DEF) — 1 free transfer", PLAN)
    assert n == 0, rows
    anton = [r for r in rows if r[0] == "Antón"]
    assert anton and anton[0][2].startswith("António") and anton[0][3] == "tool" and anton[0][4] == "sourced_ok", rows


def test_a_wrong_short_name_with_one_matching_token_resolves_to_the_tool_row_and_passes():
    n, rows = check("- **GW9:** Bijol → Nuno Tavares (DEF, Bournemouth), 0 hits", PLAN)
    assert n == 0, rows
    nt = [r for r in rows if r[0] == "Nuno Tavares"]
    assert nt and nt[0][2].startswith("António") and nt[0][4] == "sourced_ok", rows


def test_the_wrong_club_for_the_resolved_tool_row_still_fails():
    n, rows = check("- **GW9:** Bijol → Antón (Leeds, DEF)", PLAN)
    assert n == 1 and rows[0][2].startswith("António") and rows[0][4] == "sourced_wrong", rows


@pytest.mark.parametrize("text", [
    "Isak (FWD, Newcastle) is the pick.", "Isak (Newcastle) is the pick.", "Newcastle's Isak is the pick.",
    "Isak, who plays for Newcastle, is the pick.", "Isak who plays for Newcastle is the pick.",
    "Isak at Newcastle has been superb this season.", "Isak of Newcastle is the pick.", "Isak (Newcastle, FWD) is the pick.",
])
def test_every_hand_made_claim_of_the_close_report_still_fails(text):
    n, rows = check(text, ISAK)
    assert n == 1 and rows[0][4] == "sourced_wrong", (text, rows)


def test_the_table_row_still_fails():
    n, rows = check("| Player | Club |\n|---|---|\n| Isak | Arsenal |", ISAK)
    assert n == 1 and rows[0][4] == "sourced_wrong", rows


def test_a_name_that_prefixes_two_tool_rows_scores_no_claim():
    n, rows = check("Gab (Spurs) is the pick.", TWO_GABRIELS)
    assert n == 0 and rows and rows[0][2] is None and rows[0][4] == "unknown_player", rows
    n, rows = check("Gabriel (Spurs) is the pick.", TWO_GABRIELS)
    assert n == 0 and rows and rows[0][4] == "unknown_player", rows


def test_display_name_and_last_name_resolve_and_the_table_is_only_the_fallback():
    n, rows = check("Isak (Liverpool) is fine.", ISAK)
    assert n == 0 and rows[0][3] == "tool" and rows[0][4] == "sourced_ok"
    n, rows = check("Saka (Arsenal) is fine.", ISAK)                     # not in the tool rows -> the table: unsourced (a hit by design, Part C rule 4)
    assert n == 1 and rows[0][3] == "table" and rows[0][4] == "unsourced", rows
