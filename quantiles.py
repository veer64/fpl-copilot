"""
quantiles.py -- P10/P50/P90 for a prediction, by Monte Carlo over the model's OWN
component probabilities. Design and measurement: Logs/quantiles_design_2026-09-18.md.

WHY SIMULATION. Two players at the same expected points can be completely different bets and
the single number hides it (master plan 5.3, 5.4; Squad State handoff 12.2 item 1). Not a
fitted parametric shape -- that would assume the distribution the decomposed design exists to
derive. Not an empirical lookup over comparables -- that cannot tell a defender from a forward
at equal expected value. The spread is already implied by the components; simulation stops
averaging it away.

PURE. Like explain.py, this imports no part of the model stack: it reads the assembled frame's
columns and the scoring constants, so the API process can produce a quantile without loading
the model. It never changes e_points and touches no model-path file.

THE STRUCTURE. One minutes draw per iteration drives everything, which is the whole mechanism:
  1. started ~ Bern(p_start); if started, played60 ~ Bern(p60); else came_on ~ Bern(p_sub),
     with p_sub = (p_play_any - p_start)/(1 - p_start).
  2. Every rate term conditions on the REALISED minutes, not on minutes_frac. Goals and assists
     are drawn at e_goals * (m / minutes_frac), so the mean is e_goals by construction while the
     variance is no longer suppressed.
  3. Clean sheet and goals conceded are coupled through ONE team-goals draw at
     cs_lambda = -ln(p_cs). NOT at opp_lambda: at horizon steps 1-5 the two are identical to
     0.000000 because with no odds both collapse to pure Dixon-Coles, but AT STEP 0 THEY ARE
     DIFFERENT QUANTITIES -- opp_lambda is the pure-market lambda (LAM_BLEND_W = 0) while
     p_cs = exp(-cs_lambda) with cs_lambda = 0.2*DC + 0.8*market (CS_BLEND_W = 0.2). Coupling on
     opp_lambda produced a 0.30-point error on the clean-sheet term of step-0 defenders and was
     the largest residual in the whole frame. Drawing at -ln(p_cs) makes P(clean sheet) exactly
     p_cs, and leaves conceded with a rate differing by ~0.2% at step 0 and not at all after --
     a negligible error on a ~0.19-point term traded for an exact one on a term worth up to 4.

MS-1 IS A NEW ASSUMPTION AND IS NAMED AS ONE. The frame carries the MEAN of the minutes
distribution (e_minutes) and three probabilities, but NOT its shape. Sampling minutes therefore
needs something the model does not contain. "Nothing new is modelled" holds for every other
component and NOT for this one, and is not claimed. The shape is scaled per row so the mean
reproduces e_minutes exactly, which is why the reconciliation is insensitive to it -- but the
QUANTILES are not: at two alternative shapes P90 moved on ~2.5% of rows by up to 2 points,
against 0.2-0.3% for P10. Versioned so it can be varied and compared.

THE RECONCILIATION IS TWO-PART, deliberately, and one combined bar would be wrong:
  * SAMPLING component -- must sit inside max(0.02, 3*sd/sqrt(N)). Monte Carlo error is
    sd/sqrt(N), so a FLAT bound would penalise high-variance players for being high-variance;
    measured, a flat 0.05 failed on 5.7% of rows, which is a permanent finding stream rather
    than a tolerance.
  * STRUCTURAL component -- reported per row as a VALUE WITH NO PASS BAR. pts_saves and
    pts_conceded are E[floor(.)] of a Poisson whose rate the model evaluates at EXPECTED
    minutes; sampling minutes makes the rate random and E[floor(.)] at a random rate differs
    from the same at the mean rate. It is a bias, not noise: measured at -0.0155 mean on GK/DEF
    and it does NOT shrink with N. A noise band can never contain a bias, so a single combined
    bar would either hide it or fail 8% of rows forever. It is identically ZERO for MID and FWD,
    who have no floor terms.
  NOT recentred (decision 2026-09-18): the residual is a finding about the model -- the model
  evaluates a nonlinear function at a point estimate of minutes -- and smoothing it away would
  delete the one thing the simulation reveals about the model itself.

P90 IS NOT AS GOOD A NUMBER AS P50, and the output says so rather than leaving a reader to
assume otherwise. See fidelity().
"""
import math

import numpy as np

from explain import CONSTANT_LABELS, CS_PTS, GOAL_PTS, PEN_FALLBACK

METHOD_VERSION = "mc-1"

# Minutes shapes: (started and 60+, started and withdrawn, substitute), in minutes.
# Scaled per row so the mean reproduces e_minutes exactly.
MINUTES_SHAPES = {"MS-1": (85.0, 35.0, 20.0),
                  "MS-2": (80.0, 30.0, 15.0),
                  "MS-3": (88.0, 45.0, 25.0)}
