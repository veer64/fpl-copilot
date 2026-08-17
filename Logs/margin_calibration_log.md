# Pairwise margin calibration — is the predicted SPREAD between players honest?

**Date:** 2026-08-14 · **Seasons:** 2023-24, 2024-25, 2025-26 (the full portable set,
see KNOWN_ISSUES #11) · **Status:** ~~measured, replicated, NOT acted on~~ **RETRACTED, see below.**

> ## ⚠ RETRACTED — measured on D1-carrying files while describing them as baseline
>
> **Added 2026-08-17.** Every quantitative figure in this log was measured on
> walk-forward files that contained the D1 scoring terms (saves, goals conceded,
> cards, penalty share) while this log describes them as the pre-D1 baseline. D1
> had been implemented into `squad/assembly.py` earlier the same session, so every
> file regenerated afterwards carried the terms, and no stamp existed to reveal it
> (KNOWN_ISSUES #13 — same class as the availability footgun, #10).
>
> **Void:** the β table in §2, the "~2.5× starter-band exaggeration" headline, the
> three-season replication claim, and the implied 6–10 hit bar derived from them.
>
> The true baseline GK β at step 0 is **0.847**, not 0.409 — measured on
> `data/walkforward_h6_2526_baseline.parquet` (D1 disabled, provenance verified,
> stamps identical to the D1 file). The 0.41-region "baseline" figures below are
> in fact the WITH-D1 values.
>
> The file is retained, not deleted: the method in §1 is sound and reusable, and
> the numbers remain a record of what was believed. Nothing quantitative here may
> be quoted until re-measured on files stamped `d1_terms_active=False`.

---

## 1. The question, and why it is pairwise

The hit diagnosis found 53% of paid transfers cleared the 4-point bar on prediction
while only 40% beat 4 in realised terms. That hinted the model exaggerates
differences between players — and if it does, a fixed 4-point bar is cleared too
easily.

**Calibration was measured on MARGINS BETWEEN PAIRS, not on the level of any single
prediction.** That is the shape of every decision the optimiser makes. A transfer
is never "how many points will X score"; it is "is X better than Y by more than 4".
A model can be perfectly calibrated on levels and still be useless — or dangerous —
on the differences the optimiser actually consumes.

### Method

For every pair of players in the same `(gameweek, position)`:

    predicted margin = e_points[A] - e_points[B]
    realised margin  = actual_points[A] - actual_points[B]

Pairs are oriented so the predicted margin is non-negative, binned by predicted
margin, and the mean realised margin is reported per bin. The headline statistic is
the **through-origin slope β** of realised on predicted: β = 1 is honest, β < 1 means
the model overstates the gap between two players.

All pairs are used — no sampling — via streaming moment accumulation, so the full
~3.8M-pair set per season is covered without materialising it.

Run at two grains, because the transfer decision uses a window:
- **horizon step 0**: the decision gameweek itself.
- **H=3 decayed**: summed over the planning window with decay 0.3, exactly as the
  MIP weights it.

And on two populations: **all rows**, and **started (60+ minutes)**. The project's
standing finding is that all-rows metrics mostly measure "will they play".

---

## 2. The three-season result

Through-origin β:

| season | all rows, step 0 | started, step 0 | all rows, H=3 | **started, H=3 decayed** |
|---|---|---|---|---|
| 2023-24 | 0.929 | 0.585 | 0.907 | **0.540** |
| 2024-25 | 0.950 | 0.671 | 0.916 | **0.662** |
| 2025-26 | 0.958 | 0.418 | 0.929 | **0.389** |

Bin behaviour is monotone in every season — the ratio of realised to predicted falls
as the predicted margin grows. 2025-26, started band, H=3 decayed:

| predicted margin bin | n pairs | mean predicted | mean realised | ratio |
|---|---|---|---|---|
| 0–1 | 91,352 | 0.483 | 0.282 | 0.584 |
| 1–2 | 65,104 | 1.464 | 0.760 | 0.520 |
| 2–4 | 63,374 | 2.828 | 1.045 | 0.370 |
| 4–6 | 17,839 | 4.750 | 1.646 | **0.346** |
| 6+ | 3,499 | 7.289 | 2.956 | 0.406 |

The 4–6 bin is the decision-relevant one: those are the margins that clear the hit
bar on prediction, and they return 1.65 points against a 4-point charge.

*(This bin table was computed before the element-511 crosswalk correction. That
correction touched one never-selected player; the β table above is post-correction.)*

---

## 3. What replicates, and what does not

**REPLICATES — the qualitative finding, in all three seasons.**
All-rows margins are near-calibrated (**0.93–0.96**). The slope collapses once both
players are actually on the pitch (**0.39–0.67**). The all-rows figure is almost
entirely the model correctly separating "will play" from "won't play"; conditional on
both playing, the margin between them is largely fiction. Same story the three-band
slice has told since the LightGBM benchmark, now measured on the quantity the
optimiser consumes.

**DOES NOT REPLICATE — the magnitude.**
2025-26 exaggerates by ~2.4–2.6x; 2023-24 by ~1.7–1.9x; 2024-25 by ~1.5x. That is a
40%+ disagreement across three seasons on the size of the effect.

**DOES NOT REPLICATE — the position ordering.**
Started band, step 0:

| season | GK | DEF | MID | FWD | worst |
|---|---|---|---|---|---|
| 2023-24 | 0.389 | 0.575 | 0.614 | 0.454 | GK |
| 2025-26 | 0.409 | 0.414 | 0.394 | 0.548 | MID |

This matters because it weakens an earlier suggestion that the missing GK/DEF
scoring terms (saves, goals conceded) drive the collapse. GK is worst in 2023-24 —
a season with no DC term for anyone — while MID is worst in 2025-26 despite having
no missing term at all. The missing terms are at most a contributor, not the cause.

---

## 4. The implied hit bar — reported, NOT adopted

If realised ≈ β × predicted, a 4-point charge needs 4/β points of predicted margin
to be worth paying:

| view | β range | implied bar |
|---|---|---|
| started, step 0 | 0.418 – 0.671 | **5.96 – 9.57 pts** |
| started, H=3 decayed | 0.389 – 0.662 | **6.04 – 10.28 pts** |

Every season says the bar should sit materially above 4. **None of them agrees on
how far above** — a 1.7x spread on three observations.

**No shrinkage factor was fitted and no threshold was adopted.** The threshold was
then grid-searched directly and the result was negative; see
`Logs/hit_threshold_log.md`. The bar stays at 4.

---

## 5. Two caveats that bound the whole finding

**The started-only restriction conditions on an outcome the model cannot observe.**
At the deadline nobody knows who will play 60 minutes. β = 0.39 is therefore NOT the
correction a live system should apply — the real population is a mix of started and
unstarted rows, and the all-rows β is near 1. The started band isolates the hard
question; it does not describe the decision environment.

**Regression dilution biases every slope toward zero.** Noise in the predicted margin
— the x-variable — attenuates an OLS slope. Some unknown share of the collapse from
0.95 to 0.42 is therefore an estimation artefact rather than genuine
over-confidence. Separating the two needs an errors-in-variables treatment that has
not been run. Until it is, β should be read as a LOWER bound on calibration
quality, not a point estimate of it.

---

## 6. Open puzzle — carried forward, not resolved

**The 2024-25 minutes model is the worst of the three on every component metric, yet
that season produces the BEST-calibrated pairwise margins.**

    season    P(start) AUC   E[min] MAE      started beta (H=3)
    2023-24       0.9601        11.44             0.540
    2024-25       0.9533        12.44             0.662   <- worst model, best beta
    2025-26       0.9605        11.27             0.389

The minutes gap itself was investigated and is largely explained (see §7). What is
NOT explained is why the season with the weakest minutes model yields the
best-calibrated margins between players. The two move in opposite directions and
there is no account of why.

This sits directly underneath the middle value of the 6–10 hit-bar range, so it is
load-bearing: anyone treating that range as a stable estimate should know the middle
observation is unexplained.

---

## 7. Why 2024-25's minutes model is weaker (investigated, no defect found)

Ruled OUT:
- **Assistant Manager leakage.** 322 AM rows across 20 elements, all 0 minutes, zero
  element overlap with real players. The `position != "AM"` filter is complete.
- **Feature coverage.** Availability-feature null rates rise monotonically across
  seasons (0.314 → 0.414); 2024-25 sits between its neighbours, and 2025-26 has the
  highest null rate with the best metrics.
- **The quarantined training season.** Dropping 2022-23 makes 2024-25 WORSE on every
  metric (AUC 0.9533 → 0.9523, MAE 12.44 → 12.47). Its 18,014 clean labels help.

Found INSTEAD — 2024-25 is intrinsically harder:

| | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| start rate | 0.2812 | 0.3064 | 0.2810 |
| median minutes if played | 87 | 83 | 85 |
| share of appearances a full 90 | 0.4844 | 0.4590 | 0.4703 |
| distinct starters per club | 24.65 | 25.00 | 24.15 |
| **P(start\|started last GW) − P(start\|didn't)** | 0.7281 | **0.7021** | 0.7231 |

More rotation, shorter appearances, fewer full 90s, and the weakest week-to-week
persistence of the start label — which is close to what the model's dominant
features encode.

Decomposing the +1.002 MAE gap against 2023-24: **+0.623 (62%) is band MIX** (the
hard 1–59 and 60–89 bands are much more populated) and **+0.378 (38%) is within-band
error**. 2024-25 is actually BETTER than 2023-24 in the 60–89 and 90-minute bands.

Conclusion: a genuinely harder season, not a defect. The 6–10 range stands as
measured. The within-band third of the gap remains unattributed.
