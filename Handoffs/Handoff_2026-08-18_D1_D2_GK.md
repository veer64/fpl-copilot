# Handoff — 2026-08-18: D1 adopted, D2 adopted, GK investigation open

**Covers:** the D1 scoring-terms work (adopted, closed), the D2 Understat
per-match pull + cross-season rate blend (adopted), two new KNOWN_ISSUES
incidents (#13, #14), and the goalkeeper investigation (still open).

**Read first:** §1 (live config), §2 (what changed in code), §12 (traps).
Everything else is reference.

---

## 1. LIVE CONFIG — what state the code is in right now

Four gates control the equation. All are stamped into every walk-forward
artefact, so code and file can never disagree silently:

| Constant | Location | Value | Meaning |
|---|---|---|---|
| `D1_TERMS_ACTIVE` | `squad/assembly.py:43` | **True** | saves / conceded / cards / penalty-share terms in the equation |
| `CS_UNIFIED` | `squad/assembly.py:57` | **False** | CS from the 0.2-DC-blended `p_cs`, NOT from `exp(-opp_lambda)`. Tested and reverted — see §6 |
| `RATE_BLEND_ACTIVE` | `squad/attacking_rates.py:42` | **True** | k=8 cross-season attacking-rate blend is the production rate source |
| `RATE_BLEND_K` | `squad/attacking_rates.py:43` | **8.0** | blend weight `w = n90/(n90+k)` |

Other settled constants (unchanged this session): `AVAILABILITY=True`,
`ODDS_HORIZON_GWS=0`, `dgw_handling=per_fixture`, `HIT_COST=4`,
`DEFAULT_HORIZON=6`, `DEFAULT_DECAY=0.85`, `LAM_BLEND_W=0.0`,
`CS_BLEND_W=0.2`, `MIN_TIME=450`.

**Canonical files** (`data/walkforward_h6_{2025_26,2024_25,2023_24}.parquet`,
rebuilt 2026-08-18) all carry:
`d1_terms_active=True, cs_unified=False, rate_blend_active=True,
rate_blend_k=8.0, minutes_availability=True, odds_horizon_gws=0,
dgw_handling=per_fixture`. Rows: 165,401 / 152,003 / 162,604.
`dc_rule_active` is True for 2025-26 only (the DC scoring rule is 2025-26+).

**Current component metrics on those files** (step 0; starter band =
`e_minutes >= 60`; β = through-origin pairwise margin slope):

| season | agg ρ | agg MAE | GK ρ/β | DEF ρ/β | MID ρ/β | FWD ρ/β |
|---|---|---|---|---|---|---|
| 2025-26 | 0.7481 | 1.0731 | 0.190 / 0.701 | 0.265 / 1.006 | 0.193 / 0.775 | 0.162 / 0.618 |
| 2024-25 | 0.7375 | 1.0969 | 0.133 / 0.496 | 0.292 / 0.862 | 0.318 / 1.008 | 0.184 / 0.552 |
| 2023-24 | 0.7237 | 1.0673 | 0.190 / 0.640 | 0.327 / 1.012 | 0.335 / 0.909 | 0.199 / 0.434 |

> **STALE-DOC WARNING:** `Logs/d1_log.md` §8 quotes the component table as of
> D1 close (2026-08-17), measured BEFORE the rate blend was integrated. Those
> numbers no longer describe the canonical files. The table above supersedes
> it. Adding a pointer to d1_log §8 is an open action (§11).

---

## 2. CODE CHANGES, FILE BY FILE

### 2.1 `squad/assembly.py`

**New constants**
- `D1_TERMS_ACTIVE = True` (line 43) — gates the D1 block AND feeds the stamp.
- `CS_UNIFIED = False` (line 57) — gates deriving `p_cs` from `opp_lambda`.
  Comment records the full negative result so nobody re-runs it blind.
- `TEAM_MAP` gained `"Sheffield United": "Sheffield Utd"` (line 32).

**New helper**
```python
def _expected_floor_div(mu, divisor, max_k=40):
    """E[floor(X / divisor)] for X ~ Poisson(mu)."""
```
Used for saves (`//3`) and conceded (`//2`). This is the expectation of a
floor, NOT the floor of an expectation — the distinction matters because
E[floor(X/3)] ≠ floor(E[X]/3) for small μ.

**D1 feature build** (in `assemble_fixtures`, ~line 344 onward)
- Saves: rolling per-player `saves_per_90`, 5-gw window, `shift(1)` (no
  leakage), fallback to position prior shrunk ×0.3.
- **Cards: position prior ONLY** (Variant B). Computed from `df[df.season <
  season]`, i.e. PRIOR SEASONS ONLY, as realised cards per 90 by position.
  `GKP` is folded into `GK` before the rate is computed (101 rows, 2021-22,
  an alternate label in `all_seasons_fixed.parquet`).
  Reference rates (priors to 2025-26), yellow/red per 90:
  GK 0.049/0.001, DEF 0.169/0.007, MID 0.179/0.005, FWD 0.142/0.005.
- Penalty share from Understat prior-season records; `team_pen_rate` from
  realised penalties per team-season.
- Merge fallback: card columns fall back to the position rate on a missed
  merge, never to 0.

**Non-DC early-return path RESTRUCTURED.** It previously returned before the
D1 feature build, silently making prior-season files "D1 conceded-only" — a
third state no stamp distinguished. Now `if not dc_enabled` only zeroes
`p_dc_hit`; all seasons build the full D1 feature set.

**Fixture-join guards** (after the DC merge, ~line 294+)
```python
# global (pre-existing)
if matched_frac < 0.90: raise AssertionError(...)

# NEW per-team guard — the global check cannot see a single-team failure
team_match = asm.groupby("team")["team_lambda"].agg(["size", "count"])
bad = team_match[(team_match["size"] >= 3)
                 & (team_match["count"] / team_match["size"] < 0.5)]
if len(bad): raise AssertionError(... team named ...)

# NEW neutral fill — closes the NaN-sums-to-0.0 path
asm["team_lambda"] = asm["team_lambda"].fillna(LEAGUE_AVG_LAMBDA)   # 1.40
asm["opp_lambda"]  = asm["opp_lambda"].fillna(LEAGUE_AVG_LAMBDA)
asm["p_cs"]        = asm["p_cs"].fillna(float(np.exp(-LEAGUE_AVG_LAMBDA)))  # ~0.2466
```
Threshold rationale: a stale name mapping fails ~100% of one team's joins, so
50% separates that class cleanly from an occasional genuinely-unpriced fixture.

**Crosswalk guard** — first statement of `assemble_fixtures`:
```python
assert_crosswalk_unique(cw)   # KNOWN_ISSUES #3, runs on every assembly
```
Imported from `attacking_rates`.

**Equation** (`_finish_equation`)
- `if CS_UNIFIED:` overwrites `p_cs = exp(-opp_lambda)` before `pts_cs`
  (currently False → does not run).
- `if D1_TERMS_ACTIVE:` computes `pts_saves` (GK only), `pts_conceded`
  (GK/DEF only), `pts_cards` (all), and adds penalty share into `e_goals`
  before recomputing `pts_goals`. `else:` zeroes the three point terms.
- `e_points_core` includes the three new terms.
- **Bonus BPS input fix:** `bps_input` now receives predicted
  saves/cards/conceded/penalties instead of zeros. This closed a real
  train/serve skew (the BPS model was trained on those columns), worst for
  GK/DEF. Measured e_points effect is small (GK starter mean +0.013, max
  0.21) but it has NEVER been isolated from the scoring terms in any β
  measurement — see §7 open items.

**Constants updated:** `SUM_COLS` += `pts_saves, pts_conceded, pts_cards`;
`MEAN_COLS` += `saves_per_90, yellow_per_90, red_per_90, penalty_share,
team_pen_rate`; `PRED_COLS` (persist list) += the three point terms.

### 2.2 `squad/attacking_rates.py` (largest change: +175 lines)

**New constants**
```python
RATE_BLEND_ACTIVE = True
RATE_BLEND_K = 8.0
BLEND_PRIOR = {"2023-24": "2022-23", "2024-25": "2023-24", "2025-26": "2024-25"}
_MATCHES_CACHE = {}   # per-season per-match frames; the WF loop calls get_rates per cutoff
```

**ROOT FIX — duplicate `understat_id`.** The old pooling filtered on
`position.str.contains(pos_label)`, so a player whose Understat label
differed across pooled seasons (or read e.g. "F M S") entered TWO position
pools and `get_rates` returned his id twice. `assembly.py` papered over it
with `drop_duplicates(keep="first")` after sorting by npxg90 — i.e. silently
kept the higher rate. **Scope: 282 / 278 / 262 players per predicted season
(2023-24 / 2024-25 / 2025-26).**

```python
def _primary_position(us, prior_seasons):
    """ONE position label per player: from the player's HIGHEST-MINUTES prior
    season, take the first F/M/D character (Understat lists the main role
    first)."""
```
`_pool_prior_seasons(us, prior_seasons, pos_label, primary=None)` now selects
by that single label. Both paths (blend and legacy) verified to return zero
duplicate ids; the blend path additionally `assert`s it.

**The blend**
```python
def _blended_rates(predict_season, up_to_gw):
    # prior   = player's rate over the SINGLE previous season, >= MIN_TIME(450)
    #           -> fallback position-average prior -> fallback league-average prior
    # current = ratio-of-sums over gws < up_to_gw  (up_to_gw=None -> no current data)
    # rate    = w*current + (1-w)*prior,  w = n90/(n90 + RATE_BLEND_K)
    # GK-group players excluded (attacking rates are an outfield concept)
```
Rates are **ratio-of-sums** (Σstat/Σminutes×90), never means of per-match
ratios. Source: `data/history/understat_matches_<season>.parquet` (D2 Phase 1).

**New public guard**
```python
def assert_crosswalk_unique(crosswalk):
    """KNOWN_ISSUES #3: no understat_id claimed by two elements, and no element
    claiming two understat_ids. Raises with the offending rows."""
```

**`get_rates` gained a TIME DIAL — this is the important API change:**
```python
def get_rates(predict_season="2025-26", prior_seasons=None, up_to_gw=None,
              log_mlflow=False):
```
- `RATE_BLEND_ACTIVE=True` → returns the blend; **`up_to_gw` is REQUIRED for
  correctness** in any walk-forward context (`up_to_gw=k` means current-season
  form uses gws < k only). `up_to_gw=None` → pure prior-season rates.
- `RATE_BLEND_ACTIVE=False` → legacy static pooled-3-season shrinkage,
  `up_to_gw` ignored. `log_mlflow` applies to the legacy path only.

> **BEHAVIOURAL NOTE:** `assembly.py:211` (the static single-season build) and
> the `get_rates_2526()` shim both call `get_rates` WITHOUT `up_to_gw`. Under
> the blend they therefore get **pure prior-season rates with no current-season
> form**. This is leak-free and not wrong, but it means the static build is no
> longer the same model as the walk-forward build. Flagged, not fixed (§11).

### 2.3 `eval/walkforward.py` and `eval/walkforward_season.py`

**Rates moved INSIDE the cutoff loop** (they used to be hoisted out as
"constant across cutoffs" — true for the static rates, false for the blend):
```python
for k in cutoffs:
    rates, priors = rates_mod.get_rates(season, up_to_gw=k)   # season-file version
    rates, priors = rates_mod.get_rates("2025-26", up_to_gw=k)  # walkforward.py version
```
This call site is correct under either gate setting, because the legacy path
ignores `up_to_gw`.

**New stamps** (both writers, per row):
```python
result["d1_terms_active"]  = bool(assembly.D1_TERMS_ACTIVE)
result["cs_unified"]       = bool(assembly.CS_UNIFIED)
result["rate_blend_active"]= bool(rates_mod.RATE_BLEND_ACTIVE)
result["rate_blend_k"]     = float(rates_mod.RATE_BLEND_K)
```
alongside the pre-existing `minutes_availability`, `odds_horizon_gws`,
`dgw_handling`, `dc_rule_active`, `season_label`, `train_seasons`.

### 2.4 `Tests/test_walkforward_provenance.py`

- Required-stamp list extended to include `d1_terms_active`, `cs_unified`,
  `rate_blend_active`, `rate_blend_k`.
- New `test_d1_stamp_matches_code`: asserts the file's `d1_terms_active`
  equals `assembly.D1_TERMS_ACTIVE`. A failure is a question ("did you mean to
  flip the flag without rebuilding?"), not necessarily a bug.
- Suite status: **105 passed, 5 skipped**. The 5 skips are the canonical-2526
  guards, which skip because `data/walkforward_h6_2526.parquet` (the OLD
  filename) does not exist — the three-season port renamed it to
  `walkforward_h6_2025_26.parquet`. **The fingerprint guard is therefore
  currently dormant** (§12).

### 2.5 New files

| File | Purpose |
|---|---|
| `eval/understat_matches.py` | D2 Phase 1 — per-match pull; backfill == incremental |
| `eval/measure_rate_blend.py` | D2 Phase 2 — walk-forward tuning study + sealed holdout |
| `eval/measure_d1_impact.py` | early D1 helper, largely superseded — safe to delete |
| `Logs/rate_blend_log.md` | D2 protocol, curve, pre-registration, sealed result, adoption |
| `Logs/gk_investigation_log.md` | GK workstream, three steps, still open |
| `Logs/d1_log.md` | D1 record (written earlier this session) |
| `Handoffs/Progress_notes_2026-08-17.md` | status vs the Interim project plan |

---

## 3. D1 — the four missing scoring terms (ADOPTED, CLOSED)

Record: `Logs/d1_log.md`. Adopted as **Variant B**.

| Term | Rule | Implementation |
|---|---|---|
| Saves | +1 per 3, GK only | rolling per-player saves/90, shrunk; `E[floor(S/3)]` via Poisson |
| Conceded | −1 per 2, GK/DEF | from `opp_lambda`; `E[floor(C/2)]` via Poisson |
| Cards | −1 yellow, −3 red, all | **position prior from prior seasons only** |
| Penalty share | into `e_goals` | prior-season Understat `(goals − npg)/games` × `team_pen_rate` |

**Why cards are a position prior (the key finding).** Exact per-row
decomposition (identity verified to 2e-16) attributed the GK margin-β
collapse almost entirely to the per-player rolling card rate: **alone −0.419
of the joint −0.422**. Cards are rare, so a 5-gw rolling per-player rate is a
spike detector — on GK starters its mean was −0.13 pts with **SD 0.72**, and
it was anti-correlated with realised points (r ≈ −0.13). The position prior
keeps the mean deduction (DEF −0.165 vs −0.172) with per-row SD ~0.02.
Saves (−0.101) and conceded (−0.126) interact sub-additively; penalty share
moved nothing at any position (≤0.001, and exactly 0.000 for GK — GKs don't
take penalties, verified).

**Top-k selection: 0 of 144 comparisons resolved** above gameweek-to-gameweek
variation. Adoption rests on the structural argument (these are real FPL rules
the model was blind to) plus the bonus train/serve fix, NOT on a selection win.

**Model-vs-model agreement (D1 vs no-D1)** — D1's entire practical selection
effect is goalkeepers: same-#1 63–68% at GK (union-of-top-k predicted-order
ρ only 0.51–0.54) versus 97–100% at MID/FWD. Structurally expected: saves and
conceded are the only terms that reorder WITHIN a position.

---

## 4. D2 — Understat per-match pull + rate blend (ADOPTED)

Record: `Logs/rate_blend_log.md`.

### Phase 1 — the pull (`eval/understat_matches.py`)

**The old scraping surface is dead.** Understat pages no longer embed
`datesData`/`rostersData` JSON — they are JS shells. Data moved to JSON
endpoints (found by reading `understat.com/js/league.min.js` and
`match.min.js`):
```
GET https://understat.com/getLeagueData/EPL/<start-year>   -> {dates, teams, players}
GET https://understat.com/getMatchData/<match-id>          -> {rosters, shots, tmpl}
```
Both **gzip-compressed** (must check the `\x1f\x8b` magic and decompress) and
served with `X-Requested-With: XMLHttpRequest`. Rate limit used: 1.05 s.

**npxG and npg are NOT provided per player-match — they are DERIVED here.**
The roster row carries raw `xG`/`goals` only. From the same response's `shots`
payload (`situation == "Penalty"`, `result == "Goal"`):
```
npxG = xG    - Σ(that player's penalty-shot xG in the match)
npg  = goals - (that player's converted penalties in the match)
```
**Validated exactly:** summing derived per-match npxG per player and comparing
against Understat's own season-aggregates file gives **562/562 players with
zero gap** (median, p95 and max |diff| all 0.0000).

Design: backfill and weekly incremental are **one code path** — every run
fetches only matches missing from the raw cache. Raw cache at
`data/history/understat_raw/EPL_<year>/match_<id>.json.gz`, written
temp-then-rename so a killed run never leaves a half-written file. Numeric
coercion on write (Understat serves every number as a string — KNOWN_ISSUES
#2). GW mapping via vaastav `kickoff_time` dates; dates spanning two GWs take
the majority and set `gw_ambiguous=True` (zero ambiguous rows in all four
seasons).

**Coverage: 380/380 matches × 4 seasons, 45,786 player-match rows**
(11,345 / 11,384 / 11,567 / 11,490 for 2022-23 → 2025-26), zero failures.
Converted penalties per season: 74 / 96 / 69 / 77.

**Data lag: NOT measurable yet.** The 2026-27 league endpoint returns an empty
fixture list, and 2025-26 finished in May, so "how long after kickoff does data
appear" cannot be observed retroactively. The module stamps `pulled_at` and the
cache file mtimes are first-fetch times, so **running the incremental after each
gameweek accrues the measurement automatically**. The Friday-deadline question
(can midweek fixtures be relied on?) should be answered from the first 2–3 live
gameweeks of 2026-27.

### Phase 2 — tuning (`eval/measure_rate_blend.py`)

```
rate = w * (current season to date) + (1 - w) * (prior season)
w    = n90 / (n90 + k)
```
Protocol (all pre-stated): walk-forward within season (at gw g, inputs use
gws < g only); endpoint = realised npxG/90 and xA/90 over gws g..g+2 for
players with ≥90 window minutes; **tuned on 2023-24 + 2024-25 only**;
selection rule fixed before the sweep (max mean pooled Spearman over the four
cells, ties → lower MAE); grid {0.5, 1, 2, 3, 5, 8, 12, 20, 40}.

Curve (mean ρ): 0.509, 0.517, 0.526, 0.530, 0.535, **0.537 (k=8)**, 0.536,
0.531, 0.521. Smooth, single-peaked, **plateau across 5–12** — the choice is
robust to being slightly wrong.

**k = 8 was written into the log BEFORE the holdout run**, and
`measure_rate_blend.py --holdout K` **refuses to run** unless a line
containing `k = <value>` already exists in `Logs/rate_blend_log.md`.

**Sealed 2025-26 (run once):** npxG MAE 0.1108 / ρ 0.5590 and xA 0.0951 /
0.4378, versus production baseline 0.1240 / 0.4613 and 0.1030 / 0.3941.
Improvement replicates: ρ +0.098 (npxG), +0.044 (xA).

No-prior fallback: 32–34% of rows (position-average ~28%, league-average
~4.5%).

### Phase 3 — integration + measurement

Before/after on the canonical rebuild (see §2.2 for code):
- **Aggregate:** flat (ρ +0.000 to +0.001, MAE mixed).
- **Starter-band ρ:** MID improves in all three seasons (+0.002/+0.018/+0.013);
  FWD in two of three (+0.022/+0.016, −0.008 in 2025-26); **GK untouched at
  ±0.001 — correct by construction**, goalkeepers carry no attacking rates.
- **Top-k: 8 of 72 cells resolved vs a ~3.6 chance rate** — the first
  measurement this cycle to beat chance. 5 positive (2025-26 and 2024-25),
  3 negative (all 2023-24 or 2024-25 DEF k=1).
- **Selection churn:** DEF same-#1 only **37 / 45 / 74%**, MID ~75%, FWD
  79–92%, GK ~100%.

**The DEF churn is explained (investigated, read-only):** it is ladder
geometry, not excess movement in DEF inputs.
- DEF attacking rates are small and tightly clustered (npxg90 mean 0.074, SD
  0.042); a typical blend change (0.031) is ~0.73–0.96× the entire between-DEF
  spread. In relative terms DEF `pts_goals` moved 37–42% of its own mean vs
  25–29% for MID.
- **DEF's top-10 ladder has the narrowest rungs in the game: adjacent-rank gap
  0.16 pts, versus a typical blend-induced e_points change of 0.17** (ratio
  0.92–1.16×). MID 0.72–0.80×, FWD 0.48–0.72×, GK 0.18–0.60×. That ordering
  reproduces the observed same-#1 ordering exactly. Cause: clean sheets are
  team-level and *shared*, so the small attacking rate is the only
  differentiator between defenders from good teams.
- **The fallback is NOT the mechanism:** DEF fallback usage (28.0%) is barely
  above MID (22.2%) and below FWD (41.7%), and DEF rows *with* a real prior
  moved MORE (0.032) than fallback rows (0.026).
- Biggest movers are genuine role re-pricings the pooled static was blind to —
  clearest: **Keane Lewis-Potter, npxg90 0.464 → 0.112** (a pooled winger's
  rate carried by an FPL-classified defender), −1.6 e_points.

**The 2023-24 negative lean was investigated and is coincidence:** both
comparison files are post-Sheffield-fix builds (a bug in neither side cannot
produce a delta); zero Sheffield players appear in any of the 190 negative-cell
picks; the blend's Understat inputs never carried that bug (it was an odds
join); the 2022-23 prior is NOT weaker (cross-season rate ρ 0.838 vs
0.840/0.856); structure is near-identical (fallback 30.1% vs 24.6–27.4%, role
changes 9.1% vs 8.2–8.9%); and in a prior-vs-fallback split **nothing
resolves** and negativity hits prior-carrying players as hard as fallback ones.
Labelled season-level noise.

---

## 5. KNOWN_ISSUES added this session

### #13 — D1 entered `assembly.py` before the "baseline" measurements ran

D1 was implemented on 2026-08-14; the pairwise margin-calibration
measurements ran AFTER, on files regenerated with the modified equation, while
describing them as the pre-D1 baseline. No stamp existed to reveal it.

**Contaminated and retracted:** `Logs/margin_calibration_log.md` (entire
quantitative content — the β table, the "~2.5× starter-band exaggeration", the
three-season replication, the implied 6–10 hit bar) and the derived parts of
`Logs/hit_threshold_log.md` (decision to hold the threshold at 4 STANDS; its
stated rationale is marked unverified). Both files carry retraction banners.
The true baseline GK β at step 0 is **0.847**, not the log's 0.409 — that
figure was the WITH-D1 value.

**Fix:** `D1_TERMS_ACTIVE` gates and stamps from one constant;
`test_d1_stamp_matches_code` asserts file-vs-code agreement.

### #14 — "Sheffield United" vs "Sheffield Utd"

TEAM_MAP had no entry, so the Dixon-Coles fixture join (on `team` +
`match_date`) failed for **every** Sheffield fixture in their PL seasons
(2019-20, 2020-21, 2023-24). All 38 of their 2023-24 fixtures have complete
Bet365 prices — the odds were never missing, only the name match.

Compounding fallbacks: `team_lambda` NaN → `fixture_scale` fell back to 1.0
(by design), and `p_cs` NaN → `pts_cs` NaN → `e_points_core` NaN per fixture →
**the per-gameweek collapse SUMMED an all-NaN column into a clean 0.0**. Net:
every Sheffield player carried `e_points = 0.000` for all of 2023-24 — 1,429
step-0 rows (5.0% of the season), including 36 GK and 134 DEF starter rows with
realised minutes averaging 78.

The `matched_frac < 0.90` guard could not see it: one team of twenty is ~5%.

**Audit result: across all ten seasons on disk, "Sheffield United" was the
ONLY unmatched name in either direction** between the odds source and vaastav.

**Fix:** TEAM_MAP entry + per-team guard + neutral fill (§2.1), 2023-24 rebuilt.
**Third instance of the silent-fallback family** (#10 availability default,
#13 D1 stamp, #14 join-failure zeros). The lesson written into #14: every
fallback needs either a loud guard *at the failure grain* or an explicit,
stated neutral value — never an accidental zero.

**2023-24 figures that moved after the fix** (all corrected in place, old
values struck through and visible in `d1_log.md` §8 and
`gk_investigation_log.md` §6): aggregate ρ 0.668 → **0.722**; GK β 0.479 →
0.622 (baseline 0.560 → **0.833**); DEF β 0.870 → 1.064; MID β 0.791 → 0.967.
**2025-26 and 2024-25 are unaffected** (Sheffield were not in the league).

---

## 6. Goalkeeper investigation — OPEN

Record: `Logs/gk_investigation_log.md` (§9 is the current status).

**The question:** saves and conceded are the two largest GK scoring
components, the model was blind to both, and adding them made margin
calibration WORSE (GK β 0.847 → 0.676 in 2025-26) while changing roughly a
third of #1 GK picks — and no measurement can yet say whether the new
ordering is better.

**Step 1 (H3 — accidental baseline calibration): WEAKENED.** Baseline GK β
across seasons is **0.847 / 0.760 / 0.833** — stable near 0.8, so there was no
wildly-varying baseline to blame. (The original entry read 0.560 for 2023-24
and concluded H3 *strengthened*; that was the Sheffield artefact and the entry
carries a correction banner.) D1's GK β delta is sign-consistent
three-for-three (−0.171 / −0.269 / −0.211) while MID moves positive
three-for-three.

**Step 2 (H1 — double counting between `p_cs` and `opp_lambda`): SUPPORTED
for GK.** They correlate at **−0.93 to −0.95**, and `p_cs` alone explains
**71–78%** of the conceded term's variance. Residualising `opp_lambda` against
`p_cs` recovers **31% / 44% / 72%** of the GK β loss, three-for-three in the
predicted direction. (Fit in-sample per season — a diagnostic of shared
information, not a deployable fix.) **DEF overshoots** (β → 1.10–1.24), so
simple residualisation is the wrong correction there.

**Step 3 (unification): CLEAN NEGATIVE, REVERTED.** Deriving both terms from
one distribution (`p_cs = exp(-opp_lambda)`) was built, measured on all three
seasons, and reverted. GK β moved FURTHER from baseline in all three seasons
(−0.024 / −0.005 / −0.013) and CS Brier worsened +0.0011 to +0.0016 (2–3× the
0.0005 tuning margin that originally justified the 0.2 blend).
**Mechanism lesson: residualisation REMOVES shared information and β recovers;
unification does the opposite — it makes the terms perfectly redundant rather
than 94% redundant. Unification is the wrong operation for a double-count.**
The revert was verified byte-identical (md5) to the preserved pre-unification
files. **The 0.2 CS blend is retained on the strength of this test**, not its
original 0.0005 margin.

**H2 (saves rolling rate carries minutes noise): UNTESTED.**

**Two live options for whoever picks this up:**
1. **Shrink the λ spread** feeding the GK/DEF defensive terms. **Constraint: a
   new tunable that CANNOT be validated on 2025-26** (sealed) — tune on
   2024-25/2023-24 with leave-one-season-out and apply once, pre-registered.
2. **Accept β < 1** as the honest price of rule-faithful terms. Both CS points
   and the conceded deduction are real FPL rules driven by the same true
   goals-against distribution; a rule-faithful equation cannot delete one.

---

## 7. Measurement conventions established this session (house standard)

Follow these or results will not be comparable to anything above.

1. **Step 0 only** (`horizon_step == 0`) unless explicitly measuring horizons.
2. **Starter band = `e_minutes >= 60`** (predicted). "Started-only pool" in
   selection metrics means **realised** `minutes >= 60` — different thing,
   always say which.
3. **Margin β**: through-origin OLS of realised margin on predicted margin over
   all pairs within `(gw, position)`. Computed exactly by moment accumulation,
   never sampled:
   `Σ_pairs (xi-xj)(yi-yj) = Σ_gw [n·Σxy − Σx·Σy]`, likewise the denominator.
4. **Rates are ratio-of-sums**, never means of per-match ratios.
5. **Resolution test**: paired per-gameweek deltas, "resolves" iff
   `|mean delta| > 2·SE`. **Always report the resolved count against the ~5%
   chance rate** (e.g. 8/72 vs ~3.6 expected). Never declare a winner on
   unresolved cells.
6. **Never adopt on a season total.** M1 failed; path noise is sd ≈ 60.
   Simulations are provenance references only, with the full framing.
7. **Verify provenance before comparing two files** — stamps must match on
   everything except the one flag under test.
8. **Pre-register tuned parameters in the log before the sealed run.**
9. **Preserve superseded artefacts** with a descriptive suffix so every
   retracted or superseded number stays reproducible.

---

## 8. Data artefacts on disk

**Canonical (current):** `walkforward_h6_{2025_26,2024_25,2023_24}.parquet` —
D1 + Variant B cards + rate blend k=8, cs_unified False, Sheffield fixed.

**Preserved lineage** (each reproduces the figures quoted against it):

| File | What it is |
|---|---|
| `*_prerateblend.parquet` (×3) | D1 Variant B, static rates — the blend before/after baseline |
| `*_preunify.parquet` (×3) | identical content to prerateblend; pre-CS-unification |
| `*_csunified.parquet` (×3) | the reverted CS-unification build (step-3 negative) |
| `walkforward_h6_2526_baseline.parquet` | **no D1** (2025-26) — the true D1 baseline |
| `walkforward_h6_2024_25_baseline.parquet`, `..._2023_24_baseline.parquet` | no-D1 baselines |
| `walkforward_h6_2025_26_d1cards.parquet` | full D1 with PER-PLAYER rolling cards (pre-Variant-B) |
| `walkforward_h6_2023_24_sheffbug.parquet`, `..._baseline_sheffbug.parquet` | pre-#14-fix, the contaminated 2023-24 |
| `walkforward_h6_2526_prefix.parquet` | pre-M3-migration (season total 1984) |
| `walkforward_h6_2526_av/dgwonly/odds2.parquet` | **STALE, old equation — do not use** |

**Understat (D2):** `data/history/understat_matches_{2022_23,2023_24,2024_25,
2025_26}.parquet` + `data/history/understat_raw/EPL_{2022..2025}/` (380 gzipped
JSON files each, 1,520 total).

All of `data/` is gitignored.

---

## 9. Simulation reference figures (NOT evidence — never cite as such)

| Config | Total | Transfers | Hits | Bench |
|---|---|---|---|---|
| D1 Variant B, static rates (2026-08-17) | 2028 | 36 | 84 | 382 |
| + rate blend k=8 (2026-08-18) | 2060 | 37 | 84 | 278 |

Both are range checks only. **Not comparable to each other, to 1984, to 1940,
or to anything else** — the equation inputs changed between every pair. M1
failed; season totals cannot distinguish a full model from one shrunk 75%
toward the positional mean; path noise sd ≈ 60. Full framing and config stamps
in `Logs/d1_log.md` §9 and `Logs/rate_blend_log.md` §7.

---

## 10. Project status vs the Interim project plan

(`Handoffs/Progress_notes_2026-08-17.md` is the running status; the plan
itself is `Handoffs/Interim project plan.docx`, untouched.)

| Item | Status |
|---|---|
| **M1** — EV evaluator + ladders (the gate) | **FAILED** |
| **M2** — multi-season replication | **PARTIAL** — three seasons; 2021-22/2022-23 not portable (#11) |
| **M3** — baseline migration | **COMPLETE** (2026-08-14) |
| **D1** — missing scoring terms | **COMPLETE, adopted, closed** |
| **D2** — Understat per-match npxG | **COMPLETE, adopted** (Phases 1–3) |
| **D3** — DGW prediction audit | **COMPLETE** |
| **D4** — synthetic forward odds | **UNSTARTED** — entry gate (D3) satisfied |

---

## 11. OPEN ITEMS / IMMEDIATE ACTIONS

**A. (URGENT — do this first) ~30 measurement scripts live only in the session
scratchpad and WILL BE LOST.** Their methodologies are described in the logs
but the code is not in the repo. The reusable ones worth copying into `eval/`:
`d1_topk.py` (top-k with resolution test), `d1_agreement.py` (model-vs-model),
`d1_term_decomposition.py`, `d1_variants_ab.py`, `gk_h1_doublecount.py`,
`gk_h3_baseline_beta.py`, `measure_cs_unify.py`, `cs_lambda_consistency.py`,
`measure_rateblend.py`, `d1_final_metrics.py`. Path:
`C:\Users\veers\AppData\Local\Temp\claude\c--Users-veers-OneDrive-Documents-FPL-Agent\fc435743-e212-40d9-b21f-f66a9fada11c\scratchpad\`

**B. Uncommitted work.** `git status`: 6 modified
(`Handoffs/Progress_notes_2026-08-17.md`, `Tests/test_walkforward_provenance.py`,
`eval/walkforward.py`, `eval/walkforward_season.py`, `squad/assembly.py`,
`squad/attacking_rates.py`), 3 untracked (`Logs/rate_blend_log.md`,
`eval/measure_rate_blend.py`, `eval/understat_matches.py`) + this handoff.
+195/−20 lines. Verified: no parquet or data paths (all gitignored), no
secrets. Proposed message drafted in the prior turn. **Not committed —
the user runs it.**

**C. `d1_log.md` §8 is stale** — it quotes the component table as of D1 close,
before the rate blend. Needs a pointer to the current numbers (§1 above).

**D. Static build ≠ walk-forward build.** `assembly.py:211` and
`get_rates_2526()` call `get_rates` without `up_to_gw`, so the static build now
uses pure prior-season rates with no current-season form. Decide whether the
static path should thread a gameweek or be documented as a different model.

**E. The canonical fingerprint test is dormant** — it guards
`data/walkforward_h6_2526.parquet`, which no longer exists (renamed to
`_2025_26` in the M2 port). 5 tests skip. Either repoint it and set a new
fingerprint deliberately, or record why it is retired.

**F. Bonus BPS input change never isolated.** It shipped inside D1 and acts on
GK/DEF specifically; no β measurement has separated it from the scoring terms.

**G. Cold start untouched (D2).** 32–34% of rows hit the no-prior fallback —
new signings from abroad, promoted-team players, debutants. They start on a
position average and earn their own rate only as n90 accumulates against k=8.

**H. GK investigation** — see §6, two live options.

**I. `Logs/d1_implementation_summary.md`** is an early-session doc containing
pre-retraction figures (e.g. "Spearman 0.738"). Superseded by `d1_log.md`;
either delete or banner it.

**J. Understat data lag** — measure from the first 2–3 live gameweeks of
2026-27 by running `eval/understat_matches.py --season 2026-27` after each
gameweek and comparing `pulled_at` / cache mtimes against kickoff.

---

## 12. TRAPS — read before touching anything

1. **Any equation-affecting flag MUST be gated by one constant and stamped into
   the artefact.** Three incidents (#10, #13, #14) came from source and artefact
   disagreeing silently. Follow the `D1_TERMS_ACTIVE` pattern exactly.
2. **`get_rates` now needs `up_to_gw` in walk-forward contexts.** Omitting it
   is silent — you get pure prior rates, no error.
3. **Rebuilding a canonical file changes the numbers in every log that quotes
   it.** Preserve the old file with a suffix first, and correct logs in place
   with the old value struck through (see `d1_log.md` §8,
   `gk_investigation_log.md` §6 for the convention).
4. **2025-26 is the sealed test season.** Nothing may be tuned against it. Tune
   on 2023-24/2024-25, pre-register in a log, apply once.
5. **`data/history/all_seasons_fixed.parquet` uses `GW` (uppercase)**; assembly
   renames to `gw`. Understat labels seasons by START YEAR ("2025" = 2025-26).
   Understat serves all numerics as STRINGS (#2). `GKP` appears as an alternate
   `GK` label (101 rows, 2021-22).
6. **Stale walk-forward files on disk** (`_av`, `_odds2`, `_dgwonly`, `_prefix`)
   use old equations. Always check stamps before comparing.
7. **PowerShell `*>>` redirects write UTF-16** — grep the resulting logs with
   `tr -d '\0\r'` or they read as binary. Long background jobs are best run
   detached via `Start-Process -WindowStyle Hidden powershell -File <script>`
   with a Monitor watching the log; a Bash-tool foreground run can die with the
   turn.
8. **Console encoding**: printing player names with non-ASCII characters
   crashes on cp1252. Normalise to ASCII for terminal output.
9. **A full three-season walk-forward rebuild takes ~27–30 minutes**; a season
   simulation ~10–15 minutes; the four-season Understat backfill ~27 minutes at
   1 req/s (resumable).
