# FPL Copilot — Handoff, 2026-08-14

**Covers:** the EV-surface measurement attempt (failed), the double-gameweek fix, the
baseline migration, the odds decision, the multi-season port (M2), the pairwise
margin calibration finding, and the hit-threshold grid (negative).

**Next task: D1 — complete the master equation.** Full spec in §9. Read §§1–3 and
§7 before touching anything.

---

## 0. TL;DR — where the project actually is

The optimiser is not the constraint and never was. The predictions are, and this
session established two things about them that change what to do next:

1. **The master equation is INCOMPLETE.** It scores six terms and FPL scores
   eleven. Saves, goals conceded, cards, own goals, penalties missed and penalties
   saved are simply absent, and penalty share is missing from E[goals]. This is now
   the highest-value cheap work and it is D1.
2. **Season totals are not a ruler, and the two proposed replacements did not
   rescue that.** The EV-surface approach failed its gate; the control-variate
   fallback is unresolved and probably not worth the compute. Grade component
   metrics and per-decision endpoints instead.

Everything below is written so you do not re-derive any of it.

---

## 1. Working style (unchanged, and it matters)

The user is a non-technical learner building this solo. From every prior handoff,
still true:

- **SHORT responses.** Break long work into small turns. Never a wall of text.
- **Concept first, in plain language, before any code.**
- **One small step at a time**, then wait.
- **Verify every output before proceeding.** Never assume a step worked.
- **Honesty over cheerleading.** Say plainly when something is a hack, a dead end,
  or a weak result. The user values this explicitly and has repeatedly rewarded it.
- The user asks good challenging questions. When they push back, **CHECK rather
  than defend** — several real findings this session came from exactly that.

**New this session, and important:** the user is now running an explicit
report-before-you-commit discipline on data decisions. Crosswalk mappings were
proposed for confirmation before being written, twice. Keep doing that for anything
that changes a data artefact.

---

## 2. Environment

- OS Windows, PowerShell. Repo root: `C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot`
- `uv` for packages. Run: `uv run python <script>.py`, or directly
  `.venv/Scripts/python.exe <script>.py`
- **Encoding trap:** player names contain non-cp1252 characters. Prefix long-running
  prints with `PYTHONIOENCODING=utf-8` or you get `UnicodeEncodeError` mid-run.
- pandas pinned <3, pyarrow <25 (MLflow compatibility). Do not upgrade blind.
- Tests: `.venv/Scripts/python.exe -m pytest Tests/ -q` — **109 passing** as of this
  handoff.

---

## 3. THE MEASUREMENT SITUATION — read this before proposing any experiment

This is the single most important context in the project.

### 3.1 Season totals cannot distinguish prediction quality

Established previously by falsification (`Logs/instrument_b_log.md`): path noise
sd = 60.0, and a model shrunk 75% toward the positional mean scores
indistinguishably from the full model. **Any argument of the form "config X scored
N points more" is not evidence.**

### 3.2 The EV surface — built, gated, FAILED (M1)

`eval/ev_surface.py` scores each player-fixture by expected value instead of
realised points: realised minutes and fixture kept, everything volatile replaced by
smoothed expectations. It is well built and well calibrated (mean EV 1.1469 vs
realised 1.1558; variance among starters cut to 0.256 of realised).

**It failed the gate.** `eval/validate_ev_surface.py` ran two degradation ladders:

- λ-shrinkage (0/0.25/0.5/0.75): EV did NOT separate, non-monotone.
- rank-scramble, mild (0.05/0.10/0.15/0.20): realised points detected damage at
  rung 0.15 where EV did not.

**There is no rung on either ladder where EV resolves damage that realised misses.**
Mechanism: EV halved the noise but halved the signal with it. A useful fact
uncovered on the way — **λ-shrinkage preserves within-position ranking EXACTLY
(Spearman 1.000000)**, so the λ ladder was never a ranking test; it is a
magnitude/spread test. The claim in `instrument_b_log.md` that λ=0.75 is "a
within-position random picker" is factually wrong.

### 3.3 The control-variate fallback — UNRESOLVED, and probably not worth it

`eval/analyse_control_variate.py`. Two estimates straddle the 50% threshold (20.3%
closed-form, 54.2% on a proxy path) and neither is trustworthy — the closed form
relies on `realised = EV + independent noise`, which is measurably false
(sd(d_EV) exceeds sd(d_real) in 3 of 7 arms, impossible under that model).

