# Handoff — 2026-08-20 → 2026-08-23 session, FULL DETAIL (code-first)

**Covers everything in the session:** P1 opening-squad work (Steps 1+2, built
and CLOSED not adopted), the 42-sim WC1×opening grid, the WC1 rule REVISION
(GW4–5 → GW2–3, ADOPTED), the 24-sim full-system reference grid, P3 early-hit
tolerance (measured, declined), P5 bench-order + XI-tiebreak (measured,
declined), the five-step team-news investigation (incl. the oracle-minutes
instrument), GK investigation step 4 (λ shrink, weak, not adopted), the
2024-25 failure forensics + re-basing test, the D6 GW1 smoke-test miss and
salvage + Task Scheduler registration, the interim-project CLOSING POSITION,
and the stale-figure housekeeping sweep. Companion documents:
`Handoffs/Interim_project_closing_position_2026-08-21.md` (the one-page
dispositions) and `Handoffs/Handoff_2026-08-20_full_session_detail.md` (the
previous session; its §9 traps all still apply).

Test suite at close: **113 passed, 5 skipped** — unchanged all session.
NO new tests were added for the new gates (debt, §8).

---

## 1. LIVE CONFIG — every gate, its location, value, and stamp

| Constant | File | Value | Stamped as |
|---|---|---|---|
| `D1_TERMS_ACTIVE` | squad/assembly.py | True | `d1_terms_active` |
| `CS_UNIFIED` | squad/assembly.py | False | `cs_unified` |
| `RATE_BLEND_ACTIVE` / `_K` | squad/attacking_rates.py | True / 8.0 | `rate_blend_active`/`_k` |
| `SYNTHETIC_LAMBDA_ACTIVE` | squad/synthetic_lambda.py | False | `synthetic_lambda_active` |
| `BENCH_BOOST_AWARE` | squad/transfer_mip.py | True | `bench_boost_aware` |
| `DEFAULT_HORIZON` / `DEFAULT_DECAY` | squad/transfer_mip.py | 6 / 0.45 | `horizon` / `decay` |
| **`OPENING_HORIZON_ACTIVE`** | squad/simulator.py | **False** | `opening_horizon_active` (stamps what the run DID: gate AND policy=mip AND horizon-aware frame) |
| **`OPENING_ROBUST_ACTIVE`** | squad/simulator.py | **False** | `opening_robust_active` (takes precedence over the horizon gate) |
| **`BENCH_ORDER_BY_PLAY`** | squad/scoring.py | **False** | `bench_order_by_play` |
| **`XI_TIEBREAK_P60` / `XI_TIEBREAK_WEIGHT`** | squad/optimize.py | **False / 0.05** | `xi_tiebreak_p60` |
| **`EARLY_HIT_DISCOUNT_ACTIVE` / `EARLY_HIT_BAR` / `EARLY_HIT_LAST_GW`** | squad/transfer_mip.py | **False / 4.0 / 7** | `early_hit_discount_active` / `early_hit_bar` (−1 when inactive) |
| **`ORACLE_MINUTES_ACTIVE` / `ORACLE_MODE` / `ORACLE_MASK`** | squad/oracle_minutes.py | **False / "full" / None** | `oracle_minutes_active` / `oracle_mode` ("off" when inactive). DELIBERATE LEAKAGE instrument — never adopt; module carries the warning |
| `HIT_COST` | squad/transfer_mip.py | 4 | game rule |

**Chip rules of record (p4_chip_policy_log §12, one REVISION this session):**
WC1 **GW2–3** (revised 2026-08-21, §12b — was ~~GW4–5~~, struck through in
the table); WC2 pre-DGW-cluster swing; FH2 largest blank floor ≥4; BB2
biggest second-half double bench-aware; ~~TC2 biggest DGW~~ TC2 earliest eligible second-half double (revised 2026-08-24, p4 §12c (ii) — the old rule collided with BB2 and its first revision selected nothing in two of three seasons); TC1
predicted-captain peak; BB1 only at a real H1 double (measured
free-to-slightly-positive on single fixtures, ~+10 bench).

