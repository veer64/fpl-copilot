# `get_league_table` — design, measurements and the corrections it forced (2026-09-19)

One new agent tool: the league table and each club's form **as of a cutoff**, derived entirely
from match results already on the volume. No new upstream, no new credential. Built the same
day the spec arrived; **not deployed** — this log records what exists, what was measured and
what the spec got wrong, so the deploy decision can be made on the record rather than the
prompt.

Companion: `FEATURE_IDEAS.md` item 1 of "league table and team form as a tool" (HEAD copy —
see §9), `Logs/fixtures_and_prices_design_2026-09-19.md` §1 (data locations),
`Handoffs/Handoff_2026-09-19_session.md` §6 and §8 (the verification rules applied here).

---

## 1. The one rule, and where it is applied

**Every match the table counts passed `dixon_coles.knowable_before(matches, cutoff)`.** That
function is the single definition of the as-of boundary for match results: a result counts
only if the match finished before the cutoff DAY began. It already had two callers — the
fit's training filter and the as-of guard's truncation — and KNOWN_ISSUES #25 is the record of
what happened when two independently written copies of that comparison drifted (one leaked,
one fitted a degenerate model). This tool is the third caller and is wired to the same
function. Its docstring now says three.

Where it is applied, and only there: `model_tools.get_league_table` (the IO layer). The pure
module `league_table.py` receives rows the rule has already admitted and **contains no date
comparison of any kind** — a test greps both sources for every spelling of a row-level date
filter and for `.normalize()` in the pure module.

**The excluded fixtures are named with the same function, not a second one.** A fixture dated
before the cutoff day that carries no result (postponed and still on its original date, or
played but not yet ingested) must neither count nor vanish. It is found as
`knowable_before(matches with goals forced present) & ~knowable_before(matches)` — the rule's
date clause alone, minus the rule. No new comparison was written for it.

**The season is chosen the same way.** "The latest season with a fixture dated on or before
the cutoff day" is the rule asked one day later, with goals forced present. So a historical
`as_of` returns that season's table (2024-25 as of 2025-03-01: Liverpool 67 from 28), and a
`season_note` fires when the season differs from the run's.

The test that matters most monkeypatches `dixon_coles.knowable_before` to the OLD timed
comparison (the one that leaked) and asserts the tool's output **moves** — the cutoff-day match
appears, two clubs' `played` go from 2 to 3. If a second copy of the rule ever lands in the
tool, that test stops moving and fails. The cutoff is exercised at three gameweeks plus the
two boundary seconds (23:59:59 on the match day excludes it; 00:00:01 the next day includes it).

## 2. The cutoff, and why it is derived rather than read

`as_of=None` means "what the latest run knew". The run row records `frame_cutoff_gw` but **no
cutoff timestamp** (`knowledge_block` in `eval/run_live_deadline.py`). The walk-forward
derives it inline: `gw_start = v.groupby("GW")["kick"].min()`, then `.tz_localize(None)`
(`eval/walkforward_season.py:119,137`). The tool derives it the same way from the same source
(`season_stack.load_stack`, the stack plus forward skeleton), and a test computes both
expressions on the real 2026-27 calendar and asserts them equal for every gameweek. A given
`as_of` is read as UTC; a tz-aware one is converted and stripped, as the walk-forward's is.

## 3. Where the data actually lives (measured on the laptop; the server's copy is newer)

| Thing | Where | Read cost |
|---|---|---|
| Scores and prices | `data/history/odds_all_seasons_with_2026_27.parquet` via `dixon_coles._load_matches` — the FIT's own loader: same file resolution, same nine columns, same `format="mixed", dayfirst=True` date parser. Not a second reader. | ~95 ms (it reads all 181 columns; changing that is a model-path change and was not made) |
| Gameweek labels and the cutoff | `season_stack.load_stack` (stack GW1–3 locally, GW1–4 on the server; forward skeleton GW4/5–38), six columns | ~80 ms |
| Price provenance | `data/history/odds_live_pull_2026_27.provenance.json` | negligible |

**Gameweeks are labelled by pairing the two sides of each fixture id**, never by a date window
and never by matching anything numeric. The stack carries every fixture twice, once per club,
with `team`, `was_home` and `fixture`; joining the home side to the away side on the id names
both clubs with no opponent-id resolution (which would need the bootstrap and would be wrong
for historical seasons, LEAKAGE.md item 2). Measured: **0 unmapped** on 2026-27 and **0
unmapped** on 2024-25 as of March. The labels only label — the table's arithmetic never
depends on them, and a test removes the calendar entirely and shows every match still counted
with every `gw` null and the count stated.

