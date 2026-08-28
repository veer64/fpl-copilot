# Hold preference at near-ties — PRE-REGISTRATION (2026-08-27, written before any number was seen)

Tuning seasons 2023-24 and 2024-25 only. **2025-26 is sealed for the GK p_cs question and is not read at any
point in this work** (`Logs/seal_register.md`). Gate `simulator.HOLD_PREFERENCE_EPS` rests `None` (off).

## 1. Motivation (from `Logs/outputs/` and the 2026-08-27 near-tie investigation)

~20% of transfer deadlines are decided by objective margins under 0.02 in a ~100–170 objective; the transfer
MIP is argmax on a point estimate with no tie-break, no incumbent preference and no uncertainty term; at all
72 GW2–38 deadlines of the two seasons it transferred and never held; and a flip at GW2–6 re-rolls the rest of
the season (leak-fix diagnosis: +75 / −16 / −89 from single flips; solver-gap fix: 2024-25 GW3).

This is NOT the rejected per-transfer minimum-gain rule (`Logs/wildcard_and_determinism.md`), which blocked every
low-gain swap everywhere, under a wildcard, and never priced holding. The question here: when the model cannot
distinguish acting from holding, should it hold?

## 2. Specification (fixed)

- **Definition.** At a deadline, `obj_best` = the production MIP optimum (gap 0). `obj_hold` = the optimum of
  the same MIP with the single added constraint **`used[0] == 0`** (no step-0 transfer; steps 1–5 free to plan).
  **Hold margin** = `obj_best − obj_hold` (decayed e_points over the horizon).
- **Rule.** If the step-0 plan makes ≥ 1 transfer and `hold margin < ε`, execute the hold plan (no transfer this
  week; the free transfer banks under the normal FT chain). Above ε, behaviour is unchanged. Nothing else moves:
  objective, constraints, decay, hit bar, bench weights untouched.
- **Combination moves are protected by construction.** The comparison is WHOLE PLAN vs WHOLE PLAN: a
  combination move (sell two to fund one) is a single plan whose margin over holding includes every leg; its
  low-gain budget-enabling legs are never evaluated individually. A plan is held only if the entire best plan
  is within ε of doing nothing this week. This is the clean distinction the min-gain rule lacked; no
  per-swap filter exists anywhere in the rule.
