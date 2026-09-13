# Pre-registration — the Dixon-Coles cutoff-boundary fix (2026-09-13, step 2 of the plan; nothing built)

Finding: Logs/dc_degenerate_fit_finding_2026-09-13.md. Blind spot:
LEAKAGE.md residual item 7. This document fixes the FORM of the change and
the BAR it must clear, before any number is seen. It is not amended after.

## 1. The three forms, at the boundary

The boundary is the cutoff day. `cutoff` = the cutoff gameweek's first
kickoff, with time of day (e.g. Sat 2026-09-12 14:00). Archive match dates
are day-stamped. Rows in play at the boundary:

- **(a)** matches on the cutoff day, kicking off at or after the cutoff
  (all of that day's fixtures, since the cutoff is the day's first kickoff);
  played in the backtest (results present), unplayed live (goals NaN);
- **(b)** matches on the cutoff day kicking off before the cutoff — belong to
  an earlier gameweek (a rescheduled fixture). Rare; they cannot have
  FINISHED by the cutoff (a match kicking off 30–90 min before the next
  gameweek's first kickoff is in play at that instant);
- **(c)** matches dated before the cutoff day with goals NaN — a
  postponement still carrying its original date in the live slice
  (`fetch_fixtures` keeps the fixture; the archive's final calendar re-dates
  it, the live slice may not yet).

| form | training filter | admits (a)? | admits (b)? | admits (c)? | live abort fixed? | record leak closed? |
|---|---|---|---|---|---|---|
| A. played-only | `date_parsed < cutoff & goals notna` | backtest YES (leak stays); live NO | yes if played | no | yes | **no** |
| B. day granularity | `date_parsed < cutoff.normalize()` | no | no | **yes → NaN → abort** | yes, unless (c) exists | yes |
| C. refuse NaN in the fit | unchanged filter + `raise` on NaN goals | as today | as today | raises | no (it fails loudly instead) | no |

None alone is right. A leaves the record's leak in place and would make a
correctly-truncating guard FAIL against the record forever. B closes the
leak and the live abort but a postponed fixture still dated before the
cutoff day (c) reintroduces a NaN and the silent abort. C is an assertion,
not a boundary.

## 2. The form chosen: ONE rule, defined once, used by both sides

**Rule R — "a result is knowable at the cutoff if the match FINISHED before
the cutoff day began":**

    knowable(m, cutoff) := m.date_parsed < cutoff.normalize()  AND  m.home_goals, m.away_goals both present

implemented as ONE function in `squad/dixon_coles.py`
(`knowable_before(matches, cutoff) -> bool mask`) and used in exactly two
places:

1. **The fit's training filter** selects `matches[knowable]` (B + A's
   played-only clause). A postponed fixture (c) is excluded by the goals
   clause, not aborted on.
2. **The as-of guard's truncation** nulls goals for `~knowable` rows of the
   predict season (replacing the current `date_parsed >= cutoff_date`): it
   REMOVES what the rule says is unknowable, with the same function.

