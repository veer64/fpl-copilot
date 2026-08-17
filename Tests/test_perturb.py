"""Tests for the Instrument B perturbation layer.

The season-scale falsification lives in eval/falsify_perturbation.py (five full sims, far
too slow for the unit suite). What is pinned here is the jitter table, because every
interval Instrument B produces depends on two properties that would fail silently:

  - the same (element, gw, seed) must give the same draw in BOTH arms, or the paired
    difference cancels nothing and every interval is inflated;
  - the draw must not depend on row order, or two shards disagree about what "draw 7"
    means and pooling them is incoherent.

Both were got wrong once already -- the first CRN check compared two independently
merged frames positionally and reported a failure that was its own bug.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import perturb  # noqa: E402


def _frame(elements=(1, 2, 3), gws=(1, 2), cutoffs=(1, 2), base=3.0):
    rows = [{"element": e, "gw": g, "cutoff": c, "e_points": base + 0.1 * e}
            for e in elements for g in gws for c in cutoffs if c <= g]
    return pd.DataFrame(rows)


def test_same_seed_gives_same_table():
    f = [_frame()]
    assert perturb.jitter_table(f, 0.25, seed=7).equals(
        perturb.jitter_table(f, 0.25, seed=7))


def test_different_seed_gives_different_table():
    f = [_frame()]
    a = perturb.jitter_table(f, 0.25, seed=7)["_jitter"].values
    b = perturb.jitter_table(f, 0.25, seed=8)["_jitter"].values
    assert not np.allclose(a, b)


def test_table_is_row_order_blind():
    """Shards must agree on what a draw means, whatever order they read rows in."""
    f = _frame()
    a = perturb.jitter_table([f], 0.25, seed=7).reset_index(drop=True)
    b = perturb.jitter_table([f.sample(frac=1.0, random_state=1)], 0.25,
                             seed=7).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_crn_identical_jitter_across_arms():
    """Two arms differing in e_points must receive the SAME shift, away from the clip."""
    a = _frame(base=3.0)
    b = _frame(base=5.0)
    t = perturb.jitter_table([a, b], 0.25, seed=7)
    ja, jb = perturb.apply_jitter(a, t), perturb.apply_jitter(b, t)
    key = ["element", "gw", "cutoff"]
    m = (ja.set_index(key).e_points - a.set_index(key).e_points).rename("sa").to_frame()
    m["sb"] = jb.set_index(key).e_points - b.set_index(key).e_points
    assert np.allclose(m.sa, m.sb, atol=1e-12)


def test_jitter_spans_the_union_of_keys():
    """An arm carrying rows the other lacks must still share draws on the overlap."""
    a = _frame(elements=(1, 2))
    b = _frame(elements=(2, 3))
    t = perturb.jitter_table([a, b], 0.25, seed=7)
    assert set(t.element) == {1, 2, 3}
    ja, jb = perturb.apply_jitter(a, t), perturb.apply_jitter(b, t)
    key = ["element", "gw", "cutoff"]
    sa = (ja.set_index(key).e_points - a.set_index(key).e_points)
    sb = (jb.set_index(key).e_points - b.set_index(key).e_points)
    shared = sa.index.intersection(sb.index)
    assert len(shared)
    assert np.allclose(sa.loc[shared], sb.loc[shared], atol=1e-12)


def test_shared_across_cutoffs():
    """A player overrated at cutoff k stays overrated at k+1 -- the error does not
    reset every week, so neither does the draw."""
    f = _frame(elements=(1,), gws=(2,), cutoffs=(1, 2))
    t = perturb.jitter_table([f], 0.25, seed=7)
    j = perturb.apply_jitter(f, t)
    shifts = (j.e_points.values - f.e_points.values)
    assert np.allclose(shifts, shifts[0], atol=1e-12)


def test_eps_zero_is_a_no_op():
    f = _frame()
    t = perturb.jitter_table([f], 0.0, seed=1)
    out = perturb.apply_jitter(f, t)
    assert np.allclose(out.e_points, f.e_points)


def test_clip_prevents_negative_predictions():
    f = _frame(base=0.0)
    t = perturb.jitter_table([f], 5.0, seed=3)
    out = perturb.apply_jitter(f, t)
    assert (out.e_points >= 0).all()


def test_apply_jitter_preserves_row_count():
    f = _frame()
    t = perturb.jitter_table([f], 0.25, seed=7)
    assert len(perturb.apply_jitter(f, t)) == len(f)


def test_summarise_pairs_over_draws():
    df = pd.DataFrame({"eps": [0.25] * 5, "draw": range(5),
                       "arm_a": [1984] * 5, "arm_b": [1990, 2000, 1980, 1995, 1985]})
    df["delta"] = df.arm_b - df.arm_a
    s = perturb.summarise(df).iloc[0]
    assert s.draws == 5
    assert s.mean_delta == pytest.approx(6.0)
    assert s.b_wins_pct == pytest.approx(80.0)
