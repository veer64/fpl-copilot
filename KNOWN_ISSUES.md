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


## #9 — Core-Insights availability fields: two defects (found 2026-08-12)

`data/history/core_insights_gameweek_stats.parquet` carries `status`, `news`,
`chance_of_playing_this_round` and `chance_of_playing_next_round` — the only
per-gameweek availability data in the project. vaastav has none of it
(`players_raw.csv` is a single end-of-season snapshot, and stops after 2019-20).

The file IS a genuine per-week capture: a full 38x38 pairwise comparison found
exactly one non-adjacent identical pair. Adjacent weeks differ as expected
(GW15 vs GW16: 88.4% of players share a status). But two defects must be handled.

### Defect A — GW1 is a GW15 snapshot. DROP IT.
GW1 and GW15 are 100% identical across `status`, `news` and
`chance_of_playing_next_round`, for all 759 players in both. GW1 was backfilled
from a GW15-era pull.

Using it is a serious leak: it tells the model at GW1 who was injured in December.
Drop GW1's availability fields entirely — do not impute.

Unfortunate, because cold start (GW1-7 runs at 38.3 pts/gw vs 52.3 after) is
exactly where availability would help most. Gvardiol was a GW1 failure.

### Defect B — GW2-10 encode NULL as 0.0. RECODE.
In those weeks `chance_of_playing_next_round` is non-null for all 752 players.
FPL only populates this field for doubtful players, so full coverage is wrong.

The crosstab shows what happened. GW5:

| status | 0.0 | 25 | 50 | 75 | 100 |
|---|---|---|---|---|---|
| a (available)   | **459** | 0 | 0 | 0 | 92 |
| d (doubtful)    | 0 | 10 | 11 | 10 | 0 |
| i (injured)     | 35 | 0 | 0 | 0 | 0 |
| u (unavailable) | 130 | 0 | 0 | 0 | 0 |
| s (suspended)   | 4 | 0 | 0 | 0 | 0 |

459 AVAILABLE players carrying 0.0 is contradictory. Nulls were written as zero —
and zero is a meaningful value here ("will not play"), so this is not a harmless
placeholder. Everything else is coherent: d maps to 25/50/75, i/u/s map to 0.

Fix: in GW2-10, set `chance_of_playing_*` to NULL where `status == 'a'` and the
value is 0.0. Genuine zeros (status i/u/s) stay. From GW11 the field behaves
normally (427 non-null of 752).

### Caveat on all of it
One row per gameweek, captured at whatever moment Core-Insights pulled — not
necessarily the Friday deadline. Probably close, but not provably as-of.

The better long-term source is `Randdalf/fplcache` (GitHub, Unlicense): the FPL
`bootstrap-static` endpoint cached 4x daily as `{year}/{month}/{day}/{time}.json.xz`,
~7,450 commits. Timestamps let you select the pre-deadline snapshot exactly, and
it is the same field the production agent would read live — no train/serve
mismatch. Coverage for 2025-26 not yet verified.

Paid alternatives (API-Football /sidelined, Sportmonks sidelinedHistory) supply
injury start/end dates rather than as-of snapshots. End dates leak — nobody knew
on 5 Feb that an injury would end on 20 Feb — so they are second choice despite
richer detail.
---

## #10 — `minutes.py` defaults to `availability=True`, but the canonical walk-forward
   file was built WITHOUT it (found 2026-08-13)

**Status:** Live trap. Documented and guarded by a test; deliberately NOT resolved,
because resolving it means moving the project's baseline.

### The trap

`squad/minutes.py` now defaults to `availability=True` (adopted 2026-08-13; see
`Logs/availability_log.md`). `data/walkforward_h6_2526.parquet` was built BEFORE that
adoption, so it holds pre-adoption predictions.

**Regenerating that file with today's default silently moves the baseline from 1984
to 1938.** Nothing errors. Every number in every log that quotes 1984 becomes
incomparable, and the change is invisible unless you already knew to look.

    data/walkforward_h6_2526.parquet     availability=False   -> season 1984
    data/walkforward_h6_2526_av.parquet  availability=True    -> season 1938

