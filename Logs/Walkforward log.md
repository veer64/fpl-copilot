# Walk-Forward Harness — Build Log

**Phase 2, Week 6 (owed item #2 from the Optimizer handoff).** Status: complete.

Built a strict walk-forward evaluation harness: every gameweek of 2025-26 predicted
using **only** data available before that gameweek, with all components retrained or
refit at each step. Along the way, three real leaks were found and fixed.

**Headline finding: strict per-gameweek retraining changes nothing (0.715 -> 0.715).**
A measured negative result with a practical consequence.

---

## 1. What walk-forward is, and why build it

Until now, 2025-26 was validated as one sealed block: train on the past, predict the
whole season at once. That gives a headline number but tests the model at a single
point in time. Walk-forward instead mimics live operation:

> At gameweek *k*: train on everything before *k*, predict *k*, roll forward.

Each gameweek is predicted the way it would have been predicted live. This is the
"expanding window" evaluation the master plan (§4.3) requires, and it is the direct
foundation for the season simulator/backtest (§4.4, the crown jewel), which is this
same loop with the optimizer bolted on.

**"Walk-forward capable"** = a component that accepts a cutoff — a *time dial* telling
it "train as if standing at gameweek k, with k+1..38 unplayed." Adding the dial does
not change default behaviour; every component reproduces its original result when the
dial is left alone.

---

## 2. Leaks found and fixed on the way

Making components cutoff-aware exposed three leaks. Full detail in LEAKAGE.md.

| # | Where | What leaked | Fix |
|---|---|---|---|
| 1 | `attacking_rates.py` | Rates built from **2025-26's own full-season** Understat totals — predicting GW1 used a rate computed from all 38 GWs | Build from **prior seasons (2022-24, pooled counts)** |
| 2 | `bonus.py` | The empirical **BPS->bonus curve** was built on all rows *including* 2025-26 (the `season <= 2024-25` filter applied only to the LightGBM model, not the curve) | Curve now respects the cutoff |
| 3 | `assembly.py` §7 | Bonus recalibration used the **full-season 2025-26 actual bonus mean** — a constant fitted to the test season | Moved into `bonus.py`, computed from cutoff-respecting data, returned as a 4th value |

---

## 3. Component-by-component changes

| Component | Change | Leak fixed? | Time dial |
|---|---|---|---|
| `attacking_rates.py` | Prior-season pooled rates replace current-season totals | **Yes** | Not needed — prior seasons don't vary by gameweek (walk-forward **safe**, not *capable*) |
| `bonus.py` | Cutoff-aware curve + model + recalibration mean; returns 4 values | **Yes (x2)** | `up_to_gw=k` |
| `minutes.py` | Split into `_prepare` / `_build_frames` / `_train_mask`; training rows re-filterable | No — features were already shift-then-roll safe | `up_to_gw=k`, `predict_gws=[k]` |
| `dixon_coles.py` | DC fit on matches strictly before a cutoff date | No — already trained only on pre-2025-26 | `cutoff_date=d` |
| `defensive.py` | **Untouched** | No | Already walk-forward internally (`_predict_gw` trains on `gw < target_gw`) |

**Scope note on Dixon-Coles:** because `LAM_BLEND_W = 0.0`, the goal expectations
(`lam_home`/`lam_away`) that drive `fixture_scale` come **purely from Bet365 odds**,
which are inherently point-in-time. The DC fit only influences **clean sheets**, at 20%
weight (`CS_BLEND_W = 0.2`). So the time dial here is a correctness fix with a
deliberately small footprint.

Every shim (`get_rates_2526`, `get_minutes_2526`, `get_fixtures_2526`) was verified to
reproduce assembly's result **exactly** before being trusted in the loop.

---

## 4. Effect of the leak fixes on the headline result

| stage | Spearman | MAE | mean pred/actual | 70+ band pred/actual |
|---|---|---|---|---|
| Original (leaky) | 0.716 | 1.13 | 1.36 / 1.17 | 3.54 / 3.54 |
| + rates fix | 0.715 | 1.14 | 1.38 / 1.17 | 3.85 / 3.54 |
| + bonus fixes | 0.715 | 1.15 | 1.40 / 1.17 | 3.90 / 3.54 |

**Ranking never moved.** Three leaks removed, Spearman held at 0.715 throughout — which
*proves the leaks were not propping up the headline result*. That is a stronger claim
than a clean number with no self-scrutiny behind it.

**Calibration drifted, and that is the honest part.** The original "perfect" 70+ band
(3.54 = 3.54) was partly an artefact: the bonus recalibration constant was fitted to the
test season's own bonus mean. Removing that peek exposed a real ~10% over-prediction on
high-minute players. Ranking is what FPL decisions need and it is intact, but the
calibration bias is now visible and honest. A proper rank-based bonus model (already
flagged as future work in the assembly log) is the real fix.

---

## 5. The strict run

38 gameweeks, all components retrained/refit per gameweek, **13 minutes**, 29,338 rows.
Output persisted to `data/walkforward_2526.parquet`.

Per-gameweek cost ~21s, dominated by the minutes model (5 sub-models). Two components
run once outside the loop: attacking rates (constant — prior-season) and defensive
(already produces all gameweeks in one internally-walk-forward call).

### Result vs the static model

| | walk-forward | static |
|---|---|---|
| Spearman | **0.715** | 0.715 |
| MAE | **1.15** | 1.15 |
| Mean pred/actual | 1.40 / 1.17 | 1.40 / 1.17 |

### Three-band slice (house standard)

| Slice | N | Spearman | MAE |
|---|---|---|---|
| All rows | 29,338 | 0.715 | 1.15 |
| Played (>0 min) | 11,361 | 0.337 | 2.04 |
| Started (60+) | 7,738 | 0.099 | 2.41 |

Identical collapse pattern to the LightGBM benchmark (0.708 / 0.316 / 0.100). Every
model tested now lands at ~0.10 among starters — strong evidence this is a property of
**the problem**, not of any particular model. Per-gameweek FPL points are
noise-dominated once you condition on a player featuring.

---

## 6. Why retraining bought nothing (the interesting part)

Strict per-gameweek retraining produced *identical* numbers to training once. Two
honest reasons:

1. **The training set barely changes.** Components train on ~3 seasons (80k+ rows).
   Adding 10-20 gameweeks of 2025-26 (~8-15k rows) is marginal; the learned patterns
   (what predicts a start, how rotation works) do not shift.
2. **The features already carried the recency.** Rolling features (shift-then-roll over
   the last 3/5 games) *already* encode current-season form, gameweek by gameweek. The
   model was always seeing this season's information — through features, not through
   training data. Retraining just adds redundant signal.

**The lesson worth keeping: feature recency mattered; model recency did not.**

**Practical consequence:** the production `weekly_retrain` DAG (master plan §2.3) is
*not* urgent. Retraining monthly, or even per-season, is defensible — now with evidence
rather than assumption. Feature freshness is what must be kept current.

---

## 7. Related negative result: time decay

Time decay (1-year half-life, matching Dixon-Coles) was applied once to the pooled
prior-season attacking rates. Spearman unchanged (0.715); calibration marginally
**worse** (70+ band 3.85 -> 3.87; mean 1.38 -> 1.39). Dropped.

Applied **once** with a principled setting, not grid-searched — 2025-26 is the sealed
test season and tuning against it would be fishing. If decay is revisited, it must be
tuned on the **validation season (2024-25)**.

---

## 8. What this feeds / what's next

- **The harness is the substrate for the season simulator + backtest** (§4.4) — that is
  this same loop with the optimizer making transfer/captain decisions each gameweek.
- **Distil the notebook to a `.py`** (`make eval-models`, master plan §6.1) — currently
  the harness lives in `Notebooks/explore_features.ipynb`.
- **Open limitation:** prior-season attacking rates are blind to new signings, breakouts
  and decliners. Blending prior-season with current-season accumulated rates is logged
  in FEATURE_IDEAS.md — it needs a per-gameweek xG data decision first.