**Simulator capability change:** `simulate_season(bench_boost_gw=...)` now
accepts an int (legacy) OR an iterable — one Bench Boost per half, validated
by `_chip_weeks`, clash-checked vs WC/FH. Legacy stamp `bench_boost_gw` = the
single int, or −1 when none/multiple; NEW stamp `bench_boost_gws` =
comma-joined string always (e.g. "7,34"). At most one boost per H≤6 window,
asserted in `decide_gameweek_mip`.

All new-gate stamps are read LIVE via `__import__(...)` so in-process flips
by drivers register correctly (the run_chip_study pattern).

---

## 2. NEW FILES, one by one

### squad/opening_robust.py (P1 Step 2 — gated off, retained)
`robust_opening_squad(pool_by_gw, prob_by_gw, decay, mode, K=50,
seed=20260820)`. Sampling (mean-preserving, verified sum-ratio 1.001 corr
0.992 vs e_points): ONE uniform per (player, scenario) shared across the 6
weeks → `played = u < p_play_any[t]`, `sixty = u < p_60plus[t]` (persistent
availability regimes); goals/assists Poisson from pts_goals/GOAL_PTS,
pts_assists/3 conditioned on played; CS/DC Bernoulli from pts_cs/CS_PTS/p60,
pts_dc/2/p60 conditioned on sixty; smalls+bonus at conditional expectation.
Null-prob fallback (~4% rows): p_play=min(1,pts_appear), p60=max(0,app−1).
Candidates: one deterministic free-pick `build_and_solve` per scenario
(all 50 came out DISTINCT every time) + the expectation horizon MIP + the
single-GW `optimize_squad` squad. Selection: recourse-aware cross-eval —
per (candidate, scenario), weekly formation-argmax XI from current 15 ×
decay^t + captain×2, then ONE repair/week (sell one of 3 lowest
remaining-value members, best affordable same-position buy by remaining
decayed value, club≤3, bank tracked, only if strictly improving). `PROB_COLS`
= the column list the simulator slices for it. **Result: never produced a
new squad — deterministic candidates ranked 1–2 of 52 in all three seasons.**
Runtime ~6.5 min solo (K=50). `Date.now`-free, fully deterministic.

### squad/oracle_minutes.py (team-news steps 4–5 — MEASURING INSTRUMENT)
Big never-adopt warning in the docstring. `apply_oracle_minutes(df)`:
replaces e_minutes→realized minutes, p_play_any/p_60plus→indicators,
pts_appear→2/1/0 exact, pts_cs→p_cs×CS_PTS×1{60} exact, pts_dc→2×p_dc_hit×
1{60} exact, attacking/saves/conceded/cards/bonus scaled by
clip(min/max(e_min,30), 0, 2.5) (stated approximation), e_points→sum.
Row selection by `ORACLE_MODE`: "full" (all rows — the step-4 horizon-wide
oracle), "step0" (cutoff==gw only — arm A), "masked_step0" (step 0 ∧
(gw,element) ∈ `ORACLE_MASK` — arms B/C). Wired into
`simulator.load_season` (applies after the e_points-notna filter, prints a
loud line). Every touched run stamps `oracle_minutes_active=True` +
`oracle_mode`.

