"""
FPL Copilot — Multi-gameweek transfer MIP (master plan section 3.6)

Replaces the 15-solve search in simulator.decide_gameweek with a single
optimization that decides HOW MANY transfers to make, WHICH ones, and whether a
-4 hit is worth paying -- across a rolling horizon rather than one gameweek.

WHY A MIP INSTEAD OF A SEARCH
-----------------------------
The v1 policy was a loop wrapped around an optimizer: try keeping the squad, try
selling each of the 15, take the best of 16 answers. That structure has "make at
most one transfer" baked into it, and no amount of extra looping fixes the real
gap -- combination moves (sell two mid-price defenders to afford one premium) are
invisible because neither sale improves anything on its own.

Here, transfers become DECISION VARIABLES. The number of transfers is something
the solver optimizes rather than something the caller fixed in advance.

THE FORMULATION
---------------
Per player i, per gameweek t in the horizon:

    pick[i,t]     in squad at t
    buy[i,t]      entered the squad at t
    sell[i,t]     left the squad at t
    start[i,t]    in the XI at t
    captain[i,t]  wears the armband at t
    vice[i,t]     backup armband at t

The constraint that makes a squad have a PAST -- squad continuity:

    pick[i,t] = pick[i,t-1] + buy[i,t] - sell[i,t]

with pick[i,-1] being the squad actually held when the solve begins. A player
cannot be bought and sold in the same gameweek (buy + sell <= 1).

THE HIT PENALTY (and the linearization it needs)
------------------------------------------------
    transfers[t] = sum_i buy[i,t]
    hits[t]      = max(0, transfers[t] - free_transfers[t])

`max` is not linear, so it is expressed with an auxiliary integer variable:

    hits[t] >= transfers[t] - free_transfers[t]
    hits[t] >= 0

and hits[t] carries a NEGATIVE coefficient in a MAXIMIZED objective. That is the
whole trick: the solver has every incentive to push hits[t] down to its lower
bound, so the >= constraints bind exactly where max() would have. Writing it as
an equality would be both unnecessary and harder to solve.

FREE TRANSFER DYNAMICS
----------------------
    ft[t] = min(MAX_FT, max(0, ft[t-1] - used[t-1]) + 1)

Free transfers must be DECISION VARIABLES, not a precomputed schedule. An earlier
version projected them forward from a guessed transfer count, and that guess
turned out to be a fixed point: assume one transfer per week, get one free
transfer per week back, and the solver simply spent exactly its assumed allowance
every gameweek. Given five free transfers it made five transfers a week, forever.
The assumption had become the answer, and banking a transfer was impossible.

Now ft[t] is a variable, bounded by:

    ft[t] <= MAX_FT
    ft[t] <= ft[t-1] - used[t-1] + hits[t-1] + 1
    ft[t] >= 0

The `min` needs no extra machinery: larger ft[t] loosens the hit constraint below,
so the solver already wants ft[t] as large as possible and the upper bounds bind
exactly where min() would.

The `max(0, ...)` is handled by the hits[t-1] term. When no hit is taken it
contributes nothing and the rule reads exactly as written. When h hits ARE taken,
used = ft + h at the optimum, so ft[t-1] - used[t-1] + hits[t-1] = 0 and the
manager correctly gets one free transfer back from zero rather than a negative
balance. No big-M, no indicator variables.

One degeneracy worth naming: in principle the solver could inflate hits[t-1] to
buy itself a larger ft[t]. It never pays -- a hit costs 4 * decay^(t-1) while the
free transfer it would buy is worth at most 4 * decay^t, and decay < 1 -- so the
trade is strictly unprofitable for any decay below 1.0 and merely tied at 1.0.

TIME DECAY
----------
A GW+6 prediction deserves less trust than a GW+1 prediction, so future gameweeks
are discounted by DECAY^t (default 0.85). At t=5 that is 0.44 -- the solver still
plans ahead, but will not sacrifice real points now for speculative points later.

ROLLING HORIZON
---------------
Only the FIRST gameweek of the plan is executed. Next gameweek the whole thing is
re-solved with fresh data. The plan is a guide, not a commitment.

The window shrinks at the end of the season (at GW36 only GW36-38 remain). That
is correct, not degradation: a manager in May genuinely has no future to save for,
and real managers become short-termist in the run-in for exactly this reason. The
effective horizon is logged per gameweek so the behaviour is visible.

THIS APPROXIMATES A STOCHASTIC PROGRAM
--------------------------------------
The exact problem -- decisions under uncertainty over a 38-week horizon with
recourse -- is an enormous stochastic program. Rolling-horizon re-solving with
point predictions is an approximation. Everyone approximates; saying so plainly
is the honest framing, and it is what the master plan asks for in the writeup.
"""

