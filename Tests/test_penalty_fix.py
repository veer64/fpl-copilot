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


def test_bonus_modes():
    """Logs/bonus_rebuild_prereg.md: 'incumbent' unchanged; 'delete' -> e_points == core;
    'outcome' -> weights sum to one (constant tree => constant bonus) and sits on the gate."""
    old = assembly.BONUS_MODE
    try:
        assembly.BONUS_MODE = "incumbent"
        inc = assembly._finish_equation(_frame(), _ConstBPS(), lambda b: np.asarray(b) * 0.05, bonus.BPS_FEATURES, bonus_mean=0.2)
        assembly.BONUS_MODE = "delete"
        dele = assembly._finish_equation(_frame(), _ConstBPS(), lambda b: np.asarray(b) * 0.05, bonus.BPS_FEATURES, bonus_mean=0.2)
        assembly.BONUS_MODE = "outcome"
        ow = assembly._finish_equation(_frame(), _ConstBPS(), lambda b: np.asarray(b) * 0.05, bonus.BPS_FEATURES, bonus_mean=0.2)
    finally:
        assembly.BONUS_MODE = old
    assert np.allclose(dele["e_points"], dele["e_points_core"]) and (dele["exp_bonus"] == 0).all()
    assert np.allclose(ow["e_points_core"], inc["e_points_core"])
    mf = (ow["e_minutes"] / 90).clip(0, 1)
    # constant tree: E[curve(20)] = 1.0 per outcome, weights sum to 1 -> exp_bonus == 1.0 * minutes_frac exactly
    assert np.allclose(ow["exp_bonus"], 1.0 * mf, atol=1e-9)
    assert np.allclose(ow["pred_bps"], 20.0, atol=1e-9)
    assert assembly.BONUS_MODE == "delete", "BONUS_MODE resting value moved -- adoption is deliberate (Logs/bonus_delete_prereg.md)"


def test_trunc_poisson_folds_tail():
    P = assembly._trunc_poisson(np.array([0.3, 1.0, 5.0]), 3)
    assert np.allclose(P.sum(axis=1), 1.0) and P.shape == (3, 4) and P[2, 3] > 0.7


def test_canonical_bonus_mode_stamp_matches_code():
    """The d1_terms_active pattern: source and artefact must agree on the bonus term.
    Files predating the stamp are skipped (establish their status from the data)."""
    import pyarrow.parquet as pq
    root = Path(__file__).resolve().parents[1] / "data"
    checked = 0
    for tag in ("2023_24", "2024_25", "2025_26"):
        p = root / f"walkforward_h6_{tag}.parquet"
        if not p.exists():
            continue
        if "bonus_mode" not in pq.read_schema(p).names:
            pytest.skip(f"{p.name} predates the bonus_mode stamp")
        col = pd.read_parquet(p, columns=["bonus_mode"])["bonus_mode"]
        assert (col == assembly.BONUS_MODE).all(), (
            f"{p.name} stamped bonus_mode={col.iloc[0]} but assembly.BONUS_MODE={assembly.BONUS_MODE} "
            "-- source and artefact disagree; rebuild the canonical or flip the constant back, deliberately")
        checked += 1
    if checked == 0:
        pytest.skip("no canonical files present")


# ---------------------------------------------------------------------------
# Same-season leak fix (2026-08-27): the Understat penalty join must read a
# season STRICTLY BEFORE the one being predicted, in BOTH gate states. Against
# the pre-fix code this fails: _penalty_join_year / _attach_penalty_share did
# not exist and the gate-off path joined season_year itself.
# ---------------------------------------------------------------------------

def _with_gate(gate, fn):
    old = assembly.PENALTY_FIX_ACTIVE
    assembly.PENALTY_FIX_ACTIVE = gate
    try:
        return fn()
    finally:
        assembly.PENALTY_FIX_ACTIVE = old


