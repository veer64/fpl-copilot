# Hit threshold grid — a NEGATIVE result. The bar stays at 4.

**Date:** 2026-08-14 · **Seasons:** 2023-24, 2024-25, 2025-26 · **Thresholds:** 4, 6,
7, 8, 9, 10 · **Decision: NO CHANGE. The threshold remains 4, FPL's actual charge.**

> ## ⚠ PARTIALLY RETRACTED — motivating figures void; grid may inherit the same contamination
>
> **Added 2026-08-17.** The margin-calibration figures that motivated this grid —
> the 1.5–2.6× starter-band inflation and the implied 6–10 bar — were measured on
> walk-forward files containing D1 terms while described as baseline, and are
> retracted (`Logs/margin_calibration_log.md`, KNOWN_ISSUES #13). The grid search
> itself may have read the same contaminated files; it needs re-running on files
> stamped `d1_terms_active=False` before any figure or conclusion below is trusted.
>
> **The decision stands: the threshold remains 4.** Holding FPL's actual charge
> requires no model evidence. What is retracted is the stated rationale — both the
> hypothesis's motivation and the "tested properly and did not survive" narrative
> are unverified until the grid is re-run on clean files.

Written so nobody re-derives this. The hypothesis was reasonable, the evidence was
gathered properly, and it did not survive.

---

## 1. The hypothesis, and why it deserved testing

The MIP pays a -4 hit whenever predicted gain exceeds 4. But three seasons of
pairwise margin calibration (`Logs/margin_calibration_log.md`) showed that among
players who actually start, predicted margins are inflated by roughly 1.5-2.6x. The
implied bar — the predicted margin genuinely worth a 4-point charge — came out at
**6 to 10 points**, in every season above 4.

Corroborating signal from the hit diagnosis: 53% of paid transfers cleared 4 on
prediction, but only 40% beat 4 in realised terms.

So the hypothesis was specific and well-motivated: **the bar is too low, the MIP
takes hits it should not, and raising the bar should improve the decisions.**

---

## 2. Implementation — gameweek level, NOT per transfer

The bar is the coefficient on the hit penalty **inside the MIP objective**
(`squad/transfer_mip.py`, `hit_bar`, default `HIT_COST = 4`).

    obj.append(-d * hit_bar * hits[t])

Raising it does not change what a hit costs when the gameweek is scored — FPL still
deducts 4. It raises the predicted gain the solver demands before it is willing to
pay that 4.

**This is deliberately not a per-transfer filter.** A per-transfer minimum-gain rule
was already tested in `Logs/wildcard_and_determinism.md` and failed badly: it
destroyed local gain monotonically (W1 +7.6 → -1.0 as lambda went 0 → 3) because it
cut the low-gain, budget-enabling legs that make combination moves possible — the
entire reason the MIP exists over a one-at-a-time search. Raising the objective
coefficient leaves the solver free to choose combinations; it only requires the
week's aggregate to clear a higher bar.

**Endpoints are per-decision and path-free. No season total is used anywhere** —
the M1 gate established that season totals cannot distinguish the full model from
one shrunk 75% toward the positional mean (`Logs/instrument_b_log.md`).

---

## 3. What the grid did

| τ | hit gameweeks (23-24 / 24-25 / 25-26) | hit points paid |
|---|---|---|
| 4 | 10 / 8 / 10 | 96 / 48 / 80 |
| 6 | 3 / 4 / 5 | 24 / 16 / 44 |
| 7 | 1 / 3 / 2 | 4 / 12 / 8 |
| 8 | 1 / 1 / 1 | 4 / 4 / 4 |
| 9 | 1 / 1 / 1 | 4 / 4 / 4 |
| 10 | 1 / 1 / 1 | 4 / 4 / 4 |

**The parameter is close to on/off.** Moving 4 → 6 removes 60-70% of hit gameweeks;
by τ=8 all three seasons collapse to a single hit and the grid saturates. τ=8, 9 and
10 are indistinguishable. Only 4 and 6 carry enough decisions to interpret.

---

## 4. THE DECISIVE ENDPOINT — what a higher bar blocks

A higher bar is only right if the transfers it blocks were genuinely bad. Measured
inside the τ=4 run (path-free and well defined — a cross-arm comparison is not,
because the squads diverge and "the same transfer" stops existing):

| season | τ | n blocked | median realised | mean | % beat 4 | **% positive** |
|---|---|---|---|---|---|---|
| 2023-24 | 6 | 23 | **+6.0** | +4.87 | **0.61** | **0.70** |
| 2023-24 | 7 | 27 | +6.0 | +5.81 | 0.63 | 0.70 |
| 2023-24 | 10 | 32 | +6.0 | +5.84 | 0.62 | 0.69 |
| 2024-25 | 6 | 12 | +2.5 | +3.25 | 0.42 | 0.58 |
| 2024-25 | 10 | 17 | +2.0 | +3.53 | 0.41 | 0.59 |
| 2025-26 | 6 | 18 | +0.5 | −0.89 | 0.22 | 0.50 |
| 2025-26 | 10 | 26 | +2.0 | +1.23 | 0.35 | 0.58 |

**The blocked transfers were mostly good.** Across all fifteen season x τ cells the
fraction that were positive **never falls below 0.50**. In 2023-24 a bar of 6 blocks
23 transfers whose median realised gain was +6.0 and **61% of which beat the 4-point
charge outright**.

Only 2025-26 at τ=6 shows blocked transfers that look genuinely poor (mean -0.89),
and even there the median is positive and half were positive. 2025-26 is also the
season with the most extreme calibration β (0.389) — the one that motivated the
hypothesis in the first place.

**Two of three seasons say the current bar is blocking value it should not.**

---

## 5. THE SELECTION TRAP — why the retained metrics look encouraging anyway

Every metric measured on the hits that SURVIVE improves as the bar rises:

| τ | corr(pred, realised) 23-24 / 24-25 / 25-26 |
|---|---|
| 4 | 0.265 / 0.152 / 0.638 |
| 6 | 0.561 / 0.902 / 0.661 |
| 7 | 1.000 / 0.911 / 0.748 |

**This is not evidence the rule is wise.** Conditioning on a higher predicted gain and
then measuring realised gain will raise the mean of the survivors whether or not the
threshold is a good idea — you have selected the cases the model was most confident
about, and confidence correlates with outcome even in a badly calibrated model. The
survivor metrics and the blocked-transfer metrics point in opposite directions, and
the blocked-transfer evidence is the one that answers the actual question.

Anyone re-running this and seeing correlation climb from 0.27 to 1.00 should stop
and look at what was thrown away.

**The τ ≥ 7 correlations are artefacts.** They rest on 1-3 surviving transfers. A
correlation of 1.000 over two points is arithmetic, not signal. Ignore every cell at
τ ≥ 7.

Realised-gain distributions per surviving transfer also move inconsistently: the
median RISES in 2024-25 and 2025-26 but FALLS in 2023-24 (6.0 → 4.0), and the
"beat 4" fraction falls in 2023-24 from 0.65 to 0.44.

---

## 6. Decision

**The hit threshold stays at 4 — FPL's actual charge.** `hit_bar` defaults to
`HIT_COST` and the shipped behaviour is unchanged.

The calibration finding that motivated this is still real (see
`Logs/margin_calibration_log.md`); it simply does not convert into a better decision
rule via a threshold on the aggregate predicted gain. The plausible reading is that
predicted margin, even inflated, still ranks candidate transfers well enough that
cutting on its magnitude discards good moves along with bad — which is the same
lesson the per-transfer minimum-gain experiment taught in a different form.

**Do not re-run this grid without a new idea about the endpoint.** The endpoints
here are per-decision and path-free, the seasons disagree, and the decisive one is
unambiguous.

---

## 7. What was built and left in place

- `squad/transfer_mip.py` — `hit_bar` parameter, defaults to `HIT_COST = 4`.
- `squad/simulator.py` — `hit_bar` passthrough on `simulate_season`, plus a `season`
  parameter on `load_season` for the multi-season port.

Both default to the previous behaviour exactly. The machinery is retained so the
experiment is reproducible, not because the parameter should be tuned.
