# KNOWN_ISSUES.md — Confirmed Data Bugs and Their Fixes

Same spirit as LEAKAGE.md: a standing, permanent log — but for data bugs that were found,
verified, and fixed, rather than leakage risks. Keeping this separate from LEAKAGE.md since
these are correctness/labeling issues, not lookahead-into-the-future issues.

---

## 1. `team` column in `core_insights_gameweek_stats.parquet` reflects current club, not
   point-in-time club — CONFIRMED AND FIXED

**Status:** Fixed. Corrected file available. Original file untouched (raw-first discipline).

### What was wrong

The `team` column in `data/history/core_insights_gameweek_stats.parquet` shows each
player's **current/latest** club, backfilled identically across every gameweek row for
that player — not the club they actually played for **at the time** of that specific
gameweek. Any player who transferred mid-season has this column showing their new club
even for gameweeks before the transfer happened.

### How it was found and verified

1. First noticed by spot-checking bonus/BPS logic on two players (Marc Guéhi, Antoine
   Semenyo) who both transferred to Man City in January 2026 — both showed `team = "Man
   City"` even on GW5 (August 2025), well before either transfer. Confirmed both transfer
   dates via web search (Guéhi: Crystal Palace → Man City, ~Jan 2026; Semenyo: Bournemouth
   → Man City, Jan 9 2026 — both independently verified).
