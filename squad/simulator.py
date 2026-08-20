"""
FPL Copilot — Season simulator

Runs a whole 2025-26 season with the model in charge, and reports what it would
actually have scored. This is the piece that turns a PREDICTION claim ("the model
ranks players well, Spearman 0.715") into a DECISION claim ("playing this model
for a season would have scored N points").

The three parts underneath it already exist and are tested independently:
    optimize.py    -- picks a legal squad given predicted points
    scoring.py     -- scores a squad against what actually happened (pure)
    squad_state.py -- carries the 15, purchase prices, bank and free transfers

This module is only the LOOP. It holds no FPL rules of its own; every rule lives
in one of the three modules above.

WHY WALK-FORWARD PREDICTIONS
----------------------------
It reads walkforward_2526.parquet, not predictions_2526.parquet. The walk-forward
file contains AS-OF predictions: gameweek 12's numbers were produced knowing only
gameweeks 1-11. A simulated manager who used the static file would be quietly
using a model trained with knowledge of the season it is playing, which would
flatter the result for the least interesting reason.

THE WEEKLY DECISION (v1)
------------------------
Each gameweek after the first:
  1. Consider making no transfer at all -- keep the 15, re-pick the XI.
  2. For each of the 15 players, consider selling him: lock the other 14, ban him,
     let the optimizer choose the best legal replacement within budget.
  3. Take whichever of those 16 options has the highest predicted XI + captain.

The optimizer re-picks the starting XI and captain every gameweek regardless, at
no cost, because lineup changes are free in FPL. Only squad changes cost.

KNOWN v1 LIMITATIONS (documented, not hidden)
---------------------------------------------
- SINGLE transfers only. Combination moves ("sell two mid-price defenders to
  afford one premium") are invisible to this search. See FEATURE_IDEAS.md; the
  proper fix is a transfer MIP, not a bigger loop.
- NO CHIP LOGIC. Bench boost and free hit do not exist. Wildcards and a triple
  captain can be FORCED at chosen gameweeks (simulate_season's wildcard_gws and
  triple_captain_gw) purely to measure what one is worth; the simulator never
  decides to play a chip itself.
- NEVER TAKES A HIT. It only spends free transfers, so it never pays 4 points for
  a second move. The machinery for hits exists in scoring.py and squad_state.py
  and is tested; the v1 policy simply does not use it.
- Bench order is set by predicted points rather than chosen deliberately.

BLANK GAMEWEEKS
---------------
When a club has no fixture, its players have no row in that gameweek's data at
all -- in 2025-26 this bites at GW31, where five squad players disappear from a
pool that otherwise grows all season. They are still owned; they simply cannot
score. See _adjusted_pool for how they are kept representable in the MIP.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pulp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimize import optimize_squad, get_team, BUDGET
from scoring import assign_bench_order, score_gameweek
from squad_state import SquadState, sell_price, STARTING_BUDGET
from transfer_mip import (build_and_solve, plan_to_team,
                          DEFAULT_HORIZON, DEFAULT_DECAY)

REPO_ROOT = Path(__file__).resolve().parent.parent
WALKFORWARD_PATH = REPO_ROOT / "data" / "walkforward_2526.parquet"
# Horizon-aware predictions: one row per (cutoff, gameweek, player). Filtering to
# cutoff == k gives exactly what a manager standing at gameweek k could know --
# including his view of k+1..k+5, with form frozen at k. See eval/walkforward.py.
WALKFORWARD_H_PATH = REPO_ROOT / "data" / "walkforward_h6_2526.parquet"
HISTORY_PATH = REPO_ROOT / "data" / "history" / "all_seasons_fixed.parquet"
SEASON = "2025-26"

# FPL grants two wildcards a season, one per half. The split is announced rather
# than fixed -- in recent seasons the first-half chip has expired around GW19-20 --
# so it is a parameter with a sensible default, not a hard-coded rule.
DEFAULT_SECOND_HALF_START = 20


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_season(walkforward_path=None, history_path=HISTORY_PATH,
                horizon_aware=False, season=None):
    """Load as-of predictions, realized outcomes, and prices for every gameweek.

    horizon_aware=False (default) loads the original file: one prediction per
    player-gameweek, made with that gameweek's own cutoff. Correct for a
    single-gameweek policy, which never looks past the gameweek it is playing.

    horizon_aware=True loads the horizon file, which carries a `cutoff` column.
    The multi-gameweek MIP NEEDS this. Handing it the original file would be a
    leak that is easy to miss: gameweek k+3's row there was produced with cutoff
    k+3, so its rolling features were built from gameweeks k+1 and k+2 -- matches
    that have not been played when the planner is standing at gameweek k.

    Returns a frame with one row per player-gameweek (or per cutoff-gameweek-player
    when horizon_aware), carrying the prediction, the truth, and the price.
    """
    if walkforward_path is None:
        walkforward_path = WALKFORWARD_H_PATH if horizon_aware else WALKFORWARD_PATH

    if horizon_aware and not Path(walkforward_path).exists():
        raise FileNotFoundError(
            f"{walkforward_path} not found. Build it first:\n"
            "    uv run python eval/walkforward.py --horizon 6"
        )

    wf = pd.read_parquet(walkforward_path)

    history = pd.read_parquet(history_path)
    # Season is a parameter for the multi-season port (M2). Default keeps 2025-26.
    history = history[history["season"] == (SEASON if season is None else season)]
    prices = (history[["element", "round", "value"]]
              .rename(columns={"round": "gw"})
              .drop_duplicates(subset=["element", "gw"], keep="first"))

    df = wf.merge(prices, on=["element", "gw"], how="left")

    missing = df["value"].isna().sum()
    if missing:
        raise ValueError(
            f"{missing} player-gameweeks have no price -- the budget rule would be "
            "meaningless. Check the join between walkforward and history."
        )

    df["value"] = df["value"].astype(int)
    df["actual_points"] = pd.to_numeric(df["actual_points"], errors="coerce").fillna(0)
    df["minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)

    # A horizon-aware frame can carry rows with no prediction at all, and they are
    # meaningful rather than corrupt. Freezing form at cutoff k builds the minutes
    # frame from the players who HAD a gameweek-k row; a player who first appears
    # at k+2 (new signing, returning from injury, no gameweek-k fixture) is in the
    # later skeleton but absent from the frozen frame, so he arrives with NaN.
    #
    # That is exactly right: at cutoff k the manager knows nothing about him. He is
    # dropped from the pool rather than filled with a guess, so the optimizer cannot
    # buy a player it has no basis for valuing. If he is already OWNED,
    # _pool_with_owned puts him back at e_points = 0, which keeps the squad intact
    # without pretending to a prediction.
    n_before = len(df)
    df = df[df["e_points"].notna()].copy()
    dropped = n_before - len(df)
    if dropped:
        print(f"[load_season] dropped {dropped} rows ({100*dropped/n_before:.1f}%) "
              "with no prediction -- players not yet visible at their cutoff")

    return df


def gw_slice(season_df, gw, cutoff=None):
    """One gameweek's player pool, in the shape optimize.py expects.

    cutoff : when the frame is horizon-aware, which vantage point to read from.
             cutoff=k returns the view a manager standing at gameweek k had of
             gameweek gw. Passing None on a horizon-aware frame would silently
             return SIX rows per player -- one per cutoff -- so it is refused.
    """
    d = season_df[season_df["gw"] == gw]

    if "cutoff" in season_df.columns:
        if cutoff is None:
            raise ValueError(
                "this frame is horizon-aware and needs an explicit cutoff; "
                "without one every player would appear once per cutoff"
            )
        d = d[d["cutoff"] == cutoff]
        if len(d) == 0:
            # No view of this gameweek from that vantage point -- it is beyond
            # the horizon the harness was built with.
            raise ValueError(
                f"no predictions for GW{gw} from cutoff GW{cutoff}; the harness "
                f"horizon is shorter than {gw - cutoff + 1} gameweeks"
            )
    elif cutoff is not None and cutoff != gw:
        raise ValueError(
            f"cutoff={cutoff} requested for GW{gw}, but this frame has no cutoff "
            "column -- it holds only same-gameweek predictions. Load with "
            "horizon_aware=True."
        )

    cols = ["element", "name", "position", "team", "value", "e_points"]
    return d[cols].copy().reset_index(drop=True)


def gw_actuals(season_df, gw):
    """One gameweek's realized outcomes, in the shape scoring.py expects.

    On a horizon-aware frame a player appears once per cutoff, but what ACTUALLY
    happened is identical across all of them -- so one row per player is taken.
    Without this every player would be counted up to six times.
    """
    d = season_df[season_df["gw"] == gw]
    if "cutoff" in season_df.columns:
        d = d.drop_duplicates(subset="element", keep="first")
    return d[["element", "minutes", "total_points"]].copy() if "total_points" in d.columns \
        else d[["element", "minutes", "actual_points"]].rename(
            columns={"actual_points": "total_points"}).copy()


# ---------------------------------------------------------------------------
# Turning an optimizer solution into something the rest of the pipeline uses
# ---------------------------------------------------------------------------
def solution_to_squad(pool, sol):
    """Optimizer solution -> a 15-row frame with roles and bench order."""
    team = get_team(pool, sol)
    return assign_bench_order(team)


def predicted_score(team):
    """Predicted XI + captain points for a solved team. This is the objective the
    weekly decision is ranked on -- deliberately NOT including the bench, because
    the bench only scores through autosubs."""
    starters = team[team["role"] != "bench"]
    cap = team.loc[team["role"] == "CAPTAIN", "e_points"]
    return float(starters["e_points"].sum() + (cap.iloc[0] if len(cap) else 0))


# ---------------------------------------------------------------------------
# The weekly decision
# ---------------------------------------------------------------------------
def _adjusted_pool(pool, state, prices):
    """Rewrite prices so the optimizer sees the manager's real spending power, and
    make sure every player the manager owns is representable in the MIP.

    TWO THINGS HAPPEN HERE.

    1. OWNED PLAYERS ARE PRICED AT SELL VALUE.
       The optimizer enforces `sum(value) <= budget`. A mid-season manager does not
       have a fresh £100m -- he has his squad's SELL value plus the bank. Players he
       already owns are not being re-bought, so they enter at what they would fetch;
       new players cost their market price. The caller then passes
       `budget = sell value + bank`, and the constraint means exactly what FPL means.

    2. BLANKED OWNED PLAYERS ARE INJECTED BACK IN.
       In a blank gameweek a player's club has no fixture, so he has NO ROW in that
       gameweek's data at all. In 2025-26 this happens at GW31, where five squad
       players vanish from a pool that otherwise grows monotonically all season.

       That is a real FPL situation, not a data fault: the manager still owns them,
       they simply score nothing and get autosubbed. But the MIP can only reason
       about players that exist as rows, so locking them would be impossible and the
       whole gameweek would come back infeasible.

       So they are added back with e_points = 0 and their sell price as value. They
       stay lockable and keep occupying their squad slot, while zero predicted points
       means the optimizer will never choose to START one unless the formation leaves
       it no alternative -- which is exactly the right behaviour.
    """
    p = pool.copy()
    owned = dict(zip(state.squad["element"], state.squad["purchase_price"]))

    def price_for(row):
        e = row["element"]
        if e in owned:
            return sell_price(int(owned[e]), int(prices.get(e, owned[e])))
        return int(row["value"])

    p["value"] = p.apply(price_for, axis=1)

    missing = [e for e in state.elements if e not in set(p["element"])]
    if missing:
        rows = []
        for e in missing:
            s = state.squad[state.squad["element"] == e].iloc[0]
            bought = int(s["purchase_price"])
            rows.append({
                "element": e,
                "name": s.get("name", f"element_{e}"),
                "position": s["position"],
                "team": s.get("team", "UNKNOWN"),
                # No price row this gameweek, so fall back to what was paid --
                # assuming a rise would invent money that does not exist.
                "value": sell_price(bought, int(prices.get(e, bought))),
                "e_points": 0.0,          # blank gameweek: cannot score
            })
        p = pd.concat([p, pd.DataFrame(rows)], ignore_index=True)

    return p


def decide_gameweek(pool, state, prices, mode="balanced", allow_transfer=True):
    """Choose this gameweek's squad: keep, or make one transfer.

    Returns (chosen_team, transfer) where transfer is None or (out, in).

    Evaluates up to 16 options: no transfer, plus one per current player sold.
    Every option is a full MIP solve, so this is the expensive part of the loop.
    """
    # _adjusted_pool guarantees every owned player has a row, including blanked
    # ones, so all 15 are always lockable from here on.
    adj = _adjusted_pool(pool, state, prices)
    spending_power = state.budget(prices)

    current = state.elements

    # --- option 0: keep the squad, re-pick XI and captain (always free) ---
    best_team, best_score, best_transfer = None, float("-inf"), None

    prob, sol = optimize_squad(adj, mode=mode, locked_elements=current,
                               budget=spending_power)
    if pulp.LpStatus[prob.status] == "Optimal":
        best_team = solution_to_squad(adj, sol)
        best_score = predicted_score(best_team)

    if not allow_transfer:
        return best_team, None

    # --- options 1..15: sell one player, let the MIP choose the replacement ---
    for out_elem in current:
        keep = [e for e in current if e != out_elem]

        prob, sol = optimize_squad(
            adj, mode=mode, locked_elements=keep, banned_elements=[out_elem],
            budget=spending_power
        )
        if pulp.LpStatus[prob.status] != "Optimal":
            continue

        team = solution_to_squad(adj, sol)
        score = predicted_score(team)
        if score > best_score:
            in_elem = [e for e in team["element"] if e not in current]
            if len(in_elem) != 1:
                continue                  # defensive: expect exactly one new player
            best_team, best_score, best_transfer = team, score, (out_elem, in_elem[0])

    return best_team, best_transfer


# ---------------------------------------------------------------------------
# The season loop
# ---------------------------------------------------------------------------
def decide_gameweek_mip(season_df, gw, state, pool, prices, all_gws,
                        mode="balanced", horizon=DEFAULT_HORIZON,
                        decay=DEFAULT_DECAY, wildcard=False, hit_bar=None,
                        bench_boost_gw=None):
    """Plan `horizon` gameweeks ahead with the transfer MIP, return this week's move.

    Rolling horizon: the solver produces a plan for GW..GW+horizon-1, but only the
    FIRST gameweek is executed. Next gameweek the whole thing is re-solved with
    fresh data, so the plan is a guide rather than a commitment.

    The window shrinks near the end of the season (at GW36 only GW36-38 remain).
    That is correct, not degradation -- a manager in May genuinely has no future to
    save for. The effective horizon is returned so the behaviour stays visible in
    the log rather than hidden.

    Returns (team, transfers, plan_step, effective_horizon) where transfers is a
    list of (out, in) pairs -- the MIP may choose several, or none.

    wildcard=True makes transfers free for THIS gameweek only (horizon step 0).
    Since only the first step is ever executed, a wildcard is always step 0.
    """
    # Every gameweek in the plan is read from THIS gameweek's cutoff. That is the
    # whole point: gameweek k+3 as seen from k, not gameweek k+3 as seen from k+3.
    horizon_aware = "cutoff" in season_df.columns
    future = [g for g in all_gws if g >= gw][:horizon]

    pools = {}
    for g in future:
        try:
            raw = gw_slice(season_df, g, cutoff=gw if horizon_aware else None)
        except ValueError:
            # Beyond what the harness was built for -- plan with what exists
            # rather than failing the whole season.
            break
        pools[g] = _pool_with_owned(raw, state, prices)
    future = list(pools.keys())

    purchase_prices = dict(zip(state.squad["element"],
                               state.squad["purchase_price"]))

    # A scheduled Bench Boost inside the window gets its horizon index, so the
    # solver values that step's bench in full and can build toward it as the
    # boost week approaches (see transfer_mip.BENCH_BOOST_AWARE).
    bb_step = (future.index(bench_boost_gw)
               if bench_boost_gw is not None and bench_boost_gw in future
               else None)
    status, plan = build_and_solve(
        pools,
        current_squad=state.elements,
        purchase_prices=purchase_prices,
        bank=state.bank,
        free_transfers=state.free_transfers,
        mode=mode,
        decay=decay,
        wildcard_step=0 if wildcard else None,
        hit_bar=hit_bar,
        bench_boost_step=bb_step,
    )
    if plan is None:
        raise RuntimeError(f"GW{gw}: transfer MIP returned {status}")

    step = plan[0]
    team = assign_bench_order(plan_to_team(step, pools[gw]))

    # Pair each sale with a purchase. Positions must match, because the 15 is
    # fixed at 2/5/5/3 -- so a sold MID is always replaced by a bought MID.
    pos_of = dict(zip(pools[gw]["element"], pools[gw]["position"]))
    sells = list(step["sells"])
    buys = list(step["buys"])
    transfers = []
    for out_elem in sells:
        match = next((b for b in buys if pos_of.get(b) == pos_of.get(out_elem)), None)
        if match is None:
            raise RuntimeError(
                f"GW{gw}: sold {out_elem} ({pos_of.get(out_elem)}) with no "
                "matching purchase -- the squad composition constraint should "
                "have made this impossible"
            )
        buys.remove(match)
        transfers.append((out_elem, match))

    return team, transfers, step, len(future)


def _pool_with_owned(pool, state, prices):
    """Ensure every owned player has a row, even in a blank gameweek.

    Same reasoning as _adjusted_pool, but WITHOUT rewriting prices: the MIP does
    its own sell-price accounting internally, so handing it adjusted prices would
    apply the discount twice.
    """
    missing = [e for e in state.elements if e not in set(pool["element"])]
    if not missing:
        return pool

    rows = []
    for e in missing:
        s = state.squad[state.squad["element"] == e].iloc[0]
        bought = int(s["purchase_price"])
        rows.append({
            "element": e,
            "name": s.get("name", f"element_{e}"),
            "position": s["position"],
            "team": s.get("team", "UNKNOWN"),
            "value": int(prices.get(e, bought)),
            "e_points": 0.0,          # blank gameweek: cannot score
        })
    return pd.concat([pool, pd.DataFrame(rows)], ignore_index=True)


def _chip_weeks(value, chip_name, second_half_start):
    """Normalise an int / iterable / None into a set of gameweeks and enforce
    FPL's two-per-season, one-per-half rule.

    Shared by every chip that has that rule so they cannot drift apart: the
    wildcard grew this validation first, and the free hit needs exactly it.
    """
    if value is None:
        return set()
    if isinstance(value, (int, np.integer)):
        weeks = {int(value)}
    else:
        weeks = {int(g) for g in value}

    if len(weeks) > 2:
        raise ValueError(f"FPL allows two {chip_name} per season, got {len(weeks)}")
    first = {g for g in weeks if g < second_half_start}
    second = {g for g in weeks if g >= second_half_start}
    if len(first) > 1 or len(second) > 1:
        raise ValueError(
            f"one {chip_name.rstrip('s')} per half only (halves split at "
            f"GW{second_half_start}): got {sorted(first)} in the first and "
            f"{sorted(second)} in the second")
    return weeks


def simulate_season(season_df, mode="balanced", gws=None, verbose=True,
                    policy="single", horizon=DEFAULT_HORIZON, decay=DEFAULT_DECAY,
                    wildcard_gws=None, triple_captain_gw=None,
                    free_hit_gws=None, bench_boost_gw=None,
                    second_half_start=DEFAULT_SECOND_HALF_START, hit_bar=None):
    """Run the full season. Returns (final_state, decision_log DataFrame).

    policy : "single" -- the v1 search: try keeping, try selling each of the 15,
             take the best. One transfer maximum, never takes a hit.
             "mip"    -- the multi-gameweek transfer MIP: the solver decides how
             many transfers to make, which, and whether a hit is worth paying,
             planning `horizon` gameweeks ahead and executing only the first.

    wildcard_gws : gameweek(s) at which to FORCE a wildcard (unlimited free
             transfers for that week alone). Accepts an int, a list of up to two,
             or None. FPL allows two per season -- one in each half -- and that
             rule is ENFORCED here: two wildcards in the same half raises.

             This is a measurement instrument, not chip logic: the weeks are
             chosen by the caller, not by the solver, so sweeping them gives the
             value of a perfectly-timed wildcard -- an upper bound on what any
             timing rule could earn. Requires policy="mip"; a wildcard in the
             first gameweek is a no-op because the opening squad is already free.

             When two are played, the second acts on the squad the first built.
             That interaction is why two wildcards cannot be measured by adding
             two solo runs together -- they must be played in the same season.

    triple_captain_gw : gameweek at which to FORCE the Triple Captain chip, or
             None. Also a measurement instrument. Unlike the wildcard it changes
             no decision -- same squad, same transfers -- so the rest of the
             season is identical with and without it, and the gain is exactly
             that week's captain_bonus. Works under either policy.

    free_hit_gws : gameweek(s) at which to FORCE a Free Hit -- unlimited free
             transfers for one gameweek, after which the squad REVERTS to
             exactly what it was before: same players, same purchase prices,
             same bank, same free transfers. Accepts an int, a list of up to
             two, or None, with the same one-per-half rule as wildcard_gws.

             Because the squad is handed back, the chip week is solved with a
             horizon of ONE. Planning ahead would be meaningless -- next week is
             played by the squad being restored -- and it is precisely what lets
             a Free Hit go all-in on a single gameweek.

             A Free Hit and a wildcard cannot be played in the same gameweek.
             Like the others this is a measurement instrument, not chip logic:
             the week is chosen by the caller, never by the solver.

    second_half_start : first gameweek of the second half, for the one-per-half
             rule. FPL sets this by announcement each season rather than by a
             fixed number, so it is a parameter rather than a constant.

    The decision log is one row per gameweek recording the squad, the transfers,
    the captain, and the points. It is what makes the result auditable rather
    than a single number to be taken on trust.
    """
    if policy not in ("single", "mip"):
        raise ValueError(f"unknown policy {policy!r}; expected 'single' or 'mip'")

    wildcard_gws = _chip_weeks(wildcard_gws, "wildcards", second_half_start)
    free_hit_gws = _chip_weeks(free_hit_gws, "free hits", second_half_start)

    clash = wildcard_gws & free_hit_gws
    if clash:
        raise ValueError(
            f"only one chip per gameweek: wildcard and free hit both at "
            f"GW{sorted(clash)}")
    if (wildcard_gws or free_hit_gws) and policy != "mip":
        raise ValueError("wildcard_gws and free_hit_gws require policy='mip'")

    if gws is None:
        gws = sorted(season_df["gw"].unique())

    log = []
    state = None

    for gw in gws:
        pool = gw_slice(season_df, gw,
                        cutoff=gw if "cutoff" in season_df.columns else None)
        actuals = gw_actuals(season_df, gw)
        prices = dict(zip(pool["element"], pool["value"]))
        effective_horizon = 1
        is_wildcard = False
        is_free_hit = False
        is_triple_captain = (triple_captain_gw is not None
                             and gw == triple_captain_gw)

        # -- decide --
        if state is None:
            # Gameweek 1: no squad yet, so this is a free pick from scratch.
            prob, sol = optimize_squad(pool, mode=mode)
            if pulp.LpStatus[prob.status] != "Optimal":
                raise RuntimeError(f"GW{gw}: initial squad is {pulp.LpStatus[prob.status]}")
            team = solution_to_squad(pool, sol)
            transfer = None
            transfers = []

            start = team.copy()
            start["purchase_price"] = start["value"].astype(int)
            state = SquadState(start,
                               bank=STARTING_BUDGET - int(start["purchase_price"].sum()),
                               free_transfers=1)
        elif policy == "single":
            team, transfer = decide_gameweek(pool, state, prices, mode=mode)
            if team is None:
                raise RuntimeError(f"GW{gw}: no feasible squad found")
            transfers = [] if transfer is None else [transfer]

            if transfer is not None:
                out_elem, in_elem = transfer
                # The incoming player is always a REAL pool player (blanked players
                # are only ever injected for the ones already owned), so the raw
                # pool row carries his true market price -- what the manager pays.
                in_row = pool[pool["element"] == in_elem].iloc[0]
                state.make_transfer(out_elem, in_elem, in_row, prices)

        else:  # policy == "mip"
            is_wildcard = (gw in wildcard_gws)
            is_free_hit = (gw in free_hit_gws)

            if is_free_hit:
                # Taken BEFORE any transfer touches the state, and restored after
                # scoring, so the chip week leaves no trace on the squad.
                pre_chip = state.snapshot()

            # A Free Hit squad is handed back at the final whistle, so planning
            # ahead with it is meaningless -- next week is played by the squad
            # being restored, not this one. The horizon collapses to the single
            # gameweek being bought, which is also what lets the chip go all-in
            # on one week: chase a double, dodge a blank, ignore the consequences.
            eff_horizon = 1 if is_free_hit else horizon

            team, transfers, step, eff_h = decide_gameweek_mip(
                season_df, gw, state, pool, prices, gws,
                mode=mode, horizon=eff_horizon, decay=decay,
                wildcard=is_wildcard or is_free_hit, hit_bar=hit_bar,
                bench_boost_gw=bench_boost_gw)
            effective_horizon = eff_h

            # Applied as ONE atomic move: the MIP reasoned about the whole set,
            # and executing them one at a time can fail on an intermediate step
            # even when the set is affordable together.
            in_rows = {b: pool[pool["element"] == b].iloc[0]
                       for _, b in transfers}
            state.make_transfers(transfers, in_rows, prices)

        # -- keep the state's roles in step with what was just chosen --
        roles = team.set_index("element")[["role", "bench_order"]]
        state.squad = state.squad.drop(columns=["role", "bench_order"], errors="ignore")
        state.squad = state.squad.merge(
            roles, left_on="element", right_index=True, how="left")

        n_transfers = len(transfers)
        # spend_transfers returns how many were PAID; capture the free allowance
        # BEFORE spending, since scoring needs the allowance that applied.
        #
        # A wildcard makes every transfer free AND consumes no banked transfers,
        # so both the charge and the spend are skipped. Reporting the allowance as
        # the transfer count is what makes score_gameweek bill zero, and leaving
        # state.free_transfers untouched means the bank carries into next week
        # exactly as FPL does.
        # A Free Hit is the same bargain as a wildcard for one week: every
        # transfer free, no banked transfer consumed. The difference comes after
        # scoring, when the squad is handed back.
        if is_wildcard or is_free_hit:
            free_before = n_transfers
        else:
            free_before = state.free_transfers
            state.spend_transfers(n_transfers)

        # -- score --
        result = score_gameweek(
            state.squad, actuals,
            transfers_made=n_transfers,
            free_transfers=free_before,
            triple_captain=is_triple_captain,
        )
        # What actually took the field, captured before a Free Hit hands the
        # squad back. On every other gameweek these are the same thing.
        cap_row = state.squad[state.squad["role"] == "CAPTAIN"]
        played_captain = (cap_row["name"].iloc[0]
                          if len(cap_row) and "name" in cap_row else None)
        played_elements = list(state.elements)
        played_value = state.sell_value(prices)

        if is_free_hit:
            # The squad reverts; the points do not. Restoring BEFORE
            # end_gameweek means next week's free transfer is earned on the
            # pre-chip balance, which is what FPL does.
            state.restore(pre_chip)

        state.end_gameweek(result["points"])

        log.append({
            "gw": gw,
            # Provenance stamps (P4 log section 13): the config that made the
            # decisions must be visible in the artefact -- the #13 lesson.
            "horizon": int(horizon),
            "decay": float(decay),
            "bench_boost_aware": bool(__import__("transfer_mip").BENCH_BOOST_AWARE),
            "bench_boost_gw": int(bench_boost_gw) if bench_boost_gw else -1,
            "points": result["points"],
            "raw_points": result["raw_points"],
            "hit": result["hit"],
            "total_points": state.total_points,
            "captain": played_captain,
            "captain_bonus": result["captain_bonus"],
            "doubled_role": result["doubled_role"],
            "n_subs": len(result["subs_made"]),
            "bench_points": result["bench_points"],
            "n_transfers": n_transfers,
            "transfer_out": transfers[0][0] if transfers else None,
            "transfer_in": transfers[0][1] if transfers else None,
            "all_transfers": list(transfers),
            "effective_horizon": effective_horizon,
            "wildcard": is_wildcard,
            "triple_captain": is_triple_captain,
            "free_hit": is_free_hit,
            # bank and free_transfers describe the state CARRIED FORWARD, so on a
            # Free Hit week they are the restored values. elements, squad_value
            # and captain describe the squad that actually played.
            "bank": state.bank,
            "free_transfers": state.free_transfers,
            "squad_value": played_value,
            "elements": played_elements,
        })

        if verbose:
            t = "-" if not transfers else ", ".join(f"{a}->{b}" for a, b in transfers)
            wc = "  WILDCARD" if is_wildcard else ""
            if is_free_hit:
                wc += "  FREE-HIT"
            if is_triple_captain:
                wc += "  TRIPLE-CAP"
            print(f"GW{gw:2d}  {result['points']:3d} pts  "
                  f"(total {state.total_points:4d})  transfer {t:>12}  "
                  f"bank {state.bank/10:.1f}  bench {result['bench_points']:2d}{wc}")

    return state, pd.DataFrame(log)


if __name__ == "__main__":
    season = load_season()
    print(f"Loaded {len(season)} player-gameweeks across "
          f"{season['gw'].nunique()} gameweeks\n")

    state, decisions = simulate_season(season)

    print(f"\n=== SEASON TOTAL: {state.total_points} points ===")
    print(f"Transfers made:  {decisions['transfer_in'].notna().sum()}")
    print(f"Points on bench: {decisions['bench_points'].sum()}")
    print(f"Autosubs used:   {decisions['n_subs'].sum()}")
    print(f"Vice rescues:    {(decisions['doubled_role'] == 'vice').sum()}")

    out = REPO_ROOT / "data" / "simulation_log.parquet"
    decisions.to_parquet(out, index=False)
    print(f"\nDecision log -> {out}")