# Weekly ingest automated — 2026-09-11

Task: automate the weekly ingest before GW5, as scoped in the 2026-09-11 close-out
(item 3h). Production is baseline at e3d98af; GW3 ingested; GW4 builds in ~35 s for
1 credit. The gap: the weekly ingest ran on the laptop by hand and nothing on the
server performed it — GW4 nearly built on history through GW2 for that reason.
Commit ad056de. No modelling change.

## 1. What was built

`eval/run_weekly_ingest.py` — the unattended weekly ingest, under the deadline
runner's failure contract (eval/run_live_deadline.py):

- **Order** (the runbook's): `fetch_fpl_history --gw N` for every gameweek FPL
  flags `finished AND data_checked` that is not yet in the season file (then
  `--combine`) → `understat_matches` → `build_understat_aggregates` (+`--combine`)
  → `build_crosswalk` → `fetch_fixtures` (+`--combine`) → `fetch_live_odds`
  (1 credit) → `build_forward_skeleton` **last**.
- **Exit codes are law**; no pipes; output captured to a run log; `os.replace`
  under the bounded PermissionError retry; any exception → FAILED status with the
  traceback, exit 1.
- **Strict stops, never workarounds**: (a) PRICES LOST — a played fixture that
  carried pre-deadline prices before the run must carry the identical triple after
  it; (b) SKELETON STALE — a forward-skeleton fixture the master also carries
  (season_stack.load_stack's collision assert, evaluated on the files); (c) any
  step's non-zero exit. Each writes FAILED and stops.
- **Bounded retries**: an attempts sidecar per gameweek (`ingest_gwN.attempts.json`,
  MAX 8 = two days of 6-hourly ticks) then a standing FAILED "giving up"; a
  `ingest_gwN.partial.json` marker written at chain start and removed on success
  keeps a gameweek whose chain broke half-way eligible even though its rows are
  already in the season file (without it a mid-chain failure would read as
  "nothing new" forever and the skeleton would stay stale).
- **Gates before any step runs** (`plan()`): NOTHING-NEW unless a final gameweek
  is un-ingested; DEFERRED inside deadline−3h .. deadline+1h of ANY deadline (the
  T-90 build must not read inputs mid-rewrite, and no odds credit is spent next to
  the build's own pull); DEFERRED while a fixture is past kickoff without a score
  (fetch_fixtures refuses that state by design).
- **The human prompt first**: `ACTION REQUIRED` blocks precede every ordinary
  section — (i) every element with real minutes and NO Understat id, with its
  nearest Understat candidates (name score over the season's aggregate listing,
  club, games, minutes, and whether the id is already claimed) and the MANUAL-entry
  instruction; (ii) any element whose id CHANGED, or was LOST while playing (the
  alarm condition of Logs/crosswalk_2026_27_log.md). Both are recomputed on every
  tick, so they stay visible until a human closes them. The status first line says
  `SUCCESS -- ACTION REQUIRED (n items)`.
- **Input hashes**: sha256 + an order-independent content digest (sorted per-row
  hashes; writer timestamps `pulled_at`/`built_at` excluded) + row count for the
  22 live-path inputs, BEFORE and AFTER, in `ingest_manifest_gwN.json` /
  `ingest_manifest_latest.json`; `--hash-only` prints the same manifest on any
  machine. Bytes may differ across pyarrow builds; content may not.
- `/health` gained `data_freshness_by_source.weekly_ingest` (first line + age of
  the two status files) and degrades on: FAILED; ACTION REQUIRED; a tick older
  than 13 h (a dead cron); no tick ever.
- `Tests/test_weekly_ingest.py`: 17 tests, no network (fake API, fake steps writing
  a tmp data dir). Suite 249 passed.

## 2. Schedule, and how it avoids the dispatcher and the poller

Root crontab on the droplet (UTC), third line after the poller and dispatcher:

```
17 */6 * * * cd /root/fpl-copilot && flock -n /tmp/fpl-ingest.lock flock -n /tmp/fpl-dispatch.lock docker compose run --rm fpl-scheduler uv run python eval/run_weekly_ingest.py --season 2026-27 >> /var/log/fpl-ingest.log 2>&1
```

- **00:17 / 06:17 / 12:17 / 18:17 Z**, inside the scheduler image, against the
  volume. A tick with nothing to do costs one bootstrap + one fixtures call and
  writes `INGEST_TICK.txt`. FPL flags a gameweek data_checked roughly a day after
  its last match (Tuesday for a Monday game), so the ingest lands within 6 h of
  the flag, days before the next deadline; the runner also catches a
  gameweek that finalises late in the week (a Thursday flag is picked up at
  18:17 or 00:17, still outside the Friday window).
- **:17** is off the poller's and dispatcher's :00/:10 ticks.
- **Two locks**: its own (no overlapping ingests) and the DISPATCHER's — while the
  volume is being rewritten (~6 min) a dispatcher tick's `flock -n` fails and it
  simply fires 10 minutes later. Observed 2026-09-11: the forced run held the lock
  22:15–22:21Z and the 22:20 dispatcher tick left no log line (locked out); the
  22:10 and 22:30 ticks ran. The poller touches only `live/bootstrap_raw` and the
  changes file and needs no lock.
- **The window gate** is the belt to the lock's braces: even without the lock the
  runner refuses to start inside deadline−3h .. +1h, which covers the T-90 build,
  the deadline, and the Postgres write after it. GW5 (Fri 2026-09-18 17:30Z):
  window 14:30–18:30Z; the 12:17 and 18:17 ticks fall outside it.

## 3. Prices preserved — confirmed unattended

The e3d98af carry-forward in `fetch_fixtures.build_slice` (prices already held in
the existing slice are copied onto the fresh, all-null slice keyed on Date/Home/
Away, then `fetch_live_odds` re-prices only the provider's upcoming events) is
exercised by every weekly run, and the runner asserts it: before the rebuild it
records every played-and-priced fixture's triple; after `fetch_live_odds` it
requires each to be present and identical, else FAILED "PRICES LOST".

Both runs today: **played fixtures priced before 10 / after 10, all 10 identical**
(GW3's ten; GW1–2's are gone for good, recorded 2026-09-11), provenance
`prices_preserved_from_previous_slice=30` (the ten played + the twenty upcoming
carried, then overwritten by the fresh pull), 20/20 upcoming events priced.

## 4. Runs today

| | laptop `--force-gw 3` | server `--force-gw 3` (scheduler image, volume, under both locks) |
|---|---|---|
| started / finished | 22:02:49 / 22:09:21Z | 22:15:24 / 22:21:41Z |
| steps | 10, all exit 0 | 10, all exit 0 |
| GW3 | 654 rows, 10 fixtures, cross-check 0 mismatches, data_checked | same |
| Understat | 30 matches, gw 1/2/3 = 10/10/10, 0 deferred | same (10 GW3 matches fetched from the droplet IP at 1 req/s — Understat did not block it) |
| crosswalk | 387 → 387, 0 gained/lost/changed, 100.0% minutes covered | same |
| prices | 10/10 played identical; 20/20 upcoming; credits 19,327 | 10/10; 20/20; credits 19,326 |
| skeleton | 22,960 rows, gws 4..38, 0 collisions | same |
| ACTION REQUIRED | none | none |

Then, on the server, the **GW4 strict baseline build against the freshly ingested
volume: PASSED, 3,936 rows, gws 4–9, 32 s, notes only** (calendar re-pull matches
the new skeleton snapshot). The cron command string was also run once under `sh`
as root exactly as cron will: exit 0, NOTHING-NEW tick written, one line in
`/var/log/fpl-ingest.log`. The first scheduled tick is 2026-09-12 00:17Z (not
observed in this session).

## 5. The hash check — laptop vs server after both runs

`compare_manifests(laptop --hash-only, server after)`: **19 of 22 live inputs
content-identical** — the archive, `fpl_api_2026_27` (the re-pull reproduced the
season file exactly), `all_seasons_with`, the forward skeleton parquet, the
Understat matches and aggregates, the crosswalk, the odds archive, every
availability file. Two of those (crosswalk csv, understat_matches) differ in bytes
only (a writer-timestamp column / csv formatting) — the content digest is what
the claim rests on. The three that differ in content are the ones that must:
`odds_fixtures_2026_27` and its combined file (two odds pulls 12 minutes apart —
the market moved) and the skeleton provenance sidecar (pull time + calendar
snapshot). Any future "the server reproduces the laptop" claim starts from this
comparison, not from a row count.

## 6. What a maintainer sees each week, and what happens on failure

Normal week: `/health` stays `ok`; `INGEST_TICK.txt` reads `NOTHING-NEW` three
times a day until the gameweek is data_checked, then `RAN gameweek(s) [N] ->
SUCCESS`; `INGEST_STATUS.txt` (and `INGEST_GWN_STATUS.txt`) carries the sections
above; the next deadline builds on a master that includes GW N.

Something for a human: the first line becomes `SUCCESS -- ACTION REQUIRED (n
items)`, `/health` goes `degraded` with the same line in `reasons`, and the block
at the top of the status names the element, club, position, minutes and the
Understat candidates. The fix is an evidenced `MANUAL["2026-27"]` entry in
`eval/build_crosswalk.py` (as for Savio 403 → 11735), pushed; the next tick's
crosswalk rebuild picks it up and the block disappears. Until then the element
rides the positional prior — not a build blocker (strict raises only if it reaches
the top 30 by e_points).

A step fails: the chain stops there; `INGEST_STATUS.txt` starts `FAILED` with the
step, its exit code and last output, plus the consequence spelled out (the
skeleton may be stale against the master, so the next deadline build would FAIL
on the collision assert — loudly, not on stale history); `/health` degrades; the
attempts sidecar increments; the partial marker keeps the gameweek eligible; the
next 6-hourly tick retries the whole chain (every step is idempotent). After 8
failed attempts it stops retrying and the status says so; re-arm by deleting the
sidecar or running `--force-gw N` by hand. A FAILED tick decision (API
unreachable) writes `FAILED -- could not decide` to the tick file and retries next
tick without touching the volume.

## 7. Not done / unknowns, stated plainly

- The cron's own first firing (00:17Z) was not observed; the command string was
  proven under `sh` and the crontab parses. Check `/var/log/fpl-ingest.log` and
  `/health.data_freshness_by_source.weekly_ingest.last_tick` on 2026-09-12.
- Not in the chain (out of the scoped six steps): `merge_live_availability` (the
  deadline runner does it) and the fplcache-derived availability file
  (`live/availability_2026-27_fplcache.parquet`, built on the laptop from the
  fplcache clone, last 2026-08-29). The poller is authoritative for every live
  gameweek, so the deadline gameweek is unaffected; the fplcache file only fills
  older keys.
- A skeleton refresh happens only with an ingest. A fixture FPL moves between the
  weekly ingest and a deadline still trips the strict calendar check at T-90
  (three failed attempts, 1 credit each, no prediction) — by design; the ingest
  can be re-run by hand (`--force-gw` of the last gameweek) to refresh the
  skeleton if that happens before the window.
- The laptop is no longer the producer. Its copy of the volume goes stale from
  the first server ingest; sync down (not up) before running laptop-side tests
  that read the 2026-27 files, and compare manifests first.
- Understat from the droplet worked today (11 requests). A 403/429 in future is a
  hard stop in the fetcher (by design), surfaces as FAILED, and retries 6 h later.
