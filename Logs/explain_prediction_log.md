# explain_prediction — levels 1 and 2, built (2026-09-14)

Design of record: `Logs/explain_prediction_design.md` (approved as written on 2026-09-13; built after the
Dixon-Coles cutoff-day fix, as its §8 asked). Read and presentation only; nothing in the model path changed.

## 1. What was built

- `explain.py` (root, pure functions, no database, no files, no model import): `reconcile(row)` — the two
  identities (eight terms == `e_points_core`; core + bonus == `e_points`) at tolerance 1e-6, a failure is a
  FINDING; `step_is_degenerate(step_rows)` — detector 7, every club at the fit's starting point; `breakdown(row,
  step_rows)` — the nine lines in descending |points| with inputs, formula, ONE of `model` / `constant` / `rule`,
  the constant's fixed label, the penalties sub-line, the fixture line, the summary sentence, `rendered`;
  `compare(a, b)` — per-term difference ranked, the ≥ 80 % sentence, the constant-vs-model flags, the
  both-fixtures-constant caveat. The model's constants (GOAL_PTS, CS_PTS, DC_BASE, LEAGUE_AVG_LAMBDA,
  FWD_BASE_RATE) are restated in the module so the API process does not import the model stack to explain a
  row; a test asserts they equal `assembly`'s and `defensive`'s.
- Detectors, per the design's §4: 1 bonus `0 by decision` (frame stamp); 2 `flat positional value` (p_dc_hit at
  DC_BASE[position]); 3 `flat by design` (FWD at 0.005); 4 `position prior` (no understat_id — goals AND assists);
  5 `fallback 0.05` (penalty_share; plus the #19 "~50× undersized" note while `penalty_fix_active` is False);
  6 `league-average fixture` (both λ at 1.40); 7 `the fit's starting point` (step-level); 8 the flat 0.30 sub
  chance (note on appearance); 9 `position rates` (cards, a constant line); 10 the saves 0.3 × position-mean
  note; 11 `linear scale` (gamma 1.0) as a note on goals. Added since the design, from KNOWN_ISSUES #25: a
  fixture whose λ is outside [0.15, 6.0] gets "a strength parameter ran off" on the fixture line and in the
  summary — the live 2026-27 artefact is visible in every breakdown it touches.
- `model_tools.explain_prediction(player_id, gw=None)` and `compare_predictions(player_id_a, player_id_b,
  gw=None)`: the raw frame on the volume (every column, via `_frame_raw`, same file and same sidecar check as
  `_load_frame`, factored into `_check_sidecar`), sliced to the gameweek; gw defaults to the next deadline's;
  the frame-tool provenance (`predictions_as_of_cutoff_gw`, `stale_by_gameweeks`, `built`, `next_run_expected`,
  `run_id`, `note_stale`); errors for a gameweek outside the frame and for a player with no row.
- `agent.py`: the two tool schemas and dispatch; `prompts/system_prompt.md` section 1: quote the `summary`
  and the labelled lines as given, the three words are the tool's, do not editorialise, report a `finding`
  instead of a breakdown that does not reconcile.
- `Tests/test_explain_prediction.py` (11): constants equal the model's; identity pass and a broken row →
  finding; nine lines sorted, three-word vocabulary; the fixed labels; per-row detectors (positional DC, position
  prior, penalty fallback, and a real model value gets no label); the step-level detector (all-20 fires, mixed
  does not); neutral and runaway fixtures; goalkeeper lines; compare ranking, the 80 % sentence, the
  constant-vs-model flag, gameweek mismatch raises; rendered blocks; and on the live frame when present: every
  row reconciles and the step detector agrees with the data.

## 2. Local proof on the synced run-5 frame (the pre-fix frame: cutoff GW4, GW4–9; database reads stubbed)

The frame the server serves until the next successful run — built 12 Sep 11:01Z by the OLD code, so steps ≥ 1
are at the fit's starting point, exactly as the design's hand-computed examples had it. Verbatim:

