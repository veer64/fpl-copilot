# Handoff — 2026-08-18 → 2026-08-20 session, FULL DETAIL (code-first)

**Covers everything in the session:** D4 synthetic forward odds (Phases 1–2,
closed NOT adopted), the transfer sweep harness, KNOWN_ISSUES #15 (DC-wiring
fix, adopted), D6 free-half live poller (built, parked), P4 structural chip
policy (ADOPTED), bench-aware Bench Boost (ADOPTED), the standard-config
change to H=6/decay=0.45 (ADOPTED), the solver thread cap, and five
read-only analyses. Companion summary: `Handoff_2026-08-20_P4_D4_close.md`
(shorter, state-focused). This document is the code-level record.

---

## 1. LIVE CONFIG — every gate, its location, its value

| Constant | File:approx line | Value | Stamped as |
|---|---|---|---|
| `D1_TERMS_ACTIVE` | squad/assembly.py:43 | True | `d1_terms_active` |
| `CS_UNIFIED` | squad/assembly.py:57 | False | `cs_unified` |
| `RATE_BLEND_ACTIVE` / `RATE_BLEND_K` | squad/attacking_rates.py | True / 8.0 | `rate_blend_active`/`_k` |
| `SYNTHETIC_LAMBDA_ACTIVE` | squad/synthetic_lambda.py (top) | **False** | `synthetic_lambda_active` (both walk-forward writers) |
| `BENCH_BOOST_AWARE` | squad/transfer_mip.py (~line 134) | **True** | `bench_boost_aware` (simulator decision log) |
| `DEFAULT_HORIZON` / `DEFAULT_DECAY` | squad/transfer_mip.py (~150) | 6 / **0.45** | `horizon` / `decay` (simulator decision log) |
| `HIT_COST` | squad/transfer_mip.py | 4 | — (game rule) |
| env `FPL_SOLVER_THREADS` | read in squad/optimize.py `_default_solver()` | unset ⇒ HiGHS default | — |

Simulator decision logs now stamp per row: `horizon`, `decay`,
`bench_boost_aware`, `bench_boost_gw` (−1 when none). Walk-forward artefacts
stamp the equation flags as before, plus `synthetic_lambda_active`.

Test suite at close: **113 passed, 5 skipped** (skips = the dormant
`walkforward_h6_2526.parquet` fingerprint guards, pre-existing).

---

## 2. NEW FILES, one by one

### squad/synthetic_lambda.py (D4 Phase 2 serving path — gated OFF)
- `SYNTHETIC_LAMBDA_ACTIVE = False` — the gate. Header carries the full
  Phase-2 negative verdict so nobody re-flips it blind.
- `get_synthetic(predict_season, cutoff_date, fixtures)` → per-fixture
  `syn_lam_h/syn_lam_a` for UNPRICED fixtures. Serving design (fixed by the
  horizon study): ONE fresh-trained LightGBM per cutoff (pre-registered
  Phase-1 config, trained on `data/d4_market_lambda_dataset.parquet`
  non-burn-in rows with `match_date < cutoff`), fed per-horizon FROZEN
  features: market-history windows < cutoff; DC params from the cached
  per-GW fit (`data/history/d4_dc_walkforward_params.parquet`, selected as
  max cache cutoff ≤ cutoff_date); availability at the CUTOFF gw's asof
  deadline; schedule/is_home from the target's calendar row.
- `ALIAS` = the 3-entry odds→vaastav name map (Man United, Sheffield United,
  Tottenham) — applied internally.
- Module-level caches `_CACHE`/`_MODELS`. Backtest scope only (dataset ends
  2025-26); live 2026-27 use needs a dataset extension.

