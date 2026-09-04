# The app wired to the model — 2026-09-04

Replaces the naive Phase-1 predictions. Commits 901f912 (+ two NA-handling
fixes). Old tools.py/predict_naive untouched as rollback. No model, build,
or pipeline-step changes — laptop suite 229 green after, parity bit-identical.

## What the REAL frame corrected in the schema sketch

1. **The grain is (element, TARGET gw) at ONE cutoff — there is no step
   dimension.** 3,774 rows per config = 629 players × 6 target gameweeks,
   all seen from the deadline cutoff; horizon_step is derived (gw − cutoff).
   The sketch's (element, gw, step) would have double-keyed it.
2. **The frame carries NO price.** Prices join from master+skeleton at solve
   time. Price lives on model_picks (price at solve) and players_live, never
   on predictions.
3. **model_version exists nowhere as a field.** The honest version is the
   git SHA plus the frame's ~20 config-stamp columns (arm, bonus_mode,
   props_active, train_seasons, …). model_runs stores git_sha + the full
   stamp as JSONB; answers expose "git_sha/config" (e.g. 89f6406/combined)
   and the stamp stays queryable.
4. **Transfers cannot exist yet** — free-pick solves only (no tracked squad
   state). model_transfers is created and stays empty; picks rows say so.
5. The frame also carries the full component decomposition (pts_goals,
   pts_cs, p_dc_hit, team_lambda, …) — predictions keeps the queried subset
   typed (e_points, e_minutes, p_start, p_60plus, p_play_any, e_goals,
   e_assists, p_cs, exp_bonus, e_points_core); the parquet on the volume
   remains the full-fidelity record.

## Schema (all created by db_write.ensure_schema)

model_runs (run_id, season, gw, finished_at, status SUCCESS/FAILED,
recovered, git_sha, model_stamp jsonb, strict_findings jsonb,
credits_remaining, note) — one row per pipeline execution, FAILED rows
included so /health can see them.
model_predictions (run_id, config, element, gw, cutoff, horizon_step, …) —
**append-only per run, never overwritten**: the season accumulates a live
track record.
model_picks (run_id, config, element, role CAPTAIN/VICE/start/bench,
bench_order, price_tenths, e_points).
model_transfers (empty until a squad state exists).
players_live (element, name, position, team, price_tenths, status, chance,
news, updated_at) — refreshed each run. The July `players` table is left
in place, unused (rollback).

**Configs**: every child row carries config ∈ {combined, baseline}.
combined = production — every user-facing default reads it explicitly;
baseline is reachable ONLY via get_picks(shadow=true), which also returns
the element-set diff vs production. The two cannot be conflated by omission.

## The scheduler write + its failure contract

run_live_deadline, after build+solve, calls db_write.write_run (predictions
×2 configs, picks ×2, players_live refresh, stamp, findings, credits). If
the WRITE fails after a successful build: its own status-file section
("frame exists on the volume but Postgres is STALE"), non-zero exit (the
dispatcher counts a failed attempt and retries — the build is idempotent),
and /health reports the missing run. On any run failure,
db_write.write_failed_run leaves a best-effort FAILED row so /health can
name it even if the status file is never read.

## The reads (agent tools, model_tools.py)

resolve_player / list_players / get_player_card (players_live + prediction),
get_prediction(player_id, gw?) — one gw or the whole horizon, with
model_version/built_at/recovered on every answer; compare_players(a, b);
get_picks(gw?, shadow?) — XI, captain, vice, bench order;
get_best_squad(budget?) — the STORED production solve at the full budget (a
pure DB read), a real MIP at any other budget (documented deviation from
"first four are DB reads": a custom budget cannot be answered from stored
rows honestly); optimise(lock/ban/budget) — the production single-gw MIP
(gapRel=0) on data/live/_tmp_frame_combined.parquet from the volume.

**Constrained solve cost on the server: 0.9s** (ban Haaland + budget 95.0;
constraints verified honoured — banned player absent, cost 95.0, captain
falls to Foden, Cherki enters at the discount). It is fast because optimise
is the single-gw XI+captain MIP — the production free-pick convention — not
the 22s six-gameweek transfer MIP, which needs a squad state that does not
exist yet. **During a solve the chat request blocks** (~1s now, tens of
seconds if the 6-gw MIP arrives later); FastAPI's threadpool keeps serving
other requests (/health etc.) meanwhile. No job queue — stated plainly.

## /health (master plan contract)

{status, git_sha (serving code), model_versions (per config, from the run
that produced the predictions — deliberately distinct from the serving
sha), data_freshness_by_source {model_run (gw, built_at, age_hours,
recovered), players_live, frame_on_volume, next_deadline (bootstrap, cached
10 min, 5s timeout)}, db_ok, last_run, reasons}. Degrades on: DB
unreachable; no successful run recorded; inside T-90 of the next deadline
with no run for that gw; most recent run FAILED (with its note). All four
states exercised through the real code paths on the server:
- fresh:  status ok, reasons []
- no-run: "no successful pipeline run recorded at all"
- late:   "pipeline has not run for GW4 and its deadline is 30 min away"
- failed: "most recent run FAILED (GW4, …): strict preflight raised: …"

## Backfill + verify

GW3 recovery backfilled as run_id 3: recovered=true, git 89f6406, note
pointing at GW3_RECOVERY_provenance.json, 7,548 prediction rows, both
squads with roles/bench order from the shadow record, 629 players_live,
frame + prices staged on the volume for optimise().

- "Who should I captain for GW3" answers **Erling Haaland** from Postgres
  (get_picks: captain Haaland, vice Foden, cost 99.9, recovered flag
  carried). The /chat HTTP path is wired end to end but returns 500 at the
  Anthropic call: **the server's ANTHROPIC_API_KEY is invalid (401)** — the
  standing key-rotation item. USER ACTION: put the new key in
  /root/fpl-copilot/.env and `docker compose up -d` (recreate re-reads
  env_file). No code change needed.
- /health over HTTP: status ok, git_sha 3c66dc851, model_versions
  89f6406/{combined,baseline}, freshness populated, db_ok true.
- Laptop suite 229 green, parity family bit-identical (the app half touched
  nothing on the model path).

Known wart: two rolled-back backfill attempts burned run_id 1-2 (serial
sequence); run_id 3 is the first row. Harmless.
