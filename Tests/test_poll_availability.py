"""Regression tests for the D6 poller's due gate (eval/poll_availability.py::due).

The GW2 window (2026-08-28) lost a third of its final hour to an off-by-seconds
gate: the stored poll is stamped at the fetch time (~:03 past the tick minute)
while the next tick fires at ~:02, so (now - last) came up ~1 s short of the
cadence, the tick logged "next poll in 0 min" and skipped, and every phase
shifted one slot late. A poll arriving within DUE_TOLERANCE seconds of the
cadence must count as due; one well inside the cadence must not; and no
tolerance may let two consecutive ticks both count as due.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import poll_availability as pa  # noqa: E402

DEADLINE = datetime(2026, 9, 4, 17, 30, tzinfo=timezone.utc)


def _snaps(monkeypatch, stamps):
    monkeypatch.setattr(pa, "list_raw", lambda season: [(t, None) for t in stamps])


@pytest.mark.parametrize("hours_before,cadence", [(3.0, pa.NORMAL_CADENCE), (0.5, pa.FINAL_HOUR_CADENCE)])
def test_tick_one_second_early_is_due(monkeypatch, hours_before, cadence):
    """The GW2 failure: last poll stamped 1 s later than the tick minute."""
    now = DEADLINE - timedelta(hours=hours_before)
    _snaps(monkeypatch, [now - timedelta(seconds=cadence - 1)])
    is_due, why = pa.due("2026-27", DEADLINE, now)
    assert is_due, f"a tick 1 s inside the cadence must be due, got {why!r}"


@pytest.mark.parametrize("hours_before,cadence", [(3.0, pa.NORMAL_CADENCE), (0.5, pa.FINAL_HOUR_CADENCE)])
def test_tick_well_inside_cadence_is_not_due(monkeypatch, hours_before, cadence):
    now = DEADLINE - timedelta(hours=hours_before)
    _snaps(monkeypatch, [now - timedelta(seconds=cadence - 120)])
    is_due, why = pa.due("2026-27", DEADLINE, now)
    assert not is_due, f"a tick 2 min inside the cadence must not be due, got {why!r}"


def test_exact_cadence_is_due(monkeypatch):
    now = DEADLINE - timedelta(hours=3)
    _snaps(monkeypatch, [now - timedelta(seconds=pa.NORMAL_CADENCE)])
    assert pa.due("2026-27", DEADLINE, now)[0]


def test_tolerance_cannot_double_poll():
    """Ticks come every 600 s (scheduler) or 60 s (--watch). A tolerance at or
    above the shortest tick interval would let the tick AFTER a poll count as
    due again; the constant must sit strictly below it."""
    tol = getattr(pa, "DUE_TOLERANCE", 0)
    assert 0 < tol < 60, f"DUE_TOLERANCE must be in (0, 60) s, got {tol}"


def test_consecutive_scheduler_ticks_never_both_due(monkeypatch):
    """Replay a 30-min phase on the 10-min grid with the GW2 jitter (tick at
    :02, poll stamped at :03): exactly one poll per cadence, none doubled."""
    t0 = DEADLINE - timedelta(hours=4)
    last = None
    polls = []
    for k in range(0, 18):                       # 3 hours of 10-min ticks
        tick = t0 + timedelta(minutes=10 * k, seconds=2)
        _snaps(monkeypatch, [last] if last else [])
        if pa.due("2026-27", DEADLINE, tick)[0]:
            last = tick + timedelta(seconds=1)   # fetch latency: stamp 1 s after the tick
            polls.append(tick)
    gaps = [(b - a).total_seconds() for a, b in zip(polls, polls[1:])]
    assert polls and all(g == 1800 for g in gaps), f"30-min phase drifted: gaps {gaps}"
