# Handoff — 2026-08-31 → 2026-09-01 — the live-readiness session

**End state, one line: BOTH configs build a real 2026-27 deadline frame end to end;
a GW3 horizon-6 COMBINED build runs UNDER STRICT with zero raises
(`test_strict_preflight_combined_clean_at_live_deadline` pins it). Suite 226,
parity bit-identical six cells, tree clean at 25e34ad.**

Read this with `Logs/` (each task has a dated log) and `KNOWN_ISSUES.md`. The
memory files were updated (`fpl-live-ready-2026-27`, `fpl-dc-source-adopted-fpl-official`).

---

## 0. Compressed earlier-session context (pre-compaction, on record elsewhere)

D6 poller due-gate fix + GW3 scheduled tasks; droplet migrated to docker-compose
(backup verified, old volume kept); full 2026-27 ingestion built and verified:
`fetch_fpl_history` (vaastav replacement, 100.00% GW1 parity), core-insights
(+ column_map tackles->tackles_won), understat per-match + aggregates (byte-exact
reproduction proof), crosswalk (310/310, 4 evidenced MANUAL entries), season
constants extended (minutes ladder, TRAIN/PREDICT, ORDER/LABELLED, BLEND_PRIOR;
DC held at the time under #21); live parity harness (`squad/live_deadline.py`
calls `walk_forward(cutoffs=[gw])` — no second implementation) proven
bit-identical on GW5/20/33 both configs. Reference cells of record 2425/2335/2266
(hmin arm on gap0), `EXPECT_REFERENCE_CHIP` asserts them.

---

## 1. Fixture universe + live availability (commits 0b39f12, 4357a87, dbf818a, d6f4a23)

- `eval/fetch_fixtures.py`: FPL fixtures/ -> `data/history/odds_fixtures_2026_27.parquet`
  (odds-archive schema, prices null) + `--combine` -> `odds_all_seasons_with_2026_27.parquet`.
  Club policy: E0 spelling reused iff it round-trips through `assembly.TEAM_MAP`
  (only Man United, Tottenham); ambiguity raises. Guard: past-kickoff-unscored
  REFUSES the write (fired twice on real states — accepts `finished_provisional`
  scores, counted). EVERY archive int64 col -> float64 in slice+combined (NA).
- `squad/dixon_coles.py::_load_matches(predict_season)`: archive verbatim for
  seasons it contains (2025-26 parity BY CONSTRUCTION), `_with_` file for 2026-27+.
- `eval/merge_live_availability.py` -> `data/availability_2627.parquet`
  (poller authoritative per key, fplcache fills; disagreements counted).
- Preflight ledger test (`test_nonstrict_preflight_reports_instead_of_raising`)
  pins BOTH directions (still-open + closed); it was updated at each closure this
  session — keep doing that in closing commits.

## 2. Steps-1-5 extraction + live horizon-6 (c35f2ed, 2f846a1)

- The arm builder's per-cutoff closure (14 captured names) lifted into
  `eval/walkforward_arms.py`: `cutoff_components()`, `assemble_cutoff()`
  (same PROPS_HOOK module gate + finally restore), `stamp_arm_frame()`.
  `main()` calls them; live combined path calls the SAME functions.
  EXTRACTION PARITY: full 38-cutoff 2025-26 rebuild vs
  `arms_gap0/walkforward_h6_2025_26_both.parquet` BIT-IDENTICAL (165,401 rows,
  all columns; sidecar counters identical).
- `build_deadline_frame(..., horizon=)`: baseline -> `walk_forward(horizon=h)`;
  combined -> the extracted pipeline. `compare_to_canonical(..., step=)` per-step.
  H6 GW20 parity: 12/12 cells bit-identical.
- Strict horizon checks added: master rows per target gw; hmin refit presence +
  cutoff coverage; postflight OBSERVES step truncation.

## 3. DC source swap — the full arc (cd199a3, 8e653f2, 24ec9c0, 4391ec7, 57ff0d0)

1. PRE-REGISTERED test (bars committed before numbers): **FAILED** Bar 2
   (unsliced DEF Brier 0.15950->0.16154). Stopped per its own rule; recorded.
2. EXPLORATORY re-measurement (endpoint changed after the fail — NEVER cite as a
   pass): rank +3/4 cells (combined top-30 −0.0379), ECE better nearly everywhere,
   163/231 label flips + 222/271 prediction flips land on decision partitions,
   totals (illustration) baseline −5 / combined +23 with 25/28-of-38 deadlines
   differing. INCIDENT recorded: first sim pass never applied `--wf-path`
   (validated but unwired) and reproduced the records EXACTLY — caught by
   implausibility; the accident stands as a full-season sim determinism check.
