# Handoff — 2026-08-26 session, FULL DETAIL (code-first)

**Covers everything in the session, in order:** the headroom diagnosis (read-only), the penalty-term
correctness fix (pre-registered, built, FAILED its bar), the season-anticorrelation check (pattern debunked),
the top-end level calibration (pre-registered, tuned, FAILED), the bonus-term three-arm study (rebuild FAILED,
DELETE won) and the pre-registered ADOPTION of `BONUS_MODE = "delete"` (PASSED; canonicals rebuilt), Triple
Captain 2 scheduled in-sim (first legal TC2 valuation), and the move of the reference figures of record to
2251 / 2306 / 2268. Companion documents: `Handoffs/Interim_project_closing_position_2026-08-21.md` (§2 live
config and §3 figures of record, both updated), `Handoffs/Handoff_2026-08-23_full_session_detail.md` (previous
session; its §9 traps still apply).

Test suite at close: **138 passed, 5 skipped** (the 5 skips are the dormant `walkforward_h6_2526` fingerprint
guards, pre-existing). Five commits: `4bdc0b2`, `d454cb3`, `0b98cf1`, `938432c`, `7553d69`. Working tree clean.
Nothing in `data/` is tracked.

---

## 0. TL;DR — what a reader needs in one screen

1. **One equation change was adopted: the bonus term is deleted** (`assembly.BONUS_MODE = "delete"`). The
   incumbent term ranked worse than nothing on the rows the optimizer picks from (ρ with realised bonus −0.02
   on starters, −0.09…−0.19 on the top 30) because a tree trained on integer outcomes was fed expectations and
   its level was manufactured by a per-gameweek renormalisation (KNOWN_ISSUES #20). Deleting it raised sliced
   rank on both decision partitions in every season (three-season mean +0.005 / +0.006), lowered starter MAE
   everywhere, and narrowed the cross-position error spread. **Known cost:** e_points now omits realised bonus
   (~0.26 per likely starter per week, forwards understated most). A low e_points level is this decision, not a
   defect. Canonicals were REBUILT under the gate; pre-adoption canonicals preserved as `*_prebonusdel.parquet`.
2. **Two correctness candidates were pre-registered, built gated, and NOT adopted:** the penalty term fix
   (`PENALTY_FIX_ACTIVE`, rests False — rank up everywhere, but Brier at the over-predicted top 30 and a
   mis-specified movers rule failed) and the top-end calibration (`TOPEND_CAL_ACTIVE` / `FIXTURE_SCALE_GAMMA`,
   rest False / 1.0 — the lever-1 trap: everything improved except squad-relevant rank). Both gates reproduce
   the pre-change equation bit-exactly when off.
3. **The measurement convention changed:** TC2 is now scheduled IN-SIM on the rule-of-record week (GW25 / GW24 /
   GW26), captain = the MIP's own `cap` at that deadline; the path is provably unchanged, so TC2 is exactly the
   extra captain multiple (+10 / +29 / +7). **Figures of record: path 2226 / 2249 / 2220, chip-inclusive
   2251 / 2306 / 2268, margins +248 / +298 / +373.** The old 2296 / 2294 / 2206 are the old convention (TC2
   scored zero, incumbent bonus term), superseded and flagged everywhere.
4. **The "2024-25 anti-correlates with the other seasons" pattern is debunked** (r = +0.26 the other way,
   opposite sign in 14/57 arms). What is real: 2024-25 loses on 78% of arms (mean −70) because its reference is
   a 97th-percentile draw, and Salah-held weeks explain r² ≈ 0.5 of that season's totals.

---

## 1. LIVE CONFIG — every gate, its location, value, stamp

| Constant | File | Value at close | Stamped as | Status |
|---|---|---|---|---|
| `D1_TERMS_ACTIVE` | squad/assembly.py | True | `d1_terms_active` | unchanged |
| `CS_UNIFIED` | squad/assembly.py | False | `cs_unified` | unchanged |
| **`PENALTY_FIX_ACTIVE`** | squad/assembly.py | **False** | `penalty_fix_active` | NEW; measured, NOT adopted (`Logs/penalty_fix_prereg.md`) |
| **`TOPEND_CAL_ACTIVE` / `FIXTURE_SCALE_GAMMA`** | squad/assembly.py | **False / 1.0** | `topend_cal_active` / `fixture_scale_gamma` | NEW; measured at γ = 0.2, NOT adopted (`Logs/topend_calibration_prereg.md`) |
| **`BONUS_MODE`** | squad/assembly.py | **"delete"** | `bonus_mode` | NEW; **ADOPTED 2026-08-26** (`Logs/bonus_delete_prereg.md`); values `incumbent` / `delete` / `outcome` |
| `_BONUS_CAPS` | squad/assembly.py | goals 3, assists 2, conceded 4, saves 8 | — | truncation for `outcome` mode; fixed by stated tail probabilities, not tunable |
| `RATE_BLEND_ACTIVE` / `_K` | squad/attacking_rates.py | True / 8.0 | `rate_blend_active` / `_k` | unchanged |
| `SYNTHETIC_LAMBDA_ACTIVE` | squad/synthetic_lambda.py | False | `synthetic_lambda_active` | unchanged |
| `BENCH_BOOST_AWARE`, `DEFAULT_HORIZON` / `DEFAULT_DECAY`, `HIT_COST` | squad/transfer_mip.py | True, 6 / 0.45, 4 | as before | unchanged |
| all P1/P3/P5/oracle/horizon/props gates | as before | all off / None | as before | unchanged |

**Canonical walk-forward files** `data/walkforward_h6_{2023_24,2024_25,2025_26}.parquet` were REBUILT
2026-08-26 under `BONUS_MODE="delete"` (stamp `bonus_mode == "delete"` on every row, plus
`penalty_fix_active=False`, `topend_cal_active=False`, `fixture_scale_gamma=1.0`). They are asserted
bit-identical on `e_points`, `e_points_core`, `exp_bonus` to `walkforward_h6_{season}_bonusdel.parquet` (the
canonical-with-identity frames used for the measurement). Pre-adoption canonicals:
`walkforward_h6_{season}_prebonusdel.parquet` — every reference-cell read (TC1 selection) is pinned to these
(see §3.7), so the old reference figures cannot move.

**Chip rules of record** unchanged (p4 log §12, §12b, §12c (ii)); TC2 is now priced in-sim on the 12c (ii)
week (p4 log §15). TC1 remains a post-hoc read (predicted-captain peak GW1–19 excluding chip weeks).

---

## 2. NEW FILES, one by one

### Logs (results of record)
- `Logs/headroom_diagnosis.md` — the diagnostic brief: attribution ledger, the 0.099 question (split-half
  reliability ceilings ≈ 0.31 / 0.33 / 0.20; current 0.22 / 0.22 / 0.13 among realised starters), ranked ideas.
  Carries a same-day supersession marker on §0: its read-only "penalty fix" deltas were computed from the
  stored `penalty_share` column, which turned out to be a same-season LEAK (see §3.1) — read the mechanism,
  not those numbers. Bonus findings unaffected.
- `Logs/penalty_fix_prereg.md` — pre-registration, results (FAIL), season figures.
- `Logs/season_anticorrelation_check.md` — the debunk; scratch table `data/penfix_logs/anticorr_deltas.csv`.
- `Logs/topend_calibration_prereg.md` — diagnosis by decile/position/fixture-tercile, form, tuning surface,
  PRE-REGISTERED VALUE `GAMMA = 0.2`, results (FAIL), penalty re-read on the calibrated pair (FAIL), season
  figures.
- `Logs/bonus_rebuild_prereg.md` — three arms (incumbent / DELETE / outcome-weighted rebuild), results
  (rebuild FAILS; DELETE beats incumbent → recommend delete), season figures.
- `Logs/bonus_delete_prereg.md` — the ADOPTION pre-registration and results (PASS), cost statement,
  position-structure check, season figures with itemised reads.
- `Logs/p4_chip_policy_log.md` §14 (equation-change note) and **§15 (TC2 in-sim, the first legal TC2
  valuation)** — appended, not new.
- `KNOWN_ISSUES.md` **#19** (penalty term never acted: rate × missed-penalty "team rate", same-season join,
  broken fallback) and **#20** (bonus renormalisation manufactured a level over a signal-free calculation).
