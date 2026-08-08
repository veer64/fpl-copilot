# LightGBM Benchmark — Build Log

**Phase 2, Week 6 (owed item #1 from the Optimizer handoff).** Status: complete.

The decomposed points model (Spearman 0.716) needed an honest baseline: would a
brute-force model, given the same information, do just as well? Without that number,
0.716 means nothing. This log builds two LightGBM benchmarks and reports the verdict.

---

## 1. Why benchmark at all

A headline metric on its own is not evidence. "My model scored 0.716" is only
meaningful against a bar. LightGBM direct regression is the honest bar for tabular
data: it needs no decomposition, no domain knowledge, no hand-built equation. If it
matches the decomposed model, the decomposition bought nothing. If the decomposed
model wins, it earned its complexity. Either result is publishable; the *number* is
the artifact.

Two benchmarks were built:

- **Option B — raw features -> points.** Answers: *was decomposing worth it at all?*
- **Option A — component outputs -> points.** Answers: *can a learned combination of
  my own components beat my hand-built master equation?*

---

## 2. Fairness rules (what keeps this honest)

- **Same sealed test season.** 2025-26 was the decomposed model's sealed test; both
  benchmarks are judged on it (B) or within it (A). Never tuned against.
- **Same information.** Option B gets only the raw ingredients the components used,
  turned into leakage-safe features. No extra data the decomposed model never saw.
- **Same population.** Head-to-head comparisons score both models on the *identical*
  rows (inner join on element+gw), so nobody wins by being scored on an easier set.
- **Leakage-safe features.** Every rolling feature uses `shift(1)` BEFORE `rolling()`,
  grouped by (season, element), so the current gameweek can never enter its own
  feature. Verified on Haaland by hand before scaling.

---

## 3. Option B — raw features -> points

### 3.1 Features (18, all as-of)
- 12 rolling form features: total_points / minutes / expected_goals /
  expected_assists / bps / starts, each over windows {3, 5}.
- was_home (fixture signal), value (price).
- 4 position dummies (one-hot: DEF / FWD / GK / MID).

`starts` is blank pre-2022-23 (source gap); LightGBM handles NaN natively, so it is
left in rather than imputed.

### 3.2 Data-quality catches (verify-before-proceeding paid off)
- Dropped 322 Assistant-Manager (`AM`) rows — 2024-25 only, not players, different
  scoring rules. Poison in a player model.
- Merged `GKP` -> `GK` — label drift in 2021-22 (101 rows), same position.
- Confirmed price range 36-154 (£3.6m-£15.4m) — clean, no impossible values once AM
  removed.

### 3.3 Split
- Train: 2016-17 -> 2024-25 (223,821 rows).
- Test: 2025-26 sealed (29,757 rows).
- Model: LightGBM, deliberately UNTUNED (300 trees, lr 0.05, 31 leaves). A benchmark
  should be a fair baseline, not a lovingly optimized one.

### 3.4 The three-band result (the real finding)

Scored on shrinking populations — this is where the aggregate metric is exposed:

| Slice            | N      | LGBM Spearman | Decomp Spearman | LGBM MAE | Decomp MAE |
|------------------|--------|---------------|-----------------|----------|------------|
| All rows         | 29,757 | 0.708         | 0.714           | 0.995    | 1.126      |
| Played (>0 min)  | 11,498 | 0.316         | 0.341           | 1.998    | 1.998      |
| Started (60+)    | 7,815  | 0.100         | 0.104           | 2.383    | 2.361      |

**Reading it:**
- The headline 0.708 collapses to 0.100 once you remove non-players. Almost all of
  both models' apparent "skill" is ranking the EASY question (*will they play?*), not
  the hard one (*among starters, who scores more?*).
- The decomposed model wins every band, but only marginally (0.714 vs 0.708 overall;
  +0.025 among players). Real, consistent, small — not a step-change.
- LightGBM's lower MAE on "All" is the benchwarmer effect: it predicts low numbers for
  non-players slightly better. On STARTERS, the decomposed model's MAE is actually
  lower (2.361 vs 2.383). So "LightGBM is more accurate" is false where it matters.

---

## 4. Option A — component outputs -> points

Feed LightGBM the decomposed model's OWN component columns (e_minutes, pts_goals,
pts_assists, pts_cs, pts_dc, pts_appear, exp_bonus) and let it learn its own weighting,
vs the hand-built master equation (e_points).

### 4.1 Split (forced within-season)
Component outputs only exist for 2025-26 (the defensive component cannot be built for
earlier seasons — KNOWN_ISSUES #7, inconsistent CBIT recording). So A trains and tests
inside 2025-26: train GW1-25 (19,000 rows), test GW26-38 (10,757 rows). This is fine —
A's question (learned combination vs equation) does not need multiple seasons.

### 4.2 Result

| Slice           | N      | LGBM-A Spearman | Equation Spearman | LGBM-A MAE | Equation MAE |
|-----------------|--------|-----------------|-------------------|------------|--------------|
| All             | 10,757 | 0.753           | 0.713             | 0.873      | 1.072        |
| Played (>0 min) | 3,918  | 0.287           | 0.353             | 2.071      | 1.968        |
| Started (60+)   | 2,670  | 0.109           | 0.125             | 2.386      | 2.327        |

**Reading it:**
- LightGBM-A wins the HEADLINE (0.753 vs 0.713) — but the headline is the misleading,
  zero-dominated number.
- On players who actually played, the HAND-BUILT EQUATION wins on both Spearman
  (0.353 vs 0.287; 0.125 vs 0.109) and MAE (1.968 vs 2.071; 2.327 vs 2.386).
- The equation encodes structure (minutes-gating, position-aware scoring, fixture
  scaling) that LightGBM could not recover from 19k rows of a single season. The
  hand-built assembly was not wasted — it beats a learned re-combination where it
  counts.

Caveat: A is tested only on GW26-38 of one season, a smaller/later test than B. A's
0.753 is NOT comparable to B's 0.708 (different test sets). The equation-vs-learned
comparison WITHIN A is clean and fair.

---

## 5. The verdict (what the whole exercise proved)

1. **Decomposition was worth it — a little.** The decomposed model slightly beats a
   raw-feature LightGBM baseline across every slice (B).
2. **The master equation was worth it.** A learned combination of the same components
   could not beat the hand-built equation among players who played (A).
3. **Everyone hits the same wall.** Ranking among starters is ~0.10 Spearman / ~2.4 MAE
   for EVERY model. Per-gameweek FPL points are noise-dominated — a nailed premium can
   blank or haul. This is the truth about the problem, not a flaw in any model.

The decomposition's real value is not a raw-accuracy step-change (there isn't one). It
is: a small consistent edge, interpretability (component breakdown), and cold-start
handling — LightGBM cannot rank a player with no rolling history; the structural model
can predict from first principles.

---

## 6. What this feeds

- This band table is the first row of the eval ladder (master plan §3.5, §4.3).
- The Option B LightGBM model is the substrate for SHAP (next task) -> the agent's
  `explain_prediction` tool.
- The three-band method (never trust an aggregate; slice by minutes) is now the house
  standard for every future model comparison.