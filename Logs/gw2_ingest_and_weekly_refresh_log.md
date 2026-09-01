# GW2 ingest + weekly refreshes — 2026-09-01

Task: give the live build GW2 (it had GW1 features only), run the weekly
refresh sequence, verify the GW3 strict build still passes, re-run parity.
Plus (added mid-task): the transfer-window-closed watchlist.

## 1. The gate opened

`bootstrap-static` event 2: `finished=True, data_checked=True` (checked
2026-09-01 ~18:00 local). The 2026-08-31 refusal was correct; today the gate
opened on FPL's own flag, no workaround.

## 2. Ingest

`fetch_fpl_history --season 2026-27 --gw 2`: **626 player-fixture rows, 10
fixtures, cross-check vs event/live PASSED**; season file now 1,236 rows,
gws [1, 2]. `--combine` -> all_seasons_with_2026_27.parquet (253,900 archive
rows untouched + 1,236).

### Final vs the 2026-08-31 provisional pull (gate-holding evidence)

625 common (element, fixture) keys, 72 comparable columns, 45,000 cells:
**1,393 cells moved (3.1%)**.

- **442 moves in fixture 20** (Villa v ?, kicked off 19:00Z on 2026-08-31 —
  IN PLAY during the provisional pull): minutes, points, bps, goals, saves,
  DC, team score — live-match incompleteness, e.g. element 1 minutes 21->90.
  Bonus flipped here too (element 10: provisional 3 -> final 1; element 36:
  3 -> 0) — provisional bonus is an in-play bps estimate.
- **951 moves spread evenly (~100/fixture) across ALL nine finished
  fixtures**: ONLY `ict_index` / `influence` / `creativity` / `threat` —
  FPL recalibrates the ICT family after the fact. No modelling-read stat
  column moved on any finished fixture.
- **One key swapped**: element 166 (Nicolas Jackson) provisionally attributed
  to fixture 16 with 0 minutes; finally to fixture 20 (Aston Villa) with 70
  minutes — a deadline-day club transfer re-attributed by FPL mid-window.

Reading for future weeks: once a fixture is finished, the substantive columns
are stable pre-data_checked; the ICT family, bonus of in-play fixtures, and
transfer re-attribution are not. The gate earns its keep on the tail
fixtures and on windows with transfers, i.e. exactly this week's shape. Hold
it as-is.

## 3. Understat

`understat_matches --season 2026-27`: 20 completed matches listed, **1
fetched** (31199, the Monday match; the nine deferred ids 31190–31198 came
off the raw cache). File: 622 rows, 20 matches, **gw 1: 10 matches / gw 2:
10 matches, zero gw=None, zero gw_ambiguous**. GW2 = 312 rows.
Aggregates: 364 rows as of 20 completed matches; combined = 5,343 stored
(untouched) + 364.

## 4. Crosswalk rebuild (the weekly step)

364/364 understat players matched (298 exact, 56 fuzzy, 5 fuzzy_club,
1 club_token, 4 manual), 0 hard disagreements, pct_minutes_covered 100.0,
**0 elements with real minutes and no id** (the held-by-test invariant).

- **11 newly matched elements** — the system working: Nicolas Jackson (166,
  watchlist), Bruno Guimarães (452), Zion Suzuki (597), Konsa (31), Abraham
  (56), Wan-Bissaka (611), Bouaddi (616), Ali-Cho (617), Palacios (619),
  McAidoo (621), Braithwaite (622).
- **0 elements whose understat id changed** (the alarm condition — clean).
- **One id reassigned between elements, diagnosed benign**: understat 14097
  "Ryan McAidoo" moved element 392 -> 621. Last week's fuzzy match had put
  McAidoo's id on Rayan Aït-Nouri (392 — similar name, same club, 0 minutes).
  McAidoo debuted in GW2 as element 621 (8 min); the exact match claimed the
  id and the wrong fuzzy match self-corrected. Aït-Nouri (0 minutes) is
  correctly unmapped.
- Duplicate sweep: 0 duplicate understat ids, 0 duplicate elements.
- The profile audit needs ~450 minutes per player, so at two gameweeks it
  still checks **nothing** — `audit_hard_disagreements 0` is vacuous, not
  reassurance.

## 5. Skeleton + fixture universe + availability + odds

- `build_forward_skeleton`: **22,644 forward rows, gws 3..38** (was 2..38);
  20 played fixtures skipped; no postponed. Rebuilt immediately after the
  ingest — the stale skeleton still carried synthetic GW2 rows which now
  collide with real GW2 master rows; `load_stack`'s collision assert exists
  precisely to catch that state, and rebuilding first means it never fires.
- `fetch_fixtures` + `--combine`: 380 fixtures, **20 finished with scores**
  (DC now sees the GW2 results). NOTE: this rewrite nulls the price columns
  by design, hence the odds refill next.
- `merge_live_availability`: 23,611 rows (1,219 poller-authoritative +
  22,392 fplcache-only); disagreements counted
  ({status: 12, chance_this_round: 3, news: 16}), not silent.
