# Is 2024-25 anti-correlated with the other two seasons? — CHECKED, DEBUNKED (2026-08-26)

Read-only. No simulation. Inputs: every row of `Logs/season_totals_index.md` (non-superseded) that has a
reference cell under the index's own "valid comparisons" list, plus the penalty-fix arm (−5 / +114 / −67,
`Logs/penalty_fix_prereg.md`, not yet indexed). Deltas are chip-inclusive total minus the family's reference
cell in the same season. Scratch table: `data/penfix_logs/anticorr_deltas.csv`.

## 1. Population

60 arms with all three seasons (sweep cells vs `base H6 d45`; chips-era vs `baseline`; P1 arms and the WC1 grid
vs `p1log base`; full-system cells, P3, P5, team-news oracles, the horizon-minutes arm and the penalty fix vs
`fslog base_wc2`). Family counts: SWEEP 17, WC1 grid 14, FULL SYSTEM 7, CHIPS 6, P3 6, TEAM-NEWS 4, P5 2, P1 2,
ARMS (hmin) 1, PENFIX 1. Arms within a family share prefixes and are not independent; a family-level check is
reported alongside. Two all-zero arms (P5 xi; P1 p2 in seasons where it copied base) were dropped; the
2024-25 hmin arm is the GW8-stitched figure the index carries.

## 2. The test

Correlation of each season's delta with the MEAN of the other two seasons' deltas, across the 60 arms; sign
test = share of arms where the two have opposite sign; permutation null = the same statistic with the target
season's column shuffled across arms (5,000 draws) — this null carries whatever common level shift the deltas
have (they are NOT mean-zero; see §3), so the arithmetic artefact the brief warns about cannot produce it.
No row-demeaning is applied anywhere.

| target season | Pearson r vs mean(others) | p (analytic / permutation) | Spearman | opposite sign | binomial p |
|---|---|---|---|---|---|
| 2023-24 | **+0.286** | 0.027 / 0.027 | +0.249 | 16 / 54 | 0.004 |
| **2024-25** | **+0.260** | 0.045 / 0.044 | +0.256 | **14 / 57** | 0.000 |
| 2025-26 | +0.187 | 0.153 / 0.152 | +0.131 | 23 / 57 | 0.185 |

Pairwise season correlations: 2023-24×2024-25 +0.26, 2023-24×2025-26 +0.16, 2024-25×2025-26 +0.14 — all
positive.

**Verdict: the pattern does not survive. It is inverted.** 2024-25's delta is POSITIVELY correlated with the
other two (r = +0.26, permutation p = 0.044), and the sign is opposite in only 14 of 57 arms — significantly
LESS often than a coin flip (p < 0.001). Arms that help 2024-25 tend, weakly, to help the others too. The
"when 2024-25 rises the others fall" reading is apophenia driven by a handful of salient recent arms
(penalty fix −5/+114/−67; horizon minutes +109/+45/−84; team-news A +65/−87/+126) against a background of
sixty that mostly move together.

Robustness: without the WC1 grid (n = 46) the three correlations are +0.22 / +0.25 / +0.28 (p 0.15 / 0.09 /
0.06) — same sign, same size, less power. At the family level (n = 10, family means) nothing resolves
(2024-25 vs others r = +0.07, p = 0.85). 2024-25 is not special in the direction claimed; if anything the two
"normal" seasons are the ones that co-move.

## 3. The artefact check

Per-arm mean of the three deltas is −36 with sd 51 — the deltas are NOT mean-zero across seasons (most arms
lose against their reference; see §4), so a within-arm demeaning artefact would not have been the explanation
even if an anti-correlation had appeared; and no demeaning was done. The permutation null (sd of r ≈ 0.13 at
n = 60) is the honest yardstick: the observed +0.26 sits two null-sd on the POSITIVE side.

## 4. What IS real about 2024-25 (the mechanism the pattern was mis-reading)

Two facts, both already on the record, explain why the season looks "different" without any anti-correlation:

1. **Almost every arm loses in 2024-25.** Share of negative deltas: 2023-24 65%, **2024-25 78%**, 2025-26 55%;
   mean delta −24 / **−70** / −14; median −29 / **−67** / −5. That is the 97th-percentile reference
   (`Logs/why_2024_25_log.md`): the reference cells for that season sit near the top of their own path
   distribution, so a perturbation of any kind regresses toward the season's ~2190 median and books a loss on
   average. The other two seasons' references sit mid-distribution and their deltas are centred near zero.
   A +114 in 2024-25 (penalty fix) is therefore a larger surprise than a +114 elsewhere — it is a move from
   a lucky draw to a luckier one — but it is not evidence that the same change hurt the other seasons.
2. **Salah exposure explains most of the 2024-25 spread.** Across 49 2024-25 decision logs on disk (fslog,
   wclog, p1log, p3log, chiplog, oraclelog, penfix), the number of gameweeks the path HELD Salah correlates
   **+0.71** with the path total (captained weeks +0.44). The logs are bimodal: paths that held him all season
   (34 weeks) score 2183–2385; paths that dropped him in an early-wildcard rebuild and held him ~26 weeks score
   2057–2195. The penalty-fix path held him 34 weeks and captained him 23 — the term values a taker correctly,
   so the planner never sells him — and that, not a cross-season trade-off, is where its +92 path came from.
   The concentration mechanism in why_2024_25_log (13.8% top-1 share) is confirmed from the decision logs.

The structural candidates (chip weeks, blank/double calendars, squad-value distributions) were not tested
because there is no anti-correlation left to explain; they remain plausible sources of season-specific
VARIANCE, which is not what the question asked.

## 5. Implications for reading any three-season arm result

- Do not read a sign split across seasons as a trade-off. The seasons co-move weakly and positively; a
  −5 / +114 / −67 is three draws from sd ~60–85 around a small common effect, exactly as the standing
  framing says.
- 2024-25 deltas carry a **negative prior offset of roughly −45 to −55 relative to the other seasons**
  (mean −70 vs −24/−14) that is a property of its reference cell, not of the arm. Quote 2024-25 deltas with
  that offset in view — the half-artefact correction already on record — and do not treat a positive 2024-25
  delta as "the season that gains when others lose".
- The one 2024-25-specific mechanism is Salah exposure: any arm whose 2024-25 total is far from the reference
  should first be checked for whether it held or dropped one player, because ~50% of the variance in that
  season's totals (r² 0.5) is that single decision.
- None of this changes the adjudication rule: component and windowed reads decide; season totals identify.

## 6. Method notes

Deltas parsed from the index's chip-inclusive column (the `(r)` recompute where present, `= path` otherwise),
references per the index's own valid-comparison list; the WC1 grid is measured against the no-chip P1 base, so
its deltas include the wildcard's own effect (a constant within each arm across seasons, so the correlation is
unaffected by it). The sweep's 17 cells are configs rather than interventions but were kept because the
question is about co-movement across seasons, which config cells exhibit as much as arms do; dropping them
STRENGTHENS the positive co-movement (n = 43: 2023-24 r = +0.55, p < 0.001; 2024-25 r = +0.38, p = 0.013;
2025-26 r = +0.22, p = 0.16). Scripts were run inline this session; the extracted delta
table is saved alongside the penalty-fix logs.
