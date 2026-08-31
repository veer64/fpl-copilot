# Pre-registration: DC source swap (core-insights -> FPL-official counts) — 2026-08-31

Written and committed BEFORE any experiment number was computed. No bar below may be
amended after a number is seen. If a bar is missed the result is recorded as FAIL and
the work STOPS — no variants, no partial swap, no re-weighting of the two sources.

## Why (KNOWN_ISSUES #21, on record since 2026-08-31)

The DC term trains on core-insights counts. The FPL API exposes
`defensive_contribution` natively and disagrees: 87.25% exact agreement on 2025-26
GW20 (298 joined rows), 93.55% on 2026-27 GW1 (310 played rows). Disagreements are
ONE-SIGNED — core-insights always counts more, by +4 to +22; tackles and CBI match
the API exactly, so the excess sits in recoveries/clearances. On 2026-27 GW1, 7
players flipped >=10 and 4 flipped >=12. FPL awards the points: where the sources
disagree, FPL is definitionally right and the model prices returns that cannot
occur. Because the swap changes ~13% of training labels AND the rolling features
built from the same counts, it is a MODEL change, not an ingestion change — hence
this pre-registration. (Also on record: core-insights nulled `tackles` in 2026-27;
`tackles_won` carries the data and matches the API — the fetcher's evidenced
column_map covers it. Irrelevant to this test, which is 2025-26.)

## Tuning status — no holdout

Tuning seasons 2023-24 / 2024-25 / 2025-26. The seal register (2026-08-27) records:
the GK p_cs seal was RELEASED, not re-pointed; "From this date 2025-26 is a third
tuning season. The project has no holdout." and "No result from this date forward
can be described as out-of-sample on any season." NOTHING in this test is
out-of-sample. This is a three-season tuning result.

## SCOPE, stated before running (task item 4)

FPL-official per-match counts exist ONLY for 2025-26 among the tuning seasons:

- The DC rule was introduced in 2025-26. vaastav/the FPL API carry
  `defensive_contribution` from 2025-26 onward.
- Verified in the stack before this document (schema/existence check, not a result):
  `defensive_contribution` is 100.0% populated on played 2025-26 rows and **0.0%
  populated for 2023-24 and 2024-25** (columns exist, values do not).

Independently, the swap is STRUCTURALLY INERT for 2023-24 / 2024-25:
`defensive.DC_RULE_SEASONS == {"2025-26"}` returns the empty frame before any
source is read, `dc_enabled` zeroes the term in the equation for pre-rule seasons,
and `defensive.SEASON` builds features for 2025-26 only. Pre == post for those two
seasons BY CONSTRUCTION.

**Therefore the substantive test is 2025-26 ALONE.** That limitation is stated here,
up front, rather than worked around. 2023-24 / 2024-25 rows in the bar tables will
be reported as "structurally inert (pre == post by construction)" — not as passes
earned by the swap.

## The swap, specified

A module gate in `squad/defensive.py`: `DC_SOURCE = "core_insights"` (DEFAULT — the
current behaviour, bit-identical) | `"fpl_official"`. Same specification, same
features, same hyperparameters, same walk-forward retraining, same FWD flat rate,
same thresholds (CBIT >= 10 DEF, CBIRT >= 12 MID/FWD). ONLY the source of the
counts changes:

