# Understat ingestion for 2026-27 (2026-08-31)

`eval/understat_matches.py` (extended) + `eval/build_understat_aggregates.py` (new) +
`Tests/test_understat_ingest.py`. Ingestion only: no modelling code changed, no season constant extended
(`BLEND_PRIOR` untouched), no crosswalk built. Conventions match the other two fetchers of this session.

## Part A — the per-match file

**What changed in `understat_matches.py`, exactly:**
1. `SEASONS` gained `"2026-27": 2026` (also unblocks the argparse `choices`).
2. `_fetch_json` gained 3 retries with backoff and an IMMEDIATE hard stop on HTTP 403/429 ("STOP; wait
   and retry later at 1 req/s. Do not reduce the spacing."). Request spacing stays the existing
   `RATE_SECONDS = 1.05` between every match fetch; league listings are one request per run.
3. `_gw_lookup` now returns (date→gw map, per-gw fixture counts, source) and re-points the kickoff
   source: vaastav rows where the season exists in `all_seasons_fixed.parquet`, else
   **`data/history/fpl_api_{tag}.parquet`** (the FPL-API season file, which by construction contains only
   `data_checked`-FINAL gameweeks). Neither present → `LookupError` — a silent empty lookup would send
   every row to `gw=None`.
4. New `split_final_deferred`: on an archive season a residual `gw=None` **raises** listing the matches;
   on a live season a match whose date maps to no (final) gameweek, or whose gameweek is not fully
   covered by Understat results, is **DEFERRED** — dropped from the write, listed match-by-match, and
   recorded in a provenance sidecar. `gw=None` can never silently pass through.
5. The live-season write is atomic and casts `gw` back to int64 (the split's None-carrying column floats
   otherwise — caught by the schema test).

**The finality split** is therefore structural: because the gw map contains only FINAL gameweeks, rows
exist in `understat_matches_2026_27.parquet` only once their gameweek is final AND completely covered;
everything else is deferred with a listed reason and picked up automatically when the gameweek finalises
(the raw cache already holds the fetched matches, so no re-download).

**Pull result (2026-08-31):** 380 fixtures listed, 19 completed on Understat. Written: **310 rows,
10 matches, all gw=1, 0 ambiguous** (kickoff source `fpl_api_2026_27.parquet`). **Deferred, individually
listed: 9 GW2 matches** (ids 31190–31198 — Palace–City through United–Ipswich), because GW2 is not yet
`data_checked`-final in the FPL-API file. Schema vs `understat_matches_2025_26.parquet`: columns, order
and dtypes identical (after the gw int64 cast).

## Part B — the season aggregates

**What the stored file is (established with evidence):** one row per (id, understat_season), 19 columns,
every value a VERBATIM Understat string (KNOWN_ISSUES #2 preserved, e.g. xG '28.795336209237576') —
the `players` block of `getLeagueData/EPL/<year>`, unmodified. Per-match sums reproduce
games/time/goals/assists at 100% and xG/xA only to rounding, and cannot produce the season `position`
labels ('F S'), `team_title` or the full-precision strings — so the builder **pulls the endpoint**
(one request per season) rather than deriving.

**THE REPRODUCTION PROOF (the deliverable):**
- `--reproduce 2024-25`: 562 stored vs 562 fresh rows, matched 562/562, **every one of the 18 compared
  columns 100.00% exact** (verbatim strings).
- `--reproduce 2025-26`: 537 vs 537, matched 537/537, **all columns 100.00% exact**.
The builder reproduces the hand-assembled file byte-for-byte on both proven seasons; the check writes
`understat_aggregates_repro_check.json`, which the suite asserts.

**2026-27 build:** 358 rows as of 19 completed matches → `understat_season_aggregates_2026_27.parquet`
(+ provenance with pulled_at and completed-match count); `--combine` →
`understat_season_aggregates_with_2026_27.parquet` = 5,343 stored rows (untouched) + 358. The columns the
crosswalk uses (id, player_name, team_title) are fully populated. **Finality for aggregates is
provenance, not file membership**: the aggregate is a running as-of snapshot Understat updates after
every analysed match; it is never final until the season ends, and refreshing is an idempotent re-run +
re-combine. (Stated plainly rather than forcing the provisional-file pattern onto a quantity that has no
final state mid-season.)

## Politeness

1.05 s between requests everywhere (unchanged), one league listing per run, raw cache prevents
re-downloads, and a 403/429 aborts immediately with instructions to wait — the fetcher never tightens its
spacing in response to being blocked. The two Understat programs are never run concurrently.

## Append, do not rebuild

Existing parquets untouched. Season files `understat_matches_2026_27.parquet` /
`understat_season_aggregates_2026_27.parquet` with provenance sidecars; combined
`understat_season_aggregates_with_2026_27.parquet` (per-match files are per-season already, so no
combined variant is needed there).

## Tests

`Tests/test_understat_ingest.py` (7): unmapped season raises (both programs); archive-season unmapped
match raises; live-season unmapped/incomplete rows are deferred, never gw=None; per-match schema ==
2025-26 file exactly; aggregates schema == stored file exactly; the reproduction report must say exact.

## What remains (reported, NOT fixed)

**To a 2026-27 crosswalk:** `SEASON_TO_US` (`eval/build_crosswalk.py:60`) stops at 2025-26; the builder
must read the `_with_2026_27` aggregates (or the extended file) and 2026-27 vaastav-shaped rows
(`all_seasons_with_2026_27.parquet` exists); then `build_crosswalk.py --season 2026-27` and its audit.
**To a live GW7 frame, beyond the crosswalk:** pre-deadline odds + 2026-27 fixture rows in
`odds_all_seasons.parquet` (no fetcher; the fixture universe IS that file); the season-boundary constants
(`BLEND_PRIOR`, minutes ladder, ORDER/DC_SEASONS/LABELLED, DC_RULE_SEASONS/defensive.SEASON/cache key —
each a gated change guarded by `live_deadline` strict mode); pointing the consumers at the `_with_*`
files; the steps 1–5 minutes substitution (still a closure in `walkforward_arms.main`); and the DC-term
source question (#21). None touched here.
