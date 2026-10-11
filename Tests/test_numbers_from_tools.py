"""Part 5 of the smoke fixes (2026-10-10): numbers without inputs, and wrong "window" wording.

(a) "54 more forwards" was 79 - 25 done by the model; list_players now returns not_shown so there
    is nothing to compute. "28+ points" was 7 hits x 4 with the free-transfer count never shown;
    get_wildcard_gap now carries without_wildcard (free transfers now, the extra transfers, their
    hit cost) derived from the squad record by the same rule get_my_squad uses.
(b) The prompt's arithmetic rule carries the worked example.
(c) "GW9 is beyond the current model's active recommendation window" was said of a gameweek INSIDE
    the run's range. The planning note the solvers attach now says the gameweek is inside the
    model's range, and the prompt says a gameweek a tool solved is never "beyond" anything.
(d) Bonus, penalty and set-piece claims about a player come only from tools, never from memory.

Pure: the free-transfer rule is squad_store.free_transfers_at on a hand-built record.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402


def _record(gw=6, free=1):
    return {"gw": gw, "squad_json": {"free_transfers": free}}


# ------------------------------------------------------------------ (a) the wildcard's hit cost
def test_the_hit_cost_without_the_chip_is_derived_by_the_tool():
    out = mt._without_wildcard(_record(6, 1), 6, 11)
    assert out == {"free_transfers_now": 1, "transfers_needed": 11, "extra_transfers": 10,
                   "hit_cost_points": 40,
                   "note": ("making these 11 transfers without the chip would use 1 free transfer and "
                            "cost 10 extra transfers x 4 = 40 points")}


def test_banked_free_transfers_count_and_a_small_plan_costs_nothing():
    out = mt._without_wildcard(_record(6, 1), 8, 3)        # two gameweeks banked: 1 + 2 = 3 free
    assert out["free_transfers_now"] == 3 and out["extra_transfers"] == 0 and out["hit_cost_points"] == 0
    assert out["note"] == ("making these 3 transfers without the chip would use 3 free transfers and "
                           "cost 0 extra transfers x 4 = 0 points")


def test_a_record_the_rule_cannot_read_is_reported_not_guessed():
    out = mt._without_wildcard(_record(8, 1), 6, 11)       # the version is for a later gameweek
    assert out["free_transfers_now"] is None and out["hit_cost_points"] is None
    assert "free transfers are defined" in out["note"]


# ------------------------------------------------------------------ (c) the planning note
def test_the_planning_note_says_inside_the_range_never_beyond(monkeypatch):
    note = mt._planning_note(9, 6)
    assert note.startswith("Planning view for GW9")
    assert "inside the model's range" in note
    assert "beyond" not in note.lower() and "window" not in note.lower()
    assert "availability and predictions will change before then" in note
    assert mt._planning_note(6, 6) is None


# ------------------------------------------------------------------ (b), (c), (d) the prompt
def test_the_prompt_carries_the_three_rules():
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    p = agent.SYSTEM_PROMPT
    assert '"7 extra transfers x 4 = 28 points"' in p
    assert "A number whose inputs you cannot show is a number you do not state" in p
    assert "A gameweek a tool solved or priced is INSIDE the model's range" in p
    assert "Whether a player takes penalties or set pieces, or regularly earns bonus points, comes only from a tool result" in p
