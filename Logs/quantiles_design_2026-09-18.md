# Quantiles (P10/P50/P90) for `predict_points` — design and measurement (2026-09-18)

Design only. **Nothing built.** Closes the specification gap named in master plan §5.4
(`predict_points(ids, horizon, quantiles?)` returns `e_points + P10/50/90`) and carried as
item 1 of §12.2 of the Squad State handoff.

**The problem.** Two players at the same expected points can be completely different bets and
the single number hides it. §5.3's demo moment depends on the ceiling: *"Haaland by 0.8
expected points, but Salah has the higher ceiling; if you're chasing rank, that flips the
pick."*

---

## 1. Approach, and why not the alternatives

**Monte Carlo over the model's own component probabilities.** Not a fitted parametric shape —
that assumes the distribution the decomposed design exists to derive. Not an empirical lookup
over historical comparables — that cannot tell a defender from a forward at equal expected
value. Nothing new is modelled: the spread is already implied by the components, and
simulation stops averaging it away.

**Structure.** One shared minutes draw per iteration drives everything else, which is what
converts the model's own uncertainty into spread:

1. `started ~ Bern(p_start)`; if started, `played60 ~ Bern(p60)`; else
   `came_on ~ Bern(p_sub)` where `p_sub = (p_play_any − p_start)/(1 − p_start)`.
2. Every rate term conditions on the **realised** minutes, not on `minutes_frac`. Goals and
   assists are drawn Poisson at `e_goals · (m/minutes_frac)`, so the mean is `e_goals` by
   construction while the variance is no longer suppressed.
3. **Conceded and clean sheet are coupled through ONE team-goals draw**: `C ~ Poisson(opp_lambda)`
   over the match, `CS = (C == 0) and played60`, and the player's on-pitch concessions
   `~ Binomial(C, m)`.

### A check that came out well

Coupling only works if the model's `p_cs` agrees with the clean-sheet chance its own conceded
term implies. Measured on 74 regular-starting GK/DEF rows at GW6:

```
p_cs vs exp(-opp_lambda):  diff mean +0.0000, sd 0.0000, max 0.000
```

**Exactly equal on every row** — `p_cs` *is* `exp(-opp_lambda)`. The model is internally
consistent here, so the coupling introduces no contradiction and the simulation can never draw
a clean sheet alongside two conceded.

### The one place "nothing new is modelled" does not hold

The frame carries `p_start`, `p60`, `p_play_any`, `e_minutes` and `minutes_frac` — **the mean
of the minutes distribution and three probabilities, but not its shape.** Sampling minutes
needs one assumption about within-state minutes. The measurement used 85 / 35 / 20 minutes for
started-and-60+, started-and-withdrawn, and substitute, **scaled per row so the mean reproduces
`e_minutes` exactly**. That keeps every linear term reconciling regardless of the shape; only
the two `floor()` terms are shape-sensitive. This is a named constant and belongs in the
`constant` vocabulary, not buried.

## 2. Measured cost (droplet, live frame, N = 20,000)

| | measured | my estimate | |
|---|---|---|---|
| per player | **10.4–11.6 ms** | ~5 ms | **2× under** |
| full frame, 3,954 rows | **35.9–37.6 s** | 15–40 s | top of range |
| peak RSS, chunk 256 | **526 MB** | 200–300 MB | **~2× under** |
| peak RSS, chunk 512 | 921 MB | — | use 256 |

**It fits inside the build, and the memory argument is better than it first looks.** The build
peaks at 1,569 MB during assembly; the simulation runs *after*, on the finished frame, at
526 MB total with the frame resident. The peak is therefore `max(1569, 526)` — **unchanged** —
against 3,916 MB with no swap.

**Runtime is the real constraint.** A build is 70–86 s; +36 s makes it 106–122 s. The t10 slot
fires at T−10 min (600 s), so a 122 s build still finishes at T−8. It fits, but it is a ~45%
increase on the one run that cannot be late, for a number nobody acts on in the last ten
minutes. **Recommendation: compute it in the build behind a flag, OFF for t10**, on by default
for nightly / post_ingest / t90 / t30.

Per-player at 10 ms is trivially on demand, which is what the single-player drilldown path uses.

## 3. Reconciliation — the proposed 0.05 tolerance does not hold

Measured over all 3,954 rows, `|sim mean − e_points|`:

```
mean 0.0137   median 0.0063   p95 0.0531   max 0.3246
within 0.02 : 3134/3954 (79.3%)
within 0.05 : 3728/3954 (94.3%)
within 0.10 : 3937/3954 (99.6%)
```

**A flat 0.05 fails on 226 rows (5.7%).** A tolerance that 5.7% of rows breach is not a
tolerance, it is a permanent finding stream that will be ignored within a week — the alarm
fatigue failure in a different costume.

The reason it fails is structural, not a bug: Monte Carlo error is `sd/√N`, so a **flat**
absolute bound penalises high-variance players for being high-variance. The honest check scales
with the row:

> **tolerance = max(0.02, 3 · sd/√N)** — a three-sigma band on the simulation's own error,
> reported per row, with the structural component separated.

The `max 0.3246` outlier is larger than a 3-sigma band plausibly explains and should be
identified before building.

### The structural (Jensen) residual, isolated as specified

`pts_saves` and `pts_conceded` are `E[floor(·)]` of a Poisson whose rate the model evaluates at
*expected* minutes; sampling minutes makes the rate random, and `E[floor(·)]` at a random rate
differs from the same at the mean rate. Measured by re-running the same draws with the rate
pinned to the model's `minutes_frac`:

