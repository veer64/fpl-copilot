# Bonus (BPS) Model — Build Log

**Phase 2, Week 6.** Status: complete. Two-piece model built on clean vaastav data;
Core-Insights enrichment attempted and abandoned (data-quality issues).

Per master plan §3.4, bonus is deliberately kept simple — it is a small point
contribution (max 3, ~11% of appearances earn any) and rides largely on components
we already predict (goals, assists, clean sheets, minutes, defensive actions).

---

## 1. How bonus works

After each match, FPL ranks all players by their **BPS** (Bonus Points System — a
raw score from ~30 weighted on-field actions: goals, assists, clean sheets,
tackles, passes, saves, minus cards/errors/missed chances). The **top 3 BPS in each
match** get bonus points: 3 / 2 / 1. Everyone else gets 0.

**Key property — bonus is relative within a match.** You earn it by out-scoring the
*other players in your fixture*, not by hitting a fixed threshold. So the same BPS
wins 3 bonus in a dull match and 0 in a high-quality one. This is why a raw
BPS→bonus lookup is blurry (a BPS of 30 was seen with both 0 and 3 bonus in the
data).

**Data (per player-match who appeared):**
- 0 bonus: 88.8% | 1/2/3 bonus: ~11.2% total (roughly 4,000 each — every match
  awards one 3, one 2, one 1)
- BPS cleanly separates bonus tiers: mean BPS 10 (0 bonus) → 28 (1) → 32 (2) →
  40 (3), monotonic — confirming BPS drives bonus.

---

## 2. The two-piece design

Bonus is predicted in two chained steps:

```
our predictions (E[goals], E[assists], E[CS], E[minutes], E[defensive])
        │
        ▼  Piece 1: predict BPS  ──────────────────────────────
   predicted BPS
        │
        ▼  Piece 2: BPS → expected bonus curve  ───────────────
   expected bonus  (added to E[points])
```

We chose this over predicting BPS-then-ranking-within-fixture (a two-model stack)
because: (a) master plan §3.4 specifies the mapping approach, (b) bonus is small —
not worth a stack, we want *expected* bonus not exact, and (c) it reuses components
we already model.

### Piece 2 — the empirical BPS → expected-bonus curve

Built first (it defines the problem shape). Bucket historical player-matches by BPS
(width 5), average the actual bonus in each bucket. That average **is** the
expected bonus for that BPS level — and taking the average automatically handles the
"relative within a match" problem (it bakes in the historical competition).

| BPS | E[bonus] | P(any bonus) |
|---|---|---|
| ≤15 | ~0.00 | ~0.00 |
| 20 | 0.16 | 0.12 |
| 25 | 0.75 | 0.47 |
| 30 | 1.69 | 0.83 |
| 35 | 2.25 | 0.95 |
| 45 | 2.67 | 0.99 |
| 60+ | ~2.9 | 1.00 |

