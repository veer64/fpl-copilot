# Top-end level calibration — PRE-REGISTRATION (written 2026-08-26, before any code was changed)

Companions: `Logs/headroom_diagnosis.md` idea 9; `Logs/penalty_fix_prereg.md` (the fix this exists to unblock —
its §4 is NOT amended by anything here); `Logs/season_anticorrelation_check.md` (how to read season figures).
Nothing in this document may be changed after a result is seen; amendments go in dated addenda. At the time of
writing: no code changed, no file rebuilt, no rank endpoint computed for any candidate form. The diagnosis in §1
was computed read-only on the canonical files (penalty gate OFF) joined to vaastav — descriptive statistics of
the INCUMBENT, not of any candidate.

## 1. Diagnosis — where the miscalibration lives (read-only, canonical files, step-0 single-fixture rows)

Ratio = mean predicted e_goals / mean realised goals. LS = likely starters (own-cutoff p_start ≥ 0.75);
T30 = squad-relevant (top 30 by e_points within gameweek).

**(a) Deciles of e_goals, likely starters** (d0 … d9; ratio):
- 2023-24: 0.53 0.65 0.81 1.24 1.02 1.25 0.97 1.05 0.88 **1.34**
- 2024-25: 0.62 0.95 1.53 2.26 1.70 1.37 1.30 1.04 1.13 **1.40**
- 2025-26: 0.79 0.75 3.02 2.38 0.91 1.27 1.22 0.93 1.00 **1.28**

Deciles 6–8 (0.10–0.24 goals) are within ±0.13 of calibrated in every season; the top decile (0.42–0.52
predicted) is over by 28–40% in every season; the bottom deciles are UNDER (0.53–0.79) — they are near-zero
rates where a small absolute miss is a large ratio. Overall likely-starter goals are over by 5–14%. So this is a
top-end effect on the e_goals scale, not a uniform over-prediction, and it is **season-stable in sign and
size** (1.28–1.40).

**(b) Top 30:** over-predicted at every decile with positive realised goals; d7–d9 ratios 1.14 / 1.69 / 1.77
(2023-24), 1.44 / 1.37 / 1.75 (2024-25), 1.02 / 1.42 / 1.64 (2025-26). Position: FWD 1.75 / 1.56 / 1.44,
MID 1.10 / 1.42 / 1.34, DEF 1.88 / 2.77 / 1.57 (tiny rates, large ratios). The extra over-prediction of T30
relative to the LS top decile (≈1.7 vs ≈1.35) is the selection component — the winner's curse proper — which no
level calibration on e_goals can remove by construction (it is conditional on rank within the gameweek, not on
the level). What a level calibration CAN remove is the part shared with the LS top decile.

**(c) What drives the LS top-quintile over-prediction — fixture scale, not rate.** Among LS rows in the top
20% by e_goals, split by `fixture_scale` tercile (pred/real):

| season | low fixture_scale (≈0.80) | mid (≈1.15) | high (≈1.6) |
|---|---|---|---|
| 2023-24 | **0.94** | 1.09 | **1.39** |
| 2024-25 | **1.09** | 1.12 | **1.67** |
| 2025-26 | **0.83** | 1.27 | **1.47** |

Low-fixture rows are calibrated-to-under; high-fixture rows are over by 39–67%, in every season. By npxg90
tercile the pattern is weaker and less consistent (0.94 / 0.95 / 1.49; 1.33 / 1.21 / 1.34; 1.06 / 1.11 / 1.29).
The equation applies `fixture_scale = team_λ / 1.40` as a LINEAR multiplier on a player's npxG/90. A team
expected to score 1.7× the league average does not hand each attacker 1.7× his usual chances — chances are
shared, the extra team goals are spread, and part of a high λ is already the player's own rate (the market
prices the team partly because he is in it). Linear scaling therefore over-states the fixture effect at both
ends, which is exactly the shape in the table. This is the mechanism, and it is a property of the equation's
form, not of the season.

**(d) Positions:** likely-starter FWD over 1.20 / 1.10 / 1.05, MID 0.94 / 1.22 / 1.04, DEF 1.15 / 1.42 / 1.40.
Not uniform, but the fixture-scale signature is what is consistent; a per-position multiplier would be fitting
three numbers to three seasons of noise and is NOT the form chosen.

