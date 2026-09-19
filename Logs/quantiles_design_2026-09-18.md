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
3. **Conceded and clean sheet are coupled through ONE team-goals draw.** Originally written as
   `C ~ Poisson(opp_lambda)`; **CORRECTED in R3 below to `C ~ Poisson(-ln p_cs)`** after that
   coupling was found to be wrong at step 0. `CS = (C == 0) and played60`, and the player's
   on-pitch concessions `~ Binomial(C, m)`.

### A check that came out well -- and was NOT GENERAL. Superseded by R3.

Coupling only works if the model's `p_cs` agrees with the clean-sheet chance its own conceded
term implies. Measured on 74 regular-starting GK/DEF rows at GW6:

```
p_cs vs exp(-opp_lambda):  diff mean +0.0000, sd 0.0000, max 0.000
```

Exactly equal on every row -- and the conclusion drawn from it was **WRONG**, because GW6 is
horizon step 1. At steps 1-5 there are no odds and both quantities collapse to pure
Dixon-Coles, so equality there says nothing about step 0, where `opp_lambda` is the pure-market
lambda and `p_cs` comes from the 0.2/0.8 CS blend. That mistake produced the 0.3246 residual.
**A check on one horizon step is not a check on the model.** See R3 for the diagnosis and the
fix; the coupling now uses `-ln(p_cs)`.

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

The `max 0.3246` outlier is larger than a 3-sigma band plausibly explains. **Identified in R3:
a sampler bug in the clean-sheet coupling, now fixed -- max residual 0.3265 -> 0.1060.** The
figures in this section are the PRE-FIX measurement; R3 carries the corrected ones.

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

---

# Addendum — the four rulings, and what closing them found (2026-09-18)

## R1. Tolerance: `max(0.02, 3·sd/√N)` per row — accepted, and it needs a second half

Ruling accepted: a flat bound penalises high-variance players for being high-variance, and a
5.7% permanent breach rate is alarm fatigue.

Measured with the band in place (corrected sampler, N = 20,000):

```
rows inside their own band : 3636 / 3954  (92.0%)
band median 0.0200   max 0.1242
worst offenders: Ouattara DEF 0.1056/0.0200 · Struijk DEF 0.1045/0.0248
                 Tomiyasu DEF 0.0879/0.0200 · Pau Torres DEF 0.1038/0.0414
```

**Every remaining breach is a DEF, and that is the point: the band measures SAMPLING noise, and
what is left is the STRUCTURAL residual, which is not noise and does not shrink with N.** A
noise band can never contain a bias. So the check is two-part, not one:

* **sampling component** must sit inside `max(0.02, 3·sd/√N)`;
* **structural component** — measured separately by re-running the same draws with the
  saves/conceded rate pinned to `minutes_frac` — is reported per row as a value, with no pass
  bar, because it is a property of the model and not an error in the simulator.

A single combined bar would either hide the bias or fail 8% of rows forever.

## R2. t10 flag — confirmed

On for nightly, post_ingest, t90, t30. **Off for t10.** +36 s on a 70–86 s build is a ~45%
increase on the one run that cannot be late, for a number nobody acts on in the last ten
minutes.

## R3. The 0.3246 residual — a SAMPLER BUG, found and fixed. Not a model-path question.

Term-by-term attribution on the worst row (Neco Williams, DEF, GW5, N = 200,000) put the entire
residual in one term:

```
term            model column   simulated       diff
pts_appear            1.9201      1.9212     +0.0011
pts_goals             0.4650      0.4669     +0.0020
pts_assists           0.4127      0.4167     +0.0040
pts_cs                1.9712      1.6753     -0.2958   <==
pts_dc                0.9462      0.9385     -0.0076
pts_conceded         -0.1871     -0.1905     -0.0034
pts_cards            -0.1799     -0.1784     +0.0016
SUM                   5.3481      5.0499     -0.2982
```

