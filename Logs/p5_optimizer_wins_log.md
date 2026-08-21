# P5 — the two small optimizer wins (measured 2026-08-21, NOT ADOPTED)

Interim plan §4 P5. Both pieces built, gated, measured under the FULL adopted
system, and left OFF: `scoring.BENCH_ORDER_BY_PLAY = False`,
`optimize.XI_TIEBREAK_P60 = False`. Stamped per decision-log row
(`bench_order_by_play`, `xi_tiebreak_p60`), the D1_TERMS_ACTIVE pattern.

**Config:** the full-system reference cell — base opening, WC1@GW2 (the
better-supported end of the revised GW2–3 rule), WC2 {32,31,32}, FH2
{29,29,34}, BB1+BB2 bench-aware ({7,7,10}/{34,33,33}), H=6 d=0.45.
Reference run REUSED (`fslog_{tag}_base_wc2`); 9 new sims (bench / xi /
both × 3 seasons). Suite green with gates off (113+5s) — the plumbing
(p_play_any / p_60plus through gw_slice → pools → get_team/plan_to_team,
blank-week rows at explicit 0.0) is inert when the gates are off, confirmed
by the prefix results below against the PRE-plumbing reference run.

**Piece 1 — bench order by p_play_any** (autosubs fire only for players who
played; e_points ranks bench players at Spearman +0.067 vs p_play_any
+0.383 — the +2 result of Logs/wildcard_and_determinism.md).
**Piece 2 — XI tiebreak by p_60plus**, ε = 0.05 objective weight on start
variables: a player displaces an XI rival only if his e_points deficit is
< 0.05×Δp_60plus ≤ 0.05 pts. Threshold rationale: step-0 MAE ~1.07
aggregate / ~2.4 starter band → 0.05 is 2–5% of noise; ~5e4× solver
tolerance so the everywhere-ties break deterministically.

## Determinism (asserted, not assumed)

Squad paths were IDENTICAL to the reference in ALL NINE runs — the bench
arm by construction (asserted; bench order cannot feed back), and the xi
arms because ε never flipped a pick decision, only XI splits. Every delta
below is therefore a noise-free paired difference on an identical squad
path (the cleanest measurement class this project has). First points
divergence: bench arms GW34/27/33 (the first differently-resolved autosub —
twice the BB week, where the loaded bench offers real alternatives); xi
arms GW7/33/10 (the first flipped near-tie).

## Results (path deltas vs reference; chip-inclusive adds BB/TC reads)

| season | ref path | bench Δ | xi Δ | both Δ | additive? |
|---|---|---|---|---|---|
| 2023-24 | 2278 | −7 | −7 | −7 | overlapping (not −14) |
| 2024-25 | 2255 | −7 | −12 | −19 | exactly additive |
| 2025-26 | 2156 | −4 | +3 | −2 | ≈ additive |

- **Autosubs:** fired counts unchanged in every arm (11/18/8). Sub points
  gained: bench ordering RESOLVED subs worse where it differed at all
  (2024-25: 42→35; 2025-26: 29→27; 2023-24: equal until the BB week).
  **The historical +2 does not replicate** — measured −4..−7/season here.
  Mechanism: p_play_any promotes likely-to-play-but-low-scoring bodies
  ahead of slightly-less-likely but higher-scoring ones; when both would
  have played (the common case), e_points order collects more. The +2 was
  one draw on the pre-M3 H=3/d=0.3 no-chip 2025-26 config; this is three
  seasons, full system, noise-free pairing — and the sign flips.
- **Dead-XI slots:** 0/4/2 per season, UNCHANGED by every arm — neither
  piece touches the dead-bench failure mode.
- **Bench points left:** rises slightly under bench ordering (303→310,
  284→291, 430→434) — the reordering leaves more points unsubbed, the same
  story as the sub-points line.
- **XI tiebreak:** −7/−12/+3 — preferring the likelier finisher among
  near-ties does not pay; the e_points argmax was already doing the work
  (echoes the captaincy result: no alternative beats argmax e_points).
  Chip-inclusive it is a wash (the BB week reads absorb the differences).
- **vs the average manager (chip-inclusive):** ref +296/+293/+324; bench
  +296/+286/+319; xi +296/+293/+324; both +296/+286/+319.
- Replay fidelity for the autosub accounting: 36–38/38 per column per arm;
  the mismatch weeks are the BB weeks, where bench weight 1.0 makes the
  solver's XI split degenerate (stated; sub counts matched 37–38/38).

## Verdict

Both pieces measure zero-to-slightly-negative under the adopted full
system, on noise-free paired paths: bench ordering −4..−7, XI tiebreak
−12..+3, combined −2..−19. **NOT adopted; both gates rest False.** The
prior +2 for bench ordering is superseded by this cleaner, broader
measurement. The optimizer-has-converged conclusion of
wildcard_and_determinism.md stands: the binding constraint is prediction
quality, not selection mechanics.

## Files

- `squad/scoring.py` (BENCH_ORDER_BY_PLAY + assign_bench_order),
  `squad/optimize.py` (XI_TIEBREAK_P60/WEIGHT + objective + get_team),
  `squad/transfer_mip.py` (tiebreak term + plan_to_team),
  `squad/simulator.py` (column plumbing + stamps)
- `eval/run_p5.py`, `eval/measure_p5.py`;
  `data/p1/p5log_{season}_{bench,xi,both}.parquet` (gitignored)
