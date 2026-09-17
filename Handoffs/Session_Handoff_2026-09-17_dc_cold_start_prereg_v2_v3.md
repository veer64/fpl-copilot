# Session handoff — 2026-09-13 → 2026-09-17: the Dixon-Coles cold start (fix, loud detector, prereg v2 + v3), explain_prediction, alerting, the multi-run dispatcher, the agent prompt

Written for the next Claude Code session (and Veer) picking up FPL Copilot on or after Friday 2026-09-18. It is
long on purpose: every code change, constant, function, test, commit, script, number and decision from this session
is here or pointed to, so nothing has to be reconstructed from memory. Where a fact comes from a log rather than from
something re-verified at hand-over time, the log is named.

---

## 0. Read this first — the state at hand-over (Thu 2026-09-17 19:20Z)

| where | commit | notes |
|---|---|---|
| laptop `main` | `e202e29` | working tree clean except ONE untracked file: `Handoffs/Server deploy handoff.docx` (Veer's; not read, not committed — a deploy handoff may hold hosts/credentials; Veer's call) |
| `origin/main` | `e202e29` | pushed 19:11Z |
| server `/health` `git_sha` | `e202e295c` | the deploy workflow rebuilt + recreated the app container at 19:11Z (it runs on EVERY push to main, no path filter — see §2.4); code identical to `e527fb2` |
| `origin/hinge-box-v2` | `adddc17` | v2 (`f41a0fe`) + v3 (`adddc17`) model-path code, both measured, NEITHER adopted, NOT merged — pushed as a record |
| server health | `degraded`, 6 reasons | by design: `MODEL DEGRADED` findings for Coventry City (λ 0.0006 at steps 1–5, fit `converged False`) from the loud detector; the alert probe has pushed it; nothing to fix |
| last served run | run 11, GW5, `nightly:2026-09-17`, SUCCESS (11:01Z Thu) | `built` None in the health block (a known display nit, see §10) |
| next promised runs | nightly Fri 2026-09-18 11:00Z (grace 25 min); then deadline slots t90 16:00Z, t30 17:00Z, t10 17:20Z | GW5 deadline **Fri 2026-09-18 17:30Z**; no deploys/restarts 16:00Z–18:00Z, nor across the ingest ticks 00:17 / 06:17 / 12:17 / 18:17Z, nor the 11:00Z nightly |
| suite on main | 424 passed, 1 skipped (last full run on main: after `a5c2b39`, 2026-09-16) | main has had docs-only commits since |
| suite on the branch | 433 passed, 1 skipped, 1 deselected | the deselected test is `Tests/test_live_deadline.py::test_extraction_reproduces_arm_record_full_cutoff` — it extracts 2025-26 at cutoff 5 against the arm record built WITHOUT the form and diverges by design; it passes only on a REBUILT record |

