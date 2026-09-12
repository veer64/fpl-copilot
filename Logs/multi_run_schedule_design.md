# Design — run the model several times a week (2026-09-12, DESIGN ONLY, nothing built)

The brief: ~5 runs per gameweek instead of one — nightly runs once FPL has
confirmed the previous gameweek, then T-90 / T-30 / T-10 on deadline day —
every answer carrying when it was built and what it knew. Seven decisions are
settled in the brief; this document turns them into a schedule, the database
changes, the latest-run rule, the failure counting and the freshness string,
and stops there. Every run is a STRICT build, exactly as the deadline build is
today; nothing in the model path changes.

## 1. Schedule — the cron lines do not change

```
*/10 * * * *  cd /root/fpl-copilot && flock -n /tmp/fpl-poller.lock   docker compose run --rm fpl-scheduler uv run python eval/availability_poller.py --season 2026-27  >> /var/log/fpl-poller.log 2>&1
*/10 * * * *  cd /root/fpl-copilot && flock -n /tmp/fpl-dispatch.lock docker compose run --rm fpl-scheduler uv run python eval/deadline_dispatcher.py --season 2026-27  >> /var/log/fpl-dispatch.log 2>&1
17 */6 * * *  cd /root/fpl-copilot && flock -n /tmp/fpl-ingest.lock flock -n /tmp/fpl-dispatch.lock docker compose run --rm fpl-scheduler uv run python eval/run_weekly_ingest.py --season 2026-27 >> /var/log/fpl-ingest.log 2>&1
```

(The poller and dispatcher lines are the existing ones verbatim in intent; the
ingest line is the verbatim 2026-09-11 install.) Cron cannot express "once
FPL has confirmed the gameweek", so the schedule is a POLICY inside the
dispatcher, which already ticks every 10 minutes under the one lock that
serialises every build against the ingest. The dispatcher gains a pure
`plan(now, events, state, ingested_gws) -> action | None`, tested with fake
clocks the way the ingest's `plan()` is.

**Kinds and slots** (one run per tick at most; precedence deadline > post-ingest > nightly):

| kind | fires | once per | attempts | notes |
|---|---|---|---|---|
| `post_ingest` | first tick after the master gains a newly finished gameweek N (`ingest_manifest_latest.json` lists N and no SUCCESS run knows history through N) | gameweek N | 2 (next tick) | the biggest information change of the week; recommended, see open question 1 |
| `nightly` | first tick at or after 05:00Z each day, if history through the last finished gameweek is ingested, no nightly today, deadline > 90 min away, and no post_ingest run in the last 6 h | day | 2 | 05:00Z = 4h43 after the 00:17Z ingest, 1h17 before 06:17Z, ready for the user's morning (UTC−4) |
| `t90` | first tick with lead ≤ 90 min | gameweek | 3 | the safety net (calendar moved → three retries + a hand `--force-gw`), as today |
| `t30` | first tick with lead ≤ 30 min | gameweek | 2 | the decision run |
| `t10` | first tick with lead ≤ 10 min AND lead ≥ 4 min | gameweek | 1 | late team news; the 4-minute guard because build + solve ≈ 45 s and a run landing at T-1 is useless |

Nightly gating on `data_checked` is inherited: the ingest only ingests
finished + data_checked gameweeks, so "history through N is in the master"
IS the gate. A Monday match pushes the first nightly to Wednesday 05:00Z
(or the post_ingest run the same day, if adopted).

Grid note: FPL deadlines are on :00 / :30 (GW4 12:30Z, GW5 17:30Z), so T-90
/ T-30 / T-10 land exactly on the */10 grid. For a :15 deadline the T-10 run
would fire at the first tick ≤ T-10, up to T-5. Option: `*/5` for the
dispatcher line (a container start every 5 min, ~2 s CPU each). Recommend
keeping `*/10` unless a :15 deadline appears (open question 3).

