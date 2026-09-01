# The last two combined-config inputs: hmin refit + props book — 2026-08-31

Baseline was already live-ready; this closes the two combined-config levers'
strict findings for the live deadline (GW3).

## PART A — the hmin refit

**What it is** (`eval/run_horizon_minutes.py` -> `squad/horizon_minutes.py`): the
step-aware REFIT of the minutes model — the SAME five sub-models
(`_fit_step`: p_start LGBM 300/31, p60 100/7, p_sub 200/15 + isotonic, min_start
200/15, min_sub 100/7) fitted on LAGGED pairs "features at GW g -> label at
GW g+k" (`_pairs`), one fit per horizon step k = 1..5 per cutoff.

**The cold-start answer, established before fitting**: the training mask is
"prior seasons in full; current season only where the LABEL gameweek is strictly
before the cutoff" (`_train_mask`, quoted). Training pairs come overwhelmingly
from 2022-23..2025-26; the current season contributes FEATURES (the cutoff row)
plus a handful of early pairs. So a 2026-27 refit is **fittable now and
meaningful** — the same construction produced 2025-26's cutoff-GW1 rows. No
N-gameweek wait is required; nothing meaningless was fitted to close a finding.

**Two real defects fixed on the way** (both exposed by the fit, both live-path
defects, not fit hacks):
1. `horizon_minutes._frames` and `minutes._prepare` read frames that EXCLUDED
   forward-skeleton rows (`starts.notna()` dropped every unlabeled row), so no
   unplayed gameweek could be predicted at all — including a live deadline's
   STEP 0. Fix: keep labeled rows PLUS forward rows (minutes-NaN sentinel;
   pre-2022 label-less seasons have real minutes and stay excluded, #11), and
   guard the three label consumers explicitly. Proven: GW3 (unplayed)
   `get_minutes` now returns 626 rows, zero NaN e_minutes; and the step-0
   integrity assert that caught the stale-frame symptom did its job.
2. The fit's gameweek list read the frozen archive; repointed to the stack.

**The fit**: `hmin_2026_27_refit.parquet`, cutoffs 1-3 (the played gameweeks +
the live deadline), 11,172 rows, 6 steps each. Distribution vs 2025-26@cutoff-3:
p_start mean 0.195-0.231 vs 0.303-0.313, e_minutes ~19-21 vs ~27-28 — the
2026-27 refit is more conservative (two played gameweeks of features, a wider
626-row universe); the lever consumes per-player ORDERING, and the values are
real, not noise. Refresh per deadline: rerun with `--cutoffs <next gw>`.

Fallback question resolved by fitting: no 2025-26-refit fallback was needed.

## PART B — the props book

**Void rules for the six new books — established or EXCLUDED, never assumed**:

| book | rule | classification | source |
|---|---|---|---|
| fanatics | "a player must start for player proposition bets to be considered action" | **START** | Fanatics soccer betting guide / house rules |
| rebet | "if a player was not in the starting lineup, the pick will be voided" | **START** | rebet.app/sports-prediction-rules |
| ballybet | no published soccer player-prop void rule found (Kambi T&C soccer section silent) | **UNKNOWN -> EXCLUDED** | — |
| betparx | nothing published found | **UNKNOWN -> EXCLUDED** | — |
| espnbet | rules page unreachable (TLS cert mismatch, both hosts) | **UNKNOWN -> EXCLUDED** | — |
| williamhill_us | Caesars page's soccer section truncated; a basketball-section quote is not a soccer rule | **UNKNOWN -> EXCLUDED** | — |

The gate is enforced IN CODE at both ends: `build_props_consensus` drops
non-classified books (counted — this run: williamhill 20, pinnacle 6, betparx 20,
ballybet 20, williamhill_us 20, espnbet 20 board-rows) and `PropsHook` asserts at
construction (tested with a doctored frame). `_ALLOWED_BOOKS` is asserted equal
to the hook's lists. Re-admission requires a quoted published rule.

**The 2026-27 consensus** (GW1-2, historical endpoint, 3 regions — us2 added
because bovada/rebet moved there): 20/20 fixtures, **props coverage 100% at GW1
and GW2**; retained books per fixture: draftkings, betmgm, bovada, fanduel,
onexbet, betrivers, mybookieag, fanatics, rebet (9 — 7 historical + 2 verified
new). Hook constructs: 5,556 per-book rows. Partial doubles: 0.

**The crosswalk burden** (the recurring weekly cost): 2026-27 GW1-2: match rate
88.56% (859/970 rows), provenance exact 693 / token_subset 121 / club+token 39 /
fuzzy 6; **manual entries needed so far: 0**; 69 distinct unmatched names (111
rows), dominated by transfer-window mismatches (Nicolas Jackson, Guessand,
Ramazani... — players whose master club is stale at a 1-played-gameweek master;
several will self-resolve as gameweeks ingest). Outfield-starter coverage
96.67% (6 player-fixtures unpriced, 0 unmatched-with-candidate). Weekly burden
estimate: rerun crosswalk + consensus after each gameweek (~1 min compute),
review the unmatched-with-candidate list (0 this week) and top unmatched names
(~2-5 realistically needing a MANUAL entry per month, on the 162/57-per-season
historical base rate).

**The strict floor fires**: PROPS_MIN_FIXTURE_COVERAGE = 0.80 — GW3 coverage is
0/10 and preflight raises for it (and each later target gw). Honest state: the
consensus covers COMPLETED gameweeks; pricing the GW3 board requires a
pre-deadline live props pull (2 credits/fixture at two regions), which this task
deliberately did not build.

**Pipeline fixes en route** (all loud-failure preserving): region-suffix glob in
crosswalk + consensus (filenames now `_euusus2`); promoted clubs added to the
pull's TOKENS (the crosswalk's reverse map raised on Coventry — as designed);
stack repoint for the crosswalk's coverage frame with an explicit empty-guard;
consensus `n_fixtures` falls back to the stack+skeleton when no walkforward
frame exists; the partition-coverage report is SKIPPED with a note for live
seasons (never faked from a synthetic frame).

## BOTH — parity and preflight

**Parity (the gate)**: record DC source pinned, both configs, GW5/20/33:
**BIT-IDENTICAL in all six cells** — through the minutes-`_prepare` change, the
horizon repoint, and every props edit. The suite's record-parity and
arm-extraction tests (the 2025-26 arm frame reproduced through both paths) pass.

**Strict preflight, 2026-27 GW3 horizon-6 COMBINED, after this task**:
- props book finding: **GONE** (consensus + manifest exist, hook constructs)
- hmin refit finding: **GONE** (file exists, covers cutoff 3)
- remaining: props coverage 0% at GW3..GW8 (the live props pull, deliberately
  unbuilt) + the steps-1+ odds convention note.

## Credits (task accounting)

This task: **602** (historical props pull, GW1-2, 3 regions) + 0 elsewhere.
Paid-key running total: **605 used, 19,395 remaining** of 20,000/month
(602 + the 3-credit reachability probe). The old free key spent 6 this session
(h2h probes + the live odds pull's 2). The 2026-09-24 cancellation decision:
live props at 2 pulls/gameweek ≈ 40 credits/gw ≈ 180/month — trivially inside
the paid pool; whether the free tier can reach props remains unverified.