**Friday needs nothing from anyone.** The runs are scheduled, strict, served; the artefact (Coventry's runaway) is
loud on `/health` and the phone; the user's decision is that GW5 ships exactly like this.

**The one-paragraph story.** A promoted club with no history and a scoreless record makes the unregularised
Dixon-Coles MLE run off (Coventry attack −7.4, λ 0.0006). Three remedies were pre-registered and measured: a global
Gaussian prior (k = 4) — FALSIFIED (it compresses the strong end); a per-club hinge prior + plausibility box (v2) —
MARGINAL (pooled top-30 −1.5 SE, all of it 2025-26); the same with a promoted-club centre (v3) — MARGINAL (−1.35
SE, same clause). Every structural property held every time (unaffected cells bit-identical, every fit converged,
every λ inside [0.15, 6.0], the runaway gone). The residual is the reference's luck: in 2025-26 the record's
Sunderland runaway put ten of one club's players into a top 30 in weeks they scored, and removing a runaway that paid
off reads as a loss on a 30-item rank correlation. Conclusion (the user's and the prereg's): the centre is not the
lever; no fourth form without a new argument; let Coventry score. The code lives on the branch; the detector's LOUD
form is the live floor; the FATAL raise waits until the fit converges reliably.

---

## 1. Timeline, commit by commit (all on `main` unless marked; dates from the logs)

### 1.1 Multi-run schedule and the agent prompt (2026-09-12 → 13)
- `f99ffe2` proposals: `sold_for` NULL beyond step 0 explained (column comments); proof runs marked by source; hold-baseline design logged.
- `0c80ff3` design: run the model several times a week (`Logs/multi_run_schedule_design.md`).
- `6bb5bf5` multi-run schedule BUILT: `post_ingest` + `nightly` 11:00Z + `t90/t30/t10` as dispatcher policy (`eval/dispatch_policy.py`, `eval/deadline_dispatcher.py`; four `model_runs` columns: `kind`, `slot`, `knowledge`, `next_run_expected`-related; every answer says when it was built and what it knew — `_freshness` in `model_tools.py`).
- `be3bee6`, `871a697` logs.
- `61eb3e2` agent: `prompts/system_prompt.md` as a reviewed file (master plan 5.5); a tool-call failure contract instead of a 500.
- `ca3ee00`, `c69cb42`, `ef976b3` agent prompt lines from live testing (offer the nearest covered gameweek, never deliver it unasked; the preview IS the `set_my_squad(confirm=false)` call; an uncovered gameweek gets fact + timing + a one-sentence offer).

### 1.2 The Dixon-Coles cutoff-day finding and fix (2026-09-13)
- `bb312da` FINDING: every 2026-27 live build's steps ≥ 1 were the fit's STARTING POINT (home e^0.25 / away 1.0) — `get_fixtures` trained on `date_parsed < cutoff` (a timed cutoff against day-stamped dates) so the cutoff day's UNPLAYED fixtures (NaN goals) entered the training set and L-BFGS-B returned x0. In the backtest the same comparison admitted the cutoff day's RESULTS (a small leak, LEAKAGE item 7). explain_prediction designed (levels 1–2).
- `fd3b737` LEAKAGE item 7 measured; the as-of guard's blind spot (its truncation used the same comparison, so bit-identity there was structural).
- `43ed3fe` prereg for the fix (`Logs/dc_fix_prereg_2026-09-13.md`): ONE rule, defined once, used by the fit's filter and the guard's truncation; the bar before any number.
- `36f45b7` THE FIX: `dixon_coles.knowable_before(matches, cutoff)` = dated before the cutoff DAY and goals present; used by the training filter AND `eval/asof_reconstruction.py`; `_fit_dc_decay` RAISES on NaN goals ("the optimiser would silently return its starting point"); a strict degenerate-fit detector in `live_deadline.postflight` (all clubs at one λ / the starting point); the record REBUILT (canonicals → gap0 arm frames → record armlogs), `*_pre_dcfix` preserved and indexed SUPERSEDED (`eval/build_season_totals_index.py` `STALE_SUFFIXES` += `"pre_dcfix"`); fingerprint re-pinned (`Tests/test_walkforward_provenance.py`: `EXPECTED_SPEARMAN = 0.7453`, `EXPECTED_MAE = 1.0510`, `EXPECTED_ROWS = 165_401`); reference cells 2387 / 2325 / 2279 (drift checks only). Bar deviations recorded verbatim: rank endpoint 0.898 at one cell against a 0.90 bound; totals rose. **This adoption is a JUDGEMENT CALL, never a passed prereg** (`Logs/dc_fix_log_2026-09-13.md`).
- `0ca4b70` close-out: bar item 1 met on the image; the LIVE cold start found — Coventry City (0 GF in 3, no history) attack → −∞ and Hull City (0 GA in 3) defence → −∞, `converged False`; a server lock incident (a dispatcher tick hung ~13 h at interpreter exit holding the host flock; tick entrypoints now `os._exit`; the stuck container needed Veer's manual `docker rm -f` — the auto-mode classifier refuses remote writes from Claude).

### 1.3 Shrinkage attempt 1 — the k = 4 Gaussian prior (2026-09-13/14) — FALSIFIED
- `3f9c9fc` log: scheduler unblocked; the alias question (17 of 20 live clubs join the archive under their exact name; only the promoted three miss — Ipswich Town materially); shrinkage pre-registered (`Logs/dc_shrinkage_prereg_2026-09-13.md`).
- `e090ccb` outcome: k = 4 FALSIFIED (steps 1–5 top-30 sliced Spearman −0.0052 / −0.0065 in 2023-24 / 2024-25 against a bar of −0.005; `Logs/dc_shrinkage_log_2026-09-13.md`). Prior OFF: `SHRINK_K = 0`, `SHRINK_TAU = 1.40 * SHRINK_K` (objective bit-identical). KEPT on main from that prereg ("change B"): `ARCHIVE_NAME_ALIAS = {"Hull City": "Hull", "Ipswich Town": "Ipswich"}`, `canon_club()`, `NEW_TO_ARCHIVE = {"2023-24": {"Luton"}, "2024-25": {"Ipswich"}, "2026-27": {"Coventry City"}}`, `check_new_clubs(mc, predict_season)` (raises both ways: an undeclared club with no history, a declared club that has some). The strict extreme-strength detector was parked on branch `shrink-detector-strict`.

### 1.4 explain_prediction, alerting, term columns, the stored-terms path (2026-09-14)
- `ccb82ce` explain_prediction levels 1–2 (`explain.py` pure; `model_tools.explain_prediction`, `compare_predictions`); `a851d5d` proven in the image.
- `a837c38` alerting: `eval/health_alert.py` (host cron, stdlib only) → ntfy (`Logs/alerting_design_2026-09-13.md` §6 install, §7 blind spot).
- `c097603` `model_predictions` widened with 24 nullable term columns (ADD COLUMN IF NOT EXISTS; never backfilled; the INSERT names its columns); threshold-form shrinkage v1 pre-registered, design only (`Logs/dc_shrinkage_threshold_prereg_2026-09-14.md`, later SUPERSEDED). `dde0a23` proven on the live database (40 columns, 24 terms).
- `3cf11b1` `explain_prediction(run_id=...)` and `compare_runs` — the stored-terms path (why a prediction moved between two runs, term by term, with what each run knew); `2a8a70c` deployed and negatively proven on run 5 (positive proof needs two runs with stored terms — done on Tuesday, `Logs/explain_prediction_log.md`).

### 1.5 Agent prompt: the reasoning/presentation failures (2026-09-14/15)
- `6191e00` section 1: a claim in the question is not a given (check it, name the tool and the gameweek); two things are "the picks" (`get_picks` = FPL's confirmed picks for the LAST gameweek; the model's XI = the proposal for the NEXT); never explain a past choice from inference; the gameweek is part of the number; an answer must not disagree with itself; section 10 — how much of a breakdown to show.
- `8f6ffc2` "this week" = the next deadline's gameweek; comparisons are prose, one quantity, no grid; a conditional next run is stated as its condition; `compare_players` returns `first_gw`, `first_gw_e_points`, `first_gw_p_start`, `horizon_gws`, `built`, `next_run_expected`, `verdict_basis`, and `note_stale` when `first_gw < _current_gw()`.
- `a87666b` log with the four before/after `/chat` transcripts (archived in `Handoffs/scripts_2026-09-17/`).
- `696d383` the bonus level stated once per conversation (never a zero line); round a figure the same way throughout (section 9). KNOWN_ISSUES #19 CORRECTED: the penalty term is DEFINITIONAL (penalties MISSED, mostly exactly zero per row; Haaland's max 0.03 across 36 cutoffs), not "~50× too small"; its coupling with the 0.05 `penalty_share` fallback noted; the 2026-08-26 gate re-read (Brier +0.0024 / +0.0013 against +0.001, not 0.0001). **Do not reopen the penalty term** (a new prereg if ever).

### 1.6 Dispatcher: unconditional deadline slots; the crash (2026-09-15/16)
- `c975e26` the three deadline slots (t90/t30/t10) are UNCONDITIONAL (avoid a MISSING run); nightly/post_ingest stay gated on `master_gw >= gw − 1` (avoid a POINTLESS run) — "TWO GATES WITH TWO PURPOSES" in the docstring; under a stalled FPL the promise carries a certain t90 fallback (`expected_next` → `certain_kind/certain_slot/certain_at/certain_grace_min`) that `/health` checks; `freshness()` names the history gap (`history_gap(gw, history_through_gw)`). `46ac92a` proven in the image with a fake clock and the real stalled bootstrap (GW4 unconfirmed).
- `0b575ef` THE CRASH FIX: on 2026-09-15 the dispatcher crashed AFTER each build (`import config_roles` with the repo root off `sys.path`) so every slot re-fired and stayed RUNNING; fix = `sys.path.insert(0, str(REPO))` and `import config_roles as cr` at module load; `reconcile_from_db(state, rows=None)` settles RUNNING slots from `model_runs` on every tick; a slot RUNNING > `RUNNING_STALE_MIN = 90` min degrades `/health`; `main(argv=None)`; `_hard_exit`; end-to-end tick test. `1934983` the fix settled runs 7 and 9; `e8f9735` the incident report (the alert probe saw nothing to push: `/health` was `ok` throughout — the blind spot, §7 of the alerting design) and the correct reading of run 9's advice (level + dispersion, 9 of 11 overlap, Spearman 0.56; the Isak sale contaminated; not better decisions).

### 1.7 The loud detector (2026-09-16)
- `a5c2b39` `live_deadline.degraded_findings(frame, last_fit=None)`: a club's `team_lambda` outside `[LAMBDA_MIN, LAMBDA_MAX] = [0.15, 6.0]` at any horizon step, or `LAST_FIT["converged"] is False`, is a `MODEL DEGRADED:` finding — APPENDED to postflight findings, never raised; `model_tools._model_degraded_reasons(run)` turns them into `/health` reasons ("model degraded (run N, config): …"); the alert probe pushes; the build is served. User decision: the LOUD form is the floor; the FATAL raise (branch `shrink-detector-strict`) ships only once the fit converges on every build for a week. `bf691e3` proven in the image on Coventry's real λ; health degrades from the 11:00Z nightly onward.

### 1.8 Prereg v2 — hinge + box (2026-09-17)
- `e527fb2` design (`Logs/dc_shrinkage_threshold_prereg_2026-09-17.md`; v1 marked superseded: its hinge released completely at N = 10 and would let ten goalless matches run off again).
- branch `hinge-box-v2` `f41a0fe` the v2 form (§4 below); `3d7cbd8` + `60356f3` the execution log (`Logs/dc_shrinkage_v2_log_2026-09-17.md`): four implementation findings, the numbers, MARGINAL, not adopted.

### 1.9 Prereg v3 — the promoted-club centre (2026-09-17 evening)
- `a4ff959` design (`Logs/dc_shrinkage_v3_prereg_2026-09-17.md`); branch `adddc17` the v3 form; `f30eca5` the execution log (`Logs/dc_shrinkage_v3_log_2026-09-17.md`): MARGINAL, not adopted; `e202e29` where the code lives (branch pushed).

---

## 2. Server, ops and the pipeline (unchanged this session unless noted)

### 2.1 Machines and access
- Server: DigitalOcean `68.183.131.154`, `root`, key-only ssh with the repo-root `deploy_key_new` (gitignored — `git check-ignore -v deploy_key_new` before ANY `git add`; never print it; `~/.ssh` has no key). App at `/root/fpl-copilot`; Docker Compose stack: `fpl-copilot` (app + scheduler image; service `fpl-scheduler` for one-offs) and `fpl-postgres` (named volume `fpl_pgdata`); model data on volume `fpl-copilot_fpl_model_data` mounted at `/app/data`.
- The laptop (Windows 11, UTC−4) has no Postgres/Docker. DB proofs run remotely: `ssh -i deploy_key_new root@68.183.131.154 'cd /root/fpl-copilot && docker compose run --rm --no-deps -T fpl-scheduler uv run python -' < script.py` (`sys.path.insert(0, "squad")` inside).
- The Claude Code auto-mode classifier REFUSES remote writes over ssh (e.g. `docker rm -f`); Veer runs those. Read-only ssh (`docker compose ps`, `git log`, `cat`) is fine.
- `gh` is NOT installed on the laptop; watch deploys by polling `/health` for the SHA.

### 2.2 Scheduling on the server
- Weekly ingest: host cron `17 */6 * * *` (00:17 / 06:17 / 12:17 / 18:17Z) → `run_weekly_ingest.py`; status files + `/health` reasons (`weekly ingest FAILED`, `needs a human`, `never ticked`, `has not ticked for Nh`).
- Dispatcher: a 10-minute cron tick → `eval/deadline_dispatcher.py` → `eval/dispatch_policy.plan(now, events, state, master_gw)`. Kinds and windows: `DEADLINE_WINDOWS = (("t10", 0, 10), ("t30", 10, 30), ("t90", 30, 90))` minutes before the deadline; `NIGHTLY_HOUR_UTC = 11`; `POST_INGEST_QUIET_H = 6`; `ATTEMPTS = {"t10": 1, "t30": 2, "t90": 3, "post_ingest": 2, "nightly": 2}`; `GRACE_MIN = {"t10": 15, "t30": 25, "t90": 35, "post_ingest": 25, "nightly": 25}`; `DISPATCHER_STALE_MIN = 35`; `RUNNING_STALE_MIN = 90`; `TERMINAL = ("SUCCESS", "GAVE_UP")`. Deadline slots unconditional; nightly/post_ingest gated on `master_gw >= gw − 1`. Every run is STRICT. State file on the volume; `reconcile_from_db` on every tick.
- Alerting: `eval/health_alert.py` on the host (cron; env `/root/fpl-alert.env` with the ntfy server/topic; state file): `RATE_LIMIT_H = 6`, `DEBOUNCE_PROBES = 2`, `HEARTBEAT_UTC = (11, 5)`, `FINAL_SLOT_STATUSES = ("SUCCESS", "FAILED", "GAVE_UP")`, `TIMEOUT_S = 15`; pushes DEGRADED (reasons verbatim, debounced), changed/RECOVERED, slot outcomes once, ACTION REQUIRED once a day, a daily heartbeat, unreachable echo. Rule: alerting on `/health` only alarms on states `/health` can represent (the crash of 2026-09-15 was invisible to it until `RUNNING_STALE_MIN` existed).

### 2.3 `/health` (main) — fields
`status` (`ok` | `degraded`), `git_sha`, `model_versions`, `data_freshness_by_source`, `db_ok`, `last_run` {`run_id`, `gw`, `kind`, `slot`, `status`, `built`, `build_duration_s`, `freshness`, `next_run_expected` {`kind`, `slot`, `gw`, `at`, `condition`, `grace_min`, and under a stall `certain_*`}}, `reasons` (list). The branch adds `model_notes` (a list; informational).

### 2.4 Deploy pipeline — IMPORTANT
`.github/workflows/deploy.yml` runs on EVERY push to `main` (no path filter): ssh → `git pull` → `docker compose up -d --build --remove-orphans`. A docs-only push therefore rebuilds the image and RECREATES the app container (observed 19:11Z: `fpl-copilot Up 19 seconds`, `fpl-postgres Up 5 days`), and `/health.git_sha` moves to the new commit. So: every push to main is a deploy; time pushes outside the no-touch windows; check `/health.last_run.status` is not RUNNING first; verify the SHA afterwards. "Fixed" and "deployed" are different words.

---

## 3. Code map of `main` after this session (what to know to work on it)

### 3.1 `squad/dixon_coles.py`
- `knowable_before(matches, cutoff)` → boolean mask: `date_parsed` before the cutoff DAY and both goals present. Used by `get_fixtures` (`train_m = mc[knowable_before(mc, cutoff)]`) and by `eval/asof_reconstruction.py`. Never compare a timed cutoff against day-stamped dates anywhere else.
- `_fit_dc_decay(train_matches, all_teams, ref_date, half_life_days)` (main's signature): raises `ValueError` on NaN goals ("…without a result (NaN goals) — refusing to fit: the optimiser would silently return its starting point…") and on an empty set; parameters `[atk (nt), dfc (nt), hadv, rho]`, `x0 = 0` with `hadv = 0.25`, L-BFGS-B, finite-difference gradients; `LAST_FIT` (a module dict) = `n_train, n_teams, iterations, converged, max_abs_attack, max_abs_defence, home_adv, rho, ref_date, shrink_k (0), shrink_tau (0.0), n_eff_min, n_eff_min_club`. `SHRINK_K = 0`, `SHRINK_TAU = 1.40 * SHRINK_K` (a `+ 0.0` in the objective).
- Identity inside the fit is the ARCHIVE-CANONICAL name (`canon_club`; `ARCHIVE_NAME_ALIAS`); fixture OUTPUT keeps the live names (assembly's `TEAM_MAP` join unchanged). `check_new_clubs(mc, predict_season)` + `NEW_TO_ARCHIVE`.
- `get_fixtures(predict_season, cutoff_date, predict_dates, odds_available_until, …)`: `teams = sorted(set(mc.home) | set(mc.away))` — EVERY club in the archive across ALL seasons (34 in a 2025-26 fit, including clubs from later seasons with zero training rows: "phantoms" that stay at x0 in the plain fit). `_load_matches(predict_season)` reads `data/history/odds_all_seasons.parquet` (2016-17 … 2025-26) or `odds_all_seasons_with_<season>.parquet` for 2026-27+ (archive + FPL fixture slice; the laptop copy of 2026-27 files is stale — sync down before trusting it).
- Gauge fact (measured 2026-09-17): the likelihood is invariant to `atk + c / dfc − c`; L-BFGS-B from zeros keeps `sum(atk) = sum(dfc)` (to ~1e-4); in that gauge the league mean attack over a season's 20 clubs is ≈ +0.09 (all 34 clubs) / ≈ +0.20 … +0.33 (the 20 league clubs; the branch's `league_mean_attack`). "Attack 0" is NOT the league rate.

### 3.2 `squad/live_deadline.py`
- `MODEL_DEGRADED = "MODEL DEGRADED:"`; `LAMBDA_MIN, LAMBDA_MAX = 0.15, 6.0` (bounds justified in the code comment from the record's λ distribution: min 0.188 / 0.408, 0.1st pct ≥ 0.199, 99.9th ≤ 3.95, max 4.32; the only cells ever outside were the five 2024-25 cutoff-2 Ipswich cells at 0.001 — a runaway lands at 0.001, not near 0.15; never widen the box for a bad state); `MIN_FRAME_ROWS = 300`.
- `degraded_findings(frame, last_fit=None)` → list of strings (EXTREME per horizon step naming club and λ; NOT converged with iterations and max|attack|/|defence|). `postflight(frame, season, gw, strict=False, horizon=1)` does `findings.extend(degraded_findings(frame))` — never `_finding` (so never raised, even strict). The DEGENERATE detector (all clubs at one λ / the starting point) IS strict (`_finding`).
- `preflight`, `build_deadline_frame(season, gw, strict, verbose, config, horizon)`, `compare_to_canonical(frame, season, gw, canonical_path, allow_only_live, step)` unchanged.

### 3.3 `model_tools.py`
- `health()` (see §2.3); `MODEL_DEGRADED_PREFIX`; `_model_degraded_reasons(run)` parses `strict_findings` (JSONB as dict or string; unreadable → no reason) and prefixes "model degraded (run N, config): ".
- `compare_players(player_id_a, player_id_b)` (§1.5 fields); `explain_prediction(player_id, gw=None, run_id=None)`, `compare_predictions(a, b, gw=None)`, `compare_runs(player_id, gw, run_id_a, run_id_b)`; helpers `_frame_raw()` (the latest run's raw frame from the volume), `_check_sidecar(frame_p, cutoff)`, `_rows_from_db(run, config, gw)`, `_explain_from_run(run_id, player_id, gw)`.
- `explain.py` (pure): `TERMS` (nine term/column pairs), `CORE`, `CONSTANT_LABELS` (model / constant / rule labels from a fixed list), `LEAGUE_AVG_LAMBDA = 1.40`, `PEN_FALLBACK = 0.05`, `SUB_CHANCE = 0.30`, `TOL = 1e-6`, `reconcile(row)` (identity re-asserted per row; failure is a finding), `step_is_degenerate(step_rows)`, `breakdown(row, step_rows=None)`, `render(bd)`, `compare(a, b, label_a, label_b)`.
- `db_write.py`: `TERM_REAL_COLS` (the nine real terms + …), `TERM_COLS = TERM_REAL_COLS + ["understat_id", "n_fixtures"]`, `PRED_INSERT_COLS`, `prediction_rows(run_id, config, f)`, `prediction_insert_sql(columns)`; DDL `ADD COLUMN IF NOT EXISTS`; rows before 2026-09-14 are NULL in the term columns (never backfilled; the stored-terms path says so).
- `agent.py`: tool schemas for `explain_prediction` (with `run_id`), `compare_predictions`, `compare_runs`; `compare_players` description. `prompts/system_prompt.md`: sections 1 (grounding rules), 3 (conditional next run), 9 (rounding consistency), 10 (presentation; the bonus-level clause). Edit the FILE, not code; `Tests/test_agent_prompt.py` pins ~24 phrases.

### 3.4 `eval/`
`dispatch_policy.py` (§2.2; functions `parse_iso, iso, next_deadline, empty_state, _slot, _done, _attempts, deadline_window, plan, expected_next, record_outcome, health_reasons, _fmt, freshness, history_gap`), `deadline_dispatcher.py` (`reconcile_from_db`, `main(argv=None)`, `_hard_exit`, `run_build` using `cr.PRODUCTION_CONFIG`), `health_alert.py` (§2.2), `build_season_totals_index.py` (`STALE_SUFFIXES` incl. `"pre_dcfix"`; `EXPECT_ARMS_CHIP`, `EXPECT_REFERENCE_CHIP = {"2023-24": GAP0_TC2_2324, …}`, `REFERENCE_ARM` all `gap0_tc2`; the `preserved` suffix threading), `asof_reconstruction.py` (the standing leakage guard; `--season --cutoffs --config --reference record`), `walkforward_season.py` (`walk_forward(season, cutoffs=None, horizon=6, verbose=True, save_path=None)`; stamps `synthetic_lambda_active` etc.; ONE `get_fixtures` call per cutoff), `walkforward_arms.py`, `run_arms_full_system.py`.

### 3.5 Tests (48 files; the ones this session added or changed)
`test_dixon_coles_boundary.py` (9: `knowable_before`, the NaN raise message "without a result" + "starting point", the guard), `test_dixon_coles_shrinkage.py` (main: change B + the loud-detector tests + a record test that SKIPS without a `dc_shrink_k` stamp — on the branch this file is rewritten, §4.5), `test_model_degraded_health.py`, `test_live_deadline.py` (14: parity family incl. `test_parity_one_cutoff_bit_identical`, `test_parity_combined_config_bit_identical`, `test_extraction_reproduces_arm_record_full_cutoff` (GW5), `test_live_horizon6_baseline_all_steps` / `_combined_all_steps` (GW20)), `test_asof_reconstruction.py` (4), `test_explain_prediction.py` (11), `test_explain_runs.py` (4), `test_db_write_terms.py` (5), `test_health_alert.py` (12), `test_dispatch_policy.py` (21 incl. the stalled-FPL case with a fake clock), `test_deadline_dispatcher.py` (4 incl. an end-to-end tick), `test_compare_players_gw.py` (2), `test_agent_prompt.py` (5), `test_walkforward_provenance.py` (the fingerprint pins).

---

## 4. Branch `hinge-box-v2` — the v2 + v3 model-path code, precisely (NOT on main, NOT adopted)

Two commits on top of `main@e527fb2`: `f41a0fe` (v2) and `adddc17` (v3). Files: `squad/dixon_coles.py`,
`squad/live_deadline.py`, `model_tools.py`, `Tests/test_dixon_coles_shrinkage.py`, `Tests/test_model_degraded_health.py`.
To work on it: `git checkout hinge-box-v2` — but NEVER while any build queue is live (§9). Its suite: `uv run pytest
Tests -q -p no:cacheprovider --deselect Tests/test_live_deadline.py::test_extraction_reproduces_arm_record_full_cutoff`
→ 433 passed, 1 skipped (the record test keyed to `*_pre_hinge`).

### 4.1 Constants (`squad/dixon_coles.py`)
```
SHRINK_TAU0 = 1.40 * 4                # 5.6: four league-average pseudo-matches at zero evidence
SHRINK_N = 10                         # effective matches at which the hinge has fully released (0 = hinge off)
ATK_DFC_BOUND = float(np.log(4.0))    # the plausibility box, ±ln 4 = 1.3863 (0.25x .. 4x); None = box off
MU_PROMOTED_ATTACK = -0.31            # v3: the hinge's centre for a promoted club (centred coordinates)
MU_PROMOTED_DEFENCE = 0.20
```
The long comment above them carries: the k = 4 history, the two parts (A hinge = a prior about evidence, B box = a
bound about football), the scoreless table, the identifiability paragraph, the phantom-club paragraph, the v3
derivation, and "a different tau0 / N / bound / centre is a NEW pre-registration".

### 4.2 `_fit_dc_decay(train_matches, all_teams, ref_date, half_life_days, prior_teams=None, promoted_teams=None)`
1. NaN / empty refusal (main's messages, verbatim).
2. `idx`, `nt`, `h`, `a`, `hg`, `ag`, `age`, decay weights `w = exp(−ln2/half_life · age)`.
3. `n_eff` per club = Σ of its matches' weights. `in_prior` = mask of `prior_teams` (None → all). `tau_i = SHRINK_TAU0 · clip(1 − n_eff/SHRINK_N, 0, ∞)` for `in_prior` clubs, else 0 (and all 0 if `SHRINK_N` falsy). `hinge_on = any(tau_i > 0)`.
4. v3: `promoted = set(promoted_teams or ()) ∩ in_prior clubs`; `mu_a[i] = MU_PROMOTED_ATTACK` if promoted else 0; `mu_d` likewise.
5. `pri = np.where(in_prior)[0]`; `centred(p)` = `[atk − atk[pri].mean(), dfc − dfc[pri].mean()]` (the LEAGUE mean, over the predict season's clubs only — never over the 34-club team list; a phantom club with zero rows would otherwise be a free slack variable for the mean).
6. `nll(params)`: the DC negative log-likelihood (Poisson + the ρ correction on 0-0 / 0-1 / 1-0 / 1-1, τ clipped at 1e-10) weighted by `w`; if `hinge_on`: `+ 0.5 · Σ tau_i · ((c_atk − mu_a)² + (c_dfc − mu_d)²)`. Gauge-invariant (the centring), so the fit stays in the record's gauge; when no `in_prior` club is below N the objective is bit-for-bit the unregularised one (the `if` is skipped).
7. `res = minimize(nll, x0, method="L-BFGS-B")` — the record's optimiser, unbounded. `method = "L-BFGS-B"`, `boxed_refit = False`.
8. THE BOX, only if `max(|centred(res.x)| over pri, attack and defence) > B`: linear inequality constraints `A p + B ≥ 0` with one row per league club per coordinate per sign: row for club i's attack = `e_i − (1/n_league)·1_pri` (so the constraint is on the CENTRED value), same for defence, stacked with their negatives; `minimize(nll, x0, method="SLSQP", constraints=[{"type": "ineq", "fun": λp: A@p + B, "jac": λp: A}], options={"maxiter": 1000})`; `method = "SLSQP"`, `boxed_refit = True`. (On the record the box never binds — 0 of 114 cutoffs under v2 and v3; the hinge alone holds Ipswich 2024-25 cutoff 2. It binds only at ≥ 7–8 goalless matches for a no-history club.)
9. `at_bound[club] = ["attack" and/or "defence"]` for league clubs whose |centred value| is within 1e-5 of B.
10. Gate (e): `est` = league clubs with `n_eff ≥ SHRINK_N` not at a bound; `min_margin_to_bound` = min over `est` of `B − |centred|` (attack and defence), with `min_margin_club` "Club attack|defence".
11. `LAST_FIT` (cleared and refilled): `n_train, n_teams, iterations, converged, method, boxed_refit, max_abs_attack, max_abs_defence, max_abs_centred_attack, max_abs_centred_defence (league clubs), league_mean_attack, league_mean_defence, n_league, home_adv, rho, ref_date, shrink_tau0, shrink_n, bound, n_eff_min, n_eff_min_club (over prior clubs), clubs_below_n {club: {n_eff, tau, centre: "promoted"|"league"}}, promoted [list], mu_promoted {attack, defence}, hinged_not_promoted [list], at_bound {club: [coords]}, min_margin_to_bound, min_margin_club`. These stamps are how a wrong-code build was caught (§9).
12. Returns `(x, idx, nt)`.

### 4.3 `get_fixtures` on the branch
After `train_m`/`ref`: `cur = mc[mc.season == predict_season]`; `prior_teams = sorted(cur.home ∪ cur.away)`;
`earlier = sorted(s for s in mc.season.unique() if s < predict_season)`; `promoted_teams` = `prior_teams` not in the
LATEST earlier season's clubs (canonical names: 2026-27 → `Coventry City`, `Hull`, `Ipswich`), `[]` if no earlier
season; `_fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS, prior_teams=prior_teams, promoted_teams=promoted_teams)`.

### 4.4 `live_deadline.py` and `model_tools.py` on the branch
- `MODEL_NOTE = "MODEL NOTE:"` ("visible on the run and /health; never degrades, never pushes, never raises").
- `degraded_findings`: EXTREME per step — UNCHANGED and still applies to a clamped club (the bounds are the bounds); NOT converged — the message names `LAST_FIT["method"]`; then MODEL NOTES: (i) "hinge prior active (evidence below N effective matches; promoted-club centre attack −0.31 / defence 0.2): Club (n_eff, tau, centre …)", (ii) "a club below N … that is NOT promoted (centre = the league mean, v2's form): … — the evidence table said this never happens; understand the club", (iii) "Dixon-Coles strength CLAMPED at the plausibility bound (+-ln 4 of the league rate): Club (attack/defence) — … the box is holding … served". The reconciliation decided 2026-09-17: CLAMPED is the box working, never degraded; the fatal raise, when it ships, raises on EXTREME and non-convergence only.
- `model_tools.py`: `MODEL_NOTE_PREFIX`, `_prefixed_findings(run, prefix)` (shared parser), `_model_notes(run)` → `"run N, config: <note>"`, `_model_degraded_reasons` rewritten on the parser; `health()` adds `"model_notes": [...]` (informational, never a reason).

### 4.5 Tests on the branch (`Tests/test_dixon_coles_shrinkage.py`, 29 tests incl. 1 skip; `Tests/test_model_degraded_health.py` +1)
Synthetic league helpers `_m`, `_league(rng, n_rounds, teams)`, `_newcomer_rows(n_scoreless)` (club "N": n scoreless matches, alternating home 0-2 / away 1-0), `_fit(rows, **kw)`. Tests: the prereg table at n = 3 (centred attack in [−0.80, −0.35], L-BFGS-B, hinged) / 8 / 12 (exactly −ln 4 ± 1e-4, `at_bound == {"N": ["attack"]}`, `method == "SLSQP"`, gauge kept `|Σatk − Σdfc| < 1e-3`); the same newcomer runs off with the form OFF (monkeypatched `SHRINK_N = 0`, `ATK_DFC_BOUND = None`: attack < −3); a cutoff with no poor club is `np.array_equal` to the plain fit; the hinge scoped to `prior_teams` (an old club below N outside it → bit-identical; inside → hinged); a PHANTOM club (zero rows, outside `prior_teams`) stays at exactly 0.0 while another club is hinged; the box binds only on the runaway club (every other centred parameter > 0.2 from a bound; `min_margin_club` not "N"); v3: a no-rows promoted club sits exactly at (−0.31, +0.20) and a non-promoted one at (0, 0) with `promoted == ["P"]`, `hinged_not_promoted == ["Q"]`; the promoted centre lowers the n = 3 newcomer by 0.10–0.35 v centre 0 and at n = 8 both are boxed; nobody promoted → bit-identical to v2; change B (canonical names, the guard, declared new clubs exact); `test_fixture_output_keeps_live_names` (runs `get_fixtures("2026-27", cutoff "2026-09-18 19:00")` on the laptop's 2026-27 extension file: live names in the output, `converged True`, `promoted == ["Coventry City", "Hull", "Ipswich"]`, every λ inside [0.15, 6.0]); the loud detector (EXTREME appended not raised; non-converged; CLAMPED/hinged are notes and a clamped club at λ 0.14 is still EXTREME); the record test (gate (c) as a permanent test: every canonical's λ in [0.15, 6.0]) SKIPS until `data/walkforward_h6_2025_26_pre_hinge.parquet` exists. `test_model_notes_reach_health_as_information_not_reasons`.

### 4.6 Why it cannot merge as-is
`test_extraction_reproduces_arm_record_full_cutoff` extracts 2025-26 at cutoff 5 against `data/arms_gap0/walkforward_h6_2025_26_both.parquet`
(built without the form); cutoff 5 is an affected cell (Sunderland n_eff 3.9). Merging requires the record rebuild (§7). The GW20 parity tests (an unaffected cell) stay bit-identical — the structural claim holds.

---

## 5. The pre-registrations and their results (headline numbers; the logs hold every table)

### 5.1 v2 — `Logs/dc_shrinkage_threshold_prereg_2026-09-17.md` → `Logs/dc_shrinkage_v2_log_2026-09-17.md`
- Form: per-club hinge `tau_i = 5.6 · max(0, 1 − n_eff_i/10)` + box ±ln 4; the four implementation findings (all before any number): (a) identifiability → centred parameters, SLSQP for the box; (b) the hinge scoped to the predict season's clubs (a club relegated two seasons back sits at n_eff ≈ 9.5 in every fit); (c) CLAMPED = MODEL NOTE, EXTREME unchanged; (d) the phantom club (Ipswich in a 2023-24 fit, zero rows, defence driven to +26 as a slack variable for the mean; box then clamped it) → centre and box over the league's clubs only. The first build's numbers (seen before the (d) fix) are recorded as superseded.
- Endpoint (170 affected cells: 2023-24 cutoffs 1–11 Luton (+ Sheffield United at c1, 1.5 % of tau0), 2024-25 1–12 Ipswich, 2025-26 1–11 Sunderland; steps 1–5; v2 − record): starters +0.0022 (SE 0.00106, +2.1 SE); top-30 −0.0093 (SE 0.0062, −1.5 SE); per season top-30 −0.0042 / +0.0016 / −0.0264 (2025-26 ≈ −2.4 own-SE). Structural: 80 unaffected cutoffs bit-identical; 114/114 converged (max 173 it); box refits 0; λ min 0.408 / 0.508 / 0.455 (record 0.408 / **0.0007** / 0.188); nearest established club 0.64 / 0.82 / 0.89 from a bound; step-0 |Δ p_cs| max 0.046 / 0.058 / 0.065 with an affected club, ≤ 0.0016 without (the shared-parameter coupling: hadv/rho/the league mean — v2's wording "bit-identical" for those rows was an overstatement; v1 had it right). Sensitivity rows (N 6 / 15, tau0 2.8, box ln 3 / ln 6): the same pattern. Verdict: not falsified by the letter; MARGINAL under the user's condition → NOT adopted; Friday ships as today.
- Driver analysis: 2025-26's loss is the record's Sunderland runaway having been lucky (121 top-30 slots in the record, up to ten in one cell, v the form's 69); 2023-24's is Luton's slots 13 → 34 under the league-mean centre, underperforming.

### 5.2 v3 — `Logs/dc_shrinkage_v3_prereg_2026-09-17.md` → `Logs/dc_shrinkage_v3_log_2026-09-17.md`
- The centre: 9 cohorts, 27 promoted clubs, plain end-of-season fits centred over the season's 20 clubs: attack −0.307 (sd 0.221, se 0.042; 0.74×), defence +0.203 (sd 0.196; 1.22×); mid-season the same; leave-one-cohort-out within 0.02; returners no better; separate centres; FIXED constants −0.31 / +0.20. The outcome rule fixed before the number: FALSIFIED (pooled slice < −2 SE or a structural gate), MARGINAL (pooled slice in [−2, −1) SE, or a season < −2 own-SE, or a promoted-club tell), PASS.
- Endpoint (same 170 cells; v3 − record): starters +0.0018 (+2.15 SE); top-30 −0.0075 (−1.35 SE); per season top-30 −0.0049 (−0.5) / +0.0022 (+0.4) / −0.0205 (−1.7 own-SE). All structural gates held (margins 0.66 / 0.82 / 0.89; step-0 max 0.071 with, ≤ 0.0013 without; box refits 0; 114/114 converged). Verdict: **MARGINAL** (the pooled top-30 clause only). Sensitivity: six-cohort centre (−0.31/+0.16) −1.1 SE; halved −1.1 SE (2025-26 −2.5 own-SE); attack-only −1.5 SE (2025-26 −2.1 own-SE) — every centre MARGINAL by the same clause; 2025-26 stays in [−0.02, −0.03] at every centre; 2023-24 did not respond (Luton 34 → 23 slots yet net −0.0049).
- Conclusion (the user's, and the prereg's): the centre is not the lever; no fourth form without a new argument; let Coventry score.

### 5.3 The prereg discipline that governed all of it (do not drop)
Bars stated before any number and NEVER amended; adoption never on season totals; the reference does not move (always the record); "a too-clean result is a tell"; tells are stop-and-investigate; falsified or marginal → not adopted and Friday ships as today; a different constant is a new pre-registration; judgement calls are named as such, never as passed preregs; sensitivity rows are informational, never a re-choice; provenance stamps in every artefact, checked before a number is read.

---

## 6. The scripts archive — `Handoffs/scripts_2026-09-17/` (README inside maps each file to its log)
The reference builds (`ref_*.parquet`, ~16 MB each) were not archived; `refbuild_v2.py <season>` (env `REF_PREFIX`) regenerates one in ≈ 12 min (three in parallel), `v2_endpoint.py` (env `V2_PREFIX`) recomputes the endpoint + gates + the v3 rule in ≈ 1 min per prefix, `v2_summary.py` prints one line per prefix, `top30_driver.py` the driver analysis, `rebuild_hinge.ps1` the (never run) adoption rebuild. Run them from the checked-out BRANCH for v2/v3 builds and from main for plain-fit probes; and never switch branches while a queue is live.

---

## 7. If the form is ever adopted anyway (a judgement call — name it as one)
Only with Veer's explicit go. Steps, in order, from the branch: (1) `rebuild_hinge.ps1 -Season <s>` for 2023-24, 2024-25, 2025-26 (each: preserves `data/walkforward_h6_<tag>.parquet`, the gap0 arm frames + `.json` sidecars, the record armlogs as `*_pre_hinge`; canonical → arms → armlogs; ≈ 1.5 h total in parallel); (2) guards: `eval/asof_reconstruction.py` at all 38 cutoffs of 2025-26 both configs + the 2023-24 / 2024-25 samples (`guard_dcfix.ps1` pattern; ≈ 1 h); (3) `uv run pytest Tests/test_live_deadline.py Tests/test_asof_reconstruction.py` by name — must be green on the rebuilt record; (4) full suite; (5) re-pins: `Tests/test_walkforward_provenance.py` (`EXPECTED_SPEARMAN`, `EXPECTED_MAE`; rows unchanged at 165_401 — the record test in `test_dixon_coles_shrinkage.py` un-skips once `*_pre_hinge` exists), `eval/build_season_totals_index.py` (`STALE_SUFFIXES` += `"pre_hinge"`, `EXPECT_ARMS_CHIP` / `EXPECT_REFERENCE_CHIP` for the superseded `*_pre_hinge` cells, the new gap0_tc2 cells as drift checks only); (6) merge to main, push (= deploy) outside every window with no RUNNING build; (7) verify the container: `/health.git_sha`, `converged True` on the live fit, MODEL DEGRADED reasons gone, MODEL NOTES naming the hinged clubs and the centre. Season totals reported, never judged.

---

## 8. Standing rules Veer set this session (restated; do not drop)
- Model path untouched except by pre-registered changes; every model-path change needs the parity family (`Tests/test_live_deadline.py`) and `Tests/test_asof_reconstruction.py` green, by name, plus the suite, before any push.
- "Fixed" and "deployed" are different words: confirm the container via `/health.git_sha`.
- No deploys/restarts across an ingest tick (00:17 / 06:17 / 12:17 / 18:17Z), a scheduled slot (nightly 11:00Z), or deadline −90 min … +30 min; never with a live build RUNNING; a laptop rebuild and a server build must not overlap a deploy.
- Bars before any number, never amended; adoption never on season totals; silent fallbacks are the enemy; alerting on `/health` only alarms on states `/health` can represent.
- Never commit keys; never print secret values; `git check-ignore -v deploy_key_new` before any `git add`.
- Stop and leave it unpushed if something surprises you; report outcomes as they are (a failed bar is a failed bar; a judgement call is named).
- Unpushed work is how things get lost: tidy it, push docs, push branches as records, and say where the code lives.
- Do not reopen the penalty term (definitional; a new prereg if ever). Do not act on the Isak-sale advice reading (contaminated). Keep the v2 branch intact.

---

## 9. Gotchas learned this session (cheap to keep, expensive to relearn)
- **Never switch git branches, or edit a model module, while a build queue is live**: each queued build is a fresh process importing whatever is on disk; a sensitivity build silently ran the record's plain fit after a checkout; caught only by the `LAST_FIT` stamps. Check the stamps before reading any build's numbers.
- A push to `main` is a deploy (rebuild + container recreate), docs or not.
- Bash-tool heredocs: embedded Python with `\'` / `\n` / `\f` gets mangled (a path `C:\dev\fpl-copilot` inside a heredoc became `C:\devpl-copilot`) — write scripts with the Write tool; a `git commit -m "$(cat <<'EOF' … EOF)"` message containing an apostrophe can fail to parse ("unexpected EOF") — use `git commit -F msgfile`.
- Foreground `sleep` is blocked (a wait loop returned instantly); use background `until` loops with `run_in_background`.
- Windows console is cp1252: `sys.stdout.reconfigure(encoding="utf-8")` in scripts that print λ/Δ.
- PowerShell `Start-Process -ArgumentList` splits space-separated strings; pass comma lists.
- The auto-mode classifier refuses remote writes over ssh (`docker rm -f`); Veer does those. `gh` is not installed.
- `tail -N` can cut a needed first line; the swap-pairing of fixtures by identical λ values mis-pairs fixtures with identical odds — pair by the fixture calendar (the stack's kickoff windows) instead.
- The fit's team list spans every archive season: a club from a LATER season is a phantom with zero rows; any statistic "over all clubs" in the fit is wrong — use the predict season's clubs.
- The bonus model has 1e-15 floating-point noise in `pred_bps` between runs (seen once in an unaffected cutoff); `e_points` unaffected.
- The suite takes ~5 min alone and ~21 min while six builds run.

---

## 10. Open items and what comes next
1. **Coventry / the cold start (KNOWN_ISSUES #25, open).** Nothing to do; let them score. When the live fit converges on every build for a week, the FATAL raise (branch `shrink-detector-strict`) can ship — with the form NOT adopted that day is when Coventry (and Hull's defence) have enough evidence, not before. If a club ever reaches seven goalless matches the box on the branch is the ready answer (a judgement call).
2. GW5 Friday 2026-09-18: nightly 11:00Z, t90 16:00Z, t30 17:00Z, t10 17:20Z; deadline 17:30Z. The runs will carry the degraded findings. Watch the phone (the probe) rather than the terminal.
3. After GW5: the run-to-run positive proof of the stored-terms path is done (Tuesday); the Tuesday checks (`Logs/dc_fix_log_2026-09-13.md` §14, `Logs/multi_run_schedule_design.md` §11–12) are recorded.
4. `Handoffs/Server deploy handoff.docx` — untracked; Veer decides (check it for credentials before it ever goes to GitHub).
5. `last_run.built` shows `None` on `/health` for run 11 while `freshness` is present — a display nit, not investigated.
6. Squad-state step-5 MIP wiring not started (`Logs/squad_state_log.md` §7); term columns never backfilled (by design); the alerting blind spot (§7 of `Logs/alerting_design_2026-09-13.md`) is narrowed by `RUNNING_STALE_MIN`, not closed.
7. Memory files (Claude's, outside the repo) updated this session: `fpl-dc-degenerate-live-fit.md` (the whole arc), `fpl-no-branch-switch-during-builds.md` (feedback), `MEMORY.md` index.