This is the same shape as the stale-odds incident: `ODDS_HORIZON_GWS = 0` read from
source while the parquet on disk had been built at 2. Source and artefact disagreed,
nothing failed loudly, and an hour went into attributing the difference to a code
edit. Same failure mode, so it gets a loud guard rather than a comment.

### Why it is not simply fixed

Rebuilding the canonical file is the "clean" move and is exactly what must not happen
by accident. The availability model is better on component metrics but does NOT
improve the season total, so adopting it as the baseline would change the reference
every prior experiment is quoted against, in exchange for nothing measurable. That is
a deliberate decision, not a chore — it needs to be made explicitly.

### The guard

`Tests/test_walkforward_provenance.py` fingerprints the canonical file (row count,
horizon-0 Spearman and MAE). Regenerating it with availability on moves Spearman from
0.715 to 0.745 and the test fails with an explanation. The fingerprint is meant to be
updated by hand, deliberately, when the baseline is intentionally moved.

Going forward `eval/walkforward.py` stamps `minutes_availability` into its output, so
new files describe their own provenance. Files without that column predate the stamp
and are pre-adoption by definition.

### If you DO decide to move the baseline

1. Rebuild: `uv run python eval/walkforward.py --horizon 6`
2. Re-run the season to get the new reference number.
3. Update the fingerprint in `Tests/test_walkforward_provenance.py`.
4. Update every log that quotes 1984 — or state plainly that pre-2026-08-13 numbers
   are on the old baseline and are not comparable.

---

## #11 — 2021-22 and 2022-23 are NOT portable to the walk-forward harness
   (decided 2026-08-14)

**Status:** Standing decision, not a bug. Recorded so a future session does not
retry the port without knowing why it was refused.

### The constraint

`starts` — the target of the P(start) model, and the gate on every minutes-derived
term — does not exist in vaastav before 2022-23:

| season  | rows   | `starts` non-null | %     |
|---------|--------|-------------------|-------|
| 2021-22 | 25,447 | 0                 | 0.0   |
| 2022-23 | 26,505 | 18,014            | 68.0  |
| 2023-24 | 29,725 | 29,725            | 100.0 |
| 2024-25 | 27,605 | 27,605            | 100.0 |
| 2025-26 | 29,757 | 29,757            | 100.0 |

