"""
explain_prediction(run_id=...) and compare_runs: the stored-terms path (Logs/model_predictions_terms_log.md
section 1's "what it enables"). The database is stubbed through model_tools._q; the rows are the
frame-shaped synthetic rows of test_explain_prediction so a breakdown from the database equals the
breakdown from the frame, term for term. Runs before the term columns (NULL terms) answer with an error.

Run:
    uv run pytest Tests/test_explain_runs.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import explain                                             # noqa: E402
import model_tools as mt                                   # noqa: E402
from test_explain_prediction import _row                   # noqa: E402

STAMP = {"baseline": {"bonus_mode": "delete", "penalty_fix_active": False, "fixture_scale_gamma": 1.0,
                      "topend_cal_active": False, "odds_horizon_gws": 0}}
RUNS = {7: {"run_id": 7, "gw": 5, "status": "SUCCESS", "finished_at": "2026-09-15 11:03:00+00:00", "kind": "post_ingest",
            "slot": "post_ingest:GW4", "git_sha": "abc", "recovered": False, "model_stamp": STAMP, "knowledge": None},
        9: {"run_id": 9, "gw": 5, "status": "SUCCESS", "finished_at": "2026-09-18 16:02:00+00:00", "kind": "t90",
            "slot": "t90:GW5", "git_sha": "abc", "recovered": False, "model_stamp": STAMP, "knowledge": None},
        5: {"run_id": 5, "gw": 4, "status": "SUCCESS", "finished_at": "2026-09-12 11:01:01+00:00", "kind": "deadline",
            "slot": None, "git_sha": "old", "recovered": False, "model_stamp": STAMP, "knowledge": None},
        8: {"run_id": 8, "gw": 5, "status": "FAILED", "finished_at": "2026-09-16 11:03:00+00:00", "kind": "nightly",
            "slot": "nightly:2026-09-16", "git_sha": "abc", "recovered": False, "model_stamp": None, "knowledge": None}}


def _db_rows(frame_rows, run_id, null_terms=False):
    """model_predictions rows joined to players_live, as the query returns them."""
    out = []
    for r in frame_rows:
        d = {}
        for c in ["e_points", "e_points_core", "exp_bonus", "e_minutes", "p_start", "p_60plus", "p_play_any",
                  "e_goals", "e_assists", "p_cs", "pts_appear", "pts_goals", "pts_assists", "pts_cs", "pts_dc",
                  "pts_saves", "pts_conceded", "pts_cards", "e_pen_goals", "penalty_share", "team_pen_rate", "p60",
                  "minutes_frac", "p_dc_hit", "team_lambda", "opp_lambda", "fixture_scale_cal", "npxg90", "xa90",
                  "saves_per_90", "yellow_per_90", "red_per_90"]:
            v = r[c]
            d[c] = None if (null_terms and c.startswith("pts_")) or v != v else float(v)
        d.update(run_id=run_id, config="baseline", element=int(r["element"]), gw=int(r["gw"]), cutoff=int(r["cutoff"]),
                 horizon_step=int(r["horizon_step"]), understat_id=(None if r["understat_id"] != r["understat_id"] else str(int(r["understat_id"]))),
                 n_fixtures=int(r["n_fixtures"]), name=r["name"], position=r["position"], team=r["team"])
        out.append(d)
    return out


@pytest.fixture
def db(monkeypatch):
    """A fake database: run 7 and run 9 hold GW5 rows for two players (run 9 with a lower fixture
    scale for Haaland); run 5 has NULL terms; run 8 FAILED."""
    teams = [f"T{i}" for i in range(20)]
    base7 = [_row(element=411, name="Erling Haaland", team="Man City", gw=5, cutoff=4, horizon_step=1, npxg90=0.79, team_lambda=1.6, opp_lambda=1.2)] + \
            [_row(element=1000 + i, name=f"P{i}", team=t, gw=5, cutoff=4, horizon_step=1, team_lambda=0.7 + 0.08 * i, opp_lambda=2.2 - 0.06 * i) for i, t in enumerate(teams) if i > 0]
    base9 = [_row(element=411, name="Erling Haaland", team="Man City", gw=5, cutoff=5, horizon_step=0, npxg90=0.79, team_lambda=1.2, opp_lambda=1.4, p_start=0.80)] + \
            [_row(element=1000 + i, name=f"P{i}", team=t, gw=5, cutoff=5, horizon_step=0, team_lambda=0.7 + 0.08 * i, opp_lambda=2.2 - 0.06 * i) for i, t in enumerate(teams) if i > 0]
    rows = {7: _db_rows(base7, 7), 9: _db_rows(base9, 9), 5: _db_rows(base7, 5, null_terms=True)}

    def fake_q(sql, params=()):
        if "FROM model_runs" in sql:
            r = RUNS.get(int(params[0]))
            return [dict(r)] if r else []
        if "FROM model_predictions" in sql:
            run_id, config, gw = int(params[0]), params[1], int(params[2])
            return [dict(x) for x in rows.get(run_id, []) if x["gw"] == gw]
        raise AssertionError(sql)
    monkeypatch.setattr(mt, "_q", fake_q)
    monkeypatch.setattr(mt, "_dispatch_state", lambda: {})
    monkeypatch.setattr(mt, "_freshness", lambda run: f"built run {run['run_id']} ({run['kind']})")
    return base7, base9


def test_breakdown_from_the_database_equals_the_breakdown_from_the_frame(db):
    base7, _ = db
    r = mt.explain_prediction(411, gw=5, run_id=7)
    assert "error" not in r, r
    frame_bd = explain.breakdown(base7[0], pd.DataFrame(base7))
    for k in ("total_e_points", "summary", "reconciles", "lines", "fixture"):
        assert r[k] == frame_bd[k], k
    assert r["run_id"] == 7 and r["stale_by_gameweeks"] == 1 and r["predictions_as_of_cutoff_gw"] == 4
    assert r["built"] == "built run 7 (post_ingest)" and r["source"].startswith("database")
    assert r["name"] == "Erling Haaland" and r["position"] == "FWD" and r["team"] == "Man City"


def test_a_run_without_recorded_terms_answers_with_an_error_not_a_breakdown(db):
    r = mt.explain_prediction(411, gw=5, run_id=5)
    assert "error" in r and "no recorded terms" in r["error"] and "never backfilled" in r["error"]


def test_unknown_run_failed_run_missing_gw_and_missing_player(db):
    assert "no run 99" in mt.explain_prediction(411, gw=5, run_id=99)["error"]
    assert "FAILED" in mt.explain_prediction(411, gw=5, run_id=8)["error"]
    assert "outside its six-week horizon" in mt.explain_prediction(411, gw=12, run_id=7)["error"]
    assert "no row for player 424242" in mt.explain_prediction(424242, gw=5, run_id=7)["error"]
    assert "gw is required" in mt.explain_prediction(411, run_id=7)["error"]


def test_compare_runs_ranks_the_move_labels_the_sides_and_carries_what_each_run_knew(db):
    c = mt.compare_runs(411, 5, 7, 9)
    assert "error" not in c, c
    assert c["name"] == "Erling Haaland" and c["run_a"]["run_id"] == 7 and c["run_b"]["run_id"] == 9
    assert c["run_a"]["built"] == "built run 7 (post_ingest)" and c["run_b"]["built"] == "built run 9 (t90)"
    assert c["run_a"]["predictions_as_of_cutoff_gw"] == 4 and c["run_b"]["predictions_as_of_cutoff_gw"] == 5
    assert c["gap"] == pytest.approx(c["run_a"]["total_e_points"] - c["run_b"]["total_e_points"], abs=1e-4)
    assert c["terms"][0]["term"] in ("goals", "appearance") and c["sentence"].startswith("run 7")
    assert "run 7" in c["rendered"].splitlines()[0] and "run 9" in c["rendered"].splitlines()[0]
    assert c["gap"] > 0                    # run 9 saw a lower start probability and a weaker fixture
    e = mt.compare_runs(411, 5, 5, 9)
    assert "error" in e and "no recorded terms" in e["error"]
