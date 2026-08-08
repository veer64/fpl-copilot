# Component Training Reference

Compact reference for the five points-model components: what each was trained on,
which features, which seasons, and how much data. (Optimizer excluded — it consumes
predictions, it isn't trained.) Source: Phase 2 handoff + component build logs.

---

## Summary table

| Component | Model type | Predicts | Train seasons | Key features | Metric |
|---|---|---|---|---|---|
| **Minutes** | 5× LightGBM (decomposed) | E[minutes], P(start), P(60+) | 2022-23 → 2024-25 | recent starts, minutes trend, past-60 rates, prior-season fallback (cold-start) | Brier 0.089 (P start) |
| **Attacking rates** | Empirical-Bayes shrinkage | npxG/90, xA/90 (rates) | All 10 seasons (2016-17 → 2025-26)* | raw npxG/90, xA/90 shrunk toward position×season prior | 0.838 vs 0.826 raw |
| **Dixon-Coles** | Poisson MLE + odds blend | λ (goals), P(clean sheet) | All pre-2025-26 matches | team attack/defence strength, home adv, 1-yr time-decay, Bet365 odds | WDL 53.7% |
| **Defensive** | LightGBM, walk-forward | P(DC hit) | 2025-26 only** | rolling CBIT/CBIRT per-90, position, opponent context | within-season only |
| **Bonus** | LightGBM + empirical curve | E[bonus] | 2022-23 → 2024-25 | BPS components (goals/assists/CS/mins/saves/cards/conceded) → BPS→bonus curve | R² 0.747 (BPS) |

\* Shrinkage *method* validated across 8 prior seasons; rates computed per-season on Understat aggregates.
\** Defensive is 2025-26 only by necessity — CBIT recording is inconsistent in earlier seasons (KNOWN_ISSUES #7).

**Grain note (players):** "all seasons" is *player-gameweek* rows, not per-player. A player who featured 2018-2021 then left simply stops having rows — old rows still train general patterns; on return he starts "cold" (no recent rolling history) and falls back to the prior-season/position prior.

**Grain note (teams, Dixon-Coles):** relegated teams stop appearing in fixtures, so their attack/defence strength just isn't estimated while absent; on promotion they start fresh with weak/default strength until games accumulate, and the 1-yr time-decay discounts any stale pre-relegation strength anyway.

---

## Minutes — detail (5 sub-models, all LightGBM, trained 2022-25)

| Sub-model | Config | Features | Metric |
|---|---|---|---|
| P(start) | 300 trees / 31 leaves | 11 feats + cold-start (has_no_history + prior-season name fallback) | Brier 0.089 |
| P(60+ \| started) | 100 / 7, min_child 100, λ=1 | starter-only rate feats (past60_rate_3/5, last_start_minutes) | Brier 0.061 |
| P(came on \| benched) | 200 / 15 + isotonic calibration | bench/sub-appearance feats | Brier 0.087 |
| E[min \| started] | 200 / 15 | universal minutes feats | RMSE 11.99 |
| E[min \| sub] | 100 / 7 | universal minutes feats | RMSE 13.68 |

Output: (element, gw, p_start, p60, e_minutes). Cold-start via prior-season fallback matched on name.

---

## Attacking rates — detail

- Method: shrunk = w·raw + (1−w)·prior, where w = n90 / (n90 + k), prior = per-position per-season average.
- **k = 2** for FWD npxG (most reliable); **k = 10** for everything else.
- Keyed on stable Understat id. Shrinkage is noise-cleanup, not prediction.
- Defender shot-volume adjustment (+0.081 lift) exists but is NOT wired into validated assembly.

---

## Dixon-Coles — detail

- λ_home = exp(atk[home] + def[away] + home_adv); MLE via scipy L-BFGS-B; 1-yr half-life decay; DC low-score correction.
- **Two blend weights** (verified separately):
  - λ (goal expectations): **pure market, w=0** (best WDL 53.7%)
  - Clean sheets: **w=0.2** (0.2·DC + 0.8·market, best CS Brier 0.1718)
- Trained on all pre-2025-26 matches.

---

## Bonus — detail

- Piece 1: LightGBM predicts BPS from components → R² 0.747.
- Piece 2: empirical BPS→expected-bonus curve (bucket BPS by 5, average actual bonus).
- Trained on vaastav BPS (Core-Insights BPS abandoned — corrupted values, KNOWN_ISSUES #8).
- Deliberately simple per master plan §3.4 (small contribution).

---

## Note on the sealed season

2025-26 is the sealed TEST season — predicted for the live tool, NEVER tuned against.
For the *live assembly*, each component trains on all prior data and predicts 2025-26.
The train seasons above are what each component *learns from*; 2025-26 is what it *predicts*.