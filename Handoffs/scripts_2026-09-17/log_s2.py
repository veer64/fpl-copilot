from pathlib import Path

p = Path(r"C:\dev\fpl-copilot\Logs\dc_shrinkage_v2_log_2026-09-17.md")
s = p.read_text(encoding="utf-8")
old = """## 2. Reference builds and the endpoint, verbatim (prereg §2, §3)

(to be filled from the builds launched 16:31Z: scratch `refbuild_v2.py` → `ref_v2_{tag}.parquet` +
`ref_v2_{tag}_fits.json`, one `LAST_FIT` per cutoff; `v2_endpoint.py`)
"""
new = """## 2. Reference builds and the endpoint, verbatim (prereg §2, §3)

Second (corrected) builds, launched 16:51Z, done 17:10Z: scratch `refbuild_v2.py` → `ref_v2_{tag}.parquet` +
`ref_v2_{tag}_fits.json` (one `LAST_FIT` per cutoff); `v2_endpoint.py` (calendar-based opponent map from the
stack's kickoff windows, every fixture assigned, no unpaired row) → `v2_endpoint_ref_v2.json`. Against the record
`data/walkforward_h6_{tag}.parquet` (the 2026-09-13 DC-fix rebuild, no form).

### 2.1 The §2 tells and the structural gates

| | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| affected cutoffs (a league club below N, or at a bound) | 1–11 (Luton; cutoff 1 also Sheffield United, tau 0.087 = 1.5 % of tau_0) | 1–12 (Ipswich) | 1–11 (Sunderland) |
| unaffected cutoffs bit-identical, every column, every row (gate b) | 12–38: **yes** | 13–38: **yes** | 12–38: **yes** |
| rows moved in the affected cutoffs (e_points) | 93.9 %, max Δ 2.26 | 96.1 %, max Δ 3.26 | 96.5 %, max Δ 2.37 |
| box refits (SLSQP) | **0** of 38 | **0** of 38 | **0** of 38 |
| fits converged (gate c) | 38/38, max 123 it | 38/38, max 141 it | 38/38, max 173 it |
| nearest established club to a bound (gate e, ≥ 0.2) | 0.64 (Sheffield United attack, c2) | 0.82 (Southampton attack, c38) | 0.89 (Arsenal defence, c38) |
| max centred attack / defence among league clubs | 0.75 / 0.55 | 0.57 / 0.52 | 0.42 / 0.50 |
| league mean attack (over the 20 clubs) | +0.21 … +0.28 | +0.29 … +0.32 | +0.30 … +0.33 |
| team λ min (gate c, ≥ 0.15) — record | 0.408 (c2 gw3 Sheffield Utd) — 0.408 | 0.508 (c5 gw9 Southampton) — **0.0007** | 0.455 (c7 gw7 West Ham) — 0.188 |
| team λ max (≤ 6.0) | 4.32 | 4.43 | 3.38 |

- **The box never binds on the record.** The prereg named 2024-25 cutoff 2 (Ipswich, λ 0.0007) as the box's one
  record case; the hinge alone holds it — at n_eff 1.0, tau 5.05, Ipswich's attack lands inside and its cells go
  0.0007 → 0.874 (mean over its cells 0.146 → 1.189). So on the record the form is the hinge; the box is exercised
  only by the synthetic tests (n = 8 and 12 scoreless) and would first matter live at eight goalless matches.
- Affected clubs' λ (mean over the club's cells at the cutoff, record → form): Luton c1 0.97 → 1.16, c4
  0.68 → 1.11, c6 0.62 → 0.92, c11 0.75 → 0.76; Ipswich c1 0.99 → 1.31, c3 0.85 → 1.28, c12 1.13 → 1.13;
  Sunderland c1 0.74 → 1.40, **c2 1.99 → 1.53** (the one-clean-sheet defence runaway, the other direction),
  c5 1.07 → 1.16, c11 0.98 → 0.98. The hinge releases where the evidence table said it would.
- **Gate (d), step 0 p_cs.** Fixtures involving an affected club: mean |Δ| 0.0128 / 0.0105 / 0.0121, max
  **0.046 / 0.058 / 0.065** — all under the 0.15 stop. Fixtures NOT involving an affected club, at the affected
  cutoffs: max |Δ| **0.0012 / 0.0016 / 0.0010** — not bit-identical. The mechanism is the form's shared
  parameters (at 2023-24 cutoff 1 the home advantage moved +0.00008 and rho +0.00008; the league mean, over which
  the hinge centres, couples every league club at 1/20 of the hinged club's gradient). v1 §2 stated exactly this
  ("through the fitted home advantage and rho, which are shared, every fixture by a small amount"); v2 §3 (d)
  wrote "bit-identical" for those rows, which no form with shared parameters can deliver. Recorded as an
  overstatement in the prereg's wording — not a falsifier (the falsifier is |Δ p_cs| > 0.15) and not the §2 tell
  (that is cell-level: the unaffected CUTOFFS are bit-identical, and they are). The endpoint script flags it as
  written, so the flag stays in the JSON.
- The first-build tell (§1(d)) is gone: no phantom club moves, no box refit, every fit converged.

### 2.2 The primary endpoint (prereg §3) — pooled over the 170 affected cells (55 + 60 + 55), steps 1–5

| slice | record mean | form mean | paired mean Δ | SE | Δ / SE | cells up / unchanged | falsified (< −2 SE)? |
|---|---|---|---|---|---|---|---|
| likely starters (p_start ≥ .75) | 0.2268 | 0.2290 | **+0.0022** | 0.00106 | **+2.1** | 62 % / 3 % | no |
| top 30 by e_points | 0.1484 | 0.1390 | **−0.0093** | 0.00622 | **−1.5** | 42 % / 10 % | no |

Reported alongside (Δ starters / Δ top-30): per season 2023-24 +0.0009 / −0.0042, 2024-25 +0.0029 / +0.0016,
2025-26 +0.0028 / **−0.0264**; early cutoffs 1–6: +0.0015 / −0.0018, +0.0049 / +0.0013, +0.0038 / **−0.0395**;
top-30 by step, 2025-26: −0.044 / −0.026 / −0.025 / −0.035 / −0.002; 2023-24: +0.014 / −0.032 / −0.013 / −0.037 /
+0.047; 2024-25: −0.019 / −0.004 / +0.008 / +0.014 / +0.010. Season totals: not computed (they need the arm
rebuild, which did not run — see §3); they would be reported, never judged.

**Where the top-30 movement comes from** (scratch `top30_driver.py`; the affected club's players in each cell's
top 30, record v form):
- 2025-26: Sunderland players held **121** top-30 slots across the 55 cells in the record (up to ten in one cell:
  the cutoff-2 defence runaway made their clean-sheet e_points huge), 69 under the form. In the 32 cells where
  Sunderland has a player in the form's top 30, Δ −0.041; in the 20 cells where it has none in either, −0.007.
  The six worst cells are cutoffs 1–2 (Sunderland 10 → 2, 6 → 1, 8 → 1 players; cell Spearman +0.06 → −0.32,
  +0.24 → +0.02, +0.04 → −0.18): the record's runaway happened to rank a block of one club's players highly in
  weeks they scored. Their mean actual points when in the form's top 30: 3.23 v the top 30's 4.07.
- 2023-24: Luton's slots **13 → 34** — the hinge's centre (the league mean) is generous for a promoted club; their
  actual points in the form's top 30 averaged 3.06 v the top 30's 3.91. The 9 cells Luton enters: Δ −0.091; the
  other 46: **+0.013**.
- 2024-25: Ipswich 2 → 4 slots; Δ +0.002 (56 cells without) / +0.007 (4 with).

Reading: the top-30 slice measures where a promoted club's block of players lands, in both directions — removing
a runaway that happened to be "right" costs it (2025-26), and a centre at the league mean that is too generous
for a promoted side costs it (2023-24). The broad slice, likely starters, is up in all three seasons.

### 2.3 Sensitivity rows (prereg §3: informational, never a re-choice) — cutoffs 1–13 of each season, pooled

| row | cells | Δ starters (SE) | Δ top-30 (SE) | per season top-30 | converged / λ min / margin | notes |
|---|---|---|---|---|---|---|
| **the form: N 10, tau_0 5.6, box ln 4** | 170 (all affected) | +0.0022 (0.0011), +2.1 SE | −0.0093 (0.0062), −1.5 SE | −0.0042 / +0.0016 / −0.0264 | yes / 0.408 / 0.64 | |
| N = 6 | 105 | +0.0026 (0.0015), +1.7 SE | −0.0085 (0.0089), −1.0 SE | +0.0001 / +0.0020 / −0.0276 | yes / 0.408 / 0.64 | one unaffected cutoff (2025-26 c9) differs in `pred_bps` by 7e-15, e_points unchanged: bonus-model floating-point noise, not the form |
| N = 15 | 195 | +0.0019 (0.0010), +1.9 SE | −0.0075 (0.0057), −1.3 SE | −0.0042 / +0.0016 / −0.0198 | yes / 0.455 / 0.77 | |
| tau_0 = 2.8 | 170 | +0.0017 (0.0008), +2.0 SE | −0.0091 (0.0056), −1.6 SE | −0.0077 / +0.0034 / −0.0242 | yes / 0.408 / 0.64 | |
| box ln 3 | (pending) | | | | | |
| box ln 6 | (pending) | | | | | |

The pattern is the same in every row: starters up ~2 SE, top-30 down 1–1.6 SE, 2025-26's top-30 the whole of it.
The box rows can only reproduce the form exactly (the box never binds on the record).
"""
assert old in s
p.write_text(s.replace(old, new), encoding="utf-8")
print("s2 written")
