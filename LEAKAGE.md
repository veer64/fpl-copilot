# LEAKAGE.md — Known and Suspected Data Leakage Traps

This file is a living, standing checklist. Every time we discover (or even suspect)
a way that future information could leak into a feature, it gets logged here —
before it's forgotten, and before it can silently poison a model.

**Rule of thumb:** for every feature, ask — "could I have known this value on the
actual Friday before the deadline, using only data available at that moment?"
If the answer is no, or "sometimes," it belongs in this file.

---

## Confirmed traps

### 1. `xP` column (vaastav merged_gw.csv, seasons 2020-21 onward)
- **What:** FPL's own "expected points" prediction for that gameweek.
- **Why it's risky:** Per the source repo's own documented investigation, `xP` is
  scraped from FPL's `ep_this` API field *after* each gameweek ends. FPL's update
  cadence for this field is undocumented, and empirical analysis found xP's
  rolling-3 correlation with same-gameweek `total_points` is unusually high
  (~0.40) for something that's supposed to be a pre-match estimate — suggesting
  it sometimes reflects post-match information.
- **What we'll do:** Do not use `xP` as a model feature. If ever revisited, only
  use with an explicit `shift(1)` per player (i.e., last gameweek's xP, never
  the current one) — never unshifted.
- **What it IS useful for:** `xP` is FPL's own competing prediction system, not
  ground truth — `total_points` remains our actual target. But since `xP` is a
  free, pre-built "expected points" estimate, it makes a good baseline to beat
  in the model ladder (§3.5 of the master plan): once we build real models,
  we compare their accuracy against xP's accuracy (both vs. real total_points)
  to prove ours adds value, not just against naive rolling-mean baselines.

---

## Known assumptions / provenance caveats (not leakage, but same "don't forget this" spirit)

### 2. Reconstructed team-ID mappings for 2016-17 and 2017-18
- **What:** These two seasons' `merged_gw.csv` files store `team` as a numeric ID,
  not a name, and no `teams.csv` or `raw.json` exists in the source repo for
  either season to look up the real mapping.
- **What we did:** Reconstructed the ID→name mapping ourselves, using (a) the
  verified 20-club roster for each season from independent sources, and (b) the
  alphabetical-by-official-club-name ID convention confirmed real in 3 other
  seasons (2018-19, 2019-20, and a third-party FPL API reference).
- **Confidence:** High, not certain. Spot-checked against 2 real data points
  (Ospina→Arsenal in both seasons). Not independently verified against an
  archived record of the exact 2016-17/2017-18 ID list.
- **Action if this ever looks wrong:** If any downstream analysis shows
  suspicious team-level patterns for 2016-17/2017-18 specifically, revisit this
  mapping first before trusting the anomaly as real.

---

## Traps to actively watch for (seeded from the master plan, not yet hit — update as found)

### 3. Season-aggregate columns snapshotted late
- **What:** Any column that represents a full-season total/rate rather than a
  single-gameweek fact.
- **Why it's risky:** If such a column was pulled/updated after the season (or
  after the gameweek in question), using it to predict an earlier gameweek
  leaks the future into the past.
- **Status:** Not yet confirmed present in our data — watch for this specifically
  when we bring in Core-Insights and Understat next.

### 4. `chance_of_playing` fields in historical dumps
- **What:** Injury/playing-chance flags bundled into historical CSVs.
- **Why it's risky:** May reflect updates made *after* the relevant deadline,
  not the value known to managers at the time.
- **What we'll do:** Trust only our own timestamped live pulls going forward;
  treat historical injury flags as approximate, not gospel.

### 5. Cross-validation-fitted objects (calibrators, shrinkage priors, meta-learners)
- **What:** Any statistical object fit on the full dataset rather than
  walk-forward.
- **Why it's risky:** Fitting on future gameweeks and then "predicting" past
  ones with that fit is leakage, even if no individual feature looks leaky.
- **What we'll do:** Every such object must be fit walk-forward when we get to
  modeling (Week 5 onward) — no exceptions.

---

*Phase 2, Week 4 header retained; dated audits follow.*

---

## Audit 2026-09-11 — outcome-conditioned row universes and cutoff-blind features in the walk-forward harness

