# Pre-registration v2: hinge prior + plausibility box on Dixon-Coles team strengths (2026-09-17) — DESIGN ONLY, not implemented

Supersedes `Logs/dc_shrinkage_threshold_prereg_2026-09-14.md` (v1), whose linear hinge released completely at
N = 10 and would therefore have let a club scoreless in ten matches run to −∞ again. The user's requirement
(2026-09-16): the form must hold at six or eight goalless matches and beyond — "a club that has not scored by
late October is not a hypothetical" — and must say what it does at zero goals in eight and what its lambda
floor is. The bar below is fixed before any number is seen and is not amended afterward. Nothing is decided on
season totals. The first attempt (a prior on every club, k = 4) was FALSIFIED (`Logs/dc_shrinkage_log_2026-09-13.md`);
its mechanism is this design's constraint.

## 0. The constraint, and the evidence it rests on

A fixture's λ = exp(atk_A + dfc_B + hadv) multiplies TWO club parameters, so any prior that shrinks every club
compresses the strongest fixtures most — 0.2–0.4 in λ at the top, where the top-30 slice lives. The remedy must
therefore bound the evidence-poor clubs and leave every other club at its exact maximum-likelihood value.

The record's fitted parameters (prior off, canonical names, `knowable_before`; cutoffs 2/3/5/10/20/30/38 of
2023-24, 2024-25, 2025-26; scratch `param_ranges.py`), among clubs with n_eff ≥ 10 effective matches:
**attack in [−0.53, +0.90] (0.59× to 2.46× the league rate), defence in [−0.69, +0.51] (0.50× to 1.66×)**,
converged at every one of the 21 fits. Among clubs below 10: Luton 2023-24 (+0.10 attack at n_eff 1.0, −0.36 at
2.9, −0.18 at 8.4), Ipswich 2024-25 (**−7.18 at n_eff 1.0** — the runaway; −0.34 at 2.0 once they scored),
Sunderland 2025-26 (**defence −1.98 at n_eff 1.1** after one clean sheet; −0.11 at 2.1). Live 2026-27 GW5:
Coventry attack −7.39 at n_eff 4 (scoreless in four; the fit does not converge). The runaways are all in the
region n_eff < 10; nothing with evidence is anywhere near ±1.4.

## 1. The form

Two parts, each doing one job, both leaving evidence-rich clubs untouched by construction:

