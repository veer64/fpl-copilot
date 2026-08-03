# Defensive Contribution Model — Build Log

**Phase 2, Week 5–6.** Status: defender model built (within-season walk-forward);
two significant data findings; midfielder/forward models still to build.

The 2025/26 scoring rule awards **2 points** for hitting a per-match defensive
threshold: **CBIT ≥ 10** for defenders (Clearances + Blocks + Interceptions +
Tackles), **CBIRT ≥ 12** for mids/forwards (CBIT + Recoveries). This is the
model for **P(hit threshold)** per player-match.

**Data:** `core_insights_matchstats.parquet`, PL-only (`-prem-` match_ids).
**2025-26 is the season with the correct rule and recording — it is the primary
(and, per the findings below, the *only usable*) data for this target.**

---

## 1. The target — a hard, rare per-match event

CBIT/CBIRT are computed from raw components (the file's own
`defensive_contributions` column is **all-zero / unpopulated — do not use it**):

```python
cbit  = clearances + blocks + interceptions + tackles
cbirt = cbit + recoveries
dc_hit = (cbit >= 10) if Defender else (cbirt >= 12)
```

**Base rates (2025-26, players who appeared):** DEF 12.5%, MID 13.6%, FWD 5.8%,
GK 23%. The thresholds are deliberately hard — a *typical* player-match produces
~7–8 defensive actions, below the bar. Players clear it only on their busier
games. But the distribution is bimodal: defensive specialists (Senesi 59%,
Lacroix 57%, Tarkowski 54%, Van Dijk 43%) hit it routinely; attackers/subs almost
never. The model's job is to separate those two groups — the same shape as the
P(60+) problem in the minutes model.

**Validation of the computed metric:** the highest-average-CBIT players are exactly
the recognizable high-volume centre-backs (Senesi, Lacroix, Tarkowski, Van Dijk,
Andersen) — confirming the metric captures real defensive workload.

---

## 2. Finding #1 — persistence is WITHIN-season, not cross-season

Testing whether a player's defensive rate repeats:

| metric | cross-season (24-25→25-26) | within-season (H1→H2) |
|---|---|---|
| DEF cbit | 0.109 | **0.443** |
| MID cbirt | −0.054 | **0.483** |
| FWD cbit | 0.258 | **0.570** |

Cross-season persistence is near-zero; within-season is 4–5× higher. **Defensive
output is stable within a settled team context but does not survive the summer** —
because it is heavily driven by team tactics/manager/personnel, which change. This
is the opposite of the attacking stats (npxG/xA), where cross-season priors work
because attacking skill is individual and stable.

**Design consequence:** the DC model uses **within-season rolling features** (recent
gameweeks → next gameweek), NOT cross-season priors. Component detail: clearances
and headed_clearances are the most persistent (role-driven); tackles/interceptions
are more situational. The aggregate CBIT/CBIRT persists about as well as its best
component, so we model it directly.

---

## 3. Finding #2 — Bug #7: components are recorded inconsistently across seasons

Comparing defender per-90 actions between the two seasons:

| component | 2024-25 | 2025-26 | ratio |
|---|---|---|---|
| clearances | 1.97 | 4.37 | **2.21** |
| headed_clearances | 0.94 | 2.54 | **2.70** |
| blocks | 0.29 | 0.57 | 1.94 |
| interceptions | 0.68 | 1.04 | 1.52 |
| tackles | 1.49 | 1.14 | 0.77 |
| recoveries | 4.33 | 3.66 | 0.84 |
| **cbit** | **4.44** | **7.11** | **1.60** |

The shift is **non-uniform** — clearances nearly tripled while tackles/recoveries
*fell*. A real behavioral change would move all actions together; this is a
**recording/definitional change between the two data pipelines** (2024-25 was a
backfill season; 2025-26 is live). It inflates CBIT 1.6× in 2025-26, which tripled
the DC hit rate (6% → 18.6%).

**Consequence:** the target means different things in the two seasons — you cannot
train on 2024-25 and test on 2025-26. **2024-25 is unusable for this target.** The
within-season persistence finding (§2) survives, because it was measured *within*
each season where recording is internally consistent.

**Live architecture (the correct design anyway):** model within 2025-26, and append
each gameweek's data as it arrives. A live FPL tool always predicts *this* season's
next GW from *this* season's history — within-season by nature. Cold-start (GW1–6)
uses a position/team base-rate prior until the rolling window fills.

---

## 4. Finding #3 — the base rate drifts within a season, unpredictably

