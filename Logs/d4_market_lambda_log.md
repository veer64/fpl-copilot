# D4 Phase 1 — market-λ model: dataset + baseline (synthetic forward odds)

**Status: D4 CLOSED 2026-08-20 (§13).** Phase 1 complete and validated
(sealed R² 0.851 vs DC 0.595, +0.10 edge at every horizon step, leakage
audit passed). Phase 2 tested and **NOT adopted** — no pipeline benefit on
three independent measurement grains. `synthetic_lambda_active = False` on
disk; code and model retained behind the gate. Durable output: forward-step
degradation is minutes/form-driven, not fixture-driven — horizon work should
aim there. Retest only if minutes-at-horizon materially improves (§13).

**Date:** 2026-08-18 · **Scripts:** `eval/build_market_lambda_dataset.py`
(dataset), `eval/measure_market_lambda.py` (study).

## 1. What this is

The system runs at `ODDS_HORIZON_GWS = 0`: market odds price only the current
gameweek, and the transfer MIP's forward gameweeks fall back to Dixon-Coles.
Odds beat DC by a measured ~69 points (sign test p ≈ 0.0007). D4 synthesises
what the market would say for unpriced fixtures. The scalar recalibration of
DC closed at R² 0.607 — the baseline to beat.

**Target:** `market_lambda` — one value per team per match, from inverting
Bet365 1X2 odds: 1/odds, proportional overround removal, then the
(λ_home, λ_away) whose Poisson scoreline matrix reproduces the three
probabilities. Inversion is `squad.dixon_coles._implied_lambdas` — the SAME
function production uses, so the target is defined exactly as the pipeline
defines it. Round-trip verified: max |probability error| 0.00018 on a
60-match sample (two λ cannot fit three probabilities exactly; pure Poisson
slightly underprices draws — same everywhere, including production).

**Grain:** team-match, 7,600 rows, 10 seasons (2016-17 .. 2025-26).

## 2. Dataset design (decisions of record)

- **19 features, five blocks** — market history (team: own/conceded λ,
  last-5/last-10/season-to-date = 6), market history (opponent: own/conceded
  last-5/last-10 = 4), Dixon-Coles (`dc_attack` team, `dc_defence` opponent,
  `is_home` = 3), schedule (rest days + matches-in-last-14, both sides = 4),
  availability (top-5-by-minutes flagged-unavailable count, both sides = 2).
- **DC refits per (season, gameweek)**, 380 fits, 1-year half-life
  (production config), trained on matches strictly before that gameweek's
  FIRST match date — more conservative than per-date; a Sunday match never
  sees Saturday results from its own GW. Cached at
  `data/history/d4_dc_walkforward_params.parquet`.
- **Rolling windows cross season boundaries** (a club's "last 5" reaches into
  its previous season); season-to-date resets and carries the within-season
  signal. Windows are strict (`min_periods = window`): a partial window is
  NaN, not a quietly noisier mean.
- **Burn-in** = any of the 10 market-history features NaN. Rows are FLAGGED,
  not deleted; the model script drops them. Availability NaN is NOT burn-in.
- **Promoted teams:** no prior EPL matches in the odds data → market-history
  NaN → their early rows are burn-in until windows fill. In the DC fit they
  enter at neutral strength (0 attack / 0 defence) and earn parameters as
  matches accrue against the 1-year half-life.
- **Availability** (2021-22+ only, NaN before): `asof_status ∈ {i,s,u,n}` =
  flagged; `d` (doubtful) deliberately NOT counted — it is a probability, not
  a flag, and `status` dominates `chance_of_playing` (availability_log.md).
  Top-5 = by cumulative season minutes strictly before the match date; GW1 →
  ranking undefined → NaN. A (season, gw) with no availability rows → NaN,
  never 0 — a silent "everyone fit" is the KNOWN_ISSUES #14 family. Known
  staleness: `u` is 100% departures, and a departed star keeps high
  cumulative minutes for a few weeks, so the count can carry a stale flag.