- `Logs/d1_log.md` — dated correction under "penalty share moved nothing": that was the bug, not a finding.

### squad/assembly.py (the only model-code file changed)
- Constants: `PENALTY_FIX_ACTIVE`, `TOPEND_CAL_ACTIVE`, `FIXTURE_SCALE_GAMMA`, `BONUS_MODE`, `_BONUS_CAPS`,
  each with the finding written into its comment.
- D1 feature build (penalty share block): join year is `season_year - 1` when the penalty gate is on
  (`_pen_join_year`), else `season_year` (the pre-fix same-season join, kept bit-exact for reproducibility);
  gate-on fallback = mean prior-season pen-goal rate by FPL position, Understat label mapped by FIRST letter
  (F/M/D/G → FWD/MID/DEF/GK, GK forced 0); gate-off keeps the old label-mismatched fallback (0.05). The
  asm-level `fillna` is 0.0 (gate on) / 0.05 (gate off).
- `_finish_equation`:
  - `fixture_scale_cal = fixture_scale ** FIXTURE_SCALE_GAMMA` if `TOPEND_CAL_ACTIVE` else `fixture_scale`;
    `e_goals` and `e_assists` use `fixture_scale_cal`; `fixture_scale_cal` added to `MEAN_COLS`.
  - Penalty term: `e_pen_goals = penalty_share * minutes_frac` (gate on) or
    `penalty_share * team_pen_rate * minutes_frac` (gate off, the pre-fix form); `e_goals = npxg90 *
    minutes_frac * fixture_scale_cal + e_pen_goals`; `e_pen_goals` added to `SUM_COLS` so the term's level is
    auditable on every artefact (as-built it sums to ~1 per season; corrected 45–67).
  - Bonus block: `BONUS_MODE == "outcome"` → `_bonus_outcome_weighted(...)` (E[BPS], E[bonus] by enumerating
    goals 0–3 × assists 0–2 × conceded 0–4 (clean_sheets = 1{c = 0}) × GK saves 0–8, independent truncated
    Poissons on the equation's own rates via `_trunc_poisson`, tails folded into the caps; 60 tree evaluations
    per outfield row, 540 per GK row), `exp_bonus = E[bonus] * minutes_frac`, NO per-gameweek renormalisation;
    `"delete"` → `exp_bonus = 0`, `e_points = e_points_core`; `"incumbent"` → the original code path
    unchanged (tree at expectations, then `exp_bonus * bonus_mean / gw_mean`).
