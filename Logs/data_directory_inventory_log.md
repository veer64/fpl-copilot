# data/ inventory for the server storage layout — 2026-09-03 (READ-ONLY)

Grain: every file the live pipeline reads or writes, grouped by lifecycle;
research artefacts summarized. Sizes measured on disk 2026-09-03; rows/cols
from parquet metadata (no loads). data/ total: **1,477MB**.

**Correction of record:** the earlier "~550MB/season poller" figure
(2026-09-01 measurement log §4) conflated `data/teamnews/` — 63MB of STATIC
team-news research (guardian_raw archive, closed study) that happened to be
downloaded in August — with the actual poller archive, which is
`data/live/bootstrap_raw/`: 1.81MB / 14 snapshots over two deadline windows,
**~0.9MB/gw ≈ ~35MB/season**. Compaction there saves almost nothing.

## REBUILT — fully regenerated each gameweek (idempotent; size ~constant or tracking season progress)

| file | size | rows×cols | grain | writer -> readers |
|---|---|---|---|---|
| history/all_seasons_with_2026_27.parquet | 7.63MB | 255,136×74 | player-fixture, all seasons 2016-17.. | fetch_fpl_history --combine -> season_stack.stack_path() (minutes, assembly detectors, walk_forward via load_stack, defensive fpl_official, postflight) |
| history/forward_skeleton_2026_27.parquet (+.provenance) | 0.11MB | 22,644×74 | synthetic player-fixture, unplayed gws (shrinks ~630 rows/gw -> 0 at GW38) | build_forward_skeleton -> season_stack.load_stack(), live_deadline calendar check |
| history/odds_fixtures_2026_27.parquet (+.provenance) | 0.08MB | 380×181 | fixture (odds-archive schema; prices null until odds refill) | fetch_fixtures (nulls prices) + fetch_live_odds (fills B365 cols) -> combine source |
| history/odds_all_seasons_with_2026_27.parquet | 0.50MB | 4,180×181 | fixture, all seasons | fetch_fixtures --combine / fetch_live_odds -> dixon_coles._load_matches (2026-27+), live_deadline preflight |
| history/understat_season_aggregates_2026_27.parquet (+.provenance) | 0.04MB | 364×19 | understat player-season (as-of played matches) | build_understat_aggregates -> combine source |
| history/understat_season_aggregates_with_2026_27.parquet | 0.52MB | 5,707×19 | understat player-season, all seasons | build_understat_aggregates --combine -> build_crosswalk |
| history/crosswalk_2026_27.csv | 0.02MB | 364×7 | element -> understat_id (grows ~as players debut, ~550 by GW38) | build_crosswalk -> live_deadline (preflight), walkforward_season |
| availability_2627.parquet (+.provenance) | 0.03MB | 23,611×18 | (element, gw) with asof_* columns (~constant: the element×gw grid) | merge_live_availability -> availability_features.load() glob |
| odds_props/props_crosswalk_2026-27.csv | 0.37MB | 1,425×19 | board name × (gw, event) -> element (~475 rows/gw -> ~18k, ~4.5MB by GW38) | build_props_crosswalk -> build_props_consensus |
| odds_props/props_consensus_2026-27.parquet | 0.03MB | 1,246×12 | (gw, element) consensus | build_props_consensus -> measurement readers |
| odds_props/props_consensus_fixture_2026-27.parquet | 0.05MB | 1,246×11 | (event, element) | build_props_consensus -> live_deadline.props_fixture_coverage |
| odds_props/props_consensus_book_2026-27.parquet | 0.08MB | 7,035×7 | (gw, element, book) (~75k rows, ~0.7MB by GW38) | build_props_consensus -> props_feature (the hook), Tests book gate |
| horizon/hmin_2026_27_refit.parquet | 0.35MB | 11,190×18 | (cutoff, gw-step, element) minutes prediction — APPENDS a cutoff per week under skip-if-exists (~3,730 rows/cutoff -> ~142k rows, ~6-7MB by GW38) | run_horizon_minutes -> live_deadline combined build, Tests |
| live/availability_2026_27_live.parquet | 0.02MB | 1,219×18 | (element, gw) poller-observed | poll_availability -> merge_live_availability |
| live/availability_2026-27_fplcache.parquet | 0.04MB | 23,607×18 | (element, gw) from the fplcache clone | build_availability (driven by d6_postwindow; clone lives OUTSIDE data/) -> merge_live_availability |

## APPENDS — gains rows each gameweek