- **Team names:** explicit 3-entry alias map (odds → vaastav: Man United,
  Sheffield United, Tottenham), with a loud two-sided reconciliation assert
  (#14 lesson). Schedule features are EPL-only — cup/European congestion is
  invisible to this block.
- **Leakage rule (binding):** every feature strictly from before the match
  date. Every block writes an audit column carrying the max source date it
  consumed per row (`mh_prev_date`, `mh_opp_prev_date`, `dc_train_max`,
  `dc_cutoff`, `av_deadline_date`); `assert_no_leakage()` asserts strictness
  on every row at build time. Verification method: per-row date audit, not
  sampling.

## 3. PROTOCOL (this section written BEFORE the sweep ran)

- Expanding-window walk-forward by season: predicting season N trains on all
  seasons strictly before N. Model: LightGBM regression (l2), seed 42,
  deterministic.
- Hyperparameters tuned on target seasons **2017-18 .. 2024-25 only** (8
  validation cells). Grid: num_leaves {15,31,63} × learning_rate
  {0.03,0.05,0.1} × n_estimators {300,600} × min_child_samples {20,50} — 36
  configs.
- **Selection rule, fixed in advance:** the config maximising MEAN R² over
  the eight validation seasons; ties → lower mean MAE.
- **2025-26 is the SEALED test season.** It is excluded from the sweep
  entirely. `--holdout` runs it once, refuses to run without a
  `PRE-REGISTERED: {json}` line in this log, and takes its config FROM that
  line, so the registered and executed configs cannot disagree.
- Baseline on every table: the walk-forward DC model's own λ
  (`dc_lambda_pred = exp(atk_team + def_opp + hadv·is_home)`), scored on
  identical rows. Reference point: the closed scalar recalibration, R² 0.607.
- Ablations (validation seasons only): (a) without `dc_attack`/
  `dc_defence_opp`, `is_home` kept — does DC add anything over market
  history; (b) without the two availability features, 2021-22+ targets only.

## 4. Dataset build verification (2026-08-18)

`data/d4_market_lambda_dataset.parquet`: 7,600 rows, 624 burn-in, **6,976
usable**. Build ~10 min (106s inversion + ~8 min for 379 DC fits, cached).

- **Leakage audit: all strict, every applicable row.** Applicable counts
  self-verify: mh 7,566 (= 7,600 − 34 first-ever club rows), dc_train_max
  7,580 (− 20 zero-history GW1-2016 rows), dc_cutoff 7,600, av_deadline
  3,700 (= 740 × 5 covered seasons).
- **Burn-in decodes exactly:** 2016-17 = 200 (window fill, first ~10 rounds);
  a season introducing a genuinely NEW club = 38 (20 season-opener s2d rows +
  18 new-club window rows: Brentford 21-22, Forest 22-23, Luton 23-24,
  Ipswich 24-25); 2025-26 = 20 (Leeds/Burnley/Sunderland all RETURN, so their
  windows are old-but-full — the cross-season staleness flagged in §2, worth
  remembering when reading 2025-26 promoted-club predictions).
- **DC fit pathology, contained:** fits on <~40 matches are unidentified; 13
  rows carry dc_lambda_pred > 10 (9 of them inf) — all 2016-17 GW ≤ 4, ALL
  burn-in. Usable rows: 0.14–4.48, median 1.32. (This is the `overflow in
  exp` RuntimeWarning in the build output.)
- **379 DC cells, not 380:** 2022-23 GW7 has zero matches (Queen's funeral
  postponements). 2019-20's labels 30–38 are absent because vaastav labels
  Project Restart matches 39–47 — cosmetic, gw is only a join key here.
- **Availability join coverage:** 740/760 rows per covered season carry a
  value; the ONLY NaN reason is GW1's undefined minutes ranking (20
  rows/season). `mean_found = 5.0` in every season — every top-5 player had
  an asof row, so 'rows missing' vs 'nobody flagged' never actually collides
  in this data. Flag rate (mean count) 0.22–0.29.
- **Target sanity:** season means 1.24–1.42, rising in 2023-24 exactly when
  real EPL scoring did; league-average implied lambda 1.299.

## 5. Tuning results (validation seasons 2017-18 .. 2024-25)

Best by the §3 rule: num_leaves 15, lr 0.03, 300 trees, min_child_samples 20
— mean R² 0.8757, mean MAE 0.1416. The surface is FLAT (observed configs span
mean R² ~0.872–0.876): the most-regularized corner wins, and the choice is a
plateau, not a knife-edge.

