"""
Squad scoring as a TICK-LEVEL action of the weekly ingest (Decision 2,
2026-09-12): it runs after a successful chain and on NOTHING-NEW ticks, never
fails the ingest, is bounded like the ingest's own retries, and when it gives
up it writes a standing line that names what a human should do.

No network, no DB, no real steps: the FakeSteps executor from
test_weekly_ingest plays the scorer.

Run:
    uv run pytest Tests/test_weekly_ingest_scoring.py -v
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_weekly_ingest as wi                                             # noqa: E402
from test_weekly_ingest import FakeSteps, _events, _runner, _seed, NOW     # noqa: E402


def test_scoring_failure_is_action_required_not_a_failed_ingest(tmp_path):
    """The scorer exits non-zero: the ingest stays SUCCESS and clears its
    markers (the volume rewrite is not coupled to the DB) but the status
    carries ACTION REQUIRED so /health degrades; the attempt is counted."""
    h = _seed(tmp_path, gws=(1, 2, 3))
    steps = FakeSteps(h, fail_scoring_gw=4)
    R = _runner(tmp_path, steps)
    assert R.decide(now=NOW) == "RUN"
    R.run_chain()
    first = R.write_status()
    assert first.startswith("SUCCESS -- ACTION REQUIRED")
    assert steps.calls[-1] == "score_squads"
    assert not (tmp_path / "live" / "ingest_gw4.partial.json").exists()
    assert not (tmp_path / "live" / "ingest_gw4.attempts.json").exists()
    txt = (tmp_path / "live" / "INGEST_STATUS.txt").read_text()
    assert "squad scoring FAILED (attempt(s) {'4': 1} of 8" in txt
    att = json.loads((tmp_path / "live" / "scoring_attempts.json").read_text())
    assert att["4"]["attempts"] == 1 and "[inconsistent_versions]" in att["4"]["last_error"]


def test_nothing_new_tick_still_scores_outstanding_gameweeks(tmp_path):
    """Scoring is a tick-level action: with nothing to ingest it still runs, so
    a gameweek that could not be scored last time (or a squad seeded since)
    gets scored six hours later without anyone remembering."""
    h = _seed(tmp_path, gws=(1, 2, 3, 4))
    steps = FakeSteps(h)
    R = _runner(tmp_path, steps)
    assert R.decide(now=NOW) == "NOTHING-NEW"
    assert R.score_outstanding() == 0
    assert steps.calls == ["score_squads"] and steps.requested == [1, 2, 3, 4]
    assert any(t.startswith("SQUAD SCORES") for t, _ in R.sections)
    assert R.actions == []


def test_deferred_tick_does_not_score(tmp_path):
    """Inside a deadline window the tick stays quiet: main() does not call
    score_outstanding on DEFERRED, and decide() alone runs nothing."""
    h = _seed(tmp_path, gws=(1, 2, 3))
    steps = FakeSteps(h)
    R = _runner(tmp_path, steps, events=_events(deadline=NOW + timedelta(hours=1)))
    assert R.decide(now=NOW) == "DEFERRED"
    assert steps.calls == []


def test_retries_are_bounded_and_the_standing_line_names_the_fix(tmp_path):
    """Eight failures for GW4, then GW4 leaves the request, the scorer is still
    run for the others, and a STANDING ACTION REQUIRED names the inspection
    query, the fix and the re-arm -- not a traceback."""
    h = _seed(tmp_path, gws=(1, 2, 3, 4))
    steps = FakeSteps(h, fail_scoring_gw=4)
    R = _runner(tmp_path, steps)
    R.decide(now=NOW)
    for i in range(wi.MAX_SCORING_ATTEMPTS):
        R.actions.clear(); R.sections.clear()
        assert R.score_outstanding() == 1
        assert steps.requested == [1, 2, 3, 4]
    att = json.loads((tmp_path / "live" / "scoring_attempts.json").read_text())
    assert att["4"]["attempts"] == wi.MAX_SCORING_ATTEMPTS
    # the ninth tick: GW4 excluded, standing line present, others still requested
    R.actions.clear(); R.sections.clear()
    steps.fail_scoring_gw = None
    R.score_outstanding()
    assert steps.requested == [1, 2, 3]
    titles = [t for t, _ in R.actions]
    assert any("GW4 GAVE UP after 8 attempts -- human needed" in t for t in titles)
    text = next(x for t, x in R.actions if "GAVE UP" in t)
    assert "SELECT version_id, gw, created_at, squad_json->'provenance' FROM squad_versions WHERE gw = 4" in text
    assert "set_my_squad" in text and "re-arm: delete the '4' entry" in text
    assert "Traceback" not in text


def test_success_clears_the_attempt_counter(tmp_path):
    h = _seed(tmp_path, gws=(1, 2, 3, 4))
    steps = FakeSteps(h, fail_scoring_gw=4)
    R = _runner(tmp_path, steps)
    R.decide(now=NOW)
    R.score_outstanding()
    assert json.loads((tmp_path / "live" / "scoring_attempts.json").read_text())["4"]["attempts"] == 1
    steps.fail_scoring_gw = None
    R.actions.clear(); R.sections.clear()
    assert R.score_outstanding() == 0
    assert not (tmp_path / "live" / "scoring_attempts.json").exists()
    assert R.actions == []


def test_whole_run_failure_counts_globally_and_gives_up_with_db_instructions(tmp_path):
    """A scorer that cannot even start (DB unreachable) has no GWn: lines; the
    failure is counted under 'global' and after the bound the scorer is not
    invoked and the standing line points at Postgres and .env."""
    h = _seed(tmp_path, gws=(1, 2, 3, 4))

    class Down(FakeSteps):
        def __call__(self, args, timeout):
            name = Path(args[0]).stem
            self.calls.append(name)
            if name == "score_squads":
                return 1, "score_squads FAILED [db_unreachable] OperationalError: could not connect"
            return super().__call__(args, timeout)

    steps = Down(h)
    R = _runner(tmp_path, steps)
    R.decide(now=NOW)
    for _ in range(wi.MAX_SCORING_ATTEMPTS):
        R.actions.clear(); R.sections.clear()
        R.score_outstanding()
    att = json.loads((tmp_path / "live" / "scoring_attempts.json").read_text())
    assert att["global"]["attempts"] == wi.MAX_SCORING_ATTEMPTS and "4" not in att
    n_calls = len(steps.calls)
    R.actions.clear(); R.sections.clear()
    assert R.score_outstanding() is None                    # not invoked any more
    assert len(steps.calls) == n_calls
    text = next(x for t, x in R.actions if "GAVE UP" in t)
    assert "fpl-postgres" in text and ".env" in text and "delete the 'global' entry" in text


def test_scoring_instruction_falls_back_to_the_log_for_unknown_classes():
    text = wi.scoring_instruction("GW4: FAILED [error] KeyError: 'x'", 4)
    assert "INGEST_RUN.log" in text and "re-arm" in text