A single train(GW≤20)/test(GW>20) split over-predicted everything. Cause: the hit
rate itself drifted — 22.5% in the training window, 14.5% in test. The model
anchored to 22% and over-predicted.

**Is the drift a recurring pattern?** Checked both seasons' within-season trend
(GW-number vs hit-rate correlation):
- 2024-25: **+0.355** (rising)
- 2025-26: **−0.536** (falling)

**Opposite directions.** So there is *no* systematic seasonal trend — the base rate
wanders unpredictably each season. This is important: a "gameweek-number" trend
feature would have overfit 2025-26's particular downward slope and been actively
wrong in a season that rises. We deliberately did **not** add one.

**Consequence:** the fix must *adapt* to the current base rate, not *predict its
trajectory*.

---

## 5. The fix — walk-forward retraining (comparison of 4 options)

All four candidate fixes evaluated on the same test window (GW21–38, defenders).
Target actual hit rate: 0.145.

| fix | Brier | mean_pred | verdict |
|---|---|---|---|
| 0 — static (train once) | 0.1226 | 0.205 | over-predicts (baseline problem) |
| 1 — isotonic recalibration | 0.1457 | 0.212 | **worse** — calibrated on high-rate window |
| 2 — recent base-rate feature | 0.1201 | 0.202 | marginal |
| **3 — walk-forward retrain** | **0.1164** | 0.187 | **best Brier** |
| **4 — recency-weighted** | 0.1166 | **0.177** | best calibration |

**Winners: walk-forward retrain (Fix 3) and recency-weighting (Fix 4)**, essentially
tied. Both retrain on recent data so the model's base rate follows the drift.

Two lessons from the losers:
- **Recalibration (Fix 1) backfired** (Brier 0.146, worse than doing nothing)
  because the isotonic layer was fit on GW15–20 where the rate was high, then
  applied to a lower-rate period — it "corrected" toward the wrong level.
  Recalibration only helps when the calibration window matches the test period; with
  a drifting rate it doesn't.
- The residual over-prediction (+0.03 even for the best fix) is irreducible: part of
  the drop was genuinely unpredictable, and no method anticipates a wandering base
  rate perfectly.

**Decision: walk-forward retraining (Fix 3), optionally recency-weighted (Fix 4).**
This is also exactly how the model runs live — retrain each gameweek on all data so
far. The static split was *artificially* penalizing us by freezing the model at
GW20's worldview, which live operation never does.

---

## 6. Why NOT generalize walk-forward retraining to the attacking stats

Considered and rejected. Walk-forward retraining fixes a **drifting base rate**,
which DC has (measured) and the attacking stats do not — npxG/xA were validated
stable across 8 seasons with fixed cross-season priors. Player-level **momentum**
(a separate idea) is already captured by the **rolling features** present in every
model, not by retraining. So walk-forward stays a DC-specific fix, justified by
measured drift; momentum lives in rolling features.

---

## 7. Features (defender model)

Within-season, shift-then-roll (no leakage — only past matches):
- `roll_dc90_3`, `roll_dc90_5` — rolling per-90 CBIT rate (capped at 30 to kill
  tiny-minute per-90 outliers)
- `roll_hit_5` — recent hit rate
- `roll_mins_3` — recent minutes (can't accumulate actions on the bench)

Model: LightGBM classifier, walk-forward retrained per gameweek. Ranking is strong
(prediction spread ~0.01–0.76 — cleanly separates specialists from attackers);
calibration holds once the model stays current via retraining.

---

## 8. Midfielder model (CBIRT) — built, and the CDM investigation

The midfielder model reuses the defender pipeline (same rolling features, same
walk-forward retraining). Base rate is lower: **9.0%** hit CBIRT≥12 (vs defenders'
18.6%).

**Result — walk-forward beats baseline and static:**

| fix | Brier | mean_pred (actual 0.065) |
|---|---|---|
| static | 0.0608 | 0.102 |
| walk-forward | **0.0587** | 0.095 |
| recency-weighted | 0.0588 | 0.089 |
| baseline (base rate) | 0.0630 | — |

Same pattern as defenders: walk-forward retraining wins and fixes the over-
prediction from base-rate drift.

### The CDM investigation — three approaches, all converge

The midfielder calibration looked erratic in the mid-probability bins. Diagnosis:
those bins are thinly populated because **most midfielders are attackers who never
hit CBIRT** — the signal lives in a small defensive-mid (CDM) subgroup. So the
model was evaluated and re-approached focused on CDMs.

**CDMs identified correctly** by rolling CBIRT/90 (Ugarte, Palhinha, André,
Bentancur, Anderson, Florentino — genuine holding mids). Three approaches tested,
evaluated on CDM rows:

| approach | Brier on CDMs | verdict |
|---|---|---|
| base (all-mids model) | 0.1053 | — |
| + `is_cdm` indicator feature | 0.1053 | **identical** — no effect |
| CDM-only model (train on CDMs) | 0.1102 | slightly **worse** |

All three converge, and each convergence is informative:
- **The `is_cdm` flag did literally nothing** — it is derived from `roll_dc90_5`,
  which the model already has as a continuous feature. A binary built from an
  existing feature adds zero information (the tree already splits there).
- **The CDM-only model was worse** — restricting training data lost the low-end
  examples without gaining focus.
- **The base model already handles CDMs as well as anything.**

**The real ceiling is the target, not the model.** Tightening the CDM threshold
barely raised the hit rate (≥8→14%, ≥12→16%, then plateau). **Even genuine
defensive mids only hit CBIRT ~16% of the time**, because a defensive mid *averages*
~10–12 CBIRT/90 — right at the threshold — so clearing 12 in a given match is a
tail event dominated by that match's defensive flow (how much the team defended
that day), which is inherently noisy.

