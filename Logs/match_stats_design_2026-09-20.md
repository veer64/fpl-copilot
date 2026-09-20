# `get_match_stats` — one stat, one source; grain stated; the fourth caller of the rule (2026-09-20)

One new agent tool, the nineteenth: rich factual team stats — head-to-head, form windows,
home/away splits, for and against — from what is already on the volume. No model, no
prediction, no new source, no scraping. **Not deployed.**

Companions: `Logs/league_table_design_2026-09-19.md` (the pattern: §1 cutoff rule, §4.1
attribution from provenance, §5 designed refusals), `data/fbref/provenance.json` and the
per-season sidecars, `squad/team_map.py` (three named maps now: `TEAM_MAP`,
`FBREF_TEAM_MAP`, `UNDERSTAT_TEAM_MAP`).

---

## 1. One stat, one source — the registry

`match_stats.REGISTRY` is the only place a number's origin is decided. Each stat maps to
exactly one source, one grain and one column pair; a test asserts no stat has two sources and
no fallback exists. Shots live in three places on the volume and the three disagree
(different providers, different definitions); a stat whose own source lacks a season is a
**stated gap**, never filled from a neighbour.

| stat | sole source | grain |
|---|---|---|
| goals, results, head-to-head | odds archive (scores; FPL's for the live season) | per match |
| shots, shots_on_target, corners, fouls, yellow_cards, red_cards | odds archive (E0; the live season via the E0 fill) | per match |
| xg, npxg | Understat, per-player rows summed to the team per match | per match |
| possession | FBref standard table | season aggregate |
| crosses, interceptions, tackles_won, offsides, fouled, pens_won, pens_conceded | FBref misc table (`_for` and `_against`) | season aggregate |
| big_chances, woodwork, passing, aerials | **none** — refused by name, never approximated | — |

The agent passes stat **names**; there is no query parameter and the tool's source contains
no SQL. An unknown name is an error listing the valid ones.

## 2. Grain is part of the number

Every returned stat carries `grain` and its **measured** season coverage. Per-match stats
aggregate over admitted matches only and carry `matches_counted` per stat — Arsenal's 2026-27
goals count every played match while shots count only the E0-filled ones, and the two counts
travel separately. A season aggregate asked for a window, a venue or an opponent gets a
`window_refusal` / `venue_refusal` / `opponent_refusal` by name and the season figure beside
it, labelled; the figure is never presented as the window's.

**The current season's aggregate includes matches after the cutoff, and says so.** The FBref
save time is read from the season sidecar; fixtures dated after the cutoff day and on or
before the save day are counted with the same rule applied twice (goals forced present), and
the figure carries `includes_post_cutoff` with that count. Live, 2026-09-20: Liverpool's
possession comes back with `includes_post_cutoff: true, matches_after_cutoff_in_aggregate: 10`
— the ten GW5 fixtures between the GW5 cutoff and the save. Chosen over refusing the figure
under an explicit `as_of`, and applied identically whether the cutoff is defaulted or given.

## 3. The as-of rule, once

Per-match rows pass through `dixon_coles.knowable_before` exactly once, in
`model_tools.get_match_stats` (the fourth caller; the docstring in `dixon_coles.py` was
updated to three by the league-table work and this log records the fourth). Understat needs
no separate pass: its team-match xG is joined onto the archive's match rows on (day, home,
away) before the rule runs, so one filter admits both. `match_stats.py` contains no date
comparison, asserted by a source grep; the swap-in-the-old-leaky-rule test moves the output.

The cutoff derivation is now shared: `_run_cutoff(run, cal, as_of)` serves both
`get_league_table` and `get_match_stats`, so the two can never disagree.

## 4. Names — three named maps, one module, checked per season

