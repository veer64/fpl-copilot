# P4 — structural chip policy (protocol written before any simulation ran)

**Status: IN PROGRESS 2026-08-20.** Study only — nothing adopted.
Scripts: `eval/run_chip_study.py` (sims), `eval/measure_chip_study.py`
(measurement). Config: production defaults H=6, decay 0.85, policy=mip,
no other chips active except as stated.

## 1. Entry gate (D3) — re-verified on the current canonical files

The files have been rebuilt twice since the D3 fix (rate blend, #15), so the
gate was re-checked rather than assumed: doubled player-gameweeks price at
1.92 / 2.17 / 2.04 × singles (2023-24 / 2024-25 / 2025-26), e_minutes > 90
occurs ONLY on doubled rows, and `test_doubles_are_counted` passes. GATE
PASSED.

## 2. Structural calendar (from vaastav kickoffs; final calendar — reschedule
   announcements during the season are not modelled, stated as a caveat)

First half (GW1–19) is nearly EMPTY of structure in all three seasons: the
only first-half DGW is 2023-24 GW7 (2 teams), largest first-half blank is 2
teams, and 2025-26's first half has NO doubles or blanks at all. All
fixture-driven chip value lives in the second half. This is itself a P4
finding: under the two-per-type/one-per-half rule set, first-half BB/TC/FH
have almost nothing structural to aim at in these seasons.

Second-half targets (argmax within half):

| season | BB2 (teams dbl) | FH2 (teams blank) | TC2 | WC2 swing | WC2 staged |
|---|---|---|---|---|---|
| 2023-24 | GW34 (7) | GW29 (12) | GW34 | GW32 (+18) | GW33 (=BB2−1) |
| 2024-25 | GW33 (4) | GW29 (4) | GW33 | GW31 (+10) | GW32 |
| 2025-26 | GW33 (6) | GW34 (6) | GW33 | GW32 (+4) | GW32 |

Swing metric: total league fixtures in [g, g+2] minus [g−3, g−1]. The two
WC2 definitions nearly coincide (32/31/32 vs 33/32/32) — the "best swing"
IS the pre-DGW-cluster week.

## 3. Threshold rules (derived from the 3-season distribution, not
   hand-picked weeks; n=3 seasons — coarse by construction)

- **BB2**: play at the second-half gw with the most doubling teams;
  observed maxima 7/4/6 → trigger "≥4 teams doubling" uniquely selects the
  right week in 2024-25/2025-26; 2023-24 needs argmax (25 and 37 also reach
  ≥4). Rule of record: argmax over the half, with ≥4 as the "worth playing
  at all" floor.