Trigger: KNOWN_ISSUES #22 (the defensive-contribution model never scores a live deadline gameweek). Its
backtest-side consequence — model rows exist only for players who ACTUALLY PLAYED the target gameweek — was
audited here against this file's standing definition, and every other term was checked for the same shape.
Read-only; numbers from the 2025-26 canonical (`data/walkforward_h6_2025_26.parquet`), the three
`data/arms_gap0/walkforward_h6_2025_26_*.parquet` files and the GW3 recovered live frames. Nothing was fixed.

### 6. Defensive-contribution term conditioned on realised appearance in the target gameweek — CONFIRMED LEAK
- **What:** `squad/defensive.py` line 90 keeps `minutes_played >= 1` rows; line 244 fits and predicts only for
  gameweeks in that frame; line 318 assigns `p_dc_hit` to `dc_out[gw == cutoff]`. In the backtest the target
  gameweek is on disk, so a player receives the per-player model value iff he played gameweek k, and
  `DC_BASE` otherwise. The assignment — model or base — is a function of the target gameweek's outcome.
- **Does it violate the standing definition?** Yes. The rule of thumb at the top of this file: "could I have
  known this value on the actual Friday before the deadline?" No. Whether a player will play is the thing being
  predicted. This is not one of traps 1–5; it is a new class (row existence as an outcome) and is recorded as
  its own item. It is not softened by the model's features being shift(1): the FEATURES are clean, the
  SELECTION is not.
- **Which quantity leaks.** The APPEARANCE. On 2025-26 step-0 outfield rows: 9,865 model rows (38.0%) with a
  realised appearance rate of **1.000**; 16,090 base rows with a realised appearance rate of **0.046**. Among
  likely starters (p_start ≥ 0.75, n = 5,371) the model group is 91.8% of rows and appeared 1.000 against 0.456
  for the base group. At steps 1–5 the value is frozen from gameweek k, so the conditioning persists (model
  group appeared 0.836 / 0.774 / 0.734 at steps 1 / 3 / 5 against 0.148 / 0.183 / 0.204). The same numbers hold
  on the three `arms_gap0` files (model share 0.374, appeared 0.834 vs 0.150 pooled over steps).
  The DC COUNTS of the target gameweek do NOT enter the prediction: features are shift(1) over the player's
  played rows, the label `dc_hit` is never a feature. The one exception is double gameweeks — rows are per
  fixture, so the second fixture's shift(1) is the first fixture of the SAME gameweek: 127 player-gameweeks
  (1.2% of played outfield player-gameweeks in 2025-26) carry a same-gameweek count in their features.
- **Cost on the record** (KNOWN_ISSUES #22): mean |pts_dc, model vs base| 0.171 on likely starters, 0.220 on
  the top 30, 0.25–0.40 on defenders, max 1.28; top-30 Spearman 0.157 vs 0.126. Forwards invert: a forward who
  played gets 0.005, one who did not gets 0.058.
- **What we'll do:** Do not read the 2025-26 canonical or arm files' `pts_dc` as a prediction. Any fix scores
  the cutoff's full row universe from each player's last-known feature row (never `dc_out[gw == cutoff]`),
  rebuilds and re-stamps the 2025-26 canonicals, and re-measures on the decision partitions before adoption.

### 7. D1 saves feature is NOT frozen at the cutoff — CONFIRMED horizon leak (GK, steps 1–5)
- **What:** `squad/assembly.py` lines 553–567 build `saves_per_90_roll` as `shift(1).rolling(5)` over the FULL
  season frame `v_full = df[season]`, then join it to the target rows by (element, gw, fixture). For a target
  gameweek g at cutoff k < g the window is g-5..g-1, which includes realised saves from gameweeks k..g-1 —
  after the cutoff. Every other component freezes at k (`p_dc_hit`, `npxg90`, `p_start`, `team_lambda`, `p_cs`
  all vary across cutoffs for the same (element, gw): 43–98% of pairs); `saves_per_90` does not (0 of 29,338
  (element, gw) pairs differ across cutoffs — it is the same value at step 5 as at step 0).
- **Violates:** the rule of thumb (steps 1–5 read saves that had not happened at the cutoff). Step 0 is clean.
- **Magnitude:** on GK rows at steps 1–5, 27.0% carry a value different from the frozen cutoff value; on
  likely-starter goalkeepers (n = 3,057) mean |Δ pts_saves| 0.222 (step 1 0.12, step 3 0.23, step 5 0.31),
  p95 0.60, max 1.63, against a mean pts_saves of 0.50. Same magnitude class as item 6, on the one term that
  reorders goalkeepers.
- **Live divergence, measured on the GW3 combined frame:** the same code on the live stack sees NaN saves for
  unplayed gameweeks, so the window empties as the step grows — GK `saves_per_90` takes 9 distinct values at
  steps 0–3, 7 at step 4 and ONE (the fallback constant 0.2317) at step 5, where every keeper's pts_saves is
  0.0003. The backtest read realised saves there; production reads a constant. Not a leak in production; a
  second backtest-vs-live gap in the same term.
- **What we'll do:** freeze the saves feature at the cutoff like every other component (build the rolling
  value at gameweek k and carry it across the horizon), then rebuild.

