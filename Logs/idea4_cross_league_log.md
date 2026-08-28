# Idea 4 — cross-league priors: read-only feasibility (2026-08-28) — DECLINED ON EXPECTED VALUE, NOT A FEASIBILITY FAIL

Read-only. All three seasons (2025-26 is a tuning season since the seal release of 2026-08-27 — nothing here is
out-of-sample). Nothing downloaded, nothing built, nothing fitted. Outputs of record:
`Logs/outputs/idea4_feasibility.txt`; manual origin labels `Logs/outputs/idea4_origin_labels.csv`. Origin:
`Logs/headroom_diagnosis.md` §4 idea 4. Category: **declined on expected value** (the idea 7 category), not
a measurement fail (the idea 3 / idea 5 category).

## Premise

Players arriving from other leagues have no prior-season EPL Understat record, so the k = 8 rate blend falls
back to the within-position prior (`attacking_rates._blended_rates` tier 1; `assembly` position fallback for
elements with no Understat id at all). A striker signed from the Bundesliga and a squad filler get the same
number. Understat covers six leagues; the repo holds EPL only.

## Pre-registered falsifier (stated before any number) — CLEARED

If players lacking a prior-season EPL record are under 5% of squad-relevant rows (top 30 by e_points within
gameweek, step 0) across all three seasons, the idea is dead. Not amended after the result.

| season | squad-relevant rows | rows lacking an EPL prior | share |
|---|---|---|---|
| 2023-24 | 1140 | 86 | **7.54%** |
| 2024-25 | 1140 | 58 | **5.09%** |
| 2025-26 | 1140 | 92 | **8.07%** |

The bar is cleared in all three seasons. The bar was not amended. Everything below was established after the
count and is the reason the idea is declined anyway.

## Definitions

