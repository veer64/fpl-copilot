# Transfer MIP + Sweeps — Build Log

> ## ⚠ SUPERSEDED BASELINE — figures below are NOT comparable to current builds
>
> **Added 2026-08-14.** Every number in this log predates three changes that each
> moved the prediction surface it was measured on. The numbers are left in place
> deliberately — they are the record of what was believed at the time — but they
> must not be compared against anything built after 2026-08-14.
>
> **1. Baseline migration (M3).** The canonical walk-forward file was rebuilt with
> `availability=True`. It had been `availability=False`. Horizon-0 Spearman moved
> 0.715 → 0.745, MAE 1.15 → 1.11. **Any figure quoting a season total of 1984 is on
> the pre-migration baseline.** The pre-migration artefact is preserved as
> `data/walkforward_h6_2526_prefix.parquet` and still reproduces 1984 exactly, so
> these numbers remain checkable — they are stale, not lost.
>
> **2. Double-gameweek handling.** The master equation now runs per player-FIXTURE
> and sums, so a double carries both opponents. Previously three independent
> defects priced a double as a single fixture (minutes_frac capped at one fixture,
> the Dixon-Coles join kept an arbitrary fixture, the DC join took a max). Doubled
> players' predictions roughly doubled. **Any chip-timing or fixture-structure
> conclusion drawn before this is invalid**, because the planner could not see a
> double at all.
>
> **3. Odds horizon fixed at 0 (project decision, not a tunable).** Only the current
> gameweek's market is reliably published at a Friday deadline; reading odds for
> later gameweeks is a leak. Figures built at `ODDS_HORIZON_GWS = 2` are inflated
> relative to current builds — measured at roughly +39 points on one paired
> comparison. That drop is the removal of a leak, not a regression.
>
> Current canonical: `data/walkforward_h6_2526.parquet`, stamped
> `minutes_availability=True`, `odds_horizon_gws=0`, `dgw_handling='per_fixture'`.

> ### ⚠ Additional note for this log specifically: the horizon/decay sweep grid
>
> The entire (H, decay) grid — every cell from 1851 to 2097, both the odds and
> DC-only variants — was produced at `ODDS_HORIZON_GWS = 2` on the pre-migration,
> pre-DGW-fix predictions. **None of those cells is comparable to a current build,
> and the odds-variant grid is the leaky one.** The log's own §6.2 warning ("do NOT
> read the argmax") still applies, and now applies twice over.
>
> H=3 and decay=0.3 remain the shipped defaults. They were chosen on that grid and
> have NOT been re-tuned on the current surface — they are inherited settings, and
> re-tuning them on season totals would repeat the mistake the M1 gate exposed.


**Phase 4 §3.6 work, pulled forward ahead of Phase 3 DL.** Status: MIP complete and
swept; conclusions below. Chips not yet built.

Continues from `Logs/Simulator log.md` (simulator v1, 1889 points, +521 over
set-and-forget).

---

## 1. What was built

| Piece | File | Purpose |
|---|---|---|
| MLflow for simulator runs | `squad/experiment.py` | One run = one season under one config |
| HiGHS solver | `squad/optimize.py` | ~2x faster per solve, 10x faster test suite |
| Multi-GW transfer MIP | `squad/transfer_mip.py` | Solver chooses how many transfers, which, and whether a hit is worth it |
| Horizon-aware harness | `eval/walkforward.py` | As-of predictions for GW k..k+5 from cutoff k |
| Horizon sweep | `squad/sweep_horizon.py` | Season at H = 1,2,3,4,6 |
| Decay sweep | `squad/sweep_decay.py` | Season across (horizon, decay) grid, A/B on data variant |

`eval/walkforward.py` also clears the owed item from the walk-forward log
("distil the notebook to a .py", master plan §6.1).

---

## 2. The MIP formulation

Replaces the v1 search (try keeping, try selling each of the 15, take the best of
16 solves) with one optimization per gameweek.

Per player i, per gameweek t: `pick`, `buy`, `sell`, `start`, `captain`, `vice`.