**Two things ARE established regardless:** a control variate cannot change any point
estimate (the correction sums to zero), so it cannot fix non-monotonicity or
wrong-signed results; and its total value across the whole ladder is at most **one
marginal significance call**. Deciding it properly needs the per-gameweek series the
M1 run discarded — one line to persist, plus a ~50-minute deterministic re-run.

### 3.4 What TO grade on

- **Component metrics** (P(start) AUC/Brier, E[min] MAE, assembly Spearman/MAE at
  horizon 0, three-band slice). Path-free. This is how availability was adopted.
- **Per-decision endpoints** (predicted vs realised gain per transfer, distributions
  not means, opportunity cost of blocked decisions). This is how the hit threshold
  was graded.
- **Pairwise margin calibration** (`Logs/margin_calibration_log.md`).

---

## 4. Code changes this session — file by file

### 4.1 `squad/assembly.py` — MAJOR rewrite to per-fixture grain

The master equation now runs once per **player-FIXTURE** and sums to
`(element, gw)`. Return grain is unchanged, so the optimiser and simulator are
unaffected.

New/changed functions:

```
build_predictions(log_mlflow=False, availability=None)
    -> collapse_to_gameweek(build_fixture_predictions(...))   # per (element, gw)

build_fixture_predictions(log_mlflow=False, availability=None)
    runs the five components, then calls assemble_fixtures()

assemble_fixtures(df, cw, mins_out, rates, priors, fixtures, dc_out,
                  bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean,
                  gws=None, season="2025-26", dc_enabled=True)
    THE SINGLE SOURCE OF TRUTH FOR THE EQUATION. Components supplied by caller.

_finish_equation(asm, bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean,
                 n_exact_dupes=0)
    the equation itself (steps 6-7). THIS IS WHERE D1 ADDS TERMS.

collapse_to_gameweek(af)
    per-fixture -> per (element, gw). SUM_COLS sum, MEAN_COLS average.
```

Module constants you will need for D1:

```python
FIXTURE_KEY = ["element", "gw", "fixture"]
SUM_COLS  = [...additive terms...]     # ADD NEW POINT TERMS HERE
MEAN_COLS = [...rates/probabilities...] # ADD NEW RATES HERE
GOAL_PTS = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}
CS_PTS   = {"FWD": 0, "MID": 1, "DEF": 4, "GK": 4}
DC_BASE  = {"DEF": 0.125, "MID": 0.136, "FWD": 0.058, "GK": 0.0}
LEAGUE_AVG_LAMBDA = 1.40
```

**Three DGW defects closed by the grain change** (all under-counted doubles):
1. `minutes_frac = (e_minutes/90).clip(0,1)` capped the whole gameweek at one fixture.
2. The Dixon-Coles join used `drop_duplicates(["team","gw"])`, silently keeping an
   arbitrary fixture. Now joins on `(team, match_date)` — a team cannot play twice
   in a day.
3. The DC join took the MAX of two per-match probabilities. Now assigned per fixture
   by `fix_rank` (kickoff order), with the player's own gw-mean as fallback before
   the position base rate.

Appearance points fall out for free: two fixtures now yield up to 4.

**Guard added** (learn from this, it cost a full rebuild):

```python
matched_frac = asm["team_lambda"].notna().mean()
if matched_frac < 0.90:
    raise AssertionError(...)
```
A fixture join that matches nothing is otherwise SILENT: team_lambda goes NaN →
pts_cs NaN → e_points NaN → and `collapse_to_gameweek`'s groupby-sum turns a column
of NaN into a clean `0.0`. A whole season scored zero with no error.

**Exact-duplicate rows:** elements 100 and 391 carry byte-identical rows repeating
the SAME fixture id. Deduplicated via `drop_duplicates(FIXTURE_KEY)`, never summed.
These are NOT doubles (doubles have distinct fixture ids).

### 4.2 `squad/minutes.py`

```python
get_minutes(up_to_gw=None, predict_gws=None, log_mlflow=False, availability=None,
            per_fixture=False, train_seasons=None, predict_season=None)
```

- `per_fixture=True` forces `is_double_gw = 0` at PREDICT time. Nothing retrained.
  Rationale: the two minutes regressors are fitted on `minutes_capped`, and the DGW
  collapse SUMS minutes before capping at 90 — so a 90+90 player carries target 90,
  identical to a single-90 player, while a 90+45 player also carries 90 against a
  true per-match average of 67.5. The target overstates per-match minutes on double
  rows, and `is_double_gw` lets the model act on it. Left uncorrected, applying the
  inflated figure to both fixtures lands at ~2.2x instead of ~2.0x.
  **Single-gameweek rows already carry 0, so they are bit-identical either way.**
