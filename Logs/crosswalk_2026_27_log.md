# 2026-27 crosswalk (2026-08-31)

`eval/build_crosswalk.py` extended; `data/history/crosswalk_2026_27.csv`;
`Tests/test_crosswalk_2026_27.py`. Ingestion only: no modelling code changed, no season constant beyond
the crosswalk's own map extended, DC untouched (#21 stands).

## What changed in the builder

1. `SEASON_TO_US` widened to `range(2016, 2027)`.
2. New `_sources(season, us_season)`: the frozen archives are preferred verbatim; a season they do not
   contain reads the `*_with_2026_27.parquet` files produced by this session's fetchers, and raises with
   the exact build commands if those are absent. Nothing can silently read an empty season.
3. A `"2026-27"` MANUAL block (below). The guard, the audit and every floor are untouched.

## Build result (sources: `all_seasons_with_2026_27` + `understat_season_aggregates_with_2026_27`)

610 elements vs 358 Understat players → **354 matched** (288 exact, 55 fuzzy, 5 fuzzy+club,
2 club+token, 4 manual), 0 duplicate claims, club map 20/20.

**The audit reported and dropped nothing — because it checked zero pairs**: `AUDIT_MIN_MINUTES = 450`
and no player has 450 minutes after one final gameweek. Stated plainly: the profile audit is
structurally idle until roughly GW5; until then the single-token guard and the manual evidence are the
active defences. It reports rather than crashes (defect (c) of a758541 stays fixed; exercised in tests).

## The single-token names — all 14, disposition and verification

Guard rule: a single-token Understat name is admitted only if the club agrees AND the token names exactly
one Understat player at that club. All 12 admitted names were verified by GW1 minutes on both sources:

| Understat name (id) | club | claimed by | FPL v US GW1 min |
|---|---|---|---|
| Emersonn (14082) | Ipswich | 316 Emersonn Correia da Silva | 65 v 68 |
| Alisson (1257) | Liverpool | 350 Alisson Becker | 90 v 90 |
| Gabriel (5613) | Arsenal | 4 Gabriel dos Santos Magalhães | 90 v 90 |
| Richarlison (6026) | Spurs | 527 | 67 v 69 |
| Reinildo (7432) | Sunderland | 536 | 90 v 90 |
| Murillo (12123) | Nott'm Forest | 472 | 90 v 90 |
| Evanilson (12963) | Bournemouth | 79 | 74 v 77 |
| Thiago (13222) | Brentford | 106 Igor Thiago | 82 v 84 |
| Estêvão (13775) | Chelsea | 157 | 7 v 5 |
| Jair (13779) | Nott'm Forest | 474 | 90 v 90 |
| Kevin (14030) | Fulham | 263 | 17 v 15 |
| **Rayan (14395)** | Bournemouth | **67 Rayan Vitor Simplício Rocha** | 88 v 90 |
| Beto (9983) | Everton | fell through → MANUAL 248 | 11 v 7 |
| Costinha (14854) | Brighton | fell through → MANUAL 119 | 26 v 21 |

**The Cherki trap did not fire**: Cherki (399, Man City) fell through unmatched instead of taking
Bournemouth's "Rayan" — exactly the guard behaviour a758541 built — and is pinned to his own id manually.
A regression test holds both sides of that pair.

## The MANUAL block — four entries, each with evidence

| element | id | evidence |
|---|---|---|
| 399 Rayan Cherki | 8094 "Mathis Cherki" | Man City, 27v25 min GW1; same id as the 2025-26 manual entry; first-name-form mismatch |
| 248 Beto | 9983 | Everton, 11v7 min GW1; same id four seasons running + KNOWN_ISSUES #3 |
| 592 Abdoul Ouattara | 10485 "Guemissongui Ouattara" | Ipswich, 10v8 min GW1; the other Ouattara (Dango, Brentford, 68 min) is correctly claimed by element 95 |
| 119 João Pedro Loureiro da Costa | 14854 "Costinha" | Brighton DEF, 26v21 min GW1; the ONLY unclaimed Brighton player in the GW1 roster; "Costinha" = diminutive of "da Costa" |