| file | size | rows×cols | grain | per-gw | GW38 projection | writer -> readers |
|---|---|---|---|---|---|---|
| history/fpl_api_2026_27.parquet (+.provenance) | 0.09MB | 1,236×74 | player-fixture, 2026-27 finals only | ~618 rows | ~23.5k rows, ~1.5MB | fetch_fpl_history -> combine source, defensive official rows, sim prices |
| history/understat_matches_2026_27.parquet (+.provenance) | 0.04MB | 622×28 | player-match | ~311 rows | ~11.8k rows, ~0.35MB | understat_matches -> build_understat_aggregates |
| history/core_insights_*_2026_27.parquet (+.provenance) | 0.21MB | 610×90 / 400×66 | player-gw / player-match | ~305/~200 rows IF run | ~1.5MB | fetch_core_insights -> combine; **currently GW1-stale — not in the weekly runbook; record-source only since the fpl_official adoption** |
| history/core_insights_*_with_2026_27.parquet | 2.64MB | 30,588×90 / 26,993×66 | same, all seasons | — | ~4MB | fetch_core_insights --combine -> **no live-path reader today** (defensive's frozen record source reads the NON-with files) |

## ACCUMULATES — grows continuously

| store | size | growth | GW38 projection | writer -> readers |
|---|---|---|---|---|
| live/bootstrap_raw/2026-27/ | 1.81MB, 14 files | ~0.9MB/gw (deadline-window polls only) | ~35MB/season | poll_availability -> poll_availability replay, d6_postwindow |
| odds_props/raw/ | 10.60MB, 840 files | ~3.5MB/gw at the GW1-3 average (GW1-2 were 3-region historical backfills; live pulls run lighter, ~1-2MB/gw) | ~60-130MB/season | pull_live_props / pull_player_props_history -> build_props_crosswalk, build_props_consensus |
| history/understat_raw/ | 6.42MB, 1,540 files | ~40KB/gw | +1.5MB/season | understat_matches (cache; failed runs resume from it) |
| live/poller.log, GW*_WINDOW_STATUS, blind_window_diff_* | 0.07MB | trivial | trivial | poller/d6_postwindow diagnostics |

## STATIC — historical, never changes again (live-path inputs)

| file | size | rows×cols | role |
|---|---|---|---|
| history/all_seasons_fixed.parquet | 7.60MB | 253,900×74 | the frozen 2016-17..2025-26 archive; combine base; frozen-record parity; assembly/walkforward 2025-26-era readers |
| history/odds_all_seasons.parquet | 0.50MB | 3,800×181 | frozen odds archive; combine base; dixon_coles stored seasons |
| history/understat_season_aggregates.parquet | 0.50MB | 5,343×19 | frozen aggregates; combine base; assembly penalty join (prior-season label — sufficient through 2026-27) |
| history/understat_matches_2022_23..2025_26.parquet | 1.37MB | ~11.5k×28 each | frozen per-match; aggregates reproduction |
| history/player_id_crosswalk_final.csv | 0.03MB | 841×6 | 2025-26-era crosswalk (assembly, walkforward) |
| history/crosswalk_2023_24/2024_25/2025_26.csv | 0.07MB | ~550×7 each | frozen season crosswalks (arm rebuilds, tests) |
| availability_2122..2526.parquet | 0.96MB | 25-30k×18 each | historical availability — LIVE-PATH READS (availability_features.load() globs all of data/availability_*.parquet for training) |
| history/vaastav_gw1_2026_27_reference.csv | 0.10MB | 610×45 | the 100.00%-parity verification reference |
| history/fpl_api_2026_27_PROVISIONAL_gw2.parquet (+.provenance) | 0.08MB | 626×74 | the kept provisional pull — the gate-evidence record (never merged) |
| history/2016-17..2025-26/ (vaastav dirs) | 53.3MB | — | raw sources the frozen archive was built from; ingestion verifiers only |
| history/core_insights/ | 15.5MB | 116 files | raw core-insights pulls (record source) |
| history/odds/ | 1.5MB | 10 files | raw odds archive sources |

## Research artefacts — 7. / 8.

**The live subset — what a live deadline build + weekly refresh actually
touches (every REBUILT/APPENDS/ACCUMULATES row above plus the STATIC
live-path inputs): ~40MB today, ~150-190MB by GW38** (dominated by
props raw). Everything else is research:

| block | size | read by |
|---|---|---|
| loose walkforward_h6_* research frames (54 files, data/ root) | ~850MB | measurement scripts + EXPECT/provenance tests (records) |
| arms_gap0/ | 208MB | season-totals index, reference-cell tests (2425/2335/2266), extraction-parity |
| arms/ | 149MB | armlogs — the records of record |
| teamnews/ | 63MB | closed team-news study (guardian_raw 63.06MB; oraclelogs) |
| horizon/hmin_2023_24/2024_25/2025_26_refit | 21MB | arm rebuilds, record-parity tests |
| odds_props historical consensus/crosswalks (2024-25, 2025-26) | 8.6MB | props measurement scripts, backtests |
| walkforward_2526 / predictions_2526 / wf_test / d4_* / root logs | ~10MB | simulator/optimize legacy defaults, provenance test, synthetic_lambda (closed), measurement records |
| p1, sweep, chips, leakfix_logs, penfix_logs, data description | ~6MB | their measurement scripts / records |

**Nothing in the live deadline path reads any of these** — verified by
tracing every read in live_deadline, walkforward_season, walkforward_arms,
season_stack, minutes, assembly, defensive, dixon_coles, props_feature,
horizon_minutes, availability_features. ONE caveat stated plainly: the TEST
SUITE does read them (arms_gap0 extraction-parity, walkforward provenance,
EXPECT cells). A server that only builds deadline frames doesn't need them; a
server expected to run the 226-test gate does.

## 9. Poller snapshots — corrected

`live/bootstrap_raw/`: 1.81MB / 14 files after two deadline windows. The
poller runs only inside deadline windows (D6), so growth is ~0.9MB/gw ≈
**~35MB/season**. Compaction would save at most tens of MB per season —
not worth designing for. The ~550MB/season figure in the 2026-09-01 log was
wrong (attributed August's static teamnews research downloads to the poller);
corrected here.

## 10. Files nothing reads

- `.falsify_perturb.parquet` (14.75MB, data/ root) — falsify_perturbation.py's
  own TEMP file, left behind; nothing reads it back.
- `walkforward_h6_2526_dgwonly.parquet` (14.82MB) and
  `walkforward_h6_2526_odds2.parquet` (14.72MB) — no reference anywhere in
  *.py (probe-era frames; their siblings _av/_prefix ARE read by scripts/tests).
- `history/ingest_run.ps1/.log/.err`, `history/gw2_provisional.log/.err` —
  one-shot run scratch.
- `odds_props/raw_backup_2026-08-24.tar.gz` (+.sha256, README) — deliberate
  pre-cleanup backup; referenced only by its README.

Total unreferenced: **~46MB**. Proposing no changes per the task.
