"""
FPL Copilot — P1 Step 2: scenario-robust opening squad (interim plan §4).

The deterministic objective maximises EXPECTED points and prices robustness at
zero -- but the opening squad is the one decision that can be corrected only
one player per week, so being wrong at GW1 is expensive (coldstart_log). This
module picks the GW1 fifteen by sampling K scenarios from the model's own
uncertainty and choosing the squad that does best ACROSS them, with a simple
one-repair-per-week recourse so that repairable failure beats unrepairable
failure.

Everything is read from GW1's own cutoff (horizon_step 0-5); the caller hands
in the same gw_slice(cutoff=gw) pools the deterministic path uses, plus the
matching probability/component columns, so no later-cutoff row can enter.

SAMPLING (per scenario, player, week -- columns named exactly):
  participation: ONE uniform u_i per (player, scenario) shared across weeks:
    played = u_i < p_play_any[t], sixty = u_i < p_60plus[t]. Comonotone across
    weeks => persistent availability regimes (a drawn-dead player stays dead
    unless the model's own probability rises later). Null probs (~4% fringe
    rows): p_play = min(1, pts_appear), p60 = max(0, pts_appear - 1).
  appearance: 2 if sixty else 1 if played else 0   (E = pts_appear, since
    pts_appear = p_60plus + p_play_any)
  goals:   played -> Poisson(pts_goals/GOAL_PTS/p_play) * GOAL_PTS
  assists: played -> Poisson(pts_assists/3/p_play) * 3
  clean sheet: sixty -> Bern(min(1, pts_cs/CS_PTS/p60)) * CS_PTS
  def contribution: sixty -> Bern(min(1, pts_dc/2/p60)) * 2
  saves+conceded+cards+bonus: expectation scaled to the draw:
    (pts_saves+pts_conceded+pts_cards+exp_bonus)/p_play if played else 0
  Returns independent across players and weeks; NO team-level correlation
  (stated limitation). rng = default_rng(SEED), deterministic given the file.

CANDIDATES: K deterministic free-pick horizon MIPs (build_and_solve, the
Step-1 path) -- one per scenario with e_points := that scenario's points --
deduplicated, plus any caller-supplied reference squads.

SELECTION (recourse-aware): each candidate x each scenario: weeks t=0..5,
XI = formation-legal argmax of week-t scenario points among the current 15,
captain x2 = best in XI, value x decay^t. After each week t<5 ONE repair may
execute: sell one of the three lowest-remaining-value members, buy the best
same-position replacement affordable at GW1 prices (club limit enforced,
bank tracked) by remaining decayed scenario value, only if it strictly
improves. Squad = argmax MEAN scenario value. This APPROXIMATES one-transfer-
per-week recourse; simultaneous failures queue, so unrepairable pile-ups
score worse. It is not the exact stochastic program.

NOT ADOPTED: gated by simulator.OPENING_ROBUST_ACTIVE (False on disk),
stamped per decision-log row as `opening_robust_active`.
"""

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pulp  # noqa: E402

from optimize import optimize_squad, get_team  # noqa: E402
from transfer_mip import build_and_solve  # noqa: E402

SEED = 20260820
K_DEFAULT = 50
# The columns the simulator slices out of the walk-forward frame (cutoff==gw1
# rows only) to hand to the sampler.
PROB_COLS = ["element", "name", "position", "team", "value",
             "p_play_any", "p_60plus", "pts_appear", "pts_goals",
             "pts_assists", "pts_cs", "pts_dc", "pts_saves", "pts_conceded",
             "pts_cards", "exp_bonus"]
GOAL_PTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
MAX_PER_CLUB = 3
BUDGET = 1000
FORMATIONS = [(d, m, f) for d, m, f in product(range(3, 6), range(2, 6),
                                               range(1, 4)) if d + m + f == 10]


def _prob_frames(prob_by_gw):
    """Align the per-week probability/component frames on a common player
    axis. Returns (players, pos, team, price, arrays dict [n x T])."""
    gws = list(prob_by_gw)
    players = sorted(set().union(*[set(df["element"]) for df in
                                   prob_by_gw.values()]))
    idx = {e: i for i, e in enumerate(players)}
    n, T = len(players), len(gws)
    cols = ["p_play_any", "p_60plus", "pts_appear", "pts_goals", "pts_assists",
            "pts_cs", "pts_dc", "pts_saves", "pts_conceded", "pts_cards",
            "exp_bonus", "value"]
    A = {c: np.zeros((n, T)) for c in cols}
    present = np.zeros((n, T), dtype=bool)
    pos, team, name = {}, {}, {}
    for t, gw in enumerate(gws):
        df = prob_by_gw[gw]
        rows = df.set_index("element")
        for e in rows.index:
            i = idx[e]
            present[i, t] = True
            r = rows.loc[e]
            pos.setdefault(e, r["position"])
            team.setdefault(e, r["team"])
            name.setdefault(e, r.get("name", str(e)))
            for c in cols:
                v = r.get(c, 0.0)
                A[c][i, t] = 0.0 if pd.isna(v) else float(v)
    # null-probability fallback: p_play = min(1, pts_appear), p60 = rest
    pa, p6 = A["p_play_any"], A["p_60plus"]
    app = A["pts_appear"]
    bad = present & (pa <= 0) & (app > 0)
    pa[bad] = np.minimum(1.0, app[bad])
    p6[bad] = np.maximum(0.0, app[bad] - 1.0)
    return players, idx, pos, team, name, A, present


