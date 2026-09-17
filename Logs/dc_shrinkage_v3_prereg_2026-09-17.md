# Pre-registration v3: a PROMOTED-CLUB CENTRE for the hinge prior (2026-09-17 evening)

> **STATUS 2026-09-17 19:00Z: IMPLEMENTED on branch `hinge-box-v2` (commit adddc17, unpushed), the endpoint RUN, verdict
> MARGINAL by §4's rule (pooled top-30 −1.35 SE), NOT ADOPTED.** Execution log: `Logs/dc_shrinkage_v3_log_2026-09-17.md`.
> The centre was not the lever: every sensitivity centre is marginal by the same clause, 2025-26's luck component being
> the residual. Nothing below is amended.

A new pre-registration, not an amendment of v2. v2 (`Logs/dc_shrinkage_threshold_prereg_2026-09-17.md`, executed in
`Logs/dc_shrinkage_v2_log_2026-09-17.md`) passed the letter of its bar and was MARGINAL under the user's condition
(top-30 −1.5 SE pooled, all of it 2025-26) and was not adopted. Its machinery — the hinge on centred parameters,
the plausibility box, the scoping to the league's clubs, the phantom-club guard, the box/detector reconciliation —
carries over unchanged and lives on branch `hinge-box-v2`. What v3 changes is ONE thing: the point the hinge pulls an
evidence-poor promoted club toward. Everything in this document was fixed before any endpoint number of v3 was seen;
the design inputs (§1) were computed from the archive, not from the endpoint.

## 0. What v2 showed, and what this is a response to

v2's top-30 movement had two sources (v2 log §2.2), and only one is a flaw:

- **2025-26 / Sunderland is not a flaw.** The record's defence runaway put up to ten of one club's players in a single
  top 30 and they happened to score. Removing a wrong thing that paid off looks like a regression and is not one.
  v3 does not design around it, and the same component will be present in v3's numbers.
- **2023-24 / Luton is a flaw.** Luton's top-30 slots went 13 → 34 under v2 and those players underperformed (3.06 v
  the top 30's 3.91), because the hinge's centre was the LEAGUE MEAN and a promoted club is not a typical club. Pulling
  a newcomer toward the average of all twenty clubs overshoots — systematically, as §1 shows for the whole class.

So v3 replaces the league-mean centre with a promoted-club centre. The remedy for the runaway (the hinge + the box)
is unchanged; the prior's MEAN is what a promoted club has been, not what an average club is.

## 1. The centre, and how it is derived (computed 2026-09-17 17:50Z, scratch `promoted_centre.py`)

**Definition.** A promoted club's first-season strength = its centred parameters, `atk_i − mean(atk)` and
`dfc_i − mean(dfc)` over its season's twenty clubs, in the plain maximum-likelihood fit (prior off, box off, the
record's optimiser, half-life 365 d, canonical names, `knowable_before`) at a cutoff the day after that season's last
match — the value the club's parameters settle to once it has a full season of evidence, i.e. what the cold-start
prior is standing in for.

