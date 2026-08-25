"""
Horizon minutes gate (squad/horizon_minutes.py).

The per-step minutes model is gated behind a single constant that also stamps
provenance per row. Until a lever passes the acceptance test in
Logs/horizon_minutes_log.md the gate must rest False, unknown levers must be
refused loudly, and the stamps must be present on every emitted row. These
tests pin the gate and the stamp contract without training anything.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))

import horizon_minutes as hm  # noqa: E402


def test_gate_rests_false_until_a_lever_is_adopted():
    assert hm.HORIZON_MINUTES_ACTIVE is False


def test_lever_list_is_known_and_refit_first():
    assert hm.HORIZON_LEVERS[0] == "refit"
    assert set(hm.HORIZON_LEVERS) <= set(hm.KNOWN_LEVERS)


def test_unknown_lever_is_refused():
    with pytest.raises(ValueError, match="unknown horizon lever"):
        hm._check_levers(("refit", "afcon"))
    with pytest.raises(ValueError, match="base lever"):
        hm._check_levers(("suspensions",))


def test_lagged_pairs_join_features_at_g_to_labels_at_g_plus_k():
    import pandas as pd
    csx = pd.DataFrame({"season": ["s"] * 4, "element": [1, 1, 1, 2], "GW": [1, 2, 3, 1], "x": [10, 20, 30, 40]})
    labels = pd.DataFrame({"season": ["s"] * 4, "element": [1, 1, 1, 2], "GW": [1, 2, 3, 1],
                           "starts": [1, 0, 1, 0], "minutes": [90, 0, 60, 0],
                           "minutes_capped": [90, 0, 60, 0], "played_60": [1, 0, 1, 0], "came_on": [1, 0, 1, 0]})
    p = hm._pairs(csx, labels, k=2)
    assert len(p) == 1 and int(p["GW"].iloc[0]) == 1 and int(p["GW_label"].iloc[0]) == 3
    assert int(p["x"].iloc[0]) == 10 and int(p["y_minutes_capped"].iloc[0]) == 60


def test_train_mask_uses_the_label_gameweek_not_the_feature_gameweek():
    import pandas as pd
    pairs = pd.DataFrame({"season": ["cur", "cur", "prior"], "GW": [5, 6, 30], "GW_label": [8, 9, 33]})
    m = hm._train_mask(pairs, up_to_gw=9, train_seasons=["prior"], predict_season="cur")
    # label GW 8 < 9 is known at cutoff 9; label GW 9 is not; prior seasons always
    assert m.tolist() == [True, False, True]