```
Erling Haaland (FWD, Man City) -- GW5: 5.10 expected points   [reconciles: yes, residual +0.0000]
  goals                   +2.80   e_goals 0.700 (npxG/90 0.79 x 0.97 of 90 min x fixture 0.92 + pens 0.000) x 4 pts model
    of which penalties  +0.00   penalty_share 0.083 x team_pen_rate 0.000 x 0.97 min x 4 pts       model
  appearance              +1.96   P(60+) 0.97 x 2 + P(play <60) 0.02 x 1                                 model
  assists                 +0.47   e_assists 0.158 (xA/90 0.18 x 0.97 of 90 min x fixture 0.92) x 3 pts   model
  cards                   -0.15   -(yellow 0.143/90 x 1 + red 0.005/90 x 3) x 0.97 min                   constant: position rates
  defensive contribution  +0.01   p_dc_hit 0.005 x 2 x 0.97 min                                          constant: flat by design
  clean sheet             +0.00   FWD: 0 pts                                                             rule
  saves                   +0.00   not a GK                                                               rule
  goals conceded          +0.00   not GK/DEF                                                             rule
  bonus                   +0.00   bonus_mode = delete                                                    constant: 0 by decision
  fixture: team lambda 1.284 / opp lambda 1.0 (scale 0.9172) -- constant: the fit's starting point
3 of 9 lines are constants standing in for models (cards: position rates; defensive contribution: flat by design; bonus: 0 by decision) -- the rest are model outputs under FPL's rules; appearance carries a flat 0.30 sub chance; the fixture strength at this step is the fit's starting point.
```
`stale_by_gameweeks` 1; `note_stale` "the frame on the volume is GW4's … GW5's predictions here are as seen
from cutoff GW4, 1 gameweek(s) stale …".

```
Caoimhín Kelleher (GK, Brentford) -- GW5: 3.93 expected points   [reconciles: yes, residual +0.0000]
  appearance              +1.94   P(60+) 0.96 x 2 + P(play <60) 0.02 x 1                                 model
  clean sheet             +1.41   p_cs 0.368 x 4 pts x P(60+) 0.96                                       model
  saves                   +0.41   E[floor(S/3)], S ~ Poisson(saves/90 2.31 x 0.96 min)                   model
  goals                   +0.33   e_goals 0.055 (npxG/90 0.06 x 0.96 of 90 min x fixture 0.92 + pens 0.000) x 6 pts model
    of which penalties  +0.00   penalty_share 0.000 x team_pen_rate 0.333 x 0.96 min x 6 pts       model
  goals conceded          -0.27   -E[floor(C/2)], C ~ Poisson(opp lambda 1.000 x 0.96 min)               model
  assists                 +0.16   e_assists 0.053 (xA/90 0.06 x 0.96 of 90 min x fixture 0.92) x 3 pts   model
  cards                   -0.05   -(yellow 0.052/90 x 1 + red 0.001/90 x 3) x 0.96 min                   constant: position rates
  defensive contribution  +0.00   GK: excluded                                                           rule
  bonus                   +0.00   bonus_mode = delete                                                    constant: 0 by decision
  fixture: team lambda 1.284 / opp lambda 1.0 (scale 0.9172) -- constant: the fit's starting point
```
(The clean-sheet 0.368 = e^−1.0 and the conceded line on opp λ 1.000 make the finding visible on a keeper in one
glance, as the design intended.)

```
term                   Erling Haaland Alexander Isak    diff
goals                           +2.80          +1.22   +1.58
assists                         +0.47          +0.15   +0.32
appearance                      +1.96          +1.74   +0.22
cards                           -0.15          -0.13   -0.02
defensive contribution          +0.01          +0.01   +0.00
clean sheet / saves / goals conceded / bonus       +0.00 on both
Erling Haaland 5.10 vs Alexander Isak 3.00 (gap +2.10): goals 73%, assists 15% of the absolute gap.
both fixtures are the fit's starting point: the goals/assists gap is minutes and rates plus home/away, not opponent quality
```
GW12 → "the frame on the volume has no predictions for GW12: it covers GW4-GW9 as seen from cutoff GW4". GW4
(step 0) → fixture source `model` (market-priced).

One departure from the design's sample text, resolved toward consistency: the design's table labels cards as
`constant: position rates` but its sample summary counted "2 of 9"; the tool counts cards as the constant line
it is ("3 of 9") and mentions the sub-chance note once.