**Cohorts.** Every season with a prior season in the archive: 2017-18 … 2025-26 — **9 cohorts, 27 clubs** (three
promoted per season; the archive's first season, 2016-17, has no prior season to define a cohort). Every fit
converged. Each club, its evidence at its first kickoff (`n_eff`), years since last in the league, and its strength:

| season | club | n_eff at kickoff | yrs away | attack (end) | defence (end) | attack (mid) | defence (mid) | GF / GA |
|---|---|---|---|---|---|---|---|---|
| 2017-18 | Brighton | 0.0 | — | −0.32 | +0.08 | −0.51 | −0.01 | 34 / 54 |
| 2017-18 | Huddersfield | 0.0 | — | −0.55 | +0.12 | −0.29 | +0.24 | 28 / 58 |
| 2017-18 | Newcastle | 0.0 | — | −0.23 | −0.10 | −0.39 | +0.19 | 39 / 47 |
| 2018-19 | Cardiff | 0.0 | — | −0.37 | +0.27 | −0.29 | +0.39 | 34 / 69 |
| 2018-19 | Fulham | 0.0 | — | −0.39 | +0.42 | −0.38 | +0.48 | 34 / 81 |
| 2018-19 | Wolves | 0.0 | — | −0.07 | −0.11 | −0.23 | −0.15 | 47 / 46 |
| 2019-20 | Aston Villa | 0.0 | — | −0.21 | +0.24 | −0.04 | +0.25 | 41 / 67 |
| 2019-20 | Norwich | 0.0 | — | −0.76 | +0.38 | −0.31 | +0.38 | 26 / 75 |
| 2019-20 | Sheffield United | 0.0 | — | −0.25 | −0.23 | −0.15 | −0.37 | 39 / 39 |
| 2020-21 | Fulham | 11.8 | 2 | −0.57 | +0.12 | −0.45 | +0.21 | 27 / 53 |
| 2020-21 | Leeds | 0.0 | — | **+0.24** | +0.04 | +0.26 | +0.33 | 62 / 54 |
| 2020-21 | West Brom | 8.9 | 3 | −0.30 | +0.35 | −0.47 | +0.43 | 35 / 76 |
| 2021-22 | Brentford | 0.0 | — | −0.04 | +0.08 | −0.13 | +0.07 | 48 / 56 |
| 2021-22 | Norwich | 13.1 | 2 | −0.75 | +0.45 | −0.97 | +0.44 | 23 / 84 |
| 2021-22 | Watford | 24.0 | 2 | −0.35 | +0.34 | −0.12 | +0.30 | 34 / 77 |
| 2022-23 | Bournemouth | 12.2 | 3 | −0.30 | +0.27 | −0.27 | +0.38 | 37 / 71 |
| 2022-23 | Fulham | 16.4 | 2 | −0.09 | +0.02 | −0.09 | +0.06 | 55 / 53 |
| 2022-23 | Nott'm Forest | 0.0 | — | −0.26 | +0.23 | −0.51 | +0.20 | 38 / 68 |
| 2023-24 | Burnley | 25.6 | 2 | −0.35 | +0.19 | −0.38 | +0.16 | 41 / 78 |
| 2023-24 | Luton | 0.0 | — | −0.05 | +0.41 | −0.10 | +0.28 | 52 / 85 |
| 2023-24 | Sheffield United | 9.8 | 3 | −0.48 | +0.52 | −0.58 | +0.41 | 35 / 104 |
| 2024-25 | Ipswich | 0.0 | — | −0.40 | +0.40 | −0.41 | +0.15 | 36 / 82 |
| 2024-25 | Leicester | 25.3 | 2 | −0.31 | +0.28 | −0.09 | +0.27 | 33 / 80 |
| 2024-25 | Southampton | 25.2 | 2 | −0.55 | +0.37 | −0.51 | +0.27 | 26 / 86 |
| 2025-26 | Burnley | 18.9 | 2 | −0.33 | +0.33 | −0.31 | +0.30 | 38 / 75 |
| 2025-26 | Leeds | 11.2 | 3 | −0.07 | +0.11 | −0.03 | +0.29 | 49 / 56 |
| 2025-26 | Sunderland | 0.1 | 9 | −0.22 | −0.08 | −0.26 | −0.34 | 42 / 48 |

("mid" = the fit at the season's 190th match, ≈ GW20 — informational, to show the class effect is not an
end-of-season artefact.)

**The class, end of season (n = 27):**

| | mean | sd | SE of mean | median | range | multiplier |
|---|---|---|---|---|---|---|
| attack | **−0.307** | 0.221 | 0.042 | −0.308 | [−0.76, +0.24] | **0.74×** the league rate |
| defence | **+0.203** | 0.196 | 0.038 | +0.244 | [−0.23, +0.52] | concedes **1.22×** |

Mid-season the same: −0.297 / +0.207. Per-cohort attack means run −0.21 … −0.42 and defence +0.03 … +0.37; no
cohort is on the other side of zero on either. Leave-one-cohort-out moves the attack mean within [−0.29, −0.32]
and the defence mean within [+0.18, +0.23] — no single cohort drives it, and the three endpoint seasons' own cohorts
(2023-24 −0.29/+0.37, 2024-25 −0.42/+0.35, 2025-26 −0.21/+0.12) sit around the constant, not beyond it. Twenty-two
of twenty-seven attacks are below the league mean; twenty-two of twenty-seven defences above it.

**Separate centres for attack and defence: yes.** The magnitudes differ (0.31 v 0.20 in log; a promoted side is
worse at both, more so in attack), the two are only moderately correlated across clubs (−0.50), and the box and the
hinge already treat them as separate coordinates.

**Returners v long-absent: one centre.** Clubs with no usable history at kickoff (n_eff < 10, n = 17) average
−0.27 / +0.18; clubs returning within three seasons (n_eff ≥ 10, n = 10) average −0.37 / +0.25. Returners are not
better — if anything worse — and the difference (≈ 0.09, against a between-club sd of 0.2) is within noise. One
class, one centre. (The hinge only touches clubs below N = 10 anyway; returners at n_eff ≥ 10 are untouched.)

**Fixed, not estimated per fit.** The centre is a pair of constants derived once from the archive:

    MU_PROMOTED_ATTACK  = -0.31
    MU_PROMOTED_DEFENCE = +0.20

(the full-archive means to two decimals). Estimating the class mean inside each fit — from the current season's
three promoted clubs — would couple the centre to a handful of matches from exactly the evidence-poor clubs the prior
exists to supplement, and would let the predict season move its own prior. A constant cannot be gamed by the predict
season, is inspectable, and moves only by a new pre-registration. It is stamped into `LAST_FIT`.

## 2. The form

v2's form (branch `hinge-box-v2`, `squad/dixon_coles._fit_dc_decay`) with the hinge's centre moved for promoted
clubs. In the notation of the v2 log §1(a), with `ā`, `d̄` the means over the league's clubs (`prior_teams`):

    tau_i     = tau_0 · max(0, 1 − n_eff_i / N)                       tau_0 = 5.6, N = 10 (unchanged)
    objective = weighted NLL + 0.5 · Σ_i tau_i · ( (atk_i − ā − μ_atk,i)² + (dfc_i − d̄ − μ_dfc,i)² )
    μ_i       = (−0.31, +0.20) for a PROMOTED club, (0, 0) otherwise
    box       : |atk_i − ā| ≤ ln 4, |dfc_i − d̄| ≤ ln 4 for the league's clubs   (unchanged; SLSQP refit only if
                the unbounded fit leaves it)

