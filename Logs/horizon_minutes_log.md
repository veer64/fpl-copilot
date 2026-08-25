# Horizon minutes model — build log (2026-08-24)

Scoping and instrument: `Logs/horizon_minutes_scoping_log.md`. This log
records the build, one lever at a time, each measured on the acceptance test
before anything is adopted. **No policy simulation and no season total
appears here.**

## 1. Method (written before any lever was measured)

**Target.** Today `eval/walkforward_season.py` copies the cutoff's minutes
frame unchanged to all six target gameweeks (`p_start`, `p60`, `e_minutes`
byte-identical at steps 0–5 from one cutoff). The cost is the fresh-vs-stale
E[min] MAE gap: +2.3 … +7.0 minutes at k = 1 … 5, with Spearman, Brier and
AUC degrading the same way (scoping log §2).

**Shape.** `squad/horizon_minutes.get_minutes_horizon(up_to_gw=c, steps=0..5)`:
the same decomposition as `squad/minutes.py` — P(start), P(60+|start),
P(came on|bench) with isotonic calibration, E[min|start], E[min|sub] — with
identical hyperparameters, fitted **separately for each step k ≥ 1 on lagged
pairs**: features as of gameweek g (the same feature row the step-0 model
uses: shift-then-roll history plus the as-of availability block), label at
gameweek g+k. Each step learns how much to trust features of that age.
Prediction for c+k uses the cutoff-c feature row with `is_double_gw` forced
to 0 (per-fixture semantics, as today).

**Step 0 untouched by construction.** Step 0 is not re-implemented: the
module calls `minutes.get_minutes()` and returns its frame. Reproduction
check before any lever: a fresh `get_minutes()` call reproduces the
canonical walkforward's step-0 rows with max |diff| = 0.00e+00 on `p_start`,
`p60`, `e_minutes` (2024-25 cutoff 10, 674 rows; 2025-26 cutoff 20, 790
rows). The measure script repeats this check on every step-0 row of every
built season and fails if it moves.

**Walk-forward discipline.** For cutoff c and step k the training pairs are
every prior-season pair plus current-season pairs whose LABEL gameweek g+k
≤ c−1. Nothing after the cutoff enters; the 2022-23 GW1–15 quarantine is
inherited (rows without `starts` never form pairs). Train on the four
labelled seasons as the walk-forward allows (2023-24 trains on 2022-23;
2024-25 on 2022-23 + 2023-24; 2025-26 on all three); measure on the three
simulable seasons.

**Gate and provenance.** `horizon_minutes.HORIZON_MINUTES_ACTIVE` (rests
False) is the single constant a writer consults; `HORIZON_LEVERS` names the
enabled levers; unknown lever names raise. Every emitted row carries
`horizon_minutes_active`, `horizon_levers`, `horizon_step`, `cutoff`,
`minutes_availability`, `train_seasons`, `predict_season`. Builds land in
`data/horizon/hmin_{season}_{levers}.parquet`
(`eval/run_horizon_minutes.py`, atomic write, skip-if-exists).

**Acceptance test** (`eval/measure_horizon_minutes.py`), per step k = 1 … 5,
on the **common population** of single-fixture (gw, element) rows that carry
all three predictions:
- STALE = the cutoff's step-0 frame applied to gw = cutoff+k (today's
  behaviour); NEW = the step-k prediction from the same cutoff; FRESH = the
  step-0 prediction at the target's own cutoff (the ceiling for
  feature-of-that-age models).
