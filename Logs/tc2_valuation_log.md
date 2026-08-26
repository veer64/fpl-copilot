# TC2 valuation sweep -- every legal second-half week on the frozen base_wc2 paths

Generated 2026-08-24 by eval/tc2_valuation_sweep.py. Read-only; no simulations.

**Framing (binding):** every number below is a HINDSIGHT read of what one captain scored on one frozen path. Nothing here is adopted into any headline; ~~the chip-inclusive figures of record remain 2296 / 2294 / 2206 with TC2 scored as zero (p4 log section 12c)~~ **superseded 2026-08-26: TC2 is now scheduled IN-SIM on the 12c (ii) week and the figures of record are 2251 / 2306 / 2268 (p4 log section 15)**. This is a valuation study of the TC2 RULE, not a figure.

## Method (stated before the results)

* Path: data/p1/fslog_{season}_base_wc2.parquet -- the system-as-configured
    full-system cell. The captain is READ from the frozen path (`captain`,
    `doubled_role`, `captain_bonus` per gw), never re-chosen.
  * Read formula: TC2_read(gw) = captain_bonus[gw]. In the decision log
    captain_bonus = points(doubled player) x 1, where the doubled player is
    the captain, or the vice when the captain played 0 minutes
    (scoring.resolve_captain). A Triple Captain adds exactly one more
    multiple of that player's points, so the read is captain_bonus itself --
    the same quantity every TC1/TC2 read in the project uses.
  * Legal weeks: GW20-38 minus the weeks already holding a chip on that
    path (WC2, FH2, BB2; one chip per gameweek). TC1 sits in the first half.
  * Doubles inventory: walkforward n_fixtures >= 2 at own cutoff, teams
    doubling per gw (eval/quantify_collision.py convention).
  * Rule (i), 2026-08-24 morning: TC2 = largest double gameweek EXCLUDING
    the BB2 week. Where two doubles tie on team count it does not pick;
    every tied week is reported (kept as the comparison).
  * ADOPTED rule (ii), 2026-08-24 (p4 log section 12c ii): TC2 = the
    EARLIEST second-half double gameweek excluding weeks already holding a
    chip -- structural, computable from the fixture calendar alone. Reported
    per season with its read and rank so the cost of the choice is on the
    record, not hidden.
  * Old rule: largest double gameweek overall = the BB2 week. Its read is
    illegal (collision) and is shown only for comparison, ranked as if it
    had been counted among the legal weeks.
  * Random-week baseline: the mean read over the legal weeks -- what a
    manager who picked blind would expect.
  * Rank: 1 = best legal week. Percentile = share of legal weeks whose read
    is <= the week's read (ties count in favour).

## Results

### 2023-24

Path chips: WC2 GW32, FH2 GW29, BB1 GW7, BB2 GW34. Legal TC2 weeks: 16 (GW20-38 minus those three). Doubles in H2: GW25:4, GW28:2, GW34:7, GW35:2, GW37:6.

**Distribution of the TC2 read over legal weeks** (captain_bonus, points):

- min 2, q25 3.8, median 6.0, mean 7.75, q75 10.8, max 16; sd 5.03, n=16
- **random-week baseline (mean over legal weeks): 7.75**
- best five weeks: GW20 16, GW23 16, GW37 15, GW36 13, GW22 10
- worst five weeks: GW28 4, GW21 3, GW30 2, GW33 2, GW38 2
- weeks where the armband fell to the vice/none: GW31

**Per-week reads** (legal weeks; * = double gameweek):

