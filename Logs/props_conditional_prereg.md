# Player-prop odds — CONDITIONAL-RATE SPECIFICATION: PRE-REGISTRATION (written 2026-08-25, before building)

Companion to `Logs/props_prereg.md` (sections 1–8 and ADDENDA 1–3), which governs the unconditional blend. This
document governs a second specification. Nothing in it may be changed after a result is seen; amendments go in a
dated addendum at the end. Nothing from 2025-26 has been read and nothing was read in writing this. The holdout is
spent once, on whichever specification is believed at that point; neither has been run.

## 0. Why a second specification

The unconditional blend λ = w·λ_mkt + (1 − w)·λ_model mixes a market rate that is CONDITIONAL on the player
appearing with a model rate that is UNCONDITIONAL (the incumbent's `e_goals` already carries `minutes_frac`, i.e.
`p_start`/`p60`). The calibration ladder of the market alone at m = 1.517 (tuning log, re-tune section) is the
symptom: likely starters 1.00, uncertain 1.13, squad-relevant 0.92, written-off **7.33**. A price that does not
carry appearance risk is exactly right where the player surely plays and wildly high where he surely does not.

## 1. The premise, verified from the books' own rules before assuming it

The premise: at the books in the consensus, an anytime-goalscorer bet on a player who does not appear is VOID
(stake returned), so the quoted price is P(scores | appears), not P(scores). Checked 2026-08-25 against each
book's published house rules. Two conditioning events exist, and the books DIFFER:

| book | share of consensus | rule (verbatim where obtained) | conditioning event | source |
|---|---|---|---|---|
| DraftKings | 2024-25: 252 fx; 2025-26: 374 | "First/Last/Anytime/Next Goalscorer — Bets on players not taking part in the match will be void." | takes part (any minutes) | DK House Rules (MA, 8.1.24), p. 34 — PRIMARY |
| BetMGM | 160; 202 | "If a player doesn't enter the field of play during the game at all, then this player is deemed a 'non-runner' and all bets on this player are void." | takes part | help.nv.betmgm.com soccer rules — PRIMARY |
| Bovada | 305; 279 | "Anytime Goalscorer: Players who do not play any part will be graded as 'No Action'." | takes part | bovada.lv soccer betting rules — PRIMARY |
| BetRivers | 308; 357 | First/Next: "Stakes will be refunded on players who do not take part in the match…"; and "Unless otherwise specified… all other goal-related bets will require the listed player(s) to play from the start of the match to be valid." | **STARTS** (anytime falls under "all other goal-related bets") | BetRivers MD House Rules (10.26.23), soccer §5 — PRIMARY |
| MyBookie | 2025-26 only: 53 | "For Soccer only, if any player selected for any bet type does not start the game, then all bets on that player will be void." | **STARTS** | mybookie.ag sportsbook rules — PRIMARY |
| FanDuel | 304; 375 | House rules (NY, via Tioga Downs) contain First Goalscorer / Scorecast / Wincast participation clauses ("players either not taking part in the game…") but NO anytime-goalscorer clause; general soccer player-prop rule not stated. | **UNVERIFIED** — assigned "takes part" (the industry-standard and majority rule), flagged | — |
| 1xBet | 308; 376 | Rules site exposes navigation only; football goalscorer text not retrievable; no primary quote. | **UNVERIFIED** — assigned "takes part", flagged | — |
| Pinnacle | dropped under ADDENDUM 1 | — | — | — |

A secondary source (a BetMGM Michigan help article) claims pre-match anytime bets require a START; it contradicts
BetMGM's own NV house rules above and could not be retrieved; the primary governs. **Conclusion:** the premise
holds at every book that could be verified (5 of 7), but with two conditioning events — participation at three
books, a start at two — and two books unverified. The specification therefore conditions PER BOOK, and the
unverified assignment is a stated limitation, not a fact.

## 2. Specification

