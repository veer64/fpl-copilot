# FPL-API ingestion replacing vaastav for 2026-27 (2026-08-31)

`eval/fetch_fpl_history.py`; `Tests/test_fetch_fpl_history.py`. Ingestion only: no modelling code changed,
no DC source swap, `DC_SEASONS`/`defensive.py` untouched. Follows the 2026-08-31 read-only investigation
(FPL API reproduces every modelling-read vaastav column at 100.00% on 2026-27 GW1, both grains; vaastav's
own cadence collapsed mid-2025-26 and GW1 2026-27 landed 8 hours before the GW2 deadline).

## Design

- **Schema contract read at runtime**, never hardcoded: columns, order and dtypes come from
  `all_seasons_fixed.parquet` itself. Player-FIXTURE grain via `element-summary/{id}/` (one call per
  element — the same construction vaastav uses), names/positions/teams from `bootstrap-static/`,
  fixture→team mapping from `fixtures/`.
- **The `team` timing trap is closed structurally**: the player's team is derived from the fixture he
  appears in (`team_h` if `was_home` else `team_a`), never from bootstrap's current-team field (which is
  as-of pull time and measured 98.52% after one transfer window). Retro backfills are therefore safe.
- **`value` is the per-gameweek price** from element-summary (the price FPL fixed for that GW, proven
  100.00% == vaastav), never the live bootstrap price.
- **Self-check on every pull**: per-gameweek sums of the emitted per-fixture rows are compared against
  `event/{gw}/live/` for EVERY element (minutes, total_points, bps, bonus, goals, starts) — a partial
  fetch cannot pass. Hard assert for final pulls.
- Conventions: real User-Agent, 3 retries with backoff, 0.4 s between calls, structured log lines, atomic
  temp-then-rename writes, per-gameweek upsert deduped on (element, fixture, GW).

## The data_checked gate

A gameweek is written as FINAL only when its event carries `finished AND data_checked` — until then FPL
revises bps, bonus and occasionally goals/assists. Anything earlier is refused
(`ProvisionalGameweekError`) unless `--provisional`, which writes to a separate
`fpl_api_{tag}_PROVISIONAL_gw{n}.parquet` (same schema) with its own provenance JSON. **Finality is
represented by which file a row lives in**: provisional files are never merged into the season file or the
combined stack, and the season file's sidecar (`fpl_api_{tag}.provenance.json`) records
`finished`/`data_checked`/`pulled_at`/cross-check results per gameweek — `test_no_provisional_rows_in_season_file`
asserts every gameweek present is data_checked.

Measured why the gate matters (2026-08-31, GW2 pre-data_checked): element-summary and event/live
**disagreed on 31 cells** during the provisional window — minutes off by up to 12 for the same player
(e.g. element 4: 8 vs 20) — so for provisional pulls the cross-check is recorded in provenance instead of
raising; for final pulls it stays a hard assert (GW1 passed it exactly).

Demonstrated end-to-end (2026-08-31 15:30): the GW2 `--provisional` pull wrote
`fpl_api_2026_27_PROVISIONAL_gw2.parquet` (626 player-fixture rows) with **43 in-flight mismatch cells
recorded in its provenance** (up from 31 an hour earlier -- the numbers were literally moving between
pulls, e.g. element 1 minutes 27 vs 21); the side file was not merged anywhere.

## Append, do not rebuild

`all_seasons_fixed.parquet` is never touched (the API serves only the current season; the archive stays
the source of truth for the past). Final gameweeks upsert into `data/history/fpl_api_2026_27.parquet`;
`--combine` writes `data/history/all_seasons_with_2026_27.parquet` = archive + API season file, schema
asserted equal (one documented parquet round-trip artefact: `modified` reads from the stack as object only
because pre-2017 seasons carry nulls; the all-bool season column casts losslessly). Nothing in modelling
reads the combined file yet — deliberately, because the season-boundary constants are unfixed (below).

