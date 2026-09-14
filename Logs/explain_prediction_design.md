# Design — `explain_prediction`, levels 1 and 2 (2026-09-13; DESIGN ONLY, nothing built)

> **BUILT 2026-09-14** as designed, after the DC cutoff-day fix (§8's decision): `explain.py`,
> `model_tools.explain_prediction` / `compare_predictions`, the agent schemas, the prompt clause, the tests —
> `Logs/explain_prediction_log.md` has the code inventory and the proofs (the KNOWN_ISSUES #25 runaway-strength
> flag was added to the fixture line since this design).

Master plan §5.4's "demo": the breakdown of a prediction into the terms the
master equation actually sums, and the term-by-term comparison of two
players. Level 3 (attribution inside a component) is deliberately not here.
Read and presentation only; nothing in the model path changes.

**Read this first: Logs/dc_degenerate_fit_finding_2026-09-13.md.** Grounding
this design in the live frame surfaced that every horizon step ≥ 1 carries
the Dixon-Coles fit's starting point instead of team strengths. The design
below labels that per row (section 4, detector 7); it does not fix it.

## 1. Columns → terms, and the identity asserted

The frame (`_tmp_frame_baseline.parquet`, 62 columns, one row per element
and target gameweek at the run's cutoff) already carries the eight additive
terms `assembly._finish_equation` sums, plus the inputs each is made from:

| term (shown as) | column | made from (columns) | points rule |
|---|---|---|---|
| appearance | `pts_appear` | `p_60plus` (= p_start × p60), `p_play_any` | 2 × P(60+) + 1 × P(play < 60) |
| goals | `pts_goals` | `e_goals` = npxg90 × minutes_frac × fixture_scale_cal + `e_pen_goals` | × GOAL_PTS[position] (FWD 4, MID 5, DEF/GK 6) |
| — of which penalties | `e_pen_goals` × GOAL_PTS | `penalty_share`, `team_pen_rate`, minutes_frac | sub-line of goals, not a ninth term |
| assists | `pts_assists` | `e_assists` = xa90 × minutes_frac × fixture_scale_cal | × 3 |
| clean sheet | `pts_cs` | `p_cs`, `p_60plus` | × CS_PTS[position] (DEF/GK 4, MID 1, FWD 0) |
| defensive contribution | `pts_dc` | `p_dc_hit`, minutes_frac | × 2 |
| saves | `pts_saves` | `saves_per_90`, minutes_frac | E[floor(S/3)], GK only |
| goals conceded | `pts_conceded` | `opp_lambda`, minutes_frac | −E[floor(C/2)], GK/DEF only |
| cards | `pts_cards` | `yellow_per_90`, `red_per_90`, minutes_frac | −(1 × yellow + 3 × red) |
| bonus | `exp_bonus` | (fitted, then zeroed: `bonus_mode = delete`) | 0 by decision |

**Identity asserted, per row:**

    pts_appear + pts_goals + pts_assists + pts_cs + pts_dc + pts_saves + pts_conceded + pts_cards == e_points_core
    e_points_core + exp_bonus == e_points

Against `e_points`, via `e_points_core`: the eight terms are the core, bonus
is the ninth line, and the total the user sees everywhere is `e_points`.
Verified on the live frame: max |residual| 0.0 on all 3,936 rows for both
identities (the collapse sums additive terms per gameweek, so the identity
holds at the per-gameweek grain even for doubles; rates like `p_cs` are
averaged, which is why they are shown as inputs, not summed). The tool
re-asserts both on the row it reads with tolerance 1e-6 and reports a
`reconciles: false` FINDING (with the residual) rather than answering, if
either fails. Tolerance is for float summation order only; anything larger
is a defect, not rounding.

## 2. Where the row comes from, and provenance

From the frame on the volume, the same source `get_my_xi` /
`propose_transfers` read (`_load_frame`), sliced to the requested gameweek
at the frame's cutoff. Not from `model_predictions`: the database carries
only ten of the columns (no `pts_*` terms). Two consequences, and a
recommendation:

- Provenance is the frame's: run_id via the sidecar, `built` freshness line,
  `predictions_as_of_cutoff_gw`, `stale_by_gameweeks` — identical to the
  other frame-based tools. A GW5 breakdown tonight is labelled "as seen from
  the GW4 cutoff".
- Only the latest run is explainable. Recommendation (a separate, small
  change): append the eight `pts_*` columns, `e_pen_goals`, `p_dc_hit`,
  `penalty_share`, `team_pen_rate`, `team_lambda`, `opp_lambda`,
  `fixture_scale_cal`, `understat_id`, `saves_per_90`, `yellow_per_90`,
  `red_per_90` to `model_predictions` for future runs (ADD COLUMN IF NOT
  EXISTS; rows are append-only), so any run's prediction can be explained
  later and the movement between runs (decision 2 of the scheduler) is
  explainable term by term. Not required for levels 1–2 on the current run.

## 3. Level 1 — the breakdown

`explain_prediction(player_id, gw=None)`: gw defaults to the next deadline's
(stale-by-one rule as elsewhere). Response: identity + freshness, the total,
the nine lines in descending absolute contribution with the inputs each was
made from, the penalties sub-line, the reconciliation result, and the
`constants` block (section 4). Names, not ids.

## 4. Constants standing in for models — detected per row where the row can tell, by known-term list where it cannot

Two kinds, and the distinction is the design:

- **Per-row detection** (the frame carries the evidence): the label is
  attached only when the row IS on the constant, so a player with a real
  model value gets no label.
- **Known-term list** (structural: the constant is inside the formula for
  every row, or the frame keeps no marker): the label is attached to that
  term for every row, once, in the same words each time.

| # | what | detection | label kind |
|---|---|---|---|
| 1 | bonus = 0 | `bonus_mode == "delete"` (frame stamp) — every row | known-term: "0 by decision" |
| 2 | defensive contribution at the positional fallback | `p_dc_hit == DC_BASE[position]` (DEF 0.125, MID 0.136, FWD 0.058) — 220 of 585 outfield rows at step 0 | per-row: "flat positional value — no model row" |
| 3 | defensive contribution, forwards, by design | `position == FWD and p_dc_hit == 0.005` (FWD_BASE_RATE) — 47 of 78 | per-row: "flat by design (no forward model; 0.4% hit rate)" |
| 4 | attacking rates from the position prior | `understat_id` is null — 269 of 656 (41%) at step 0; goalkeepers receive the DEF prior | per-row: "position prior, no Understat record" |
| 5 | penalty share fallback | `penalty_share == 0.05` — 323 of 656 (49%) | per-row: "fallback 0.05"; plus the term-level note that the whole penalty term is ~50× undersized (KNOWN_ISSUES #19) and `team_pen_rate` is 0 on 630 of 656 rows, so penalties ≈ 0 for almost everyone |
| 6 | neutral fixture (unmatched Dixon-Coles join) | `team_lambda == 1.40 and opp_lambda == 1.40` — 0 rows tonight | per-row: "league-average fixture — no fixture match" |
| 7 | **degenerate Dixon-Coles fit** (the finding) | `team_lambda ∈ {e^0.25, 1.0}` for EVERY team at that step (test at step level, label each row) — all rows at steps ≥ 1 tonight | per-row: "fixture strength: the fit's starting point (home/away only) — see finding" |
| 8 | sub-appearance floor | `p_play_any = p_start + (1 − p_start) × 0.30` — every row | known-term on appearance: "P(play <60) uses a flat 0.30 for the sub chance" |
| 9 | cards | position rates only (Variant B) — every row | known-term on cards: "position rates, no player model" |
| 10 | saves fallback | 0.3 × position mean where a keeper has no rolling history — not marked on the row | known-term on saves: "may be the 0.3 × position-mean fallback (not marked per row)" |
| 11 | fixture scale linear | gamma 1.0 — every row | known-term on goals/assists: "linear in team strength (gamma 1.0)" |

Not in the breakdown, because they are not terms of `e_points`:
`bench_weight` 0.2 and `VICE_WEIGHT` 0.001 (optimiser); they belong to an
explanation of the XI, not of a prediction. The step-1+ market gap
(`ODDS_HORIZON_GWS = 0`, pure DC) is covered by detector 7 while the fit is
degenerate, and by a known-term note ("steps beyond the deadline use the
fitted Dixon-Coles strengths, not the market") once it is not.

**The labelling wording.** Every line carries exactly one of three words as
its `source`, and the words never vary:

- `model` — "computed by a fitted model for this player/fixture".
- `constant` — "a fixed value standing in for a model this project has not
  built (or has switched off); the same for every player in this situation".
- `rule` — "FPL's scoring rule applied to a model output" (the points
  multipliers; never a disclaimer).

The `constant` lines say WHICH constant in one clause, in a fixed
vocabulary: "flat positional value", "flat by design", "position prior",
"fallback 0.05", "league-average fixture", "the fit's starting point", "0 by
decision", "flat 0.30 sub chance", "position rates", "linear scale". And
the response carries ONE summary line, not an essay:

    "3 of 9 lines are constants standing in for models (defensive
    contribution: flat positional value; penalties: fallback 0.05; bonus: 0
    by decision) — the rest are model outputs under FPL's rules."

The agent quotes the summary line and the labelled lines; it does not
editorialise about them.

## 5. Level 2 — the comparison

`compare_predictions(player_id_a, player_id_b, gw=None)`: both breakdowns on
the same gameweek at the same cutoff, the per-term DIFFERENCE (a − b), the
terms ranked by |difference|, and a sentence naming the terms that account
for ≥ 80% of the gap. Constants are carried on both sides with their
labels, and a difference that comes entirely from a constant on one side is
flagged ("the whole DC gap is a flat positional value vs a model value").
Same freshness and identity checks; the identity is asserted on both rows.

## 6. What the two responses look like on the current frame (GW5 as seen from cutoff 4; computed by hand from the raw rows)

**Level 1 — Haaland, GW5 (5.10 expected points)**

```
built Sat 12 Sep 11:01Z (deadline, run 5) … predicting GW5 as seen from the GW4 cutoff (1 gameweek stale)
Erling Haaland (FWD, Man City) — GW5: 5.10 expected points   [reconciles: yes, residual 0.0000]
  goals            +2.80   e_goals 0.700 (npxG/90 0.79 × 0.97 of 90 min × fixture 0.92) × 4 pts      model | rule
    of which penalties +0.00   penalty_share 0.083 × team_pen_rate 0.000                                model (term ~50× undersized, #19)
  appearance       +1.96   P(60+) 0.97 × 2 + P(play <60) 0.02 × 1                                        model | constant: flat 0.30 sub chance
  assists          +0.47   e_assists 0.158 × 3                                                            model | rule
  defensive contr. +0.01   p_dc_hit 0.005 × 2 × 0.97                                                     constant: flat by design (no forward model)
  clean sheet       0.00   FWD: 0 pts                                                                     rule
  saves             0.00   not a GK                                                                       rule
  conceded          0.00   not GK/DEF                                                                     rule
  cards            −0.15   yellow 0.143/90, red 0.005/90 × 0.97                                           constant: position rates
  bonus             0.00                                                                                  constant: 0 by decision (~0.3/wk understated)
  fixture: team λ 1.284 / opp λ 1.000 — constant: the fit's starting point (home/away only) — see finding
2 of 9 lines are constants standing in for models (defensive contribution: flat by design; bonus: 0 by decision); appearance and cards carry a flat 0.30 sub chance and position card rates; the fixture strength at this step is the fit's starting point.
```

**Level 2 — Haaland vs Isak, GW5 (5.10 vs 3.00; gap +2.10)**

```
term            Haaland   Isak    diff    where it comes from
goals            +2.80   +1.22   +1.58   npxG/90 0.79 vs 0.53; fixture 0.92 (home) vs 0.71 (away) — both fixtures are the fit's starting point, so this is home/away only
appearance       +1.96   +1.74   +0.22   P(60+) 0.97 vs 0.82
assists          +0.47   +0.15   +0.32   xA/90 0.18 vs 0.09 at the same fixture constants
cards            −0.15   −0.13   −0.02   same position rates × minutes
defensive contr. +0.01   +0.01    0.00   both flat by design
clean sheet / saves / conceded / bonus: 0 on both
Goals account for 75% of the gap, assists 15%, appearance 10%. Caveat: at this step neither player's fixture carries a team strength (the fit's starting point) — the goals gap is minutes and rates plus home/away, not opponent quality.
```

**Level 1 — Kelleher (GK), GW5 (3.93):** appearance +1.94 (model; flat 0.30
sub chance), clean sheet +1.41 (p_cs 0.368 = e^−1.0 — constant: the fit's
starting point, away side), saves +0.41 (saves/90 2.31 — model; may be the
0.3 × position-mean fallback), goals +0.33 (npxG/90 0.062 — position prior?
no: understat_id present → model), assists +0.16, conceded −0.27
(opp λ 1.000 — constant: the fit's starting point), cards −0.05 (position
rates), DC 0 (rule: GK excluded), bonus 0. The clean-sheet and conceded
lines make the finding visible on a goalkeeper in one glance, which is the
point.

## 7. Tests (before any code is pushed)

Pure functions over a frame row: the identity assert (pass, and a
deliberately broken row → finding), every detector on synthetic rows
(including detector 7 on a step where all teams share {e^0.25, 1.0}), the
three-word source vocabulary and the summary line, the comparison ranking
and the ≥ 80% sentence, the stale-by-one labelling; plus a live check that
the eight terms reconcile on every row of the current frame.

## 8. Decision needed before building

The finding changes what these tools would say tonight on every row beyond
step 0: "fixture strength: the fit's starting point". Building the tools
without the fix is still right — they would tell the truth — but the user
should decide whether the DC fix (a model-path change with a record impact)
comes first, so that the first breakdowns users read are not dominated by a
defect the project already knows about.
