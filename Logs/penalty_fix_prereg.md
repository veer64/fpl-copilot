# Penalty term — CORRECTNESS FIX: PRE-REGISTRATION (written 2026-08-26, before any code was changed)

Companion: `Logs/headroom_diagnosis.md` §0 (the diagnosis), `Logs/d1_log.md` (where the term was adopted).
Nothing in this document may be changed after a result is seen; amendments go in a dated addendum at the end.
No file has been rebuilt and no endpoint has been computed at the time of writing.

## 1. The defect, verified at source (not assumed)

`squad/assembly.py`, D1 feature build (lines 440–495 at the time of writing) and `_finish_equation` (556–559):

    penalty_share = (goals − npg) / (games + 1)                   # Understat season aggregate
    team_pen_rate = Σ penalties_missed / n_gameweeks               # per (season, team), from vaastav
    e_goals      += penalty_share × team_pen_rate × minutes_frac

Three independent faults, each checked against the data this session:

1. **`penalty_share` is not a share.** It is the player's penalty GOALS PER GAME in the joined Understat
   season (Salah 2024: 9 pens / 38 games = 0.231; the fifth-best taker 0.105). A per-game pen-goal rate already
   embeds how often the team wins penalties. Multiplying it by any team rate double-applies the frequency.
2. **`team_pen_rate` is built from penalties MISSED, not awarded.** `penalties_missed` sums to 11 / 14 / 15
   league-wide in 2023-24 / 2024-25 / 2025-26; the resulting per-team series has mean 0.020 (range 0–0.054).
   The product therefore predicts **1.3 / 0.9 / 1.4 penalty goals per season league-wide** against 96 / 69 /
   77 realised (Understat, converted penalties). The D1 log's "penalty share moved nothing at any position
   (≤ 0.001)" was this bug swallowing the term, not the term being inert.