- New module-level helpers: `_trunc_poisson(mu, cap)`, `_bonus_outcome_weighted(a, bps_input, bps_model,
  bps_to_bonus, BPS_FEATURES)`.

### eval — builders (each flips a gate IN-PROCESS and restores it in `finally`; canonicals never written)
- `eval/run_penalty_fix.py` — `--season S` builds `walkforward_h6_{tag}_penfix.parquet`; `--check --cutoff 20`
  rebuilds one cutoff gate-OFF and asserts bit-exact vs canonical (max |Δ| 0.0 on 9 columns, 4,401 rows).
- `eval/tune_topend_cal.py` — γ grid {1.0 … 0.0} from STORED canonical columns (no rebuild; bonus held at
  canonical), selection rule = min |ratio_high − 1| + |ratio_low − 1| on the fixture-scale terciles of the
  likely-starter top quintile, pooled over 2023-24 + 2024-25; prints the surface and the selection.
- `eval/run_topend_cal.py` — `--arm cal | cal_penfix`; reads `GAMMA = …` from the LAST `## PRE-REGISTERED
  VALUE` section of the prereg (`registered_gamma()`); **REFUSES to build 2025-26 without that line** and
  refuses `--gamma` overrides for 2025-26; `--check` = gates-off bit-exact reproduction.
