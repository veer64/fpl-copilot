# Core-insights ingestion for 2026-27 (2026-08-31)

`eval/fetch_core_insights.py`; `Tests/test_fetch_core_insights.py`. Ingestion only: defensive.py,
DC_SEASONS, DC_RULE_SEASONS and the DC source are untouched (the FPL-API swap is a separate, measured
change). Mirrors the conventions of `eval/fetch_fpl_history.py`: runtime-read schema contract, retries/
backoff/spacing/UA, structured logging, atomic writes, per-GW upsert, provenance sidecars, and the
finality-is-the-file provisional split.

## Path construction — fail loudly, never guess

The repo reorganised across seasons (2024-2025 used `data/<season>/playermatchstats/`; 2025-2026+ uses
`data/<season>/By Gameweek/GW{n}/…`), so every path comes from an explicit per-season `SEASON_LAYOUT`
entry. An unmapped season raises `LayoutError` with instructions to inspect the repo and add the mapping;
a 404 raises after retries; a missing required column raises naming it; a required column that is present
but ENTIRELY NULL raises (see the tackles finding). Nothing falls through to an empty frame.

## THE FINDING: 2026-27 renamed the tackles semantic

The 2026-27 `playermatchstats.csv` carries a `tackles` column that is **100% null** (in the repo's own
2025-26 files it was fully populated), while `tackles_won` is populated. Measured against the FPL API on
GW1: **core `tackles_won` == the API's native `tackles` EXACTLY (1.000 on every played row)**, and
core `clearances + blocks + interceptions` == the API's CBI at 1.000. So what defensive.py means by
`tackles` is published as `tackles_won` this season. Handled as an explicit, evidenced
`column_map: {"tackles": "tackles_won"}` in `SEASON_LAYOUT` with an ambiguity guard: if the source's own
`tackles` ever comes back non-null alongside, the pull raises rather than choosing. Filling the dead
column with zeros would have put cbit agreement with the API at 36% instead of 94% — the silent-fallback
family, refused by construction. (Also handled: 6 playerstats ids absent from players.csv — dropped with
a provenance count after verifying none appears in matchstats; integer-schema NAs are filled 0 with
per-column counts in provenance, matching both the historical parquet's own int64 convention and
defensive.py's `fillna(0)`.)

## Finality

FINAL requires all three: every `matches.csv` row for the gameweek `finished == True`; every match_id
present in `playermatchstats.csv`; and the match count equal to the authoritative FPL `fixtures/?event=`
count. Otherwise `ProvisionalGameweekError`, with `--provisional` writing `*_PROVISIONAL_gw{n}.parquet`
side files (own provenance) that are never merged — identical to the FPL fetcher's split.

## Verification — 2026-27 GW1 (written FINAL)

- **400 matchstats rows over 10/10 matches, 400 players; 610 position rows** (positions Goalkeeper/
  Defender/Midfielder/Forward, none null).
- **Schema vs `core_insights_matchstats.parquet`: columns identical and ordered, zero dtype mismatches.**
  All-null columns in the pull, all parquet-only with no 2026-27 source and none read by defensive.py:
  `corners, successful_dribbles_percent, tackles_won_percent, walking_distance, defensive_contributions`.
- **cbit/cbirt computed exactly as defensive.py** (C+B+I+T, +R), played rows (n=310):
  cbit mean 3.47, p50/p90/p99 = 3/8/15.9, max 21; cbirt mean 6.47, p50/p90/p99 = 6/13/20.8, max 24 —
  same shape as last season's distributions.

## Cross-check vs the FPL API (report only — evidence for the later swap decision, not acted on)

dc_metric (position-dependent cbit/cbirt) vs the API's native `defensive_contribution`, GW1, 310 played
players: **93.55% exact** (historical 2025-26 GW20: 87.25% — similar family, somewhat better). The 20
disagreements are **all one-signed — core counts MORE than FPL, never less** (+4 to +22, mean |diff|
0.62): with tackles and CBI proven identical, the excess sits in recoveries/clearances counting for a
small set of players. Threshold-relevant: 7 players flip the ≥10 line, 4 flip ≥12. The two sources
remain different instruments; the swap stays a measured model change.

## Append, do not rebuild

Existing parquets untouched. Final gameweeks upsert into `core_insights_matchstats_2026_27.parquet` +
`core_insights_gameweek_stats_2026_27.parquet` (provenance `core_insights_2026_27.provenance.json`);
`--combine` writes `core_insights_matchstats_with_2026_27.parquet` (26,593 + 400 rows) and
`core_insights_gameweek_stats_with_2026_27.parquet` (29,978 + 610), schemas asserted. Nothing in
modelling reads the combined files yet.

## What still stands between the DC term and 2026-27 (reported, NOT fixed)

1. `DC_SEASONS = {"2025-26"}` — `eval/walkforward_season.py:62` (gates `dc_enabled`; 2026-27 currently
   zeroes the term).
2. `DC_RULE_SEASONS = {"2025-26"}` — `squad/defensive.py:231` (empty frame for 2026-27).
3. `defensive.SEASON = "2025-2026"` — `squad/defensive.py:24` (hard-filters the feature frame to last
   season even if the sets were widened).
4. `_DC_HITS_CACHE` keyed on the literal `"full"` with no season — `squad/defensive.py:232` (widening the
   sets without season-keying it would serve 2025-26 probabilities for 2026-27 gameweeks).
5. defensive.py must read the `*_with_2026_27` (or extended) parquets rather than the frozen originals.
Each is a gated, stamped change with the live parity harness as its regression net; none was touched here.

## Tests

`Tests/test_fetch_core_insights.py` (suite 184): unmapped season fails loudly; every leg of the finality
rule independently refuses; a missing `finished` column is a LayoutError; the column map applies on a dead
schema column and REFUSES when both are populated or the source column is absent; matchstats schema ==
parquet exactly; gameweek_stats schema + complete position map.