- **FH2**: largest blank; observed maxima 12/4/6 → floor ≥4 teams blanking.
- **TC2**: the largest DGW (captain choice is the simulator's own argmax).
- **WC1**: policy-fixed GW4–6 (escaping the opening squad, not fixtures);
  swept 4/5/6.
- **First half**: BB1/TC1 only where a DGW exists (2023-24 GW7); FH1 at the
  largest blank where one exists (2023-24 GW17, 2024-25 GW15); 2025-26 first
  half has no valid target for any of the three.

## 4. Measurement protocol (Instrument A, adapted; stated before running)

One full-season sim per configuration vs a shared no-chip baseline. The MIP
is deterministic, so chip and baseline paths are IDENTICAL before the chip
week — asserted per run (pre-chip per-gw points must equal the baseline's),
not assumed. The W-window effect from the chip-week anchor is the paired
per-gameweek delta summed over [g, g+W), W ∈ {1, 2, 3, 5} — equivalent to
pathcontrol's windowed estimate at the chip anchor, where the crossover
collapses by prefix identity.

**No intervals will be quoted anywhere**: active anchors per (chip, W) cell
are ≤3 (one chip week per season), far below the MIN_ACTIVE_FOR_CI = 8 rule
(squad/pathcontrol.py; a block bootstrap over mostly-zeros prints a
spuriously narrow interval). Point effects per chip per season, plus the
mean over active cells, with n_active shown.

**Triple Captain needs no simulation**: the chip changes no decision — its
gain is exactly `captain_bonus` at the chip week, read off the baseline
log (squad/simulator.py docstring). Same value at every W.

**Staging increment**: (WC2@BB2−1 + BB2 combo effect) − (BB2-alone effect),
both over the combo's window — chips measured jointly, never summed
(Interim plan §4 warning).

Season totals are recorded once, framing mandatory: identify configs, not
evidence, not comparable to any earlier figure.

## 5. Configurations (22 sims; BB and TC need none)

Per season: baseline; WC1@4/5/6; BB2; FH2; WC2-swing; WC2-staged+BB2 combo;
plus 2023-24 BB1@7, FH1@17 and 2024-25 FH1@15. TC from baseline logs.

(results to be appended)

## 5a. Protocol amendment (before any sim ran): BB needs no simulation either

Bench Boost, like Triple Captain, is an EXOGENOUS instrument here: forced by
the caller, it changes no transfer decision, so its effect is exactly
`bench_points` at the chip week, read off the relevant log. BB2-alone reads
the baseline log; the staged variant's BB increment reads the WILDCARD run's
log at the BB week (the wildcard reshapes the bench first — that difference
IS the staging effect). Caveat stated: this measures BB under the CURRENT
solver, which does not load the bench for a coming boost; it is a
lower bound on what a BB-aware solver could set up, exactly as TC measures
the current captain, not a TC-aware pick. Sim count drops to 22: per season
baseline + WC1@4/5/6 + FH1 (where a target exists) + FH2 + WC2-swing +
WC2-staged (2025-26: swing and staged coincide at GW32 — one sim, read
twice).

## 6. RESULTS (2026-08-20, all 22 sims; full tables in
   eval/measure_chip_study.py output)

Family means over active cells (points, paired vs baseline, by window W):

| family | W=1 | W=2 | W=3 | W=5 | seasons positive |
|---|---|---|---|---|---|
| FH2 (blank ≥4 teams) | +15.0 | +19.7 | **+28.7** | +27.3 | 3/3 at every W |
| WC2-swing (pre-DGW-cluster) | +10.3 | +19.0 | +21.3 | +24.0 | 3/3 at W≥2 |
| WC2-staged (BB−1) | −1.5 | +10.5 | +8.5 | +12.0 | mixed (2024-25 negative at W3) |
| WC1 (GW4–6 pooled) | +6.4 | +10.7 | +5.3 | +5.4 | best week UNSTABLE across seasons |
| FH1 (blank <4 teams) | **−14.0** | −15.5 | −20.0 | −23.5 | 0/2 — actively harmful |
| TC2 (largest DGW) | +7.7 (all W) | | | | 3/3 |
| BB2 alone | +2.3 (all W) | | | | tiny |
| BB2 staging increment | +2.7 mean, but −2/+11/−1 | | | | noise |

Standouts: **Free Hit at a genuinely large blank is the best chip measured**
(the 12-team blank alone: +56 at W=3); **Free Hit at a token blank is
actively harmful** — the ≥4-teams floor is strongly supported, and below it
the right play is not playing the chip. **WC2 at the pre-cluster swing week
is the most consistent chip** (and swing ≈ staged−1 anyway). **WC1's best
week is not identifiable from three seasons** (GW4 wins 2025-26 +35, GW5
wins 2024-25 +45, GW6 negative twice) — policy can say "GW4–5", not finer.
**Bench Boost is nearly worthless under the current solver** (~2), and
staging a wildcard before it does NOT reliably load the bench (−2/+11/−1):
the MIP optimizes the XI, not the bench. The plan's BB estimate (+22)
requires a bench-aware solver that does not exist. TC2 ≈ +8 under the
current captain rule.

No intervals anywhere: n_active ≤ 3 per cell (below the ≥8 rule). No
adoption. Season totals recorded in the measurement output under the
standard framing; not repeated here.

Naive (illegitimate) sum of best-family local effects ≈ +70 at W=3 — the
combined run (§7) exists precisely because that sum double-counts paths.

## 7. Proposed combined run (not launched)

One sim per season with all supportable chips on one path: WC1@4 (or 5),
FH2@{29/29/34}, WC2-swing@{32/31/32}; BB2 and TC2 read off the combined
log at {34/33/33}. FH1 EXCLUDED (measured harmful at every available
target). 3 sims + 2 pairwise probes (FH2×WC2 ordering in 2023-24, where
they sit 3 gws apart; WC1×FH1 dropped with FH1). Caveat of record: after
WC1 the path diverges, so later chip-week deltas are no longer
path-controlled — joint capture traded for path control, per the plan's
"measure jointly, never sum".

## 8. Bench-aware Bench Boost + combined runs (protocol before running,
   2026-08-20)

