# Baseline adopted as production; reference cells re-pointed — 2026-09-11

**A judgement call, made after a leak fix invalidated the comparison the earlier choice rested on. NOT a
decision taken on season totals.** Companion records: `Logs/asof_rebuild_log.md` (the fix and the rebuild),
`LEAKAGE.md` (items 6-9 and the guard's residuals), `KNOWN_ISSUES.md` #22 / #23 / #24, `Logs/season_totals_index.md`
(header carries this framing), `config_roles.py` (the one constant that says which config is production).

## 1. The framing

On 2026-08-28 the reference cells were re-pointed to the HORIZON arm and combined (props + horizon) was named
production intent, with an objection recorded: both levers had FAILED their pre-registered component tests
and the adoption cited season totals, which the standing rule forbids.

On 2026-09-10/11 three leaks were found and fixed (KNOWN_ISSUES #22 DC, #23 saves, #24 p60 starter-history),
an as-of reconstruction guard was built, and the record was rebuilt. Post-fix, chip-inclusive:

| | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| reference hmin | 2302 | 2275 | 2227 |
| shadow baseline | 2390 | 2285 | 2249 |
| production both | — | 2335 | 2074 |

**This adoption is NOT taken on those figures.** The grounds are:

1. **Baseline is the only configuration whose adoption never required an objection to be recorded.** Both
   levers failed their pre-registered tests (props: likely starters +0.0094 against the +0.020 bar, four specs;
   horizon lever 1: minutes rank fell on both decision partitions at every step in all three seasons).
2. **The leak fix invalidated the comparison the 2026-08-28 choice rested on.** Production consumed the leaked
   p60 through TWO channels — the step-0 feature and the hmin refit, whose cutoff row went through the same
   starter-history merge — so the horizon lever was measured against a baseline with LESS leak exposure than it
   had itself. The earlier verdicts held "to first order" because both arms carried the same leaked DC term, but
   that symmetry does not extend to p60: baseline carried it once, horizon and combined carried it at step 0 and
   again at steps 1-5.
3. **Rank evidence post-fix is mixed, not decisive**, and is reported as such (asof_rebuild_log §6): baseline's
   top-30 Spearman improved on two of three seasons (+0.0035, +0.0080; −0.0028 in 2023-24); combined's 2025-26
   top 30 fell −0.0172 while its 2024-25 rose +0.0049. One draw each. Likely-starter rank fell 0.005-0.014 in
   every configuration and season — the leaked outcome leaving, not a difference between configurations.
4. **Returning to baseline removes the props dependency entirely** — the paid odds tier, the live board pull
   inside each deadline window, the per-gameweek name crosswalk with its manual entries, the consensus build,
   and the silent degradation to horizon-only when a board is missing.

**The cost, recorded.** Horizon's measured season gains (+82 / +29 / +76 pre-fix, the hmin_gap0 rows against the
gap0_tc2 rows) are given up. Those gains were never attributed to any decision class by the decomposition
(`data/leakfix_logs/decomp_all_cells.txt`: four comparable decisions across three seasons, netting +62 against
+224 of path gain; no mechanism identified). Post-fix the same comparison reads −88 / −10 / −22, which is
reported for completeness and is likewise not evidence (single draws, path sd ~60-85).

## 2. The levers: UNSETTLED, not settled — record, do not act

Both levers' pre-registered verdicts (props: `Logs/props_prereg.md` and `props_conditional_prereg.md`; horizon
minutes: `Logs/horizon_minutes_log.md`) were reached on frames carrying LEAKAGE.md items 6-9. The old FAILs are
not necessarily wrong — the props test measured a goals rate against realised goals and the horizon test measured
minutes against realised minutes, neither of which the leaks touched directly — but the appearance probabilities
the props hook conditioned on (`p_play_any`, built from a p_start that was clean and a 0.30 floor) and the p60
the horizon refit produced were both inside the blast radius, so the frames those verdicts were read on are no
longer clean. They are recorded as UNSETTLED. Any future re-measurement is a NEW pre-registration on the
as-of-rebuilt frames, with its bars stated before a number is read. Nothing was re-measured here.

## 3. What changed

- `eval/build_season_totals_index.py`: `EXPECT_REFERENCE_CHIP` {2425, 2335, 2266} -> **{2390, 2285, 2249}**;
  `REFERENCE_ARM` -> gap0_tc2 for all three seasons; the as-of re-run figures added to `EXPECT_ARMS_CHIP`
  (gap0_tc2 2390/2285/2249, hmin_gap0 2302/2275/2227, both_gap0 2335/2074) alongside the pre-rebuild figures,
  now keyed `*_preasof`; `_preasof` added to the stale-suffix list so every pre-rebuild row is flagged
  SUPERSEDED; the props_gap0 armlogs (not re-run) are read against the `_preasof` frames they were built on so
  their figures of record (2328 / 2221) still reproduce; header, section note, comparison rule 10 and the
  footer carry the framing above.