Shape: **flat ~0 below BPS ~20**, steep rise through the **critical zone 20–40**,
**plateau near 3 above ~45** (can't exceed max 3). Implication: the BPS predictor
only needs accuracy in the 20–40 zone; distinguishing a 5 from a 10 is irrelevant
(both → 0 bonus).

### Piece 1 — predicting BPS from components

BPS is essentially a **weighted sum of on-field actions**, so it is highly
predictable from things we already forecast. Drivers (correlation with BPS): goals
0.60, minutes 0.47, clean sheets 0.39, assists 0.36. Effect sizes are clean and
additive — each goal ≈ +19 BPS; a full 90 ≈ +8; a defender/keeper clean sheet worth
far more than a midfielder's.

**Trained on ACTUAL historical components** (goals/assists/CS/minutes + position +
saves/cards/goals-conceded/penalties), walk-forward (train ≤2023-24, test 2024-25).
The BPS→component relationship is a fixed property of the scoring system, so it is
learned identically whether inputs are actual or predicted — at assembly we simply
feed *predicted* components into the same trained model.

**Algorithm comparison (this is a case where trees genuinely won):**

| model | MAE | R² |
|---|---|---|
| Linear (original 4 components) | 5.39 | 0.620 |
| Linear (+ saves/cards/conceded) | 5.22 | 0.652 |
| RandomForest | 4.23 | 0.742 |
| XGBoost | 4.20 | 0.747 |
| **LightGBM** | **4.19** | **0.747** |

Unlike prior bake-offs where algorithms tied, **trees beat linear by ~0.09 R²
here** — because BPS has real positional *interactions* (a save matters only for
keepers; goals-conceded interacts with position; cards have threshold effects) that
a purely additive linear model misses. Among trees, choice doesn't matter
(RF≈XGB≈LGBM) — LightGBM chosen (fastest, used elsewhere). SVR abandoned mid-run
(O(n²), hung on ~90k rows — a known scaling issue, not needed).

**Final Piece 1: LightGBM, R² 0.747, MAE 4.2 BPS.**

---

## 3. Core-Insights enrichment — attempted and abandoned

The vaastav model's ceiling (R² 0.75) is limited by **missing features**: the big
BPS drivers *tackles, recoveries, CBI, key passes* are **empty (0.0 coverage) in
recent vaastav seasons**. Core-Insights matchstats has them, so we attempted to
enrich.

**It failed on data quality, not concept:**
- BPS lives in the Core-Insights *gameweek* file (matchstats has the actions but no
  BPS), so a join was needed.
- After joining, goals-vs-BPS correlation collapsed to **0.11** (vaastav: 0.60) and
  BPS **max was 673** — impossible (real BPS maxes ~130).
- **272 rows had corrupted BPS >130.** Removing them lifted correlation to 0.44 —
  better but still wrong.
- The residual problem is a **grain mismatch**: matchstats per-match vs gw-file
  per-gameweek did not align cleanly (the double-fixture check returned all 38
  gameweeks, indicating the matchstats `gw`/match grain doesn't map 1:1 to FPL
  gameweeks). Fully reconciling it would take substantial cleaning.

**Decision: abandon the enrichment, keep the clean vaastav model (R² 0.75).**
Rationale: bonus is a small contribution (plan says keep simple), R² 0.75 is
already adequate, and the Core-Insights BPS column has real corruption + grain
issues whose cleaning cost far exceeds the marginal gain. This is the disciplined
call — the enrichment's value was measured to be modest and its data untrustworthy.

**New data finding (Bug #8):** Core-Insights gameweek-file `bps` column contains
corrupted values (272 rows >130, impossible), and its grain does not cleanly map to
FPL gameweeks. Do not use Core-Insights BPS without cleaning.

---

## 4. Assembly note

At assembly (step 4), bonus becomes a plug-in:
1. Feed **predicted** components (from minutes/goals/assists/CS/defensive models)
   into the trained LightGBM BPS model → **predicted BPS**.
2. Look up predicted BPS on the **Piece-2 curve** → **expected bonus**.
3. Add expected bonus to the player's E[points].

Both pieces are trained and ready; only the swap of actual→predicted inputs remains,
which happens naturally at assembly.

---

## 5. Summary

| item | result |
|---|---|
| Design | two-piece: predict BPS → map BPS to expected bonus |
| Piece 2 (BPS→bonus curve) | empirical; flat <20, steep 20–40, plateau ~3 above 45 |
| Piece 1 (predict BPS) | LightGBM, R² 0.747, MAE 4.2 (trees beat linear — positional interactions) |
| Trained on | actual historical components; swap to predicted at assembly |
| Core-Insights enrichment | abandoned — corrupted BPS + grain mismatch (Bug #8); vaastav kept |
| Contribution size | small (max 3, ~11% earn any) — kept deliberately simple per §3.4 |

**2025-26 test season untouched; validation walk-forward on 2024-25.**