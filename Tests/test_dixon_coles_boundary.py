"""
The Dixon-Coles cutoff boundary (Logs/dc_fix_prereg_2026-09-13.md, rule R):
a result is knowable at the cutoff iff the match FINISHED before the cutoff
DAY -- dated before that day, with goals present. One function,
`dixon_coles.knowable_before`, used by the fit's training filter and by the
as-of guard's truncation; a NaN goal in a training set RAISES instead of
letting the optimiser return its starting point; and the strict postflight
detector fires on a degenerate frame.

Synthetic matches only; no network, no build.

Run:
    uv run pytest Tests/test_dixon_coles_boundary.py -v
"""

import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dixon_coles as dc                                   # noqa: E402
import live_deadline as ld                                 # noqa: E402

CUTOFF = pd.Timestamp("2026-09-12 14:00:00")               # Saturday 14:00: the gameweek's first kickoff


def _m(date, hg, ag, season="2026-27", home="A", away="B"):
    return dict(date_parsed=pd.Timestamp(date), home_goals=hg, away_goals=ag, season=season, home=home, away=away)


def _matches(rows):
    return pd.DataFrame(rows)


# ------------------------------------------------------------- the rule
def test_rule_admits_only_matches_finished_before_the_cutoff_day():
    m = _matches([
        _m("2026-09-11", 1, 0),          # the day before, played          -> knowable
        _m("2026-09-12", 2, 1),          # cutoff day, played (backtest)    -> NOT (finished after the cutoff)
        _m("2026-09-12", None, None),    # cutoff day, unplayed (live)      -> NOT
        _m("2026-09-12", 0, 0),          # cutoff day, an earlier kickoff   -> NOT (in play at the cutoff)
        _m("2026-09-05", None, None),    # dated earlier, postponed, no goals -> NOT (goals clause)
        _m("2026-09-13", 3, 3),          # after                              -> NOT
    ])
    k = dc.knowable_before(m, CUTOFF)
    assert k.tolist() == [True, False, False, False, False, False]


def test_rule_is_day_granular_not_timed():
    m = _matches([_m("2026-09-12", 1, 0)])
    assert not dc.knowable_before(m, pd.Timestamp("2026-09-12 23:59:59")).iloc[0]
    assert dc.knowable_before(m, pd.Timestamp("2026-09-13 00:00:00")).iloc[0]


# ----------------------------------------------------- the fit assertion
def test_fit_refuses_a_training_set_with_nan_goals():
    rows = [_m("2026-09-0%d" % (d + 1), (d % 3), (d % 2), home="A" if d % 2 else "B", away="B" if d % 2 else "A")
            for d in range(8)]
    rows.append(_m("2026-09-12", None, None))
    m = _matches(rows)
    with pytest.raises(ValueError) as ei:
        dc._fit_dc_decay(m, ["A", "B"], CUTOFF, 365)
    assert "without a result" in str(ei.value) and "starting point" in str(ei.value)


def test_fit_refuses_an_empty_training_set():
    with pytest.raises(ValueError):
        dc._fit_dc_decay(_matches([]).reindex(columns=["date_parsed", "home_goals", "away_goals", "home", "away"]),
                         ["A", "B"], CUTOFF, 365)


def test_fit_on_played_rows_moves_from_its_starting_point_and_records_a_summary():
    rng = np.random.default_rng(0)
    rows = []
    for d in range(60):
        rows.append(_m(pd.Timestamp("2026-07-01") + pd.Timedelta(days=d), int(rng.poisson(1.6)), int(rng.poisson(0.9)),
                       home="A" if d % 2 else "B", away="B" if d % 2 else "A"))
    p, idx, nt = dc._fit_dc_decay(_matches(rows), ["A", "B"], CUTOFF, 365)
    assert not (np.abs(p[:2 * nt]).max() == 0.0 and abs(p[-2] - 0.25) < 1e-12)     # it moved
    assert dc.LAST_FIT["n_train"] == 60 and dc.LAST_FIT["n_teams"] == 2 and dc.LAST_FIT["iterations"] > 0


# ------------------------------------- one function, used by both sides
def test_the_guard_truncates_with_the_same_function_the_fit_filters_with():
    import asof_reconstruction as ar
    src_guard = inspect.getsource(ar.asof_world)
    src_fit = inspect.getsource(dc.get_fixtures)
    assert "dixon_coles.knowable_before(" in src_guard
    assert "knowable_before(matches, cutoff)" in src_fit
    assert "date_parsed\"] >= cutoff_date" not in src_guard            # the old timed comparison is gone
    assert "date_parsed\"] < cutoff]" not in src_fit


# ------------------------------------------------------ the detector
def _frame(lams_by_step):
    rows = []
    for step, lams in lams_by_step.items():
        for i, lam in enumerate(lams):
            rows.append(dict(horizon_step=step, gw=4 + step, team=f"T{i}", element=100 * step + i,
                             team_lambda=lam, opp_lambda=1.0, e_points=1.0, understat_id=1.0, position="MID",
                             p_dc_hit=0.1, penalty_share=0.0))
    return pd.DataFrame(rows)


def test_detector_raises_under_strict_on_the_starting_point_pattern():
    good = list(np.linspace(0.7, 2.4, 20))
    bad = [float(np.exp(0.25))] * 10 + [1.0] * 10
    f = _frame({0: good, 1: bad})
    with pytest.raises(ld.LiveStrictError) as ei:
        ld.postflight(f, "2026-27", 4, strict=True, horizon=2)
    assert "DEGENERATE at horizon step 1" in str(ei.value) and "starting point" in str(ei.value)


def test_detector_raises_on_two_values_even_if_not_the_starting_point():
    f = _frame({0: [1.3] * 10 + [0.9] * 10})
    with pytest.raises(ld.LiveStrictError):
        ld.postflight(f, "2026-27", 4, strict=True, horizon=1)


def test_detector_is_quiet_on_a_healthy_step_and_reports_when_not_strict():
    f = _frame({0: list(np.linspace(0.7, 2.4, 20)), 1: [float(np.exp(0.25))] * 10 + [1.0] * 10})
    findings = ld.postflight(f, "2026-27", 4, strict=False, horizon=2)
    assert any("DEGENERATE at horizon step 1" in x for x in findings)
    assert not any("step 0" in x and "DEGENERATE" in x for x in findings)
