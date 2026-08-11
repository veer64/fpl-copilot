"""
FPL Copilot — Block bootstrap confidence intervals

A season total is one number from one season played once. It cannot, on its own,
distinguish two very different stories:

    1. The transfer machinery genuinely works, and would win by roughly this much
       on any season.
    2. The model got lucky in 2025-26 -- a captain haul landing in the right week,
       a transfer that happened to come good -- and the edge would shrink or vanish
       on a different season.

Both stories produce exactly the same 1889. This module is how you tell them apart.

THE IDEA
--------
You cannot replay 2025-26. So you build alternative seasons out of the one you
observed: draw gameweeks at random WITH REPLACEMENT until you have 38 of them,
sum the result, and repeat a thousand times. Some gameweeks appear twice, some not
at all. The spread across those thousand fake seasons tells you how much the total
could plausibly have moved by luck alone.

WHY BLOCKS
----------
A plain bootstrap treats every gameweek as independent. FPL gameweeks are not. If
a key player is injured in GW14 he is probably still injured in GW15 and GW16;
form, fixture runs and injuries all arrive in STREAKS.

Shuffling individual gameweeks destroys those streaks, and a bootstrap that
destroys real dependence reports an interval that is too NARROW -- it would make
the result look more certain than it is. Resampling contiguous BLOCKS of
gameweeks keeps the streaks intact.

Block length is a genuine trade-off, not a tuning knob to optimise:
    too short -> streaks broken, interval too narrow, overconfident
    too long  -> few distinct blocks, interval too wide, underpowered
For 38 gameweeks, 4-6 is a reasonable range. The default is 5, and
`sensitivity_to_block_length` exists precisely so the choice can be shown not to
drive the conclusion.

WHAT GETS RESAMPLED
-------------------
Not season totals -- the per-gameweek DIFFERENCE between two strategies. For each
gameweek the model scored something and the baseline scored something; the gap is
the model's edge that week. Those 38 gaps sum to the headline margin.

Bootstrapping the differences rather than the two totals separately is deliberate:
both strategies faced the SAME gameweeks, so a week where everyone hauled is not
evidence about either one. Pairing cancels that shared variation out and gives a
much tighter, more honest read on the thing actually in question.
"""

import numpy as np
import pandas as pd

DEFAULT_BLOCK = 5
DEFAULT_N_BOOT = 2000


def _resample_blocks(values, block_length, rng):
    """Build one alternative season by drawing contiguous blocks with replacement.

    Blocks wrap around the end of the season, which keeps every starting position
    equally likely. Without wrapping, late gameweeks would be systematically
    under-sampled -- a subtle bias that would quietly distort the interval.
    """
    n = len(values)
    out = []
    while len(out) < n:
        start = int(rng.integers(0, n))
        block = [values[(start + i) % n] for i in range(block_length)]
        out.extend(block)
    return np.array(out[:n])


def block_bootstrap(values, block_length=DEFAULT_BLOCK, n_boot=DEFAULT_N_BOOT,
                    seed=0):
    """Bootstrap the SUM of a per-gameweek series.

    values : array of per-gameweek numbers (points, or differences between two
             strategies)
    Returns the array of n_boot resampled sums.
    """
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=float)
    return np.array([_resample_blocks(values, block_length, rng).sum()
                     for _ in range(n_boot)])


def interval(samples, level=0.95):
    """Percentile interval from bootstrap samples.

    The percentile method is used because it is transparent and needs no
    distributional assumption. It is slightly biased for skewed statistics; for a
    SUM over 38 roughly-exchangeable terms that bias is negligible, and the
    honesty of a method the reader can verify by eye is worth more here.
    """
    lo = (1 - level) / 2 * 100
    hi = (1 + level) / 2 * 100
    return float(np.percentile(samples, lo)), float(np.percentile(samples, hi))