- Endpoints: E[min] MAE and Spearman vs `minutes_capped`; Brier and AUC for
  P(start) vs `starts`, P(play) = p_start + 0.30·(1−p_start) vs minutes > 0
  (assembly's composite), P(60+) = p_start·p60 vs minutes ≥ 60.
- Gap closed at step k = (MAE_stale − MAE_new) / (MAE_stale − MAE_fresh).
- Step-0 rows must equal the canonical file exactly; the cross-step flip rate
  (step 0 vs any of 1–5 on opposite sides of 15/60 minutes, same
  player-week) must not exceed today's.
- A lever that fails stops the build; no second lever is stacked on an
  unproven first.

**Levers, build order of record.** 1 refit (existing features, per-step
fit); 2 derivable suspensions (5-in-19, 10-in-32, 15, any red; one fixture
ahead; no red-card lengths, no cup cards); 3 return dates from `asof_news`
("DD Mon" → expected-available gameweek; the club's date is a forecast and
its accuracy never enters; "unknown return date" is its own category); 4
fixture congestion (final-calendar caveat mandatory). Out of scope: AFCON,
squad competition, inferring `starts`.

## 2. Lever 1 — step-aware refit, existing features only

Build: `data/horizon/hmin_{season}_refit.parquet`, all 38 cutoffs × steps
0–5, three seasons (172k / 165k / 176k rows; 45–48 min per season with the
three running in parallel; training pairs 47k → 38k as the lag grows).
Stamps on every row: `horizon_minutes_active=True`, `horizon_levers=refit`.

**Step 0 untouched: PASS.** On single-fixture rows `p_start` and `p60`
reproduce the canonical files exactly (max |diff| 0.00e+00, all three
seasons). `e_minutes` also, except **10 rows in 2025-26 (Junior Kroupi GW1–9,
Ben Gannon-Doak GW1) where the canonical value is exactly 2× the model's
with `p_start`/`p60` identical and `n_fixtures` = 1** — the canonical
value is a sum of two identical rows somewhere upstream of
`collapse_to_gameweek` (the crosswalk carries one row per element, so it
is not #3/#12; cause not located in this session). That is a canonical-file
defect, not a step-0 movement: the model's own output is single-valued and
the measure script names and counts the pattern rather than hiding it.
Recorded as KNOWN_ISSUES #17 (OPEN).

**Flip rate: PASS** (must not rise): 9.6% → 5.2%, 8.0% → 3.5%, 7.0% → 3.3%.

**Acceptance table** (common population per step, singles; st = stale =
today's copied step-0 frame, new = step-k refit, fr = fresh = step 0 at the
target's own cutoff):

| season | k | n | MAE st / new / fr | **MAE gap closed** | RMSE st / new / fr | RMSE gap closed | Spearman st / new | Brier(start) st / new / fr | AUC(start) st / new / fr | AUC(60+) st / new |
|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | 1 | 26,010 | 13.42 / 14.57 / 10.70 | **−42%** | 24.72 / 24.33 / 20.12 | +8% | .735 / .742 | .0968 / .0940 / .0672 | .928 / .932 / .964 | .924 / .927 |
| 2023-24 | 3 | 24,481 | 16.33 / 18.05 / 10.78 | **−31%** | 29.00 / 27.72 / 20.21 | +15% | .661 / .679 | .1292 / .1189 / .0678 | .884 / .894 / .963 | .881 / .891 |
| 2023-24 | 5 | 23,057 | 17.85 / 19.63 / 10.76 | **−25%** | 31.07 / 29.34 / 20.12 | +16% | .619 / .643 | .1474 / .1317 / .0672 | .859 / .872 / .964 | .857 / .869 |
| 2024-25 | 1 | 25,413 | 14.49 / 15.60 / 11.95 | **−44%** | 25.17 / 24.65 / 21.06 | +13% | .746 / .755 | .1044 / .1004 / .0768 | .921 / .927 / .956 | .916 / .922 |
| 2024-25 | 3 | 23,926 | 16.81 / 18.61 / 12.02 | **−38%** | 28.55 / 27.30 / 21.14 | +17% | .682 / .701 | .1308 / .1201 / .0776 | .885 / .897 / .955 | .882 / .893 |
| 2024-25 | 5 | 22,532 | 18.33 / 20.25 / 12.06 | **−31%** | 30.56 / 28.79 / 21.19 | +19% | .641 / .668 | .1461 / .1312 / .0778 | .863 / .877 / .955 | .860 / .874 |
| 2025-26 | 1 | 27,672 | 13.32 / 14.44 / 10.86 | **−46%** | 24.17 / 23.79 / 20.00 | +9% | .749 / .756 | .0961 / .0931 / .0693 | .930 / .934 / .962 | .926 / .930 |
| 2025-26 | 3 | 26,038 | 15.92 / 17.44 / 10.84 | **−30%** | 28.10 / 26.65 / 19.97 | +18% | .681 / .705 | .1256 / .1136 / .0695 | .890 / .903 / .962 | .887 / .900 |
| 2025-26 | 5 | 24,671 | 17.33 / 18.74 / 10.83 | **−22%** | 30.02 / 27.77 / 19.98 | +22% | .641 / .680 | .1410 / .1218 / .0695 | .866 / .889 / .962 | .865 / .886 |

(k = 2 and 4 sit between their neighbours in every column; full output from
`eval/measure_horizon_minutes.py --levers refit`.) Pooled MAE gap closed
by step: −44% / −40% / −33% / −29% / −26%. Pooled RMSE gap closed: ≈ +10% /
+13% / +17% / +18% / +19%. Brier(start) gap closed ≈ +10% at k = 1 rising to
≈ +20–27% at k = 5. Bias (mean predicted − mean actual) is within ±0.4 min
for stale, new and fresh alike.

**Verdict on the test as written: FAIL.** The E[min] endpoint of record is
MAE, and MAE is worse at every step in every season. Per the discipline the
build stops here; **lever 2 is not started.**

**What the failure is made of** (the outcome-band decomposition, every
season, every step): the refit's absolute error is *higher* on the 0-minute
band (e.g. 2023-24 k=1: 7.3 → 8.6) and on the 60+ band (23.7 → 25.3) and
*lower* on the 1–59 band (22.2 → 21.3), while its RMSE, Brier, AUC and
Spearman are all better and its bias is unchanged. Minutes are bimodal
(61% zeros, 27% sixty-plus); a lagged model that honestly spreads
probability across the two modes moves its MEAN prediction toward the
middle, and mean absolute error rewards a committed prediction near one
mode over a calibrated mean between them. The stale frame is more
committed because it is more confident than it should be at lag — the
same over-confidence the flip rate measures, and the refit halves the flip
rate. So MAE and the proper scoring rules disagree for a structural reason,
not a modelling one.

**The instrument question this raises (for decision, not decided here).**
The points equation consumes `e_minutes` and `p_60plus` linearly
(`pts_appear`, `pts_cs`, DC, the attacking rates all scale with them), i.e.
as MEANS. The correct scoring rule for a mean prediction is squared error
(RMSE) with a calibration check, and for the probabilities Brier/AUC —
exactly the endpoints on which the refit improves. MAE was the E[min]
endpoint pre-registered in the scoping log; changing the pre-registered
endpoint after seeing a result is precisely the move the discipline
exists to stop, so it is not changed here. The evidence that it is
mis-specified for a bimodal target is stated above and left for the user.
Under RMSE the refit would close ≈ 10–19% of the gap — a pass in sign,
modest in size: lever 1 alone does not close "most of the gap" under any
endpoint, so the later levers would still be needed.

## 3. Lever 1 sliced on cutoff-knowable partitions (2026-08-24; measurement only, no rebuild)

Why NOT slice on realised minutes: conditioning on the outcome flatters the stale frame, which is over-confident exactly on the players who turned out to start, and it removes the failure mode that matters most (85 minutes predicted, 0 played -- the Gvardiol case). Every partition below was knowable at the cutoff: the STALE p_start band (the incumbent's own view, so both arms are scored on the same rows), squad relevance = the top 30 by the incumbent's step-k e_points within the target gameweek (ranked over every walkforward row at that cutoff, then intersected with the singles population), and position. Common population per slice and step; st = stale, new = step-k refit, fr = fresh. Gap closed = (st - new)/(st - fr). Flip-rate membership uses the k=1 stale view.

### 2023-24

**likely starter (stale p_start >= 0.75)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5,537 | 20.69 / 23.06 / 16.38 | **-55%** | 31.43 / 30.90 / 24.70 | **+8%** | +6.6 / +1.0 | 0.306 / 0.283 / 0.498 | 0.1470 / 0.1413 / 0.0927 | 0.650 / 0.642 / 0.840 | 0.589 / 0.594 | 0.658 / 0.648 | 11% / 10% / 79% | 76.1→69.9 / 43.7→37.5 / 9.8→14.5 |
| 2 | 5,356 | 23.53 / 26.66 / 16.27 | **-43%** | 35.07 / 33.85 / 24.67 | **+12%** | +10.2 / +1.2 | 0.291 / 0.267 / 0.582 | 0.1824 / 0.1686 / 0.0927 | 0.636 / 0.627 / 0.880 | 0.584 / 0.580 | 0.647 / 0.633 | 15% / 11% / 74% | 76.3→66.3 / 45.5→35.7 / 9.8→17.4 |
| 3 | 5,180 | 25.51 / 28.98 / 16.45 | **-38%** | 37.46 / 35.60 / 24.76 | **+15%** | +12.8 / +0.9 | 0.269 / 0.241 / 0.622 | 0.2068 / 0.1857 / 0.0941 | 0.627 / 0.622 / 0.893 | 0.578 / 0.581 | 0.635 / 0.623 | 17% / 11% / 71% | 76.6→63.3 / 46.6→33.8 / 9.8→19.9 |
| 4 | 5,007 | 26.61 / 30.36 / 16.64 | **-38%** | 38.73 / 36.65 / 24.99 | **+15%** | +14.3 / +0.9 | 0.268 / 0.229 / 0.643 | 0.2233 / 0.1977 / 0.0977 | 0.632 / 0.618 / 0.900 | 0.581 / 0.583 | 0.637 / 0.619 | 19% / 11% / 70% | 76.5→61.7 / 46.2→32.9 / 9.7→21.3 |
| 5 | 4,914 | 27.89 / 31.49 / 16.51 | **-32%** | 40.21 / 37.70 / 24.85 | **+16%** | +16.2 / +1.4 | 0.262 / 0.215 / 0.665 | 0.2401 / 0.2091 / 0.0949 | 0.624 / 0.607 / 0.909 | 0.567 / 0.567 | 0.634 / 0.610 | 21% / 12% / 68% | 77.0→60.9 / 46.4→32.0 / 9.6→22.4 |

Flip rate in this slice (k=1 membership, n=4,395): today 17.0% → new 7.4%.

**uncertain (0.25 <= stale p_start < 0.75)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3,706 | 34.06 / 34.00 / 25.66 | **+1%** | 37.29 / 37.49 / 31.44 | **-3%** | -0.3 / +0.4 | 0.199 / 0.190 / 0.560 | 0.2444 / 0.2456 / 0.1800 | 0.606 / 0.607 / 0.804 | 0.578 / 0.569 | 0.625 / 0.608 | 25% / 28% / 47% | 43.0→43.8 / 23.5→23.6 / 35.6→34.9 |
| 2 | 3,630 | 35.00 / 35.06 / 23.20 | **-0%** | 38.22 / 38.29 / 29.81 | **-1%** | +0.7 / +0.1 | 0.156 / 0.161 / 0.634 | 0.2495 / 0.2497 / 0.1600 | 0.587 / 0.590 / 0.845 | 0.538 / 0.533 | 0.610 / 0.603 | 28% / 26% / 46% | 44.1→43.8 / 23.0→22.6 / 36.4→36.9 |
| 3 | 3,556 | 36.06 / 35.65 / 22.05 | **+3%** | 39.13 / 38.90 / 29.00 | **+2%** | +1.6 / +0.0 | 0.124 / 0.145 / 0.675 | 0.2542 / 0.2498 / 0.1514 | 0.570 / 0.587 / 0.862 | 0.539 / 0.529 | 0.587 / 0.591 | 30% / 25% / 45% | 44.3→42.9 / 24.1→22.2 / 37.1→38.1 |
| 4 | 3,412 | 36.18 / 36.13 / 21.49 | **+0%** | 39.23 / 39.39 / 28.71 | **-1%** | +3.3 / +0.5 | 0.130 / 0.118 / 0.688 | 0.2564 / 0.2549 / 0.1443 | 0.563 / 0.569 / 0.873 | 0.545 / 0.527 | 0.579 / 0.568 | 32% / 24% / 44% | 44.1→41.5 / 24.0→22.3 / 37.0→39.7 |
| 5 | 3,343 | 36.73 / 36.03 / 20.59 | **+4%** | 39.76 / 39.40 / 27.78 | **+3%** | +3.4 / -1.0 | 0.105 / 0.144 / 0.717 | 0.2580 / 0.2508 / 0.1375 | 0.558 / 0.583 / 0.884 | 0.522 / 0.541 | 0.574 / 0.588 | 33% / 23% / 43% | 44.7→39.6 / 23.6→21.1 / 37.6→41.3 |

Flip rate in this slice (k=1 membership, n=2,718): today 16.2% → new 8.2%.

**written off (stale p_start < 0.25)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16,767 | 6.46 / 7.47 / 5.52 | **-107%** | 17.73 / 17.09 / 14.43 | **+19%** | -2.4 / -0.0 | 0.432 / 0.461 / 0.527 | 0.0476 / 0.0449 / 0.0338 | 0.825 / 0.869 / 0.941 | 0.850 / 0.872 | 0.824 / 0.868 | 86% / 9% / 5% | 2.0→3.7 / 13.1→13.6 / 71.5→61.7 |
| 2 | 16,253 | 7.87 / 9.25 / 6.11 | **-78%** | 20.59 / 19.41 / 15.28 | **+22%** | -3.9 / -0.1 | 0.410 / 0.464 / 0.564 | 0.0636 / 0.0576 / 0.0380 | 0.792 / 0.859 / 0.952 | 0.817 / 0.858 | 0.793 / 0.859 | 84% / 9% / 7% | 2.1→4.7 / 14.1→14.5 / 73.4→60.1 |
| 3 | 15,745 | 8.85 / 10.47 / 6.36 | **-65%** | 22.36 / 20.87 / 15.61 | **+22%** | -4.8 / -0.1 | 0.393 / 0.464 / 0.587 | 0.0755 / 0.0673 / 0.0403 | 0.765 / 0.844 / 0.957 | 0.797 / 0.849 | 0.768 / 0.845 | 83% / 9% / 8% | 2.1→5.5 / 15.1→15.0 / 74.4→59.1 |
| 4 | 15,079 | 9.66 / 11.35 / 6.50 | **-54%** | 23.75 / 22.01 / 15.73 | **+22%** | -5.6 / -0.2 | 0.383 / 0.472 / 0.609 | 0.0849 / 0.0740 / 0.0413 | 0.752 / 0.846 / 0.962 | 0.786 / 0.849 | 0.753 / 0.845 | 82% / 9% / 9% | 2.1→5.9 / 15.6→15.7 / 75.1→58.8 |
| 5 | 14,800 | 10.25 / 11.99 / 6.63 | **-48%** | 24.71 / 22.77 / 15.85 | **+22%** | -6.2 / -0.3 | 0.377 / 0.476 / 0.621 | 0.0916 / 0.0791 / 0.0421 | 0.747 / 0.843 / 0.964 | 0.776 / 0.847 | 0.750 / 0.842 | 81% / 9% / 9% | 2.2→6.3 / 15.6→15.8 / 75.4→58.2 |

Flip rate in this slice (k=1 membership, n=12,865): today 5.7% → new 3.8%.

**squad-relevant (top 30 by stale step-k e_points in gw)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 987 | 18.44 / 20.62 / 15.02 | **-64%** | 29.76 / 29.70 / 23.98 | **+1%** | +5.8 / +1.6 | 0.352 / 0.316 / 0.514 | 0.1330 / 0.1321 / 0.0884 | 0.657 / 0.622 / 0.836 | 0.551 / 0.536 | 0.655 / 0.630 | 10% / 9% / 81% | 77.8→73.8 / 40.9→37.2 / 8.7→12.3 |
| 2 | 958 | 21.44 / 24.00 / 14.83 | **-39%** | 33.59 / 32.50 / 23.78 | **+11%** | +9.5 / +2.5 | 0.331 / 0.326 / 0.601 | 0.1715 / 0.1574 / 0.0905 | 0.642 / 0.644 / 0.881 | 0.538 / 0.549 | 0.649 / 0.642 | 13% / 11% / 77% | 77.7→70.6 / 45.2→37.0 / 8.7→14.4 |
| 3 | 916 | 23.24 / 26.12 / 14.94 | **-35%** | 35.88 / 33.88 / 23.77 | **+16%** | +11.8 / +2.0 | 0.307 / 0.287 / 0.632 | 0.1958 / 0.1717 / 0.0908 | 0.638 / 0.652 / 0.895 | 0.551 / 0.562 | 0.631 / 0.637 | 15% / 12% / 74% | 77.8→66.7 / 46.5→34.3 / 8.7→16.8 |
| 4 | 889 | 23.99 / 28.17 / 15.31 | **-48%** | 36.92 / 35.78 / 24.41 | **+9%** | +12.5 / +1.2 | 0.262 / 0.222 / 0.629 | 0.2034 / 0.1887 / 0.0945 | 0.623 / 0.606 / 0.895 | 0.542 / 0.549 | 0.618 / 0.600 | 16% / 10% / 73% | 78.4→66.2 / 45.5→35.6 / 8.8→18.6 |
| 5 | 899 | 24.25 / 28.77 / 14.71 | **-47%** | 37.41 / 36.08 / 23.41 | **+9%** | +13.5 / +1.0 | 0.296 / 0.224 / 0.660 | 0.2119 / 0.1967 / 0.0887 | 0.622 / 0.594 / 0.911 | 0.536 / 0.538 | 0.625 / 0.584 | 17% / 10% / 73% | 78.4→65.0 / 45.4→34.6 / 8.4→19.4 |

Flip rate in this slice (k=1 membership, n=743): today 12.0% → new 5.1%.

**position GK**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2,982 | 7.31 / 8.58 / 5.92 | **-92%** | 19.69 / 19.83 / 16.58 | **-5%** | -0.1 / -0.0 | 0.679 / 0.682 / 0.701 | 0.0470 / 0.0479 / 0.0326 | 0.967 / 0.971 / 0.984 | 0.964 / 0.967 | 0.965 / 0.968 | 77% / 1% / 22% | 4.4→5.4 / 31.7→27.5 / 16.4→19.1 |
| 2 | 2,895 | 8.51 / 10.32 / 6.09 | **-75%** | 22.25 / 22.01 / 17.01 | **+4%** | -0.1 / -0.0 | 0.660 / 0.667 / 0.701 | 0.0609 / 0.0593 / 0.0344 | 0.953 / 0.960 / 0.983 | 0.950 / 0.957 | 0.951 / 0.958 | 77% / 1% / 22% | 5.2→6.5 / 29.2→26.0 / 19.2→23.0 |
| 3 | 2,811 | 9.40 / 11.81 / 6.08 | **-72%** | 24.01 / 23.52 / 16.84 | **+7%** | -0.1 / -0.0 | 0.643 / 0.648 / 0.701 | 0.0716 / 0.0682 / 0.0342 | 0.941 / 0.947 / 0.983 | 0.939 / 0.944 | 0.940 / 0.945 | 77% / 1% / 22% | 5.8→7.5 / 29.7→27.1 / 21.1→26.3 |
| 4 | 2,698 | 9.93 / 12.84 / 6.18 | **-78%** | 24.94 / 24.81 / 17.00 | **+2%** | -0.2 / -0.2 | 0.633 / 0.638 / 0.701 | 0.0767 / 0.0754 / 0.0342 | 0.933 / 0.939 / 0.983 | 0.931 / 0.936 | 0.931 / 0.936 | 77% / 1% / 22% | 6.1→8.0 / 30.4→27.8 / 22.3→28.9 |
| 5 | 2,646 | 10.76 / 13.55 / 6.17 | **-61%** | 26.31 / 25.73 / 16.89 | **+6%** | -0.1 / -0.3 | 0.619 / 0.627 / 0.701 | 0.0854 / 0.0814 / 0.0337 | 0.923 / 0.932 / 0.983 | 0.921 / 0.928 | 0.922 / 0.929 | 77% / 1% / 22% | 6.7→8.4 / 32.3→26.6 / 24.0→30.7 |

Flip rate in this slice (k=1 membership, n=2,297): today 6.1% → new 5.1%.

**position DEF**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 8,423 | 15.98 / 17.51 / 12.65 | **-46%** | 28.15 / 27.66 / 22.89 | **+9%** | -0.6 / -0.4 | 0.713 / 0.717 / 0.787 | 0.1113 / 0.1080 / 0.0750 | 0.916 / 0.918 / 0.958 | 0.908 / 0.911 | 0.911 / 0.912 | 60% / 9% / 32% | 9.8→11.3 / 25.7→24.6 / 25.0→27.3 |
| 2 | 8,166 | 17.96 / 19.93 / 12.68 | **-37%** | 30.95 / 29.86 / 22.93 | **+14%** | -0.7 / -0.6 | 0.666 / 0.674 / 0.787 | 0.1332 / 0.1249 / 0.0750 | 0.889 / 0.893 / 0.958 | 0.880 / 0.884 | 0.885 / 0.888 | 60% / 9% / 32% | 11.5→13.4 / 26.0→23.3 / 28.0→31.3 |
| 3 | 7,928 | 19.47 / 21.67 / 12.69 | **-32%** | 32.92 / 31.45 / 22.89 | **+15%** | -0.6 / -0.8 | 0.629 / 0.638 / 0.787 | 0.1495 / 0.1379 / 0.0751 | 0.867 / 0.872 / 0.958 | 0.859 / 0.864 | 0.862 / 0.867 | 60% / 9% / 32% | 12.7→14.8 / 27.4→23.2 / 30.1→34.2 |
| 4 | 7,608 | 20.49 / 22.80 / 12.75 | **-30%** | 34.19 / 32.51 / 22.95 | **+15%** | -0.5 / -0.9 | 0.600 / 0.610 / 0.787 | 0.1625 / 0.1475 / 0.0756 | 0.850 / 0.856 / 0.958 | 0.841 / 0.847 | 0.847 / 0.851 | 60% / 9% / 32% | 13.9→15.8 / 26.2→22.4 / 31.5→36.2 |
| 5 | 7,462 | 21.53 / 23.46 / 12.62 | **-22%** | 35.48 / 33.28 / 22.71 | **+17%** | -0.5 / -1.1 | 0.574 / 0.590 / 0.789 | 0.1743 / 0.1543 / 0.0741 | 0.835 / 0.844 / 0.959 | 0.826 / 0.837 | 0.831 / 0.840 | 60% / 9% / 32% | 14.7→16.2 / 26.4→22.0 / 33.0→37.6 |

Flip rate in this slice (k=1 membership, n=6,481): today 13.5% → new 7.7%.

**position MID**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 11,237 | 13.54 / 14.46 / 10.82 | **-34%** | 23.85 / 23.42 / 19.39 | **+10%** | +0.1 / +0.7 | 0.749 / 0.756 / 0.817 | 0.1003 / 0.0971 / 0.0713 | 0.924 / 0.928 / 0.960 | 0.919 / 0.922 | 0.918 / 0.921 | 58% / 16% / 26% | 6.9→8.3 / 21.5→20.6 / 23.6→24.5 |
| 2 | 10,902 | 15.10 / 16.43 / 10.80 | **-31%** | 26.22 / 25.41 / 19.38 | **+12%** | +0.2 / +0.8 | 0.706 / 0.719 / 0.818 | 0.1179 / 0.1116 / 0.0708 | 0.899 / 0.907 / 0.961 | 0.895 / 0.900 | 0.895 / 0.902 | 58% / 16% / 26% | 8.2→10.2 / 22.4→20.8 / 26.2→28.0 |
| 3 | 10,570 | 16.22 / 17.61 / 10.87 | **-26%** | 27.72 / 26.44 / 19.46 | **+16%** | +0.1 / +0.8 | 0.677 / 0.697 / 0.818 | 0.1307 / 0.1201 / 0.0718 | 0.881 / 0.892 / 0.960 | 0.879 / 0.887 | 0.878 / 0.888 | 58% / 16% / 26% | 9.1→11.3 / 23.4→20.5 / 28.0→30.1 |
| 4 | 10,149 | 16.97 / 18.50 / 10.93 | **-25%** | 28.76 / 27.32 / 19.53 | **+16%** | +0.2 / +0.8 | 0.654 / 0.677 / 0.818 | 0.1404 / 0.1269 / 0.0723 | 0.866 / 0.880 / 0.960 | 0.867 / 0.876 | 0.866 / 0.878 | 58% / 16% / 26% | 9.8→12.1 / 23.9→20.9 / 29.1→31.5 |
| 5 | 9,957 | 17.46 / 19.10 / 10.86 | **-25%** | 29.44 / 27.83 / 19.38 | **+16%** | +0.2 / +0.7 | 0.639 / 0.663 / 0.819 | 0.1458 / 0.1303 / 0.0713 | 0.859 / 0.873 / 0.961 | 0.857 / 0.868 | 0.859 / 0.870 | 58% / 16% / 26% | 10.2→12.6 / 23.9→20.4 / 29.9→32.9 |

Flip rate in this slice (k=1 membership, n=8,599): today 8.2% → new 4.0%.

**position FWD**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3,368 | 12.08 / 12.89 / 9.65 | **-33%** | 22.24 / 21.86 / 17.87 | **+9%** | -0.1 / +0.5 | 0.744 / 0.750 / 0.806 | 0.0933 / 0.0897 / 0.0649 | 0.926 / 0.930 / 0.962 | 0.928 / 0.932 | 0.921 / 0.925 | 62% / 17% / 21% | 5.3→6.5 / 19.6→19.1 / 26.2→27.2 |
| 2 | 3,276 | 13.77 / 14.81 / 9.68 | **-26%** | 24.90 / 23.85 / 17.93 | **+15%** | -0.3 / +0.5 | 0.698 / 0.715 / 0.807 | 0.1122 / 0.1032 / 0.0645 | 0.897 / 0.907 / 0.963 | 0.903 / 0.912 | 0.893 / 0.903 | 62% / 17% / 21% | 6.4→8.0 / 21.3→19.7 / 29.7→31.1 |
| 3 | 3,172 | 14.97 / 15.97 / 9.83 | **-20%** | 26.63 / 25.23 / 18.21 | **+17%** | -0.1 / +0.6 | 0.664 / 0.684 / 0.803 | 0.1248 / 0.1124 / 0.0660 | 0.873 / 0.889 / 0.961 | 0.886 / 0.897 | 0.871 / 0.885 | 63% / 16% / 21% | 7.3→9.1 / 22.6→19.6 / 32.0→33.8 |
| 4 | 3,043 | 15.56 / 16.60 / 9.88 | **-18%** | 27.49 / 25.94 / 18.24 | **+17%** | +0.1 / +0.6 | 0.644 / 0.670 / 0.804 | 0.1331 / 0.1188 / 0.0669 | 0.859 / 0.875 / 0.960 | 0.876 / 0.890 | 0.857 / 0.873 | 63% / 16% / 21% | 7.9→9.5 / 22.6→19.7 / 32.9→35.4 |
| 5 | 2,992 | 16.22 / 17.23 / 9.82 | **-16%** | 28.36 / 26.61 / 18.18 | **+17%** | +0.1 / +0.6 | 0.625 / 0.652 / 0.805 | 0.1404 / 0.1245 / 0.0661 | 0.846 / 0.861 / 0.961 | 0.866 / 0.880 | 0.846 / 0.861 | 63% / 16% / 21% | 8.4→9.9 / 23.2→19.9 / 34.4→37.1 |

Flip rate in this slice (k=1 membership, n=2,601): today 7.5% → new 3.0%.

### 2024-25

**likely starter (stale p_start >= 0.75)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5,740 | 20.34 / 22.70 / 16.90 | **-69%** | 30.55 / 30.06 / 25.11 | **+9%** | +5.5 / +0.0 | 0.330 / 0.316 / 0.501 | 0.1426 / 0.1379 / 0.0996 | 0.648 / 0.645 / 0.811 | 0.582 / 0.583 | 0.656 / 0.655 | 10% / 11% / 79% | 76.0→70.0 / 42.5→36.6 / 10.1→14.7 |
| 2 | 5,571 | 22.35 / 25.81 / 17.15 | **-66%** | 33.31 / 32.38 / 25.45 | **+12%** | +8.1 / -0.7 | 0.315 / 0.295 / 0.552 | 0.1677 / 0.1581 / 0.1024 | 0.639 / 0.635 / 0.844 | 0.581 / 0.587 | 0.647 / 0.641 | 13% / 11% / 76% | 76.0→66.2 / 43.5→34.3 / 10.1→17.7 |
| 3 | 5,431 | 23.93 / 27.75 / 17.13 | **-56%** | 35.23 / 33.67 / 25.38 | **+16%** | +10.1 / -1.0 | 0.303 / 0.283 / 0.587 | 0.1885 / 0.1712 / 0.1021 | 0.635 / 0.639 / 0.863 | 0.590 / 0.597 | 0.640 / 0.641 | 15% / 11% / 74% | 76.0→63.4 / 43.9→32.3 / 10.2→19.7 |
| 4 | 5,258 | 25.17 / 29.03 / 17.03 | **-47%** | 36.73 / 34.79 / 25.24 | **+17%** | +11.8 / -0.4 | 0.289 / 0.265 / 0.616 | 0.2038 / 0.1817 / 0.1014 | 0.638 / 0.634 / 0.878 | 0.588 / 0.595 | 0.635 / 0.632 | 17% / 11% / 72% | 76.1→62.5 / 45.4→32.9 / 10.1→20.6 |
| 5 | 5,135 | 26.11 / 30.25 / 17.17 | **-46%** | 37.75 / 35.53 / 25.50 | **+18%** | +12.9 / -1.0 | 0.280 / 0.250 / 0.630 | 0.2149 / 0.1886 / 0.1034 | 0.632 / 0.630 / 0.882 | 0.590 / 0.593 | 0.635 / 0.633 | 18% / 12% / 70% | 76.1→60.6 / 45.4→31.5 / 10.2→22.3 |

Flip rate in this slice (k=1 membership, n=4,829): today 12.5% → new 4.6%.

**uncertain (0.25 <= stale p_start < 0.75)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 4,443 | 32.74 / 32.65 / 25.34 | **+1%** | 36.18 / 35.93 / 30.79 | **+5%** | +1.2 / +1.3 | 0.233 / 0.249 / 0.560 | 0.2382 / 0.2346 / 0.1822 | 0.633 / 0.644 / 0.800 | 0.587 / 0.592 | 0.644 / 0.642 | 25% / 31% / 44% | 42.2→42.5 / 22.6→22.4 / 34.6→34.4 |
| 2 | 4,324 | 33.50 / 33.58 / 23.80 | **-1%** | 36.92 / 36.72 / 29.76 | **+3%** | +2.1 / +1.2 | 0.204 / 0.217 / 0.621 | 0.2425 / 0.2398 / 0.1697 | 0.616 / 0.620 / 0.827 | 0.571 / 0.581 | 0.630 / 0.622 | 27% / 29% / 44% | 42.8→41.8 / 22.6→22.1 / 35.0→36.1 |
| 3 | 4,193 | 34.12 / 33.93 / 22.83 | **+2%** | 37.44 / 37.10 / 29.27 | **+4%** | +2.9 / +1.1 | 0.183 / 0.192 / 0.646 | 0.2486 / 0.2430 / 0.1646 | 0.593 / 0.603 / 0.838 | 0.574 / 0.569 | 0.609 / 0.606 | 29% / 29% / 43% | 42.8→41.3 / 23.3→21.5 / 35.5→37.3 |
| 4 | 4,070 | 34.48 / 34.23 / 22.46 | **+2%** | 37.73 / 37.37 / 29.11 | **+4%** | +4.0 / +0.9 | 0.181 / 0.180 / 0.659 | 0.2472 / 0.2418 / 0.1604 | 0.600 / 0.602 / 0.846 | 0.562 / 0.565 | 0.610 / 0.597 | 30% / 28% / 41% | 43.2→40.1 / 23.5→20.9 / 35.6→39.0 |
| 5 | 3,969 | 35.18 / 34.84 / 21.88 | **+3%** | 38.35 / 37.93 / 28.58 | **+4%** | +4.1 / +0.7 | 0.145 / 0.148 / 0.680 | 0.2521 / 0.2466 / 0.1551 | 0.582 / 0.583 / 0.855 | 0.549 / 0.545 | 0.590 / 0.583 | 31% / 27% / 42% | 43.5→40.3 / 24.0→21.0 / 36.0→39.5 |

Flip rate in this slice (k=1 membership, n=3,630): today 12.9% → new 4.7%.

**written off (stale p_start < 0.25)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 15,230 | 6.97 / 7.96 / 6.17 | **-125%** | 17.99 / 17.23 / 15.02 | **+26%** | -2.2 / +0.3 | 0.439 / 0.474 / 0.536 | 0.0509 / 0.0471 / 0.0374 | 0.814 / 0.872 / 0.933 | 0.848 / 0.874 | 0.810 / 0.871 | 85% / 10% / 5% | 2.4→4.1 / 13.1→13.3 / 70.8→61.1 |
| 2 | 14,740 | 8.12 / 9.56 / 6.60 | **-95%** | 20.27 / 19.13 / 15.57 | **+24%** | -3.3 / +0.4 | 0.419 / 0.471 / 0.567 | 0.0635 / 0.0574 / 0.0406 | 0.787 / 0.862 / 0.944 | 0.819 / 0.856 | 0.783 / 0.860 | 84% / 10% / 6% | 2.5→5.2 / 13.9→13.7 / 72.4→59.6 |
| 3 | 14,302 | 9.03 / 10.65 / 6.91 | **-77%** | 21.95 / 20.30 / 15.87 | **+27%** | -4.3 / +0.5 | 0.404 / 0.476 / 0.592 | 0.0743 / 0.0647 / 0.0428 | 0.769 / 0.856 / 0.950 | 0.800 / 0.850 | 0.766 / 0.856 | 82% / 10% / 8% | 2.5→6.0 / 14.1→13.7 / 73.3→57.8 |
| 4 | 13,829 | 9.90 / 11.58 / 7.07 | **-59%** | 23.44 / 21.33 / 16.04 | **+29%** | -5.1 / +0.4 | 0.388 / 0.482 / 0.610 | 0.0840 / 0.0715 / 0.0442 | 0.754 / 0.851 / 0.955 | 0.784 / 0.847 | 0.752 / 0.851 | 81% / 10% / 9% | 2.6→6.5 / 14.6→14.0 / 74.0→57.2 |
| 5 | 13,428 | 10.37 / 12.12 / 7.20 | **-55%** | 24.23 / 21.97 / 16.23 | **+28%** | -5.6 / +0.5 | 0.379 / 0.484 / 0.622 | 0.0885 / 0.0751 / 0.0451 | 0.743 / 0.847 / 0.956 | 0.774 / 0.846 | 0.741 / 0.846 | 81% / 10% / 9% | 2.6→6.8 / 15.0→14.5 / 74.8→57.1 |

Flip rate in this slice (k=1 membership, n=12,789): today 4.8% → new 2.8%.

**squad-relevant (top 30 by stale step-k e_points in gw)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1,026 | 18.91 / 20.70 / 16.24 | **-67%** | 29.59 / 29.01 / 25.15 | **+13%** | +5.6 / +1.6 | 0.401 / 0.384 / 0.514 | 0.1400 / 0.1353 / 0.1060 | 0.679 / 0.668 / 0.806 | 0.579 / 0.568 | 0.674 / 0.677 | 9% / 11% / 80% | 76.1→72.2 / 42.7→37.9 / 9.1→12.4 |
| 2 | 995 | 20.85 / 23.51 / 16.76 | **-65%** | 32.50 / 31.32 / 25.88 | **+18%** | +8.3 / +1.6 | 0.381 / 0.368 / 0.557 | 0.1637 / 0.1526 / 0.1112 | 0.646 / 0.646 / 0.828 | 0.556 / 0.568 | 0.667 / 0.664 | 12% / 11% / 77% | 77.0→69.3 / 41.8→34.7 / 9.0→14.7 |
| 3 | 983 | 22.33 / 25.77 / 17.02 | **-65%** | 34.23 / 33.00 / 25.99 | **+15%** | +10.1 / +1.5 | 0.357 / 0.300 / 0.561 | 0.1817 / 0.1696 / 0.1126 | 0.661 / 0.637 / 0.840 | 0.574 / 0.572 | 0.683 / 0.654 | 14% / 12% / 74% | 77.0→67.8 / 41.3→34.5 / 9.2→16.5 |
| 4 | 942 | 22.95 / 26.54 / 16.77 | **-58%** | 34.89 / 33.43 / 25.83 | **+16%** | +10.3 / +1.0 | 0.330 / 0.264 / 0.581 | 0.1906 / 0.1749 / 0.1153 | 0.636 / 0.619 / 0.842 | 0.554 / 0.563 | 0.652 / 0.631 | 14% / 12% / 74% | 77.1→66.9 / 43.8→35.3 / 9.3→17.5 |
| 5 | 907 | 23.84 / 28.10 / 16.80 | **-61%** | 35.94 / 34.60 / 25.95 | **+13%** | +11.9 / +1.0 | 0.339 / 0.243 / 0.610 | 0.2021 / 0.1848 / 0.1148 | 0.643 / 0.606 / 0.858 | 0.566 / 0.550 | 0.656 / 0.613 | 16% / 11% / 73% | 76.6→65.8 / 45.9→36.1 / 9.1→18.8 |

Flip rate in this slice (k=1 membership, n=818): today 7.3% → new 2.9%.

**position GK**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2,661 | 9.63 / 11.03 / 7.32 | **-61%** | 22.93 / 22.59 / 18.38 | **+8%** | -0.2 / -0.2 | 0.690 / 0.701 / 0.729 | 0.0640 / 0.0621 / 0.0405 | 0.950 / 0.959 / 0.977 | 0.947 / 0.954 | 0.949 / 0.957 | 73% / 1% / 26% | 6.3→7.2 / 36.5→34.5 / 18.2→20.9 |
| 2 | 2,579 | 10.82 / 13.01 / 7.51 | **-66%** | 25.14 / 24.57 / 18.76 | **+9%** | -0.2 / -0.3 | 0.669 / 0.685 / 0.727 | 0.0775 / 0.0739 / 0.0423 | 0.936 / 0.948 / 0.976 | 0.933 / 0.944 | 0.934 / 0.946 | 73% / 1% / 26% | 7.1→8.6 / 37.1→33.1 / 20.4→24.8 |
| 3 | 2,504 | 11.83 / 14.48 / 7.39 | **-60%** | 26.84 / 25.87 / 18.41 | **+12%** | -0.1 / -0.2 | 0.649 / 0.672 / 0.730 | 0.0884 / 0.0820 / 0.0407 | 0.924 / 0.940 / 0.977 | 0.921 / 0.937 | 0.922 / 0.938 | 73% / 1% / 26% | 7.9→9.7 / 38.2→32.9 / 22.2→27.4 |
| 4 | 2,424 | 12.73 / 15.47 / 7.44 | **-52%** | 28.27 / 26.99 / 18.55 | **+13%** | +0.0 / -0.2 | 0.627 / 0.656 / 0.729 | 0.0983 / 0.0896 / 0.0415 | 0.910 / 0.929 / 0.977 | 0.907 / 0.926 | 0.908 / 0.927 | 73% / 0% / 26% | 8.6→10.4 / 37.7→32.0 / 23.8→29.4 |
| 5 | 2,360 | 13.66 / 16.51 / 7.43 | **-46%** | 29.63 / 28.08 / 18.57 | **+14%** | +0.1 / -0.3 | 0.613 / 0.643 / 0.729 | 0.1081 / 0.0970 / 0.0414 | 0.901 / 0.922 / 0.977 | 0.897 / 0.917 | 0.899 / 0.919 | 73% / 1% / 26% | 9.2→10.9 / 37.3→32.5 / 25.4→31.6 |

Flip rate in this slice (k=1 membership, n=2,208): today 9.1% → new 5.9%.

**position DEF**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 8,512 | 16.06 / 17.61 / 13.04 | **-51%** | 27.46 / 26.98 / 22.78 | **+10%** | -0.1 / +0.0 | 0.723 / 0.731 / 0.792 | 0.1112 / 0.1070 / 0.0778 | 0.915 / 0.920 / 0.955 | 0.909 / 0.913 | 0.912 / 0.917 | 59% / 9% / 32% | 10.3→12.0 / 25.5→24.0 / 23.7→26.0 |
| 2 | 8,247 | 17.57 / 19.71 / 13.08 | **-47%** | 29.73 / 28.71 / 22.82 | **+15%** | -0.0 / -0.1 | 0.685 / 0.699 / 0.792 | 0.1274 / 0.1193 / 0.0781 | 0.893 / 0.902 / 0.955 | 0.887 / 0.894 | 0.890 / 0.899 | 59% / 9% / 32% | 11.7→13.8 / 26.0→23.1 / 25.8→29.4 |
| 3 | 8,006 | 18.66 / 21.11 / 13.10 | **-44%** | 31.21 / 29.79 / 22.82 | **+17%** | -0.0 / -0.2 | 0.655 / 0.674 / 0.793 | 0.1400 / 0.1280 / 0.0782 | 0.876 / 0.888 / 0.955 | 0.869 / 0.878 | 0.875 / 0.886 | 58% / 9% / 32% | 12.7→15.1 / 26.3→22.2 / 27.2→31.7 |
| 4 | 7,742 | 19.62 / 22.16 / 13.17 | **-39%** | 32.50 / 30.74 / 22.88 | **+18%** | -0.0 / -0.2 | 0.631 / 0.654 / 0.792 | 0.1501 / 0.1353 / 0.0786 | 0.864 / 0.876 / 0.955 | 0.855 / 0.867 | 0.862 / 0.873 | 58% / 9% / 32% | 13.5→16.0 / 26.9→22.1 / 28.5→33.4 |
| 5 | 7,528 | 20.31 / 23.00 / 13.19 | **-38%** | 33.36 / 31.42 / 22.91 | **+19%** | +0.0 / -0.4 | 0.616 / 0.637 / 0.792 | 0.1576 / 0.1410 / 0.0786 | 0.854 / 0.865 / 0.955 | 0.845 / 0.857 | 0.852 / 0.862 | 58% / 9% / 32% | 14.1→16.6 / 27.5→21.9 / 29.4→35.0 |

Flip rate in this slice (k=1 membership, n=7,093): today 10.3% → new 4.5%.

**position MID**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 11,409 | 15.19 / 15.90 / 12.75 | **-29%** | 24.94 / 24.22 / 21.11 | **+19%** | +0.4 / +0.6 | 0.753 / 0.764 / 0.819 | 0.1148 / 0.1092 / 0.0880 | 0.908 / 0.915 / 0.944 | 0.917 / 0.922 | 0.901 / 0.908 | 53% / 19% / 28% | 8.1→9.2 / 21.6→20.6 / 24.5→25.5 |
| 2 | 11,064 | 16.31 / 17.51 / 12.79 | **-34%** | 26.51 / 25.73 / 21.16 | **+15%** | +0.4 / +0.5 | 0.720 / 0.731 / 0.819 | 0.1269 / 0.1205 / 0.0881 | 0.891 / 0.897 / 0.944 | 0.898 / 0.901 | 0.885 / 0.890 | 53% / 19% / 28% | 9.2→10.8 / 22.1→20.2 / 26.0→28.5 |
| 3 | 10,751 | 17.24 / 18.44 / 12.81 | **-27%** | 27.76 / 26.52 / 21.20 | **+19%** | +0.5 / +0.4 | 0.695 / 0.711 / 0.818 | 0.1393 / 0.1276 / 0.0889 | 0.874 / 0.884 / 0.943 | 0.885 / 0.890 | 0.869 / 0.879 | 53% / 19% / 28% | 10.1→11.8 / 22.5→19.8 / 27.5→30.2 |
| 4 | 10,414 | 18.06 / 19.22 / 12.79 | **-22%** | 28.81 / 27.20 / 21.16 | **+21%** | +0.5 / +0.5 | 0.671 / 0.694 / 0.818 | 0.1476 / 0.1326 / 0.0884 | 0.861 / 0.875 / 0.944 | 0.872 / 0.881 | 0.857 / 0.870 | 54% / 19% / 28% | 10.8→12.6 / 23.1→19.8 / 28.6→31.5 |
| 5 | 10,141 | 18.55 / 19.85 / 12.82 | **-23%** | 29.38 / 27.75 / 21.19 | **+20%** | +0.5 / +0.3 | 0.658 / 0.681 / 0.819 | 0.1514 / 0.1366 / 0.0885 | 0.854 / 0.866 / 0.943 | 0.864 / 0.873 | 0.850 / 0.862 | 54% / 18% / 28% | 11.3→13.1 / 23.5→19.8 / 29.2→32.8 |

Flip rate in this slice (k=1 membership, n=9,558): today 6.7% → new 2.4%.

**position FWD**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2,831 | 11.53 / 12.67 / 9.76 | **-65%** | 20.47 / 20.53 / 17.49 | **-2%** | +0.4 / +0.9 | 0.786 / 0.788 / 0.832 | 0.0799 / 0.0808 / 0.0626 | 0.947 / 0.947 / 0.967 | 0.938 / 0.939 | 0.941 / 0.941 | 58% / 18% / 24% | 5.2→6.6 / 18.9→18.6 / 21.3→23.0 |
| 2 | 2,745 | 13.02 / 14.62 / 9.87 | **-51%** | 22.92 / 22.44 / 17.66 | **+9%** | +0.5 / +1.2 | 0.740 / 0.753 / 0.831 | 0.0963 / 0.0934 / 0.0639 | 0.925 / 0.930 / 0.966 | 0.910 / 0.917 | 0.921 / 0.927 | 58% / 18% / 24% | 6.7→8.7 / 19.6→18.8 / 23.6→26.0 |
| 3 | 2,665 | 14.19 / 15.69 / 9.93 | **-35%** | 24.63 / 23.60 / 17.76 | **+15%** | +0.5 / +1.4 | 0.703 / 0.725 / 0.832 | 0.1085 / 0.1021 / 0.0648 | 0.905 / 0.916 / 0.965 | 0.887 / 0.897 | 0.902 / 0.914 | 58% / 18% / 24% | 7.7→10.1 / 19.9→17.7 / 25.5→27.8 |
| 4 | 2,577 | 15.02 / 16.59 / 9.89 | **-31%** | 25.95 / 24.55 / 17.67 | **+17%** | +0.6 / +1.8 | 0.676 / 0.707 / 0.834 | 0.1174 / 0.1097 / 0.0648 | 0.889 / 0.903 / 0.965 | 0.873 / 0.885 | 0.887 / 0.903 | 58% / 18% / 24% | 8.5→11.1 / 20.6→18.0 / 26.7→29.0 |
| 5 | 2,503 | 15.85 / 17.16 / 9.98 | **-22%** | 27.06 / 25.06 / 17.87 | **+22%** | +0.7 / +2.0 | 0.650 / 0.694 / 0.832 | 0.1261 / 0.1118 / 0.0661 | 0.875 / 0.901 / 0.964 | 0.860 / 0.879 | 0.875 / 0.899 | 58% / 18% / 24% | 9.2→11.8 / 21.1→17.9 / 28.2→29.7 |

Flip rate in this slice (k=1 membership, n=2,389): today 5.3% → new 2.8%.

### 2025-26

**likely starter (stale p_start >= 0.75)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5,710 | 20.48 / 22.97 / 16.63 | **-65%** | 30.82 / 30.33 / 24.72 | **+8%** | +5.5 / +0.1 | 0.326 / 0.314 / 0.515 | 0.1436 / 0.1387 / 0.0962 | 0.635 / 0.632 / 0.822 | 0.567 / 0.567 | 0.657 / 0.645 | 10% / 11% / 79% | 76.4→70.7 / 43.6→38.1 / 10.1→14.8 |
| 2 | 5,574 | 23.11 / 26.53 / 16.71 | **-53%** | 34.28 / 33.05 / 24.74 | **+13%** | +9.0 / +0.3 | 0.311 / 0.298 / 0.591 | 0.1788 / 0.1653 / 0.0985 | 0.633 / 0.630 / 0.867 | 0.556 / 0.559 | 0.645 / 0.637 | 13% / 12% / 75% | 76.7→67.4 / 45.8→36.5 / 10.0→17.7 |
| 3 | 5,409 | 25.11 / 28.73 / 16.78 | **-43%** | 36.67 / 34.67 / 24.87 | **+17%** | +11.7 / +0.6 | 0.298 / 0.283 / 0.634 | 0.2047 / 0.1820 / 0.1002 | 0.617 / 0.622 / 0.880 | 0.561 / 0.571 | 0.636 / 0.636 | 16% / 12% / 72% | 76.6→64.5 / 46.2→34.6 / 10.0→19.7 |
| 4 | 5,236 | 26.16 / 29.97 / 16.69 | **-40%** | 37.88 / 35.49 / 24.60 | **+18%** | +13.0 / +0.4 | 0.295 / 0.278 / 0.658 | 0.2180 / 0.1896 / 0.0996 | 0.619 / 0.622 / 0.893 | 0.566 / 0.576 | 0.634 / 0.631 | 18% / 12% / 70% | 76.5→62.7 / 46.8→34.0 / 10.0→21.1 |
| 5 | 5,142 | 27.27 / 31.00 / 16.80 | **-36%** | 39.13 / 36.24 / 24.78 | **+20%** | +14.4 / +0.4 | 0.280 / 0.264 / 0.666 | 0.2325 / 0.1978 / 0.1009 | 0.618 / 0.619 / 0.894 | 0.558 / 0.570 | 0.629 / 0.629 | 19% / 12% / 69% | 76.7→61.4 / 46.8→32.4 / 10.1→22.3 |

Flip rate in this slice (k=1 membership, n=4,854): today 11.8% → new 4.8%.

**uncertain (0.25 <= stale p_start < 0.75)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 4,503 | 32.89 / 33.02 / 25.82 | **-2%** | 36.25 / 36.18 / 31.06 | **+1%** | +1.0 / +0.9 | 0.231 / 0.234 / 0.554 | 0.2411 / 0.2390 / 0.1844 | 0.621 / 0.624 / 0.795 | 0.585 / 0.582 | 0.649 / 0.638 | 24% / 32% / 44% | 41.9→42.3 / 23.2→23.0 / 35.2→35.4 |
| 2 | 4,373 | 33.91 / 34.01 / 24.00 | **-1%** | 37.15 / 36.97 / 29.88 | **+2%** | +1.3 / +0.6 | 0.199 / 0.203 / 0.623 | 0.2452 / 0.2423 / 0.1700 | 0.605 / 0.608 / 0.826 | 0.579 / 0.576 | 0.620 / 0.612 | 26% / 30% / 44% | 42.2→42.0 / 23.6→22.7 / 36.0→37.0 |
| 3 | 4,227 | 34.92 / 34.74 / 23.12 | **+2%** | 38.05 / 37.55 / 29.37 | **+6%** | +2.2 / +0.5 | 0.175 / 0.205 / 0.659 | 0.2508 / 0.2430 / 0.1601 | 0.583 / 0.600 / 0.846 | 0.571 / 0.584 | 0.603 / 0.606 | 29% / 28% / 43% | 42.5→40.9 / 24.2→22.7 / 36.6→38.3 |
| 4 | 4,094 | 35.26 / 34.71 / 22.31 | **+4%** | 38.51 / 37.68 / 28.82 | **+9%** | +3.1 / +0.2 | 0.132 / 0.189 / 0.677 | 0.2538 / 0.2423 / 0.1532 | 0.571 / 0.605 / 0.858 | 0.549 / 0.576 | 0.584 / 0.602 | 30% / 28% / 42% | 43.1→39.8 / 24.0→21.7 / 37.1→39.6 |
| 5 | 4,033 | 35.65 / 34.83 / 21.85 | **+6%** | 38.78 / 37.67 / 28.60 | **+11%** | +3.7 / +0.5 | 0.134 / 0.207 / 0.692 | 0.2537 / 0.2389 / 0.1506 | 0.571 / 0.615 / 0.863 | 0.559 / 0.584 | 0.584 / 0.611 | 32% / 27% / 42% | 42.9→39.4 / 24.6→21.5 / 37.2→39.9 |

Flip rate in this slice (k=1 membership, n=3,623): today 11.1% → new 3.8%.

**written off (stale p_start < 0.25)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 17,459 | 5.93 / 6.86 / 5.12 | **-115%** | 16.62 / 16.08 / 13.61 | **+18%** | -1.9 / +0.2 | 0.426 / 0.456 / 0.509 | 0.0433 / 0.0405 / 0.0308 | 0.850 / 0.893 / 0.951 | 0.870 / 0.894 | 0.848 / 0.892 | 88% / 8% / 5% | 2.0→3.5 / 12.7→13.3 / 69.9→61.3 |
| 2 | 16,965 | 7.07 / 8.36 / 5.53 | **-84%** | 19.01 / 18.10 / 14.14 | **+19%** | -3.0 / +0.2 | 0.413 / 0.468 / 0.545 | 0.0562 / 0.0512 / 0.0336 | 0.821 / 0.884 / 0.960 | 0.843 / 0.885 | 0.818 / 0.882 | 86% / 8% / 6% | 2.0→4.4 / 14.2→13.9 / 71.7→59.9 |
| 3 | 16,402 | 8.00 / 9.26 / 5.72 | **-55%** | 20.90 / 19.18 / 14.38 | **+26%** | -4.1 / -0.0 | 0.404 / 0.489 / 0.578 | 0.0673 / 0.0576 / 0.0360 | 0.793 / 0.885 / 0.964 | 0.822 / 0.886 | 0.789 / 0.882 | 85% / 8% / 7% | 2.0→4.8 / 14.5→13.9 / 73.2→58.6 |
| 4 | 15,839 | 8.72 / 10.03 / 5.85 | **-46%** | 22.21 / 19.99 / 14.54 | **+29%** | -4.7 / +0.1 | 0.384 / 0.492 / 0.591 | 0.0746 / 0.0618 / 0.0366 | 0.772 / 0.885 / 0.967 | 0.802 / 0.882 | 0.770 / 0.884 | 84% / 8% / 8% | 2.1→5.3 / 15.4→14.4 / 74.2→57.3 |
| 5 | 15,496 | 9.26 / 10.49 / 5.98 | **-37%** | 23.13 / 20.55 / 14.78 | **+31%** | -5.3 / -0.2 | 0.373 / 0.498 / 0.602 | 0.0813 / 0.0661 / 0.0379 | 0.759 / 0.882 / 0.968 | 0.789 / 0.880 | 0.756 / 0.881 | 83% / 8% / 8% | 2.1→5.4 / 15.8→14.8 / 74.7→57.1 |

Flip rate in this slice (k=1 membership, n=14,713): today 4.4% → new 2.7%.

**squad-relevant (top 30 by stale step-k e_points in gw)**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1,037 | 17.97 / 20.46 / 14.67 | **-75%** | 28.94 / 28.66 / 23.21 | **+5%** | +5.2 / +0.8 | 0.355 / 0.329 / 0.491 | 0.1269 / 0.1238 / 0.0848 | 0.658 / 0.649 / 0.824 | 0.584 / 0.578 | 0.687 / 0.665 | 10% / 9% / 81% | 76.9→72.7 / 40.1→36.4 / 8.5→12.5 |
| 2 | 1,018 | 19.90 / 23.44 / 14.75 | **-68%** | 31.94 / 31.04 / 23.09 | **+10%** | +7.9 / +0.4 | 0.357 / 0.333 / 0.566 | 0.1519 / 0.1431 / 0.0836 | 0.640 / 0.632 / 0.864 | 0.575 / 0.569 | 0.658 / 0.652 | 12% / 9% / 79% | 78.3→70.7 / 43.2→35.3 / 8.2→14.8 |
| 3 | 976 | 21.66 / 25.74 / 15.08 | **-62%** | 33.86 / 32.58 / 23.50 | **+12%** | +10.0 / +0.5 | 0.349 / 0.310 / 0.625 | 0.1787 / 0.1621 / 0.0896 | 0.639 / 0.637 / 0.887 | 0.593 / 0.574 | 0.665 / 0.653 | 14% / 10% / 76% | 77.3→67.9 / 45.4→35.2 / 8.4→16.8 |
| 4 | 948 | 21.77 / 26.58 / 14.66 | **-68%** | 34.27 / 32.99 / 22.33 | **+11%** | +10.3 / -0.8 | 0.323 / 0.290 / 0.634 | 0.1845 / 0.1656 / 0.0875 | 0.617 / 0.636 / 0.891 | 0.562 / 0.563 | 0.654 / 0.656 | 14% / 10% / 76% | 78.0→67.0 / 44.9→33.2 / 8.2→18.2 |
| 5 | 940 | 23.55 / 27.79 / 15.38 | **-52%** | 36.33 / 34.02 / 23.48 | **+18%** | +12.5 / +0.2 | 0.346 / 0.319 / 0.647 | 0.2005 / 0.1730 / 0.0930 | 0.650 / 0.652 / 0.890 | 0.576 / 0.574 | 0.671 / 0.667 | 16% / 11% / 73% | 77.8→64.7 / 45.6→32.0 / 8.3→19.0 |

Flip rate in this slice (k=1 membership, n=866): today 8.5% → new 3.8%.

**position GK**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3,198 | 6.69 / 7.88 / 5.15 | **-77%** | 18.68 / 18.80 / 15.04 | **-3%** | -0.4 / -0.5 | 0.671 / 0.675 / 0.694 | 0.0426 / 0.0431 / 0.0272 | 0.966 / 0.969 / 0.981 | 0.964 / 0.967 | 0.966 / 0.968 | 78% / 0% / 22% | 4.0→4.7 / 33.8→35.5 / 15.9→18.8 |
| 2 | 3,109 | 7.81 / 9.52 / 5.08 | **-62%** | 21.21 / 20.97 / 14.82 | **+4%** | -0.4 / -0.6 | 0.651 / 0.659 / 0.696 | 0.0553 / 0.0541 / 0.0263 | 0.952 / 0.957 / 0.983 | 0.950 / 0.956 | 0.952 / 0.957 | 78% / 0% / 22% | 4.7→5.7 / 38.6→35.9 / 18.3→22.7 |
| 3 | 3,008 | 8.71 / 10.68 / 5.18 | **-56%** | 23.04 / 22.39 / 15.20 | **+8%** | -0.3 / -0.5 | 0.637 / 0.647 / 0.694 | 0.0655 / 0.0617 / 0.0277 | 0.942 / 0.949 / 0.981 | 0.940 / 0.947 | 0.942 / 0.949 | 78% / 0% / 22% | 5.3→6.5 / 36.0→34.7 / 20.2→25.1 |
| 4 | 2,907 | 9.22 / 11.39 / 5.10 | **-53%** | 24.02 / 23.03 / 14.82 | **+11%** | -0.3 / -0.7 | 0.629 / 0.644 / 0.697 | 0.0722 / 0.0658 / 0.0263 | 0.935 / 0.945 / 0.983 | 0.934 / 0.944 | 0.936 / 0.945 | 78% / 0% / 22% | 5.7→6.9 / 31.2→31.0 / 21.2→27.0 |
| 5 | 2,848 | 9.83 / 12.00 / 5.04 | **-45%** | 25.13 / 23.83 / 14.69 | **+12%** | -0.2 / -0.6 | 0.616 / 0.633 / 0.696 | 0.0790 / 0.0705 / 0.0264 | 0.927 / 0.938 / 0.983 | 0.926 / 0.937 | 0.928 / 0.938 | 78% / 0% / 22% | 6.1→7.3 / 35.8→34.8 / 22.4→28.3 |

Flip rate in this slice (k=1 membership, n=2,688): today 5.6% → new 4.0%.

**position DEF**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 9,067 | 16.04 / 17.50 / 13.04 | **-49%** | 27.56 / 27.06 / 22.80 | **+10%** | -0.1 / +0.0 | 0.728 / 0.734 / 0.793 | 0.1110 / 0.1071 / 0.0782 | 0.916 / 0.920 / 0.955 | 0.917 / 0.920 | 0.912 / 0.915 | 59% / 10% / 31% | 9.8→11.2 / 26.5→25.3 / 24.8→27.1 |
| 2 | 8,825 | 17.61 / 19.74 / 13.04 | **-46%** | 29.85 / 28.95 / 22.78 | **+13%** | -0.0 / -0.0 | 0.690 / 0.701 / 0.794 | 0.1291 / 0.1217 / 0.0783 | 0.895 / 0.899 / 0.955 | 0.895 / 0.901 | 0.891 / 0.895 | 59% / 9% / 31% | 11.1→13.1 / 27.7→25.2 / 27.0→30.7 |
| 3 | 8,541 | 18.96 / 21.04 / 13.03 | **-35%** | 31.67 / 29.92 / 22.77 | **+20%** | -0.1 / -0.3 | 0.655 / 0.678 / 0.794 | 0.1450 / 0.1296 / 0.0786 | 0.874 / 0.885 / 0.955 | 0.875 / 0.888 | 0.871 / 0.882 | 59% / 9% / 31% | 12.2→14.2 / 28.5→24.1 / 29.0→33.2 |
| 4 | 8,258 | 19.89 / 21.95 / 13.00 | **-30%** | 32.92 / 30.63 / 22.71 | **+22%** | -0.1 / -0.4 | 0.629 / 0.662 / 0.795 | 0.1553 / 0.1349 / 0.0782 | 0.858 / 0.876 / 0.955 | 0.861 / 0.879 | 0.855 / 0.873 | 59% / 9% / 31% | 12.9→14.9 / 29.1→24.3 / 30.4→34.7 |
| 5 | 8,094 | 20.47 / 22.50 / 13.15 | **-28%** | 33.58 / 30.99 / 22.97 | **+24%** | -0.0 / -0.5 | 0.613 / 0.652 / 0.792 | 0.1617 / 0.1380 / 0.0798 | 0.848 / 0.870 / 0.954 | 0.851 / 0.872 | 0.846 / 0.868 | 59% / 9% / 31% | 13.5→15.4 / 29.4→23.7 / 31.1→35.7 |

Flip rate in this slice (k=1 membership, n=7,622): today 9.6% → new 4.0%.

**position MID**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12,361 | 13.30 / 14.20 / 10.83 | **-37%** | 23.42 / 22.97 / 19.29 | **+11%** | +0.3 / +0.5 | 0.754 / 0.763 / 0.816 | 0.1002 / 0.0963 / 0.0731 | 0.923 / 0.929 / 0.958 | 0.931 / 0.935 | 0.919 / 0.923 | 60% / 16% / 25% | 6.5→7.7 / 22.0→21.2 / 24.2→25.7 |
| 2 | 12,022 | 14.75 / 15.88 / 10.81 | **-29%** | 25.58 / 24.66 / 19.26 | **+14%** | +0.4 / +0.6 | 0.716 / 0.732 / 0.816 | 0.1161 / 0.1083 / 0.0731 | 0.900 / 0.910 / 0.958 | 0.910 / 0.917 | 0.897 / 0.906 | 60% / 16% / 25% | 7.7→9.3 / 23.4→21.1 / 26.4→28.7 |
| 3 | 11,626 | 15.95 / 16.99 / 10.79 | **-20%** | 27.35 / 25.80 / 19.25 | **+19%** | +0.5 / +0.6 | 0.681 / 0.709 / 0.816 | 0.1296 / 0.1164 / 0.0731 | 0.879 / 0.896 / 0.958 | 0.891 / 0.905 | 0.876 / 0.892 | 60% / 15% / 25% | 8.7→10.2 / 23.9→21.0 / 28.5→30.9 |
| 4 | 11,234 | 16.65 / 17.67 / 10.70 | **-17%** | 28.32 / 26.36 / 19.10 | **+21%** | +0.6 / +0.8 | 0.659 / 0.694 / 0.817 | 0.1365 / 0.1195 / 0.0720 | 0.868 / 0.890 / 0.960 | 0.878 / 0.896 | 0.864 / 0.886 | 60% / 15% / 25% | 9.4→11.0 / 24.3→20.5 / 29.6→32.2 |
| 5 | 11,018 | 17.34 / 18.19 / 10.70 | **-13%** | 29.26 / 26.87 / 19.14 | **+24%** | +0.6 / +0.6 | 0.636 / 0.681 / 0.816 | 0.1442 / 0.1239 / 0.0721 | 0.855 / 0.881 / 0.959 | 0.866 / 0.889 | 0.853 / 0.878 | 60% / 15% / 25% | 10.1→11.4 / 24.6→20.5 / 30.6→33.4 |

Flip rate in this slice (k=1 membership, n=10,337): today 6.2% → new 3.0%.

**position FWD**

| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | band MAE st→new 0 / 1-59 / 60+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3,046 | 12.24 / 13.16 / 10.54 | **-54%** | 21.28 / 21.20 / 18.39 | **+3%** | +0.7 / +0.8 | 0.791 / 0.793 / 0.834 | 0.0918 / 0.0909 / 0.0714 | 0.934 / 0.934 / 0.958 | 0.943 / 0.944 | 0.929 / 0.928 | 57% / 20% / 23% | 5.3→6.2 / 20.0→19.6 / 22.6→24.4 |
| 2 | 2,956 | 13.54 / 14.79 / 10.49 | **-41%** | 23.20 / 22.86 / 18.33 | **+7%** | +0.7 / +0.8 | 0.758 / 0.762 / 0.835 | 0.1064 / 0.1029 / 0.0717 | 0.913 / 0.915 / 0.958 | 0.923 / 0.925 | 0.908 / 0.909 | 56% / 20% / 23% | 6.2→7.8 / 21.2→19.4 / 24.6→27.7 |
| 3 | 2,863 | 14.32 / 15.64 / 10.46 | **-34%** | 24.34 / 23.66 / 18.24 | **+11%** | +0.7 / +0.6 | 0.732 / 0.742 / 0.836 | 0.1150 / 0.1085 / 0.0713 | 0.899 / 0.905 / 0.958 | 0.908 / 0.912 | 0.895 / 0.899 | 57% / 20% / 23% | 7.0→8.7 / 21.3→18.8 / 26.1→29.8 |
| 4 | 2,770 | 14.95 / 16.29 / 10.46 | **-30%** | 25.21 / 24.35 / 18.22 | **+12%** | +0.6 / +0.5 | 0.713 / 0.726 / 0.837 | 0.1209 / 0.1143 / 0.0716 | 0.889 / 0.894 / 0.958 | 0.898 / 0.902 | 0.884 / 0.889 | 56% / 20% / 23% | 7.4→9.3 / 21.9→18.6 / 27.2→31.3 |
| 5 | 2,711 | 15.77 / 16.82 / 10.55 | **-20%** | 26.28 / 24.86 / 18.45 | **+18%** | +0.5 / +0.3 | 0.696 / 0.714 / 0.835 | 0.1317 / 0.1188 / 0.0734 | 0.874 / 0.886 / 0.956 | 0.889 / 0.895 | 0.870 / 0.880 | 56% / 20% / 23% | 7.7→9.7 / 22.9→18.5 / 29.0→32.7 |

Flip rate in this slice (k=1 membership, n=2,543): today 4.0% → new 1.8%.

### Pooled gap closed (mean over seasons)

| slice | k=1 MAE / RMSE | k=2 | k=3 | k=4 | k=5 |
|---|---|---|---|---|---|
| likely starter (stale p_start >= 0.75) | -63% / +8% | -54% / +12% | -46% / +16% | -42% / +17% | -38% / +18% |
| uncertain (0.25 <= stale p_start < 0.75) | +0% / +1% | -1% / +1% | +2% / +4% | +2% / +4% | +4% / +6% |
| written off (stale p_start < 0.25) | -115% / +21% | -86% / +22% | -66% / +25% | -53% / +26% | -47% / +27% |
| squad-relevant (top 30 by stale step-k e_points in gw) | -69% / +6% | -57% / +13% | -54% / +15% | -58% / +12% | -53% / +14% |
| position GK | -76% / -0% | -68% / +6% | -63% / +9% | -61% / +9% | -51% / +11% |
| position DEF | -49% / +10% | -44% / +14% | -37% / +17% | -33% / +19% | -29% / +20% |
| position MID | -33% / +13% | -31% / +14% | -24% / +18% | -21% / +19% | -20% / +20% |
| position FWD | -51% / +3% | -39% / +10% | -30% / +14% | -26% / +15% | -19% / +19% |

### Reading (the question was: is the MAE-vs-RMSE disagreement concentrated, or everywhere?)

**Everywhere, with one flat exception.** MAE is worse and RMSE better in every
slice, every season, every step, except the uncertain band, where both are
flat (MAE +0…+4%, RMSE +1…+6%). In particular:

- **Likely starters (stale p_start ≥ 0.75):** MAE gap −38…−63%, RMSE gap
  +8…+18%. The stale frame carries a **bias of +5.5 to +16 minutes** here —
  it predicts its own likely starters to play 5–16 minutes more than they do,
  growing with k — and 10–21% of these rows play 0 (the Gvardiol case; the
  share rises with k). The refit's bias is 0 to +1.4. Band decomposition:
  the refit is better on the 0-band (76 → 61–70) and worse on the 60+ band
  (9.8 → 14–22); 68–79% of the band plays 60+, so MAE nets negative while
  RMSE nets positive.
- **Squad-relevant (top 30):** the same shape, MAE −53…−69%, RMSE +6…+15%,
  stale bias +5 to +13.5 minutes, 9–17% of the incumbent's own top-30 rows
  play 0. AUC(start) is low-signal in both starter slices (0.60–0.68 both
  arms: start is near-certain by construction).
- **Written off (< 0.25):** the bimodality artefact in its purest form —
  MAE −47…−115% because a small positive mean replaces a near-zero one on
  the 81–88% who play 0, RMSE +18…+31%, and AUC(start) rises from
  0.74–0.85 to 0.84–0.89: the refit ranks returners far better.
- **Uncertain (0.25–0.75):** where a lagged model was supposed to earn its
  keep, lever 1 barely moves either metric; both arms sit at MAE 33–36 vs
  fresh 21–26. The gap here is information the cutoff does not have, which
  is what levers 2–4 were meant to supply.
- **Positions:** identical pattern in all four (GK RMSE ≈ flat at k=1, then
  positive). Flip rate falls in every slice.

**Answer on the criterion set for this section: the second case.** MAE gets
worse among likely starters and squad-relevant rows too, not only among the
written off. On the pre-registered MAE endpoint the refit is worse where
decisions are made, and the endpoint argument does not rescue lever 1 there.
The build stays stopped; no lever 2.

**What the slices add that the aggregate hid** (stated as facts, not as a
case for changing the endpoint): the disagreement is the same mechanism
everywhere — a calibrated mean vs a committed one on a bimodal outcome — and
in the decision-relevant slices the incumbent is not just committed but
**systematically optimistic by 5–16 minutes at lag about its own picks**,
which the refit removes. Whether the points equation should consume a
committed or a calibrated `e_minutes` at steps 1–5 is the decision the
endpoint choice encodes; it is not decided here.

### Spearman per slice (the rank endpoint the optimizer consumes; added 2026-08-24)

Spearman(e_minutes, minutes_capped) stale / new / fresh, and gap closed = (new - stale)/(fresh - stale). Aggregate rank correlation in this project has repeatedly measured "will they play" rather than "who plays more"; the slices separate the two.

**2023-24**

| slice | k=1 st/new/fr (gap) | k=2 | k=3 | k=4 | k=5 |
|---|---|---|---|---|---|
| likely starter (stale p_start >= 0.75) | 0.306/0.283/0.498 (-12%) | 0.291/0.267/0.582 (-8%) | 0.269/0.241/0.622 (-8%) | 0.268/0.229/0.643 (-10%) | 0.262/0.215/0.665 (-11%) |
| uncertain (0.25 <= stale p_start < 0.75) | 0.199/0.190/0.560 (-3%) | 0.156/0.161/0.634 (+1%) | 0.124/0.145/0.675 (+4%) | 0.130/0.118/0.688 (-2%) | 0.105/0.144/0.717 (+6%) |
| written off (stale p_start < 0.25) | 0.432/0.461/0.527 (+31%) | 0.410/0.464/0.564 (+35%) | 0.393/0.464/0.587 (+37%) | 0.383/0.472/0.609 (+39%) | 0.377/0.476/0.621 (+41%) |
| squad-relevant (top 30 by stale step-k e_points in gw) | 0.352/0.316/0.514 (-22%) | 0.331/0.326/0.601 (-2%) | 0.307/0.287/0.632 (-6%) | 0.262/0.222/0.629 (-11%) | 0.296/0.224/0.660 (-20%) |
| position GK | 0.679/0.682/0.701 (+15%) | 0.660/0.667/0.701 (+18%) | 0.643/0.648/0.701 (+10%) | 0.633/0.638/0.701 (+7%) | 0.619/0.627/0.701 (+9%) |
| position DEF | 0.713/0.717/0.787 (+6%) | 0.666/0.674/0.787 (+6%) | 0.629/0.638/0.787 (+6%) | 0.600/0.610/0.787 (+5%) | 0.574/0.590/0.789 (+7%) |
| position MID | 0.749/0.756/0.817 (+10%) | 0.706/0.719/0.818 (+11%) | 0.677/0.697/0.818 (+14%) | 0.654/0.677/0.818 (+14%) | 0.639/0.663/0.819 (+14%) |
| position FWD | 0.744/0.750/0.806 (+10%) | 0.698/0.715/0.807 (+16%) | 0.664/0.684/0.803 (+15%) | 0.644/0.670/0.804 (+16%) | 0.625/0.652/0.805 (+15%) |

**2024-25**

| slice | k=1 st/new/fr (gap) | k=2 | k=3 | k=4 | k=5 |
|---|---|---|---|---|---|
| likely starter (stale p_start >= 0.75) | 0.330/0.316/0.501 (-8%) | 0.315/0.295/0.552 (-9%) | 0.303/0.283/0.587 (-7%) | 0.289/0.265/0.616 (-8%) | 0.280/0.250/0.630 (-9%) |
| uncertain (0.25 <= stale p_start < 0.75) | 0.233/0.249/0.560 (+5%) | 0.204/0.217/0.621 (+3%) | 0.183/0.192/0.646 (+2%) | 0.181/0.180/0.659 (-0%) | 0.145/0.148/0.680 (+1%) |
| written off (stale p_start < 0.25) | 0.439/0.474/0.536 (+36%) | 0.419/0.471/0.567 (+35%) | 0.404/0.476/0.592 (+39%) | 0.388/0.482/0.610 (+42%) | 0.379/0.484/0.622 (+43%) |
| squad-relevant (top 30 by stale step-k e_points in gw) | 0.401/0.384/0.514 (-14%) | 0.381/0.368/0.557 (-7%) | 0.357/0.300/0.561 (-28%) | 0.330/0.264/0.581 (-26%) | 0.339/0.243/0.610 (-35%) |
| position GK | 0.690/0.701/0.729 (+28%) | 0.669/0.685/0.727 (+27%) | 0.649/0.672/0.730 (+29%) | 0.627/0.656/0.729 (+28%) | 0.613/0.643/0.729 (+26%) |
| position DEF | 0.723/0.731/0.792 (+12%) | 0.685/0.699/0.792 (+13%) | 0.655/0.674/0.793 (+14%) | 0.631/0.654/0.792 (+14%) | 0.616/0.637/0.792 (+12%) |
| position MID | 0.753/0.764/0.819 (+17%) | 0.720/0.731/0.819 (+11%) | 0.695/0.711/0.818 (+13%) | 0.671/0.694/0.818 (+15%) | 0.658/0.681/0.819 (+14%) |
| position FWD | 0.786/0.788/0.832 (+5%) | 0.740/0.753/0.831 (+14%) | 0.703/0.725/0.832 (+17%) | 0.676/0.707/0.834 (+19%) | 0.650/0.694/0.832 (+24%) |

**2025-26**

| slice | k=1 st/new/fr (gap) | k=2 | k=3 | k=4 | k=5 |
|---|---|---|---|---|---|
| likely starter (stale p_start >= 0.75) | 0.326/0.314/0.515 (-6%) | 0.311/0.298/0.591 (-5%) | 0.298/0.283/0.634 (-4%) | 0.295/0.278/0.658 (-5%) | 0.280/0.264/0.666 (-4%) |
| uncertain (0.25 <= stale p_start < 0.75) | 0.231/0.234/0.554 (+1%) | 0.199/0.203/0.623 (+1%) | 0.175/0.205/0.659 (+6%) | 0.132/0.189/0.677 (+10%) | 0.134/0.207/0.692 (+13%) |
| written off (stale p_start < 0.25) | 0.426/0.456/0.509 (+37%) | 0.413/0.468/0.545 (+42%) | 0.404/0.489/0.578 (+49%) | 0.384/0.492/0.591 (+53%) | 0.373/0.498/0.602 (+54%) |
| squad-relevant (top 30 by stale step-k e_points in gw) | 0.355/0.329/0.491 (-20%) | 0.357/0.333/0.566 (-11%) | 0.349/0.310/0.625 (-14%) | 0.323/0.290/0.634 (-11%) | 0.346/0.319/0.647 (-9%) |
| position GK | 0.671/0.675/0.694 (+17%) | 0.651/0.659/0.696 (+19%) | 0.637/0.647/0.694 (+17%) | 0.629/0.644/0.697 (+21%) | 0.616/0.633/0.696 (+20%) |
| position DEF | 0.728/0.734/0.793 (+9%) | 0.690/0.701/0.794 (+10%) | 0.655/0.678/0.794 (+17%) | 0.629/0.662/0.795 (+20%) | 0.613/0.652/0.792 (+22%) |
| position MID | 0.754/0.763/0.816 (+15%) | 0.716/0.732/0.816 (+16%) | 0.681/0.709/0.816 (+21%) | 0.659/0.694/0.817 (+23%) | 0.636/0.681/0.816 (+25%) |
| position FWD | 0.791/0.793/0.834 (+4%) | 0.758/0.762/0.835 (+5%) | 0.732/0.742/0.836 (+10%) | 0.713/0.726/0.837 (+10%) | 0.696/0.714/0.835 (+13%) |

**Pooled (mean over seasons): gap closed on Spearman**

| slice | k=1 | k=2 | k=3 | k=4 | k=5 | mean delta new-stale (k=1..5) |
|---|---|---|---|---|---|---|
| likely starter (stale p_start >= 0.75) | -9% | -7% | -7% | -8% | -8% | -0.023 |
| uncertain (0.25 <= stale p_start < 0.75) | +1% | +2% | +4% | +3% | +7% | +0.017 |
| written off (stale p_start < 0.25) | +34% | +37% | +41% | +45% | +46% | +0.074 |
| squad-relevant (top 30 by stale step-k e_points in gw) | -19% | -7% | -16% | -16% | -21% | -0.038 |
| position GK | +20% | +21% | +19% | +19% | +18% | +0.013 |
| position DEF | +9% | +10% | +12% | +13% | +14% | +0.016 |
| position MID | +14% | +13% | +16% | +17% | +17% | +0.020 |
| position FWD | +6% | +12% | +14% | +15% | +17% | +0.017 |

**Reading (Spearman).** The aggregate Spearman gain (+0.02 to +0.04, e.g.
2025-26 k=5 .641 → .680) is **concentrated in the written-off band**: gap
closed +34…+54%, mean Δ +0.074, in every season and step — the refit ranks
returners ("will they play") much better. Among **likely starters it is
negative** in every season and step (−4…−12%, Δ −0.023) and among
**squad-relevant rows negative** in every season and step (−2…−35%, Δ
−0.038): on the rows the optimizer actually orders, the refit ranks "who
plays more" slightly *worse* than the stale frame. The uncertain band is
flat to slightly positive (+1…+13%). The position slices are positive
(+4…+29%) only because each position mixes written-off and starting
players, so they re-measure membership, not within-set order — the
0.715 → 0.099 pattern exactly. Two further facts: within the starter and
top-30 slices BOTH arms are poor at within-set ordering (Spearman 0.22–0.40
against fresh 0.50–0.66), so that gap is almost entirely information the
cutoff lacks; and the refit's rank gain among the written-off is real but
is the one the optimizer never consumes (those players are not selected).
**Conclusion: on the rank endpoint the optimizer consumes, lever 1 is worse
where decisions are made; the aggregate Spearman gain does not reach the
optimizer.** This sharpens, rather than softens, the second-case verdict
above.

## 4. Lever 3 -- return dates from asof_news: COVERAGE CHECK (2026-08-24). Stopped at coverage; no parser built into the model.

Lever 2 (suspensions) skipped by decision: reach one fixture ahead, where the
stale gap is smallest. Lever 3 was chosen because it is the only on-disk
input that reaches k = 3..5, where the gap is +5 to +7 minutes, and because
lever 1 failed by recombining features the cutoff already had -- this one
would bring information the cutoff lacks.

### Method (stated before the count)

`eval/scope_horizon_returns_coverage.py`, read-only. From `asof_news` ONLY
(the as-of discipline), three categories per flagged row (status i/d/s/n):
an explicit date ("Expected back 14 Sep", "Suspended until 23 Aug"; year
inferred from the deadline, +-6-month rule), "unknown return date" as its
own category, or no return language. A date maps to the first gameweek
whose DEADLINE falls on/after date-1 day: the deadline calendar is fixed at
season start, so this mapping needs no final fixture calendar and carries
no lever-4-style caveat. A "flip row" is a (cutoff c, gw c+k, element)
where the player is flagged at c with a parsed return gameweek j <= c+k:
the stale frame believes absent, the feature would say expected back.
No realised minutes were read anywhere in the check.

D7 guarantee, as designed (not built): the feature vector at (c, k) is a
function of asof_news at c and the deadline calendar only. Whether the club
date proved right never enters as a feature, a filter, a weight or a
selection rule; the outcome at c+k is used solely as the training LABEL,
exactly as for every other feature. Learning how reliable club forecasts
are from prior-season labels is legitimate; using a row's own outcome to
qualify its date is the injury-API-with-end-dates leak, and is excluded.

### Numbers

| season | flagged rows | explicit date | unknown return | no return language | dated rows returning within 1 / 2 / 3 / 4 / 5 gws | beyond 5 |
|---|---|---|---|---|---|---|
| 2023-24 | 4,465 (15.1%) | 1,731 (39%) | 1,421 (32%) | 1,313 (29%) | 335 / 307 / 175 / 109 / 69 | 644 |
| 2024-25 | 3,648 (13.3%) | 1,509 (41%) | 1,029 (28%) | 1,110 (30%) | 335 / 253 / 145 / 79 / 63 | 575 |
| 2025-26 | 3,601 (12.1%) | 1,162 (32%) | 1,357 (38%) | 1,082 (30%) | 279 / 209 / 123 / 72 / 52 | 357 |

Flip rows at k >= 3, pooled over three seasons (per-season tables in the
script output):

| k | flip rows / all rows | in the incumbent's top 30 / relevant rows | flip rows for top-30-calibre players (own-cutoff top 30 in any of the prior 5 gws; knowable) | would be in the fresh top 30 (descriptive) | unknown-return rows |
|---|---|---|---|---|---|
| 3 | 2,229 / 79,063 (2.82%) | **0 / 3,150 (0.00%)** | 208 | 45 | 3,627 |
| 4 | 2,418 / 76,961 (3.14%) | **0 / 3,060 (0.00%)** | 229 | 57 | 3,564 |
| 5 | 2,526 / 74,842 (3.38%) | **0 / 2,970 (0.00%)** | 228 | 71 | 3,493 |

### What the numbers say

1. **The feature never touches the incumbent's top 30 -- by construction.**
   A player the feature acts on is flagged at the cutoff, so his stale
   e_points is near zero and he is never in the stale top 30; likewise his
   stale p_start is < 0.25, so he is in the written-off band. Every flip row
   sits in the one slice the pass condition excludes.
2. **The footprint is small even on the knowable calibre definition:** about
   70 flip rows per season per step at k >= 3 for top-30-calibre players,
   ~7% of a ~1,000-row relevant slice; and only 15-33 per season-step would
   enter the fresh top 30 at the target gameweek.
3. **"Unknown return date" rows (3.5k pooled per step) all confirm an absence
   the stale frame already assumes** -- near-zero delta by construction.

### Decision: stop at coverage. Lever 3 fails the pre-registered test before
### it is built.

The pass condition requires Spearman to improve among likely starters (stale
p_start >= 0.75) AND squad-relevant rows (incumbent's top 30) at k >= 3. On
those partitions this feature has exactly zero rows to act on. Its entire
effect would land in the written-off band, which the pass condition names as
a fail however large. Building the parser cannot change that arithmetic.

### The structural finding (recorded for the instrument, not decided here)

A sliced test whose decision-relevant partitions are defined by the STALE
view cannot register any feature whose action is to revive a written-off
player -- the return-date feature is the canonical case, and it is the mirror
image of the Gvardiol failure (predicted 85, played 0) that motivated slicing
on prediction rather than outcome. The stale partition was the right fix for
lever 1, whose claimed gain was membership; it is blind by construction to a
lever whose entire contribution IS membership at k >= 3. A partition that
would see it without conditioning on the outcome exists and is knowable at
the cutoff -- top-30-calibre: in the own-cutoff top 30 in any of the 5
gameweeks before the cutoff -- but adopting it after seeing this result is an
amendment to the pre-registration and is the user's call. On that partition
the footprint is ~7% of the slice, which is the number to weigh.

Horizon work is parked here with a clean negative: lever 1 worse where
decisions are made on both MAE and rank; lever 3 unable to reach the
decision-relevant population as the test defines it. The stale gap at
k >= 3 (+5 to +7 minutes) remains measured and unclosed.
