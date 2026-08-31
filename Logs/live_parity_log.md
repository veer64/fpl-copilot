# Live deadline path — parity harness (2026-08-31)

Precondition for any 2026-27 live build: prove a live path produces **bit-identical** output to the
canonical backtest path on completed 2025-26 gameweeks. `squad/live_deadline.py`;
`Tests/test_live_deadline.py`. No modelling code was changed.

## 1. The seam

"Assemble inputs" ends and "compute the frame" begins inside `walk_forward`'s per-cutoff loop body
(`eval/walkforward_season.py:119–161`), at six shared calls:

```python
rates, priors = rates_mod.get_rates(season, up_to_gw=k)
m_k = minutes_mod.get_minutes(up_to_gw=k, predict_gws=[k], per_fixture=True,
                              availability=AVAILABILITY, train_seasons=tr, predict_season=season)
bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = bonus_mod.get_bonus_model(
    up_to_gw=k, train_until=tr[-1], predict_season=season)
f_k = dc_mod.get_fixtures(predict_season=season, cutoff_date=cutoff_date,
                          odds_available_until=odds_until)
dc_k = def_mod.get_dc_hits(season, k, targets)
a_k = assembly.collapse_to_gameweek(assembly.assemble_fixtures(
    df, cw, m_k, rates, priors, f_k, dc_k, bps_model, bps_to_bonus,
    BPS_FEATURES, bonus_mean, gws=targets, season=season, dc_enabled=dc_enabled))
```

The live path shares **everything including the loop body**: `build_deadline_frame(season, gw)` calls
`walk_forward(season, cutoffs=[gw], horizon=1)` itself. `horizon=1` makes `targets == [gw]` — exactly
the step-0 slice (the minutes stale-copy loop is a no-op at one target; the bonus normalisation is
per-gameweek; every other input is target-independent). Nothing is reimplemented; the module adds only
read-only pre/post-flight detectors and the parity comparator. That step-0-under-horizon-1 equals
step-0-under-horizon-6 is **proved by the parity test**, not assumed.

## 2. Parity result — PASS

Live build vs `data/walkforward_h6_2025_26.parquet` (rebuilt 2026-08-28 on the fixed crosswalk),
rows aligned on element, all 62 columns compared, numeric bar = max |Δ| exactly 0.0, non-numeric bar =
string equality, NaN placement compared:

| cutoff | rows (live = canonical) | verdict |
|---|---|---|
| GW5 | 741 = 741 | **BIT-IDENTICAL** (46 numeric + 16 non-numeric columns) |
| GW20 | 790 = 790 | **BIT-IDENTICAL** |
| GW33 (double gameweek: 248 doubled step-0 rows; also the BB2 week) | 829 = 829 | **BIT-IDENTICAL** |

No column differed at any magnitude. This also re-confirms the pipeline's determinism (LightGBM fits
included), previously seen in the arms rebuild (107 cutoffs, max |Δe_points| = 0).

## 3. Strict mode

`build_deadline_frame(..., strict=True)` — **live only; backtests keep current behaviour** (the flag
defaults off and nothing in the harness reads it). Every detector below raises `LiveStrictError` under
strict and is reported as a finding otherwise. Detectors are read-only inspections of the input files
and the produced frame; the modelling modules are untouched.

### Full fallback inventory (all found; ⊘ = raised in strict mode, ○ = reported note)

