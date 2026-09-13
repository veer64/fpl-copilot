# FINDING — the live Dixon-Coles fit is degenerate on every 2026-27 build (2026-09-13 ~03:00Z)

Found while designing `explain_prediction` (the breakdown would have shown
it on the first row a user read). NOT fixed: `squad/dixon_coles.py` and the
walk-forward path are model path, parity-locked and as-of-guarded, and the
fix changes the backtest record (section 5). Nothing pushed. Reported.

## 1. What the frame shows

Every live 2026-27 frame (the GW3 recovered and server frames, run 5's GW4
frame) carries EXACTLY TWO lambda values at every horizon step ≥ 1:
`team_lambda` / `opp_lambda` ∈ {1.284, 1.000} — home 1.284, away 1.000, for
all twenty clubs, every gameweek 5–9. Step 0 (the deadline gameweek) has
twenty distinct values. The 2025-26 walk-forward record has twenty distinct
values at EVERY step (checked at cutoffs 4 and 20, steps 0–2).

1.284 = e^0.25 and 1.000 = e^0: the Dixon-Coles fit's INITIAL parameters
(`_fit_dc_decay`: `x0 = zeros; x0[-2] = 0.25`). The optimiser never moved.

## 2. Reproduction (inside the scheduler image, read-only)

The live builder (`walkforward_arms.cutoff_components`, called by
`live_deadline.build_deadline_frame`) calls

    get_fixtures(predict_season="2026-27", cutoff_date="2026-09-12 14:00:00",
                 odds_available_until="2026-09-14 19:00:00")

(`cutoff_date = gw_start.loc[k]` = the FIRST KICKOFF of the cutoff gameweek,
with its time of day). Isolated:

| call | GW5 distinct lam_home | note |
|---|---|---|
| cutoff `2026-09-12` (midnight), no odds_until | 10 | GW5 priced by the live odds pull (market) |
| cutoff `2026-09-12 14:00`, no odds_until | 10 | same — market masks the fit |
| cutoff `2026-09-12`, odds_until 14 Sep | 10 (1.613, 1.45, …) | pure DC, fit healthy |
| **cutoff `2026-09-12 14:00`, odds_until 14 Sep** | **1 (1.284)** | **pure DC, fit degenerate — the live call** |

The fit alone: cutoff at midnight → 3,830 training rows, max|attack| 6.05,
home advantage 0.174; cutoff at 14:00 → **3,837 rows, 7 with NaN goals,
max|attack| 0.0, home advantage 0.25 (= x0)**.

## 3. Mechanism

`get_fixtures` builds `train_m = matches[date_parsed < cutoff]`. Match dates
are day-stamped (midnight); the live cutoff carries a time of day. So the
cutoff DAY's fixtures with kickoffs later than the cutoff time — unplayed,
`home_goals` NaN — enter the training set. `poisson.logpmf(NaN, …)` makes the
negative log-likelihood NaN, L-BFGS-B terminates at iteration 0, and the
fit returns its starting point. No error is raised anywhere; postflight has
no non-degeneracy check on DC strengths. Silent-fallback family.

Live it happens on EVERY build, because the cutoff is by construction the
first kickoff of a gameweek whose fixtures on that day are unplayed. In the
backtest it never happens, because the cutoff day's fixtures are played
(goals present) — which is also section 5.

## 4. Scope and consequences

- **Steps 1–5 of every live frame carry no team strength at all**: fixture
  difficulty is home/away only. The six-week transfer MIP's horizon
  (proposals 1–4 of 2026-09-12, the "later steps"), `get_my_xi`'s stale-by-one
  GW5 XI served last night (Isak benched at e_goals 0.306 with
  `fixture_scale` 0.714 = 1.0/1.4 — the away constant, not Liverpool's
  opponent), and every `propose_transfers` result beyond step 0 were computed
  on flat fixtures.
- **Step 0 is mostly protected by the market**: goal expectations are pure
  market (`LAM_BLEND_W = 0`) where odds exist (all 10 GW4 fixtures were
  priced). Clean sheets blend `0.2 × DC + 0.8 × market`, so step-0 `p_cs`
  carries a 20% share of a degenerate CS (exp(−1.284) = 0.277 / exp(−1.0) =
  0.368 in place of the real DC value). Any step-0 fixture the odds pull
  does not price falls to the degenerate DC entirely.
- **The 2025-26 record and every backtest figure are unaffected** by the
  degeneracy (their fits trained on played rows). The H6 / decay 0.45
  choices stand as evidence about the METHOD; the live horizon is currently
  weaker than the backtest implies.
- The deadline-day runs on Friday (t90/t30/t10) will carry the same defect
  at steps 1–5 and in 20% of step-0 clean sheets; step-0 goals are fine
  where priced.
- Nightly / post-ingest runs: the cutoff is the NEXT deadline gameweek's
  first kickoff (a future date), so the whole cutoff day's fixtures are
  unplayed → degenerate as well.

## 5. Corollary for the backtest (to verify, not verified here)

In the backtest the same `date_parsed < cutoff(time)` filter admits the
cutoff day's PLAYED matches — results of fixtures that kicked off AT OR
AFTER the cutoff time on the cutoff day (the cutoff is that day's first
kickoff). That is a small as-of leak in the record's Dixon-Coles training
set, of the class LEAKAGE.md items 6–9. The as-of guard cannot see it: it
reconstructs the inputs as the record built them (both sides share the
filter). Quantify before deciding: how many cutoff-day matches per cutoff
(often 1–3 on a Saturday cutoff day), and whether excluding them moves
the record.

## 6. Fix direction (NOT applied — the user's decision; model path)

One of: `train_m = matches[(date_parsed < cutoff) & home_goals.notna()]`
(train on played matches only — also closes section 5 on the record), or
compare at day granularity `date_parsed < cutoff.normalize()` (excludes the
whole cutoff day — closes section 5 too but drops legitimately-played
earlier-in-the-day matches at steps ≥ 1, which the backtest never had), or
keep the filter and make the fit REFUSE NaN goals (loud, would have raised
on 2026-09-04). Any of them changes the record → parity moves by design →
a re-registration and a rebuild decision, not a hotfix. Add a postflight
detector either way: "DC strengths degenerate (all zero) — refusing" in
strict mode, and a per-row label in `explain_prediction`
(`team_lambda ∈ {e^0.25, 1.0}` across all teams at a step).

## 7. What I did not do

Did not edit `dixon_coles.py`, `assembly.py`, `walkforward_arms.py` or the
postflight. Did not push. Did not re-run any build that writes. The
explain_prediction design (Logs/explain_prediction_design.md) now carries a
detector for exactly this pattern, because that is what the feature is for.