- `fpl_official` builds the per-player-match rows from the season stack
  (vaastav-shaped, per (player, GW, fixture)): `dc_metric` = the NATIVE
  `defensive_contribution` column — the awarded count itself, not a reconstruction
  from components, because FPL being definitionally right is the entire premise;
  minutes = stack `minutes`; position = stack position mapped
  DEF/MID/FWD -> Defender/Midfielder/Forward (GK excluded in both pipelines — the
  model never predicts goalkeepers). Player id: stack `element` == core-insights
  `player_id` (the join the fetcher's cross-check already uses).
- Rolling features (`roll_dc90_3c/5c`, `roll_hit_5`, `roll_mins_3`) computed by the
  SAME code from the official metric/minutes.
- `_DC_HITS_CACHE` is keyed by source for in-process hygiene of this test only. The
  season-less cache-key defect remains an ADOPTION-time fix (with any
  DC_SEASONS / DC_RULE_SEASONS change), exactly as #21 records.

## PRE-REGISTERED BARS (all must hold; none may be amended after a number)

**Bar 1 — rank must not fall.** Step-0 rows (horizon_step == 0). Partitions:
(a) likely starters, `p_start >= 0.75`; (b) squad-relevant, top 30 by `e_points`
within gameweek. Metric: Spearman(e_points, actual GW total points from the stack,
summed per (element, gw)) computed per gameweek, averaged over gameweeks. Configs:
baseline (canonical `walkforward_h6_2025_26.parquet` convention) and combined (the
`arms_gap0` both-arm convention) — pre = the existing record frames; post = the
same builders re-run with `DC_SOURCE="fpl_official"`. BAR: post mean Spearman >=
pre mean Spearman **at 4 decimal places, on every (partition x config) cell for
2025-26**, with 2023-24 / 2024-25 reported as structurally inert. Report pre and
post per partition per season per config.

**Bar 2 — DC calibration must IMPROVE on FPL-official counts.** Ground truth: the
official `dc_hit` (native count vs the position threshold) from the stack. Join:
(player, gw); player-gws with more than one match on either source are EXCLUDED and
counted (per-match alignment inside a DGW is not identifiable). Evaluated on the
INTERSECTION of the pre and post predicted row sets (sizes reported). Families:
DEF = P(CBIT >= 10), MID = P(CBIRT >= 12) — the modelled positions. FWD is
reported for completeness but is NOT a bar (flat constant on both sides; nothing
can improve by construction). BAR: Brier_post < Brier_pre STRICTLY, for BOTH the
DEF and MID families. Reliability summary reported (not a separate bar): 10
equal-width probability bins, predicted mean vs observed rate per bin, and ECE
(count-weighted mean |gap|), pre and post.

**Bar 3 — season totals are NOT a bar.** Reported for all three seasons, both
configs, labelled ILLUSTRATION ONLY, and MAY NOT be cited in the verdict. The
standing rule holds: paired path sd ~85; one near-tie flip has been shown to move
a season by +/-90. 2023-24 / 2024-25: the record values (inert). 2025-26: pre =
the record armlogs (`armlog_2025_26_gap0_tc2` shadow, `armlog_2025_26_hmin_gap0_tc2`
reference; if a needed pre armlog for the both-config is absent, a fresh pre run
on the EXISTING unswapped frame is made with the same runner — decided by file
existence, checked after this document is committed); post = the same runner,
same convention (gap0, opening base, WC1@2, chip weeks of record, TC2 in-sim
@GW26), on the swapped frames.

## Also reported (item 7, operationalised now)

- Label flips, full 2025-26: player-matches whose official vs core-insights metric
  sits on opposite sides of 10 (DEF) / 12 (MID/FWD), per direction.
- Prediction flips: rows on the evaluation intersection where `p_dc_hit >= 0.5`
  differs pre vs post, per direction.
- Row/threshold counts for how many of the model's predicted-hit calls change.

## Verdict rule

PASS iff Bar 1 holds on every cell AND Bar 2 holds on both families. Anything
else is a FAIL, recorded, full stop. Season totals do not enter the verdict in
either direction. If it clears: STOP — adoption, any DC_SEASONS /
DC_RULE_SEASONS change, and the `_DC_HITS_CACHE` season-key fix are a separate
commit and a separate decision.

## Parity requirement (item 10)

With the gate at its default (`core_insights`), the existing 2025-26 parity suite
must still pass bit-identically for both configs after the code change — proven
before any experiment runs, and the suite pins the default.

## Run plan (est. cost)

1. Implement the gate; run the parity suite (swap OFF). ~10 min.
2. Build official counts + label-flip table (item 7 label half). ~minutes.
3. Retrain DC on official counts; bar-2 Brier/reliability pre & post. ~minutes.
4. Rebuild the two 2025-26 frames swapped (38 cutoffs each). ~35 min.
5. Bar-1 Spearman tables pre & post. ~minutes.
6. Season-total runs on the swapped frames (2 configs, TC2 in-sim). ~1-2 h.
7. Report; verdict; log. Whatever the verdict, the gate stays defaulted to
   core_insights.
