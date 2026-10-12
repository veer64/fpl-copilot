"""One source for timing (3b, 2026-10-09): a tool's run metadata and the context block read the same
helper (now_context.next_run), so for a frozen clock they state the same next run, and the deadline-day
run times are exact UTC times computed from the deadline, never by the model.

Frozen clock, seeded deadlines / finished gameweeks / dispatch state; no database, no network.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dispatch_policy as dp                               # noqa: E402
import model_tools as mt                                   # noqa: E402
import now_context as nc                                   # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 8, 18, 42, tzinfo=UTC)
DL = {5: datetime(2026, 9, 18, 17, 30, tzinfo=UTC), 6: datetime(2026, 10, 10, 10, 0, tzinfo=UTC),
      7: datetime(2026, 10, 17, 10, 0, tzinfo=UTC)}
CLUBS = ["Arsenal", "Chelsea"]
RUN = {"run_id": 24, "gw": 6, "finished_at": "2026-09-29 11:01:48+00:00", "kind": "nightly", "slot": "nightly:2026-09-29",
       "git_sha": "abc", "recovered": False, "knowledge": None}


@pytest.fixture
def frozen(monkeypatch):
    state = {}

    def seed(st):
        state.clear()
        state.update(st)
    monkeypatch.setattr(nc, "clock", lambda: NOW)
    monkeypatch.setattr(nc, "_load_deadlines", lambda: dict(DL))
    monkeypatch.setattr(nc, "_load_finished", lambda: [1, 2, 3, 4, 5])
    monkeypatch.setattr(nc, "_load_clubs", lambda: list(CLUBS))
    monkeypatch.setattr(nc, "_load_dispatch_state", lambda: dict(state))
    monkeypatch.setattr(mt, "_dispatch_state", lambda: dict(state))
    return seed


def test_the_deadline_day_runs_are_exact_utc_times_from_the_deadline():
    d = nc.deadline_day_runs(NOW, DL, dp)
    assert d["gw"] == 6 and d["deadline"] == "2026-10-10T10:00:00Z"
    assert (d["t90"], d["t30"], d["t10"]) == ("2026-10-10T08:30:00Z", "2026-10-10T09:30:00Z", "2026-10-10T09:50:00Z")
    assert d["words"] == "Deadline-day runs for GW6: 08:30, 09:30 and 09:50 UTC."
    assert nc.deadline_day_runs(datetime(2027, 7, 1, tzinfo=UTC), DL, dp) is None


def test_tool_metadata_and_the_context_block_agree_on_a_dispatcher_promise(frozen):
    frozen({"expected_next": {"kind": "t90", "slot": "t90:GW6", "gw": 6, "at": "2026-10-10T08:30:00Z", "condition": None, "grace_min": 35}})
    text, _ = nc.build(NOW)
    meta = mt._run_meta(dict(RUN))
    nr = nc.next_run()
    assert meta["next_run_expected"] == nr["expected"] and nr["source"] == "the dispatcher's promise"
    assert f"Next expected update (the dispatcher's promise): {meta['next_run_words']}." in text   # Part C: plain words
    assert meta["next_run_words"] == "the update 90 minutes before the deadline, Saturday 2026-10-10 08:30 UTC"
    assert "next update Sat 10 Oct 08:30Z (90 minutes before the deadline)" in meta["built"] and "not scheduled" not in meta["built"]
    assert meta["deadline_day_runs"]["t90"] == "2026-10-10T08:30:00Z" and "Deadline-day runs for GW6: 08:30, 09:30 and 09:50 UTC." in text


def test_tool_metadata_and_the_context_block_agree_when_the_schedule_derives_the_run(frozen):
    frozen({})                                           # the laptop: no dispatcher record
    text, omitted = nc.build(NOW)
    meta = mt._run_meta(dict(RUN))
    nr = nc.next_run()
    assert nr["source"] == "by the schedule" and meta["next_run_expected"] == nr["expected"]
    assert meta["next_run_words"] == "the nightly update, due now (Thursday 2026-10-08 18:42 UTC)"
    assert f"Next expected update (by the schedule): {meta['next_run_words']}." in text
    assert "next update Thu 08 Oct 18:42Z (nightly)" in meta["built"] and "not scheduled" not in meta["built"]
    assert "next_run" not in omitted


def test_frame_built_carries_the_same_three_fields_with_or_without_a_run(frozen, monkeypatch):
    frozen({})
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    fb = mt._frame_built(6)
    assert fb["built"] is None and fb["next_run_words"] == "the nightly update, due now (Thursday 2026-10-08 18:42 UTC)"
    assert fb["deadline_day_runs"]["t10"] == "2026-10-10T09:50:00Z"
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: dict(RUN))
    fb2 = mt._frame_built(6)
    assert fb2["next_run_words"] == fb["next_run_words"] and fb2["deadline_day_runs"] == fb["deadline_day_runs"] and fb2["run_id"] == 24


def test_a_broken_schedule_never_takes_a_tool_down(frozen, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("volume gone")
    monkeypatch.setattr(nc, "next_run", boom)
    meta = mt._run_meta(dict(RUN))
    assert meta["next_run_expected"] is None and meta["next_run_words"] is None and "next update not scheduled" in meta["built"]


def test_the_prompt_sends_the_model_to_the_tools_for_the_times():
    import agent
    p = agent.SYSTEM_PROMPT
    assert "never compute those times yourself" in p and "`deadline_day_runs`" in p
    assert "for a 17:30 UTC deadline: 16:00, 17:00 and 17:20 UTC" not in p
    assert "Never guess why a club or player is missing (relegation, a transfer, an injury)." in p
