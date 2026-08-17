# Goalkeeper investigation — why did the two most GK-relevant terms make GK worse?

**Opened:** 2026-08-17 · **Status: OPEN** — three steps run (§§6–8: H3
weakened, H1 refined, unification tested and reverted). The D1 workstream is
CLOSED (`Logs/d1_log.md`); this investigation stays open on its own. §9 states
where it stands and the two live options.

---

## 1. The question

Saves and goals conceded are the two largest goalkeeper scoring components,
and the model was structurally blind to both until D1. Adding them:

- made GK margin calibration WORSE — pairwise β (through-origin, starter band,
  step 0, 2025-26) fell from **0.847 to 0.676**, with the two terms individually
  responsible (saves −0.101, conceded −0.126, sub-additive jointly);
- changed roughly **a third of #1 goalkeeper picks** (same-#1 agreement 63–68%
  across all three seasons, union-of-top-k predicted-order ρ only 0.51–0.54 —
  the lowest of any position by a wide margin);
- and no measurement so far can say whether the NEW ordering is better or worse
  against reality (4 of 168 paired top-k comparisons resolve, ~chance rate).

Terms that make the prediction MORE informed should not make its pairwise
margins LESS calibrated. Either the terms are wrong in a way not yet
identified, or the baseline's GK calibration was good by accident. Nobody
currently knows which.

## 2. Evidence assembled so far (all from the D1 work, 2026-08-14 → 08-17)

**Verified before/after (identical provenance, step 0, starter band):**

| quantity | baseline | with saves+conceded (Variant B) |
|---|---|---|
| GK margin β, 2025-26 | 0.847 | 0.676 |
| GK starter Spearman, 2025-26 | 0.203 | 0.191 |

**Term-by-term decomposition** (exact per-row reconstruction, identity check
2e-16, `d1_term_decomposition.py` + `d1_variants_ab.py` in the 2026-08-17
session scratchpad; results reproduced in `Logs/d1_log.md` §3):

| term | GK β delta (alone) | GK starter mean (SD) | corr w/ actual |
|---|---|---|---|
| saves | −0.101 | +0.490 (0.289) | ~+0.09 |
| conceded | −0.126 | −0.388 (0.201) | ~0 |
| cards (per-player, since removed) | −0.419 | −0.132 (0.722) | ~−0.13 |
| penalty share | 0.000 | 0.000 (0.000) | n/a |

Saves and conceded PARTIALLY CANCEL per-row (one positive, one negative), and
their joint β damage (−0.171) is smaller than the sum of their separate damage
(−0.227). The cards defect was fixed by Variant B; the saves+conceded effect
remains and is what this investigation is about.

**Cross-season GK state (Variant B build, step 0, starter band):**

| season | GK Spearman | GK β |
|---|---|---|
| 2025-26 | 0.191 | 0.676 |
| 2024-25 | 0.133 | 0.491 |
| 2023-24 | 0.204 | 0.479 |

(Baseline β for 2024-25/2023-24 was measured in step 1 — see §6.)

**The recurring negative: 2024-25 GK, two appearances, not conclusive:**
1. Top-k watch item (`d1_log.md` §8): 2024-25 GK top-k realised points, two of
   the three resolved-by-chance-rate cells (−0.36 at k=5 all-pool, −0.58 at
   k=1 started).
2. Agreement measurement (§10): 2024-25 all-pool GK k=5 hindsight overlap
   −0.26, the only GK cell to resolve.
A third independent appearance should be treated as a pattern.

**Also relevant:** the bonus BPS input change shipped with D1 (predicted
saves/conceded/cards now fed instead of zeros) — its measured e_points effect
was small (GK starter mean +0.013, max 0.21) but it acts on GK/DEF
specifically and has never been isolated from the scoring terms in any β
measurement.

## 3. Hypotheses raised and NOT ruled out

**H1 — opp_lambda double-counts information already in p_cs for goalkeepers.**
The conceded term uses `opp_lambda` (market-implied expected goals against);
p_cs (clean-sheet probability) is derived from the same market information and
already carries 4 × p_cs × p_60plus for a GK. A goalkeeper facing a weak
attack is now rewarded twice (higher p_cs AND lower conceded deduction), and
one facing a strong attack punished twice — stretching predicted GK margins
beyond what realised margins support, which is exactly what β < 1 measures.

**H2 — the saves rolling rate carries minutes noise.**
`saves_per_90` is built as `saves / (minutes + 1) * 90` per gameweek, then
rolled over 5 gameweeks. Short appearances distort the per-90 rate; the +1
denominator biases it; and the rolling mean of ratios is not the ratio of
rolling sums. The term's correlation with actual points is positive (~+0.09)
but its week-to-week variance may still widen predicted margins more than the
signal justifies.

