# Cross-season attacking-rate blend (D2 Phase 2) — tuning and pre-registration

**Status: ADOPTED 2026-08-18 — k = 8, `rate_blend_active=True`.** The blend
is the production rate source in `squad/attacking_rates.py`, stamped into
every walk-forward artefact. Adoption rationale in §8; the cold-start gap
remains OPEN (§9). Sections 1–7 are the tuning, pre-registration, sealed
result, integration measurement and sanity simulation, in order.

**Date:** 2026-08-18 · **Script:** `eval/measure_rate_blend.py` (study),
`squad/attacking_rates.py` (production).

---

## 1. The blend

    rate = w * (current season to date) + (1 - w) * (prior season)
    w    = n90 / (n90 + k),   n90 = current-season minutes-to-date / 90

Data: `data/history/understat_matches_<season>.parquet` (D2 Phase 1).
All rates are ratio-of-sums, never means of per-match ratios (the GK
investigation H2 lesson). The study lives entirely in understat-id space —
no crosswalk join occurs, so the KNOWN_ISSUES #3 sweep is not exercised here;
it remains mandatory at integration (`assert_crosswalk_unique()`).

Prior = the player's immediately-previous season, ≥450 minutes (MIN_TIME
precedent). Fallbacks for players without one, point-in-time safe:
tier 1 = position-average prior rate (position = modal current-season position
to date), tier 2 = league-average prior rate (position unknowable, e.g. any
debutant at GW1). GK-group players excluded.

## 2. Protocol (stated before running)

- Walk-forward within season: at gameweek g, inputs use gws < g only.
- Endpoint: realised npxG/90 and xA/90 over gws g..g+2, players with ≥90
  window minutes. MAE + pooled Spearman per (season, stat).
- Tuning on 2023-24 and 2024-25 only. Grid: k ∈ {0.5, 1, 2, 3, 5, 8, 12, 20, 40}.
- **Selection rule (fixed before the sweep ran):** k maximising mean pooled
  Spearman over the four cells (2 seasons × 2 stats); ties → lower mean MAE.

## 3. Tuning results

Evaluation populations: 2023-24 — 8,770 rows, 472 players; 2024-25 — 8,876
rows, 470 players (g 1–36). Rows without a usable player prior: 34.0% and
31.8% (tier 1 position-avg: 2,554 / 2,410; tier 2 league-avg: 430 / 410).

The full curve (pooled Spearman per cell; mean over cells):

| k | 23-24 npxG | 23-24 xA | 24-25 npxG | 24-25 xA | mean ρ | mean MAE |
|---|---|---|---|---|---|---|
| 0.5 | 0.5499 | 0.4634 | 0.5694 | 0.4543 | 0.5093 | 0.1135 |
| 1 | 0.5578 | 0.4724 | 0.5758 | 0.4633 | 0.5173 | 0.1112 |
| 2 | 0.5660 | 0.4829 | 0.5812 | 0.4728 | 0.5258 | 0.1091 |
| 3 | 0.5703 | 0.4890 | 0.5835 | 0.4788 | 0.5304 | 0.1081 |
| 5 | 0.5745 | 0.4955 | 0.5846 | 0.4852 | 0.5350 | 0.1074 |
| **8** | **0.5760** | **0.4988** | **0.5841** | **0.4883** | **0.5368** | **0.1072** |
| 12 | 0.5745 | 0.4985 | 0.5816 | 0.4880 | 0.5357 | 0.1072 |
| 20 | 0.5701 | 0.4933 | 0.5765 | 0.4832 | 0.5308 | 0.1077 |
| 40 | 0.5617 | 0.4813 | 0.5676 | 0.4728 | 0.5209 | 0.1087 |

The curve is smooth and single-peaked; 5–12 is a plateau (mean ρ within
0.002), with 8 the maximum on the pre-stated rule and tied-best MAE. The
choice is the top of a plateau, not a knife-edge — a k of 5 or 12 would be
defensible, which is worth remembering if this is ever re-tuned.

## 4. Production baseline on the same rows

Static season rates from `attacking_rates.get_rates` (pooled 3 prior seasons,
k=2 FWD-npxG / k=10 otherwise, constant all season):

| season | npxG MAE / ρ | xA MAE / ρ |
|---|---|---|
| 2023-24 | 0.1219 / 0.4772 | 0.1019 / 0.4145 |
| 2024-25 | 0.1233 / 0.5014 | 0.1054 / 0.4257 |

The blend at k=8 beats it in all four cells on both metrics (Spearman
+0.075 to +0.099, MAE −0.012 to −0.015). Quirk noted during this study:
`get_rates()` can return the same understat_id twice when a player carried
different position labels across the pooled seasons — duplicates were meaned
for this evaluation and should be looked at before integration.

## 5. PRE-REGISTRATION

**Chosen: k = 8** by the selection rule above, on the tuning seasons only.
2025-26 has not been touched at the time this line is written. It will now be
run once with k = 8 and the result appended below, whatever it shows.