No fuzzy floor was lowered.

## COVERAGE — the deliverable

- **Every FPL element with GW1 minutes is mapped: 310 of 310** (306 automatic + the 4 manual above).
  **Elements with real minutes and no id: 0** (last season the answer was two — Cherki and Jimenez — and
  both cost points; this season it is zero at build time, held by a test).
- 256 elements lack an id — **all with 0 minutes**: unplayed squad filler and new signings Understat has
  never listed. pct_minutes_covered **99.6%** before the manual block, **100.0% of played minutes** after.
- 48 of 358 Understat aggregate listings have no GW1 appearance (carryover/games=0 rows) — normal.

## THE SEPTEMBER PROBLEM — stated plainly

Understat only lists a player once he has PLAYED, and only GW1 is final on both sides. Consequences:
1. Today, zero playing elements lack an id — but that is a statement about GW1 only. Summer signings who
   debut in GW2+ (and every promoted-club squad player yet to appear) will enter Understat's data later,
   and the guard's uniqueness premise is evaluated against the *current* club roster — e.g. "Gabriel" is
   admitted now because Magalhães is the only Arsenal Gabriel Understat has listed in 2026-27 so far; if
   Martinelli or Jesus appears later, the automatic pass would (rightly) start refusing the token, and
   the pinning must move to MANUAL then.
2. **The crosswalk therefore needs REBUILDING after every finalised gameweek**, in the weekly ingest
   sequence: fetch_fpl_history → understat_matches → build_understat_aggregates (+ combines) →
   build_crosswalk. It is idempotent and takes seconds; the tests re-verify the manual block and the
   single-token holds on every run. An element that is unmatched this week and matched next week is the
   system working; a *changed* id week-to-week is an alarm (the duplicate sweep and the held-pairs test
   are the tripwires).
3. Until a player appears in Understat, his element correctly carries no id and takes the positional
   prior — `live_deadline` postflight counts these and raises under strict only when one reaches the
   top 30.

## Promoted clubs

Coventry City → "Coventry", Hull City → "Hull", Ipswich Town → "Ipswich" (relegated out: Burnley,
West Ham, Wolves). All resolved by the existing exact/alias logic — `_team_map` 20/20, held by a test.
`assembly.TEAM_MAP` (the #14 Sheffield-class fixture guard) concerns the ODDS file's club names, not
Understat's; it is untouched here and flagged again under "what remains".

## Tests

`Tests/test_crosswalk_2026_27.py` (7, suite 198): manual entries resolve to their stated ids; no
duplicate claims; all 20 clubs incl. promoted resolve; the twelve verified single-token holds; Cherki≠Rayan
both ways; audit reported (0 checked, 0 dropped — not a crash); every playing element mapped.

## What remains before a live GW7 frame (reported, NOT fixed)

1. **Odds/fixtures**: pre-deadline odds + 2026-27 rows in `odds_all_seasons.parquet` (the fixture
   universe), plus `assembly.TEAM_MAP` entries for the promoted clubs in the odds source's naming — the
   actual #14-class risk, untouched.
2. **Season constants**: `BLEND_PRIOR` (+ per-match blend file naming is already satisfied), the minutes
   ladder, `ORDER`/`DC_SEASONS`/`LABELLED`, `DC_RULE_SEASONS`/`defensive.SEASON`/the season-less DC cache
   — each a gated change; `live_deadline` strict mode raises on all of them today.
3. **Consumers still read the frozen files**: `crosswalk_for` finds `crosswalk_2026_27.csv` by name
   (done), but minutes/bonus/pen-rate read `all_seasons_fixed.parquet` and rates read
   `understat_matches_{tag}.parquet` (naming already per-season ✓) — the vaastav-shaped consumers need
   pointing at `all_seasons_with_2026_27.parquet`.
4. **Steps 1–5 minutes substitution** (combined arm) still lives inside `walkforward_arms.main`.
5. **Weekly operations**: the rebuild-after-each-gameweek sequence above, plus the DC source question
   (#21) before the DC term can run at all.
