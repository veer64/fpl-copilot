# Per-Match Attacking Signals — Investigation Log

**Phase 2, Week 6.** Status: investigated whether Core-Insights per-match data
improves the attacking rate estimates (npxG/xA) beyond the Understat
season-aggregate signals we already use. Conclusion reached; production blend
design documented; one production data-source dependency flagged.

**Question:** our attacking rates (shrunk npxG/xA) come from Understat
**season aggregates** (10 seasons, stable). Core-Insights matchstats offers
**per-match** data (2 seasons) with richer fields. Does it add predictive value —
and if so, how do we use it?

---

## 1. The two sources — a granularity vs history tradeoff

| | Understat season aggregates | Core-Insights matchstats |
|---|---|---|
| Grain | season totals | **per-match** |
| History | **10 seasons** (2016–2025) | 2 seasons (2024-25, 2025-26) |
| Signals | xG, xA, npxG, shots | xG, xA, **xgot, shots_on_target, big_chances_missed, chances_created, touches_opposition_box** |
| Cross-season id | Understat `id` (stable) | Core-Insights `player_id` |

Understat = stable deep baseline. Core-Insights = reactive recent form + richer
fields, but shallow history.

---

## 2. Do the richer fields beat plain xG? — No

Tested which per-match signal best predicts next-period goals/90 (within-season
half-split, per position):

- **Midfielders (n=236):** xg (0.642) is the clear best; total_shots, sot, xgot,
  touches_box all rank below it.
- **Forwards (n=53):** xg (0.559) at/near the top (only the noisy
  big_chances_missed edged it, on a tiny sample).

**The fancy fields (xgot, touches_box, chances_created) do not beat plain xG.**
So Core-Insights' *extra columns* add little predictive value over the xG we
already use. (This is also the master plan's stance on the ICT index — use raw
underlying signals, not FPL's opaque composite; here even the raw extras don't
beat xG.)

---

## 3. Does per-match RECENCY beat the season average? — Yes (modestly)

The real value of per-match data is not richer fields but **recent form** —
something season aggregates structurally cannot capture. Tested by predicting
next-match goals/90 from rolling recent-form features, held-out (train 2024-25,
test 2025-26), five algorithms:

| method | held-out RMSE |
|---|---|
| baseline (season-avg xG as prediction) | 0.531 |
| **RandomForest** | **0.465** |
| LightGBM | 0.474 |
| LinearRegression | 0.479 |
| SVR | 0.480 |
| XGBoost | 0.481 |

Two findings:
- **Recent-form models beat the season-average baseline** (~0.47 vs 0.53). So
  per-match recency *does* add real predictive signal.
- **Algorithm choice barely matters** (all within 0.016) — it is feature-limited,
  not algorithm-limited. Same lesson as the E[min|started] bake-off. No deep
  learning justified here: DL amplifies existing signal, and on 2 seasons of
  tabular data with a flat algorithm ceiling there is nothing for it to exploit
  that boosting/RF do not already capture (consistent with master plan §3.5 —
  DL must earn its place; boosting is expected to be hard to beat).

**Caveat — the noise ceiling:** all RMSEs are high (~0.47) because *single-match*
goals are dominated by irreducible randomness (a 0.5-xG chance scores 0, 1, or 2).
Recency helps, but single-match prediction has a hard ceiling. The value shows up
in the *rate estimate* (which feeds the points model), not in nailing any one match.

---

## 4. Why NOT build a cross-source blend backtest

The natural next step — formally blend the Understat season prior with
Core-Insights recent form and validate — was considered and **declined**, for a
concrete reason:

**The ID bridge between the two sources only exists for 2025-26.** The chain is
Core-Insights `id` → `player_id_crosswalk_final.csv` (element → understat_id) →
Understat `id`. That crosswalk is **single-season (2025-26 only)**; ~525 players
bridge. So a cross-source blend could only be *validated on one season* — thin
evidence, plus fragile ID-bridging code. Tuning a blend weight on one season risks
overfitting for negligible payoff.

We already have what we need: recency demonstrably adds signal (§3). The remaining
question is a *design* question (how to combine stable prior + live form in
production), not a modeling question needing another backtest.

---

## 5. The production blend design (the deliverable)

The system combines the two the way a manager reasons — stable baseline,
progressively overridden by live form. Same append-as-you-go pattern as the
defensive-contribution model.

1. **Season start (cold-start):** lean on the **stable Understat prior** — the
   player's shrunk npxG/xA from prior seasons (recency-weighted toward the most
   recent season). *Not* the previous season's last-5-games form — that is the
   *noisy* component of output, and the summer (transfers, role/manager changes,
   fitness resets) destroys short-term form while preserving the underlying rate.
   Cross-season persistence holds for the season *rate* (0.68), not for recent
   form.

2. **In-season:** blend in **rolling current-season form** from per-match data,
   weighting recent form more as gameweeks accumulate. By ~GW5–6 the current
   season dominates the prior.

3. **Irreducible cold-start:** GW1–4 stays genuinely uncertain for new signings
   (no PL history), promoted-club players, and unrevealed role changes — no prior
   fixes a player with no relevant history. This is the real "cold-start problem":
   the prior is weakest exactly when there is no current data to correct it.

This mirrors the two other stable-base + live-signal blends in the system:
Dixon-Coles + betting odds, and the DC walk-forward retraining.

---

## 6. Production data-source dependency — FLAGGED, needs resolution

**Open question for production ingestion (§2.1–2.3 of the master plan):**

- **Understat** has a live path — the `understat_sync` weekly DAG pulls the
  completed gameweek's xG/xA via the `understatapi` package. So season-aggregate
  recency is covered live.
- **Core-Insights matchstats** (the per-match source used here) is a **GitHub repo
  (olbauday/FPL-Core-Insights)**, described in the plan as a historical/backfill
  source — **not** a guaranteed live per-match feed. Its live availability depends
  on that repo being maintained through the 2025-26 season.

**Implication:** the richer per-match fields (xgot, touches_box, etc.) may not have
a reliable live feed. But since §2 showed those fields do **not** beat plain xG,
this is low-risk: the production recency signal can come from **Understat's own
weekly per-GW xG** (which *is* live) plus the **FPL API's post-match stats**,
without depending on Core-Insights staying current. Core-Insights remains useful
for backfill/enrichment but is not on the critical live path.

**Action:** verify at season start whether Core-Insights updates live; if not,
source in-season xG recency from Understat weekly + FPL API. Not a blocker.

---

## 7. Summary

| finding | result |
|---|---|
| Richer Core-Insights fields (xgot, box touches) vs plain xG | do **not** beat xG |
| Per-match recency vs season average | **helps** (~0.47 vs 0.53 RMSE, held-out) |
| Algorithm choice | barely matters (flat ~0.47 across RF/LGBM/XGB/SVR/linear) |
| Deep learning | not justified — feature/noise-limited, not algorithm-limited |
| Single-match prediction | hard noise ceiling; value is in the rate estimate, not one match |
| Cross-source blend backtest | declined — ID bridge is 2025-26-only; thin/fragile |
| Production design | stable Understat prior (cold-start) → rolling per-match form (in-season) |
| Production data gap | Core-Insights per-match is GitHub/backfill, not guaranteed live; fall back to Understat weekly + FPL API for live xG recency |

**2025-26 test season remains untouched for final evaluation.**