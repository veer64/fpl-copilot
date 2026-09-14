# Shrinkage on Dixon-Coles team strengths — execution log (2026-09-13 evening)

Pre-registration: `Logs/dc_shrinkage_prereg_2026-09-13.md` (the form, k = 4, the endpoint, the falsifier, the
detector — all fixed before any number below was seen). Companions: `Logs/dc_fix_log_2026-09-13.md` §8 (the live
artefact) and §10 (the alias check); KNOWN_ISSUES #25. Recorded in execution order; a STOP is where the run would
have ended.

## 1. The code (prereg §1, §2, §5)

- `squad/dixon_coles.py`
  - `SHRINK_K = 4`, `SHRINK_TAU = 1.40 * SHRINK_K` (= 5.6; 1.40 is the league-average λ, the neutral fill's).
    `_fit_dc_decay`'s objective gains `0.5 * SHRINK_TAU * (Σ atk² + Σ dfc²)`; `home_adv` and `rho` free. The
    comment above the constants carries the pseudo-match arithmetic and the "fixed before measurement" note.
  - `LAST_FIT` gains `shrink_k`, `shrink_tau`, `n_eff_min`, `n_eff_min_club` (the club with the least
    decay-weighted evidence — the one the prior matters most for).
  - Change B: `ARCHIVE_NAME_ALIAS = {"Hull City": "Hull", "Ipswich Town": "Ipswich"}`, `canon_club()`; the fit
    trains on a canonical-name view (`mc`) and looks parameters up by canonical name; the fixture OUTPUT keeps
    the live names (the FPL-named frame joins on them via `assembly.TEAM_MAP`, unchanged).
  - The name guard `check_new_clubs(mc, predict_season)`: a predict-season club with no prior-season rows must
    be declared in `NEW_TO_ARCHIVE` (`2023-24: Luton; 2024-25: Ipswich; 2026-27: Coventry City`), and a declared
    club must really have none — either way round it raises `ValueError` and the build stops.
- `squad/live_deadline.postflight` (on branch `shrink-detector-strict` only, see §6): the permanent strict detector — any club's `team_lambda` outside
  [0.15, 6.0] at any step, and `LAST_FIT.converged` False — through `_finding`. The bounds' reasoning is in the
  code comment (the user's point 1): they come from the record's distribution at steps ≥ 1 (min 0.188 / 0.408,
  0.1st pct ≥ 0.199, 99.9th ≤ 3.95, max 4.32), sit outside every legitimate value with margin, and the only
  cells ever outside were the 0.001 Ipswich cells — three orders of magnitude out, not near the edge. Shipping
  with the prior is a sequencing fact, not a bound-setting one.
- Provenance: a `dc_shrink_k` stamp on every walk-forward row was added for the reference builds and REMOVED
  again once the prior was switched off (§6): it would have added a column the record does not carry.
- Tests: `Tests/test_dixon_coles_shrinkage.py` (10): a scoreless newcomer is bounded (attack in (−1.2, −0.15),
  converged, n_eff_min names it); without the prior the same newcomer runs below −3; established clubs move
  < 0.08 and keep 75–105 % of their MLE; canonical names and both directions of the guard; the declared sets
  match the archive exactly for every season on this machine; fixture output keeps live names and every live
  λ is inside the bounds with `converged` True; the detector raises at 0.001 and 6.5, is quiet at 0.2, raises on
  a non-converged fit; the record-bounds test (skips until a canonical carries the stamp).
  `test_dixon_coles_boundary.py`'s source check updated for the canonical-name view. 16 passed, 1 skipped
  (pre-rebuild) at this point.

## 2. Reference builds (prereg §6.3)

Three canonicals rebuilt IN THE SCRATCHPAD with the prior (`refbuild_shrink.py`; `walk_forward(season,
horizon=6, save_path=scratch)`), never touching `data/`; plus the informational k ∈ {2, 8} rows for 2025-26 on
cutoffs 1–6 and 20. Compared against the current record (the 2026-09-13 DC-fix rebuild, no prior) with
`shrink_endpoint.py`, which computes exactly §4 of the prereg. Builds ran 19:10–19:24Z (the laptop then slept;
the endpoint was computed at 02:10Z on 2026-09-14). Row counts identical to the record (162,604 / 152,003 /
165,401).

## 3. The endpoint, verbatim (k = 4) — FALSIFIED

Sliced Spearman(e_points, actual_points), mean over all cutoffs; "starters" = p_start ≥ .75, "top30" = the
frame's own top 30 by e_points within the gameweek. Record → with the prior (Δ):

| season | steps 1–5 starters | steps 1–5 top30 | step 0 starters | step 0 top30 |
|---|---|---|---|---|
| 2023-24 | 0.2576 → 0.2597 (+0.0021) | 0.1359 → 0.1306 (**−0.0052**) | 0.3138 → 0.3136 (−0.0002) | 0.1461 → 0.1384 (**−0.0076**) |
| 2024-25 | 0.2580 → 0.2576 (−0.0004) | 0.1510 → 0.1445 (**−0.0065**) | 0.3002 → 0.3002 (−0.0000) | 0.1904 → 0.1945 (**+0.0041**) |
| 2025-26 | 0.1771 → 0.1782 (+0.0011) | 0.0761 → 0.0761 (+0.0000) | 0.2012 → 0.2017 (+0.0006) | 0.0972 → 0.0957 (−0.0015) |

- **Primary bar (six numbers ≥ −0.005): NOT MET.** Two of six fall below it: the top-30 slice at steps 1–5 in
  2023-24 (−0.0052) and 2024-25 (−0.0065). The starters slice is flat or up everywhere.
- **Step 0 within ±0.002: NOT MET** on the top-30 slice in 2023-24 (−0.0076) and 2024-25 (+0.0041). Step 0
  changes only through p_cs's 0.2 DC share, but a 30-item Spearman reorders on shifts of a few hundredths of a
  point in pts_cs.
- Sanity bound: MET — every team λ inside [0.15, 6.0] in all three builds (min 0.455–0.555, max 3.38–4.43).
- Cold-start cell: the 2024-25 cutoff 2 Ipswich cells go 0.0008 → 1.148 (the fix working as designed).
- Early cutoffs 1–6, steps 1–5 (reported, not judged): starters −0.0009 / +0.0024 / +0.0056; top30 −0.0004 /
  −0.0003 / −0.0001.

**Falsifier applied: change A (k = 4) does not go in.** Per the standing rule the bar is not re-argued; the
outcome is recorded as a failed pre-registration and the prior is OFF in the code (`SHRINK_K = 0`, the
penalty exactly 0.0, objective bit-identical to before — §6).

## 4. The §3 tells, investigated (a prereg requirement, not an argument)

- "Established clubs at cutoffs ≥ 10 move by > 0.05 in λ" fired in every season (558 / 555 / 406 cells, max
  |Δλ| 0.43 / 0.30 / 0.30). Investigation: the prereg's "< 0.03 in λ" expectation was mis-derived — it
  reasoned in log-strength for ONE parameter. A fixture λ = exp(atk_A + dfc_B + hadv) carries TWO shrunk
  parameters, and 6–8 % shrinkage of each on a strong-attack/weak-defence pairing at λ ≈ 3–4 moves λ by
  0.2–0.4, multiplicatively. In log-strength the prior did exactly what k = 4 says (n_eff ≈ 60–70 →
  factor ≈ 0.92–0.94); in λ at the top of the distribution that is not small. The tell was worth having:
  it says the prior compresses the strongest fixtures — which is also the likeliest mechanism for the
  top-30 loss (the top 30 by e_points are strong-club players; compressing their fixture λ blurs the
  ordering among them). Recorded; the expectation is not rewritten.
- "Nothing moved at the early cutoffs" did not fire (mean |Δλ| 0.05–0.09 at cutoffs 1–6).

**Sensitivity rows (informational only, 2025-26 on cutoffs 1–6 and 20, never citable):** k = 2: starters
+0.0052, top30 −0.0340; k = 8: starters +0.0070, top30 −0.0118. On this early-cutoff-heavy subset the
top-30 slice loses at every k tried and the starters slice gains at every k; the subset is not comparable to
the full-season numbers above. What it suggests for a NEXT pre-registration (which would be a new one, not
a tuning of this): the loss sits in the top-30 slice, i.e. in ordering among strong clubs, so a form that
shrinks only clubs with little evidence (a hinge: prior weight zero once n_eff exceeds ~10) might keep the
cold-start fix without compressing the strong end — untested, unregistered, a hypothesis.

## 5. What was learned about the endpoint

Two things worth writing down for the next prereg. (1) The top-30 Spearman on 30 items is noisy per cell
(one neighbour swap ≈ 0.01–0.02); averaged over 190 cells its paired standard error is roughly 0.003–0.004,
so a bar at 0.005 is about 1.5–2 standard errors — a −0.0052 can be sampling. That does not soften the
verdict (the bar is the bar) but the next prereg should either use more cells (all three seasons pooled) or
state the bar in standard-error terms. (2) The step-0 check at ±0.002 on a 30-item slice is tighter than the
slice's own noise, so it will fail on almost any change; a starters-only step-0 check or a p_cs-level check
(mean |Δ p_cs| ≤ x) would test what was meant.

## 6. What is in the tree now (local, UNPUSHED), and the Friday question

- Prior OFF: `SHRINK_K = 0` → `SHRINK_TAU = 0.0`; the penalty term is exactly 0.0, so the fit is bit-identical
  to the pre-shrinkage objective. The machinery and `LAST_FIT` fields stay (documented outcome in the module
  comment). The full suite — parity family and the as-of guard against the record — is the proof of
  bit-identity (§7).
- Change B stays: `ARCHIVE_NAME_ALIAS`, `canon_club`, the name guard `check_new_clubs`, `NEW_TO_ARCHIVE`.
  It changes nothing on the record seasons (no alias applies; the guard passes) and gives Ipswich Town its
  2024-25 rows live. Live effect on Coventry / Hull: none — their defect is the prior's job.
- The permanent detector is NOT on main: it is on branch `shrink-detector-strict` (commit 419772c, with its
  two tests), strict: λ outside [0.15, 6.0], or a
  non-converged fit, raises. **If pushed as is, today's live build FAILS** (Coventry attack, Hull defence),
  which is what the user asked the detector to do — "should raise under strict, not be served" — but it means
  no GW5 model runs until a remedy lands. Not pushed for that reason: the deployed server stays on 3f9c9fc
  (no prior, no detector, the two clubs served at the extremes).
- The `dc_shrink_k` provenance stamp was removed again (it would have added a column the record does not
  have, forcing a rebuild for a change that is not adopted).
- Options for Friday, for the user: (a) leave the server as deployed (steps ≥ 1 wrong at the two extremes,
  everything else right); (b) push B + the detector and accept FAILED runs until a remedy — the agent then
  serves the last successful run (run 5, 12 Sep, the pre-fix degenerate frame) under the stale-by-one rule,
  which is worse; (c) a new pre-registration of a narrower form (hinge / small-sample-only shrinkage, or a
  hard floor on n_eff below which a club is priced at the promoted-club mean), with the endpoint lessons of
  §5, landing Tuesday/Wednesday; (d) revert to the flat pre-fix state — uniformly wrong, neutral to the
  optimiser — the user's own argument against it stands.