2021-22 has no label at all. 2022-23 has a partial label (the GW1–15 quarantine,
KNOWN_ISSUES #4) and — more decisively — no PRIOR season carrying the label, so
the minutes model could only be trained on later seasons. That is training on the
future, which is the exact leak the walk-forward harness exists to prevent.

### Why the obvious workaround is refused

The tempting fix is to infer `starts` from `minutes` for the missing seasons.

**That reintroduces the defect the quarantine was created to isolate.** 2022-23
GW1–15 was quarantined precisely because minutes cannot distinguish a subbed-off
starter from an early substitute: 2,005 rows had `starts=0` with `minutes>=90`,
and an 11-slot budget check showed no team-gameweek reaching 11 confirmed
starters, so the corruption was far wider than the unambiguous cases. Inferring
the label season-wide would bake that same ambiguity into the target itself, and
every downstream figure from those seasons would silently inherit it.

**Three seasons on a clean label is better evidence than five with two built on a
known-bad target.**

### What this means for M2

The multi-season replication set is **2023-24, 2024-25 and 2025-26**. Not five.
Any claim resting on cross-season replication is a three-season claim.

### The guard

`eval/walkforward_season.py::train_seasons_for()` returns only prior LABELLED
seasons and `walk_forward()` raises for a season with none, pointing at this
entry. It cannot silently fall back to training on the future.

---

## #12 — Crosswalk ONE-TO-ONE wrong matches: a defect class the duplicate sweep
   cannot see (found 2026-08-14)

**Status:** Two instances found and corrected. A post-build audit now guards
against it. The class is not fully closed — see "What the audit cannot catch".

### The defect

A vaastav `element` mapped to the WRONG Understat `id`, where the mapping is still
one-to-one. Nothing is duplicated, nothing errors, and the player simply carries
another player's attacking rates for a whole season.

**KNOWN_ISSUES #3's duplicate sweep cannot detect this.** That sweep checks whether
an id is claimed twice. Here each id is claimed exactly once — it is just pointing
at the wrong person.

### The two instances

Both are Brazilian/Portuguese full-legal-name cases at Nottingham Forest, and both
were found by ACCIDENT while chasing an unmatched player, never by any check on the
matched ones.

**1. 2024-25.** Element 653 "Felipe Rodrigues da Silva" (Forest DEF, 891 min, 0G 0A)
claimed Understat 12766 "Jota Silva" (Forest MID, 799 min, 3G 1A) via a club+token
pass scoring 66.7. A defender took a forward's identity.

Root cause: the token-uniqueness test was evaluated against UNCLAIMED club-mates
only. The other "Silva" at the club had already been matched and was therefore
invisible, so "silva" looked discriminating when it is not. Fixed by testing
uniqueness against every club-mate in the season, claimed or not.

**2. 2025-26 — the canonical file.** `player_id_crosswalk_final.csv`, element 511
"Felipe Rodrigues da Silva" (Forest DEF, 1340 min, 1G 0A) → 12766 "Jota Silva"
(7 min). Correct id is 13068 "Morato", who IS Felipe Rodrigues da Silva:
1340v1333 min, 1v1 G, 0v0 A.

This one had a measurable effect. Attacking rates pool prior seasons and require 450
minutes; Jota Silva's 2024 row has 799, so it CLEARED the threshold and was used
rather than falling back to a prior:

    id 12766 (used)      npxG/90 0.3085   xA/90 0.3779
    id 13068 (correct)   npxG/90 0.0110   xA/90 0.0000

A centre-back was given a winger's attacking rate — ~28x the npxG. His `pts_goals`
averaged 0.403 against a DEF cohort mean of 0.137, the 91st percentile of defenders
for predicted goal points, for a player who scored once.

**Mitigation:** element 511 was never selected in any gameweek of the canonical run
and appeared in no transfer, so the realised path was unaffected. He does sit in the
pairwise-margin population as an inflated DEF.

### The guard

`eval/build_crosswalk.py::_audit()` runs automatically after every build. For every
matched pair with 450+ minutes it compares minutes and goals across the two
independent sources:

- **minutes**: tolerance `max(240, 35% of the larger value)` — scaled, because 60
  minutes apart is nothing on 2,500 and damning on 150. **RAISES on failure.**
- **goals**: absolute margin of 3, which absorbs definitional differences without
  absorbing a different player. **RAISES on failure.**
- **club**: **WARNS only.** Mid-season transfers produce genuine false positives
  (Ouattara, Ramsey, Garnacho, Nelson, Doak all legitimately show one club in
  vaastav and another in Understat).

### What the audit CANNOT catch

It catches wrong matches whose profiles disagree. It cannot catch a wrong match
between two players with similar minutes and goals at the same club — Arsenal's
three Gabriels would pass it. **The uniqueness rule remains the primary defence and
the audit is a second net with known holes.**

### Practical rule

Any crosswalk that is built, edited or extended gets the audit run over it. The
2025-26 canonical file was built by the original fuzzy-then-manual process and had
never had this audit applied until now; it has now been audited and corrected, and
the canonical walk-forward file was rebuilt on the corrected version.

---

## Open puzzle — 2024-25: worst minutes model, best-calibrated margins (2026-08-14)

Not a bug. Recorded because it sits underneath a number the project may lean on.

    season    P(start) AUC   E[min] MAE      started beta (H=3 decayed)
    2023-24       0.9601        11.44               0.540
    2024-25       0.9533        12.44               0.662   <- worst model, best beta
    2025-26       0.9605        11.27               0.389

2024-25 has the weakest minutes model of the three portable seasons AND the
best-calibrated pairwise margins between players. The two move in opposite
directions and **there is no account of why**.

The minutes gap itself was investigated and is largely explained — 2024-25 is
intrinsically harder (most rotation, shortest appearances, fewest full 90s, weakest
week-to-week start persistence at 0.7021 against 0.7281 and 0.7231), with 62% of the
MAE gap attributable to band mix rather than worse within-band prediction. AM
leakage, feature coverage and training composition were all ruled out.

What is unexplained is the calibration direction. This matters because 2024-25 is
the MIDDLE observation in the 6-10 implied-hit-bar range
(`Logs/margin_calibration_log.md`); anyone treating that range as a stable estimate
should know its middle value is unexplained.

**2026-08-17: the beta column above is contaminated** — those values were measured
on files carrying D1 terms while described as baseline (see #13 and the retraction
header in `Logs/margin_calibration_log.md`). The puzzle may dissolve entirely on
clean files; do not investigate it before re-measuring.

---

## #13 — D1 scoring terms entered `assembly.py` before the "baseline"
   measurements ran; every rebuilt file carried them with no stamp
   (found 2026-08-17)

**Status:** Incident recorded. Logs retracted, stamp and guard added. No D1
verdict is implied here — adopting or reverting D1 is a separate, still-open
decision that must be made on clean before/after measurements.

### What happened

D1 (saves, goals conceded, cards, penalty share) was implemented into
`squad/assembly.py` on 2026-08-14. The pairwise margin-calibration measurements
ran AFTER that, on walk-forward files regenerated with the modified equation —
while describing those files as the pre-D1 baseline. Nothing errored, because no
stamp existed to say whether a file carried the terms.

Same class as #10 (the availability footgun) and the stale-odds incident: source
and artefact disagree, nothing fails loudly, and downstream conclusions inherit
the mismatch invisibly. This is the third instance of the class; the lesson is
that ANY equation-changing flag must be stamped into the artefact the moment it
exists, not when it first causes a problem.

### What was contaminated

- `Logs/margin_calibration_log.md` — the entire β table, the "~2.5× starter-band
  exaggeration", the three-season replication, and the implied 6–10 hit bar.
  Retracted via header. The verified clean pair: baseline GK β at step 0 is
  **0.847** (`data/walkforward_h6_2526_baseline.parquet`, D1 disabled, stamps
  otherwise identical), with-D1 is **0.425**. The log's 0.41-region "baseline"
  was in fact the with-D1 measurement.
- `Logs/hit_threshold_log.md` — motivating figures void; the grid may have read
  the same files and needs re-running. The decision (threshold stays 4) stands
  on its own, but its stated rationale is unverified either way.
- The "Open puzzle" β column directly above this entry (0.540 / 0.662 / 0.389) —
  same source.
- The first D1 comparison report's "baseline" columns (β 0.945/0.837, the
  three-season Spearman table) are worse than contaminated: untraceable to any
  file on disk, and inconsistent with the verified re-measurement.

