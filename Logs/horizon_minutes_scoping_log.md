# Horizon minutes prediction — scoping log (2026-08-24)

**Status: scoping only. No model built, no simulation run.** Every figure
below is read off the frozen logs and the canonical walkforward files.
Scripts: `eval/scope_horizon_armB_diagnosis.py`, `eval/scope_horizon_instrument.py`,
`eval/scope_horizon_data_audit.py`, `eval/scope_horizon_training_scope.py`.

Target as stated: today minutes are predicted once per cutoff and frozen
across horizon steps 1–5 (confirmed in `eval/walkforward_season.py`: the
cutoff's minutes frame is copied per target gameweek, so `p_start`, `p60`,
`e_minutes` are byte-identical at all six steps from one cutoff — the Task 2
frozen check finds 100% identity in every season). The prize is bounded by
the full-horizon oracle (+117/season path, +131 chip-inclusive; ~1/6 through
the 52-case frame, 60–75% transfer timing). The plan's design constraint was
"Arm A (perfect step-0 truth, stale steps 1–5) lost 91; partial truth in a
coherent belief system subtracts; any candidate must update all six steps
together", and its warning was Arm B (calendar-knowable only): −46 / −120 /
+30.

## 0. Verdicts up front

1. **Task 1 — the consistency hypothesis is REFUTED as the cause of Arm B's
   loss, and the design constraint it motivated is not supported by the
   decision-level evidence.** Arm B was inconsistent by construction (step-0
   rows only), so the premise of the hypothesis holds; but the inconsistency
   did not cost the points. B's "knowledge" was 96–97% redundant with what
   the model already believed; contradiction-driven decisions were 4 / 2 / 0
   transfers per season; B's transfer quality versus the reference's was a
   wash (+5 / +2 / −1 next-3-gw points); and the −56 / −140 / +24 path
   deltas are path-divergence lottery — the per-gameweek loss in weeks with
   no reveal-driven decision at all is −2.0 / −4.1 / +0.7, with 2024-25's
   matching the −4.19/gw baseline-luck artefact already on record. Arm A
   settles it: in 2024-25 its decisions were +231 next-3-gw points BETTER
   than the reference's, and its path still lost 85. **What Arm B measured
   was noise, not a mechanism.** The target can survive (see Task 2), but
   the plan's premise needs restating before anything is built (§5).
2. **Task 2 — an instrument exists and separates.** Per-step component
   endpoints (E[min] MAE and Spearman, P(play)/P(60+)/P(start) Brier and
   AUC at steps 0–5) degrade monotonically with step in all three seasons
   on a common population, and a degradation ladder orders truth < fresh <
   stale-k < shrunk < shuffled with wide, consistent gaps. The quantity a
   horizon model must move is the fresh-vs-stale MAE gap, +2.3 … +7.0
   minutes at k = 1 … 5. Not a blocking result.
3. **Task 3** — of the five knowable inputs, the return-date language in
   fplcache news ("Expected back 14 Sep", "Suspended until 23 Aug": explicit
   dates on 32–41% of flagged rows) is the only one on disk that reaches
   steps 1–5 directly; suspensions are derivable at 86–92% precision but
   41–55% coverage; the fixture calendar inside the horizon is the FINAL
   calendar (100% agreement, a mild hindsight on double-gameweek timing);
   the AFCON flag appears a median 6–7 days before the deadline and is never
   visible at the previous deadline; squad competition is computable for
   the current gameweek only, on coarse labels.
4. **Task 4** — four seasons carry the `starts` label (2022-23 partial:
   GW1–15 quarantined, 8,491 null rows), three are simulable. KNOWN_ISSUES
   #11 holds and blocks the walk-forward for 2022-23 and earlier, NOT
   training: 2022-23 is already in `minutes.TRAIN_SEASONS` and
   `walkforward_season.LABELLED`.

Per the instruction, this stops here: the Task 1 finding is the kind that
means rethinking before building.

## 1. Task 1 — Arm B reproduced and diagnosed

### What Arm B knew and how it was applied (re-derived from code)