Every source's club names go through `team_map.py` — `TEAM_MAP` for the archive,
`FBREF_TEAM_MAP` (already applied at export), `UNDERSTAT_TEAM_MAP` (new, measured from the
five files' 27 spellings) — then the fit's own `ARCHIVE_NAME_ALIAS` where a season's FPL
spelling is the archive's, and the result is checked against the club set **measured from the
stack** for that season. Any residue is an error naming the source, season and names; nothing
is joined.

**Found on real data, not in the synthetic tests:** the first live run refused every
2024-25 question — Understat "Ipswich" → map "Ipswich Town" → the 2024-25 stack says
"Ipswich". The alias fallback the map's comment promised had not been wired into the tool. It
is now, with a test that reproduces the case.

## 5. Attribution from provenance, never from the file

The FBref block of every answer is read at call time from `data/fbref/provenance.json` and
the season sidecars: source ("MANUAL browser saves by the human"), the coverage statement
(starts at 2016-17 because names cannot be verified earlier), `seasons_on_disk`, the
season statement ("SEASON AGGREGATES, NOT PER-MATCH. xG is UNAVAILABLE…"), and each season's
save time. A test flips the sidecar and asserts the answer flips; the tool's source contains
none of those strings.

## 6. Designed refusals, all with a stated reason

- stat outside its measured range → `coverage_note` naming covered and uncovered seasons,
  `matches_counted 0`, totals null. Corners for 2026-27 are **covered** on the laptop because
  the E0 fill landed (30 matches) — read from the archive, as the spec anticipated, not assumed.
- possession / crosses… with a window, venue or opponent → grain refusal by name.
- big_chances, woodwork, passing, aerials → "held nowhere", no value key at all.
- unknown club → error naming the known clubs; "spurs", "tottenham", "man united" resolve.
- zero meetings → a stated zero with a sentence, not an empty list alone.
- partial window → `requested`, `matches_in_scope`, `matches_counted`, `complete: false`.
- pens_won / pens_conceded → null with "empty in FBref's export … null, not zero".
- unmapped name in any source → the join is refused.

## 7. Measured, end to end through `agent.call_tool`

Laptop, no Postgres (run row stubbed), real files, best of three:

| call | ms |
|---|---|
| cold first call (scipy import inside) | 1,826–1,924 |
| Liverpool possession, current season | 536–543 |
| Liverpool v Everton, last 5 meetings over 6 seasons, goals+shots+xG both sides | 565–606 |
| Arsenal shots at home, current season | 535–537 |
| Hull corners + possession + crosses, 2 seasons, last 5 | 551–555 |
| core set, Man City, 3 seasons, both sides | 520–568 |
| explicit `as_of` | 518–527 |
| unknown stat (validation only) | 0.0 |

Payloads 3.5k–7.5k characters. Warm calls are about 2.5× the league table's because every
call re-reads the archive (twice: the fit's loader plus the stat columns), all five Understat
files, the FBref CSVs and the stack's club sets; nothing is cached. Whether to cache is a
separate decision.

Hand-checked live: Liverpool v Everton last five (2026-04-19 A 2-1 W, 2025-09-20 H 2-1 W,
2025-04-02 H 1-0 W, 2025-02-12 A 2-2 D, 2024-04-24 A 0-2 L), record 3-1-1, goals 7-6, shots
71-50, xG 6.585-5.875, Understat unjoined 0. Man City over three seasons: 79 matches counted.

## 8. The tool-budget argument, and the open item that does not close here

Surface 18 → **19**. The argument, not the use case: this displaces a refusal the grounding
contract forces on questions users ask ("how much possession has Liverpool had", "the last
five Liverpool–Everton meetings"), over data already on the volume, through one registry and
the one as-of rule, and nothing else on the surface can answer a stats question. **Tool-
selection accuracy remains unmeasured at any surface size**; the instrument is still the
open item it was, and adding the nineteenth tool does not close it.

## 9. Files

New: `match_stats.py` (pure), `Tests/test_match_stats.py` (28 tests). Changed:
`model_tools.py` (`_run_cutoff` factored out of `get_league_table`; `_ms_archive`,
`_ms_understat`, `_ms_fbref`, `_ms_club_sets`, `get_match_stats`), `agent.py` (schema +
dispatch, 19), `prompts/system_prompt.md` (§2d new, §6 in-scope line; betting wording
untouched), `squad/team_map.py` (`UNDERSTAT_TEAM_MAP`). Nothing deployed.