def compare_strategies(model_points, baseline_points, label="baseline",
                       block_length=DEFAULT_BLOCK, n_boot=DEFAULT_N_BOOT, seed=0):
    """The main entry point: is the model's margin over a baseline real?

    model_points, baseline_points : per-gameweek points, SAME gameweeks, SAME order.

    Returns a dict with the observed margin, its confidence interval, and the
    share of resampled seasons in which the model lost. That last figure is the
    one to quote: it answers "how often would luck alone have produced a worse
    result than the baseline?" directly, without a p-value ritual.
    """
    m = np.asarray(model_points, dtype=float)
    b = np.asarray(baseline_points, dtype=float)
    if len(m) != len(b):
        raise ValueError(f"length mismatch: {len(m)} model vs {len(b)} baseline "
                         "-- the two strategies must cover the same gameweeks")

    diff = m - b
    observed = float(diff.sum())

    samples = block_bootstrap(diff, block_length, n_boot, seed)
    lo, hi = interval(samples)

    return {
        "baseline": label,
        "observed_margin": observed,
        "ci_low": lo,
        "ci_high": hi,
        "ci_excludes_zero": lo > 0 or hi < 0,
        "share_of_seasons_model_loses": float((samples <= 0).mean()),
        "bootstrap_sd": float(samples.std()),
        "block_length": block_length,
        "n_boot": n_boot,
        "n_gameweeks": len(m),
        "samples": samples,
    }


def season_total_interval(points, block_length=DEFAULT_BLOCK,
                          n_boot=DEFAULT_N_BOOT, seed=0):
    """Confidence interval on a single strategy's season total.

    Useful for reporting, but note it answers a WEAKER question than
    compare_strategies: it describes how much the total could have varied, not
    whether one strategy beats another. The paired comparison is the one that
    supports a claim.
    """
    samples = block_bootstrap(points, block_length, n_boot, seed)
    lo, hi = interval(samples)
    return {
        "observed_total": float(np.sum(points)),
        "ci_low": lo,
        "ci_high": hi,
        "bootstrap_sd": float(samples.std()),
        "samples": samples,
    }


def sensitivity_to_block_length(model_points, baseline_points,
                                block_lengths=(1, 2, 4, 5, 6, 8, 10),
                                n_boot=DEFAULT_N_BOOT, seed=0):
    """Re-run the comparison across block lengths.

    Block length is a judgement call, so the honest move is to show the
    conclusion does not depend on it. If the interval excludes zero at every
    sensible block length, the choice of 5 was not doing the work.

    Expect the interval to WIDEN as blocks get longer -- that is the method
    correctly acknowledging dependence, not a problem. Block length 1 is the
    plain (non-block) bootstrap, included to show how much narrower it wrongly
    looks when streaks are ignored.
    """
    rows = []
    for L in block_lengths:
        r = compare_strategies(model_points, baseline_points,
                               block_length=L, n_boot=n_boot, seed=seed)
        rows.append({
            "block_length": L,
            "margin": r["observed_margin"],
            "ci_low": round(r["ci_low"], 1),
            "ci_high": round(r["ci_high"], 1),
            "excludes_zero": r["ci_excludes_zero"],
            "loses_pct": round(100 * r["share_of_seasons_model_loses"], 2),
        })
    return pd.DataFrame(rows)


def report(result):
    """Print a comparison result in plain language."""
    verdict = ("the margin is unlikely to be luck"
               if result["ci_excludes_zero"]
               else "LUCK CANNOT BE RULED OUT -- the interval includes zero")

    print(f"vs {result['baseline']}")
    print(f"  observed margin : {result['observed_margin']:+.0f} points")
    print(f"  95% interval    : [{result['ci_low']:+.0f}, {result['ci_high']:+.0f}]")
    print(f"  model loses in  : {100 * result['share_of_seasons_model_loses']:.1f}% "
          f"of resampled seasons")
    print(f"  block length {result['block_length']}, {result['n_boot']} resamples")
    print(f"  -> {verdict}")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from simulator import load_season, simulate_season
    from baselines import set_and_forget, hindsight_set_and_forget

    season = load_season()

    print("Running model and baselines...")
    state, sim_log = simulate_season(season, verbose=False)
    saf_total, saf_log = set_and_forget(season)
    hind_total, hind_log = hindsight_set_and_forget(season)

    print(f"\nmodel {state.total_points}  set-and-forget {saf_total}  "
          f"hindsight {hind_total}\n")

    total_ci = season_total_interval(sim_log["points"].values)
    print(f"Season total    : {total_ci['observed_total']:.0f} "
          f"[{total_ci['ci_low']:.0f}, {total_ci['ci_high']:.0f}]\n")

    for label, log in [("set_and_forget", saf_log), ("hindsight", hind_log)]:
        r = compare_strategies(sim_log["points"].values, log["points"].values,
                               label=label)
        report(r)
        print()

    print("Sensitivity to block length (vs set_and_forget):")
    print(sensitivity_to_block_length(sim_log["points"].values,
                                      saf_log["points"].values).to_string(index=False))