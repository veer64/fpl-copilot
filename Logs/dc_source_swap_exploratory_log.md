# DC source swap — FULL EXPLORATORY MEASUREMENT — 2026-08-31

## Framing, recorded plainly

A pre-registered test of this swap was run and **FAILED** (`Logs/dc_source_swap_prereg.md`,
commits cd199a3 / 8e653f2 / 24ec9c0). Its bar was DC calibration on Brier, unsliced:
DEF 0.15950 -> 0.16154, worse, so the run stopped and rank and season totals were
never produced. That bar was inconsistent with every other adoption test in this
project, which places its bars on the decision partitions. This run therefore
measures the sliced quantities the earlier test should have used — but because the
endpoint is being changed AFTER a fail, this run is **EXPLORATORY and cannot be
cited as a passed pre-registration**. Any adoption from it is a judgement call made
with the failed result in view, and must be recorded as such.

**Scope, known before running:** official FPL counts exist only for 2025-26 — the
rule began that season and the term is structurally inert before it. One season,
one draw. The `DC_SOURCE` gate defaulted to `core_insights` throughout; nothing was
adopted.

Stated analysis choices (exploratory, declared at run time): partitions are defined
per-frame (each model's own step-0 view); for item 4 a (player, gw) is
partition-relevant if it reaches either partition in either the pre or post frame;
calibration rows are the 9,746-row single-match intersection joined to official
hits (multi-match player-gws excluded, as in the pre-registered test).

## 1. Sliced calibration (Brier / ECE vs FPL-official hits)

| slice | fam | n (pre/post) | Brier pre -> post | ECE pre -> post |
|---|---|---|---|---|
| all players | DEF | 3,619 | 0.15950 -> 0.16154 (worse) | 0.0516 -> 0.0442 (better) |
| all players | MID | 4,853 | 0.09300 -> 0.09182 (better) | 0.0346 -> 0.0257 (better) |
| all players | FWD | 1,274 | 0.00624 -> 0.00624 | 0.0013 -> 0.0013 |
| likely starters | DEF | 2,165 | 0.19111 -> 0.19163 (worse, +0.0005) | 0.0651 -> 0.0548 (better) |
| likely starters | MID | 2,232 | 0.13359 -> 0.13082 (better) | 0.0483 -> 0.0339 (better) |
| likely starters | FWD | 479 | 0.01656 -> 0.01656 | 0.0117 -> 0.0117 |
| top-30 | DEF | 445 / 452 | 0.20733 -> 0.20614 (better) | 0.0767 -> 0.0491 (better) |
| top-30 | MID | 403 / 412 | 0.08020 -> 0.08145 (worse) | 0.0396 -> 0.0517 (worse) |
| top-30 | FWD | 83 / 84 | 0.01195 -> 0.01181 | 0.0070 -> 0.0069 |

Pattern: ECE improves nearly everywhere (7 of 8 non-FWD cells); Brier is mixed —
DEF all-players and likely-starters slightly worse, DEF top-30 better; MID better
except top-30 (small n, membership differs per frame).

## 2. Rank (mean per-gw Spearman, e_points vs actual GW points, 38 gws)

| config | partition | pre | post | delta |
|---|---|---|---|---|
| baseline | likely starters | +0.2147 | +0.2205 | **+0.0058** |
| baseline | top-30 | +0.0977 | +0.1151 | **+0.0174** |
| combined | likely starters | +0.2212 | +0.2255 | **+0.0043** |
| combined | top-30 | +0.0733 | +0.0354 | **−0.0379** |

Three of four cells improve; combined top-30 falls sharply. Note: the per-row
e_points deltas are IDENTICAL between configs at step 0 (the DC term enters both
identically; props/hmin do not touch p_dc_hit at step 0), so the divergent rank
deltas are entirely partition-composition effects — top-30 is a 30-row/gw,
high-variance read.

## 3. Season totals — ILLUSTRATION ONLY (not citable toward any decision)

Same runner, same convention (gap0, opening base, WC1@2, WC2@32, FH2@34, TC2 in-sim
@26), record frame vs swapped frame. Armlog chip-inclusive basis (the quoted cells
2216/2264 are the resolution figures = these + exogenous chip reads of +56/+37):

| config | record | swapped | delta | transfers | hit pts | action diffs |
|---|---|---|---|---|---|---|
| baseline (gap0_tc2) | 2160 | 2155 | **-5** | 75 -> 78 | 4 -> 12 | transfers differ at 25/38 deadlines; captain at 2 (GW4, 24); chips identical; identical squad 8/38 |
| combined (both_gap0_tc2) | 2227 | 2250 | **+23** | 82 -> 77 | 20 -> 4 | transfers differ at 28/38 deadlines; captain at 6; chips identical; identical squad 9/38 |

Raw paths: baseline 2164 -> 2167, combined 2247 -> 2254. Opposite-signed deltas in
the two configs, both far inside the paired-path sd ~85; the +/-90 near-tie rule
applies. These numbers are illustration and carry no evidential weight.

INCIDENT, recorded: the first sim pass silently reproduced the records EXACTLY
(+0, zero action diffs at 38/38, both configs) because the runner's new --wf-path
override validated its arguments but never replaced wf_path -- both sims read the
record frames. Caught by the implausibility of 38/38 identical actions against
frames known to differ (222 partition prediction flips); fixed, artefacts deleted,
rerun with the override printed in-log ("wf-path OVERRIDE in force"). Silver
lining, worth keeping: that accidental pass reproduced both record armlogs
bit-for-bit through every transfer, captain and chip -- a full-season determinism
check of the sim path that had never been run.

## 4. What actually changes, on the decision partitions

- Label flips (player-gws where core and official disagree on the hit): 231 total;
  **163 land on either partition** (163 likely-starters, 29 top-30). The flips are
  overwhelmingly on decision-relevant players — defensive starters play a lot.
- Prediction flips (p >= 0.5): 271 total; **222 on either partition** (222
  starters, 72 top-30; 122 of the partition flips are gained hits).
- Frame movement: |Δ e_points| on partition rows mean 0.082, p95 0.326,
  max 1.396 (identical in both configs at step 0, as above).

## 5. The sign question — RESOLVED

**Every disagreeing row in both #21 spot checks is a GOALKEEPER.** FPL's native
`defensive_contribution` is exactly CBIT for DEF and CBIRT for MID/FWD (100.00%
identity against FPL's own component columns) — and **0 for goalkeepers**, who
cannot earn DC points. The cross-checks' position-appropriate construction
(`np.where(position == "Defender", cbit, cbirt)`) hands goalkeepers the CBIRT
formula, so each GK contributes his full CBIRT (recoveries-dominated, +4..+22)
against a definitional zero. GW1 2026-27 reproduced verbatim: all 20 disagreements
are Goalkeepers; the "7 flips at 10 / 4 flips at 12" in #21 are all goalkeepers —
players the DC model never predicts. GW20 2025-26: same mechanism (Raya, Martínez,
Petrović, ... — minutes identical row-for-row, so not a match-assignment issue).

**The true, model-relevant discrepancy has the OPPOSITE sign**: FPL counts MORE
tackles than core-insights' `tackles` column (17.3% of player-matches, mean
−0.33/match, up to −41 over a season for one player; core-higher essentially never
at 0.48%). Components otherwise agree: C+B+I 97.3% exact per match (FPL's `cbi`
column excludes tackles), recoveries 98.5% exact, per-GW CBIR-without-tackles
96.0% exact with symmetric 2% tails. `tackles_won` is further from FPL's tackles
(61.7% exact, mean −0.77) than `tackles` (82.2%, −0.33) — FPL's tackles semantic
sits between core's two columns, closest to but above core's `tackles`.

So: the spot checks misled because their comparison population silently included
goalkeepers with a formula that does not apply to them; #21's "core always counts
more, +4..+22, one-signed" dissolves entirely into that artefact, and the
season-long truth is official-higher via tackles. The label consequences run
through the model's own population: official hit rates are HIGHER than core's
(DEF 0.208 vs 0.184; MID 0.108 vs 0.089).

## 6. Parity

With the gate at its default (`core_insights`), the three-cutoff step-0 parity
(GW5/20/33 incl. the DGW): **PASS, bit-identical, both configs.** Suite unchanged.

## 7. No recommendation

Per the task: everything above is measurement. The decision belongs to the
project owner and will be recorded as a judgement call made with the failed
pre-registration in view.