import sys
from pathlib import Path

import pandas as pd
import pulp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimize import (
    SQUAD_SIZE, XI_SIZE, POSITION_LIMITS, FORMATION, MAX_PER_CLUB,
    VICE_WEIGHT, resolve_bench_weight, _default_solver, _is_set,
)
from squad_state import sell_price, MAX_FREE_TRANSFERS

HIT_COST = 4
DEFAULT_HORIZON = 6
DEFAULT_DECAY = 0.85


def build_and_solve(
    pool_by_gw,
    current_squad,
    purchase_prices,
    bank,
    free_transfers,
    mode="balanced",
    bench_weight=None,
    decay=DEFAULT_DECAY,
    wildcard_step=None,
    solver=None,
):
    """Solve the multi-gameweek transfer plan.

    pool_by_gw       : {gw: DataFrame[element, name, position, team, value, e_points]}
                       in horizon order. The FIRST key is the gameweek to execute.
    current_squad    : list of elements held right now (empty at GW1)
    purchase_prices  : {element: price paid}, for the sell-price rule
    bank             : money in hand, in tenths
    free_transfers   : free transfers available in the first gameweek
    decay            : per-gameweek discount on future predicted points
    wildcard_step    : horizon index (0 = the executed gameweek) at which transfers
                       are free, or None. Budget, squad composition and club limits
                       still apply. Banking is untouched, so the following gameweek
                       resumes with its normal free transfer.

    Returns (status, plan) where plan is a list of per-gameweek dicts.
    """
    w_bench = resolve_bench_weight(mode, bench_weight)
    gws = list(pool_by_gw.keys())
    T = len(gws)
    if T == 0:
        raise ValueError("pool_by_gw is empty -- nothing to plan")

    # Every player who appears in ANY gameweek of the horizon, plus everyone
    # currently owned. Owned players must be representable even in a gameweek
    # where they have no fixture, or the continuity constraint cannot hold.
    all_players = set()
    for df in pool_by_gw.values():
        all_players.update(df["element"])
    all_players.update(current_squad)
    players = sorted(all_players)

    # Static attributes, taken from wherever the player first appears.
    attrs = {}
    for df in pool_by_gw.values():
        for r in df.itertuples():
            attrs.setdefault(r.element, {"position": r.position, "team": r.team,
                                         "name": getattr(r, "name", str(r.element))})

    missing_attrs = [e for e in players if e not in attrs]
    if missing_attrs:
        raise ValueError(
            f"{len(missing_attrs)} owned players have no attributes anywhere in the "
            "horizon -- pass them through pool_by_gw with e_points=0"
        )

    # Predicted points and prices per (player, gameweek). A player absent from a
    # gameweek scores zero there and cannot be bought into it.
    pts, price, available = {}, {}, {}
    for t, gw in enumerate(gws):
        df = pool_by_gw[gw].set_index("element")
        for i in players:
            if i in df.index:
                pts[(i, t)] = float(df.loc[i, "e_points"])
                price[(i, t)] = int(df.loc[i, "value"])
                available[(i, t)] = True
            else:
                pts[(i, t)] = 0.0
                price[(i, t)] = int(purchase_prices.get(i, 40))
                available[(i, t)] = False

    owned = set(current_squad)
    is_first_squad = len(owned) == 0

    prob = pulp.LpProblem("fpl_transfer_plan", pulp.LpMaximize)

    pick = {(i, t): pulp.LpVariable(f"pick_{i}_{t}", cat="Binary")
            for i in players for t in range(T)}
    start = {(i, t): pulp.LpVariable(f"start_{i}_{t}", cat="Binary")
             for i in players for t in range(T)}
    cap = {(i, t): pulp.LpVariable(f"cap_{i}_{t}", cat="Binary")
           for i in players for t in range(T)}
    vice = {(i, t): pulp.LpVariable(f"vice_{i}_{t}", cat="Binary")
            for i in players for t in range(T)}
    buy = {(i, t): pulp.LpVariable(f"buy_{i}_{t}", cat="Binary")
           for i in players for t in range(T)}
    sell = {(i, t): pulp.LpVariable(f"sell_{i}_{t}", cat="Binary")
            for i in players for t in range(T)}

    # Hits are integers, not binaries: a gameweek can carry several.
    hits = {t: pulp.LpVariable(f"hits_{t}", lowBound=0, cat="Integer")
            for t in range(T)}

    # Free transfers are DECISION VARIABLES, derived from the solver's own buy
    # choices. Precomputing them from a guessed transfer count made the guess
    # self-fulfilling and left banking impossible -- see the module docstring.
    ft = {t: pulp.LpVariable(f"ft_{t}", lowBound=0,
                             upBound=MAX_FREE_TRANSFERS, cat="Integer")
          for t in range(T)}

    # ---- objective -----------------------------------------------------
    # Decayed predicted points for the XI, the captain again, an epsilon for the
    # vice tie-break, a weighted bench, minus the cost of hits.
    obj = []
    for t in range(T):
        d = decay ** t
        for i in players:
            p = pts[(i, t)]
            if p == 0:
                continue
            obj.append(d * p * start[(i, t)])
            obj.append(d * p * cap[(i, t)])
            obj.append(d * VICE_WEIGHT * p * vice[(i, t)])
            obj.append(d * w_bench * p * (pick[(i, t)] - start[(i, t)]))
        obj.append(-d * HIT_COST * hits[t])
    prob += pulp.lpSum(obj)

    # ---- per-gameweek squad and XI rules --------------------------------
    for t in range(T):
        prob += pulp.lpSum(pick[(i, t)] for i in players) == SQUAD_SIZE

        for pos, n in POSITION_LIMITS.items():
            prob += pulp.lpSum(pick[(i, t)] for i in players
                               if attrs[i]["position"] == pos) == n

        # SORTED, and that is load-bearing. A set of strings iterates in an order
        # that depends on Python's per-process string hash randomisation, so the
        # club constraints were emitted in a different order in every process.
        # That changes nothing about the feasible region, but it changes which of
        # several EXACTLY TIED optima the solver returns -- and with a weak
        # ranking signal, ties are everywhere. Measured effect: the same season,
        # same data, same config returned 1973 or 1984 depending on the run.
        teams = sorted({attrs[i]["team"] for i in players})
        for team in teams:
            prob += pulp.lpSum(pick[(i, t)] for i in players
                               if attrs[i]["team"] == team) <= MAX_PER_CLUB

        prob += pulp.lpSum(start[(i, t)] for i in players) == XI_SIZE
        for i in players:
            prob += start[(i, t)] <= pick[(i, t)]
            # A player with no fixture cannot start, and cannot be bought in.
            if not available[(i, t)]:
                prob += start[(i, t)] == 0
                prob += buy[(i, t)] == 0

        for pos, (lo, hi) in FORMATION.items():
            in_pos = pulp.lpSum(start[(i, t)] for i in players
                                if attrs[i]["position"] == pos)
            prob += in_pos >= lo
            prob += in_pos <= hi

        prob += pulp.lpSum(cap[(i, t)] for i in players) == 1
        prob += pulp.lpSum(vice[(i, t)] for i in players) == 1
        for i in players:
            prob += cap[(i, t)] <= start[(i, t)]
            prob += vice[(i, t)] <= start[(i, t)]
            prob += cap[(i, t)] + vice[(i, t)] <= 1

    # ---- squad continuity: the constraint that gives the squad a past ----
    for i in players:
        prev = 1 if i in owned else 0
        for t in range(T):
            if t == 0:
                prob += pick[(i, 0)] == prev + buy[(i, 0)] - sell[(i, 0)]
            else:
                prob += pick[(i, t)] == pick[(i, t - 1)] + buy[(i, t)] - sell[(i, t)]
            # Buying and selling the same player in one gameweek is never useful
            # and would let the solver inflate the transfer count for free.
            prob += buy[(i, t)] + sell[(i, t)] <= 1

    # ---- money ----------------------------------------------------------
    # Owned players enter at their SELL value (they are not being re-bought);
    # everyone else at market price. Budget is sell value + bank, which is what
    # a mid-season manager actually commands -- not a fresh 100m.
    if is_first_squad:
        for t in range(T):
            prob += pulp.lpSum(price[(i, t)] * pick[(i, t)]
                               for i in players) <= 1000
    else:
        sellv = {i: sell_price(int(purchase_prices.get(i, price[(i, 0)])),
                               int(price[(i, 0)]))
                 for i in owned}
        spending_power = sum(sellv.values()) + bank
        for t in range(T):
            cost = []
            for i in players:
                v = sellv[i] if i in owned else price[(i, t)]
                cost.append(v * pick[(i, t)])
            prob += pulp.lpSum(cost) <= spending_power

    # ---- free transfers and hits ----------------------------------------
    # Both are linearized without big-M. hits[t] is penalized in a MAXIMIZED
    # objective so the solver pushes it to its lower bound; ft[t] loosens that
    # penalty so the solver pushes it to its upper bound. Each therefore binds
    # exactly where max() and min() would, with only one-sided constraints.
    used = {t: pulp.lpSum(buy[(i, t)] for i in players) for t in range(T)}

    # The opening 15 is a free pick, not fifteen transfers. Counting it as spend
    # would drive ft[1] to 5 - 15 + 1 = -9 against a lower bound of 0, making the
    # whole model infeasible -- which is exactly what it did before this line.
    spend = dict(used)
    if is_first_squad:
        spend[0] = 0
    # A wildcard costs no BANKED transfers either. Without this the relief on the
    # hit constraint is useless: ft[1] <= ft[0] - used[0] + hits[0] + 1 still
    # debits every wildcard transfer, so with hits driven to zero the chain
    # forces used[0] <= ft[0] + 1 -- two transfers, not unlimited. The chip was
    # silently reduced to one extra free transfer at every horizon above T=1,
    # which is why it only looked correct on a truncated one-gameweek season.
    if wildcard_step is not None:
        spend[wildcard_step] = 0

    prob += ft[0] == free_transfers
    for t in range(1, T):
        # ft[t] <= max(0, ft[t-1] - used[t-1]) + 1, with the max handled by the
        # hits term: when h hits are taken, used = ft + h at the optimum, so
        # ft[t-1] - used[t-1] + hits[t-1] collapses to exactly 0.
        prob += ft[t] <= ft[t - 1] - spend[t - 1] + hits[t - 1] + 1

    for t in range(T):
        if t == 0 and is_first_squad:
            # The opening 15 is a free pick, not fifteen transfers.
            prob += hits[0] == 0
            continue
        # A wildcard makes transfers free for one gameweek. Rather than inflating
        # ft (which is capped at MAX_FREE_TRANSFERS and banks forward, so a large
        # value would leak free transfers into later weeks), the hit penalty is
        # switched off for that step alone. 15 is large enough never to bind: a
        # 15-man squad admits at most 15 transfers.
        relief = 15 if t == wildcard_step else 0
        prob += hits[t] >= used[t] - ft[t] - relief

    prob.solve(solver or _default_solver())
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return status, None

    # ---- read the plan back ---------------------------------------------
    plan = []
    for t, gw in enumerate(gws):
        squad = [i for i in players if _is_set(pick[(i, t)])]
        plan.append({
            "gw": gw,
            "horizon_step": t,
            "squad": squad,
            "starters": [i for i in players if _is_set(start[(i, t)])],
            "captain": next((i for i in players if _is_set(cap[(i, t)])), None),
            "vice": next((i for i in players if _is_set(vice[(i, t)])), None),
            "buys": [i for i in players if _is_set(buy[(i, t)])],
            "sells": [i for i in players if _is_set(sell[(i, t)])],
            "hits": int(round(hits[t].value() or 0)),
            "free_transfers": int(round(ft[t].value() or 0)),
            "transfers_made": len([i for i in players if _is_set(buy[(i, t)])]),
            "decay_weight": decay ** t,
        })

    return status, plan


def plan_to_team(plan_step, pool):
    """Turn the first step of a plan into the role-tagged frame the rest of the
    pipeline expects (same shape as optimize.get_team)."""
    squad = set(plan_step["squad"])
    starters = set(plan_step["starters"])

    rows = []
    for r in pool.itertuples():
        if r.element not in squad:
            continue
        if r.element == plan_step["captain"]:
            role = "CAPTAIN"
        elif r.element == plan_step["vice"]:
            role = "VICE"
        elif r.element in starters:
            role = "start"
        else:
            role = "bench"
        rows.append({"element": r.element, "name": getattr(r, "name", str(r.element)),
                     "position": r.position, "team": r.team,
                     "value": r.value, "e_points": r.e_points, "role": role})

    return pd.DataFrame(rows)