def sample_scenarios(prob_by_gw, K=K_DEFAULT, seed=SEED):
    """Draw K scenarios. Returns (players, pos, team, name, price0,
    pts[K x n x T]) -- price0 is each player's GW1 price (first week seen)."""
    players, idx, pos, team, name, A, present = _prob_frames(prob_by_gw)
    n, T = present.shape
    rng = np.random.default_rng(seed)
    pa = np.clip(A["p_play_any"], 0.0, 1.0)
    p6 = np.clip(np.minimum(A["p_60plus"], pa), 0.0, 1.0)
    safe_pa = np.where(pa > 0, pa, 1.0)
    safe_p6 = np.where(p6 > 0, p6, 1.0)
    lam_g = np.where(pa > 0, A["pts_goals"] / safe_pa, 0.0)
    lam_a = np.where(pa > 0, A["pts_assists"] / 3.0 / safe_pa, 0.0)
    cs_den = np.array([CS_PTS[pos[e]] for e in players])[:, None].astype(float)
    p_cs_c = np.where((p6 > 0) & (cs_den > 0),
                      np.minimum(1.0, A["pts_cs"] / np.where(cs_den > 0, cs_den, 1)
                                 / safe_p6), 0.0)
    p_dc_c = np.where(p6 > 0, np.minimum(1.0, A["pts_dc"] / 2.0 / safe_p6), 0.0)
    goal_val = np.array([GOAL_PTS[pos[e]] for e in players])[:, None].astype(float)
    smalls = np.where(pa > 0, (A["pts_saves"] + A["pts_conceded"]
                               + A["pts_cards"] + A["exp_bonus"]) / safe_pa, 0.0)

    pts = np.zeros((K, n, T))
    for k in range(K):
        u = rng.random(n)[:, None]                      # one uniform per player
        played = (u < pa) & present
        sixty = (u < p6) & present
        goals = rng.poisson(np.where(played, lam_g / np.where(goal_val > 0,
                                                              goal_val, 1), 0.0))
        assists = rng.poisson(np.where(played, lam_a, 0.0))
        cs = (rng.random((n, T)) < np.where(sixty, p_cs_c, 0.0))
        dc = (rng.random((n, T)) < np.where(sixty, p_dc_c, 0.0))
        p = (np.where(sixty, 2.0, np.where(played, 1.0, 0.0))
             + goals * goal_val + assists * 3.0
             + cs * cs_den + dc * 2.0
             + np.where(played, smalls, 0.0))
        pts[k] = p
    price0 = np.zeros(n)
    for i, e in enumerate(players):
        first = np.argmax(present[i])
        price0[i] = A["value"][i, first]
    return players, idx, pos, team, name, price0, pts, present


def _best_xi_value(members_idx, week_pts, pos_arr):
    """Formation-legal argmax XI value + captain double, from scenario pts."""
    by_pos = {p: [] for p in ("GK", "DEF", "MID", "FWD")}
    for i in members_idx:
        by_pos[pos_arr[i]].append(week_pts[i])
    for p in by_pos:
        by_pos[p].sort(reverse=True)
    gk = by_pos["GK"][0] if by_pos["GK"] else 0.0
    best = -1e18
    for d, m, f in FORMATIONS:
        if (len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m
                or len(by_pos["FWD"]) < f):
            continue
        v = gk + sum(by_pos["DEF"][:d]) + sum(by_pos["MID"][:m]) \
            + sum(by_pos["FWD"][:f])
        if v > best:
            best = v
    cap = max((week_pts[i] for i in members_idx), default=0.0)
    return best + cap


