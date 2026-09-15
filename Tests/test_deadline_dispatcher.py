"""
The dispatcher MODULE (eval/deadline_dispatcher.py), not just its policy: the post-build path
that crashed on 2026-09-15 (`import config_roles` after a successful build, the repo root not on
sys.path -- four identical builds, each slot re-fired, /health ok throughout), the reconciliation
of a slot left RUNNING from model_runs, and one whole tick end to end with the network, the season
file, the build and the state file all faked.

Run:
    uv run pytest Tests/test_deadline_dispatcher.py -v
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import deadline_dispatcher as dd                           # noqa: E402
import dispatch_policy as dp                               # noqa: E402

from datetime import datetime, timedelta, timezone                 # noqa: E402

DL5 = datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc)
EVENTS = [dict(id=g, deadline_time=(DL5 + timedelta(days=7 * (g - 5))).strftime("%Y-%m-%dT%H:%M:%SZ"),
               finished=g <= 4, data_checked=g <= 4) for g in range(1, 10)]


def test_config_roles_resolves_at_import_and_run_build_reads_the_sidecar(monkeypatch, tmp_path):
    assert dd.cr.PRODUCTION_CONFIG                            # imported at module load, on the root path
    monkeypatch.setattr(dd, "LIVE", tmp_path)
    side = {"run_id": 12, "config": dd.cr.PRODUCTION_CONFIG, "gw": 5, "kind": "nightly", "slot": "nightly:2026-09-16",
            "knowledge": {"history_through_gw": 4}}
    (tmp_path / f"_tmp_frame_{dd.cr.PRODUCTION_CONFIG}.provenance.json").write_text(json.dumps(side), encoding="utf-8")

    class R:
        returncode = 0
    monkeypatch.setattr(dd.subprocess, "run", lambda *a, **k: R())
    code, got = dd.run_build("2026-27", 5, "nightly", "nightly:2026-09-16", 1)
    assert code == 0 and got["run_id"] == 12 and got["slot"] == "nightly:2026-09-16"


def test_a_slot_left_running_is_settled_from_model_runs():
    st = dp.empty_state()
    st["slots"] = {"post_ingest:GW4": {"kind": "post_ingest", "gw": 5, "status": "RUNNING", "attempts": 2,
                                       "started_at": "2026-09-15T18:40:05Z"},
                   "nightly:2026-09-15": {"kind": "nightly", "gw": 5, "status": "RUNNING", "attempts": 2,
                                          "started_at": "2026-09-15T19:00:04Z"},
                   "t90:GW5": {"kind": "t90", "gw": 5, "status": "RUNNING", "attempts": 1, "started_at": "2026-09-18T16:00:05Z"}}
    rows = [dict(run_id=6, slot="post_ingest:GW4", status="SUCCESS", finished_at="2026-09-15T18:31:26+00:00",
                 knowledge=json.dumps({"history_through_gw": 4})),
            dict(run_id=7, slot="post_ingest:GW4", status="SUCCESS", finished_at="2026-09-15T18:41:22+00:00",
                 knowledge={"history_through_gw": 4}),
            dict(run_id=9, slot="nightly:2026-09-15", status="SUCCESS", finished_at="2026-09-15T19:01:25+00:00",
                 knowledge={"history_through_gw": 4}),
            dict(run_id=10, slot="t90:GW5", status="FAILED", finished_at="2026-09-18T16:02:00+00:00", knowledge=None)]
    settled = dd.reconcile_from_db(st, rows=rows)
    assert st["slots"]["post_ingest:GW4"]["status"] == "SUCCESS" and st["slots"]["post_ingest:GW4"]["run_id"] == 7
    assert st["slots"]["nightly:2026-09-15"]["status"] == "SUCCESS" and st["slots"]["nightly:2026-09-15"]["run_id"] == 9
    assert st["slots"]["t90:GW5"]["status"] == "FAILED"
    assert st["last_success"]["run_id"] == 9 and st["last_success"]["history_through_gw"] == 4
    assert len(settled) == 3
    # nothing RUNNING -> nothing read, nothing changed
    assert dd.reconcile_from_db(st, rows=[]) == []
    # with the slots settled, the policy no longer re-fires them
    p = dp.plan(dp.parse_iso("2026-09-15T21:20:00Z"), EVENTS, st, master_gw=4)
    assert p["action"] is None and "already SUCCESS" in p["reason"]


def test_one_tick_end_to_end_records_the_outcome_and_the_next_promise(monkeypatch, tmp_path):
    monkeypatch.setattr(dd, "LIVE", tmp_path)
    monkeypatch.setattr(dd, "STATE", tmp_path / "dispatch_state.json")
    monkeypatch.setattr(dd, "master_max_gw", lambda season: 4)
    monkeypatch.setattr(dd, "reconcile_from_db", lambda state, rows=None: [])

    class Resp:
        def json(self):
            return {"events": EVENTS}
    monkeypatch.setattr(dd.requests, "get", lambda *a, **k: Resp())
    side = {"run_id": 12, "config": dd.cr.PRODUCTION_CONFIG, "gw": 5, "kind": "post_ingest", "slot": "post_ingest:GW4",
            "knowledge": {"history_through_gw": 4}}
    monkeypatch.setattr(dd, "run_build", lambda *a, **k: (0, side))
    dd.main(["--season", "2026-27", "--now", "2026-09-15T18:30:00Z"])
    st = json.loads((tmp_path / "dispatch_state.json").read_text(encoding="utf-8"))
    s = st["slots"]["post_ingest:GW4"]
    assert s["status"] == "SUCCESS" and s["run_id"] == 12 and s["history_through_gw"] == 4
    assert st["last_success"]["history_through_gw"] == 4
    assert st["expected_next"]["kind"] in ("nightly", "t90")
    # a second tick ten minutes later does NOT re-fire the slot
    calls = []
    monkeypatch.setattr(dd, "run_build", lambda *a, **k: calls.append(a) or (0, side))
    dd.main(["--season", "2026-27", "--now", "2026-09-15T18:40:00Z"])
    assert calls == []


def test_a_slot_running_too_long_degrades_health():
    st = dp.empty_state()
    st["last_tick"] = "2026-09-15T21:10:03Z"
    st["slots"] = {"nightly:2026-09-15": {"kind": "nightly", "gw": 5, "status": "RUNNING", "attempts": 2,
                                          "started_at": "2026-09-15T19:00:04Z"}}
    r = dp.health_reasons(dp.parse_iso("2026-09-15T21:12:00Z"), st, next_gw=5)
    assert any("has been RUNNING for 131 min" in x and "died after or during its build" in x for x in r)
    assert dp.health_reasons(dp.parse_iso("2026-09-15T19:30:00Z"), st, next_gw=5) == []      # a build in progress