**(e) Other components:** assists show the same top-decile signature (e_assists own-decile top ratio 1.31 / 1.55 /
1.42 on LS) and are scaled by the same linear `fixture_scale`, so the form applies to both attacking terms.
Clean sheets given 60+ minutes are 1.20 / 1.05 / 1.04 — not stable, and p_cs is a market probability already
blended (CS_BLEND_W); left alone. e_points overall on LS is 1.10 / 1.09 / 1.02 — the goals/assists top-end is
most of it.

## 2. The form, chosen from (c), and its single parameter

    fixture_scale_cal = fixture_scale ** GAMMA          (GAMMA in [0, 1]; 1.0 = incumbent)
    e_goals   = npxg90 × minutes_frac × fixture_scale_cal + e_pen_goals
    e_assists = xa90   × minutes_frac × fixture_scale_cal

Applied to every row (no threshold, no decile map), both attacking terms, before the bonus input. Everything
else unchanged (the [0.5, 2.0] clip stays on the base scale; penalties are not fixture-scaled, as today).

Why this and not the alternatives named in the brief: a shrinkage above a prediction threshold or a per-decile
multiplier would treat the symptom (level at the top) and would ALSO shrink the low-fixture rows that are
already under-predicted; an isotonic map on e_goals preserves the within-gameweek rank of e_goals but cannot
see fixture_scale and so cannot correct the two ends in opposite directions. `fixture_scale^γ` moves both ends
the right way with one parameter (γ < 1 raises predictions when fixture_scale < 1 and lowers them when > 1),
and it is the form the mechanism in (c) implies. Its known limitation, stated now: it does not touch the
selection component of the top-30 over-prediction (§1b); that part is expected to remain and is reported, not
targeted.

**One tunable, γ, set by CALIBRATION, not by rank** (the amendment-4 lesson from props: a rank criterion
cannot set a level parameter).

## 3. Tuning protocol (2023-24 + 2024-25 only; 2025-26 sealed)

- Grid: γ ∈ {1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.0}.
- Tuning statistic, computed from the STORED canonical columns (npxg90, xa90, minutes_frac, fixture_scale,
  e_pen_goals) with e_goals recomputed at each γ — no rebuild during tuning; the bonus term's reaction to
  e_goals is ignored at this stage and stated: **selection rule = the γ that minimises
  |ratio_high − 1| + |ratio_low − 1|**, where ratio_high / ratio_low are pred/real e_goals on the HIGH and LOW
  fixture_scale terciles of the likely-starter top quintile, pooled over the two tuning seasons. Ties → the
  larger γ (closer to the incumbent). This targets the structure in §1c directly and leaves the top-30 rank
  untouched as a criterion, so the pass condition below is a genuine test rather than a fit.
- Reported for information at every γ (tuning seasons): the likely-starter decile table, the top-30 ratio, the
  top-30 e_points spread (sd, p10–p90), and Spearman on both decision partitions (recomputed e_points with the
  bonus term held at its canonical value — an approximation stated as such; the pre-registered measurement uses
  full rebuilds).
- The chosen γ is written into a dated `## PRE-REGISTERED VALUE` section of THIS file as the exact line
  `GAMMA = …` before any 2025-26 file is opened by the measurement. The measurement script refuses `--holdout`
  unless that exact line is present in the LAST such section (the k = 8 / props guard pattern). 2025-26 is then
  built and measured ONCE at that γ and the result appended whatever it shows.

## 4. Pass condition — stated now, with the trap named

**The trap:** horizon-minutes lever 1 improved Brier, AUC and aggregate rank and failed because rank fell on
the decision partitions. A calibration that shrinks levels will look good on Brier almost by construction and
`fixture_scale^γ` preserves within-team rank exactly; what it changes is CROSS-team rank on the attacking terms,
which is where it can fail. **Calibration improvement alone is NOT a pass.** Conditions, on the two tuning
seasons AND on the sealed season, at the pre-registered γ, measured on FULL rebuilds:

1. **Rank must not fall on either decision partition in any season**: Δ Spearman(e_points, realised points)
   on likely starters and on squad-relevant ≥ −0.003 (the resolution used in the penalty prereg), partitions
   defined on the incumbent's own view. Reported alongside: uncertain, written-off, full starter band.
2. **The level must close**: on the likely-starter top decile the pred/real ratio must move at least HALF of the
   way from its incumbent value toward 1.00 in every season (e.g. 1.34 → ≤ 1.17), and the high-fixture-tercile
   ratio of §1c likewise. On the top 30 the ratio must fall in every season (any amount; the selection component
   is expected to remain).