Plus **C as the assertion**: `_fit_dc_decay` raises if any training row has
a NaN goal ("Dixon-Coles training set contains N unplayed matches --
refusing to fit"). It cannot fire under R; it exists so that any future
path that bypasses the filter fails loudly instead of returning x0.

**Why one function, and why this makes the sides able to disagree.** Today
the filter and the guard are aligned by accident: two independent
expressions of the same wrong comparison, so the guard's bit-identity at the
boundary is structural. Under R the alignment is deliberate and lives in
one place. If the training filter is ever loosened (a timed cutoff again, or
goals-NaN tolerated), the guard still nulls by R and the as-of fit differs
from the record → the guard FAILS. If the guard is loosened, the filter
still excludes. Drift in either direction is visible; only a change to the
one function moves both, and that change is reviewed as a rule, not as two
filters. The guard also keeps nulling PRICES beyond `odds_until` as now
(unchanged; that boundary is the gameweek's last kickoff, not the cutoff day).

**Proof that the sides can disagree, pre-registered as the FIRST test of
step 3:** run the guard with the new truncation against the OLD 2025-26
record at cutoff 4 (8 cutoff-day matches admitted by the old filter). It
must FAIL with diffs at steps ≥ 1 (and small ones in `p_cs` at step 0). If
it passes, the guard still cannot see the boundary and step 3 stops there.

## 3. What the fix changes, stated before any number

- **Live (2026-27):** every horizon step ≥ 1 gets fitted team strengths
  instead of the starting point; step-0 clean sheets lose the 0.2 share of a
  degenerate value. Nothing else in the live path changes.
- **The record (2025-26 canonical, the gap0 arm frames, and the 2023-24 /
  2024-25 canonicals for the reference cells):** the fit at every cutoff
  with cutoff-day matches (34 of 38 in 2025-26; the 159 admitted matches)
  trains without them. Steps ≥ 1 move by the sample's order (top-30 mean
  |Δe_points| 0.02–0.08, max ~0.5 at cutoffs 3–4); step 0 moves only through
  `p_cs`. Deadlines can change. Season totals will change and are NOT the
  judge (section 5).
- **Fingerprint constants** in `Tests/test_walkforward_provenance.py`
  (0.7454 / 1.0506) are re-pinned with a dated note; the totals index is
  regenerated and the old cells flagged SUPERSEDED with the convention,
  exactly as on 2026-09-11.
- **Unchanged:** the minutes models and the horizon-minutes refit (no fixture
  input), attacking rates, the DC-contribution model, the bonus model, the
  market inversion, the optimiser and MIP.

## 4. The detector, so it cannot recur silently

- `postflight` (strict): at every horizon step present in the frame, the
  set of distinct `team_lambda` across teams must exceed 2, and no step may
  have all teams' lambdas within {exp(0.25), 1.0} ± 1e-6 — "Dixon-Coles
  strengths degenerate at step s (all teams share the fit's starting point)"
  through the strict-raising helper, NOT a plain `findings.append` (the
  failure mode of the existing detector at `live_deadline.py:442-448`).
- The fit assertion (section 2, C).
- The frame provenance sidecar / KNOWLEDGE block records the DC fit summary
  (training rows, max |attack|, home advantage, cutoff-day matches excluded)
  so a degenerate fit is visible in `/health` and every `built` line, not
  only in a raise.
- Tests: the detector fires on a synthetic degenerate frame and not on the
  2025-26 record; the assertion fires on a NaN-goal training row; `knowable`
  excludes (a) unplayed, (a) played-same-day, (b) and (c) and admits the day
  before; the guard's truncation and the filter are the SAME function
  (asserted by identity).

## 5. The bar, pre-registered (adoption is never on season totals)

This is a correctness fix: a fit that terminates at iteration zero on a NaN
likelihood is wrong by definition, and training on results that had not
happened is a leak by definition. The endpoint below is the check that
nothing else broke, not the justification for the change.

1. **Correctness, live:** on a strict build of the current live cutoff in
   the image (read-only, to /tmp), every step ≥ 1 has ≥ 18 distinct
   `team_lambda` values across the 20 clubs, and the fitted strengths equal
   (bit-identical) those of the healthy reproduction of 2026-09-13 (cutoff
   at midnight, odds_until as live). The strict detector passes; injected
   degeneracy makes it raise.
2. **The guard can disagree:** the pre-registered failure of section 2
   against the old record is observed and recorded.
3. **The guard passes on the rebuilt record:** bit-identical at ALL 38
   cutoffs of 2025-26, both configs, and at the 2023-24 / 2024-25 sample
   cutoffs used on 2026-09-11 — the standing test at cutoffs 20/24 stays in
   the suite.
4. **Parity family:** passes on the rebuilt record (parity is between
   configs on the shared path; it is not expected to move — if it does,
   stop).
5. **Rank endpoint, the sanity check (rebuilt vs old 2025-26 record, per
   cutoff, per step):** step 0: top-30 Spearman ≥ 0.99 and likely-starter
   mean |Δe_points| ≤ 0.03 at every cutoff; steps 1–5: top-30 Spearman
   ≥ 0.90 at every cutoff (the counterfactual sample's floor, at cutoff 4)
   and likely-starter mean |Δ| ≤ 0.10. Outside those bounds in EITHER
   direction — including "nothing moved at all" at a cutoff with ≥ 5
   admitted matches — is a stop-and-investigate, not a pass or a fail to be
   argued.
6. **Direction expectation, stated now:** hindsight removal's sign is
   expected to be negative or null on the arm totals at steps ≥ 1, as on
   2026-09-11; a RISE in totals after removing information is a tell to
   investigate before anything is recorded.
7. **Not cited as evidence, under any outcome:** season totals, the
   reference cells, or any change in a chip cell. They are regenerated and
   labelled; they do not decide.

If the endpoint is changed after a result is seen, the outcome is
exploratory and not citable as a passed pre-registration, and any adoption
is recorded as a judgement call, per the standing rule.

## 6. Order for step 3 (each with a stop point)

1. Code: `knowable_before`, the filter, the guard's truncation through it,
   the fit assertion, the strict detector, the KNOWLEDGE fields, tests.
   Suite green locally. NOT pushed.
2. The disagreement proof (section 2) against the old record. Stop and
   report if it does not fail.
3. Rebuild: 2025-26 canonical; gap0 arm frames; 2023-24 and 2024-25
   canonicals; totals index; fingerprint re-pin; superseded flags. The
   `_preasof` naming convention of 2026-09-11 is reused as `_pre_dcfix`.
4. Bar items 3–7 evaluated and recorded verbatim, then and only then the
   suite + parity + as-of gates, the push, a deploy outside every slot
   (next windows: not across 12:17 / 18:17Z, not inside Friday 16:00–18:00Z),
   the container verified, and bar item 1 on the deployed image.
5. Stop and report before `explain_prediction`.