- `eval/run_bonus_rebuild.py` — `--arm bonusow` (outcome mode, in-process) or `--arm bonusdel` (no rebuild:
  canonical with `e_points := e_points_core`, `exp_bonus := 0`, `bonus_mode := "delete"`, after asserting the
  identity `e_points == core + exp_bonus`); `--check` = incumbent-mode bit-exact reproduction.
- `eval/run_arms_full_system.py` (MODIFIED) — new arms `penfix`, `cal`, `cal_penfix`, `bonusow`, `bonusdel`
  whose walk-forward frames live in `data/` (not `data/arms/`); asserts the frame's stamps match the arm;
  **`--tc2 <gw>`** schedules Triple Captain 2 in-sim (passes `triple_captain_gw` to `simulate_season`; output
  `armlog_{tag}_{arm}_tc2.parquet`; stamps `tc2_gw`; asserts the week holds no other chip and is ≥ 20; TC2
  included in `check_chip_schedule`). The armlog's `arm` column stays the BASE arm; the `_tc2` variant is
  identified by filename and `tc2_gw > 0`.

### eval — measurements (each reads the pre-registered partitions on the incumbent's own view)
- `eval/measure_penalty_fix.py` — §4 of the penalty prereg exactly: conditions 1–5, decile/outcome-band
  tables, league-wide pen-goal sanity, npxG-source double-count check (`npxg_source_check()` reads
  `understat_matches_2024_25.parquet` and asserts npxG < xG − 0.5 on every converted-penalty row and that
  `attacking_rates.py` reads the `npxG` column), top-30 movers by name with prior-season pen goals via the
  crosswalk. `--calibrated` re-reads the same §4 on `_cal` vs `_cal_penfix`.
- `eval/measure_topend_cal.py` — §4 of the calibration prereg; `--holdout` adds 2025-26 and REFUSES without the
  value line; reports both penalty states.
- `eval/measure_bonus_rebuild.py` — three arms on the same rows; §5 decision rule printed.
- `eval/measure_bonus_delete.py` — the adoption bar (rank, MAE, position-error spread, within-position rank,
  levels by position); asserts every DELETE row is stamped.
- `eval/measure_tc2_insim.py` — compares `_bonusdel_tc2` vs `_bonusdel` gameweek by gameweek (squads,
  transfers, captains must be identical), isolates the TC2 read, prints the deadline captain and the top-3 by
  step-0 e_points at that cutoff, legality with TC2 + TC1.
- `eval/measure_arms_full_system.py` (MODIFIED) — labels for the new arms; `cap_pred_arm` reads the arm's own
  frame for TC1 selection; reference reads via `_ref_wf_path` (§3.7).
- `eval/build_season_totals_index.py` (MODIFIED, see §3.8).

### Tests
- `Tests/test_penalty_fix.py` — `test_gate_off_is_prefix_form`, `test_gate_on_drops_team_factor_only`,
  `test_gate_rests_false_on_disk`, `test_topend_gate_off_is_identity_and_on_applies_gamma`,
  `test_bonus_modes` (incumbent unchanged; delete → core; outcome with a constant tree gives exactly
  `1.0 × minutes_frac`, i.e. the outcome weights sum to one; asserts `BONUS_MODE == "delete"` at rest),
  `test_trunc_poisson_folds_tail`, `test_canonical_bonus_mode_stamp_matches_code` (the `d1_terms_active`
  pattern on all three canonicals).

### Scratch (session-only, not in the repo)
- `data/penfix_logs/` — every build/sim log and the measurement outputs of record
  (`measure_penalty_fix.txt`, `measure_penalty_fix_calibrated.txt`, `tune_topend_cal.txt`,
  `measure_topend_cal.txt`, `measure_bonus_rebuild.txt`, `measure_bonus_delete.txt`, `measure_tc2_insim.txt`,
  `measure_arms_*.txt`, `anticorr_deltas.csv`) plus the orchestrator shell scripts. Gitignored; copy anything
  needed into `Logs/` before relying on it.