- **Who is promoted:** a club in the predict season's fixtures that was not in the previous season's fixtures, read
  from the archive under canonical names at every cutoff (2026-27: Coventry City, Hull City, Ipswich Town — the last
  via the alias to 2024-25's Ipswich). It is a data fact, not a declaration; `NEW_TO_ARCHIVE` stays what it is (the
  guard against unmapped aliases) and is not reused for this.
- **A non-promoted club below N** does not exist on the record or live (the evidence table: every club in the league
  in either of the last two seasons carries n_eff ≥ 25 at cutoff 1). If one ever appears, it gets centre (0, 0) —
  v2's form — and a MODEL NOTE names it.
- Everything else is v2: centred parameters over the league's clubs only; the hinge scoped to the league's clubs; the
  box for the league's clubs; phantoms at the starting point; L-BFGS-B unless the box is needed; `LAST_FIT` gains
  `promoted` (the list) and `mu_promoted` (the constants). Detector reconciliation unchanged: CLAMPED and hinge-active
  are MODEL NOTES; EXTREME [0.15, 6.0] and non-convergence are MODEL DEGRADED; the fatal raise, when it ships,
  raises on those two only.

**What it does at zero goals in n matches, no history, at the league rate (1.4) v average opposition** (scratch
`v3_tables.py`; MAP attack under the hinge, then the box):