3. **No flattening**: the sd of top-30 e_points, and the p90 − p10 spread of top-30 e_goals, must each remain
   ≥ 85% of the incumbent's in every season — a calibration that buys its level by compressing the top end into
   the middle is a fail even if 1–2 pass.
4. Brier and log loss on P(goal ≥ 1) reported on both partitions; they are expected to improve and count for
   nothing.

Any one failure → gate stays False, γ is recorded, result appended as a negative.

**Then, and only then, the penalty fix is re-measured** against the calibrated incumbent (`_cal` vs
`_cal_penfix`) under `Logs/penalty_fix_prereg.md` §4 EXACTLY as written — same five conditions, same caps, the
same ≥ 3-prior-pens movers rule that mis-fired in 2023-24. That section is not amended. Both readings are
reported: calibration alone, and calibration + penalty fix.

## 5. Build and provenance

- `assembly.TOPEND_CAL_ACTIVE` (rests False) and `assembly.FIXTURE_SCALE_GAMMA` (= the pre-registered value once
  written; until then 1.0); stamped per row as `topend_cal_active` and `fixture_scale_gamma` by all three
  walk-forward writers. Gate off reproduces the current equation bit-exactly (checked at one cutoff).
- Builds, all with `eval/run_topend_cal.py` flipping gates in-process, canonicals untouched:
  `walkforward_h6_{season}_cal.parquet` (calibration on, penalty off) and
  `walkforward_h6_{season}_cal_penfix.parquet` (both on), for the two tuning seasons first; 2025-26 only after
  the value line exists.
- Measurement: `eval/measure_topend_cal.py` (§4 conditions 1–4, decile tables before/after, both penalty
  states) and `eval/measure_penalty_fix.py --calibrated` (the penalty §4 re-read on the `_cal` pair).
- Season figures LAST, via `eval/run_arms_full_system.py --arm cal / cal_penfix`, reference not re-run, under
  the standing framing, with the 2024-25 Salah-held count reported next to the total.

## 6. What is expected, stated now (not a pass condition)

γ well below 1 (the high-tercile over-prediction of 39–67% against a fixture_scale of ~1.6 implies roughly
γ ≈ 0.3–0.5 if the whole excess were fixture-driven; some of it is rate/selection, so γ may land higher).
Likely-starter top decile should calibrate to within ~10%; the top-30 ratio should fall from ~1.6–1.75 to
~1.3–1.4 and no further (the selection residual). Rank on squad-relevant could move either way: easy-fixture
premiums are demoted relative to hard-fixture premiums, which is the trade this form makes; if the market's
fixture information was worth more than its linear over-statement cost, rank falls and the form is wrong.
Penalty-fix Brier on the top 30 should then sit inside its cap because the base level the term adds to is no
longer over — that is the whole hypothesis, and it can fail.

---

## PRE-REGISTERED VALUE (2026-08-26, written before any 2025-26 file was opened by the calibration build or measurement)

GAMMA = 0.2

Selected on 2023-24 + 2024-25 by the §3 rule exactly as written (min |ratio_high − 1| + |ratio_low − 1| on the
fixture-scale terciles of the likely-starter top quintile, pooled; ties → larger γ). Surface (`eval/tune_topend_cal.py`,
stored columns, bonus held at canonical; output of record `data/penfix_logs/tune_topend_cal.txt`):

| γ | low / mid / high tercile ratio | objective | LS d9 ratio (23-24 / 24-25) | T30 ratio | T30 e_points sd | Δρ LS (approx.) | Δρ T30 (approx.) |
|---|---|---|---|---|---|---|---|
| 1.0 | 1.010 / 1.107 / 1.516 | 0.525 | 1.34 / 1.40 | 1.40 / 1.60 | 1.04 / 1.05 | — | — |
| 0.8 | 1.053 / 1.075 / 1.365 | 0.418 | 1.24 / 1.32 | 1.29 / 1.49 | 0.88 / 0.91 | +0.002 / +0.003 | −0.016 / −0.006 |
| 0.6 | 1.100 / 1.045 / 1.230 | 0.330 | 1.18 / 1.25 | 1.19 / 1.40 | 0.77 / 0.80 | +0.004 / +0.006 | −0.036 / −0.017 |
| 0.4 | 1.150 / 1.017 / 1.109 | 0.259 | 1.14 / 1.18 | 1.10 / 1.31 | 0.68 / 0.72 | +0.005 / +0.008 | −0.060 / −0.028 |
| **0.2** | 1.203 / 0.989 / 1.001 | **0.204** | 1.11 / 1.22 | 1.03 / 1.23 | 0.63 / 0.66 | +0.004 / +0.009 | **−0.086 / −0.042** |
| 0.0 | 1.259 / 0.962 / 0.904 | 0.355 | 1.11 / 1.22 | 0.95 / 1.16 | 0.60 / 0.64 | +0.002 / +0.008 | −0.112 / −0.058 |

