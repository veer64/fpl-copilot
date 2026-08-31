# Steps-1-5 minutes substitution extracted; live horizon-6 frames — 2026-08-31

Task: make the combined arm's steps-1-5 horizon-minutes substitution importable and
extend the live path to full horizon-6 builds. DC untouched (#21 stands). No live
odds pulling.

## 1. The closure, traced

The substitution itself is `minutes_frames(m_k, k, targets, hmin)` — module-level in
`eval/walkforward_arms.py` all along (steps ≥ 1 take the per-step refit's
p_start/p60/e_minutes where `hmin` has a row for (cutoff, horizon_step, element);
elements without a refit row keep the stale step-0 copy, counted; step 0 is always the
canonical minutes frame). But it was unusable outside `main()` because the frame it
builds could only enter the equation through the `assemble(mins, hook)` closure in
`main()`'s per-cutoff loop, which captured FOURTEEN enclosing-scope names:
`k, targets, season, dc_enabled` (loop/config state) and
`df, cw, rates, priors, f_k, dc_k, bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean`
(the per-cutoff components). That capture is why it was not importable.

## 2. The extraction (no behaviour change)

Three module-level functions in `eval/walkforward_arms.py`, the closure's captures now
explicit signatures:

- `cutoff_components(season, k, targets, tr, gw_start, gw_end, all_gws)` — the five
  per-cutoff getters (rates, minutes, bonus, DC fixtures, DC hits), computed ONCE per
  cutoff, verbatim from the loop body.
- `assemble_cutoff(comp, df, cw, mins, k, targets, season, dc_enabled, hook=None)` —
  the lifted `assemble` closure: same `assembly.PROPS_HOOK` module gate, same finally
  restore, same `f_k.copy()`, same cutoff/horizon_step stamping.
- `stamp_arm_frame(res, season, tr, arm, dc_enabled)` — the provenance stamp block,
  so a live frame is stamped IDENTICALLY to the record files.

`walkforward_arms.main` now calls these three (plus `minutes_frames`) — the old inline
code is GONE, not duplicated. `squad/live_deadline.py`'s combined config calls the SAME
four functions at every horizon (baseline stays on `walk_forward`, the canonical
builder — which is itself the horizon-6 implementation for the no-substitution path).
No second implementation exists anywhere.

## 3. Extraction parity — first deliverable

Full 2025-26 arm rebuild (`--arms both`, all 38 cutoffs) through the extracted
functions, compared to the record `data/arms_gap0/walkforward_h6_2025_26_both.parquet`
over every cutoff, every step, every common column, equal NaN placement:

**BIT-IDENTICAL: 165,401 rows in both, 38 cutoffs x steps 0-5, 46 numeric + 20
non-numeric columns, max |Delta| exactly 0.0, equal NaN placement.** The column
sets were EQUAL (the `penalty_join_prior_season` tolerance turned out unneeded --
the arm record already carries it). Sidecar counters identical to the record:
props overridden 15,580 / partial doubles 22 / GK skipped 0; hmin refit rows
134,365 / stale fallback 0. The in-run no-hook repro: max |Delta e_points|
0.00e+00 over all 38 cutoffs, 0 row differences. 16.5 min.

Test
`test_extraction_reproduces_arm_record_full_cutoff` pins a full six-step cutoff (GW5)
against the record so any future divergence of the extracted path fails the suite.

## 4. Live horizon-6 — second deliverable

`build_deadline_frame(..., horizon=6)` / CLI `--horizon 6`. 2025-26 GW20, per step:

| step | gw | baseline vs canonical | combined vs arm record |
|---|---|---|---|
| 0 | 20 | BIT-IDENTICAL (790 rows) | BIT-IDENTICAL (790 rows) |
| 1 | 21 | BIT-IDENTICAL (795 rows) | BIT-IDENTICAL (795 rows) |
| 2 | 22 | BIT-IDENTICAL (799 rows) | BIT-IDENTICAL (799 rows) |
| 3 | 23 | BIT-IDENTICAL (803 rows) | BIT-IDENTICAL (803 rows) |
| 4 | 24 | BIT-IDENTICAL (811 rows) | BIT-IDENTICAL (811 rows) |
| 5 | 25 | BIT-IDENTICAL (817 rows) | BIT-IDENTICAL (817 rows) |

Max |Δ| exactly 0.0 and equal NaN placement in all twelve cells (46 numeric + 16/20
non-numeric columns per cell). Step 0 was already proven; steps 1-5 are the new claim.
The three-cutoff step-0 parity (GW5/20/33 incl. the DGW, both configs) re-run after
all changes: **PARITY: PASS** twice — unchanged and green, even though the combined
config now routes through the extracted pipeline (which the arm sidecar had already
proven reproduces `walk_forward` at max |Δ| exactly 0 over all 38 cutoffs).

## 5. What steps 1-5 need that step 0 does not (state for 2026-27)

- **The horizon skeleton — MISSING and silently degrading.** Targets derive from the
  master's own gameweeks (`targets = [g for g in all_gws if k <= g < k+H]`), and the
  FPL-API master gains a gameweek only after it is PLAYED. A 2026-27 horizon-6 build
  today would silently produce a 1-step frame — no error, just fewer steps. No current
  ingester builds future-gameweek skeleton rows. Now a strict finding (preflight) AND
  an observed truncation check (postflight).
- **Future fixtures across the horizon window — PRESENT** (the fixture universe holds
  all 380), but **unpriced**: every steps-1-5 lambda would be pure DC. The
  all-unpriced check now also covers the steps-1+ window.
- **The hmin refit file — MISSING for 2026-27** (`hmin_2026_27_refit.parquet` does not
  exist; the stored refits are backtest artefacts per season). Without it, steps 1-5
  silently keep the stale step-0 copy while the frame is stamped
  `horizon_minutes_active=True`. Now a strict finding (file missing, and
  file-present-but-no-rows-for-this-cutoff).
- **Props coverage per target gameweek** (combined): the coverage floor now checks
  every target gw, not just the deadline gw.
- **Forward-looking availability — NOT needed.** Steps 1-5 reuse the step-0 minutes
  frame (stale copy or refit substitution); availability enters the model only at the
  cutoff, through step-0 minutes. Nothing new required, by design.
- **DC hits for future gws** — cutoff-frozen per-player model over targets; for
  2026-27 held under #21 regardless.

## 6. Strict mode additions

Preflight (`horizon > 1`): master rows for every target gameweek (else SILENTLY
DROPPED steps); hmin refit file exists and covers the cutoff (combined); odds fixture
rows and the all-unpriced-window check across the steps-1+ kickoff window; props
coverage per target gw (combined). Postflight (`horizon > 1`): the frame's realised
steps must equal the expected range — the truncation OBSERVED, not just inferred.

## 7. Strict preflight, 2026-27 GW1 horizon-6 combined (reported, not fixed)

1. props per-book consensus missing (`props_consensus_book_2026-27.parquet`)
2. horizon-minutes refit file missing (`hmin_2026_27_refit.parquet`) — steps 1-5
   would silently keep the stale step-0 copy, lever OFF in fact while stamped ON
3. `DC_SEASONS` hold — #21
4. `DC_RULE_SEASONS` hold — #21
5. odds PRICES missing for ALL 10 GW1 fixtures — pure DC; live odds is a separate job
6. horizon-6: master has NO rows for target gameweeks [2, 3, 4, 5, 6] — the 6-step
   frame would quietly become 1-step; no current ingester builds future-gameweek
   skeleton rows

## Tests (suite 211)

- `test_extraction_reproduces_arm_record_full_cutoff` — extraction parity, GW5, six steps
- `test_live_horizon6_baseline_all_steps` / `test_live_horizon6_combined_all_steps` —
  GW20, six steps each, hard-findings empty
- the nine existing live_deadline tests, including the step-0 parity pair — unchanged, green
