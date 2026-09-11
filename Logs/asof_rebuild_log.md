# As-of rebuild log — 2026-09-11: the guard, three leaks closed, the record rebuilt

Companion records: `LEAKAGE.md` (audit of 2026-09-11 and its closure section), `KNOWN_ISSUES.md` #22 / #23 / #24,
`Logs/model_inventory_log.md` (the inventory that surfaced #22). Code: `eval/asof_reconstruction.py`,
`Tests/test_asof_reconstruction.py`, `squad/minutes.py`, `squad/horizon_minutes.py`, `squad/defensive.py`,
`squad/assembly.py`, `squad/live_deadline.py`, `eval/walkforward_season.py`, `eval/walkforward_arms.py`,
`eval/walkforward.py`.

## 0. The statement that governs every number below

**These are MODEL CHANGES, not repairs.** The record files built before this date carried three terms that were
conditioned on outcomes of the gameweek being predicted: the defensive-contribution term on realised appearance
(#22), the P(60+ | start) feature vector on the realised start (#24), and the goalkeeper saves feature at steps
1-5 on realised saves after the cutoff (#23). None of those is knowable at a deadline, so a live build could
never have reproduced the record. The fixed terms are the honest ones; they will not match the leaked figures,
and the deltas below are the correction working, not a regression. In every case the fitted MODEL is unchanged
(proven in section 3); what changed is which rows are scored and with what feature vector.

## 1. The guard — as-of reconstruction

`eval/asof_reconstruction.py`: for (season, cutoff k) every per-season input is cut to the deadline's information
set — the stack to gameweeks < k with a forward skeleton (the master's own rows for gameweeks >= k, every
measurement column nulled) for the rest; core-insights, Understat per-match rows and availability likewise; odds
results nulled for fixtures dated >= the cutoff and prices nulled beyond the last kickoff of gameweek k; and,
for the combined config, the horizon-minutes refit RECONSTRUCTED in-process from the truncated stack and injected
through `live_deadline.load_hmin_refit` (the single read of that file on the live path, refactored for this).
The frame is rebuilt through `live_deadline.build_deadline_frame` — the same entry point production uses — and
compared column by column, step by step, against the record rows for that cutoff. Outcome columns (`minutes`,
`actual_points`) are excluded and listed separately. A column that differs is reading post-cutoff information.

Why parity could not do this: `live_deadline` rebuilds a historical cutoff from the same on-disk inputs the
record was built from, with the target gameweek already played; both paths read the leak, so they agree.
Master plan §7.4 exhibit B (research path vs production path, same feature vector) is satisfied trivially
because they are one path here. This guard is the executable form of master plan §4.2.

## 2. Step 1 — the guard run on the UNFIXED code (before any fix)

2025-26, cutoffs 3 / 20 / 24 / 33 (24 spans the GW26 double; 33 is itself a double and spans GW36), both configs,
DC source pinned to `core_insights` (what the record was built under, so the source adoption of 2026-08-31 does
not contaminate the comparison). Row sets identical at every cutoff and step. Fifteen columns moved; cutoff 20,
baseline, rows differing at step 0 / step 5 and |delta| over differing rows:

| column | step 0 | step 5 | max abs | mean abs | source |
|---|---|---|---|---|---|
| p_dc_hit | 272 | 272 | 0.590 | 0.125 | item 6 (#22) |
| pts_dc | 272 | 272 | 1.001 | 0.174 | item 6 |
| saves_per_90 | 67 | 94 | 5.345 | 0.196 | items 7-8 (#23) |
| pts_saves | 67 | 91 | 1.337 | 0.041 | items 7-8 |
| team_pen_rate | 402 | 415 | 0.053 | 0.030 | item 8 |
| e_pen_goals, e_goals, pts_goals | 224 | 224 | 0.018 | 0.001 | item 8, downstream |
| **p60** | **214** | **214** | **0.189** | **0.045** | **item 9 (#24) — the third leak** |
| p_60plus, pts_appear | 214 | 214 | 0.146 | 0.029 | item 9, downstream |
| pts_cs | 193 | 193 | 0.195 | 0.018 | item 9, downstream |
| pred_bps | 0 | 15 | 2.776 | 1.076 | downstream (zeroed by BONUS_MODE) |
| e_points_core, e_points | 528 | 533 | 1.358 | 0.102 | all of the above |

Cutoffs 3, 24 and 33 showed the same fifteen columns with the same shape (cutoff 3: p_dc_hit max 0.077 — the
cold-start mean; cutoff 33 step 1 has fewer rows because GW34 is a blank for some clubs). Combined: identical at
step 0; at steps 1-5 the p60 family showed ZERO movement only because the refit was read from disk — which is
exactly why the guard was extended to reconstruct it before anything was fixed.

Columns that never moved: p_start, e_minutes, npxg90, xa90, team_lambda, opp_lambda, p_cs, fixture_scale,
penalty_share, the card rates, e_assists, pts_assists, pts_conceded, pts_cards, every stamp.

The third leak, verified at cutoff 20: all 214 moved `p60` rows started gameweek 20 (220 starters, 6 unmoved
with zero history), zero non-starters moved; p60 0.9361 (record) vs 0.8915 (as-of) on the moved rows,
likely starters signed −0.0292, max 0.1893. Mechanism: `minutes.py:118` (`sd = col[starts == 1]`) and
`minutes.py:292-295` (merge by (season, element, GW), fill 0); the same merge in `horizon_minutes._frames`.

## 3. The fixes, and the proof that the models did not move

| leak | fix | proof the fitted model is unchanged |
|---|---|---|
| #24 p60 | `minutes._build_frames` builds the starter-history block as of each gameweek on every row; `get_minutes` and `horizon_minutes._frames` read it from `cs`; the `starts == 1` merge is gone (one fix, both paths) | on all 30,162 start rows (the P(60+ \| start) training frame) the three features are bit-identical to the old construction, NaN pattern identical -> same training data, same model. Changed: 6,363 non-start rows in 2025-26 and 9,102 live rows now carry history |
| #22 DC | `defensive.get_dc_hits` -> `_score_cutoff`: train per position on all feature-bearing rows with gw < k (as before), score every player with a played row before k on his as-of feature row (`_asof_rows`, means over his last 3 / 5 played rows) | for every played single-fixture player at cutoffs 3 / 10 / 20 / 24 / 33 the new value equals the old path's bit-for-bit (262/262, 278/278, 272/272, 277/277, 213/213); only double-gameweek rows changed (65 of 152 at cutoff 33 — the same-gameweek artefact removed); 66 / 136 / 178 / 189 / 122 players who did not play are now scored instead of DC_BASE |
| #23 saves + aggregates | `assemble_fixtures(cutoff_gw=k)`: saves = mean of the last <= 5 rows with gw < k, frozen across the horizon; position fallback and `team_pen_rate` over rows with gw < k; passed by every writer and the live path | no model to preserve; step-0 single-fixture values are the same window as before |

## 4. The guard after the fixes

Both configs, cutoffs 3 / 20 / 24 / 33, the refit reconstructed in-process on BOTH sides for combined:
**every column bit-identical at every step, row sets identical, zero moving columns.** Wired into the suite as
`Tests/test_asof_reconstruction.py` (cutoffs 20 and 24, both configs, against the record files).

## 5. Rebuild

All three seasons: DC is zeroed in 2023-24 and 2024-25, but the saves freeze (goalkeepers, steps 1-5), the two
aggregates and the p60 fix (every position, step 0 and the refit) touch every season. Rebuilt in this order per
season, three seasons in parallel: horizon refit (`run_horizon_minutes --levers refit`) alongside the canonical
(`walkforward_season --horizon 6`) -> arm frames (`walkforward_arms --out-dir data/arms_gap0`; 2024-25 from
cutoff 8) -> armlogs on the record conventions (`run_arms_full_system`: gap0 --tc2 at the rule week, then
hmin_gap0 and both_gap0, with --tc2 26 for 2025-26 as the record). The live 2026-27 refit (cutoffs 1-3) was
rebuilt alongside. Every pre-rebuild artefact is preserved as `*_preasof.parquet` (canonicals, arm frames,
armlogs, refits). The 2025-26 rebuild is under the live DC source (`fpl_official`); the pre-rebuild record was
under `core_insights`, so its DC term differs for two reasons — the source adoption and the leak closure — and
section 3's equivalence check (old path vs new path under the SAME source) is what isolates the leak closure.

Arm frames reproduce their rebuilt canonicals exactly (no-hook rebuild vs canonical, max |Δ e_points| 0 over 38 /
31 / 38 cutoffs; hmin refit rows substituted 130,831 / 100,312 / 134,365-class, stale fallback 0). Suite after the
rebuild: **233 passed** (229 before + the four as-of guard tests), including every record-parity test against the
rebuilt files under the live DC source. Live: `live_deadline --strict --horizon 6` builds BOTH configs for
2026-27 GW3 (the last deadline with full inputs; GW4's props board is not yet pulled) with notes only, and the
"p_dc_hit sits at DC_BASE" note that fired on every pre-fix live build is gone.

## 6. RANK — sliced Spearman(e_points, realised points), step 0, before -> after

| season | config | likely starters (p_start >= .75) | squad-relevant (top 30 by e_points) | all rows | MAE realised starters |
|---|---|---|---|---|---|
| 2023-24 | baseline | 0.3292 -> 0.3242 (−0.0050) | 0.2384 -> 0.2357 (−0.0028) | 0.7235 -> 0.7226 | 2.267 -> 2.267 |
| 2023-24 | reference (hmin) | 0.3292 -> 0.3242 (−0.0050) | 0.2384 -> 0.2357 (−0.0028) | 0.7235 -> 0.7226 | 2.267 -> 2.267 |
| 2024-25 | baseline | 0.3037 -> 0.2969 (−0.0068) | 0.2164 -> 0.2199 (+0.0035) | 0.7371 -> 0.7355 | 2.180 -> 2.179 |
| 2024-25 | combined | 0.2958 -> 0.2874 (−0.0084) | 0.2055 -> 0.2104 (+0.0049) | 0.7358 -> 0.7340 | 2.181 -> 2.181 |
| 2024-25 | reference (hmin) | 0.2954 -> 0.2877 (−0.0077) | 0.2127 -> 0.2175 (+0.0049) | 0.7370 -> 0.7353 | 2.193 -> 2.193 |
| 2025-26 | baseline | 0.2231 -> 0.2099 (−0.0132) | 0.1574 -> 0.1654 (+0.0080) | 0.7466 -> 0.7454 | 2.340 -> 2.339 |
| 2025-26 | combined | 0.2290 -> 0.2148 (−0.0142) | 0.1540 -> 0.1368 (−0.0172) | 0.7473 -> 0.7461 | 2.331 -> 2.331 |
| 2025-26 | reference (hmin) | 0.2231 -> 0.2099 (−0.0132) | 0.1574 -> 0.1654 (+0.0080) | 0.7466 -> 0.7454 | 2.340 -> 2.339 |

(Step 0 of the hmin arm is the canonical, hence identical rows. 2024-25 rows are GW8-38 for the arms; the
combined and reference "before" files for 2025-26 were built under the core-insights DC source, the "after"
under fpl_official, so their DC term moved for two reasons — section 3 isolates the leak closure.)

Reading, under section 0: the likely-starter partition loses 0.005-0.014 of rank in every season and config. That
is the outcome information leaving. On that partition the OLD p60 correlated with the realised 60-minute outcome
at 0.32 and the fixed p60 at 0.19-0.20 (section 8) — the old value knew who had started. Aggregate rank and
starter MAE are flat. The top-30 partition is mixed (+0.004 / +0.008 baseline 2024-25 / 2025-26, −0.003 2023-24,
−0.017 combined 2025-26). No figure here is a regression to be recovered; the record before this date was scored
with information a deadline does not have.

## 7. THE THREE TERMS — before -> after on the canonicals, rows changed

2025-26 (165,401 rows, 6 steps):

| term | rows changed (step 0) | mean before -> after | mean \|Δ\| on changed | max \|Δ\| |
|---|---|---|---|---|
| p_dc_hit | 79,760 (14,417) | 0.1091 -> 0.1061 | 0.071 | 0.672 |
| pts_dc | 78,710 (14,417) | 0.0729 -> 0.0773 | 0.055 | 1.396 |
| saves_per_90 | 17,808 (2,510) | 0.0859 -> 0.0836 | 0.218 | 6.923 |
| pts_saves | 11,229 (1,338) | 0.0117 -> 0.0116 | 0.065 | 1.628 |
| p60 | 35,030 (6,529) | 0.8366 -> 0.8505 | 0.065 | 0.242 |
| p_60plus | 35,030 (6,529) | 0.2588 -> 0.2621 | 0.015 | 0.165 |
| pts_appear | 35,030 (6,529) | 0.7510 -> 0.7543 | 0.016 | 0.221 |
| pts_cs | 30,955 (5,771) | 0.1605 -> 0.1622 | 0.009 | 0.246 |
| team_pen_rate | 85,996 (15,228) | 0.0204 -> 0.0288 | 0.039 | 0.447 |
| e_points | 121,838 (21,659) | 1.1924 -> 1.2017 | 0.045 | 1.628 |

DC, step-0 outfield rows: before, 16,090 of 25,955 at `DC_BASE`, model rows appeared 1.000 vs base 0.046 (the
leak); after, 9,939 at base, model rows appeared 0.631 vs base 0.050 — the base rows are now players with no
played row before the cutoff, a pre-cutoff selection. Defenders carry 5,299 distinct values, max 0.840.
Saves, likely-starter goalkeepers, pts_saves mean by step: before 0.503 / 0.508 / 0.499 / 0.478 (steps 0/1/3/5),
after 0.503 / 0.502 / 0.505 / 0.505 — the frozen feature is flat across the horizon, as every other component.

2023-24 (162,604 rows) and 2024-25 (152,003 rows): DC untouched (zero everywhere, the rule did not exist);
saves changed on 10.7% / 9.6% of rows (max |Δ pts_saves| 3.15 / 1.85); p60 on 22.0% / 24.6% (mean +0.010 /
+0.018, max 0.244 / 0.284); team_pen_rate on 44.6% / 56.4%; e_points on 44.2% / 53.0% (mean |Δ| 0.021 / 0.022).

## 8. p60 SPECIFICALLY — level and ordering, step 0

| season | partition | n | p60 mean before -> after | rows changed | rank corr(old, new) | Spearman(p60, realised 60+) before -> after |
|---|---|---|---|---|---|---|
| 2023-24 | likely starters | 6,074 | 0.9431 -> 0.9462 | 609 | 0.976 | 0.320 -> 0.200 |
| 2023-24 | squad-relevant | 1,140 | 0.9470 -> 0.9502 | 93 | 0.979 | 0.353 -> 0.240 |
| 2024-25 | likely starters | 6,051 | 0.9414 -> 0.9464 | 638 | 0.974 | 0.330 -> 0.201 |
| 2024-25 | squad-relevant | 1,140 | 0.9456 -> 0.9505 | 118 | 0.983 | 0.344 -> 0.228 |
| 2025-26 | likely starters | 6,042 | 0.9443 -> 0.9477 | 606 | 0.978 | 0.321 -> 0.187 |
| 2025-26 | squad-relevant | 1,140 | 0.9520 -> 0.9543 | 88 | 0.986 | 0.298 -> 0.198 |
| 2025-26 | realised non-starters | 17,977 | 0.8028 -> 0.8176 | 4,304 | 0.905 | — |

The level on the decision partitions moved UP by ~0.003-0.005 — the rows that changed are the ones the old
construction zeroed (players who did not start that gameweek but had history), and the model reads real history
as higher than zero history. Realised starters' own values are untouched (their feature rows were already the
history before the start). The ordering is largely preserved (0.97-0.99 rank correlation on the decision
partitions; 0.90 on non-starters, where the change is). The "0.936 vs 0.892" of the Step-1 diagnosis was the
old code on truncated data (everyone zeroed) against the record (starters with history); after the fix
everyone carries history, so starters keep their values and non-starters rise. The clearest single read is the
last column: the old p60 predicted the realised 60-minute outcome on likely starters at 0.32 because it was
computed knowing they had started; the honest p60 sits at 0.19-0.20.

Refit (steps 1-5, all three seasons): p_start and e_minutes bit-identical before vs after; p60 changed on 87% of
refit rows (the step-k models retrain on lagged pairs whose feature rows now carry history); likely-starter level
unchanged (0.953 -> 0.954 at step 1), rank correlation 0.95-0.98. The step-0 P(60+ | start) model is provably
unchanged (section 3); the refit's step-k p60 models are legitimately refit on the corrected frame.

## 9. Deadlines changed, and the TOTALS on the record conventions

Executed action (transfer set) differing between the pre-rebuild and rebuilt armlogs, same gameweek:

| season | shadow (gap0) | reference (hmin_gap0) | production (both_gap0) |
|---|---|---|---|
| 2023-24 | 13 of 38 (1 captain) | 36 of 38 (2) | — |
| 2024-25 | 29 of 38 (1) | 23 of 31 (3) | 25 of 31 (2) |
| 2025-26 | 30 of 38 (4) | 28 of 38 (1) | 36 of 38 (15) |

Once one deadline's action differs the paths diverge (the standing "divergence lottery"); the counts say the
paths are different, not how much any single decision moved.

Totals on the index's own conventions (`data/leakfix_logs/arms_table.py` logic: path ex-TC2, TC2 in-sim or the
captain multiple at the rule week, BB1/BB2 bench reads, TC1 on the arm's own step-0 predictions, chip-inclusive;
the "before" column reproduces every current cell exactly, which is the check that the conventions match):

| season | config | path ex-TC2 before -> after | chip reads after (gw) | chip-incl before -> after | Δ |
|---|---|---|---|---|---|
| 2023-24 | shadow gap0_tc2 | 2291 -> 2344 | TC2 10@25 in-sim, BB1 10@7, BB2 20@34, TC1 6@6 | 2343 -> **2390** | +47 |
| 2023-24 | reference hmin_gap0 | 2386 -> 2246 | TC2 10@25 cap-mult, BB1 14@7, BB2 26@34, TC1 6@6 | 2425 -> **2302** | −123 |
| 2024-25 | shadow gap0_tc2 | 2219 -> 2201 | TC2 29@24 in-sim, BB1 19@7, BB2 27@33, TC1 9@18 | 2306 -> **2285** | −21 |
| 2024-25 | reference hmin_gap0 (GW8+) | 2254 -> 2194 | TC2 29@24 cap-mult, BB1 19@7, BB2 24@33, TC1 9@18 | 2335 -> **2275** | −60 |
| 2024-25 | production both_gap0 (GW8+) | 2372 -> 2261 | TC2 29@24 cap-mult, BB1 19@7, BB2 24@33, TC1 2@4 | 2459 -> **2335** | −124 |
| 2025-26 | shadow gap0_tc2 | 2153 -> 2187 | TC2 7@26 in-sim, BB1 18@10, BB2 21@33, TC1 16@17 | 2216 -> **2249** | +33 |
| 2025-26 | reference hmin_gap0_tc2 | 2216 -> 2161 | TC2 7@26 in-sim, BB1 27@10, BB2 16@33, TC1 16@17 | 2266 -> **2227** | −39 |
| 2025-26 | production both_gap0_tc2 | 2220 -> 2029 | TC2 7@26 in-sim, BB1 16@10, BB2 14@33, TC1 8@1 | 2264 -> **2074** | −190 |

Transfers / hits after: 84/48, 87/60, 81/52, 78/40, 85/56, 78/20, 75/8, 81/12 (row order as above). Margins vs the
fplcache average manager: +387, +299, +277, +267, +327, +354, +332, +179.

Reading, under the standing framing (a season total is one draw with path sd ~60-85; totals never decide
adoptions): the production configuration falls in both of its seasons (−124, −190) and the reference falls in
all three (−123, −60, −39); the shadow moves +47 / −21 / +33. That is the direction section 0 predicted — the
record was scored with outcome information it should not have had, and the combined config's step-0 props
blend conditioned on the leaked appearance probability twice over (p_play_any in the hook, and the DC and p60
terms in the same e_points). None of these numbers is a regression to recover; they are what the honest frames
score.

### Superseded, as of this rebuild
- Reference cells **2425 / 2335 / 2266** (arms/armlog_*_hmin_gap0[_tc2], built 2026-08-27/28 on frames carrying
  items 6-9).
- Shadow cells **2343 / 2306 / 2216** (gap0_tc2).
- Production-intent cells **2459 / 2264** (both_gap0[_tc2]).
- The props arm cells **2328 / 2221** (props_gap0; the props arm FRAMES were rebuilt with the others, the
  props_gap0 armlogs were NOT re-run — exploratory, never evidence).
- Every earlier lineage cell built on the pre-rebuild canonicals (2251/2306/2268, 2343/2300/2190, the
  _precrosswalk rows, the p1/fslog, p3, p5, chip and oracle grids) inherits the same three terms; they are
  superseded as figures of the equation, and remain valid only as records of what those studies measured at the
  time. The pre-rebuild artefacts are preserved as `*_preasof.parquet`.

### Candidates for the single re-pointing (NOT done here — `EXPECT_REFERENCE_CHIP` and the index are untouched)
- reference hmin_gap0: **2302 / 2275 / 2227**
- shadow gap0_tc2: **2390 / 2285 / 2249**
- production both_gap0: **2335 (2024-25) / 2074 (2025-26)**

## 10. What the guard does NOT cover
Listed in `LEAKAGE.md` (Closure 2026-09-11, "What the guard does NOT cover"): inputs read from disk that are not
per-season-truncated (props books and their crosswalk, the player crosswalks, the availability as-of
reconstruction rule itself), inputs whose as-of version cannot be rebuilt from what is on disk (Bet365 CLOSING
prices at step 0, the final fixture calendar, final Understat xG, roster identity for future gameweeks),
everything outside the frame (optimiser, transfer MIP, simulator state and price replay, chip scheduling, the
totals read layer), outcome-selected TRAINING rows on pre-cutoff data (legitimate conditionals the guard cannot
tell from leaks), cutoff coverage (four cutoffs of one season; two in the suite), and the same-gameweek double
window inside DC training rows.