3. **The Understat join is SAME-season, not prior-season, and the fallback never matches.**
   `season_year = int(season[:4])` (2025 for 2025-26) is joined to `understat_season == 2025`, and Understat
   labels 2025-26 as "2025" (handoff 2026-08-18 trap #5). The comment says "2025-26 players look up their
   2024-25 record"; the code looks up their 2025-26 record — the season being predicted. That is a leak of the
   outcome (who took penalties this season), invisible only because fault 2 multiplied it by ~0.02. Separately,
   the position-mean fallback groups on Understat labels ("F M S", "D M") and is mapped from FPL labels
   (DEF/MID/FWD), so it matches nothing but "GK"; **28.9% of canonical 2025-26 step-0 rows carry the
   hard-coded default 0.05** — a per-game pen-goal rate higher than every real taker's but the top four.

`npxg90` excludes penalties at source: `eval/understat_matches.py` derives `npxG = xG − Σ penalty-shot xG` and
`npg = goals − converted penalties` per player-match, validated 562/562 against Understat's own aggregates, and
`attacking_rates._blended_rates` reads that `npxG` column. The legacy static path reads the aggregates' `npxG`.
So restoring the penalty term does not double-count; this is re-verified in Part 3.

**Consequence for the record:** the read-only deltas quoted in `Logs/headroom_diagnosis.md` §0 for "penalty
fix" were computed from the STORED `penalty_share` column, i.e. with the same-season leak and the 0.05 fallback
in place. They are superseded by this pre-registration and a dated marker is added to that file. Nothing from
them is carried forward as an expectation here.

## 2. The correction — a bug fix, no new information, no free parameter

Under one gate `assembly.PENALTY_FIX_ACTIVE` (rests **False** on disk until adopted; stamped per row as
`penalty_fix_active` by every walk-forward writer — `eval/walkforward.py`, `eval/walkforward_season.py`,
`eval/walkforward_arms.py`), when the gate is on:

    pen_rate_prior  = (goals − npg) / (games + 1)   from the Understat aggregate of the season BEFORE the
                                                    predicted one (understat_season = season_year − 1)
    fallback        = mean of pen_rate_prior by FPL position over that prior season's Understat rows,
                      position mapped by the first letter of the Understat label (F→FWD, M→MID, D→DEF,
                      GK→GK; GK is 0 by construction); applied to rows with no prior-season record
    e_goals         = npxg90 × minutes_frac × fixture_scale  +  pen_rate_prior × minutes_frac

i.e. the spurious `× team_pen_rate` factor is removed, the join is moved to the prior season as the code's
own comment intended, and the fallback is computed on labels that exist. Everything else is unchanged:
`minutes_frac` gating, `GOAL_PTS`, the downstream `pts_goals` and the BPS input (which reads `penalty_share`
into its `penalties_missed` proxy at ×0.1 — unchanged in form; its level moves with the corrected rate and is
reported, not tuned). The `team_pen_rate` column is still computed and persisted so the gate-off path is
bit-identical to today.

**Why this is not a feature and carries no tunable.** Nothing new enters the equation: the D1 adoption
already declared the penalty term (d1_log §1, term 4); the term simply never functioned. The corrected form is
the definition of the quantity the comment describes — prior-season penalty goals per game, scaled by expected
minutes. The `+1` in the denominator and the per-game (not per-90) basis are inherited unchanged from the
existing code and are NOT re-tuned here. Two constructions that WOULD be features, each needing its own
pre-registration before it is built, are named now and excluded: (a) blending current-season penalties taken
to date into the rate (a blend weight), and (b) team penalties AWARDED × taker share × conversion (a
conversion constant and a share model). `games + 1 → time/90` is likewise excluded as a definitional change.

**What is expected, stated now (not a pass condition):** rank should rise more on squad-relevant than on
likely starters (takers cluster at the top); league-wide predicted penalty goals should land BELOW realised,
because a prior-season rate misses takers who inherit the duty mid-season and new signings; the largest
e_points movers among the top 30 should be recognisable penalty takers (Salah, Haaland, Palmer, Bruno
Fernandes, Watkins, Wood, Mbeumo, Isak-class), and a list not dominated by takers is a failure regardless of
the endpoint.

## 3. Endpoint — the sliced rank instrument, unchanged since lever 1

Population: single-fixture (`n_fixtures == 1`) step-0 rows present in BOTH the canonical file and the
`_penfix` build (they are the same rows by construction; asserted), joined to vaastav realised points by
`(element, gw)`. Partitions, defined on the CANONICAL file's own view so both arms score the same rows:

- **likely starters**: own-cutoff `p_start ≥ 0.75`;
- **squad-relevant**: top 30 by the canonical `e_points` within the gameweek;
- reported, not decisive: uncertain (0.25 ≤ p_start < 0.75), written-off (< 0.25, no minutes floor), full
  starter band (`e_minutes ≥ 60`), realised started (minutes ≥ 60).

Primary: Spearman(e_points, realised points) per partition, per season, canonical vs `_penfix`.
Secondary: Brier and log loss on P(goal ≥ 1) = 1 − exp(−e_goals) against realised goals ≥ 1; calibration
(mean e_goals vs realised goals; reliability deciles on the full starter band); outcome-band decomposition of
|e_goals − goals| for goals = 0 / 1 / 2+; MAE/RMSE of e_points; the same on the written-off band.
Sanity: league-wide Σ (pen term) over step-0 single-fixture rows per season vs Understat converted penalties
(96 / 69 / 77 for 2023-24 / 2024-25 / 2025-26; 2022-23 = 74 is the prior for 2023-24). Structural: the gate-off
rebuild of one cutoff per season must reproduce the canonical rows bit-exactly (max |Δe_points| = 0), and a
unit test must show gate-on changes `e_goals` by exactly `pen_rate × minutes_frac`.

## 4. Pass condition — the bar for a correctness fix, argued in advance

The +0.020 bar (props_prereg §3) is a FEATURE bar: it is the cross-book disagreement floor below which a
gain cannot be attributed to a new information source. No information source is added here and nothing is
tuned, so that bar does not apply — and this is stated before any number exists so it cannot be invoked to
dismiss a small gain or to excuse a loss. A correctness fix is adopted unless it makes the decisions worse.
Therefore, on all three seasons:

1. **Rank must not fall on either decision partition** in any season. "Fall" = Δ Spearman < −0.003 (the
   partition-level resolution the props tuning treated as noise; stated so a −0.001 is not read as a revert
   trigger and a −0.010 is). Additionally the three-season mean Δ must be ≥ 0 on BOTH partitions.
2. **League-wide predicted penalty goals must land in [35, 115] per season** — at least ~25× the as-built
   figure and no more than 1.2× realised. Overshooting realised (> 1.2×) is a revert trigger: it would mean
   the term double-counts or the fallback is inflating non-takers.
3. **Brier on P(goal ≥ 1) must not worsen by more than 0.001** on either decision partition in any season.
4. **No double-counting**: the `npxG` source derivation is re-verified on the per-match files (Part 3) and the
   blend path is shown to read it. Failure here is a revert regardless of 1–3.
5. **The top-30 movers list must be dominated by penalty takers** (≥ 7 of the top 10 movers per season are
   players with ≥ 3 prior-season penalty goals). Failure here means the join or crosswalk is wrong.

Any one failure → the gate stays False, the `_penfix` files are kept as a record, and the result is appended
here as a negative. All five passing → recommend adoption: flip the gate, promote the `_penfix` files to
canonical (preserving the current canonicals as `*_prepenfix.parquet`), update the provenance fingerprint
deliberately, and only then run any season figure — under the standing framing, never as evidence.

## 5. Procedure

1. Code: gate + stamp + prior-season join + fallback (Part 2). Unit test for gate-on/gate-off behaviour.
2. Build `data/walkforward_h6_{season}_penfix.parquet` for all three seasons with the gate flipped
   in-process (the run_chip_study pattern); canonicals untouched. Gate-off single-cutoff reproduction check.
3. `eval/measure_penalty_fix.py`: Parts 3–4 exactly as written, plus the movers list by name.
4. Record: results appended below; `Logs/d1_log.md` dated marker correcting the "moved nothing" reading;
   `KNOWN_ISSUES.md` entry (silent-fallback family — a term that entered the equation and never acted);
   `Logs/headroom_diagnosis.md` dated marker superseding its read-only penalty deltas.
5. One commit. Adoption is a separate, user-triggered step.

2025-26 is not a sealed season for this question (spent 2026-08-26 on the props season figures); with no
tunable there is nothing to hold out, and all three seasons are reported.

---

## RESULTS (2026-08-26, `eval/measure_penalty_fix.py`; builds `data/walkforward_h6_{season}_penfix.parquet`, gate flipped in-process; canonicals untouched). VERDICT UNDER §4: **FAIL — gate stays False.**

Gate-off reproduction (`eval/run_penalty_fix.py --check`, 2024-25 cutoff 20): max |Δ| = 0.0 on every compared
column over 4,401 rows — the pre-fix equation is reproduced bit-exactly. Test suite 134 passed, 5 skipped.
Condition 4 (no double count): 63 player-matches with a converted penalty on the 2024-25 per-match file, all with
npxG < xG − 0.5 (mean gap 0.834); the blend reads `npxG` — **PASS**.

| season | paired rows | predicted pen goals as built → fixed (realised; prior) | cond 2 | Δρ likely | Δρ squad-relevant | cond 1 | ΔBrier likely / squad | cond 3 | takers in top-10 movers | cond 5 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | 27,759 | 1.5 → **44.9** (96; 74) | PASS | **+0.0042** | **+0.0059** | PASS | +0.0002 / +0.0008 | PASS | 2/10 (rule: ≥ 3 prior pens) | **FAIL** |
| 2024-25 | 26,555 | 0.9 → **66.7** (69; 96) | PASS | **+0.0042** | **+0.0166** | PASS | +0.0003 / **+0.0024** | **FAIL** | 7/10 | PASS |
| 2025-26 | 28,929 | 1.5 → **48.8** (77; 69) | PASS | **+0.0034** | **+0.0087** | PASS | +0.0002 / **+0.0013** | **FAIL** | 7/10 | PASS |

Three-season mean Δρ: likely starters **+0.0040**, squad-relevant **+0.0104** — both ≥ 0 (PASS). Rank also rises
on the full starter band (+0.004 / +0.004 / +0.004), on realised starters (+0.003 / +0.004 / +0.002) and on the
uncertain band (+0.001 ×3); the written-off band is unchanged (−0.0001). Log loss on likely starters is flat
(±0.0004). Fallback footprint with the gate on: 48–51% of rows carry exactly 0 (no prior-season record or no
prior-season penalty), 0.65–1.1% carry > 0.1/game, max 0.19–0.26 — the 0.05-on-29%-of-rows default is gone.

**Top-30 movers (sum of Δe_points over top-30 rows; prior-season pen goals):** 2023-24 Haaland +19.3 (7),
Saka +6.9 (2), Bruno Fernandes +5.7 (2), Salah +5.3 (2), Álvarez +2.3 (1), Havertz +2.2 (1), Ødegaard +2.2 (0),
Isak +2.1 (2), Son +1.9 (0), Wilson +1.9 (3). 2024-25 Palmer +40.7 (9), Haaland +26.1 (7), Salah +24.9 (5),
Saka +14.1 (6), Isak +11.3 (5), Bruno +9.3 (4), Mbeumo +7.5 (3), Ødegaard +4.6 (2), Son +3.8 (2), Eze +1.7 (1).
2025-26 Salah +26.3 (9), Mbeumo +12.3 (5), Haaland +11.6 (3), Bruno +9.4 (3), Palmer +4.9 (4), Saka +4.3 (1),
João Pedro +3.0 (5), Semenyo +2.2 (0), Enzo +2.1 (0), Isak +1.0 (4).

**Reading, written after the numbers and changing nothing above.**

1. The mechanism is confirmed: league-wide penalty goals go from ~1 to 45–67 per season, the movers are the
   penalty takers, rank rises on every decision partition in every season, and the rise is largest on
   squad-relevant (up to +0.017), as predicted in §2.
2. **Condition 5 failed in 2023-24 on the rule as written, not on the substance.** The rule required ≥ 3
   prior-season penalty goals; the 2022-23 prior was a 74-penalty season and Saka, Bruno, Salah and Isak each
   had exactly 2. The list is nine takers and Ødegaard. The rule was mis-specified for a low-penalty prior year;
   under the pre-registration a failed condition is a failed condition, so it is recorded as one.
3. **Condition 3 failed in two seasons on the squad-relevant partition**, and this failure is substantive. The
   canonical top 30 is already over-predicted on goals — mean e_goals 0.31 / 0.33 / 0.22 against realised
   0.22 / 0.21 / 0.15 (the winner's-curse level noted in `Logs/headroom_diagnosis.md` §2, "top-end level
   calibration") — and the corrected term adds 0.01–0.03 goals on exactly those rows, so a proper scoring rule on
   the LEVEL worsens (Brier +0.0008 / +0.0024 / +0.0013 vs the +0.001 cap) while the RANK improves. The
   outcome-band decomposition shows the same thing: MAE on the 1-goal and 2+-goal bands falls in every season
   (the term is right about who scores), MAE on the 0-goal band rises (the level at the top is too high before
   the term is added). On likely starters, where the level is near calibrated (0.13 vs 0.10–0.12), Brier is
   flat (+0.0002 / +0.0003 / +0.0002).
4. What this does NOT license: changing the cap after seeing the number, or adopting on rank alone. What it
   does establish for the record: the penalty term is now correct in form and level (45–67 vs ~1), and the
   remaining obstacle to adopting it is the pre-existing over-prediction of the top 30, which the term makes
   slightly worse in absolute terms. **The order of operations is therefore: top-end level calibration
   (diagnosis idea 9, its own pre-registration, tuned on prior seasons) FIRST, then this fix re-measured
   against the calibrated incumbent under this §4 unchanged.** A separate pre-registration for that calibration
   is the next step; nothing here is adopted.

Season figures (three full-system sims on the `_penfix` frames, reference config, TC2 scored zero, baseline
not re-run) are appended below when complete — under the standing framing, never as evidence.

### Season figures (2026-08-26; `eval/run_arms_full_system.py --arm penfix`, three full-season sims on the `_penfix` frames under the reference config — base opening, WC1@2, WC2/FH2/BB1/BB2 rules of record, H=6 decay 0.45, TC2 scored ZERO; reference cells NOT re-run; `eval/measure_arms_full_system.py`)

> *Note added 2026-08-26 (later): the reference 2296 / 2294 / 2206 quoted in this table is the OLD convention (TC2 scored zero, incumbent bonus term). The figures of record are now 2251 / 2306 / 2268 (`bonus_mode=delete` + TC2 in-sim; p4 log §15). This table stands as the comparison that was made at the time.*

| season | reference chip-incl | penfix path (Δ) | chip reads BB1 / BB2 / TC1 | penfix chip-incl (Δ) | margin vs avg mgr | W=3 paired deltas at anchors (Instrument A; not path-controlled after the first; never add) |
|---|---|---|---|---|---|---|
| 2023-24 | 2296 | 2256 (−22) | +13 / +16 / +6 | **2291 (−5)** | +288 | WC1@2 +0, BB1@7 −27, FH2@29 −33, WC2@32 +15, BB2@34 −28 |
| 2024-25 | 2294 | 2347 (+92) | +6 / +46 / +9 | **2408 (+114)** | +400 | WC1@2 +0, BB1@7 +44, FH2@29 +38, WC2@31 +4, BB2@33 −20 |
| 2025-26 | 2206 | 2085 (−71) | +19 / +19 / +16 | **2139 (−67)** | +244 | WC1@2 −8, BB1@10 +8, WC2@32 −27, BB2@33 +9, FH2@34 +24 |

Mean Δ chip-inclusive +14 over three single draws spanning −67 to +114 — inside the paired path noise
(sd ~85) in every season, and the 2024-25 reference is the 97th-percentile-baseline season. Standing framing:
these identify the configuration and adjudicate nothing; the verdict above rests on the component read alone.
Artefacts: `data/arms/armlog_{season}_penfix.parquet`; the WC1@2 anchor is +0 in two seasons because the opening
squads coincide until the wildcard.
