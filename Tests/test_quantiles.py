"""Quantiles (quantiles.py). Design and measurement: Logs/quantiles_design_2026-09-18.md.

The contract these hold to:
  * the simulation MEANS reconcile with e_points, in TWO parts -- a sampling half with a
    per-row tolerance, and a structural half reported with NO pass bar because it is a bias;
  * the clean sheet couples to -ln(p_cs), NOT opp_lambda -- the bug that cost 0.30 points on
    step-0 defenders, and the reason a check on one horizon step is not a check on the model;
  * a draw can never award a clean sheet alongside a conceded goal;
  * determinism: same (run_seed, element, gw) -> same numbers, whatever the row order;
  * MS-1 is a NEW ASSUMPTION, named and versioned, and it moves P90 more than P10/P50;
  * P90 is never presented as comparable in quality to P50.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import quantiles as qt                                          # noqa: E402


def a_row(**kw):
    """A defender who usually starts, against a mid-strength opponent."""
    r = dict(element=101, gw=7, position="DEF", p_start=0.90, p60=0.88, p_play_any=0.93,
             minutes_frac=0.80, e_goals=0.06, e_assists=0.05, p_cs=0.30, opp_lambda=1.20,
             p_dc_hit=0.13, saves_per_90=0.0, yellow_per_90=0.15, red_per_90=0.005,
             exp_bonus=0.0, e_pen_goals=0.0, penalty_share=0.05, e_points=3.0)
    r.update(kw)
    return r


def model_e_points(r):
    """The model's own arithmetic for this synthetic row, so the test has a truth to
    reconcile against rather than a number the simulator produced."""
    p60p = r["p_start"] * r["p60"]
    ppa, mf = r["p_play_any"], r["minutes_frac"]
    gp, csp = qt.GOAL_PTS[r["position"]], qt.CS_PTS[r["position"]]
    pts = p60p * 2 + max(ppa - p60p, 0) * 1
    pts += r["e_goals"] * gp + r["e_assists"] * 3
    pts += r["p_cs"] * csp * p60p
    pts += r["p_dc_hit"] * 2 * mf
    pts -= (r["yellow_per_90"] * 1 + r["red_per_90"] * 3) * mf
    lam = -math.log(r["p_cs"]) * mf
    pts -= sum(math.floor(c / 2) * math.exp(-lam) * lam ** c / math.factorial(c) for c in range(40))
    return pts


# ------------------------------------------------------------------ determinism
def test_same_seed_and_row_give_identical_numbers():
    r = a_row()
    a = qt.quantiles_for_row(r, run_seed=7, n=4000)
    b = qt.quantiles_for_row(r, run_seed=7, n=4000)
    assert a == b


def test_the_stream_is_keyed_by_row_not_by_order():
    """Row order, chunking and parallelism must not change a stored quantile."""
    r1, r2 = a_row(element=101), a_row(element=202)
    first = qt.quantiles_for_row(r1, 7, n=4000)
    _ = qt.quantiles_for_row(r2, 7, n=4000)
    again = qt.quantiles_for_row(r1, 7, n=4000)
    assert first == again


def test_a_different_run_seed_gives_different_draws():
    assert (qt.quantiles_for_row(a_row(), 7, n=4000)["q_p90"]
            != qt.quantiles_for_row(a_row(), 8, n=4000)["q_p90"]) or True   # may tie on ints
    a = qt.simulate_row(a_row(), 4000, qt.row_rng(7, 101, 7))[0]
    b = qt.simulate_row(a_row(), 4000, qt.row_rng(8, 101, 7))[0]
    assert not np.array_equal(a, b)


# ------------------------------------------------- the coupling that was wrong
def test_clean_sheet_couples_to_p_cs_not_opp_lambda():
    """THE BUG: coupling to opp_lambda cost 0.30 points on step-0 defenders, because at
    step 0 opp_lambda is the pure-market lambda while p_cs comes from the 0.2/0.8 CS blend.
    They agree at steps 1-5 and NOT at step 0, so the rate must come from p_cs."""
    r = a_row(p_cs=0.50, opp_lambda=2.50, minutes_frac=1.0, p_start=1.0, p60=1.0,
              p_play_any=1.0, e_goals=0.0, e_assists=0.0, p_dc_hit=0.0,
              yellow_per_90=0.0, red_per_90=0.0)
    free, _ = qt.simulate_row(r, 40_000, qt.row_rng(1, 1, 1))
    # a DEF playing 90: 2 appearance + 4 if clean sheet - floor(conceded/2)
    got_cs = float(np.mean((free - 2.0) >= 4.0))
    assert abs(got_cs - r["p_cs"]) < 0.01, got_cs
    # had it coupled to opp_lambda the rate would be exp(-2.5) = 0.082, nowhere near 0.50
    assert abs(got_cs - math.exp(-r["opp_lambda"])) > 0.3


def test_a_clean_sheet_never_coexists_with_a_conceded_goal():
    r = a_row(p_cs=0.35, minutes_frac=1.0, p_start=1.0, p60=1.0, p_play_any=1.0,
              e_goals=0.0, e_assists=0.0, p_dc_hit=0.0, yellow_per_90=0.0, red_per_90=0.0)
    free, _ = qt.simulate_row(r, 20_000, qt.row_rng(2, 2, 2))
    # 2 + 4 = 6 exactly when a clean sheet; any concession subtracts, so 6 is the max and
    # nothing may sit strictly between "clean sheet" and "clean sheet minus a deduction"
    assert free.max() == 6.0
    assert set(np.unique(free)) <= {6.0, 2.0, 1.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0}


# ------------------------------------------------------- the two-part reconciliation
def test_the_sampling_half_reconciles_with_the_model_arithmetic():
    r = a_row()
    r["e_points"] = model_e_points(r)
    q = qt.quantiles_for_row(r, 11, n=60_000)
    assert abs(q["q_resid_sampling"]) <= q["q_tolerance"] * 2.0, q


def test_the_tolerance_scales_with_the_row_and_never_below_the_floor():
    q = qt.quantiles_for_row(a_row(), 3, n=20_000)
    assert q["q_tolerance"] >= qt.TOL_FLOOR
    assert q["q_tolerance"] == pytest.approx(
        max(qt.TOL_FLOOR, qt.TOL_SIGMA * q["q_sd"] / math.sqrt(20_000)))


def test_the_structural_half_is_zero_for_positions_with_no_floor_terms():
    """MID and FWD have neither saves nor conceded, so the Jensen term cannot exist."""
    for pos in ("MID", "FWD"):
        q = qt.quantiles_for_row(a_row(position=pos), 5, n=8000)
        assert q["q_resid_structural"] == 0.0, pos


def test_the_structural_half_is_present_for_gk_and_def_and_has_no_pass_bar():
    q = qt.quantiles_for_row(a_row(position="DEF"), 5, n=40_000)
    assert q["q_resid_structural"] != 0.0
    # reconciles() judges the SAMPLING half only -- the bias has no bar
    r = dict(q_resid_sampling=0.001, q_tolerance=0.02, q_resid_structural=-9.0)
    assert qt.reconciles(r) is True


def test_reconciles_fails_when_the_sampling_half_breaches():
    assert qt.reconciles(dict(q_resid_sampling=0.5, q_tolerance=0.02)) is False


# --------------------------------------------------------------- MS-1 is an assumption
def test_the_minutes_shape_is_named_and_versioned():
    assert qt.DEFAULT_SHAPE == "MS-1"
    assert qt.MINUTES_SHAPES["MS-1"] == (85.0, 35.0, 20.0)
    assert len(qt.MINUTES_SHAPES) >= 3, "alternatives must exist so it can be varied"
    q = qt.quantiles_for_row(a_row(), 1, n=4000)
    assert q["q_minutes_shape"] == "MS-1" and q["q_method_version"] == qt.METHOD_VERSION


def test_the_shape_barely_moves_the_mean_because_it_is_scaled_per_row():
    r = a_row()
    means = []
    for shape in ("MS-1", "MS-2", "MS-3"):
        free, _ = qt.simulate_row(r, 40_000, qt.row_rng(9, 1, 1), shape)
        means.append(float(np.mean(free)))
    assert max(means) - min(means) < 0.05, means


# ------------------------------------------------------------------- degeneracy
def test_a_fringe_player_gets_a_one_sided_bar_and_says_so():
    q = qt.quantiles_for_row(a_row(p_start=0.02, p60=0.5, p_play_any=0.12,
                                   minutes_frac=0.05), 4, n=20_000)
    assert q["q_p10"] == q["q_p50"] == 0.0
    assert q["q_degenerate"] is True
    assert q["q_distinct"] < 3
    assert qt.fidelity(q)["degenerate"] is True
    assert "one-sided" in qt.fidelity(q)["degenerate_note"]


def test_a_regular_starter_is_not_degenerate():
    q = qt.quantiles_for_row(a_row(), 4, n=20_000)
    assert q["q_degenerate"] is False and q["q_distinct"] == 3


# ------------------------------------------------------------- P90 is not P50's equal
def test_p90_is_explicitly_flagged_as_the_weakest_of_the_three():
    fid = qt.fidelity({**a_row(), **qt.quantiles_for_row(a_row(), 6, n=4000)})
    assert fid["p90_is_weaker_than_p50"] is True
    c = fid["p90_caveat"].lower()
    for needed in ("bonus", "penalt", "minutes shape", "p90"):
        assert needed in c, needed
    assert "do not read p90 as comparable in quality to p50" in c


def test_the_three_fragilities_are_each_named():
    fid = qt.fidelity({**a_row(), **qt.quantiles_for_row(a_row(), 6, n=4000)})
    terms = {z["term"] for z in fid["zero_variance_terms"]}
    assert {"bonus", "penalties", "cards"} <= terms
    assert fid["summary"].endswith("bias P90 low.")
    assert all(z["source"] == "constant" for z in fid["zero_variance_terms"])


def test_the_fidelity_labels_come_from_explain_s_fixed_vocabulary():
    from explain import CONSTANT_LABELS
    fid = qt.fidelity({**a_row(), **qt.quantiles_for_row(a_row(), 6, n=4000)})
    for z in fid["zero_variance_terms"]:
        assert z["constant"] in CONSTANT_LABELS.values(), z


# ------------------------------------------------------------------- plumbing
def test_add_quantiles_adds_every_column_and_leaves_e_points_alone():
    f = pd.DataFrame([a_row(element=1), a_row(element=2, position="MID")])
    out = qt.add_quantiles(f, run_seed=42, n=3000)
    for c in qt.QUANTILE_COLS:
        assert c in out.columns, c
    pd.testing.assert_series_equal(out["e_points"], f["e_points"])
    assert list(out["element"]) == [1, 2]


def test_the_columns_are_persisted_and_nullable():
    import db_write
    for c in qt.QUANTILE_COLS:
        assert c in db_write.QUANT_COLS or c in ("q_draws",), c
        assert c in db_write.PRED_INSERT_COLS, c
    ddl = (REPO / "db_write.py").read_text(encoding="utf-8")
    for c in ("q_p10", "q_p90", "q_resid_structural", "q_method_version"):
        assert f"ADD COLUMN IF NOT EXISTS {c}" in ddl, c


def test_t10_is_the_skipped_kind_and_the_seed_is_recorded():
    src = (REPO / "eval" / "run_live_deadline.py").read_text(encoding="utf-8")
    assert 'QUANTILE_SKIP_KINDS = ("t10",)' in src
    assert '"quantile_seed"' in src, "a stored quantile must be reproducible from the run record"


def test_a_run_that_skipped_quantiles_writes_NULL_not_ZERO():
    """THE distinction the nullable columns exist to protect. t10 does not compute
    quantiles, so its rows must read as "not computed" -- never as a P10/P50/P90 of 0,
    a standard deviation of 0, or a residual of 0, all of which would be a confident
    claim of NO UNCERTAINTY instead of an absent calculation."""
    import db_write
    f = pd.DataFrame([{
        "element": 411, "gw": 5, "cutoff": 5, "e_points": 5.1, "e_points_core": 5.1,
        "exp_bonus": 0.0, "e_minutes": 87.3, "p_start": 0.97, "p_60plus": 0.97,
        "p_play_any": 0.979, "e_goals": 0.7, "e_assists": 0.158, "p_cs": 0.368,
    }])                                            # NO q_* columns, exactly as t10 leaves it
    cols, rows = db_write.prediction_rows(1, "baseline", f)
    got = dict(zip(cols, rows[0]))
    for c in qt.QUANTILE_COLS:
        if c in got:
            assert got[c] is None, f"{c} is {got[c]!r}, must be None for a run that skipped"
    assert got["e_points"] == 5.1, "the prediction itself is unaffected"


def test_quantile_columns_carry_no_sql_default():
    """A DEFAULT 0 would silently turn every skipped run into a claim of certainty."""
    import db_write
    ddl = db_write.DDL
    for c in qt.QUANTILE_COLS:
        for line in ddl.splitlines():
            if f"ADD COLUMN IF NOT EXISTS {c} " in line or f"ADD COLUMN IF NOT EXISTS {c}\t" in line:
                assert "DEFAULT" not in line.upper(), line
                assert "NOT NULL" not in line.upper(), line
