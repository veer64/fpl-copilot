"""
FPL Copilot — Squad Optimizer (single gameweek)

Picks the provably-optimal FPL squad for a given gameweek, choosing the 15,
the starting XI (in a legal formation), and the captain all at once.

FPL rules enforced:
    - 15 players total (2 GK, 5 DEF, 5 MID, 3 FWD)
    - total price <= £100.0m
    - at most 3 players from any single club
    - exactly 11 starters in a legal formation (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD)
    - exactly 1 captain, who must be a starter (captain scores 2x)
    - exactly 1 vice-captain, a different starter (takes the armband if the
      captain plays 0 minutes)

VICE-CAPTAIN
------------
The vice only scores when the captain blanks, so his expected contribution is
almost zero -- but he must still be CHOSEN, and chosen sensibly. Left out of the
objective entirely, the solver would pick any starter at random, since all
choices score identically.

So the vice carries a deliberately tiny objective weight (VICE_WEIGHT). It is a
tie-breaker, not a real term: large enough to make the solver prefer the best
remaining starter, small enough that it can never change which 15 are bought or
who starts. Do not raise it to "value the vice properly" -- the honest version of
that is weighting by P(captain does not play), which needs the minutes model and
belongs in a later revision.

BENCH WEIGHT
------------
Only the starting XI (+ the captain again) score in real FPL; the bench only
plays when a starter is auto-subbed. We model this with a `bench_weight`:
each bench player contributes `bench_weight * e_points` to the objective.

    weight 0.0  -> ghost bench (max starting XI, throwaway bench)
    weight 0.2  -> real, usable bench with minimal XI sacrifice   (default)
    weight 1.0  -> all 15 weighted equally (the old "best 15" behaviour)

Named modes map to sensible weights, but you can always pass a raw number:

    MODES = {"best_11": 0.0, "balanced": 0.2, "strong_bench": 0.35, "best_15": 1.0}

    optimize_squad(df, mode="balanced")         # by name
    optimize_squad(df, bench_weight=0.5)         # raw override (e.g. "stronger bench")

LOCKING
-------
Any number of players can be forced into the squad, by element ID or by name:

    optimize_squad(df, locked_elements=[381])
    optimize_by_names(df, lock_names=["Salah", "Haaland"])

BANNING
-------
The mirror of locking: any number of players can be forbidden from the squad.

    optimize_squad(df, banned_elements=[381])
    optimize_by_names(df, ban_names=["Salah"])

This exists for the season simulator. To decide "should I transfer this player
out?", you need the best squad available WITHOUT him — which you cannot ask for
using locks alone. Banning also covers injuries and suspensions.

A player cannot be both locked and banned; that raises an error rather than
silently resolving one way.

Input files (relative to repo root):
    data/predictions_2526.parquet          -- e_points per player-GW (from assembly.py)
    data/history/all_seasons_fixed.parquet -- has the price column ("value")

Usage:
    from optimize import load_gw_data, optimize_squad, optimize_by_names, show_team

    df = load_gw_data(gw=1)
    prob, sol = optimize_squad(df, mode="balanced")
    show_team(df, sol)
"""

import pandas as pd
import pulp

# ---------------------------------------------------------------------------
# Config — the FPL rules, in one place so they're easy to find and change
# ---------------------------------------------------------------------------
BUDGET = 1000                 # £100.0m, in FPL's tenths-of-a-million units
SQUAD_SIZE = 15
XI_SIZE = 11
POSITION_LIMITS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}   # squad counts (exact)
FORMATION = {"GK": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}  # XI (min, max)
MAX_PER_CLUB = 3
POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}

# Tie-breaker weight for the vice-captain. Deliberately tiny: it decides WHICH
# starter gets the armband if the captain blanks, without ever influencing which
# 15 are bought or who starts. See the VICE-CAPTAIN note in the module docstring.
VICE_WEIGHT = 0.001