## 3. Deployed and proven in the image (2026-09-14 02:30Z)

Pushed ccb82ce (with e090ccb, the prior-off / alias commit, verified by the same suite); "Deploy to Server"
landed and `/health` reported `git_sha` ccb82ce39, status `ok`, at 02:30:27Z — no build slot was running
(dispatch state: no slots; last tick 02:20Z), 3 h 47 min before the 06:17Z ingest tick. Then, inside the
scheduler image against the real volume and database (`docker compose run --rm --no-deps -T`, read-only):

- `explain_prediction(411, gw=5)` → the Haaland breakdown of §2 byte-for-byte, with real provenance: `run_id`
  5, `stale_by_gameweeks` 1, `built` "built Sat 12 Sep 11:01Z (deadline, run 5) -- knowledge not recorded (a
  pre-multi-run row) -- predicting GW4 -- next run when GW4 confirmed by FPL and ingested …", `note_stale`
  "the frame on the volume is GW4's (built 2026-09-12 11:00Z); GW5's predictions here are as seen from cutoff
  GW4, 1 gameweek(s) stale …".
- `explain_prediction(82, gw=5)` → the Kelleher breakdown of §2, same provenance.
- `explain_prediction(411, gw=4)` (step 0, the deadline gameweek) → 5.89 expected points; goals +3.48 on
  fixture 1.14; **fixture line `team lambda 1.5953 / opp lambda 1.2393 -- model`** (market-priced at step 0),
  summary with no fixture caveat, `stale_by_gameweeks` 0. The same player one step apart shows the step-0 /
  step-1 difference the finding described.
- `compare_predictions(411, 379, gw=5)` → the table of §2 (goals 73 %, assists 15 %; both fixtures at the
  starting point).
- GW12 → the covered-range error; an unknown element → the no-row error. No exceptions; every result
  reconciled at residual +0.0000.

Both tools will show the fixture line as `model` at every step once a post-fix run lands (post_ingest:GW4 when
FPL confirms GW4), and the "parameter ran off" flag on Coventry's and Hull's fixtures at steps ≥ 1 until the
KNOWN_ISSUES #25 remedy exists.

## 4. The stored-terms path: `explain_prediction(run_id=…)` and `compare_runs` (2026-09-14, afternoon)

Now that every run records its terms (`Logs/model_predictions_terms_log.md`), the same pure `explain.breakdown`
/ `compare` run over a row built from the database:

- `model_tools._rows_from_db(run, config, gw)`: the gameweek slice of a stored run as a frame-shaped DataFrame —
  the terms and inputs from `model_predictions`, `name` / `position` / `team` from `players_live`, the per-run
  frame stamps (`bonus_mode`, `penalty_fix_active`, `fixture_scale_gamma`, `topend_cal_active`,
  `odds_horizon_gws`) from `model_runs.model_stamp`. A run whose terms are NULL (every run up to 5) raises, and
  the tools answer with that error — "no recorded terms … never backfilled — only its totals can be read".
- `explain_prediction(player_id, gw, run_id=…)`: the stored breakdown with that run's provenance (`built`,
  `predictions_as_of_cutoff_gw`, `stale_by_gameweeks`, `source: database`). `gw` is required with `run_id`.
- `compare_runs(player_id, gw, run_id_a, run_id_b)`: both stored breakdowns, the per-term difference a − b
  ranked, the ≥ 80 % sentence, the constant-vs-model flags, and what each run knew (`run_a.built`,
  `run_b.built`, each run's cutoff) — the "Tuesday said 8.5, Friday says 6.2" answer. `explain.compare` gained
  `label_a` / `label_b` so the rendering says "run 7 vs run 9" for one player.
- Agent: `run_id` on the explain schema, the `compare_runs` schema and dispatch, the prompt clause extended.
- Tests: `Tests/test_explain_runs.py` (4) over a stubbed database: a breakdown from the database equals the
  breakdown from the same row in a frame, term for term; NULL terms → the error; unknown / FAILED run, a
  gameweek outside the horizon, a missing player, `gw` missing; `compare_runs` ranks the move, labels the sides,
  carries both `built` lines and both cutoffs.