| gw | teams doubling | captain | doubled | TC2 read | rank/16 | pctile |
|---|---|---|---|---|---|---|
| GW20 | - | Mohamed Salah | captain | 16 | 1 | 100% |
| GW21 | - | Bukayo Saka | captain | 3 | 13 | 25% |
| GW22 | - | Bukayo Saka | captain | 10 | 5 | 75% |
| GW23 | - | Alejandro Garnacho | captain | 16 | 1 | 100% |
| GW24 | - | Darwin Núñez Ribeiro | captain | 6 | 8 | 56% |
| GW25* | 4 | Erling Haaland | captain | 10 | 5 | 75% |
| GW26 | - | Erling Haaland | captain | 5 | 11 | 38% |
| GW27 | - | Erling Haaland | captain | 6 | 8 | 56% |
| GW28* | 2 | Norberto Murara Neto | captain | 4 | 12 | 31% |
| GW30 | - | Darwin Núñez Ribeiro | captain | 2 | 14 | 19% |
| GW31 | - | Erling Haaland | vice | 6 | 8 | 56% |
| GW33 | - | Mohamed Salah | captain | 2 | 14 | 19% |
| GW35* | 2 | Nicolas Jackson | captain | 8 | 7 | 62% |
| GW36 | - | Mohamed Salah | captain | 13 | 4 | 81% |
| GW37* | 6 | Erling Haaland | captain | 15 | 3 | 88% |
| GW38 | - | Erling Haaland | captain | 2 | 14 | 19% |

**Rule (i) -- largest double EXCLUDING the BB2 week (superseded the same day by (ii); kept as the comparison):**

- GW37 (DGW x6; captain Erling Haaland, doubled=captain): read **15**, rank 3/16, percentile 88%, vs random-week mean +7.25 (+1.44 sd)

**ADOPTED rule (ii) -- EARLIEST eligible second-half double (p4 log section 12c ii, 2026-08-24):**

- GW25 (DGW x4; captain Erling Haaland, doubled=captain): read **10**, rank 5/16, percentile 75%, vs random-week mean +2.25 (+0.45 sd); vs rule (i) week GW37 read 15: -5

**Old rule -- largest double overall = the BB2 week (ILLEGAL read, comparison only):**

- GW34 (DGW x7; captain Mohamed Salah, doubled=captain): read 3; had it been legal it would rank 13/17 (percentile 25% of the legal weeks), vs random-week mean -4.75.

**Secondary -- does 'double' carry signal at all?** mean read on legal double weeks 9.25 (n=4) vs single weeks 7.25 (n=12): +2.00.

### 2024-25

Path chips: WC2 GW31, FH2 GW29, BB1 GW7, BB2 GW33. Legal TC2 weeks: 16 (GW20-38 minus those three). Doubles in H2: GW24:2, GW25:2, GW32:2, GW33:4.

**Distribution of the TC2 read over legal weeks** (captain_bonus, points):

- min 2, q25 2.8, median 7.5, mean 9.69, q75 14.2, max 29; sd 8.98, n=16
- **random-week baseline (mean over legal weeks): 9.69**
- best five weeks: GW24 29, GW32 27, GW25 20, GW28 15, GW26 14
- worst five weeks: GW27 3, GW21 2, GW35 2, GW36 2, GW37 2
- weeks where the armband fell to the vice/none: none

**Per-week reads** (legal weeks; * = double gameweek):

| gw | teams doubling | captain | doubled | TC2 read | rank/16 | pctile |
|---|---|---|---|---|---|---|
| GW20 | - | Mohamed Salah | captain | 7 | 9 | 50% |
| GW21 | - | Mohamed Salah | captain | 2 | 13 | 25% |
| GW22 | - | Mohamed Salah | captain | 3 | 10 | 44% |
| GW23 | - | Mohamed Salah | captain | 8 | 7 | 62% |
| GW24* | 2 | Mohamed Salah | captain | 29 | 1 | 100% |
| GW25* | 2 | Mohamed Salah | captain | 20 | 3 | 88% |
| GW26 | - | Mohamed Salah | captain | 14 | 5 | 75% |
| GW27 | - | Cole Palmer | captain | 3 | 10 | 44% |
| GW28 | - | Mohamed Salah | captain | 15 | 4 | 81% |
| GW30 | - | Mohamed Salah | captain | 3 | 10 | 44% |
| GW32* | 2 | Harvey Barnes | captain | 27 | 2 | 94% |
| GW34 | - | Mohamed Salah | captain | 8 | 7 | 62% |
| GW35 | - | Mohamed Salah | captain | 2 | 13 | 25% |
| GW36 | - | Mohamed Salah | captain | 2 | 13 | 25% |
| GW37 | - | Mohamed Salah | captain | 2 | 13 | 25% |
| GW38 | - | Mohamed Salah | captain | 10 | 6 | 69% |