### eval drivers/measures (all: skip-if-exists, atomic tmp→rename, JSON
lists, config stamped per row, in-process gate flips restored in `finally`)
- **run_p1_opening.py / measure_p1_opening.py** — P1 Step 1 arms
  {base, p1} × 3 seasons → `data/p1/p1log_{tag}_{arm}.parquet`. Measure:
  GW1-15 step tables from cutoff==1 pivots; CAPTURE metric (calibrated:
  best-15 = raw top-15 by actual points — reproduces coldstart's 174.3/180.1
  exactly; capture = era points-share, the log's 39.86/174.3≈22.7%);
  per-gw vs avg manager; survival GW8/GW15; asserts arms differ ONLY on
  `opening_horizon_active` and share horizon/decay/bb/wf_file stamps.
  Avg-manager per gw: fplcache POST-SEASON snapshot (date-window trap!),
  `events[].average_entry_score`, sums asserted == 2003/2008/1895.
- **run_p1_robust.py / measure_p1_robust.py** — arm p2; measure is 3-way
  (base/p1/p2) with exact stamp-discipline asserts.
- **run_p1_wc_grid.py / measure_p1_wc_grid.py** — WC1∈{2..8} × opening ×
  season (42 sims) → `wclog_{tag}_{opening}_wc{k}.parquet`. Prefix identity
  asserted vs the reused p1log baselines. Measure: W∈{1,2,3,5} anchor
  deltas, sign consistency, GW1-10 vs avg, survival, totals; partial-grid
  tolerant.
- **run_full_system.py / measure_full_system.py** — the 24-cell all-chips
  grid → `fslog_{tag}_{opening}_wc{k}.parquet`. Chip weeks: WC2 32/31/32,
  FH2 29/29/34, BB2 34/33/33, BB1 {23-24:7,7; 24-25: base 7 / p1 9;
  25-26: 10,10} (BB1 rule: the only H1 double, else argmax predicted BENCH
  points of the baseline squad over GW3-19 minus {2,4,6,8}). Prefix
  boundary min(wc1, bb1−5). Measure: path + CHIP-INCLUSIVE totals (path +
  bench@BB1 + bench@BB2 + capbonus@TC2(=BB2 wk, both added per P4
  convention, optimistic by min(TC2, BB2 bench)) + capbonus@TC1 (argmax
  predicted captain GW1-19 excl chip weeks, from the cell's own log)),
  margins vs fplcache avg, W3 anchors, and THE BB1 PAIRING: fslog vs the
  same (season,opening,wc1) wclog differ only by BB scheduling before GW28
  — prefix-verified 24/24; BB1 net = path Δ over [bb1−5, bb1+5] + bench@bb1.
- **run_p3.py / measure_p3.py** — early-hit bars {3,2,1} × WC1{2,6} ×
  season (18 sims) → `p3log_{tag}_wc{k}_bar{b}.parquet`; bar 4 = reused
  fslog references. Measure: GW2-7 hits/points, per-decision E1/E2 transfer
  quality (pred = decayed H-window at own cutoff; realized = undecayed
  next-3-gw), full distributions with hit-week subset, selection-trap
  caveat in mirror.
- **run_p5.py / measure_p5.py** — arms {bench, xi, both} × season (9 sims)
  → `p5log_{tag}_{arm}.parquet` under the full-system wc2 config. Driver
  asserts: bench arm's SQUADS identical to reference all season;
  first-divergence gws stamped (`first_squad_divergence`,
  `first_points_divergence`). Measure replays weeks with arm-correct rules
  (ε-tiebreak in XI reconstruction for xi arms; BENCH_ORDER_BY_PLAY set for
  bench arms) and verifies fidelity per week vs raw_points/bench_points/
  n_subs/captain (36–38/38; BB weeks are the mismatches — wb=1 makes the
  XI split degenerate).
- **build_teamnews_cases.py** — the FIXED 52-case list →
  `data/teamnews/case_list.parquet` + `Logs/teamnews_case_list.md`.
  Definition (reproduces the prior count exactly): owned player in the d45
  base path, own-cutoff e_minutes ≥ 60, played 0. Columns incl. deadline
  UTC+local, asof availability row, minutes gw−3..gw+3, fixture context
  (midweek, prev/next-gap days, post-break ≥13d), heuristic `group`.
- **fetch_teamnews_guardian.py** — Guardian Open Platform lookup. Key from
  `.env` `GUARDIAN_API_KEY` (gitignored; never stored/printed — raw files
  verified key-free). ONE query stream per (team, season, gw) window
  (deadline−10d..+3d, section=football, show-fields=body, paged ≤5,
  1 req/s, 429 backoff), raw-first to `data/teamnews/guardian_raw/` (90
  files). LOCAL passage extraction: per-player ALIAS regexes (Guardian
  common names; `(?<!Old )\bTrafford\b`; Arsenal Gabriel excludes
  Jesus/Martinelli), ABSENCE regex with LEADING word boundaries (v1 matched
  "ill" in Colwill/still, "rest" in Forest, "missed" in dismissed; bare
  "miss(es)" removed for news phrasings), 140-char proximity rule.
  `--parse-only` re-parses cached raw. Output guardian_passages.parquet
  (classification pre/post/none + up to 5 verbatim passages).
- **value_teamnews_cases.py** — step 3B/C. Bench-bounded per-case value via
  exact replay (52/52 fidelity): autosub fired → max(0, best legal bench
  alt − sub points); dead slot → best alt; captaincy increment only if
  doubled_role == "none" (the vice self-corrects otherwise). Tiers: floor
  (verified 10) 7.0 pts/3 seasons; middle ×0.42 precision 14.2; ceiling
  (all 52) 56.0.
- **run_teamnews_oracle.py / measure_teamnews_oracle.py** — step 4 full
  oracle (3 sims) → `data/teamnews/oraclelog_{tag}.parquet`; measure:
  totals + chip-incl, per-gw delta distribution, valued transfer diffs
  (E2), captaincy changes, 52-case avoidance vs step-3 values,
  identical-vs-differing-squad decomposition (came back DEGENERATE — zero
  identical weeks).
- **run_teamnews_knowable.py / measure_teamnews_knowable.py** — step 5 arms
  A/B/C (9 sims) → `oraclelog_{tag}_{A,B,C}.parquet`. Arm B mask built
  from vaastav: ≥60 PL min within prior 4 days OR first gw after 3+
  zero-min gws (12.6–15.1k reveals; European midweeks NOT derivable,
  stated). Arm C mask = the 10 verified cases. Measure prints PATH and
  CHIP-INCLUSIVE columns side by side (user requirement) + % of step-4
  delta surviving.
- **gk_lambda_shrink.py** — GK step 4. β = through-origin pairwise slope,
  within (gw, position), starter band e_min≥60, moment accumulation
  (n·Σpa−ΣpΣa over n·Σp²−(Σp)²). VALIDATES first by reproducing 0.847
  (no-D1 baseline) and 0.676 (prerateblend) on preserved artefacts —
  refuses to run otherwise. Shrink: per-gw team-mean recentre lam' =
  m_gw + s(lam−m_gw), conceded term ONLY, recomputed through assembly's
  own `_expected_floor_div`; applied as delta recon(s)−recon(1) so s=1 is
  exactly canonical. `--tune` (sweep on 23-24/24-25 + era gap incl. 25-26
  at s=1) / `--holdout --s-gk --s-def` (sealed, run once).
- **poll_availability.bat** — user's Task Scheduler launcher (cd + uv run
  --once). Task "FPL availability poller" REGISTERED by the user, every
  10 min; power conditions fixed via Set-ScheduledTask (battery allowed,
  WakeToRun true).

### New logs (all results of record live here)
`Logs/p1_opening_log.md` (§0 closure decision; §1–6 Steps 1–2; §7 WC1 grid;
§8 full-system reference; §9 files), `Logs/p3_early_hits_log.md`,
`Logs/p5_optimizer_wins_log.md`, `Logs/teamnews_case_list.md`,
`Logs/teamnews_step2_guardian.md`, `Logs/teamnews_step3_valuation.md`,
`Logs/teamnews_step4_oracle.md`, `Logs/teamnews_step5_knowable.md`,
`Logs/why_2024_25_log.md` (forensics + the re-basing test),
`Handoffs/Interim_project_closing_position_2026-08-21.md`.

---

## 3. MODIFIED FILES, one by one

### squad/simulator.py (the biggest surface)
- Gates + docstrings: `OPENING_HORIZON_ACTIVE`, `OPENING_ROBUST_ACTIVE`.
- GW1 branch (state is None): robust path (lazy-imports opening_robust,
  builds pools via gw_slice(cutoff=gw) + prob slices via PROB_COLS, locks
  the chosen 15 through optimize_squad for XI/roles) → elif horizon path
  (build_and_solve free-pick over the window, plan_to_team) → else legacy
  single-GW. Both raise loudly on mip + non-horizon-aware frame.
- Multi-BB: `_chip_weeks` normalisation for bench boosts + clash check;
  `decide_gameweek_mip` accepts int/iterable, asserts ≤1 boost in window;
  GW1 horizon path computes bb_step from the set.
- `gw_slice` now carries `p_play_any`/`p_60plus` when present;
  `_adjusted_pool` and `_pool_with_owned` fill those with explicit 0.0 on
  injected blank-week rows.
- `load_season` applies the oracle transform when its gate is on (loud
  print).
- Decision-log stamps added: `opening_horizon_active`,
  `opening_robust_active`, `bench_order_by_play`, `xi_tiebreak_p60`,
  `oracle_minutes_active`, `oracle_mode`, `early_hit_discount_active`,
  `early_hit_bar`, `bench_boost_gws` (and `bench_boost_gw` legacy
  semantics: single int or −1).

### squad/transfer_mip.py
- P3: `EARLY_HIT_DISCOUNT_ACTIVE/EARLY_HIT_BAR/EARLY_HIT_LAST_GW`; per-step
  `bar_t` in the objective (gws[t] ∈ 2..7). Documented degeneracy: bar <
  HIT_COST×decay (=1.8) weakens the anti-inflation argument at the GW7→8
  boundary — bar=1 crosses it, 2–3 don't.
- P5: reads `optimize.XI_TIEBREAK_P60/WEIGHT` live; builds p60[(i,t)] dict
  (raises if gate on and column missing); adds d·w·p60·start terms.
- `plan_to_team` carries p_play_any/p_60plus into the team frame.

### squad/optimize.py
- `XI_TIEBREAK_P60=False`, `XI_TIEBREAK_WEIGHT=0.05` (threshold rationale
  in the comment: 2–5% of prediction MAE, ~5e4× solver tolerance);
  objective term on start vars when gated; `get_team` carries the prob
  columns.

### squad/scoring.py
- `BENCH_ORDER_BY_PLAY=False`; `assign_bench_order` orders outfield bench
  by p_play_any (e_points tiebreak) when gated, RAISES if the column is
  missing (no silent fallback).

### Logs/p4_chip_policy_log.md
- §12 table: WC1 row revised to **GW2–3**, old rule struck with
  date+reason; §12a review record (completed, case assembled); §12b full
  revision reasoning (evidence, generalisation, conditionality on cold GW1
  inputs + revisit trigger, option-value reservation → range not point,
  confidence statement).

### KNOWN_ISSUES.md — #15 contamination-surface DISCHARGED (2026-08-22
sweep record appended).

### Housekeeping sweep (2026-08-22) — 16 logs + 2 handoffs
Supersession addenda on the five 2026-08-14-bannered logs (availability,
instrument_b, Walkforward, wildcard_and_determinism, Transfer mip); new
banners: coldstart (capture re-measured 31.7/37.1/27.5), Simulator log,
Assembly log, Bonus model log, d1_implementation_summary (superseded by
Variant B); d1_log §8 2025-26 row struck + current values, §9 index
pointer; rate_blend_log §7/§8 notes; gk log era banner;
overnight log stage table fixed; season_totals_index coverage note
(indexes through 2026-08-20 ONLY — the generator globs chips+sweep only);
Handoff 08-14 + 08-18 point-in-time banners.

### Logs/gk_investigation_log.md — §10 step 4 (era gap, sweep,
pre-registration incl. the stated DEF deviation, holdout, verdict).

