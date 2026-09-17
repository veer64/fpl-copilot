# Prereg v2 (hinge prior + plausibility box) — execution log (2026-09-17)

Pre-registration: `Logs/dc_shrinkage_threshold_prereg_2026-09-17.md` (approved by the user 2026-09-17 with the
condition: if the bar is falsified or the result is marginal, Friday ships exactly as today — loud, degraded, the
artefact named — and the bar is not amended). Recorded in execution order. §1 was written BEFORE the reference
builds finished (they were launched 16:31Z; §1 closed 16:40Z); §2 carries the numbers verbatim.

## 1. Implementation findings — three things the prereg did not specify, settled before any endpoint number

The form was implemented literally first (raw-coordinate prior, L-BFGS-B box bounds on the raw parameters). Its
own unit tests failed on the synthetic league, and the failure was informative, not a bug in the test:

**(a) Identifiability.** The Dixon-Coles likelihood is invariant to `atk + c / dfc − c` for any constant c. On
the record the fits sit in the gauge `sum(atk) = sum(dfc)` (L-BFGS-B from zeros never moves along the flat
direction; measured on the 2025-26 archive at three cutoffs: |sum(atk) − sum(dfc)| ≤ 7e-4, finite-difference
noise), and in that gauge the LEAGUE MEAN attack is +0.09 to +0.10, not 0 (the mean defence the same, home
advantage 0.135–0.157). So "attack 0 = the league rate", which both the prior's centre and the box's meaning rely
on, is not true of the raw coordinates. Worse, a penalty on ONE club's raw coordinates is not gauge-invariant: the
optimiser cheapens it by shifting the WHOLE league along the flat direction at zero likelihood cost (the prior
then acts on the club's attack + defence sum, and only half as strongly), and a raw-coordinate box lets a scoreless
club keep running off through that shift until some established club hits the OPPOSITE bound — observed on the
synthetic test at n = 12: the newcomer at −ln 4 and an ordinary club pinned at +ln 4. That is precisely the
"established club at a bound" the prereg's gate (e) forbids, produced by the mechanism itself.

Decision: both parts act on CENTRED parameters, `atk_i − mean(atk)` and `dfc_i − mean(dfc)` over the clubs in
the fit. The hinge is `0.5 · Σ tau_i · ((atk_i − ā)² + (dfc_i − d̄)²)`; the box is `|atk_i − ā| ≤ ln 4`,
`|dfc_i − d̄| ≤ ln 4`. Both are invariant to the gauge, so the fit stays in the record's gauge (asserted in the
tests: `|sum(atk) − sum(dfc)| < 1e-3`) and "0.25× the league rate" means exactly that. The box is no longer a
simple bound, so the refit uses SLSQP with 4·nt linear inequality constraints (constant Jacobian) from the same
starting point; L-BFGS-B — the record's optimiser — is used for every fit that never needs the box, so the
structural bit-identity is unchanged. `LAST_FIT` records `method`. The centred ranges of the 34 clubs in the
2025-26 fits (all clubs in the training set, relegated ones included) are attack [−0.69, +0.62], defence
[−0.67, +0.44]: inside the box by ≥ 0.70. The prereg's raw ranges [−0.53, +0.90] / [−0.69, +0.51] were measured
in the record's gauge and are consistent with these once the +0.09 mean is removed.

This is a correction of what the prereg's words already meant, made before any number; tau_0, N, the box's width,
the endpoint, the slices and the falsifier are untouched.

