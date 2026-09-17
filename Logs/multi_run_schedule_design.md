# Design — run the model several times a week (2026-09-12; sections 1–9 the approved design, section 10 the build as deployed the same day)

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

---

## 10. BUILT (2026-09-12, commit 6bb5bf5)

Design: `Logs/multi_run_schedule_design.md`, approved with three answers
(post_ingest included; nightly at **11:00Z**, not 05:00Z — 07:00 Eastern,
clear of the 06:17 and 12:17 ticks; dispatcher tick stays `*/10`) and two
additions (t10 at ONE attempt is a recorded decision: a T-10 blip falls back
to T-30's answer and a retry would land at T-0; `/health` checks the
promised next run against what landed).

**Cron lines unchanged.** The schedule is `eval/dispatch_policy.py`, a pure
policy the dispatcher asks every 10 minutes under the dispatch lock:

| kind | window / gate | attempts |
|---|---|---|
| t10 | lead in [4, 10] min | 1 (recorded decision) |
| t30 | lead in (10, 30] | 2 |
| t90 | lead in (30, 90] | 3 (the safety net) |
| post_ingest | the season file gained a confirmed gameweek since the last successful run; previous gw ingested | 2 |
| nightly | first tick ≥ 11:00Z, previous gw confirmed and ingested, none today, no post_ingest success in 6 h | 2 |

Deadline-day windows are disjoint so each fires once; nightly/post_ingest
are gated on the PREVIOUS gameweek being ingested (never a clock alone).
`expected_next` is the promise; `health_reasons` (decision 5): a lone
nightly failure is not a reason, two consecutive give-ups are, any
deadline-day give-up is, a promised timed run that did not land within its
grace is, a dispatcher that stopped ticking is.

