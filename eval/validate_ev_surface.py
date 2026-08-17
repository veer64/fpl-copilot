#!/usr/bin/env python
"""
validate_ev_surface.py -- the pass/fail gate for the EV scorer.

THE QUESTION
------------
Realized season points cannot distinguish prediction quality. Measured on this
project: a model whose predictions are shrunk 75% toward the positional mean --
effectively a within-position random picker, top-15 spread collapsed from 2.72 to
0.55 -- scores INDISTINGUISHABLY from the full model (+22.5, p=0.548). All four
rungs of that ladder converged into a 42-point band, and lift was explained almost
entirely by regression to each arm's own mean (corr = -0.955).

`eval/ev_surface.py` claims to fix this by removing the haul/blank realization
lottery while preserving minutes. This file tests that claim, and it is the gate:
if the EV scorer cannot separate a deliberately crippled model from the real one,
it is no better than the season total and must not be used to argue for any
change.

TWO LADDERS, BECAUSE THEY DAMAGE DIFFERENT THINGS
-------------------------------------------------
Ladder 1, lambda-shrinkage (squad/degrade.py, reused unchanged so the rungs are
the same ones previously measured): e_points is pulled toward the positional mean.

    Note carefully what this does and does not do. Shrinking scales every
    deviation by (1 - lambda), which preserves within-position ORDER exactly. It
    destroys SPREAD, not ranking. What degrades is the optimizer's ability to
    trade points against price, so squad composition changes wholesale while the
    implied ranking does not.

Ladder 2, rank-scramble: a fraction of players have their e_points values
permuted among themselves within position. This leaves the marginal distribution
of e_points -- and therefore tie density and top-15 spread -- essentially
untouched, while destroying the ranking itself.

A real prediction improvement is mostly a ranking change, so ladder 2 is the more
faithful test of the thing the surface is meant to measure. Ladder 1 is included
because it is the ladder the season total already failed, which makes it the
direct comparison.

HOW A PATH IS EV-SCORED
-----------------------
The season runs exactly as it currently runs -- same simulator, same policy, same
data path, nothing about the decisions is changed. Only the SCORER changes. For
each gameweek the squad that actually took the field is re-scored by handing
`squad/scoring.py` an actuals frame whose `total_points` column holds ev_points
instead of realized points, with REALIZED minutes left in place.

Leaving realized minutes in place is what makes autosubs, the captain-to-vice
fallback and the blank-gameweek handling behave identically to a real scoring
run, so a policy that fielded a player who did not play is still penalised. The
verified scorer is reused rather than reimplemented; transfer hits are a
deterministic -4 and are carried across from the decision log unchanged.

The XI, captain and vice are reconstructed from the 15 in the decision log, which
does not store roles. That reconstruction is exact rather than approximate: with
the squad fixed, the optimizer's objective in `start` reduces to maximising
sum(start * e_points) subject to formation, so the best legal XI by e_points IS
the XI the MIP chose. `--selfcheck` verifies this empirically by re-scoring with
REALIZED points and comparing against the decision log gameweek by gameweek; it
runs by default and its result is reported before any ladder number is quoted.

THE HEAD-TO-HEAD, AND WHY THE FIRST PASS DID NOT SETTLE ANYTHING
---------------------------------------------------------------
The first run used scramble rungs 0.25/0.5/0.75 and bootstrapped only the EV
series. Both were mistakes. The top rung destroyed 1,071 EV points -- roughly
eighteen times the ~60-point path-noise floor -- and damage that large is
detected by the realized season total too (-1,121, monotone). So the ladder
established that EV scoring is not broken, and nothing at all about whether it is
SHARPER than the number it is meant to replace.

This version fixes both. Every arm's path is scored by BOTH surfaces in a single
pass, so the two scorers see the identical squad, XI, captain and autosubs and
differ only in the points surface. Both are bootstrapped against their own
baseline, and the reported sensitivity is

    |delta| / (width of that scorer's own 95% interval)

which is comparable across scorers because both are in points on the same paths.
The scramble rungs are now 0.05-0.20, which is the range where a real model
improvement lives and therefore the only range where the choice of scorer matters.

The decisive question is narrow: is there a rung where EV resolves the damage and
realized does not? If the two scorers agree everywhere, EV buys nothing and that
is the finding.

NOTHING HERE IS TUNED TO PASS. The rungs, the constants and the scoring path were
fixed before the run, and the milder ladder was chosen to make the test HARDER for
both scorers, not easier for EV. A failure is reported as a failure, including the
failure mode where realized turns out to be equally sensitive.

Usage:
    uv run python eval/validate_ev_surface.py                 # both ladders
    uv run python eval/validate_ev_surface.py --ladder lam    # one ladder
    uv run python eval/validate_ev_surface.py --quick         # 12 gameweeks
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import degrade  # noqa: E402
from bootstrap import compare_strategies  # noqa: E402
from scoring import assign_bench_order, score_gameweek  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

from ev_surface import build_ev_surface  # noqa: E402

SEASON = "2025-26"
BASE_WF = REPO / "data" / "walkforward_h6_2526.parquet"
TMP = REPO / "data" / ".ev_ladder_tmp.parquet"
OUT = REPO / "data" / "ev_ladder_validation.parquet"

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
LAMBDAS = [0.0, 0.25, 0.5, 0.75]

# Deliberately mild. The first pass used 0.25/0.5/0.75, which destroyed 1,071 EV
# points at the top rung -- roughly eighteen times the ~60-point path-noise floor.
# Damage that large is detected by the realized season total too, so it cannot
# discriminate between the two scorers. These rungs sit in the range where a real
# model improvement lives, which is the only range where the choice of scorer
# actually matters.
SCRAMBLES = [0.0, 0.05, 0.10, 0.15, 0.20]

# Formation rules, restated here only for XI reconstruction. The authoritative
# copies live in squad/optimize.py and squad/scoring.py.
POS_MIN = {"DEF": 3, "MID": 2, "FWD": 1}
POS_MAX = {"DEF": 5, "MID": 5, "FWD": 3}
XI_OUTFIELD = 10


# ---------------------------------------------------------------------------
# Ladder 2: rank-scramble
# ---------------------------------------------------------------------------
def scramble(df, frac, seed=0):
    """Permute e_points among a random fraction of players, within position.

    PERSISTENT ACROSS CUTOFFS BY CONSTRUCTION. The permutation is chosen once per
    (gw, position) and the same element -> element mapping is applied at every
    cutoff. That matters: a genuinely worse model misranks a player consistently,
    whereas re-drawing the permutation per cutoff would model a planner whose view
    of the same gameweek churns from week to week, which is a different (and
    easier) kind of damage.

    Values are exchanged rather than resampled, so the marginal distribution of
    e_points within each (cutoff, gw, position) is EXACTLY preserved -- hence tie
    density and top-15 spread are untouched and the only thing damaged is order.
    """
    if frac <= 0:
        return df.copy()

    out = df.copy().reset_index(drop=True)
    if out.duplicated(["cutoff", "gw", "element"]).any():
        raise ValueError("(cutoff, gw, element) is not unique -- the value "
                         "exchange below would fan out rows")

    rng = np.random.default_rng(seed)

    # One selection per (gw, position), over the union of elements across
    # cutoffs, plus a fixed random ordering of those members.
    recs = []
    for (gw, position), g in out.groupby(["gw", "position"], sort=True):
        members = np.sort(g["element"].unique())
        k = int(round(frac * len(members)))
        if k < 2:
            continue
        chosen = rng.choice(members, size=k, replace=False)
        recs.append(pd.DataFrame({
            "gw": gw, "position": position, "element": chosen,
            "_rank": rng.permutation(len(chosen)),
        }))

    if not recs:
        return out

    out = out.merge(pd.concat(recs, ignore_index=True),
                    on=["gw", "position", "element"], how="left")

    # Rotate values by one place among the chosen members PRESENT in each
    # (cutoff, gw, position), taken in the fixed random order.
    #
    # A rotation is used rather than applying a global permutation because not
    # every chosen element appears at every cutoff. Mapping onto an absent target
    # would silently drop and duplicate values, so the marginal distribution of
    # e_points would shift -- and ladder 2 would no longer be a pure ranking test,
    # which is its entire justification. Rotating whatever subset is present is a
    # bijection on that subset by construction, so the multiset of e_points within
    # every group is preserved EXACTLY. Tie density and top-15 spread therefore
    # cannot move, and this is asserted below rather than assumed.
    sel = out["_rank"].notna()
    part = out.loc[sel].sort_values(["cutoff", "gw", "position", "_rank"])
    rolled = part.groupby(["cutoff", "gw", "position"])["e_points"].transform(
        lambda s: np.roll(s.to_numpy(), 1))
    out.loc[rolled.index, "e_points"] = rolled.to_numpy()
    out = out.drop(columns=["_rank"])

    # equal_nan: the walkforward file carries ~3.7k NaN e_points (players not yet
    # visible at their cutoff, which load_season drops). Without it this check
    # fails unconditionally rather than on a real defect.
    before = np.sort(df["e_points"].to_numpy())
    after = np.sort(out["e_points"].to_numpy())
    if len(before) != len(after) or not np.allclose(before, after, equal_nan=True):
        raise AssertionError("scramble changed the e_points distribution; it must "
                             "only permute values, never alter them")
    return out


def scramble_damage(original, degraded):
    """Rank damage, plus the tie metrics -- which should be UNCHANGED.

    Reporting both is the point: it demonstrates the two ladders attack different
    axes rather than being two dials on the same one.
    """
    a = original[original.get("horizon_step", 0) == 0]
    b = degraded[degraded.get("horizon_step", 0) == 0]
    j = a[["element", "gw", "position", "e_points"]].merge(
        b[["element", "gw", "e_points"]], on=["element", "gw"],
        suffixes=("_orig", "_deg"))

    rhos = []
    for _, g in j.groupby(["gw", "position"]):
        if len(g) > 3 and g["e_points_orig"].nunique() > 1:
            r = g["e_points_orig"].corr(g["e_points_deg"], method="spearman")
            if np.isfinite(r):
                rhos.append(r)

    moved = float((j["e_points_orig"].to_numpy()
                   != j["e_points_deg"].to_numpy()).mean())
    out = {"mean_within_pos_spearman": round(float(np.mean(rhos)), 4) if rhos else np.nan,
           "frac_rows_changed": round(moved, 4)}
    out.update(degrade.tie_density(degraded))
    return out


# ---------------------------------------------------------------------------
# EV scoring of a realized squad path
# ---------------------------------------------------------------------------
def _best_xi(squad):
    """The optimal legal XI by e_points. Exact, not heuristic -- see module docstring.

    squad : frame with element, position, e_points (the 15).
    """
    gks = squad[squad["position"] == "GK"].sort_values("e_points", ascending=False)
    out = squad[squad["position"] != "GK"].sort_values("e_points", ascending=False)

    xi = [gks["element"].iloc[0]] if len(gks) else []
    taken = {"DEF": 0, "MID": 0, "FWD": 0}

    # minimums first
    for p, need in POS_MIN.items():
        rows = out[out["position"] == p].head(need)
        xi.extend(rows["element"].tolist())
        taken[p] = len(rows)

    # then the best remaining, respecting per-position caps
    chosen = set(xi)
    for r in out.itertuples():
        if len(xi) - (1 if gks.shape[0] else 0) >= XI_OUTFIELD:
            break
        if r.element in chosen:
            continue
        if taken[r.position] >= POS_MAX[r.position]:
            continue
        xi.append(r.element)
        chosen.add(r.element)
        taken[r.position] += 1

    return set(xi)


def reconstruct_team(elements, pool, pos_map):
    """Rebuild the role-tagged 15 the decision log does not store.

    Missing pool rows (blank gameweek) enter at e_points = 0, exactly as the
    simulator's own _pool_with_owned does.
    """
    rows = []
    lookup = pool.set_index("element")[["position", "e_points"]].to_dict("index")
    for e in elements:
        rec = lookup.get(e)
        rows.append({"element": e,
                     "position": rec["position"] if rec else pos_map.get(e, "MID"),
                     "e_points": rec["e_points"] if rec else 0.0})
    squad = pd.DataFrame(rows)

    xi = _best_xi(squad)
    starters = squad[squad["element"].isin(xi)].sort_values(
        "e_points", ascending=False)
    cap = starters["element"].iloc[0] if len(starters) else None
    vice = starters["element"].iloc[1] if len(starters) > 1 else None

    def role(e):
        if e == cap:
            return "CAPTAIN"
        if e == vice:
            return "VICE"
        return "start" if e in xi else "bench"

    squad["role"] = squad["element"].map(role)
    return assign_bench_order(squad)


def score_path(log, season_df, surfaces, pos_map):
    """Score ONE realized squad path against SEVERAL points surfaces at once.

    surfaces : {name: (points_by_gw, minutes_by_gw)}, each {gw: {element: value}}.
    Returns  : {name: array of per-gameweek points}.

    Scoring every surface inside a single pass is what makes the head-to-head
    valid: both scorers see the identical squad, the identical XI, the identical
    captain and the identical autosubs, so the only thing that differs between
    them is the points surface itself. Reconstructing the team twice would risk
    the two scorers silently diverging on a tie-break.

    Passing the EV surface gives the EV-scored season; passing realized
    total_points reproduces the simulator exactly and is how the self-check works.

    Hits are deterministic (-4 per extra transfer) and are taken from the log
    unchanged, so they enter both scorers identically.
    """
    out = {k: [] for k in surfaces}
    for r in log.itertuples():
        gw = int(r.gw)
        pool = season_df[(season_df["gw"] == gw) & (season_df["cutoff"] == gw)]
        team = reconstruct_team(list(r.elements), pool, pos_map)

        for name, (points_by_gw, minutes_by_gw) in surfaces.items():
            pts, mins = points_by_gw.get(gw, {}), minutes_by_gw.get(gw, {})
            actuals = pd.DataFrame({
                "element": team["element"],
                "minutes": [mins.get(e, 0) for e in team["element"]],
                "total_points": [pts.get(e, 0.0) for e in team["element"]],
            })
            res = score_gameweek(team, actuals, transfers_made=0, free_transfers=0)
            out[name].append(res["raw_points"] - float(r.hit))
    return {k: np.array(v, dtype=float) for k, v in out.items()}


def surface_lookups(ev):
    """Collapse the EV surface to one row per (element, gw).

    Double gameweeks are two fixtures and therefore two rows; scoring.py expects
    them pre-aggregated, so both ev_points and minutes are summed -- the same
    convention the simulator's own gw_actuals uses.
    """
    a = ev.groupby(["gw", "element"], as_index=False).agg(
        ev_points=("ev_points", "sum"), minutes=("minutes", "sum"))
    pts = {gw: dict(zip(g["element"], g["ev_points"])) for gw, g in a.groupby("gw")}
    mins = {gw: dict(zip(g["element"], g["minutes"])) for gw, g in a.groupby("gw")}
    return pts, mins


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_arm(df, gws=None):
    """Run the season on a (possibly degraded) prediction frame. Returns the log."""
    df.to_parquet(TMP, index=False)
    try:
        season = load_season(walkforward_path=TMP, horizon_aware=True)
        kw = dict(SIM_KW)
        if gws is not None:
            kw["gws"] = gws
        state, log = simulate_season(season, **kw)
    finally:
        TMP.unlink(missing_ok=True)
    return int(state.total_points), log, season


def significance(arm, base, label):
    """Paired block bootstrap of one arm against the baseline, on one surface."""
    res = compare_strategies(arm, base, label=label)
    width = res["ci_high"] - res["ci_low"]
    return {"delta": res["observed_margin"], "ci_low": res["ci_low"],
            "ci_high": res["ci_high"], "width": width,
            "excludes_zero": res["ci_excludes_zero"],
            # DETECTION REQUIRES THE RIGHT SIGN. Every arm here is strictly worse
            # than the baseline by construction, so a significantly POSITIVE delta
            # is a false positive -- the scorer has confidently reported that a
            # crippled model is better -- and must not be counted as sensitivity.
            "detects": bool(res["ci_excludes_zero"]
                            and res["observed_margin"] < 0),
            "wrong_sign": bool(res["ci_excludes_zero"]
                               and res["observed_margin"] > 0),
            "share_worse": res["share_of_seasons_model_loses"],
            # Effect size relative to the width of its own interval. This is the
            # sensitivity number: it asks how large the signal is compared with
            # the uncertainty the same data supports, so it is comparable across
            # two scorers measured in the same units on the same paths.
            "sensitivity": abs(res["observed_margin"]) / width if width > 0 else np.nan}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ladder", choices=["lam", "scramble", "both"], default="both")
    ap.add_argument("--quick", action="store_true",
                    help="12 gameweeks instead of 38 -- smoke test only, NOT a gate")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-selfcheck", action="store_true")
    ap.add_argument("--save", default=str(OUT))
    args = ap.parse_args()

    gws = list(range(1, 13)) if args.quick else None
    if args.quick:
        print("!! --quick: 12 gameweeks. Smoke test only; not a valid gate.\n")

    print("building EV surface ...", flush=True)
    ev = build_ev_surface(SEASON)
    ev_pts, ev_mins = surface_lookups(ev)
    print(f"  {len(ev):,} player-fixtures, mean ev {ev['ev_points'].mean():.4f} "
          f"vs realized {ev['total_points'].mean():.4f}\n", flush=True)

    base = pd.read_parquet(BASE_WF)
    pos_map = dict(zip(base["element"], base["position"]))
    real_pts = {gw: dict(zip(g["element"], g["actual_points"]))
                for gw, g in base.drop_duplicates(["gw", "element"]).groupby("gw")}
    real_mins = {gw: dict(zip(g["element"], g["minutes"]))
                 for gw, g in base.drop_duplicates(["gw", "element"]).groupby("gw")}

    surfaces = {"ev": (ev_pts, ev_mins), "real": (real_pts, real_mins)}

    # ---- baseline arm (shared rung 0 of both ladders) ----
    t0 = time.time()
    print("running baseline arm (lam=0 / scramble=0) ...", flush=True)
    base_total, base_log, base_season = run_arm(base, gws)
    base_series = score_path(base_log, base_season, surfaces, pos_map)
    base_ev = base_series["ev"]
    print(f"  realized {base_total}   EV {base_ev.sum():.1f}   "
          f"({time.time()-t0:.0f}s)\n", flush=True)

    # ---- self-check: does the reconstruction reproduce the simulator exactly? ----
    if not args.no_selfcheck:
        recon = base_series["real"]
        logged = base_log["points"].to_numpy(dtype=float)
        exact = int((recon == logged).sum())
        print("=== HARNESS SELF-CHECK (realized scoring vs decision log) ===")
        print(f"  gameweeks matching exactly : {exact}/{len(logged)}")
        print(f"  reconstructed total        : {recon.sum():.0f}")
        print(f"  decision-log total         : {logged.sum():.0f}")
        print(f"  mean abs per-gw difference : {np.abs(recon-logged).mean():.3f}")
        if exact != len(logged):
            print("  NOTE: XI reconstruction is not bit-exact. Differences arise on "
                  "exact ties, where the MIP's choice among equal-valued XIs is "
                  "arbitrary. Ladder comparisons stay valid because every arm is "
                  "reconstructed the same way, but the absolute EV totals carry "
                  "this reconstruction error.")
        print()

    rows = [{"ladder": "baseline", "rung": 0.0, "realized": base_total,
             "ev": float(base_ev.sum())}]
    # Per-gameweek series for EVERY arm and BOTH surfaces, so the two scorers can
    # be bootstrapped against the same paths rather than only the baseline.
    per_gw = {("baseline", 0.0): base_series}
    damage = []

    ladders = []
    if args.ladder in ("lam", "both"):
        ladders.append(("lam", LAMBDAS,
                        lambda d, r: degrade.degrade(d, r),
                        lambda o, d: degrade.tie_density(d)))
    if args.ladder in ("scramble", "both"):
        ladders.append(("scramble", SCRAMBLES,
                        lambda d, r: scramble(d, r, seed=args.seed),
                        scramble_damage))

    for name, rungs, make, damage_fn in ladders:
        for rung in rungs:
            if rung == 0.0:
                dmg = damage_fn(base, base)
                dmg.update({"ladder": name, "rung": rung})
                damage.append(dmg)
                rows.append({"ladder": name, "rung": rung,
                             "realized": base_total, "ev": float(base_ev.sum())})
                per_gw[(name, rung)] = base_series
                continue

            t0 = time.time()
            print(f"running {name}={rung} ...", flush=True)
            deg = make(base, rung)
            dmg = damage_fn(base, deg)
            dmg.update({"ladder": name, "rung": rung})
            damage.append(dmg)

            total, log, season = run_arm(deg, gws)
            series = score_path(log, season, surfaces, pos_map)
            per_gw[(name, rung)] = series
            rows.append({"ladder": name, "rung": rung, "realized": total,
                         "ev": float(series["ev"].sum()),
                         "realized_rescored": float(series["real"].sum())})
            print(f"  realized {total}   EV {series['ev'].sum():.1f}   "
                  f"({time.time()-t0:.0f}s)", flush=True)

    res = pd.DataFrame(rows)
    dmg_df = pd.DataFrame(damage)

    # ---------------- report ----------------
    pd.set_option("display.width", 200, "display.max_columns", None)

    print("\n" + "=" * 78)
    print("DAMAGE VERIFICATION -- what each rung actually did to the predictions")
    print("=" * 78)
    for name in dmg_df["ladder"].unique():
        print(f"\n[{name}]")
        sub = dmg_df[dmg_df["ladder"] == name].drop(columns=["ladder"])
        print(sub.to_string(index=False))

    print("\n" + "=" * 78)
    print("SEASON TOTALS PER RUNG -- EV-scored, with realized alongside")
    print("=" * 78)
    for name in [l[0] for l in ladders]:
        sub = res[res["ladder"] == name].sort_values("rung")
        print(f"\n[{name}]")
        print(f"{'rung':>6} {'EV total':>10} {'EV vs r0':>10} "
              f"{'realized':>10} {'real vs r0':>11}")
        ev0 = sub[sub["rung"] == 0]["ev"].iloc[0]
        r0 = sub[sub["rung"] == 0]["realized"].iloc[0]
        for r in sub.itertuples():
            print(f"{r.rung:>6.2f} {r.ev:>10.1f} {r.ev-ev0:>+10.1f} "
                  f"{r.realized:>10.0f} {r.realized-r0:>+11.0f}")
        # Per-gameweek noise on the paired difference series -- the quantity the
        # bootstrap interval is built from, shown directly so the sensitivity
        # numbers below are traceable to something concrete.
        print(f"  {'rung':>6} {'sd(EV diff/gw)':>16} {'sd(real diff/gw)':>18}")
        for rung in sub["rung"]:
            if rung == 0:
                continue
            de = per_gw[(name, rung)]["ev"] - per_gw[(name, 0.0)]["ev"]
            dr = per_gw[(name, rung)]["real"] - per_gw[(name, 0.0)]["real"]
            print(f"  {rung:>6.2f} {de.std():>16.2f} {dr.std():>18.2f}")

    print("\n" + "=" * 78)
    print("HEAD-TO-HEAD -- the same paths scored two ways")
    print("=" * 78)
    print("sens = |delta| / CI width. Higher means the effect is larger relative")
    print("to the uncertainty that scorer's own data supports.")
    print("sig:  D = detected damage (significant AND negative)")
    print("      X = FALSE POSITIVE (significant but positive -- the scorer says")
    print("          the crippled model is better)")
    print("      . = not significant")

    hh = {}
    for name in [l[0] for l in ladders]:
        sub = res[res["ladder"] == name].sort_values("rung")
        print(f"\n[{name}]")
        print(f"  {'rung':>5} | {'EV delta':>9} {'EV 95% CI':>20} {'sens':>5} "
              f"{'sig':>4} | {'REAL delta':>10} {'REAL 95% CI':>20} {'sens':>5} "
              f"{'sig':>4} | {'sens ratio':>10}")
        for rung in sub["rung"]:
            if rung == 0:
                continue
            e = significance(per_gw[(name, rung)]["ev"],
                             per_gw[(name, 0.0)]["ev"], f"{name}=0")
            r = significance(per_gw[(name, rung)]["real"],
                             per_gw[(name, 0.0)]["real"], f"{name}=0")
            ratio = e["sensitivity"] / r["sensitivity"] if r["sensitivity"] else np.nan
            hh[(name, rung)] = {"ev": e, "real": r, "ratio": ratio}

            def flag(s):
                return "D" if s["detects"] else ("X" if s["wrong_sign"] else ".")

            print(f"  {rung:>5.2f} | {e['delta']:>+9.1f} "
                  f"[{e['ci_low']:>+8.1f},{e['ci_high']:>+8.1f}] "
                  f"{e['sensitivity']:>5.2f} {flag(e):>4} | "
                  f"{r['delta']:>+10.1f} "
                  f"[{r['ci_low']:>+8.1f},{r['ci_high']:>+8.1f}] "
                  f"{r['sensitivity']:>5.2f} {flag(r):>4} | "
                  f"{ratio:>10.2f}")

        mono_ev = bool(np.all(np.diff(sub["ev"].to_numpy()) < 0))
        mono_real = bool(np.all(np.diff(sub["realized"].to_numpy(float)) < 0))
        print(f"\n  monotone decreasing:  EV {mono_ev}   realized {mono_real}")

    print("\n" + "=" * 78)
    print("DETECTION THRESHOLD -- smallest rung each scorer still resolves")
    print("=" * 78)
    thresholds = {}
    for name in [l[0] for l in ladders]:
        rungs = sorted(r for (n, r) in hh if n == name)
        for scorer in ("ev", "real"):
            hit = next((r for r in rungs if hh[(name, r)][scorer]["detects"]), None)
            thresholds[(name, scorer)] = hit
        print(f"\n[{name}]")
        for scorer, lab in (("ev", "EV"), ("real", "realized")):
            t = thresholds[(name, scorer)]
            print(f"  {lab:<9} smallest rung DETECTED (sig + correct sign): "
                  f"{t if t is not None else 'NONE -- never detected at any rung'}")
        for scorer, lab in (("ev", "EV"), ("real", "realized")):
            miss = [r for r in rungs if not hh[(name, r)][scorer]["detects"]]
            wrong = [r for r in rungs if hh[(name, r)][scorer]["wrong_sign"]]
            print(f"  {lab:<9} not detected at: "
                  f"{miss if miss else 'detected at every rung'}"
                  + (f"   FALSE POSITIVES at {wrong}" if wrong else ""))

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    for name in [l[0] for l in ladders]:
        rungs = sorted(r for (n, r) in hh if n == name)
        label = "lambda" if name == "lam" else "scramble"
        # The decisive case: a rung EV resolves and realized does not.
        ev_only = [r for r in rungs if hh[(name, r)]["ev"]["detects"]
                   and not hh[(name, r)]["real"]["detects"]]
        real_only = [r for r in rungs if hh[(name, r)]["real"]["detects"]
                     and not hh[(name, r)]["ev"]["detects"]]
        ev_fp = [r for r in rungs if hh[(name, r)]["ev"]["wrong_sign"]]
        real_fp = [r for r in rungs if hh[(name, r)]["real"]["wrong_sign"]]
        ratios = [hh[(name, r)]["ratio"] for r in rungs
                  if np.isfinite(hh[(name, r)]["ratio"])]

        print(f"\n  [{label}] Does EV detect degradation that realized scoring misses?")
        if ev_only and not real_only:
            print(f"    YES -- EV detects at rung(s) {ev_only} where realized "
                  f"does not.")
        elif real_only and not ev_only:
            print(f"    NO -- the reverse. Realized detects at rung(s) "
                  f"{real_only} where EV does not.")
        elif ev_only and real_only:
            print(f"    MIXED -- EV detects at {ev_only}, realized detects at "
                  f"{real_only}. Neither dominates.")
        else:
            print("    NO -- the two scorers agree on every rung. Neither "
                  "detects a rung the other misses.")
        if ev_fp or real_fp:
            print(f"    WARNING -- false positives (significant, wrong sign): "
                  f"EV at {ev_fp or 'none'}, realized at {real_fp or 'none'}. "
                  f"A scorer that confidently rates a crippled model BETTER is "
                  f"not sensitive, it is miscalibrated.")
        if ratios:
            print(f"    median sensitivity ratio EV/realized: "
                  f"{np.median(ratios):.2f} "
                  f"({'EV sharper' if np.median(ratios) > 1 else 'realized sharper'})"
                  f"  -- magnitude only, ignores sign")

    print("\n  Caveat that applies to every interval above: the block bootstrap "
          "resamples\n  gameweeks within ONE realized path per arm, so it measures "
          "within-season\n  variability, not the path lottery. EV scoring removes "
          "most of the outcome\n  lottery but not the branch structure of which "
          "squads got built.")

    if args.save and not args.quick:
        res.to_parquet(args.save, index=False)
        dmg_df.to_parquet(str(args.save).replace(".parquet", "_damage.parquet"),
                          index=False)
        print(f"\nwrote {args.save}")


if __name__ == "__main__":
    main()