Recorded with the value, so the sealed measurement is read with them in view:
1. **The two ends do not meet.** Pooled over the tuning seasons the low tercile was already calibrated at γ = 1
   (1.01, not the per-season 0.94 / 1.09 / 0.83 the diagnosis showed), so shrinking the exponent trades the
   high tercile against the low one and the objective's minimum is where they cross (γ = 0.2, low 1.20 / high
   1.00). A pure exponent is not the exact shape; the rule still selects, and is followed.
2. **The information columns already show the §4 trap.** At γ = 0.2 the approximate rank on squad-relevant is
   −0.086 / −0.042 against a −0.003 floor while likely starters rises +0.004 / +0.009 and the top-30 e_points
   spread drops to 0.63 (a 40% compression, below the 85% floor of condition 3). The pre-registered measurement
   on full rebuilds is what decides; this is stated now so that a FAIL there cannot be called a surprise, and a
   PASS would be one.
3. Nothing is re-tuned. 2025-26 is built and measured once at γ = 0.2.

---

## RESULTS (2026-08-26; full rebuilds `walkforward_h6_{season}_cal.parquet` / `_cal_penfix.parquet` at γ = 0.2; `eval/measure_topend_cal.py --holdout`; output of record `data/penfix_logs/measure_topend_cal.txt`). VERDICT UNDER §4: **FAIL — gate stays False; γ = 0.2 recorded, not adopted.**

Gate-off reproduction at 2024-25 cutoff 20: bit-exact (max |Δ| = 0.0 on all compared columns). Tests 135 passed.

**Calibration alone (canonical → `_cal`), per season:**

| season | Δρ likely | Δρ squad-relevant | cond 1 | LS d9 ratio | high-tercile ratio | T30 ratio | cond 2 | T30 e_points sd ratio | T30 e_goals p90−p10 ratio | cond 3 | Brier LS / T30 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | +0.0039 | **−0.0861** | FAIL | 1.34 → 1.11 | 1.39 → 0.90 | 1.40 → 1.03 | PASS | **0.60** | 0.72 | FAIL | 0.0837→0.0830 / 0.1375→0.1326 |
| 2024-25 | +0.0086 | **−0.0423** | FAIL | 1.40 → 1.22 | 1.67 → 1.12 | 1.60 → 1.23 | FAIL (d9 not halfway) | **0.63** | 0.74 | FAIL | 0.0759→0.0749 / 0.1295→0.1234 |
| 2025-26 (sealed, once) | +0.0009 | +0.0119 | PASS | 1.28 → 1.20 | 1.47 → 1.04 | 1.48 → 1.18 | FAIL (d9 not halfway) | **0.70** | 0.74 | FAIL | 0.0730→0.0724 / 0.1037→0.1004 |

With the penalty fix on (`_penfix` → `_cal_penfix`) the picture is the same: Δρ squad-relevant −0.079 / −0.024 /
+0.012, spread ratios 0.62 / 0.70 / 0.72, levels 1.41→1.05 / 1.70→1.35 / 1.63→1.33.

**Reading, written after the numbers and changing nothing above.**

1. **This is the lever-1 trap, exactly as §4 named it.** Brier and log loss improve on every partition in every
   season; likely-starter rank rises slightly; the top-30 level calibrates (1.40 → 1.03 in 2023-24); and rank on
   squad-relevant — the partition where the optimizer chooses — falls by 0.086 and 0.042 in the two tuning
   seasons. Calibration improvement alone was declared not a pass, and it is not one.
