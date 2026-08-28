# Handoff — sessions of 2026-08-27 → 2026-08-28 (full detail, code-first)

Predecessor: `Handoffs/Handoff_2026-08-26_full_session_detail.md` (commit 2af7d56). Read that first for the
equation, gates, chip conventions and the reference move to 2251/2306/2268. This document covers everything
after it. Nothing here supersedes the master plan's standing rules: **never adopt on season totals; pre-registered
bars may not be amended after seeing numbers; exploratory outputs are labelled as such.**

Machine: Windows 11, local clock = UTC−4 (see memory `fpl-machine-utc-minus-4-deadline-trap`). Python via
`uv` (`C:\Users\veers\.local\bin\uv.exe run python …`) or `.venv/Scripts/python.exe`. Repo at
`c:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot`. `openpyxl` was installed into the venv this session
(`uv pip install openpyxl`). `/mnt/skills` does not exist on this machine.

---

## 0. One-paragraph state of the project

Two correctness fixes were committed (penalty same-season join leak, e04fb72; MIP gap tolerance 0, 37ad782).
Regenerating the reference on the fixed code produced a new **candidate reference `gap0_tc2` = 2343 / 2306 / 2190**
(2023-24 / 2024-25 / 2025-26, chip-inclusive; paths 2301 / 2248 / 2131 incl. TC2). **`EXPECT_REFERENCE_CHIP`
still reads {2251, 2306, 2268} and the index has NOT been regenerated — that is the user's reserved decision.**
Five ideas were tested and all failed or were declined (teammate absence, TC2 refinement, selection-based
calibration, hold preference at near-ties, GK p_cs-side shrink). **The 2025-26 seal was deliberately RELEASED
on 2026-08-27; 2025-26 is now a third tuning season; the project has no holdout.** Exploratory props / horizon /
combined arms now exist on all three seasons (table §6); they are path-lottery results and cannot be cited for
adoption. Ten reconciled Excel files sit in `analysis/`. The D6 GW2 availability poller ran its window on
2026-08-28 (§9). A shadow-mode design for 2026-27 was delivered but not implemented (§10). There is a
substantial pile of **uncommitted work** (§11).

---

## 1. Commits made this session (chronological)

| hash | what |
|---|---|
| e04fb72 | penalty term: prior-season Understat join in BOTH gate states (leak fix) + tests |
| 37ad782 | solver: HiGHS/CBC `gapRel=0.0, gapAbs=0.0` explicit in `optimize._default_solver` + tests |
| 66b98e2 | logs 2026-08-27: idea 5 FAIL, idea 3 FAIL, idea 7 declined-untested, selection calibration FAIL, structural finding, #19 fallback note, seal register |
| 8f619b2 | tests: dormant fingerprint guards repointed to `walkforward_h6_2025_26.parquet`; assert stamps |
| f24bb5a | eval: `leakfix` arm plumbing (runner, index generator, measure script); EXPECT_REFERENCE_CHIP deliberately NOT updated |

Everything after f24bb5a is **uncommitted** (§11).

---

## 2. Correctness fix 1 — penalty same-season leak (e04fb72)

**Finding (read-only pass, 2026-08-27).** `squad/assembly.py::_attach_penalty_share` joined Understat penalty
data for the *same* season as the walk-forward cutoff regardless of the `PENALTY_FIX_ACTIVE` gate. With the
gate off the join still ran, so end-of-season penalty shares leaked into `e_pen_goals` and via that into
`pred_bps` and `e_points` at every cutoff. KNOWN_ISSUES #19 was about the *magnitude* of the term; this was a
separate leak.

**Fix.**
- `squad/assembly.py`: new `_penalty_join_year(season_year) -> season_year - 1`; `_attach_penalty_share(v_full, cw, season)` always joins the prior season; fallback value is gate-dependent and unchanged in magnitude (0.05 with gate off); a warning is emitted for the first season in the data (no prior). Comment block updated.
- `eval/walkforward_season.py`: stamps `result["penalty_join_prior_season"] = True` into the canonical frame's attrs/json sidecar.
- `Tests/test_penalty_fix.py`: +5 tests (join year strictly prior in both gate states; end-to-end leak test asserting no same-season row contributes; first-season edge).
- `eval/run_penalty_fix.py` docstring note; `KNOWN_ISSUES.md` #19 notes (leak closed; fallback characterised).