---

## 3. WHAT WAS DONE, in order, with the code that did it

### 3.1 Penalty term (commit `4bdc0b2`) — pre-registered, built, FAILED
Verified at source before pre-registering: `penalty_share = (goals − npg)/(games+1)` is a per-game pen-goal
RATE, not a share; `team_pen_rate = Σ penalties_missed / gw_count` (league totals 11 / 14 / 15; series mean
0.02); the Understat join used `season_year == understat_season` and Understat labels 2025-26 as "2025" → the
SAME season (a leak the ×0.02 hid); the position fallback grouped on Understat labels ("F M S") mapped from
FPL labels → matched only GK → **28.9% of rows carried the hard-coded 0.05**. League-wide predicted pen goals as
built: 1.3 / 0.9 / 1.4 vs 96 / 69 / 77 realised.
Fix (gated): drop the team factor, prior-season join, first-letter fallback. Result: pen goals → 45 / 67 / 49;
rank +0.004 / +0.004 / +0.003 likely, **+0.006 / +0.017 / +0.009** squad-relevant; movers = the takers (Palmer
+40.7, Haaland +26.1, Salah +24.9 …). **FAIL** on condition 3 (Brier on the top 30 +0.0024 / +0.0013 vs cap
0.001 — the top 30 was already over-predicted on goals, 0.31–0.33 vs 0.21–0.22) and on the 2023-24 movers rule
(≥ 3 prior pens mis-specified for a 74-penalty prior year; the list is nine takers and Ødegaard). Re-read on
the calibrated pair (§3.3) still FAILS (2025-26 Brier +0.0011, movers 3/10 and 5/10).

### 3.2 Season anti-correlation check (in `d454cb3`) — debunked
60 three-season arms from the index + the penalty arm; deltas vs each family's reference. 2024-25 vs mean of
others: Pearson **+0.26** (perm p 0.044), opposite sign 14 / 57 (p < 0.001 the OTHER way); 2023-24 +0.29;
2025-26 +0.19; family level nothing; without the sweep +0.55 / +0.38 / +0.22. Real facts: 2024-25 negative on
78% of arms (mean −70 vs −24 / −14) = the 97th-percentile reference; Salah-held weeks correlate +0.71 with the
path total across 49 2024-25 logs (34 weeks → 2183–2385; ~26 weeks → 2057–2195).