**H3 — the baseline margin was accidentally well-scaled through compensating
errors.** The baseline was blind to saves (which ADD GK points) and to
conceded (which SUBTRACTS them). For the typical starting GK these blindnesses
partially cancel in the LEVEL, and may also have cancelled in the SPREAD —
producing β ≈ 0.85 by luck rather than by correctness. Under this hypothesis
D1 did not break a calibrated margin; it removed one of two offsetting errors
and exposed the other. The 2024-25/2023-24 baseline β measurements (not yet
run) discriminate this: if baseline GK β is also ~0.85 there, accident is less
plausible; if it varies widely, more plausible.

## 4. What this file is not

No investigation has been run. No hypothesis has been tested. Nothing here is
a finding. The adoption of Variant B stands on the record in `Logs/d1_log.md`;
this workstream exists because §6 of that log must not quietly become
accepted background.

## 5. Pointers

- `Logs/d1_log.md` — §3 (decomposition), §6 (open question), §8 (watch item),
  §10 (agreement/convergence)
- KNOWN_ISSUES #13 — the contamination incident; which files are trustworthy
- Verified artefacts: `data/walkforward_h6_2526_baseline.parquet` (no D1),
  `data/walkforward_h6_2025_26_d1cards.parquet` (per-player cards),
  `data/walkforward_h6_{2025_26,2024_25,2023_24}.parquet` (Variant B,
  `d1_terms_active=True` stamped)
- Measurement scripts from the 2026-08-17 session scratchpad:
  `d1_clean_measure.py`, `d1_term_decomposition.py`, `d1_variants_ab.py`,
  `d1_topk.py`, `d1_agreement.py` (scratchpads are session-temporary — copy
  into the repo if the methodology needs to be rerun exactly)

## 6. Step 1 (2026-08-17) — H3 test: three-season baseline β

> **CORRECTED by step 2 (§7), same day.** The 2023-24 baseline GK β of 0.560
> below was substantially an artefact of ~36 starter rows with missing market
> inputs (null p_cs/opp_lambda). On market-complete rows the three baselines
> are **0.847 / 0.760 / 0.834** — stable near 0.8, not the wide range this
> entry reads from. **The H3-STRENGTHENED conclusion below is therefore
> materially weakened; H1 is now the stronger explanation** (see §7). The
> entry is kept as written because the sign-consistency observation and the
> per-position table remain valid; only the season-volatility reading was
> driven by the artefact.

**Measured:** baseline (no-D1) margin β for 2024-25 and 2023-24 on the same
methodology as 2025-26 (step 0, starter band, through-origin). Provenance
verified: all three baseline files D1-free, stamps identical to the B builds.

| season | pos | β baseline | β Variant B | Δ |
|---|---|---|---|---|
| 2025-26 | GK | 0.847 | 0.676 | −0.171 |
| 2024-25 | GK | 0.760 | 0.491 | −0.269 |
| 2023-24 | GK | 0.833 | 0.622 | −0.211 |
| ~~2023-24~~ | ~~GK~~ | ~~0.560~~ | ~~0.479~~ | ~~−0.081~~ |
| 2025-26 | DEF | 1.074 | 0.988 | −0.087 |
| 2024-25 | DEF | 1.019 | 0.900 | −0.120 |
| 2023-24 | DEF | 1.100 | 1.064 | −0.036 |
| ~~2023-24~~ | ~~DEF~~ | ~~0.794~~ | ~~0.870~~ | ~~**+0.076**~~ |
| 2025-26 | MID | 0.720 | 0.724 | +0.003 |
| 2024-25 | MID | 1.106 | 1.123 | +0.017 |
| 2023-24 | MID | 0.957 | 0.967 | +0.010 |
| ~~2023-24~~ | ~~MID~~ | ~~0.776~~ | ~~0.791~~ | ~~+0.015~~ |
| 2025-26 | FWD | 0.623 | 0.632 | +0.009 |
| 2024-25 | FWD | 0.498 | 0.489 | −0.009 |
| 2023-24 | FWD | 0.492 | 0.492 | −0.000 |
| ~~2023-24~~ | ~~FWD~~ | ~~0.493~~ | ~~0.485~~ | ~~−0.008~~ |

