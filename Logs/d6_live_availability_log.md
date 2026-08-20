# D6 (free half) — live availability poller: closing the blind window

**Status: BUILT AND VERIFIED 2026-08-20. NOT integrated into the model.**
Script: `eval/poll_availability.py`. First live deadline it will serve:
**GW1 2026-27, 2026-08-21 17:30 UTC**.

## 1. The problem

fplcache snapshots bootstrap-static 4×/day (~6h gaps). News breaking inside
the pre-deadline gap is invisible — Gvardiol GW1 2025-26 (stamped 68 min
after the last snapshot, 3.5h before the deadline; predicted 72 min, played
0) is the flagship case. The historical `asof_*` reconstruction recovers
these after the fact; live operation needs the state at decision time.

## 2. What was built

- **Schedule, derived from the API's own `events`** (never hard-coded):
  every 30 min from deadline−4h, every 10 min in the final hour, plus one
  poll just after the deadline — the post-deadline poll enables the exact
  `late_news` recovery rule `eval/build_availability.py` uses on fplcache,
  so live and historical tables are built by the SAME rule.
- **Tick model**: `--once` decides for itself whether a poll is due (cadence
  gating against the newest raw file) and exits quietly otherwise. Any
  external scheduler at any frequency is safe; sleep/reboot/double-start are
  all idempotent. `--watch` is a convenience loop around the same tick.
- **Raw-first archive**: `data/live/bootstrap_raw/<season>/<utc>.json.gz`,
  temp-then-rename — a failed fetch never lands, every derived table is
  rebuildable.
- **Change detection**: any move in `status` / `chance_of_playing_this_round`
  / `news` between consecutive polls → row in
  `data/live/availability_changes_<season>.parquet` with minutes-to-deadline.
  This is the signal the blind window was hiding.
- **`--build`**: derives `data/live/availability_<season>_live.parquet` at
  (gw, element) grain — column list, order, dtypes and asof rule IDENTICAL
  to `data/availability_{season}.parquet` (verified against
  availability_2526.parquet: columns identical, dtypes cast to match), so
  existing feature code reads it unchanged. `asof_source` is
  `live_snapshot` / `live_late_news`.
- **Schema-drift guard**: required event/element fields asserted on every
  fetch with the missing field named; an unknown status letter raises
  (the a/d/i/s/u/n characterisation would no longer cover the data).

## 3. Verification (2026-08-20, live API)

Season derived 2026-27; GW1 deadline read from events; two forced polls
stored (599 elements each, gzip ~131KB); change detection ran (zero changes
across 1s — correct); `--build` correctly refuses while no deadline has
completed; cadence gate correctly reports "window opens at deadline−4h".

## 4. Scheduling (proposed, NOT registered)

Windows Task Scheduler, every 10 minutes; the tick gates itself:

    schtasks /Create /TN "FPL availability poller" /SC MINUTE /MO 10
      /TR "\"C:\...\uv.exe\" run python eval\poll_availability.py --once"
      /ST 00:00

(Or run `--watch` in a terminal on deadline days.) Left to the user: it
changes machine state.

## 5. Reconciliation with the fplcache-derived historical files

The two archives have different granularity and MUST NOT be silently mixed:

1. **Separate files, separate namespaces.** Historical:
   `data/availability_{season}.parquet` (fplcache, 4×/day, whole season).
   Live: `data/live/availability_{season}_live.parquet` (10–30 min, deadline
   windows only). No file overwrites the other.
2. **Row-level provenance.** `asof_source` values are disjoint:
   `snapshot`/`late_news` (fplcache) vs `live_snapshot`/`live_late_news`.
   Any future merged view carries the source per row by construction.
3. **The same construction rule** (last strictly-pre-deadline snapshot +
   post-deadline late-news recovery) means the columns MEAN the same thing;
   the only difference is `hours_before_deadline` (≤6h vs ≤0.5h) — which is
   exactly the quantity D6 exists to shrink.
4. **Backtest policy unchanged**: fplcache remains the backtest source
   (per the availability log); the live archive becomes a backtest source
   only once enough gameweeks accumulate, and then only via an explicit,
   stamped decision — not by silent preference.
5. **The payoff measurement**: for any gameweek where BOTH exist, comparing
   fplcache's asof table against the live final poll quantifies what the 6h
   window actually misses (the Gvardiol class) — that comparison is the
   first analysis to run once live gameweeks accrue, and it doubles as the
   Understat-lag measurement's sibling (handoff item J).

## 6. Not done, deliberately

No model integration, no scheduler registration, no merged
live+historical view. Build, store, verify only.

## 7. PARKED (2026-08-20) — built, one live smoke test, then production wiring

**Status: built and parked, with a single live smoke test at GW1 2026-27.**
The poller will be run MANUALLY for the GW1 window (2026-08-21, deadline
17:30 UTC), started around 13:30 UTC via `--watch`, as a one-off
verification that it works against the live API under real conditions.
No scheduler registered, no ongoing operation, no model integration.
Ongoing operation is deferred to production wiring.

**Why parked — recorded so no future session relitigates it.** The poller's
value CANNOT be measured retrospectively. It exists to capture news that
fplcache missed, and anything fplcache missed is by definition absent from
every archive on disk. The only possible measurement is to run it live and
diff against fplcache afterward. That measurement is DEFERRED, not skipped.

**Scheduling options considered (for the production decision):**
- GitHub Actions: free, but cron drifts 5–15 min — poor for the final hour,
  which is exactly the window that matters.
- The existing DigitalOcean droplet: precise, always on, already paid for —
  the likely production answer.
- Windows Task Scheduler on this machine: fails when the machine sleeps,
  as it did on 2026-08-19 mid-run. Not suitable unattended.

**Expected magnitude, for calibration:** the availability log measured ~47
rows per season where the late-news recovery rule changes anything, 42 of
them flipping `a` → not-`a`. This is a small, sharp fix, not a large one —
but the flips it catches are exactly the Gvardiol class.

## 8. GW1 smoke test — what to check afterward (mechanical)

1. **Snapshot count and cadence**: expect ~8 polls at 30-min spacing from
   13:30, ~6 at 10-min spacing in the final hour, plus one post-deadline
   poll. Gaps mean the watch loop or the machine stalled.
2. **Change rows**: did any fire in `availability_changes_2026_27.parquet`,
   and how many minutes before the deadline (the `minutes_to_deadline`
   column is the payoff figure).
3. **`--build`**: produces `availability_2026_27_live.parquet` with columns,
   order and dtypes matching the historical schema (the §3 check, now on
   real completed-deadline data).
4. **Diff against fplcache** once its GW1 snapshot lands: same (gw, element)
   grain, compare asof_* — anything the live poll saw that fplcache's
   reconstruction missed is the first real measurement of the blind window.
