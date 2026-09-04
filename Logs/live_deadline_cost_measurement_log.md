# What a live deadline build costs — memory, time, disk — 2026-09-01

READ-ONLY measurement on the laptop (Windows 11, multi-core; the droplet is
1 vCPU / 2GB / 50GB Ubuntu 24.04 running fpl-copilot + fpl-postgres under
docker-compose). No code changed; every step is the idempotent weekly re-run.
Question: does the per-deadline workload fit the droplet?

**Method.** Each step run as a subprocess of `.venv` python with a 50ms RSS
sampler; peak = max of OS-tracked `peak_wset` over the process tree (the venv
python.exe is a shim, so the real interpreter is the child — the tree number
is the honest one). Raw records: scratchpad `measurements.jsonl` (session
temp). Solver: HiGHS in-process at gapRel=0/gapAbs=0 (the gap0 convention,
optimize.py:147).

## THE PEAK

**The horizon-6 combined build peaks at 1,590MB (OS-tracked; 1,504MB
sampled). It does not fit a 2GB droplet that is already running Docker,
Postgres and the OS.** Everything else fits under 600MB.

## 1. Per-step peak RSS and wall clock

| step | wall | peak RSS | bound by |
|---|---|---|---|
| fetch_fpl_history --gw 2 | 351.8s | 435MB | network (632 rate-limited API calls) |
| fetch_fpl_history --combine | 3.0s | 593MB | memory/CPU (254k-row archive concat) |
| understat_matches | 3.9s | 133MB | network (steady-state: league listing only) |
| understat aggregates + combine | 1.9s | 118MB | CPU |
| build_crosswalk | 4.3s | 146MB | CPU |
| fetch_fixtures | 1.8s | 201MB | network (one pull) |
| fetch_fixtures --combine | 3.0s | 198MB | CPU |
| merge_live_availability | 0.7s | 147MB | CPU |
| build_forward_skeleton | 1.1s | 485MB | CPU (+1 network call) |
| fetch_live_odds | 1.8s | 205MB | network (1 credit) |
| strict preflight (combined, H6) | 1.9s | 258MB | CPU (+ calendar re-pull) |
| **build_deadline_frame combined H6** | **16.0s** | **1,590MB** | **memory/CPU** |
| optimizer (load + open15 + 6-gw MIP) | 23.5s | 416MB | CPU |

Laptop total for one deadline: **~7 minutes**, of which ~6 minutes is the
rate-limited element-summary crawl (identical on any machine). The
CPU-bound work is ~45s on this laptop; on 1 vCPU expect roughly 2–4x —
still minutes, not hours. Time is not the constraint anywhere; memory is.

Not in scope (per task list): pull_live_props (network, 30 credits) and the
props crosswalk/consensus rebuilds (seconds, small frames, run earlier today).

**Measurement incident, recorded honestly:** the first fixtures measurement
"hung 1800s" — that was the HARNESS (subprocess stdout PIPE never drained
until exit; fetch_fixtures emits a large wall of PerformanceWarnings that
filled the 64KB pipe and blocked the child). Re-measured with output drained:
1.8s. The 1800s row in measurements.jsonl is invalidated. Side observation
for ops: any wrapper that pipes fetch_fixtures' output must drain it, or
suppress the warning spew with 2>$null as the runbook already does.

## 2. Where the build's memory goes

In-memory (deep) sizes of what the build path holds:

| frame | rows × cols | memory |
|---|---|---|
| cross-season stack (all_seasons_with) | 255,136 × 74 | 217MB |
| forward skeleton | 22,644 × 74 | 19MB |
| load_stack() = stack+skeleton concat | 277,780 × 74 | 236MB |
| core-insights gameweek stats | 30,588 × 90 | 32MB |
| availability | 23,611 × 18 | 12MB |
| odds/fixture universe | 4,180 × 181 | 7MB |
| understat aggregates | 5,707 × 19 | 6MB |
| hmin refit | 11,190 × 18 | 5MB |
| props consensus | ~9.5k total | ~2MB |
| **the OUTPUT frame (3,774 rows)** | 3,774 × ~50 | **3.6MB** |

