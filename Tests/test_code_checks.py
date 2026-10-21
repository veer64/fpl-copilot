"""eval/judge/code_checks.py (2026-10-21): the flags-relabelled check matches its written definition -- a sentence
fails only when it TIES an FPL flag / chance of playing to a gameweek different from the one the turn's tool output
gives for that flag; a flag beside an unrelated gameweek (a plan step, a gap figure) is not a tie; a flag with no
gameweek is the report-only row "flag without gameweek". The validation set of eval/reports/checker_and_fix_batch4_v1.md
A2, as tests. No API, no DB (the player table is loaded once at import from the local data, as the checker always did)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from judge import code_checks as ck                        # noqa: E402

GW7 = {"collins": {"gws": {7}, "chances": {0}}, "gakpo": {"gws": {7}, "chances": {25}}, "isak": {"gws": {7}, "chances": {25}},
       "foden": {"gws": {7}, "chances": {0}}}


def hits(text, flags):
    return [(h["player"], h["sentence_gw"]) for h in ck.relabelled(text, flags)]


# ---- known real relabels: must FAIL --------------------------------------------------------------------------------

def test_r1_foden_returns_in_gw8_fails_when_the_sentence_names_him():
    gw6 = {"foden": {"gws": {6}, "chances": {0}}}
    named = "**Keep an eye on the updated FPL flag on deadline day (17 Oct) to confirm Foden's return for GW8.**"
    assert hits(named, gw6) == [("foden", [8])]
    assert hits(named, {"foden": {"gws": {7}, "chances": {0}}}) == [("foden", [8])]
    # the literal sentence of 12 Oct says "his return": a per-sentence, name-based check cannot attach it to Foden
    # (the old checker could not either); pinned here as the known limit, not as a pass
    literal = "**Keep an eye on the updated FPL flag on deadline day (17 Oct) to confirm his return for GW8.**"
    assert hits(literal, gw6) == []


def test_r2_collins_gw6_flag_tied_to_gw7_fails():
    assert hits("Collins is injured with a 0% chance of playing in GW7.", {"collins": {"gws": {6}, "chances": {0}}}) == [("collins", [7])]


def test_r3_the_definitions_own_example_fails():
    assert hits("Gakpo 25% for GW8.", GW7) == [("gakpo", [8])]
    assert hits("Gakpo (25% chance of playing) is a risk for GW8.", GW7) == [("gakpo", [8])]


def test_hand_made_ties_to_a_wrong_gameweek_fail():
    assert hits("Collins is injured, 0% chance of playing in GW8.", GW7) == [("collins", [8])]
    assert hits("Isak will miss GW8 with his thigh injury.", GW7) == [("isak", [8])]
    assert hits("Collins is out until GW9.", GW7) == [("collins", [9])]
    assert hits("For GW8, Collins is unavailable.", GW7) == [("collins", [8])]


# ---- known misfires: must PASS --------------------------------------------------------------------------------------

M1 = ("- **Gap: +11.8 over six gameweeks (weighted); +11.9 for GW8 alone** — a clear gain, driven largely by swapping out "
      "the two doubtful Liverpool players (Isak at 25%, Gakpo at 25%) and the Collins injury concern.")
M2 = "- **GW11:** Cody Gakpo → Sávio (Spurs MID, £6.5m) — if Gakpo remains doubtful"


def test_m1_v1_sentence_is_not_a_tie():
    assert hits(M1, GW7) == []


def test_m2_v2_sentence_is_not_a_tie():
    assert hits(M2, GW7) == []


# ---- hand-made PASS cases ---------------------------------------------------------------------------------------------

def test_tie_to_the_right_gameweek_passes():
    assert hits("Collins is 0% chance of playing in GW7.", GW7) == []
    assert hits("Collins and Gakpo are both flagged at 0% chance of playing GW7.", GW7) == []


def test_flag_beside_a_plan_step_passes():
    assert hits("- **GW9:** Collins → Calafiori — Collins is injured", GW7) == []
    assert hits("That's a big GW7 gap, driven by getting two injured players (Gakpo, Collins) off the pitch.", GW7) == []


def test_the_f13_latest_flag_form_passes():
    assert hits("Gakpo's latest FPL flag (for GW7, as of 17 Oct 2026): chance of playing 25% — kept for the GW9 step.", GW7) == []


def test_a_flag_with_no_gameweek_is_not_this_check_but_the_report_only_row():
    s = "Collins is injured (0%). Gakpo looks doubtful too."
    assert hits(s, GW7) == []
    assert [h["player"] for h in ck.flag_without_gw(s, GW7)] == ["collins", "gakpo"]
    assert ck.flag_without_gw("Collins is 0% chance of playing in GW7.", GW7) == []


# ---- the tool side ------------------------------------------------------------------------------------------------------

def test_tool_flags_collect_the_gameweek_and_the_chance_per_player():
    rec = {"turns": [{"calls": [{"tool": "propose_transfers", "output": str({
        "transfers": [{"out": "Nathan Collins", "chance_words_out": "chance of playing in GW7: 0%, FPL as of 17 Oct 2026"}],
        "squad": [{"name": "Cody Gakpo", "chance_words": "latest FPL flag (for GW7, as of 17 Oct 2026): chance of playing 25%"}]})}]}]}
    f = ck.tool_flags(rec)
    assert f["collins"] == {"gws": {7}, "chances": {0}}
    assert f["gakpo"] == {"gws": {7}, "chances": {25}}


def test_checks_carry_both_rows():
    rec = {"id": "x", "result": "PASS", "rendered_reply": "Collins is injured (0%). Gakpo 25% for GW8.",
           "turns": [{"calls": [{"tool": "get_my_squad", "output": str({"squad": [
               {"name": "Nathan Collins", "chance_words": "chance of playing in GW7: 0%, FPL as of 17 Oct 2026"},
               {"name": "Cody Gakpo", "chance_words": "chance of playing in GW7: 25%, FPL as of 17 Oct 2026"}]})}]}]}
    c = ck.checks(rec)
    assert [h["player"] for h in c["flag_relabelled"]] == ["gakpo"]
    assert [h["player"] for h in c["flag_without_gw"]] == ["collins"]
    assert "flag_without_gw" in ck.REPORT_ONLY_KEYS and "flag_without_gw" not in ck.KEYS
