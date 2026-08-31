# Fixture universe + live availability integration — 2026-08-31

Task: two integrations for live 2026-27. Part A: the fixture universe from the FPL
fixtures/ endpoint in the odds-archive schema, prices null (pure-DC fallback, counted).
Part B: the live availability files merged into the `data/` glob the model reads.
DC untouched (#21 stands). No live odds pulling (separate job).

## Parity (the gate)

Re-run after ALL changes, both configs, three cutoffs (GW5 / GW20 / GW33-DGW, 2025-26):
**BIT-IDENTICAL in all six cells** (max |Δ| exactly 0.0, NaN placement equal).
`PARITY: PASS` twice. Preserved by construction: `dixon_coles._load_matches(predict_season)`
reads the untouched archive verbatim for any season the archive contains, and
`odds_all_seasons_with_{tag}.parquet` only for seasons it does not (2026-27+);
`test_historical_seasons_still_read_the_frozen_archive` asserts frame equality.

## Part A — fixture universe (`eval/fetch_fixtures.py`, commit 4357a87 + dbf818a)

- 380 fixtures → `data/history/odds_fixtures_2026_27.parquet`; `--combine` →
  `odds_all_seasons_with_2026_27.parquet` (3800 archive rows byte-identical + 380).
- Club names, #14 class: E0 spelling reused iff it round-trips through
  `assembly.TEAM_MAP` to the FPL name — reused: **Man United, Tottenham**. Everything
  else takes the FPL name verbatim (TEAM_MAP passes unknowns through; the 2026-27 stack
  carries FPL names, so the (team, match_date) join is exact). Ambiguity raises
  (`ClubNameError`, tested). Documented: E0 "Ipswich" strength stranded; Coventry City /
  Hull City have no archive rows — all three promoted clubs start from zero-information
  DC priors.
- Pure-DC confirmed end-to-end: `get_fixtures("2026-27")` returns 380 rows, ALL
  `lambda_source == "dc"`, `odds_used` all False, lambdas and clean-sheet probs real
  (test). Per-fixture unpriced counts remain the designed, counted fallback.
- Scores: 20 finished with scores at pull time. The past-kickoff-unscored guard fired
  **twice on real states** before the clean pull (10 GW2 fixtures pre-`finished` flag;
  then Villa–Arsenal literally in play) — behaving exactly as designed. Two findings
  folded in: `finished` lags `finished_provisional` until FPL's post-match processing,
  so provisional scores are accepted and counted in provenance (`provisional_scored`);
  and every archive int64 column (not just the four score columns) is all-NA in the
  slice, so the documented lossless float64 cast covers them all, slice and combined.

## Part B — live availability (`eval/merge_live_availability.py`, commit 0b39f12)

- `data/availability_2627.parquet`: 23,611 rows = 1,219 poller-authoritative +
  22,392 fplcache-only. Exact historical schema (read at runtime), season "2026-27"
  in every key, asof_* discipline untouched.
- Authority per (season, element, gw): **poller wins**, fplcache fills. 1,215
  overlapping keys; disagreements counted into provenance, never silently resolved:
  `asof_status` 12, `asof_chance_of_playing_this_round` 3, `asof_news` 16.
- Derived state, regenerated per run; the live archives under `data/live/` are never
  modified. Uniqueness asserted at write AND by `attach()`'s row-count guard.
- First write went to `availability_26.parquet` via a tag-slicing bug — **removed**
  (minutes old, my own artefact), fixed with an assert on the tag. Notably parity was
  bit-identical even with that file in the glob (2026-27 rows cannot touch a 2025-26
  build), but the correct name is what the convention and tests pin.
- `attach()` on 2026-27 keys now returns real values: UNKNOWN fraction < 5%
  (was 100% — the whole block silently UNKNOWN — before this task).

## Strict preflight after both integrations (2026-27, GW1)

Down from four findings to **three**:
1. `DC_SEASONS` hold — #21, deliberate, closes via pre-registration.
2. `DC_RULE_SEASONS` hold — same.
3. **odds PRICES missing for ALL GW1 fixtures** — NEW strict finding added this task:
   the fixture half of the old odds finding is closed, but a fully unpriced deadline
   gameweek (every lambda pure DC) is a live quality regression vs every backtest
   (100% priced) and raises until live odds pulling lands. Honest note: the user
   expected "the odds PRICES to still raise" — per-fixture gaps do NOT raise (designed,
   counted fallback); only the all-unpriced-gameweek case does, which is exactly the
   state 2026-27 is in today. The check derives the GW window from the FPL-API
   master's kickoff times, so it can only assess gameweeks the master covers.

Availability no longer appears. `odds_all_seasons has NO rows` no longer appears.
Ledger test (`test_nonstrict_preflight_reports_instead_of_raising`) updated in both
directions, prices needle pinned at GW1.

## What remains (unchanged standing items)

- DC pre-registration (#21) — the named next gated change.
- Live odds provider — separate job; until then every 2026-27 deadline runs pure DC
  and strict preflight says so.
- Weekly ops order now: fetch_fpl_history → understat_matches → aggregates →
  crosswalk → **fetch_fixtures (+ --combine)** → **merge_live_availability**.