# P5 piece 2 (interim plan section 4): XI tie-breaking by p_60plus. When two
# players' e_points are within noise, prefer the one more likely to finish
# the match (appearance points are 2 vs 1, and the determinism log showed
# exactly-tied optima are everywhere). Implemented as a small objective
# weight on start variables: a lower-e_points player can displace a rival
# only if his e_points deficit is < WEIGHT x (his p_60plus - the rival's),
# i.e. at most 0.05 pts. THE NOISE THRESHOLD IS 0.05 because step-0
# prediction MAE is ~1.07 aggregate / ~2.4 in the starter band -- 0.05 is
# 2-5% of measurement noise, far below anything the predictions can resolve,
# while being ~5e4 x solver tolerance so ties break deterministically.
# Gated and stamped per decision-log row as `xi_tiebreak_p60`. NOT ADOPTED --
# measured 2026-08-21, report-only.
XI_TIEBREAK_P60 = False
XI_TIEBREAK_WEIGHT = 0.05


def _default_solver():
    """Pick the best available MIP solver.

    CBC ships with PuLP and always works. HiGHS is a modern open-source solver,
    roughly twice as fast on this problem for an IDENTICAL objective (verified on
    GW1: 61.2512 both ways, 1.24s vs 0.64s).

    Speed stops being a nicety once the multi-GW transfer MIP arrives: that model
    is perhaps fifty times this size (750 players x 8 gameweeks x buy/sell/hold
    binaries), and a solver that merely copes here will crawl there.

    Falls back to CBC silently if highspy is not installed, so the module never
    hard-depends on an optional package.
    """
    # FPL_SOLVER_THREADS caps HiGHS's threads per process. HiGHS multi-threads
    # by default, so N parallel simulations x unbounded threads oversubscribes
    # the machine -- measured 2026-08-20: the same season's sims ran 11-14 min
    # solo and 40-78 min under five unthrottled processes. Parallel sweep
    # drivers set this to 2; unset keeps the old single-process behaviour.
    import os
    threads = os.environ.get("FPL_SOLVER_THREADS")
    try:
        if "HiGHS" in pulp.listSolvers(onlyAvailable=True):
            return (pulp.HiGHS(msg=False, threads=int(threads)) if threads
                    else pulp.HiGHS(msg=False))
    except Exception:
        pass
    return pulp.PULP_CBC_CMD(msg=False)

# named bench-weight presets (raw bench_weight always overrides these)
MODES = {
    "best_11": 0.0,       # pure starting XI, ghost bench
    "balanced": 0.2,      # strong XI + a genuinely useful bench (default)
    "strong_bench": 0.35, # trade a little XI ceiling for a safer bench
    "best_15": 1.0,       # all 15 equal (original behaviour)
}
DEFAULT_MODE = "balanced"

from pathlib import Path

# repo root = two levels up from this file (squad/optimize.py -> fpl-copilot/)
REPO_ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS_PATH = REPO_ROOT / "data" / "predictions_2526.parquet"
HISTORY_PATH = REPO_ROOT / "data" / "history" / "all_seasons_fixed.parquet"
SEASON = "2025-26"


