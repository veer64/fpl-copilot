"""
explain_prediction levels 1-2 (Logs/explain_prediction_design.md): pure functions over
a frame row. The identity assert (pass, and a broken row -> finding), every detector on
synthetic rows (incl. the step-level starting-point detector), the three-word source
vocabulary and the summary line, the comparison ranking and the >= 80% sentence, the
constant-vs-model flag; the restated constants equal the model's; and, when the live
frame is on disk, the eight terms reconcile on every row.

Run:
    uv run pytest Tests/test_explain_prediction.py -v
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import explain                                                 # noqa: E402

FRAME = REPO / "data" / "live" / "_tmp_frame_baseline.parquet"


def _row(element=1, name="A Player", position="FWD", team="Man City", gw=5, step=1,
         p_start=0.97, p60=1.0, e_minutes=87.3, npxg90=0.79, xa90=0.18, team_lambda=1.284, opp_lambda=1.0,
         p_cs=0.368, p_dc_hit=0.005, saves_per_90=0.0, yellow_per_90=0.143, red_per_90=0.005,
         penalty_share=0.083, team_pen_rate=0.0, understat_id=123.0, bonus=0.0, bonus_mode="delete",
         pts_saves=0.0, pts_conceded=0.0, n_fixtures=1, **over):
    """A row consistent with the master equation (so the identities hold), from inputs."""
    mf = min(max(e_minutes / 90.0, 0), 1)
    fs = min(max(team_lambda / 1.40, 0.5), 2.0)
    p60p = p_start * p60
    ppa = p_start + (1 - p_start) * 0.30
    e_pen = penalty_share * team_pen_rate * mf
    e_goals = npxg90 * mf * fs + e_pen
    e_ast = xa90 * mf * fs
    r = dict(element=element, name=name, position=position, team=team, gw=gw, cutoff=gw - step, horizon_step=step,
             minutes_frac=mf, fixture_scale_cal=fs, fixture_scale=fs, fixture_scale_gamma=1.0, topend_cal_active=False,
             p_start=p_start, p60=p60, p_60plus=p60p, p_play_any=ppa, e_minutes=e_minutes,
             npxg90=npxg90, xa90=xa90, e_goals=e_goals, e_assists=e_ast, e_pen_goals=e_pen,
             team_lambda=team_lambda, opp_lambda=opp_lambda, p_cs=p_cs, p_dc_hit=p_dc_hit,
             saves_per_90=saves_per_90, yellow_per_90=yellow_per_90, red_per_90=red_per_90,
             penalty_share=penalty_share, team_pen_rate=team_pen_rate, understat_id=understat_id,
             bonus_mode=bonus_mode, penalty_fix_active=False, odds_horizon_gws=0, n_fixtures=n_fixtures,
             pts_appear=p60p * 2 + max(ppa - p60p, 0) * 1,
             pts_goals=e_goals * explain.GOAL_PTS[position], pts_assists=e_ast * 3,
             pts_cs=p_cs * explain.CS_PTS[position] * p60p,
             pts_dc=(0.0 if position == "GK" else p_dc_hit * 2 * mf),
             pts_saves=pts_saves, pts_conceded=pts_conceded,
             pts_cards=-(yellow_per_90 * 1 + red_per_90 * 3) * mf, exp_bonus=bonus)
    r["e_points_core"] = sum(r[c] for c in explain.CORE)
    r["e_points"] = r["e_points_core"] + r["exp_bonus"]
    r.update(over)
    return pd.Series(r)


def _step(rows):
    return pd.DataFrame([r for r in rows])


def test_restated_constants_equal_the_models():
    import assembly, defensive
    assert explain.GOAL_PTS == assembly.GOAL_PTS and explain.CS_PTS == assembly.CS_PTS
    assert explain.DC_BASE == assembly.DC_BASE and explain.LEAGUE_AVG_LAMBDA == assembly.LEAGUE_AVG_LAMBDA
    assert explain.FWD_BASE_RATE == defensive.FWD_BASE_RATE
    assert explain.X0_HOME == pytest.approx(math.exp(0.25))


def test_identity_holds_on_a_consistent_row_and_a_broken_row_is_a_finding():
    r = _row()
    rec = explain.reconcile(r)
    assert rec["reconciles"] and abs(rec["residual_core"]) < 1e-9
    bad = r.copy(); bad["pts_goals"] += 0.01
    bd = explain.breakdown(bad, _step([bad]))
    assert bd["reconciles"] is False and "finding" in bd and "does NOT reconcile" in bd["finding"]
    assert abs(bd["residual_core"] - 0.01) < 1e-9


def test_lines_are_nine_sorted_by_size_with_one_of_three_source_words():
    bd = explain.breakdown(_row(), _step([_row()]))
    assert [l["term"] for l in bd["lines"]].__len__() == 9
    pts = [abs(l["points"]) for l in bd["lines"]]
    assert pts == sorted(pts, reverse=True)
    assert {l["source"] for l in bd["lines"]} <= {"model", "constant", "rule"}
    assert bd["lines"][0]["term"] == "goals" and bd["total_e_points"] == pytest.approx(float(_row()["e_points"]), abs=1e-4)
    assert "penalties" in next(l for l in bd["lines"] if l["term"] == "goals")


def test_forward_dc_flat_by_design_and_bonus_off_are_constants_with_the_fixed_labels():
    bd = explain.breakdown(_row(), _step([_row()]))
    by = {l["term"]: l for l in bd["lines"]}
    assert by["defensive_contribution"]["source"] == "constant" and by["defensive_contribution"]["constant"] == "flat by design"
    assert by["bonus"]["source"] == "constant" and by["bonus"]["constant"] == "0 by decision"
    assert by["cards"]["source"] == "constant" and by["cards"]["constant"] == "position rates"
    assert by["clean_sheet"]["source"] == "rule" and by["saves"]["source"] == "rule" and by["goals_conceded"]["source"] == "rule"
    assert by["goals"]["source"] == "model" and by["appearance"]["source"] == "model"
    assert "3 of 9 lines are constants" in bd["summary"] and "defensive contribution: flat by design" in bd["summary"]
    assert "flat 0.30 sub chance" in bd["summary"] and "position rates" in bd["summary"]


def test_positional_dc_fallback_and_position_prior_and_penalty_fallback_are_detected_per_row():
    mid = _row(position="MID", p_dc_hit=0.136, understat_id=float("nan"), penalty_share=0.05)
    bd = explain.breakdown(mid, _step([mid]))
    by = {l["term"]: l for l in bd["lines"]}
    assert by["defensive_contribution"]["constant"] == "flat positional value"
    assert by["goals"]["source"] == "constant" and by["goals"]["constant"] == "position prior"
    assert by["assists"]["constant"] == "position prior"
    assert by["goals"]["penalties"]["source"] == "constant" and by["goals"]["penalties"]["constant"] == "fallback 0.05"
    assert "penalties: fallback 0.05" in bd["summary"]
    real = _row(position="MID", p_dc_hit=0.21)
    by2 = {l["term"]: l for l in explain.breakdown(real, _step([real]))["lines"]}
    assert by2["defensive_contribution"]["source"] == "model" and by2["goals"]["source"] == "model"


def test_starting_point_detector_is_step_level_and_labels_the_fixture():
    teams = [f"T{i}" for i in range(20)]
    deg = [_row(element=i, team=t, team_lambda=(math.exp(0.25) if i % 2 == 0 else 1.0), opp_lambda=(1.0 if i % 2 == 0 else math.exp(0.25)))
           for i, t in enumerate(teams)]
    step = _step(deg)
    assert explain.step_is_degenerate(step) is True
    bd = explain.breakdown(deg[0], step)
    assert bd["fixture"]["source"] == "constant" and bd["fixture"]["constant"] == "the fit's starting point"
    assert "the fit's starting point" in bd["summary"]
    healthy = [_row(element=i, team=t, team_lambda=0.7 + 0.08 * i, opp_lambda=2.2 - 0.06 * i) for i, t in enumerate(teams)]
    hs = _step(healthy)
    assert explain.step_is_degenerate(hs) is False
    assert explain.breakdown(healthy[3], hs)["fixture"]["source"] == "model"
    # one club at the starting point among healthy ones is not the pattern
    mixed = healthy[:-1] + [deg[0]]
    assert explain.step_is_degenerate(_step(mixed)) is False


def test_neutral_fixture_and_runaway_strength_are_labelled():
    n = _row(team_lambda=1.40, opp_lambda=1.40)
    bd = explain.breakdown(n, _step([n]))
    assert bd["fixture"]["constant"] == "league-average fixture"
    r = _row(team_lambda=0.002, opp_lambda=1.3)
    bd = explain.breakdown(r, _step([r]))
    assert any("ran off" in x for x in bd["fixture"]["notes"]) and "KNOWN_ISSUES #25" in bd["summary"]


def test_goalkeeper_lines_use_the_rules_and_the_saves_note():
    gk = _row(position="GK", p_dc_hit=0.0, saves_per_90=2.31, pts_saves=0.41, pts_conceded=-0.27, p_cs=0.368)
    bd = explain.breakdown(gk, _step([gk]))
    by = {l["term"]: l for l in bd["lines"]}
    assert by["defensive_contribution"]["source"] == "rule" and by["saves"]["source"] == "model"
    assert any("0.3 x position-mean fallback" in x for x in by["saves"]["notes"])
    assert by["goals_conceded"]["source"] == "model" and by["clean_sheet"]["source"] == "model"
    assert bd["reconciles"]


def test_compare_ranks_terms_names_the_eighty_percent_and_flags_constant_vs_model():
    a = _row(element=1, name="Haaland", npxg90=0.79, xa90=0.18, p_start=0.97)
    b = _row(element=2, name="Isak", team="Liverpool", npxg90=0.53, xa90=0.09, p_start=0.82, team_lambda=1.0, opp_lambda=1.284)
    ba, bb = explain.breakdown(a, _step([a, b])), explain.breakdown(b, _step([a, b]))
    c = explain.compare(ba, bb)
    assert c["terms"][0]["term"] == "goals" and c["gap"] == pytest.approx(ba["total_e_points"] - bb["total_e_points"], abs=1e-4)
    assert c["sentence"].startswith("Haaland") and "goals" in c["sentence"] and "%" in c["sentence"]
    assert all(abs(c["terms"][i]["diff"]) >= abs(c["terms"][i + 1]["diff"]) for i in range(len(c["terms"]) - 1))
    # a constant on one side vs a model value on the other is flagged
    m = _row(element=3, name="Rice", position="MID", p_dc_hit=0.136)
    n = _row(element=4, name="Caicedo", position="MID", p_dc_hit=0.22)
    bm, bn = explain.breakdown(m, _step([m, n])), explain.breakdown(n, _step([m, n]))
    c2 = explain.compare(bm, bn)
    dc = next(t for t in c2["terms"] if t["term"] == "defensive_contribution")
    assert dc["flag"] and "flat positional value" in dc["flag"] and "model value" in dc["flag"]
    with pytest.raises(ValueError):
        explain.compare(ba, explain.breakdown(_row(element=9, gw=6), _step([_row(element=9, gw=6)])))


def test_rendered_blocks_carry_the_header_the_lines_and_the_summary():
    bd = explain.breakdown(_row(), _step([_row()]))
    r = bd["rendered"]
    assert r.splitlines()[0].startswith("A Player (FWD, Man City) -- GW5:") and "[reconciles: yes" in r
    assert "of which penalties" in r and r.splitlines()[-1] == bd["summary"]


@pytest.mark.skipif(not FRAME.exists(), reason="live frame not on this machine")
def test_live_frame_reconciles_on_every_row_and_the_step_detector_matches_the_data():
    f = pd.read_parquet(FRAME)
    core = f[explain.CORE].sum(axis=1)
    assert (core - f["e_points_core"]).abs().max() <= explain.TOL
    assert ((f["e_points_core"] + f["exp_bonus"]) - f["e_points"]).abs().max() <= explain.TOL
    for gw, step in f.groupby("gw"):
        lam = step.groupby("team")["team_lambda"].first().dropna()
        expect = bool(len(lam) >= 10 and (np.isclose(lam, math.exp(0.25), atol=1e-6) | np.isclose(lam, 1.0, atol=1e-6)).all())
        assert explain.step_is_degenerate(step) is expect, gw
        bd = explain.breakdown(step.iloc[0], step)
        assert bd["reconciles"] and len(bd["lines"]) == 9