- **Exclusions, stated in the implementation:** wildcard and Free Hit weeks (no free transfer to bank; the
  chip week's rebuild is the plan) and the opening squad (GW1). On those weeks the rule is not consulted.
- **One free parameter ε**, fitted on the two tuning seasons only, by the rule in §3. No other tunable.

## 3. ε — calibration rule (fixed before the sweep is read)

Instrument: at every non-chip GW2–38 deadline of both seasons on the reference paths of record
(`armlog_{season}_gap0_tc2`, replayed states), compute the hold margin and the **realised 6-gameweek net** of
the best plan's step-0 transfers = Σ(realised points of players brought in) − Σ(players sent out) over
GW..GW+5 − hit points paid at that deadline. Fit **realised_net = a + b·margin** by OLS pooled over both
seasons. **ε = −a / b** if `a < 0 < b` (the margin below which transferring is expected to lose to holding);
if `a ≥ 0` (transferring pays at every margin) or `b ≤ 0`, then **ε = 0 — the rule never fires and the test is
dead on the tuning seasons; recorded as such.** ε is capped at nothing and is not tuned against any bar.

## 4. PRE-REGISTERED BARS (all must hold; none may be amended after a number is seen)

1. **Rank** — Spearman(e_points, realised) on likely starters (own-cutoff p_start ≥ .75) and squad-relevant
   (top 30 by e_points within gameweek) must not fall in either season. *Stated now: the rule does not touch
   predictions, so pre == post by construction; the bar is reported and is vacuous for this intervention.*
2. **Realised horizon points** — over the 6 gameweeks following each deadline where the rule holds instead of
   transferring, the realised net of the declined transfer(s) (ins − outs − hits paid), pooled across affected
   deadlines, must be **≤ 0** (holding did not lose points on the horizon the decision was made under).
   Measured on the simulated paths WITH the rule, from the declined plan the simulator records at each hold.
3. **Mechanism check (reported, not a bar):** transfers made, hits taken, and whether the banked transfers are
   subsequently spent at deadlines whose hold margin exceeds the margins of the deadlines skipped.

Season totals are REPORTED as illustration only; they are not a bar and may not be cited in the verdict.
If a bar is missed: FAIL, stop — no variants, no widened ε, no alternative endpoint. If it clears: STOP;
adoption requires a separate pre-registration.

## 5. Caveat stated in advance

With 2025-26 sealed there is no holdout: ε is fitted and bar 2 is evaluated on the same two seasons. Bar 2
on the sim path uses the rule's own hold deadlines (which depend on ε), so it is an in-sample check of a
one-parameter rule, and a PASS here is a tuning-season result, not evidence for adoption.

---

## RESULTS (2026-08-27) — ε = 0 by the pre-registered rule; the rule never fires; recorded as a FAIL (dead on the tuning seasons)

Instrument run as §3 on the reference paths (`armlog_{season}_gap0_tc2`), 68 non-chip GW2–38 deadlines (34 per
season; WC GW2 / WC2 and FH excluded by spec). Output of record `Logs/outputs/hold_sweep_2023_24.txt`,
`hold_sweep_2024_25.txt`, `hold_fit_eps.txt`. No 2025-26 file read.

**The hold margin is not a near-tie quantity.** Best plan vs best HOLD plan: min 0.0198, q10 0.836, q25 1.554,
**median 2.454**, q75 3.679, q90 7.03, max 13.56 (objective units, decayed e_points over the horizon). Only ONE
deadline in 68 sits below 0.05 and two below 0.5. The ~20% of deadlines decided by margins < 0.02 in the
near-tie sweep were ties between ALTERNATIVE TRANSFERS; against doing nothing, the optimizer's chosen plan is
clear by ~2.5 points of horizon objective at the median. The premise "the model cannot distinguish acting from
holding" does not hold on these seasons.

**Calibration (§3):** realised 6-gw net of transferring = **+9.05 (SE 3.94) − 0.482 (SE 0.93) × margin**, corr
−0.06, n 68. Intercept ≥ 0 ⇒ **ε = 0.** Transferring is expected to pay even at zero margin (+9 points per
deadline over the horizon, on average, at the smallest margins: the 10 deadlines under 1.0 realised +4.5 mean).

Lowest-margin deadlines:

 season  gw  margin  n_tr  hits  realised_net
2024-25  17  0.0198   1.0   0.0           9.0
2024-25  22  0.3113   1.0   0.0          11.0
2023-24  27  0.6605   1.0   0.0          28.0
2024-25  20  0.6928   1.0   0.0         -15.0
2023-24  11  0.7148   1.0   0.0           4.0
2023-24  36  0.7622   1.0   0.0           2.0

**Bars.** (1) Rank — vacuous by construction (predictions untouched); pre == post. (2) Realised horizon points
— no affected deadline exists at ε = 0; the pooled set is empty and the bar cannot be evaluated. (3) Mechanism
— nothing to report; no transfer was declined. **No gate-on simulation was run and none may be run under this
pre-registration** (a non-zero ε would be an amendment after seeing the number). Season totals: none produced.

**Verdict: does not clear its bars on the tuning seasons — FAIL by inapplicability.** The rule as specified never
fires, and the calibration says holding would have cost points had it fired. `simulator.HOLD_PREFERENCE_EPS` rests
None; the gated implementation (`transfer_mip.build_and_solve(force_hold=...)`, `plan[0]["objective"]`, the
simulator gate and log fields `hold_pref_eps` / `hold_applied` / `hold_margin` / `declined_transfers`;
`Tests/test_hold_preference.py`) stays in the tree as the instrument, off.

**What this changes in the near-tie reading.** The path lottery is seeded by ties between transfer options, not
by marginal decisions to transfer at all. Any future tie-break idea must act on the choice AMONG transfer plans
(e.g. between plans within ε of each other), not on the act-vs-hold margin — and that is a different
pre-registration.

