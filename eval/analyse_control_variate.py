#!/usr/bin/env python
"""
analyse_control_variate.py -- can EV work as a control variate rather than a
replacement scorer?

BACKGROUND
----------
EV-as-replacement failed the M1 gate: on the mild scramble ladder realized points
detected damage at rung 0.15 where EV did not, and on the lambda ladder realized
detected at two rungs where EV detected at none. The mechanism was that EV halved
the noise but halved the signal with it.

The fallback proposal is to use EV as a CORRECTION to realized points rather than
a replacement:

    adjusted = realized - beta * (EV - mean_EV)

with beta chosen to minimise variance. The stated threshold for adopting it is a
>= 50% variance reduction.

WHAT THE RETAINED DATA CAN AND CANNOT ANSWER
--------------------------------------------
`data/ev_ladder_validation.parquet` holds SEASON TOTALS ONLY -- ten rows of
(ladder, rung, realized, ev). The per-gameweek series were held in memory during
the M1 run and discarded. So the following CANNOT be computed from it directly:

    - per-gameweek corr(realized, EV) along a path, per arm
    - the optimal beta
    - adjusted deltas with recomputed CIs

That is a real gap in what the previous run retained, and it is stated rather
than papered over. Two things rescue the question without a blind re-run:

1. THE M1 RUN PRINTED THE PER-GAMEWEEK DIFFERENCE SDs for both scorers at every
   rung. Those are recovered below (RECOVERED_SD, with provenance). Under the
   decomposition the EV surface is explicitly built on --

       realized_gw = ev_gw + noise_gw,   cov(ev, noise) = 0

   -- the correlation follows in closed form:

       rho = cov(d_r, d_ev) / (sd_r * sd_ev) = var(d_ev) / (sd_r * sd_ev)
           = sd(d_ev) / sd(d_r)

   so rho is recoverable from the two sds alone, and the implied variance
   reduction is 1 - rho^2. No simulation needed.

2. THE CORRELATION CAN BE MEASURED DIRECTLY on a constructed squad path, using
   the walk-forward predictions and the EV surface that are both on disk. The
   construction is a free re-pick of the best legal XI by e_points each gameweek
   -- the same reference construct the cold-start analysis used. It is NOT the
   MIP path (no budget, no club limit, no transfer persistence), so it is a proxy
   and is labelled as one throughout. Its job is to check the closed-form
   estimate against a real measurement, not to replace it.

THE STRUCTURAL POINT, WHICH NEEDS NO DATA AT ALL
------------------------------------------------
Centering on the sample mean makes the correction sum to zero over the season, so

    sum(adjusted) == sum(realized)   exactly.

A control variate therefore CANNOT change any point estimate. It cannot fix the
non-monotonicity in either ladder, and it cannot fix a wrong-signed result. It can
only narrow confidence intervals, by a factor of sqrt(1 - rho^2).

And there is a deeper problem with this particular pairing. A control variate
removes only the variance it is CORRELATED with. EV was constructed specifically
to be uncorrelated with the haul/blank realization lottery -- that is what
"removing the lottery" means. But that lottery is precisely what dominates the
variance of realized points. So EV is, by construction, close to orthogonal to the
noise it would need to subtract. This analysis quantifies how close.

Usage:
    uv run python eval/analyse_control_variate.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

from bootstrap import block_bootstrap, interval  # noqa: E402

from ev_surface import build_ev_surface  # noqa: E402

SEASON = "2025-26"
BASE_WF = REPO / "data" / "walkforward_h6_2526.parquet"
RESULTS = REPO / "data" / "ev_ladder_validation.parquet"
VARIANCE_TARGET = 0.50          # Fable's threshold for adopting the fallback

# Per-gameweek sd of the PAIRED DIFFERENCE series, both scorers, recovered from
# the M1 head-to-head run's printed output (eval/validate_ev_surface.py, section
# "SEASON TOTALS PER RUNG"). Embedded because the per-gameweek series themselves
# were not persisted; these summary statistics were the only per-gameweek
# information the run wrote down.
RECOVERED_SD = {
    ("lam", 0.25): (3.65, 10.77),
    ("lam", 0.50): (4.70, 13.99),
    ("lam", 0.75): (5.69, 11.86),
    ("scramble", 0.05): (4.22, 12.75),
    ("scramble", 0.10): (6.43, 14.27),
    ("scramble", 0.15): (7.11, 12.72),
    ("scramble", 0.20): (5.62, 12.48),
}

POS_MIN = {"DEF": 3, "MID": 2, "FWD": 1}
POS_MAX = {"DEF": 5, "MID": 5, "FWD": 3}


# ---------------------------------------------------------------------------
def best_xi(g):
    """Best legal XI by e_points from a whole-gameweek pool.

    PROXY. No budget, no max-3-per-club, no squad persistence -- so this is not
    the path the MIP walks. It is used only to measure the CORRELATION STRUCTURE
    between the two scorers over a season, which is a property of "a set of ~11
    selected players scored two ways" rather than of the budget constraint.
    """
    g = g.sort_values("e_points", ascending=False)
    gk = g[g["position"] == "GK"].head(1)
    out = g[g["position"] != "GK"]

    picks = [gk]
    taken = {"DEF": 0, "MID": 0, "FWD": 0}
    for p, need in POS_MIN.items():
        rows = out[out["position"] == p].head(need)
        picks.append(rows)
        taken[p] = len(rows)

    chosen = pd.concat(picks)
    remaining = out[~out["element"].isin(chosen["element"])]
    extra = []
    for r in remaining.itertuples():
        if len(chosen) + len(extra) >= 11:
            break
        if taken[r.position] >= POS_MAX[r.position]:
            continue
        extra.append(r.Index)
        taken[r.position] += 1
    if extra:
        chosen = pd.concat([chosen, remaining.loc[extra]])
    return chosen


def path_series(pred, ev_lookup):
    """Per-gameweek (realized, EV) totals for the constructed path, incl. captain."""
    real, evp = [], []
    for gw, g in pred.groupby("gw"):
        xi = best_xi(g)
        elems = list(xi["element"])
        cap = xi.sort_values("e_points", ascending=False)["element"].iloc[0]
        r = sum(ev_lookup["real"].get((gw, e), 0.0) for e in elems)
        v = sum(ev_lookup["ev"].get((gw, e), 0.0) for e in elems)
        # captain doubles under both scorers, identically
        r += ev_lookup["real"].get((gw, cap), 0.0)
        v += ev_lookup["ev"].get((gw, cap), 0.0)
        real.append(r)
        evp.append(v)
    return np.array(real), np.array(evp)


def control_variate(d_real, d_ev):
    """Optimal beta, rho, and the adjusted difference series.

    beta* = cov(d_real, d_ev) / var(d_ev) minimises var(d_real - beta*d_ev).
    Centering d_ev on its own sample mean is what leaves the point estimate
    untouched.
    """
    if np.var(d_ev) == 0:
        return dict(beta=np.nan, rho=np.nan, var_reduction=0.0, adjusted=d_real)
    beta = float(np.cov(d_real, d_ev, ddof=1)[0, 1] / np.var(d_ev, ddof=1))
    rho = float(np.corrcoef(d_real, d_ev)[0, 1])
    adjusted = d_real - beta * (d_ev - d_ev.mean())
    return dict(beta=beta, rho=rho, var_reduction=rho ** 2, adjusted=adjusted)


def ci(series, seed=0):
    s = block_bootstrap(series, seed=seed)
    lo, hi = interval(s)
    return float(series.sum()), lo, hi, hi - lo


# ---------------------------------------------------------------------------
def main():
    pd.set_option("display.width", 200, "display.max_columns", None)

    print("=" * 78)
    print("0. WHAT THE RETAINED DATA ACTUALLY CONTAINS")
    print("=" * 78)
    res = pd.read_parquet(RESULTS)
    print(f"{RESULTS.name}: shape {res.shape}, columns {list(res.columns)}")
    print("\nThis is SEASON TOTALS ONLY. The per-gameweek series were not")
    print("persisted, so the following are NOT directly computable from it:")
    print("  - per-gameweek corr(realized, EV) per arm")
    print("  - the optimal beta")
    print("  - adjusted deltas with recomputed CIs")
    print("\nProceeding two ways: (1) closed form from the per-gameweek sds the")
    print("M1 run printed, (2) direct measurement on a constructed proxy path.\n")

    # ---------------- 1. closed form from recovered sds ----------------
    print("=" * 78)
    print("1. CLOSED FORM -- rho implied by the per-gameweek sds the M1 run printed")
    print("=" * 78)
    print("Under realized = EV + independent noise:  rho = sd(d_EV) / sd(d_real)")
    print("Variance reduction from the control variate = rho^2\n")
    print(f"  {'ladder':>9} {'rung':>5} {'sd(d_EV)':>9} {'sd(d_real)':>11} "
          f"{'rho':>6} {'var reduction':>14} {'>=50%?':>8}")
    closed = []
    for (lad, rung), (sd_ev, sd_r) in RECOVERED_SD.items():
        rho = sd_ev / sd_r
        vr = rho ** 2
        closed.append({"ladder": lad, "rung": rung, "rho": rho, "var_reduction": vr})
        print(f"  {lad:>9} {rung:>5.2f} {sd_ev:>9.2f} {sd_r:>11.2f} "
              f"{rho:>6.3f} {vr:>13.1%} {'YES' if vr >= VARIANCE_TARGET else 'no':>8}")
    closed = pd.DataFrame(closed)
    print(f"\n  median rho {closed['rho'].median():.3f}   "
          f"median variance reduction {closed['var_reduction'].median():.1%}")
    print(f"  rho required for {VARIANCE_TARGET:.0%} reduction: "
          f"{np.sqrt(VARIANCE_TARGET):.3f}")

    # ---------------- 2. direct measurement on a constructed path ----------------
    print("\n" + "=" * 78)
    print("2. DIRECT MEASUREMENT -- constructed path (PROXY, not the MIP path)")
    print("=" * 78)
    print("building EV surface ...", flush=True)
    ev = build_ev_surface(SEASON)
    agg = ev.groupby(["gw", "element"], as_index=False).agg(
        ev_points=("ev_points", "sum"), total_points=("total_points", "sum"))
    ev_lookup = {
        "ev": {(r.gw, r.element): r.ev_points for r in agg.itertuples()},
        "real": {(r.gw, r.element): r.total_points for r in agg.itertuples()},
    }

    base = pd.read_parquet(BASE_WF)
    base = base[base["horizon_step"] == 0].dropna(subset=["e_points"])

    import degrade  # noqa: E402
    from validate_ev_surface import scramble  # noqa: E402

    arms = {("baseline", 0.0): base}
    for lam in [0.25, 0.50, 0.75]:
        arms[("lam", lam)] = degrade.degrade(base, lam)
    for f in [0.05, 0.10, 0.15, 0.20]:
        arms[("scramble", f)] = scramble(base, f, seed=0)

    series = {}
    for key, df in arms.items():
        series[key] = path_series(df, ev_lookup)

    r0, v0 = series[("baseline", 0.0)]
    print(f"\nbaseline path: realized {r0.sum():.0f}, EV {v0.sum():.0f}")
    print(f"  within-arm corr(realized_gw, EV_gw) = "
          f"{np.corrcoef(r0, v0)[0,1]:.3f}")
    print(f"  sd per gw: realized {r0.std():.2f}, EV {v0.std():.2f}")

    print("\nwithin-arm correlation, per arm:")
    print(f"  {'arm':>18} {'corr(real,EV)':>14} {'sd real':>9} {'sd EV':>8}")
    for key, (r, v) in series.items():
        print(f"  {str(key):>18} {np.corrcoef(r, v)[0,1]:>14.3f} "
              f"{r.std():>9.2f} {v.std():>8.2f}")

    # ---------------- 3. apply the control variate ----------------
    print("\n" + "=" * 78)
    print("3. CONTROL VARIATE APPLIED TO THE PAIRED DIFFERENCES (proxy path)")
    print("=" * 78)
    print("d_real = realized_arm - realized_baseline, per gameweek; likewise d_EV.")
    print("The relevant correlation for a BETWEEN-ARM comparison is corr(d_real,")
    print("d_EV), not the within-arm one above.\n")
    print(f"  {'arm':>18} {'rho(d)':>7} {'beta*':>7} {'1-rho^2':>8} | "
          f"{'raw delta':>10} {'raw CI width':>13} | {'adj delta':>10} "
          f"{'adj CI width':>13} {'shrink':>7}")
    rows = []
    assumption = []
    for key, (r, v) in series.items():
        if key == ("baseline", 0.0):
            continue
        d_r, d_v = r - r0, v - v0
        cv = control_variate(d_r, d_v)
        # The closed form in section 1 assumed cov(EV, noise) = 0, which implies
        # rho == sd(d_EV)/sd(d_real). Here both sides are measurable, so the
        # assumption can be tested rather than trusted.
        assumption.append({"arm": str(key), "sd_d_ev": d_v.std(),
                           "sd_d_real": d_r.std(),
                           "sd_ratio": d_v.std() / d_r.std() if d_r.std() else np.nan,
                           "rho_measured": cv["rho"],
                           "abs_delta": abs(float(d_r.sum()))})
        raw_d, raw_lo, raw_hi, raw_w = ci(d_r)
        adj_d, adj_lo, adj_hi, adj_w = ci(cv["adjusted"])
        shrink = adj_w / raw_w if raw_w else np.nan
        rows.append({"arm": str(key), "rho_d": cv["rho"], "beta": cv["beta"],
                     "var_reduction": cv["var_reduction"],
                     "raw_delta": raw_d, "raw_ci": (raw_lo, raw_hi),
                     "adj_delta": adj_d, "adj_ci": (adj_lo, adj_hi),
                     "width_ratio": shrink})
        print(f"  {str(key):>18} {cv['rho']:>7.3f} {cv['beta']:>7.3f} "
              f"{1-cv['var_reduction']:>8.3f} | {raw_d:>+10.1f} {raw_w:>13.1f} | "
              f"{adj_d:>+10.1f} {adj_w:>13.1f} {shrink:>7.3f}")

    cvdf = pd.DataFrame(rows)
    print(f"\n  point estimates identical (raw vs adjusted): "
          f"{np.allclose(cvdf['raw_delta'], cvdf['adj_delta'])}")
    print("  -- as they must be: the correction sums to zero over the season.")

    # ---- is the closed form's independence assumption actually true? ----
    print("\n" + "-" * 78)
    print("3b. TESTING THE CLOSED FORM'S ASSUMPTION (both sides measurable here)")
    print("-" * 78)
    print("Section 1 assumed cov(EV, noise)=0, which forces rho == sd(d_EV)/sd(d_real).")
    print("If measured rho exceeds the sd ratio, EV is correlated with the noise too")
    print("and the closed form UNDERSTATES rho.\n")
    adf = pd.DataFrame(assumption)
    print(f"  {'arm':>18} {'sd(d_EV)':>9} {'sd(d_real)':>11} {'sd ratio':>9} "
          f"{'rho measured':>13} {'gap':>7} {'|delta|':>8}")
    for r in adf.itertuples():
        print(f"  {r.arm:>18} {r.sd_d_ev:>9.2f} {r.sd_d_real:>11.2f} "
              f"{r.sd_ratio:>9.3f} {r.rho_measured:>13.3f} "
              f"{r.rho_measured - r.sd_ratio:>+7.3f} {r.abs_delta:>8.0f}")
    print(f"\n  median sd ratio {adf['sd_ratio'].median():.3f} vs median measured "
          f"rho {adf['rho_measured'].median():.3f}")
    corr_eff = np.corrcoef(adf["abs_delta"], adf["rho_measured"])[0, 1]
    print(f"  corr(|delta|, rho) across arms = {corr_eff:+.3f} "
          f"(no relationship -- effect size does not explain rho)")

    violations = adf[adf["sd_ratio"] > 1.0]
    print(f"\n  ASSUMPTION VIOLATED in {len(violations)} of {len(adf)} arms.")
    print("  Under realized = EV + independent noise, sd(d_EV) <= sd(d_real) is")
    print("  forced. Ratios above 1.0 are therefore impossible under that model:")
    for r in violations.itertuples():
        print(f"    {r.arm:>18}  sd ratio {r.sd_ratio:.3f}")
    print("  EV is NOT simply realized-minus-independent-noise. It carries variance")
    print("  of its own that realized does not (its rates and market P(CS) move")
    print("  with fixture even when the realized outcome does not). So the closed")
    print("  form in section 1 does not hold and its 20.3% must NOT be quoted as")
    print("  the answer. Both estimates below are reported, and they disagree.")

    # ---------------- 4. implied effect on the REAL M1 deltas ----------------
    print("\n" + "=" * 78)
    print("4. IMPLIED EFFECT ON THE ACTUAL M1 DELTAS")
    print("=" * 78)
    print("Point estimates are unchanged by construction. Applying the closed-form")
    print("rho to the M1 realized CIs gives the narrowing the fallback would buy.\n")
    m1 = {  # realized delta and CI, from the M1 head-to-head run
        ("lam", 0.25): (-124.0, -231.0, -34.0),
        ("lam", 0.50): (-27.0, -155.0, +83.0),
        ("lam", 0.75): (-126.0, -235.0, -31.0),
        ("scramble", 0.05): (-104.0, -243.0, +21.0),
        ("scramble", 0.10): (-101.0, -313.0, +123.0),
        ("scramble", 0.15): (-187.0, -347.0, -39.0),
        ("scramble", 0.20): (-164.0, -287.0, -22.0),
    }
    print("Both candidate variance reductions are applied, because the two")
    print("estimates disagree and the choice between them changes decisions.\n")
    scenarios = [("low", float(closed["var_reduction"].median())),
                 ("high", float(cvdf["var_reduction"].median()))]
    for lab, vr in scenarios:
        k = np.sqrt(max(0.0, 1 - vr))
        print(f"  scenario '{lab}': variance reduction {vr:.1%}, "
              f"CI width x {k:.3f}")
        print(f"    {'ladder':>9} {'rung':>5} {'delta':>8} {'realized CI':>22} "
              f"{'adjusted CI':>22} {'sig now':>8} {'sig after':>10} {'FLIPS':>6}")
        for key, (d, lo, hi) in m1.items():
            c = (lo + hi) / 2
            nlo, nhi = c + (lo - c) * k, c + (hi - c) * k
            now = lo > 0 or hi < 0
            aft = nlo > 0 or nhi < 0
            print(f"    {key[0]:>9} {key[1]:>5.2f} {d:>+8.1f} "
                  f"[{lo:>+8.1f},{hi:>+8.1f}] [{nlo:>+9.1f},{nhi:>+9.1f}] "
                  f"{str(now):>8} {str(aft):>10} {'YES' if now != aft else '':>6}")
        print()

    # ---------------- 5. verdict ----------------
    print("\n" + "=" * 78)
    print("5. VERDICT")
    print("=" * 78)
    med_closed = closed["var_reduction"].median()
    med_direct = cvdf["var_reduction"].median()
    lo_direct = cvdf["var_reduction"].min()
    hi_direct = cvdf["var_reduction"].max()
    print(f"  closed form (real MIP paths, ASSUMPTION VIOLATED) : {med_closed:.1%}")
    print(f"  direct measurement (proxy path, not the MIP path) : {med_direct:.1%}"
          f"   range {lo_direct:.1%} to {hi_direct:.1%}")
    print(f"  threshold                                         : "
          f"{VARIANCE_TARGET:.0%}")

    print("\n  VERDICT: NOT ESTABLISHED EITHER WAY.")
    print("""
  The two available estimates straddle the threshold and neither is
  trustworthy for this decision:

    - The closed form is computed on the REAL MIP paths but relies on
      realized = EV + independent noise, which section 3b shows is false
      (sd(d_EV) exceeds sd(d_real) in 3 of 7 arms, impossible under that
      model). Its 20.3% cannot be quoted.

    - The direct measurement makes no such assumption, but is computed on a
      PROXY path with no budget, no club limit and no transfer persistence.
      Its arms diverge about twice as far as the MIP's, and its per-arm
      variance reduction ranges from 21% to 73% -- a spread wide enough to
      contain both a clear pass and a clear fail.

  Deciding this needs corr(d_real, d_EV) measured on the actual MIP paths.
  That requires the per-gameweek series the M1 run discarded. The fix is one
  line (persist `per_gw`) plus a deterministic re-run of the nine arms --
  the simulator is deterministic, so this re-derives rather than re-rolls,
  and it was already confirmed when the lambda arms reproduced exactly.
  About 50 minutes. I am not guessing in place of that measurement.""")

    print("\n  TWO THINGS THAT ARE ESTABLISHED REGARDLESS:")
    print("""
  1. The control variate cannot change any point estimate. Centering on the
     sample mean makes the correction sum to zero, so sum(adjusted) equals
     sum(realized) exactly -- confirmed numerically above. It therefore
     cannot fix the non-monotonicity in either ladder, nor the wrong-signed
     rungs, nor the fact that realized out-detected EV at scramble 0.15. It
     narrows intervals and does nothing else.

  2. At the low estimate it changes no decision at all: every one of the
     seven M1 rungs keeps its existing significance status. At the high
     estimate exactly one rung flips (scramble 0.05). So the entire value of
     the fallback, across the whole ladder, is at most one marginal
     significance call -- and only if the optimistic estimate is the right
     one.""")


if __name__ == "__main__":
    main()