**Cause.** The sampler coupled the clean sheet to the team-goals draw at `opp_lambda`. That is
right at steps 1–5 and WRONG at step 0:

```
p_cs vs exp(-opp_lambda), regular-starting GK/DEF, by horizon step
   step 0 (gw5) : mean diff -0.0006  sd 0.0211  max|d| 0.0782
   steps 1-5    : max |d| = 0.000000   (n = 370)
```

At steps 1–5 there are no odds, so the lambda and the clean-sheet lambda both collapse to pure
Dixon-Coles and are identical. **At step 0 they are different quantities**: `opp_lambda` is the
pure-market lambda (`LAM_BLEND_W = 0`) while `p_cs = exp(-cs_lambda)` with
`cs_lambda = 0.2·DC + 0.8·market` (`CS_BLEND_W = 0.2`). For that row the 0.0822 probability gap
× 4 pts × `p_60plus` ≈ 0.296 — the whole residual.

My earlier "p_cs equals exp(-opp_lambda) exactly on every row" check was run on **GW6 only**,
which is step 1. It was true, and it did not generalise to the step the feature is mostly read
at. A check on one horizon step is not a check on the model.

**Fix.** Draw team goals at `cs_lambda = -ln(p_cs)`, not `opp_lambda`. Then `P(clean sheet)` is
`p_cs` by construction, the clean-sheet term reconciles exactly, and conceded inherits a rate
that differs from `opp_lambda` by ~0.2% at step 0 and not at all at steps 1–5 — a negligible
error on a term worth ~0.19 points, traded for an exact one on a term worth up to 4.

```
team goals ~ Poisson(opp_lambda)  [original] : mean 0.0137  p95 0.0516  max 0.3265
team goals ~ Poisson(-ln p_cs)    [corrected]: mean 0.0128  p95 0.0505  max 0.1060
```

**Max residual 0.3265 → 0.1060.** What remains is consistent with the structural term; the
pathological outlier is gone. The model was never wrong here — `pts_cs == p_cs · CS_PTS ·
p_60plus` holds to 0.000000 on every row. **No model-path question arises.**

## R4. The minutes shape is a NEW ASSUMPTION: named MS-1, versioned, and measured

The frame carries the **mean** of the minutes distribution (`e_minutes`) and three
probabilities, but **not its shape**. Sampling minutes requires an assumption the model does not
contain. It is named rather than buried:

> **MS-1** — minutes 85 / 35 / 20 for started-and-60+, started-and-withdrawn, and substitute,
> scaled per row so the mean reproduces `e_minutes` exactly. Carried as
> `minutes_shape_version` alongside `quantile_method_version`, so it can be varied and
> compared.

**"Nothing new is modelled" is therefore NOT true of the minutes draw, and is not claimed.** It
holds for every other component.

Sensitivity, two alternative shapes, corrected sampler, N = 20,000:

| shape | resid mean | P10 mean\|d\| | P50 mean\|d\| | P90 mean\|d\| | P90 rows changed |
|---|---|---|---|---|---|
| **MS-1** 85/35/20 | 0.0128 | — | — | — | baseline |
| MS-2 80/30/15 | 0.0130 | 0.0023 | 0.0054 | **0.0252** | **2.6%** |
| MS-3 88/45/25 | 0.0128 | 0.0028 | 0.0064 | **0.0242** | **2.5%** |

The **reconciliation is insensitive** to the shape — by construction, since the per-row scaling
forces the mean to match. The **quantiles are not**, and the sensitivity is concentrated exactly
where it hurts:

* P10 moves on 0.2–0.3% of rows, P50 on 0.6–0.7%;
* **P90 moves on ~2.5% of rows, by up to 2 whole points on the worst.**

**So P90 is now fragile in three independent ways**: bonus-at-zero and the penalty term bias it
low (§4), and the one assumption the model forced us to invent moves it on 2.5% of rows. The
quantile that carries all the new information is the least trustworthy number the feature
produces. That strengthens §4's finding rather than softening it.

