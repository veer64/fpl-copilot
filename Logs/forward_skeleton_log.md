# Forward-gameweek skeleton — 2026-08-31

The last structural blocker for a live horizon-6 frame: the master gains a gameweek
only after it is played, so a 2026-27 H=6 build silently collapsed 6 -> 1 (and a live
unplayed DEADLINE gameweek had no step 0 at all — minutes.py predicts for the
master's rows at the predict gw). `eval/build_forward_skeleton.py` now supplies
synthetic player-fixture rows for unplayed gameweeks; `season_stack.load_stack()` =
stack + skeleton, wired into exactly the consumers that need future rows
(walk_forward, minutes, live_deadline's combined path and preflight). Archives
untouched; the skeleton is derived state, regenerated per pull.

## Backfill verification (the deliverable) — construction VERIFIED at all three cutoffs

2025-26, skeleton from (final calendar + identity-as-of-k) vs the master's actual
rows, horizon window:

| cutoff | window | churn | construction cols (team/opp/was_home/kickoff) | per-(element,GW) fixture counts | value drift | pos reclass |
|---|---|---|---|---|---|---|
| GW5 | 6-10 | 0.5% (18 joiners) | ALL EXACT | 0 mismatches / 3,705 pairs | mean +0.19, p95 1.0 | 0 |
| GW20 (Jan window) | 21-25 | 3.1% (24 departed, 99 joined, 1 moved-and-met) | ALL EXACT | 0 / 3,950 | mean +0.05, p95 1.0 | 0 |
| GW30 (spans DGW33, 13 fixtures) | 31-35 | 0.8% (32 joiners) | ALL EXACT | 0 / 3,702, max 2 fixtures/gw | mean +0.04, p95 1.0 | 0 |

Doubles give two rows with distinct fixture ids and real kickoffs; blanks give none;
joins land; per-(element, GW) fixture-count identity holds through the double.
Notable exhibit, classified as churn not construction: **Ward-Prowse, West Ham ->
Burnley inside the January window, and his old and new clubs then MET (fixture
244)** — the same (element, fixture) key on both sides with club columns differing.
The master's 100/391-class byte-identical duplicate rows are dropped and counted,
mirroring assembly's documented dedup.

## Parity (the gate) — PASS

The frozen records were built on core-insights DC (superseded by the 2026-08-31
adoption), so the isolated gate pins that source, making the skeleton the ONLY
variable: **BIT-IDENTICAL, both configs, GW5/20/33** — through the load_stack
concat (which upcasts the master's int64 stat columns to float64), the pen-rate
denominator change, and the preflight rewiring. The suite's record-parity tests run
the same pin and pass (216). The CLI `--parity` under the live default shows
exactly the quantified DC-adoption move (max 0.540/0.498/1.396 on 243/235/251
rows) — the known model change, not the skeleton.

## The 2026-27 horizon-6 build — the collapse is CLOSED

GW1 baseline H=6: **six steps, rows 610 / 626 / 626 / 626 / 626 / 626** (step 0 =
master GW1 actual rows; steps 1-5 = forward rows), e_points real at every step
(means 1.37 / 1.30-1.33). DC sits at the cold-start base rates (610/610, reported);
every lambda pure DC (odds pending).

## What forward rows carry, and the stated limits

element/name/position/team/opponent_team(int id)/GW/round/fixture/was_home/
kickoff_time/value; every measurement column NaN (int64 -> float64 in the file).
Information-set limits recorded in provenance, not hidden: value = price at pull
time (drift unknowable; measured mean +0.04..+0.19 over a window historically);
club assignment = bootstrap current squads (window churn 0.5-3.1% measured).
Postponed fixtures (event/kickoff null) are EXCLUDED, never assigned, and listed in
provenance so an under-counted gameweek is visible (2026-27 today: none; 370
forward fixtures, gws 2-38, 23,162 rows).

## Residual risk, stated plainly

The backfill cannot prove calendar-as-of-cutoff fidelity: only the FINAL 2025-26
calendar exists, not what the endpoint showed at cutoff k, so reschedule behaviour
is historically untestable. The live mitigation is the STRICT RE-PULL CHECK
(#14 class): at decision time (strict preflight only — report mode stays offline),
fixtures/ is re-pulled and (fixture id, event, kickoff_time) compared against the
calendar snapshot in the skeleton's provenance; any mismatch touching the target
gameweeks raises (a moved kickoff shifts match_date and silently drops the DC
join). Unchanged-calendar runs append a note. Offline at decision time is itself a
strict finding.

## Strict preflight, 2026-27 GW1 horizon-6 combined — four findings, skeleton CLOSED

1. props per-book consensus missing (2026-27)
2. hmin refit missing (2026-27)
3. odds PRICES missing for ALL 10 GW1 fixtures
4. odds PRICES missing for ALL 50 fixtures in the steps-1+ window (GW2-6) — this
   check could not even RUN before (no window to derive); the skeleton closing the
   horizon exposed it, honestly.

The horizon-collapse finding is gone; it returns if the skeleton is absent or
stale for the window.

## Tests (suite 216)

double -> two rows / blank -> none / postponed excluded; played fixtures never
duplicated; the GW20 backfill as a construction regression; the re-pull check notes
on match and RAISES on a moved fixture (monkeypatched); the record-parity tests
unchanged and green with the skeleton present.

Weekly ops order gains: fetch_fpl_history -> ... -> fetch_fixtures ->
merge_live_availability -> **build_forward_skeleton** (refresh at every deadline
run; the strict re-pull check enforces freshness).
