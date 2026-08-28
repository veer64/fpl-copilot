"""Hold preference at near-ties (Logs/hold_preference_prereg.md): gate semantics.

The gate rests None. `force_hold=True` must forbid every step-0 transfer and leave later steps free; with
the gate off the simulator's decision path must not consult it at all (the log stamps hold_pref_eps = -1).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "squad"))
import simulator  # noqa: E402
import transfer_mip  # noqa: E402


def test_gate_rests_none_on_disk():
    assert simulator.HOLD_PREFERENCE_EPS is None, (
        "HOLD_PREFERENCE_EPS was set on disk -- the hold preference is a pre-registered TEST, not adopted "
        "(Logs/hold_preference_prereg.md)")


def _pool(gw, players):
    return pd.DataFrame([dict(element=e, name=f"p{e}", position=pos, team=f"T{e % 7}", value=v, e_points=p)
                         for e, pos, v, p in players])


def test_force_hold_forbids_step0_transfers_only():
    # 15 owned players + 2 attractive outsiders; two-step horizon; enough bank to buy.
    owned = [(i, pos, 45, 2.0) for i, pos in zip(range(1, 16), ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3)]
    outsiders = [(101, "MID", 50, 9.0), (102, "FWD", 50, 9.0)]
    pools = {1: _pool(1, owned + outsiders), 2: _pool(2, owned + outsiders)}
    prices = {e: 45 for e, *_ in owned}
    st, plan = transfer_mip.build_and_solve(pools, current_squad=[e for e, *_ in owned], purchase_prices=prices,
                                            bank=100, free_transfers=1, decay=0.5)
    assert st == "Optimal" and plan[0]["transfers_made"] >= 1, "sanity: without force_hold the solver transfers"
    st_h, plan_h = transfer_mip.build_and_solve(pools, current_squad=[e for e, *_ in owned], purchase_prices=prices,
                                                bank=100, free_transfers=1, decay=0.5, force_hold=True)
    assert st_h == "Optimal"
    assert plan_h[0]["transfers_made"] == 0 and plan_h[0]["buys"] == [] and plan_h[0]["sells"] == []
    assert plan_h[1]["transfers_made"] >= 1, "later steps stay free to plan the same move"
    assert plan[0]["objective"] >= plan_h[0]["objective"], "the hold plan can never beat the unconstrained optimum"