Per validation season, chosen config vs walk-forward DC-alone (same rows):

| season | model R² / MAE | DC R² / MAE | n |
|---|---|---|---|
| 2017-18 | 0.8783 / 0.1448 | 0.7693 / 0.2206 | 690 |
| 2018-19 | 0.9097 / 0.1289 | 0.7936 / 0.2083 | 688 |
| 2019-20 | 0.8677 / 0.1483 | 0.7740 / 0.2042 | 688 |
| 2020-21 | 0.8834 / 0.1293 | 0.7371 / 0.2014 | 722 |
| 2021-22 | 0.9096 / 0.1225 | 0.7730 / 0.2114 | 722 |
| 2022-23 | 0.8890 / 0.1283 | 0.7292 / 0.2056 | 722 |
| 2023-24 | 0.8506 / 0.1583 | 0.8380 / 0.1777 | 722 |
| 2024-25 | 0.8173 / 0.1723 | 0.7499 / 0.2091 | 722 |

The model beats DC-alone in ALL EIGHT seasons; the narrowest margin is
2023-24 (+0.013), where DC-alone had its best year. NOTE on the 0.607
reference: the closed scalar recalibration was measured on a different design
— the honest baseline is the same-row DC-alone column above (0.73–0.84).

**DC ablation** (drop dc_attack/dc_defence_opp, keep is_home): R² falls in
all eight seasons, mean −0.0173. The DC features DO add information over
market history.

**Availability ablation** (2021-22+ targets): +0.0000 / +0.0010 / +0.0022 /
+0.0014 R². Direction positive but negligible, consistent with 0.1% gain
importance each. Plausible mechanism: the last-5 market history already
embeds the market's knowledge of absences; a top-5 flag count adds little on
top. NOT resolved as a real effect — four season cells is too few.

**Schedule features: exactly 0.0 importance, all four.** EPL-only rest/
congestion carries nothing the market history doesn't. (European/cup
congestion is invisible to this block — a caveat, not a verdict on
congestion itself.)

Feature importance (gain %, chosen config, train = all < 2025-26):
mh_own_l10 32.2 · mh_own_s2d 15.1 · mh_opp_own_l10 10.6 · dc_attack 10.0 ·
is_home 9.9 · mh_opp_conc_l10 8.7 · dc_defence_opp 7.7 · mh_own_l5 3.4 ·
everything else ≤ 1.1 (mh_conc_* ~0 — the team's OWN conceded history is
correctly irrelevant to its own scoring; the opponent's conceded history is
the defence read and does matter — a structural sanity check the model
passes).

## 6. PRE-REGISTRATION

**Chosen by the §3 rule, on validation seasons only. 2025-26 has not been
touched at the time this line is written; it will now be run ONCE, whatever
it shows.**

PRE-REGISTERED: {"num_leaves": 15, "learning_rate": 0.03, "n_estimators": 300, "min_child_samples": 20}

## 7. Sealed 2025-26 result (run once, after §6 was written)

| | model R² / MAE | DC-alone R² / MAE | n |
|---|---|---|---|
| **2025-26** | **0.8511 / 0.1270** | 0.5951 / 0.2191 | 740 |

The improvement REPLICATES on the sealed season: model R² sits inside the
validation band (0.82–0.91) while DC-alone had its worst season. The config
was taken from the §6 line by the script itself and not revisited.

Corroboration: DC-alone same-row R² on 2025-26 (0.595) lands next to the
closed scalar-recalibration figure (0.607) — the two studies measured the
same baseline and agree, which ties this dataset back to the prior
measurement.

(Procedural note: 2025-26 is the project's sealed season; this study used it
exactly once, pre-registered, per the house standard — the same pattern as
rate_blend_log.md §5–6.)

## 8. Phase 1 verdict

Dataset and baseline model COMPLETE. The market-history + DC + is_home
feature set predicts market_lambda at R² 0.85–0.91 out-of-sample versus
0.60–0.84 for walk-forward DC-alone, in all nine measured seasons.

**What this does NOT show:** R² against the market's own number is not
points. The operational question — does a synthetic λ at horizon k+1..k+3
improve e_points / selection metrics versus the DC fallback inside the
pipeline — is Phase 2, unmeasured. NOT integrated, NOT adopted.