**Squad continuity** — the constraint that gives a squad a past:

    pick[i,t] = pick[i,t-1] + buy[i,t] - sell[i,t]
    buy[i,t] + sell[i,t] <= 1

**Hits, linearized without big-M:**

    hits[t] >= used[t] - ft[t]

Only the `>=` side is written. `hits[t]` carries a negative coefficient in a
maximized objective, so the solver drives it to its lower bound and the constraint
binds exactly where `max(0, ...)` would.

**Free transfers as decision variables:**

    ft[0] = free_transfers
    ft[t] <= ft[t-1] - spend[t-1] + hits[t-1] + 1
    ft[t] <= 5,  ft[t] >= 0

The `hits[t-1]` term handles the `max(0, ...)`: when h hits are taken,
`used = ft + h` at the optimum, so the expression collapses to exactly 0 and the
manager correctly gets one back from zero rather than a negative balance.

**Time decay:** future gameweeks contribute `decay^t` of their predicted points.

**Rolling horizon:** plan H gameweeks, execute only the first, re-solve next week.

---

## 3. Bugs found (six, all real)

### 3.1 Float equality in `get_team` — CBC was hiding it

`get_team` compared solver output with `== 1`. CBC returns a clean `1.0`; HiGHS
returns `0.9999999997`. Squads silently came back with 12 or 14 players.

Caught by the property tests the moment the solver changed. Hand-written tests with
fixed inputs would never have found it. Fixed with `_is_set()`, thresholding at 0.5.

**This is the strongest argument for property testing in the project so far.** The
bug had been latent through every squad ever built.

### 3.2 Hard-coded £100m budget

`optimize_squad` enforced the full starting budget on every solve, so mid-season it
selected squads the manager could not afford. Surfaced as
`transfer unaffordable: bank 10 + 50 - 63 = -3` at GW8. Fixed with a `budget`
parameter defaulting to `BUDGET`.

### 3.3 Blank gameweek at GW31

Five squad players had no data row at all (no fixture) — the only dip in a pool
otherwise growing 690 → 841 rows. The MIP cannot lock a player who is not a row, so
every option came back infeasible. Fixed by injecting blanked owned players at
`e_points = 0` with their sell price.

### 3.4 Sequential transfers failing on affordable sets

The MIP reasons about a whole set of transfers; `make_transfer` executed them one at
a time. Selling a £6.5m to buy a £14m fails alone even when a second transfer in the
same move frees the cash. Fixed with `SquadState.make_transfers()`, atomic and
money-pooling.

### 3.5 Free transfers as a self-fulfilling projection

`_project_free_transfers` guessed a transfer count, then computed available free
transfers from that guess — a fixed point. Given 5 free transfers the solver made
exactly 5 transfers a week, forever; banking was impossible. Fixed by making `ft` a
decision variable (§2).

### 3.6 Batch-dependent bonus normalisation

    a["exp_bonus"] *= bonus_mean / a["exp_bonus"].mean()

The mean was taken across the whole assembled frame. Under the rolling harness that
frame is six gameweeks, so gameweek k's prediction depended on which of k+1..k+5
happened to be computed alongside it. Observed as a ~0.03 point shift.

Fixed by normalising **per gameweek**. This is the more correct normalisation on its
own terms, not merely the more convenient one: bonus points are a fixed per-match
quantity (3, 2, 1 per fixture), so their mean is a per-gameweek property.

### 3.7 Odds boundary on the wrong kickoff

`odds_available_until` used `gw_start` (FIRST kickoff of the gameweek), so "odds
through GW12" excluded every Saturday, Sunday and Monday fixture of GW12 — roughly
nine of ten matches. Fixed to use `gw_end` (last kickoff).

**Verification that both 3.6 and 3.7 were fixed:** the step-0 diff between the odds
and DC-only prediction files went to exactly `0.0000`, as it must, since both use
odds for the gameweek being played.

---

## 4. The horizon leak, and how it was closed

The MIP plans H gameweeks ahead and needs predictions for all of them. Reading them
from `walkforward_2526.parquet` looks harmless but is not: gameweek k+3's row there
was produced with cutoff k+3, so its rolling features were built from gameweeks k+1
and k+2 — matches not yet played when the planner stands at k.