## 6. Sealed 2025-26 result (run once, after §5 was written)

Population: 8,826 evaluation rows, 458 players, g 1-36; 32.1% of rows without
a usable player prior (position-avg 2,468, league-avg 368) -- same shape as
the tuning seasons.

| | npxG MAE / rho | xA MAE / rho |
|---|---|---|
| **blend, k=8** | **0.1108 / 0.5590** | **0.0951 / 0.4378** |
| production baseline | 0.1240 / 0.4613 | 0.1030 / 0.3941 |

The improvement REPLICATES on the sealed season, same direction and similar
size as tuning: Spearman +0.098 (npxG) and +0.044 (xA), MAE -0.013 and
-0.008. k was chosen before this run and not revisited (§5).

Status: measured, replicated, NOT integrated. Integration into
attacking_rates.py is a separate decision; when it happens, (a) run
assert_crosswalk_unique() before any element join (#3), (b) resolve the
duplicate-understat_id quirk in get_rates noted in §4, and (c) the blend
changes the equation's inputs, so stamp it (the #13 lesson).

## 7. Sanity-check simulation -- PROVENANCE REFERENCE ONLY (2026-08-18)

**Season total: 2060** (2025-26, one run, blend active). 37 transfers, 84 hit
points paid, 278 points left on bench. Range check passed: every quantity is
in the normal band for this config family -- nothing pathological.

**This figure identifies what the blend config produced. It is not evidence
about the blend.**

- It is NOT comparable to 2028, 1984, 1940, or any earlier figure -- the
  equation inputs changed between every pair of those runs.
- The M1 gate failed: season totals cannot distinguish a full model from one
  shrunk 75% toward the positional mean, and path noise is sd ~ 60. A
  movement of any size here means nothing.
- **It must never be cited as showing the blend helped or hurt.**

Config stamp for this run:

    source                data/walkforward_h6_2025_26.parquet (built 2026-08-18)
    rate_blend_active     True
    rate_blend_k          8.0
    d1_terms_active       True
    cs_unified            False
    minutes_availability  True
    odds_horizon_gws      0
    dgw_handling          per_fixture
    policy                mip
    H (horizon)           6
    decay                 0.85
    hit_bar               4 (FPL's actual charge, default)
    crosswalk             player_id_crosswalk_final.csv (post-#12 audit,
                          Sheffield fix #14, per-assembly #3 uniqueness guard)

## 8. Adoption rationale (2026-08-18)

1. **Component metrics on the sealed season, pre-registered:** npxG Spearman
   0.461 -> 0.559, xA 0.394 -> 0.438, MAE better on both. k was written into
   this log BEFORE the holdout run (SS5) and never revisited.
2. **k = 8 sits on a plateau** -- 5 through 12 score near-identically (SS3) --
   so the choice is robust to being slightly wrong.
3. **Starter-band Spearman improves for MID in all three seasons and FWD in
   two of three.** GK is untouched at +/-0.001 -- correct by construction:
   goalkeepers carry no attacking rates.
4. **Top-k resolved 8 of 72 cells against a ~3.6 chance rate** -- the first
   measurement this cycle to beat chance. Signs split by season; 2023-24's
   negative lean was investigated and every proposed mechanism ruled out
   (Sheffield bug mechanically impossible -- both comparison files post-fix
   and zero Sheffield players among the picks; prior quality equal, rho 0.838
   vs 0.840/0.856; fallback exposure not the driver -- negativity hits
   prior-carrying players equally; nothing resolves in the finer split).
   Labelled SEASON-LEVEL NOISE.
5. **The large DEF selection churn (37-45% same-#1) is explained, not
   alarming:** defenders' top-10 ladder has the narrowest rungs in the game
   (0.16 pts adjacent gap vs a typical blend-induced change of 0.17), because
   clean sheets are team-level and shared, leaving the small attacking rate
   as the only differentiator between defenders from good teams. The biggest
   movers are GENUINE role re-pricings the pooled static was blind to --
   Lewis-Potter carrying a winger's pooled rate as an FPL defender being the
   clearest (0.464 -> 0.112 npxG/90).
6. **Simulator sanity check clean** (SS7): no structural anomaly.

Also closed by the integration: the duplicate-understat_id defect in
get_rates (282/278/262 players per season sat in two position pools under
the old contains() pooling; root-fixed via one primary position per player),
and the KNOWN_ISSUES #3 sweep now runs on every assembly.

## 9. OPEN -- the cold-start gap

**32-34% of evaluation rows still hit the no-prior fallback**, and for them
the blend contributes nothing beyond a position-average prior: new signings
from abroad, promoted-team players and debutants start on the position mean
and earn their own rate only as n90 accumulates against k=8. Cold start for
those players is UNTOUCHED by this adoption. Any future fix (e.g. cross-league
priors, transfer-fee/market-value priors) is new work with its own tuning
protocol -- and 2025-26 is still the sealed season.