**Change under test:** `transfer_mip.BENCH_BOOST_AWARE` (False on disk;
flipped in-process for these runs, stamped `bench_boost_aware` per log row).
When a Bench Boost is scheduled at gameweek g, the MIP's bench weight for
that horizon step is 1.0 (all fifteen score) — the solver builds toward the
boost as g enters the H=6 window; the wildcard at g−1 is the transfer-freedom
mechanism. Property tests: Tests/test_bench_boost_aware.py (gate-off
inertness, gate-on-no-step inertness, boost-week bench never worse ×3 seeds,
weight locality).

**Runs:**
1. Bench-aware BB re-measure (3 sims, H=6 d=0.85): wildcard@{33,32,32} +
   bench_boost_gw@{34,33,33} vs the existing chip-study baselines. Report
   per season: bench composition and bench_points at the BB week before/
   after, and the BB package effect = W-window paired path delta plus
   bench_points@g — against the old exogenous estimate (+2.3 mean).
2. Combined chip runs (6 sims): WC1@4 + FH2@{29,29,34} + WC2@{32,31,32} +
   bench-aware BB@{34,33,33}; TC2 read off the combined log. At H=6 d=0.85
   (pairs with all existing P4 numbers) AND H=6 d=0.6 (pairs with the
   transfer sweep's base_H6_d60 no-chip runs). CROSS-CONFIG TOTALS ARE NOT
   COMPARABLE — different decay families; each config is read only against
   its own baseline.

All runs under the thread-capped parallel pool (FPL_SOLVER_THREADS=2, six
workers) — the controlled speedup measurement for the parallelisation item.
Path-control caveat as §7: after the first chip the path diverges.

## 9. Section-8 RESULTS (2026-08-20) — nothing adopted, gate stays False

**Bench-aware BB package** (path delta from wildcard week + boosted bench;
old exogenous estimate was +2.3):

| season | pre-position (bb−5..wc−1) | bench@BB before→after | package W=2 / W=3 / W=5 |
|---|---|---|---|
| 2023-24 | +19 | 3 → 3 | +17 / +25 / +23 |
| 2024-25 | 0 | 1 → 17 | +6 / −20 / −20 |
| 2025-26 | −1 | 3 → 11 | +30 / +31 / +49 |

Two of three seasons clearly positive (~+25..+49 at W≥3) — an order of
magnitude over the unaware +2.3. The 2024-25 case is the failure mode on
record: the solver loaded the bench (1→17) but paid more in XI/path than the
bench returned (package −20). 2023-24 shows the opposite surprise: bench
unchanged (3→3) yet +25 — the awareness moved value through the XI and
pre-positioning instead. Mechanism works; its net sign depends on prediction
quality at the reshuffle, exactly like every other lever in this project.
n_active ≤ 3 per cell — no intervals, per the ≥8 rule.

**Combined package, W=3 deltas at each chip anchor (vs own-family baseline;
CROSS-CONFIG TOTALS NOT COMPARABLE):**

| season | config | WC1@4 | WC2 | BB week | + BB bench | + TC |
|---|---|---|---|---|---|---|
| 2023-24 | d85 | +15 | +19 | +18 | 3 | 3 |
| 2023-24 | d60 | −16 | +60 | +47 | 11 | 3 |
| 2024-25 | d85 | +7 | −16 | −27 | 19 | 7 |
| 2024-25 | d60 | +12 | −28 | −30 | 29 | 7 |
| 2025-26 | d85 | +35 | +20 | +34 | 10 | 13 |
| 2025-26 | d60 | +54 | +43 | +5 | 26 | 13 |

The 2024-25 second-half cluster is negative at BOTH decays (the same
reshuffle-into-error failure mode as its bench-aware run), while 2023-24 and
2025-26 are positive nearly everywhere. Interaction vs sum-of-parts: at d85
the combined local effects land in the same range as the individual chips
suggested (no large synergy or cannibalisation is resolvable at n=3 seasons).
Windows overlap between WC2 and BB anchors (2 gws apart) — the anchor deltas
are NOT additive with each other.

**Parallelisation:** 6 workers × FPL_SOLVER_THREADS=2: per-sim latency ~33
min vs ~11-15 solo (contention persists — combined sims are also inherently
heavier: every horizon window contains a chip), but wall-clock throughput
~2× the sequential equivalent. Yesterday's unthrottled 5-way runs hit 78
min/sim; the cap removes that pathology. Recommendation for future sweeps:
4 workers × 2 threads.

## 10. H=6 / decay=0.45 chip run (protocol before running, 2026-08-20)

**Rationale of record:** H=6 is REQUIRED for bench-aware Bench Boost — the
boost must enter the horizon early enough (bb−5) for the solver to build
toward it. Decay 0.45 is mid-range and deliberately chosen: 0.85 was never
in any sweep — it was inherited from a config stamp — and season totals
could not separate decay options (the sweep's E1–E4 endpoints showed no
consistent decay winner). This is a MECHANISM-BASED decision, stated as
such, not a measured optimum.

**Baselines reused, not re-run:** sweep base_H6_d45 (2204 / 2362 / 2032).
Provenance verified below; prefix-identity of each chip run's pre-GW4 path
against its baseline is asserted at measurement (the canary for any code-
path drift, e.g. the FPL_SOLVER_THREADS cap added after the sweep — the
gate-off inertness of BENCH_BOOST_AWARE is property-tested).

**Configs (3 sims; the 'all chips' variant is a DERIVED READ, not a second
sim):** WC1@4 + WC2-swing@{32,31,32} + FH2@{29,29,34} + bench-aware
BB2@{34,33,33}, decay 0.45, gate on in-process. TC1, TC2 and BB1 change no
decisions (TC doubles the chosen captain; unoptimised BB reads the bench),
so the all-chips numbers come off the SAME log — running a second sim per
season would produce a bit-identical file under the deterministic solver.
- TC1 rule: the GW1–19 week where the sim's own captain's PREDICTED points
  peak (fixture difficulty enters via fixture_scale/λ already); report the
  week, the player, and what he actually scored.
- BB1: GW10 flat across seasons — ARBITRARY, flagged unoptimised; measures
  whether a single-fixture boost is worth anything at all.
- Windows: anchors 4, FH2, WC2, BB2; WC2/BB2 are 1–2 gws apart so their
  windows OVERLAP at W≥2 and must not be added; FH2@29 vs WC2@31/32
  overlaps at W=5 in 2024-25 (noted per season).

## 11. Section-10 RESULTS (2026-08-20). Not adopted; gate stays False.

Prefix identity vs the sweep d45 baselines PASSED in all three seasons (the
thread-cap/gate-branch code drift canary held). One sim per season; the
all-chips rows are derived reads (TC1/TC2/BB1 change no decisions).

| season | base | sim | path Δ | +BB2 | +TC2 | pkg2h | +TC1 | +BB1@10 | all-chips |
|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | 2204 | 2233 | +29 | 46 | 3 | 2282 | 6 | 37 | 2325 |
| 2024-25 | 2362 | 2118 | **−244** | 29 | 7 | 2154 | 9 | 8 | 2171 |
| 2025-26 | 2032 | 2062 | +30 | 24 | 13 | 2099 | 16 | 4 | 2119 |

Margins vs average manager (claimed / fplcache): 2023-24 pkg2h +244/+279;
2024-25 +0/+146; 2025-26 +204/+204.

W=3 anchor deltas: 2023-24 WC1 −11, FH2 +25, WC2 +53, BB2 +12 (bench 46 —
the d45 bench-aware run genuinely loaded the bench); 2024-25 ALL second-half
anchors negative (WC2 −38, BB2 −28, FH2 −8) — the third independent
appearance of 2024-25's late-season failure mode; 2025-26 all positive
(WC1 +45, WC2 +30, BB2 +32, FH2 +34). Anchors within 5 gws overlap — never
added. TC1 rule selections: GW6 Haaland (pred 11.1 → 6), GW18 Salah (10.9 →
9), GW17 Haaland (9.2 → 16); mean +10.3. BB1 unoptimised: 37/8/4 — the 37
is one lucky bench week on single fixtures, not policy.

**Comparability vs decay 0.85:** totals are NOT comparable across decay
families (different baselines, different paths). The only legitimate
cross-family statement is qualitative sign agreement per anchor: 2024-25's
second-half cluster is negative in BOTH families; 2023-24/2025-26 positive
in both. n=3 seasons; no intervals (≥8 rule).

## 12. P4 ADOPTED (2026-08-20) — rules of record

| Chip | Rule of record | Evidence |
|---|---|---|
| Wildcard 1 | **Policy-fixed GW2–3 (REVISED 2026-08-21, §12b).** ~~Policy-fixed GW4–5 (exact week NOT identifiable from 3 seasons)~~ — superseded 2026-08-21: set before GW2–3 were ever tested; GW4 measured weakest of GW2–5 | §12b revision record; §12a review; p1_opening_log.md §7–8 (both grids). Original evidence: §6 |
| Wildcard 2 | The pre-DGW-cluster fixture-swing week | most consistent chip: positive 3/3 seasons at W≥2 (§6), swing ≈ staged−1 |
| Bench Boost 2 | Second-half gw with most doubling teams, floor ≥4; **bench-aware solver ON** | §9/§11: bench-aware package +25/+31 (d85), bench 46 pts at d45; unaware BB was +2.3 |
| Free Hit 2 | Largest blank, floor ≥4 teams blanking; **never below the floor** | +28.7 mean at W3; below-floor measured −20 mean (actively harmful) |
| Triple Captain 2 | Largest double gameweek | +7.7 mean |
| Triple Captain 1 | GW1–19 week where the intended captain's predicted points peak | +10.3 mean (§11) |
| Bench Boost 1 | Only where a genuine first-half double exists — near-worthless on single fixtures | 37/8/4 unoptimised (the 37 a fluke); no H1 doubles in 2/3 seasons |

**Results, honestly:** at H=6 decay 0.45 the package gains +78 (2023-24) and
+67 (2025-26) over its own baselines in chip-inclusive terms, and LOSES in
2024-25 — the third independent appearance of that season's failure mode
across both decay families and the bench-aware run. **Diagnosis of record:
reshuffle-into-error.** A chip forces a rebuild; when late-season predictions
are wrong (as 2024-25's are), the rebuild locks the errors in. The chip
policy's risk is not timing — it is prediction quality at the reshuffle.

## 12a. WC1 review queued (2026-08-21, cross-reference — NOT an adoption)

The overnight WC1 × opening grid (42 sims, Logs/p1_opening_log.md §7)
supersedes §6's "GW4–6, unresolvable" framing: at W=3, WC1@GW2 is positive
in all six season×opening arms (cross-season mean ~+41 under both
openings) while GW4 — inside the adopted "GW4–5" rule — is negative in 4
of 6 arms and GW6–8 are broadly negative. The rule of record in §12 STANDS
until a deliberate revision; any revision should cite that grid and note
its caveat: a GW2 wildcard partly substitutes for fixing the opening squad
(P1), so the two levers must stay jointly measured.

**Review completed 2026-08-21; the rule was revised to GW2–3 the same day —
see §12b for the decision record. The assembled case:**
The assembled case (all W ∈ {1,2,3,5}, both grids, both openings, three
seasons): GW2 is the only week positive in 6/6 arms at W=1, 2 AND 3 (5/6 at
W=5), at ~2.5× the magnitude of any alternative (W=3 mean +41 vs GW3 +17,
GW5 +15); GW4 is 2/6 at W=3 — the weakest of GW2–5; GW6 is the worst week
on the board (1/6). Anchors reproduce under the full-system grid (median
|diff| 0, mean 2.9) — replication under perturbation, not an independent
sample. The GW2 gain is a 10–13-transfer full rebuild whose window delta is
spread across all three weeks, in all three seasons — not one fluke week,
season, or player. Counter-case recorded: (a) the gain is proportional to
the opening squad's coldness — it generalises for THIS system live (same
cold GW1) but shrinks if the opening ever improves; (b) no lookahead — GW2
decisions use only cutoff-2 data, which a live manager also has; (c) the
UNMEASURED cost is option value: spending WC1 at GW2 forfeits cover for a
later first-half crisis, and the anchor window cannot price that (the three
measured first halves contain almost no chip-worthy structure, but n=3
calendars is thin). Supported ranking: GW2 > {GW3, GW5} > GW4; GW3 is the
defensible conservative middle (6/6 at W=2–3, half the magnitude, one more
week of information, keeps more option value). Confidence: sign
consistency is the strength; magnitudes are single draws; no intervals
possible.

## 12b. WC1 rule REVISED: GW4–5 → GW2–3 (2026-08-21, user decision)

The rule of record for Wildcard 1 is now **policy-fixed GW2–3**. Reasoning
of record:

1. **The evidence.** GW2 is positive at the W=3 anchor in six of six
   season×opening arms across BOTH grids (the 42-sim isolated grid and the
   24-sim full-system grid), and positive at W=1, 2 and 3 — the only week
   to manage that. Cross-season W=3 means: GW2 +41, GW3 +17, GW5 +15,
   GW4 −2.
2. **The old rule's basis is gone.** GW4–5 was set (§6) before GW2 and GW3
   were ever tested. With the full grid on disk, GW4 is the weakest of
   GW2–5 and is now contradicted (2/6 arms positive at W=3).
3. **The mechanism generalises.** A GW2 wildcard uses only cutoff-2 data —
   information a live manager genuinely has at that deadline. No hindsight
   artefact; the walk-forward discipline holds.
4. **The conditionality, recorded explicitly.** The GW2 edge exists because
   this system's GW1 predictions are the coldest of its season —
   prior-season rates, ~32% no-prior players — so one real week is the
   largest information gain it ever receives. If D5 (player props) or
   lineup data ever improve GW1, this edge SHRINKS BY CONSTRUCTION. The
   substitution finding is direct evidence: +15 under the horizon opening
   vs +35 under base at the same anchor. Revisit this rule whenever the
   opening-squad inputs materially improve.
5. **The unmeasured reservation.** Playing WC1 at GW2 forfeits chip cover
   for a first-half crisis. The anchor window cannot price option value and
   neither can season totals (M1). The mitigation — three measured
   calendars showed almost no first-half chip structure (§2) — is thin
   evidence, and this reservation is why the rule is a GW2–3 RANGE rather
   than GW2 alone: GW3 is 6/6 at W=2–3 at half the magnitude, with one more
   week of information and slightly more option value retained.
6. **Confidence: moderate on sign, low on magnitude.** Three seasons,
   single draws per cell, no intervals (≥8 rule). The strength is
   consistency — 6/6 arms × three windows × two grids — not effect size.

## 13. STANDARD CONFIG ADOPTED: H=6, decay=0.45

`transfer_mip.DEFAULT_DECAY` 0.85 → 0.45; DEFAULT_HORIZON stays 6.
**Rationale of record (mechanism-based, stated as such):** H=6 because
bench-aware Bench Boost needs the boost week inside the horizon (bb−5);
decay 0.45 because 0.85 was INHERITED from a config stamp, never swept, and
season totals cannot rank decays (M1). The simulator now stamps `horizon`
and `decay` into every decision-log row, and `BENCH_BOOST_AWARE = True` is
the resting state (inert unless a Bench Boost is scheduled;
property-tested).