### Logs/d6_live_availability_log.md — §9 GW1 outcome (window MISSED on
timezone; salvage: post-deadline poll, schema-identical --build, late-news
rule fired live on 5 players; blind-window diff lost for GW1; GW2 retry
plan in LOCAL time).

### Handoffs/Progress_notes_2026-08-17.md — Phase P dispositions, WC1
review closed, 2026-08-21 section.

---

## 4. RESULTS OF RECORD (headlines; details in the named logs)

- **P1 CLOSED not adopted** (p1 log §0): Step 1 mechanism works, endpoints
  mixed (+21/−11/+21 GW1-7 vs avg; 5-of-12 under full system); Step 2
  collapses to expectation (deterministic squads rank 1–2 of 52, thrice);
  the durable finding is SUBSTITUTION with the early wildcard; simplicity
  counted. Untried levers recorded: correlated scenarios, CVaR.
- **WC1 rule ADOPTED GW2–3** (p4 §12b): GW2 positive 6/6 arms at W=1,2,3 in
  BOTH grids, mean +41/+42 at W3; GW4 contradicted (2/6). Conditionality:
  the edge rides on cold GW1 inputs — shrinks if D5/lineups improve the
  opening. Anchors reproduce under the full system (median |diff| 0).
> **Correction 2026-08-24:** the chip-inclusive figures in the next bullet (2299 / 2301 / 2219, +99..+437) included an illegal Triple Captain 2 read on the Bench Boost 2 week; read them as 2296 / 2294 / 2206 (+92..+430). p4 log §12c, KNOWN_ISSUES #16. *(2026-08-26: superseded again — the figures of record are 2251 / 2306 / 2268 under bonus_mode=delete with TC2 in-sim; closing position §3.)*