Tolerable at this size, and the reason to version it: MS-1 is a decision that can be revisited
against realised minutes, and a stamped version makes old and new rows comparable instead of
silently different.

## Still open before building

* the two-part reconciliation check (R1) needs its structural half specified in code;
* MS-1 wants a check against realised minutes distributions when there is a season of them.

---

# Built (2026-09-18)

`quantiles.py` (pure, imports no part of the model stack -- the explain.py precedent),
`db_write.py` (12 nullable columns, `ADD COLUMN IF NOT EXISTS`), `eval/run_live_deadline.py`
(post-build hook, off for t10, seed recorded in the knowledge block), `model_tools.py`
(`get_prediction` returns the quantile block and the fidelity block),
`prompts/system_prompt.md` (the reporting contract), `Tests/test_quantiles.py`.

**The model path is untouched.** The simulation reads the assembled frame and adds columns;
`e_points` is unchanged. Parity proven, not asserted -- see the suite record below.

**Both halves of the reconciliation are in code.** `q_resid_sampling` is judged against
`q_tolerance = max(0.02, 3*sd/sqrt(N))`; `q_resid_structural` is stored as a value and
`quantiles.reconciles()` deliberately does not look at it. The structural half is obtained from
the SAME draws by redrawing only the two floor terms at the pinned rate, so it costs two extra
draws on GK/DEF rows rather than a second full simulation, and it is identically zero for MID
and FWD.

**The fidelity block names all three fragilities of P90** -- bonus at zero, the penalty term,
and MS-1's sensitivity -- and carries `p90_is_weaker_than_p50: true`. The prompt forbids
presenting P90 as comparable in quality to P50, forbids adding the two residuals together, and
requires saying "not computed" rather than nothing when a run skipped them.

## Open item, dated: MS-1 against realised minutes

**2026-09-18 -- OPEN.** MS-1 (85 / 35 / 20) is an assumption the model does not contain. It is
scaled per row so the mean reproduces `e_minutes` exactly, which is why the reconciliation is
insensitive to it, and it is versioned as `minutes_shape_version` so it can be varied. What it
has NOT been is validated against reality: nobody has compared it to the realised distribution
of minutes for started-and-60+, started-and-withdrawn and substitute appearances.

**Not blocking, and deliberately not blocked on.** 2026-27 is five gameweeks old, so there is
no season of realised minutes to validate against yet, and waiting would hold a specified
feature behind data that does not exist. The sensitivity is bounded and measured: P90 moves on
~2.5% of rows across the three shapes, P10 and P50 on under 1%.

**Revisit when a season of 2026-27 minutes exists** (or against an archive season, which is the
cheaper test and could be done sooner). The check is: fit the three within-state means from
realised minutes, compare to 85/35/20, and if they differ materially, add the fitted shape as
MS-4 and re-measure the P90 movement rather than silently replacing MS-1 -- the version stamp
exists so old and new rows stay comparable.

---

# Incident (2026-09-18 23:09Z - 23:4xZ): every prediction call failed. A read that depended on a write.

**What broke.** From the quantiles deploy at 23:09:40Z, `get_prediction` raised
`UndefinedColumn: column "q_p10" does not exist` on every call. The agent could not answer a
prediction question at all.