DEFAULT_SHAPE = "MS-1"

N_DRAWS = 20_000
TOL_FLOOR = 0.02        # below this, sampling noise is not worth reporting
TOL_SIGMA = 3.0         # a three-sigma band on the simulation's own error

QUANTILE_COLS = ["q_p10", "q_p50", "q_p90", "q_sd", "q_degenerate", "q_distinct",
                 "q_resid_sampling", "q_resid_structural", "q_tolerance",
                 "q_method_version", "q_minutes_shape", "q_draws"]


def row_rng(run_seed, element, gw):
    """A stream keyed by (run, element, gameweek) -- independent of row order, chunking and
    parallelism, so a stored quantile is reproducible from the run record alone."""
    return np.random.default_rng(np.random.SeedSequence([int(run_seed), int(element), int(gw)]))


def _f(row, key, default=0.0):
    v = row.get(key, default)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return default if v != v else v


def simulate_row(row, n, rng, shape=DEFAULT_SHAPE):
    """One row's simulated point totals. Returns (free, pinned): `free` conditions the
    saves/conceded rate on the realised minutes, `pinned` holds it at the model's
    minutes_frac. Their difference IS the structural residual; for MID/FWD they are the
    same array, because those positions carry no floor terms."""
    a, b, c = (x / 90.0 for x in MINUTES_SHAPES[shape])
    pos = str(row.get("position", ""))
    ps, p60 = _f(row, "p_start"), _f(row, "p60")
    ppa, mf = _f(row, "p_play_any"), _f(row, "minutes_frac")
    eg, ea = _f(row, "e_goals"), _f(row, "e_assists")
    pdc, s90 = _f(row, "p_dc_hit"), _f(row, "saves_per_90")
    y90, r90 = _f(row, "yellow_per_90"), _f(row, "red_per_90")
    pcs = min(max(_f(row, "p_cs"), 1e-9), 1.0)
    gp, csp = GOAL_PTS.get(pos, 0), CS_PTS.get(pos, 0)
    is_gk, is_gkdef = pos == "GK", pos in ("GK", "DEF")

    psub = min(max((ppa - ps) / max(1.0 - ps, 1e-9), 0.0), 1.0) if ps < 1 else 0.0
    denom = ps * p60 * a + ps * (1 - p60) * b + (1 - ps) * psub * c
    k = (mf / denom) if denom > 1e-12 else 0.0

    started = rng.random(n) < ps
    p60d = started & (rng.random(n) < p60)
    came = (~started) & (rng.random(n) < psub)
    m = np.where(p60d, a, np.where(started, b, np.where(came, c, 0.0))) * k
    played = started | came
    scale = (m / mf) if mf > 1e-9 else np.zeros(n)

    base = np.where(p60d, 2.0, np.where(played, 1.0, 0.0))
    base = base + rng.poisson(np.maximum(eg * scale, 0.0)) * gp
    base = base + rng.poisson(np.maximum(ea * scale, 0.0)) * 3.0
    base = base + (rng.random(n) < np.clip(pdc * m, 0, 1)) * 2.0

    # ONE team-goals draw at -ln(p_cs) drives both the clean sheet and the concessions,
    # so the simulation can never award a clean sheet alongside a conceded goal.
    c_team = rng.poisson(-math.log(pcs), n)
    base = base + ((c_team == 0) & p60d) * float(csp)
    base = base - (rng.random(n) < np.clip(y90 * m, 0, 1)) * 1.0
    base = base - (rng.random(n) < np.clip(r90 * m, 0, 1)) * 3.0

    if not is_gkdef:
        return base, base                      # no floor terms: structural residual is 0

    free = base - np.floor(rng.binomial(c_team, np.clip(m, 0, 1)) / 2.0)
    pinned = base - np.floor(rng.binomial(c_team, min(max(mf, 0.0), 1.0)) / 2.0)
    if is_gk:
        free = free + np.floor(rng.poisson(np.maximum(s90 * m, 0.0)) / 3.0)
        pinned = pinned + np.floor(rng.poisson(max(s90 * mf, 0.0), n) / 3.0)
    return free, pinned