- "Lacking an EPL prior" = no ≥ 450-minute record in the immediately previous EPL season on
  `understat_matches_*` (the blend's own eligibility rule), or no Understat id in the crosswalk.
- Reasons, from the seasons on disk plus manual origin labels for every no-prior player who reaches a decision
  partition (labels are from general knowledge, recorded in the CSV; new-to-EPL players who never reach a
  partition were not labelled): foreign league; Championship (promoted club or loan-back); academy; thin EPL
  prior (< 450 min); returning to EPL (an earlier season, not the immediate prior); no crosswalk id.
- Understat-covered origin leagues: La Liga, Bundesliga, Serie A, Ligue 1, RFPL.
- Decision partitions: likely starters (p_start ≥ .75) and squad-relevant (top 30 by e_points within gameweek).

## 1. Population (outfield step-0 rows; players / player-gameweeks)

| reason | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| foreign league | 46 / 1569 | 42 / 1356 | 38 / 1409 |
| Championship | 44 / 1442 | 32 / 1008 | 28 / 997 |
| academy | 4 / 108 | 5 / 176 | 0 |
| thin EPL prior (< 450 min) | 55 / 1977 | 42 / 1527 | 51 / 1854 |
| returning to EPL | 54 / 1937 | 56 / 2091 | 43 / 1506 |
| no crosswalk id (squad filler, 2 LS rows/season; one exception, see side finding 2) | 236 / 7012 | 185 / 5775 | 259 / 8466 |
| new to EPL, unlabelled (never reach a partition) | 54 / 1374 | 58 / 1663 | 60 / 1844 |

Only 39–44% of outfield rows carry a usable player prior at all.

## 2. Decision partitions — the population the idea can touch

| | LS 23-24 | LS 24-25 | LS 25-26 | T30 23-24 | T30 24-25 | T30 25-26 |
|---|---|---|---|---|---|---|
| all no-prior rows | 24.1% | 22.2% | 23.7% | 7.54% | 5.09% | 8.07% |
| foreign arrivals | 8.1% | 7.7% | 8.6% | 3.86% | 2.02% | 4.65% |
| **foreign & Understat-covered** | 5.5% | 5.7% | 6.3% | **3.51%** | **1.58%** | **4.04%** |

The bar counted all no-prior rows. The rows cross-league priors could change — foreign arrivals from covered
leagues — are 3.51 / 1.58 / 4.04% of squad-relevant rows: 12–15 players and 18–46 rows per season.

## 3. How wrong the position prior is for foreign arrivals (≥ 450 realised EPL minutes; prior − realised)

| | DEF (n = 18 / 16 / 19) | MID (n = 19 / 20 / 12) | FWD (n = 4 / 4 / 7) |
|---|---|---|---|
| npxG/90 mean error | −0.003 / +0.004 / +0.007 | −0.011 / +0.011 / −0.020 | −0.100 / +0.024 / −0.026 |
| npxG/90 MAE (sd) | 0.03 (0.04) | 0.09 (0.11) | 0.05–0.17 (0.06–0.20) |
| prior too high in | 56 / 50 / 74% | 47 / 65 / 58% | 25 / 75 / 43% |

**The premise is true per player and washes out at the mean**: the within-position prior is essentially
unbiased for the arrival cohort in every position and season. The arrivals that reach the top 30 are those the
prior undershoots (mean npxG error −0.074 / −0.050 / −0.028; Jackson −0.26, Diaby −0.13, Thiaw −0.13, Ekitiké
−0.16, Wirtz −0.12, Savinho −0.11), but that is a selection effect — current-season form pulled the blend up and
put them in the partition — not a league-strength bias a conversion factor would fix.

## 4. e_points cost (oracle = replace the prior share of the blend with the realised season rate)

| foreign & covered rows | mean (1−w) | prior's share of e_points | mean \|Δ\| per affected row | spread across the whole partition |
|---|---|---|---|---|
| likely starters | 0.44–0.46 | 12% | 0.19 / 0.11 / 0.15 | **0.010 / 0.006 / 0.009** |
| squad-relevant | 0.40–0.48 | 12–15% | 0.42 / 0.29 / 0.24 | **0.015 / 0.005 / 0.010** |

The per-affected-row oracle (0.24–0.42 on the top 30) is inside the GK p_cs 0.26–0.50 range, but it assumes
perfect foresight of the realised rate and it is diluted by rarity to 0.005–0.015 per partition row. A realistic
prior (a noisy, league-shifted prior-season rate recovering a fraction of the oracle) lands at ~0.003–0.005 —
the penalty-fallback scale already declined as unactionable. Signed oracle Δ on likely starters flips sign
across seasons (+0.09 / 0.00 / +0.02). By the time an arrival reaches the top 30 the prior carries only ~40–48%
of the rate.

## 5. Coverage ceiling

Foreign arrivals with a prior season in an Understat-covered league: 33/46 (72%), 29/42 (69%), 25/38 (66%);
40/44, 18/23, 46/53 of foreign top-30 rows. Unhelpable: Eredivisie (13 players over three seasons — Timber,
Kerkez, Kudus, Bassey, Minteh, Hato …), Portugal (6 — Evanilson, Gyökeres, Nico González, Mateus Fernandes),
Belgium (7), Brazil (5), Turkey, Sweden, Czech, Scotland, Switzerland, Ligue 2; and every Championship arrival
(28–44 players per season). ~30% of arrivals come from leagues Understat does not cover.

## 6. What building it would take (inventory; none of it exists)

- Ingestion: `eval/understat_matches.py` hard-codes `getLeagueData/EPL/<year>`; no non-EPL pull anywhere.
  Five more league pulls per prior season (~1,800 matches/season) into the per-match cache.
- Identity: Understat ids are global across its leagues, so foreign → EPL identity is free for covered leagues
  provided the element → Understat crosswalk (`build_crosswalk.py`, built against EPL aggregates only) is
  extended to match arrivals against the other leagues' player lists before their first EPL appearance.
- League-strength conversion: does not exist. Movers with ≥ 450 subsequent EPL minutes over the three seasons:
  Serie A 25, Ligue 1 24, Bundesliga 23, La Liga 15 — ~5–8 per league per season split across three positions.
  A per-league × position factor would be fit on 1–3 players per cell; only a single pooled factor is
  fittable, and §3 says its value is ≈ 1.0 already.

## Verdict — DECLINED ON EXPECTED VALUE

The falsifier is cleared, so by the pre-registered rule the idea is not dead on count. It is declined because
the touchable population is 1.6–4.0% of squad-relevant rows, the prior is unbiased for that cohort, the
partition-wide ceiling is ≈ 0.01 e_points/row and a realistic implementation ≈ 0.003–0.005, ~30% of arrivals
are unreachable, and the conversion factor cannot be fit. No weaker variant explored. If ever revisited it is a
new pre-registration on three tuning seasons.

## Side findings

### OPEN QUESTION (not closed) — the thin-prior / returning-EPL half of the no-prior rows

Half of the no-prior squad-relevant rows (42 / 35 / 32 of 86 / 58 / 92) belong to thin-prior and returning-EPL
players — Cole Palmer 2023-24 (Understat 2022-23 < 450 min), Ismaïla Sarr 2024-25 (returning after a season
away), Igor Thiago 2025-26 (< 450 min in 2024-25) — who already have EPL history that the single-prior-season
k = 8 blend does not reach back to (`BLEND_PRIOR` is one season; the ≥ 450-minute bar discards a thin one
outright rather than weighting it). Larger population than idea 4's (thin + returning: 25 / 12 / 29 T30 rows
vs 18 / 18 / 46 foreign-covered), uses data already on disk (`understat_matches_2022_23` onward and the
2016+ aggregates), needs no ingestion and no crosswalk work. **First candidate if modelling reopens.** Not
measured here; the multi-season reach-back is what the D2 blend deliberately did not tune
(`Logs/rate_blend_log.md`).

### Crosswalk gap (2025-26)

Rayan Cherki (element 417) reached the top-30 partition twice and likely-starters 10 times in 2025-26 with no
Understat id in `player_id_crosswalk_final.csv`, so his rate was the position prior all season with no
current-season blend. Scoped separately (same-day report); not an idea-4 matter.

---

## MODELLING IS CLOSED (2026-08-28)

With idea 4 declined the ranked list of `Logs/headroom_diagnosis.md` §4 is exhausted:

- failed on measurement: idea 3 (TC2 refinement), idea 5 (teammate absence), selection-based calibration (9b),
  hold preference at near-ties, top-end level calibration (9);
- declined on expected value: idea 7 (price anticipation), idea 4 (cross-league priors);
- parked, not failed: GK p_cs LEVEL shrink — measured 0.26–0.50 e_points per decision-partition row, three
  open design questions (`Logs/seal_register.md` PARKED row);
- adopted this cycle: bonus deletion (#20), penalty join leak fix (#19 leak), zero-gap solver.

The project moves to the prod switch: live ingestion for 2026-27 (vaastav, odds and Understat all end at
2025-26; only the availability poller writes live data), then the shadow-mode runner
(`Handoffs/Handoff_2026-08-28_full_session_detail.md` §10).