```
GK/DEF, minutes-conditioned : mean |resid| 0.0207
GK/DEF, rate pinned         : mean |resid| 0.0120
structural component        : mean -0.0155   sd 0.0204
non-GK/DEF (no floor terms) : mean |resid| 0.0090   <- sampling noise only
```

**The structural residual is real, one-directional and about the size of the sampling noise:
the simulation scores GK and DEF ~0.016 points below `e_points`, systematically.** It does not
shrink with N.

**No recentring** (user decision, 2026-09-18). The residual is a finding about the model — the
model evaluates a nonlinear function at a point estimate of minutes — and smoothing it away
would delete the one piece of information the simulation produces about the model itself.

## 4. FINDING: the feature's headline use case is its weakest output

**P90 carries the new information. P90 is also what the known defects corrupt most. And they
corrupt it on precisely the premium penalty-taking captain candidates the ceiling comparison
exists to serve.**

§5.1 already publishes "N of 9 lines are constants standing in for models". **In a point
estimate a constant is a level error; in a distribution it is ZERO VARIANCE** — the existing
summary line becomes a far sharper instrument here. Measured on the live GW6 frame (659 rows):

| term | label | effect on the distribution |
|---|---|---|
| bonus | `constant` / *0 by decision* | **all 659 rows exactly 0**. Real bonus is 0–3 and concentrated on hauls — pure right-tail mass. P90 too low and the wrong shape |
| penalties | `constant` / *fallback 0.05*, and #19's definitional zero | `e_pen_goals` mean **0.00015**, exactly 0 on **637/659** rows. A taker's ceiling carries essentially no penalty mass |
| cards | `constant` / *position rates* | variance from a league rate, not the player |
| DC (FWD) | `constant` / *flat by design* | zero player-level variance |

Bonus is worth ~0.3 points a week as a level shift and was deleted on that basis
(KNOWN_ISSUES #20, adopted 2026-08-26). As a **variance** source it is not a 0.3-point
question: it is 0–3 points landing exactly on the hauls that define the upper tail.

**This is a third argument for reopening the bonus and penalty work**, alongside #19's 2026-09-14
correction of the reading and the `penalty_share` coupling that #19 records. The earlier
arguments were about the level and about rank endpoints. This one is different in kind: a
feature specified in the master plan cannot do its job while these two terms contribute no
variance, and the failure is concentrated on the exact players the feature exists to compare.
Not re-argued here and nothing reopened — recorded so the next pre-registration has it.

**Surfaced, not disclaimed.** Output carries a `quantile_fidelity` block reusing
`explain_prediction`'s fixed vocabulary — the constant-sourced terms, their named constants, a
one-line count, and an explicit **direction: P90 is biased low**. Never a bare P90.

## 5. Degenerate rows — measured, and signalled explicitly

FPL points are integers, so the simulated distribution is discrete and the quantiles are coarse.
Measured over all 3,954 rows:

```
P10 == P50              : 2367 / 3954  (59.9%)
P10 == P50 == 0         : 2365
P10 == P50 == P90       : 0 rows
all three equal, any row: 0 rows
```

**The bar never fully collapses** — no row has all three quantiles equal — but on 60% of rows it
collapses at the **bottom**: P10 = P50 = 0 for fringe players who usually do not play, with P90
carrying the only signal. That is honest and correct, and it is not something the frontend should
have to infer from equality.

**Signalled as data, not left to be discovered:**

* `quantile_degenerate` — boolean, true when `P10 == P50`;
* `quantile_distinct` — count of distinct values among the three (1, 2 or 3);
* both stored alongside the quantiles, so the UI renders a one-sided bar deliberately rather
  than a zero-width one by accident.

## 6. Determinism

`SeedSequence(entropy=run_seed, spawn_key=(element, gw))` — independent of row order, chunking
and parallelism, so the same row in the same run always draws the same numbers. `run_seed`,
`n_draws` and `quantile_method_version` live in `model_runs.knowledge` beside the existing
provenance. A stored quantile is reproducible from the run record alone.

## 7. Storage

**Stored columns on `model_predictions` plus `quantile_method_version`**, with on-demand
recompute for single-player drilldown.

The deciding constraint is the **frontend, not the modelling**: the Predictions screen needs a
sortable table of ~3,900 rows with range bars, and on-demand would pay 36 s per page load.
Stored columns follow the 24-term-columns precedent — nullable, never backfilled, one SELECT on
the read path — and let `compare_runs` show how the *range* moved between runs, not just the
point. The cost is that quantiles freeze at the sampler version that wrote them, which the
version stamp makes visible instead of silent.

## 8. Model path

**Not touched.** This reads the assembled frame and derives new columns; `e_points` is unchanged,
so parity and the as-of guard are unaffected. Nothing in `assembly`, `minutes`, `dixon_coles`,
`defensive`, `bonus`, `attacking_rates` or `horizon_minutes` changes. If closing the
reconciliation residual ever required changing how a term is computed, that would be a
model-path change and a new pre-registration.

## 9. Open before building

* the **0.3246 max residual** — identify the row and the cause;
* confirm the revised per-row tolerance `max(0.02, 3·sd/√N)`;
* confirm the t10 flag;
* the minutes-shape constant (85/35/20) wants a sensitivity check, since the two `floor()` terms
  are the only ones that depend on it.