**Why.** The twelve quantile columns are added by `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
inside `db_write.ensure_schema`, and **only the write paths call it -- no read does.** The last
write was run 15 at 17:21:29Z, nearly six hours before the deploy; the next was days away,
because the nightly is gated until GW5 is confirmed. So the migration had never executed, while
the widened `SELECT` naming those columns went live immediately. Confirmed by
`information_schema`: `present 0/12`, table at 40 columns.

**It was not a NULL-handling bug.** Tested in isolation the same evening, `_quantile_block` on
rows whose twelve values are all `None` returns `computed: false` with the "not computed"
explanation. The nullable design was sound; the SEQUENCING was not.

**Fixed, in two steps.** `ensure_schema` run against the live database (12/12 present, nullable,
no defaults, 52 columns, zero rows with a non-null `q_p50`), then `get_prediction` called
directly -- run 15 reads `computed: false`, and `compare_players`, `compare_predictions` and
`get_picks` are unaffected.

**The durable fix is on the READ side, deliberately** (user decision): optional columns are
selected only when the live schema has them, via a 60-second-TTL introspection cache that picks
up a migration without restarting the API. Making migrations stricter would have left the same
fragility for the next column added. A read must never depend on a write having happened.

## What made it possible, and the rule it produced

The live verification an hour earlier ran **`quantiles.add_quantiles` over the frame** and
reported 24.9 s, 3,954 rows and a clean structural distribution. All true, and all about the
computation. **`get_prediction` -- the only path the agent uses -- was never called once.**

That is the second time in two days: on 2026-09-17 a cookie jar proved every endpoint answered
while the browser UI rendered `undefined`, because curl never executes the page's JavaScript.
Both verifications were real, measured, and aimed one layer below the failure, which is exactly
what made them convincing and useless.

Recorded as a standing rule in section 14 of the Squad State handoff: **verify the path the user
touches, not the path you were thinking about.**

## The test that was missing

`test_a_run_that_skipped_quantiles_writes_NULL_not_ZERO` proved the WRITE emits `None` when the
FRAME lacks the columns. Nothing proved the READ survives a DATABASE that has never seen them --
a different direction entirely. Now covered by five tests, including one that drives
`get_prediction` end to end against a simulated pre-migration schema and asserts the generated
SQL names no column the schema lacks.

---

# Runaway fixtures reach the quantiles (2026-09-18)

## The question, and the measurement that answered it

Asked: *does the quantile block inherit the model-degraded condition — a P90 for a player facing
Coventry at steps 1-5 is built on lambda 0.0006 — the way `explain_prediction` flags it?*

Measured on the live frame before changing anything. **No.**

| | |
|---|---|
| Rows whose fixture has a lambda outside [0.15, 6.0] | **338 of 3,954** |
| By gameweek (gw6-10) | 67 / 77 / 65 / 67 / 62 |
| Own attack ran off / opponent's attack ran off | 185 / 153 |
| Terms `fidelity()` mentioned: runaway, lambda, #25, Coventry, degraded, extreme | **none of the six** |
| `explain_prediction` on the same row | full note, KNOWN_ISSUES #25 named |

What it does to the numbers:

- **Malick Thiaw** (Newcastle DEF, GW6, facing Coventry): `p_cs 0.9994` → **P10/P50/P90 = 5/6/12**.
  A near-certain clean sheet, sampled 20,000 times as though it were real.
- **Coventry forwards**, GW6: `e_goals 0.0004` → **P90 = 1**. The ceiling of a Premier League
  forward, from a strength that never converged.

## The finding: reusing a module's vocabulary is not reusing its detection

`quantiles.py` imported `CONSTANT_LABELS`, `CS_PTS`, `GOAL_PTS` and `PEN_FALLBACK` from
`explain.py`. It shared the scoring constants and the fixed label set, and the fidelity block was
written deliberately "in explain_prediction's fixed vocabulary". The import list made it look
like one source of truth. **The bound check was not in it**, because it was never exported —
`fixture_runaway` did not exist, the test lived inline inside `breakdown()`. So the two modules
said different things about the same row, and the quieter one was the one the agent quotes when
someone asks whether a pick is safe.

This is the **fourth** instance of the §14 pattern, after:

1. *Alerting on a health endpoint only alarms on states that endpoint can represent* — the probe
   inherited the blind spots of the thing it probed.
2. *"Fixed" and "deployed" are different words* — the verified artefact was not the served one.
3. *Verify the path the USER touches, not the path you were thinking about* — `add_quantiles`
   measured clean over the frame while `get_prediction` raised on every call.

Each time the check was real and aimed one step to the side of the thing that was broken. Here
the sideways step was **an import list that carried the words and not the test**. A shared
vocabulary is evidence of nothing: it makes two modules describe the same world in the same
terms, which is precisely what disguises them disagreeing about the facts. Rule: *when two
modules must agree about a condition, export the PREDICATE, not the sentence.*

## What was built

- `explain.py` — `LAMBDA_MIN/LAMBDA_MAX`, `RUNAWAY_NOTE`, `fixture_runaway(row)` and
  `runaway_side(row)` factored out of `breakdown()`, which now calls them. `RUNAWAY_NOTE` is
  byte-identical to the sentence `breakdown()` emitted before, so explain's output is unchanged
  (its 15 tests pass untouched).
  `runaway_side()` returns `club=None` for the opponent **on purpose**: the frame carries the
  player's own club and not their opponent's, and pairing clubs by matching lambdas is the
  recorded mis-pairing trap. The side is described, never guessed.
- `quantiles.fidelity()` — calls `fixture_runaway`, adds a **fourth fragility** naming the club
  and its lambda with the #25 reference, in explain's words.
- `model_tools._quantile_block()` — `runaway`, `p10_unusable` and `runaway_sides` on **every
  `per_gw` entry**, because a horizon usually mixes affected and clean fixtures and one
  answer-level flag would either condemn the clean gameweeks or excuse the broken one.
- `prompts/system_prompt.md` — one rule, in the quantiles section.

## P10 is the number this corrupts, and it outranks the P90 caveat

The first three fragilities all understate a **ceiling**. This one fabricates a **floor**, and
they are not symmetric: an understated ceiling makes a reader miss an opportunity, but a floor is
what a reader trusts when deciding a pick is **safe**, so a manufactured one makes them take a
risk they were told did not exist. `fidelity()` therefore gives P10 its own caveat — the only
term-level caveat besides P90's — and the prompt requires it *before* the floor is quoted, not
after.

## Which row speaks for the answer

It was `max(abs(q_resid_sampling))`. That was arbitrary: sampling noise is the one part of this
that is bounded, tolerance-checked and reported per row already, so the noisiest row is not the
most fragile one — in the mixed horizon used as a test case the noisiest row is a **clean** one.
Now: the earliest gameweek that **has** the condition, falling back to the earliest gameweek when
none does. Deterministic in both branches, and independent of row order. When only some
gameweeks are affected the caveat prefixes itself with the gameweeks it is true of
(`Applies to GW6, GW8 only, not the whole horizon`), and `fidelity.runaway_gws` carries the list.

## Tests

`Tests/test_quantile_runaway.py`, 19 tests in four groups: the detection is shared (including one
that monkeypatches `explain.LAMBDA_MIN` and asserts the quantile flag follows — a second copy of
the bound fails it), `fidelity()` flags the row in explain's exact words, the answer-level block
comes from the affected rows and is scoped and order-independent, and the prompt carries the
rule.

## Not closed by this

This makes the defect **visible**; it does not fix it. KNOWN_ISSUES #25 stays open, and the
cold-start work (v2 hinge+box, v3 promoted-club centre, both MARGINAL) is still the place a fix
would come from. What changed is that a reader can no longer be handed a 99.94% clean sheet with
nothing said. Note the **third** consequence of #25 now on the record, after the degraded-run
detector and the hold-vs-move bias: it manufactures confident floors in the quantile answer.

## The same pattern, one step further in: the flag would have been DEAD ON ARRIVAL

Caught during the build, before deploy, and worth recording because it is the §14 pattern
applied to the fix for the §14 pattern.

`fidelity()` was correct. `_quantile_block()` was correct. Nineteen tests passed. And
`get_prediction` would have reported `runaway: false` on all 338 affected rows — because its
`SELECT` names neither `team_lambda` nor `opp_lambda`. `PRED_BASE_COLS` and `PRED_OPTIONAL_COLS`
were built for the quantile read and carry no model internals, so `fixture_runaway(r)` would have
seen two missing columns, read them as NaN, and answered **False** on every live row.

That is worse than not having built it. An absent flag is silence; a flag that cannot see its own
input reads as **"checked, and fine."** The unit tests could not catch it: they construct rows
with the lambdas present, which is the shape the function is designed for and not the shape the
live read produces.

Fixed on the read side, consistent with the 2026-09-18 incident rule: `team_lambda` and
`opp_lambda` join `PRED_OPTIONAL_COLS` (selected only when the live schema has them) and are
listed in `PRED_INTERNAL_COLS`, which strips them from the `predictions` payload — they are
**inputs to a flag, not outputs**, and a raw strength parameter printed beside `e_points` invites
the agent to quote it as a prediction.

The club needed the same treatment. `model_predictions` does not carry `team`, and pairing clubs
by matching lambdas is the recorded mis-pairing trap, so it comes from one guarded `players_live`
lookup: if it fails the club is simply not named (`"this player's own club at lambda 0.0006"`) and
the prediction is unaffected. `explain.runaway_side` now returns `club=None` rather than
`str(None)` when the frame has no club — a caller that prints the club must be able to tell "not
known" from a name, or it prints the placeholder, which a test caught as the literal string
`"None (own team) at lambda 0.0006"`.

Four further tests cover it, including one asserting the lambdas are selected, one asserting they
are stripped from `predictions`, and one that makes the club lookup raise and requires the
prediction to survive with the flag still set.

**Generalised: check that a new signal can SEE its inputs on the live read path, not only that it
computes correctly when handed them.** Three of the four §14 entries are now the same shape — the
verification was real, and aimed one layer to the side.

## Open item, dated: `squad/live_deadline.py:411` is a second copy of the bound
*(2026-09-19 UTC = 2026-09-18 20:xx local; same session as everything above it — this machine is UTC−4 and the log is headed by its local date.)*

Swept the repo for the box afterwards. `explain.py` now owns it for the read path, and
`quantiles.py` and `model_tools.py` both call `explain.fixture_runaway`. But
**`squad/live_deadline.py:411` declares its own `LAMBDA_MIN, LAMBDA_MAX = 0.15, 6.0`** for the
loud detector that writes `degraded_findings` at build time. The two agree today only because
the literals were typed twice.

Not merged here, deliberately. They are different granularities: the detector tests a whole
**fit's** lambda series per horizon step and names the club, while `fixture_runaway` tests **one
row's** two lambdas. Merging them means deciding which shape is primary, and `live_deadline.py`
is on the build path — a change there is not a by-the-way edit at the end of a feature.

**OPEN ITEM (2026-09-19 UTC): one bound, two declarations, and nothing fails if they drift.**

This is exactly what `test_quantiles_uses_explains_detection_and_not_a_second_copy` and
`test_moving_the_bound_moves_both` were written to prevent — and the second copy was already
there when they were written. The tests guard the two modules the feature touched; they say
nothing about the build path, so the defect the feature exists to stop is still live one file
over. Worth stating plainly rather than leaving implied: **a test that pins the modules you just
edited is not a test that pins the invariant.**

- **Fix:** `live_deadline.py` imports `LAMBDA_MIN`/`LAMBDA_MAX` from `explain.py` and keeps its
  own series-level logic and its own message. One declaration, two granularities.
- **Test that must come with it:** one asserting the build-time detector and
  `explain.fixture_runaway` classify the same lambda identically, driven off the shared
  constants so moving the box moves both — the existing monkeypatch test extended to a third
  caller.
- **Why not done here:** `squad/live_deadline.py` is on the build path. Changing it at the end of
  a read-path feature is the kind of by-the-way edit that lands untested in a deadline build, and
  the no-touch window rules exist for precisely that. It needs its own change, its own suite run
  and its own deploy.
- **Risk while open:** low today (the literals agree), unbounded on the day someone tunes one.
  Every consumer of the fit -- the degraded detector, the hold-vs-move refusal and now the
  quantile floor -- would then disagree about what counts as degraded.