- **Full-system reference** (p1 log §8): all 24 cells clear the average
  manager (+99..+437 chip-incl). System-as-configured (wc2 cells):
  **2299 / 2301 / 2219** vs avg 2003/2008/1895. BB1 on singles ≈ free
  (~+10 bench, no detectable build cost; the +37 was a fluke).
- **P3 declined**: early-hit discount pays only where the wildcard is late
  (wc6 bar2-3: median +7-9, 61-68% beat 4); under WC1@2 it's ~50%
  break-even. Bar=1 degrades + has the formulation caveat.
- **P5 declined** (noise-free paired paths — squads identical all 9 runs):
  bench-order −4..−7 (the historical +2 DOES NOT replicate; p_play
  ordering resolves subs worse), XI tiebreak −12..+3, dead slots untouched.
  Optimizer-has-converged reconfirmed.
- **Team-news (5 steps)**: 52-case list fixed (def reproduces exactly);
  Guardian: 24 auto-pre → 10 verified (precision 0.42; zero of 14
  adjudicated upgrades — commentary/collisions/team-sheet-time);
  bench-bounded value floor **2.3/season** (autosub+vice self-heal; both
  captained cases auto-passed to vice), middle 4.7, ceiling 18.7 — the old
  ~29+29 was gross-not-net; **full oracle +146/+109/+95 path (+131
  chip-incl mean)** — 52-case channel ≈ a sixth of it, transfers/rotation-
  timing dominant, captaincy +31/+25/+10; **knowable split**: A (step-0
  only) +65/−91/+126 chip-incl (unreliable), B (calendar-knowable)
  −46/−120/+30 (partial-truth injection HARMS — design constraint: any
  team-news integration must update ALL horizon steps consistently), C
  (reported) +0/−107/−1 (buyable ≈ nothing). D5/D6-paid argued AGAINST on
  evidence; the honest target is horizon minutes prediction; step 5
  defines the acceptance test (close full-vs-A gap without arm-B
  inconsistency).