`squad/oracle_minutes.py`, mode `masked_step0`: rows with `cutoff == gw`
(horizon step 0) AND `(gw, element) ∈ ORACLE_MASK` had their minutes
replaced by realized minutes (and the dependent terms recomputed); every
other row — every step 1–5 row for every player, and step-0 rows outside
the mask — kept the model's own beliefs. The mask
(`eval/run_teamnews_knowable.knowable_mask`, reproduced here exactly:
14,801 / 12,844 / 15,052 reveals) = players who logged ≥60 PL minutes in a
fixture within the prior 4 days, OR the first gameweek after a 3+-gameweek
zero-minute absence. So: **step 0 updated for the masked subset; steps 1–5
frozen for everyone. Inconsistent by construction — as was Arm A.**

### Was the information informative?

| season | reveals | moved the step-0 belief by ≥30 min | absent-surprise (truth <15, model ≥60) | present-surprise (truth ≥60, model <30) |
|---|---|---|---|---|
| 2023-24 | 14,801 | 575 (3.9%) | 81 | 160 |
| 2024-25 | 12,592 | 462 (3.7%) | 59 | 141 |
| 2025-26 | 15,052 | 476 (3.2%) | 47 | 137 |

96–97% of what Arm B "knew" the model already believed. Of the
absent-surprises (player rested/dropped this week), 33% / 51% / 51% played
≥60 the very next week — the stale step-1 belief was right about next week
about half the time; step-0 truth says nothing about next week.

### Contradictions with the stale steps

Absent-but-still-rated-next-week: 70 / 59 / 47 player-weeks;
present-but-written-off-next-week: 146 / 134 / 129. These exist. The
question is whether the solver acted on them and lost.

### Decisions, classified (B vs the fslog base_wc2 reference)

| season | B path Δ | B-only transfers | reveal-driven (mean E2) | contradiction-driven (mean E2) | not reveal-driven (mean E2) | reference-only transfers (mean E2) | B-only − ref-only E2 |
|---|---|---|---|---|---|---|---|
| 2023-24 | −56 | 38 | 20 (+1.05) | 4 (−3.25) | 18 (+5.56) | 40 (+2.90) | **+5** |
| 2024-25 | −140 | 53 | 19 (+2.42) | 2 (+3.00) | 34 (+4.41) | 50 (+3.88) | **+2** |
| 2025-26 | +24 | 36 | 7 (+4.29) | 0 | 29 (+4.10) | 36 (+4.17) | **−1** |

E2 = realized points of (in − out) over the next three gameweeks. Per-gameweek
path delta B − reference: weeks with a reveal-driven transfer +0.86 / −2.40 /
+0.43 (n = 7 / 10 / 7); **all other weeks −2.00 / −4.14 / +0.68**. First
divergent gameweek 19 / 7 / 10.

Reading: contradiction-driven decisions are too few (4 / 2 / 0) to move a
season; B's decisions were as good as the reference's; the loss sits in
weeks where B made no reveal-driven decision at all — the different-squad
lottery. 2024-25's −4.14/gw in those weeks is the baseline-luck artefact of
record (why_2024_25_log: arms lose ~4.19/gw against the 97th-percentile
baseline even in zero-transfer weeks).

### Arm A says the same thing louder

| season | A path Δ | A-only transfers (mean E2) | reference-only (mean E2) | A-only − ref-only E2 | other-weeks Δ/gw |
|---|---|---|---|---|---|
| 2023-24 | +28 | 83 (+4.65) | 89 (+5.11) | −69 | +1.13 |
| 2024-25 | −85 | 86 (+5.69) | 74 (+3.49) | **+231** | −3.77 |
| 2025-26 | +121 | 82 (+5.05) | 73 (+5.18) | +36 | +3.97 |

Perfect step-0 truth for every player produced decisions 231 next-3-gw
points better than the reference's in 2024-25 and the path lost 85. The
season total did not measure the decisions; it measured the draw.

### Verdict

- Confirmed: Arm B (and A) updated step 0 only; steps 1–5 stayed at the
  model's beliefs.
- Refuted: that this inconsistency is what cost the points. The measured
  losses are single-draw path divergence on top of the 2024-25 artefact.
