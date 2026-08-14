"""Tests for the path-controlled harness summary statistic.

The harness itself is falsified end-to-end by falsify_pathcontrol.py (which needs a
full season and is far too slow for the unit suite). What is pinned here is the
summary layer, because that is where a real defect was found: averaging a
single-gameweek treatment over every anchor divided a +53 effect by 38 and reported
+1.4. A statistic that silently dilutes the thing it measures is worse than no
statistic, so both the dilution and the refusal-to-quote-a-CI are locked down.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import pathcontrol as pc  # noqa: E402


def _frame(deltas, W=1):
    """One row per (anchor, ref); both refs agree, as they do when arms share state."""
    rows = []
    for anchor, d in enumerate(deltas, start=1):
        for ref in ("A", "B"):
            rows.append({"W": W, "anchor": anchor, "ref": ref,
                         "a_points": 50.0, "b_points": 50.0 + d, "delta": d})
    return pd.DataFrame(rows)


def test_sparse_treatment_is_not_diluted():
    """A chip active in one gameweek out of 38 must report its own size."""
    deltas = [0.0] * 38
    deltas[3] = 53.0
    s = pc.summarise(_frame(deltas)).iloc[0]
    assert s.n_active == 1
    assert s.mean_active_anchors == 53.0
    assert round(s.mean_all_anchors, 3) == round(53.0 / 38, 3)


def test_sparse_treatment_gets_no_confidence_interval():
    """Three observations do not support an interval, and a block bootstrap of
    mostly-zeros returns a lower bound of exactly 0 that looks like a result."""
    deltas = [0.0] * 38
    for i in (1, 2, 3):
        deltas[i] = 60.0
    s = pc.summarise(_frame(deltas)).iloc[0]
    assert s.n_active == 3
    assert np.isnan(s.ci_low) and np.isnan(s.ci_high)
    assert s.excludes_0 is None


def test_pervasive_treatment_uses_all_anchors_and_gets_an_interval():
    rng = np.random.default_rng(0)
    deltas = list(rng.normal(2.0, 1.0, 38))
    s = pc.summarise(_frame(deltas)).iloc[0]
    assert s.n_active == 38
    assert s.mean_all_anchors == s.mean_active_anchors
    assert not np.isnan(s.ci_low)
    # `assert x` not `x is True`: an all-bool column comes back as numpy's bool dtype.
    assert s.excludes_0  # a clear +2 effect should clear zero


def test_null_treatment_summarises_to_zero():
    s = pc.summarise(_frame([0.0] * 38)).iloc[0]
    assert s.n_active == 0
    assert s.mean_all_anchors == 0.0
    assert s.mean_active_anchors == 0.0
    assert s.tied == 38


def test_crossover_directions_reported_separately():
    """If the two reference directions disagree, that must stay visible rather than
    being averaged away -- it is the signal that one arm is being flattered."""
    rows = []
    for anchor in range(1, 11):
        rows.append({"W": 1, "anchor": anchor, "ref": "A",
                     "a_points": 50.0, "b_points": 60.0, "delta": 10.0})
        rows.append({"W": 1, "anchor": anchor, "ref": "B",
                     "a_points": 50.0, "b_points": 48.0, "delta": -2.0})
    s = pc.summarise(pd.DataFrame(rows)).iloc[0]
    assert s.delta_ref_A == 10.0
    assert s.delta_ref_B == -2.0
    assert s.mean_all_anchors == 4.0  # the crossover average