- **GK step 4 not adopted**: conceded-λ shrink too weak (80% cut → +0.06..
  +0.09; grid-edge selection; holdout 0.701→0.790 exceeded the
  pre-stated +0.06). Era gap re-measured: GK β 0.640/0.496/0.701, DEF
  1.012/0.862/0.975 (DEF problem largely dissolved). Untested remainder:
  p_cs-side shrink (trades vs CS Brier; needs own pre-registration).
- **2024-25 forensics**: signature ≈ HALF ARTEFACT (larger half). Baseline
  = 97th-pctile of 34 paths (+169 premium; Salah 318/344 held; luck −125
  vs −307..−454); arms lose −4.19/gw in NO-transfer weeks (kills
  reshuffle-into-error); churn cost real but small (−1.2/gw) and
  near-universal. Re-basing vs per-gw median pool: 8/19 negatives flip,
  all shrink, one-signed corrections vs mixed ±10-15 controls; method weak
  point: season-TOTAL re-base overcorrects +50..90 (chip mismatch) — the
  team-news re-based figures are optimistic. Re-READ (not rewrite): p4 §12
  2024-25 rows, §12a/b GW6-8 framing, teamnews step-5 arms.
- **D6**: GW1 window MISSED (timezone: machine is UTC−4; window was
  09:30–13:30 LOCAL). Salvaged: post-deadline poll (+44min, 600 elements),
  --build schema-identical, late-news rule fired live on 5 players (Bruno
  G., Hirst, Porro, Van de Ven, Sarr — all flag-clears). GW1 blind-window
  diff permanently lost. **GW2: Friday 2026-08-28, window 09:30–13:30
  LOCAL, deadline 13:30 local.** Task Scheduler task registered by user
  (10-min cadence, battery-allowed, WakeToRun=true); belt-and-braces:
  sleep off 09:15–14:00 local.

