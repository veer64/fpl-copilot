# Pre-registration: THRESHOLD-form shrinkage on Dixon-Coles team strengths (2026-09-14) — DESIGN ONLY, not implemented

> **SUPERSEDED 2026-09-17 by `Logs/dc_shrinkage_threshold_prereg_2026-09-17.md` (v2)** before any implementation:
> this linear hinge releases completely at N = 10, so a club scoreless in ten matches would run to −∞ again. v2
> keeps the hinge and adds a plausibility box (±ln 4) that holds at any number of goalless matches; its lambda
> floor is stated there. Kept for the record; nothing here was run.

The second attempt at KNOWN_ISSUES #25 ("exposed, not fixed"). The first, a Gaussian prior on every club
(`Logs/dc_shrinkage_prereg_2026-09-13.md`, k = 4), was FALSIFIED on its endpoint
(`Logs/dc_shrinkage_log_2026-09-13.md` §3). This is a NEW pre-registration, not a tuning of that one: the
form is different by construction, and the bar below is fixed before any number is seen and is not amended
afterward. Nothing is decided on season totals.

## 0. What the first attempt taught, and the constraint it leaves

A fixture's λ multiplies TWO club parameters, `exp(atk_A + dfc_B + hadv)`. A prior that shrinks every club by
6–8 % in log-strength therefore compresses the strongest fixtures most — 0.2–0.4 in λ at the top of the
distribution (fix log §4) — and the top-30-by-e_points slice lives exactly there. That is where the
2023-24 / 2024-25 losses came from (−0.0052 / −0.0065 on top-30, starters flat or up). The defect being
fixed, meanwhile, lives entirely at the OTHER end: a club with almost no evidence and a one-sided record.
**Constraint: the remedy must leave a club with adequate evidence at its exact maximum-likelihood value.**
A threshold form does that by construction, not by tuning.

## 1. The form