**Measured cost of the leak:** on an 8-gameweek test, the MIP scored 452 with leaky
data and **393** with honest data. Roughly **45% of the apparent gain was the leak**.

**The fix is feature freezing.** At cutoff k the components run once, for gameweek k,
and that prediction is carried forward across the horizon. This is not a shortcut
around the leak; it is the honest answer to "what does the manager know about
gameweek k+3 right now?" — current form, projected forward. Conservative by
construction: it cannot invent knowledge, only fail to anticipate change.

Fixtures still vary per gameweek (opponents are published a season ahead).

### 4.1 Prediction decay by horizon step

Full season, 165,401 rows across 38 cutoffs:

| Step | N | Spearman | MAE |
|---|---:|---:|---:|
| 0 | 29,338 | 0.715 | 1.15 |
| 1 | 28,088 | 0.682 | 1.20 |
| 2 | 27,249 | 0.661 | 1.23 |
| 3 | 26,449 | 0.641 | 1.27 |
| 4 | 25,579 | 0.629 | 1.28 |
| 5 | 24,997 | 0.617 | 1.30 |

Step 0 reproduces the strict harness **exactly** (0.715 / 1.15 / 29,338 rows, and
all three band slices match), confirming the horizon extension did not disturb the
baseline.

### 4.2 The band decay table — the finding that reframed everything

All-rows decay looked gentle (86% retained over five steps), which initially seemed
to justify long horizons. Splitting by minutes band killed that reading:

| Step | All rows | Played (>0) | **Started (60+)** |
|---|---:|---:|---:|
| 0 | 0.715 | 0.337 | **0.099** |
| 1 | 0.682 | 0.294 | 0.087 |
| 2 | 0.661 | 0.276 | 0.097 |
| 3 | 0.641 | 0.249 | 0.080 |
| 4 | 0.629 | 0.236 | 0.076 |
| 5 | 0.617 | 0.221 | **0.068** |

**The headline number is the least informative one.** All-rows Spearman holds up
because it is mostly separating "plays" from "does not play", which stays
predictable for weeks. That is not the decision being made.

Among STARTED players — the only kind a squad contains — the signal is near noise at
EVERY horizon: 0.099 at step 0, 0.068 at step 5. Consistent with the LightGBM
benchmark and every other model tested, all landing at ~0.10.

**Consequence:** the horizon cannot be buying better player-ranking. If it earns
anything it earns it through fixture difficulty (stable, knowable weeks ahead) and
through banking transfers rather than spending every week. Different mechanism than
"predict further ahead", and worth knowing which one is operating.

---

## 5. Sweeps

### 5.1 Horizon sweep (decay 0.85, pre-bugfix data)

| Policy | H | Total | Margin | 95% CI | Trf | Hits | Min |
|---|---:|---:|---:|---|---:|---:|---:|
| single | 1 | 1889 | +521 | [+343, +708] | 37 | 0 | 4.1 |
| mip | 1 | 1836 | +468 | [+274, +654] | 42 | 16 | 0.3 |
| mip | 2 | 1996 | +628 | [+473, +783] | 46 | 32 | 1.1 |
| mip | 3 | 1999 | +631 | [+484, +774] | 54 | 64 | 2.2 |
| mip | 4 | 1949 | +581 | [+416, +737] | 54 | 64 | 3.7 |
| mip | 6 | 1939 | +571 | [+399, +740] | 57 | 76 | 11.1 |

**MIP H=1 is WORSE than the v1 search** (1836 vs 1889). With no future visibility,
taking hits is just burning points. The gain comes from planning, not from the
formulation.

### 5.2 Methodological error worth recording

The horizon sweep was run at decay 0.85, concluded H=2-3, and the decay sweep then
explored only H=2 and H=3. **Step 2 only searched where step 1 pointed, but step 1
used a decay that specifically penalises long horizons.** Classic local optimum.

Re-testing H=4,5,6 at low decay showed H=4, H=5 and H=6 producing *identical*
results (2078, 45 transfers, 28 hit points) — at decay 0.3 a gameweek four steps out
is weighted 0.008 and changes no decisions. The horizon saturates rather than
degrading.

