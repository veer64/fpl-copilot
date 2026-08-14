"""
FPL Copilot — Path-controlled evaluation (Instrument A: windowed restart, crossover)

WHY THIS EXISTS
---------------
A season total cannot measure a change that alters which players get picked. One
different pick at GW1 sends the rolling re-solve down a different branch, and with
Spearman ~0.10 among 60+ starters that branch is close to a coin flip. Squad overlap
between two arms decays to 4/15 by May. Every recent experiment died here:

    chips        local +12.3 (W3), season -26.2, path sd ~52
    decay sweep  1973 / 1880 / 1887 / 1955 across neighbouring values
    availability -46 with CI [-123, +28]; per-gameweek deltas summing 334 to net -46

Those are comparisons of different seasons, not of different policies.

WHAT THIS MEASURES — AND WHAT IT CANNOT
---------------------------------------
Both arms are restarted from the SAME state at every anchor gameweek, run freely for
W gameweeks against the same realised outcomes, then discarded. `W` is a dial on how
much compounding is admitted:

    W=1   pure decision quality. Zero path divergence. Blind to compounding.
    W=3   decision quality plus three weeks of consequences.
    W=38  the status quo: one observation, all the noise.

These are DIFFERENT ESTIMANDS, not the same estimand measured better. W=1 answers
"given the same state, does B choose better?" It is structurally blind to squad-value
growth, free-transfer banking, chip timing, and any effect whose mechanism is
"sacrifice now to set up later" — such a treatment will score neutral-to-negative
here and that is the instrument working, not failing. Horizon and decay tuning are
compounding parameters by construction and a W=1 number for them is meaningless.

CROSSOVER
---------
Anchoring only on A's trajectory means B is never allowed to build its own squad,
which flatters the incumbent. Every anchor is therefore evaluated twice, once on each
arm's own trajectory, and the two estimates averaged.

An arm replayed from a state on its OWN trajectory reproduces that trajectory exactly
(the simulator is deterministic after the `sorted()` fix), so those halves are read
straight off the reference run rather than recomputed. `selfreplay_matches_reference`
in the falsification suite checks that identity rather than assuming it.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimize import optimize_squad
from scoring import assign_bench_order, score_gameweek
from simulator import (_pool_with_owned, decide_gameweek_mip, gw_actuals,
                       gw_slice, solution_to_squad)
from squad_state import STARTING_BUDGET, SquadState
from transfer_mip import DEFAULT_DECAY, DEFAULT_HORIZON

DEFAULT_W = (1, 2, 3, 5)


# ---------------------------------------------------------------------------
# One arm = one set of predictions, plus whatever chips it is allowed
# ---------------------------------------------------------------------------
class Arm:
    def __init__(self, name, season_df, wildcard_gws=(), mode="balanced",
                 horizon=DEFAULT_HORIZON, decay=DEFAULT_DECAY):
        self.name = name
        self.season_df = season_df
        self.wildcard_gws = set(int(g) for g in wildcard_gws)
        self.mode = mode
        self.horizon = horizon
        self.decay = decay
        self.all_gws = sorted(season_df["gw"].unique())


def _replay(arm, gws, state=None):
    """Replay `gws` from `state` (None = build a squad from scratch).

    Deliberately mirrors simulate_season's loop rather than calling it, because that
    function always starts at GW1 with no squad. The duplication is the risk this
    module carries, so `reproduces_simulate_season` in the falsification suite pins
    the two together at W=38.

    Returns (per-gameweek rows, final state). `state` is mutated; pass a restored
    copy if the caller needs to keep it.
    """
    df = arm.season_df
    horizon_aware = "cutoff" in df.columns
    rows = []

    for gw in gws:
        pool = gw_slice(df, gw, cutoff=gw if horizon_aware else None)
        actuals = gw_actuals(df, gw)
        prices = dict(zip(pool["element"], pool["value"]))
        is_wildcard = gw in arm.wildcard_gws

        if state is None:
            prob, sol = optimize_squad(pool, mode=arm.mode)
            team = solution_to_squad(pool, sol)
            transfers = []
            start = team.copy()
            start["purchase_price"] = start["value"].astype(int)
            state = SquadState(start,
                               bank=STARTING_BUDGET - int(start["purchase_price"].sum()),
                               free_transfers=1)
        else:
            team, transfers, _step, _eff = decide_gameweek_mip(
                df, gw, state, pool, prices, arm.all_gws, mode=arm.mode,
                horizon=arm.horizon, decay=arm.decay, wildcard=is_wildcard)
            in_rows = {b: pool[pool["element"] == b].iloc[0] for _, b in transfers}
            state.make_transfers(transfers, in_rows, prices)

        roles = team.set_index("element")[["role", "bench_order"]]
        state.squad = state.squad.drop(columns=["role", "bench_order"], errors="ignore")
        state.squad = state.squad.merge(roles, left_on="element", right_index=True,
                                        how="left")

        n = len(transfers)
        if is_wildcard:
            free_before = n
        else:
            free_before = state.free_transfers
            state.spend_transfers(n)

        result = score_gameweek(state.squad, actuals, transfers_made=n,
                                free_transfers=free_before)
        state.end_gameweek(result["points"])
        rows.append({"gw": gw, "points": result["points"], "hit": result["hit"],
                     "n_transfers": n, "elements": list(state.elements)})

    return rows, state


def trajectory(arm, gws=None):
    """Run the arm start to finish, capturing the state BEFORE each decision.

    The snapshots are what both arms get restarted from, so they must be taken at
    the top of the gameweek — after last week's points were banked, before this
    week's transfer.
    """
    gws = gws or arm.all_gws
    states, rows = {}, []
    state = None
    for gw in gws:
        states[gw] = state.snapshot() if state is not None else None
        r, state = _replay(arm, [gw], state)
        rows.extend(r)
    return pd.DataFrame(rows), states


def _restored(snap):
    """A fresh SquadState from a snapshot, with the window's score starting at zero."""
    if snap is None:
        return None
    s = SquadState(snap["squad"].copy(deep=True), bank=int(snap["bank"]),
                   free_transfers=int(snap["free_transfers"]))
    return s