### eval/build_market_lambda_dataset.py (D4 Phase 1 dataset)
Target: `market_lambda` per team-match (7,600 rows, 10 seasons) via
`squad.dixon_coles._implied_lambdas` (production-identical inversion,
round-trip verified 1.8e-4). 19 features in five blocks; strict windows
(min_periods=window); burn-in FLAGGED not deleted; per-block leakage AUDIT
COLUMNS + `assert_no_leakage()` (strictly-before-match-date on every row);
per-team-and-frame-grain fallback guards (the #14 lesson); availability NaN
carries its reason. DC refits per (season, gw) cached to
`d4_dc_walkforward_params.parquet` (379 cells; 2022-23 GW7 has no matches).

### eval/measure_market_lambda.py (D4 Phase 1 study)
Expanding-window walk-forward by season; tuned 2017-18..2024-25 only;
selection rule pre-stated; `--holdout` REFUSES to run without a
`PRE-REGISTERED: {json}` line in Logs/d4_market_lambda_log.md and takes its
config FROM the log (first occurrence that parses as JSON — prose mentions
of the marker are skipped).

### eval/audit_market_lambda_leakage.py (independent audit)
Checks 1–7: shuffle (ρ→~0 ✓), bit-exact 5-fixture hand reconstruction
(4.4e-16 ✓), single-feature R² (max 0.505 ✓), time reversal (NOT CLEAN —
size confound, recorded), gap test (0.79 vs 0.876 ✓), DC cutoff from raw
dates (10/10 ✓), availability asof-vs-deadline (0 violations in ~87k ✓).

### eval/measure_market_lambda_horizon.py (staleness study)
Step k freezes everything at the gw k−1 POSITIONS before the target
(positions, not labels — 2019-20's 39–47 relabelling). Result: fresh-trained
beats stale-trained at every step; model edge over equally-stale DC flat at
~+0.10 R² for steps 1–6.

### eval/measure_synthetic_lambda.py (D4 Phase 2 measurement)
Before/after pairs canonical vs `*_synth`. Provenance gate (stamps must
match except the flag under test — this CAUGHT the wrong-writer 2025-26
build), step-0 bit-exactness (max |diff| 0.0 over 8 columns ×3 seasons),
ρ/MAE by step ×2 pools, per-position starter ρ, margin β (through-origin
pairwise, moment accumulation, per (cutoff, position)), per-step top-k with
paired resolution, horizon-sum top-k, agreement. Optional season args.

### eval/run_transfer_sweep.py + eval/measure_transfer_sweep.py (D4 sweep)
54 sims: H {3,4,6} × decay {0.30,0.45,0.60} × base/synth × 3 seasons,
policy=mip, no chips. Resumable: one parquet per config under `data/sweep/`
(skip-if-exists, atomic write), lists stored as JSON strings. Endpoints:
E1 corr(pred gain, real gain) — pred = decayed H-window sum at the
transfer's cutoff from the SAME file the config planned on; E2 realized
gain per transfer (undecayed H-window, truncation flagged); E3 activity;
E4 declined-transfer gains on a fixed 3-gw yardstick. Also writes
`data/sweep/transfer_table.parquet` (2,967 transfers).

### eval/poll_availability.py (D6 free half — built, PARKED)
Deadline-aware bootstrap-static poller. Schedule from the API's own
`events` (30 min from deadline−4h, 10 min final hour, one post-deadline
poll enabling the exact `late_news` recovery rule build_availability uses).
`--once` tick model (cadence-gated vs newest raw file — any scheduler
frequency safe, sleep/reboot idempotent), `--watch`, `--build` (derived
table with columns/dtypes IDENTICAL to `availability_{season}.parquet`,
asof_source `live_snapshot`/`live_late_news` so archives can never silently
mix), `--status`. Raw-first gzip archive `data/live/bootstrap_raw/<season>/`
temp-then-rename. Change detection → `availability_changes_<season>.parquet`
with minutes_to_deadline. Schema-drift asserts name the missing field;
unknown status letters raise. Reconciliation policy in
Logs/d6_live_availability_log.md §5; GW1 2026-27 smoke-test checklist §8.

### eval/run_chip_study.py (P4 driver, three phases)
- `CONFIGS` — individual chips (22 sims; BB/TC exogenous, read off logs).
- `PHASE2_CONFIGS` (--phase2) — bench-aware re-measure + combined d85/d60.
- `PHASE3_CONFIGS` (--phase3) — the adopted-config package at d=0.45.
- `--only` for disjoint parallel workers; skip-if-exists resumable; atomic
  writes; `--phase2/--phase3` flip `BENCH_BOOST_AWARE` in-process (now moot
  — gate is True on disk).
- `run()` asserts PRE-CHIP PREFIX IDENTITY vs the baseline log. Boundary
  subtleties (both were real bugs, both fixed): (a) decay-overridden configs
  can't assert vs the d85 baseline — skipped, checked at measurement vs the
  own-family baseline; (b) bench-awareness diverges at `bb_gw − (H−1)`, so
  the identity boundary is `min(chip gws, bb−H+1)` and measurement reports
  the pre-positioning window separately.

### eval/measure_chip_study.py / measure_chip_phase2.py / measure_chip_d45.py
Phase-specific measurement: W-window paired deltas (W ∈ 1,2,3,5) at chip
anchors; BB = `bench_points` at the chip week off the relevant log; TC =
`captain_bonus`; staging increment; pkg/all-chips derived rows; margins vs
average manager (claimed AND fplcache-derived); NO intervals anywhere
(n_active ≤ 3 < the ≥8 rule). Filename-parse trap fixed: config name =
`stem.split("_", 3)[-1]`.

### eval/build_season_totals_index.py → Logs/season_totals_index.md
Every season total ever produced (89 rows: 31 chips + 54 sweep + 4
references) with config, wf file, provenance family, build date, both
margin columns, and the EXHAUSTIVE valid-comparison list. References
(1984/1938/2028/2060) are comparable to nothing.

### Tests
- `Tests/test_dc_hits_wiring.py` — #15 guard: canonical 2025-26 p_dc_hit
  max > 0.2 and DEF nunique > 100; pre-rule seasons return empty typed
  frame.
- `Tests/test_bench_boost_aware.py` — 6 property tests: gate-off inertness
  (kept valid for reproducing old runs), gate-on-no-step inertness,
  boost-week bench never worse (×3 seeds), boost-weight locality to its
  step. Fixture restores whatever resting state it found.

### Rescued from the doomed scratchpad (handoff item A, partial)
`eval/d1_topk.py`, `eval/d1_agreement.py` — verbatim copies; they define
the top-k/agreement conventions the chip measurements follow.

---

## 3. MODIFIED FILES, one by one

### squad/transfer_mip.py
- `BENCH_BOOST_AWARE = True` (ADOPTED 2026-08-20). In `build_and_solve`:
  new param `bench_boost_step` (horizon index or None); objective's bench
  weight is per-step `wb_t = 1.0 if (gate and t == bench_boost_step) else
  w_bench`. Inert without a scheduled boost — ordinary solves byte-identical.
- `DEFAULT_DECAY = 0.45` (ADOPTED; mechanism-based rationale in the comment
  and P4 log §13). Docstring's decay example updated.

### squad/simulator.py
- `simulate_season(..., bench_boost_gw=None)` →
  `decide_gameweek_mip(..., bench_boost_gw=...)` → computes
  `bb_step = future.index(bench_boost_gw)` when inside the window →
  `build_and_solve(bench_boost_step=...)`.
- Decision-log rows now stamp `horizon`, `decay`, `bench_boost_aware`,
  `bench_boost_gw`.
- NOTE: BB/TC still change NO scoring inside the sim — they are exogenous
  reads (`bench_points`, `captain_bonus`); only the SOLVER is bench-aware.

### squad/optimize.py
- `_default_solver()` honours `FPL_SOLVER_THREADS` (HiGHS `threads=` param).
  Measured: 5 unthrottled parallel sims → 78 min/sim; capped at 2 with ≤6
  workers → 11–35 min. Unset = old behaviour.

### squad/dixon_coles.py (D4 Phase 2 — inert while gate False)
- imports `synthetic_lambda`; in `get_fixtures`, where odds are unusable AND
  the gate is on AND `cutoff_date` is not None, fills `mkt_lam_h/a` from
  `get_synthetic` and treats those rows as priced (λ pure synthetic, CS
  0.2·DC + 0.8·synthetic). New per-fixture `lambda_source` column
  (odds | synthetic | dc) in the return frame.

### squad/defensive.py (#15 fix — ADOPTED)
- `DC_RULE_SEASONS = {"2025-26"}`, `_DC_HITS_CACHE`, and
  `get_dc_hits(season, cutoff_gw, target_gws)` — THE shared path: the
  player's own cutoff-gw p_dc_hit frozen across the horizon; empty typed
  frame for pre-rule seasons or featureless early gws. Header documents the
  "DC" naming collision (defensive contribution vs Dixon-Coles).

### eval/walkforward.py and eval/walkforward_season.py
- BOTH now call `def_mod.get_dc_hits(...)` (walkforward_season previously
  passed an EMPTY frame even for 2025-26 → canonical files priced the DC
  rule at position base rates, max 0.136 — KNOWN_ISSUES #15, fourth
  silent-fallback incident).
- BOTH stamp `synthetic_lambda_active` from the gate constant.
- Note: the canonical LINEAGE is walkforward_season.py for ALL seasons
  (including 2025-26). walkforward.py remains 2025-26-only and correct, but
  building canonicals with it produces different stamps (no `season_label`/
  `train_seasons`/`dc_rule_active`) — the provenance gate catches the mix.

### Tests/test_bench_boost_aware.py + docstring
Updated for the adopted resting state (True); gate-off behaviour still
tested via in-process flip.

---

## 4. RESULTS OF RECORD (details in the logs)

- **D4** (Logs/d4_market_lambda_log.md, closed §13): Phase 1 GOOD as a
  model (sealed R² 0.851 vs DC 0.595; +0.10 edge at all horizon steps;
  audit passed). Phase 2 NO pipeline benefit on three grains (accuracy
  flat; top-k ≤ chance; per-decision corr 0.301 base vs 0.264 synth; sign
  test 11–16 p=0.44). Durable mechanism: forward-step decay is
  minutes/form-driven, not fixture-driven. β structure (MID/FWD→1, GK/DEF
  away, 60/60 cells) = GK-investigation H1 signature.
- **#15** (KNOWN_ISSUES): canonicals rebuilt; 2023-24/2024-25 bit-identical
  (dc off); 2025-26 new step-0 baseline ρ 0.7471 / MAE 1.0732, starter-band
  GK .190 DEF .285 MID .214 FWD .157. Pre-fix files preserved `*_dcbase`.
- **P4** (Logs/p4_chip_policy_log.md §12 ADOPTED): rules of record per chip
  (WC1 GW4–5 policy; WC2 pre-DGW swing; BB2 biggest double ≥4 floor,
  bench-aware; FH2 biggest blank ≥4 floor, NEVER below (−20); TC2 biggest
  DGW; TC1 captain-prediction peak +10.3; BB1 only on a real H1 double).
  d45 package: +78 / LOSES 2024-25 / +67 chip-inclusive.
- **Bench-aware BB**: unaware +2.3 → aware packages +25/−20/+31 (d85) and a
  46-pt boosted bench (2023-24 d45). Failure mode on record: loads the
  bench but pays more in XI when predictions are wrong at the reshuffle.

---

## 5. ANALYSES (read-only; scripts in the session scratchpad, findings in chat/logs)

1. **Season-totals index** — Logs/season_totals_index.md (generator in
   eval/). Average-manager verification: fplcache sum(average_entry_score)
   = 2003 / 2008 / 1895 vs claimed 2038 / 2154 / 1895 — 2024-25 differs by
   146; definitions differ (sum of per-GW means ≠ mean of totals); BOTH
   margins carried everywhere.
2. **GW-by-GW table** (2025-26 d45): like-for-like ends GW3; +49 peak at
   GW5 → −18 trough GW18 (wildcard decay) → endgame chip cluster rebuilds
   to +30 final.
3. **Late-news cost** (3 seasons, d45 baselines): 52 cases predicted≥60min/
   played 0. ZERO were flags the model ignored; ZERO are D6-catchable in
   backtest (BY CONSTRUCTION — the backtest consumes asof = deadline truth,
   which is exactly what D6 supplies live; D6's value is live-backtest
   parity, ~42 flips/season). All 52 are post-deadline/rotation:
   unreachable by any polling; net ~29 pts/season + ~29 captain
   counterfactual. Route: predicted lineups (D6 paid / D5) or rotation
   modelling.
4. **Captaincy**: rule = pure argmax e_points in XI (vice = 2nd, armband
   auto-passes on 0 minutes). Hindsight gap 252/155/237 (~215/season);
   captain best-in-15 ~25% of weeks. NO alternative (p60×e_points,
   p_start≥0.85 filter, DGW-restricted, vice) wins across seasons. Gap
   tracks prediction quality (2024-25 best predictions → smallest gap).
   Verdict: mostly irreducible variance.
5. **WHY 2024-25 fails with chips** (LATEST FINDING — NOT yet folded into
   the P4 log; a §12 correction note is QUEUED): the standing
   "reshuffle-into-error via bad late predictions" diagnosis FAILS its
   premise — 2024-25's GW26–38 is its own best prediction block
   (ρ .327/MAE 2.31). The −244 decomposes: −6 (GW4–8), **−185 (GW9–27,
   chip-free drift)**, −53 (GW28–38). The second-half chip transfers were
   individually GOOD (+148 realized in-vs-out over 3-gw windows, 26%
   negative), and ISOLATED FH2/WC2 in 2024-25 measured POSITIVE (+18/+8).
   Revised mechanism: **early-wildcard branch divergence** — WC1@4
   compounding against the best baseline path anywhere (2362) — plus one
   genuinely negative bench-aware staging reshuffle. Headroom hypothesis
   (chips have nothing to add to a strong squad) NOT supported (headroom
   19.5/16.8/12.5 vs effects +53/−38/+30, no relation, n=3). Minutes misses
   among chip-ins: 6/31 (Son, Foden at 0% of next-3 gws ≥60) — real but
   minority.

---

## 6. ARTEFACTS ON DISK (all gitignored)

- Canonical: `walkforward_h6_{2023_24,2024_25,2025_26}.parquet` (post-#15).
- Preserved: `*_dcbase` (pre-#15), `*_presynth` (pre-D4-phase-2, ==
  canonical content at the time), `*_synth` (synthetic-λ builds, stamped
  True; 2025-26 rebuilt post-#15, others DC-irrelevant), plus the full D1/D2
  lineage from the previous handoff.
- D4: `d4_market_lambda_dataset.parquet`, `history/d4_dc_walkforward_params
  .parquet`, `sweep/simlog_*` (54) + `transfer_table.parquet`.
- P4: `chips/chiplog_*` (22 individual + 9 phase-2 + 3 pkg_d45 = 34).
- D6: `live/bootstrap_raw/2026-27/` (2 verification polls).
- Session scratchpad (analysis one-offs, logs of all runs):
  `C:\Users\veers\AppData\Local\Temp\claude\c--Users-veers-OneDrive-Documents-FPL-Agent\462998c5-482d-4f97-9e87-a4ee87aa6c62\scratchpad\`
  — the reusable pieces are already in eval/; the rest is disposable but
  contains run logs (stage1_builds, sweep_*, chips_*, p2_*, p3_*) and
  analysis outputs (gw_analysis, late_news_cost, captain_analysis,
  why_2425).

## 7. COMMIT STATE at handoff time

Earlier batches (D4 arc + #15 + D6 + sweeps) were proposed and left to the
user to commit. The final uncommitted batch: modified
`Handoffs/Progress_notes_2026-08-17.md`, `squad/optimize.py`,
`squad/simulator.py`, `squad/transfer_mip.py`; new `Logs/p4_chip_policy_
log.md`, `Logs/season_totals_index.md`, `Tests/test_bench_boost_aware.py`,
5 eval/ chip+index scripts, the two 2026-08-20 handoffs. Verified: no
parquet, no secrets, data/ ignored. Proposed message in chat (P4 adoption).

## 8. OPEN ITEMS FOR THE NEXT SESSION

1. **Fold the 2024-25 revision into the P4 log** (§12 correction note:
   diagnosis relocated from "late predictions" to "early-wildcard branch
   divergence"; isolated chips were positive there). The finding lives only
   in this handoff and chat until then.
2. **GW1 2026-27 poller smoke test** — deadline 2026-08-21 17:30 UTC,
   `--watch` from ~13:30 UTC; afterward checklist in
   d6_live_availability_log.md §8; then the fplcache diff (first real
   blind-window measurement).
3. **Pre-#15 figure corrections** in older logs (d1_log §8, GK log tables)
   — surface listed in KNOWN_ISSUES #15.
4. **GK investigation** (two live options; D4's β structure corroborates
   H1 from an independent intervention).
5. **2024-25 follow-up**: why did WC1@4 specifically send that season down
   a −185 branch? (Candidate: rotation-hardness — its minutes model is the
   weakest of the three; Son/Foden-class buys.) Also whether WC1 policy
   should carry a season-condition (NOT adopted; needs its own protocol).
6. Inherited: D2 cold start (~32% no-prior), M1 kill-criterion record,
   live-freeze decision, D5 spend decision, dormant 2526 fingerprint tests,
   XI split not persisted in decision logs (extend the log if analyses keep
   needing it).

## 9. TRAPS (delta over Handoff_2026-08-18 §12 — that list still applies)

- "DC" is overloaded: defensive.py (defensive contribution, p_dc_hit) vs
  dixon_coles.py (team goals). Name the module.
- `get_fixtures` works in ODDS names; synthetic_lambda and the d4 dataset in
  VAASTAV names; the 3-entry alias map is duplicated in both modules.
- Prefix-identity asserts: boundary must be `min(chip gws, bb_gw−H+1)` and
  same-decay-family only.
- HiGHS multi-threads by default → set `FPL_SOLVER_THREADS=2` for parallel
  sims (4 workers × 2 threads recommended).
- Bash background tasks die at ~10 min; detached Start-Process + log +
  Monitor for anything longer. Builders write only on completion.
- pandas: `row.name` in iterrows is the INDEX not the 'name' column;
  fplcache post-season snapshots must be picked by date window or you read
  the next season's zeroed bootstrap; console prints must be
  ascii-encoded (cp1252).
- The simulator scores NO chip points itself: BB/TC values are exogenous
  reads off `bench_points`/`captain_bonus`; season totals from chip runs
  are path totals, chip-inclusive totals = path + reads.