def evaluate_candidate(squad_idx, pts_k, pos_arr, team_arr, price0, decay):
    """One candidate x one scenario, with one repair per week. Returns the
    decayed scenario value."""
    n, T = pts_k.shape
    members = list(squad_idx)
    bank = BUDGET - sum(price0[i] for i in members)
    total = 0.0
    for t in range(T):
        total += (decay ** t) * _best_xi_value(members, pts_k[:, t], pos_arr)
        if t == T - 1:
            continue
        # remaining decayed value per member / per outsider
        rem = pts_k[:, t + 1:] @ (decay ** np.arange(t + 1, T))
        club = {}
        for i in members:
            club[team_arr[i]] = club.get(team_arr[i], 0) + 1
        worst = sorted(members, key=lambda i: rem[i])[:3]
        best_gain, best_swap = 0.0, None
        member_set = set(members)
        for out in worst:
            budget_i = price0[out] + bank
            for i in np.argsort(-rem):
                if i in member_set or pos_arr[i] != pos_arr[out]:
                    continue
                if price0[i] > budget_i:
                    continue
                extra = club.get(team_arr[i], 0) - (team_arr[i] == team_arr[out])
                if extra >= MAX_PER_CLUB:
                    continue
                gain = rem[i] - rem[out]
                if gain > best_gain:
                    best_gain, best_swap = gain, (out, int(i))
                break            # sorted by rem: first legal is the best buy
        if best_swap is not None:
            out, inn = best_swap
            bank += price0[out] - price0[inn]
            members.remove(out)
            members.append(inn)
    return total


def robust_opening_squad(pool_by_gw, prob_by_gw, decay, mode="balanced",
                         K=K_DEFAULT, seed=SEED, reference_squads=(),
                         verbose=False):
    """Pick the GW1 fifteen by scenario sampling + recourse-aware selection.

    pool_by_gw : {gw: frame} exactly as build_and_solve takes (cutoff=gw1)
    prob_by_gw : {gw: frame} same rows plus the probability/component columns
    reference_squads : iterable of element-lists to include as candidates
    Returns (squad_elements, diagnostics dict).
    """
    players, idx, pos, team, name, price0, pts, present = \
        sample_scenarios(prob_by_gw, K=K, seed=seed)
    pos_arr = {i: pos[e] for e, i in idx.items()}
    team_arr = {i: team[e] for e, i in idx.items()}

    # ---- candidates: one deterministic MIP per scenario ------------------
    gws = list(pool_by_gw)
    candidates, seen = [], set()
    for k in range(K):
        pools_k = {}
        for t, gw in enumerate(gws):
            df = pool_by_gw[gw].copy()
            df["e_points"] = [pts[k, idx[e], t] for e in df["element"]]
            pools_k[gw] = df
        status, plan = build_and_solve(
            pools_k, current_squad=[], purchase_prices={}, bank=0,
            free_transfers=1, mode=mode, decay=decay)
        if plan is None:
            continue
        squad = tuple(sorted(plan[0]["squad"]))
        if squad not in seen:
            seen.add(squad)
            candidates.append(squad)
        if verbose and (k + 1) % 10 == 0:
            print(f"  [robust] {k + 1}/{K} scenario solves, "
                  f"{len(candidates)} distinct squads", flush=True)
    # The two deterministic strategies always compete as candidates, so the
    # robust pick can never be worse than them ON ITS OWN OBJECTIVE: the
    # expectation horizon MIP (Step 1's rule) and any caller references.
    status, plan = build_and_solve(
        pool_by_gw, current_squad=[], purchase_prices={}, bank=0,
        free_transfers=1, mode=mode, decay=decay)
    if plan is not None:
        squad = tuple(sorted(plan[0]["squad"]))
        if squad not in seen:
            seen.add(squad)
            candidates.append(squad)
    # ... and the single-gameweek expectation squad (the base rule).
    prob, sol = optimize_squad(pool_by_gw[gws[0]], mode=mode)
    if pulp.LpStatus[prob.status] == "Optimal":
        squad = tuple(sorted(get_team(pool_by_gw[gws[0]], sol)["element"]))
        if squad not in seen:
            seen.add(squad)
            candidates.append(squad)
    for ref in reference_squads:
        squad = tuple(sorted(ref))
        if all(e in idx for e in squad) and squad not in seen:
            seen.add(squad)
            candidates.append(squad)

    # ---- recourse-aware cross-evaluation ---------------------------------
    scores = []
    for squad in candidates:
        sidx = [idx[e] for e in squad]
        vals = [evaluate_candidate(sidx, pts[k], pos_arr, team_arr, price0,
                                   decay) for k in range(K)]
        scores.append((float(np.mean(vals)), squad))
    scores.sort(reverse=True)
    best_mean, best_squad = scores[0]
    diag = {
        "n_candidates": len(candidates),
        "best_mean": best_mean,
        "score_table": [(m, list(s)) for m, s in scores],
        "K": K, "seed": seed,
    }
    return list(best_squad), diag