**Concurrency, unchanged by construction.** Every build runs under the
host `flock` on `/tmp/fpl-dispatch.lock`; the ingest takes the same lock
while it rewrites the volume; the poller is lock-free and touches only
`live/bootstrap_raw`. A full ingest chain (≤ 6 min at :17) never overlaps
05:00Z; on deadline day the ingest DEFERs inside deadline−3h..+1h within
~10 s and its :17 minute is never on the */10 grid. Peak memory per run is
the build's 1,569 MB, one run at a time, margin unchanged (section 12 of
Logs/squad_state_log.md).

## 2. Database — one table gains four columns; nothing else

```sql
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS kind      TEXT NOT NULL DEFAULT 'deadline';
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS slot      TEXT;      -- 'nightly:2026-09-16' | 't30:GW5' | 'post_ingest:GW4'
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS attempt   INT;
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS knowledge JSONB;     -- what the run knew (section 5)
CREATE INDEX IF NOT EXISTS ix_runs_latest ON model_runs (gw, status, finished_at DESC);
```

Idempotent, in `db_write.DDL`; existing rows read `kind = 'deadline'`
(run 5 was a T-90 run). `model_predictions`, `model_picks` stay append-only
per run_id (decision 2: ~3,900 rows × ~6 runs × 35 weeks ≈ 800k rows, tens
of MB). `players_live` stays an upsert (latest). No change to squad tables;
scoring keys on the version at the deadline, not on runs.

**Volume.** `_tmp_frame_baseline.parquet` stays "the latest successful
build" (overwritten), plus a sidecar `_tmp_frame_baseline.provenance.json`
{run_id, kind, slot, built_at, knowledge} so the file-based tools
(`optimise`, `get_my_xi`, `propose_transfers`) quote freshness without a DB
join and can detect a frame/run mismatch. Status: `GW{gw}_BUILD_STATUS.txt`
= latest run (unchanged name, so /health and the runbook keep working) +
an archive copy `live/runs/GW5_t30_20260918T1700Z.txt` per run. Dispatcher
state: `live/dispatch_state.json` replaces the per-gw `.done` /
`.attempts.json` markers: `{gw, slots: {slot: {status, attempts, run_id,
started_at, finished_at, last_exit}}, consecutive_nightly_failures,
last_success: {run_id, kind, finished_at}}` (a missing file = fresh).

## 3. Latest-run resolution — already the read layer's rule; made explicit

`model_tools._latest_run(gw=None)` = the newest SUCCESS run by
`finished_at` (optionally for a gameweek). That is the whole rule: the read
layer serves the latest; history stays. Changes: `_run_meta` carries `kind`,
`slot`, `knowledge` and the freshness string; `get_picks(gw=G)` = latest
SUCCESS for G; `health.model_versions` = the latest run's. Between a
deadline and the first run for the next gameweek, the latest run's cutoff is
the last deadline's — the stale-by-one path `get_my_xi` / `propose_transfers`
already take (labelled), now with the freshness string saying so in words.
A FAILED run leaves the previous frame and the previous latest row in place;
the sidecar's run_id must equal the DB's latest SUCCESS run_id or the tools
say "frame and database disagree" instead of answering.

## 4. Failure counting (decision 5) — in the dispatcher's state file; /health reads it

- **nightly / post_ingest**: a failed attempt → dispatcher log line + the
  archived status file; one retry at the next tick; the slot is FAILED after
  2. A FAILED slot increments `consecutive_nightly_failures`; any SUCCESS of
  those kinds resets it to 0. `/health` degrades only when the counter ≥ 2
  ("two nights without a model: <slot>, <slot>: <first lines>"). A single
  failure is visible in `/health.last_attempt` but is not a reason.
- **t90 / t30 / t10**: a slot FAILED after its attempts degrades
  immediately ("T-30 build FAILED for GW5 (2/2): <first line>"). T-90 keeps
  its three attempts and the hand `--force-gw` escape.
