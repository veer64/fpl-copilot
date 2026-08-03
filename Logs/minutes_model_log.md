# Minutes Model — Build Log

**Phase 2, Week 5.** Status: all components built, composed, calibrated, and
cold-start handled.

Validation season is 2024-25 throughout. **2025-26 (test) has not been touched.**

---

## 1. What the minutes model is and why it exists

FPL points decompose into structurally different processes (master plan §3.0).
Minutes gate all of them: a player who scores 6 points per appearance but starts
half the time is a 3-point player, not a 6-point player. Phase 1's
`predict_naive.py` ignored this entirely — points-per-game with no minutes-risk
adjustment — which is the single most common failure of naive FPL models.

The model is decomposed rather than a single blob prediction, because "how many
minutes will this player get" is really several different questions with
different populations:

| Component | Question | Type |
|---|---|---|
| P(start) | Will they be in the XI? | classifier |
| P(60+ \| started) | If they start, do they reach the 60-min threshold? | classifier |
| P(came on \| didn't start) | If benched, do they appear at all? | classifier |
| E[min \| started] | If they start, how long? | regressor |
| E[min \| sub] | If they come on, how long? | regressor |

The 60-minute threshold matters because it gates 1 extra appearance point **and**
all clean-sheet points (4 for GK/DEF, 1 for MID).

**Note on P(60+ | started):** it is built but not yet consumed. It does not appear
in the E[minutes] composition (§6.1) — it is needed downstream by the expected-
*points* model, for clean-sheet points (`P(CS) × CS_pts × P(≥60)`) and the
1-vs-2 appearance-point split.

---

## 2. Data preparation

### 2.1 Source and label availability

Working file: `data/history/all_seasons_fixed.parquet` (vaastav) — 253,900 rows
× 74 columns, one row per player-gameweek-season, 10 seasons (2016-17 → 2025-26).

`starts` is the label. It only exists from 2022-23 onward, which caps usable
data at 4 seasons:

```
2016-17 .. 2021-22        0 rows with starts
2022-23              18,014
2023-24              29,725
2024-25              27,605
2025-26              29,757
                    -------
                    105,101 rows with a trustworthy label
```

Only vaastav was used. The other sources were considered and rejected for this
model: Understat is attacking output (irrelevant to starting), Core-Insights is
2025-26 only (our test season, so untrainable), odds are team-level.

### 2.2 Bug #4 — `starts` broken for 2022-23 GW1–15

Found by cross-checking `starts` against `minutes`: 2,005 rows had `starts=0`
with `minutes>=90`. A full 90 is impossible without starting (FPL caps minutes
at 90; a substitute cannot accumulate 90). All 2,005 were exactly 90, all in
2022-23, all in GW1–15. GW7 was absent — the round postponed after the Queen's
death, so no matches, which corroborated that this was real data and not
corruption.

An 11-slot budget check (count confirmed starters per team-gameweek) found **no**
team-GW reaching 11 confirmed starters in that window — most sat at 5–6. Since
every team fields exactly 11, this proved the bug was far wider than the 2,005
unambiguous cases: starters subbed off before 90 were also mislabelled.

Breakdown of `starts=0` rows in the window:

| minutes | count | interpretation |
|---|---|---|
| 90 | 2,005 | certain real starts |
| 60–89 | 813 | ambiguous — subbed-off starter vs early-injury sub |
| 1–59 | 1,218 | mostly genuine subs |
| 0 | 4,455 | genuine non-players, correctly labelled |

**Decision:** set `starts = NaN` for all 8,491 rows in 2022-23 GW1–15.
Reconstructing per-player is guesswork — minutes alone cannot distinguish a
subbed-off starter from an early substitute. Every row's `minutes` and
`total_points` were kept; only the untrustworthy label was nulled.

### 2.3 Player identity — the Ben Davies collision

Grouping by `name` merged two different real players: 2022-23 contained two
"Ben Davies" (elements 432 and 499). Their rolling-history features would have
been blended into one fictional player.

**Fix:** group by `(season, element)`. `element` is unique within a season (it
only resets *across* seasons), so the pair is a guaranteed-unique player-season
key. All feature engineering uses this key.

**Standing lesson: verify by `element`, not `name`.** Several later inspections
looked jumbled purely because they filtered on name.

### 2.4 Double gameweeks

3,324 player-GW combinations had exactly 2 rows (never 3+) — double gameweeks,
where a player has two fixtures in one GW. This broke the one-row-per-player-GW
grain that `shift(1)` ("last gameweek") depends on.

**Options considered:** collapse to one row; keep per-match grain; collapse plus
a flag; drop the rows entirely.

**Decision — collapse and flag.** One row per player-GW: `minutes` and
`total_points` summed, `starts` = "started at least one match" (max of {0,1}),
plus a new `is_double_gw` flag so the information that it *was* a double is not
lost. Dropping was rejected outright — deleting real data to avoid handling it
is the wrong instinct. Per-match grain was rejected because every downstream
component (and eventually the optimizer) assumes one row per player-GW.

105,101 → 101,777 rows.

**Consequence — `minutes_capped`.** Summed double-GW minutes (135, 180) broke
minutes *averages*, which showed a max of 180 — impossible for a per-match
average. A `minutes_capped = minutes.clip(upper=90)` column was introduced for
all minutes-form features. The true summed `minutes` column is untouched.

### 2.5 Bug #5 — Assistant Manager rows

Two independent smells during Wave 2, same root cause: `position_code` had 5
categories when FPL has 4, and `value` had a minimum of 5 (= £0.5m, below FPL's
£3.5m floor). Both traced to 312 rows with position `AM` — Assistant Managers,
introduced with the AM chip in 2024-25. Managers are not players: all 312 have
`minutes=0`, `starts=0`, and a nonsense ~£1.5m price.

**Fix:** filter `position != "AM"`. This should stay permanently in the pipeline,
not be treated as a 2024-25 patch — the chip may persist or return.

101,777 → 101,465 rows.

### 2.6 Final table

After dropping rows with no prior history: **98,489 rows**, start rate **0.292**.
(Those dropped rows were later recovered — see §6.7.)

---

## 3. Features

Every feature is an as-of function: computed only from gameweeks strictly before
the current one. The universal pattern is **shift-then-roll inside the group**:

```python
grp[col].transform(lambda s: s.shift(1).rolling(window).agg(how))
```

`shift(1)` is the leakage guard — it guarantees a GW20 feature stops at GW19.
`groupby(["season", "element"])` prevents history bleeding across season
boundaries or between players. `transform` keeps row alignment automatically
(manual index handling caused a real `IndexError` and was abandoned).

### Wave 1 — recent starts and minutes

| feature | definition |
|---|---|
| `started_last_gw` | did they start the previous GW (0/1) |
| `starts_last3` | count of starts in prior 3 GWs (0–3) |
| `starts_last5` | count of starts in prior 5 GWs (0–5) |
| `avg_min_last3` | mean `minutes_capped` over prior 3 GWs |
| `avg_min_last5` | mean `minutes_capped` over prior 5 GWs |
| `is_double_gw` | flag from §2.4 |

### Wave 2 — injury proxies and role

Vaastav has **no** injury or availability column (`chance_of_playing` lives in
the live FPL bootstrap, which is a current-value field nobody snapshots
retroactively). Rather than chase unavailable data, injuries were inferred from
the footprint they leave in minutes.

| feature | definition | what it catches |
|---|---|---|
| `consec_zero_mins` | run of consecutive 0-minute GWs immediately prior; resets on any appearance | currently absent |
| `gws_since_last_start` | GWs since their most recent start | out of the XI, but may still be playing as a sub |
| `minutes_trend_N` | mean minutes over prior N GWs − mean over prior 8 | abnormal *relative to their own baseline* |
| `position_code` | GK/DEF/MID/FWD as 0–3 | rotation patterns differ by position |
| `value` | FPL price in tenths of £M | nailedness prior |

The three proxies are complementary: #1 asks *are they absent*, #2 asks *are they
out of the XI*, #3 asks *is this abnormal for this specific player*. A benchwarmer
playing 0 minutes is normal (trend ≈ 0); a regular starter playing 0 is an
emergency (trend ≈ −70). Only #3 captures that.

**Trend window — tested, not assumed.** The 2-GW window was an arbitrary initial
choice. Both were built and compared on validation:

| variant | Brier (P(start)) |
|---|---|
| `minutes_trend_2` | 0.0880 |
| `minutes_trend_3` | **0.0877** |

`minutes_trend_3` selected.

---

## 4. Splits

**Walk-forward by season — never shuffled.** Shuffling time-ordered data lets the
model train on GW20 to predict GW10, which is impossible in production and
produces a fake-good score.

| split | seasons | rows | start rate |
|---|---|---|---|
| Train | 2022-23, 2023-24 | 43,565 | 0.292 |
| Validation | 2024-25 | 26,427 | 0.304 |
| **Test** | **2025-26** | **28,497** | **0.282 — UNTOUCHED** |

(Wave 2 features reduce these slightly — 41,929 / 25,354 — since the trend
features need ≥2 prior GWs.)

Start rates are similar across splits, so no split is skewed.

---

## 5. The components

### 5.1 P(start)

**Model progression:**

| model | features | Brier | 0.1–0.2 gap | 0.2–0.3 gap | 0.3–0.4 gap |
|---|---|---|---|---|---|
| baseline (flat 0.29) | — | 0.2118 | — | — | — |
| Logistic regression | 6 | 0.0894 | +0.115 | +0.114 | +0.126 |
| LightGBM | 6 | 0.0882 | +0.023 | +0.022 | +0.065 |
| LightGBM | 11 | **0.0877** | **+0.014** | **+0.032** | **+0.029** |

**Key finding — the headline metric hid what mattered.** LightGBM improved Brier
over logistic regression by only 1.3% (0.0894 → 0.0882), which read as "adds
nothing." But the underconfidence in the 0.1–0.4 band — the rotation-risk zone
where FPL decisions actually get made — collapsed from ~12 points to ~2. The
Brier is dominated by ~13,000 easy bench rows, so the decision-relevant slice
barely moves the average. This is master plan §4.3 in practice: **choose metrics
for the decision, not the leaderboard.**

Final calibration (11 features) is within ±0.032 in every bin.

**Feature importance:**

```
minutes_trend_3       1924
avg_min_last5         1649
value                 1627
avg_min_last3         1574
gws_since_last_start   551
position_code          550
consec_zero_mins       521
is_double_gw           238
starts_last3           172
starts_last5            99
started_last_gw         95
```

`minutes_trend_3` — the injury proxy whose window we nearly picked arbitrarily —
is the single most-used feature.

**Ablation — the start-history features are redundant.** `started_last_gw` ranks
*last* despite looking strongest in raw EDA (80% of starters started last week vs
8% of non-starters). Cause: `avg_min_last3/5` encode the same information
continuously and more richly — a player averaging 70 minutes obviously started.
The trees prefer the continuous form.

| feature set | Brier | mid-band gap |
|---|---|---|
| All 11 | 0.0877 | +0.015 |
| Without start-history (8) | 0.0881 | +0.011 |

Difference is within noise and the two metrics disagree on direction.
**Decision: keep all 11** — cost is near-zero and the ablation itself is a useful
artifact.

XGBoost was also tested and did not beat LightGBM.

### 5.2 P(60+ | started)

Trained only on rows where `starts == 1` — asking "will they reach 60 minutes" is
meaningless for someone who never got on the pitch.

29,722 starter rows, base rate **0.932** (27,708 yes / 2,014 no). Train 11,854,
val 7,575. Only ~2,000 negative examples exist in total, making this a
rare-event problem.

| config | Brier | prediction spread |
|---|---|---|
| baseline (flat 0.93) | 0.0626 | — |
| original (300 trees, 31 leaves) | 0.0638 | 0.160–1.000 |
| **constrained** (100 trees, 7 leaves, min_child 100, λ=1) | **0.0607** | 0.580–0.991 |
| constrained + class weighting | 0.2061 | 0.169–0.938 |

**The original model lost to the flat base rate.** The 1.000 predictions were the
tell — overfitting on a rare-event problem. Constraining fixed it and produced a
genuine (if modest) win.

**Class weighting was a disaster — 3× worse than baseline.** `scale_pos_weight`
deliberately distorts probabilities to make the model attend to the minority
class; it pushed all predictions far below the true 93% base rate and wrecked
calibration. **Lesson: class weighting optimises for detecting the minority class
at the direct expense of honest probabilities. When calibration is the goal, it
is the wrong tool.**

Calibration is good where the data is dense (0.90–0.95 bin: gap −0.004 on 2,838
rows; 0.95–1.00: +0.002 on 3,308 rows). The sparse low bins (23 and 89 rows) show
larger gaps, but at 23 rows a single player swings the gap by ~0.04 — that is
sampling noise, not a calibration flaw, and was deliberately not chased.

### 5.3 P(came on | didn't start)

**Not in the original 3-stage framing** — it was discovered as a gap when
assembling the composition formula, which needs it to weight the substitute path.

71,743 non-starter rows, base rate **0.152** (60,812 / 10,931). Train 29,700,
val 17,553.

| model | Brier | mid-band (0.3–0.7) gap |
|---|---|---|
| baseline (flat 0.15) | 0.1400 | — |
| **current** (200 trees, 15 leaves) | **0.0899** | +0.039 |
| constrained | 0.0907 | +0.041 |
| looser (400 trees, 31 leaves) | 0.0925 | +0.019 |

**Best relative improvement of any component — 36% over baseline.** Prediction
spread 0.001–0.845, so the model confidently separates structural
non-appearances from likely substitutes.

This was the hardest population to model in principle, because the 60,812 zeros
are a *mixed* group: genuine unused bench players, injured players not in the
squad, fringe squad members, and youth registrations. Only the first has any real
appearance chance. The features apparently do separate them.

**Feature importance:**

```
value                  578   <- top feature
minutes_trend_3        522
avg_min_last5          375
consec_zero_mins       332
avg_min_last3          326
position_code          253
gws_since_last_start   239
starts_last5            72
is_double_gw            54
starts_last3            49
started_last_gw          0   <- entirely unused
```

Price is the strongest signal for identifying which benched players actually get
minutes. `started_last_gw` scores exactly 0 — within a bench-only population
almost nobody started last week, so it is constant and carries no information.

The residual +0.03 to +0.05 underconfidence across 0.3–0.7 was subsequently fixed
by isotonic calibration — see §6.6.

### 5.4 E[min | started]

**Feature-set change forced by composition.** The first version used
starter-only features (`past60_rate_3/5`, `last_start_minutes`) and scored RMSE
11.88 / MAE 8.01. But those features are undefined for players who never started
— 19,139 of 26,919 validation rows (71%) were missing them.

This exposed a design tension: `E[min | started]` is a **hypothetical** — "*if*
this player were to start, how long would he play?" — and the composition needs
that answer even for players who probably won't start.

**Decision: retrain on universally-available features only.**

| version | RMSE | MAE | defined for |
|---|---|---|---|
| with starter-only features | 11.88 | 8.01 | starters only |
| **without (selected)** | **11.99** | **8.16** | **everyone** |

Less than 1% accuracy cost for a model defined everywhere, plus more training
rows (12,229 vs 11,854, since first-starts are no longer dropped). Simplicity
won; a model defined everywhere prevents a whole class of production bugs.

**Algorithm comparison — six families, one conclusion:**

| model | RMSE | MAE |
|---|---|---|
| **LightGBM** | **11.88** | 8.01 |
| MLP (256,128) | 11.96 | 8.07 |
| MLP (64,32) | 11.98 | 7.98 |
| MLP (128,64,32) | 12.02 | 8.17 |
| Linear | 12.02 | 8.38 |
| Ridge | 12.02 | 8.38 |
| SVR (rbf) | 12.45 | **7.32** |
| baseline (predict the mean) | 12.75 | 9.40 |

**Everything clusters within 0.6 RMSE.** Bigger neural networks did not help —
the wide MLP took 10 seconds to arrive at the same answer as everything else.
When six very different algorithm families converge this tightly, the ceiling is
**feature information, not algorithm choice.** Further model tuning is not the
lever; better features are (fixture congestion, match state, age, minutes load).

**Quantile regression** was also tested (LightGBM `objective="quantile"`, α =
0.1/0.5/0.9). The q50 model scored RMSE 14.59 / MAE 7.13 — better MAE, worse
RMSE, exactly mirroring SVR. Coverage of the [p10, p90] interval was **90.1%**
when it should be 80%, with mean width 19.8 minutes: the intervals are too wide,
i.e. the uncertainty estimate is over-cautious and not yet honest.

### 5.5 E[min | sub]

10,931 rows where a non-starter appeared. Distribution is tight and short:
mean 18.4, median 16, IQR 7–26, max 90 (likely early-injury replacements).
Train 4,290, val 2,941 — the smallest dataset of any component.

| config | RMSE | MAE |
|---|---|---|
| baseline (flat 18.4) | 14.05 | 11.15 |
| current (200 trees, 15 leaves) | 13.87 | 10.82 |
| **constrained** (100 trees, 7 leaves) | **13.68** | **10.67** |
| very tight (60 trees, 5 leaves, λ=5) | 13.68 | 10.69 |

Constraining helped, confirming overfitting on 4,290 rows. That "constrained" and
"very tight" land on *identical* RMSE is a clean signature of a weak-signal
problem — past a point, extra constraint changes nothing because the model has
already been reduced to the small amount of genuine signal available.

**2.6% better than baseline.** Kept because it is free, but sub minutes are
largely unpredictable from player history — *when* a manager makes a substitution
depends on match state, not on the player.

---

## 6. Composition, calibration, and cold start

### 6.1 The formula

Every player-gameweek falls into exactly one of three mutually exclusive,
exhaustive situations: started / didn't start but came on / didn't play. Applying
the **law of total expectation** over that partition:

```
E[min] = P(start)·E[min|start] + P(sub)·E[min|sub] + P(no play)·E[min|no play]
```

The third term vanishes because `E[min | no play] = 0`. Expanding `P(sub)` via
the chain rule — to be a substitute you must clear two hurdles, not starting
*and then* being called on:

**E[min] = p · E[min|start] + (1 − p) · q · E[min|sub]**

where `p` = P(start) and `q` = P(came on | didn't start).

```python
v["e_minutes"] = (
    v["p_start"] * v["min_start"]
    + (1 - v["p_start"]) * v["p_sub"] * v["min_sub"]
)
```

Worked example — rotation-risk midfielder with p = 0.6, q = 0.5,
min_start = 80, min_sub = 20:

```
E[min] = 0.6 × 80  +  0.4 × 0.5 × 20  =  48 + 4  =  52
```

48 minutes come from the starting path, only 4 from the bench path. **The
starting path dominates**, which is why P(start) is by far the most important
component.

### 6.2 Output

25,354 of 26,919 validation rows scored.

```
mean   27.28      (actual mean: 27.56)
min     0.06
25%     0.65
50%    10.61
75%    57.01
max    87.91
```

No impossible values. The low median reflects the U-shaped population found in
early EDA: most player-gameweeks are fringe players, with a second cluster of
nailed starters and a sparse middle.

### 6.3 End-to-end evaluation

| | RMSE | MAE |
|---|---|---|
| **Composed model** | **22.97** | 13.88 |
| baseline: `avg_min_last3` | 24.63 | **12.66** |
| baseline: flat mean | 38.19 | 35.17 |

The composed model wins RMSE by 7% but **loses MAE** to a single rolling-mean
column — and loses it in nearly every slice (by predicted-minutes band, by
position, by price tier). Only the 15–30 minute band showed a win (+0.65).

### 6.4 Why MAE is the wrong metric here — the central finding

This is the most important methodological result of the week.

Diagnostic on nailed starters (`p_start > 0.85`, n = 3,600):

```
average p_start    0.913
average min_start  86.16     (predicted minutes IF they start)
average e_minutes  79.40     (after probability weighting)
average ACTUAL     79.73     <- essentially unbiased

MAE, composed        15.54
MAE, min_start only  11.62
MAE, avg_min_last3   10.94   <- naive baseline "wins"
```

The composed prediction is **almost perfectly unbiased** (79.40 vs 79.73), yet
its MAE is worse. The reason is what an expectation *is*.

For a player with p = 0.9 and min_start = 88, we predict 79. Reality is bimodal:
~90% of the time he plays ~88 (we're off by 9), ~10% of the time he plays 0
(we're off by 79). Our prediction is **never exactly right** — it is the
probability-weighted average of two outcomes that genuinely occur.

The naive baseline predicts ~88 and is nearly exact 90% of the time, badly wrong
10% of the time. Lower MAE, worse estimate of the expectation.

**The principle: the mean minimises squared error; the median minimises absolute
error.** Judging an expectation by MAE structurally penalises correct
probabilistic reasoning and rewards a model that predicts the modal outcome.

Corroborating evidence from this same build:

- SVR won MAE (7.32) and lost RMSE (12.45) — §5.4
- Quantile-median regression won MAE (7.13) and lost RMSE (14.59) — §5.4
- Composed model unbiased at every level checked — overall 27.28 vs 27.56, nailed
  starters 79.40 vs 79.73

**Decision: RMSE is the primary metric for all E[minutes] components. MAE is
reported as secondary context only.** Downstream, E[minutes] feeds an
expected-*points* calculation, where the probability-weighted value is exactly
what is required — a modal prediction would systematically overvalue
rotation-risk players.

### 6.5 Two-player walkthrough

**Mohamed Salah, 2024-25** — the nailed starter. `p_start` sits at 0.88–0.97 and
`e_minutes` lands at 78–85 against actual 90s. The shrinkage below 90 correctly
accounts for the ~10% chance he doesn't start. GW7 is the payoff: he played only
72, and the 84.50 prediction was closer than "he always plays 90" would have
been. The substitute path is negligible for him — (1−0.92) × 0.37 × 22 ≈ 0.7
minutes. All value comes from term 1.

**Curtis Jones, 2024-25** — the rotation player, and the more instructive case.
`p_start` climbs across the season as he breaks into the team:

```
GW    3     4     5     6     7     8     9    10    11    12
p   0.01  0.01  0.15  0.28  0.33  0.60  0.76  0.89  0.61  0.60
```

The model learns his changing role in real time — the injury proxies and rolling
features doing exactly what they were built for. At GW5–6, `p_sub` is 0.53–0.71
and `e_minutes` of 17–31 genuinely blends both routes. This is the murky middle
where the decomposition earns its place: a single rolling mean cannot express
"probably benched, but likely to come on."

GW10 is the honest failure — predicted 74.14, actual 24. That is the irreducible
part: team-news information we do not have.

### 6.6 Calibration — isotonic on the substitute model

The P(came on | didn't start) model had a consistent +0.03 to +0.05
underconfidence across the 0.3–0.7 band (§5.3). Isotonic regression was fitted
as a post-hoc correction layer.

**Fitting protocol.** The correction must be learned on data the base model did
not train on, or it memorises noise. Validation (2024-25) was split by
gameweek — calibrator fitted on GW≤19 (7,619 rows), measured on GW>19
(9,934 rows). Splitting by gameweek rather than randomly preserves the
walk-forward time discipline.

| | Brier | mid-band gap (0.3–0.7) |
|---|---|---|
| raw | 0.0864 | +0.037 |
| **calibrated** | 0.0870 | **−0.009** |

The systematic underconfidence is essentially eliminated — a 4× improvement in
the targeted band — at a Brier cost of 0.0006. Compare the earlier capacity
experiment (§5.3), where a looser model achieved a similar gap fix but cost
0.0026 of Brier: isotonic gets the same correction for a quarter of the price.

Isotonic is monotonic, so it adjusts the probability *values* without disturbing
the model's ranking.

**P(start) was deliberately NOT calibrated.** Its worst bin is +0.032 with most
within ±0.02 — scattered small deviations rather than a systematic bias. Fitting
a correction with nothing to correct would burn half of validation and risk
introducing noise (the calibrator slightly worsened Brier even where it helped
the gap). **Principle: calibrate when a systematic bias has been diagnosed, not
as a routine step.**

### 6.7 Cold start — solved

Previously ~3,288 rows (~3%) with no prior-gameweek history were dropped,
meaning **no prediction at all** for GW1 players and new arrivals — precisely
when the live model is most in demand.

#### Composition of the problem

Of 784 no-history rows in validation:
- **616 are GW1** — this is overwhelmingly a season-opener problem, not a
  transfer problem
- **490 (63%) played the previous season** — history we were discarding
- 294 are genuinely new to the league

#### Fix 1 — keep the rows, fill defaults, add a flag

Start/minutes history filled with 0, plus a `has_no_history` flag so the model
can distinguish "genuinely played 0 minutes" from "we have no information."
`position_code`, `value` and `is_double_gw` are never missing — they come from
the roster (bootstrap-static), which is exactly what IS available for new players.

Result on no-history rows: Brier **0.1676**, predicted mean 0.312 vs actual start
rate 0.298 — weak but **essentially unbiased**. Honest base-rate-level
predictions beat no answer.

#### Fix 2 — prior-season fallback

Per player-season aggregates (`prev_start_rate`, `prev_avg_minutes`,
`prev_games`) computed from season N and attached to season N+1 as a prior.
Matched on `name`, which is stable across seasons — unlike `element`, which
resets.

Because the match is on name and not team, **intra-PL transfers are covered for
free**: a player moving from Brighton to Arsenal still carries his prior stats.
A `transfer_status` flag distinguishes the cases (0 = same club, 1 = moved within
the PL, 2 = no prior season) so the model can learn how far to trust the prior in
each.

| feature set | all val rows | no-history rows |
|---|---|---|
| without prior-season | 0.0893 | 0.1676 |
| **with prior-season** | **0.0890** | **0.1471** |

**12% improvement on the targeted group.** At GW1 the model now knows Salah
started every game last season rather than treating him as a blank slate.

Note 0.1471 remains far worse than the 0.0877 achieved on players with
current-season history. Prior-season data is a useful prior, **not a substitute
for knowing what is happening now** — roles change over a summer.

#### Known limitations
- **94 player-seasons have >1 team** (mid-season transfers, or name collisions).
  `prev_team` takes an arbitrary one, so `transfer_status` is unreliable for
  these. Small (94 of ~2,400) but a known-wrong corner.
- **Promoted-club players look "genuinely new"** even when they are established
  Championship starters. Unfixable without non-PL data. Accepted risk — the FPL
  crowd rarely picks newly-promoted players in volume.

### 6.8 Negative result — form/role features do not help

Prompted by the Curtis Jones incoherence: his `p_sub` stayed flat at ~0.65 while
`p_start` climbed 0.01 → 0.89. An established starter should have a *low*
probability of being a bench appearance. The hypothesis was that the sub model
sees recent *playing time* but not recent *role*.

Two features were built to capture role direction:
- `start_rate_trend` — start rate over prior 3 GWs minus prior 8 GWs
- `minutes_share_5` — mean minutes over prior 5 GWs as a fraction of 90

| feature set | Brier | mid-band gap |
|---|---|---|
| without form | 0.0899 | +0.039 |
| with form | 0.0900 | +0.038 |

**No effect.** Both differences are noise.

Likely cause is the same redundancy found with the start-history features in
§5.1: `avg_min_last3/5` and `minutes_trend_3` already encode most of the role
information. Our features keep converging on the same underlying signal.

This strengthens the §5.4 conclusion. **We are feature-information-limited, and
the limit is not about cleverer recombinations of minutes history.** Six
algorithm families could not beat it; two rounds of minutes-derived features
could not either. What would help is genuinely NEW information: injury flags,
fixture congestion, match state, depth charts.

The Curtis Jones incoherence remains real — these features simply do not fix it.
The proper fix is likely the depth-chart work (§7.3), which is new information
rather than another rearrangement of the same minutes data.

---

## 7. Open items

### 7.1 Quantile interval width

The [p10, p90] interval covers 90.1% of outcomes when it should cover 80% —
too wide, so uncertainty is currently over-stated. Needs narrowing before the
distributional output is trustworthy for the optimizer.

### 7.2 Cold-start residuals

Resolved in the main (§6.7), but two corners remain:
- The 94 multi-team player-seasons where `transfer_status` is unreliable.
- Promoted-club players who appear as genuinely new despite being established
  starters at Championship level.

### 7.3 Feature idea — depth chart / backup promotion

A player's P(start) depends on the availability of whoever is ahead of them, not
just their own history. Kelleher averages ~0 minutes so every current feature
says "won't start" — but if Alisson is flagged injured pre-deadline, Kelleher is
nailed on. Wave 1/2 features are player-in-isolation and structurally blind to
this.

Requires a depth chart (who is the established starter per team per position) and
a pre-deadline availability flag. GK is the clean first case — usually an obvious
#1 and #2. Hardest part is defining "the starter ahead of them" reliably from
data.

Given §6.8, this is now the **highest-value remaining feature idea**: it is
genuinely new information rather than another transformation of minutes history.

### 7.4 Real injury data

Vaastav has no availability column, so all injury signal is proxied from minutes
patterns. The real `chance_of_playing` field arrives naturally once the live
system starts daily bootstrap snapshots in August (master plan §2.3). At that
point the proxies should be re-evaluated against the genuine flag.

Note the current ingestion is static, not dynamic — the new season's roster will
be picked up when the FPL game opens (late July), which per master plan §0.1 is
also the first schema-drift test.

### 7.5 Wire into production

All work so far lives in standalone notebook cells. Nothing is wired into the
live FastAPI app, which still serves Phase 1's `predict_naive.py`. Model
persistence, a shared feature module (to avoid train/serve skew), and the
predictions mart are all outstanding.

---

## 8. Summary table

| component | model | metric | vs baseline |
|---|---|---|---|
| P(start) | LightGBM, 11 features | Brier 0.0877 | 0.2118 |
| P(start) incl. cold start | + `has_no_history` + prior-season | Brier 0.0890 (all rows) | — |
| P(60+ \| started) | LightGBM constrained | Brier 0.0607 | 0.0626 |
| P(came on \| benched) | LightGBM + isotonic | Brier 0.0870, gap −0.009 | 0.1400 |
| E[min \| started] | LightGBM (universal features) | RMSE 11.99 | 12.75 |
| E[min \| sub] | LightGBM constrained | RMSE 13.68 | 14.05 |
| **composed E[min]** | law of total expectation | **RMSE 22.97** | 24.63 |

The two P(start) rows are not directly comparable: 0.0877 is scored on the
reduced set that excluded no-history players; 0.0890 includes the 784 hard rows
that were previously unanswerable.

Bugs found and fixed this week: **#4** (`starts` broken 2022-23 GW1–15),
**#5** (Assistant Manager rows). Both documented in `KNOWN_ISSUES.md`.

**2025-26 test season remains untouched.**