Per-club prior precision that is zero once the club has enough evidence:

    n_eff_i  = Σ_{matches of club i in the training set} w_m          (the fit's own decay weights, half-life 365 d)
    tau_i    = tau_0 · max(0, 1 − n_eff_i / N)
    objective = weighted NLL + 0.5 · Σ_i tau_i · (atk_i² + dfc_i²)      (home_adv, rho free, as before)

- Above N effective matches a club is the unregularised MLE — bit-for-bit, since its penalty is exactly 0.0.
- Below N the prior ramps linearly from tau_0 at zero evidence to 0 at N, centred at 0 (league average, the
  same neutral point as the unmatched-fixture fill and the first attempt).
- A linear hinge rather than a smooth ramp: one threshold to defend, fully released, no tail that touches
  strong clubs. A hard cap on |θ| was rejected (it leaves the club AT the extreme, λ multiplier e^−3 = 0.05);
  a post-hoc blend of parameters was rejected (not an estimator of anything).

**tau_0 = 5.6 (= 1.40 × 4, four league-average pseudo-matches at zero evidence)** — the first attempt's
strength, kept: at n_eff = 3 with N = 10 the effective tau is 3.9, and a scoreless club after three matches
sits at attack ≈ −0.56 (0.57 × league average) instead of −∞. Kept rather than re-chosen so that the only new
degree of freedom in this prereg is N.

**N = 10 effective matches**, chosen from the record's own evidence table, computed before any endpoint
number (scratch `neff_by_cutoff.py`; n_eff at the cutoff's first kickoff, half-life 365 d, canonical names):

| season | clubs with no usable history | their n_eff at cutoffs 1 / 3 / 5 / 10 / 12 / 14 | smallest n_eff among the other clubs at cutoff 1 |
|---|---|---|---|
| 2023-24 | Luton | 0.0 / 1.0 / 2.9 / 8.4 / 10.1 / 11.7 | 9.8 (Sheffield United — two seasons old, then 25+ for every other club) |
| 2024-25 | Ipswich | 0.0 / 2.0 / 3.8 / 8.3 / 9.9 / 11.7 | 25.2 (Southampton) |
| 2025-26 | Sunderland (2016-17 rows weigh ≈ 0) | 0.1 / 2.1 / 3.9 / 8.4 / ≈10 / ≈12 | 8.4+ for Sunderland itself; every other club ≥ 25 |
| 2026-27 (live) | Coventry City, Hull (2016-17 rows weigh ≈ 0) | 0.0 / 2.0 / … | Ipswich Town ≈ 1 + 0.25 × 38 |

Reading: a club that was in the league in either of the last two seasons carries n_eff ≥ 25 at cutoff 1 and is
above N = 10 at every cutoff — untouched by construction all season. A club with no usable history crosses
N = 10 at cutoff 12–13, i.e. after ten to twelve of its own matches, by which point a one-sided record is no
longer plausible and the MLE's standard error on an attack parameter is ≈ 1/√(10 × 1.4) ≈ 0.27 — acceptable.
The one club near the boundary in the record, Sheffield United 2023-24 (9.8 at cutoff 1, 10.7 at cutoff 2),
receives at most 2 % of tau_0 for one cutoff. N = 10 is therefore the smallest round number that separates
the two classes in every season on the record; it is not fitted to any outcome.

## 2. What it changes, by construction (statable before any run)

Only cells (cutoff, step) in which at least one club has n_eff < N move at all: 2023-24 cutoffs 1–12 (Luton;
cutoffs 1–2 also Sheffield United, ≤ 2 %), 2024-25 cutoffs 1–12 (Ipswich), 2025-26 cutoffs 1–12 (Sunderland)
— about 36 of 114 cutoffs, and within them the fixtures of those clubs and (through the fitted home
advantage and rho, which are shared) every fixture by a small amount. **Every other cell is bit-identical to
the current record.** That is the structural check, and it is a stop-and-investigate if it fails: movement
in an unaffected cell means the implementation is not the form. And "a too-clean result is a tell": no
movement at all in the affected cells means the same.

Live at the GW5 cutoff: Coventry City (n_eff 2.0 at cutoff 3 → tau ≈ 4.5) and Hull (2.0) come inside the
[0.15, 6.0] box; Ipswich Town (with change B's alias, n_eff ≈ 10.5) is essentially untouched; the seventeen
established clubs are bit-identical to today's fit.

## 3. The endpoint and the bar — carrying both lessons

Sliced Spearman(e_points, actual_points) per (season, cutoff, step) on (i) likely starters (p_start ≥ .75) and
(ii) the top 30 by e_points within the gameweek, computed on **the affected cells only** (cells with a club
below N; ≈ 36 cutoffs × 5 steps ≈ 180 cells per slice, POOLED across the three seasons — the unaffected cells
are bit-identical by construction and would only dilute), steps 1–5.

- **Primary bar, in standard-error terms (lesson 1):** for each slice, the pooled paired mean Δ (with the
  prior − record) across the affected cells, with SE = sd(paired Δ)/√cells. **Falsified if the pooled mean Δ
  is below −2 SE on either slice.** Reported alongside: the per-season means, the early-cutoff (1–6) means,
  and the absolute figure with its SE so the reader sees both.
- **Step 0 on p_cs directly (lesson 2), not a ranking:** every step-0 row whose fixture involves no
  sub-threshold club must be bit-identical in `p_cs` (structural); for fixtures that involve one, the mean
  and max |Δ p_cs| are reported, and **any |Δ p_cs| > 0.15 is a stop** (the largest legitimate move is the
  cold-start cell itself: 0.2 × (e^−0.001 − e^−1.15) ≈ 0.14, the DC share of a fixture going from a runaway
  to a sensible λ).
- **Sanity, absolute:** after the change every team λ at every step of every cutoff of the three seasons
  lies in [0.15, 6.0]; the 2024-25 cutoff 2 Ipswich cells (0.001 today) must land inside it.
- **Gates on adoption:** the structural bit-identity check above; parity family and the as-of guard
  bit-identical on the rebuilt record (all 38 cutoffs of 2025-26 both configs, the 2023-24 / 2024-25
  samples); suite green; fingerprint and index re-pinned with the pre-change artefacts preserved as
  `*_pre_hinge`; on the deployed image Coventry's and Hull's fixtures inside the box and `converged` True.
- **Reported, never judged:** season totals and chip cells (relabelled, per the fix log §7's lesson);
  sensitivity rows N ∈ {6, 15} and tau_0 = 2.8 on the affected cells (informational; never a re-choice).

**Falsifier, in one place:** (a) pooled mean Δ < −2 SE on either slice; or (b) any unaffected cell not
bit-identical; or (c) any λ outside [0.15, 6.0] after the change; or (d) any step-0 |Δ p_cs| > 0.15. Any one
→ the change does not go in, the outcome is recorded as a failed pre-registration, and the Friday question
stays as it is (the server serving the unshrunk fit with the two runaway clubs).

## 4. The detector

Unchanged from the first prereg and already written (branch `shrink-detector-strict`): strict raise in
`live_deadline.postflight` on any club λ outside [0.15, 6.0] at any step and on a non-converged fit, with
the bounds' reasoning in the code comment. It ships WITH this change, never before it (today's live build
would fail on Coventry and Hull). `LAST_FIT` additionally records the clubs below N and their tau_i, so the
KNOWLEDGE block names who the prior touched.

## 5. Order, with stop points (Tuesday / Wednesday)

1. Implement on a branch from `shrink-detector-strict`: the hinge in `_fit_dc_decay` (n_eff per club is
   already computed there), `SHRINK_N`, `LAST_FIT` fields; tests (a scoreless newcomer bounded; a club at
   n_eff ≥ N bit-identical to the MLE; the ramp releases linearly; the structural cells). Suite green. No
   push.
2. Reference builds of the three canonicals in the scratchpad (≈ 15 min); the structural check, the
   affected-cell endpoint with its SE, the p_cs check, the sanity bound — recorded verbatim; the falsifier
   applied. **Stop and report.** If falsified: nothing else happens.
3. Only if not falsified: the record rebuild (canonicals → gap0 arm frames → record armlogs ≈ 1.5 h;
   `*_pre_hinge` preserved), guards ≈ 1 h, parity, suite, re-pins; push; deploy outside every slot — not
   across 00:17 / 06:17 / 12:17 / 18:17Z, not 11:00Z once nightly is live, not Friday 16:00–18:00Z, and never
   while a live build is RUNNING (dispatch state checked first; a laptop rebuild and a server build must
   not overlap the deploy); container verified; the live bar in the image.
4. Stop and report.

Cost: implementation + tests ≈ 1 h; reference builds + endpoint ≈ 30 min; if adopted, ≈ 3 h of laptop time
plus the deploy window. Feasible for Tuesday; Wednesday at the latest for a fresh post-ingest run to carry it
before Friday's deadline-day runs.