### 8. Full-season aggregates inside the D1 block — trap #3, CONFIRMED present (small magnitude)
- **What:** two D1 fallbacks are computed over the ENTIRE predicted season at every cutoff:
  `team_pen_rate` (assembly.py lines 597–602: `penalties_missed` summed over all played gameweeks of the
  season ÷ gameweek count; one value per team across all 38 cutoffs) and `saves_prior` (line 563: the
  position mean of `saves_per_90` over the whole season, ×0.3, used where a keeper has no rolling history).
- **Violates:** trap #3 in this file ("season-aggregate columns snapshotted late"), which was seeded as "not yet
  confirmed present" and now is.
- **Magnitude:** `team_pen_rate` multiplies a term already ~50× too small (KNOWN_ISSUES #19): e_pen_goals ×
  GOAL_PTS has mean 0.0006 and max 0.033 points per row. The `saves_prior` constant (0.1858) sits on 2,499 of
  3,383 GK step-0 rows (bench keepers), worth ~0.001 pts each. Negligible in points; a leak by definition.
  Live divergence: on GW3 `team_pen_rate` is 0 or 0.5 (two played gameweeks, one miss) against 0.026–0.054 in
  the backtest — the as-of value is 10–20× the full-season one.
- **What we'll do:** compute both from gameweeks < k (or drop them when #19 is closed).

### Term-by-term audit — does the backtest row universe or feature depend on target-gameweek outcomes?

| term | decided at | universe / freeze | outcome-conditioned? |
|---|---|---|---|
| minutes (p_start, p60, e_minutes) | minutes.py:54 `df[starts.notna() \| minutes.isna()]`, :296 `pf = csx[season == predict].dropna(SUBF + S1)`, :130 `_train_mask` | every stack row at gw k: step-0 rows per cutoff median 772.5 = stack elements per gw 772.5; step-0 appearance rate 0.387 = stack 0.386 | **No.** The `starts.notna()` filter fixed 2026-08-31 dropped only unlabelled rows; 2025-26 has 0 null `starts`, so it never conditioned the backtest — a live-only bug. |
| horizon-minutes refit (combined, steps 1–5) | horizon_minutes.py:163 cutoff row, :95 label gw < cutoff; walkforward_arms.py:47–48 | cutoff-k rows; labels strictly before the cutoff | **No.** |
| attacking rates | attacking_rates.py:291 `cur[gw < up_to_gw]`, :275 prior file | pre-cutoff Understat rows; `npxg90` varies across cutoffs (46.6% of pairs) | **No.** |
| Dixon-Coles / market lambda | dixon_coles.py:278 `matches[date < cutoff]`, :243 `date <= odds_available_until` (= last kickoff of gw k) | refit per cutoff; `team_lambda`, `p_cs` vary across cutoffs (97.6%) | **No** for this shape. Separate known caveat, on record in `Logs/live_odds_log.md` §5: the backtest's step-0 prices are Bet365 CLOSING, which for a Sunday fixture post-date the Friday deadline by two days and embed lineups; live reads a pre-deadline snapshot. Not audited further here. |
| bonus (fitted, zeroed) | bonus.py:37 `_cutoff_mask`, :136, :162 | cutoff-respecting | **No** (and inert under `BONUS_MODE = "delete"`). |
| defensive contribution | defensive.py:90, :244, :318 | played rows of gw k only | **YES — item 6.** |
| saves | assembly.py:553–567 | full-season rolling, not frozen at k | **Yes at steps 1–5 — item 7**; step 0 clean; fallback constant is trap #3 (item 8). |
| goals conceded | assembly.py `opp_lambda * minutes_frac` | per-cutoff lambda | **No.** |
| cards | assembly.py:574 `hist = df[season < season]` | prior seasons only | **No.** |
| penalty share | assembly.py:297 `_attach_penalty_share`, join year = prior season | prior season only | **No.** |
| team penalty rate | assembly.py:597–602 | whole predicted season | **Yes — trap #3, item 8** (negligible points). |
| props hook (combined, step 0) | props_feature.py:78 (pre-deadline boards), :88 `gw == cutoff` | pre-deadline market | **No.** |
| assembly skeleton | assembly.py:395, :401 | every stack row for the target gameweeks; vaastav carries every registered element whether he played or not | **No.** |

**Verdict on the shape.** The appearance-conditioning shape (a term computed only where the outcome row
exists) occurs ONCE, in the defensive module. A second shape occurs three times and is systematic: the D1
block inside `assemble_fixtures` is built from the full-season frame with no cutoff argument (the five component
getters all take `up_to_gw` / `cutoff_date`; the D1 feature code, added 2026-08-14/17, does not). One instance
is the saves horizon leak (material, GK steps 1–5); two are full-season aggregates (negligible points). Root
cause: `assemble_fixtures(df, ...)` receives the whole stack and is trusted to look only at the past; nothing
enforces it.

### Which figures of record are touched (item 6; items 7–8 sit inside every 2025-26 cell at steps 1–5 too)

The DC rule is stamped `dc_rule_active = False` with `p_dc_hit = 0` on every 2023-24 and 2024-25 row, so
only 2025-26 cells carry item 6.

| figure | file | touched |
|---|---|---|
| reference cells 2425 (2023-24), 2335 (2024-25) | `arms_gap0/walkforward_h6_{2023_24,2024_25}_hmin.parquet` | no (DC zero) |
| reference cell **2266** (2025-26 horizon arm) | `arms_gap0/walkforward_h6_2025_26_hmin.parquet` | **yes** (model share 0.374, appeared 0.834 vs 0.150) |
| shadow 2343 (2023-24), 2306 (2024-25) | canonicals | no |
| shadow **2216** (2025-26 baseline gap0) | `walkforward_h6_2025_26.parquet` | **yes** |
| props arm 2328 (2024-25) | `arms_gap0/…2024_25_props` | no |
| props arm **2221** (2025-26) | `arms_gap0/…2025_26_props` | **yes** |
| production intent **2264** (2025-26 combined), 2459 (2024-25 combined) | `arms_gap0/…_both` | **2264 yes**; 2459 no |
| every superseded 2025-26 cell (2268, 2190, 2206, 2212, 2283 …) | | yes, since the #15 wiring fix of 2026-08-19 put the per-player DC term into 2025-26 files |
| the DC adoption's own measurements | `Logs/dc_source_swap_prereg.md`, DC build log | component-level Brier on played rows = P(hit \| played) by construction — a legitimate conditional metric, not touched by the assembly selection; the FAIL verdict stands. The #15 rebuild's 2025-26 step-0 aggregate (ρ 0.7471 / MAE 1.0732, d1_log §8 addendum) IS an assembly-level figure with the conditioned term in it. |
| pre-registered tests whose verdict could turn on DC | bonus-delete, penalty-fix, top-end calibration, selection calibration (all measured on 2025-26 canonicals among others) | paired comparisons with the SAME conditioned term in both arms; verdicts are differences and are unaffected to first order. Absolute 2025-26 levels quoted in them are inflated on DEF/MID. |
| props (tuned on 2024-25), horizon minutes (minutes-level), rate blend (Understat-level), D1 adoption (2026-08-17, DC then at base rates everywhere, step 0 only) | | not touched |

### What the parity harness cannot see, and what would

`squad/live_deadline.py` calls `walkforward_season.walk_forward` (or the arm builder) with `cutoffs=[gw]` on the
SAME stack file the canonical was built from, and asserts bit-identity for historical gameweeks (2025-26 GW5 /
20 / 33; `Tests/test_live_deadline.py::test_parity_*`). Both sides therefore see gameweek k's played rows. Parity
proves the two CODE PATHS agree; it says nothing about whether the code path reads INFORMATION that will not
exist at a live deadline. Every item above (6, 7, 8) passes parity bit-for-bit, because the leak is in the
inputs both paths share, not in either path.

Master plan §7.4 exhibit B ("the same (player, gw) through the research path and the production path must
produce identical feature vectors") would NOT have caught this, for the same reason: research and production
here ARE one path (§1.3's "same code path for both" was implemented literally), so exhibit B is satisfied
trivially and cannot detect a shared dependence on future rows. It tests code divergence, not information-set
divergence.

The test that would catch it — and does not exist in `Tests/` (no as-of or truncation test over the stack;
the only "as_of" references are the availability block's own) — is the AS-OF RECONSTRUCTION test: for a
historical cutoff k, build the frame from a stack TRUNCATED to gameweeks < k plus a forward skeleton for
k..k+5 (the live information set, reconstructed), and assert bit-identity against the canonical row for
cutoff k. Any column that differs is target-gameweek information. On today's code that test would fail on
`p_dc_hit` (item 6), `saves_per_90` at steps 1–5 (item 7) and `team_pen_rate` / the GK fallback (item 8), and
would pass on every other column in the table above. It is the executable form of master plan §4.2's
"tests asserting feature.as_of < deadline(gw)", which was seeded in the plan and never built.

---

## Closure 2026-09-11 — the as-of reconstruction guard built, a third leak found by it, all three closed

The guard specified above now exists: `eval/asof_reconstruction.py`, wired into the suite as
`Tests/test_asof_reconstruction.py`. Run on the UNFIXED code first (2025-26, cutoffs 3 / 20 / 24 / 33, both
configs, DC source pinned to what the record was built under), it moved fifteen columns and one of them was not
items 6–8.

### 9. P(60+ | start) feature vector selected on the realised start — CONFIRMED LEAK, found by the guard, CLOSED
- **What:** `squad/minutes.py` built the starter-history block (`past60_rate_3`, `past60_rate_5`,
  `last_start_minutes`) on the `starts == 1` frame (line 118) and merged it onto the prediction frame by
  (season, element, GW) with a zero fill (lines 292–295). A player carried real starter history at gameweek k
  only if he STARTED gameweek k. The features themselves were shift(1) and clean; the selection was the outcome —
  the DC shape again. `squad/horizon_minutes._frames` did the same merge for the refit's cutoff row, so the
  combined config's steps 1–5 carried it too.
- **Verified:** at cutoff 20 all 214 rows whose `p60` moved under truncation started gameweek 20 (220 starters
  in the frame, 6 unmoved because their history was zero anyway); zero non-starters moved. `p60` on the moved
  rows: 0.936 in the record against 0.892 as-of; likely starters −0.029 signed, max 0.189. Dependants:
  `p_60plus`, `pts_appear`, `pts_cs`. `p_start` and `e_minutes` were never affected (their feature lists have no
  starter-history block).
- **Live consequence (before the fix):** skeleton rows have null `starts`, so every live player's starter history
  was zero and production `p60` sat below the backtest's on every nailed starter.
- **Fix:** `minutes._build_frames` now computes the block AS OF each gameweek for every row (inclusive rolling on
  start rows, shifted one row and carried forward within (season, element)); both `get_minutes` and
  `horizon_minutes._frames` read it from `cs` and the merge is gone — one fix, both paths. On start rows the
  values are bit-identical to the old construction (30,162 rows, max |Δ| 0, NaN pattern identical), so the fitted
  P(60+ | start) model is unchanged; only the prediction frame moved (6,363 non-start rows in 2025-26 and 9,102
  live rows now carry history instead of zero).

### Items 6–8: CLOSED 2026-09-11
- **6 (DC):** `defensive.get_dc_hits` scores every player with a played row before the cutoff on his as-of feature
  row (`_asof_rows` / `_score_cutoff`); training is unchanged (all feature-bearing rows with gw < cutoff). For every
  played single-fixture player at cutoffs 3 / 10 / 20 / 24 / 33 the value is bit-identical to the old path
  (262/262, 278/278, 272/272, 277/277, 213/213); the only value changes are double-gameweek rows (the
  same-gameweek artefact, 65 of 152 at cutoff 33); 66–189 players per cutoff who did not play are now scored
  instead of taking `DC_BASE`. Live, the lookup is no longer empty.
- **7 (saves):** `assembly.assemble_fixtures(..., cutoff_gw=k)` freezes the saves feature at the cutoff (mean of the
  player's last ≤ 5 rows with gw < k, carried across the horizon). Every walk-forward writer and the live path
  pass it; None keeps the legacy construction for the static `python assembly.py` build only.
- **8 (aggregates):** `team_pen_rate` and the goalkeeper saves fallback are computed over rows with gw < k.

**THESE ARE MODEL CHANGES, NOT REPAIRS.** The record's DC term was conditioned on realised appearance, its
starter-history block on the realised start, and its saves feature on realised saves after the cutoff. A live
build cannot reproduce any of that, because none of it is knowable at a deadline. The fixed terms are the honest
ones and do not match the leaked figures; the deltas in `Logs/asof_rebuild_log.md` are the correction, not a
regression.

### The guard, verified
After the fixes, the as-of rebuild is bit-identical to a full-information build at cutoffs 3 / 20 / 24 / 33 for
both configs — every column, every step, row sets identical — with the combined config's refit RECONSTRUCTED from
the truncated stack on both sides (`live_deadline.load_hmin_refit` is the one read of that file and is
substituted in-process), so steps 1–5 are genuinely under test. `Tests/test_asof_reconstruction.py` compares
the as-of rebuild against the record files at cutoffs 20 and 24 (24 spans the GW26 double) for both configs.

### What the guard does NOT cover (the residual, stated plainly)
1. **Inputs read from disk that are not per-season-truncated:** the props consensus books (pre-deadline boards by
   construction, but the crosswalk that maps book names to elements was built on the whole season's rosters), the
   crosswalks (identity from a full-season name match), prior-season files, and the availability file's
   `asof_*` reconstruction itself (built from post-deadline snapshots by a rule the guard trusts, not tests).
2. **Inputs whose as-of version cannot be rebuilt from what is on disk:** Bet365 CLOSING prices (the record's
   step-0 market is priced after the deadline, up to days later for Sunday fixtures; the only pre-deadline prices
   held are the 2026-27 live pulls) — `Logs/live_odds_log.md` §5; the odds archive's fixture universe (final
   calendar, not the calendar as of the cutoff — postponements and reschedules are invisible); Understat
   per-match rows (final xG, not xG as first published); the forward skeleton's identity (the guard uses the
   master's recorded identity for gameweeks ≥ k, not the roster as of the deadline — churn is a measured limit of
   `build_forward_skeleton --backfill`, not tested here).
3. **Everything outside the frame:** the optimiser, the transfer MIP, the simulator's squad state and price
   replay, chip scheduling (BB/TC/FH/WC weeks chosen by rules of record that were themselves picked with the
   whole season on disk), the season-totals read layer. The guard asserts the FRAME is as-of; a policy that reads
   the frame correctly can still be tuned on the future.
4. **Training-set membership by outcome:** the guard checks that PREDICTIONS at cutoff k do not read rows ≥ k. A
   model whose training rows for gws < k were selected on an outcome (e.g. the DC training rows are played rows,
   the bonus rows are minutes ≥ 1 rows) is a modelling choice the guard cannot distinguish from a leak; those
   selections are on pre-cutoff rows and are legitimate conditionals, but the guard is not what says so.
5. **Coverage:** four cutoffs of one season (two in the suite). A term that reads the future only in a state the
   chosen cutoffs never hit (a blank gameweek, GW1–2 cold start, a triple) is not exercised. Add a cutoff before
   assuming.
6. **Same-gameweek double-fixture windows inside training rows:** the DC training feature for the second fixture
   of a double still includes the first fixture of the same gameweek (both pre-cutoff, so not a leak at
   prediction; a construction quirk the guard does not see).

*Last updated: 2026-09-11 — items 6–9 closed, guard built and wired (`Tests/test_asof_reconstruction.py`), residual list above.*