**2023-24 rows corrected 2026-08-17** after the Sheffield United join-failure
fix (KNOWN_ISSUES #14): the original build forced e_points to 0.0 for every
Sheffield Utd row (1,429 step-0 rows). Struck-through rows are the superseded
measurements, kept visible. The corrected 2023-24 baseline GK β (0.833)
matches the market-complete estimate from step 2 (0.834) to 0.001,
independently confirming the §7 correction.

**H3 reading (criterion stated before measuring): H3 STRENGTHENED.**
Baseline GK β varies 0.560–0.847 across seasons — there was no stable,
calibrated baseline GK margin for D1 to break. The 2023-24 baseline, with no
D1 at all, was already worse-scaled (0.560) than 2025-26 WITH D1 (0.676). The
0.847 that framed "D1 broke a calibrated margin" is the top of a wide range,
not a property the baseline possessed.

**Baseline β is season-volatile at every position**, not just GK: DEF spans
0.794–1.074 (crossing 1.0), MID 0.720–1.106, FWD 0.493–0.623. Position-level β
at 38 gameweeks is a noisy quantity; single-season values should not be read
as model properties. (This also retroactively contextualises §1's framing.)

**What keeps H1/H2 alive:** D1's GK β delta is sign-consistent three-for-three
(corrected: −0.211 / −0.269 / −0.171; was ~~−0.081 / −0.269 / −0.171~~) while
MID moves positive three-for-three. A systematic GK-specific stretch from
saves+conceded remains on the table even though the baseline level argument
now favours H3. ~~In 2023-24 D1 IMPROVED DEF β — the DEF sign is not
season-stable.~~ **Superseded by the #14 correction:** on corrected data DEF
degrades in all three seasons (−0.087 / −0.120 / −0.036) — the DEF sign IS
season-stable, and the GK deltas are now also uniform in size. Both facts
sharpen the case that saves+conceded apply a systematic stretch wherever they
act, GK hardest.

2024-25 GK again shows the largest degradation (−0.269, plus the largest
Spearman drop −0.036) — consistent with its prior appearances, but this
measurement shares data with them: corroboration, NOT an independent third
appearance.

## 7. Step 2 (2026-08-17) -- H1 test: double-counting between p_cs and opp_lambda

**Measured:** correlation of the two inputs, variance overlap of the conceded
term with p_cs, and margin beta with the conceded term rebuilt from opp_lambda
RESIDUALISED against p_cs (fit in-sample per season-position on the starter
band -- a DIAGNOSTIC of shared information, not a deployable fix). All betas
on matched populations (rows with complete market inputs).

| season | pos | corr(p_cs, opp_lambda) | R2 conceded~p_cs | beta base | beta B | beta resid | recovery |
|---|---|---|---|---|---|---|---|
| 2025-26 | GK | -0.954 | 0.770 | 0.847 | 0.676 | 0.799 | 72% |
| 2024-25 | GK | -0.931 | 0.779 | 0.760 | 0.491 | 0.574 | 31% |
| 2023-24 | GK | -0.933 | 0.717 | 0.834 | 0.639 | 0.724 | 44% |
| 2025-26 | DEF | -0.954 | 0.760 | 1.074 | 0.988 | 1.167 | 207% (overshoot) |
| 2024-25 | DEF | -0.935 | 0.771 | 1.019 | 0.900 | 1.105 | 172% (overshoot) |
| 2023-24 | DEF | -0.934 | 0.711 | 1.087 | 1.054 | 1.240 | 558% (overshoot) |

**H1 SUPPORTED for GK.** p_cs and opp_lambda correlate at -0.93 to -0.95 --
close to the same variable -- and p_cs alone explains 71-78% of the conceded
term's variance: the conceded term is roughly three-quarters redundant with
information the equation already carried. Residualising recovers 31% / 44% /
72% of the GK beta loss, three-for-three in the predicted direction.

**DEF overshoots**: residualising pushes DEF beta past baseline into beta > 1
(1.10-1.24, margins now UNDERSTATED). Double-counting is real at both
positions, but simple residualisation is the wrong correction for DEF --
plausibly because DEF's clean-sheet term (4 pts) is large relative to its
conceded exposure. Any fix must treat the two positions differently.

**Correction to step 1 (see banner in section 6):** matching populations exposed
~36 GK / ~134 DEF starter rows in 2023-24 with null p_cs/opp_lambda that had
dragged the 2023-24 baseline beta down (GK 0.560 -> 0.834 without them). On
market-complete rows the three baseline GK betas are 0.847 / 0.760 / 0.834 --
stable near 0.8. **H3 is materially weakened; H1 is now the stronger
explanation**: a stable ~0.8 baseline plus a mechanism-confirmed three-for-three
partial recovery fits "the conceded term double-counts clean-sheet information"
far better than "the baseline was accidentally calibrated."

**Open side-finding:** the null-market-input rows themselves (which fixtures,
why odds are missing, what fills the equation there, whether any beta
measurement should include them) are unexplained as of this entry.

## 8. Step 3 (2026-08-17) -- CS/conceded unification: a clean NEGATIVE, reverted

**Built and tested:** pts_cs derived from exp(-opp_lambda) -- the same pure-
market distribution the conceded term uses -- replacing the separately-blended
p_cs (0.2 Dixon-Coles). Motivated by H1's double-count finding. Gated as
`CS_UNIFIED` in assembly.py, stamped as `cs_unified`, measured before/after on
all three seasons (step 0, starter band), then REVERTED.

**The pre-stated test and its failure.** The test, fixed before measuring:
does GK beta recover toward its no-D1 baseline (~0.85) without DEF
overshooting past 1.0? It failed on the half that mattered -- GK beta moved
FURTHER from baseline in all three seasons (-0.024 / -0.005 / -0.013; e.g.
2025-26: 0.676 -> 0.652 against baseline 0.847). DEF did not overshoot, but
that half was moot since the recovery it guarded against never happened.

**CS Brier worsened everywhere:** +0.0011 to +0.0016 across all three seasons
and both positions -- 2-3x larger than the 0.0005 tuning margin implied. The
"top of a flat region" turned out to have a real, if small, slope.

**The mechanism lesson.** H1's diagnostic RESIDUALISED the conceded term
against p_cs -- it removed the shared information from one of the two terms,
and beta recovered (31%/44%/72%). Unification is the OPPOSITE operation: it
makes the two terms perfectly redundant instead of 94% redundant, so the same
signal enters the margin twice, exactly. Beta ticked down three-for-three,
as this mechanism predicts. **Unification is the wrong operation for a
double-count.**

**H1 refined, not confirmed.** The beta stretch is not a disagreement
artifact between two differently-blended inputs -- eliminating the
disagreement made nothing better. It looks like the market-lambda spread
across goalkeepers is genuinely wider than realised margins resolve.

**The two live options, for whoever picks this up:**
1. Shrink the lambda spread feeding the GK/DEF defensive terms (a calibration
   of the input distribution, not a deletion of a term), or
2. Accept beta < 1 as the honest price of rule-faithful terms.
Both clean-sheet points and the conceded deduction are real FPL rules driven
by the same true goals-against distribution; a rule-faithful equation cannot
simply delete one of them. Any fix must act on the input, not the rules.

**Blend decision recorded:** the 0.2 CS blend is RETAINED. Its original
justification (0.0005 Brier margin on 380 matches) was weak; the unification
test is now the real reason -- removing it measurably worsened Brier and
margin calibration together. CS_UNIFIED stays False unless this negative is
re-litigated with new evidence.

**Revert verified:** canonical files restored byte-identical to the preserved
pre-unification artefacts (md5-equal; beta and Spearman reproduce the
"before" measurements to 4 decimals; 105 tests pass). The unified builds are
preserved as data/walkforward_h6_*_csunified.parquet so this negative stays
checkable. Measurement scripts: measure_cs_unify.py, cs_lambda_consistency.py
(2026-08-17 session scratchpad).

## 9. Status at D1 close (2026-08-17) -- OPEN, with two live options

D1 is closed and adopted as Variant B; this investigation remains open. Where
it stands: H3 (accidental baseline calibration) weakened by the corrected
stable baselines (0.847 / 0.760 / 0.833); H2 (saves minutes noise) untested;
H1 refined by steps 2-3 into a calibration question -- the market-lambda
spread across goalkeepers appears genuinely wider than realised margins
resolve, and the redundancy between the CS and conceded terms is a property
of the rules, not a fixable input disagreement.

**The two live options:**

1. **Shrink the lambda spread** feeding the GK/DEF defensive terms -- a
   calibration of the input distribution, not a deletion of a term.
   **Constraint: this introduces a NEW TUNABLE PARAMETER that cannot be
   validated on 2025-26, which is the sealed test season.** Any shrink factor
   must be tuned on 2024-25 and/or 2023-24 (leave-one-season-out per the M2
   discipline) and applied to 2025-26 exactly once, pre-registered. Tuning it
   against 2025-26 beta would be fishing in the sealed season.
2. **Accept beta < 1 as the honest price of rule-faithful terms.** Both
   clean-sheet points and the conceded deduction are real FPL rules driven by
   the same true goals-against distribution; a rule-faithful equation cannot
   delete one. Under this option the beta record stands as the measured cost
   and the optimizer's hit bar carries the consequence, not the equation.

Step 3 (§8) rules out the third path that looked available: unifying the two
terms' inputs. It made every metric slightly worse and is recorded as a clean
negative.