**Rule (i) -- largest double EXCLUDING the BB2 week (superseded the same day by (ii); kept as the comparison):**

- TIE: 3 doubles share the largest team count (2); the rule does not pick between them. All tied weeks reported.
- GW24 (DGW x2; captain Mohamed Salah, doubled=captain): read **29**, rank 1/16, percentile 100%, vs random-week mean +19.31 (+2.15 sd)
- GW25 (DGW x2; captain Mohamed Salah, doubled=captain): read **20**, rank 3/16, percentile 88%, vs random-week mean +10.31 (+1.15 sd)
- GW32 (DGW x2; captain Harvey Barnes, doubled=captain): read **27**, rank 2/16, percentile 94%, vs random-week mean +17.31 (+1.93 sd)

**ADOPTED rule (ii) -- EARLIEST eligible second-half double (p4 log section 12c ii, 2026-08-24):**

- GW24 (DGW x2; captain Mohamed Salah, doubled=captain): read **29**, rank 1/16, percentile 100%, vs random-week mean +19.31 (+2.15 sd); vs rule (i) week GW25 read 20: +9; rule (i) week GW32 read 27: +2

**Old rule -- largest double overall = the BB2 week (ILLEGAL read, comparison only):**

- GW33 (DGW x4; captain David Raya Martin, doubled=captain): read 7; had it been legal it would rank 9/17 (percentile 50% of the legal weeks), vs random-week mean -2.69.

**Secondary -- does 'double' carry signal at all?** mean read on legal double weeks 25.33 (n=3) vs single weeks 6.08 (n=13): +19.26.

### 2025-26

Path chips: WC2 GW32, FH2 GW34, BB1 GW10, BB2 GW33. Legal TC2 weeks: 16 (GW20-38 minus those three). Doubles in H2: GW26:2, GW33:6, GW36:2.

**Distribution of the TC2 read over legal weeks** (captain_bonus, points):

- min 0, q25 1.8, median 6.0, mean 4.88, q75 7.0, max 11; sd 3.46, n=16
- **random-week baseline (mean over legal weeks): 4.88**
- best five weeks: GW36 11, GW28 9, GW30 9, GW26 7, GW35 7
- worst five weeks: GW22 2, GW23 1, GW29 1, GW31 0, GW38 0
- weeks where the armband fell to the vice/none: GW28, GW38

**Per-week reads** (legal weeks; * = double gameweek):

| gw | teams doubling | captain | doubled | TC2 read | rank/16 | pctile |
|---|---|---|---|---|---|---|
| GW20 | - | Erling Haaland | captain | 2 | 11 | 38% |
| GW21 | - | Erling Haaland | captain | 6 | 6 | 69% |
| GW22 | - | Erling Haaland | captain | 2 | 11 | 38% |
| GW23 | - | Erling Haaland | captain | 1 | 13 | 25% |
| GW24 | - | Erling Haaland | captain | 5 | 10 | 44% |
| GW25 | - | Jurriën Timber | captain | 6 | 6 | 69% |
| GW26* | 2 | Gabriel dos Santos Magalhães | captain | 7 | 4 | 81% |
| GW27 | - | Erling Haaland | captain | 6 | 6 | 69% |
| GW28 | - | Erling Haaland | vice | 9 | 2 | 94% |
| GW29 | - | Marc Guéhi | captain | 1 | 13 | 25% |
| GW30 | - | Gabriel dos Santos Magalhães | captain | 9 | 2 | 94% |
| GW31 | - | Malick Thiaw | captain | 0 | 15 | 12% |
| GW35 | - | Erling Haaland | captain | 7 | 4 | 81% |
| GW36* | 2 | Erling Haaland | captain | 11 | 1 | 100% |
| GW37 | - | Gabriel dos Santos Magalhães | captain | 6 | 6 | 69% |
| GW38 | - | Erling Haaland | none | 0 | 15 | 12% |