2. **The form is wrong in a specific, informative way.** `fixture_scale^0.2` compresses a 1.6 fixture multiplier
   to 1.10: it removes the market's fixture information from the attacking terms almost entirely. The rank loss
   on the top 30 says that information is worth more to the ORDER of premiums than its linear over-statement costs
   in LEVEL. The level problem at the top is real (§1) but it is not fixable by shrinking the fixture effect;
   the diagnosis in §1c mistook the fixture-scale bins' pred/real gradient for a form error when part of it is
   the selection component (the top quintile by e_goals over-represents high-fixture rows, whose positive errors
   are exactly what selection admits). The pooled low tercile was already calibrated at γ = 1 (1.01), so the rule
   was minimising a trade-off rather than correcting two ends — recorded in the PRE-REGISTERED VALUE entry
   before the measurement, and confirmed by it.
3. **Condition 3 fails everywhere (spread 0.60–0.72 of the incumbent):** the calibration bought its level by
   flattening the top end into the middle — the failure mode the condition existed to catch.
4. **2025-26 passed condition 1** (+0.012 on squad-relevant) while failing 2 and 3; one season against two, and
   the sealed season, so it is noted and not weighted.

**Penalty fix re-read under `Logs/penalty_fix_prereg.md` §4 UNCHANGED, calibrated pair (`_cal` vs `_cal_penfix`;
`eval/measure_penalty_fix.py --calibrated`, output `data/penfix_logs/measure_penalty_fix_calibrated.txt`):**
rank +0.0044 / +0.0041 / +0.0039 on likely starters and **+0.0113 / +0.0338 / +0.0016** on squad-relevant (all
PASS; means +0.004 / +0.016); pen goals 45 / 67 / 49 (PASS); Brier on squad-relevant +0.0005 / +0.0010 / **+0.0011**
(2025-26 FAIL by 0.0001); movers ≥ 3-pens rule 3/10 / 7/10 / **5/10** (FAIL in two seasons). **OVERALL FAIL.**
The calibration did move the penalty fix's Brier into or onto its cap in the two tuning seasons (+0.0024 → +0.0010,
+0.0008 → +0.0005) — the hypothesis that the level at the top was the blocker is supported in direction — but the
sealed season misses the cap by 0.0001 and the movers rule fails, and a calibration that itself fails cannot be the
incumbent anyway. The penalty fix's original §4 is not amended; a re-pre-registration of its condition 5 (which was
mis-specified for low-penalty prior years) is the user's call and is not made here.

**What stands:** the diagnosis tables in §1 (the top-30 over-prediction is real and season-stable; the selection
component is the larger part); the tuning surface; a clean negative on the exponent form. What would be next, not
started: a calibration that acts on the SELECTION component rather than the fixture term — e.g. shrinkage of a
player's e_goals toward his within-position prior as a function of his rank within the gameweek — which by
construction reduces levels at the top without discarding fixture information. It needs its own pre-registration.

Season figures for the `cal` and `cal_penfix` arms are appended below when complete — standing framing, never
evidence, with the 2024-25 Salah-held count.

### Season figures (2026-08-26; `eval/run_arms_full_system.py --arm cal / cal_penfix`, reference config, TC2 scored ZERO, reference cells and the penfix arm NOT re-run; `eval/measure_arms_full_system.py`)

> *Note added 2026-08-26 (later): the reference 2296 / 2294 / 2206 quoted in this table is the OLD convention (TC2 scored zero, incumbent bonus term). The figures of record are now 2251 / 2306 / 2268 (`bonus_mode=delete` + TC2 in-sim; p4 log §15). This table stands as the comparison that was made at the time.*

| season | reference | penfix (earlier) | **cal** | **cal + penfix** | 2024-25 Salah held / captained (ref 34 / 26) |
|---|---|---|---|---|---|
| 2023-24 | 2296 | 2291 (−5) | **2265 (−31)** | **2286 (−10)** | — |
| 2024-25 | 2294 | 2408 (+114) | **2298 (+4)** | **2399 (+105)** | cal 30 / 27; cal+penfix 34 / 30; penfix 34 / 23 |
| 2025-26 | 2206 | 2139 (−67) | **2111 (−95)** | **2135 (−71)** | — |

Path totals: cal 2215 / 2247 / 2058; cal+penfix 2221 / 2366 / 2100. W=3 anchor deltas in the measure output. Standing
framing: single draws, sd ~60 (paired ~85); identify, never adjudicate. The 2024-25 read follows the Salah rule from
`Logs/season_anticorrelation_check.md`: the two arms that held him all season (+105, +114) sit ~100 above the one that
dropped him for four weeks (+4) — the concentration mechanism, not the calibration. Nothing here changes the component
verdict: both gates rest False.