3. SIGN QUESTION RESOLVED: every #21 spot-check disagreement was a GOALKEEPER
   (outfield formula vs FPL's definitional 0 for GKs). The REAL discrepancy is
   opposite-signed: FPL counts MORE tackles than core's `tackles` (17.3% of
   matches). #21 corrected in place.
4. **ADOPTED as a judgement call** (user's decision, framing in the log/commit):
   `defensive.DC_SOURCE = "fpl_official"` default; season-parametric
   `_raw_rows_official(season)`; `_DC_HITS_CACHE` keyed `(source, season)`;
   `DC_SEASONS`/`DC_RULE_SEASONS` += 2026-27; empty-predictions cold-start guard
   (2026-27 has 0 predicted rows until played gws accrue -> assembly uses
   DC_BASE, postflight notes it). **Record-parity tests pin
   `core_insights` via `_frozen_record_source()` in `Tests/test_live_deadline.py`**
   — the frozen 2025-26 records predate the adoption. Quantified move vs records:
   mean |Δe_points| 0.0146/0.0205/0.0417 at GW5/20/33.
5. Chip-breakdown forensics (read-only): the 2264 combined cell is CORRECT; my
   2272 recomputation used the wrong cap_pred family. Convention split is real
   and deliberate: gap0-arm TC1 reads use `cap_pred_gap0` (the ARM'S OWN frame —
   both-arm picks GW1 Salah +8), reference rows use `_ref_wf_path`. Also: TC2
   in-sim increment = `captain_bonus // 2`; the gap0 branch never lists a
   TC2-cap@BB2 read. Reference cells recompute exactly (2216/2221/2266/2264;
   2425/2335 incl. the rule-week TC2-equivalent read for TC2-zero arms).
6. **Reference cells 2266 (and combined 2264) are SUPERSEDED by the adoption and
   NOT re-pointed** (2425/2335 are DC-inert). Re-pointing = rebuild 2025-26
   canonical+arm frames under fpl_official + armlogs + EXPECT updates. Open.

## 4. Forward-gameweek skeleton (b75f60e, 7e58d62)

- `eval/build_forward_skeleton.py`: FIXTURES-FIRST construction (a double = two
  rows with distinct fixture ids; a blank = none; postponed event/kickoff-null
  EXCLUDED and listed). Rows carry identity + geometry + value
  (`opponent_team` is the INT team id!); every measurement column NaN
  (int64->float64 in the file; **minutes NaN is the synthetic-row sentinel**).
  Provenance stores the calendar snapshot for the re-pull check.
  BACKFILL verified at cutoffs 5/20/30 (construction ALL EXACT; churn/value
  drift MEASURED; the Ward-Prowse moved-and-met exhibit classified as churn;
  100/391 dup rows dropped mirroring assembly).
- `squad/season_stack.py::load_stack(columns=)` = stack + skeleton, collision-
  asserted (fires if the skeleton is stale after ingesting a played gw —
  **REBUILD THE SKELETON after every fetch_fpl_history ingest**). Wired into:
  `walk_forward`, `minutes.py`, live_deadline preflight + combined build,
  `horizon_minutes._frames`, props crosswalk coverage. Actuals-semantics readers
  stay on `stack_path()` (postflight pen aggregate, defensive official rows,
  ingestion verifiers). Concat upcasts master int64 stat cols to float64 —
  parity-proven harmless.
- `assembly.py` team_pen_rate: denominator = PLAYED gws (`minutes.notna()`),
  else forward rows divide one played gw's pens by 38.
- `live_deadline._fixture_calendar_check` (STRICT-ONLY, does network): re-pulls
  fixtures/ and compares (id, event, kickoff) vs the skeleton provenance
  snapshot; mismatch touching target gws raises (#14 class). Tests monkeypatch
  `ld._pull_fixtures`.

## 5. Live match odds (e78510f, b9e880d)

- `eval/fetch_live_odds.py`: the-odds-api uk h2h -> B365H/D/A columns of the
  2026-27 slice (the ONLY price columns the model reads; `_implied_lambdas` is
  1X2-only). Construction: de-margined MEDIAN CONSENSUS over a FIXED 12-book
  panel (PANEL list in the file), MIN_BOOKS=5 else unpriced-counted. **Bet365 is
  NOT available** — the stated, un-parity-testable input change; `odds_source`
  stamp in dixon_coles documents both eras. λ level matches 2025-26 B365 closing
  to ~0.006 mean total goals. NAME_MAP (20 clubs, loud). ~1 credit/pull covers
  ~2 gameweeks of events.
- CONVENTION CORRECTIONS made honestly: `ODDS_HORIZON_GWS=0` means steps-1+
  prices never reach the model — the steps-1+ all-unpriced strict finding became
  a NOTE (backtests ran the same way). Deadline-gw all-unpriced stays STRICT.
- 2026-27 "graduated": the missing-season strict pin moved to 2027-28 (a latent
  preflight NameError on the no-rows path was fixed by that pin).

## 6. hmin refit + props book (d199a42, a99b11c, a2c87b1)

- **THE MOST IMPORTANT CODE CHANGE OF THE SESSION** — `minutes.py::_prepare`:
  was `df[df["starts"].notna()]`, which dropped every forward row, so NO
  unplayed gameweek could be predicted AT ALL (a live deadline's step 0
  included; backtests never noticed because whole seasons are on disk). Now:
  `df[df["starts"].notna() | df["minutes"].isna()]` (sentinel-based; pre-2022
  label-less seasons keep their exclusion, #11), with label consumers guarded
  (`trc` filters starts.notna; sd/bd's ==1/==0 exclude NaN; horizon `labels`
  filtered). GW3 unplayed: 626 rows, zero NaN e_minutes. Parity-proven.
- hmin refit (`eval/run_horizon_minutes.py` -> `squad/horizon_minutes.py`):
  COLD-START ANSWER — training pairs come from PRIOR seasons (+current only
  where label-gw < cutoff), so a 2026-27 fit is meaningful NOW. Fitted cutoffs
  1-3 -> `data/horizon/hmin_2026_27_refit.parquet` (11,172 rows). Conservative
  vs 2025-26@c3 (p_start mean ~0.20 vs ~0.31) — two played gws of features.
  Refresh per deadline: `--cutoffs <next gw>`.
- Props book panel drift (3 of 7 historical books remain): fanatics + rebet
  VERIFIED as START books from their published rules; ballybet/betparx/espnbet/
  williamhill_us = UNKNOWN -> `props_feature.EXCLUDED_BOOKS_NO_VOID_RULE`,
  dropped counted at consensus AND asserted at hook construction
  (`Tests/test_props_book_gate.py`, incl. a doctored-frame raise test).
  Re-admission requires a quoted published rule.
- GW1-2 consensus from the historical endpoint (602 credits, regions eu,us,us2 —
  us2 REQUIRED, bovada/rebet moved there): coverage 100%/100%, 9 books, hook
  constructs. Pipeline fixes: region-suffix glob (files now `_euusus2`),
  promoted clubs in TOKENS, crosswalk coverage read -> load_stack + empty-guard,
  consensus `n_fixtures` stack fallback + partition report skipped-with-note
  when no walkforward frame exists.
- Crosswalk burden: 88.56% match, **0 manual entries yet**, 69 unmatched names
  (transfer-window master-staleness: Jackson, Guessand...). Maintainer watches
  the printed "proposed MANUAL pass" table + top-unmatched list
  (also in `Logs/props_crosswalk_log.md`).

## 7. Live props pull — the milestone (25e34ad)

- `eval/pull_live_props.py --season 2026-27 --gw N`: live per-event boards
  (events list FREE; odds 3 credits/fixture at eu,us,us2) written in the
  historical raw layout ({"data": ...} wrap + manifest) so crosswalk/consensus
  are UNCHANGED. Re-pulls REPLACE the gameweek's manifest rows (latest
  pre-deadline snapshot is the record); per-fixture timestamps + minutes-to-
  deadline in the manifest. Post-deadline pulls warn loudly.
- Props coverage floor corrected to the hook's reach: PropsHook moves
  `gw == cutoff` rows ONLY -> the 0.80 floor is STRICT for the deadline gw,
  steps-1+ coverage is a note.
- GW3 pulled 10/10 (30 credits). **THE STRICT END-TO-END BUILD**: 3,756 rows,
  six steps; props overrode 407 step-0 player-fixtures; hmin substituted 3,130
  rows; calendar re-pull verified; ALL findings notes.

## 8. Test landscape (226 passing)

Key guards a future session must not break:
- `test_strict_preflight_combined_clean_at_live_deadline` — THE MILESTONE.
- `test_unavailable_props_board_raises_not_degrades` — 0/10 board raises.
- Record-parity family (`test_parity_*`, `test_extraction_*`, `test_live_horizon6_*`)
  — ALL pin `core_insights` via `_frozen_record_source()`; the frozen artefacts
  must stay reproducible bit-for-bit through the gate.
- The preflight LEDGER test — update still_open/closed IN the closing commit.
- `test_dc_source_adopted_fpl_official`, `test_dc_seasons_extended_at_adoption`.
- Forward-skeleton family (doubles/blank/postponed, backfill regression,
  re-pull raise), live-odds family (NAME_MAP raise, exact de-margin, countable
  panel degradation), book-gate family.

## 9. Ops runbook — GW3 deadline (Fri 2026-09-04; machine is UTC−4, convert!)

Per-deadline sequence (all idempotent, re-run near the deadline):
```
uv run python eval/fetch_fpl_history.py --season 2026-27 --gw 2   # when data_checked; then --combine
uv run python eval/understat_matches.py && uv run python eval/build_understat_aggregates.py ...
uv run python eval/build_crosswalk.py --season 2026-27
uv run python eval/fetch_fixtures.py --season 2026-27 && ... --combine
uv run python eval/merge_live_availability.py --season 2026-27
uv run python eval/build_forward_skeleton.py --season 2026-27     # ALWAYS after any master ingest
uv run python eval/fetch_live_odds.py --season 2026-27            # h2h, 1 credit
uv run python eval/pull_live_props.py --season 2026-27 --gw 3     # 30 credits, T-90..T-30
uv run python eval/build_props_crosswalk.py && uv run python eval/build_props_consensus.py --seasons 2026-27
uv run python eval/run_horizon_minutes.py --season 2026-27 --levers refit --cutoffs 3   # skip-if-exists; delete to refresh
# then: strict preflight + the build
python: ld.build_deadline_frame('2026-27', 3, strict=True, config='combined', horizon=6)
```
GW2 master ingest note: it was still `finished=False, data_checked=False` on
2026-09-01 — the final-gate refused correctly. After ingesting, the skeleton
MUST be rebuilt or `load_stack`'s collision assert fires (by design).

## 10. Credits & accounts

- Paid key (in `.env` since 2026-09-01): **635/20,000 used** (602 GW1-2
  historical props + 3 probe + 30 GW3 live). Steady state ~60-90/gw.
- Old free key spent 6 (h2h probes + live-odds pulls at 1/pull). The paid plan's
  2026-09-24 cancellation: h2h fits free tier ~40x over; props-on-free-tier is
  UNVERIFIED — test one us-region props probe on a free key before deciding.

## 11. Open items / next session candidates

1. **DC term for 2026-27 is an empty cold start** (rolling features are shift(1);
   predictions begin as gws accrue; base rates + postflight note meanwhile).
2. **Reference cells 2266/2264 SUPERSEDED, not re-pointed** (see §3.6). The
   season-totals index still asserts the OLD cells — regenerating the index is
   fine (armlogs untouched); re-pointing is the gated follow-up.
3. GW2 ingest + skeleton rebuild + hmin/crosswalk refresh before Friday.
4. Simulator `load_season` for a LIVE season: prices join per (element, round)
   from the master — forward rows carry value, but the live-sim path itself has
   NOT been exercised (only frame-building has). Test before trusting a live
   transfer decision end to end (the optimizer at one gw is what a deadline
   needs).
5. espnbet/Caesars/ballybet/betparx re-admission iff a published soccer void
   rule is found (quote it in props_feature).
6. Crosswalk MANUAL watchlist (Jackson etc.) — several self-resolve once GW2+
   master rows land; add evidenced MANUAL entries only per the standard.
7. Standing: ANTHROPIC key rotation + server stray-file deletion (user);
   GW2/GW3 scheduled-task cleanup (user); seal state = no holdout (2026-08-27,
   nothing out-of-sample ever again for these seasons).

## 12. Session lessons (cheap to keep, expensive to relearn)

- `| grep -v Warning` SWALLOWS exit codes in `&&` chains — a failed step can
  cascade and even commit. Prefer `2>/dev/null` or check artefacts.
- Runner overrides must PRINT when in force (the unwired `--wf-path` incident:
  a too-clean result — 38/38 identical actions — was the tell).
- Background `uv run` can queue behind foreground uv processes (~30 min once).
- Multi-heredoc Bash commands can trip quoting; use the Write tool for logs.
- Position-appropriate metric comparisons must EXCLUDE goalkeepers explicitly
  (the #21 artefact class).
- pandas: empty list -> DataFrame() has NO columns (guard before groupby);
  int64 can't hold NA (float64 + document); `np.allclose` fails on NaN.
- When a strict finding closes "for free", suspect the check mis-frames the
  model's actual reach (ODDS_HORIZON_GWS=0, step-0-only props hook) — align the
  gate with the code, in the open, rather than relaxing it.
