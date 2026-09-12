"""
The multi-run schedule as a pure policy (eval/dispatch_policy.py): kinds,
gating, attempts, precedence, the expected-next promise, the outcome
bookkeeping, the /health reasons (decision 5 + the broken-promise check) and
the freshness string. Fake clocks, fake events, no I/O.

Run:
    uv run pytest Tests/test_dispatch_policy.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "eval") not in sys.path:
    sys.path.insert(0, str(REPO / "eval"))

import dispatch_policy as dp                               # noqa: E402

DL5 = datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc)     # Friday
EVENTS = [dict(id=g, deadline_time=(DL5 + timedelta(days=7 * (g - 5))).strftime("%Y-%m-%dT%H:%M:%SZ"),
               finished=g <= 4, data_checked=g <= 4) for g in range(1, 10)]


def at(day, h, m=0):
    return datetime(2026, 9, day, h, m, tzinfo=timezone.utc)


def fresh():
    return dp.empty_state()


def succeed(state, p, hist=4, when=None):
    dp.record_outcome(state, p, True, run_id=99, history_through_gw=hist,
                      finished_at=dp.iso(when or datetime(2026, 9, 16, 11, 1, tzinfo=timezone.utc)))


# ------------------------------------------------------------ gating
def test_nothing_fires_until_the_previous_gameweek_is_ingested():
    p = dp.plan(at(13, 12), EVENTS, fresh(), master_gw=3)        # Sunday, GW4 not ingested
    assert p["action"] is None and "GW4 not yet confirmed and ingested" in p["reason"]
    assert p["expected_next"]["kind"] == "post_ingest" and p["expected_next"]["at"] is None
    assert "GW4 confirmed" in p["expected_next"]["condition"]


def test_post_ingest_fires_once_when_the_master_gains_a_gameweek():
    st = fresh()
    p = dp.plan(at(15, 12, 30), EVENTS, st, master_gw=4)          # Tuesday, GW4 just ingested
    assert p["action"] == "post_ingest" and p["slot"] == "post_ingest:GW4" and p["attempt"] == 1
    succeed(st, p, hist=4, when=at(15, 12, 32))
    p2 = dp.plan(at(15, 12, 40), EVENTS, st, master_gw=4)
    assert p2["action"] is None                                     # same day, before 11:00? no: 12:40 is after
    # 12:40 is after 11:00Z but a post_ingest succeeded 8 minutes ago -> nightly suppressed
    assert "post_ingest run succeeded within" in p2["reason"]


def test_nightly_fires_at_eleven_utc_once_a_day_and_not_before():
    st = fresh()
    st["last_success"] = {"history_through_gw": 4}                  # a post_ingest already knew GW4
    assert dp.plan(at(16, 10, 50), EVENTS, st, master_gw=4)["action"] is None
    p = dp.plan(at(16, 11, 0), EVENTS, st, master_gw=4)
    assert p["action"] == "nightly" and p["slot"] == "nightly:2026-09-16"
    succeed(st, p, when=at(16, 11, 1))
    assert dp.plan(at(16, 11, 10), EVENTS, st, master_gw=4)["action"] is None
    assert dp.plan(at(17, 11, 0), EVENTS, st, master_gw=4)["slot"] == "nightly:2026-09-17"


def test_nightly_needs_the_season_file_to_be_current():
    st = fresh()
    st["last_success"] = {"history_through_gw": 3}
    assert dp.plan(at(16, 11, 0), EVENTS, st, master_gw=3)["action"] is None
    assert dp.plan(at(16, 11, 0), EVENTS, st, master_gw=None)["action"] is None


def test_deadline_day_windows_are_disjoint_and_fire_once_each():
    st = fresh()
    st["last_success"] = {"history_through_gw": 4}
    pn = dp.plan(at(18, 11, 0), EVENTS, st, master_gw=4)
    assert pn["action"] == "nightly"                                 # deadline-day nightly, T-390
    succeed(st, pn, when=at(18, 11, 1))
    for t, kind in ((at(18, 15, 50), None), (at(18, 16, 0), "t90"), (at(18, 16, 10), None),
                    (at(18, 17, 0), "t30"), (at(18, 17, 10), None), (at(18, 17, 20), "t10")):
        p = dp.plan(t, EVENTS, st, master_gw=4)
        if kind is None:
            if p["action"] is not None:
                # 15:50 is T-100: nightly already done today -> nothing
                assert False, (t, p)
        else:
            assert p["action"] == kind, (t, p)
            succeed(st, p, when=t + timedelta(minutes=1))
    assert dp.plan(at(18, 17, 27), EVENTS, st, master_gw=4)["action"] is None    # T-3: below the minimum lead


def test_t10_has_one_attempt_by_recorded_decision():
    assert dp.ATTEMPTS["t10"] == 1
    st = fresh()
    p = dp.plan(at(18, 17, 20), EVENTS, st, master_gw=4)
    assert p["action"] == "t10"
    dp.record_outcome(st, p, False, exit_code=1, finished_at=dp.iso(at(18, 17, 21)))
    assert st["slots"]["t10:GW5"]["status"] == "GAVE_UP"
    assert dp.plan(at(18, 17, 24), EVENTS, st, master_gw=4)["action"] is None


def test_t90_retries_three_times_then_gives_up():
    st = fresh()
    for i in range(3):
        p = dp.plan(at(18, 16, 0) + timedelta(minutes=10 * i), EVENTS, st, master_gw=4)
        assert p["action"] == "t90" and p["attempt"] == i + 1
        dp.record_outcome(st, p, False, exit_code=1)
    assert st["slots"]["t90:GW5"]["status"] == "GAVE_UP"
    assert dp.plan(at(18, 16, 30), EVENTS, st, master_gw=4)["action"] is None
    assert dp.plan(at(18, 17, 0), EVENTS, st, master_gw=4)["action"] == "t30"     # a fresh chance


def test_precedence_is_deadline_over_post_ingest_over_nightly():
    st = fresh()                                                     # nothing known; master through 4
    p = dp.plan(at(18, 16, 0), EVENTS, st, master_gw=4)
    assert p["action"] == "t90"                                      # not post_ingest, though it is due


# --------------------------------------------------------- outcomes / counters
def test_consecutive_nightly_give_ups_count_and_reset():
    st = fresh()
    st["last_success"] = {"history_through_gw": 4}
    for day in (16, 17):
        for i in range(2):
            p = dp.plan(at(day, 11, 10 * i), EVENTS, st, master_gw=4)
            assert p["action"] == "nightly"
            dp.record_outcome(st, p, False, exit_code=1)
    assert st["consecutive_nightly_failures"] == 2
    p = dp.plan(at(18, 11, 0), EVENTS, st, master_gw=4)
    succeed(st, p, when=at(18, 11, 1))
    assert st["consecutive_nightly_failures"] == 0


# ---------------------------------------------------------- expected next
def test_expected_next_between_deadlines_is_the_next_nightly_then_t90():
    st = fresh()
    st["last_success"] = {"history_through_gw": 4}
    e = dp.expected_next(at(16, 12, 0), EVENTS, st, master_gw=4)      # Tuesday noon, nightly not done
    assert e["kind"] == "nightly" and e["slot"] == "nightly:2026-09-16"   # due now (11:00 passed)
    st["slots"]["nightly:2026-09-16"] = {"kind": "nightly", "status": "SUCCESS", "attempts": 1}
    e = dp.expected_next(at(16, 12, 0), EVENTS, st, master_gw=4)
    assert e["slot"] == "nightly:2026-09-17" and e["at"] == "2026-09-17T11:00:00Z"
    for d in (17, 18):
        st["slots"][f"nightly:2026-09-{d}"] = {"kind": "nightly", "status": "SUCCESS", "attempts": 1}
    e = dp.expected_next(at(18, 12, 0), EVENTS, st, master_gw=4)
    assert e["kind"] == "t90" and e["at"] == "2026-09-18T16:00:00Z"


def test_expected_next_on_deadline_day_walks_the_windows():
    st = fresh()
    e = dp.expected_next(at(18, 16, 5), EVENTS, st, master_gw=4)      # inside t90 window, not done
    assert e["kind"] == "t90"
    st["slots"]["t90:GW5"] = {"kind": "t90", "status": "SUCCESS", "attempts": 1}
    e = dp.expected_next(at(18, 16, 5), EVENTS, st, master_gw=4)
    assert e["kind"] == "t30" and e["at"] == "2026-09-18T17:00:00Z"
    st["slots"]["t30:GW5"] = {"kind": "t30", "status": "SUCCESS", "attempts": 1}
    st["slots"]["t10:GW5"] = {"kind": "t10", "status": "GAVE_UP", "attempts": 1}
    e = dp.expected_next(at(18, 17, 25), EVENTS, st, master_gw=4)
    assert e["kind"] == "post_ingest" and e["at"] is None and "GW5 confirmed" in e["condition"]


# ------------------------------------------------------------ /health
def test_a_broken_timed_promise_degrades_and_a_kept_one_does_not():
    st = fresh()
    st["last_tick"] = dp.iso(at(17, 11, 20))
    st["expected_next"] = {"kind": "nightly", "slot": "nightly:2026-09-17", "gw": 5,
                           "at": "2026-09-17T11:00:00Z", "grace_min": 25}
    assert dp.health_reasons(at(17, 11, 20), st, next_gw=5) == []          # inside grace
    r = dp.health_reasons(at(17, 11, 30), st, next_gw=5)
    assert any("promised run nightly:2026-09-17 at 2026-09-17T11:00:00Z did not land (never attempted)" in x for x in r)
    st["slots"]["nightly:2026-09-17"] = {"kind": "nightly", "status": "SUCCESS", "attempts": 1}
    assert dp.health_reasons(at(17, 11, 30), st, next_gw=5) == []


def test_a_dead_dispatcher_leaves_the_promise_standing_and_is_named():
    st = fresh()
    st["last_tick"] = dp.iso(at(17, 9, 0))
    st["expected_next"] = {"kind": "nightly", "slot": "nightly:2026-09-17", "gw": 5,
                           "at": "2026-09-17T11:00:00Z", "grace_min": 25}
    r = dp.health_reasons(at(17, 12, 0), st, next_gw=5)
    assert any("dispatcher has not ticked" in x for x in r) and any("did not land" in x for x in r)


def test_decision_5_one_nightly_failure_is_not_a_reason_two_are():
    st = fresh()
    st["last_tick"] = dp.iso(at(17, 11, 20))
    st["consecutive_nightly_failures"] = 1
    assert dp.health_reasons(at(17, 11, 20), st, next_gw=5) == []
    st["consecutive_nightly_failures"] = 2
    assert any("2 consecutive nightly" in x for x in dp.health_reasons(at(17, 11, 20), st, next_gw=5))


def test_any_deadline_day_give_up_degrades_immediately():
    st = fresh()
    st["last_tick"] = dp.iso(at(18, 17, 22))
    st["slots"]["t10:GW5"] = {"kind": "t10", "gw": 5, "status": "GAVE_UP", "attempts": 1}
    assert any("deadline-day run t10:GW5 FAILED" in x for x in dp.health_reasons(at(18, 17, 22), st, next_gw=5))
    st["slots"]["t10:GW5"]["gw"] = 4                                     # last week's: not a reason now
    assert dp.health_reasons(at(18, 17, 22), st, next_gw=5) == []


# ----------------------------------------------------------- freshness
def test_freshness_string_names_time_knowledge_target_and_promise():
    run = {"run_id": 7, "gw": 5, "kind": "nightly", "finished_at": "2026-09-16T11:03:00+00:00",
           "knowledge": {"duration_s": 44.2, "history_through_gw": 4,
                         "history_ingested_at": "2026-09-15T12:24:00Z",
                         "availability_asof": "2026-09-16T11:00:10Z",
                         "odds_pulled_at": "2026-09-16T11:02:00Z",
                         "deadline_at": "2026-09-18T17:30:00Z"}}
    exp = {"kind": "nightly", "slot": "nightly:2026-09-17", "at": "2026-09-17T11:00:00Z"}
    s = dp.freshness(run, exp)
    assert s.startswith("built Wed 16 Sep 11:03Z (nightly, run 7, 44 s)")
    assert "knows results through GW4 (ingested Tue 15 Sep 12:24Z)" in s
    assert "team news to Wed 16 Sep 11:00Z" in s and "odds pulled Wed 16 Sep 11:02Z" in s
    assert "predicting GW5 (deadline Fri 18 Sep 17:30Z)" in s
    assert s.endswith("next run Thu 17 Sep 11:00Z (nightly)")


def test_freshness_degrades_gracefully_for_a_pre_multi_run_row_and_a_conditional_promise():
    run = {"run_id": 5, "gw": 4, "kind": "deadline", "finished_at": "2026-09-12T11:01:01+00:00", "knowledge": None}
    s = dp.freshness(run, {"kind": "post_ingest", "at": None, "condition": "GW4 confirmed by FPL and ingested"})
    assert "knowledge not recorded" in s and "next run when GW4 confirmed" in s
