"""
FPL Copilot — Gameweek scoring (pure)

Takes a squad and what ACTUALLY happened, returns the points that squad scored.

This module is deliberately pure: no file reads, no network, no global state, no
randomness. Same inputs always give the same output. That is what makes it
testable in isolation, and it is why the season simulator can lean on it without
worrying about hidden coupling.

WHAT IT MODELS
--------------
1. Autosubs. A starter who played 0 minutes is replaced by a bench player, in
   bench order, but only if the replacement keeps the formation legal. This is
   applied by FPL automatically after all matches finish.
2. Captaincy. The captain's points are doubled — tripled if the Triple Captain
   chip is played. If the captain played 0 minutes, the vice-captain takes the
   armband instead, chip included. If both blanked, nobody is multiplied.
3. Transfer hits. Each transfer beyond the free allowance costs 4 points,
   subtracted from that gameweek's total.

WHAT IT DOES NOT MODEL (v1, deliberate)
---------------------------------------
- Wildcard, bench boost and free hit. Only Triple Captain is scored here; the
  others change the squad or the XI rather than the multiplier, so they belong to
  the optimizer and simulator rather than to this function.
- Double gameweeks. `actuals` is expected to be pre-aggregated to one row per
  player per gameweek, so a player with two fixtures arrives as a single summed
  row. Minutes are summed too, which means a player who played 0 in one fixture
  and 90 in the other correctly counts as having played.

FORMATION RULES USED FOR AUTOSUBS
---------------------------------
Exactly 1 GK, at least 3 DEF, at least 2 MID, at least 1 FWD. A bench outfielder
can only come on if removing the blanked starter and adding him leaves those
minimums intact. The bench goalkeeper can only replace the starting goalkeeper.
"""

import pandas as pd

# Minimum starters per position for a legal formation. The GK line is exact
# (always exactly 1); the outfield lines are floors.
MIN_FORMATION = {"DEF": 3, "MID": 2, "FWD": 1}
HIT_COST = 4          # points deducted per transfer beyond the free allowance
XI_SIZE = 11

# P5 piece 1 (interim plan section 4): order the outfield bench by
# p_play_any instead of e_points. Bench order only matters for autosubs, and
# an autosub fires only if that player actually PLAYED -- and e_points is
# near-useless for ranking bench players by that (Spearman vs
# actually-played: p_play_any +0.383, e_points +0.067;
# Logs/wildcard_and_determinism.md). Measured +2 in a clean paired
# comparison. Gated and stamped per decision-log row as
# `bench_order_by_play` (the D1_TERMS_ACTIVE pattern). NOT ADOPTED --
# measured 2026-08-21, report-only.
BENCH_ORDER_BY_PLAY = False


def assign_bench_order(team):
    """Give each bench player an order: 0 for the bench GK, then 1, 2, 3 for the
    outfielders ranked by predicted points (best first).

    This is a CONVENIENCE, not part of scoring — the scorer takes bench order as
    an explicit input so it stays pure. Real managers set this by hand; ranking by
    predicted points is the sensible automatic equivalent.

    Expects columns: position, role, e_points. Returns a copy with `bench_order`
    (NaN for starters).
    """
    t = team.copy()
    t["bench_order"] = pd.NA

    bench = t[t["role"] == "bench"]

    # The bench goalkeeper is a special slot: he can only ever replace the
    # starting goalkeeper, so he sits outside the outfield ordering.
    gk = bench[bench["position"] == "GK"]
    t.loc[gk.index, "bench_order"] = 0

    outfield = bench[bench["position"] != "GK"]
    if BENCH_ORDER_BY_PLAY:
        # Order by likelihood of playing; e_points only breaks ties. A frame
        # without the column fails LOUDLY -- silently falling back to
        # e_points would be exactly the silent-fallback family (#10/#13/
        # #14/#15). Injected blank-week rows carry p_play_any = 0.0.
        if "p_play_any" not in outfield.columns:
            raise ValueError(
                "BENCH_ORDER_BY_PLAY is on but the team frame has no "
                "p_play_any column -- plumb it through gw_slice/pools/"
                "plan_to_team rather than falling back to e_points")
        outfield = outfield.assign(
            _pplay=outfield["p_play_any"].fillna(0.0).astype(float)
        ).sort_values(["_pplay", "e_points"], ascending=False)
    else:
        outfield = outfield.sort_values("e_points", ascending=False)
    for rank, idx in enumerate(outfield.index, start=1):
        t.loc[idx, "bench_order"] = rank

    return t.drop(columns=["_pplay"], errors="ignore")


def _legal_after_swap(starter_positions, out_pos, in_pos):
    """Would the XI still be legal if `out_pos` left and `in_pos` came on?

    starter_positions: list of positions currently in the XI (including the
    blanked player still being counted, since he has not been removed yet).
    """
    counts = {}
    for p in starter_positions:
        counts[p] = counts.get(p, 0) + 1
    counts[out_pos] = counts.get(out_pos, 0) - 1
    counts[in_pos] = counts.get(in_pos, 0) + 1

    # exactly one goalkeeper, always
    if counts.get("GK", 0) != 1:
        return False
    for pos, floor in MIN_FORMATION.items():
        if counts.get(pos, 0) < floor:
            return False
    return True


