"""Prompt S1 (12 Nov 2026): /health's "weekly ingest needs a human" reason follows the NEWER of INGEST_STATUS.txt and
INGEST_TICK.txt, by the time each file says it was written (its header line, else its mtime). Until S1 it fired on either
file, so an item fixed by hand (U1's crosswalk pins) kept /health degraded until the next run with work rewrote the status
file, although every 6-hourly tick since already said the item was gone. Everything else is unchanged: a FAILED last run
still degrades whatever the tick says, the tick's age still decides "has not ticked", the understat fallback stays
informational."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import model_tools  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc)
STATUS_AR = "SUCCESS -- ACTION REQUIRED (1 item, see below) -- DEGRADED (understat fallback for GW[10])"
TICK_AR = "NOTHING-NEW -- ACTION REQUIRED (1 item(s), see below)"


def _write(live, name, first, written, mtime=None, header=True):
    body = first + "\n"
    if header:
        body += f"weekly ingest 2026-27 -- written {written:%Y-%m-%d %H:%M:%S}Z -- git e704d1893 -- data /app/data\n"
    body += "\n== ... ==\n"
    p = live / name
    p.write_text(body, encoding="utf-8")
    ts = (mtime or written).timestamp()
    os.utime(p, (ts, ts))
    return p


def _dirs(tmp_path):
    live, hist = tmp_path / "live", tmp_path / "history"
    live.mkdir()
    hist.mkdir()
    return live, hist


def _run(tmp_path):
    reasons = []
    out = model_tools._weekly_ingest_status(reasons, live=tmp_path / "live", history=tmp_path / "history", now=NOW)
    return reasons, out


def _human(reasons):
    return [r for r in reasons if r.startswith("weekly ingest needs a human")]


def test_a_newer_clean_tick_clears_an_older_status_item(tmp_path):
    """Today's production case: the GW10 status (9 Nov) still carries the item, the 12 Nov tick does not."""
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_STATUS.txt", STATUS_AR, datetime(2026, 11, 9, 18, 23, 23, tzinfo=timezone.utc))
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 12, 15, 12, 35, tzinfo=timezone.utc))
    reasons, out = _run(tmp_path)
    assert _human(reasons) == []
    assert reasons == []
    assert out["action_source"] == "last_tick"


def test_a_newer_status_item_still_degrades_over_an_older_clean_tick(tmp_path):
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 12, 12, 17, 8, tzinfo=timezone.utc))
    _write(live, "INGEST_STATUS.txt", STATUS_AR, datetime(2026, 11, 12, 12, 30, 0, tzinfo=timezone.utc))
    reasons, out = _run(tmp_path)
    assert _human(reasons) == ["weekly ingest needs a human: " + STATUS_AR + " (data/live/INGEST_STATUS.txt)"]
    assert out["action_source"] == "last_run"


def test_a_newer_tick_item_degrades_and_is_quoted(tmp_path):
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_STATUS.txt", "SUCCESS", datetime(2026, 11, 9, 18, 23, 23, tzinfo=timezone.utc))
    _write(live, "INGEST_TICK.txt", TICK_AR, datetime(2026, 11, 12, 12, 17, 8, tzinfo=timezone.utc))
    reasons, _ = _run(tmp_path)
    assert _human(reasons) == ["weekly ingest needs a human: " + TICK_AR + " (data/live/INGEST_TICK.txt)"]


def test_the_header_time_wins_over_the_file_mtime(tmp_path):
    """A copied or restored file keeps its header; the header is what 'written' means."""
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_STATUS.txt", STATUS_AR, datetime(2026, 11, 9, 18, 23, 23, tzinfo=timezone.utc),
           mtime=datetime(2026, 11, 12, 15, 25, tzinfo=timezone.utc))        # touched later (a copy), written earlier
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 12, 15, 12, 35, tzinfo=timezone.utc))
    reasons, out = _run(tmp_path)
    assert _human(reasons) == []
    assert out["last_run"]["written"] == "2026-11-09T18:23:23Z"
    assert out["last_tick"]["written"] == "2026-11-12T15:12:35Z"


def test_without_a_header_the_mtime_decides(tmp_path):
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_STATUS.txt", STATUS_AR, datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc), header=False)
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 12, 12, 17, tzinfo=timezone.utc), header=False)
    reasons, out = _run(tmp_path)
    assert len(_human(reasons)) == 1 and out["action_source"] == "last_run"


def test_only_one_file_present_still_reports_its_item(tmp_path):
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_STATUS.txt", STATUS_AR, datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc))
    reasons, _ = _run(tmp_path)
    assert len(_human(reasons)) == 1
    assert "weekly ingest has never ticked on this volume (cron not installed?)" in reasons


def test_a_failed_run_still_degrades_whatever_the_tick_says(tmp_path):
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_STATUS.txt", "FAILED", datetime(2026, 11, 12, 12, 20, tzinfo=timezone.utc))
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 12, 15, 12, tzinfo=timezone.utc))
    reasons, _ = _run(tmp_path)
    assert any(r.startswith("weekly ingest FAILED") for r in reasons)


def test_a_stale_tick_is_still_a_reason(tmp_path):
    live, _ = _dirs(tmp_path)
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc))
    reasons, out = _run(tmp_path)
    assert out["last_tick"]["age_hours"] == 19.5
    assert any("has not ticked for 20h" in r for r in reasons)


def test_the_understat_fallback_stays_informational(tmp_path):
    live, hist = _dirs(tmp_path)
    _write(live, "INGEST_TICK.txt", "NOTHING-NEW", datetime(2026, 11, 12, 15, 12, tzinfo=timezone.utc))
    (hist / "understat_matches_2026_27.fallback.json").write_text('{"gws": [9, 10]}', encoding="utf-8")
    reasons, out = _run(tmp_path)
    assert reasons == []
    assert out["understat_fallback_gws"] == [9, 10]


def test_the_default_paths_are_the_repo_volume():
    """Called the old way (one argument) it reads REPO/data/live and REPO/data/history, as /health does."""
    reasons = []
    out = model_tools._weekly_ingest_status(reasons)
    assert set(out) >= {"last_run", "last_tick", "understat_fallback_gws", "action_source"}