**Rule (i) -- largest double EXCLUDING the BB2 week (superseded the same day by (ii); kept as the comparison):**

- TIE: 2 doubles share the largest team count (2); the rule does not pick between them. All tied weeks reported.
- GW26 (DGW x2; captain Gabriel dos Santos Magalhães, doubled=captain): read **7**, rank 4/16, percentile 81%, vs random-week mean +2.12 (+0.61 sd)
- GW36 (DGW x2; captain Erling Haaland, doubled=captain): read **11**, rank 1/16, percentile 100%, vs random-week mean +6.12 (+1.77 sd)

**ADOPTED rule (ii) -- EARLIEST eligible second-half double (p4 log section 12c ii, 2026-08-24):**

- GW26 (DGW x2; captain Gabriel dos Santos Magalhães, doubled=captain): read **7**, rank 4/16, percentile 81%, vs random-week mean +2.12 (+0.61 sd); vs rule (i) week GW36 read 11: -4

**Old rule -- largest double overall = the BB2 week (ILLEGAL read, comparison only):**

- GW33 (DGW x6; captain Erling Haaland, doubled=captain): read 13; had it been legal it would rank 1/17 (percentile 100% of the legal weeks), vs random-week mean +8.12.

**Secondary -- does 'double' carry signal at all?** mean read on legal double weeks 9.00 (n=2) vs single weeks 4.29 (n=14): +4.71.

## Pooled view (three seasons, thin sample)

- rule-of-record weeks evaluated: 6 (ties counted separately); mean percentile 92%, percentiles 88%, 100%, 88%, 94%, 81%, 100%; mean gap vs random-week baseline +10.41 points (gaps +7.2, +19.3, +10.3, +17.3, +2.1, +6.1).
- **ADOPTED rule (ii), earliest eligible double** -- 2023-24 GW25 read 10 rank 5/16 pctile 75% (+2.2 vs mean); 2024-25 GW24 read 29 rank 1/16 pctile 100% (+19.3 vs mean); 2025-26 GW26 read 7 rank 4/16 pctile 81% (+2.1 vs mean). Mean percentile 85%; these are the costs of the choice, on the record, not figures of record.
- A rule indistinguishable from random sits at the 50th percentile with a zero mean gap. Three seasons cannot separate anything but a large effect: 3 seasons (6 candidate weeks once ties are listed; tied weeks within a season are NOT independent draws) of ~16 legal weeks each.

## Reading (data-driven; the caveats above are binding)