### The fix

`squad/assembly.py` now carries `D1_TERMS_ACTIVE`, which both GATES the D1 terms
in `_finish_equation` and is STAMPED into every walk-forward file as
`d1_terms_active` — a per-row provenance column exactly like
`minutes_availability` / `odds_horizon_gws` / `dgw_handling`, written by both
`eval/walkforward.py` and `eval/walkforward_season.py`. Because gate and stamp
read the same constant, an artefact cannot disagree with the code silently.

`Tests/test_walkforward_provenance.py` requires the stamp on the canonical file
and asserts it matches `assembly.D1_TERMS_ACTIVE`
(`test_d1_stamp_matches_code`), so a rebuild under a flipped flag fails loudly.

Files missing the column predate the stamp. Establish their status from the data
— `pts_saves` non-zero on GK rows means D1 was active — before comparing them
with anything.

---

## #14 -- "Sheffield United" vs "Sheffield Utd": a team-name join failure that
   manufactured a season of zero predictions (found 2026-08-17)

**Status:** Fixed (TEAM_MAP + per-team guard + neutral fill) and 2023-24
rebuilt. Recorded because it is the THIRD instance of the silent-fallback
family (#10 availability, #13 D1 stamp): a fallback that manufactures
plausible-looking values instead of failing loudly.

### What happened

The odds source names the club "Sheffield United"; vaastav names it
"Sheffield Utd". TEAM_MAP had no entry for it, so the Dixon-Coles fixture join
(on team + match_date, squad/assembly.py) failed for EVERY Sheffield fixture
in their Premier League seasons on disk: 2019-20, 2020-21 and 2023-24. All 38
of their 2023-24 fixtures have complete Bet365 prices in
odds_all_seasons.parquet -- the odds were never missing, only the name match.

Downstream, the failure compounded through two silent fallbacks:

1. team_lambda NaN -> fixture_scale fell back to a neutral 1.0 (by design).
2. p_cs NaN -> pts_cs NaN -> e_points_core NaN per fixture -> and the
   per-gameweek collapse SUMS an all-NaN column into a clean 0.0.

Net effect: every Sheffield Utd player carried e_points = 0.000 for every
gameweek of 2023-24 -- 1,429 step-0 rows (5.0% of the season), including 36 GK
and 134 DEF rows in the starter band with realised minutes averaging 78 and
realised points averaging 1.8. A file full of structurally-valid-looking rows
whose predictions were join-failure artefacts.

The existing guard (matched_frac < 0.90 raises) could not see it: one team of
twenty is ~5% of rows. A full-season single-team failure is invisible to a
global threshold by construction.

### What was contaminated

Every 2023-24 walk-forward measurement made before 2026-08-17 included these
rows. Specifically, from the D1/GK work: the three-season before/after tables,
the top-k selection measurement, the model-agreement measurement, the adoption
metrics in Logs/d1_log.md section 8 (2023-24 aggregate Spearman 0.668 -- the gap
to the other seasons' 0.74-0.75 was substantially this artefact), and the GK
investigation step-1 baseline beta for 2023-24 (0.560, corrected to ~0.83 on
market-complete rows -- see Logs/gk_investigation_log.md sections 6-7). The
retracted margin-calibration and hit-threshold logs also included them, on top
of their #13 contamination. Any earlier handoff figure for 2023-24 inherits
the same rows.

**2025-26 and 2024-25 are unaffected** -- zero null-market rows in either
season (Sheffield were not in the league). Prior-season POOLED RATES are also
unaffected: they read vaastav only and never touch the odds join.

### The fix (2026-08-17)

1. TEAM_MAP gained "Sheffield United" -> "Sheffield Utd". The full audit of
   every team name in odds_all_seasons.parquet against every vaastav team
   name across all ten seasons found this to be the ONLY unmatched name in
   either direction; nothing else remains silent.
2. A PER-TEAM guard beside the global one: any team with >= 3 fixture rows
   matching below 50% raises with the team named. A stale name mapping fails
   ~100% of one team's joins, so 50% separates that class cleanly from the
   occasional genuinely unpriced fixture.
3. The deeper fallback is closed: residual guard-passing unmatched fixtures
   now get NEUTRAL market values (lambda 1.40 both ways, p_cs = exp(-1.40)
   ~= 0.25) instead of NaN, so a join failure can no longer reach the
   NaN-sum-to-zero path and a player keeps his minutes/rates-based prediction
   under a neutral-fixture assumption.
4. 2023-24 rebuilt, both canonical (Variant B) and no-D1 baseline. The
   contaminated artefacts are preserved as
   data/walkforward_h6_2023_24_sheffbug.parquet and
   data/walkforward_h6_2023_24_baseline_sheffbug.parquet, so every figure
   they produced stays checkable.

### The family pattern, third confirmation

#10: an availability default that silently moved the baseline. #13: an
equation change with no stamp, so "baseline" measurements ran on modified
files. #14: a join failure whose NaN summed to a clean 0.0. In all three, the
failure produced OUTPUT THAT LOOKED VALID. The recurring lesson: every
fallback needs either a loud guard at the failure grain (per-team here, not
just global) or an explicit, stated neutral value -- never an accidental zero.