| # | Fallback | Where it hides | Strict |
|---|---|---|---|
| 1 | Availability season/gameweek absent → whole block silently fills UNKNOWN(−1)/0/NaN; `data/live/` is invisible to the model's glob | `availability_features.attach` left-join fills | ⊘ preflight |
| 2 | Season absent from minutes.py's hardcoded `order` ladder (~:90) → `prev_* = 0`, `transfer_status = 2` for the whole league, silently | minutes.py prior-season block | ⊘ preflight (ladder parsed from source, so the check cannot drift) |
| 3 | Season absent from `DC_SEASONS` / `DC_RULE_SEASONS` while the rule is in force (≥ 2025-26) → live scoring term silently zeroed | walkforward_season:101 / defensive:247 | ⊘ preflight |
| 4 | Crosswalk file missing | walkforward_season raises anyway | ⊘ preflight (before the expense) |
| 5 | Crosswalk missing an element that reaches the top 30 by e_points → silent positional-prior rates (the Cherki class, ~+1.3 e_points/row) | assembly:436 fill | ⊘ postflight |
| 6 | `get_minutes` returning an empty frame (silent empty return at minutes:280) | frame row count | ⊘ postflight (< 300 rows) |
| 7 | `team_pen_rate` 0.08 default | assembly fallback | ⊘ postflight (exact: teams absent from the season's vaastav penalty aggregate) |
| 8 | Fixture-join coverage: assembly's own guards allow 10% global / 50% per-team leakage; live demands 100% at the deadline gameweek | null `team_lambda` | ⊘ postflight |
| 9 | Vaastav master missing the season or the gameweek | preflight | ⊘ |
| 10 | `BLEND_PRIOR` unmapped / Understat per-match file missing (prior or current) | attacking_rates raises with a clear message, but only mid-build | ⊘ preflight |
| 11 | Understat aggregates missing the prior year → `penalty_share` silently falls to position means / 0.05 | assembly `_attach_penalty_share` | ⊘ preflight |
| 12 | Fixture unpriced (no B365) → pure-DC lambdas, `lambda_source="dc"` | dixon_coles blend weights | ○ **by design** — correct behaviour, counted, never strict (see §4) |
| 13 | Any element without `understat_id` (beyond the top 30) → positional priors; **GKs receive the DEF prior** | assembly:433 (`pos_lab` maps GK→D) | ○ counted (240/275/294 of 741/790/829 rows on the three cutoffs — overwhelmingly fringe players Understat never saw) |
| 14 | `p_dc_hit` at the DC_BASE position rates (defensive model cold start inside an enabled season) | defensive `_predict_gw` | ○ correct early-season behaviour |
| 15 | `penalty_share == 0.05` conservative fill (gate-off path) | assembly | ○ counted (343–417 rows per cutoff today) |

Fallbacks found beyond the task's list: #9–#11 (hard input absences that raise late or not at all),
#12–#15 (the graceful family), plus two non-fallback defects already on record from the
reconnaissance and NOT fixed here (read-only task): minutes.py logs MLflow params from module
constants rather than the arguments, and `get_fixtures`' empty-season early return omits the
`lambda_source` column that its normal return carries.

## 4. What strict mode cannot catch — legitimately thinner live inputs

These are "less data, same code, correct behaviour" — NOT defects, and strict must not fire on them:

1. **Understat publishes after matches.** At a Friday deadline the per-match file ends at the previous
   gameweek; the k=8 blend's current-season side simply has one week less. The blend weight
   `w = n90/(n90+8)` is continuous — the code path is identical, the estimate honestly wider.
2. **Odds move until kickoff; closing odds do not exist at the deadline.** The backtest's B365 closing
   odds are a post-hoc archive. A live pull captures deadline-time odds — same code
   (`odds_available_until` gates exactly this), slightly different numbers than a retro-build would
   later see. A fixture with no odds at the deadline falls to pure DC, per-fixture, counted (#12).
3. **Availability is as-of by construction.** The live poller's deadline snapshot IS the definition of
   the asof_* columns; fplcache's retro-build may differ only via its own blind window — the D6
   workstream measures precisely this (GW2: 3 status flips caught live that fplcache missed).
4. **Defensive-model and rate cold starts** early in a season: DC_BASE rates and prior-season-weighted
   blends are the designed priors, not substitutions.

By contrast, everything in §3 marked ⊘ is a **wrong value substituted** (zero for a live rule, a flat
0.30-floor unknown for a known injury, a position average for a premium player) — that distinction is
the boundary between strict raises and notes.

## 5. Tests (wired into the suite)

`Tests/test_live_deadline.py` — 7 tests, suite total 172 passed:
- `test_parity_one_cutoff_bit_identical` — builds GW20 through the live path and asserts bit-identity;
  **fails if the live path ever diverges from the harness**;
- comparator self-tests: a 1e-9 perturbation and a dropped row are both detected;
- strict preflight passes for 2025-26 GW20, raises for 2026-27, and reports ≥ 5 findings non-strict;
- the minutes-ladder source parser sees the seasons that are present.

## 6. Boundary of this task

No 2026-27 ingestion was built and nothing was fetched. The parity harness is the gate: any future
live input pipeline must feed the same files the harness reads and keep this test green.