**The name bridge.** The archive spells three clubs the football-data way (`Man United`,
`Tottenham`, `Sheffield United`). The bridge is `TEAM_MAP`, which lived in `squad/assembly.py`
— and `assembly` imports `minutes`, `bonus`, `dixon_coles`, `defensive`, `attacking_rates`:
**sklearn, lightgbm and scipy, 1.8 s, the model in memory.** A read-side tool cannot import
that. Two copies already exist in `eval/` (`build_market_lambda_dataset.ALIAS`, and
`ev_surface.TEAM_MAP`, which is **stale — it lacks Sheffield United**, the exact #14 defect).
A fourth copy was refused. Instead the literal moved to **`squad/team_map.py`** (pure) and
`assembly.py` imports it from there: a one-line relocation, the dict pinned identical by a
test (`assembly.TEAM_MAP is team_map.TEAM_MAP`). **This is a model-path file touched.** The
diff is the import line and a comment; no behaviour can change; the full suite, which includes
the tests that import `assembly`, is the gate that ran. It is separable into its own commit
and is flagged for veto in the handoff.

## 4. What the spec got wrong, measured

### 4.1 "This is Bet365's pre-match pricing" — not for the live season

The spec's attribution rule: *"this is Bet365's pre-match pricing, never ours."* Measured
before labelling anything:

| season | rows priced | overround min / mean / max |
|---|---|---|
| 2016-17 … 2025-26 (football-data) | 380 each | 1.017 – 1.075, mean ≈ 1.03–1.055 |
| **2026-27** (the live pull) | 30 | **0.99997 / 1.00000 / 1.00002** |

The 2026-27 rows of the B365-named columns carry an overround of exactly one because they are
not bookmaker prices. `odds_live_pull_2026_27.provenance.json`:

> `construction`: "de-margined median consensus, fixed 12-book panel, min 5"
> `panel`: betfair_ex_uk, betway, boylesports, casumo, grosvenor, leovegas, livescorebet,
> skybet, sport888, unibet_uk, virginbet, williamhill
> `source_note`: **"NOT Bet365, NOT closing -- pre-deadline snapshot"**

Bet365 is not in the panel. Labelling the live season's number "Bet365's" would have been a
false attribution — the laundering error in reverse, and on exactly the season a user asks
about. **So the label is read from the sidecar, never assumed from the column name:**
`league_table.odds_attribution(provenance)` returns `source_kind: "bet365"` for an archive
season and `source_kind: "consensus"` with the construction, panel size, source note and pull
time for a live one. The numbers do not change — only who is credited. A test flips the
provenance and asserts the label flips and the values do not. The prompt (§2c) and the schema
description say "the market's", name both cases, and tell the agent to use the tool's words.

The reported overround is what made this visible. The spec asked for it "so the normalisation
is visible, not hidden"; it was, and it showed the normalisation was a no-op on the live
season, which is how the question "why?" got asked. Keep reporting it.

### 4.2 `xpts_diff = points − odds_xpts` would be the partial-sum masquerade the spec forbids

On the live data **20 of the 30 played matches carry no price at all** (GW1–2 predate the
odds pull; only GW3's were captured). The spec says exclude those from `odds_xpts` and return
`xpts_matches_counted` "so a partial sum can never be mistaken for a full one" — and, in the
same section, defines `xpts_diff` as points over ALL matches minus that partial sum. Those two
instructions conflict on this data. The tool computes `xpts_diff` over the **counted matches
only** and reports `xpts_points_basis` (the points in those matches) alongside, with a note
saying so. When every match is priced the two definitions coincide (2024-25: 28 of 28).

### 4.3 Three pointers in the spec were stale

- `Logs/fixtures_and_prices_design_2026-09-19.md` **§6** is the tool-budget item; the data
  locations are **§1**.
- "LEAKAGE.md item 7" is the D1 saves horizon leak; the cutoff-boundary record is
  **KNOWN_ISSUES #25**, which cites item 7 as the trigger that found it.
- "Baseline on main is 424 passed / 1 skipped" — the baseline measured before any change was
  **596 passed, 1 skipped in 10m30s** (the handoff's figure). The merge tripwire is therefore
  596 → 596 + 36.

## 5. Designed refusals

- **A club with no admitted match** returns a null row with `no_matches: true` and a `reason`,
  position `null`, listed after the ranked clubs. Never 0-0-0. Every club of the season is
  listed, from the season's fixture list, so at GW1's cutoff the table is 20 null rows.
- **`as_of` before the archive's first match** returns `status: before_first_match` with the
  date, an empty table and no `error` (it is an answer, not a failure).
- **`as_of` after the latest ingested result** returns `status: after_latest_result` with both
  dates in the statement and the list of fixtures dated before the cutoff day with no result.
  Live: as of 2026-09-19 12:00Z the laptop's archive lists **11 GW4 fixtures** as missing and
  says the table is INCOMPLETE, not merely older. If nothing is scheduled in the gap the
  statement says the table is complete as of the cutoff.
- **Doubles** are a list per (club, gameweek) with `double_gameweek: true`; the calendar
  pairing keeps both legs. `drop_duplicates(["team","gw"])` appears nowhere.
- **An unknown club** is an error naming the known clubs; resolution reuses `_resolve_team`
  and its aliases, so "tottenham", "spurs" and "man united" all resolve.
- **A missing archive file** is an error saying "missing FILE, not an empty season".

## 6. Measured runtime — end to end through `agent.call_tool`, not summed

The laptop has no Postgres, so `_latest_run` / `_run_meta` were stubbed to a real-shaped row
(one ~1 ms round trip and the dispatch-state read are what the stub skips). Everything else is
the production path on the real files. Two runs, best of three each:

| call | run A | run B |
|---|---|---|
| **cold** first call (scipy imported inside the call) | 1,500 ms | 1,193 ms |
| warm, full table, default cutoff | 253 ms | 192 ms |
| warm, one club | 273 ms | 195 ms |
| warm, explicit `as_of` (GW2 / GW3 / now) | 244–258 ms | 157–193 ms |
| warm, historical season (second calendar read) | 384 ms | 242 ms |
| warm, `include_odds_xpts=False` | 243 ms | 161 ms |

Payload: ~20.8k characters for the full table with odds, ~13.3k without, ~4.4k for one club.
The cold cost is `import dixon_coles` (scipy); mlflow stays out. Once per process.

## 7. What was verified, and how

- 36 tests in `Tests/test_league_table.py`, driving `model_tools.get_league_table` and
  `agent.call_tool("get_league_table", …)` with the IO helpers monkeypatched.
- The rule-swap test (§1); no-second-comparison source assertions; three cutoffs; the
  walk-forward derivation equality on the real calendar; hand-built points/GD; home + away
  splits summing to the table on every counter; overround-normalised probabilities summing to
  one and a corrupt price refused; a club missing one price counting fewer than played; a
  double returning both; the null row; both `as_of` refusals; the postponement listed not
  counted; the season following `as_of`; team resolution; a missing archive as an error; the
  tool reading no prediction table (rule 2 is moot by construction — asserted so it stays
  so); the pure module importing nothing of the stack; the lazy import and the fit's loader;
  `TEAM_MAP` with one home; the docstring counting three callers; the prompt in scope with the
  betting line intact and the word "combined" absent; the attribution following the provenance.
- Real-data runs (§6): GW2 cutoff 10 matches, GW3 20, GW4 30; Man City above Arsenal on goals
  for at level points and goal difference; Hull third with three clean sheets, 1 of 3 matches
  priced; 2024-25 as of March 0 unmapped.
- Full suite after every edit: **632 passed, 1 skipped in 9m24s** — the 596 baseline plus
  the 36 new tests, nothing else moved.

**Not verified:** the path on the server. The verification rule this spec carries — call
`get_league_table` itself after the deploy — has not run because there was no deploy. The
laptop's archive is the 2026-09-11 copy (GW1–3 results); the server's has GW4.

## 8. The tool-budget argument (the handoff said the next tool needs one)

Registered surface goes **17 → 18** (19 counting `search_news`). The argument, not the use
case: this tool displaces a **refusal the grounding contract forces** on a question users
demonstrably ask ("how is Hull doing?", 2026-09-17), over a source the volume already holds,
through the one filter the model already trusts. It reads no prediction, refits nothing, and
answers in ~200 ms. Nothing else on the surface can answer it, and answering it from general
knowledge is forbidden. The instrument (tool-selection accuracy at 10/15/18) is still not
built; that remains the open item it was.

## 9. Two things found in the working tree, not touched

- **`FEATURE_IDEAS.md` had an uncommitted deletion** of its last ~112 lines — the whole
  league-table entry this spec points at, and the tool-budget item — replaced by a single
  space. The handoff's git status did not list it. It looks accidental. Left exactly as found;
  the entry was read from `HEAD`. Do not stage it.
- `Handoffs/Quantiles Handoff.docx` is untracked, as the handoff already noted.

## 10. Files

New: `league_table.py` (pure), `squad/team_map.py` (pure), `Tests/test_league_table.py`
(35 tests), `Tests/test_team_map.py` (the pinning test, in its own file so the relocation
commit stands alone).
Changed: `model_tools.py` (`_league_matches`, `_league_calendar`, `_odds_provenance`,
`get_league_table`), `agent.py` (schema + dispatch, 18 tools), `prompts/system_prompt.md`
(§2c new, §6 in-scope line), `squad/assembly.py` (import `TEAM_MAP` from `team_map`),
`squad/dixon_coles.py` (docstring: three callers — no code).