Per book b, per fixture, after the ADDENDUM 1 shared-set scaling gives p_b (the book's margin-adjusted implied
probability):

    P_b(appears)  = p_play_any   if b conditions on participation   (DraftKings, BetMGM, Bovada; FanDuel, 1xBet assigned)
                  = p_start      if b conditions on a start          (BetRivers, MyBookie)
    p_b,uncond    = p_b · P_b(appears) / m
    p_mkt         = mean over books of p_b,uncond          (equal weight, merged by element, as before)
    λ_mkt         = −ln(1 − p_mkt)                          (Σ over the player's fixtures in a double)
    λ             = w · λ_mkt + (1 − w) · λ_model

**Which appearance quantity and why.** Both come from the existing minutes model in the walkforward
(`p_start`; `p_play_any = p_start + (1 − p_start)·0.30`, `squad/assembly.py`). The conditioning event is a
property of each book's rule, so the quantity is chosen per book, not globally: P(takes part) is `p_play_any`,
P(starts) is `p_start`. No composite is invented. Known weakness, written down now: `p_play_any` carries a flat
0.30 sub-appearance floor, so on the written-off band (mean `p_start` 0.057) it is 0.340 — almost certainly too
high for players ruled out. That is a defect of the minutes model, not of this specification, and §4 separates the
two.

**Form.** The conditioning is applied on the PROBABILITY scale — P(scores) = P(appears)·P(scores | appears) is an
identity — and converted to a rate afterwards. The rate-scale form λ_cond·P(appears) sketched in the request
differs at second order (≤ 1% at p ≤ 0.3) and is not used; stated so the choice is on record.

**Everything else is inherited unchanged** from props_prereg.md: outfield only (amendment 2); partial doubles
excluded with the count reported (amendment 3); population = single-fixture outfield player-gameweeks in the
starter band (own-cutoff e_minutes ≥ 60) the market prices, incumbent scored on the same rows; step 0 only;
partitions likely starters (p_start ≥ .75) and squad-relevant (top 30 by own-cutoff e_points); coverage gate 80%.

**Build requirement.** `eval/build_props_consensus.py` must emit per-book scaled probabilities
(`props_consensus_book_{season}.parquet`: event_id, element, book, p_adj) so the per-book conditioning can be
applied at measurement time; the consensus itself is unchanged. Two uniform variants — all books at `p_play_any`,
all at `p_start` — are DIAGNOSTICS ONLY (§4), reported alongside and never selectable.

## 3. Endpoint and pass condition — UNCHANGED from props_prereg.md §2–§3

Primary: pooled Spearman(λ, realised goals) at step 0 on likely starters and squad-relevant. Pass: (1) ≥ +0.020 on
BOTH, pooled over 2024-25 GW8–38 + 2025-26, and non-negative in each season; (2) written-off band (p_start < .25,
no e_minutes floor) not worse by more than 0.020; (3) Brier on P(≥ 1) not worse on either decision partition. Not
softened. Secondary endpoints as §4 of the parent document.

## 4. Predictions, stated before anything is built (the premise is falsifiable and this is how)

**P1 — the premise test, independent of the minutes model (tuning season, realised minutes used as a
diagnostic).** On written-off rows where the player DID take part (realised minutes > 0), compare the market's
unconditional-as-quoted p/m (m = 1.517) with the realised P(≥ 1) on those rows. If the price is conditional on
appearing, that ratio should be near 1 or above it (short sub appearances score less than a typical appearance,
so above 1 is expected); if the price were already unconditional, the ratio would be near P(appears) on that band
(≈ 0.13–0.20 — the 1/7.33 signature). **Thresholds fixed now: ratio ≥ 0.7 → premise supported; < 0.5 → premise
WRONG → the specification is ABANDONED, not patched; 0.5–0.7 → indeterminate, stop and report.** The same ratio on
started rows is reported for the start-conditioned reading. Likely-starter rows are the control: ≈ 1.00 by
construction.

**P2 — the spec-level collapse, which is a JOINT test of the premise and the minutes model's P(appears).** Written-
off band ratio after conditioning, from the cutoff-side means (p/m 0.0933 → realised 0.0127; mean p_play_any
0.340, mean p_start 0.057): all-`p_play_any` → ≈ 7.33 × 0.340 ≈ **2.5**; all-`p_start` → ≈ 7.33 × 0.057 ≈
**0.42**; the per-book specification lands between, nearer 2.5 (three-to-two books condition on participation and
the two unverified books are assigned to it). **So the ratio is NOT predicted to reach 1 with the existing minutes
model** — it is bounded by the 0.30 sub floor — and a residual of ~2.5 is the minutes model's miscalibration on
that band, not the premise failing. What WOULD falsify the premise at spec level: the written-off ratio staying
above ~5 under every variant. The realised appearance rate on the written-off band is reported next to its
predicted 0.340 / 0.057 so the two effects can be told apart.

**P3 — the likely-starter band barely moves.** Mean p_play_any there is 0.927 with little spread, so conditioning
is close to a constant rescale; m recalibrates to ≈ 1.517 × 0.93 ≈ 1.41 and the decision-partition Spearman should
move by less than 0.005 from the unconditional specification. **Condition (1) is therefore NOT expected to be
repaired by this specification** — likely starters sat at +0.0085 against a +0.020 bar unconditionally, and the
conditional form acts on the written-off band, i.e. on condition (2). If P1 supports the premise, the prediction is
that condition (2) recovers from −0.028 to within −0.020 and conditions (1)/(3) are unchanged. That is stated now so
a pass on (2) cannot later be read as a pass overall.

## 5. Tuning protocol — same protocol, same guard

- 2024-25 GW8–38 only. 2025-26 sealed; no file from it is opened by the tuning path.
- m by CALIBRATION on the likely-starter partition, market alone, on the conditioned quantity (amendment 4 form:
  m = mean over rows of mean_b[p_b · P_b(appears)] / mean realised P(≥ 1)), rounded to 3 dp.
- w = 0.75 BY PRIOR (amendment 5). The w surface {0, .25, .5, .75, 1} at that m is reported for information. The
  prior is departed from ONLY if all of: the rank argmax is unique, differs from 0.75, beats 0.75 by ≥ 0.020 in
  MEAN, and survives leave-one-out of every top-5 contributor on both decision partitions. Stated now; expected
  not to trigger.
- Salah guard and leave-one-out re-run the whole procedure (m recalibrated), as in the re-tune.
- The four §3 conditions are printed for the tuning season and recorded, not evidence.
- The chosen pair is written into a dated `## PRE-REGISTERED VALUE` section of THIS file as the exact line
  `spec = conditional: w = …, m = …`. The measurement script's `--spec conditional --holdout W M` refuses unless
  that exact line is present in the LAST such section of this file; the unconditional guard in props_prereg.md is
  untouched. Verified both ways before the sealed run, as before.
- 2025-26 is run ONCE, for ONE specification, and appended whatever it shows.

## 6. Limitations written down now

1. Two consensus books (FanDuel, 1xBet — 612 of 1,637 = 37% of 2024-25 book-fixtures) have an ASSIGNED conditioning event. If a
   later primary source shows either conditions on a start, the per-book table is amended by dated addendum and
   the build re-run before any holdout.
2. The minutes model's P(appears) is not calibrated on the written-off band (the 0.30 floor). The specification
   inherits that; §4 P2 says how it shows up and how it is distinguished from the premise.
3. Everything in props_prereg.md §7 (1.7 seasons; US books not the live books; 2024-25 a 97th-percentile draw;
   crosswalk risk; one snapshot) applies unchanged.
4. Goalkeepers remain outside the feature (amendment 2).

---

## RESULTS — P1, the premise test (2026-08-26). Method as §4 P1; thresholds as fixed there. No 2025-26 file read.

Script: `eval/measure_props_premise.py`. Per-book probabilities recomputed from the raw boards with the builder's exact scaling and asserted to reproduce the stored consensus. Output of record (verbatim):

```
P1 -- premise test on 2024-25 GW8-38, m = 1.517 (pre-registered scalar). No 2025-26 file read. Per-book recomputation reproduces the stored consensus: ASSERTED.
  written-off band (p_start < .25), outfield singles the market prices, partial doubles excluded: n 4,716
  realised appearance rate on the band: took part 0.244 (n 1153); started 0.064 (n 304); substitute 0.180 (n 849).  Minutes-model means on the band: p_start 0.057, p_play_any 0.340  [for P2]
  as-quoted calibration on ALL band rows (the 7.33 signature): mean p/m 0.0933 vs realised 0.0127 -> ratio 7.33

  HEADLINE (consensus price):
    written-off, TOOK PART (minutes > 0)                 n  1153  mean p/m 0.1102  realised P(>=1) 0.0520  ratio 2.12
      of which STARTED                                   n   304  mean p/m 0.0928  realised P(>=1) 0.0855  ratio 1.08
      of which SUBSTITUTE appearance                     n   849  mean p/m 0.1164  realised P(>=1) 0.0400  ratio 2.91
    control: likely starters, all rows (~1.00 by construction) n  3930  mean p/m 0.1076  realised P(>=1) 0.1076  ratio 1.00

  P1 RATIO = 2.12 (n = 1153)  ->  PREMISE SUPPORTED (>= 0.7)

  BY BOOK (each book's own scaled price on the rows IT priced; same m). Written-off took-part ratio, then started / substitute, then the likely-starter control:
    book           n played  ratio | n start  ratio | n sub  ratio |  LS n LS ratio | mean p (band, played) 
    draftkings          925   1.86 |     245   0.99 |   680   2.51 |  3168     1.00 | 0.1650   [participation (DK/BetMGM/Bovada)]
    betmgm              554   2.12 |     136   1.28 |   418   2.51 |  2022     1.04 | 0.1623   [participation (DK/BetMGM/Bovada)]
    bovada             1103   2.12 |     291   1.09 |   812   2.92 |  3915     1.00 | 0.1659   [participation (DK/BetMGM/Bovada)]
    betrivers           604   1.89 |     205   0.98 |   399   3.18 |  3886     1.01 | 0.1712   [start (BetRivers)]
    fanduel            1112   2.16 |     295   1.09 |   817   2.98 |  3873     0.98 | 0.1765   [unverified (FanDuel)]
    onexbet            1103   2.29 |     297   1.08 |   806   3.45 |  3889     0.99 | 0.1667   [unverified (1xBet)]

  BY GROUP (rows pooled across the group's books):
    participation (DK/BetMGM/Bovada)   played n  2582 ratio  2.02 | started n  672 ratio  1.08 | sub n 1910 ratio  2.67
    start (BetRivers)                  played n   604 ratio  1.89 | started n  205 ratio  0.98 | sub n  399 ratio  3.18
    unverified (FanDuel)               played n  1112 ratio  2.16 | started n  295 ratio  1.09 | sub n  817 ratio  2.98
    unverified (1xBet)                 played n  1103 ratio  2.29 | started n  297 ratio  1.08 | sub n  806 ratio  3.45

  PRICE LEVEL on the same written-off rows (book / participation-group mean, same (gw, element)); a start-conditioned price should sit ABOVE a participation-conditioned one on fringe players:
    betrivers      n  1187  geometric mean ratio 1.037  (median 1.028; on sub rows n 399 1.007; on started rows n 205 1.017)   [start (BetRivers)]
    fanduel        n  3481  geometric mean ratio 1.029  (median 1.018; on sub rows n 815 1.056; on started rows n 294 0.996)   [unverified (FanDuel)]
    onexbet        n  3565  geometric mean ratio 1.067  (median 1.046; on sub rows n 792 1.045; on started rows n 292 1.034)   [unverified (1xBet)]
    draftkings     n  2873  geometric mean ratio 0.979  (median 0.993; on sub rows n 680 0.986; on started rows n 245 0.974)   [participation (DK/BetMGM/Bovada)]
    betmgm         n  1805  geometric mean ratio 0.985  (median 0.992; on sub rows n 418 0.990; on started rows n 136 0.983)   [participation (DK/BetMGM/Bovada)]
    bovada         n  3473  geometric mean ratio 1.022  (median 1.004; on sub rows n 812 1.015; on started rows n 291 1.026)   [participation (DK/BetMGM/Bovada)]
```

---

## RESULTS — build and tuning on 2024-25 (2026-08-26). Method as §2 and §5; no 2025-26 file read.

Build: `eval/build_props_consensus.py` now emits `props_consensus_book_{season}.parquet` (per-book scaled
probabilities; asserted: their mean reproduces the stored consensus). Built for 2024-25 only (`--seasons 2024-25`);
the 2025-26 per-book file is generated at holdout time by the same code. Measurement:
`eval/measure_props_endpoint.py --spec conditional --tune`, which substitutes the conditioned consensus
probability for the unconditional one and reuses every amendment-4/5 step unchanged.

### Headline

- **m = 1.396** by calibration on the conditioned quantity (0.1501 / 0.1075, n = 3,924 likely starters) —
  P3 predicted ≈ 1.41.
- **w = 0.75 by prior; the departure rule did not trigger.** The rank argmax IS 0.75 (mean 0.2957 vs 0.2949 at
  w = 1); Salah guard: m = 1.416, argmax 0.75, rule still not triggered; whole-procedure leave-one-out of the 18
  top contributors: 17 leave the argmax at 0.75, dropping Wissa moves it to w = 1 by 0.0007. The prior stands.
- **P2: written-off ratio 7.33 → 2.59.** The pre-registered line was ≤ ~2.5 with the 0.30 floor as-is: **missed
  by 0.09** — nowhere near the ~5 that would falsify the premise. The residual is the minutes model's floor, as
  predicted: with the floor refit on the band (0.30 → 0.199, DIAGNOSIS ONLY, not adopted) the ratio is 1.89;
  with FanDuel and 1xBet assigned to start books, 1.37; all-`p_start` 0.48 (overshoots, as predicted).
- **§3 on the tuning season (NOT evidence): (1) FAIL — likely starters +0.0094 (< +0.020), squad-relevant
  +0.0206; (2) PASS — written-off −0.0165 (was −0.0283 unconditional); (3) PASS — Brier 0.0879 → 0.0861 and
  0.1677 → 0.1585. Overall FAIL**, exactly the outcome §4 P3 said to expect: the specification repairs condition
  (2) and does nothing for condition (1), which has now failed at +0.0087, +0.0078, +0.0085 and +0.0094 across
  four specifications.

### Influence of the two unverified books (FanDuel, 1xBet; 37% of 2024-25 book-fixtures)

| variant | m | written-off ratio | Δ likely | Δ squad | Δ written-off | (1) | (2) | (3) |
|---|---|---|---|---|---|---|---|---|
| adopted: unverified → participation | 1.396 | 2.59 | +0.0094 | +0.0206 | −0.0165 | FAIL | PASS | PASS |
| sensitivity: unverified → start | 1.378 | 1.37 | +0.0094 | +0.0205 | −0.0008 | FAIL | PASS | PASS |
| diag: floor refit 0.199 (not adopted) | 1.383 | 1.89 | +0.0095 | +0.0203 | −0.0104 | FAIL | PASS | PASS |
| diag: all-`p_play_any` (not selectable) | 1.405 | 2.70 | +0.0094 | +0.0207 | −0.0134 | FAIL | PASS | PASS |
| diag: all-`p_start` (not selectable) | 1.357 | 0.48 | +0.0095 | +0.0200 | +0.0008 | FAIL | PASS | PASS |

The assignment changes **no verdict** and leaves the decision partitions untouched (±0.0001), but it moves the
written-off band by 0.016 — the size of the pass margin — and the P2 ratio from 2.59 to 1.37. **The written-off
numbers of this specification therefore carry the unverified assignment as a limitation**; the decision-partition
numbers do not. It cannot be resolved from behaviour (P1) and is resolved only by a primary rules source.

### Output of record (verbatim)

```
CONDITIONAL SPECIFICATION -- tuning on 2024-25 GW8-38 only (no 2025-26 file read). Unverified books (FanDuel, 1xBet) assigned: participation. Outfield singles in window: 19,710; priced 11,606; partial doubles flagged and excluded: 24.
coverage: likely starters 90.3% of 4347; squad-relevant 97.5% of 638; uncertain 88.3% of 409; full starter band 90.1% of 4756; written off (no e_minutes floor) 40.0% of 11788

m by CALIBRATION on likely starters, market alone, on the CONDITIONED quantity: mean 0.1501 / realised 0.1075 -> m = 1.396 (n = 3924)
  post-hoc calibration of the conditioned market alone at this m, by partition (mean p_cond/m vs realised):
    likely starters                    n  3924  mean p/m 0.1076  realised 0.1075  ratio 1.000
    squad-relevant                     n   622  mean p/m 0.2101  realised 0.2267  ratio 0.927
    uncertain                          n   361  mean p/m 0.0968  realised 0.0997  ratio 0.970
    full starter band                  n  4285  mean p/m 0.1066  realised 0.1069  ratio 0.998
    written off (no e_minutes floor)   n  4716  mean p/m 0.0330  realised 0.0127  ratio 2.592

w SURFACE at m = 1.396 (information; w is set by prior unless the departure rule triggers)
      w     m |   likely    squad     MEAN | uncertain  starter writtenoff
   0.00  1.40 |   0.2750   0.2866   0.2808 |    0.3172   0.2784     0.1401
   0.25  1.40 |   0.2791   0.2936   0.2863 |    0.3257   0.2827     0.1369
   0.50  1.40 |   0.2822   0.3018   0.2920 |    0.3312   0.2861     0.1301
   0.75  1.40 |   0.2843   0.3071   0.2957 |    0.3371   0.2883     0.1236
   1.00  1.40 |   0.2840   0.3057   0.2949 |    0.3370   0.2881     0.1169

DEPARTURE RULE: rank argmax w = 0.75 (mean 0.2957) vs prior w = 0.75 (mean 0.2957); gap +0.0000; unique True; differs False; beats by >= 0.020 False
  -> does NOT depart: w = 0.75 (by PRIOR), m = 1.396

SALAH GUARD (whole procedure without him): m = 1.416; rank argmax w = 0.75 (mean 0.2739) vs 0.75 (mean 0.2739), gap +0.0000 -> departure rule still does not trigger
  whole-procedure leave-one-out of the top-5 contributors at the chosen pair (m recalibrated; rank argmax reported):
    likely starters: rho(candidate) 0.2843, delta +0.0094; top-5 by rho share: Mohamed Salah +0.0185, Alexander Isak +0.0143, Yoane Wissa +0.0122, Erling Haaland +0.0106, Chris Wood +0.0088
      drop Mohamed Salah                    -> m 1.416, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Alexander Isak                   -> m 1.416, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Yoane Wissa                      -> m 1.418, rank argmax w = 1, gap to 0.75 +0.0007
      drop Erling Haaland                   -> m 1.399, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Chris Wood                       -> m 1.410, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Bryan Mbeumo                     -> m 1.408, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Moisés Caicedo Corozo            -> m 1.392, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Sander Berge                     -> m 1.391, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Matheus Santos Carneiro Da Cunha -> m 1.412, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Max Kilman                       -> m 1.392, rank argmax w = 0.75, gap to 0.75 +0.0000
    squad-relevant: rho(candidate) 0.3071, delta +0.0206; top-5 by rho share: Mohamed Salah +0.0562, Alexander Isak +0.0359, Erling Haaland +0.0253, William Saliba +0.0140, Joško Gvardiol +0.0124
      drop Mohamed Salah                    -> m 1.416, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Alexander Isak                   -> m 1.416, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Erling Haaland                   -> m 1.399, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop William Saliba                   -> m 1.398, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Joško Gvardiol                   -> m 1.398, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Jarrod Bowen                     -> m 1.412, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Gabriel dos Santos Magalhães     -> m 1.393, rank argmax w = 0.75, gap to 0.75 +0.0000
      drop Amad Diallo                      -> m 1.398, rank argmax w = 0.75, gap to 0.75 +0.0000

P2 -- written-off band ratio after conditioning at m = 1.396: mean p/m 0.0330 vs realised 0.0127 -> 2.59 (n 4716; was 7.33 unconditional). Pre-registered: <= ~2.5 expected with the 0.30 floor; > ~5 under every variant falsifies the premise. -> NOT MET (> 2.5)

PASS CONDITIONS (section 3, UNCHANGED) on 2024-25 at spec = conditional: w = 0.75, m = 1.396 -- tuning season, NOT evidence:
  (1) +0.020 on BOTH decision partitions: likely +0.0094, squad +0.0206 -> FAIL; non-negative this season: yes
  (2) written-off band not worse by > 0.020: -0.0165 -> PASS
  (3) Brier not worse on either decision partition: likely starters 0.0879->0.0861; squad-relevant 0.1677->0.1585 -> PASS
  overall on this season: FAIL

--- 2024-25 tuning season (NOT evidence), conditional spec: w = 0.75, m = 1.396 vs incumbent (w = 0) on the common population; partial doubles excluded: 24 ---
  partition                               n   Spearman inc  Spearman cand    delta
  likely starters                      3924         0.2750         0.2843  +0.0094
  squad-relevant                        622         0.2866         0.3071  +0.0206
  uncertain                             361         0.3172         0.3371  +0.0199
  full starter band                    4285         0.2784         0.2883  +0.0100
  written off (no e_minutes floor)     4716         0.1401         0.1236  -0.0165
  secondary (incumbent -> candidate):
    likely starters                    Brier 0.0879->0.0861  logloss 0.3032->0.2974  mean pred/realised 0.122/0.108->0.112/0.108  MAE 0.1986->0.1923  RMSE 0.3430->0.3333  MAE by outcome 0/1/2+ 0.125/0.735/1.671 -> 0.112/0.781/1.774
    squad-relevant                     Brier 0.1677->0.1585  logloss 0.5080->0.4859  mean pred/realised 0.306/0.227->0.237/0.227  MAE 0.4215->0.3743  RMSE 0.5324->0.4951  MAE by outcome 0/1/2+ 0.355/0.505/1.512 -> 0.255/0.633/1.675
    uncertain                          Brier 0.0793->0.0790  logloss 0.2707->0.2704  mean pred/realised 0.113/0.100->0.101/0.100  MAE 0.1835->0.1776  RMSE 0.3178->0.3146  MAE by outcome 0/1/2+ 0.113/0.739/1.702 -> 0.100/0.801/1.749
    full starter band                  Brier 0.0872->0.0855  logloss 0.3004->0.2951  mean pred/realised 0.121/0.107->0.111/0.107  MAE 0.1973->0.1910  RMSE 0.3410->0.3317  MAE by outcome 0/1/2+ 0.124/0.735/1.674 -> 0.111/0.782/1.772
    written off (no e_minutes floor)   Brier 0.0121->0.0124  logloss 0.0561->0.0657  mean pred/realised 0.013/0.013->0.028/0.013  MAE 0.0254->0.0408  RMSE 0.1244->0.1258  MAE by outcome 0/1/2+ 0.013/0.945/2.104 -> 0.028/0.939/2.142
  reliability deciles, full starter band (incumbent | candidate): n, mean predicted P(>=1), realised
    d0: n  429  0.016/0.023 | 0.029/0.028
    d1: n  428  0.026/0.030 | 0.039/0.026
    d2: n  429  0.036/0.040 | 0.046/0.035
    d3: n  428  0.050/0.028 | 0.056/0.033
    d4: n  429  0.066/0.044 | 0.068/0.047
    d5: n  428  0.088/0.084 | 0.087/0.070
    d6: n  428  0.122/0.119 | 0.113/0.112
    d7: n  429  0.167/0.170 | 0.153/0.161
    d8: n  428  0.235/0.213 | 0.205/0.227
    d9: n  429  0.406/0.317 | 0.312/0.331

DIAGNOSIS (not adopted; a minutes-model change needing its own pre-registration): on the written-off band p_play_any 0.340 vs realised took-part 0.244 (p_start 0.057 vs realised started -- see P1). Refitting the flat substitute floor so the band mean matches: 0.30 -> 0.199.
  variant                                            m | WO ratio | section-3 deltas at w = 0.75 | conditions
  ADOPTED: per-book, floor 0.30, unverified=participation m 1.396 | WO ratio  2.59 | d likely +0.0094 squad +0.0206 uncertain +0.0199 WO -0.0165 | (1) FAIL (2) PASS (3) PASS
  diag: per-book, floor refit 0.199            m 1.383 | WO ratio  1.89 | d likely +0.0095 squad +0.0203 uncertain +0.0199 WO -0.0104 | (1) FAIL (2) PASS (3) PASS
  sensitivity: unverified books -> start       m 1.378 | WO ratio  1.37 | d likely +0.0094 squad +0.0205 uncertain +0.0199 WO -0.0008 | (1) FAIL (2) PASS (3) PASS
  diag: all-p_play_any (not selectable)        m 1.405 | WO ratio  2.70 | d likely +0.0094 squad +0.0207 uncertain +0.0209 WO -0.0134 | (1) FAIL (2) PASS (3) PASS
  diag: all-p_start (not selectable)           m 1.357 | WO ratio  0.48 | d likely +0.0095 squad +0.0200 uncertain +0.0199 WO +0.0008 | (1) FAIL (2) PASS (3) PASS

Write 'spec = conditional: w = 0.75, m = 1.396' into a dated '## PRE-REGISTERED VALUE' section of Logs/props_conditional_prereg.md BEFORE any --spec conditional --holdout. 2025-26 has not been read; its per-book file is generated at holdout time by the same builder code.
```

---

## PRE-REGISTERED VALUE (2026-08-26; written before any 2025-26 file was opened; the conditional guard reads the LAST such heading in THIS file)

spec = conditional: w = 0.75, m = 1.396

w = 0.75 BY PRIOR (amendment 5; the departure rule did not trigger). m = 1.396 by calibration on the conditioned
quantity (amendment 4 form). Unverified books assigned "takes part" (the adopted variant above). On the tuning
season this pair FAILS §3 overall — condition (1) at +0.0094 on likely starters — with (2) and (3) passing; recorded
here so the miss is on file before the sealed season is spent. P2 landed at 2.59 against ≤ ~2.5 (miss of 0.09;
residual = the minutes model's 0.30 substitute floor, not the premise).

The sealed season is run ONCE, for ONE specification, and has not been run for either:
`uv run python eval/measure_props_endpoint.py --spec conditional --holdout 0.75 1.396` (requires
`props_consensus_book_2025-26.parquet`, generated at that time by `eval/build_props_consensus.py --seasons 2025-26`).

---

## CLOSE-OUT (2026-08-26) — NOT ADOPTED

The conditional specification is the correct form (premise verified from house rules and by P1; condition (2)
repaired) and still misses condition (1) on likely starters at +0.0094 against +0.020 — the fourth miss at the same
value. Not adopted; the value line above stands as the record of what would have been run. The holdout guard was
never exercised; 2025-26 was spent on season figures (`Logs/props_season_log.md`). The one durable by-product is the
minutes-model defect P1 surfaced — the flat 0.30 substitute floor in `p_play_any` — opened as KNOWN_ISSUES #18 and
NOT fixed here. Full close-out: `Logs/props_prereg.md` CLOSE-OUT.