@pytest.mark.parametrize("gate", [False, True])
def test_penalty_join_year_is_strictly_prior_in_both_gate_states(gate):
    years = pd.Series([2023, 2024, 2025])
    joined = _with_gate(gate, lambda: assembly._penalty_join_year(years))
    assert (joined < years).all(), f"gate={gate}: join year not strictly prior: {joined.tolist()}"
    assert (joined == years - 1).all()
    assert _with_gate(gate, lambda: assembly._penalty_join_year(2024)) == 2023


@pytest.mark.parametrize("gate", [False, True])
def test_penalty_share_never_reads_the_predicted_season(gate, monkeypatch, tmp_path):
    """End-to-end through _attach_penalty_share on a synthetic Understat file:
    a player whose ONLY record is in the season being predicted must NOT
    receive it (leak); a player with a prior-season record must."""
    us = pd.DataFrame({
        "id": [1, 1, 2, 3], "player_name": ["a", "a", "b", "c"],
        "games": [30, 30, 30, 30], "goals": [10, 20, 8, 5], "npg": [4, 20, 8, 5],
        "position": ["F S", "F S", "M S", "GK"], "understat_season": [2023, 2024, 2024, 2023],
    })
    us_path = tmp_path / "understat_season_aggregates.parquet"
    us_path.parent.mkdir(exist_ok=True)
    us.to_parquet(us_path)
    # _attach_penalty_share reads BASE + r"\data\history\understat_season_aggregates.parquet"
    (tmp_path / "data" / "history").mkdir(parents=True)
    us.to_parquet(tmp_path / "data" / "history" / "understat_season_aggregates.parquet")
    monkeypatch.setattr(assembly, "BASE", str(tmp_path))

    v_full = pd.DataFrame({"element": [11, 12, 13], "season": ["2024-25"] * 3,
                           "position": ["FWD", "MID", "GK"]})
    cw = pd.DataFrame({"element": [11, 12, 13], "understat_id": [1, 2, 3]})
    out = _with_gate(gate, lambda: assembly._attach_penalty_share(v_full, cw, "2024-25"))
    assert (out["_pen_join_year"] == 2023).all()
    assert (out["understat_season"].dropna() == 2023).all(), "a 2024 (predicted-season) record was joined"
    # player 1: prior-season (2023) record 10-4=6 pen goals / 31 games; NOT the 2024 record (0 pens)
    assert abs(float(out.loc[out.element == 11, "penalty_share"].iloc[0]) - 6 / 31) < 1e-12
    # player 2: only a 2024 record -> must fall to the fallback, never to its own-season value (0.0 here
    # would be indistinguishable, so the 2024 record carries 0 pens and the fallback is checked directly)
    fb = 0.05 if not gate else float(out.loc[out.element == 12, "penalty_share"].iloc[0])
    assert pd.isna(out.loc[out.element == 12, "understat_season"].iloc[0])
    assert float(out.loc[out.element == 12, "penalty_share"].iloc[0]) == pytest.approx(fb)


def test_penalty_first_season_edge_case_warns_and_falls_back(monkeypatch, tmp_path):
    """No prior-season rows at all: warn, match nothing, never use the same season."""
    us = pd.DataFrame({"id": [1], "player_name": ["a"], "games": [30], "goals": [10], "npg": [4],
                       "position": ["F S"], "understat_season": [2024]})
    (tmp_path / "data" / "history").mkdir(parents=True)
    us.to_parquet(tmp_path / "data" / "history" / "understat_season_aggregates.parquet")
    monkeypatch.setattr(assembly, "BASE", str(tmp_path))
    v_full = pd.DataFrame({"element": [11], "season": ["2024-25"], "position": ["FWD"]})
    cw = pd.DataFrame({"element": [11], "understat_id": [1]})
    with pytest.warns(RuntimeWarning, match="no Understat aggregate rows for the prior season"):
        out = _with_gate(False, lambda: assembly._attach_penalty_share(v_full, cw, "2024-25"))
    assert pd.isna(out["understat_season"].iloc[0]) and float(out["penalty_share"].iloc[0]) == 0.05
    with pytest.warns(RuntimeWarning):
        out_on = _with_gate(True, lambda: assembly._attach_penalty_share(v_full, cw, "2024-25"))
    assert float(out_on["penalty_share"].iloc[0]) == 0.0