def apply_autosubs(squad, minutes):
    """Work out the final XI after automatic substitutions.

    squad   : DataFrame with element, position, role, bench_order
    minutes : dict {element: minutes played this gameweek}

    Returns (final_xi_elements, subs_made) where subs_made is a list of
    (out_element, in_element) pairs, in the order they were applied.

    A player missing from `minutes` is treated as having played 0 — that is the
    correct reading for a player with no fixture (blank gameweek) or no data row.
    """
    starters = squad[squad["role"] != "bench"]
    bench = (squad[squad["role"] == "bench"]
             .sort_values("bench_order"))

    pos_of = dict(zip(squad["element"], squad["position"]))
    played = lambda e: minutes.get(e, 0) > 0

    final_xi = list(starters["element"])
    available_bench = list(bench["element"])
    subs_made = []

    # Only bench players who actually played can come on. A bench player who also
    # blanked is no use as a replacement.
    for out_elem in list(starters["element"]):
        if played(out_elem):
            continue

        out_pos = pos_of[out_elem]
        current_positions = [pos_of[e] for e in final_xi]

        for in_elem in list(available_bench):
            in_pos = pos_of[in_elem]

            # The bench keeper is only ever a like-for-like keeper swap.
            if (in_pos == "GK") != (out_pos == "GK"):
                continue
            if not played(in_elem):
                continue
            if not _legal_after_swap(current_positions, out_pos, in_pos):
                continue

            final_xi.remove(out_elem)
            final_xi.append(in_elem)
            available_bench.remove(in_elem)
            subs_made.append((out_elem, in_elem))
            break

    return final_xi, subs_made


def resolve_captain(squad, minutes, final_xi):
    """Decide who actually gets the doubled score.

    The captain doubles. If he played 0 minutes the armband passes to the vice.
    If the vice also blanked, nobody doubles.

    Returns (element_to_double, reason) where reason is one of
    "captain", "vice", or "none" — worth recording, because a season where the
    vice keeps rescuing you tells you something about the captaincy picks.
    """
    cap_rows = squad[squad["role"] == "CAPTAIN"]
    vice_rows = squad[squad["role"] == "VICE"]

    cap = cap_rows["element"].iloc[0] if len(cap_rows) else None
    vice = vice_rows["element"].iloc[0] if len(vice_rows) else None

    # The doubled player must be in the FINAL XI. A captain who was autosubbed
    # out blanked by definition, so this is belt-and-braces.
    if cap is not None and minutes.get(cap, 0) > 0 and cap in final_xi:
        return cap, "captain"
    if vice is not None and minutes.get(vice, 0) > 0 and vice in final_xi:
        return vice, "vice"
    return None, "none"


def score_gameweek(squad, actuals, transfers_made=0, free_transfers=1,
                   triple_captain=False):
    """Score one gameweek. PURE — no I/O, no state.

    squad          : DataFrame, the 15 players, with columns
                     element, position, role (CAPTAIN/VICE/start/bench),
                     bench_order (from assign_bench_order)
    actuals        : DataFrame with element, minutes, total_points — one row per
                     player for THIS gameweek (pre-aggregated for doubles)
    transfers_made : how many transfers were made this gameweek
    free_transfers : how many were free
    triple_captain : play the Triple Captain chip this gameweek — the armband
                     multiplies by 3 instead of 2. Falls through to the vice on a
                     blank exactly as the normal armband does, which is FPL's
                     rule: the chip attaches to the armband, not to the player.

    Returns a dict:
        points        -- final points after the captain bonus and any hit
        raw_points    -- points before the hit was deducted
        hit           -- points lost to extra transfers (>= 0)
        captain_bonus -- extra points from the armband (1x the doubled player's
                         score normally, 2x under Triple Captain)
        doubled       -- element that was doubled (None if nobody)
        doubled_role  -- "captain", "vice", or "none"
        final_xi      -- the 11 elements that actually scored
        subs_made     -- list of (out, in) autosub pairs
        bench_points  -- points left on the bench (diagnostic, not scored)
    """
    minutes = dict(zip(actuals["element"], actuals["minutes"]))
    points = dict(zip(actuals["element"], actuals["total_points"]))

    final_xi, subs_made = apply_autosubs(squad, minutes)
    doubled, doubled_role = resolve_captain(squad, minutes, final_xi)

    raw = sum(points.get(e, 0) for e in final_xi)
    # The armband adds EXTRA copies on top of the one already counted in the XI:
    # one extra for a normal captain (2x total), two for Triple Captain (3x).
    extra = 2 if triple_captain else 1
    captain_bonus = points.get(doubled, 0) * extra if doubled is not None else 0
    raw += captain_bonus

    # Extra transfers cost 4 points each. Never negative: unused free transfers
    # are banked by the caller, not refunded as points here.
    hit = max(0, transfers_made - free_transfers) * HIT_COST

    bench_elements = [e for e in squad["element"] if e not in final_xi]
    bench_points = sum(points.get(e, 0) for e in bench_elements)

    return {
        "points": raw - hit,
        "raw_points": raw,
        "hit": hit,
        "captain_bonus": captain_bonus,
        "doubled": doubled,
        "doubled_role": doubled_role,
        "final_xi": final_xi,
        "subs_made": subs_made,
        "bench_points": bench_points,
    }