| n scoreless | tau_i | v2 (centre 0): attack, λ v average | **v3 (centre −0.31): attack, ×, λ v average, λ v the strongest defence (0.50×)** |
|---|---|---|---|
| 1 | 5.04 | −0.22, 1.12 | **−0.48**, 0.62×, 0.86, 0.43 |
| 2 | 4.48 | −0.41, 0.93 | **−0.64**, 0.53×, 0.74, 0.37 |
| 3 | 3.92 | −0.59, 0.77 | **−0.79**, 0.45×, 0.63, 0.32 |
| **4 (Coventry now)** | 3.36 | −0.77, 0.65 | **−0.95**, 0.39×, **0.54**, 0.27 |
| 5 | 2.80 | −0.96, 0.54 | **−1.12**, 0.33×, 0.46, 0.23 |
| **6** | 2.24 | −1.17, 0.44 | **−1.32**, 0.27×, **0.38**, 0.19 |
| 7 | 1.68 | −1.4, box | ≈ −1.55 → **box −1.39**, 0.25×, 0.35, 0.17 |
| **8** | 1.12 | box | **box −1.39**, 0.25×, **0.35**, 0.17 |
| 10, 12, 20 … | 0 | box | box −1.39, 0.25×, 0.35, 0.17 |

The lambda floor is v2's (0.25× the league rate: ≈ 0.35 at home v average, ≈ 0.17 v the strongest defence the
record has fitted); the box binds one match earlier than under v2 (the seventh goalless match rather than the
eighth) because the path starts lower. Coventry today, four goalless: attack −0.95 (0.39×), λ ≈ 0.54 v average at
home — against the record's −7.4 and 0.0006. A club conceding nothing (Hull, three clean sheets): defence −0.47
(v2 −0.59), opponents' λ 0.88 (v2 0.77) — the defence centre (+0.20) pulls a clean-sheet run back harder than the
league mean did, which is the right direction for a promoted side.

**The record's three cold-start cases at cutoffs 1–6** (the club's centred attack / defence, and its mean own-attack
λ over the next six fixtures; record = the plain fit; v2 = centre 0; v3 = the promoted centre; every v3 fit
converged, no box needed):

| | cutoff (n_eff) | record: atk / dfc / λ | v2: atk / dfc / λ | **v3: atk / dfc / λ** |
|---|---|---|---|---|
| Luton 2023-24 | 1 (0.0) | −0.20 / +0.10 / 1.00 | 0.00 / 0.00 / 1.24 | **−0.31 / +0.20 / 0.89** |
| | 3 (2.0) | −0.72 / +0.80 / 0.66 | −0.17 / +0.46 / 1.17 | **−0.40 / +0.55 / 0.92** |
| | 6 (3.8) | −0.85 / +0.56 / 0.58 | −0.37 / +0.41 / 0.97 | **−0.54 / +0.47 / 0.82** |
| Ipswich 2024-25 | 1 (0.0) | −0.29 / +0.05 / 1.01 | 0.00 / 0.00 / 1.38 | **−0.31 / +0.20 / 0.99** |
| | 2 (1.0) | **−7.22** / +0.09 / **0.00** | −0.20 / +0.03 / 1.15 | **−0.46 / +0.17 / 0.87** |
| | 6 (4.8) | −0.73 / −0.01 / 0.71 | −0.41 / −0.01 / 1.00 | **−0.54 / +0.04 / 0.88** |
| Sunderland 2025-26 | 1 (0.1) | −0.75 / +0.39 / 0.70 | −0.02 / +0.01 / 1.52 | **−0.32 / +0.21 / 1.10** |
| | 2 (1.1) | +0.43 / **−1.87** / 2.30 | +0.16 / −0.18 / 1.72 | **−0.06 / −0.02 / 1.37** |
| | 6 (4.9) | −0.27 / −0.40 / 1.00 | −0.19 / −0.25 / 1.09 | **−0.28 / −0.18 / 0.99** |

