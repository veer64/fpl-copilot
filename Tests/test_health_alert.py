"""
The /health consumer's state machine (eval/health_alert.py, Logs/alerting_design_2026-09-13.md):
two-probe debounce, change detection, recovery, rate limiting, slot outcomes once, ACTION dedupe
per day, the daily heartbeat, unreachable echo -- pure functions on dicts, no network.

Run:
    uv run pytest Tests/test_health_alert.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "eval") not in sys.path:
    sys.path.insert(0, str(REPO / "eval"))

import health_alert as ha                                  # noqa: E402

T0 = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)


def H(status="ok", reasons=(), slots=None, tick="NOTHING-NEW", sha="a851d5d92", run=5):
    return {"status": status, "reasons": list(reasons), "git_sha": sha,
            "last_run": {"run_id": run, "freshness": "built Sat 12 Sep 11:01Z (deadline, run 5)"},
            "data_freshness_by_source": {
                "schedule": {"slots_this_gameweek": slots or {},
                             "expected_next": {"kind": "post_ingest", "at": None, "condition": "GW4 confirmed"}},
                "weekly_ingest": {"last_tick": {"first_line": tick}}}}


def run(seq, state=None, start=T0, step_min=10):
    """Feed a sequence of health docs (None = unreachable) 10 minutes apart; collect events."""
    st = state or ha.empty_state()
    out = []
    for i, h in enumerate(seq):
        ev, st = ha.plan(start + timedelta(minutes=step_min * i), h, st)
        out.append([e["key"] for e in ev])
    return out, st


def test_a_single_degraded_probe_is_not_a_page_two_are():
    ev, st = run([H("degraded", ["dispatcher has not ticked since 03:20Z"]), H("ok")])
    assert ev == [[], []] and st["bad_streak"] == 0
    ev, st = run([H("degraded", ["x"]), H("degraded", ["x"])])
    assert ev == [[], ["degraded"]] and st["degraded_pushed"]


def test_degraded_message_carries_the_reasons_verbatim_and_high_priority():
    st = ha.empty_state()
    _, st = ha.plan(T0, H("degraded", ["weekly ingest cron has not ticked for 16h"]), st)
    ev, st = ha.plan(T0 + timedelta(minutes=10), H("degraded", ["weekly ingest cron has not ticked for 16h"]), st)
    assert len(ev) == 1 and ev[0]["priority"] == 5
    assert "- weekly ingest cron has not ticked for 16h" in ev[0]["message"] and "a851d5d92" in ev[0]["title"]


def test_same_reasons_are_not_repeated_inside_the_rate_limit_but_are_after_it():
    seq = [H("degraded", ["x"])] * 3
    ev, st = run(seq)
    assert ev == [[], ["degraded"], []]
    later = T0 + timedelta(hours=ha.RATE_LIMIT_H, minutes=25)
    ev2, st = ha.plan(later, H("degraded", ["x"]), st)
    assert [e["key"] for e in ev2] == ["still_degraded"] and "so far" in ev2[0]["message"]


def test_changed_reasons_push_once_and_recovery_pushes_with_the_duration():
    ev, st = run([H("degraded", ["x"]), H("degraded", ["x"]), H("degraded", ["x", "y"]), H("degraded", ["x", "y"]), H("ok")])
    assert ev == [[], ["degraded"], ["changed"], [], ["recovered"]]
    assert st["degraded_pushed"] is False and st["degraded_since"] is None
    ev2, st2 = run([H("degraded", ["x"]), H("degraded", ["x"])])
    e, _ = ha.plan(T0 + timedelta(hours=2), H("ok"), st2)
    assert e[0]["key"] == "recovered" and "2h00" in e[0]["message"] and "x" in e[0]["message"]


def test_slot_outcomes_push_once_per_slot_and_final_status():
    slots = {"t90:GW5": {"kind": "t90", "status": "RUNNING", "attempts": 1}}
    ev, st = run([H(slots=slots)])
    assert ev == [[]]
    slots = {"t90:GW5": {"kind": "t90", "status": "SUCCESS", "attempts": 1, "run_id": 5}}
    ev, st = ha.plan(T0, H(slots=slots), st)
    assert [e["key"] for e in ev] == ["slot:t90:GW5"] and ev[0]["priority"] == 3 and "built Sat 12 Sep" in ev[0]["message"]
    ev, st = ha.plan(T0 + timedelta(minutes=10), H(slots=slots), st)
    assert ev == []
    slots["t10:GW5"] = {"kind": "t10", "status": "GAVE_UP", "attempts": 1}
    ev, st = ha.plan(T0 + timedelta(minutes=20), H(slots=slots), st)
    assert [e["key"] for e in ev] == ["slot:t10:GW5"] and ev[0]["priority"] == 5 and "GAVE_UP" in ev[0]["title"]


def test_action_required_is_pushed_once_per_text_per_day():
    tick = "NOTHING-NEW -- ACTION REQUIRED (1 item(s), see below)"
    ev, st = run([H(tick=tick), H(tick=tick)])
    assert ev == [["action"], []]
    e, st = ha.plan(T0 + timedelta(days=1), H(tick=tick), st)
    assert [x["key"] for x in e] == ["action"]
    e, st = ha.plan(T0 + timedelta(days=1, minutes=10), H(tick=tick + " x"), st)
    assert [x["key"] for x in e] == ["action"]


def test_heartbeat_fires_once_a_day_after_eleven_oh_five_utc():
    st = ha.empty_state()
    e, st = ha.plan(T0.replace(hour=11, minute=0), H(), st)
    assert e == []
    e, st = ha.plan(T0.replace(hour=11, minute=10), H(), st)
    assert [x["key"] for x in e] == ["heartbeat"] and e[0]["priority"] == 1 and "built Sat 12 Sep" in e[0]["message"]
    e, st = ha.plan(T0.replace(hour=11, minute=20), H(), st)
    assert e == []
    e, st = ha.plan(T0.replace(hour=11, minute=10) + timedelta(days=1), H(), st)
    assert [x["key"] for x in e] == ["heartbeat"]


def test_unreachable_needs_two_probes_then_echoes_and_reports_return():
    ev, st = run([None, None, None, H()])
    assert ev == [[], ["unreachable"], [], ["reachable"]] and st["unreachable_streak"] == 0


def test_plan_never_mutates_the_input_state():
    st = ha.empty_state()
    before = dict(st)
    ha.plan(T0, H("degraded", ["x"]), st)
    assert st == before


def test_env_file_parsing_and_state_round_trip(tmp_path):
    env = tmp_path / "fpl-alert.env"
    env.write_text("# topic\nNTFY_TOPIC=abc-123\nHEALTH_URL = http://x/health\n", encoding="utf-8")
    cfg = ha.read_env(str(env))
    assert cfg == {"NTFY_TOPIC": "abc-123", "HEALTH_URL": "http://x/health"}
    p = tmp_path / "s" / "state.json"
    st = ha.empty_state(); st["bad_streak"] = 2
    ha.save_state(str(p), st)
    assert ha.load_state(str(p))["bad_streak"] == 2
    assert ha.load_state(str(tmp_path / "missing.json")) == ha.empty_state()


def test_main_dry_run_against_a_stub_health(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ha, "fetch_health", lambda url: H("degraded", ["r1"]))
    s = tmp_path / "state.json"
    assert ha.main(["--dry-run", "--url", "http://stub/health", "--state", str(s), "--env", str(tmp_path / "none.env")]) == 0
    assert not s.exists()                       # dry run writes no state
    out = capsys.readouterr().out
    assert "health=degraded" in out and "(dry-run)" in out


def test_main_refuses_to_run_without_a_topic(tmp_path, capsys):
    rc = ha.main(["--state", str(tmp_path / "s.json"), "--env", str(tmp_path / "none.env"), "--url", "http://127.0.0.1:9/health"])
    assert rc == 2 and "NO NTFY_TOPIC" in capsys.readouterr().out
