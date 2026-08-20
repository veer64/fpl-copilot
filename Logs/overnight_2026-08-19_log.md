# Overnight run — 2026-08-19: DC-wiring fix, D4 Phase 2 re-run, transfer sweep

Four sequential stages, each verified before the next. Written incrementally
so partial results survive an interrupted run.

| Stage | Task | Status |
|---|---|---|
| 1 | Defensive-contribution wiring fix + canonical rebuild | IN PROGRESS |
| 2 | D4 Phase 2 re-run on fixed files | pending |
| 3 | Transfer sweep H×decay×synth, path-free endpoints | pending |
| 4 | Season totals (sanity framing only) | pending |

## Stage 1 — the defect

`walkforward_season.py` passes an EMPTY p_dc_hit frame for every season,
including 2025-26 where dc_rule_active=True, so assembly's fallback chain
lands every player on the POSITION BASE RATE (DC_BASE, max 0.136 = MID).
`walkforward.py` wires `defensive.get_dc_2526()` (per-player model, max
~0.80). The canonical lineage is walkforward_season (rebuild_rateblend.ps1),
so every canonical file priced defensive contribution at position base rates.

Fix: one shared path — `defensive.get_dc_hits(season, cutoff_gw, targets)`
(module-cached, returns the cutoff-gw per-player row frozen across the
horizon; empty-but-typed for pre-rule seasons) — called by BOTH writers.

(stage results appended below as they land)

## Interruption record

The machine slept ~01:20 on 2026-08-19 and the session process died. The
detached stage-1 build survived long enough to finish 2025-26 (10.8 min) and
2024-25 (9.2 min); 2023-24 died at cutoff GW31 with NOTHING written (the
writer saves only on completion — old canonical intact). Stages 2–4 had not
launched (gated on verification). Resumed 21:38: 2023-24 relaunched.

## Stage 1 — verification (2 of 3 seasons, 2023-24 pending)

- **2025-26**: p_dc_hit max 0.136 (4 distinct) → **0.798 (7,913 distinct)**.
  Step-0 aggregate ρ 0.7481 → 0.7471, MAE 1.0731 → 1.0732 (flat). Starter-band
  ρ: DEF 0.265 → **0.285**, MID 0.193 → **0.214**, GK 0.190 → 0.190
  (untouched — GK base rate is 0, the expected structural signature),
  FWD 0.162 → 0.157. Nothing implausible; DEF/MID improving is the direction
  a real per-player DC signal should produce. **PASS.**
- **2024-25**: bit-identical to _dcbase (step-0 max |e_points diff| 0.0e+00) —
  the shared-path refactor changes nothing for pre-rule seasons. **PASS.**
- Stale-figure consequence (trap 3): every log quoting canonical 2025-26
  numbers built 2026-08-14..18 now quotes superseded values (agg ρ 0.7481,
  DEF/MID starter ρ, β tables). KNOWN_ISSUES #15 records the contamination
  surface; in-place corrections are queued as morning work, not done blind
  overnight.

## Stage 1 — CLOSED (final gate)

Test suite 107 passed, 5 skipped (the two new #15 guards pass). 2023-24
canonical rebuild relaunched (cosmetic — bit-identity proven on 2024-25).

## Stage 2 — COMPLETE: Phase 2 verdict RE-CHECKED on fixed files, unchanged

2025-26 synth rebuilt on the fixed base (19.8 min). Measurement
(scratchpad measure_phase2_fixed.txt): stamps match ×3, step-0 BIT-EXACT ×3.
The D4 Phase 2 verdict is CONFIRMED with defensive contribution properly
priced, not flat-rated:

- aggregate ρ steps 1–5: −0.0007..−0.0011 (all rows); MAE better at every
  step in 2025-26 (−0.002..−0.003), flat elsewhere.
- top-k resolution: 3/120, 6/120, 2/120 vs ~6 chance/season — nothing.
- margin β: MID/FWD toward 1 and GK/DEF away at every step, every season —
  the same 60/60 directional structure as the pre-fix measurement.
- starter-band ρ 2025-26: DEF up at every step (e.g. step 3 0.235→0.250),
  GK down at steps 1–4 — same shape as pre-fix.

Synthetic λ remains NOT adopted; gate stays False on disk.

## Stage 1 addendum — new post-fix 2025-26 step-0 baseline (canonical)

agg ρ 0.7471 / MAE 1.0732 (was 0.7481 / 1.0731 flat-rated); starter-band ρ
GK 0.190, DEF 0.285, MID 0.214, FWD 0.157. Logs quoting the old values are
superseded (KNOWN_ISSUES #15).

## Stage 3 — COMPLETE: 54/54 sims, zero failures. Path-free endpoints

Full tables: scratchpad sweep_endpoints.txt; per-transfer table (2,967
transfers) at data/sweep/transfer_table.parquet; per-config decision logs at
data/sweep/simlog_*.parquet.

**E1 — corr(predicted gain, realized gain):** positive in ALL 54 configs
(Pearson 0.05–0.48). Pooled over 2,967 transfers: Pearson 0.282 / Spearman
0.269. The MIP's predicted margins carry genuine signal. Pooled by variant:
base 0.301 vs synth 0.264 — synthetic λ slightly WORSE, consistent with the
Phase 2 verdict.

**E2 — realized gain per transfer (H-window, undecayed):** mean +4.3 to
+10.4 per transfer, 60–84% positive, in every config. Longer H → larger mean
gain but deeper left tail (p10 to −23 at H=6) and 14–23% truncated windows.

**E3 — activity:** transfers 44–72, hit points 24–136. Decay 0.6 buys more
hits in 2023-24 (92→116→136 across H at d60); milder elsewhere.

**E4 — declined transfers (fixed 3-gw yardstick), vs taken on the SAME
yardstick:** taken beats declined in all three seasons — 6.99 vs ~5.9
(2023-24), 5.20 vs 4.73 (2024-25), 6.49 vs 5.31 (2025-26). Two readings:
the selection among candidates carries real skill (+0.5..+1.2/3gw), AND the
declined pool is still strongly positive (~+5/3gw) — the option set is deep;
aggressive configs are not harvesting junk.

No H or decay wins on these endpoints with any consistency across seasons;
differences between grid cells are small against per-transfer spread.

## Stage 4 — season totals (SANITY FRAMING ONLY)

Recorded in sweep_endpoints.txt with the mandatory framing: they identify
configs, are NOT evidence (M1 failed, path sd ~60), are NOT comparable to
2060/2028/1984 (equation inputs changed, #15), and no winner is picked.
Ranges: 2023-24 1975–2228, 2024-25 2243–2415, 2025-26 1929–2102. Nothing
pathological.

## Run status: ALL FOUR STAGES COMPLETE (2026-08-20)