### 3.3 Top-end calibration (commit `d454cb3`) — pre-registered, tuned, FAILED
Diagnosis (read-only): LS top decile over 1.34 / 1.40 / 1.28 (season-stable); within the LS top quintile the
over-prediction tracks fixture_scale (high tercile 1.39 / 1.67 / 1.47, low 0.94 / 1.09 / 0.83); assists same
signature; CS not stable. Form: `fixture_scale ** γ` on both attacking terms. Tuning (stored columns, 2023-24 +
2024-25) selected **γ = 0.2**; the pre-registered-value entry recorded, BEFORE the sealed measurement, that the
information columns already showed squad-relevant rank falling (−0.086 / −0.042) and spread compressing to
0.63. Full rebuilds confirmed: rank FAILS in both tuning seasons, spread 0.60–0.72 (< 0.85 floor) everywhere,
level halfway-closure fails in two seasons; 2025-26 (sealed, once) passed rank only. The lever-1 trap exactly:
the form strips the market's fixture information from premiums. The residual top-end error is mostly the
SELECTION component (winner's curse), not fixture scaling.

### 3.4 Bonus term — three arms (commit `0b98cf1`) — rebuild FAILED, DELETE won
Incumbent: tree at expectations + per-gw renormalisation. DELETE: `e_points_core` (identity on the canonical).
REBUILD: outcome-weighted (§2). Result: rebuild carries signal (ρ with realised bonus on starters +0.14 / +0.17
/ +0.13; FWD top-30 ratio 0.30–0.48 → 0.66–1.04) at **a quarter of the true level** (0.06–0.08 vs 0.29) because
the renormalisation that propped the incumbent was dropped and tree + curve at integer outcomes sit near zero
(reliability deciles slope ~1, intercept ~−0.15); MID/DEF/GK under-credited; 2025-26 squad-relevant −0.012 vs
DELETE. DELETE beats the incumbent +0.008 / +0.003 / +0.004 likely, +0.012 / +0.007 / −0.003 squad. A level
scalar/floor would be a fitted component → excluded in advance, named for a future pre-registration.

### 3.5 Bonus DELETE — adoption (commit `0b98cf1`) — PASS
Own pre-registration; conditions: rank ≥ −0.003 both partitions every season and mean > 0 (PASS: means
+0.0050 / +0.0055); starter MAE not worse (PASS: 2.283 → 2.223, 2.202 → 2.158, 2.342 → 2.327); position-error
spread across FWD/MID/DEF on likely starters not wider (PASS: 0.57 → 0.47, 0.74 → 0.65, 0.53 → 0.44). Cost
recorded: e_points on likely starters 3.33 / 3.32 / 3.48 → 3.02 / 3.04 / 3.18 vs realised 3.04 / 3.05 / 3.42;
forwards now the most understated position (−0.3 to −0.6 per week), keepers still over. Adoption steps:
constant flipped; canonicals rebuilt (`walkforward_season.py --season S --horizon 6`, ~40 min in parallel);
asserted equal to the `_bonusdel` frames (max |Δ| 0.0); `_prebonusdel` preserved; provenance test added;
closing position and p4 log §14 updated.

### 3.6 TC2 in-sim (commit `938432c`) and the reference move (commit `7553d69`)
`--tc2` on the bonusdel arm at GW25 / GW24 / GW26 (12c (ii) from the calendar on the delete frames).
Captain = the MIP `cap` variable at that deadline (argmax step-0 e_points in the XI, cutoff predictions only);
verified Haaland 15.22 ×2, Salah 15.85 ×2, Gabriel 11.61 ×2 — each the squad's top-rated player that week,
each doubling. Squads, transfers and captains identical to the delete arm in all 38 gws × 3 seasons; per-gw
point differences exactly at the TC2 week (+10 / +29 / +7). Legality PASS with TC1 + TC2. Figures of record
moved to **2251 / 2306 / 2268** (path 2226 / 2249 / 2220); closing position §3, index header and reference
cells, dated markers on every log quoting 2296 / 2294 / 2206 as current.

### 3.7 The reference-read pin (`_ref_wf_path`) — a trap that was avoided
`measure_full_system.py`, `measure_arms_full_system.py`, `measure_p5.py`, `measure_teamnews_knowable.py`,
`build_season_totals_index.py` all pick the reference cells' TC1 week from the CANONICAL predictions. After the
bonus adoption changed the canonical, that read would have silently moved 2296 / 2294 / 2206 (the same
silent-fallback shape as #16). Each now calls `_ref_wf_path(tag)`, which prefers
`walkforward_h6_{tag}_prebonusdel.parquet` when it exists. **Any new measure script that reads reference-cell
predictions must do the same.**

### 3.8 Index generator changes (`eval/build_season_totals_index.py`)
`EXPECT_ARMS_CHIP` extended to every 2026-08-26 arm (drift check); `EXPECT_REFERENCE_CHIP = 2251/2306/2268`
asserted on the `bonusdel_tc2` rows; `ARM_LABEL` / `ARM_WF_IN_DATA` for arms whose frames live in `data/`;
`tc_weeks_insim()` replaces the old "no in-sim TC ever" assert — allowed ONLY on `bonusdel_tc2`, every other
family still asserts none; `row()` takes `tc_insim` for the legality check and never ADDS a `TC2 in-sim` read
(it is inside the path; listed for the record); the `_tc2` filename suffix is folded into the arm name; old
`fslog base_wc2` rows flagged "SUPERSEDED AS REFERENCE CELL"; header/footer/valid-comparisons updated. Output:
232 rows, every row passed `check_chip_schedule`.

---

## 4. RESULTS OF RECORD (season figures, all under the standing framing)

| arm | 2023-24 | 2024-25 | 2025-26 | status |
|---|---|---|---|---|
| **reference of record: bonus delete + TC2 in-sim** | **2226 / 2251** | **2249 / 2306** | **2220 / 2268** | figures of record (path / chip-incl) |
| old reference (fslog base_wc2; incumbent bonus, TC2 zero) | 2278 / 2296 | 2255 / 2294 | 2156 / 2206 | SUPERSEDED as reference |
| bonus delete, TC2 zero | 2216 / 2241 | 2220 / 2277 | 2213 / 2261 | adopted model, old TC2 convention |
| bonus rebuild (outcome) | 2243 / 2280 | 2268 / 2312 | 2044 / 2094 | NOT adopted |
| penalty fix | 2256 / 2291 | 2347 / 2408 | 2085 / 2139 | NOT adopted |
| top-end cal γ=0.2 | 2215 / 2265 | 2247 / 2298 | 2058 / 2111 | NOT adopted |
| cal + penalty fix | 2221 / 2286 | 2366 / 2399 | 2100 / 2135 | NOT adopted |

Chip reads for the reference of record: BB1 +17 / +17 / +12, BB2 +2 / +31 / +20, TC1 +6 / +9 / +16 (GW6 / 18 /
17), TC2 +10 / +29 / +7 (GW25 / 24 / 26, in the path). 2024-25 Salah held / captained: reference 34 / 26;
bonusdel 34 / 25; bonusdel_tc2 34 / 25; penfix 34 / 23; cal 30 / 27.

Component results of record are in the four prereg logs (§2). Nothing above adjudicated an adoption.

---

## 5. MEASUREMENT CONVENTIONS ESTABLISHED THIS SESSION

- **Decision partitions are the endpoint**: likely starters (own-cutoff `p_start ≥ 0.75`) and squad-relevant
  (top 30 by the INCUMBENT's `e_points` within gameweek), single-fixture step-0 rows joined to vaastav by
  `(element, gw)`; Δ Spearman ≥ −0.003 per season is the "not worse" floor. Three candidates with better
  Brier / level / aggregate metrics failed on these partitions in one session; do not skip them.
- **A correctness fix gets its own bar, stated first**: not the +0.020 feature bar, but "not worse where
  decisions are made, and the level sanity target lands" — with revert triggers named (penalty prereg §4).
- **Level parameters by calibration, never by rank; then rank as the test** (calibration prereg §3/§4). A
  pre-registered value entry may — must — record what the information columns already show before the sealed
  measurement runs, so a FAIL cannot be called a surprise.
- **Adoption is its own pre-registration** with a cost statement (bonus delete §3) and a structural check that
  can stop it (§4 position spread).
- **DELETE arms are decisive controls**, not formalities.
- **Every reference-cell read goes through `_ref_wf_path`** (§3.7).
- **TC2 is scheduled in-sim** on the 12c (ii) week for any new full-system arm; compare to `bonusdel_tc2`.
- **Level sanity against a known total** before accepting "inert" (#19's lesson: the penalty term summed to 1
  vs 96 realised while being reported as "moved nothing").
- **`vaastav xP` is leaky** (ρ 0.5–0.55 with realised among starters); never a benchmark.

---

## 6. ARTEFACTS ON DISK (all gitignored)

- Canonicals (bonus_mode=delete, rebuilt 2026-08-26): `data/walkforward_h6_{2023_24,2024_25,2025_26}.parquet`.
- Pre-adoption canonicals: `*_prebonusdel.parquet` (the reference-read source).
- Arm frames in `data/`: `*_penfix`, `*_cal`, `*_cal_penfix`, `*_bonusow`, `*_bonusdel` (== canonical).
- Decision logs in `data/arms/`: `armlog_{season}_{penfix,cal,cal_penfix,bonusow,bonusdel,bonusdel_tc2}.parquet`
  (plus the earlier props/hmin/both/baseline8).
- Scratch: `data/penfix_logs/` (see §2).

---

## 7. OPEN ITEMS FOR THE NEXT SESSION

1. **Penalty term, still broken in production** (`PENALTY_FIX_ACTIVE=False`): the equation still believes
   nobody takes penalties. The corrected form is right in level (45–67 pen goals vs ~1) and improves rank
   everywhere; it failed on Brier at the over-predicted top 30 and on a mis-specified movers threshold. Path
   forward: re-pre-register condition 5 (e.g. ≥ 2 prior pens, or top-5 by prior pens present) and either accept
   condition 3 as a level trade or fix the top-end selection component first. Do NOT amend the existing §4.
2. **Top-end over-prediction is real and unaddressed** (top-30 e_goals 1.4–1.6× realised); it is mostly
   winner's-curse selection, not fixture scaling. The next candidate (its own pre-registration): shrink
   `e_goals` toward the within-position prior as a function of rank within the gameweek — acts on the selection
   component without discarding fixture information.
3. **Bonus term absent**: e_points understates forwards by ~0.3–0.6/week relative to defenders. The
   outcome-weighted machinery (`BONUS_MODE="outcome"`) carries signal at a quarter of the level; a level scalar
   or floor, or a curve rebuilt on the integer-outcome grid, is the starting point — fitted component, new
   pre-registration; judge it first on whether it closes the FWD/DEF gap and beats DELETE.
4. **Re-test props against the corrected equation** ($0, data on disk): the market prices penalties and bonus;
   the +0.02 squad-relevant gain may have been those.
5. **Other measure scripts** (`measure_p3.py`, `measure_chip_*`, teamnews scripts) that read canonical
   predictions for reference reads should be checked for `_ref_wf_path` if they are ever re-run.
6. **Index generator**: `EXPECT_*` dicts must be extended when any new arm lands, or generation fails on
   drift (by design).
7. Inherited and unchanged: D6 GW2 retry (Friday 2026-08-28, 09:30–13:30 LOCAL), live-freeze decision, D2
   cold-start third, KNOWN_ISSUES #17 (Kroupi doubled e_minutes) and #18 (p_play_any 0.30 floor), dormant
   2526 fingerprint tests.

---

## 8. TRAPS (delta over the 2026-08-23 handoff §9 — that list still applies)

- **`bonus_mode` changed the canonicals.** Any log figure produced before 2026-08-26 was on `bonus_mode=
  incumbent`; the preserved `_prebonusdel` files reproduce them. Stamps must match on everything except the
  variable under test before any comparison — `bonus_mode` is now in that list.
- **Reference-cell chip reads read predictions** (TC1 week). Always via `_ref_wf_path`; a plain canonical read
  moves the old reference figures.
- **The Understat season label is the START year** ("2025" = 2025-26). This bit the penalty join; it will bite
  any prior-season join written as `season_year == understat_season`.
- **Position fallbacks must use FPL labels** (GK/DEF/MID/FWD), not Understat's ("F M S"). Map by first letter.
- **`d.flags` is a pandas attribute** — name a column anything else (it broke a parse this session).
- **Bash heredocs with backticks/`'''` in this harness can fail to parse**; write long patch scripts to a file
  and run them.
- **`armlog_*_tc2.parquet` carries the BASE arm in its `arm` column**; identify TC2 runs by filename and
  `tc2_gw`.
- **The simulator's TC flag touches scoring only**; a scheduled TC never changes a decision, which is why the
  path is provably unchanged — but also why the MIP cannot plan FOR a TC week. If a TC-aware objective is ever
  built, the path will move and the read stops being separable.
- **Season totals moved ±55 in opposite directions on identical chip weeks** (bonusdel −55 / +55): that is the
  noise the record describes; never read it as a season-specific effect.