**Conclusion:** the base all-mids walk-forward model is about as good as match-level
midfielder DC prediction gets. CDM-focusing was tested three ways and did not help.
Accepted as-is; mids earn less DC than defenders, and we have hit the predictability
ceiling.

### Team-defensive-style feature — tested, neutral

A rolling team-defensive-volume feature (`team_def_roll`) was built (team ranking
validated: Brentford/Man Utd/Bournemouth high, Villa/Fulham/Chelsea/Arsenal low —
football-sensible). It moved midfielder Brier by 0.0001 (nothing). Reason:
redundant with the player's own rolling rate — a defensive mid at a defending team
already has a high personal rate. Not used. (Same redundancy pattern as price vs
npxG on the attacking side.)

---

## 9. Forward model — no model needed (no signal)

Forwards hit CBIRT so rarely that modeling is counterproductive. In the
feature-ready 2025-26 set the hit rate is **0.4%** — genuine strikers essentially
never accumulate 12 defensive actions. Tested three approaches on GW21+ forward-
matches:

| method | Brier |
|---|---|
| **baseline (flat base rate)** | **0.0031** |
| rolling-rate (own recent hit rate) | 0.0040 |
| LightGBM | 0.0041 |

**The flat baseline wins** — both the rolling rate and LightGBM are *worse* than
predicting the same near-zero probability for everyone. There is no signal to model;
any deviation from "≈0% for all forwards" just adds error.

**Decision: no forward DC model.** Assign forwards a flat base-rate P(DC hit) (~0.4–
1%) as a tiny constant in the E[points] assembly. Zero complexity spent, which is
the correct response to an event that effectively doesn't happen.

---

## 10. Open items

- **Cold-start (GW1–6)** — thin within-season history; needs a position/team
  base-rate prior fallback for defenders and mids.
- **Richer defensive detail** — `core_insights_matchstats` has finer stats (duels,
  blocks split out, xgot_faced, sweeper_actions) not yet tested as DC features.
- **Confirmation on more data** — only a partial 2025-26 season exists. Re-validate
  as gameweeks accumulate (the live append-as-you-go design does this naturally).

---

## 9. Summary

| finding | result |
|---|---|
| Target | P(CBIT≥10 DEF / CBIRT≥12 MID-FWD) per match; ~12–14% base rate |
| Persistence | within-season only (0.44–0.57); cross-season near-zero (team-context-driven) |
| Bug #7 | components recorded inconsistently across seasons (clearances 2.2×, CBIT 1.6×); 2024-25 unusable |
| Base-rate drift | wanders unpredictably (2024-25 rose, 2025-26 fell); no trend feature |
| Fix | walk-forward retraining (+ recency weighting); = live operation |
| Recalibration | backfired under drift — only works if cal window matches test period |
| Not generalized | attacking stats are stable; walk-forward is DC-specific |
| Defender model | walk-forward LGBM; strong ranking, calibrated once current |
| Midfielder model | walk-forward LGBM; works but capped by noisy target |
| Forward model | none — 0.4% hit rate, flat baseline beats any model |
| CDM focus | tested 3 ways (flag / CDM-only / base) — all converge; base is best |
| Ceiling | even real CDMs hit CBIRT only ~16%/match — match-flow noise dominates |
| Team-style feature | tested, neutral (redundant with player's own rolling rate) |

**2025-26 remains the live/test season; validation is within-season walk-forward.**