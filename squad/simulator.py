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
- NO CHIPS. No wildcard, bench boost, triple captain or free hit.
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

import pandas as pd
import pulp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimize import optimize_squad, get_team, BUDGET
from scoring import assign_bench_order, score_gameweek
from squad_state import SquadState, sell_price, STARTING_BUDGET

REPO_ROOT = Path(__file__).resolve().parent.parent
WALKFORWARD_PATH = REPO_ROOT / "data" / "walkforward_2526.parquet"
HISTORY_PATH = REPO_ROOT / "data" / "history" / "all_seasons_fixed.parquet"
SEASON = "2025-26"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_season(walkforward_path=WALKFORWARD_PATH, history_path=HISTORY_PATH):
    """Load as-of predictions, realized outcomes, and prices for every gameweek.

    Returns a single frame with one row per player-gameweek carrying both the
    prediction (e_points) and the truth (minutes, actual_points), plus price.
    """
    wf = pd.read_parquet(walkforward_path)

    history = pd.read_parquet(history_path)
    history = history[history["season"] == SEASON]
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
    return df


def gw_slice(season_df, gw):
    """One gameweek's player pool, in the shape optimize.py expects."""
    d = season_df[season_df["gw"] == gw].copy()
    cols = ["element", "name", "position", "team", "value", "e_points"]
    return d[cols].reset_index(drop=True)


def gw_actuals(season_df, gw):
    """One gameweek's realized outcomes, in the shape scoring.py expects."""
    d = season_df[season_df["gw"] == gw]
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
def simulate_season(season_df, mode="balanced", gws=None, verbose=True):
    """Run the full season. Returns (final_state, decision_log DataFrame).

    The decision log is one row per gameweek recording the squad, the transfer,
    the captain, and the points. It is what makes the result auditable rather
    than a single number to be taken on trust.
    """
    if gws is None:
        gws = sorted(season_df["gw"].unique())

    log = []
    state = None

    for gw in gws:
        pool = gw_slice(season_df, gw)
        actuals = gw_actuals(season_df, gw)
        prices = dict(zip(pool["element"], pool["value"]))

        # -- decide --
        if state is None:
            # Gameweek 1: no squad yet, so this is a free pick from scratch.
            prob, sol = optimize_squad(pool, mode=mode)
            if pulp.LpStatus[prob.status] != "Optimal":
                raise RuntimeError(f"GW{gw}: initial squad is {pulp.LpStatus[prob.status]}")
            team = solution_to_squad(pool, sol)
            transfer = None

            start = team.copy()
            start["purchase_price"] = start["value"].astype(int)
            state = SquadState(start,
                               bank=STARTING_BUDGET - int(start["purchase_price"].sum()),
                               free_transfers=1)
        else:
            team, transfer = decide_gameweek(pool, state, prices, mode=mode)
            if team is None:
                raise RuntimeError(f"GW{gw}: no feasible squad found")

            if transfer is not None:
                out_elem, in_elem = transfer
                # The incoming player is always a REAL pool player (blanked players
                # are only ever injected for the ones already owned), so the raw
                # pool row carries his true market price -- what the manager pays.
                in_row = pool[pool["element"] == in_elem].iloc[0]
                state.make_transfer(out_elem, in_elem, in_row, prices)

        # -- keep the state's roles in step with what was just chosen --
        roles = team.set_index("element")[["role", "bench_order"]]
        state.squad = state.squad.drop(columns=["role", "bench_order"], errors="ignore")
        state.squad = state.squad.merge(
            roles, left_on="element", right_index=True, how="left")

        n_transfers = 0 if transfer is None else 1
        paid = state.spend_transfers(n_transfers)

        # -- score --
        result = score_gameweek(
            state.squad, actuals,
            transfers_made=n_transfers,
            free_transfers=n_transfers if paid == 0 else 0,
        )
        state.end_gameweek(result["points"])

        cap_row = state.squad[state.squad["role"] == "CAPTAIN"]
        log.append({
            "gw": gw,
            "points": result["points"],
            "raw_points": result["raw_points"],
            "hit": result["hit"],
            "total_points": state.total_points,
            "captain": cap_row["name"].iloc[0] if len(cap_row) and "name" in cap_row else None,
            "captain_bonus": result["captain_bonus"],
            "doubled_role": result["doubled_role"],
            "n_subs": len(result["subs_made"]),
            "bench_points": result["bench_points"],
            "transfer_out": transfer[0] if transfer else None,
            "transfer_in": transfer[1] if transfer else None,
            "bank": state.bank,
            "free_transfers": state.free_transfers,
            "squad_value": state.sell_value(prices),
            "elements": list(state.elements),
        })

        if verbose:
            t = "-" if transfer is None else f"{transfer[0]}->{transfer[1]}"
            print(f"GW{gw:2d}  {result['points']:3d} pts  "
                  f"(total {state.total_points:4d})  transfer {t:>12}  "
                  f"bank {state.bank/10:.1f}  bench {result['bench_points']:2d}")

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