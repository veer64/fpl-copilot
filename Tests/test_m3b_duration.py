"""M3b duration check (Prompt C Part 5, 2026-10-26). DEFINITION: a duration, difference or count in a reply is SUPPORTED if
code computes the same value from dates present in that turn's tool outputs or message lines, at the precision the reply
states (rounded or truncated both accepted; "about / roughly / just under / over" widen it to +- half the smallest unit
stated, and "just under / over" must be on the right side). Implemented in eval/judge/number_claims.py as a code check that
turns a judge M3b FAIL into PASS ("code: computed") only when it matches.

VALIDATION SET (Prompt A's saved answers, 25 Oct): the dismissed misfires must PASS -- time:1 x4 "5 days, 20 hours and 30
minutes" from Sunday 2026-10-25 14:30 UTC to Saturday 2026-10-31 11:00 UTC, time:12 "4 days and ~3.5 hours" from the run
built 2026-10-21 11:01:46 UTC; the real errors must still FAIL -- time:8 old r1 "just under 5 days", new r1 "roughly 6 days
and 20 hours"."""
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from judge import number_claims as NC                     # noqa: E402

UTC = timezone.utc
CONTEXT = ("CONTEXT BLOCK (rebuilt every turn from local data; today, the gameweek state, the update schedule, the clubs)\n"
           "- Now: Sunday 2026-10-25 14:30 UTC.\n"
           "- Gameweeks: GW7 is the last finished gameweek; GW8 is in progress (deadline passed, not yet final); next deadline GW9, Saturday 2026-10-31 11:00 UTC.")
HISTORY = ("{'player_id': 411, 'name': 'Haaland', 'history': [{'run_id': 46, 'built_at': '2026-10-21 11:01:46.377019+00:00', "
           "'built': 'nightly run built Wed 21 Oct 11:01Z', 'e_points': 7.47}]}")
SOURCES = [CONTEXT, "How long until the GW9 deadline?", HISTORY]


def _claims(reply):
    return NC.extract_claims(reply, user_text="")


def _check(reply, sources=SOURCES):
    claims = _claims(reply)
    out = {}
    for c in claims:
        ok, why = NC.duration_supported(c, sources)
        out[c["text"]] = (ok, why)
    return out


def test_datetime_candidates_come_from_the_material_in_every_stored_shape():
    cands = NC.datetime_candidates(SOURCES)
    assert datetime(2026, 10, 25, 14, 30, tzinfo=UTC) in cands              # the Now line
    assert datetime(2026, 10, 31, 11, 0, tzinfo=UTC) in cands               # the context block's deadline
    assert datetime(2026, 10, 21, 11, 1, 46, tzinfo=UTC) in cands           # a tool's built_at
    more = NC.datetime_candidates(["deadline 2026-10-31T11:00:00Z", "Next deadline: GW9, Sat 31 Oct 2026 11:00 UTC — in 5 d", "built Fri 23 Oct 17:21Z"])
    assert datetime(2026, 10, 31, 11, 0, tzinfo=UTC) in more and datetime(2026, 10, 23, 17, 21, tzinfo=UTC) in more


def test_parse_duration_reads_components_hedges_and_decimals():
    d = NC.parse_duration_at("that's **5 days, 20 hours and 30 minutes** away", 10)
    assert d["seconds"] == 5 * 86400 + 20 * 3600 + 30 * 60 and d["unit"] == 60 and d["hedge"] is None
    d = NC.parse_duration_at("just under **5 days away** from now", 14)
    assert d["seconds"] == 5 * 86400 and d["unit"] == 86400 and d["hedge"] == "just under"
    d = NC.parse_duration_at("is **4 days and ~3.5 hours**, so", 6)
    assert d["seconds"] == 4 * 86400 + 3.5 * 3600 and d["unit"] == 360 and d["hedge"] == "about"
    assert NC.parse_duration_at("he scored 5 goals in 20 games", 11) is None


def test_validation_set_time_1_exact_duration_passes():
    out = _check("The GW9 deadline is **Saturday 2026-10-31 at 11:00 UTC**. From now (Sunday 2026-10-25 14:30 UTC) that's **5 days, 20 hours and 30 minutes** away.")
    assert out["5"][0] and out["20"][0] and out["30"][0], out
    assert "code: computed" in out["5"][1]


def test_validation_set_time_12_about_decimal_hours_passes():
    out = _check("From Wednesday 21 October 11:01 UTC to now (Sunday 25 October 14:30 UTC) is **4 days and ~3.5 hours**, so roughly **4 days** since it last moved.")
    assert out["3.5"][0] and out["4"][0], out


def test_validation_set_time_8_real_errors_still_fail():
    out = _check("The **GW9 deadline is Saturday 31 October at 11:00 UTC** — that's just under **5 days away** from now (Sunday 25 October, 14:30 UTC).")
    assert out["5"][0] is False and "wrong side" in out["5"][1]
    out = _check("The next deadline is **Saturday 31 October at 11:00 UTC**, so you have roughly **6 days and 20 hours** from now.")
    assert out["6"][0] is False and out["20"][0] is False


def test_about_just_over_and_truncation_are_accepted_on_the_right_side():
    out = _check("which is about **5 days and 20 hours away** from now (Sunday 14:30 UTC).")
    assert out["5"][0] and out["20"][0]
    out = _check("so you have just over **5 days and 20 hours** from now to make any transfers.")
    assert out["5"][0] and out["20"][0]
    out = _check("you have **5 days** left.")                                   # truncated to days
    assert out["5"][0]
    out = _check("you have **6 days** left.")                                   # rounded to days (5.85 -> 6)
    assert out["6"][0]
    out = _check("you have just over **6 days** left.")                         # wrong side of 6
    assert out["6"][0] is False


def test_apply_duration_check_flips_only_matching_rows_to_computed():
    reply = "From now (Sunday 2026-10-25 14:30 UTC) that's **5 days, 20 hours and 30 minutes** away. The model updates three more times."
    claims = _claims(reply)
    rows = [{"id": c["id"], "text": c["text"], "number": c["value"], "context": c["context"], "final": "WRONG", "why": "judge", "code": {}} for c in claims]
    out = NC.apply_duration_check(rows, claims, SOURCES)
    by = {r["text"]: r for r in out}
    assert by["5"]["final"] == "DERIVED" and by["5"]["why"].startswith("code: computed") and by["5"]["code"]["duration_ok"] is True
    assert by["20"]["final"] == "DERIVED" and by["30"]["final"] == "DERIVED"
    assert by["three"]["final"] == "WRONG"                                       # not a duration: untouched
    assert NC.code_verdict(out) == "FAIL" and "three" in NC.code_reason(out)