- `fetch_live_odds`: **20/20 listed events priced, 0 thin-panel** (covers
  GW3+GW4 boards); 1 credit; **19,364 credits remaining** (636 used total).

## 6. hmin refit — two gameweeks of features

Snapshotted the old fit, deleted, refit cutoffs 1–3 -> 11,190 rows (was
11,172; +3 elements × 6 steps at cutoff 3).

- cutoff 1: identical (means to 4dp) — training unchanged, as expected.
- cutoff 2: essentially unchanged (p_start 0.3642 -> 0.3644).
- **cutoff 3 (the GW3 deadline fit): p_start mean 0.2018 -> 0.3515**,
  e_minutes mean 19.18 -> 31.67. Per step: gw3 0.161 -> 0.362, decaying to
  gw8 0.230 -> 0.344. The one-gameweek conservatism (0.20 vs 2025-26's
  ~0.30–0.31) was feature scarcity and two played gameweeks resolved it —
  the fit now sits at/just above the 2025-26 reference band.
- Per-row deltas at cutoff 3: median p_start +0.044, p95 +0.49; 1,706/3,756
  rows moved by >0.1 — the mass is players whose GW2 start/no-start resolved
  their status.

## 7. Props book refresh

- Crosswalk rebuild: 2026-27 outfield starter coverage **96.11%** (11
  players / 14 player-fixtures uncovered; 13 unpriced, 1 unmatched-with-
  candidate). GW3: 455 board rows, 415 matched, 40 unmatched (dominated by
  promoted-club boards).
- Consensus rebuild: 9 retained books, void-rule gate enforced (excluded
  rows counted per book: espnbet 26/30, williamhill_us 30, betparx 30,
  ballybet 30, williamhill 20, pinnacle 6).
- **Jackson props note**: his GW2 board row ("Chelsea v Brighton") is now
  correctly UNMATCHED — the club-constrained match refuses because element
  166's club is Aston Villa post-transfer; a historical board row, harmless.
  He is NOT on the GW3 board yet (pulled before books reacted to the move).
  Friday's T-90..T-30 re-pull should list him on Hull v Aston Villa; the
  crosswalk rebuild after the re-pull should exact-match. **Verify on
  Friday** — he is the highest-implied name in the season (0.44) and exactly
  the Cherki class if the board lists him and the match fails.

## 8. The strict build + parity

- `build_deadline_frame('2026-27', 3, strict=True, config='combined',
  horizon=6)`: **PASSED, zero raises. 3,774 rows, gws 3–8** (was 3,756;
  +3 elements × 6 steps).
- **Full suite: 226 passed** (200.9s) — including the record-parity family
  (three cutoffs GW5/20/33, both configs, record DC source pinned via
  `_frozen_record_source`), the milestone test, the preflight ledger, the
  book gate, the forward-skeleton family. Nothing historical moved.

## 9. Transfer-window watchlist (window shut 2026-09-01; report-only, no fixes)

Bootstrap today: **629 elements; 3 new** since the 2026-08-31 snapshot (the
provisional pull's element universe, 626):

| element | player | club | pos | price | minutes | understat id |
|---|---|---|---|---|---|---|
| 627 | Bradley Barcola | Liverpool | MID | £8.0m | 0 | none — positional prior |
| 628 | Allan (Andrade Elias) | Man City | MID | £6.0m | 0 | none — positional prior |
| 629 | Michael Zetterer | Leeds | GKP | £4.0m | 0 | none — positional prior |

- 0 of 3 have played; 0 have an understat id; **all three ride the
  positional prior until they play** (Understat lists a player only after
  his first EPL appearance — the weekly crosswalk rebuild picks each up
  then; none of these needs a MANUAL entry).
- Decision-partition likelihood: **Barcola is the one to watch** — an £8.0m
  Liverpool midfielder reaches the top-30 partition the moment he starts,
  and until his first appearance he carries the positional prior (the
  Cherki-class exposure, ~+1.3 e_points/row if mis-modelled while in the
  top 30). Allan (£6.0m, Man City rotation) is possible but unlikely to be
  a likely-starter immediately; Zetterer (£4.0m backup GK) is not
  partition-relevant.
- Adjacent, not new-element: **Nicolas Jackson** (166, £6.5m FWD, Aston
  Villa, 70 min) — already crosswalked for Understat; props mapping pending
  Friday's board re-pull (see §7).

## 10. Still needed before Friday 2026-09-04 13:30 local (17:30Z)

1. Deadline-day re-runs (idempotent): merge_live_availability,
   fetch_live_odds (1 credit), pull_live_props GW3 at T-90..T-30
   (30 credits) + crosswalk/consensus rebuild, calendar-sensitive strict
   build last. hmin refit does NOT need re-running (no new labels before
   the deadline).
2. **Verify Jackson lands on the Villa GW3 board and matches** after the
   props re-pull (§7).
3. Open item 4 from the handoff still stands: the live-sim `load_season` /
   optimizer path at one gw has never been exercised — the frame builds,
   but the transfer decision end-to-end is untested.
4. User-side standing items: GW2/GW3 scheduled-task cleanup, ANTHROPIC key
   rotation.