def windowed(arm_a, arm_b, W, anchors=None, ref_log_a=None, states_a=None,
             ref_log_b=None, states_b=None, verbose=True):
    """Crossover windowed comparison at window length W.

    Returns one row per (anchor, reference arm) with both arms' W-week totals.
    """
    if ref_log_a is None:
        ref_log_a, states_a = trajectory(arm_a)
    if ref_log_b is None:
        ref_log_b, states_b = trajectory(arm_b)

    gws = arm_a.all_gws
    anchors = anchors or gws
    pts_a = dict(zip(ref_log_a.gw, ref_log_a.points))
    pts_b = dict(zip(ref_log_b.gw, ref_log_b.points))

    rows = []
    for k in anchors:
        window = [g for g in gws if k <= g < k + W]
        if len(window) < W:
            continue  # partial window at the end of the season: not comparable
        for ref, states, own_pts, own_arm, other_arm in (
                ("A", states_a, pts_a, arm_a, arm_b),
                ("B", states_b, pts_b, arm_b, arm_a)):
            # The reference arm replayed from its own state reproduces itself, so
            # its total is read off the reference log rather than recomputed.
            own_total = sum(own_pts[g] for g in window)
            other_rows, _ = _replay(other_arm, window, _restored(states[k]))
            other_total = sum(r["points"] for r in other_rows)
            a_total = own_total if ref == "A" else other_total
            b_total = other_total if ref == "A" else own_total
            rows.append({"W": W, "anchor": k, "ref": ref,
                         "a_points": a_total, "b_points": b_total,
                         "delta": b_total - a_total})
        if verbose:
            print(f"  W={W} anchor GW{k:<2d} done", end="\r", flush=True)
    if verbose:
        print()
    return pd.DataFrame(rows)


MIN_ACTIVE_FOR_CI = 8


def summarise(df, block=4, n_boot=2000, seed=0):
    """Crossover point estimate and a block-bootstrap interval over anchors.

    PERVASIVE vs SPARSE TREATMENTS, and why both columns are here
    ------------------------------------------------------------
    A treatment that changes predictions everywhere (a model change) is active at
    every anchor, and the mean over all anchors is the estimate you want.

    A treatment active in ONE gameweek (a chip) leaves almost every anchor exactly
    tied, and averaging over all of them divides the effect by the number of anchors
    -- a wildcard worth +53 in its own week reports as +1.4 across 38 anchors. That
    is dilution, not measurement.

    So both are reported, and `n_active` tells you which to read. With only a handful
    of active anchors an interval over them is not meaningful, and it is left blank
    rather than printed as a spuriously narrow number: a block bootstrap of mostly
    zeros happily returns a lower bound of exactly 0, which looks like a result and
    is not.

    Anchors overlap when W>1, so their differences are correlated; the block
    bootstrap over anchor order is what keeps the interval honest about that.
    """
    from bootstrap import block_bootstrap, interval

    out = []
    for W, g in df.groupby("W"):
        # Average the two reference directions at each anchor first — that pairing
        # is the crossover, and bootstrapping it as one unit keeps it intact.
        per_anchor = g.groupby("anchor")["delta"].mean().sort_index()
        active = per_anchor[per_anchor != 0]
        by_ref = g.groupby("ref")["delta"].mean()

        row = {
            "W": int(W),
            "n_anchors": len(per_anchor),
            "n_active": len(active),
            "mean_all_anchors": round(float(per_anchor.mean()), 3),
            "mean_active_anchors": round(float(active.mean()), 3) if len(active) else 0.0,
            "delta_ref_A": round(float(by_ref.get("A", np.nan)), 3),
            "delta_ref_B": round(float(by_ref.get("B", np.nan)), 3),
            "b_better": int((per_anchor > 0).sum()),
            "a_better": int((per_anchor < 0).sum()),
            "tied": int((per_anchor == 0).sum()),
        }
        if len(active) >= MIN_ACTIVE_FOR_CI:
            samples = block_bootstrap(per_anchor.values, block_length=block,
                                      n_boot=n_boot, seed=seed)
            lo, hi = interval(samples / len(per_anchor))
            row.update(ci_low=round(lo, 3), ci_high=round(hi, 3),
                       excludes_0=bool(lo > 0 or hi < 0))
        else:
            row.update(ci_low=np.nan, ci_high=np.nan, excludes_0=None)
        out.append(row)
    return pd.DataFrame(out)