**(b) Which clubs the hinge may touch.** The prereg's evidence table counted the predict season's clubs. But
the training set holds every club in the archive (34 in a 2025-26 fit), and a club relegated two seasons before
the predict season sits at n_eff ≈ 38 × 2⁻² ≈ 9.5 < N in every fit — Sheffield United and Luton in every 2025-26
cutoff, Burnley likewise. A hinge on such a club would switch the penalty on at EVERY cutoff and break the
bit-identity the prereg promises for unaffected cells, for no benefit: those clubs' parameters are never used.
Decision: the hinge applies to the clubs whose parameters are USED — the predict season's clubs, passed to the
fit as `prior_teams` (default None = every club, the literal form). The box applies to every club (it binds only
where a likelihood has no minimum, which no old club's 38-match season produces). Test: an old club below N
outside `prior_teams` leaves the fit bit-identical to the plain one.

**(c) The box and the detector — the reconciliation the user asked to settle now.** A club CLAMPED at the
plausibility bound (`LAST_FIT["at_bound"]`) is the box working, not a parameter running off. It is a
`MODEL NOTE:` finding (`live_deadline.MODEL_NOTE`), alongside a second note naming the clubs the hinge touched
(`clubs_below_n` with n_eff and tau — the KNOWLEDGE visibility the prereg §4 promised). Notes appear in the run's
findings and on `/health` as `model_notes`; they never become a reason, never degrade, never push, never raise.
The EXTREME check is UNCHANGED and still applies to a clamped club: the bounds [0.15, 6.0] are the bounds, and a
lambda below 0.15 is a MODEL DEGRADED finding whoever produces it (the prereg's floor arithmetic: 0.25× v the
strongest fitted defence gives ≈ 0.17 at home and less away, so a clamped club at a top defence away is close to
the bound — if the record shows one below 0.15 after the change, gate (c) falsifies the prereg; live, it is a
legitimate finding and the answer is to understand the club, never to widen the box). The fatal raise, when it
ships, raises on EXTREME and on a non-converged fit only. Test: a clamped club at λ 0.41 is a note, not degraded;
the same club at λ 0.14 is EXTREME regardless.

Code: `squad/dixon_coles.py` (`SHRINK_TAU0 = 5.6`, `SHRINK_N = 10`, `ATK_DFC_BOUND = ln 4`; `_fit_dc_decay(...,
prior_teams=None)`: n_eff per club, tau_i, the centred hinge, the unbounded L-BFGS-B fit, the SLSQP refit only
if a centred parameter is outside the box, `LAST_FIT` with `method`, `boxed_refit`, `league_mean_attack/defence`,
`clubs_below_n`, `at_bound`, `min_margin_to_bound` + `min_margin_club` (gate (e), computed in the fit);
`get_fixtures` passes the predict season's clubs); `squad/live_deadline.py` (`MODEL_NOTE`, the two notes in
`degraded_findings`, the non-converged message names the method); `model_tools.py` (`_model_notes`,
`_prefixed_findings`, `/health.model_notes`). Tests: `Tests/test_dixon_coles_shrinkage.py` (the table at
n = 3 / 8 / 12 on centred attack: pull, then exactly −ln 4 at the box with `method == "SLSQP"`; the same newcomer
runs off with the form off; a cutoff with no poor club bit-identical to the plain fit; the hinge scoped to
`prior_teams`; the box binds only on the runaway club with every other centred parameter > 0.2 from a bound;
notes v degraded), `Tests/test_model_degraded_health.py` (notes reach `/health` as information). The record test
(gate (c) as a permanent test) is keyed to the `*_pre_hinge` artefact and skips until the rebuild.

Named gates before the reference builds: `Tests/test_live_deadline.py` 13 passed, 1 failed —
`test_extraction_reproduces_arm_record_full_cutoff`, which extracts 2025-26 at cutoff 5 against the arm record
built without the form. Cutoff 5 is an affected cell (Sunderland n_eff 3.9 there), so the divergence is the form
working, not a tell; the two GW20 tests (an unaffected cell) stayed bit-identical. The gate applies to the REBUILT
record and is re-run there. `Tests/test_asof_reconstruction.py` 4 passed.

Full suite at step 1 (16:40Z, the GW5 parity test deselected for the reason above): **429 passed, 1 skipped** (the
record test keyed to `*_pre_hinge`). Nothing pushed.

**(d) Found by the first reference build's structural tell (16:50Z) — recorded with the numbers that were
seen.** The first build with (a)–(c) in place reported: unaffected cutoffs bit-identical in every season (gate b
held); but 2023-24 cutoffs 2–10 took a box refit with `Ipswich` at BOTH bounds. Ipswich was not in the league in
2023-24: the fit's team list spans every archive season (2016-17 … 2025-26, 34 clubs), so a club promoted in a
LATER season is in the fit with zero training rows — a phantom whose parameters nothing anchors (in the record's
plain fit they simply stay at the starting point). With the centring of (a) taken over all 34 clubs, the phantom
became a free slack variable for the league mean: at 2023-24 cutoff 2 the unbounded fit moved Ipswich's defence
to +26.3 to shift the mean and cheapen Luton's penalty (non-converged, 190 iterations), and the box then clamped
the phantom at ±ln 4, shifting every other club's CENTRED value by ln 4 / 34 ≈ 0.04 (their fixture λ barely
moved: home advantage +0.0004, rho +0.0005). That is "the implementation is not the form" — exactly what the tell
is for. Fix: the league mean (for the hinge's centre and the box) and the box itself are taken over the predict
season's clubs (`in_prior`, n_league = 20); every other club is the plain MLE or, for a phantom, the starting
point, as on the record. `LAST_FIT` records `n_league`. The endpoint script was also made conservative: a step-0
row whose opponent cannot be paired by the exact λ swap is never counted as "no affected club" (the first build's
2023-24 "clean" maximum of 0.018 was Everton v Luton at cutoff 7, mis-paired — Luton IS the affected club).

Numbers seen on that first build, superseded and recorded so the sequence is honest: pooled starters Δ +0.0021
(SE 0.00085), top-30 Δ −0.0076 (SE 0.0054); per season top-30 −0.0044 / +0.0052 / −0.0248. The bar was not
touched; the second build below is the one it applies to.

Suite after the fix (16:59Z, same deselection): **430 passed, 1 skipped** (the phantom-club test added). Nothing pushed.

## 2. Reference builds and the endpoint, verbatim (prereg §2, §3)

Second (corrected) builds, launched 16:51Z, done 17:10Z: scratch `refbuild_v2.py` → `ref_v2_{tag}.parquet` +
`ref_v2_{tag}_fits.json` (one `LAST_FIT` per cutoff); `v2_endpoint.py` (calendar-based opponent map from the
stack's kickoff windows, every fixture assigned, no unpaired row) → `v2_endpoint_ref_v2.json`. Against the record
`data/walkforward_h6_{tag}.parquet` (the 2026-09-13 DC-fix rebuild, no form).

### 2.1 The §2 tells and the structural gates

| | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| affected cutoffs (a league club below N, or at a bound) | 1–11 (Luton; cutoff 1 also Sheffield United, tau 0.087 = 1.5 % of tau_0) | 1–12 (Ipswich) | 1–11 (Sunderland) |
| unaffected cutoffs bit-identical, every column, every row (gate b) | 12–38: **yes** | 13–38: **yes** | 12–38: **yes** |
| rows moved in the affected cutoffs (e_points) | 93.9 %, max Δ 2.26 | 96.1 %, max Δ 3.26 | 96.5 %, max Δ 2.37 |
| box refits (SLSQP) | **0** of 38 | **0** of 38 | **0** of 38 |
| fits converged (gate c) | 38/38, max 123 it | 38/38, max 141 it | 38/38, max 173 it |
| nearest established club to a bound (gate e, ≥ 0.2) | 0.64 (Sheffield United attack, c2) | 0.82 (Southampton attack, c38) | 0.89 (Arsenal defence, c38) |
| max centred attack / defence among league clubs | 0.75 / 0.55 | 0.57 / 0.52 | 0.42 / 0.50 |
| league mean attack (over the 20 clubs) | +0.21 … +0.28 | +0.29 … +0.32 | +0.30 … +0.33 |
| team λ min (gate c, ≥ 0.15) — record | 0.408 (c2 gw3 Sheffield Utd) — 0.408 | 0.508 (c5 gw9 Southampton) — **0.0007** | 0.455 (c7 gw7 West Ham) — 0.188 |
| team λ max (≤ 6.0) | 4.32 | 4.43 | 3.38 |

- **The box never binds on the record.** The prereg named 2024-25 cutoff 2 (Ipswich, λ 0.0007) as the box's one
  record case; the hinge alone holds it — at n_eff 1.0, tau 5.05, Ipswich's attack lands inside and its cells go
  0.0007 → 0.874 (mean over its cells 0.146 → 1.189). So on the record the form is the hinge; the box is exercised
  only by the synthetic tests (n = 8 and 12 scoreless) and would first matter live at eight goalless matches.
- Affected clubs' λ (mean over the club's cells at the cutoff, record → form): Luton c1 0.97 → 1.16, c4
  0.68 → 1.11, c6 0.62 → 0.92, c11 0.75 → 0.76; Ipswich c1 0.99 → 1.31, c3 0.85 → 1.28, c12 1.13 → 1.13;
  Sunderland c1 0.74 → 1.40, **c2 1.99 → 1.53** (the one-clean-sheet defence runaway, the other direction),
  c5 1.07 → 1.16, c11 0.98 → 0.98. The hinge releases where the evidence table said it would.
- **Gate (d), step 0 p_cs.** Fixtures involving an affected club: mean |Δ| 0.0128 / 0.0105 / 0.0121, max
  **0.046 / 0.058 / 0.065** — all under the 0.15 stop. Fixtures NOT involving an affected club, at the affected
  cutoffs: max |Δ| **0.0012 / 0.0016 / 0.0010** — not bit-identical. The mechanism is the form's shared
  parameters (at 2023-24 cutoff 1 the home advantage moved +0.00008 and rho +0.00008; the league mean, over which
  the hinge centres, couples every league club at 1/20 of the hinged club's gradient). v1 §2 stated exactly this
  ("through the fitted home advantage and rho, which are shared, every fixture by a small amount"); v2 §3 (d)
  wrote "bit-identical" for those rows, which no form with shared parameters can deliver. Recorded as an
  overstatement in the prereg's wording — not a falsifier (the falsifier is |Δ p_cs| > 0.15) and not the §2 tell
  (that is cell-level: the unaffected CUTOFFS are bit-identical, and they are). The endpoint script flags it as
  written, so the flag stays in the JSON.
- The first-build tell (§1(d)) is gone: no phantom club moves, no box refit, every fit converged.

### 2.2 The primary endpoint (prereg §3) — pooled over the 170 affected cells (55 + 60 + 55), steps 1–5

| slice | record mean | form mean | paired mean Δ | SE | Δ / SE | cells up / unchanged | falsified (< −2 SE)? |
|---|---|---|---|---|---|---|---|
| likely starters (p_start ≥ .75) | 0.2268 | 0.2290 | **+0.0022** | 0.00106 | **+2.1** | 62 % / 3 % | no |
| top 30 by e_points | 0.1484 | 0.1390 | **−0.0093** | 0.00622 | **−1.5** | 42 % / 10 % | no |

Reported alongside (Δ starters / Δ top-30): per season 2023-24 +0.0009 / −0.0042, 2024-25 +0.0029 / +0.0016,
2025-26 +0.0028 / **−0.0264**; early cutoffs 1–6: +0.0015 / −0.0018, +0.0049 / +0.0013, +0.0038 / **−0.0395**;
top-30 by step, 2025-26: −0.044 / −0.026 / −0.025 / −0.035 / −0.002; 2023-24: +0.014 / −0.032 / −0.013 / −0.037 /
+0.047; 2024-25: −0.019 / −0.004 / +0.008 / +0.014 / +0.010. Season totals: not computed (they need the arm
rebuild, which did not run — see §3); they would be reported, never judged.

**Where the top-30 movement comes from** (scratch `top30_driver.py`; the affected club's players in each cell's
top 30, record v form):
- 2025-26: Sunderland players held **121** top-30 slots across the 55 cells in the record (up to ten in one cell:
  the cutoff-2 defence runaway made their clean-sheet e_points huge), 69 under the form. In the 32 cells where
  Sunderland has a player in the form's top 30, Δ −0.041; in the 20 cells where it has none in either, −0.007.
  The six worst cells are cutoffs 1–2 (Sunderland 10 → 2, 6 → 1, 8 → 1 players; cell Spearman +0.06 → −0.32,
  +0.24 → +0.02, +0.04 → −0.18): the record's runaway happened to rank a block of one club's players highly in
  weeks they scored. Their mean actual points when in the form's top 30: 3.23 v the top 30's 4.07.
- 2023-24: Luton's slots **13 → 34** — the hinge's centre (the league mean) is generous for a promoted club; their
  actual points in the form's top 30 averaged 3.06 v the top 30's 3.91. The 9 cells Luton enters: Δ −0.091; the
  other 46: **+0.013**.
- 2024-25: Ipswich 2 → 4 slots; Δ +0.002 (56 cells without) / +0.007 (4 with).

Reading: the top-30 slice measures where a promoted club's block of players lands, in both directions — removing
a runaway that happened to be "right" costs it (2025-26), and a centre at the league mean that is too generous
for a promoted side costs it (2023-24). The broad slice, likely starters, is up in all three seasons.

### 2.3 Sensitivity rows (prereg §3: informational, never a re-choice) — cutoffs 1–13 of each season, pooled

| row | cells | Δ starters (SE) | Δ top-30 (SE) | per season top-30 | converged / λ min / margin | notes |
|---|---|---|---|---|---|---|
| **the form: N 10, tau_0 5.6, box ln 4** | 170 (all affected) | +0.0022 (0.0011), +2.1 SE | −0.0093 (0.0062), −1.5 SE | −0.0042 / +0.0016 / −0.0264 | yes / 0.408 / 0.64 | |
| N = 6 | 105 | +0.0026 (0.0015), +1.7 SE | −0.0085 (0.0089), −1.0 SE | +0.0001 / +0.0020 / −0.0276 | yes / 0.408 / 0.64 | one unaffected cutoff (2025-26 c9) differs in `pred_bps` by 7e-15, e_points unchanged: bonus-model floating-point noise, not the form |
| N = 15 | 195 | +0.0019 (0.0010), +1.9 SE | −0.0075 (0.0057), −1.3 SE | −0.0042 / +0.0016 / −0.0198 | yes / 0.455 / 0.77 | |
| tau_0 = 2.8 | 170 | +0.0017 (0.0008), +2.0 SE | −0.0091 (0.0056), −1.6 SE | −0.0077 / +0.0034 / −0.0242 | yes / 0.408 / 0.64 | |
| box ln 3 | (pending) | | | | | |
| box ln 6 | (pending) | | | | | |

The pattern is the same in every row: starters up ~2 SE, top-30 down 1–1.6 SE, 2025-26's top-30 the whole of it.
The box rows can only reproduce the form exactly (the box never binds on the record).

## 3. The decision at the stop point (prereg §5 step 2; the user's condition of 2026-09-17)

**By the letter of the bar: not falsified.** (a) neither slice is below −2 SE (starters +2.1 SE, top-30 −1.5 SE);
(b) every unaffected cutoff is bit-identical; (c) every λ is inside [0.15, 6.0] and every fit converged; (d) the
largest step-0 |Δ p_cs| is 0.065 against a stop of 0.15; (e) the nearest established club is 0.64 from a bound.

**By the user's condition — "if the bar is falsified, or the result is marginal, Friday ships exactly as it is
today" — this is marginal.** The top-30 slice is at −1.5 SE pooled and its whole loss sits in 2025-26 (−0.026,
about −2.4 of that season's own SE), the season most like the live one; the sign matches the falsified k = 4's
signature, even though the mechanism is different (there, strong clubs compressed; here, strong clubs are
bit-identical and the movement is where one promoted club's block of players lands). Starters, the broad slice,
is up in every season. §2.2's driver analysis says the top-30 loss is largely the record's runaway having been
lucky in 2025-26 cutoffs 1–2, and the prior's centre being generous for Luton in 2023-24 — a reading, not a
number the bar was written on. The condition is applied as stated: **NOT adopted at this stop point. Friday's
runs ship exactly as today** — the loud detector carries Coventry's runaway (λ 0.0006, converged False) to
`/health` and the phone; the builds are served.

What is in the tree: the form, the detector reconciliation, the `/health` notes and the tests, committed on branch
`hinge-box-v2` from main (unpushed — the model path cannot go to main until the record is rebuilt, because the
GW5 extraction-parity test diverges against the old record by design). main carries only this log, the prereg's
status line and KNOWN_ISSUES #25's note. The rebuild is scripted (`scratch rebuild_hinge.ps1`: preserves every
artefact as `*_pre_hinge`, then canonical → gap0 arms → armlogs per season) and the guards, parity-by-name,
re-pins and deploy steps are as the prereg §5 step 3 lists them: ≈ 3 h of laptop time plus a deploy window. A go
given before ~05:00Z Friday still lands before the 11:00Z nightly; later than that, the change is for GW6.

Not done, deliberately: no rebuild, no re-pins, no push, no deploy. The bar is not amended; a different N, tau_0
or box is a new pre-registration.