**(A) Hinge prior on evidence-poor clubs** (v1's, unchanged): per club i,
`tau_i = tau_0 · max(0, 1 − n_eff_i / N)`, `objective = weighted NLL + 0.5 · Σ_i tau_i · (atk_i² + dfc_i²)`,
with `tau_0 = 5.6` (four league-average pseudo-matches at zero evidence) and `N = 10` (v1 §1's evidence table:
a club in the league in either of the last two seasons carries n_eff ≥ 25 at cutoff 1; a no-history club
crosses 10 at cutoff 12–13). Above N the penalty is exactly 0.0.

**(B) Plausibility box on every club's parameters**, as L-BFGS-B bounds: `atk_i, dfc_i ∈ [−ln 4, +ln 4]`
(0.25× to 4× the league rate). This is not shrinkage — it is a statement of what a Premier League club can be,
and it never binds on a club with evidence: the record's rich-club ranges sit inside it by 0.86 / 0.49 in log
on the attack side and 0.70 / 0.88 on the defence side, and the historical extremes of the league (the worst
attack ≈ 0.4×, the best defence ≈ 0.3×) are inside it too. It binds only where the likelihood has no
minimum — a one-sided record with the hinge released — and there it turns −∞ into 0.25×. Box bounds are the
only form that holds at ANY number of goalless matches; every prior that releases with evidence eventually
lets an unbroken zero run off (v1's defect), and a prior that never releases compresses the strong end (the
first attempt's defect).

**What the form does at zero goals in n matches, no history** (MAP under A, then B; scratch computation,
verbatim):

| n scoreless | tau_i | attack (MAP) | after the box | multiplier | λ v an average defence (at home) | λ v the strongest observed defence (0.50×) |
|---|---|---|---|---|---|---|
| 1 | 5.04 | −0.22 | −0.22 | 0.80× | 1.33 | 0.56 |
| 2 | 4.48 | −0.41 | −0.41 | 0.66× | 1.10 | 0.46 |
| 3 | 3.92 | −0.59 | −0.59 | 0.55× | 0.92 | 0.39 |
| 4 (Coventry now) | 3.36 | −0.77 | −0.77 | 0.46× | 0.77 | 0.32 |
| 6 | 2.24 | −1.17 | −1.17 | 0.31× | 0.52 | 0.22 |
| 8 | 1.12 | −1.75 | **−1.39** | 0.25× | 0.41 | 0.17 |
| 10, 12, 20 … | 0 | −∞ | **−1.39** | 0.25× | 0.41 | 0.17 |

**The lambda floor:** a club's own attack (or an opponent's, through the defence bound) can go no lower than
0.25× the league rate — λ ≈ 0.41 against an average defence, ≈ 0.17 against the strongest defence the record
has ever fitted, and 0.09 only if BOTH clubs sit at their bounds, which the record never shows and which
would itself be a finding. The extreme-strength detector's box [0.15, 6.0] is unchanged; after this change it
can fire only on that double-bound case. Symmetric for a club that concedes nothing (Hull after three,
Sunderland after one): the defence bound −ln 4 caps an opponent's λ at no less than 0.25× of theirs.

Not chosen, recorded: a smooth ramp instead of the hinge (one more shape to defend); a class-specific prior
mean for promoted clubs; asymmetric bounds; any change to `HALF_LIFE_DAYS`, `LAM_BLEND_W`, `CS_BLEND_W`;
tuning `tau_0`, `N` or the box on the endpoint (sensitivity rows are informational only).

## 2. What it changes, stated before any number

Only cells where at least one club has n_eff < N, or where a parameter sits at the box. On the record that is
2023-24 cutoffs 1–12 (Luton; cutoffs 1–2 also Sheffield United at ≤ 2 %), 2024-25 cutoffs 1–12 (Ipswich; the
cutoff-2 runaway is the box's only record case), 2025-26 cutoffs 1–12 (Sunderland). **Every other cell is
bit-identical to the current record**: the hinge is 0.0 above N, and no rich club touches the box. Live at
GW5: Coventry's attack goes −7.39 → −0.77 (0.46×, λ ≈ 0.77 at home v average), the fit converges, Hull and
Ipswich Town move little, the seventeen established clubs are bit-identical to today's fit.

Tells (each a stop-and-investigate): movement in a cell with no sub-N club and no parameter at the box (the
implementation is not the form); no movement in the affected cells (too clean); `converged` False anywhere
after the change; any established club within 0.2 of a bound.

## 3. The endpoint and the bar — carrying both lessons

Sliced Spearman(e_points, actual_points) per (season, cutoff, step) on (i) likely starters p_start ≥ .75 and
(ii) the top 30 by e_points within the gameweek, on the **affected cells only** (≈ 36 cutoffs × 5 steps per
slice), **pooled across the three seasons**, steps 1–5.

- **Primary, in standard-error terms (lesson 1):** per slice, the pooled paired mean Δ (with the change −
  record) across the affected cells, SE = sd(paired Δ)/√cells. **Falsified if the pooled mean Δ is below
  −2 SE on either slice.** Per-season means, the early-cutoff (1–6) means and the absolute figures are reported
  alongside so the reader sees both.
- **Step 0 on p_cs directly (lesson 2):** every step-0 row whose fixture involves no affected club is
  bit-identical in `p_cs` (structural); for the rest, mean and max |Δ p_cs| are reported, and **any |Δ p_cs| >
  0.15 is a stop** (the largest legitimate move: 0.2 × (e^−0.001 − e^−1.15) ≈ 0.14, a runaway becoming sane).
- **Sanity, absolute:** after the change every team λ at every step of every cutoff of the three seasons lies
  in [0.15, 6.0], every fit converges, and no established club is within 0.2 of a bound.
- **Gates on adoption:** the structural bit-identity above; the parity family (`Tests/test_live_deadline.py`)
  and `Tests/test_asof_reconstruction.py` bit-identical on the rebuilt record, by name; the guard at all 38
  cutoffs of 2025-26 both configs plus the 2023-24 / 2024-25 samples; suite green; fingerprint and index
  re-pinned with the pre-change artefacts preserved as `*_pre_hinge`; on the deployed image Coventry inside
  the box, `converged` True, and the loud detector's MODEL DEGRADED findings gone from a strict build.
- **Reported, never judged:** season totals and chip cells; sensitivity rows N ∈ {6, 15}, tau_0 = 2.8,
  box ln 3 / ln 6 on the affected cells (informational; never a re-choice).

**Falsifier, in one place:** (a) pooled mean Δ < −2 SE on either slice; (b) any unaffected cell not
bit-identical; (c) any λ outside [0.15, 6.0] or any non-converged fit after the change; (d) any step-0
|Δ p_cs| > 0.15; (e) any established club within 0.2 of a bound. Any one → not adopted, recorded as a failed
pre-registration; the loud detector keeps carrying the artefact to the phone and Friday's builds are served
as they are today.

## 4. The detector

Already live in its LOUD form (a5c2b39). The FATAL form (branch `shrink-detector-strict`) ships only once
this change is adopted and the fit converges on every build for a week — the user's condition of 2026-09-16.

## 5. Order, with stop points

1. Implement on a branch: `SHRINK_N`, the per-club tau_i in `_fit_dc_decay`, the bounds passed to L-BFGS-B
   (`ATK_DFC_BOUND = ln 4`), `LAST_FIT` gains `n_eff` and `at_bound` per affected club; tests (the table above
   at n = 3, 8, 12; a rich club bit-identical to the MLE; the box binds only where the MLE would run off;
   structural cells). Suite green. No push.
2. Reference builds of the three canonicals in the scratchpad (≈ 15 min); §2's tells; §3's numbers verbatim;
   the falsifier applied. **Stop and report.**
3. Only if not falsified: the record rebuild (≈ 1.5 h) → guards (≈ 1 h) → parity + as-of by name → suite →
   re-pins → push → deploy outside every slot (not across 00:17 / 06:17 / 12:17 / 18:17Z, not the 11:00Z
   nightly, not inside Friday 16:00–18:00Z) with no live build RUNNING → container verified → the live bar.
4. Stop and report.

**Timing against Friday's deadline (17:30Z).** Steps 1–2 ≈ 1.5 h from a go. If adopted, step 3 ≈ 3 h of
laptop time plus the deploy. A go before ~05:00Z Friday lets the deploy land before the 11:00Z nightly, so
the T-90 / T-30 / T-10 runs build on a converged fit; a go later than that means Friday's runs are served
as today (loud, degraded, Tuesday-shaped horizon steps) and the change lands for GW6.
