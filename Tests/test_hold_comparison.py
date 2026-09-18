"""The hold comparison (2026-09-18, Logs/hold_comparison_log_2026-09-18.md).

`propose_transfers` reported a gain but never what doing nothing scores, so a
reader could not tell a clear gain from a near-tie -- on a system where roughly
20% of backtest deadlines were decided by margins under 0.02, with no tie-break
principle and two exact ties in 2025-26.

The contract these tests hold to:
  * the baseline is "hold THIS gameweek only" -- step 0 forced to zero
    transfers, steps 1-5 free, so the rolled free transfer is earned and spent
    inside the plan;
  * it MEASURES and never decides -- the recommendation is byte-for-byte what
    the move solve produced, and HOLD_PREFERENCE_EPS (the constant that WOULD
    change the decision) stays None;
  * it is OFF by default, so the backtest is bit-identical.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO))

import simulator                                    # noqa: E402
import transfer_mip                                 # noqa: E402
from squad_state import SquadState                  # noqa: E402

POSNS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _season_df(gws, owned_pts=2.0, outsider_pts=9.0):
    """A minimal horizon-UNAWARE frame: gw_slice takes it with cutoff=None."""
    rows = []
    for g in gws:
        for i, pos in zip(range(1, 16), POSNS):
            rows.append(dict(gw=g, element=i, name=f"own{i}", position=pos,
                             team=f"T{i % 7}", value=45, e_points=owned_pts))
        # two attractive outsiders in positions the squad can swap into
        rows.append(dict(gw=g, element=101, name="star_mid", position="MID",
                         team="TZ", value=50, e_points=outsider_pts))
        rows.append(dict(gw=g, element=102, name="star_fwd", position="FWD",
                         team="TY", value=50, e_points=outsider_pts))
    return pd.DataFrame(rows)


def _state(bank=100, free_transfers=1):
    sq = pd.DataFrame([dict(element=i, position=pos, purchase_price=45,
                            name=f"own{i}", team=f"T{i % 7}")
                       for i, pos in zip(range(1, 16), POSNS)])
    return SquadState(sq, bank=bank, free_transfers=free_transfers)


def _decide(df, state, gws, **kw):
    prices = {e: 45 for e in state.elements}
    pool0 = simulator.gw_slice(df, gws[0])
    return simulator.decide_gameweek_mip(
        df, gws[0], state, pool0, prices, gws, mode="balanced",
        horizon=len(gws), decay=0.5, return_plan=True, **kw)


# --------------------------------------------------------------- the gate
def test_hold_preference_eps_is_still_none():
    """The constant that would CHANGE the recommendation must stay unset. The
    hold comparison reports a number; it must never quietly decide with it."""
    assert simulator.HOLD_PREFERENCE_EPS is None


# ------------------------------------------------ off by default = backtest safe
def test_default_is_off_so_the_backtest_path_is_untouched():
    df, st, gws = _season_df([1, 2]), _state(), [1, 2]
    team, transfers, step, eff_h, plan = _decide(df, st, gws)
    for k in ("hold_objective", "hold_plan", "hold_team", "hold_solved", "hold_seconds"):
        assert k not in step, f"{k} leaked into the default path"
    assert step["hold_margin"] is None and step["hold_applied"] is False


def test_hold_compare_does_not_change_the_recommendation():
    """The whole point: same team, same transfers, same objective."""
    df, gws = _season_df([1, 2]), [1, 2]
    a = _decide(df, _state(), gws)
    b = _decide(df, _state(), gws, hold_compare=True)
    team_a, tr_a, step_a, _, _ = a
    team_b, tr_b, step_b, _, _ = b
    assert tr_a == tr_b
    assert step_a["objective"] == step_b["objective"]
    assert step_a["squad"] == step_b["squad"]
    assert sorted(step_a["starters"]) == sorted(step_b["starters"])
    assert step_a["captain"] == step_b["captain"]
    pd.testing.assert_frame_equal(team_a.reset_index(drop=True), team_b.reset_index(drop=True))


# ------------------------------------------------------------- the measurement
def test_hold_compare_measures_the_gap_when_the_plan_moves():
    df, gws = _season_df([1, 2]), [1, 2]
    _, transfers, step, _, _ = _decide(df, _state(), gws, hold_compare=True)
    assert step["transfers_made"] > 0, "sanity: the free outsiders make moving worth it"
    assert step["hold_solved"] is True
    assert step["hold_status"] == "Optimal"
    assert step["hold_objective"] is not None
    # the hold can never beat the unconstrained optimum, so the gap is >= 0
    assert step["hold_margin"] == pytest.approx(
        float(step["objective"]) - float(step["hold_objective"]))
    assert step["hold_margin"] >= 0
    assert step["hold_seconds"] is not None and step["hold_seconds"] >= 0


def test_the_hold_plan_holds_step_zero_and_leaves_later_steps_free():
    df, gws = _season_df([1, 2]), [1, 2]
    _, _, step, _, _ = _decide(df, _state(), gws, hold_compare=True)
    hp = step["hold_plan"]
    assert hp[0]["transfers_made"] == 0 and hp[0]["buys"] == [] and hp[0]["sells"] == []
    assert hp[1]["transfers_made"] >= 1, "hold THIS week only -- later steps stay free"


def test_the_rolled_free_transfer_is_earned_inside_the_hold_plan():
    """Holding at step 0 must leave ft[1] = ft[0] + 1, else the hold is valued
    as though the transfer vanished."""
    df, gws = _season_df([1, 2]), [1, 2]
    _, _, step, _, _ = _decide(df, _state(free_transfers=1), gws, hold_compare=True)
    hp = step["hold_plan"]
    assert hp[0]["free_transfers"] == 1
    assert hp[1]["free_transfers"] == 2, "the rolled transfer was not credited"


def test_the_hold_xi_is_re_solved_not_frozen():
    """The XI is a decision variable at every step, so holding is not penalised
    by a lineup the manager would have fixed anyway."""
    df, gws = _season_df([1, 2]), [1, 2]
    _, _, step, _, _ = _decide(df, _state(), gws, hold_compare=True)
    hold_team = step["hold_team"]
    assert hold_team is not None
    assert (hold_team["role"] != "bench").sum() == 11
    assert (hold_team["role"] == "CAPTAIN").sum() == 1


# -------------------------------------------- the skip when the move already holds
def test_no_second_solve_when_the_move_solve_already_holds():
    """If the unconstrained optimum makes no step-0 transfer, forcing
    used[0] == 0 cannot change it: the gap is exactly zero and paying for a
    second solve would be waste, not rigour."""
    df = _season_df([1, 2], owned_pts=9.0, outsider_pts=0.1)   # nothing worth buying
    _, _, step, _, plan = _decide(df, _state(), [1, 2], hold_compare=True)
    assert step["transfers_made"] == 0, "sanity: there is nothing worth transferring for"
    assert step["hold_solved"] is False
    assert step["hold_seconds"] == 0.0
    assert step["hold_margin"] == 0.0
    assert step["hold_objective"] == float(step["objective"])
    assert step["hold_plan"] is plan
    assert step["hold_team"] is None                # the caller reuses the move team


# --------------------------------------------------------------- the schema
def test_plan_kind_and_paired_proposal_id_are_persisted_columns():
    import db_write
    assert "plan_kind" in db_write.PLAN_COLS
    assert "paired_proposal_id" in db_write.PLAN_COLS
    ddl = db_write.SCHEMA_SQL if hasattr(db_write, "SCHEMA_SQL") else ""
    if not ddl:
        ddl = Path(REPO / "db_write.py").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS plan_kind" in ddl
    assert "ADD COLUMN IF NOT EXISTS paired_proposal_id" in ddl


def test_the_gap_is_not_stored_as_its_own_column():
    """Both objectives are on the rows; a stored copy of their difference is one
    more thing that can disagree with them."""
    import db_write
    assert not any("gap" in c for c in db_write.PLAN_COLS)


# ------------------------------------------------- the timing wording was revised
def test_the_wait_wording_matches_two_solves():
    import model_tools
    for blob in (model_tools.propose_transfers.__doc__,
                 Path(REPO / "agent.py").read_text(encoding="utf-8"),
                 Path(REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")):
        assert "ten to forty seconds" not in blob
    assert "twenty to sixty seconds" in model_tools.propose_transfers.__doc__
