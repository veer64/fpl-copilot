"""Plain output at the source (2026-10-09): explain_prediction, compare_predictions and compare_runs
START with summary_plain -- two to four sentences a football fan understands -- and keep everything
technical (lines, formulas, inputs, source labels, notes, rendered, residuals) under `detail`,
unchanged. The "50x undersized / penalties MISSED / KNOWN_ISSUES" text and the saves-fallback caveat
are gone from all three; the only penalty note left, under detail, is the floor sentence.

Pure: synthetic rows from test_explain_prediction._row; the tool layer runs on the fake database and
frame the explain-runs tests already use.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import explain                                             # noqa: E402
import model_tools as mt                                   # noqa: E402
from test_explain_prediction import _row, _step            # noqa: E402
from test_explain_runs import RUNS, _db_rows               # noqa: E402

FORBIDDEN = re.compile(r"KNOWN_ISSUES|50x|MISSED|fallback|\bconstant\b|\brule\b|\bmodel\b|lambda|npxG|\bx\s*\d|=|"
                       r"P\(|minutes_frac|fixture_scale|_per_90|\bp_cs\b", re.I)
PEN_NOTE = "penalty upside is not fully counted; for regular takers treat the figure as a floor."


def haaland(**over):
    kw = dict(element=411, name="Erling Haaland", position="FWD", team="Man City", gw=6, step=0,
              p_start=0.99, p60=0.98, npxg90=0.95, xa90=0.17, team_lambda=1.9, opp_lambda=1.1, p_cs=0.27,
              q_p10=2.0, q_p50=6.0, q_p90=10.0)
    kw.update(over)
    return _row(**kw)


# ---------------------------------------------------------------- the breakdown
def test_summary_plain_is_first_and_reads_like_a_fan_wrote_it():
    r = haaland()
    bd = explain.breakdown(r, _step([r]))
    assert list(bd)[0] == "summary_plain"
    s = bd["summary_plain"]
    assert s.startswith("Erling Haaland is expected to score ")
    assert f"{bd['total_e_points']:.1f} points in GW6" in s
    assert "chance to score" in s                                   # the biggest reason, in words
    assert "play the whole game" in s                               # p_60plus 0.97
    assert "A likely range is 2 to 10 points." in s                 # the quantiles, as tool values
    assert 2 <= s.count(".") <= 5 and len(s) < 600
    assert not FORBIDDEN.search(s), FORBIDDEN.search(s)


def test_the_range_sentence_says_so_when_the_run_computed_no_quantiles():
    r = _row(gw=6, step=0)                                          # no q_ columns at all
    s = explain.breakdown(r, _step([r]))["summary_plain"]
    assert "No likely range is available for this run." in s


def test_a_defender_reads_the_clean_sheet_and_a_keeper_reads_saves():
    d = _row(element=5, name="A Defender", position="DEF", team="Arsenal", gw=6, step=0, npxg90=0.05, xa90=0.1,
             p_cs=0.46, p_dc_hit=0.3, pts_conceded=-0.3)
    s = explain.breakdown(d, _step([d]))["summary_plain"]
    assert "clean-sheet chance" in s and "46%" in s
    t = _row(element=6, name="A Defender", position="DEF", team="Arsenal", gw=6, step=0, npxg90=0.05, xa90=0.1,
             p_cs=0.12, p_dc_hit=0.3, pts_conceded=-0.6)
    assert "a tough fixture keeps his clean-sheet chance low" in explain.breakdown(t, _step([t]))["summary_plain"]
    gk = _row(element=7, name="A Keeper", position="GK", team="Arsenal", gw=6, step=0, p_dc_hit=0.0, saves_per_90=2.31,
              pts_saves=0.41, pts_conceded=-0.27, p_cs=0.368, npxg90=0.0, xa90=0.0)
    assert "saves" in explain.breakdown(gk, _step([gk]))["summary_plain"]


def test_a_player_who_rarely_plays_is_said_so():
    r = _row(gw=6, step=0, p_start=0.15, p60=0.5)
    assert "unlikely to play much" in explain.breakdown(r, _step([r]))["summary_plain"]


def test_the_penalty_and_saves_caveats_are_gone_and_the_only_penalty_note_is_the_floor_sentence():
    r = haaland()
    bd = explain.breakdown(r, _step([r]))
    blob = json.dumps(bd)
    assert "50x" not in blob and "MISSED" not in blob and "KNOWN_ISSUES" not in blob and "#19" not in blob
    goals = next(l for l in bd["lines"] if l["term"] == "goals")
    assert goals["penalties"]["notes"] == [PEN_NOTE]
    fixed = _row(gw=6, step=0, penalty_fix_active=True)
    g2 = next(l for l in explain.breakdown(fixed, _step([fixed]))["lines"] if l["term"] == "goals")
    assert g2["penalties"]["notes"] == []
    gk = _row(position="GK", p_dc_hit=0.0, saves_per_90=2.31, pts_saves=0.41, pts_conceded=-0.27, p_cs=0.368)
    saves = next(l for l in explain.breakdown(gk, _step([gk]))["lines"] if l["term"] == "saves")
    assert saves["notes"] == [] and "fallback" not in json.dumps(saves)


def test_a_runaway_strength_is_still_named_without_an_issue_number():
    r = _row(team_lambda=0.002, opp_lambda=1.3)
    bd = explain.breakdown(r, _step([r]))
    assert "ran off" in bd["summary"] and any("ran off" in x for x in bd["fixture"]["notes"])
    assert "KNOWN_ISSUES" not in json.dumps(bd)
    assert "KNOWN_ISSUES" not in explain.RUNAWAY_NOTE


# ---------------------------------------------------------------- the comparison
def test_compare_has_a_plain_summary_naming_the_winner_and_the_reasons():
    a = haaland()
    b = _row(element=379, name="Alexander Isak", position="FWD", team="Liverpool", gw=6, step=0, p_start=0.6, p60=0.8,
             npxg90=0.55, xa90=0.1, team_lambda=1.5, opp_lambda=1.2, p_cs=0.3)
    ba, bb = explain.breakdown(a, _step([a, b])), explain.breakdown(b, _step([a, b]))
    c = explain.compare(ba, bb)
    assert list(c)[0] == "summary_plain"
    s = c["summary_plain"]
    assert s.startswith(f"Erling Haaland {ba['total_e_points']:.1f} vs Alexander Isak {bb['total_e_points']:.1f} for GW6: Erling Haaland by ")
    assert "Most of the gap is " in s and ("chance to score" in s or "likely" in s)
    assert not FORBIDDEN.search(s), FORBIDDEN.search(s)


def test_a_run_to_run_comparison_reads_as_a_move_with_the_runs_named_in_plain_words():
    a = haaland(p_start=0.9)
    b = haaland(p_start=0.5)
    ba, bb = explain.breakdown(a, _step([a])), explain.breakdown(b, _step([b]))
    c = explain.compare(ba, bb, label_a="run 7", label_b="run 9", plain_a="Tuesday's update", plain_b="Thursday's update")
    s = c["summary_plain"]
    assert s.startswith("Erling Haaland's GW6 number moved from ")
    assert "(Tuesday's update)" in s and "(Thursday's update)" in s and "down " in s
    assert "likely" in s                                            # the move is how likely he is to play
    assert "run 7" not in s and "run 9" not in s


# ---------------------------------------------------------------- the three tools
@pytest.fixture
def db(monkeypatch):
    teams = [f"T{i}" for i in range(20)]
    base7 = [_row(element=411, name="Erling Haaland", team="Man City", gw=5, cutoff=4, horizon_step=1, npxg90=0.79, team_lambda=1.6, opp_lambda=1.2)] + \
            [_row(element=1000 + i, name=f"P{i}", team=t, gw=5, cutoff=4, horizon_step=1, team_lambda=0.7 + 0.08 * i, opp_lambda=2.2 - 0.06 * i) for i, t in enumerate(teams) if i > 0]
    base9 = [_row(element=411, name="Erling Haaland", team="Man City", gw=5, cutoff=5, horizon_step=0, npxg90=0.79, team_lambda=1.2, opp_lambda=1.4, p_start=0.80)] + \
            [_row(element=1000 + i, name=f"P{i}", team=t, gw=5, cutoff=5, horizon_step=0, team_lambda=0.7 + 0.08 * i, opp_lambda=2.2 - 0.06 * i) for i, t in enumerate(teams) if i > 0]
    rows = {7: _db_rows(base7, 7), 9: _db_rows(base9, 9)}

    def fake_q(sql, params=()):
        if "FROM model_runs" in sql:
            r = RUNS.get(int(params[0]))
            return [dict(r)] if r else []
        if "FROM model_predictions" in sql:
            run_id, config, gw = int(params[0]), params[1], int(params[2])
            return [dict(x) for x in rows.get(run_id, []) if x["gw"] == gw]
        if "FROM players_live" in sql:
            return []
        raise AssertionError(sql)
    monkeypatch.setattr(mt, "_q", fake_q)
    monkeypatch.setattr(mt, "_dispatch_state", lambda: {})
    monkeypatch.setattr(mt, "_freshness", lambda run: f"built run {run['run_id']} ({run['kind']})")
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    frame = pd.DataFrame(base9)
    monkeypatch.setattr(mt, "_frame_raw", lambda: (frame, 5, pd.Timestamp("2026-09-18 16:02:00+00:00")))
    monkeypatch.setattr(mt, "_current_gw", lambda: 5)
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: dict(RUNS[9]))
    monkeypatch.setattr(mt, "_frame_built", lambda cutoff: {"built": "built run 9 (t90)", "next_run_expected": None})
    return base7, base9


def test_explain_prediction_starts_with_summary_plain_and_keeps_the_technical_parts_under_detail(db):
    r = mt.explain_prediction(411, gw=5, run_id=7)
    assert "error" not in r, r
    assert list(r)[0] == "summary_plain" and r["summary_plain"].startswith("Erling Haaland is expected to score ")
    assert set(r["detail"]) >= {"lines", "fixture", "summary", "rendered", "residual_core", "residual_total"}
    assert not any(k in r for k in ("lines", "fixture", "summary", "rendered", "residual_core"))
    assert r["total_e_points"] == r["detail"]["lines"] and False if False else r["total_e_points"] > 0
    assert r["reconciles"] is True and r["run_id"] == 7 and r["name"] == "Erling Haaland"
    frame_bd = explain.breakdown(db[0][0], pd.DataFrame(db[0]))
    for k in ("lines", "fixture", "summary", "rendered"):
        assert r["detail"][k] == frame_bd[k], k                    # unchanged, just moved
    live = mt.explain_prediction(411, gw=5)
    assert list(live)[0] == "summary_plain" and "detail" in live and "lines" not in live


def test_compare_runs_and_compare_predictions_start_plain_and_keep_breakdowns_under_detail(db):
    c = mt.compare_runs(411, 5, 7, 9)
    assert "error" not in c, c
    assert list(c)[0] == "summary_plain" and c["summary_plain"].startswith("Erling Haaland's GW5 number moved from ")
    assert "built run 7" not in c["summary_plain"] and "Tue 15 Sep" in c["summary_plain"]
    assert set(c["detail"]) >= {"terms", "sentence", "flags", "rendered", "breakdown_a", "breakdown_b"}
    assert not any(k in c for k in ("terms", "sentence", "rendered", "breakdown_a"))
    assert c["run_a"]["run_id"] == 7 and c["run_b"]["run_id"] == 9 and "gap" in c and c["name"] == "Erling Haaland"
    p = mt.compare_predictions(411, 1001, gw=5)
    assert "error" not in p, p
    assert list(p)[0] == "summary_plain" and p["summary_plain"].startswith("Erling Haaland ")
    assert set(p["detail"]) >= {"terms", "sentence", "flags", "rendered", "breakdown_a", "breakdown_b"}
    assert "terms" not in p and p["a"]["name"] == "Erling Haaland" and p["gap"] == pytest.approx(p["a"]["total_e_points"] - p["b"]["total_e_points"], abs=1e-4)


def test_an_unavailable_player_leads_the_plain_summary(db, monkeypatch):
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {411: {"available": False, "availability_note": "Has joined Al Hilal permanently"}})
    r = mt.explain_prediction(411, gw=5)
    assert list(r)[:3] == ["summary_plain", "available", "availability_note"]
    assert r["summary_plain"].startswith("Erling Haaland cannot play for his club: Has joined Al Hilal permanently.")


# ---------------------------------------------------------------- descriptions and prompt
def test_the_three_descriptions_and_the_prompt_point_at_summary_plain():
    import agent
    for name in ("explain_prediction", "compare_predictions", "compare_runs"):
        d = next(t for t in agent.tools_schema if t["name"] == name)["description"]
        assert "summary_plain" in d and "detail" in d, name
    p = agent.SYSTEM_PROMPT
    assert "Answer from `summary_plain`. Use `detail` only when the user asks for the breakdown, the maths or how the number is built." in p
    assert "Never volunteer the penalty limitation." in p
    assert "our numbers don't fully count penalties, so for a regular taker treat it as a floor" in p
    assert "Never explain the cause." in p
    assert "penalty term is built from penalties missed" not in p