Reading: at cutoff 1 a club with no evidence sits exactly at the centre (an implementation check, §5); v3's early
λ for a promoted attack is ~25 % below v2's (0.89 v 1.24, 0.99 v 1.38, 1.10 v 1.52) and close to what the plain
fit gave where the plain fit was sane. One honest note against the story in §0: Luton's own first season ended at
attack −0.05 (52 goals) — near the league mean, so v2's centre was closer to Luton's eventual truth than v3's is. A
prior is about the class, not the individual; v3 is right for the twenty-seven, and v2's Luton cells lost because
early-season Luton attackers priced at the league rate were ranked into the top 30 in weeks they did not score.
Whether a 25 % lower λ takes enough of them out of the top 30 is what the endpoint measures.

Not chosen, recorded: a per-fit estimate of the class mean (§1); a centre that depends on years away (§1: no
signal); a centre on the market's early odds (would re-import a point-in-time input into a fit that is supposed to
be independent of it); any change to tau_0, N, the box, `HALF_LIFE_DAYS`, `LAM_BLEND_W`, `CS_BLEND_W`; tuning the
centre on the endpoint (the sensitivity rows in §4 are informational).

## 3. What it changes, stated before any number

The same cells as v2 — the hinge's scope is unchanged: 2023-24 cutoffs 1–11 (Luton; cutoff 1 also Sheffield United
at 1.5 % of tau_0 — a promoted club, so it takes the promoted centre; at 1.5 % of tau_0 that moves it by < 0.01),
2024-25 cutoffs 1–12 (Ipswich), 2025-26 cutoffs 1–11 (Sunderland). Non-promoted clubs are never hinged. **Every
unaffected cutoff is bit-identical to the record**, as under v2 (the objective is the same function there).

**What moves inside an affected cutoff — said accurately this time.** The affected club's own fixtures move most
(its λ, the p_cs of it and its opponents). Every other fixture at that cutoff moves a little through the shared
parameters — the home advantage, rho, and the league mean over which the hinge centres — v2's builds put that at
≤ 0.0016 in p_cs at step 0 and ~0.0001 in the home advantage. That is expected, is not a tell, and is reported (the
mean and max |Δ p_cs| on those rows), not asserted away. v1 §2 said this; v2 §3 (d) wrongly wrote "bit-identical" for
those rows; this document says: **fixtures without an affected club at an affected cutoff move by at most a few
thousandths in p_cs, and a move above 0.01 there IS a tell** (an order of magnitude above the mechanism).

**Expected effect on the two slices — a statement, not a hedge.** Relative to v2 I expect a Pareto improvement:
top-30 better (fewer promoted-club attackers over-ranked into the top 30 — the Luton mechanism, and the same for
Sunderland's cutoff-1 attackers under v2's 1.52), starters unchanged within noise (the broad slice was driven by the
runaways' removal, which v3 keeps). Relative to the RECORD — which is what the bar measures — I expect starters
positive (~+2 SE, as v2) and top-30 still negative in 2025-26 (the Sunderland luck component, ≈ −0.02 in that season,
does not go away) but less negative than v2's −0.0264, so a pooled top-30 in roughly [−1 SE, +0.5 SE]. If instead the
top-30 stays at −1.5 SE or worse, the centre was not the problem — and the honest conclusion is to stop changing the
prior and let Coventry score.

Tells (each a stop-and-investigate): a promoted club with n_eff = 0 at cutoff 1 not sitting at (−0.31, +0.20) exactly;
movement in a cutoff with no promoted club below N; a box refit on the record (the table says none is needed until
the seventh goalless match, and no record club has more than two); `converged` False anywhere; an established club
within 0.2 of a bound; no movement at all in the affected cells; a step-0 |Δ p_cs| above 0.01 on a fixture with no
affected club.

## 4. The endpoint and the bar — carrying every lesson, with "marginal" defined before the number

The endpoint is v2's, unchanged: sliced Spearman(e_points, actual_points) per (season, cutoff, step) on (i) likely
starters p_start ≥ .75 and (ii) the top 30 by e_points, on the affected cells only (the same 170: 55 + 60 + 55),
pooled across the three seasons, steps 1–5; paired Δ = v3 − RECORD (the record, not v2: the reference does not move);
SE = sd(paired Δ) / √cells. Per-season Δ with the season's own SE (sd of that season's paired Δ / √its cells), the
early-cutoff (1–6) means and the absolute figures are reported alongside. Season totals are reported, never judged.

