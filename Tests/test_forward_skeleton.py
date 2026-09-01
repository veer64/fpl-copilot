"""Tests for the forward-gameweek skeleton (eval/build_forward_skeleton.py) and
the decision-time calendar re-pull check (live_deadline)."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import build_forward_skeleton as bfs  # noqa: E402
import live_deadline as ld  # noqa: E402
from season_stack import forward_path  # noqa: E402

FIX = [
    dict(id=101, event=30, kickoff_time="2027-04-01T19:00:00Z", team_h="Alpha", team_a="Beta"),
    dict(id=102, event=30, kickoff_time="2027-04-03T15:00:00Z", team_h="Gamma", team_a="Alpha"),  # Alpha DOUBLE
    dict(id=103, event=None, kickoff_time=None, team_h="Delta", team_a="Beta"),                   # POSTPONED
]
SQUADS = {"Alpha": [dict(element=1, name="A One", position="MID", value=50)],
          "Beta": [dict(element=2, name="B Two", position="DEF", value=45)],
          "Gamma": [dict(element=3, name="G Three", position="FWD", value=60)],
          "Delta": [dict(element=4, name="D Four", position="GK", value=40)]}
OPP = {"Alpha": 1, "Beta": 2, "Gamma": 3, "Delta": 4}


def _schema():
    return bfs._master_schema()


def test_double_two_rows_blank_none_postponed_excluded():
    """The fixtures-first construction claims: a double gives TWO rows with
    distinct fixture ids and real kickoffs; a team with no scheduled fixture
    gives NONE; a postponed fixture is EXCLUDED, never assigned."""
    df, postponed, _ = bfs.skeleton_rows(FIX, SQUADS, _schema(), "2026-27", set(), OPP)
    a = df[df["element"] == 1]
    assert len(a) == 2 and set(a["fixture"].astype(int)) == {101, 102}
    assert a["kickoff_time"].nunique() == 2
    assert df[df["element"] == 4].empty            # Delta's only fixture is postponed -> blank, no rows
    assert postponed == [103] and 103 not in set(df["fixture"].astype(int))
    assert bool(a[a["fixture"] == 101]["was_home"].iloc[0]) is True
    assert bool(a[a["fixture"] == 102]["was_home"].iloc[0]) is False
    assert int(a[a["fixture"] == 102]["opponent_team"].iloc[0]) == OPP["Gamma"]
    # measurement columns are NaN, identity/geometry are real
    assert a["minutes"].isna().all() and a["total_points"].isna().all()
    assert (a["value"] == 50).all() and (a["GW"] == 30).all()


def test_played_fixture_skipped():
    """A fixture the master already carries is never duplicated."""
    df, _, n_known = bfs.skeleton_rows(FIX, SQUADS, _schema(), "2026-27", {101}, OPP)
    assert n_known == 1 and 101 not in set(df["fixture"].astype(int))


def test_backfill_construction_regression():
    """The 2025-26 backfill at GW20 (a January-window cutoff): row-set equality
    up to measured churn, and EXACT team/opponent/was_home/kickoff/position and
    per-(element, GW) fixture-count identity on the intersection."""
    assert bfs.backfill("2025-26", 20) is True


def test_repull_mismatch_raises(monkeypatch):
    """The #14-class decision-time guard: an unchanged calendar notes and
    passes; a moved fixture in a target gameweek raises under strict."""
    fp = forward_path()
    if fp is None or not fp.with_suffix(".provenance.json").exists():
        pytest.skip("no forward skeleton on disk")
    prov = json.loads(fp.with_suffix(".provenance.json").read_text(encoding="utf-8"))
    tg = prov["gws_covered"][:1]
    fresh = [dict(id=int(k), event=v[0], kickoff_time=v[1]) for k, v in prov["calendar"].items()]
    monkeypatch.setattr(ld, "_pull_fixtures", lambda: fresh)
    notes = []
    ld._fixture_calendar_check(notes, True, prov["season"], tg)
    assert any("matches the skeleton snapshot" in n for n in notes)
    moved = [dict(f) for f in fresh]
    for f in moved:
        if f["event"] == tg[0]:
            f["kickoff_time"] = "2099-01-01T12:00:00Z"
            break
    monkeypatch.setattr(ld, "_pull_fixtures", lambda: moved)
    with pytest.raises(ld.LiveStrictError):
        ld._fixture_calendar_check([], True, prov["season"], tg)