- Not "worthless" either: the information was overwhelmingly REDUNDANT —
  the calendar-knowable subset barely moves step-0 beliefs, because the
  model already prices short-term rotation and returns at step 0.
- Consequence: the plan's design constraint "partial truth subtracts, so
  everything must update together" was inferred from noise. Updating all
  six steps consistently is still the right shape for a horizon model — but
  because the value lives at steps 1–5 (Task 2), not because step-0-only
  updates are toxic.

## 2. Task 2 — can the instrument tell good from bad?

Method: three canonical walkforwards; single-fixture rows only
(`n_fixtures == 1`, so minutes are on a one-match scale); common population
= (gw, element) pairs present at all six steps (24,401 / 23,344 / 25,341);
`starts` joined from vaastav for P(start). Probability columns are NaN on
2–4% of rows at steps 1–5 (players without a minutes-model row at that
cutoff); dropped per metric.

### Per-step endpoints (2023-24; the other two seasons are within ±1 MAE / ±0.01 AUC and identically ordered)

| step | MAE | Spearman | Brier play | AUC play | Brier 60+ | AUC 60+ | Brier start | AUC start |
|---|---|---|---|---|---|---|---|---|
| 0 | 10.62 | 0.797 | 0.119 | 0.961 | 0.068 | 0.961 | 0.066 | 0.965 |
| 1 | 13.40 | 0.689 | 0.139 | 0.924 | 0.095 | 0.927 | 0.094 | 0.931 |
| 2 | 14.97 | 0.648 | 0.153 | 0.899 | 0.112 | 0.903 | 0.113 | 0.907 |
| 3 | 16.07 | 0.620 | 0.161 | 0.881 | 0.125 | 0.884 | 0.127 | 0.887 |
| 4 | 16.87 | 0.586 | 0.168 | 0.867 | 0.133 | 0.870 | 0.138 | 0.872 |
| 5 | 17.67 | 0.582 | 0.175 | 0.854 | 0.142 | 0.857 | 0.147 | 0.859 |

All eight metrics degrade monotonically with step, in all three seasons.
**Fresh-vs-stale MAE gap** (step-0 prediction for a gameweek vs the step-k
prediction made k weeks earlier, same rows): 2023-24 +2.8 / +4.4 / +5.5 /
+6.3 / +7.1; 2024-25 +2.4 / +3.6 / +4.6 / +5.5 / +6.2; 2025-26 +2.3 / +3.7 /
+4.9 / +5.7 / +6.5 minutes at k = 1 … 5. This is the quantity a horizon
minutes model exists to close.

### Consistency across steps for the same player-week

Seen from its six cutoffs, a player-week's e_minutes has mean sd 7.5–8.9
min; 9–14% have a range ≥60 min; 8–12% FLIP (step 0 on the other side of
15/60 from some earlier step). A horizon model must not raise the flip rate
while closing the gap — the current values are the ceiling.

### Falsification — the ladder (same rows at every rung; 2023-24, step 3 shown)

| variant | MAE | Spearman | Brier play | AUC play |
|---|---|---|---|---|
| truth | 0.00 | 1.000 | 0.000 | 1.000 |
| fresh (step 0 for this gw) | 10.62 | 0.797 | 0.119 | 0.961 |
| stale (step 3 as built) | 16.07 | 0.620 | — | — |
| shrunk 75% to position mean | 26.86 | 0.760 | 0.204 | 0.961 |
| shuffled within (gw, position) | 34.36 | 0.010 | 0.314 | 0.503 |

The instrument detects every degradation, and the two axes are
complementary exactly as the M1 review predicted: shrinking preserves rank
(Spearman 0.80 → 0.76, AUC unchanged) while MAE and Brier explode; staleness
degrades BOTH. So the endpoint set is MAE + Spearman + Brier/AUC together,
never one alone. **Separation shown; the instrument stands.**

### Acceptance test for any candidate (restated on this instrument)