- ~~**Not a null on this evidence.** Every rule-of-record candidate in every season sits in the top quarter of its season's legal weeks (worst candidate per season: 88%, 88%, 81%); mean gap vs the random-week baseline +10.4 points. If the rule were picking blind, the chance that the worst candidate of all three seasons still lands in the top quarter is roughly 0.25^3 = 1.6%.~~ -- **SUPERSEDED 2026-08-24 (user review): wrong null.** That test asks "picked blind among 16 legal weeks", but the rule picks a DOUBLE, and doubles outscore singles by construction (two matches). Conditional on landing on a double, top-quartile is far likelier than 25%, so the 1.6% measures the existence of doubles, not the rule.
- **Established: play TC2 on a double.** Mean read on legal double weeks vs single weeks supports it in all three seasons: 2023-24 +9.2 vs +7.2; 2024-25 +25.3 vs +6.1; 2025-26 +9.0 vs +4.3.
- **NOT established: that the LARGEST double is the right choice among doubles.** The correct null is "largest double vs any double". On that comparison the rule fired in one of three seasons and tied in the other two (2023-24: GW37 read 15 vs the other eligible doubles 10/4/8; 2024-25: TIE, rule selected nothing; 2025-26: TIE, rule selected nothing). One season is not evidence.
- **Weight caveat:** the largest single read in the sweep (GW24 2024-25, 29, Salah) comes from the season whose baseline is a 97th-percentile draw with a 13.8% Salah concentration (Logs/why_2024_25_log.md). It should not carry weight.
- **The mechanism is the ordinary one, not a subtle edge:** a double gives the captain two matches. Mean read on legal double weeks vs single weeks: 2023-24 +9.2 vs +7.2; 2024-25 +25.3 vs +6.1; 2025-26 +9.0 vs +4.3. Three seasons of realised captain points on one path each.
- **The old rule's week (BB2) is a poor TC week on these paths even ignoring legality:** its read ranks 2023-24 13/17 (captain Mohamed Salah, read 3); 2024-25 9/17 (captain David Raya Martin, read 7); 2025-26 1/17 (captain Erling Haaland, read 13). The bench-aware Bench Boost objective (bench weight 1.0 that week) reshapes the squad for the bench and degrades the captain choice -- the biggest-DGW week is exactly where the two chips fight over the same squad.
- **Tie-break ADOPTED (p4 log section 12c ii): the EARLIEST eligible second-half double.** Rule (i) selected nothing in two of three seasons (ties among 2-team doubles). The predicted-captain selector proposed the same day was checked for computability BEFORE adoption (next section) and refused -- not computable at decision time. Earliest is structural: computable from the calendar alone, always selects, matches what is established (play a double) and no more, and removes the unpriced cost of holding out for a better double that may never come. It is a tie-break of ignorance, not skill; it exists so the rule terminates. Its cost on these paths: 2023-24 GW25 read 10 (rank 5/16); 2024-25 GW24 read 29 (rank 1/16); 2025-26 GW26 read 7 (rank 4/16).
- **What would change the reading:** a fourth and fifth season (2021-22/2022-23 are not portable, KNOWN_ISSUES #11), or a policy-level test where TC2 is scheduled in-sim on the rule's week with the captain chosen at the deadline -- i.e. a simulation, deliberately not run here.

## Tie-break computability check (2026-08-24) -- the proposed rule is NOT computable as written

Proposed (user, 2026-08-24): *TC2 = a second-half double, excluding weeks already holding a chip; among eligible doubles, the week where the intended captain's predicted points at that week's own cutoff are highest.* Checked here BEFORE adoption, per instruction: can the selector be computed at decision time? Method in `eval/tc2_tiebreak_computability.py` (docstring). Frozen base_wc2 paths; no simulations.

### 2023-24 -- eligible doubles [25, 28, 35, 37], chip weeks [29, 32, 34]

- Candidates span GW25..GW37 = 12 gameweeks; the horizon sees 5 ahead. From the first candidate's deadline the later candidates [35, 37] are **invisible** -- their own-cutoff predictions do not exist yet and no horizon projection reaches them.

| candidate | captain at own cutoff | own-cutoff e_points | realised read | visible from earlier candidates (projection, step) |
|---|---|---|---|---|
| GW25 | Erling Haaland | 15.59 | 10 | not visible from any earlier candidate |
| GW28 | Norberto Murara Neto | 10.78 | 4 | from GW25: 7.02 (Ross Barkley, step 3) |
| GW35 | Nicolas Jackson | 9.31 | 8 | not visible from any earlier candidate |
| GW37 | Erling Haaland | 14.93 | 15 | from GW35: 9.88 (Nicolas Jackson, step 2) |

- literal selector (argmax of own-cutoff values -- needs every cutoff, i.e. hindsight): **GW25** (read 10)
- sequential decision-time approximation (play when own value >= every visible later projection): **GW25** (read 10)
- sweep's best-read week over ALL legal weeks (pure hindsight): GW20 (read 16)
- step-k projected captain points vs the eventual own-cutoff value, all legal H2 weeks (corr / MAE / same-captain rate): k=1: 0.81 / 1.13 / 50%; k=2: 0.61 / 1.70 / 25%; k=3: 0.75 / 1.53 / 25%; k=4: 0.62 / 1.84 / 12%; k=5: 0.73 / 1.39 / 12%

### 2024-25 -- eligible doubles [24, 25, 32], chip weeks [29, 31, 33]

- Candidates span GW24..GW32 = 8 gameweeks; the horizon sees 5 ahead. From the first candidate's deadline the later candidates [32] are **invisible** -- their own-cutoff predictions do not exist yet and no horizon projection reaches them.

| candidate | captain at own cutoff | own-cutoff e_points | realised read | visible from earlier candidates (projection, step) |
|---|---|---|---|---|
| GW24 | Mohamed Salah | 16.41 | 29 | not visible from any earlier candidate |
| GW25 | Mohamed Salah | 18.01 | 20 | from GW24: 19.16 (Mohamed Salah, step 1) |
| GW32 | Harvey Barnes | 11.27 | 27 | not visible from any earlier candidate |

- literal selector (argmax of own-cutoff values -- needs every cutoff, i.e. hindsight): **GW25** (read 20)
- sequential decision-time approximation (play when own value >= every visible later projection): **GW25** (read 20)
- sweep's best-read week over ALL legal weeks (pure hindsight): GW24 (read 29)
- step-k projected captain points vs the eventual own-cutoff value, all legal H2 weeks (corr / MAE / same-captain rate): k=1: 0.94 / 0.80 / 81%; k=2: 0.95 / 0.79 / 81%; k=3: 0.91 / 1.01 / 81%; k=4: 0.96 / 0.78 / 75%; k=5: 0.91 / 1.02 / 62%

### 2025-26 -- eligible doubles [26, 36], chip weeks [32, 33, 34]

- Candidates span GW26..GW36 = 10 gameweeks; the horizon sees 5 ahead. From the first candidate's deadline the later candidates [36] are **invisible** -- their own-cutoff predictions do not exist yet and no horizon projection reaches them.

| candidate | captain at own cutoff | own-cutoff e_points | realised read | visible from earlier candidates (projection, step) |
|---|---|---|---|---|
| GW26 | Gabriel dos Santos Magalhães | 12.34 | 7 | not visible from any earlier candidate |
| GW36 | Erling Haaland | 16.06 | 11 | not visible from any earlier candidate |

- literal selector (argmax of own-cutoff values -- needs every cutoff, i.e. hindsight): **GW36** (read 11)
- sequential decision-time approximation (play when own value >= every visible later projection): **GW26** (read 7)
- sweep's best-read week over ALL legal weeks (pure hindsight): GW36 (read 11)
- step-k projected captain points vs the eventual own-cutoff value, all legal H2 weeks (corr / MAE / same-captain rate): k=1: 0.93 / 0.88 / 81%; k=2: 0.25 / 1.50 / 69%; k=3: 0.90 / 1.10 / 69%; k=4: 0.87 / 1.17 / 50%; k=5: 0.04 / 1.61 / 56%

**Verdict.** The selector as written -- compare candidates by their own-cutoff predictions -- is **not computable at decision time**: in every season the eligible doubles span more than the horizon, so the comparison can only be made after the last candidate's cutoff has passed. It is a hindsight rule dressed as a prediction rule. The computable variant is a sequential stopping rule using horizon projections for the candidates it can see (invisible ones cannot enter the comparison); its picks differ from the literal selector where a later candidate is invisible (literal GW25, GW25, GW36; sequential GW25, GW25, GW26; sweep best-read GW20, GW24, GW36). Neither selector simply reproduces the hindsight winner, which is the right sign; but the projections degrade with step (same-captain rate falls to 12-62% by step 5 in two of three seasons) and, decisively, candidates beyond the horizon are not visible at all. **Not adopted.** The tie-break adopted instead (p4 log section 12c (ii), 2026-08-24) is structural: TC2 = the EARLIEST eligible second-half double, computable from the fixture calendar alone. A decision-time PREDICTIVE TC2 rule needs a stopping formulation and a simulation to value it, which this study deliberately does not run.

## What this is not

- Not a figure: no read here enters the chip-inclusive headline. The headline scores TC2 as zero by decision.
- Not a predictive test: the reads are realised captain points on one path, seen after the fact. A rule that ranks well here on three draws has demonstrated compatibility with the data, not skill.
- The doubles inventory is thinner than the season count: two of three seasons have no second-largest double above two teams, so the rule ties and does not pick.