## 9. Independent leakage audit (2026-08-18, after Phase 1 close)

Script: `eval/audit_market_lambda_leakage.py`. Deliberately does NOT trust the
builder's audit columns — every check returns to raw sources or perturbs the
learning problem. Results:

| check | result |
|---|---|
| 1 shuffle (target permuted within season) | PASS — R² −0.02..−0.16, mean −0.08 |
| 2 future-blind reconstruction, 5 fixtures × 19 features + target, by hand from raw | PASS — worst diff 4.4e-16 (float epsilon) |
| 3 single-feature R² | PASS — max mh_own_l10 0.505, nothing near 0.7 |
| 4 time reversal | NOT CLEAN — bwd 0.883 ≈ fwd 0.884; per-season deltas track n_train (bwd +0.040 with 9× data, −0.026 with 722 rows), a size confound the check cannot remove; leak reading contradicted by checks 1/2/3/6 |
| 5 gap test (no market-history features) | PASS — 0.791 vs 0.876 full; market history carries a real +0.085 |
| 6 DC cutoff vs own-GW matches, raw dates, 10 cells | PASS — 0 own-GW matches in training, all 10 |
| 7 availability asof vs deadline | PASS — 0 of ~87k stamped rows post-deadline; 30–48 status flips/season (log's ~47) |

## 10. Horizon degradation (audit check 8)

Script: `eval/measure_market_lambda_horizon.py`. Step k freezes ALL
information at the first match of the gameweek k−1 positions before the
target's (gameweek POSITIONS, so 2019-20's 39–47 labels and 2022-23's missing
GW7 cannot corrupt the arithmetic). Frozen: market history, DC fit (cached
per-GW fit at the freeze gameweek), availability (top-5 ranking and statuses
at the freeze deadline). Schedule stays calendar-based (public in advance).
Common evaluation rows across all steps (n=5,012, valid at step 6), eight
validation seasons; 2025-26 untouched, not even as training. Baseline =
DC frozen at the SAME cutoff (the production fallback is equally stale).

Mean R² over seasons:

| step | A: fresh-trained | B: stale-trained | DC-frozen | A−DC |
|---|---|---|---|---|
| 1 | 0.8742 | 0.8741 | 0.7707 | +0.104 |
| 2 | 0.8650 | 0.8643 | 0.7616 | +0.103 |
| 3 | 0.8586 | 0.8503 | 0.7505 | +0.108 |
| 4 | 0.8501 | 0.8413 | 0.7420 | +0.108 |
| 5 | 0.8430 | 0.8355 | 0.7343 | +0.109 |
| 6 | 0.8298 | 0.8177 | 0.7249 | +0.105 |

