# Availability signal — extraction, override test, feature test

> ## ⚠ SUPERSEDED BASELINE — figures below are NOT comparable to current builds
>
> **Added 2026-08-14.** Every number in this log predates three changes that each
> moved the prediction surface it was measured on. The numbers are left in place
> deliberately — they are the record of what was believed at the time — but they
> must not be compared against anything built after 2026-08-14.
>
> **1. Baseline migration (M3).** The canonical walk-forward file was rebuilt with
> `availability=True`. It had been `availability=False`. Horizon-0 Spearman moved
> 0.715 → 0.745, MAE 1.15 → 1.11. **Any figure quoting a season total of 1984 is on
> the pre-migration baseline.** The pre-migration artefact is preserved as
> `data/walkforward_h6_2526_prefix.parquet` and still reproduces 1984 exactly, so
> these numbers remain checkable — they are stale, not lost.
>
> **2. Double-gameweek handling.** The master equation now runs per player-FIXTURE
> and sums, so a double carries both opponents. Previously three independent
> defects priced a double as a single fixture (minutes_frac capped at one fixture,
> the Dixon-Coles join kept an arbitrary fixture, the DC join took a max). Doubled
> players' predictions roughly doubled. **Any chip-timing or fixture-structure
> conclusion drawn before this is invalid**, because the planner could not see a
> double at all.
>
> **3. Odds horizon fixed at 0 (project decision, not a tunable).** Only the current
> gameweek's market is reliably published at a Friday deadline; reading odds for
> later gameweeks is a leak. Figures built at `ODDS_HORIZON_GWS = 2` are inflated
> relative to current builds — measured at roughly +39 points on one paired
> comparison. That drop is the removal of a leak, not a regression.
>
> Current canonical: `data/walkforward_h6_2526.parquet`, stamped
> `minutes_availability=True`, `odds_horizon_gws=0`, `dgw_handling='per_fixture'`.


Source: `fplcache/` (Randdalf/fplcache, Unlicense, gitignored). Built by
`eval/build_availability.py` -> `data/availability_{2122..2526}.parquet`.

## What the data is

FPL bootstrap-static cached 4x/day. For each gameweek we take the last snapshot
STRICTLY before the deadline. Gap: min 0.37h, median 4.33h, max 5.58h (2025-26);
no gameweek exceeds 6h in any of the five seasons.

**The blind window, and the fix.** Four snapshots a day means news breaking in the
last few hours before a deadline is invisible to the pre-deadline snapshot.
Gvardiol's GW1 injury was stamped 68 minutes after our snapshot and 3.5h BEFORE the
deadline — the project's flagship failure case is exactly the one the naive
extraction misses. `news_added` survives into later snapshots, so the first
post-deadline snapshot recovers the true deadline state without leaking: accept only
items stamped before the deadline. Those are the `asof_*` columns. 47 rows/season,
42 of them flipping `a` -> not-`a`. **Train and backtest on `asof_*`.**