def quantiles_for_row(row, run_seed, n=N_DRAWS, shape=DEFAULT_SHAPE):
    """The stored record for one row: the three quantiles, the two residual halves, the
    tolerance the sampling half is judged against, and the degeneracy signals."""
    rng = row_rng(run_seed, row["element"], row["gw"])
    free, pinned = simulate_row(row, n, rng, shape)
    p10, p50, p90 = (float(x) for x in np.quantile(free, [0.10, 0.50, 0.90]))
    sd = float(np.std(free))
    ep = _f(row, "e_points")
    structural = float(np.mean(free) - np.mean(pinned))
    sampling = float(np.mean(pinned) - ep)
    return {
        "q_p10": p10, "q_p50": p50, "q_p90": p90, "q_sd": sd,
        # integer points make the distribution discrete; on ~60% of rows the bar collapses at
        # the BOTTOM (P10 == P50 == 0 for a fringe player) with P90 carrying the only signal.
        # Signalled as data so the UI renders a one-sided bar deliberately, not by accident.
        "q_degenerate": bool(p10 == p50),
        "q_distinct": int(len({p10, p50, p90})),
        "q_resid_sampling": sampling,
        "q_resid_structural": structural,
        "q_tolerance": max(TOL_FLOOR, TOL_SIGMA * sd / math.sqrt(n)),
        "q_method_version": METHOD_VERSION, "q_minutes_shape": shape, "q_draws": int(n),
    }


def add_quantiles(frame, run_seed, n=N_DRAWS, shape=DEFAULT_SHAPE):
    """Add QUANTILE_COLS to a copy of `frame`. e_points is untouched."""
    out = [quantiles_for_row(r, run_seed, n, shape) for r in frame.to_dict("records")]
    f = frame.copy()
    for col in QUANTILE_COLS:
        f[col] = [o[col] for o in out]
    return f


def reconciles(row):
    """The sampling half only. The structural half has NO pass bar by design."""
    s, t = _f(row, "q_resid_sampling"), _f(row, "q_tolerance", TOL_FLOOR)
    return abs(s) <= t


def fidelity(row):
    """What the reader must be told about these numbers, in explain_prediction's fixed
    vocabulary (model / constant / rule and the named constants) -- not a disclaimer essay.

    A constant term is a level error in a point estimate and ZERO VARIANCE in a distribution,
    so explain's 'N of 9 lines are constants' summary is a much sharper instrument here."""
    zero_variance, notes = [], []
    if abs(_f(row, "exp_bonus")) < 1e-12:
        zero_variance.append({"term": "bonus", "source": "constant",
                              "constant": CONSTANT_LABELS["bonus_off"],
                              "effect": "real bonus is 0-3 and concentrated on hauls: pure "
                                        "right-tail mass, so P90 is too low and the wrong shape"})
    if abs(_f(row, "e_pen_goals")) < 1e-9 or abs(_f(row, "penalty_share") - PEN_FALLBACK) < 1e-9:
        zero_variance.append({"term": "penalties", "source": "constant",
                              "constant": CONSTANT_LABELS["pen_fallback"],
                              "effect": "the term measures penalties MISSED (KNOWN_ISSUES #19), "
                                        "so a taker's ceiling carries almost no penalty mass"})
    zero_variance.append({"term": "cards", "source": "constant",
                          "constant": CONSTANT_LABELS["card_rates"],
                          "effect": "variance from a league rate, not this player"})

    st = _f(row, "q_resid_structural")
    if abs(st) > 1e-9:
        notes.append(f"structural residual {st:+.4f} points: the model evaluates the saves and "
                     "conceded terms at EXPECTED minutes, so simulating minutes disagrees with "
                     "it by a bias that does not shrink with more draws. Reported, not corrected.")

    return {
        "p90_is_weaker_than_p50": True,
        "p90_caveat": (
            "P90 carries the new information and is the LEAST reliable of the three. It is "
            "fragile in three independent ways: bonus is fixed at zero so the entire upper tail "
            "is missing; the penalty term measures penalties missed, so takers' ceilings are "
            "understated; and the minutes shape (" + str(row.get("q_minutes_shape", DEFAULT_SHAPE))
            + ") is an assumption the model does not contain, which moves P90 on about 2.5% of "
              "rows by up to 2 points while barely moving P10 or P50. Do not read P90 as "
              "comparable in quality to P50, and do not compare two players' ceilings without "
              "saying this."),
        "zero_variance_terms": zero_variance,
        "n_zero_variance": len(zero_variance),
        "summary": (f"{len(zero_variance)} of 9 lines contribute no variance because they are "
                    f"constants; all of them bias P90 low."),
        "degenerate": bool(row.get("q_degenerate", False)),
        "degenerate_note": ("P10 == P50: the range bar is one-sided, which is correct for a "
                            "player who usually does not play -- P90 carries the only signal."
                            if row.get("q_degenerate") else None),
        "notes": notes,
        "method_version": row.get("q_method_version", METHOD_VERSION),
        "minutes_shape": row.get("q_minutes_shape", DEFAULT_SHAPE),
        "draws": int(_f(row, "q_draws", N_DRAWS)),
    }