- `model_runs` FAILED rows are still written (evidence); `health()`'s
  current "most recent run FAILED" rule becomes kind-aware (a lone nightly
  FAILED row is not a reason). ACTION REQUIRED semantics are untouched: a
  strict raise that names a fix is still a human item.
- Bounded like everything else: after the attempts, a slot stops retrying;
  the next slot is a fresh chance. No slot can burn odds credits every 10
  minutes.

## 5. "When it ran and what it knew" — the knowledge block and the freshness string

The runner records `knowledge` from artefacts it already produces:

| field | source (exists today) |
|---|---|
| `history_through_gw`, `history_ingested_at` | max GW in `fpl_api_2026_27.parquet`; `ingest_manifest_latest.json.written` |
| `availability_asof` | the merged live availability file's provenance (max snapshot timestamp after `merge_live_availability`) |
| `odds_pulled_at`, `credits_remaining` | `odds_live_pull_2026_27.provenance.json.pulled_at`; the step's output line |
| `calendar_snapshot_at` | the strict preflight's calendar re-pull (its note line) |
| `frame_cutoff_gw`, `frame_gws` | the built frame |
| `kind`, `slot`, `attempt`, `started_at`, `finished_at`, `duration_s`, `git_sha` | the runner (started_at is real since 5262f61) |

Rendered once, in one place (`model_tools.freshness(run)`), and quoted
everywhere:

```
built Tue 16 Sep 05:03Z (nightly, run 7, 44 s) —
knows results through GW4 (ingested Mon 15 Sep 12:24Z), team news to Tue 16 Sep 05:00Z, odds pulled 05:02Z —
predicting GW5 (deadline Fri 18 Sep 17:30Z) —
next run Wed 17 Sep 05:00Z (nightly); deadline day Fri 16:00Z, 17:00Z, 17:20Z
```

Surfaced in `/health` (`last_run.freshness`, `next_run_expected`,
`schedule`, and `build_duration_s` so a slowing build is visible week to
week) and in every tool that reads a run or the frame (`get_prediction`,
`compare_players`, `get_picks`, `get_best_squad`, `optimise`, `get_my_xi`,
`propose_transfers`) as `built` + `next_run_expected`. The agent tool
descriptions tell the model to quote it and to say "check back after <next
run>" (decision 7). The fuller "what is still to come" (press conferences)
lands with the agent system prompt, per the brief.

## 6. Costs

Odds: 1 credit per run, ~6–7 per gameweek, ~250 a season of 19,326.
Postgres: ~3,900 prediction rows per run. Volume: one status archive file
per run. Anthropic: none. CPU: one build (~45 s) per run.

## 7. Tests (before any push)

`Tests/test_deadline_dispatcher.py` on the pure `plan()`: nightly gated on
ingestion and on 05:00Z; post_ingest detection; the deadline slots fire
once each with the T-10 minimum-lead guard; attempts per kind; precedence;
the state file round trip; `consecutive_nightly_failures` and the health
reasons per decision 5; freshness rendering from a fake knowledge block;
`_latest_run` picking the newest of several SUCCESS runs for a gameweek
(fake rows). Suite + parity family + as-of test, as always.

## 8. Rollout

Midweek, never inside deadline−90..+30 or across an ingest tick; the first
nightly runs then exercise the multi-run path on live data before Friday's
T-90 ever depends on it. `dispatch_state.json` starts fresh; the legacy
`dispatch_gw{N}.done` marker for GW5 is honoured for the t90 slot if the
deploy lands after it.

## 9. Open questions for the user

1. **post_ingest run**: include it (recommended — it is when the week's
   biggest information change lands; ~1 more credit) or nightly only?
2. **Nightly hour**: 05:00Z proposed (ready for the morning, clear of both
   ingest ticks). Alternative: 23:00Z (evening reading, includes the day's
   ingests).
3. **Dispatcher tick**: keep `*/10` (T-10 exact on :00/:30 deadlines) or
   `*/5` (exact for any deadline, one extra container start per 5 min).