## The deliverable: GW1 verification vs vaastav's published gw1.csv

Final pull 2026-08-31: 610 player-fixture rows, 10 fixtures, 629 API calls, event/live cross-check PASSED.
Compared against `vaastav/Fantasy-Premier-League data/2026-27/gws/gw1.csv` (kept as
`data/history/vaastav_gw1_2026_27_reference.csv` for the regression test):

- **Rows: 610 = 610, matched 610, zero rows unique to either source.**
- **All 22 modelling-read columns: 100.00% exact** (GW, name, position, team, opponent_team, was_home,
  kickoff_time, minutes, starts, total_points, value, goals_scored, assists, clean_sheets, saves,
  yellow_cards, red_cards, goals_conceded, penalties_missed, own_goals, bps, bonus).
- **Every other shared column also 100.00%** (DC + components, all xG fields, ICT, transfers, selected,
  scores, modified, round) — with ONE exception: **`xP` 0.00%**, vaastav's own prediction model, which has
  no API source, is not read by any modelling code, and is emitted as null. Not a tolerance — an explained,
  structural absence.

## Season boundaries exposed by appending 2026-27 (REPORTED, NOT FIXED — none extended in this task)

| constant | location |
|---|---|
| `order` ladder (prev-season priors) | `squad/minutes.py:90` |
| `DC_SEASONS` | `eval/walkforward_season.py:62` |
| `ORDER` | `eval/walkforward_season.py:59-60` |
| `LABELLED` | `eval/walkforward_season.py:64` |
| `DC_RULE_SEASONS` | `squad/defensive.py:231` (+ `SEASON` at :24, `_DC_HITS_CACHE` keyed without season at :232) |
| `BLEND_PRIOR` | `squad/attacking_rates.py:46` (+ `PRIOR_SEASONS` :58-66 for the legacy gate) |
| `SEASON_TO_US` | `eval/build_crosswalk.py:60` |
| `SEASONS` | `eval/understat_matches.py:56` |
| `TRAIN_SEASONS`/`PREDICT_SEASON` defaults | `squad/minutes.py:36-37` (call sites pass explicit values) |

`live_deadline.preflight` already raises on the minutes ladder, DC sets, BLEND_PRIOR and the data absences
under strict mode.

## What this does NOT unblock — still standing between here and a live GW7 prediction

1. **Fixtures/odds for the deadline gameweek**: the fixture universe the model consumes IS the odds
   archive (`odds_all_seasons.parquet`, football-data E0 — closing odds, published after matches). A live
   deadline needs pre-kickoff odds (or a pure-DC week) and 2026-27 fixture rows in that file; no fetcher
   exists.
2. **Understat 2026-27**: per-match file (rate blend's current-season side) and season aggregates
   (crosswalk, penalty join). `eval/understat_matches.py` exists but its `SEASONS` dict ends at 2025-26,
   and its `gw` mapping needs the very 2026-27 vaastav-shaped rows this fetcher now provides.
3. **The 2026-27 crosswalk**: buildable only once Understat serves 2026-27 ('2026' aggregates) and
   `SEASON_TO_US` is widened; until then every player takes positional-prior rates (the Cherki class).
4. **The season-list extensions** above — each a gated, stamped change in its own right.
5. **Steps 1–5 minutes substitution for the combined arm**: lives only inside `walkforward_arms.main` as a
   closure; a live H=6 frame for the planner needs it importable.
6. **Core-insights 2026-27 ingest** (or the measured API alternative) for the DC term — deliberately out of
   scope here; the DC source swap is a model change needing its own measurement (API counts disagree with
   core-insights on ~13% of rows).

## Tests

`Tests/test_fetch_fpl_history.py` (suite 178): the data_checked gate refuses unfinished/unchecked
gameweeks (no network); output schema == stack schema exactly (columns, order, dtypes, with the documented
`modified` round-trip allowlist); GW1 parity vs the vaastav reference fails on regression; no gameweek in
the season file without a data_checked provenance entry.
