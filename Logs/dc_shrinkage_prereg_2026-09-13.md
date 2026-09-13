# Pre-registration: shrinkage on Dixon-Coles team strengths (2026-09-13) — NOT implemented

A model-path change. The bar below is fixed before any number is seen and is not amended afterward; if it is
changed after a result is seen the outcome is exploratory and any adoption is a judgement call recorded as one
(standing rule). Nothing here is decided on season totals. Companion: `Logs/dc_fix_log_2026-09-13.md` §8 (the
live artefact), §10 (the alias check), KNOWN_ISSUES #25 ("exposed, not fixed").

## 0. The defect, stated

`_fit_dc_decay` maximises a time-weighted Dixon-Coles likelihood with no prior on the per-club attack and
defence parameters. For a club whose training rows contain no goals (attack) or no goals conceded (defence),
the log-likelihood is monotone in that parameter and the maximum is at −∞; L-BFGS-B stops wherever its line
search gives up (`converged` False), typically at −6 to −8, and the club's fixtures are priced at λ ≈ 0.001.
It happens only when the club has no archive history to dilute the run — i.e. promoted clubs in the first
weeks of a season — and it recurs every August. Live today at the GW5 cutoff: Coventry City (0 scored in 3,
attack → −∞, its λ ≈ 0.002 at GW6–10) and Hull City (0 conceded in 3, defence → −∞, every opponent's λ ≈
0.0005). In the record: 2024-25 cutoff 2, Ipswich (λ 0.001 at steps 1–5), the only cells below 0.15 in the
three rebuilt canonicals. Why it matters more than "two clubs": the six-week MIP selects on exactly these
extremes (clean sheets against Coventry at p ≈ 1; attackers facing Hull at ≈ 0 goals) at the horizon steps
the plan is built on. A flat fit is uniformly wrong and neutral to the optimiser; this is confidently wrong in
a direction the optimiser chases.

The alias check (fix log §10) did not change the diagnosis: 17 of 20 clubs join their full archive under the
exact name; the three that do not are the three promoted clubs, and only Ipswich Town's unjoined rows
('Ipswich', 2024-25, 76 rows at decay weight ≈ 0.25) are material. That is change B below, small and separate.

## 1. Change A — the form, and why

**A Gaussian prior centred at 0 on every attack and defence parameter**, i.e. the MAP estimate of the same
model: add `0.5 * tau * (sum(atk²) + sum(dfc²))` to the weighted negative log-likelihood in `_fit_dc_decay`.
`home_adv` and `rho` stay unpenalised. Zero is the parameterisation's own centre (attack and defence are log
multipliers around the league mean), so the prior mean is "league average", the same neutral point as the
unmatched-fixture fill (λ = 1.40 both ways, p_cs 0.247). Why this form: the penalty grows quadratically while
the log-likelihood of a scoreless record is only linear in the parameter, so no parameter can run to ±∞ and
the optimiser converges; it is the textbook ridge on team strengths, not new modelling; and it adds one
constant, not a per-club rule.

**Strength, in pseudo-matches, and how it releases.** Per match the Fisher information for an attack (or
defence) parameter is ≈ λ ≈ `LEAGUE_AVG_LAMBDA` = 1.40, time-decayed like the likelihood, so a club with
n_eff effective matches (Σ of its decay weights) carries ≈ 1.40 · n_eff of information. A prior with
precision tau = 1.40 · k is worth k league-average pseudo-matches, and the posterior mode shrinks the MLE
toward 0 by the factor n_eff / (n_eff + k). **Pre-registered: k = 4 (tau = 5.6).** Consequences, computed
before any run: a club scoreless after three matches with no history gets attack ≈ −0.5 (0.61 × league
average) instead of −∞; after 20 effective matches a club keeps 83 % of its MLE; an established club
(n_eff ≈ 60–70 with the 365-day half-life) keeps ≥ 94 %, i.e. its log-strength moves by ≤ 0.02 for typical
values. The prior never re-tightens: as matches accrue the factor → 1. Why 4 and not 1 or 10: k = 1 still
prices a scoreless promoted club at 0.35 × league (harsh for the class, whose historical attack is ≈ 0.75 ×);
k = 10 at 0.77 × barely lets three matches speak. k is NOT tuned on the endpoint: a sensitivity row at
k ∈ {2, 8} is reported for information and cannot change the adoption.

Not chosen, recorded: a class-specific prior mean for promoted clubs (a second parameter to defend); an
asymmetric tau for defence; any change to `HALF_LIFE_DAYS`, `LAM_BLEND_W`, `CS_BLEND_W`.

## 2. Change B — live club-name canonicalisation (data, not model)