## 5. MEASUREMENT CONVENTIONS ESTABLISHED/RECOVERED THIS SESSION

- **Capture of best-available 15** = era POINTS-SHARE vs raw top-15 by
  actual points (calibrated against coldstart's own numbers; overlap-count
  is NOT it).
- **Avg manager per gw** = fplcache post-season snapshot (pick by date
  window!), events[].average_entry_score; sums must assert 2003/2008/1895.
- **XI replay** = formation-argmax of own-cutoff step-0 e_points (+ε·p60
  when that gate is on), captain=argmax e_points in XI, production
  assign_bench_order + score_gameweek; verify per week vs raw_points/
  bench_points/n_subs/captain BEFORE trusting (38/38 on chip-free logs;
  BB weeks mismatch under wb=1 degeneracy).
- **β** = through-origin pairwise within (gw,pos), starter band, moment
  accumulation; validate on preserved 0.847/0.676 first.
- **Re-basing** = per-gw MEDIAN across the season's non-oracle paths,
  excluding window-chip-playing paths; NOT single-path (the log's "wc5"
  suggestion was wrong — high percentile, not median). Season-TOTAL
  re-base is unreliable (chip composition mismatch).
- **E1/E2 transfer quality** = decayed H-window predicted at own cutoff /
  undecayed next-3-gw realized (transfer-sweep conventions).

## 6. ARTEFACTS ON DISK (all gitignored)

- `data/p1/`: p1log ×6 (+p2 ×3), wclog ×42, fslog ×24, p3log ×18,
  p5log ×9. Totals for every one are in the respective logs; the index
  covers only through 2026-08-20 (coverage note added).
- `data/teamnews/`: case_list, guardian_raw/ (90 json, key-free,
  verified), guardian_passages, case_values, oraclelog ×3 (full) + ×9
  (A/B/C).
- `data/live/`: GW1 salvage (bootstrap_raw 3 polls,
  availability_2026_27_live.parquet, changes parquet).
- Session scratchpad (dies with the session; reusable pieces already in
  eval/): check_provenance.py, smoke_p1/p2, calibrate_capture,
  extract_avg_manager, analyse_p1_reversal, decompose_worst_weeks,
  bb1_select_and_smoke, wc1_rule_review, why_2425_v2, rebase_2425,
  print_unverified + all run logs.

## 7. COMMIT STATE at handoff