# ---------------------------------------------------------------------------
# Data prep
# ---------------------------------------------------------------------------
def load_gw_data(gw, predictions_path=PREDICTIONS_PATH, history_path=HISTORY_PATH):
    """Load predictions for one gameweek and attach each player's price.

    Returns a tidy dataframe (one row per player) with the columns the
    optimizer needs: element, name, position, team, value, e_points.
    Index is reset to 0..N-1 so it lines up with the decision variables.
    """
    preds = pd.read_parquet(predictions_path)
    gw_preds = preds[preds["gw"] == gw].copy()

    # prices come from the history file's "value" column (round == gameweek)
    history = pd.read_parquet(history_path)
    history = history[history["season"] == SEASON]
    prices = history[history["round"] == gw][["element", "value"]].copy()

    # a couple of players can have duplicate price rows (identical value) --
    # dedupe so no player appears twice in the optimizer input
    prices = prices.drop_duplicates(subset="element", keep="first")

    merged = gw_preds.merge(prices, on="element", how="left")

    # guard: every player must have a price, or the budget rule is meaningless
    missing = merged["value"].isna().sum()
    if missing:
        raise ValueError(
            f"{missing} players have no price for GW{gw} -- cannot optimize. "
            "Check the join keys / history file coverage."
        )

    cols = ["element", "name", "position", "team", "value", "e_points"]
    return merged[cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Bench-weight resolution
# ---------------------------------------------------------------------------
def resolve_bench_weight(mode=None, bench_weight=None):
    """Decide the bench weight from a named mode and/or a raw override.

    Priority: an explicit bench_weight wins. Otherwise the named mode is
    looked up. If neither is given, DEFAULT_MODE is used.
    """
    if bench_weight is not None:
        return float(bench_weight)
    if mode is None:
        mode = DEFAULT_MODE
    if mode not in MODES:
        raise ValueError(
            f"Unknown mode '{mode}'. Choose one of {list(MODES)}, "
            "or pass a raw bench_weight."
        )
    return MODES[mode]


# ---------------------------------------------------------------------------
# The optimizer
# ---------------------------------------------------------------------------
def optimize_squad(df, mode=None, bench_weight=None, locked_elements=None,
                   banned_elements=None, budget=None, solver=None):
    """Build and solve the MIP for one gameweek: 15 + XI + captain.

    df               : output of load_gw_data()
    mode             : named bench preset -- one of MODES (default "balanced")
    bench_weight     : raw bench weight; overrides `mode` if given
    locked_elements  : optional list of element IDs forced into the squad
    banned_elements  : optional list of element IDs forbidden from the squad
    budget           : spending limit in tenths; defaults to the full BUDGET
    solver           : PuLP solver instance; defaults to HiGHS, else CBC

    Returns (prob, sol):
        prob -- the solved PuLP problem (check pulp.LpStatus[prob.status])
        sol  -- dict of the four variable sets: {"pick","start","captain","vice"},
                each {row_index: binary variable}
    """
    if locked_elements is None:
        locked_elements = []
    if banned_elements is None:
        banned_elements = []

    # A player cannot be both required and forbidden -- that is a caller bug,
    # and silently picking a winner would hide it.
    clash = set(locked_elements) & set(banned_elements)
    if clash:
        raise ValueError(f"Elements both locked and banned: {sorted(clash)}")

    # A fresh manager has the full BUDGET. A mid-season manager does not -- he has
    # his squad's SELL value plus whatever is in the bank, which is strictly less
    # than 100m once prices have moved. The simulator passes that real figure in.
    # Defaulting to BUDGET keeps every standalone call behaving exactly as before.
    if budget is None:
        budget = BUDGET

    w = resolve_bench_weight(mode, bench_weight)

    prob = pulp.LpProblem("fpl_squad_xi", pulp.LpMaximize)

    # four sets of on/off decision variables per player
    pick    = {i: pulp.LpVariable(f"pick_{i}",    cat="Binary") for i in df.index}
    start   = {i: pulp.LpVariable(f"start_{i}",   cat="Binary") for i in df.index}
    captain = {i: pulp.LpVariable(f"captain_{i}", cat="Binary") for i in df.index}
    vice    = {i: pulp.LpVariable(f"vice_{i}",    cat="Binary") for i in df.index}

    pts = df["e_points"]

    # --- objective: XI points + captain again (2x) + weighted bench + vice tiebreak ---
    # a bench player is "picked but not starting" -> (pick - start)
    obj = (
        pulp.lpSum(start[i]   * pts[i] for i in df.index)
        + pulp.lpSum(captain[i] * pts[i] for i in df.index)
        + w * pulp.lpSum((pick[i] - start[i]) * pts[i] for i in df.index)
        + VICE_WEIGHT * pulp.lpSum(vice[i] * pts[i] for i in df.index)
    )
    if XI_TIEBREAK_P60:
        if "p_60plus" not in df.columns:
            raise ValueError(
                "XI_TIEBREAK_P60 is on but the pool has no p_60plus column "
                "-- plumb it through gw_slice rather than silently skipping "
                "the tiebreak")
        p60 = df["p_60plus"].fillna(0.0).astype(float)
        obj += XI_TIEBREAK_WEIGHT * pulp.lpSum(
            start[i] * p60[i] for i in df.index)
    prob += obj

    # --- squad-level rules (on `pick`) ---
    prob += pulp.lpSum(pick[i] for i in df.index) == SQUAD_SIZE

    for pos, n in POSITION_LIMITS.items():
        prob += pulp.lpSum(
            pick[i] for i in df.index if df.loc[i, "position"] == pos
        ) == n

    prob += pulp.lpSum(pick[i] * df.loc[i, "value"] for i in df.index) <= budget

    for team in df["team"].unique():
        prob += pulp.lpSum(
            pick[i] for i in df.index if df.loc[i, "team"] == team
        ) <= MAX_PER_CLUB

    # --- starting XI rules ---
    prob += pulp.lpSum(start[i] for i in df.index) == XI_SIZE

    # can only start someone you picked
    for i in df.index:
        prob += start[i] <= pick[i]

    # legal formation (min/max starters per position)
    for pos, (lo, hi) in FORMATION.items():
        starters_in_pos = pulp.lpSum(
            start[i] for i in df.index if df.loc[i, "position"] == pos
        )
        prob += starters_in_pos >= lo
        prob += starters_in_pos <= hi

    # --- captain rules ---
    prob += pulp.lpSum(captain[i] for i in df.index) == 1
    for i in df.index:                       # captain must be a starter
        prob += captain[i] <= start[i]

    # --- vice-captain rules ---
    prob += pulp.lpSum(vice[i] for i in df.index) == 1
    for i in df.index:
        prob += vice[i] <= start[i]          # vice must be a starter
        prob += captain[i] + vice[i] <= 1    # and cannot also be the captain

    # --- locked players: force into the squad ---
    for elem in locked_elements:
        matches = df.index[df["element"] == elem]
        if len(matches) == 0:
            raise ValueError(f"Locked element {elem} not found in GW data.")
        prob += pick[matches[0]] == 1

    # --- banned players: forbid from the squad ---
    # A missing banned player is NOT an error: he may simply not appear in this
    # gameweek's data (blank gameweek, no fixture), which already achieves the ban.
    for elem in banned_elements:
        matches = df.index[df["element"] == elem]
        if len(matches) > 0:
            prob += pick[matches[0]] == 0

    prob.solve(solver or _default_solver())   # msg=False silences the solver log
    return prob, {"pick": pick, "start": start, "captain": captain, "vice": vice}


def resolve_names(df, names, action="lock"):
    """Turn a list of name searches into a list of element IDs.

    Substring, case-insensitive. Warns (and skips) on no-match or
    multi-match so we never silently lock or ban the wrong player.
    """
    elements = []
    for nm in names:
        matches = df[df["name"].str.contains(nm, case=False, na=False)]
        if len(matches) == 0:
            print(f"[skip] no player matches '{nm}'")
        elif len(matches) > 1:
            print(f"[skip] '{nm}' matches {len(matches)} players -- be more specific:")
            print(matches[["name", "team"]].to_string(index=False))
        else:
            elements.append(matches.iloc[0]["element"])
            print(f"[{action}] {matches.iloc[0]['name']}")
    return elements


def optimize_by_names(df, lock_names=None, ban_names=None, mode=None, bench_weight=None):
    """Convenience wrapper: lock and/or ban players by name, then optimize the rest."""
    if lock_names is None:
        lock_names = []
    if ban_names is None:
        ban_names = []
    locked_elements = resolve_names(df, lock_names, action="lock")
    banned_elements = resolve_names(df, ban_names, action="ban")
    return optimize_squad(
        df, mode=mode, bench_weight=bench_weight,
        locked_elements=locked_elements, banned_elements=banned_elements
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
# Binary variables come back from the solver as FLOATS, and different solvers
# round differently: CBC tends to return a clean 1.0 while HiGHS may return
# 0.9999999997. Comparing with `== 1` therefore silently DROPS players and was
# producing 12- and 14-man squads the moment the solver changed. Always threshold
# solver output rather than testing it for exact equality.
_BINARY_THRESHOLD = 0.5


def _is_set(var):
    """True if a binary decision variable came back as 1, allowing for the
    floating-point slop every MIP solver leaves behind."""
    v = var.value()
    return v is not None and v > _BINARY_THRESHOLD


def get_team(df, sol):
    """Return the selected 15 as a dataframe with a `role` column
    (CAPTAIN / VICE / start / bench), sorted starters-first then by position."""
    pick, start, captain = sol["pick"], sol["start"], sol["captain"]
    vice = sol.get("vice", {})               # tolerate older solutions without vice
    # Probability columns ride along when the pool carries them -- bench
    # ordering (scoring.BENCH_ORDER_BY_PLAY) needs p_play_any downstream.
    extra = [c for c in ("p_play_any", "p_60plus") if c in df.columns]
    rows = []
    for i in df.index:
        if _is_set(pick[i]):
            if _is_set(captain[i]):
                role = "CAPTAIN"
            elif i in vice and _is_set(vice[i]):
                role = "VICE"
            elif _is_set(start[i]):
                role = "start"
            else:
                role = "bench"
            rows.append((df.loc[i, "element"], df.loc[i, "name"],
                         df.loc[i, "position"], df.loc[i, "team"],
                         df.loc[i, "value"], df.loc[i, "e_points"], role,
                         *[df.loc[i, c] for c in extra]))

    team = pd.DataFrame(rows, columns=[
        "element", "name", "position", "team", "value", "e_points", "role",
        *extra
    ])
    team["role_sort"] = (team["role"] == "bench").astype(int)   # starters first
    team["pos_sort"] = team["position"].map(POS_ORDER)
    team = team.sort_values(
        ["role_sort", "pos_sort", "e_points"], ascending=[True, True, False]
    )
    return team.drop(columns=["role_sort", "pos_sort"]).reset_index(drop=True)


def team_points(df, sol):
    """The objective value the way FPL actually scores it:
    starting XI points + the captain's points again."""
    team = get_team(df, sol)
    starters = team[team["role"] != "bench"]
    cap_pts = team.loc[team["role"] == "CAPTAIN", "e_points"].iloc[0]
    return round(starters["e_points"].sum() + cap_pts, 2)


def show_team(df, sol):
    """Pretty-print the team, marking the captain, plus a summary."""
    team = get_team(df, sol)
    display = team.copy()
    display.loc[display["role"] == "CAPTAIN", "name"] += "  (C)"
    display.loc[display["role"] == "VICE", "name"] += "  (V)"

    print(display[["name", "position", "team", "value", "e_points", "role"]]
          .to_string(index=False))

    bench = team[team["role"] == "bench"]
    print(f"\nTotal spent:            £{team['value'].sum() / 10:.1f}m")
    print(f"Starting XI + captain:  {team_points(df, sol)} pts")
    print(f"Bench value:            £{bench['value'].sum() / 10:.1f}m")
    print("\nPlayers per club:")
    print(team["team"].value_counts().to_string())


# ---------------------------------------------------------------------------
# Run directly: python optimize.py  -> best balanced GW1 team from scratch
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    df = load_gw_data(gw=1)
    prob, sol = optimize_squad(df, mode="balanced")
    print("Status:", pulp.LpStatus[prob.status],
          f"(mode=balanced, bench_weight={MODES['balanced']})\n")
    show_team(df, sol)