**Verification.** 2024-25 rebuilt and compared (`Logs/outputs/leakfix_verify_2024_25.txt`): penalty_share
differs on the expected rows only; the term's magnitude/fallback untouched. Canonicals rebuilt for all three
seasons **with** the stamp (`data/walkforward_h6_{2023_24,2024_25,2025_26}.parquet`); pre-fix lineage
preserved as `_preleakfix` files.

**0.05 fallback characterisation (read-only, `Logs/outputs/fallback_characterisation.txt`):** the fallback is
40–90× above realised per-appearance penalty-goal rate; it is harmless only because the term is ~50×
undersized overall (KNOWN_ISSUES #19), so the two errors cancel. No replacement proposed.

---

## 3. What regeneration on the leak-fixed code showed, and the diagnosis that led to fix 2

**Task 2 season re-run (arm `leakfix`, TC2 in-sim):** 2023-24 +75, 2024-25 −16, **2025-26 −89** vs
2251/2306/2268. Stop condition (>~20) tripped; EXPECT not updated.

**Diagnosis (read-only):**
- The simulator is deterministic: pre-fix inputs reproduce 2213 bit-exactly (`diag_q1_*.txt`).
- The −89 is a single near-tie flip at 2025-26 GW5 (runner-up margin 0.0102 → 0.0043 after the leak removal) cascading through the season (`diag_q2_gw5.txt`). Pure leak removal on all rows; swings of +75/−16/−89 sit inside the paired path sd ≈ 85.
- Near-tie investigation (`neartie_sweep*.py`, `neartie_{season}[_postfh].parquet`): ~20% of deadlines are decided by margins < 0.02 objective units between alternative transfer plans. No tie-break principle exists. **HiGHS's default `mip_rel_gap` (1e-4) was returning sub-optimal plans** — demonstrated on 2024-25 GW3 where the returned plan was not the optimum (`gap0_exact_ties.log`, `gap0_resolve_summary.txt`).
- Min-gain-rejection provenance: the 2026-08-11/12 session log; 2025-26 only; not pre-registered.

---

## 4. Correctness fix 2 — solver tolerance (37ad782)

`squad/optimize.py::_default_solver`: `GAP = dict(gapRel=0.0, gapAbs=0.0)` passed to both `HiGHS_CMD` and
`PULP_CBC_CMD` with an explanatory comment. `Tests/test_solver_gap.py` (3 tests: solver kwargs carry zero
gaps; a constructed near-tie MIP returns the true optimum; CBC path identical). 72-deadline re-solve
(`gap0_resolve.py`, `gap0_resolve_{season}.parquet`): **one action changed** (2024-25 GW3, which now equals
the pre-leak-fix run's action); runtime unchanged. `gap0_stability.py` confirms repeat solves are bit-stable.

---

## 5. New reference candidate — arm `gap0` (NOT yet adopted)

Runner arm `gap0` (`eval/run_arms_full_system.py`) asserts the zero-gap solver and stamps `solver_gap_zero`
into the armlog. Run with `--tc2` on all three seasons on the leak-fixed canonicals:

| season | path incl. TC2 | BB1 | BB2 | TC1 read (gw) | chip-inclusive | old reference |
|---|---|---|---|---|---|---|
| 2023-24 | 2301 | 23 | 13 | 6 (GW6) | **2343** | 2251 |
| 2024-25 | 2248 | 16 | 33 | 9 (GW18) | **2306** | 2306 |
| 2025-26 | 2131 | 15 | 28 | 16 (GW17) | **2190** | 2268 |

Armlogs: `data/arms/armlog_{season}_gap0_tc2.parquet`. Chip reads: `data/leakfix_logs/gap0_chip_reads.txt`.
Seal-register row (permitted read, written before launch) covers the 2025-26 read.

**Reserved for the user:** update `EXPECT_REFERENCE_CHIP` in `eval/build_season_totals_index.py` (commit
message must carry old + new), flag 2251/2306/2268 as superseded in the index, regenerate the index, update
closing position + handoff. Do not do this unprompted.

---

## 6. Exploratory arms — three-season table (NOT ADOPTABLE)

All arms run on frames in `data/arms_gap0/walkforward_h6_{season}_{props|hmin|both}.parquet` (built by
`eval/walkforward_arms.py --out-dir data/arms_gap0`), on the leak-fixed canonicals with gap-0 solver. Runner
arms `props_gap0 / hmin_gap0 / both_gap0`; provenance check is bit-exact `penalty_share` vs canonical (the arm
frames lack the `penalty_join_prior_season` stamp). 2024-25 arms start at **GW8** (props coverage) by resuming
from the `gap0_tc2` GW7 state and ran TC2 zero (so a TC2-equivalent captain multiple is added at the rule week
for the chip-inclusive figure); 2025-26 arms start GW1 with TC2 in-sim. Source of record:
`data/leakfix_logs/arms_table.txt` / `.csv` (`arms_table.py`), endpoints `arm_endpoints_*.txt`.

| season | baseline (gap0) | props | horizon (hmin) | combined |
|---|---|---|---|---|
| 2023-24 | 2343 | no cell (no props coverage) | 2425 (+82) | no cell |
| 2024-25 | 2306 | 2328 (+22) | 2335 (+29) | 2459 (+153) |
| 2025-26 | 2190 | 2212 (+22) | 2266 (+76) | 2283 (+93) |

**Why these cannot attribute anything (`decomp_all_cells.txt`, `decomp_cell.py`, `decomp_*.csv`):** in every
cell the arm differs from baseline on 24–35 deadlines, of which only 0–2 are INDEPENDENT decisions (same
state, different choice); the rest are cascade after the first divergence. Independent-decision sums are
−3 to +51. Component decomposition (holdings / bench-XI / captain / hits / residual): bench/XI is the only
component positive in all seven moved cells (+13 to +95); holdings flips sign (−71 to +96). Horizon's +72 on
2023-24 traced to one lucky divergence at GW2 (`hmin_decomp_2023_24.txt`). Both Task-1 and Task-2 conclusions:
path lottery, not decision quality. Season totals disagreed in sign across seasons for props and horizon in the
prior close-out and remain the standing illustration (`Logs/props_season_log.md`, KNOWN_ISSUES #18).

Near-tie diagnostic (Part 3): at near-tie deadlines props/hmin do not discriminate beyond chance; n too small
(`neartie_arms_*.txt`).

---

## 7. Ideas tested and closed this session

| idea | result | record |
|---|---|---|
| Idea 5 teammate-absence conditional rates | FAIL (feasibility; ~50 player-gameweeks falsifier not met) | `Logs/teammate_absence_log.md`, `outputs/idea5_feasibility.txt` |
| Idea 3 TC2 rule refinement | FAIL — refinement never binds on any season | `Logs/p4_chip_policy_log.md` §16 |
| Idea 7 | declined-untested | 66b98e2 log entry |
| Selection-based calibration (passes 1–2) | FAIL — rank falls, spread collapses; **structural finding**: goals-only calibration to realised components is coupled to the bonus deletion (points ratio → 0.93) | `Logs/selection_calibration_prereg.md` §5, `outputs/selcal_pass{1,2}.txt` |
| Hold preference at near-ties (pre-registered) | FAIL by inapplicability: calibration rule gives ε = 0; hold margin is not a near-tie quantity (median 2.45, only 1/68 < 0.05); realised net of transferring +9.05 at zero margin | `Logs/hold_preference_prereg.md` RESULTS; `outputs/hold_sweep_*.txt`, `hold_fit_eps.txt` |
| GK p_cs-side λ-spread shrink (pass 1, read-only) | premise REFUTED on tuning seasons (all step-0 GK rows market-priced); instead a level over-prediction of CS 1.2–1.3× (1.28–1.55× on squad-relevant GKs). **PARKED**, three open design questions recorded | `data/leakfix_logs/gk_pcs_pass1.txt`; seal register PARKED row |
| p_play_any 0.30 floor (#18) | demoted not closed: ≤0.03 e_points/row on decision partitions | seal register row |

**Hold-preference gated implementation is in the tree, OFF, uncommitted** (§11): `simulator.HOLD_PREFERENCE_EPS = None`;
`transfer_mip.build_and_solve(force_hold=…)` adds `used[0] == 0`; `plan[0]["objective"]` now populated always;
per-gw log fields `hold_pref_eps` (−1.0 when off), `hold_applied`, `hold_margin` (NaN when off),
`declined_transfers` (JSON). `Tests/test_hold_preference.py` (2 tests). Runner arm `hold_gap0 --hold-eps`.
**Trap fixed:** `hold_info` must be initialised at the top of each gameweek loop or GW1 raises
`UnboundLocalError`.

---

## 8. Seal register — the important governance change

`Logs/seal_register.md` now records, in order: SEALED (GK p_cs-side, 2026-08-27) → #18 rejected as seal
question → two permitted reads (leak-fix regen; gap0 regen) → INCIDENT (horizon-slices instrument launched
with the season list overridden on the wrong module; stopped; no 2025-26 number produced) → **SEAL RELEASED,
not re-pointed** → CONSEQUENCE (no future claim is out-of-sample on any season; a clean holdout needs 2026-27
as it accrues or a pre-carved partition) → PARKED (GK p_cs level shrink). The last three rows are uncommitted.

---

## 9. D6 availability poller — GW2 window (2026-08-28) and its state right now

Setup (all done the evening of 08-27): scheduled task `FPL availability poller` every 10 min (WakeToRun,
Interactive-only), `poll_availability.bat` now logs `tick start` / `tick exit code` and all stdout/stderr to
`data/live/poller.log`; `eval/poll_availability.py --once` decides for itself whether a poll is DUE
(`NORMAL_CADENCE=1800`, `FINAL_HOUR_CADENCE=600`, window opens at deadline−4h, post-deadline recovery poll).
Post-window automation `eval/d6_postwindow.py` (verify polls → `--build` → fplcache blind-window diff if a
post-deadline snapshot exists → writes `data/live/GW<n>_WINDOW_STATUS.txt`, first line SUCCESS/PARTIAL/FAIL).
Tasks: `FPL D6 GW2 wake` 09:25, `FPL D6 GW2 postwindow` 13:45, `FPL D6 GW2 postwindow (late diff)` 21:00 local.
fplcache clone is repo-local `fplcache/` (gitignored), fallback `C:/Users/veers/fplcache`.

**Observed window (deadline 17:30Z = 13:30 local):** 25 ticks 09:25–13:30, **all exit 0**. Polls stored:
09:30, 10:00, 10:40, 11:10, 11:40, 12:10, 12:30, 12:40, 12:50, 13:10, plus 13:30 post-deadline recovery
(`data/live/bootstrap_raw/2026-27/2026082*T*Z.json.gz`, ~139 KB each, 616→620 elements).
`availability_changes_2026_27.parquet` last written 12:10 (46 changes at 09:30 vs the prior night, 5 at 10:00,
1 at 12:10, none after). Max gap 40 min; 10 pre-deadline polls.

**Bug found (not fixed, reported to user):** the due gate at `eval/poll_availability.py:224`
(`(now - last).total_seconds() >= cadence`) fails by ~1 s because files are stamped at :03 and ticks start at
:02 → the 10:30, 13:00 and 13:20 ticks logged "next poll in 0 min" and skipped. Final hour got 4 polls instead
of 6; last pre-deadline poll was 20 min out. Suggested fix: tolerance (`>= cadence - 30`). Apply before the
next window; do not touch anything during a window without telling the user.

**Still pending at time of writing:** the 13:45 postwindow run and the 21:00 late diff. Check
`data/live/GW2_WINDOW_STATUS.txt` and the tail of `poller.log`. Expect verdict SUCCESS on the gap/count bars
(10 ≥ 8, max gap 40 ≤ 45, post-deadline poll present); the fplcache diff may be PENDING until the clone has a
post-17:30Z snapshot.

---

## 10. Shadow-mode design for 2026-27 (delivered, not implemented)

Read-only reconnaissance findings: `SquadState` is a single mutable object (snapshot/restore/to_dict exist);
`pathcontrol._restored`; chips are schedule arguments and gates are module globals; `main.py` is a FastAPI chat
agent that serves no picks; **no 2026-27 model-input data exists on disk** beyond availability/fplcache
(vaastav, odds, Understat end at 2025-26); XI/bench/vice are not logged per deadline. Per-gw paired sd ≈ 13
from the armlogs → detectable ≈ 6.8 pts/gw at n = 15, 4.3 at n = 38: **15 gameweeks cannot separate two
configs.** Props degrade silently (unpriced rows keep the model). Cost ≈ 3–6 min per deadline for two configs.
Build order if authorised: live ingestion feeds → one-cutoff `live_deadline.py` → two-config runner with a
per-config `ConfigState` (SquadState + chip ledger) → persistence → settlement.

Props pipeline requirements (read-only report): the-odds-api v4 historical, market `player_goal_scorer_anytime`,
regions eu+us, paid plan (price not recorded in repo), coverage from autumn 2024; `PropsHook` needs
`props_consensus_book_{season}.parquet` + `raw/scale/{season}/manifest.csv`. No purchase recommended.

---

## 11. UNCOMMITTED work (git status at handoff time)

```
 M Logs/seal_register.md                (RELEASE / CONSEQUENCE / PARKED rows)
 M eval/measure_arms_full_system.py     (labels for leakfix, gap0)
 M eval/run_arms_full_system.py         (arms gap0, props_gap0, hmin_gap0, both_gap0, hold_gap0 --hold-eps)
 M poll_availability.bat                (logging to data/live/poller.log)
 M squad/simulator.py                   (HOLD_PREFERENCE_EPS gate, hold_info, 4 log fields)
 M squad/transfer_mip.py                (force_hold kwarg, plan[0]["objective"])
?? Logs/hold_preference_prereg.md
?? Logs/outputs/hold_fit_eps.txt, hold_sweep_2023_24.txt, hold_sweep_2024_25.txt
?? Tests/test_hold_preference.py
?? analysis/                            (10 xlsx, §12)
?? eval/d6_postwindow.py
?? "Handoffs/Session handoff modelling extension.docx"   (user's own file — leave alone)
?? this handoff
```
Also untracked/ignored by design: `data/arms/*gap0*`, `data/arms_gap0/`, `data/leakfix_logs/` (scratch scripts
and outputs), `data/live/`. Commit only when the user directs; suggested split: (a) simulator/transfer_mip/test/prereg
hold-preference; (b) runner + measure arms; (c) seal register; (d) poller + d6_postwindow; (e) analysis/.
`poll_availability.bat` will get LF→CRLF on commit (harmless).

---

## 12. `analysis/` Excel files

Ten files `{baseline|props|horizon|combined}_{season}.xlsx`, one sheet each: per-GW rows (XI by position then
bench in bench order), captain yellow / vice blue, doubled points shown "raw (multiplied)", GW totals with
"after hits", transfers listing with "(-4 hit)" on the paid legs, chip rows, reconciliation block that ties
path + BB1 + BB2 + TC1 read (+ TC2 equivalent where the arm ran TC2 zero) to the season figure of record.
**All ten reconcile.** Built by `data/leakfix_logs/reconstruct_cell.py` (deterministic re-solve of every
deadline, asserted against the armlog's transfers/raw_points/hit at each GW; `OPENING_HORIZON_ACTIVE=False`
for the GW1 squad) → `recon_{season}_{stem}.parquet` → `write_xlsx.py` (RECORD/TC1 dicts hard-code the
figures; update them if the reference changes). Confirmed for the user: hits are taken (e.g. 2025-26 combined
GW4 used 2 banked FTs, so no hit that week).

---

## 13. Conventions, traps and lessons (add to the 08-26 list)

- Chip-inclusive = path (incl. TC2 in-sim) + BB1 bench + BB2 bench + TC1 read; when an arm ran TC2 zero, add the captain multiple at the rule week (GW25/24/26).
- Arms that start at GW8 resume from `armlog_{season}_gap0_tc2` GW7 state; reconstruct/decomp scripts stitch the baseline prefix.
- Bash heredocs containing quotes/backticks/`\U` paths break in this harness → write scripts with the Write tool and run them; use forward slashes.
- Season-name forms differ: `2026-27` (dirs, fplcache) vs `2026_27` (parquet stems).
- `measure_horizon_minutes_slices.py` loops over `measure_horizon_minutes.SEASONS` — override `m.base.SEASONS`, not the child module.
- Six parallel sims took 287 min from contention; run sequentially or throttle `FPL_SOLVER_THREADS=2`.
- Passing a truncated `gws` list to `simulate_season` shortens the horizon and changes results — not a gate effect.
- Never print or log `ODDS_API_KEY` (read from `.env`).
- No sims during a poller window.

---

## 14. Open items, in the order they are likely to be asked

1. User's reserved decision on adopting gap0 (2343/2306/2190) as reference (§5).
2. Commit the uncommitted pile (§11) when directed.
3. Read `data/live/GW2_WINDOW_STATUS.txt` after 13:45 / 21:00; fix the 1-second due-gate slip before GW3's window; GW3 deadline must be converted from UTC to local (UTC−4) before scheduling new wake/postwindow tasks.
4. Shadow-mode implementation if authorised (§10 build order).
5. GK p_cs LEVEL shrink remains PARKED with three design questions (seal register).
6. KNOWN_ISSUES #18 demoted, #19 magnitude still gated/not adopted, #20 bonus delete adopted.
