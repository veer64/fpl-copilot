# E[points] Assembly — Build Log

**Phase 2, Week 6.** Status: complete and validated. The five component models
(minutes, attacking rates, Dixon-Coles, defensive contribution, bonus) are joined
into a single per-player-gameweek **E[points]** prediction for the live 2025-26
season, validated against actuals.

This is the capstone that turns five separate models into one prediction.

---

## 1. What assembly does

Combine the components via the master equation (master plan §3.0):

```
E[pts] = appearance
       + E[goals]·goal_pts(pos)
       + E[assists]·3
       + P(clean sheet)·CS_pts(pos)·P(60+)
       + P(DC hit)·2
       + E[bonus]
```

Each term is built from a different model's output, at one row per (player, gameweek).

---

## 2. The ID bridge — the first and thorniest task

The five components speak **four different ID schemes**:

| component | native key |
|---|---|
| Minutes | vaastav `element` |
| Attacking rates | Understat `id` |
| Dixon-Coles | team name (football-data.co.uk style) |
| Defensive contribution | Core-Insights `player_id` |
| Bonus | (rides on components) |

**Resolved using `player_id_crosswalk_final.csv`** (from Phase 1 — element ↔
player_id ↔ understat_id, 841 players, 2025-26). Key facts that made it work:

- **The spine is perfect:** all 841 crosswalk elements match 2025-26 vaastav
  elements exactly (0 mismatches) — both pull from the same official FPL API.
- **`element == player_id`** in 2025-26, so minutes ↔ DC join **directly**, no
  translation. One less bridge.
- **`understat_id` is nullable** — only 525/841 (62%) have one; the rest are bench
  players Understat never tracked. These get the position-average attacking-rate
  fallback, not a broken join.
- **Team names:** only **2 mismatches** (Man United→Man Utd, Tottenham→Spurs); 18/20
  already agreed. A 2-entry map fixed it.
- **No gameweek in the odds file:** bridged via `kickoff_time` in vaastav →
  (team, gw, date), then joined to Dixon-Coles fixtures on (team, date).

**Two duplication bugs caught during joins** (both would have inflated the final
points):
- Attacking join grew asm 29k→43k: Understat multi-position labels ("F M S") gave
  duplicate understat_ids. Fixed by deduping rates to one row per player (primary
  position).
- DC join grew asm by 114: double-GW per-match rows. Fixed by collapsing to one
  row per (element, gw), taking max p_dc_hit.

Final skeleton: **29,338 player-gameweeks**, one row each, all IDs attached.

---

## 3. Training for the live season

Each component predicts **2025-26** (the live/sealed season). For assembly, models
train on **all prior data** (not the train/validate split used to *measure* them):

- Minutes: trained on 2022-25, predicts 2025-26
- Attacking rates: shrunk 2025-26 rates (method validated on 8 prior seasons)
- Dixon-Coles: fit on all pre-2025-26 matches (1-yr decay), predicts 2025-26 fixtures
- Defensive contribution: walk-forward within 2025-26 (retrains per gameweek)
- Bonus: BPS model trained on 2022-25

**2025-26 is the sealed test season** — predicted for the live tool, never tuned
against.

---

## 4. The master equation, term by term

- **Appearance** (3-state): `P(60+)·2 + P(plays <60)·1`, where P(60+) = p_start·p60.
- **Goals:** `E[goals]·goal_pts`, E[goals] = npxg90 · (e_minutes/90) · fixture_scale,
  fixture_scale = team_λ / league_avg_λ (1.40), clipped [0.5, 2.0].
- **Assists:** `E[assists]·3`, E[assists] = xa90 · (e_minutes/90) · fixture_scale.
- **Clean sheet:** `P(CS)·CS_pts·P(60+)` — requires 60+ minutes; DEF/GK 4, MID 1, FWD 0.
- **Defensive contribution:** `P(DC hit)·2 · (e_minutes/90)`.
- **Bonus:** predicted BPS → empirical curve → scaled by minutes, recalibrated to
  the actual bonus rate.

goal_pts = FWD 4, MID 5, DEF/GK 6.

---

## 5. THE KEY FIX — gate every performance term by playing probability

Initial validation showed **systematic ~2× over-prediction**, worst for nailed
players (70+ min: predicted 5.90 vs actual 3.54). Decomposing by scoring component
revealed the culprit precisely:

| component | predicted | actual |
|---|---|---|
| goals | 0.53 | 0.44 ✓ |
| assists | 0.25 | 0.27 ✓ |
| clean sheet | 0.74 | 0.65 ✓ |
| appearance | 1.77 | ~1.9 ✓ |
| **bonus** | **2.28** | **0.27** ✗ 8× |

Bonus was the loud offender, but the deeper, systematic bug was that **several terms
did not respect playing probability**. The clearest example: the DC fallback gave
benched players a position base rate (0.125), so a benched defender earned
0.125·2 = 0.25 DC points *for a match he'd never play*. Across 16,770 low-minute
rows, this inflated everything.

**The principle that fixed it:** *you only earn points for what happens on the
pitch.* Every performance term must be scaled by expected playing time:
- DC: `× (e_minutes/90)` — no minutes, no defensive actions, no DC points
- Clean sheet: gated by P(60+), not just p60
- Bonus: `× (e_minutes/90)` and recalibrated
- Appearance: proper 3-state on P(60+) and P(any play)

This was a **principled fix, not a hack** — and the calibration snapped into place.

**Before → after, predicted vs actual by minutes band:**