Committed during the session (by the user, from proposed messages): the P1
closure batch; the WC1 rule revision; P5+P3+D6-outcome (+ closing
position); the team-news steps 1–5 batch. FINAL batch (housekeeping sweep
+ GK step 4 + forensics + poll_availability.bat): `git add -A` + commit
command provided at session end — verify `git status` is clean before
building on this. No parquet, no secrets, .env gitignored throughout
(verified per batch, incl. a key-scan of the Guardian raw store).

## 8. OPEN ITEMS FOR THE NEXT SESSION

1. **D6 GW2 smoke test, Friday 2026-08-28, 09:30–13:30 LOCAL** — the task
   is registered; verify `powercfg /waketimers` shows it armed near the
   window; afterwards run the §8 checklist + the fplcache blind-window
   diff (THE measurement, lost once already).
2. **Live 2026-27 season** is underway (GW1 played 2026-08-21). The
   live-freeze decision (closing position §4) remains unmade; GW2-3 is now
   the adopted WC1 window — if a live config is ever frozen, that rule
   binds immediately.
3. **p_cs-side λ shrink** (GK log §10): needs its own pre-registered
   protocol; trades against CS Brier; tune 23-24/24-25 only.
4. **Horizon minutes prediction** is the declared target (teamnews step 5;
   closing position §5). Acceptance test defined: close part of the
   full-vs-A oracle gap with a CONSISTENT all-steps update; must not
   reproduce arm B's partial-truth failure.
5. **Re-read flags** stand on p4 §12 2024-25 rows / §12a-b / teamnews
   step-5 (why_2024_25_log) — future decisions citing those must apply the
   half-artefact correction.
6. **Unrecomputed**: post-blend step-0 aggregates for 2023-24/2024-25
   (every marker says so); 2023-24/2024-25 p3/p5-era metrics all current.
7. **Index generator** (build_season_totals_index.py) doesn't glob
   data/p1 or data/teamnews — extend before regenerating.
8. **Test debt**: no property tests for the seven new gates (P1×2, P5×2,
   P3, oracle×1 + multi-BB). Gate-off inertness is currently guarded only
   by the suite + prefix-identity asserts in drivers.
9. Inherited and still open: D2 cold start (~32% no-prior), M1
   kill-criterion record, XI split not persisted in decision logs,
   dormant 2526 fingerprint guards.

## 9. TRAPS (delta over the 2026-08-20 handoff §9 — that list still applies)

- **This machine is UTC−4.** Every FPL deadline is stated UTC; convert
  BEFORE scheduling anything. The GW1 window was lost to exactly this.
- The oracle instrument is deliberate leakage: any artefact with
  `oracle_minutes_active=True` is a measurement, never a baseline.
- Partial minutes-truth injected at step 0 against unchanged steps 1–5
  HARMS decisions (teamnews arm B). Never integrate team-news that way.
- `bench_boost_gw` stamp is −1 when TWO boosts are scheduled — read
  `bench_boost_gws` (string) instead.
- TC2 and BB2 share the biggest-DGW week in all three seasons; the P4
  convention adds both reads — chip-inclusive figures are optimistic by
  min(TC2, BB2 bench).
- Replay fidelity breaks specifically at bench-aware BB weeks (wb=1 makes
  the XI split degenerate) — check fidelity per week, not per run.
- Guardian: aliases (Trafford≠Old Trafford, Gabriel≠Jesus/Martinelli,
  Beto≠Pedro Neto), leading word boundaries on absence terms, and read
  passages before trusting counts. Key lives ONLY in .env.
- Windows monitors: Monitor tool max 1h non-persistent — re-arm or use
  persistent for multi-hour sim fleets; sims are launched detached
  (Start-Process) with FPL_SOLVER_THREADS=2, ≤6 workers.
- Season-total re-basing across chip-composition mismatches overcorrects
  by the chips' own worth; only windowed re-bases are trustworthy.
- The `.docx` handoffs are plan-of-record; corrections go to .md files
  only.
