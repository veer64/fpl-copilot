# KNOWN_ISSUES #15 guard: defensive-contribution hits must come from the
# per-player model, not the position base-rate fallback.
#
# The defect: walkforward_season.py passed an EMPTY p_dc_hit frame for every
# season including 2025-26, so assembly's fallback chain put every player on
# DC_BASE (max 0.136 = MID) and the canonical files silently priced the
# 2025-26 defensive-contribution rule at position base rates. The fix is one
# shared path, defensive.get_dc_hits, used by BOTH writers.
#
# NAMING TRAP, for the reader: p_dc_hit / defensive.py = the DEFENSIVE
# CONTRIBUTION scoring rule; dixon_coles.py = the team-GOALS model. Both get
# called "DC" in the logs. They are unrelated.

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

CANONICAL_2526 = REPO / "data" / "walkforward_h6_2025_26.parquet"
BASE_RATE_MAX = 0.136          # DC_BASE["MID"], the largest base rate


def test_pre_rule_season_returns_empty_typed_frame():
    import defensive
    out = defensive.get_dc_hits("2023-24", 20, [20, 21, 22])
    assert list(out.columns) == ["player_id", "position", "p_dc_hit", "gw"]
    assert len(out) == 0


@pytest.mark.skipif(not CANONICAL_2526.exists(), reason="canonical 2025-26 absent")
def test_canonical_2526_carries_per_player_dc_not_base_rates():
    """Variance of p_dc_hit must exceed what base rates alone can produce.
    Base-rate-only files cap at 0.136 and carry a handful of distinct values;
    the per-player model reaches ~0.80 with hundreds of distinct estimates."""
    df = pd.read_parquet(CANONICAL_2526, columns=["p_dc_hit", "position",
                                                  "horizon_step"])
    s0 = df[df["horizon_step"] == 0]
    assert s0["p_dc_hit"].max() > 0.2, (
        f"p_dc_hit max {s0['p_dc_hit'].max():.3f} <= 0.2: the file carries "
        f"base rates -- the KNOWN_ISSUES #15 defect is back")
    n_def = s0[s0["position"] == "DEF"]["p_dc_hit"].nunique()
    assert n_def > 100, (
        f"only {n_def} distinct DEF p_dc_hit values -- base-rate-like, "
        f"expected hundreds from the per-player model")