Findings: (1) degradation is gentle (~0.009 R²/step) and DC-frozen degrades
in parallel, so the model's EDGE is flat ~+0.10 at every horizon; (2) the
model never crosses below the fallback on the mean, and per-season only in
2023-24 (DC's best year) at deep steps, by ≤0.011; (3) R² never approaches
0.60 — worst cell 0.750; the ~0.60 DC reference was a 2025-26 figure, and on
these rows DC-frozen sits 0.72–0.77; (4) **variant B (stale-trained, one
model per step) does NOT beat variant A — A ≥ B at every step, gap growing
to 0.012 at step 6.** The train-on-stale hypothesis did not survive
measurement; the fresh-trained model transfers to stale inputs. B also
trains on fewer rows (stale windows drop early-season cells), which is part
of why. Production implication: one fresh-trained model + per-horizon frozen
features is both simpler and better on these measurements. (The `overflow in
exp` warnings during assembly are the known degenerate 2016-17 GW≤4 DC fits;
those rows never enter evaluation and dc_frozen_pred is not a feature.)

## 11. PHASE 2 — pipeline integration test (protocol written before results)

**Question:** does synthetic λ move e_points and selection, versus the pure-DC
fallback, at horizon steps 1–5? Step 0 keeps real odds (`ODDS_HORIZON_GWS=0`
stands) and must be bit-exact.

**Change under test:** `squad/synthetic_lambda.py` (new) holds the gate
`SYNTHETIC_LAMBDA_ACTIVE` and the serving model; `dixon_coles.get_fixtures`
fills unpriced fixtures' market λ from it when the gate is on, after which the
ordinary tuned blend weights apply (λ pure synthetic, CS 0.2·DC + 0.8·synth —
the synthetic value stands in for the market it approximates). Per-fixture
`lambda_source` column (odds | synthetic | dc). Both writers stamp
`synthetic_lambda_active` from the gate constant.

**Serving design (fixed by the §10 horizon study):** ONE fresh-trained model
refit per cutoff — trained on Phase 1 fresh features, non-burn-in rows with
match_date < cutoff (prior seasons + predicted season to date), pre-registered
§6 config — fed per-horizon frozen features (market history < cutoff, DC from
the cached per-GW fit at the cutoff, availability at the CUTOFF gw's asof
deadline, schedule/is_home from the calendar). Per-step stale models measured
worse (§10) and are not built. Backtest scope only: features come from the
Phase 1 dataset; live 2026-27 needs a dataset extension.

**Sanity check at one cutoff (2024-25, GW20) before building:** priced
fixtures bit-identical gate-on/off; 181/181 unpriced fixtures filled
(lambda_source: 199 odds, 181 synthetic, 0 dc); synth vs realized future
market λ ρ 0.877 / MAE 0.231 vs DC 0.853 / 0.251.

**Files:** canonicals preserved as `*_presynth.parquet` (md5-verified);
synth builds written to `*_synth.parquet` — canonicals untouched, so
"do not adopt" holds trivially. Measurement:
`eval/measure_synthetic_lambda.py`, conventions per §7 of the 2026-08-18
handoff and the rescued `eval/d1_topk.py` / `eval/d1_agreement.py`.

**Pre-stated metrics:** per season, before/after — (1) ρ/MAE by step 0–5, all
rows + starter band (e_minutes≥60), step 0 bit-exact required; (2)
starter-band ρ by position × step; (3) margin β by position × step
(through-origin pairwise, moment accumulation); (4) per-step top-k realized
points k∈{1,3,5}, pools all/started(minutes≥60), paired per-cutoff deltas,
resolved iff |mean|>2·SE, counted against ~5% chance; plus a planner-grain
horizon-sum (steps 1–5) top-k; (5) agreement: same-#1 and top-5 overlap by
position × step. H is NOT changed in this run; per-step quality is reported
so the H question can be decided separately.

(results to be appended)

## 12. PHASE 2 RESULTS (2026-08-19) — NOT ADOPTED, gate returned to False

**Step 0 bit-exact in all three seasons** (28,742 / 26,919 / 29,338 rows, max
|diff| 0.0 over 8 prediction columns) — after one comparability fix: the
first 2025-26 synth build used `walkforward.py` while the canonical lineage
is `walkforward_season.py`; the provenance check caught it (§7-convention
stamps differ) and 2025-26 was rebuilt with the season writer.

**INCIDENTAL FINDING, pre-existing:** the two writers disagree about the DC
term. `walkforward_season.py` passes an EMPTY p_dc_hit frame even for
2025-26 (dc_rule_active=True), so the CANONICAL 2025-26 file's p_dc_hit is
the position BASE RATE (max 0.136 = DC_BASE[MID]); `walkforward.py` wires
the per-player DC model (max ~0.80). The canonical lineage therefore prices
defensive contribution at position base rates, not the per-player model.
Not introduced by this work; needs its own decision (KNOWN_ISSUES candidate).

**Aggregate ρ/MAE, steps 1–5 (after − before):** ρ −0.0006..−0.0017 (all
rows) in every season; starter band −0.018..+0.001. MAE flat in 2023-24,
slightly worse in 2024-25, better at every step in 2025-26 (−0.002..−0.003).
Verdict: flat, lean negative.

**Margin β by position — the one perfectly consistent structural effect.**
Across 3 seasons × 5 steps (15 cells per position): MID β toward 1 in 15/15,
FWD toward 1 in 15/15, GK away in 15/15, DEF away in 15/15 (e.g. 2025-26
step 1: MID 0.948→0.971, FWD 0.945→0.980, GK 0.891→0.865, DEF 0.992→0.966).
Hypothesis (untested): sharper synthetic team-attack spread makes attacking
spreads more honest, while the conceded/CS side inherits the GK-investigation
H1 double-count sensitivity — a sharper opp_lambda spread pushes GK/DEF β
down exactly as D1's conceded term did.

**Starter-band ρ by position:** 2025-26 splits structurally — DEF and MID
improve at every step, GK worsens at steps 1–4; 2024-25 worsens nearly
everywhere; 2023-24 mixed. No position improves in all three seasons.

**Top-k (k∈{1,3,5}, pools all/started, paired per-cutoff, steps 1–5):**
resolved 3/120, 6/120, 6/120 vs ~6 chance per season — **15/360 vs ~18
chance: nothing resolves.** Directions contradict across seasons (2024-25's
resolved cells negative, 2025-26's mostly positive). Horizon-sum (steps 1–5
summed): 2023-24 MID k=3 −0.82 RES vs 2025-26 MID k=3 +1.07 RES — noise.

**Agreement:** same-#1 65–97% by (position, step); top-5 overlap 3.9–4.6/5.
The fill reorders selections modestly; most at GK/MID deep steps.

**The H question (reported, not acted on):** before-model per-step ρ (all
rows) 2025-26: 0.677/0.640/0.612/0.589/0.576 for steps 1–5; synthetic λ does
not materially change the curve. The case for H>3 rests on the same numbers
it did before — the forward-step degradation is dominated by frozen
minutes/form, not by fixture pricing.

**Verdict: the λ-level edge (+0.10 R² at every horizon step) does NOT
translate into e_points accuracy or selection gains.** e_points at forward
steps is dominated by frozen minutes and player form; team-λ refinement is
second-order there. NOT adopted; `SYNTHETIC_LAMBDA_ACTIVE = False`;
canonical files untouched (md5-verified _presynth copies exist); the
*_synth.parquet artefacts (stamped synthetic_lambda_active=True) reproduce
every number above via eval/measure_synthetic_lambda.py.

## 13. D4 CLOSED (2026-08-20)

**Phase 1 complete and validated. Phase 2 tested and NOT adopted.
`synthetic_lambda_active = False` on disk; code and model retained behind
the gate.**

**Phase 1 succeeded as a modelling result.** Sealed-season R² 0.851 vs 0.595
for Dixon-Coles alone; the edge (+0.10 R²) sustained across horizon staleness
steps 1–6 against an equally-stale DC baseline; config pre-registered before
the sealed run; independent leakage audit passed, including a bit-exact hand
reconstruction of five fixtures (worst |diff| 4.4e-16) and a per-gameweek DC
cutoff check from raw dates.

**Phase 2 found no pipeline benefit. Three independent measurement grains
agree:**
- prediction accuracy at forward steps: flat (ρ −0.001..−0.002; MAE
  marginally better in 2025-26 only), re-confirmed after the #15 DC-wiring
  fix on properly-priced files;
- top-k selection: at or below chance in all three seasons (11 resolved of
  360 cells vs ~18 chance);
- per-decision, from 2,967 sweep transfers: corr(predicted gain, realized
  gain) 0.301 base vs 0.264 synth; paired season-total sign test over 27
  matched configs 11–16 against synth, p = 0.442 (the method that
  established odds-vs-DC at 16/18, p ≈ 0.0007 — this is nothing like that).

**The mechanism finding — the durable output of D4:** forward-step
degradation is driven by FROZEN MINUTES AND FORM, not fixture pricing.
Team-λ refinement is second-order at horizon. Future horizon work should aim
at minutes/form persistence, not at fixtures.

**The one consistent effect:** margin β moved toward 1.0 for MID and FWD in
60 of 60 (season × step) cells and away for GK and DEF in 60 of 60 — the
same signature as the H1 double-count hypothesis in
Logs/gk_investigation_log.md. If that investigation resumes, this is
corroborating evidence from an independent intervention.

**Retest condition:** if minutes prediction at horizon materially improves,
λ may stop being second-order; the serving path (squad/synthetic_lambda.py),
the per-cutoff model, and the full artefact lineage (*_synth.parquet,
*_presynth.parquet) reproduce every number in this log. Flip the gate only
with a new pre-registered protocol.