- `Logs/season_totals_index.md` regenerated (drift assert passed; see section 5 for what changed beyond the
  three cells).
- `config_roles.py` (new): `PRODUCTION_CONFIG = "baseline"`, `SHADOW_CONFIG = None`, `CONFIGS`,
  `LEVER_INPUTS_ACTIVE` — the single source read by the runner, the DB writer and the app.
- `eval/run_live_deadline.py`: the props pull, props crosswalk, props consensus and the hmin delete-and-refit
  run only when `LEVER_INPUTS_ACTIVE`; strict builds, solves and DB rows for `CONFIGS` only; the Jackson
  props-mapping check and the config-disagreement section degrade to explicit "not applicable" notes.
- `model_tools.py` / `db_write.py` / `agent.py`: every `'combined'` literal replaced by
  `config_roles.PRODUCTION_CONFIG`; the shadow read returns an explicit error when no shadow is configured;
  `/health` reports model versions for `CONFIGS`; the on-demand optimiser reads
  `data/live/_tmp_frame_baseline.parquet`.
- `squad/live_deadline.py`: header states the roles; `--config combined` still builds (the parity and as-of
  tests keep it pinned).

## 4. Configuration roles in the closing position

**Production = baseline.** Every user-facing read, the deadline solve and the on-demand optimiser use it.

**Shadow: none.** The honest answer is that there is no longer a reason to run one. The shadow comparison never
had statistical power (index header: paired per-gameweek sd ~13, detectable difference 6.8 pts/gw at n = 15 and
4.3 at n = 38, against historical config differences of 0 to +4 pts/gw), a live 2026-27 track record cannot
settle either lever (n too small; totals are forbidden as evidence anyway), and the shadow's inputs are exactly
the paid and weekly steps production no longer needs. If either lever is re-opened by a new pre-registration and
passes, `config_roles.SHADOW_CONFIG = "combined"` re-enables the full combined path in one line — the code,
the fetchers, the tests and the record parity all stay.

**Turned OFF, kept, not deleted** (all behind `LEVER_INPUTS_ACTIVE`): the live props pull (30-60 paid credits
per gameweek at 3 per fixture across eu/us/us2), the per-gameweek props crosswalk (the manual-entry surface:
162 and 57 manual entries historically, ~150 unmatched rows per season) and consensus build, and the hmin
delete-and-refit (~6 minutes of compute per deadline plus the weekly delete-and-refit that skip-if-exists
required). What it saves per deadline: four subprocess steps, the paid-tier credit spend, one strict raise
surface (props coverage < 80%), and the silent horizon-only degradation mode. What it does NOT change: the
availability merge, the live h2h odds pull, the strict build, the solve, the DB write, `/health`.

**The server.** The scheduler's per-deadline sequence is `eval/run_live_deadline.py`, invoked by
`eval/deadline_dispatcher.py` from host cron (docker-compose `fpl-scheduler`); it now runs
merge_live_availability -> fetch_live_odds -> strict build (baseline) -> solve -> Postgres. No cron or
compose change is needed; the gating is in the runner. `live_deadline.build_deadline_frame` defaults to
baseline as before. Both configs may still be built by hand with `--config`.

## 5. The odds subscription

h2h match odds are still needed (the step-0 market lambda) and fit the free tier ~40x over (~2 pulls per
gameweek ≈ 80 credits per season against 500 per month; `Logs/live_odds_log.md`). Props were the paid tier's
only consumer. **The 2026-09-24 cancellation can be allowed to lapse.** Two caveats from the odds log: the key in
`.env` reads as a free-tier key (497 -> 496 credits across a session), so it may already be the free key and the
lapse changes nothing operationally; and if props are ever re-opened the paid tier is a prerequisite again.

## 6. Verification

- Index: drift assert passed on regeneration (every `EXPECT_ARMS_CHIP` figure, the three new reference cells,
  the fslog 2296/2294/2206 and the p1 2204/2362/2032 reproduced).
- Suite: green (see the commit).
- Live: `squad/live_deadline.py --season 2026-27 --gw 3 --strict --config baseline --horizon 6` builds with
  notes only (GW3 is the last deadline with full inputs; GW4 needs no props board any more).

## 7. What changed in the index beyond the three cells

See the commit and section 3: the header framing; eleven new SUPERSEDED `_preasof` rows (the pre-rebuild
gap0_tc2 / hmin_gap0 / both_gap0 armlogs for every season); the re-run gap0_tc2 / hmin_gap0 / both_gap0 rows
with their new figures and flags; the props_gap0 rows re-flagged (not re-run, read against `_preasof` frames);
the fslog base_wc2 and bonusdel_tc2 flag text now points at the baseline cells; the arms section title and
note; comparison rule 10; the footer's MOVED entry; the walkforward-provenance key gains the `_preasof` frames.