2. Full scope was then quantified by comparing, for every (player, gameweek) in 2025-26,
   `core_insights_gameweek_stats.parquet`'s `team` against `all_seasons.parquet` (vaastav)'s
   `team` for the same player+gameweek — joined via `player_id_crosswalk_final.csv`, NOT
   by raw name matching (names don't always match exactly across sources).
3. **Confirmed scope: 27 unique players, 321 affected rows** out of 29,978 total (~1.1%).
   Spans TWO separate transfer windows, not just January — also includes players who
   transferred right around the August/September 2025 deadline (e.g. Eberechi Eze, Crystal
   Palace → Arsenal, completed 23 Aug 2025 — verified the season had already started by then,
   so his early-gameweek Crystal Palace rows in vaastav are correct, and Core-Insights'
   "Arsenal" label on those same early rows is the bug).
4. Verified the underlying performance stats (`minutes`, `goals_conceded`, `clean_sheets`,
   `bps`) are NOT corrupted — this is a labeling bug on one column only, not a data-integrity
   problem across the file. Cross-checked against vaastav (immune to this bug, since it's
   static historical data) and found exact agreement on all performance numbers.

### The fix

**New file:** `data/history/core_insights_gameweek_stats_fixed.parquet`

- Adds `team_corrected` — the point-in-time-correct team, sourced from vaastav via the
  player-ID crosswalk, joined on `(element, GW)`.
- Adds `team_is_corrected` (boolean) — `True` for the 29,338 rows we could verify/correct
  against vaastav; `False` for the 640 rows with no crosswalk match (these keep the
  original, possibly-stale `team` value as a fallback — better than null, but flagged so
  it's not silently trusted).
- Original `team` column is preserved untouched, so the bug is auditable and nothing is
  silently overwritten.
- Row count is unchanged from the original file: 29,978 in, 29,978 out.

### A build gotcha hit while fixing this (worth knowing if this file is ever rebuilt)

The first version of the fix script **inflated row count to 30,397** (419 extra rows).
Root cause: `all_seasons.parquet` (vaastav) has 419 rows where the same player has TWO
rows for the same `(element, GW)` pair — this is real and expected, not a bug: it's FPL's
**double-gameweek** phenomenon (a team plays two matches in the same numbered gameweek,
e.g. due to a rescheduled fixture — confirmed via GW26, where Arsenal players had two
rows with different `fixture`/`opponent_team` values but identical `team`). Joining
against vaastav without deduplicating first caused each double-gameweek player to match
twice. Fix: deduplicate vaastav's lookup table on `(element, GW)` via `.drop_duplicates()`
BEFORE the join — safe to do because `team` is always identical across a player's
double-gameweek rows (verified this holds for all 15 affected players who are also in the
27-player mismatch list, via direct inspection — no case had conflicting team values
within a duplicate pair).

**Minor discrepancy note:** the original scope-quantification (§ above) reported 322
mismatched rows; after the fix, only 321 rows show as changed. Root cause identified and
confirmed: the ORIGINAL quantification script had the same un-deduplicated-vaastav issue,
which caused exactly one real mismatch (Ben Gannon-Doak, GW1, Liverpool→Bournemouth) to be
counted twice. The true count was always 321 — fully explained, not a second undiscovered
bug.

### Practical rule going forward

**Never use `core_insights_gameweek_stats.parquet`'s own `team` column for anything
point-in-time-sensitive** (fixture difficulty joins, opponent strength, historical
team-level features). Use `core_insights_gameweek_stats_fixed.parquet`'s `team_corrected`
column instead, and check `team_is_corrected` if you need to know whether a given row's
value is verified or a fallback.

### Files involved

- `data/history/core_insights_gameweek_stats.parquet` — original, untouched, still has the bug
- `data/history/core_insights_gameweek_stats_fixed.parquet` — corrected version, use this one
- `data/history/team_label_bug_mismatches.csv` — full list of the 322 raw mismatch rows found
  during scope quantification (contains the 1-row double-count described above; the fixed
  Parquet file itself is the authoritative correction, not this CSV)

---

## 2. Numeric columns stored as strings in `understat_season_aggregates.parquet` —
   CONFIRMED AND FIXED

**Status:** Fixed at load-time via `pd.to_numeric`. Original file untouched (raw-first
discipline). Found by the data-exploration chat, logged here for the record.

### What was wrong

All 14 numeric-looking columns in `data/history/understat_season_aggregates.parquet` are
stored as strings, not numbers — including `games`, `time`, `goals`, `xG`, `assists`, `xA`,
`shots`, `key_passes`, `yellow_cards`, `red_cards`, `npg`, `npxG`, `xGChain`, `xGBuildup`.

This is silent and dangerous: no error is thrown when running `.sum()`, `.mean()`, or a
numeric filter on these columns — pandas just does string concatenation instead of
addition, or lexicographic instead of numeric comparison, and hands back a wrong answer
that looks plausible enough to miss at a glance.

### How it was found and verified

1. Spotted while inspecting `dtypes` on first load — every column showed `str`, including
   ones that are obviously numeric by name and by the values printed (e.g. `xG` showing
   `"15.253082547336817"`).
2. Confirmed with a live demo of the bug: summing the first 5 rows of `goals` as-is
   returned `2925242020` — the literal string concatenation of `"29"+"25"+"24"+"20"+"20"`,
   not the real sum (118).
3. Before fixing, checked all 14 numeric-looking columns for any non-numeric junk (empty
   strings, `None`-as-text, stray characters) that could break a blind cast. Zero
   non-numeric values found in any of the 14 columns — safe, mechanical fix.
4. Applied `pd.to_numeric()` to all 14 columns. Confirmed fix: `goals` now sums to 10,400
   across the full file (10 seasons × ~500 attacking players), a plausible total, versus
   the nonsensical 10-digit string-concatenation result beforehand.

### The fix

```python
numeric_cols = ["games", "time", "goals", "xG", "assists", "xA", "shots", "key_passes",
                 "yellow_cards", "red_cards", "npg", "npxG", "xGChain", "xGBuildup"]
for col in numeric_cols:
    df[col] = pd.to_numeric(df[col])
```

`id` and `understat_season` are deliberately left as strings — they're identifiers/labels,
not quantities. Note `understat_season` is a string like `"2016"`; sort/filter by season
either as a string or cast to int explicitly if numeric ordering matters.

### Practical rule going forward

Always run the cast above immediately after loading this file, before any aggregation,
sort, or filter on the numeric columns. No fix has been applied to the file on disk — this
must be repeated in every script that touches this file, or wrapped in a shared loader
function if this file gets used more than a couple of times.

### Files involved

- `data/history/understat_season_aggregates.parquet` — original, untouched, still has
  string-typed numeric columns; cast required on every load.

---

*Last updated: Phase 2, Week 4/5 boundary*

---

## 3. Duplicate `understat_id` in `player_id_crosswalk_final.csv` — one Understat ID
   claimed by two different real players — CONFIRMED AND FIXED

**Status:** Fixed in place (file overwritten — this was a single-cell correction to an
already-"final" file, not a structural rebuild). Found by the data-exploration chat,
verified independently here, logged for the record.

### What was wrong

`element=646` (João Victor Gomes da Silva, i.e. "João Gomes", Wolves) and `element=311`
(Norberto Bercique Gomes Betuncal, i.e. "Beto", Everton) were BOTH assigned
`understat_id = 11384`. Only one of them can be correct — 11384 is genuinely João Gomes'
Understat ID (confirmed via `understat.com/player/11384`, a real, live Wolves player page).
Beto's real Understat ID is 9983 (confirmed via `understat.com/player/9983`, a real, live
Everton player page).

**Likely root cause:** both players' full legal names contain the token "Gomes"
("João Victor **Gomes** da Silva" / "Norberto Bercique **Gomes** Betuncal") — almost
certainly what caused whatever name-matching step built this crosswalk entry to collide
the two. Same general failure family as the earlier fuzzy-match errors documented when the
crosswalk was first built (duplicate "Gabriel" claims, duplicate "Rayan" claims) — shared-
surname-token collisions are a recurring risk pattern for this player pool, especially for
Portuguese/Brazilian names built from multiple family-name tokens.

### How it was found and verified

1. Found via manual/exploratory review, not the original automated duplicate-detection pass.
2. Verified both real Understat player pages independently via web search before accepting
   the correction.
3. Ran a full systematic sweep afterward, checking ALL of `element`, `player_id`, and
   `understat_id` for ANY duplicate values across the whole 841-row crosswalk — **confirmed
   this was the only duplicate in the entire file**.

### The fix

```python
crosswalk.loc[crosswalk["element"] == 311, "understat_id"] = 9983
```

Applied directly to `data/history/player_id_crosswalk_final.csv` (overwritten in place).

### Practical rule going forward

If this crosswalk is ever rebuilt (e.g. extended to another season), rerun the full
duplicate sweep (all 3 ID columns) as a standard last step before trusting the output —
this bug proves the original build process can let at least one collision through silently.

### Files involved

- `data/history/player_id_crosswalk_final.csv` — corrected in place; `element=311` now
  correctly shows `understat_id=9983`

---

*Last updated: Phase 2, Week 4/5 boundary*

## Bug #4: `starts` column broken for 2022-23 GW1–15 (all seasons parquet)

**File affected:** `data/history/all_seasons.parquet` (source: vaastav)
**Fixed copy:** `data/history/all_seasons_fixed.parquet`
**Status:** Fixed (labels quarantined, not reconstructed)

### Symptom
`starts` was added by vaastav from 2022-23 onward. In 2022-23, for GW1
through GW15, the column is unreliable: many genuine starters are recorded
as `starts=0`.

### How it was found
Cross-check `starts` vs `minutes`: found 2005 rows with `starts=0` AND
`minutes>=90`. A full 90 is impossible without starting (FPL caps minutes at
90; a sub cannot accumulate 90). All 2005 were exactly 90 min, all in
2022-23, all in GW1–15 (GW7 absent — postponed round after the Queen's
death, so no matches; consistent with real data).

### Scope is wider than the 2005
An 11-slot budget check (count confirmed starters per team-gameweek in the
window) found NO team-GW reaching 11 confirmed starters — most sat at 5–6.
Since every team fields exactly 11, this proves the bug affects far more than
the 2005 unambiguous cases: starters subbed off before 90 min (and other
cases) are also mislabelled `starts=0`. The column is untrustworthy
wholesale for this window, not surgically fixable player-by-player.

### Breakdown of `starts=0` rows in 2022-23 GW1–15
- minutes == 90 : 2005  (certain real starts)
- minutes 60–89 :

## Bug #5: Assistant Manager (AM) rows pollute player data

**File affected:** `data/history/all_seasons.parquet` / `all_seasons_fixed.parquet`
**Status:** Handled in modeling (rows filtered out); not fixed on disk

### Symptom
The `position` column contains a 5th value, `AM` (Assistant Manager), alongside
the four real player positions (GK/DEF/MID/FWD). 312 rows, all in 2024-25.

### Cause
FPL introduced the Assistant Manager chip in 2024-25. Managers (e.g. Mikel
Arteta) appear as selectable entities in the game and therefore appear as rows
in vaastav's player data — but they are NOT players.

### How it was found
Two independent smells during Wave 2 feature building, which turned out to be
the same root cause:
1. `position_code` had 5 categories (0-4) when FPL has only 4 positions.
2. `value` had a minimum of 5 (= £0.5m), below FPL's £3.5m minimum player price.
Investigating both led to the same 312 AM rows (managers are priced ~£1.5m,
i.e. value=15, and always have minutes=0, starts=0).

### Impact if unhandled
Managers never start matches, so all 312 rows are guaranteed starts=0 with
minutes=0. They follow none of the logic a minutes model learns from, and would
inject pure noise into training. They also break any price-based feature
(a £1.5m "player" is nonsense as a nailedness prior).

### Fix applied
Filter `position != "AM"` before modeling. Applied in the notebook after the
double-GW collapse, before feature assembly. `position_code` is derived AFTER
this filter so codes run 0-3, not 0-4.

### Note for future seasons
The AM chip may persist or return. Any season using the chip will contain AM
rows — the filter should stay permanently in the modeling pipeline rather than
being treated as a one-off 2024-25 patch.

## Walk-forward prediction files — which is which (2026-08-11)

Three files, identical shape, DIFFERENT odds assumptions. The filename is the
only thing distinguishing them, so check here before trusting a season total.

| File | ODDS_HORIZON_GWS | What it assumes |
|---|---|---|
| `walkforward_h6_2526.parquet` | **0** | Odds for the CURRENT gameweek only. Everything further out falls back to Dixon-Coles. This is production reality and the default. |
| `walkforward_h6_2526_odds2.parquet` | 2 | Odds through k+2. Optimistic — bookmakers have not reliably priced two gameweeks ahead at a Friday deadline. Kept only to reproduce earlier numbers. |
| `walkforward_2526.parquet` | n/a | Original single-cutoff file, no `cutoff` column. Correct for the v1 single-transfer policy ONLY. |

**Editing `ODDS_HORIZON_GWS` does not regenerate anything.** The constant on disk
describes the LAST build, not the file you are about to read. Rebuild with
`uv run python eval/walkforward.py --horizon 6` (~8-20 min) after changing it.

### The leak this hid
`load_season()` defaults to `horizon_aware=False`, which loads the single-cutoff
file. Combined with `policy="mip"` that is a real leak: the planner reads gameweek
k+1 as-of-k+1 rather than as-of-k. `experiment.py` raises on this; calling
`simulate_season` directly does NOT. Measured cost at H=3/decay 0.45: ~8 points
(2083 vs 2075) — small at a short horizon, larger at H=6.

### The finding that came out of it
On the honest file the transfer MIP scores **1886** (H=3, decay 0.45; DC-only grid
peaks at 1973 at decay 0.3). The v1 single-transfer search scores **1889** and is
INVARIANT to this change, since it only ever reads `cutoff == gw` rows.

**Without odds beyond the current gameweek, the multi-gameweek MIP's advantage over
the single-transfer search essentially disappears.** Its edge was coming from
odds-informed future gameweeks, not from the optimization itself. Decay 0.45 was
tuned on the odds file and is not the DC-only optimum — re-tune before quoting.