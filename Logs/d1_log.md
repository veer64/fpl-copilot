# D1 — the missing scoring terms. Adopted as Variant B (position-prior cards).

**Status: ADOPTED as Variant B — CLOSED 2026-08-17.** Final live config:
D1 terms active (`d1_terms_active=True`), cards as position priors (prior
seasons only, GKP folded in), `cs_unified=False` (the unification was tested
and reverted — GK investigation step 3), 0.2 clean-sheet blend retained,
`minutes_availability=True`, `odds_horizon_gws=0`, `dgw_handling=per_fixture`,
hit threshold 4, post-audit crosswalk with the Sheffield fix (KNOWN_ISSUES
#14). Closing metrics in §8 verified live on the canonical files at close;
the goalkeeper question remains OPEN in `Logs/gk_investigation_log.md`.

**Date:** 2026-08-17 · **Files:** `squad/assembly.py`
(equation), `eval/walkforward.py` + `eval/walkforward_season.py` (stamp),
`Tests/test_walkforward_provenance.py` (guard).

This log records an adoption that was nearly a reversion twice, and the
measurement failures that made it so. Read KNOWN_ISSUES #13 alongside it.

---

## 1. What D1 is

Four FPL scoring rules the master equation was structurally blind to:

1. **Saves** — +1 per 3 saves (GK only). Rolling per-player saves/90, shrunk,
   through E[floor(S/3)] via Poisson PMF.
2. **Goals conceded** — −1 per 2 (GK/DEF only). From `opp_lambda`
   (market-implied), through E[floor(C/2)].
3. **Cards** — −1 yellow, −3 red (all positions). **Position-prior only — see §3.**
4. **Penalty share** — added to E[goals]: `penalty_share × team_pen_rate ×
   minutes_frac`, from prior-season Understat records.

D1 also closed a genuine **train/serve skew in the bonus BPS input**: the BPS
model was trained on saves/cards/conceded/penalties but fed zeros at predict
time, worst for GK/DEF. It now receives the predicted values.

## 2. The measurement failure that almost sank it (and the logs it voided)

D1 was implemented into `assembly.py` BEFORE the pairwise margin-calibration
measurements ran. Every walk-forward file regenerated afterwards silently
carried the terms, so the "baseline" β table in `Logs/margin_calibration_log.md`
was in fact measured WITH D1 — that log and the derived parts of
`Logs/hit_threshold_log.md` are retracted (KNOWN_ISSUES #13). Separately, the
first D1 comparison report's figures were untraceable to any file and were
discarded outright.

The clean, provenance-verified before/after (step 0, starter band e_minutes≥60,
2025-26, `walkforward_h6_2526_baseline.parquet` vs the original full-D1 build,
preserved as `walkforward_h6_2025_26_d1cards.parquet`):

| | GK | DEF | MID | FWD |
|---|---|---|---|---|
| margin β, baseline | 0.847 | 1.074 | 0.720 | 0.623 |
| margin β, full D1 (per-player cards) | 0.425 | 0.912 | 0.690 | 0.616 |

## 3. Why Variant B: the cards term was the defect

Exact per-row decomposition (terms recoverable from stored columns; identity
verified to 2e-16) attributed the GK collapse almost entirely to **cards**:
alone −0.419 of the joint −0.422. Cards are rare events, so a 5-gameweek
rolling per-player rate is a spike detector: on GK starters its mean was −0.13
points with SD 0.72, and it was anti-correlated with realised points
(r ≈ −0.13). Saves (−0.101) and conceded (−0.126) interact sub-additively;
penalty share moved nothing at any position (≤0.001).

**Variant B** replaces the per-player rolling card rate with a position-level
base rate — realised cards per 90 by position, computed from PRIOR SEASONS
ONLY, never from the season being predicted, applied as
`−(ȳ_pos + 3·r̄_pos) × minutes_frac`. Reference rates (priors to 2025-26):
GK 0.049/0.001, DEF 0.169/0.007, MID 0.179/0.005, FWD 0.142/0.005 (yellow/red
per 90). This keeps the mean card deduction (DEF −0.165 vs −0.172 per-player)
while cutting per-row SD from ~0.72 to ~0.007 on GK and ~0.2 to ~0.024
elsewhere. The GKP/GK label inconsistency in `all_seasons_fixed.parquet`
(101 rows, 2021-22) is folded in before the rate is computed.

Measured effect of B vs baseline (2025-26, step 0, starter band): GK β
0.847 → 0.678, DEF 1.074 → 0.989, MID +0.004, FWD +0.007; Spearman deltas all
within ±0.013.

## 4. Selection is neutral — the top-k measurement

Because the optimizer selects from the top of each position, top-k selection
quality was measured directly: per gameweek, per position, k ∈ {1,3,5}, four
metrics (top-k realised points, same on a started-only pool, hindsight-top-k
overlap, mean realised rank of picks), four variants. **None of the 144
variant-vs-baseline comparisons resolved above gameweek-to-gameweek variation**
(paired per-gw deltas, |mean| > 2·SE criterion, 38 observations). Selection is
neutral at this sample size; adoption rests on the structural arguments and the
component metrics, not on a selection win.

## 5. Adoption rationale, in full

1. The four terms are real FPL scoring rules the model was structurally blind
   to. Blindness is not neutrality: uncounted saves systematically under-price
   busy goalkeepers; uncounted conceded systematically over-price defenders in
   hard fixtures.
2. D1 closed a genuine train/serve skew in the bonus BPS input.
3. Variant B removes the card-variance defect that caused most of the GK β
   collapse, keeping the mean deduction with none of the per-player noise.
4. Top-k selection showed no resolvable difference anywhere — adopting B does
   not measurably help or hurt selection; it makes the equation honest about
   rules that exist.

## 6. OPEN AND UNEXPLAINED — do not treat as resolved

**GK margin β falls from 0.847 to ~0.68 even without per-player cards**, driven
by saves and goals conceded — the two terms that should have helped goalkeepers
most. Both make the prediction more informed; both make the pairwise margin
scale WORSE. Single-term deltas: saves −0.101, conceded −0.126 (sub-additive
jointly). GK starter-band Spearman also dips ~0.013. This is not understood.
Possibilities not yet ruled out: the terms are right but the margin was
accidentally well-scaled before (compensating errors); opp_lambda double-counts
information already in p_cs for goalkeepers; the saves rolling rate carries
minutes noise. **Nobody should quote GK β ≈ 0.68 as "the calibrated state" —
it is the current state, with an open question attached.**

## 7. Implementation notes

- `D1_TERMS_ACTIVE` in `assembly.py` gates the terms AND feeds the
  `d1_terms_active` stamp written by both walk-forward writers; the provenance
  test asserts file-vs-code agreement. A silent repeat of #13 is now
  structurally impossible.
- The non-DC early-return path in `assemble_fixtures` previously skipped the
  entire D1 feature build, silently making prior-season files "D1
  conceded-only" — a third state no stamp distinguished. The path is
  restructured so ALL seasons build the features; only `p_dc_hit` remains
  DC-gated.
- Superseded artefacts preserved: `walkforward_h6_2526_baseline.parquet`
  (no D1), `walkforward_h6_2025_26_d1cards.parquet` (full D1, per-player
  cards). The incident figures in KNOWN_ISSUES #13 reproduce on these.

## 8. Final component metrics (Variant B, step 0)

All three canonical walk-forward files regenerated 2026-08-17 with
`d1_terms_active=True` stamped on every row; stamps otherwise
`minutes_availability=True`, `odds_horizon_gws=0`, `dgw_handling=per_fixture`.
Full test suite: 105 passed, 5 skipped (the canonical-2526 guards, file absent).
Prior seasons carry the full D1 feature set for the first time — they were
previously "conceded-only" via the early-return path (§7).

| season | agg ρ | agg MAE | GK ρ / β | DEF ρ / β | MID ρ / β | FWD ρ / β |
|---|---|---|---|---|---|---|
| 2025-26 | 0.748 | 1.079 | 0.191 / 0.676 | 0.253 / 0.988 | 0.191 / 0.724 | 0.170 / 0.632 |
| 2024-25 | 0.736 | 1.095 | 0.133 / 0.491 | 0.291 / 0.900 | 0.300 / 1.123 | 0.162 / 0.489 |
| 2023-24 | 0.722 | 1.065 | 0.191 / 0.622 | 0.332 / 1.064 | 0.322 / 0.967 | 0.183 / 0.492 |
| ~~2023-24~~ | ~~0.668~~ | ~~1.061~~ | ~~0.204 / 0.479~~ | ~~0.340 / 0.870~~ | ~~0.313 / 0.791~~ | ~~0.187 / 0.485~~ |

(ρ = starter-band Spearman, e_minutes ≥ 60; β = pairwise margin slope,
through-origin, same band.)

**2023-24 row corrected 2026-08-17** after the Sheffield United join-failure
fix (KNOWN_ISSUES #14): the original build carried 1,429 rows (5.0% of the
season, all Sheffield Utd players) with e_points forced to 0.0, which
depressed the aggregate ρ and every β. The struck-through row is the
superseded measurement, kept visible; the season now sits in line with the
other two. The top-k and agreement measurements' 2023-24 cells (§8 watch item,
§10) were NOT re-run and still include the contaminated rows.

2025-26 baseline reference (no D1): agg ρ 0.746, MAE 1.106; the Variant B build
trades ~0.01 of starter-band Spearman at GK/DEF for the honest scoring terms —
see §6 for the open question on GK β.

**Top-k selection, Variant B vs baseline, all three seasons** (k ∈ {1,3,5},
both pools, paired per-gw deltas): **3 of 72 comparisons resolve above 2·SE**,
against ~3.6 expected by chance at that threshold — consistent with noise in
aggregate. All three resolved cells are GK and all three negative (2024-25
all-pool k=5 −0.36, 2024-25 started k=1 −0.58, 2023-24 started k=3 −0.48);
recorded as a WATCH ITEM on GK top-k selection, not as evidence in either
direction. No DEF/MID/FWD cell resolves in any season or pool.

## 9. Season simulation — PROVENANCE REFERENCE ONLY

**Season total: 2028** (2025-26, one run, 2026-08-17). 36 transfers, 84 hit
points paid, 382 points left on bench.

**This figure identifies what the Variant B config produced. It is not
evidence about D1.**

- It is **not comparable to 1984, 1940, or any earlier figure** — the equation,
  the crosswalk, the odds horizon and the availability setting have all changed
  since those were produced.
- **The M1 gate failed**: season totals cannot distinguish a full model from
  one shrunk 75% toward the positional mean, and path noise is sd ≈ 60. A
  movement of any size here means nothing.
- **It must never be cited as showing D1 helped or hurt.** Anyone quoting 2028
  against any other total is repeating the exact mistake the M1 gate exists to
  prevent.

Config stamp for this run:

    source            data/walkforward_h6_2025_26.parquet (built 2026-08-17)
    d1_terms_active   True
    card_treatment    position_prior (prior-seasons realised rates, GKP folded in)
    minutes_availability  True
    odds_horizon_gws  0
    dgw_handling      per_fixture
    policy            mip
    H (horizon)       6
    decay             0.85
    hit_bar           4 (FPL's actual charge, default)
    crosswalk         player_id_crosswalk_final.csv (post-#12 audit)

## 10. Model-vs-model agreement (measured 2026-08-17, final B build vs baseline)

Part 1 is DETERMINISTIC — it compares the two prediction files directly, no
outcome luck involved, so it resolves exactly regardless of sample size.

**D1's practical effect on selection is concentrated entirely in goalkeeper
ordering.** Same #1 pick, top-k set agreement, and predicted-order Spearman on
the union of top-k sets (step 0, all-rows pool; started-only within a few
points everywhere):

| season | pos | same #1 | identical top-3 | identical top-5 | union ρ (k5) |
|---|---|---|---|---|---|
| 2025-26 | GK | 68% | 34% | 32% | 0.51 |
| 2025-26 | DEF | 92% | 79% | 76% | 0.89 |
| 2025-26 | MID | 100% | 89% | 92% | 0.97 |
| 2025-26 | FWD | 100% | 84% | 79% | 0.90 |
| 2024-25 | GK | 68% | 34% | 24% | 0.53 |
| 2024-25 | DEF | 89% | 84% | 68% | 0.90 |
| 2024-25 | MID | 97% | 95% | 89% | 0.97 |
| 2024-25 | FWD | 100% | 92% | 84% | 0.97 |
| 2023-24 | GK | 63% | 26% | 24% | 0.54 |
| 2023-24 | DEF | 87% | 74% | 63% | 0.87 |
| 2023-24 | MID | 97% | 92% | 97% | 0.97 |
| 2023-24 | FWD | 97% | 92% | 82% | 0.97 |

GK: different #1 roughly one gameweek in three, union ρ 0.51–0.54. DEF
secondary (87–92% same #1). MID/FWD are effectively the same model (97–100%,
ρ 0.97). Structurally expected: saves and conceded are the only terms that
REORDER within a position; MID/FWD receive only the near-zero penalty term and
a position-constant card deduction.

**Part 2 (against reality): 4 of 168 paired comparisons resolve, against ~8.4
expected by chance at 2·SE — mixed signs and positions. Whether D1's different
goalkeeper ordering is BETTER does not resolve at 38 gameweeks.** Within-own-
top-k ordering (3–5 points per gameweek) was predicted not to resolve and did
not: all 48 cells unresolved.

**Convergence note — three separate findings now point at goalkeepers:**
1. the unexplained β collapse from saves+conceded (§6),
2. the GK top-k watch item (§8),
3. this divergence: D1 changes roughly a third of #1 GK picks and no
   measurement can yet say whether the new ordering is better.

**2024-25 GK is the recurring negative — second appearance** (top-k watch item
in §8; hindsight overlap −0.26 at k=5 here). Still not conclusive; recorded so
a third appearance is recognised as a pattern rather than rediscovered.

See `Logs/gk_investigation_log.md` — the goalkeeper question is now its own
workstream.