- `train_seasons` / `predict_season` for the multi-season port. Defaults reproduce
  2025-26 exactly.

### 4.3 `squad/attacking_rates.py`

`PRIOR_SEASONS` now covers every season. Each season is predicted from the THREE
Understat seasons before it, never its own (the leak fixed in LEAKAGE.md #4):

```python
"2021-22": ["2018","2019","2020"],  "2022-23": ["2019","2020","2021"],
"2023-24": ["2020","2021","2022"],  "2024-25": ["2021","2022","2023"],
"2025-26": ["2022","2023","2024"],
```

### 4.4 `squad/dixon_coles.py`

```python
get_fixtures(predict_season=None, cutoff_date=None, predict_dates=None,
             odds_available_until=None, ...)
```
**Trap I hit and you should not repeat:** I first added the parameter to the
signature and never used it in the body. It silently returned 2025-26 fixtures for a
2023-24 request, every fixture-dependent term went NaN, and the groupby-sum turned
that into 0.0. A parameter that is accepted and ignored is worse than no parameter.
It is now threaded through all four internal uses.

### 4.5 `squad/bonus.py`

```python
get_bonus_model(up_to_gw=None, log_mlflow=False, train_until=None,
                predict_season=None)
```

### 4.6 `squad/transfer_mip.py`

```python
HIT_COST = 4          # FPL's actual charge. A game rule; never change.
build_and_solve(..., hit_bar=None)   # decision bar, defaults to HIT_COST
    obj.append(-d * hit_bar * hits[t])
```
Raising `hit_bar` does not change what a hit costs when scored — it raises the
predicted gain the solver demands. Gameweek-level, not a per-transfer filter.

### 4.7 `squad/simulator.py`

```python
load_season(walkforward_path=None, history_path=HISTORY_PATH,
            horizon_aware=False, season=None)
simulate_season(..., hit_bar=None)
decide_gameweek_mip(..., hit_bar=None)
```

### 4.8 `eval/walkforward.py` — duplicate equation DELETED

It carried its own copy of the master equation (~lines 115–210) so the harness could
supply per-cutoff components. **The two copies drifted, and that is exactly how the
three DGW defects survived being fixed in `assembly.py` — the second copy produced
the file the simulator reads.** It now calls:

```python
a_k = assembly.collapse_to_gameweek(
    assembly.assemble_fixtures(df, cw, m_k, rates, priors, f_k, dc_k,
                               bps_model, bps_to_bonus, BPS_FEATURES,
                               bonus_mean, gws=targets))
```

Constants now pinned, not inherited:
```python
ODDS_HORIZON_GWS = 0   # FIXED PROJECT DECISION. Not a tunable. Do not sweep.
AVAILABILITY = True    # the M3 baseline migration
```
Provenance stamped on every row: `minutes_availability`, `odds_horizon_gws`,
`dgw_handling`.

### 4.9 `eval/build_crosswalk.py` — NEW

Per-season vaastav `element` ↔ Understat `id` crosswalk. Understat ids are stable;
vaastav's reshuffle every summer (KNOWN_ISSUES #6).

Passes, in order: exact normalised name → fuzzy `token_set_ratio` (floor 88, margin
4) → `fuzzy+club` → `club+token` (a token that identifies exactly ONE club-mate) →
`MANUAL` hand-resolved overrides.

Key components:
```python
CLUB_ALIASES = {...}   # explicit. Fuzzy club matching FAILS SILENTLY.
MANUAL = {"2023-24": {element: (understat_id, evidence)}, "2024-25": {...}}
_team_map(...)         # RAISES if any club is unmapped
_audit(...)            # post-build profile agreement check
```

### 4.10 `eval/walkforward_season.py` — NEW

Walk-forward harness for a season other than 2025-26. Reuses `assemble_fixtures`
unchanged. Handles era-correctness (`dc_enabled`), training-season selection, and
provenance stamping. Raises for a season with no prior labelled season.

### 4.11 `Tests/test_walkforward_provenance.py` — rewritten

Now defends the POST-migration file. New tests: provenance stamps present and
correct, fingerprint (Spearman 0.745 / MAE 1.109), **doubles are counted (409 at
horizon 0)**, pre-migration file preserved and still reproduces its own fingerprint,
and **`test_equation_exists_in_exactly_one_place`** which scans `squad/` and `eval/`
for `a["pts_appear"] =` and fails if a second copy reappears.

---

## 5. Data artefacts and provenance

| file | what it is |
|---|---|
| `data/walkforward_h6_2526.parquet` | **CANONICAL 2025-26.** availability=True, odds=0, per_fixture, corrected crosswalk |
| `data/walkforward_h6_2526_prefix.parquet` | pre-migration, preserved. Reproduces season total **1984** exactly |
| `data/walkforward_h6_2526_dgwonly.parquet` | control arm: new equation, availability OFF |
| `data/walkforward_h6_2023_24.parquet` | 2023-24, DC rule off |
| `data/walkforward_h6_2024_25.parquet` | 2024-25, DC rule off |
| `data/history/crosswalk_2023_24.csv` | 569 rows, 100% minutes coverage |
| `data/history/crosswalk_2024_25.csv` | 561 rows, 100% minutes coverage |
| `data/history/player_id_crosswalk_final.csv` | 2025-26, **element 511 corrected** |
| `data/walkforward_h6_2526_av.parquet`, `_odds2.parquet` | STALE (old equation). Candidates for deletion |

**Baseline note:** the canonical season total after migration was **1940** on the
pre-crosswalk-correction file. It was NOT re-run after the element-511 correction,
because that player was never selected — any movement would be a branch artefact.
**Do not compare 1940 with 1984.** Different provenance.

---

## 6. Findings this session

### 6.1 Pairwise margin calibration — `Logs/margin_calibration_log.md`

Through-origin β of realised margin on predicted margin, within (gameweek, position):

| season | all rows s0 | started s0 | all rows H3 | started H3 decayed |
|---|---|---|---|---|
| 2023-24 | 0.929 | 0.585 | 0.907 | 0.540 |
| 2024-25 | 0.950 | 0.671 | 0.916 | 0.662 |
| 2025-26 | 0.958 | 0.418 | 0.929 | 0.389 |

Replicates: all-rows near-calibrated, collapse once both players start. Does NOT
replicate: magnitude, and position ordering (GK worst in 2023-24, MID worst in
2025-26 — which weakens the "missing GK/DEF terms cause it" story, though D1 may
still help). Implied hit bar 6–10, **not adopted**.

### 6.2 Hit threshold grid — `Logs/hit_threshold_log.md` — NEGATIVE

τ ∈ {4,6,7,8,9,10} × 3 seasons. **Decision: threshold stays at 4.** The blocked
transfers were mostly good — never below 50% positive across fifteen cells; 2023-24
at τ=6 blocked 23 transfers with median +6.0 and 61% beating the charge. Survivor
metrics improve at higher τ but that is selection, not evidence. Do not re-run
without a new endpoint idea.

### 6.3 M2 multi-season port

**Portable set is THREE seasons: 2023-24, 2024-25, 2025-26.** 2021-22 and 2022-23
are not portable — `starts` (the P(start) target) does not exist before 2022-23.
KNOWN_ISSUES #11 records the decision and the reason.

Component metrics:

| season | train | P(start) AUC | Brier | E[min] MAE | assembly ρ (h0) | started ρ |
|---|---|---|---|---|---|---|
| 2023-24 | 2022-23 | 0.9601 | 0.0707 | 11.44 | 0.6641 | 0.1950 |
| 2024-25 | 2022-23,2023-24 | 0.9533 | 0.0792 | 12.44 | 0.7321 | 0.1698 |
| 2025-26 | 2022-23,2023-24,2024-25 | 0.9605 | 0.0712 | 11.27 | 0.7449 | 0.1178 |

### 6.4 Crosswalk one-to-one wrong matches — KNOWN_ISSUES #12

Two instances, both found by accident. The 2025-26 canonical file had element 511
(a Forest centre-back) mapped to Jota Silva, giving him a winger's attacking rate
(npxG/90 0.3085 vs 0.0110 correct). Corrected to 13068 (Morato). Never selected, so
the realised path was unaffected. A post-build audit now guards this.

---

## 7. Traps — do not re-trip these

1. **A parameter added to a signature but not used in the body.** Cost a full
   rebuild (dixon_coles). Always verify the parameter changes the output.
2. **groupby-sum turns all-NaN into 0.0.** A broken join produces a structurally
   perfect file full of zeros. Guard coverage explicitly.
3. **`np.allclose` with NaN is False regardless of correctness.** Use `equal_nan=True`.
4. **Understat numerics are STRINGS** (KNOWN_ISSUES #2). `pd.to_numeric` on every
   load, including `id` comparisons — `us.id == 2496` fails silently.
5. **`d.flags` collides with a pandas DataFrame attribute.** Use `d["flags"]`.
6. **Fuzzy CLUB matching fails silently** — "Spurs" vs "Tottenham" scores ~0. Use
   explicit aliases with an assertion.
7. **Regenerating an artefact inherits today's defaults.** KNOWN_ISSUES #10. Always
   pin provenance explicitly and stamp it into the file.
8. **`itertuples` renames columns that are Python keywords or contain symbols**
   (`in`, `B365>2.5`). Rename before iterating.
9. **Season totals are not evidence.** See §3.

---

## 8. Master equation as it stands (what D1 changes)

In `assembly._finish_equation`:

```python
a["minutes_frac"]  = (a["e_minutes"] / 90.0).clip(0, 1)      # PER FIXTURE now
a["fixture_scale"] = (a["team_lambda"] / 1.40).fillna(1.0).clip(0.5, 2.0)
a["e_goals"]       = a["npxg90"] * a["minutes_frac"] * a["fixture_scale"]
a["e_assists"]     = a["xa90"]   * a["minutes_frac"] * a["fixture_scale"]
a["pts_goals"]     = a["e_goals"]   * a["position"].map(GOAL_PTS)
a["pts_assists"]   = a["e_assists"] * 3
a["p_60plus"]      = a["p_start"] * a["p60"]
a["p_play_any"]    = a["p_start"] + (1 - a["p_start"]) * 0.30
a["pts_appear"]    = a["p_60plus"]*2 + (a["p_play_any"] - a["p_60plus"]).clip(lower=0)*1
a["pts_cs"]        = a["p_cs"] * a["position"].map(CS_PTS) * a["p_60plus"]
a["pts_dc"]        = a["p_dc_hit"] * 2 * a["minutes_frac"]
a["e_points_core"] = pts_appear + pts_goals + pts_assists + pts_cs + pts_dc
# then bonus, then e_points = e_points_core + exp_bonus
```

**Governing principle, do not violate it:** *you only earn points for what happens
on the pitch.* Every performance term is scaled by expected playing time. This fix
(assembly log §5) is what took the model from ~2x over-prediction to calibrated.

---

## 9. NEXT TASK — D1: complete the master equation

### 9.1 What is missing

FPL scores eleven things. The equation scores six. Missing entirely:

| term | rule | notes |
|---|---|---|
| **saves** | +1 per 3 saves | GK only. A busy keeper earns ~1–1.3/match — currently invisible, so the model cannot see budget-keeper value |
| **goals conceded** | −1 per 2 conceded | GK/DEF only. ~−0.7 vs a strong opponent |
| **yellow cards** | −1 each | |
| **red cards** | −3 each | |
| **own goals** | −2 each | rare |
| **penalties missed** | −2 each | rare |
| **penalties saved** | +5 each | GK only, rare |
| **penalty share in E[goals]** | — | `npxg90` is NON-penalty xG. Penalty takers are exactly the premium captain candidates and their pens are currently unmodelled. Master plan §3.4 specified `+ penalty share × team pen rate`; never wired |

### 9.2 The scoring constants are VERIFIED, not assumed

Empirically reconciled this session by reconstructing `total_points` from components:

- **2025-26 (DC rule ON): 29,757 / 29,757 exact (100%)**
- **2023-24 (DC rule OFF): 29,725 / 29,725 exact (100%)**
- **2024-25 (DC rule OFF): 27,283 / 27,283 exact (100%)**

Falsification confirmed every constant is load-bearing (perturbing any one breaks
rows), with two exceptions untestable from this data: GK goal points (no keeper
scored) and GK DC ineligibility (no GK row has DC ≥ 10).

Verified formula:
```python
appearance = 2 if minutes >= 60 else (1 if minutes > 0 else 0)
goals      = goals_scored * {GK:6, DEF:6, MID:5, FWD:4}
assists    = assists * 3
clean_sheet= clean_sheets * {GK:4, DEF:4, MID:1, FWD:0}   # 60-min rule already in the column
saves      = saves // 3
conceded   = -(goals_conceded // 2)   if position in (GK, DEF) else 0
cards      = -1*yellow_cards - 3*red_cards
own_goals  = -2 * own_goals
pens       = -2*penalties_missed + 5*penalties_saved
dc         = 2 if (DEF and dc >= 10) or (MID/FWD and dc >= 12) else 0   # 2025-26 ONLY
```

### 9.3 Suggested approach per term

**Goals conceded — easiest and already in the frame.** `opp_lambda` is the market's
expected goals against that team in that fixture and is already joined per fixture.

    E[conceded] = opp_lambda * minutes_frac
    pts_conceded = -E[floor(C/2)],  C ~ Poisson(E[conceded]),  GK/DEF only

**Use the expectation OF the floor, not the floor of the expectation** — I hit this
in `ev_surface.py` and it was worth ~1,250 points of level error there. Helper
exists in `eval/ev_surface.py::_expected_floor_div` (do not import it into
`squad/` — that file is evaluation-only; copy the six lines).

**Saves.** GK only. Rolling saves-per-90 from vaastav (`saves` column, complete in
all ten seasons), shrunk, × `minutes_frac`, then `E[floor(S/3)]`. A better version
conditions on `opp_lambda` (more shots faced → more saves) — worth testing, since a
keeper at a weak team facing many shots is exactly the budget-keeper value the model
currently cannot see.

**Cards.** Rolling yellow/red per 90, heavily shrunk (rare events), × `minutes_frac`.
Small but nearly free.

**Own goals / pens missed / pens saved.** Tiny. Heavy shrinkage toward a position
base rate is fine. Include for completeness rather than accuracy.

**Penalty share.** Understat gives `goals - npg` = penalty goals historically, per
player per season, already on disk in `understat_season_aggregates.parquet`.
Core-Insights has `penalties_order` but 2025-26 only, so for multi-season work
derive share from historical penalty goals. Then:

    E[goals] = npxg90 * minutes_frac * fixture_scale
             + pen_share * team_pen_rate * minutes_frac

### 9.4 Where the code goes

All of it in `assembly._finish_equation`, at per-fixture grain, **every term gated by
`minutes_frac` or `p_60plus`**. Then:

1. Add each new point column to `SUM_COLS`.
2. Add each new rate/probability to `MEAN_COLS`.
3. Add to `e_points_core`.
4. Add to `PRED_COLS` in `__main__` if you want it persisted.

**Also fix the bonus input while you are there.** `bps_input` currently hard-codes
zeros:
```python
"saves": 0, "yellow_cards": 0, "red_cards": 0,
"goals_conceded": 0, "penalties_missed": 0, "own_goals": 0
```
The BPS model was TRAINED on those features with real values, so feeding zeros
systematically distorts predicted BPS — most for keepers and defenders. Once the new
terms exist, feed the expectations in.

### 9.5 How to measure it — NOT with season totals

- **Primary:** assembly Spearman/MAE at horizon 0, and the three-band slice,
  **computed WITHIN position groups** — specifically within GK and within DEF, where
  saves and conceded bite. The aggregate will barely move and that is expected;
  do not read the aggregate as a null result.
- **Calibration by minutes band** (the `_calibration_table` already in assembly).
  Adding negative terms will lower predictions; check the 70+ band.
- **Pairwise margin β within GK and within DEF** — reuse the method in
  `Logs/margin_calibration_log.md`. If the missing-terms hypothesis is right, GK/DEF
  β should rise. **This is the cleanest test of whether D1 worked.**
- **All three seasons.** The portable set exists now; use it.
- Do NOT run a season simulation to justify D1.

### 9.6 Cautions

- 2025-26 is the sealed test season. Anything tunable is tuned on 2023-24 / 2024-25.
- Regenerating `walkforward_h6_2526.parquet` moves the baseline again. Expect the
  provenance test to fail and update its fingerprint deliberately.
- Era-correctness: saves/conceded/cards/pens exist in ALL ten seasons (verified,
  100% non-null). Only DC is 2025-26-only. So D1 applies uniformly across the
  portable set.
- Single-gameweek predictions will change — that is the point. Do not expect
  bit-exactness this time; expect the GK/DEF calibration to improve.

---

## 10. Resume checklist

```bash
cd "C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
.venv/Scripts/python.exe -m pytest Tests/ -q          # expect 109 passed
.venv/Scripts/python.exe -c "import pandas as pd; d=pd.read_parquet('data/walkforward_h6_2526.parquet'); print(d[['minutes_availability','odds_horizon_gws','dgw_handling']].drop_duplicates())"
```
Expect `True / 0 / per_fixture`.

Read, in order: this handoff §§3, 7, 9 → `Logs/margin_calibration_log.md` →
`Logs/hit_threshold_log.md` → `KNOWN_ISSUES.md` #10, #11, #12 → then start D1.