**The three outcomes, fixed now:**

- **FALSIFIED** — any one of: (a) either pooled slice < −2 SE; (b) any unaffected cutoff not bit-identical; (c) any λ
  outside [0.15, 6.0] or any non-converged fit; (d) any step-0 |Δ p_cs| > 0.15 on a fixture involving an affected
  club, or > 0.01 on one that does not; (e) any established club within 0.2 of a bound.
- **MARGINAL** — not falsified, and any one of: either pooled slice in [−2 SE, −1 SE); any single season's slice below
  −2 of that season's own SE; the promoted-club tells of §3. (Under this definition v2 was marginal on both counts:
  top-30 −1.5 SE pooled, 2025-26 top-30 −2.4 own-SE.)
- **PASS** — neither. Then, and only then, the change goes in.

Falsified or marginal → not adopted, recorded as such; the loud detector keeps carrying the artefact; no fourth form
without a new argument about what is wrong. The bar is not amended after a result. Sensitivity rows (informational,
never a re-choice): the centre from the six cohorts that are not endpoint seasons, 2017-18 … 2022-23 (attack −0.31,
defence +0.16); the centre halved (−0.155, +0.10); attack-only (−0.31, 0); v2's centre (0, 0) is already measured.

**Gates on adoption** (unchanged): the structural bit-identity; the parity family (`Tests/test_live_deadline.py`) and
`Tests/test_asof_reconstruction.py`, by name, bit-identical on the REBUILT record; the guard at all 38 cutoffs of
2025-26 both configs plus the 2023-24 / 2024-25 samples; suite green; fingerprint and index re-pinned with the
pre-change artefacts preserved as `*_pre_hinge`; on the deployed image Coventry inside the box, `converged` True, the
MODEL DEGRADED findings gone from a strict build and the MODEL NOTES naming the hinged clubs and the centre.

## 5. Order, with stop points (no deadline behind this: GW5 is covered; Coventry's number matters again for GW6)

1. Implement on branch `hinge-box-v2` (v3 = v2 + the centre; nothing in v2 is rewritten): `MU_PROMOTED_ATTACK`,
   `MU_PROMOTED_DEFENCE`, promoted-club detection from the archive in `get_fixtures` (passed to the fit as
   `promoted_teams`), the centre in the hinge, `LAST_FIT["promoted"]` / `["mu_promoted"]`, the MODEL NOTE naming
   the centre. Tests: a promoted club with no rows sits exactly at the centre; a non-promoted club below N sits at
   (0, 0); the §2 table at n = 3 / 6 / 8 on centred attack (box at the seventh); the v2 tests unchanged and green;
   the record test keyed to `*_pre_hinge`. Suite green. No push. ≈ 45 min.
2. Reference builds of the three canonicals in the scratchpad (three parallel processes, ≈ 15 min; **no branch
   switch and no model-module edit while they run** — the v2 lesson); the endpoint script as v2's (`v2_endpoint.py`)
   with the reference row unchanged; §3's tells; §4 applied verbatim. **Stop and report.**
3. Only on PASS: the record rebuild (`rebuild_hinge.ps1`, `*_pre_hinge` preserved) → guards → parity + as-of by name
   → suite → re-pins → push → deploy outside every slot (not across 00:17 / 06:17 / 12:17 / 18:17Z, not the 11:00Z
   nightly, not inside deadline − 90 min … + 30 min) with no live build RUNNING → container verified → the live bar.
4. Stop and report.

Cost to the stop point ≈ 1.5 h; adoption ≈ 3 h of laptop time plus a deploy window, any day before GW6's deadline.
