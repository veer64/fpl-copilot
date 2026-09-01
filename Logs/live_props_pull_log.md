# Pre-deadline live props pull — 2026-09-01 — THE COMBINED CONFIG IS LIVE-READY

`eval/pull_live_props.py` closes the last input between the combined config and a
live prediction.

## The milestone, stated plainly

**A real 2026-27 GW3 horizon-6 COMBINED build ran END TO END UNDER STRICT and
raised nothing.** 3,756 rows, six steps of 626; props overrode 407 player-fixtures
at step 0; the hmin refit substituted 3,130 rows at steps 1-5 (0 stale fallbacks);
the fixture-calendar re-pull check verified live against the skeleton snapshot;
every finding a note. Strict preflight finds NOTHING that raises. The suite pins
this as `test_strict_preflight_combined_clean_at_live_deadline` — if it ever
raises again, a live input has rotted.

## What is shared, what is new

SHARED (the whole downstream pipeline): build_props_crosswalk ->
build_props_consensus unchanged; the live puller writes the historical pull's
exact raw layout (gw{gw}_{event}_{regions}.json wrapped {"data": ...} +
manifest.csv rows) and imports its helpers (fixtures, deadlines, token matching,
atomic writes). NEW: the live endpoints (events list FREE; per-event odds at
markets x regions), snapshot-REPLACE semantics (a re-pull supersedes the
gameweek's manifest rows — the latest pre-deadline board is the record), and
per-fixture pull-timestamp provenance (manifest snapshot column + minutes-to-
deadline).

## Timing

Cadence: run in the pre-deadline build sequence, recommended T-90..T-30 min. The
historical deadline-60s convention cannot run that late unattended. The
pre-deadline-snapshot-is-the-decision-set reasoning HOLDS for props, strengthened:
the FPL deadline sits ~90 min before first kickoff, so confirmed lineups exist at
NEITHER deadline-60s NOR T-90 — the two snapshots are the same pre-lineup
information class, differing by up to ~an hour of drift. A pull after the deadline
prints a loud post-deadline warning. This first pull ran early (T-78h, GW3
deadline Fri) — re-run near the deadline to refresh; re-pulls replace.

## Regions and credits

eu,us,us2 (us2 required: bovada and rebet live there) = **3 credits/fixture**.
This pull: 10/10 fixtures, **30 credits**. Task total 30; paid key now
**635/20,000 used, 19,365 remaining**. Steady state ~30-60 credits/gameweek
(1-2 pulls) ≈ 1,140-2,280/season.

## Coverage and the floor

GW3: **10/10 fixtures priced (100%)** — 7-11 books per board at pull time. The
floor (PROPS_MIN_FIXTURE_COVERAGE = 0.80) fires on the DEADLINE gameweek —
corrected this task to be strict for the deadline gw ONLY: the hook moves
step-0 rows exclusively ("only rows with gw == cutoff move"), so steps-1+ board
coverage never reaches the model — the same step-0-only correction the odds
check received (ODDS_HORIZON_GWS=0). Steps-1+ coverage is now a labelled note.
Partial boards are counted, never hidden (thin-panel -> unpriced-counted at
consensus; per-fixture override counts in the hook; the unavailable-board test
pins that 0/10 RAISES).

## The weekly crosswalk step

The live path runs the same crosswalk refresh (rerun after the pull; ~1 min).
GW1-3 state: 0 manual entries needed; unmatched names are SURFACED, not buried —
the crosswalk prints "Unmatched WITH a candidate name — the proposed MANUAL
pass" plus the top-25 unmatched by implied probability (currently led by
transfer-window master-staleness: Jackson 0.44, Guessand 0.36, ...), and writes
the same tables to Logs/props_crosswalk_log.md. A maintainer watches exactly
those two lists.

## The sequence

... -> build_forward_skeleton -> fetch_live_odds -> **pull_live_props ->
build_props_crosswalk -> build_props_consensus** -> strict preflight -> build.
SEPARATE from fetch_live_odds, deliberately: different endpoint family
(per-event props vs one h2h sweep), different output (raw boards for the
three-step pipeline vs price columns in the odds slice), different failure
domains. They share only the key and the conventions.

## Failure behaviour

Board unavailable / API error at deadline time: the events call raises loudly,
a per-fixture odds failure is recorded as CALL_FAILED and stays unpriced-counted,
and the strict coverage floor RAISES on the deadline gameweek — the combined
config can never silently become horizon-only. Maintainer action: retry the
pull closer to the deadline; if the provider is down outright, the choice is
explicit — run baseline, or run combined non-strict with the finding on record.
Nothing decides that silently.

## Parity (the gate)

Record DC source pinned, both configs, GW5/20/33: **BIT-IDENTICAL, all six
cells.** Suite **226 passed** (new: the milestone test and the
unavailable-board-raises test; the still-raises pin was retired by its own
closing-update rule).