On the common population, at each k = 1 … 5: MAE below the stale value by a
stated fraction of the fresh-vs-stale gap, Spearman and AUC(start) above
stale, step-0 metrics not worse than today's, flip rate not above today's.
Only then a policy simulation — and that simulation is measured on paired
windows, never on the season total (Task 1 is the standing illustration).

## 3. Task 3 — what is actually knowable at step k

| input | on disk? | reach | coverage / quality | note |
|---|---|---|---|---|
| Fixture calendar | yes (walkforward, steps 0–5) | k ≤ 5 | n_fixtures agrees 100% with the own-cutoff value at every step, doubles included; rows present 98% → 88% at k = 1 → 5 (blanks, pool churn) | It is the FINAL calendar: `get_fixtures` limits only the Dixon–Coles fit to the cutoff date, not the fixture list. Live DGW announcement lag (2–5 weeks) is not modelled — a mild hindsight to state, and the reason congestion is "knowable" in backtest but partly not live. |
| Suspensions from cards | derivable (vaastav yellow/red per fixture) | next fixture, k = 1 | derived bans 105 / 100 / 73; precision vs status 's' 92 / 91 / 86%; coverage of 's' rows 50 / 55 / 41%; 96 / 88 / 86% of derived bans played 0 | Misses cup cards, red-card ban lengths, FA charges; thresholds 5-in-19, 10-in-32, 15, any red. |
| AFCON / international (status 'n') | yes (availability asof flags) | ≤ 1 week | 23 / 34 / 55 absence starts; lead time deadline − news_added median 6.7 / 6.3 / 6.9 days, ≥7 days only 39 / 26 / 15%; never 'n' at the previous deadline (0 / 0 / 0); 2025-26 GW17 cluster 33 starts, run length median 5 gws | The flag is a one-step signal. Tournament dates and squad lists are knowable weeks ahead but are NOT on disk. |
| News text | yes (asof_news) | k ≤ 5 where a date is given | flagged rows 100% non-empty; explicit "DD Mon" date 39 / 41 / 32%; "expected back / return" 66–68%; "unknown return date" 28–38%; "% chance" 29–30%; "Suspended until DD Mon" present | The only on-disk input that names future weeks. Read-only audit; no parser built. |
| Squad competition | derivable (availability × vaastav team/position) | k = 0 only | 58–62% of (gw, team, position) cells have ≥1 unavailable same-position teammate, 33–38% have ≥2; DEF pools 12–13, MID 16–17 per squad | Four coarse classes; for k > 0 it is an extrapolation of current flags. |

## 4. Task 4 — training data scope

`starts` non-null: 2021-22 and earlier 0%; 2022-23 68.0% (18,014 of 26,505;
all 8,491 GW1–15 rows null by the KNOWN_ISSUES #4 quarantine); 2023-24,
2024-25, 2025-26 100%. `walkforward_season.LABELLED = {2022-23, 2023-24,
2024-25, 2025-26}`; `minutes.TRAIN_SEASONS = [2022-23, 2023-24, 2024-25]`.
Four labelled seasons for training (one partial), three simulable: a
walk-forward season needs a PRIOR labelled season, so 2022-23 cannot be
walked and 2021-22 has no label. **#11 holds and blocks end-to-end
simulation for ≤2022-23, not training.** Inferring `starts` from minutes for
the unlabelled seasons stays refused for #4's reason.

## 5. What this means for the plan (no model proposed)

- The premise to restate: not "partial truth subtracts" but "one-week
  knowledge is nearly redundant at step 0 and does nothing for steps 1–5,
  so its measured season effect is lottery noise". The oracle's +131 is
  multi-week foresight; the +2.3 … +7.0-minute stale gap at k = 1 … 5 is
  where it lives.
- The instrument is the per-step endpoint set above, with the ladder as its
  proof of separation, and the acceptance test in §2.
- The knowable inputs that reach k ≥ 1 on disk are, in order of reach:
  return dates in news text, derivable suspensions, and the fixture calendar
  (already used for fixture terms, never for minutes — congestion rotation
  is the untested lever, with the DGW-timing hindsight caveat). AFCON needs
  an external calendar; squad competition is a step-0 feature.
- Three simulable seasons; every policy claim stays a three-season claim.
