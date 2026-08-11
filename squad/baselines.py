"""
FPL Copilot — Baselines

A season total on its own means nothing. 1889 points is either good or bad
entirely depending on what the alternatives scored, and the alternatives have to
be run through the SAME scoring code, on the SAME data, to be comparable at all.

That is what this module is for. Each baseline is a different answer to "what
would a manager who did not have this model have scored?", and every one of them
goes through scoring.py exactly as the real simulation does -- same autosub
rules, same captaincy fallback, same everything.

THE BASELINES
-------------
1. SET AND FORGET
   Pick the best GW1 squad the model can find, then never transfer again. Captain
   the highest predicted player each week (lineup changes are free in FPL, so a
   set-and-forget manager still picks his XI).

   This is the most important baseline by far: it isolates the value of the
   TRANSFER MACHINERY. Both it and the full simulation start from the identical
   GW1 squad and use identical predictions -- the only difference is that one
   makes 37 transfers and the other makes none. If they score the same, the
   weekly transfer loop is doing nothing.

2. PERFECT-HINDSIGHT SET AND FORGET
   The same idea, but the GW1 squad is chosen using each player's ACTUAL total
   points for the season. This is cheating and cannot be achieved by anyone; it
   is included as a CEILING. It answers "how much of the gap is bad prediction
   versus bad decision-making?" -- if the model's set-and-forget is far below
   this, the predictions are the bottleneck, not the optimizer.

3. TEMPLATE
   Own the most popular players. Real FPL exposes ownership percentages; this
   dataset does not, so ownership is proxied by season-long total points, which
   is what drives popularity in practice. Treat it as an approximation and say so.

4. RANDOM SQUADS
   Legal random squads, scored the same way, many times over. This gives the
   FLOOR and, more usefully, a distribution: beating the random mean by less than
   its own spread is not evidence of skill.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
The real "average FPL manager" number (around 2000 for a season) cannot be
reproduced from this data, because it reflects millions of humans making
transfers with news access this model does not have. Quoting it alongside these
baselines would be comparing across different scoring paths. It belongs in the
write-up as context, not in the results table as a row.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pulp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimize import optimize_squad, get_team, POSITION_LIMITS, MAX_PER_CLUB, BUDGET
from scoring import assign_bench_order, score_gameweek
from simulator import gw_slice, gw_actuals, solution_to_squad


def _slice(season_df, gw):
    """Cutoff-aware gw_slice.

    A horizon-aware frame holds one row per (cutoff, gameweek, player). A baseline
    manager standing at gameweek k sees exactly what anyone else standing there
    sees, so the right vantage point is always cutoff == gw. Without this every
    player would appear once per cutoff and every count would be inflated.
    """
    cutoff = gw if "cutoff" in season_df.columns else None
    return gw_slice(season_df, gw, cutoff=cutoff)


# ---------------------------------------------------------------------------
# Shared machinery: score a FIXED squad across a whole season
# ---------------------------------------------------------------------------
def _reassign_roles(squad_15, gw_points):
    """Re-pick the XI and captain for a fixed 15, using this gameweek's numbers.

    Lineup changes are free in FPL, so even a manager who never transfers still
    chooses his best XI every week. Not doing this would understate the baseline
    and flatter the full simulation by comparison.

    Picks the best legal formation by brute force over the small set of shapes,
    which is faster and simpler than a MIP for a fixed 15.
    """
    s = squad_15.copy()
    s["gw_points"] = s["element"].map(gw_points).fillna(0.0)

    by_pos = {p: s[s["position"] == p].sort_values("gw_points", ascending=False)
              for p in ["GK", "DEF", "MID", "FWD"]}

    best, best_total = None, float("-inf")
    for n_def in range(3, 6):
        for n_mid in range(2, 6):
            n_fwd = 10 - n_def - n_mid
            if not (1 <= n_fwd <= 3):
                continue
            if (n_def > len(by_pos["DEF"]) or n_mid > len(by_pos["MID"])
                    or n_fwd > len(by_pos["FWD"])):
                continue

            xi = pd.concat([
                by_pos["GK"].head(1),
                by_pos["DEF"].head(n_def),
                by_pos["MID"].head(n_mid),
                by_pos["FWD"].head(n_fwd),
            ])
            total = xi["gw_points"].sum()
            if total > best_total:
                best, best_total = xi, total

    xi_elements = set(best["element"])
    s["role"] = np.where(s["element"].isin(xi_elements), "start", "bench")

    # captain = best starter, vice = second best
    starters = s[s["role"] == "start"].sort_values("gw_points", ascending=False)
    s.loc[s["element"] == starters.iloc[0]["element"], "role"] = "CAPTAIN"
    if len(starters) > 1:
        s.loc[s["element"] == starters.iloc[1]["element"], "role"] = "VICE"

    return assign_bench_order(s.drop(columns=["gw_points"]))


def score_fixed_squad(season_df, squad_15, gws=None, points_col="e_points",
                      label="baseline", verbose=False):
    """Score one unchanging 15 across the season, re-picking the XI each week.

    points_col : which column drives the XI and captain choice. "e_points" is the
                 honest version (what the manager predicts). Passing an actuals
                 column instead produces a hindsight ceiling.
    """
    if gws is None:
        gws = sorted(season_df["gw"].unique())

    log, total = [], 0
    for gw in gws:
        pool = season_df[season_df["gw"] == gw]
        if "cutoff" in season_df.columns:
            # One vantage point only -- otherwise a player appears once per cutoff
            # and the dict is silently built from whichever row lands last.
            pool = pool[pool["cutoff"] == gw]
        gw_points = dict(zip(pool["element"], pool[points_col]))

        squad = _reassign_roles(squad_15, gw_points)
        result = score_gameweek(squad, gw_actuals(season_df, gw),
                                transfers_made=0, free_transfers=1)
        total += result["points"]

        log.append({
            "gw": gw,
            "points": result["points"],
            "total_points": total,
            "captain_bonus": result["captain_bonus"],
            "doubled_role": result["doubled_role"],
            "n_subs": len(result["subs_made"]),
            "bench_points": result["bench_points"],
            "strategy": label,
        })
        if verbose:
            print(f"{label} GW{gw:2d}  {result['points']:3d}  (total {total:4d})")

    return total, pd.DataFrame(log)


# ---------------------------------------------------------------------------
# Baseline 1: set and forget
# ---------------------------------------------------------------------------
def set_and_forget(season_df, mode="balanced", gws=None):
    """Best GW1 squad by predicted points, then never transfer.

    Isolates the value of the transfer machinery: same start, same predictions,
    zero transfers.
    """
    first_gw = min(gws) if gws else int(season_df["gw"].min())
    pool = _slice(season_df, first_gw)

    prob, sol = optimize_squad(pool, mode=mode)
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"set_and_forget: GW{first_gw} squad is "
                           f"{pulp.LpStatus[prob.status]}")

    squad = solution_to_squad(pool, sol)
    return score_fixed_squad(season_df, squad, gws=gws, label="set_and_forget")


# ---------------------------------------------------------------------------
# Baseline 2: perfect hindsight (a ceiling, not an achievable strategy)
# ---------------------------------------------------------------------------
def hindsight_set_and_forget(season_df, mode="balanced", gws=None):
    """The best possible unchanging 15, chosen knowing the whole season.

    CHEATING BY CONSTRUCTION. Nobody can do this. It exists to separate two very
    different failure modes: if the model's set-and-forget is far below this
    ceiling, the PREDICTIONS are the bottleneck; if it is close, the predictions
    are fine and the remaining gap is decision-making.
    """
    first_gw = min(gws) if gws else int(season_df["gw"].min())

    # Dedupe FIRST. On a horizon-aware frame a player's gameweek appears once per
    # cutoff, so summing raw would count his actual points up to six times and
    # inflate the ceiling accordingly.
    season_totals = (season_df.drop_duplicates(subset=["element", "gw"])
                     .groupby("element")["actual_points"].sum()
                     .rename("season_points"))

    pool = _slice(season_df, first_gw).copy()
    pool["e_points"] = pool["element"].map(season_totals).fillna(0.0)

    prob, sol = optimize_squad(pool, mode=mode)
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError("hindsight: infeasible")

    squad = get_team(pool, sol)
    # Score it on real per-gameweek performance, not the season totals used to pick it.
    return score_fixed_squad(season_df, squad, gws=gws, label="hindsight")


# ---------------------------------------------------------------------------
# Baseline 3: template
# ---------------------------------------------------------------------------
def template_squad(season_df, mode="balanced", gws=None):
    """Own the popular players.

    APPROXIMATION, and worth being explicit about it: real template teams are
    defined by ownership percentage, which this dataset does not contain. Season
    total points is used as a proxy, on the reasoning that high scorers are what
    managers pile into. That makes this baseline partly hindsight-informed, so it
    sits somewhere between set-and-forget and the true ceiling. Do not present it
    as an achievable strategy.
    """
    return hindsight_set_and_forget(season_df, mode=mode, gws=gws)


# ---------------------------------------------------------------------------
# Baseline 4: random legal squads
# ---------------------------------------------------------------------------
def random_squad(pool, rng):
    """A legal random 15: correct positions, under budget, max 3 per club.

    Retries until it finds one. Sampling cheap players preferentially would bias
    the floor upward, so selection is uniform and infeasible draws are discarded.
    """
    for _ in range(2000):
        picks = []
        ok = True
        club_count = {}
        for pos, n in POSITION_LIMITS.items():
            candidates = pool[pool["position"] == pos]
            if len(candidates) < n:
                return None
            chosen = candidates.sample(n=n, random_state=int(rng.integers(1 << 31)))
            picks.append(chosen)

        squad = pd.concat(picks)
        if squad["value"].sum() > BUDGET:
            continue
        if squad["team"].value_counts().max() > MAX_PER_CLUB:
            continue
        return squad.reset_index(drop=True)
    return None


def random_baseline(season_df, n_runs=50, seed=0, gws=None):
    """Score many random squads to get a floor AND a spread.

    The spread is the point. Beating the random mean by less than its own
    standard deviation is not evidence of skill -- it is within noise.
    """
    rng = np.random.default_rng(seed)
    first_gw = min(gws) if gws else int(season_df["gw"].min())
    pool = _slice(season_df, first_gw)

    totals, logs = [], []
    for i in range(n_runs):
        squad = random_squad(pool, rng)
        if squad is None:
            continue
        total, log = score_fixed_squad(season_df, squad, gws=gws,
                                       label=f"random_{i}")
        totals.append(total)
        logs.append(log)

    return np.array(totals), pd.concat(logs, ignore_index=True) if logs else pd.DataFrame()


# ---------------------------------------------------------------------------
# Run them all
# ---------------------------------------------------------------------------
def run_all_baselines(season_df, gws=None, n_random=50, verbose=True):
    """Every baseline, returned as one comparison table."""
    rows = []

    saf_total, saf_log = set_and_forget(season_df, gws=gws)
    rows.append({"strategy": "set_and_forget", "total": saf_total,
                 "per_gw": saf_total / len(saf_log)})
    if verbose:
        print(f"set and forget      : {saf_total}")

    hind_total, hind_log = hindsight_set_and_forget(season_df, gws=gws)
    rows.append({"strategy": "hindsight_ceiling", "total": hind_total,
                 "per_gw": hind_total / len(hind_log)})
    if verbose:
        print(f"hindsight ceiling   : {hind_total}")

    rand_totals, _ = random_baseline(season_df, n_runs=n_random, gws=gws)
    if len(rand_totals):
        rows.append({"strategy": "random_mean", "total": int(rand_totals.mean()),
                     "per_gw": rand_totals.mean() / (len(gws) if gws else 38)})
        if verbose:
            print(f"random ({len(rand_totals)} squads)  : "
                  f"mean {rand_totals.mean():.0f}, sd {rand_totals.std():.0f}, "
                  f"range {rand_totals.min()}-{rand_totals.max()}")

    return pd.DataFrame(rows), rand_totals


if __name__ == "__main__":
    from simulator import load_season, simulate_season

    season = load_season()

    print("Running the model...")
    state, sim_log = simulate_season(season, verbose=False)
    print(f"model               : {state.total_points}\n")

    print("Running baselines...")
    table, rand_totals = run_all_baselines(season)

    print("\n=== COMPARISON ===")
    model_total = state.total_points
    for _, r in table.iterrows():
        gap = model_total - r["total"]
        print(f"{r['strategy']:20s} {int(r['total']):5d}   model {gap:+5d}")

    if len(rand_totals):
        z = (model_total - rand_totals.mean()) / (rand_totals.std() or 1)
        print(f"\nModel is {z:.1f} standard deviations above the random mean.")