"""
Instrument B — prediction-perturbation outer loop.

WHY IT EXISTS
-------------
The simulator is deterministic after the `sorted()` fix, so a season total is one
number from one realised path. `block_bootstrap` resamples gameweeks WITHIN that one
path and therefore never samples the path lottery -- the fact that a different pick
at GW1 sends the whole season down a different branch. It understates uncertainty in
exactly the dimension that keeps defeating this project.

Replicates have to come from outside the simulator. Here they come from jittering the
predictions: draw j perturbs `e_points`, both arms re-solve against the SAME draw, and
the paired difference D_j = total_B - total_A is recorded. The spread of D over draws
is an honest interval on the margin, because each draw sends both arms somewhere
different and the pairing cancels what they share.

COMMON RANDOM NUMBERS
---------------------
The jitter is a function of (element, gw, seed) alone -- not of row order, not of which
file it is applied to. It is built once from the union of keys across both arms and
merged into each. Give the two arms independent noise and you are sampling two
lotteries instead of one, and the paired difference stops cancelling anything.

The jitter is shared across CUTOFFS by design. A player this model overrates stays
overrated as the horizon rolls; the wildcard investigation found exactly that ("the
error persisting because features move slowly"). Drawing fresh noise per cutoff would
model an error that resets every week, which is not the error we have.

CHOOSING EPSILON
----------------
eps is in points, on a scale where horizon-0 residual sd is ~2.0 and mean e_points
~1.4.

    eps ~ 1e-3   below any real preference. Flips only EXACTLY TIED optima, which is
                 the mechanism that gave 1973 vs 1984 before `sorted()`. Isolates pure
                 tie-chaos.
    eps 0.2-1.0  a fraction of residual sd. Samples something like genuine model
                 uncertainty.

Report the whole sweep. A margin that survives every eps is robust; one that appears
at a single eps is not.

WHAT THIS CANNOT DO
-------------------
It samples the path lottery, not model uncertainty properly. The gold standard would
bootstrap the TRAINING data and rebuild the walk-forward per draw, propagating real
parameter uncertainty -- 13 min per draw, ~11h at J=50, rejected on cost. Additive
jitter is a stand-in for that, and it degrades both arms in common (the top-15 gets
contaminated by upward draws from a long tail); CRN is what stops that common
degradation contaminating the DIFFERENCE.
"""

import numpy as np
import pandas as pd

KEYS = ["element", "gw"]

# Attached to every summary this module produces, so it travels with the numbers
# instead of living in whichever report happened to introduce them.
CAVEAT = (
    "Instrument B samples the PATH LOTTERY -- which branch a season lands on when a "
    "changed pick\ncascades -- and NOT model-parameter uncertainty. Additive jitter on "
    "e_points is a stand-in\nfor the latter; propagating it properly would mean "
    "bootstrapping the training data and\nrebuilding the walk-forward per draw (~13 min "
    "each, ~11h at J=50), which was rejected on\ncost. So these intervals are honest "
    "about 'which branch did we land on' and SILENT about\n'is the model itself right'. "
    "Do not read them as wider than that."
)


def jitter_table(frames, eps, seed):
    """One jitter value per (element, gw), shared by every arm and every cutoff.

    Built from the UNION of keys so an arm carrying a row the other lacks still gets
    the same draw for the rows they share. Keys are sorted before the draw so the
    result depends on the key set and the seed alone, never on row order.
    """
    keys = pd.concat([f[KEYS] for f in frames], ignore_index=True).drop_duplicates()
    keys = keys.sort_values(KEYS).reset_index(drop=True)
    rng = np.random.default_rng(seed)
    keys["_jitter"] = rng.normal(0.0, eps, size=len(keys))
    return keys


def apply_jitter(df, table):
    """Add the jitter to e_points, clipped at zero.

    Clipping matters: a negative expected score is not a thing the optimiser should
    ever be offered, and letting one through would make a player actively repellent
    rather than merely unattractive.
    """
    n = len(df)
    out = df.merge(table, on=KEYS, how="left")
    if len(out) != n:
        raise ValueError(f"jitter join changed row count: {n} -> {len(out)}")
    out["e_points"] = (out["e_points"] + out["_jitter"].fillna(0.0)).clip(lower=0.0)
    return out.drop(columns="_jitter")


def report(df, level=0.95):
    """summarise() plus the caveat, for anywhere the intervals are quoted."""
    return f"{summarise(df, level).to_string(index=False)}\n\n{CAVEAT}"


def summarise(df, level=0.95):
    """Paired summary over draws. `df` needs columns: eps, draw, arm_a, arm_b, delta.

    Quote the result via report(), or repeat CAVEAT alongside it -- see module docstring.
    """
    lo_q, hi_q = (1 - level) / 2 * 100, (1 + level) / 2 * 100
    z = 1.959963985
    rows = []
    for eps, g in df.groupby("eps"):
        d = g["delta"].values
        n = len(d)
        sd = float(d.std(ddof=1)) if n > 1 else 0.0
        se = sd / np.sqrt(n) if n > 1 else 0.0
        rows.append({
            "eps": eps,
            "draws": n,
            "mean_delta": round(float(d.mean()), 1),
            "sd_delta": round(sd, 1),
            # CI on the MEAN -- "is the average margin non-zero". This is the one that
            # answers whether the treatment helps.
            "mean_ci_low": round(float(d.mean() - z * se), 1),
            "mean_ci_high": round(float(d.mean() + z * se), 1),
            "mean_excludes_0": bool(abs(d.mean()) > z * se) if n > 1 else False,
            # Spread of the DRAWS -- "how much could one season differ". Much wider,
            # and a different question. Conflating the two was a real bug here once:
            # the draw spread straddled zero while the mean was three SE from it.
            "draw_p2.5": round(float(np.percentile(d, lo_q)), 1),
            "draw_p97.5": round(float(np.percentile(d, hi_q)), 1),
            "b_wins_pct": round(100 * float((d > 0).mean()), 1),
            "mean_a": round(float(g["arm_a"].mean()), 1),
            "mean_b": round(float(g["arm_b"].mean()), 1),
            "sd_a": round(float(g["arm_a"].std(ddof=1)), 1) if n > 1 else 0.0,
        })
    return pd.DataFrame(rows).sort_values("eps")