### 5.3 Full grid, corrected data (18 configs per variant)

Baseline in both: **set-and-forget 1368**, identical, confirming the two variants
share a GW1 squad.

**Odds variant** (`ODDS_HORIZON_GWS = 2`):

| H \ decay | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.85 |
|---|---:|---:|---:|---:|---:|---:|
| 2 | 1974 | 1974 | 1936 | 1967 | 1996 | 1996 |
| 3 | 2023 | 2077 | **2097** | 1915 | 1969 | 1968 |
| 4 | 1983 | 1978 | 1984 | 1937 | 1999 | 1922 |

**DC-only variant** (`ODDS_HORIZON_GWS = 0`):

| H \ decay | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.85 |
|---|---:|---:|---:|---:|---:|---:|
| 2 | 1898 | 1889 | 1908 | 1912 | 1851 | 1924 |
| 3 | 1973 | 1880 | 1887 | 1955 | 1942 | 1935 |
| 4 | 1901 | 1891 | 1893 | **1989** | 1930 | 1903 |

---

## 6. What the sweeps actually establish

### 6.1 Odds are worth roughly 70 points — this one is solid

**Odds wins 16 of 18 paired configs** (only H3/0.6 and H4/0.6 go the other way).
A sign test on 16/18 gives p ≈ 0.0007.

Mean across all configs: odds **1983**, DC-only **1915** — a gap of **~69 points**.
That is a better estimate than the 110-point gap at the respective argmaxes, which
compares two separately-cherry-picked cells.

### 6.2 The parameter grid is noisy — do NOT read the argmax

H=3 goes 2097 at decay 0.5 and 1915 at decay 0.6. A 182-point swing from a small
parameter change is noise, not signal. Confidence intervals are ±200 and overlap
almost completely across the whole grid.

**Honest best estimate of the model's season total: 1980-2000, not 2097.**

### 6.3 The clean decay trend did not survive the bugfixes

On pre-bugfix data, mean total by decay ran 2004 / 1999 / 1998 / 1948 / 1910 —
monotone, with hits rising 22 → 50. It looked like a mechanism.

On corrected data the odds-variant means are 1993 / 2010 / 2006 / 1940 / 1988 / 1962.
No monotone trend. **The earlier "lower decay is clearly better" finding was largely
an artifact of bugs 3.6 and 3.7.**

Worth recording as a caution: a clean monotone pattern across a parameter sweep felt
like strong evidence, and it evaporated once two unrelated bugs were fixed.

---

## 7. Current state

- **Best honest configuration:** MIP, H=3, decay 0.4-0.5, odds available 2 gameweeks
  ahead. Around 2000-2100 points, versus 1368 set-and-forget.
- **v1 reference:** single-transfer policy, 1889.
- **Hindsight ceiling:** 2554 (unchanged, cannot be reached).
- Solve time: ~2.5 min per season at H=3, ~4 min at H=4.

---

## 8. Open problems

### 8.1 `ODDS_HORIZON_GWS = 2` is optimistic for production

The FPL deadline is typically Friday ~11am. At that moment the current gameweek is
certainly priced and the next one usually is, but **two gameweeks ahead is doubtful**
and will not reflect team news. Realistic production is probably 1.

The two grids bracket the truth: odds (optimistic) and DC-only (pessimistic).
Production likely sits between. A third harness at `ODDS_HORIZON_GWS = 1` would
locate it.

### 8.2 Dixon-Coles fallback costs ~70 points

Established in §6.1. Before building anything new, check whether DC's lambdas are
simply MISCALIBRATED against market-implied ones — a regression of one on the other
is 20 minutes and might reveal a constant offset that a scalar correction fixes.

Note `LAM_BLEND_W = 0.0` was tuned when odds were always available. It has never
been tuned for the fallback case, so pure DC may just need recalibrating rather than
replacing.

### 8.3 Everything before §5.3 used buggy data

The horizon sweep (§5.1) and the first decay sweeps ran before bugs 3.6 and 3.7 were
fixed. Their conclusions about H and decay should be treated as superseded by §5.3.
The 2078 figure in particular does not survive.