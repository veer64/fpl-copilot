"""Penalty-term correctness fix (Logs/penalty_fix_prereg.md): gate semantics.

Gate OFF must reproduce the pre-fix equation exactly (penalty_share x
team_pen_rate x minutes_frac); gate ON must add penalty_share x minutes_frac
and nothing else. Both are checked on a synthetic per-fixture frame through
assembly._finish_equation itself, so the test breaks if the equation drifts.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "squad"))
import assembly  # noqa: E402
import bonus  # noqa: E402


class _ConstBPS:
    def predict(self, X):
        return np.full(len(X), 20.0)


def _frame():
    return pd.DataFrame({
        "element": [1, 2, 3, 4], "gw": [5, 5, 5, 5], "fixture": [10, 10, 11, 11],
        "position": ["MID", "FWD", "DEF", "GK"],
        "e_minutes": [90.0, 60.0, 80.0, 90.0], "p_start": [1.0, 0.6, 0.9, 1.0],
        "p60": [0.95, 0.9, 0.9, 1.0], "npxg90": [0.4, 0.5, 0.05, 0.0],
        "xa90": [0.3, 0.1, 0.05, 0.0], "team_lambda": [1.8, 1.2, 1.4, 1.0],
        "opp_lambda": [1.0, 1.5, 1.4, 2.0], "p_cs": [0.4, 0.2, 0.25, 0.1],
        "p_dc_hit": [0.1, 0.05, 0.4, 0.0], "saves_per_90": [0, 0, 0, 3.0],
        "yellow_per_90": [0.18, 0.14, 0.17, 0.05], "red_per_90": [0.005] * 4,
        "penalty_share": [0.2, 0.1, 0.0, 0.0], "team_pen_rate": [0.02, 0.05, 0.0, 0.0],
    })


def _run(gate):
    old = assembly.PENALTY_FIX_ACTIVE
    assembly.PENALTY_FIX_ACTIVE = gate
    try:
        a = assembly._finish_equation(_frame(), _ConstBPS(), lambda b: np.asarray(b) * 0.05,
                                      bonus.BPS_FEATURES, bonus_mean=0.2)
    finally:
        assembly.PENALTY_FIX_ACTIVE = old
    return a


@pytest.mark.skipif(not assembly.D1_TERMS_ACTIVE, reason="penalty term is a D1 term")
def test_gate_off_is_prefix_form():
    a = _run(False)
    mf = (a["e_minutes"] / 90).clip(0, 1)
    expect = a["penalty_share"] * a["team_pen_rate"] * mf
    assert np.allclose(a["e_pen_goals"], expect)
    base = a["npxg90"] * mf * a["fixture_scale"]
    assert np.allclose(a["e_goals"], base + expect)


@pytest.mark.skipif(not assembly.D1_TERMS_ACTIVE, reason="penalty term is a D1 term")
def test_gate_on_drops_team_factor_only():
    off, on = _run(False), _run(True)
    mf = (on["e_minutes"] / 90).clip(0, 1)
    assert np.allclose(on["e_pen_goals"], on["penalty_share"] * mf)
    # everything except the penalty term is untouched
    delta_goals = on["e_goals"] - off["e_goals"]
    assert np.allclose(delta_goals, on["e_pen_goals"] - off["e_pen_goals"])
    assert np.allclose(on["e_assists"], off["e_assists"])
    assert np.allclose(on["pts_cs"], off["pts_cs"])
    assert np.allclose(on["pts_appear"], off["pts_appear"])
    # a taker (penalty_share 0.2, 90 min) gains 0.2 goals; non-takers gain nothing
    assert abs(float(delta_goals.iloc[0]) - 0.2 + 0.2 * 0.02) < 1e-9
    assert float(delta_goals.iloc[2]) == 0.0 and float(delta_goals.iloc[3]) == 0.0


def test_gate_rests_false_on_disk():
    assert assembly.PENALTY_FIX_ACTIVE is False, (
        "PENALTY_FIX_ACTIVE was flipped on disk -- adoption is a deliberate step "
        "(Logs/penalty_fix_prereg.md section 4); update this test when adopting")


def test_topend_gate_off_is_identity_and_on_applies_gamma():
    """Logs/topend_calibration_prereg.md: gate off -> fixture_scale_cal == fixture_scale;
    gate on -> fixture_scale ** gamma on both attacking terms, nothing else moves."""
    old = (assembly.TOPEND_CAL_ACTIVE, assembly.FIXTURE_SCALE_GAMMA)
    try:
        assembly.TOPEND_CAL_ACTIVE, assembly.FIXTURE_SCALE_GAMMA = False, 1.0
        off = assembly._finish_equation(_frame(), _ConstBPS(), lambda b: np.asarray(b) * 0.05, bonus.BPS_FEATURES, bonus_mean=0.2)
        assert np.allclose(off["fixture_scale_cal"], off["fixture_scale"])
        assembly.TOPEND_CAL_ACTIVE, assembly.FIXTURE_SCALE_GAMMA = True, 0.5
        on = assembly._finish_equation(_frame(), _ConstBPS(), lambda b: np.asarray(b) * 0.05, bonus.BPS_FEATURES, bonus_mean=0.2)
    finally:
        assembly.TOPEND_CAL_ACTIVE, assembly.FIXTURE_SCALE_GAMMA = old
    assert np.allclose(on["fixture_scale_cal"], off["fixture_scale"] ** 0.5)
    mf = (on["e_minutes"] / 90).clip(0, 1)
    assert np.allclose(on["e_assists"], on["xa90"] * mf * on["fixture_scale_cal"])
    assert np.allclose(on["e_goals"] - on["e_pen_goals"], on["npxg90"] * mf * on["fixture_scale_cal"])
    assert np.allclose(on["e_pen_goals"], off["e_pen_goals"])
    assert np.allclose(on["pts_cs"], off["pts_cs"]) and np.allclose(on["pts_appear"], off["pts_appear"])
    assert assembly.TOPEND_CAL_ACTIVE is False and assembly.FIXTURE_SCALE_GAMMA == 1.0
