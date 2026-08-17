# Instrument B — perturbation loop: built, falsified, and found NOT usable for

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

# arm-vs-arm prediction-quality comparisons

`squad/perturb.py`, `eval/measure_perturbation.py`, `eval/falsify_perturbation.py`,
`squad/degrade.py`, `eval/measure_degradation.py`. Tests: `Tests/test_perturb.py`.

## What it is

The simulator is deterministic, so replicates come from outside: jitter `e_points`,
both arms re-solve against the SAME draw (common random numbers), record the paired
difference. The spread over draws is an honest interval on the margin.

Falsified 6/6, including `null_treatment_is_zero` (identical arms -> delta exactly 0,
though the LEVEL moved -16, which is CRN working) and `eps_zero_reproduces` (exactly
1984/1938).

## The one thing it settled

**The path lottery, measured rather than assumed: sd(season total) = 60.0**, range
1828-2050 across 25 draws. The project's carried figure of ~52 was close but slightly
optimistic. Every single-run margin ever quoted here is one sample from a
distribution that wide.

**The -46 availability margin was never a measurement.** At eps=0.001 the jitter only
breaks exact ties and does not move the path; it returns -34.9 and the availability
arm gives the identical 1938 on all 8 draws. As soon as eps is large enough to sample
the branch structure the sign flips (+46.8, +32.2, +65.0 at eps 0.1/0.25/0.5).

## The thing it did NOT settle, and why the instrument is limited

Under perturbation availability led baseline by +32.2 (n=25, p=0.010). But the arm
that loses under perturbation is also the arm with more degenerate optima -- at
eps=0.001 baseline has sd 16.6 while availability has sd 0.0. So "1984 was a lucky
path" and "baseline is more noise-fragile" both predicted the observation.

**The degradation test.** Baseline predictions shrunk toward the positional mean by
lam, giving strictly worse models with strictly more ties. Tie-density verified
BEFORE running: players within 0.05 of the selection boundary go 3.63 -> 4.79 -> 5.92
-> 10.45, top-15 spread collapses 2.72 -> 0.55. The manipulation works.

Paired against baseline under the same draws (n=8 each):

| lam | unperturbed | perturbed mean | delta vs base | p | MDE(80%) |
|---|---|---|---|---|---|
| 0.00 | 1984 | 1906.2 | 0 | - | - |
| 0.25 | 1860 | 1904.1 | -2.1 | 0.938 | 74 |
| 0.50 | 1957 | 1945.6 | **+39.4** | 0.215 | 81 |
| 0.75 | 1858 | 1928.8 | +22.5 | 0.548 | 100 |

**A model with predictions shrunk HALFWAY to the positional mean shows +39.4 under
the same instrument that gave availability +32.2.** A model shrunk three quarters of
the way -- nearly a within-position random picker, top-15 spread 0.55 -- shows +22.5.
None of them differs significantly from baseline.

All four arms converge to a 42-point band (1904-1946) regardless of prediction
quality, and lift is almost perfectly explained by the unperturbed value alone:
**corr(unperturbed, lift) = -0.955**. That is regression to the mean, not a sharpness
effect.

## The conclusion, which is about the METRIC not about availability

**The season total cannot distinguish prediction quality across a very wide range.**
It cannot separate the full model from one shrunk 75% toward the positional mean.
Availability's +32.2 sits exactly at the instrument's minimum detectable effect at
n=25 (32.3; effect/MDE = 1.00), and a knowingly-worse arm produces a larger point
estimate. So +32.2 is NOT evidence the availability model wins on season points, just
as -46 was not evidence it loses. Neither number means anything.

Instrument B IS good for: measuring the path lottery, and demonstrating that a given
single-run figure is noise. It is NOT good for: arm-vs-arm comparisons of prediction
quality at any effect size this project has produced. More draws do not fix this --
the confound is that the response surface is flat, not that n is small.

## THE AVAILABILITY ADOPTION IS UNAFFECTED

Stated separately and deliberately. The adoption rests on minutes-model component
metrics measured on the sealed season, path-free and independent of everything above:

    P(start) AUC     0.9491 -> 0.9607        E[min] MAE   12.82 -> 11.24
    P(start) Brier   0.0803 -> 0.0710        E[min] RMSE  22.02 -> 20.32
    first-week-of-absence Brier  0.2397 -> 0.0782
    "just cleared" E[min] 27.1 -> 42.9 against 43.1 actual

None of those depend on a season total or on Instrument B. A future session must not
unpick the adoption because a season-level number moved; the season-level number is
exactly the thing shown here to be uninformative.

## Consequence for the queued cold-start work

The planned opening-squad 2x2 used season total as its endpoint. That endpoint cannot
distinguish lam=0.75 from lam=0, so it will not distinguish a better opening squad
either. **The cold-start experiment needs a different endpoint before it is worth
running** -- the path-free capture measure already computed (22.7% of best-available-15
in GW1-7 against 32.5% from GW8) is a candidate, as is Instrument A anchored near GW1.