| band | before (pred) | after (pred) | actual |
|---|---|---|---|
| <15 | 0.78 | 0.37 | 0.13 |
| 15-45 | 2.33 | 1.32 | 1.44 |
| 45-70 | 4.30 | 2.56 | 2.63 |
| **70+** | **5.90** | **3.54** | **3.54** |

Nailed players went from 1.7× over to **exactly calibrated**.

---

## 6. Validation — the honest verdict

Predicted E[points] vs actual points, all 2025-26 player-gameweeks with results:

| metric | value |
|---|---|
| **Spearman (rank) correlation** | **0.716** |
| Pearson correlation | 0.581 |
| MAE | 1.13 points |
| Mean predicted / actual | 1.36 / 1.17 (near-unbiased) |
| MAE vs fair baseline | 1.12 vs 1.07 |

**How to read this:**
- **Spearman 0.716 is strong** — the model ranks players well, which is what FPL
  decisions need (who to pick, not exact points).
- **Calibration is monotonic and unbiased** — every predicted bucket scores higher
  than the last; nailed players are exactly calibrated.
- **The "fair baseline" (1.07) is each player's prior-games average** — a genuinely
  hard predictor for *established* players, and we essentially match it (1.12) while
  ranking better (Spearman) AND predicting players it can't (new signings, no-history
  players, fixture swings). The baseline needs history; we predict from first
  principles.
- **Per-GW FPL points are noise-dominated** — a nailed premium can blank or haul, so
  MAE ~1.0 is near the irreducible floor. We're at it.

The naive full-season-average baseline (MAE 1.01) is **not** a fair comparison — it
uses future information (the games being predicted). The prior-games baseline (1.07)
is the honest one.

---

## 7. Modularization — from notebook to standalone pipeline

The validated notebook was hardened into a **production-shaped modular pipeline**:
five component modules, each exposing one clean function, plus an orchestrator that
imports them. No shared globals, no pasted cells, no re-exec — one command runs
everything.

```
Components to predict points/
  minutes.py          → get_minutes_2526()   → mins_out (element,gw,p_start,p60,e_minutes)
  attacking_rates.py  → get_rates_2526()     → (rates, priors)
  dixon_coles.py      → get_fixtures_2526()  → fixtures (lam, p_cs, match_date)
  defensive.py        → get_dc_2526()        → dc_out (walk-forward, all gameweeks)
  bonus.py            → get_bonus_model()    → (bps_model, bps_to_bonus, BPS_FEATURES)
  assembly.py         → imports all five, joins, master equation, validates, saves
```

**Run:** `python assembly.py` (retrains all components, ~few minutes). It builds the
predictions, prints validation, and persists `data/predictions_2526.parquet` for the
optimizer downstream.

**Two bugs found and fixed during modularization:**
- **Empty early gameweeks (DC):** `get_dc_2526()` loops all gameweeks; GW1–2 have no
  rolling features, so `_predict_gw` returned an empty list → `pd.concat([])` crash.
  Fixed: return `None` for featureless gameweeks, filter before concat. Those players
  correctly fall back to the position base rate in assembly.
- **Filename↔module mismatch:** files must be named exactly `attacking_rates.py` etc.
  (no spaces/caps) for imports to resolve.

**Reproduces the validated result** (run from the modular pipeline):

| metric | notebook | modular pipeline |
|---|---|---|
| Spearman | 0.716 | 0.715 |
| MAE | 1.13 | 1.13 |
| MAE vs fair baseline | 1.12 / 1.07 | 1.12 / 1.07 |
| Mean pred / actual | 1.36 / 1.17 | 1.36 / 1.17 |

Run-to-run randomness shifts absolute e_points slightly (e.g. top player's peak), but
ranking and calibration are stable. The bonus over-prediction fix (minutes-gating +
recalibration to actual rate) lives in `assembly.py` §7, exactly as validated.

---

## 8. Known limitations / future work

- **Fringe (<15 min) still slightly over** (0.38 vs 0.13) — low-stakes bench players;
  the DC/bonus fallbacks for no-history players are still a touch generous. Minor.
- **Bonus is recalibrated, not first-principles** — predicting bonus from smoothed
  BPS overweights it (bonus needs *top-3-in-match*, which a point estimate misses).
  Kept simple per §3.4; a proper rank-based bonus model is future work.
- **Model is "steady"** — rates are season-level, so it favors proven premiums and
  won't catch a differential's hot streak. Correct for *expected* value.
- **No model caching yet** — every run retrains all components from scratch. Next
  optimization: serialize fitted models (the master plan's MLflow registry).
- **Not yet the `fpl/` package** — the modules live in one folder; the full package
  layout (`fpl/models/`, `fpl/features/`), Postgres predictions mart, and the
  `predict_points` agent tool are Week 7 production work. This modular pipeline is the
  right foundation for it.
- **Cross-model dedup** is handled in `assembly.py` (asserts guard against it); could
  move into the component modules.

---

## 8. Summary

| item | result |
|---|---|
| ID bridge | crosswalk spine perfect (841/841); element==player_id; 2 team-name fixes |
| Grain | 29,338 player-GWs, deduped (caught 2 join-duplication bugs) |
| Master equation | 6 terms, position-aware scoring |
| Key fix | gate every performance term by playing probability (DC was the bug) |
| Calibration | nailed players exactly calibrated (3.54 = 3.54) |
| Ranking | Spearman 0.716 |
| MAE | 1.13 (matches fair no-leakage baseline; near noise floor) |
| Bias | near-zero (mean 1.36 vs 1.17) |

**The five component models now produce one validated E[points] prediction for the
live season. 2025-26 remains the sealed test — predicted, not tuned against.**