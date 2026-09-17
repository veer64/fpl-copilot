# Prereg v3 (promoted-club centre) — execution log (2026-09-17 evening)

Pre-registration: `Logs/dc_shrinkage_v3_prereg_2026-09-17.md` (approved by the user 2026-09-17 ~18:05Z: "Go ahead and
implement"). The outcome rule — FALSIFIED / MARGINAL / PASS — was fixed there before any number. Recorded in
execution order; §1 was closed before the reference builds finished (launched 18:14Z).

## 1. Implementation (prereg §5 step 1), on branch `hinge-box-v2` — v3 = v2 + the centre

- `squad/dixon_coles.py`: `MU_PROMOTED_ATTACK = -0.31`, `MU_PROMOTED_DEFENCE = 0.20` with the derivation in the
  comment (27 clubs, 9 cohorts, fixed constants, why not per-fit, "a different centre is a new pre-registration").
  `_fit_dc_decay(..., prior_teams=None, promoted_teams=None)`: per-club centre vectors `mu_a` / `mu_d` (the constants
  for a promoted club in the league, 0 otherwise); the hinge term becomes
  `0.5 · Σ tau_i · ((c_atk,i − mu_a,i)² + (c_dfc,i − mu_d,i)²)` on the same centred coordinates — still
  gauge-invariant (a constant offset), so the record's gauge is kept; the box, the scoping, the phantom guard, the
  unbounded-then-SLSQP structure are untouched. `LAST_FIT` gains `promoted` (the list), `mu_promoted` (the
  constants), `hinged_not_promoted` (a club below N with centre 0 — the case the evidence table says never happens),
  and each `clubs_below_n` entry carries `centre: promoted | league`. `get_fixtures` derives `promoted_teams` from
  the archive: the predict season's clubs absent from the latest earlier archive season, under CANONICAL names
  (2026-27 → `Coventry City`, `Hull`, `Ipswich`; the archive's first season has no earlier season → nobody).
- `squad/live_deadline.py`: the hinge-active MODEL NOTE names the centre and each club's centre; a second note
  names any hinged club that is not promoted ("understand the club"). CLAMPED / EXTREME / non-converged unchanged.
- Tests (`Tests/test_dixon_coles_shrinkage.py`): a promoted club with no rows sits exactly at (−0.31, +0.20) and a
  non-promoted one at (0, 0), both flagged in `LAST_FIT` (the prereg §3 first tell as a unit test); the promoted
  centre lowers a scoreless newcomer at n = 3 by 0.10–0.35 relative to v2 (the table says 0.20 at the real league
  rate) and at n = 8 both sit at the box, −ln 4 exactly, by SLSQP; with nobody promoted the fit is bit-identical to
  v2's; the live-fixture test asserts the promoted three are detected; the notes test carries the centre. 28 passed,
  1 skipped in the three fit/detector files. `Tests/test_model_degraded_health.py` unchanged and green.
- Full suite on the branch (18:35Z, the GW5 extraction-parity test deselected as for v2 — it diverges against the
  old record by design and is re-run on the rebuilt record): **433 passed, 1 skipped**. Code committed on the branch
  (adddc17), nothing pushed.

Reference builds: `refbuild_v2.py` with `REF_PREFIX=ref_v3` → `ref_v3_{tag}.parquet` + `_fits.json`, three parallel
processes from 18:14Z; sensitivity queues (`refbuild_v3s.py`: the six-cohort centre −0.31 / +0.16, the halved
centre −0.155 / +0.10, attack-only −0.31 / 0; cutoffs 1–13) from 18:15Z. No branch switch and no model-module edit
while they run (the v2 lesson). The endpoint script (`v2_endpoint.py`) gained the prereg's outcome rule (pooled
slices, each season's own SE, the 0.01 shared-parameter tell) before any build finished.

## 2. Reference builds and the endpoint, verbatim (prereg §3, §4)

Builds done 18:55Z (slower than v2's — the suite and the sensitivity queues shared the CPU). Every fits log carries
the stamps (`shrink_n` 10, `shrink_tau0` 5.6, `bound` 1.386, `n_league` 20, `mu_promoted` −0.31 / +0.20) and the
detected promoted three per season: 2023-24 Burnley / Luton / Sheffield United; 2024-25 Ipswich / Leicester /
Southampton; 2025-26 Burnley / Leeds / Sunderland — the archive's cohorts, exactly. `hinged_not_promoted` empty at
every cutoff. Against the record `data/walkforward_h6_{tag}.parquet` (the 2026-09-13 rebuild, no form).

### 2.1 The §3 tells and the structural gates

| | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| affected cutoffs | 1–11 (Luton; c1 also Sheffield United at 1.5 % of tau_0) | 1–12 (Ipswich) | 1–11 (Sunderland) |
| unaffected cutoffs bit-identical, every column, every row | 12–38: **yes** | 13–38: **yes** | 12–38: **yes** |
| rows moved in the affected cutoffs (e_points) | 93.8 %, max Δ 1.49 | 96.0 %, max Δ 2.68 | 96.5 %, max Δ 2.81 |
| box refits | **0** of 38 | **0** of 38 | **0** of 38 |
| fits converged | 38/38, max 123 it | 38/38, max 141 it | 38/38, max 173 it |
| nearest established club to a bound (≥ 0.2) | 0.66 (Sheffield United attack, c2) | 0.82 (Southampton attack, c38) | 0.89 (Arsenal defence, c38) |
| team λ min / max (record min) | 0.409 / 4.32 (0.408) | 0.509 / 4.43 (**0.0007**) | 0.455 / 3.38 (0.188) |
| step-0 \|Δ p_cs\|, fixtures WITH an affected club: mean / max (stop 0.15) | 0.0081 / **0.025** | 0.0056 / **0.044** | 0.0128 / **0.071** |
| step-0 \|Δ p_cs\|, fixtures WITHOUT one, at affected cutoffs (tell > 0.01) | 0.0010 | 0.0013 | 0.0012 |

A promoted club with no evidence sits at the centre (Luton c1: attack −0.31, defence +0.20 — the first tell, as a
unit test and on the record). No tell fired. The affected clubs' own-attack λ, mean over the club's cells (record →
v2 → v3): Luton c1 0.97 → 1.16 → **0.88**, c3 1.13 → 1.24 → 0.97, c6 0.62 → 0.92 → 0.80, c11 0.75 → 0.76 → 0.75;
Ipswich c1 0.99 → 1.31 → **0.98**, c2 0.15 → 1.19 → **0.94** (the 0.0007 runaway: 0.805 at its lowest cell), c6
0.76 → 0.92 → 0.89, c12 1.13 → 1.13 → 1.13; Sunderland c1 0.74 → 1.40 → **1.06**, c2 1.99 → 1.53 → **1.25**, c6
0.98 → 0.99 → 0.97, c11 0.98 → 0.98 → 0.97. The v3 table's predictions (§2 of the prereg) hold to two decimals.

### 2.2 The primary endpoint — pooled over the 170 affected cells (55 + 60 + 55), steps 1–5, v3 − record

| slice | record mean | v3 mean | paired mean Δ | SE | Δ / SE | cells up / unchanged | v2, for the reader |
|---|---|---|---|---|---|---|---|
| likely starters (p_start ≥ .75) | 0.2268 | 0.2286 | **+0.0018** | 0.00085 | **+2.15** | 59 % / 4 % | +0.0022, +2.1 SE |
| top 30 by e_points | 0.1484 | 0.1409 | **−0.0075** | 0.00552 | **−1.35** | 40 % / 15 % | −0.0093, −1.5 SE |

Per season (Δ starters, Δ top-30, each with the season's own SE): 2023-24 +0.0011 (+1.4), **−0.0049 (−0.5)**;
2024-25 +0.0018 (+1.6), +0.0022 (+0.4); 2025-26 +0.0026 (+1.2), **−0.0205 (−1.7)**. Early cutoffs 1–6 top-30:
−0.0006 / +0.0061 / −0.0408. Top-30 by step, 2025-26: −0.037 / −0.009 / −0.005 / −0.060 / +0.008. Season totals
not computed (no arm rebuild ran).

**The outcome rule, applied verbatim (prereg §4):** FALSIFIED — no: neither pooled slice < −2 SE; unaffected cutoffs
bit-identical; every λ in [0.15, 6.0]; every fit converged; step-0 max 0.071 < 0.15 with an affected club and
0.0013 < 0.01 without; nearest established club 0.66 from a bound. **MARGINAL — yes: the pooled top-30 slice is at
−1.35 SE, inside [−2 SE, −1 SE).** No season is below −2 of its own SE (2025-26 top-30 −1.7); no promoted-club tell.
**Verdict: MARGINAL. Not adopted.**

**Against the expectation stated in the prereg §3** ("a Pareto improvement over v2: top-30 better, starters
unchanged within noise; against the record, starters ~+2 SE and top-30 in roughly [−1 SE, +0.5 SE]"): the direction
was right and the size was not. Relative to v2 the top-30 slice improved (−0.0093 → −0.0075; 2025-26 −0.026 →
−0.021; 2024-25 +0.0016 → +0.0022) and starters stayed within noise (+0.0022 → +0.0018); against the record the
top-30 slice landed at −1.35 SE, outside the predicted band. **The 2023-24 / Luton cells did not respond at all**
(−0.0042 → −0.0049) even though Luton's early λ fell by a quarter (1.16 → 0.88 at cutoff 1) — the "Luton flaw"
reading in prereg §0 was not borne out: the centre was not the lever there. §2.3 says where the change came from.

### 2.3 Where the top-30 movement comes from under v3 (scratch `top30_driver.py`, `V2_PREFIX=ref_v3`)

| season | affected club's top-30 slots: record → v2 → v3 | cells with the club in v3's top 30: n, Δ | cells with it in neither: n, Δ | its players' mean points when in v3's top 30 v the top 30's |
|---|---|---|---|---|
| 2023-24 | Luton 13 → 34 → **23** | 7, −0.076 | 48, +0.005 | 3.19 v 3.92 |
| 2024-25 | Ipswich 2 → 4 → 3 | 3, −0.010 | 57, +0.003 | 2.00 v 3.96 |
| 2025-26 | Sunderland 121 → 69 → **51** | 24, −0.029 | 20, −0.003 | 2.93 v 4.04 |

The centre did what it was built to do — a third fewer Luton entries, a quarter fewer Sunderland entries than v2 —
and the slice still loses in the cells where a promoted club's players remain in the top 30 (they still underperform
it: 3.2 v 3.9, 2.9 v 4.0). The worst 2025-26 cells are unchanged from v2: cutoff 2 (10 → 1 Sunderland players, cell
Spearman +0.06 → −0.28), the record's clean-sheet runaway having been lucky. The 2023-24 net did not move because
the seven cells Luton still enters lose as much as the nine did under v2.

### 2.4 Sensitivity rows (prereg §4: informational, never a re-choice) — cutoffs 1–13, the same 170 affected cells

| centre (attack / defence) | Δ starters (SE) | Δ top-30 (SE) | per season top-30, own-SE | rule |
|---|---|---|---|---|
| **v3: −0.31 / +0.20** | +0.0018 (0.0008), +2.1 | −0.0075 (0.0055), **−1.35** | −0.0049 (−0.5) / +0.0022 (+0.4) / −0.0205 (−1.7) | MARGINAL |
| six non-endpoint cohorts: −0.31 / +0.16 | +0.0018 (0.0008), +2.2 | −0.0058 (0.0052), −1.1 | −0.0007 (−0.1) / +0.0041 (+0.7) / −0.0215 (−1.8) | MARGINAL |
| halved: −0.155 / +0.10 | +0.0022 (0.0009), +2.5 | −0.0064 (0.0057), −1.1 | +0.0029 (+0.3) / +0.0064 (+1.0) / −0.0295 (−2.5) | MARGINAL (2025-26 own-SE too) |
| attack only: −0.31 / 0 | +0.0018 (0.0008), +2.2 | −0.0082 (0.0055), −1.5 | −0.0004 (0.0) / +0.0007 (+0.1) / −0.0259 (−2.1) | MARGINAL (2025-26 own-SE too) |
| v2: 0 / 0 (for the reader) | +0.0022 (0.0011), +2.1 | −0.0093 (0.0062), −1.5 | −0.0042 / +0.0016 / −0.0264 | MARGINAL |

Every centre on the table converges, keeps every λ inside the box, never needs the box on the record, and leaves the
unaffected cutoffs bit-identical. Every one is MARGINAL by the same clause: the pooled top-30 slice sits between −1.1
and −1.5 SE, and it is 2025-26 that puts it there at every centre (−0.02 to −0.03), while 2023-24 and 2024-25 hover
about zero. The stamps (`mu_promoted`) were checked on every sensitivity file before its endpoint was read.

## 3. The decision at the stop point (prereg §5 step 2)

**MARGINAL by the rule fixed before the number: not adopted.** Not falsified (no pooled slice below −2 SE; every
structural gate held: unaffected cutoffs bit-identical, 114 of 114 fits converged, every λ inside [0.15, 6.0] with
the 2024-25 Ipswich cells 0.0007 → 0.805, nearest established club 0.66 from a bound, step-0 movement 0.071 at most
with an affected club and 0.0013 without). Marginal on the pooled top-30 slice, −1.35 SE. The rule is applied as
written; the bar is not amended; no sensitivity row is a re-choice.

**What the result says.** The centre is not the problem. Against v2 it did what the prereg said it would — promoted
clubs' early λ down a quarter, fewer of their players in the top 30, the top-30 slice better, starters unchanged —
and the slice is still marginal, because what is left is the component the prereg said would not go away: in
2025-26 the record's Sunderland runaway put a block of one club's players into the top 30 in weeks they scored, and
removing a runaway that paid off reads as a loss on a 30-item rank correlation. No centre on the sensitivity table
moves 2025-26 out of [−0.02, −0.03]. The 2023-24 "Luton flaw" reading of prereg §0 was not borne out: Luton's cells
did not respond to the centre. Starters — the broad slice, where most decisions are made — are up about 2 SE under
every form tried (v2, v3, every sensitivity row).

**Consequence, as the prereg says:** no fourth form without a new argument about what is wrong, and there is none
here — the hinge and the box do their job (the runaway is gone, every fit converges, the floor is 0.25× the league
rate), and the endpoint's residual is the reference's luck, not the form's error. The sensible answer is the user's:
stop changing the prior and let Coventry score. The loud detector keeps carrying the artefact to `/health` and the
phone; Friday's GW5 runs ship exactly as today.

What is in the tree: v3's code and tests on branch `hinge-box-v2` (commits f41a0fe v2, adddc17 v3; suite 433
passed, 1 skipped; unpushed — the model path cannot go to main without the rebuild, and the GW5 extraction-parity
test diverges against the old record by design). main carries the logs, the prereg status lines and KNOWN_ISSUES
#25's note; nothing pushed, nothing deployed, the record untouched. If the user ever wants the form in despite the
rule, the path is scripted (`rebuild_hinge.ps1`, `*_pre_hinge`) — but it would be a judgement call and must be
named as one, never as a passed pre-registration.
