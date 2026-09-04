# Pipeline moved to the droplet — 2026-09-04

Server: root@68.183.131.154, 2 vCPU / 3.8GB / 77GB (52GB free), Etc/UTC,
docker-compose stack. App behaviour untouched (main.py byte-identical;
health 200 throughout). Commits: 391e52d (scheduler service + volume +
dispatcher), 6502ecc (libgomp1), 195da6e (forward-slash path literals).

## The verify (the headline)

**The server reproduces the laptop's GW3 frames.** Both configs built under
strict from the copied inputs with ZERO raises; cell-exact comparison vs the
laptop's RECOVERED frames: identical shapes (3,774×67 / 3,774×63), every
integer/string/key column bit-exact, and the only deltas are last-ulp float
noise — max |Δ| 1.8e-15, touching 1–12 rows of 3,774 in derived float
columns (e_minutes → e_points at 2.2e-16) — Windows-vs-Linux libm, not a
modelling difference. **The solved fifteen, captain (Haaland), vice and
99.9 cost are exactly identical.** Same code, same data, same answer.

Server timings (2 vCPU): strict combined build 39.1s, baseline 34.3s, solve
0.7s; process peak 1,664MB (combined alone) / **1,829MB with both configs
in one process** — the shape run_live_deadline uses. Against 3.8GB with
~0.7GB of OS+containers: ~1.3GB headroom. Weekly steps: availability merge
1.6s, props crosswalk 84.3s (all seasons), consensus 1.7s, skeleton 2.3s
(482MB). Strict findings all notes, same set as the laptop (props 10/10 at
GW3, step-0-only hook, ODDS_HORIZON_GWS=0, calendar match, DC cold start,
penalty fill).

Three portability bugs found BY the verify, each fixed and committed:
1. **libgomp.so.1 missing** — slim image lacked LightGBM's OpenMP runtime;
   the API never imports lightgbm so two weeks of serving never noticed.
2. **Windows path literals** — the de-hardcoded BASE constants still
   concatenated `r"\data\..."`; `/app\data\...` on Linux. 11 sites in the
   five live-path modules switched to forward slashes (read identically on
   Windows; laptop suite 229 green before push).
3. **Historical props raw needed** — build_props_crosswalk iterates every
   board season, so raw/scale/2024-25 + 2025-26 belong in the live subset
   (the one inventory judgement the verify overturned). Shipped (+6.1MB).

## 1. The data volume

Named volume `fpl-copilot_fpl_model_data`, mounted at **/app/data by BOTH
fpl-copilot (api) and fpl-scheduler**. Contents per the 2026-09-03
inventory: STATIC live-path inputs (frozen archives, historical availability,
crosswalks, frozen core-insights pair, verification references), APPENDS
(fpl_api, understat matches), REBUILT (combined stacks, skeleton, odds slice,
aggregates, crosswalk, availability merge, props consensus, hmin refit),
ACCUMULATES (understat raw, props raw — now all seasons, live/ incl.
bootstrap_raw, frames, shadow record). **41MB + 6.1MB props history; 1,661+
files.** NOT copied: loose walkforward frames, arms/arms_gap0, teamnews, old
hmin refits, vaastav season dirs, core-insights raw dir, d4/research files.

**The server does NOT run the test suite** — deliberate: the record-parity
family reads the research artefacts, which stay laptop-side. The gate is:
229 suite + parity on the laptop before every push; server correctness is
established by the reproduction above, not by re-running the suite there.

## 2. The scheduler service

`fpl-scheduler` in docker-compose: same image the app builds (no second
build), profile-gated so `up -d` never starts it; host cron invokes
`docker compose run --rm`. Mounts the model volume and **bind-mounts the
live ./.env at /app/.env** — fetch_live_odds/pull_live_props read the key by
PARSING the file, so the baked-at-build copy would go stale. App and
postgres services unchanged.

**.env: USER ACTION REQUIRED** — add one line to /root/fpl-copilot/.env:
`ODDS_API_KEY=<the paid the-odds-api key>` (present keys: ANTHROPIC_API_KEY,
DB_*). No rebuild needed (bind mount). Until it lands, the GW4 T-90 run
fails at fetch_live_odds — loudly, with a FAILED status file.

## 3. Cron — two schedules (installed, root crontab)

- Poller: `*/10 * * * *` → `poll_availability.py --once`; the script's OWN
  due-gate decides (window deadline−4h, 30-min cadence, 10-min final hour,
  DUE_TOLERANCE=30s — the GW2 off-by-a-second fix, verified holding on GW3).
- Weekly build: `*/10 * * * *` → `eval/deadline_dispatcher.py` — **derives
  the next deadline from bootstrap-static on every tick** and fires
  run_live_deadline once inside T-90; success marker ends the window;
  failures retry ≤3 then surface. Hardcoded times were rejected because
  they drift: **GW4's deadline is 12:30Z, not 17:30Z** — the mechanism was
  vindicated before it ever fired.
- Both lines under `flock -n` (no overlap), logging to /var/log/fpl-*.log.
- Smoke-tested live: poller "GW4 +185.6h — not due", dispatcher "11136 min
  away — not due (fires at T-90)".

## 4. Timezone

Server is **Etc/UTC** (synchronized). Cron is UTC, FPL deadlines are UTC,
both gates compare UTC-to-UTC — **no timezone conversion exists anywhere in
the chain**. The laptop's UTC−4 trap cannot recur on this path.

## 6. Unattended failure modes (reported, not fixed)

GUARDED: strict raise → no build + status file; step exit codes checked (no
pipes); os.replace bounded retry; cron overlap (flock); deadline drift
(API-derived); poller cadence (DUE_TOLERANCE); hung steps (subprocess
timeouts 1200s/3600s; dispatcher HTTP timeout 30s); OOM at current sizes
(1.83GB peak vs ~3.1GB available — and an OOM kill would surface as a
FAILED status via the dispatcher's exit-code path).

UNGUARDED — the honest list:
1. **Nobody reads the status file.** The laptop had a human; the server has
   no alerting. A FAILED build waits silently until someone looks. Biggest.
2. **The Actions deploy is flaky** — it failed twice today on a stale
   container-name conflict and was completed manually; a silently failed
   deploy leaves server code behind main with no alarm.
3. **Docker image accumulation**: every rebuild leaves ~1GB dangling; no
   `docker system prune` scheduled. 52GB free today; will erode over a
   season of deploys.
4. .env is baked into the image by `COPY . .` (no .dockerignore) — secrets
   in image layers.
5. /var/log/fpl-*.log grow unbounded (no logrotate entry). Small but real.
6. No backup of fpl_model_data (pgdata has one). Low severity — the volume
   is rebuildable from APIs + the laptop copy.
7. External-API failure modes inside the crawl (429s, outages) have no
   fine-grained retry — the coarse guard is the dispatcher's 3 whole-run
   attempts.
8. ODDS_API_KEY absent until the user adds it (see §2).

## What moved and what did NOT

MOVED: the poller (10-min tick, due-gated) and the deadline-day build
(T-90 dispatcher → refreshes → strict both configs → solve → status file).
NOT MOVED (still laptop): the weekly INGEST half of the runbook
(fetch_fpl_history/understat/crosswalk after each played gw — needs a
data_checked trigger, a separate design), d6_postwindow + the fplcache
clone (Windows uv path + git clone), the test suite (deliberate, above).
The laptop's scheduled tasks remain armed — both pollers now run in
parallel (harmless; retiring the laptop's is the user's call once trust is
established). Postgres untouched; main.py untouched.