Supersedes `core_insights_gameweek_stats.parquet` entirely (KNOWN_ISSUES #9): that
file has `news_added` 100% null and encodes null as 0.0 for GW2-10.

## Characterisation (2025-26)

| status | n | P(0 mins) | P(60+) |
|---|---|---|---|
| a | 19,363 | 0.432 | 0.390 |
| d | 1,039 | 0.688 | 0.165 |
| i | 2,150 | 0.990 | 0.002 |
| n / s / u | 196 / 151 / 6,337 | 1.000 | 0.000 |

- `u` is **100% departures** (6,442 of 6,442) — loan, permanent transfer, released.
  Not one injury. A permanent exclusion, structurally unlike i/d/s.
- `status` dominates `chance_of_playing`: `status='i'` with `cop=100` is 134 rows,
  all zero minutes. `cop_this_round` goes stale; `status` does not.
- `cop` null is NOT a low score — it means "no news on file" (P(0 mins) 0.570,
  between cop=50 and cop=75).

## Attempt 1 — hard override. FAILED.

Zero `e_points` for status in {i,s,n,u}, cop-scaled multiplier on `d`, applied to
the walk-forward file. 14 arms. **Not one beat baseline 1984**; range -11 to -128.

Why: it deletes information rather than adding it. And the exposure is tiny — the
baseline squad held a flagged-out player in only **27 of 570 squad-gameweek slots
(4.7%)**, worth 66 gross predicted points, most already recovered by autosubs. Only
14 flagged player-gameweeks all season rank top-30 by `e_points` in their own week.

The -50 was path divergence, not merit: zeroing four top-50 players at GW1 changed
the opening squad, and by GW6 the arms shared 8 of 15 players (baseline captained
Haaland 16, the arm captained Salah 2 — that one week was -42 of the -50).

The `d` sweep was non-monotone (0.00->-118, 0.25->-74, 0.50->-14, 0.75->-111,
1.00->-50): a smooth parameter producing a jagged response surface is noise.

`isn_only` was identical to `zeros_all` in every gameweek and `u_only` identical to
baseline for 35 of 38 — departures are inert, they were never going to be picked.

## Attempt 2 — availability as FEATURES. Minutes model improved; season did not.

Nine features: status code, cop this/next, cop-known flag, flag duration,
just-flagged, just-cleared, news age in days, departure flag. Availability built for
the training seasons too (2022-23..2024-25); join coverage 99.4-99.7% per season.

**ADOPTED 2026-08-13** into `squad/minutes.py` (`availability=True`, the default),
with the feature block in `squad/availability_features.py` and tests in
`Tests/test_availability_features.py`. `availability=False` reproduces the
pre-adoption model exactly, which is what `data/walkforward_h6_2526.parquet` and the
1984 baseline were built from. **Adopted on the minutes model's own merits. There is
no season-points claim attached to it.**

FOOTGUN: `minutes.py` now defaults to availability=True, so regenerating
`walkforward_h6_2526.parquet` would produce the availability predictions and move the
1984 reference to 1938. The canonical file has deliberately NOT been regenerated;
`walkforward_h6_2526_av.parquet` holds the availability version alongside it.

A defect the tests caught during adoption: the departure regex was tuned on 2025-26
and matched only 89% of `u` rows across the five seasons (earlier seasons say
"Permanent transfer to X", "Left the club by mutual consent", "Contract ended", and
there are typos like "Loaened to Derby County"). Fixed structurally rather than by a
better regex -- `is_departure()` anchors on `status == 'u'`, which is a departure by
construction, and uses text only to catch departures filed under other statuses.

### Minutes model — clear improvement

| metric | baseline | +availability |
|---|---|---|
| P(start) Brier | 0.0803 | **0.0710** (-11.6%) |
| P(start) AUC | 0.9491 | **0.9607** |
| P(start) log loss | 0.2577 | **0.2270** |
| P(60+ \| started) Brier | 0.0634 | 0.0634 (flat) |
| E[min] RMSE | 22.02 | **20.32** |
| E[min] MAE | 12.82 | **11.24** |
| E[min] Spearman | 0.7725 | **0.8017** |

AUC moving means DISCRIMINATION improved, not just calibration — something a pure
zero-deleter cannot do. P(60+|started) is flat, correctly: given a player starts,
availability adds nothing.

Where it lands:

| subset | n | Brier base->av | E[min] base->av | actual |
|---|---|---|---|---|
| first week flagged | 956 | 0.2397->0.0782 | 37.3->13.8 | 11.6 |
| just cleared | 783 | 0.1943->0.1528 | 27.1->42.9 | 43.1 |
| doubtful (d) | 1,069 | 0.1594->0.1174 | 26.4->19.5 | 17.2 |

**The `just cleared` row was not anticipated.** The model was UNDER-predicting
returning players by 16 minutes, because their recent history is all zeros. Only a
feature can fix that; an override can only push down.

Assembly, horizon step 0: Spearman 0.715 -> **0.745**, MAE 1.15 -> **1.11**.
Played (>0 min) 0.3375 -> 0.343; started 60+ 0.0992 -> **0.108**. The override moved
these last two by 0.0001 and 0.0000.

Revisions are correct in both directions: downward >0.5 (n=1,035) old 2.21 -> new
0.77 vs actual 0.52; upward >0.5 (n=989) old 1.92 -> new 2.75 vs actual 2.64.

### Season simulation — no gain

H=3, decay 0.3, balanced, bench 0.2, horizon_aware. Deterministic 3/3 both arms.

| arm | total | vs 1984 | GW1-7/gw | GW8+/gw | hits |
|---|---|---|---|---|---|
| baseline | 1984 | 0 | 43.00 | 54.29 | 20 |
| availability | 1938 | **-46** | 43.14 | 52.77 | 32 |

Paired bootstrap: -46, 95% CI [-123, +28], does NOT exclude zero, loses in 88.2% of
resampled seasons, -0.88x the ~52 path sd. **Not established in either direction.**

GW1-7 delta +1. Better in 16 gameweeks, worse in 21. Sum of |per-gw delta| is 334
to net -46 — 334 points of movement for no net gain, which is churn, not signal.
Squad overlap decays from 12/15 at GW1 to 4/15 late: the arms are different seasons.
Hits rose 20 -> 32; sharper predictions make the MIP pay to chase them.

## Conclusion

The minutes model is genuinely better and should be adopted on that basis. The
season total does not improve, and the instrument cannot resolve a difference this
size. Both statements are true at once and neither should be used to argue the other.

The binding constraint is not prediction quality. It is that the optimiser fields 15
of ~800 players, so a flagged player has to rank very high to cost anything — 27
slots, 66 gross points, most of it already handled by autosubs. **A better minutes
model cannot recover more than the thing is worth.**

Ablation (leave-one-out, on the sealed test season — diagnostic only, NOT used for
selection): `av_cop_next` and `av_news_age_days` carry the signal.
`av_cop_this_known` is never split on; `av_status_code` and `av_flag_duration` have
negative cost. The block is highly redundant, so leave-one-out understates all of
them; the whole-block effect is what matters.

## Open item — the instrument

Season totals cannot measure a change that perturbs the opening squad, because path
divergence (sd ~52) swamps it and `block_bootstrap` resamples within one realised
path per arm. Measuring this properly needs a path-controlled instrument: hold the
squad path fixed and vary only the decision under test. That is the blocker on every
question of this shape, not just this one.

---

# Path-controlled harness (Instrument A) — built, falsified, validated

`squad/pathcontrol.py`, `eval/falsify_pathcontrol.py`, `eval/validate_pathcontrol.py`.
Crossover windowed restart: both arms restarted from the SAME state at every anchor,
run freely for W gameweeks, discarded. W is a dial on admitted compounding.

## Falsification, 6/6 (run this before trusting any number)

| check | result |
|---|---|
| reproduces simulate_season | 1984 = 1984, every gameweek identical |
| self-replay identity | 5 anchors replayed exactly |
| null treatment (identical arms) | max \|delta\| = **0**, exactly |
| oracle (perfect foresight) | **+232.4** per 3-GW window, CI [+213.8, +251.0] |
| oracle wins nearly everywhere | 5 of 5 anchors |

Null returns exactly zero, so the harness cannot invent a difference. Oracle
(season 4775 vs 1984) still comes back huge, so removing path noise has not removed
the ability to see a real effect.

## A defect found in the SUMMARY, not the harness

First wildcard run reported +1.4 per window. The wildcard is active in one gameweek,
so 37 of 38 anchors were exactly tied and the mean over all anchors divided a +53
effect by 38. `summarise` now reports `n_active` and `mean_active_anchors` alongside
the all-anchor mean, and refuses to quote an interval below 8 active anchors -- a
block bootstrap of mostly zeros returns a lower bound of exactly 0, which looks like
a result and is not. Pinned by Tests/test_pathcontrol.py.

## Validation target 1 — availability (pervasive treatment)

| W | n_active | mean/window | CI | b better | a better | tied |
|---|---|---|---|---|---|---|
| 1 | 26 | **+0.289** | [-1.74, +2.57] | 13 | 13 | 12 |
| 2 | 35 | +0.230 | [-3.93, +4.49] | 20 | 15 | 2 |
| 3 | 35 | -1.181 | [-6.74, +4.77] | 17 | 18 | 1 |
| 5 | 34 | -6.971 | [-14.85, +1.32] | 11 | 23 | 0 |

Matches the prediction stated in advance: a small positive at W=1, nothing that
clears zero. **The harness did not manufacture significance.**

New finding the season total could not give: the effect degrades monotonically with
W. Individual decisions are neutral-to-slightly-positive; the damage is in
COMPOUNDING, which matches the measured churn (hits 20 -> 32). The -46 is not purely
a lottery artifact. No individual W clears zero, so the trend is suggestive only.

## Validation target 2 — wildcard GW4 (sparse treatment)

| W | n_active | mean over active anchors |
|---|---|---|
| 1 | 1 | **+53.0** |
| 2 | 2 | +61.0 |
| 3 | 3 | +62.7 |
| 5 | 4 | +69.5 |

**My stated prior was wrong and the comparison needs correcting.** +12.3 is the mean
across all 38 possible wildcard weeks; this ran GW4 specifically, which the wildcard
log records as one of the strongest (GW2-5: +72/+82/+71/+43 at W4). The right
comparison is +71, and W=5 gives +69.5. That is a good reproduction of the known
local effect.

## What the harness actually bought — honestly

**For sparse/local treatments: transformative.** The wildcard goes from "season
-26.2, indistinguishable from noise" to "+62.7 in its own three-week window",
isolated exactly. This is the case the instrument was built for and it works.

**For pervasive small-effect treatments: decomposition, but NOT power.** At W=1 the
per-anchor sd is 6.38 over 38 anchors, so the SE of the season-scale sum is ~39 and
the implied interval (+11 +/- 77) is no tighter than the season total's [-123, +28].
The binding variance is NOT the path lottery -- it is irreducible gameweek-to-gameweek
scoring variance, which survives sharing a starting squad. Forced-path separates
decision quality from compounding; it does not make a small effect measurable.

That boundary is the real result. Do not expect this harness to rescue marginal
model changes. It answers "is this decision better", cleanly, and it answers "where
does the season number come from" -- it does not lower the bar for a season claim.

## Still needs the full season

Chip timing policy, free-transfer banking, team-value growth, and horizon/decay
tuning -- all compounding by construction. A W=1 number for them is meaningless.

## Not built

Instrument B (prediction-perturbation outer loop, J draws, ~75 min at 3x parallel).
Given the finding above -- that intrinsic gameweek variance dominates at W=1 -- it
would help the season-scale (Q3) question specifically, where the path lottery IS a
major variance source. Still worth building for that, but it will not rescue Q1.