`_load_matches` merges the football-data archive (names of record: 'Hull', 'Ipswich', 'Man United', …) with
the live pull, whose names differ for returning clubs ('Hull City', 'Ipswich Town'). B maps the live names
onto the archive's for the live season only, and adds a guard: every club in the live season's fixtures must
either exist in the archive or be listed as promoted for that season, else the build raises under strict
(so next August's names are checked, not assumed). Expected effect: Ipswich Town gains its 2024-25 rows at
weight ≈ 0.25 (λ at steps ≥ 1 moves by < 0.1); Hull's 2016-17 rows weigh ≈ 0.001 (no visible move); Coventry
has no archive rows under any name (no move). B cannot touch the record: the three record seasons have no
alias (fix log §10) — verified, not assumed, by the parity family and the guard being bit-identical after B
alone.

## 3. What A changes, stated before any number

Team lambdas wherever the fit prices a fixture: every step ≥ 1, and at step 0 only the 0.2 DC share of p_cs
(goals at step 0 are market-priced, `LAM_BLEND_W` = 0). Largest where n_eff is small — the first six cutoffs
of a season and promoted clubs — negligible for established clubs at mid-season. Expected: the record's
cold-start cells move toward the league mean (2024-25 cutoff 2 Ipswich 0.001 → within [0.5, 1.0]; 2023-24
cutoffs 2–5 Luton / Burnley / Sheffield United; 2025-26 cutoffs 1–5 Leeds / Burnley / Sunderland) and every
established club at cutoffs ≥ 10 moves by < 0.03 in λ. **Tells, either of which is a stop-and-investigate:**
nothing moves at the early cutoffs ("a too-clean result"); or established clubs move by > 0.05 at mid-season
cutoffs (the prior is stronger than the arithmetic above says).

## 4. The endpoint and the bar (adoption is never on season totals)

Reference builds of the three canonicals with A (in-process; the record is rebuilt only on adoption).
Endpoint: **sliced Spearman(e_points, actual_points)** per (season, cutoff, step) on two slices — (i) likely
starters, `p_start ≥ .75`; (ii) the top 30 by `e_points` within the gameweek — the decision partitions.

- **Primary (steps 1–5, where the fit prices goals):** the mean over all cutoffs of each season, each slice
  — six numbers. **Bar: none of the six falls by more than 0.005 against the current record** (non-inferiority;
  shrinkage is a correctness fix for a class of cells, not a claimed improvement). **Falsifier:** any of the six
  below −0.005 → A does not go in, and the Friday question becomes flat-vs-unshrunk again.
- **Step 0 must not move** beyond p_cs's DC share: |Δ mean Spearman| ≤ 0.002 per season, both slices.
- **Sanity, absolute:** after A, every team λ at every step of every cutoff of the three seasons lies in
  [0.15, 6.0] (the detector's bounds, §5). One cell outside → the form is insufficient → not adopted.
- **Reported, not judged:** the early-cutoff (1–6) means; the specific cold-start cells; the k ∈ {2, 8}
  sensitivity; arm totals with the lesson of the fix log §7 attached (a sign expectation for totals is not a
  check).
- **Gates on adoption:** parity family and the as-of guard bit-identical on the rebuilt record (all 38 cutoffs
  of 2025-26, both configs, plus the 2023-24 / 2024-25 samples), suite green, fingerprint and index re-pinned
  with the pre-shrinkage artefacts preserved as `*_pre_shrink`.

## 5. The detector (permanent, strict)

`live_deadline.postflight`: for every horizon step and club, `team_lambda` outside **[0.15, 6.0]** raises
under strict through `_finding` ("Dixon-Coles strength EXTREME: <club> λ = … at step N — a parameter ran off;
no history and a one-sided record?"). Bounds from the rebuilt record's team-fixture cells at steps ≥ 1:
minimum 0.188 (2025-26) / 0.408 (2023-24), 0.1st percentile ≥ 0.199, 99.9th ≤ 3.95, maximum 4.32; the only
cells below 0.15 are the five Ipswich cells at 2024-25 cutoff 2 (0.001). Tests: an injected 0.001 raises; the
three canonicals pass at every cutoff; `LAST_FIT.converged` False becomes a strict finding too. **Sequencing
constraint:** this detector would fail today's live build (Coventry, Hull), so it ships WITH A, never before
it; deploying it alone would stop every build until Friday.

## 6. Order, with stop points

1. B: the alias map and the name guard; tests; suite. Parity and the guard unchanged (verified). No push.
2. A: the prior in `_fit_dc_decay` (`LAST_FIT` gains `tau`, `k`, and per-club n_eff min); the detector;
   tests. Suite green locally. No push.
3. The reference builds with A; §3's tells checked; §4's six numbers, the step-0 check and the sanity bound
   recorded verbatim; the falsifier applied. **Stop and report.** If falsified: nothing else happens, and the
   revert-to-flat question is put to the user for Friday.
4. Only if not falsified: the record rebuild (canonicals → gap0 arm frames → record armlogs, `*_pre_shrink`
   preserved), guards, parity, suite, re-pins; push; deploy outside every slot (not across 00:17 / 06:17 /
   12:17 / 18:17Z, not 11:00Z once nightly is live, not Friday 16:00–18:00Z); container verified; on the
   deployed image Coventry's and Hull's fixtures within bounds and `converged` True. A laptop rebuild does not
   touch the server; the deploy waits for the rebuild to finish so a rebuild and a live build are never in
   flight together.
5. Stop and report before `explain_prediction`.

Rough cost: B 30 min; A + detector + tests 1 h; reference builds 15 min; if adopted, the rebuild ≈ 1.5 h of
laptop time plus ≈ 1 h of guard runs, then the deploy. Feasible for a Tuesday/Wednesday landing.
