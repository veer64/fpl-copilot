"""M3a push PART 3 (2026-10-23), failing tests first: two live code locks on the final reply (agent.py's reply path,
beside the tool-name and plain-word locks).

L1 clubs: a club claim about a player whose club CONTRADICTS the turn's tool row for that player (the club resolver of
   eval/judge/club_claims.py, tool rows first) -> the club is replaced with the tool's; players-table-only or ambiguous
   names -> no change (logged only). Measured: four 'Alexander Isak (FWD, Newcastle)' answers with team_out Liverpool
   in the plan.
L2 weekdays was DROPPED in the gate of the same day (fallback: a lock that breaks its neighbours is dropped): live, on
   get_player_card:9, it turned a sourced 'Monday' (the club's "Monday's press conference") into 'Tuesday' three times
   out of three because the model had attached the wrong date (20 Oct) -- the date, not the weekday, was the slip. The
   lock trusted the date. Pinned below: a weekday is never touched.
The text outside the corrected span stays byte-identical; the raw reply is kept for the canary and the checkers."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import reply_locks as rl                                   # noqa: E402

PLAYERS = [{"element": 379, "name": "Alexander Isak", "position": "FWD", "team": "Liverpool"},
           {"element": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City"},
           {"element": 3, "name": "Bukayo Saka", "position": "MID", "team": "Arsenal"},
           {"element": 4, "name": "Nick Pope", "position": "GK", "team": "Newcastle"},
           {"element": 1, "name": "Gabriel dos Santos Magalhães", "position": "DEF", "team": "Arsenal"},
           {"element": 2, "name": "Gabriel Martinelli Silva", "position": "MID", "team": "Arsenal"},
           {"element": 5, "name": "Son Heung-min", "position": "MID", "team": "Spurs"}]
PLAN = json.dumps({"this_deadline": {"transfers": [{"out": "Alexander Isak", "out_id": 379, "in": "Erling Haaland", "in_id": 411,
                                                     "team_out": "Liverpool", "position_out": "FWD", "team_in": "Man City", "position_in": "FWD"}]}})
TWO_GABRIELS = json.dumps({"rows": [{"name": "Gabriel dos Santos Magalhães", "team": "Arsenal", "position": "DEF"},
                                     {"name": "Gabriel Martinelli Silva", "team": "Arsenal", "position": "MID"}]})


def test_l1_a_club_that_contradicts_the_tool_row_is_replaced_and_nothing_else_moves():
    text = "Out: **Alexander Isak (FWD, Newcastle)** for Haaland.\nThe rest of the plan holds."
    new, log = rl.lock_clubs(text, [PLAN], PLAYERS)
    assert new == "Out: **Alexander Isak (FWD, Liverpool)** for Haaland.\nThe rest of the plan holds."
    assert len(log) == 1 and log[0]["player"] == "Alexander Isak" and log[0]["before"] == "Newcastle" and log[0]["after"] == "Liverpool"


def test_l1_a_claim_inside_a_table_cell_without_a_club_column_is_corrected():
    text = "| Out | Sell | In | Buy |\n|---|---|---|---|\n| Alexander Isak (FWD, Newcastle) | £9.0m | João Pedro (FWD, Chelsea) | £7.8m |"
    new, log = rl.lock_clubs(text, [PLAN], PLAYERS)
    assert new == "| Out | Sell | In | Buy |\n|---|---|---|---|\n| Alexander Isak (FWD, Liverpool) | £9.0m | João Pedro (FWD, Chelsea) | £7.8m |"
    assert [c["after"] for c in log if c["player_text"] == "Alexander Isak"] == ["Liverpool"]


def test_l1_a_table_cell_is_corrected_too():
    text = "| Player | Club |\n|---|---|\n| Isak | Newcastle |\n| Haaland | Man City |"
    new, log = rl.lock_clubs(text, [PLAN], PLAYERS)
    assert new == "| Player | Club |\n|---|---|\n| Isak | Liverpool |\n| Haaland | Man City |"
    assert [c["after"] for c in log] == ["Liverpool", None]                   # Haaland's cell is right: logged, unchanged


@pytest.mark.parametrize("text", [
    "Saka (Newcastle) is the pick.",                            # players-table only: no tool row -> no change
    "Gabriel (Spurs) is the pick.",                             # ambiguous between two tool rows -> no change
    "**GW8: Haaland at Aston Villa (away, Saturday 24 Oct)**",  # a fixture, not a club claim
    "Alexander Isak (FWD, Liverpool) is fine.",                 # correct club
    "Isak's goals came at Newcastle last season.",              # no claim form
])
def test_l1_leaves_everything_else_byte_identical(text):
    new, log = rl.lock_clubs(text, [PLAN, TWO_GABRIELS], PLAYERS)
    assert new == text and all(c.get("after") is None for c in log)


def test_apply_locks_corrects_clubs_only_keeps_the_raw_and_never_touches_a_weekday():
    raw = "Isak (FWD, Newcastle) came off on Monday 20 Oct; the deadline is Friday 31 October 11:00 UTC."
    out, log = rl.apply_locks(raw, [PLAN], PLAYERS)
    assert out == "Isak (FWD, Liverpool) came off on Monday 20 Oct; the deadline is Friday 31 October 11:00 UTC."
    assert raw.startswith("Isak (FWD, Newcastle)")
    assert [c["lock"] for c in log] == ["clubs"]
    assert not hasattr(rl, "lock_weekdays") and not hasattr(rl, "year_from_context")


def test_the_agent_applies_the_locks_before_rendering_citations(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    src = Path(agent.__file__).read_text(encoding="utf-8")
    i, j = src.find("plain, n_words = plain_words(plain)"), src.find("rendered = render_citations(plain, returned_results)")
    assert 0 < i < j and "apply_locks(" in src[i:j], "the locks run after the plain-word lock and before the citations are rendered"
