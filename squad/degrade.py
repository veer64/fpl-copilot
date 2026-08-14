"""
Deliberately degraded prediction arms, for closing Instrument B's confound.

THE CONFOUND
------------
Under perturbation the availability arm beat the baseline by +41.5 [+18.2, +64.7],
reversing the -46 of the single realised path. But the arm that LOST under
perturbation is also the arm with more degenerate optima: at eps=0.001 the baseline
has sd 16.6 across draws while the availability arm returns the identical total eight
times out of eight. A weaker-ranked model sitting on more ties is more disruptable by
any noise, regardless of whether its realised path was lucky. So "1984 was a lucky
path" and "the baseline is more noise-fragile" both predict what was observed.

THE TEST
--------
Shrink the baseline's own predictions toward the positional mean. That yields a
strictly worse model with strictly more ties, differing from the baseline in
SHARPNESS alone -- same features, same season, same everything else. Sweeping the
shrinkage gives a gradient rather than a single point.

    e_points(lam) = mu_pos + (1 - lam) * (e_points - mu_pos)

lam=0 is the baseline untouched; lam=1 collapses every player in a position to the
same value, which is maximal degeneracy.

WHAT EACH EXPLANATION PREDICTS (stated before running, so the result cannot be read
both ways afterwards)

  Explanation 2, the artifact reading: perturbation systematically flatters the
  sharper arm. Then amplification -- perturbed delta minus unperturbed delta for
  baseline vs degraded -- is POSITIVE and INCREASES with lam. Baseline's own lift
  should rise toward zero as lam grows, because a degraded arm has less real signal
  for the noise to destroy.

  Explanation 1, the luck reading: amplification is ~0 at every lam, and lift is
  governed by how lucky each realised path happened to be rather than by sharpness.

The discriminating quantity is where the availability arm's anomalous lift of +14.9
falls against the lift-vs-sharpness curve traced by this family. Noise destroying
signal should push lift NEGATIVE for any arm carrying real signal; availability's
being positive is the anomaly that the curve either explains or does not.
"""

import numpy as np
import pandas as pd

GROUP = ["cutoff", "gw", "position"]


def degrade(df, lam):
    """Shrink e_points toward the positional mean within each (cutoff, gw, position).

    Shrinking WITHIN position and gameweek is deliberate: shrinking globally would
    mostly erase the position and fixture structure, which is not the axis under test.
    What must degrade is the model's ability to separate players it is choosing
    between.
    """
    if lam == 0:
        return df.copy()
    out = df.copy()
    mu = out.groupby(GROUP)["e_points"].transform("mean")
    out["e_points"] = (mu + (1.0 - lam) * (out["e_points"] - mu)).clip(lower=0.0)
    return out


def tie_density(df, taus=(0.001, 0.01, 0.05)):
    """How much of the selection boundary is degenerate.

    Perturbation can only change a decision where two candidates are close enough for
    the jitter to reorder them. The boundary that matters is the edge of the squad, so
    this counts players within tau of the 15th-best prediction in their gameweek --
    not ties anywhere in the pool, which would be dominated by the irrelevant tail.

    Reported at horizon step 0, one view per gameweek.
    """
    d = df[df.get("horizon_step", 0) == 0] if "horizon_step" in df.columns else df
    rows = []
    for gw, g in d.groupby("gw"):
        e = np.sort(g["e_points"].values)[::-1]
        if len(e) < 16:
            continue
        boundary = e[14]  # 15th best
        row = {"gw": gw, "spread_top15": float(e[0] - e[14]),
               "exact_dupes": int(len(e) - len(np.unique(np.round(e, 9))))}
        for tau in taus:
            row[f"near_{tau}"] = int(np.sum(np.abs(e - boundary) <= tau))
        rows.append(row)
    t = pd.DataFrame(rows)
    summary = {"mean_spread_top15": round(float(t.spread_top15.mean()), 3),
               "mean_exact_dupes": round(float(t.exact_dupes.mean()), 1)}
    for tau in taus:
        summary[f"mean_within_{tau}_of_boundary"] = round(float(t[f"near_{tau}"].mean()), 2)
    return summary
