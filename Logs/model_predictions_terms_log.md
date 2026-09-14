# Term columns on `model_predictions` — design and build (2026-09-14)

Why: with five runs a week the database keeps every run's `e_points` but not its reasons; when someone asks
why Tuesday's run said 8.5 and Friday's said 6.2, the frames that could answer are gone (only the latest
frame lives on the volume, and `explain_prediction` reads that). The design of record for the breakdown
(`Logs/explain_prediction_design.md` §2) recommended appending the terms to `model_predictions`.

## 1. Design

**Which columns.** Exactly what `explain.breakdown` reads, so a stored row can be explained the way a frame
row is, term by term, later:

| group | columns | type |
|---|---|---|
| the eight additive terms | `pts_appear, pts_goals, pts_assists, pts_cs, pts_dc, pts_saves, pts_conceded, pts_cards` | REAL |
| the penalties sub-line | `e_pen_goals, penalty_share, team_pen_rate` | REAL |
| the inputs the lines are made from | `p60, minutes_frac, p_dc_hit, team_lambda, opp_lambda, fixture_scale_cal, npxg90, xa90, saves_per_90, yellow_per_90, red_per_90` | REAL |
| identity of the rates and the grain | `understat_id` (TEXT; NULL = position prior), `n_fixtures` (INT) | |

Already there: `e_points, e_points_core, exp_bonus, e_minutes, p_start, p_60plus, p_play_any, e_goals,
e_assists, p_cs`. The frame stamps a breakdown also needs (`bonus_mode`, `penalty_fix_active`,
`fixture_scale_gamma`, `topend_cal_active`, `odds_horizon_gws`) are per run, not per row, and are already in
`model_runs.model_stamp` (STAMP_COLS) — no duplication. 24 new columns.

**Storage cost.** A run writes one row per (element, target gw): 3,936 today (656 players × 6 gameweeks).
The 24 new columns add ≈ 22 × 4 B + a short text + 4 B ≈ 100–110 B per row (plus Postgres per-row overhead
that is already paid). Five runs a week over the ≈ 34 remaining weeks ≈ 170 runs ≈ 670 k rows: the whole
table ≈ 670 k × (existing ≈ 70 B + new ≈ 105 B + tuple header ≈ 30 B) ≈ 140 MB, indexes ≈ 40 MB. The
droplet's disk is 77 GB at 46 %. Not a consideration.

**Widen or sibling.** Widen. The alternative — a sibling `model_prediction_terms` keyed like the parent — would
keep the hot table narrow, but every reader of `model_predictions` already names the columns it wants
(`SELECT e_points, … FROM model_predictions`), so width costs those readers nothing, and one row per
prediction with its own reasons is the simpler invariant (no join that can miss). The explain design chose
widening for the same reason.

**Does widening disturb append-only?** No. Append-only here means rows are inserted and never updated or
deleted (the `(run_id, config, element, gw)` primary key and the absence of any UPDATE path; it is a
convention of the write path, not a trigger, on this table). `ALTER TABLE … ADD COLUMN IF NOT EXISTS` is a
schema change: it touches no row, rewrites nothing (a nullable column with no default is a catalogue-only
change in Postgres), and existing rows read NULL — which is the truth: their terms were not recorded. No
backfill: filling run 5's terms from the frame on the volume would be an UPDATE, and the frame is the only
witness; the honest record is "terms recorded from the first run after this change". The INSERT names its
columns from now on (it was positional), so the statement cannot silently misalign if the column order
changes again.

**Uncontroversial?** Yes: additive, idempotent (`ensure_schema` runs the same `ADD COLUMN IF NOT EXISTS` on
every write), no reader changes, no row rewrites, cost negligible, and it is the design already approved.
Built below.

**What it enables next (not built here):** `explain_prediction(player_id, gw, run_id=…)` reading the stored
row (joined to `players_live` for name / position / team and to `model_runs.model_stamp` for the per-run
stamps) and a run-to-run comparison ("Tuesday 8.5 → Friday 6.2: goals −1.8 because fixture scale …"). That
is the same pure `explain.breakdown` / `compare` over a row built from the database; it needs the first
populated run to prove, which is the post-ingest run for GW4.

## 2. Built

- `db_write.py`: 24 `ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS …` lines in the DDL that
  `ensure_schema` runs on every write, plus a `COMMENT ON TABLE` stating the NULL semantics; `TERM_REAL_COLS`
  / `TERM_COLS` / `PRED_INSERT_COLS`; `prediction_rows(run_id, config, frame)` builds the rows (absent or NaN
  → NULL, `understat_id` stored as the integer text, `n_fixtures` as INT) and `prediction_insert_sql`
  names every column — the positional `INSERT … VALUES (%s × 16)` is gone. `write_run` calls the two.
- `Tests/test_db_write_terms.py` (5): the DDL has every column, idempotent, no default, no UPDATE, the comment;
  the INSERT names its columns with matching placeholders; rows carry the terms and NaN / absent become NULL;
  the stored set covers everything `explain.breakdown` reads; the production frame carries every term column
  and builds rows with no NULL term.
