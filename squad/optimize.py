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
def optimize_squad(df, mode=None, bench_weight=None, locked_elements=None):
    """Build and solve the MIP for one gameweek: 15 + XI + captain.

    df               : output of load_gw_data()
    mode             : named bench preset -- one of MODES (default "balanced")
    bench_weight     : raw bench weight; overrides `mode` if given
    locked_elements  : optional list of element IDs forced into the squad

    Returns (prob, sol):
        prob -- the solved PuLP problem (check pulp.LpStatus[prob.status])
        sol  -- dict of the three variable sets: {"pick","start","captain"},
                each {row_index: binary variable}
    """
    if locked_elements is None:
        locked_elements = []
    w = resolve_bench_weight(mode, bench_weight)

    prob = pulp.LpProblem("fpl_squad_xi", pulp.LpMaximize)

    # three sets of on/off decision variables per player
    pick    = {i: pulp.LpVariable(f"pick_{i}",    cat="Binary") for i in df.index}
    start   = {i: pulp.LpVariable(f"start_{i}",   cat="Binary") for i in df.index}
    captain = {i: pulp.LpVariable(f"captain_{i}", cat="Binary") for i in df.index}

    pts = df["e_points"]

    # --- objective: XI points + captain again (2x) + weighted bench ---
    # a bench player is "picked but not starting" -> (pick - start)
    prob += (
        pulp.lpSum(start[i]   * pts[i] for i in df.index)
        + pulp.lpSum(captain[i] * pts[i] for i in df.index)
        + w * pulp.lpSum((pick[i] - start[i]) * pts[i] for i in df.index)
    )

    # --- squad-level rules (on `pick`) ---
    prob += pulp.lpSum(pick[i] for i in df.index) == SQUAD_SIZE

    for pos, n in POSITION_LIMITS.items():
        prob += pulp.lpSum(
            pick[i] for i in df.index if df.loc[i, "position"] == pos
        ) == n

    prob += pulp.lpSum(pick[i] * df.loc[i, "value"] for i in df.index) <= BUDGET

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

    # --- locked players: force into the squad ---
    for elem in locked_elements:
        matches = df.index[df["element"] == elem]
        if len(matches) == 0:
            raise ValueError(f"Locked element {elem} not found in GW data.")
        prob += pick[matches[0]] == 1

    prob.solve(pulp.PULP_CBC_CMD(msg=False))  # msg=False silences the solver log
    return prob, {"pick": pick, "start": start, "captain": captain}


def resolve_names(df, lock_names):
    """Turn a list of name searches into a list of element IDs.

    Substring, case-insensitive. Warns (and skips) on no-match or
    multi-match so we never silently lock the wrong player.
    """
    locked_elements = []
    for nm in lock_names:
        matches = df[df["name"].str.contains(nm, case=False, na=False)]
        if len(matches) == 0:
            print(f"[skip] no player matches '{nm}'")
        elif len(matches) > 1:
            print(f"[skip] '{nm}' matches {len(matches)} players -- be more specific:")
            print(matches[["name", "team"]].to_string(index=False))
        else:
            locked_elements.append(matches.iloc[0]["element"])
            print(f"[lock] {matches.iloc[0]['name']}")
    return locked_elements


def optimize_by_names(df, lock_names=None, mode=None, bench_weight=None):
    """Convenience wrapper: lock players by name, then optimize the rest."""
    if lock_names is None:
        lock_names = []
    locked_elements = resolve_names(df, lock_names)
    return optimize_squad(
        df, mode=mode, bench_weight=bench_weight, locked_elements=locked_elements
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def get_team(df, sol):
    """Return the selected 15 as a dataframe with a `role` column
    (CAPTAIN / start / bench), sorted starters-first then by position."""
    pick, start, captain = sol["pick"], sol["start"], sol["captain"]
    rows = []
    for i in df.index:
        if pick[i].value() == 1:
            if captain[i].value() == 1:
                role = "CAPTAIN"
            elif start[i].value() == 1:
                role = "start"
            else:
                role = "bench"
            rows.append((df.loc[i, "element"], df.loc[i, "name"],
                         df.loc[i, "position"], df.loc[i, "team"],
                         df.loc[i, "value"], df.loc[i, "e_points"], role))

    team = pd.DataFrame(rows, columns=[
        "element", "name", "position", "team", "value", "e_points", "role"
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