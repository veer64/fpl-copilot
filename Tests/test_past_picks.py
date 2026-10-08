"""The four features of 2026-10-08: past picks on get_picks (4a), get_prediction_history (4b),
get_wildcard_gap (4c) and get_fixtures' season summary of doubles and blanks (4d).

4a: get_picks with a played gameweek used to be told "already played" and sent elsewhere; now it
answers with the stored fifteen of the last run before that deadline and scores it through the
one scorer (scoring.score_gameweek on the stored actuals). 4b: one query over the stored runs,
oldest to newest, so "what changed overnight" never needs a run id. 4c: the same decayed-horizon
MIP propose_transfers runs, with its wildcard relief, against the current squad's best XI each
gameweek. 4d: the calendar already held every double and blank; the tool now says so for a club.

Pure except 4c, which runs one real small MIP on a synthetic horizon frame (~2 s). The IO helpers
are monkeypatched; nothing reads the database, the volume or the network.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402

UTC = timezone.utc


# ---------------------------------------------------------------- 4a
T = datetime(2026, 9, 4, 19, 47, tzinfo=UTC)
RUNS = {3: {"run_id": 3, "gw": 3, "season": "2026-27", "kind": "deadline", "slot": None, "status": "SUCCESS",
            "finished_at": T, "recovered": True, "git_sha": "abc", "knowledge": None},
        24: {"run_id": 24, "gw": 6, "season": "2026-27", "kind": "nightly", "slot": "nightly:2026-09-29", "status": "SUCCESS",
             "finished_at": datetime(2026, 9, 29, 11, 1, tzinfo=UTC), "recovered": False, "git_sha": "abc", "knowledge": None}}

# the stored fifteen of run 3 (document bench order 1..4; the bench GK is 1)
PICKS = ([{"player_id": 1, "name": "GK A", "position": "GK", "team": "A", "role": "start", "bench_order": None, "price_tenths": 45, "e_points": 3.0},
          {"player_id": 2, "name": "GK B", "position": "GK", "team": "B", "role": "bench", "bench_order": 1, "price_tenths": 40, "e_points": 1.0}]
         + [{"player_id": 10 + i, "name": f"DEF {i}", "position": "DEF", "team": f"C{i}", "role": "start" if i < 4 else "bench",
             "bench_order": None if i < 4 else 2, "price_tenths": 45, "e_points": 2.5} for i in range(5)]
         + [{"player_id": 20 + i, "name": f"MID {i}", "position": "MID", "team": f"D{i}", "role": ("CAPTAIN" if i == 0 else "VICE" if i == 1 else "start" if i < 4 else "bench"),
             "bench_order": None if i < 4 else 3, "price_tenths": 60, "e_points": 5.0 - i} for i in range(5)]
         + [{"player_id": 30 + i, "name": f"FWD {i}", "position": "FWD", "team": f"E{i}", "role": "start" if i < 2 else "bench",
             "bench_order": None if i < 2 else 4, "price_tenths": 70, "e_points": 4.0} for i in range(3)])


def master(gw, points, minutes):
    rows = [{"element": e, "GW": gw, "fixture": 1, "minutes": minutes.get(e, 90), "total_points": p} for e, p in points.items()]
    return pd.DataFrame(rows)


@pytest.fixture
def past_db(monkeypatch):
    def latest_run(gw=None, any_status=False):
        if gw is None:
            return dict(RUNS[24])
        return dict(RUNS[gw]) if gw in RUNS else None

    def fake_q(sql, params=None):
        if "FROM model_picks" in sql:
            return [dict(r) for r in PICKS] if params[0] == 3 else []
        if "min(gw)" in sql:
            return [{"gw": 3}]
        raise AssertionError(sql)
    monkeypatch.setattr(mt, "_latest_run", latest_run)
    monkeypatch.setattr(mt, "_q", fake_q)
    monkeypatch.setattr(mt, "_dispatch_state", lambda: {})
    monkeypatch.setattr(mt, "_freshness", lambda run: f"built run {run['run_id']} ({run['kind']})")
    # GW3 actuals: the captain (20) blanked with 0 minutes, so the vice (21) is doubled; DEF 3 (13) did not
    # play and the first outfield bench player (14, bench 2) comes on
    pts = {1: 2, 2: 6, 10: 6, 11: 1, 12: 2, 13: 0, 14: 8, 20: 0, 21: 9, 22: 2, 23: 3, 24: 1, 30: 2, 31: 7, 32: 4}
    mins = {13: 0, 20: 0}
    m = master(3, pts, mins)
    monkeypatch.setattr(mt, "_actuals_master", lambda: (m, {3: {"finished": True, "data_checked": True, "pulled_at": "2026-09-07T00:00:00Z"}}))
    return m


def test_a_played_gameweek_returns_the_stored_picks_of_the_run_before_its_deadline_scored(past_db):
    out = mt.get_picks(gw=3)
    assert "error" not in out, out
    assert out["past"] is True and out["stored"] is True and out["gw"] == 3 and out["run_id"] == 3
    assert "PAST picks" in out["note"] and "GW3" in out["note"]
    assert out["captain"] == "MID 0" and out["vice"] == "MID 1"
    assert len(out["xi"]) == 11 and len(out["bench_in_order"]) == 4
    a = out["actual"]
    # two autosubs (13 out, 14 in; the 0-minute captain 20 out, 24 in): 2+6+1+2+8+9+2+3+1+2+7 = 43;
    # the captain did not play so the vice's 9 is doubled -> 52, no hit (a free-pick squad makes no transfer)
    assert a["points_raw"] == 43 + 9 and a["points"] == 52 and a["hit"] == 0
    assert a["doubled"] == 21 and a["doubled_role"] == "vice"
    assert sorted(a["subs_made"]) == [[13, 14], [20, 24]] and sorted(a["final_xi"]) == [1, 10, 11, 12, 14, 21, 22, 23, 24, 30, 31]
    assert a["autosubs_applied"] is True and a["provisional"] is False
    assert next(r for r in out["xi"] if r["player_id"] == 21)["actual_points"] == 9
    assert next(r for r in out["xi"] if r["player_id"] == 13)["minutes"] == 0


def test_a_played_gameweek_no_run_covered_names_the_first_gameweek_with_one(past_db):
    out = mt.get_picks(gw=2)
    assert out["error_kind"] == "no_run_for_gw" and out["first_gw_with_a_run"] == 3
    assert "GW2" in out["error"] and "GW3" in out["error"]


def test_a_played_gameweek_not_yet_in_the_actuals_is_returned_unscored(past_db, monkeypatch):
    monkeypatch.setattr(mt, "_actuals_master", lambda: (master(2, {1: 1}, {}), {}))
    out = mt.get_picks(gw=3)
    assert out["past"] is True and out["actual"] is None and "cannot be scored" in out["actual_note"]


def test_the_default_and_in_horizon_answers_do_not_go_through_the_past_branch(past_db, monkeypatch):
    seen = []
    monkeypatch.setattr(mt, "_past_picks", lambda gw, shadow=False: seen.append(gw) or {"past": True})
    monkeypatch.setattr(mt, "_run_horizon", lambda run: (6, 11))
    monkeypatch.setattr(mt, "optimise", lambda **kw: {"error": "not solved here"})
    mt.get_picks()                                   # default: the stored solve path (fake_q has no picks for 24 -> empty)
    mt.get_picks(gw=9)                               # inside the horizon: computed through optimise
    assert seen == []
    assert mt.get_picks(gw=0)["error_kind"] == "invalid_gw"
    mt.get_picks(gw=3)
    assert seen == [3]