**Everything is loaded whole; nothing is streamed.** The 1.6GB peak is ~6-7
full-stack equivalents alive at once: `load_stack()` is called independently
by minutes.py, the walkforward path and the preflight (each holding its own
236MB copy), assembly reads the season file again, concat itself transiently
holds source+result (~470MB), and pandas merges copy. The output is 0.2% of
the peak — the build's memory is all input scaffolding, none of it output.

## 3. The optimizer — first end-to-end exercise of the live-sim path

The GW3 combined frame was fed through `load_season` (prices joined per
(element, round) from a master+skeleton concat — the join the handoff's open
item 4 predicted; it worked), `gw_slice(3, cutoff=3)` gave a 629-player pool,
and:

- opening fifteen (single-gw XI+captain MIP): **0.4s**, squad cost 99.9
- **decide_gameweek_mip GW3, horizon 6, gapRel=0: 22.4s**, peak process RSS
  416MB. It held (0 transfers — correct: the state WAS the frame's own
  optimum), captain Haaland, objective 99.41.

Consistent with the backtest reference (33–41s median per deadline on this
laptop). On 1 vCPU expect roughly a minute typical, a few minutes worst-case
(backtest worst >180s laptop). Memory-wise the solve fits the droplet today.
This was a plumbing/measurement exercise, not a decision of record — the
opening state was synthetic, not the user's real squad.

## 4. Disk

`data/` today: **1,477MB**. Composition: ~897MB loose research walkforward
frames (~50 files × ~17MB, static), arms/arms_gap0 357MB (static research),
history 110MB, teamnews 63MB, odds_props 23MB, horizon 21MB, rest small.

A season of weekly ingests adds roughly:
- teamnews poller snapshots: 63MB accrued in August alone → **~550MB/season**
  (the dominant grower; compaction would cap it)
- props raw boards: ~3.5MB/gw → ~130MB/season
- master/understat/availability/hmin: < 2MB/gw combined → ~60MB/season

Call it **+0.75GB/season**. The subset a live build actually needs
(history + horizon + odds_props + live + availability) is ~250MB today.
Disk is a non-issue on 50GB even with Docker and Postgres resident.

## 5. Verdict

**The full sequence does not fit the 2GB droplet. The constraint is memory,
in exactly one step: the build (1.6GB). CPU is not a constraint anywhere.**

- The 2GB droplet already spends several hundred MB on Ubuntu + dockerd +
  Postgres + the FastAPI app. The build's 1.6GB peak lands on top of that:
  OOM-kill or swap-thrash territory. Not "tight" — does not fit.
- **Could run there comfortably today:** every fetch/merge step ≤ 258MB
  (ingest crawl, understat, crosswalk, fixtures, availability, odds,
  preflight), and the optimizer at 416MB. The two ~500-600MB steps
  (ingest --combine, skeleton) fit but tightly — schedule them off-peak.
- **Could not:** build_deadline_frame (1.6GB).
- **A 4GB droplet fits the whole thing with headroom** (1.6GB peak + ~0.8GB
  system/containers ≈ 2.4GB, >1.5GB free); 1 vCPU only stretches ~45s of
  CPU work to a few minutes, fine against a weekly deadline. 2 vCPU would
  also serve the app while a build runs, but is optional.
- The natural split if the droplet stays 2GB: ingestion + solve on the
  droplet, the build on the laptop — but that leaves the deadline-critical
  step on the non-server machine, which defeats the purpose. If the pipeline
  is to live server-side, resize to 4GB.

Caveats: Windows RSS ≈ Linux RSS for this workload (same pandas/pyarrow
allocations), sampled at 50ms with the main child's OS-tracked peak_wset as
the authority; figures are one run each, but the big numbers are structural
(frame sizes), not noise. Measurement spent 3 odds credits (19,361 remain).