**What changed in code.** `eval/deadline_dispatcher.py` rewritten around
the policy (state in `live/dispatch_state.json`; the legacy
`dispatch_gw{N}.done` honoured as a completed t90; `--dry-run`, `--now`).
`eval/run_live_deadline.py`: `--kind/--slot/--attempt`; a KNOWLEDGE block
(history through gw + ingest manifest time, availability merge time, odds
pull time, frame cutoff/gws, duration, git) written to `model_runs` and to
`_tmp_frame_{config}.provenance.json`; per-run status archive
`live/runs/GW{gw}_{kind}_{ts}.txt`; still a STRICT build. `db_write`:
`model_runs` + kind/slot/attempt/knowledge (+ index), applied on the server
(existing rows read `kind = deadline`); the backfill writes
`kind = recovered`. `model_tools`: every run-backed answer carries `built`
(`dispatch_policy.freshness`) and `next_run_expected`; the frame-based tools
refuse if the frame sidecar names a different run than the database's
latest for that gameweek; `/health` reports `schedule` (last tick, expected
next, consecutive give-ups, last success, this gameweek's slots),
`last_run.freshness` and `build_duration_s`, and applies the reasons above.
`agent.py`: quote `built`, say when to check back (decision 7).

**Freshness string, as rendered (test):** `built Wed 16 Sep 11:03Z (nightly,
run 7, 44 s) -- knows results through GW4 (ingested Tue 15 Sep 12:24Z), team
news to Wed 16 Sep 11:00Z, odds pulled Wed 16 Sep 11:02Z -- predicting GW5
(deadline Fri 18 Sep 17:30Z) -- next run Thu 17 Sep 11:00Z (nightly)`. A
pre-multi-run row (run 5) renders "knowledge not recorded"; a conditional
promise renders "next run when GW4 confirmed by FPL and ingested …".

**Tests.** `Tests/test_dispatch_policy.py` (17): gating, once-a-day, the
disjoint windows, t10 = 1, t90 × 3 then give up, precedence, the consecutive
counter and its reset, expected_next between deadlines and on deadline day,
the broken promise (inside vs after grace, kept vs not), a dead dispatcher,
decision 5's one-vs-two, deadline-day give-ups (only for the next gw), the
freshness string. Suite **359 passed, 0 skipped**; parity and as-of
families inside it. Model path untouched.

**"Nothing fires tonight" — confirmed, not assumed.** A dry run of the
dispatcher against the live bootstrap (laptop, 22:40Z): `deadline GW5 at
2026-09-18T17:30:00Z; season file through GW3; decision: none -- GW4 not
yet confirmed and ingested`, expected next = post_ingest, conditional. The
pure policy walked through the week with the real events and a season file
through GW4: nothing on Sun/Mon/Tue 11:00; **post_ingest fires at the first
tick after GW4 is ingested** (Tue 12:30 in the walk); the same-day nightly
is suppressed; nightly Wed 17, Thu 18 and Fri 18 at 11:00Z; **Fri t90
16:00Z, t30 17:00Z, t10 17:20Z**; nothing after the deadline until GW5 is
ingested.

**Deployed and verified (22:45Z).** /health `git_sha 6bb5bf526`, ok, zero
reasons; api restarted; the four columns applied to `model_runs` at 22:40Z
(rows 3-5 read `kind = deadline`). The first real cron tick after the
deploy (22:50:03Z) decided `none -- GW4 not yet confirmed and ingested
(season file through GW3)` and wrote `live/dispatch_state.json` with
`expected_next = post_ingest:GW4 (conditional)`; the dispatcher's dry run on
the server said the same. /health now carries `schedule` (last tick,
expected next, counters, slots) and `last_run.freshness`; `get_prediction`
and `get_my_xi` carry `built` + `next_run_expected` (run 5 renders
"knowledge not recorded (a pre-multi-run row)" until the first multi-run
build lands).

**What runs unattended before Friday 2026-09-18 17:30Z.** Poller every 10
min. Dispatcher every 10 min: nothing until GW4 is ingested; then
`post_ingest:GW4` at the first tick after that ingest (~Tue), nightly
`11:00Z` on the days after, `t90` 16:00Z / `t30` 17:00Z / `t10` 17:20Z
Friday. Ingest ticks 00:17/06:17/12:17/18:17Z: NOTHING-NEW until FPL flags
GW4, then GW4 ingested + scored on the tick after. Odds: 1 credit per build.

**Check on Tuesday.** (1) The first `squad_scores` row for GW4 (section 15
of Logs/squad_state_log.md). (2) The first multi-run build: `/health` →
`schedule.last_success.slot == "post_ingest:GW4"`, `last_run.kind ==
"post_ingest"`, `last_run.freshness` naming "knows results through GW4",
`build_duration_s` filled, reasons `[]`; on the volume
`live/runs/GW5_post_ingest_*.txt` and `_tmp_frame_baseline.provenance.json`
with the same run_id as `model_runs`' latest. Then Wednesday 11:00Z the
first nightly, and `expected_next` becoming a timed promise.

**Open.** Option B unchanged (unwired). The freshness string's "what is
still to come" (press conferences) lands with the agent system prompt. The
`availability_asof` field is the merge time (the poller's snapshot is ≤ 10
min older), not the poller's own timestamp — good enough for the sentence,
noted. `optimise` still solves the frame's own step 0. The T-10 4-minute
guard and the :00/:30 assumption are documented, not enforced by cron.

## 11. Decision 2026-09-15 — the deadline slots are unconditional; two gates, two purposes

**The report that prompted it, corrected.** While waiting for FPL to confirm GW4 (all ten fixtures played by
Monday 19:00Z; the bootstrap still `finished=False` at Tuesday 01:00Z) the assistant reported that every run
kind, including T-90 / T-30 / T-10, was gated on the previous gameweek being ingested. Reading `plan()` again:
that was wrong for the runs and right for the promise. The deadline-day branch comes first and never
consulted `master_gw`, so the three slots would have fired on Friday under a stall. What WAS conditional: (a)
`expected_next` between deadlines with `master_gw < gw-1` promised only "post_ingest when GW4 is confirmed",
so `/health` had no timed promise to check and the freshness line told the user nothing about Friday; (b) the
freshness line did not say that a build's history stopped short of the previous gameweek; (c) nothing tested
the stalled case, so the guarantee was an accident of branch order, not a decision.

**The decision (user, 2026-09-15).** The three deadline slots fire regardless of confirmation state — their
purpose is to avoid a MISSING run. Nightly and post_ingest stay gated on the previous gameweek being confirmed
and ingested — their purpose is to avoid a POINTLESS run. Different purposes; the distinction is in the module
docstring and at both branches so nobody re-unifies them. A build on history through GW3 is worse than one
through GW4 and far better than none; strict stays on for every run.

**What changed (`eval/dispatch_policy.py`).**
- `plan()`: the deadline branch is documented as unconditional and its reason names the history gap ("GW4 not
  yet confirmed and ingested when this was built: history stops at GW3"); the between-deadlines reason says the
  deadline-day runs fire regardless.
- `expected_next()` between deadlines under a stall: the conditional post_ingest promise now carries a CERTAIN
  fallback — `certain_kind` t90, `certain_slot`, `certain_at` = deadline − 90 min, `certain_grace_min` — and
  `health_reasons()` degrades if that slot has not landed by `certain_at` + grace ("the deadline safety net,
  due regardless of …").
- `freshness()`: "knows results through GW3 -- GW4 not yet confirmed and ingested when this was built: history
  stops at GW3", and "next run when GW4 confirmed … (post_ingest); in any case Fri 18 Sep 16:00Z (t90),
  whatever FPL confirms". `history_gap()` is the one sentence, shared by the reason and the freshness line.
- Tests (`Tests/test_dispatch_policy.py`): the stalled-FPL case with a fake clock and an unconfirmed bootstrap
  — all three slots fire in order with the season file at GW3 AND with it unreadable, each reason naming the
  gap; between deadlines nothing but the promise moves; a missed safety net degrades health under the stall;
  the freshness wording. 21 policy tests.

**Deployed and proven (c975e26, 01:26Z 2026-09-15; suite 417 passed, 1 skipped; no slot running; the 06:17Z
tick untouched).** In the scheduler image, against the REAL inputs — FPL's bootstrap as served at that minute
(GW4 `finished=False data_checked=False`: the stalled case is live), the real season file (through GW3), the
real dispatch state (no slots) — with a fake clock, nothing saved, nothing run:

```
2026-09-17T12:00Z: action=None  reason=GW5 deadline in 29.5 h; GW4 not yet confirmed and ingested (season file
                   through GW3) -- no nightly or post-ingest run until it is; the deadline-day runs fire regardless
                   expected_next: post_ingest (conditional) + certain_kind t90, certain_at 2026-09-18T16:00:00Z
2026-09-18T16:01Z: action=t90  t90:GW5  "T-89 -- t90 window (GW4 not yet confirmed and ingested when this was built: history stops at GW3)"
2026-09-18T17:01Z: action=t30  t30:GW5  (same gap named)
2026-09-18T17:21Z: action=t10  t10:GW5  (same gap named)
freshness a T-90 build would carry: built Fri 18 Sep 16:01Z (t90, run 999, 50 s) -- knows results through GW3
  (ingested Tue 08 Sep 00:17Z), team news to Fri 18 Sep 15:50Z, odds pulled Fri 18 Sep 16:00Z -- GW4 not yet
  confirmed and ingested when this was built: history stops at GW3 -- predicting GW5 -- next run when GW4
  confirmed by FPL and ingested (…), then nightly at 11:00Z (post_ingest); in any case Fri 18 Sep 16:00Z (t90),
  whatever FPL confirms
```

## 12. Incident 2026-09-15 18:30-19:01Z — the first live multi-run builds: four identical SUCCESS runs, and /health said ok

**What happened.** FPL confirmed GW4 in time for the 18:17Z ingest tick (`RAN gameweek(s) [4] -> SUCCESS`, the
first `squad_scores` row written: GW4 49 points, captain Haaland). The 18:30Z dispatcher tick fired
post_ingest:GW4 — the first build the multi-run dispatcher had ever run live. The build SUCCEEDED (run 6,
3,954 prediction rows WITH the term columns, the frame on the volume, `/health` ok) and then the dispatcher
crashed: `run_build` did `import config_roles` after the subprocess returned, and the repo root was not on the
dispatcher's `sys.path` (only `eval/` was). The crash came AFTER the build and BEFORE `record_outcome`, so the
slot stayed `RUNNING` with its attempt counted; the 18:40Z tick fired attempt 2 (run 7, identical), crashed
the same way; attempts exhausted, the 18:50Z and 19:00Z ticks fired the nightly twice (runs 8 and 9). Four
bit-identical builds in 31 minutes; `last_success` never set; `/health` `ok` throughout, because no FAILED
status was ever recorded and each tick overwrote the promise before dying. The Tuesday-checks watcher was
what noticed (four runs where one was expected).

**Why it was latent.** The dispatcher's tests exercised the POLICY (`dispatch_policy`) and the tick with the
build mocked at the policy level; nothing imported the dispatcher module and ran its post-build path. The
GW4 deadline build on 12 Sep ran under the single-run dispatcher. Same family as the unread status file: a
success followed by a silent crash is indistinguishable from a success.

**Fixes (commit after this section).**
- `deadline_dispatcher.py`: the repo root on `sys.path`; `config_roles` imported at module load — an import
  that can fail must fail at the FIRST tick, not after a build.
- `reconcile_from_db(state)`: on every real tick, a slot left `RUNNING` is settled from `model_runs` (the one
  record the runner always writes): a SUCCESS row for that slot marks it SUCCESS (with run_id and
  `history_through_gw`, and sets `last_success`); a FAILED row marks it FAILED; an unreachable database logs
  and leaves the state alone. The next real tick after this deploy settles post_ingest:GW4 and
  nightly:2026-09-15 from runs 7 and 9.
- `dispatch_policy.health_reasons`: a slot `RUNNING` for more than 90 min (the runner's own timeout is 60)
  degrades `/health` — "the dispatcher tick died after or during its build and never recorded the outcome" —
  which is what the alert probe would have pushed.
- `Tests/test_deadline_dispatcher.py` (4): `config_roles` resolves at import and `run_build` reads the
  sidecar; a RUNNING slot is settled from model_runs rows (SUCCESS, FAILED, and the policy then does not
  re-fire); ONE WHOLE TICK end to end with the network, the season file, the build and the state file faked —
  SUCCESS recorded, `last_success` set, the promise written, and a second tick does not re-fire; the stale
  RUNNING health reason.

**Cost.** Four identical runs (6-9) in the database — harmless (same inputs, same frame), the agent serves run
9. No user-visible wrong answer; the failure was a silent waste plus a state that would have re-fired
post_ingest on the next confirmed gameweek only once (attempts fresh per slot).

**Deployed 0b575ef (21:27Z) and settled by the next real tick.** On landing, `/health` turned `degraded` on
the new reason — both slots RUNNING for 130-170 min — which is the detector working. The 21:30:04Z tick
logged `reconcile: post_ingest:GW4 -> SUCCESS (run 7)` and `reconcile: nightly:2026-09-15 -> SUCCESS (run 9)`,
set `last_success` (run 9, history through GW4) and `/health` returned to `ok` with zero reasons; the
promise is nightly:2026-09-16 at 11:00Z. Suite 421 passed, 1 skipped.

**The Tuesday checks (fix log section 12), all done on the same evidence.** (1) the alert channel — not yet
installed (user); (2) GW4 ingested (`history_through_gw` 4) and post_ingest:GW4 SUCCESS — yes, via the
reconciliation; (3) the first `squad_scores` row: GW4, 49 points net, captain Haaland (doubled), one autosub,
bench 14; (4) term columns: runs 6-9 each 3,954 prediction rows with 3,954 recorded terms; (5)
`explain_prediction(411, gw=5)` on run 9's frame: fixture line `model`, `stale_by_gameweeks` 0, no
starting-point label anywhere; `compare_runs(411, 5, 6, 9)` from stored terms: "gap +0.00: no term differs"
(identical inputs — the reader works on the database); (6) `dc_fit`: n_train 3,840 (GW4's ten matches
added), `converged` False, max |attack| 7.39 — Coventry still scoreless, the KNOWN_ISSUES #25 artefact as
predicted; GW6 rows with a lambda below 0.15: Coventry City 37 and their opponents Newcastle 30 (the
runaway seen from both sides); Hull's defence no longer runs off (they conceded in GW4).

**What the alert probe saw (added 2026-09-16 00:40Z, at the user's request).** The probe HAD been installed
(env file and cron line since Sun 14 Sep 15:44Z; the 11:05Z heartbeat fired on the 15th). Its log through the
crash window, every ten minutes from 18:10Z to 19:30Z: `health=ok reasons=0 events=none`. It pushed nothing
because there was nothing to push: no FAILED status was ever recorded and the promise was overwritten each
tick, so `/health` was `ok` for the whole incident. That is the second finding, and the larger one: a tick
that dies after a successful build was a class `/health` could not see, and an alert that consumes `/health`
inherits every blind spot `/health` has. The `RUNNING_STALE_MIN` reason closes this class. After the fix
deployed (21:27Z) the probe saw `degraded` once (21:30:02Z, one probe before the 21:30:04Z tick settled the
slots) and then `ok`, so no DEGRADED page (two consecutive probes are required, by design); at 21:40Z it
pushed two slot outcomes — post_ingest:GW4 SUCCESS (run 7) and nightly:2026-09-15 SUCCESS (run 9) — the
first two pushes the channel has carried for real. No human touched the server or the state file: the
recovery was the deployed code's reconciliation on the next tick; the only human action was the code fix
and its deploy.

**Are the run outputs trustworthy?** Yes. The runner ran to completion each time: strict preflight and
postflight passed, the frame was written to the volume, the sidecar and the status archive were written,
the model_runs / model_predictions / model_picks rows were committed (3,954 predictions with terms per run).
The crash was in the DISPATCHER'S bookkeeping after the runner's subprocess had returned exit 0. Runs 6-9 are
bit-identical because their inputs were identical; the agent serves run 9.

**Can it recur before Friday, and are the deadline slots exposed?** The crash path was the same for every
kind, so the deadline slots WERE exposed (a t90 that built and then crashed would have re-fired at t30 as
attempt 1 of its own slot, and so on — the builds would still have happened, the bookkeeping would not).
The import now happens at module load and is tested; the end-to-end tick test runs the post-build path; the
reconciliation settles any slot a future crash leaves RUNNING; the stale-RUNNING reason degrades `/health`
within 90 min and the probe pushes it. Residual: a NEW kind of post-build crash would still cost one
re-fire before the reconciliation catches it on the next tick — a wasted build, not a missing one.

---

## 13. Verification 2026-09-17 22:00Z — the ungating was already in place; the prompt was re-issued from a stale note

**Why this section exists.** `Handoffs/Squad State handoff.docx` §2.5 ("OPEN — the deadline slots are still
conditionally gated") and §12.1 ("Ungate the three deadline slots — prompt issued, not confirmed. Do before
Friday.") both describe the ungating as outstanding, and a work prompt was issued on that basis. It is not
outstanding. It was done on 2026-09-14 in `c975e26`, deployed, tested and proven live, and section 11 above is
its record. The docx was saved at 21:37Z on 2026-09-17, about three hours AFTER the same session pushed the
work it calls unpushed — it is stale at its own write time, not wrong about a later regression.

This is the second time the "everything is gated" reading has been acted on. Section 11 records the first: the
report that prompted the 2026-09-14 decision was itself wrong about the runs (right about the promise). A
re-issued prompt is cheap; a re-implementation on top of working code is not. Hence a permanent note.

**What was checked, and how (nothing was changed).**

| requirement, as re-stated in the prompt | where it already is | evidence |
|---|---|---|
| t90 / t30 / t10 fire regardless of confirmation state | `plan()`, the `if lead <= 90:` branch — it comes first and RETURNS before the `master_gw` gate is ever reached; the `master_gw is None` (unreadable season file) path is below it too | `eval/dispatch_policy.py` ~line 127, comment "UNCONDITIONAL: this branch comes before, and never consults, the previous-gameweek gate below" |
| nightly / post_ingest keep the gate unchanged | the between-deadlines branch still returns early on `master_gw < prev_gw` | same file, the branch below the deadline return |
| the freshness line names the gameweek the history actually reaches | `history_gap(gw, history_through_gw)` — one shared sentence, used by the dispatcher reason and by `freshness()` | "GW4 not yet confirmed and ingested when this was built: history stops at GW3" |
| strict stays on | not optional: `strict=True` is hard-coded in the runner | `eval/run_live_deadline.py` line 295 |
| a test with a fake clock and an unconfirmed bootstrap proving all three fire | `test_deadline_slots_fire_with_an_unconfirmed_bootstrap_and_a_stale_season_file` — fake clock, `EVENTS_STALLED`, run for BOTH `master_gw=3` and `master_gw=None`, asserts `fired == ["t90", "t30", "t10"]` and that every reason names the gap | `Tests/test_dispatch_policy.py` line 54 |

`uv run pytest Tests/test_dispatch_policy.py Tests/test_deadline_dispatcher.py -q` -> **25 passed in 0.92 s**.

**Deployed already.** The served SHA is `e32e31b2a`; `git merge-base --is-ancestor c975e26 e32e31b` is true, and
the file on the server carries the UNCONDITIONAL comment at lines 34 and 127 (read-only ssh). There was nothing
to deploy, so the container was not touched and no no-touch window was spent.

**The push half of the same prompt was also already done.** Against a fresh `git fetch --all --prune`:
`git rev-list --left-right --count origin/main...main` = `0 0`, and the same for `origin/hinge-box-v2...hinge-box-v2`.
main and the branch are both on origin; `origin/hinge-box-v2` head is `adddc17` (f41a0fe = v2, adddc17 = v3),
not merged, exactly as intended. The "where the code lives" record the prompt asked for already exists and says
so: `Logs/dc_shrinkage_v3_log_2026-09-17.md` section 4, written 19:10Z.

**The correction to carry forward.** `Handoffs/Squad State handoff.docx` §2.5 and §12.1 are both stale and should
be struck or marked done; the .docx is the user's file, so it is left untouched here. Anything generated from
that docx will keep re-raising these two items until it is. The live open items from §12.1 that ARE real remain
real: the external uptime monitor, and rotating the ntfy topic (it was pasted into a chat).
