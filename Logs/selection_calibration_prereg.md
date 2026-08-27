# Selection-based calibration of e_goals by rank within gameweek — pre-registration and results (2026-08-27) — FAIL

Two passes on 2023-24 and 2024-25 only. 2025-26 was not opened at any point. Nothing adopted, no code changed;
every number was computed offline from the stored canonical columns (`bonus_mode = delete`, pre-leak-fix
canonicals; the penalty leak fix changes e_goals by ≤ 0.031 per row and does not bear on anything below).
Measurement outputs of record: `Logs/outputs/selcal_pass1.txt`, `Logs/outputs/selcal_pass2.txt`.

## 1. Premise (from `Logs/topend_calibration_prereg.md` and the 2026-08-26 handoff §7.2)

The top 30 by e_points within gameweek over-predict realised goals by ~1.4–1.6×, season-stable. Idea 9
(`fixture_scale ** γ`) failed because it stripped the market's fixture information from premiums (squad-relevant
rank −0.086 / −0.042). The residual was diagnosed as a SELECTION component (winner's curse from ranking on the
model's own errors). This log tests the natural alternative: shrink e_goals by rank within gameweek toward a
within-position prior, leaving fixture_scale untouched.

## 2. Pass 1 — shape of the problem (read-only, 2026-08-27)

Step-0 single-fixture rows, ranked within gameweek by e_points; realised ex-bonus (the bonus term is deleted).

| rank bin | n | 2023-24 pts / goals ratio | 2024-25 pts / goals ratio |
|---|---|---|---|
| 1–5 | 190 | 1.29 / **1.55** | 1.32 / **1.61** |
| 6–10 | 190 | 1.17 / 1.40 | 1.22 / 1.51 |
| 11–20 | 380 | 1.14 / 1.39 | 1.30 / 1.76 |
| 21–30 | 380 | 1.05 / 0.97 | 1.20 / 1.49 |
| 31–50 | 760 | 1.11 / 1.19 | 1.10 / 1.35 |
| 51–100 | 1,900 | 1.06 / 1.03 | 1.00 / 1.05 |

- Monotone in rank and steepest at the very top; the two seasons disagree on where it fades (rank 21–30:
  0.97× vs 1.49×). Within the top 30 it is position-tilted: DEF 1.9× / 2.6×, GK ∞ (e_goals 0.06–0.08 vs 0),
  FWD 1.54× / 1.56×, MID 1.08× / 1.43×.
- **Term decomposition, top 30 (pred − real, points):** goals +0.37 / +0.62 (62% / 63% of the gap); assists
  +0.10 / +0.22; clean sheets +0.09 / +0.13; saves +0.04; conceded +0.02–0.04; appearance ≈ 0. Goals dominate
  but ~35–40% of the gap is in assists and clean sheets. The deleted bonus term is the offsetting −0.49 / −0.47.
- **Hook point:** after `pts_goals` is recomputed at `assembly.py:694` (or after the props hook at 703) and
  before `e_points_core` at 709. Downstream movers: `pts_goals`, `e_points_core`, `e_points`, `pred_bps`
  (inert under delete). No rank-within-gameweek quantity exists in the production path.
- **Within-position priors on disk:** `attacking_rates._blended_rates → pos_prior[grp]` (prior-season npxG/90
  by F/M/D, league fallback; prior-season only per predicted season; the module's metric logging scores
  against `EVAL_SEASON = "2025"`).
- **Spread baseline (within-gameweek sd of e_points):** likely starters 1.057 / 1.073; squad-relevant top 30
  0.923 / 0.986; top-30 range rank-1 7.76 / 8.13 → rank-30 3.84 / 3.89.

## 3. Pass 2 — PRE-REGISTERED SPECIFICATION (fixed before any result)

- Shrink e_goals only: `e_goals' = e_goals − s·(e_goals − T)`, `T = pos_prior_npxg90(position) × minutes_frac
  × fixture_scale_cal + e_pen_goals` (FPL FWD/MID/DEF → F/M/D; GK target 0, GK being excluded from attacking
  rates). `pts_goals` and `e_points` recomputed after the shrink.
- Applies to ranks 1–10 within gameweek by e_points on step-0 rows. **Double-gameweek convention:** ranks are
  computed among single-fixture rows only; double rows are neither ranked nor shrunk (a double's e_points is a
  two-fixture sum that occupies the top ranks for calendar reasons, not selection on error; the decision
  partitions are defined on single-fixture rows; doubles are 3–7% of step-0 rows).
- Target fixed (the attacking_rates prior); no alternatives.
- One free parameter s, fitted on 2023-24 + 2024-25 pooled BY LEVEL ONLY: argmin over a 0.05 grid of
  |pooled e_goals'/realised goals − 1| on ranks 1–10. Rank plays no part in selection.
- Ranks 1–5 reported as a narrower variant for visibility; 1–10 is the pre-registered arm.

**Bars (all must pass):** (1) Spearman(e_points, realised) must not fall on either decision partition (likely
starters p_start ≥ .75; squad-relevant = incumbent's top 30) in either season; (2) within-gameweek sd of
e_points ≥ 0.85 × the pass-1 baseline on both partitions; (3) level improvement alone is not evidence — a ratio
moving toward 1.0 with rank falling is a FAIL. No bar may be amended after a number is seen; a miss stops the
work (no variants, no wider window, no other target).

## 4. RESULTS (2026-08-27) — FAIL

**Fit:** s* = **0.65** (pooled ranks 1–10 goals ratio 1.53 at s = 0 → 1.0011 at 0.65; surface linear). The
R = 5 variant fitted the same way also gives 0.65.

| arm R=10, s=0.65 | 2023-24 | 2024-25 |
|---|---|---|
| Bar 1 rank, likely starters | 0.3060 → 0.3053 (−0.0007) FAIL | 0.2889 → 0.2879 (−0.0011) FAIL |
| Bar 1 rank, squad-relevant | 0.1569 → 0.1522 (−0.0047) FAIL | 0.1453 → 0.1274 (**−0.0179**) FAIL |
| Bar 2 spread, likely starters | 0.871× baseline PASS | 0.868× PASS |
| Bar 2 spread, squad-relevant | **0.571×** FAIL | **0.579×** FAIL |
| Bar 3 | ratios → 1.0 with rank falling: FAIL | FAIL |

R = 5 (visibility only): rank −0.0006 / −0.0116 and −0.0004 / −0.0069; squad-relevant spread 0.60× / 0.61×.

Calibration by rank bin, pre → post (R = 10): goals 1–5 1.55 → 0.97 / 1.61 → 1.03; 6–10 1.40 → 0.96 /
1.51 → 1.07; other bins unchanged by construction. Points (vs total incl. bonus) 1–5 1.14 → **0.93** / 1.14 →
**0.93**. Movement: 22 / 11 top-30 rows swap; within-top-30 order changes on 923 / 849 of 1,140 rows; the
per-gameweek top-1 pick changes in **14 / 11 of 38** gameweeks; mean e_points change on shrunk rows −0.87 /
−0.86, max 3.2.

**Mechanism.** Shrinking ranks 1–10 toward the position prior compresses them into the 11–30 band (rank-1
mean falls ~3 points). The calibration gain is bought by discarding the ordering the optimizer captains on —
the same trade that failed idea 9, reached via rank instead of fixture scale. Recorded as a FAIL on the
tuning seasons; not adopted; no read on 2025-26; no variants explored, per the pre-registration.

## 5. STRUCTURAL FINDING (not a result; constrains all future calibration work)

**Goals-only calibration is coupled to the bonus deletion.** Bringing the goals ratio on ranks 1–10 to 1.0
pushed the POINTS ratio on those ranks to 0.93 (under-prediction), because the deleted bonus term already
offsets the top-30 level by ≈ −0.48 points (`Logs/bonus_delete_prereg.md` cost statement; pass-1 decomposition
above). Any future level calibration must either target realised points INCLUDING bonus, or address the bonus
term first. Calibrating one term against its own realised component while another term is deliberately absent
will over-shoot on points every time.

## 6. What is now closed and what remains

Closed on the tuning seasons: fixture-scale calibration (idea 9, `Logs/topend_calibration_prereg.md`) and
rank-within-gameweek shrink of e_goals (this log). The top-end over-prediction itself is real and unaddressed
(handoff 2026-08-26 §7.2); the two closed forms both lose rank where decisions are made. Any third form is a
new pre-registration and must respect §5.
