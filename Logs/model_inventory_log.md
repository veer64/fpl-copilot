# Model inventory — every model in the live path, its features, outputs, training and gates

**Written 2026-09-10, read-only, from the code at HEAD 4bbf8ec (2026-09-04).** Nothing was run; every fact below
is quoted from source or from a log that is named. Where a number comes from a log rather than the code, the log
is cited and the caveat that it was measured on an earlier surface is carried. This is the system's model
documentation: what exists, what each consumes and produces, what is fitted versus computed, and what is on or off.

Configs: `combined` is production, `baseline` is the shadow (`model_tools.py`, `db_write.py`). Both are built at
every deadline by `eval/run_live_deadline.py` through `squad/live_deadline.build_deadline_frame` at horizon 6.

Last touch per live-path file (git): assembly.py / attacking_rates.py / defensive.py / walkforward_arms.py
195da6e 2026-09-04; dixon_coles.py 46ba0e4 2026-09-04; live_deadline.py 25e34ad 2026-09-01; minutes.py /
horizon_minutes.py d199a42, bonus.py 17426f3, props_feature.py a99b11c, walkforward_season.py 7e58d62
(all 2026-08-31); availability_features.py 6d395a8 2026-08-17.

---

## 0. The live path, and the seam

One deadline build = `walkforward_season.walk_forward(season, cutoffs=[gw], horizon=6)` (baseline) or the
arm builder's extracted per-cutoff pipeline (combined). Both call the SAME five component getters, in this order,
then the SAME master equation:

    rates, priors = attacking_rates.get_rates(season, up_to_gw=k)                    # formula, not a fit
    m_k           = minutes.get_minutes(up_to_gw=k, predict_gws=[k], per_fixture=True,
                                        availability=True, train_seasons=tr, predict_season=season)   # 5 LightGBM fits + isotonic
    bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = bonus.get_bonus_model(up_to_gw=k, train_until=tr[-1], predict_season=season)  # LightGBM fit, output zeroed
    f_k           = dixon_coles.get_fixtures(predict_season=season, cutoff_date=gw_start[k], odds_available_until=gw_end[k])  # MLE fit + market inversion
    dc_k          = defensive.get_dc_hits(season, k, targets)                        # LightGBM fits per position per gameweek
    a_k           = assembly.collapse_to_gameweek(assembly.assemble_fixtures(df, cw, mins, rates, priors, f_k, dc_k,
                        bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean, gws=targets, season=season, dc_enabled=True))

`tr = train_seasons_for("2026-27") = ["2022-23", "2023-24", "2024-25", "2025-26"]` (the seasons carrying the
`starts` label; 2022-23 GW1-15 is quarantined, KNOWN_ISSUES #4). `targets = [k .. k+5]`.

Row universe: `season_stack.load_stack()` = `data/history/all_seasons_with_2026_27.parquet` (frozen vaastav archive
2016-17..2025-26 + FPL-API rows for played 2026-27 gameweeks, `eval/fetch_fpl_history.py`) concatenated with the
forward skeleton `forward_skeleton_2026_27.parquet` (one synthetic row per player-fixture for unplayed gameweeks,
measurement columns NaN, `eval/build_forward_skeleton.py`). Element -> Understat id: `crosswalk_2026_27.csv`
(`eval/build_crosswalk.py`; columns season, element, understat_id, matched_name, match_type, match_score,
match_evidence -- no `player_id` column, so assembly sets `player_id = element`, which is what the FPL-official DC
source keys on).

Everything is refit at every build. Nothing in the live path is fitted once and stored; the only stored fitted
artefact the live path reads is the horizon-minutes refit file (section 2), and even that is refit per cutoff.

---

## 1. The minutes model — `squad/minutes.py::get_minutes`

**What it is.** Five LightGBM sub-models plus one isotonic calibrator, composed by the law of total expectation:

    e_minutes = p_start * min_start + (1 - p_start) * p_sub * min_sub

| sub-model | object | config | rows it trains on | label |
|---|---|---|---|---|
| `p_start` (P(start)) | `LGBMClassifier` | 300 trees / 31 leaves / lr 0.05 / seed 42 | every labelled player-gameweek | `starts` (0/1) |
| `p60` (P(60+ min \| started)) | `LGBMClassifier` | 100 / 7 / min_child 100 / reg_lambda 1 / lr 0.05 | rows with `starts == 1` | `played_60 = minutes_capped >= 60` |
| `p_sub` (P(came on \| benched)) | `LGBMClassifier` + `IsotonicRegression(out_of_bounds="clip")` | 200 / 15 / min_child 50 / lr 0.05 | rows with `starts == 0`, SUBF non-null | `came_on = minutes > 0` |
| `min_start` (E[min \| started]) | `LGBMRegressor` | 200 / 15 / min_child 50 / lr 0.05 | `starts == 1`, S1 non-null | `minutes_capped` (minutes clipped at 90) |
| `min_sub` (E[min \| came on]) | `LGBMRegressor` | 100 / 7 / min_child 100 / reg_lambda 1 / lr 0.05 | `starts == 0 & came_on == 1`, SUBRF non-null | `minutes_capped` |

The isotonic layer is fitted on the `p_sub` model's predictions over its OWN training rows (in-sample), then
applied at prediction. (The log's protocol, minutes_model_log §6.6, fitted it on held-out gameweeks; the
production code does not hold out.) `p_start` is deliberately NOT calibrated (log §6.6). Nothing is stored;
`get_minutes.last_models` and `.last_frame` are in-process diagnostics only.

**Every feature it consumes**, named as the code names them. Built in `_prepare` and `_build_frames` from the
collapsed player-gameweek frame (double gameweeks summed then `minutes_capped = min(minutes, 90)`; all rolling
features are shift-then-roll, i.e. strictly past gameweeks of the SAME season).

*Minutes history (from the season stack, per (season, element)):*

| feature | meaning |
|---|---|
| `started_last_gw` | `starts` shifted one gameweek |
| `starts_last3`, `starts_last5` | sum of starts over the previous 3 / 5 gameweeks |
| `avg_min_last3`, `avg_min_last5` | mean of capped minutes over the previous 3 / 5 gameweeks |
| `consec_zero_mins` | run length of consecutive zero-minute gameweeks up to last week |
| `gws_since_last_start` | gameweeks elapsed since the last start |
| `minutes_trend_3` | mean capped minutes last 3 minus mean last 8 (the injury proxy) |
| `is_double_gw` | 1 if the player's team has two fixtures in the gameweek (forced to 0 at prediction under `per_fixture=True`) |

*Position and market (from the season stack):*

| feature | meaning |
|---|---|
| `position_code` | categorical code of GK/DEF/MID/FWD |
| `value` | FPL price in tenths of a million at that gameweek (forward rows carry the price as of the skeleton pull) |

*Prior season (cold start; `_build_frames`, joined on (season, name) via the hard-coded ladder
`order = ["2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]` -- a season missing from this list makes the
whole league cold-start silently; preflight parses it from source):*

| feature | meaning |
|---|---|
| `has_no_history` | 1 if `started_last_gw` or `avg_min_last3` is null (first gameweek of the season for that player) |
| `prev_start_rate` | previous season's start rate (0 if no previous season) |
| `prev_avg_minutes` | previous season's mean capped minutes |
| `prev_games` | previous season's gameweek count |
| `transfer_status` | 2 if no previous-season row (new to the league), else 0 |

*Starter history (starters only; filled 0 for everyone else at prediction):*

| feature | meaning |
|---|---|
| `past60_rate_3`, `past60_rate_5` | share of the player's previous 3 / 5 STARTS that reached 60 minutes |
| `last_start_minutes` | capped minutes in the previous start |

*Availability (`squad/availability_features.py`, from `data/availability_2627.parquet`; built for 2026-27 by
`eval/merge_live_availability.py` = the D6 poller's 10-minute pre-deadline samples where present, else the
fplcache 4x/day snapshot; all columns are the `asof_*` reconstruction of the true deadline state, never the raw
snapshot):*

| feature | meaning |
|---|---|
| `av_status_code` | `asof_status` mapped a=0, d=1, i=2, s=3, n=4, u=5; -1 = no availability row |
| `av_cop_this` | `asof_chance_of_playing_this_round` (NaN kept: null means no news, not a low score) |
| `av_cop_next` | `asof_chance_of_playing_next_round` |
| `av_cop_this_known` | 1 if `av_cop_this` is non-null |
| `av_flag_duration` | consecutive gameweeks the status has been non-`a` |
| `av_just_flagged` | 1 in the first gameweek of a flag (contiguous gameweeks only) |
| `av_just_cleared` | 1 in the first gameweek after a flag clears |
| `av_news_age_days` | deadline minus `asof_news_added`, in days (negative ages nulled) |
| `av_is_departure` | 1 if status `u`, or the news text matches the departure regex |

Feature lists per sub-model (the availability block `AV` is appended to every list because
`AVAILABILITY_DEFAULT = True`):

- `p_start`: `xFP = S1(11) + [has_no_history, prev_start_rate, prev_avg_minutes, prev_games, transfer_status] + AV(9)` = 25 features
- `p60`: `xS2 = S1(11) + [past60_rate_3, past60_rate_5, last_start_minutes] + AV(9)` = 23
- `p_sub`: `xSUBF = SUBF(11, the S1 set) + AV(9)` = 20
- `min_start`: `xS1 = S1(11) + AV(9)` = 20
- `min_sub`: `xSUBRF = [avg_min_last3, avg_min_last5, minutes_trend_3, consec_zero_mins, gws_since_last_start, position_code, value, is_double_gw] + AV(9)` = 17

**Feature importance.** Not logged by the pipeline (`log_mlflow` is False in every live call, and MLflow logs
model objects, not importances). The only record is minutes_model_log.md §5.1 and §5.3, on the pre-availability
11-feature models trained on 2022-23 + 2023-24 (LightGBM split counts):

| P(start) | | P(came on \| benched) | |
|---|---|---|---|
| minutes_trend_3 | 1924 | value | 578 |
| avg_min_last5 | 1649 | minutes_trend_3 | 522 |
| value | 1627 | avg_min_last5 | 375 |
| avg_min_last3 | 1574 | consec_zero_mins | 332 |
| gws_since_last_start | 551 | avg_min_last3 | 326 |
| position_code | 550 | position_code | 253 |
| consec_zero_mins | 521 | gws_since_last_start | 239 |
| is_double_gw | 238 | starts_last5 | 72 |
| starts_last3 | 172 | is_double_gw | 54 |
| starts_last5 | 99 | starts_last3 | 49 |
| started_last_gw | 95 | started_last_gw | 0 |

No importance exists for the 25-feature production fit (with cold-start and availability blocks). The
availability log reports the block's effect only at the metric level (P(start) Brier 0.0803 -> 0.0710,
AUC 0.949 -> 0.961, E[min] RMSE 22.02 -> 20.32; docstring of `get_minutes`).

**What it produces.** `DataFrame[element, gw, name, position, p_start, p60, e_minutes]` for the deadline
gameweek only (`predict_gws=[k]`), one row per player with all S1 + SUBF features non-null. Consumers:

- `p_start` -> `p_60plus = p_start * p60`, `p_play_any = p_start + (1 - p_start) * 0.30`, `pts_appear`; the
  props hook's conditioning (combined); written to Postgres.
- `p60` -> `p_60plus` -> `pts_cs`, the bonus-model `clean_sheets` input.
- `e_minutes` -> `minutes_frac = clip(e_minutes / 90, 0, 1)`, which gates every rate term; written to Postgres.
- `p_sub`, `min_start`, `min_sub` are computed and NOT returned to assembly (see section 13, item 1).
- Steps 1-5: baseline copies the step-0 row unchanged to each target gameweek; combined substitutes the
  horizon refit (section 2).

**How it is trained.** Inside the weekly pipeline, refit at every build. Training mask: all rows of the four
labelled prior seasons plus 2026-27 gameweeks strictly before `k`. Forward-skeleton rows (minutes NaN) are in the
feature frame but excluded from every fit. Sample sizes for the live fit are not logged; the log's figures on a
two-season train set were p_start 43,565, p60 11,854 (12,229 after the universal-feature change), p_sub 29,700,
min_start 12,229, min_sub 4,290 rows -- the live fit uses four seasons, so roughly double. Metrics of record:
Brier p_start 0.0710 (with availability), Brier p60 0.0607, RMSE e_minutes 20.32, composed RMSE 22.97 on the
older surface (minutes_model_log §6.3).

**Gates and constants.** `AVAILABILITY_DEFAULT = True`; `TRAIN_SEASONS` default
`["2022-23","2023-24","2024-25","2025-26"]` (overridden by the harness to the same list);
`PREDICT_SEASON = "2026-27"`; the season ladder `order` (above); `per_fixture=True` (harness); random_state 42
everywhere; minutes cap 90.

---

## 2. The horizon-minutes refit — `squad/horizon_minutes.py`, built by `eval/run_horizon_minutes.py`

**What it is.** The same five sub-models and isotonic layer (`_fit_step`, identical hyperparameters), fitted
SEPARATELY for each horizon step k = 1..5 on lagged pairs: the feature row at gameweek g, the label at g + k
(`_pairs`). Step 0 is `minutes.get_minutes()` verbatim. Prediction for cutoff c, step k uses the cutoff-c feature
row (with `is_double_gw` forced 0). A fitted model, refit per cutoff, one fit per step.

**Features.** Exactly the section-1 lists (`_frames` rebuilds `xFP, xS2, xS1, xSUBF, xSUBRF` from `minutes.S1`,
`SUBF`, `SUBRF` + the availability block). No horizon-specific features exist: levers 2-4 (derivable suspensions,
return dates from news, congestion) were never built (horizon_minutes_log §5). No feature importance is logged.

**Training.** Prior labelled seasons in full, plus 2026-27 pairs whose LABEL gameweek is strictly before the
cutoff (`_train_mask`). Historical three-season builds had 47k -> 38k training pairs per step as the lag grew
(horizon_minutes_log §2). The 2026-27 file `data/horizon/hmin_2026_27_refit.parquet` holds cutoffs 1-3, 11,190
rows (gw2 refresh log §6), i.e. six steps x ~620 players per cutoff.

**Where and when it is fitted.** NOT inside the deadline build. `run_horizon_minutes.py` is SKIP-IF-EXISTS: the
deadline runner's step `run_horizon_minutes (skip-if-exists)` is a no-op once the file exists, so a new cutoff's
rows only appear if the file is deleted and refit during the weekly refresh (the Handoff of 2026-09-01 says
"delete to refresh"; the gw2 log records exactly that). The strict preflight raises for the combined config if
the file lacks rows for the deadline cutoff, so a missed refresh fails the build rather than silently running
stale. (The data-directory inventory log describes the file as "appends a cutoff per week under skip-if-exists";
the code does not append -- it returns.)

**Outputs.** `OUT_COLS = [element, gw, horizon_step, name, position, p_start, p60, p_sub, min_start, min_sub,
e_minutes]` + stamps (`cutoff`, `horizon_minutes_active=True`, `horizon_levers`, `minutes_availability`,
`train_seasons`, `predict_season`). Consumed ONLY by the combined config: `walkforward_arms.minutes_frames`
replaces `p_start`, `p60`, `e_minutes` at steps 1-5 for elements that have a refit row; elements without one keep
the stale step-0 copy (counted as `n_stale`). Nothing else reads the file.

**Gate.** `HORIZON_MINUTES_ACTIVE = False`, `HORIZON_LEVERS = ("refit",)`, `KNOWN_LEVERS = (refit, suspensions,
returns, congestion)`. The gate is a documentation constant: no consumer reads it. The substitution is an input
file, not a flag, and it is what production (combined) runs -- see section 11.

**Verdict of record.** FAILED its pre-registered acceptance test: E[min] MAE worse at every step in every season
(RMSE, Brier, AUC better -- the MAE/mean disagreement is structural), and Spearman fell 7-9% among likely starters
and 7-21% among squad-relevant rows (horizon_minutes_log §3, §5). Not adopted at the module gate; applied in the
production config regardless.

---

## 3. Dixon-Coles, the market inversion, and the synthetic fill — `squad/dixon_coles.py`

**Dixon-Coles (fitted, MLE).** Per fixture: `lam_home = exp(atk[h] + def[a] + hadv)`, `lam_away = exp(atk[a] + def[h])`,
independent Poisson goals with the Dixon-Coles low-score correction `tau(rho)` on 0-0, 1-0, 0-1, 1-1. Negative
log-likelihood weighted by `w = exp(-ln2 / 365 * age_days)` (one-year half-life), minimised by L-BFGS-B from
`x0 = 0` with `hadv = 0.25`. Parameter vector: one attack and one defence per team over the WHOLE odds archive
(`teams = every home/away name in the file`, so relegated and promoted sides all carry a parameter), plus `hadv`
and `rho`. Refit at every build on every match dated strictly before `cutoff_date = first kickoff of gameweek k`.

Training data: `data/history/odds_all_seasons_with_2026_27.parquet` (football-data archive seasons + the FPL-API
fixture slice for 2026-27 with live prices, `eval/fetch_fixtures.py` + `eval/fetch_live_odds.py`). Columns read:
`Date, HomeTeam, AwayTeam, FTHG, FTAG, season, B365H, B365D, B365A`. Sample size = every archived match before
the cutoff (ten seasons on disk per the TEAM_MAP audit note; not logged for the live fit).

**Market inversion (a numerical solve, not a fit).** Where a fixture has all three prices and its date is
`<= odds_available_until`: implied probabilities `p = (1/odds) / sum(1/odds)` (proportional de-vig), then
Nelder-Mead from `(ln 1.4, ln 1.1)` on `(lh, la)` minimising the squared distance between the market's (pH, pD, pA)
and the Poisson-grid (max 10 goals) outcome probabilities. Output `mkt_lam_h`, `mkt_lam_a`, `p_H/p_D/p_A`.

Live 2026-27 prices are NOT Bet365 closing: `eval/fetch_live_odds.py` writes a de-margined MEDIAN consensus over a
fixed 12-book panel (`PANEL`, `MIN_BOOKS = 5`; a fixture with fewer panel books is left unpriced and counted)
into the `B365*` columns because those are the only columns the model reads. The `odds_source` MLflow param and
the pull's provenance sidecar record this.

**Blend (formula).** Per fixture, `priced = odds usable OR synthetic filled`:

    lam_w  = LAM_BLEND_W if priced else 1.0      # LAM_BLEND_W = 0.0 -> lambda is PURE MARKET when priced
    cs_w   = CS_BLEND_W  if priced else 1.0      # CS_BLEND_W  = 0.2 -> 0.2 * DC + 0.8 * market for clean sheets
    lam_home = lam_w * dc_lam_h + (1 - lam_w) * mkt_h
    p_home_cs = exp(-(cs_w * dc_lam_a + (1 - cs_w) * mkt_a))      # and symmetrically for away

`ODDS_HORIZON_GWS = 0` (walkforward_season.py, a fixed project decision): `odds_available_until = last kickoff of
gameweek k`, so only the deadline gameweek's fixtures use the market; steps 1-5 are PURE Dixon-Coles for both
lambda and clean sheets, in backtest and live alike.

**Outputs.** `DataFrame[season, home, away, match_date, lam_home, lam_away, p_home_cs, p_away_cs, odds_used,
lambda_source in {odds, synthetic, dc}]`. Assembly joins on (team, match date) after `TEAM_MAP` and consumes:
`team_lambda` -> `fixture_scale = clip(team_lambda / 1.40, 0.5, 2.0)` scaling `e_goals` and `e_assists`;
`opp_lambda` -> `pts_conceded` and the bonus `goals_conceded` input; `p_cs` -> `pts_cs` and the bonus
`clean_sheets` input; `p_cs` is written to Postgres.

Metrics of record (docstring): WDL accuracy 53.7% (scores the market), CS Brier 0.1718 at w = 0.2; the 0.2 CS
weight is retained on the strength of the CS_UNIFIED negative (assembly.py comment), not its original margin.

**Gates and constants.** `HALF_LIFE_DAYS = 365`, `LAM_BLEND_W = 0.0`, `CS_BLEND_W = 0.2`, `PREDICT_SEASON = "2025-26"`
(default, overridden by the harness), `max_goals = 10`, `ODDS_HORIZON_GWS = 0`, `TEAM_MAP = {Man United: Man Utd,
Tottenham: Spurs, Sheffield United: Sheffield Utd}` (assembly), `PANEL` (12 books) and `MIN_BOOKS = 5` (live odds).

**Synthetic market lambda (fitted, NOT active) -- `squad/synthetic_lambda.py`.** `SYNTHETIC_LAMBDA_ACTIVE = False`.
A LightGBM regressor (300 trees / 15 leaves / lr 0.03 / min_child 20, seed 42, deterministic) refit per cutoff on
`data/d4_market_lambda_dataset.parquet` (2016-17..2025-26 only; NOT extended to 2026-27) predicting the market
lambda for unpriced fixtures from 19 features: market history `mh_own_l5/l10/s2d`, `mh_conc_l5/l10/s2d`,
`mh_opp_own_l5/l10`, `mh_opp_conc_l5/l10`; the cached DC walk-forward `dc_attack`, `dc_defence_opp`; `is_home`;
schedule `sch_rest_days`, `sch_m14`, `sch_rest_days_opp`, `sch_m14_opp`; availability `av_top5_out`,
`av_top5_out_opp`. Logged gain importance (d4_market_lambda_log §5): mh_own_l10 32.2%, mh_own_s2d 15.1,
mh_opp_own_l10 10.6, dc_attack 10.0, is_home 9.9, mh_opp_conc_l10 8.7, dc_defence_opp 7.7, mh_own_l5 3.4, rest
<= 1.1, schedule features exactly 0. Sealed 2025-26 R² 0.851 vs DC-alone 0.595 at the lambda level, but no
e_points or selection gain (§12) -- not adopted. When on, it would fill `mkt_lam_*` for unpriced fixtures and the
ordinary blend weights would apply.

---

## 4. The attacking-rate blend — `squad/attacking_rates.py::get_rates` (formula, not a fit)

**What it is.** `RATE_BLEND_ACTIVE = True` routes to `_blended_rates`:

    prior   = the player's own PREVIOUS-season npxG/90 and xA/90 (ratio of sums) if previous-season minutes >= 450,
              else the position-average prior rate (F / M / D, position = modal per-match position),
              else the league-average outfield prior rate
    current = ratio of sums over 2026-27 gameweeks < k   (0 if none)
    w       = n90 / (n90 + RATE_BLEND_K),  n90 = current-season minutes / 90,  K = 8
    npxg90  = w * current_npxg90 + (1 - w) * prior_npxg90        (same for xa90)

At GW1 `w = 0` for everyone (prior only). Goalkeepers are excluded from the rate table.

**Features / inputs.** Two per-match Understat files: `understat_matches_2025_26.parquet` (prior, via
`BLEND_PRIOR["2026-27"] = "2025-26"`) and `understat_matches_2026_27.parquet` (current), columns
`understat_player_id, gw, minutes, npxG, xA, position`. `npxG` is derived at ingest as `xG - penalty-shot xG`
(`eval/understat_matches.py`), so penalties never enter the rate.

**Outputs.** `rates: DataFrame[understat_id, npxg90, xa90]` and `priors = {F, M, D: {npxg, xa}}`. Assembly joins
rates through the crosswalk; an element with no Understat id, or one absent from both files, takes the position
prior via `pos_lab = {FWD: F, MID: M, DEF: D, GK: D}` -- goalkeepers receive the DEFENDER prior. Consumed by
`e_goals = npxg90 * minutes_frac * fixture_scale (+ e_pen_goals)` and `e_assists = xa90 * minutes_frac *
fixture_scale`, hence `pts_goals`, `pts_assists`, the bonus inputs, and (combined) the props blend.

**Tuning of record.** K chosen on 2023-24 + 2024-25 by pre-registered rule (mean pooled Spearman; the 5-12
plateau, K = 8 the peak at 0.5368) and replicated on sealed 2025-26 (+0.098 npxG / +0.044 xA Spearman over the
static rates; rate_blend_log §3-§6). Adopted 2026-08-18. OPEN: 32-34% of evaluation rows have no usable player
prior and sit on the position mean (§9).

**Gates and constants.** `RATE_BLEND_ACTIVE = True`, `RATE_BLEND_K = 8.0`, `MIN_TIME = 450`, `BLEND_PRIOR` (2023-24
-> 2022-23 ... 2026-27 -> 2025-26), `_MATCHES_CACHE`. Legacy path (gate False, inactive): pooled three prior
Understat seasons from `understat_season_aggregates.parquet` (`PRIOR_SEASONS["2026-27"] = [2023, 2024, 2025]`),
per-position shrinkage `shrunk = w * raw + (1 - w) * prior, w = n90 / (n90 + k)`, k = 2 for forward npxG and 10
otherwise, one position per player from the highest-minutes prior season.

---

## 5. The defensive-contribution model — `squad/defensive.py`

**What it is.** A LightGBM classifier per position (Defender, Midfielder), refit for EVERY target gameweek on
all earlier gameweeks of the SAME season (within-season walk-forward; no cross-season training, because the hit
rate drifts unpredictably -- DC build log §4-§5). Config `LGBMClassifier(n_estimators=150, num_leaves=15,
min_child_samples=40, learning_rate=0.05, random_state=42)`. Forwards get no model: flat `FWD_BASE_RATE = 0.005`.
Goalkeepers are excluded entirely.

Label: `dc_hit = 1{dc_metric >= threshold}`, threshold 10 for defenders and 12 for midfielders/forwards.
Source under `DC_SOURCE = "fpl_official"` (adopted 2026-08-31, a judgement call after a FAILED pre-registration --
dc_source_swap_prereg.md; never cite as a pass): `dc_metric` = the season stack's native
`defensive_contribution` count per (element, GW, fixture), rows with `minutes >= 1`. The `core_insights` path
(CBIT/CBIRT reconstructed from tackles, interceptions, recoveries, blocks, clearances) is retained for
bit-exact reproduction of the frozen 2025-26 records only.

**Features (4)**, shift-then-roll within (player, season):

| feature | meaning |
|---|---|
| `roll_dc90_3c` | mean over the previous 3 matches of `dc_metric / minutes * 90`, clipped at 30 |
| `roll_dc90_5c` | same over the previous 5 matches, clipped at 30 |
| `roll_hit_5` | share of the previous 5 matches that hit the threshold |
| `roll_mins_3` | mean minutes over the previous 3 matches |

No feature importance is logged (the MLflow run logs a per-gameweek Brier table, not importances; and the
pipeline never logs).

**Cold-start rules inside the model.** Rows lacking any feature (a player's first match) are dropped. A position
with fewer than 150 prior feature-bearing rows gets the prior rows' mean hit rate, or 0.13 if there are none.
If no gameweek has features at all, `get_dc_2526` returns an EMPTY typed frame.

**Outputs.** `get_dc_hits(season, k, targets)` returns `[player_id, position, p_dc_hit, gw]`: the player's
gameweek-k estimate repeated for every target gameweek (frozen across the horizon). Assembly consumes
`p_dc_hit` -> `pts_dc = p_dc_hit * 2 * minutes_frac`; rows with no DC row take `DC_BASE = {DEF 0.125, MID 0.136,
FWD 0.058, GK 0.0}` (unknown position 0.10).

**CLOSED 2026-09-11 (Logs/asof_rebuild_log.md): `get_dc_hits` now scores every player with a played row before the
cutoff on his as-of feature row; the lookup described below is gone, the model is unchanged, and the record was
rebuilt. The paragraph is kept as the description of the pre-fix path.**

**Live-path finding (VERIFIED 2026-09-10 on the GW3 recovered frames; KNOWN_ISSUES #22).** `_raw_rows_official` kept only rows with
`minutes_played >= 1`, and `get_dc_2526` predicts only for gameweeks present in that frame. The deadline gameweek
is unplayed at build time (its rows are forward-skeleton rows with NaN minutes), so `dc_out` never contains
`gw == k` and `get_dc_hits` returns empty at EVERY live cutoff, not only early in the season. Every live row then
prices defensive contribution at `DC_BASE`. In the backtest, gameweek k is on disk, so the per-player model does
act. The postflight detector labels the >90%-at-base state "the defensive model's cold-start prior, correct
early-season behaviour" and reports it as a note, so a live build will not raise. The Handoff of 2026-09-01
(item 1) expects predictions to "begin as gws accrue"; on this reading of the code they will not, because the
lookup is `dc_out[gw == cutoff_gw]`, and that gameweek has no played rows. This is the single largest structural
difference between what the backtest of record scored and what production computes. Verified and quantified in
KNOWN_ISSUES #22 (section 15, item 1).

**Gates and constants.** `DC_SOURCE = "fpl_official"`, `SEASON = "2025-2026"` (core path only),
`FWD_BASE_RATE = 0.005`, `FEATURES` (4), min prior rows 150, no-prior fallback 0.13, per-90 clip 30,
`recency_weight = False` (the 0.9^age weighting exists and is off), `DC_RULE_SEASONS = {2025-26, 2026-27}`,
`_DC_HITS_CACHE` keyed (source, season), thresholds 10 / 12, `DC_SEASONS` (walkforward_season) = the same two.

---

## 6. The bonus model — `squad/bonus.py::get_bonus_model` (fitted; output zeroed)

**Does it run?** YES. Every build fits the LightGBM BPS regressor, builds the BPS -> bonus curve, computes
`bonus_mean`, and assembly predicts `pred_bps` for every row and computes `exp_bonus = bps_to_bonus(pred_bps) *
minutes_frac`. Then, because `BONUS_MODE = "delete"`, assembly sets `exp_bonus = 0.0` and `e_points = e_points_core`.
The fit and prediction are dead work; `pred_bps` survives in the frame (a `MEAN_COLS` column) but not in Postgres
(`db_write.PRED_COLS` carries `exp_bonus`, which is 0).

**What it is (when it acts).** Piece 1: `LGBMRegressor(n_estimators=300, num_leaves=31, learning_rate=0.05,
random_state=42)` predicting realised `bps`. Piece 2: empirical curve `E[bonus | bps]` by 5-point bins with at
least 30 rows, linear interpolation, clipped to the bin range. Piece 3: `bonus_mean` = mean realised bonus over
all player-fixture rows at the cutoff, used by the incumbent mode's per-gameweek renormalisation.

**Features (`BPS_FEATURES`, 13)**: `goals_scored, assists, clean_sheets, minutes, is_def, is_mid, is_gk, saves,
yellow_cards, red_cards, goals_conceded, penalties_missed, own_goals` -- realised integers at training; at
prediction assembly feeds expectations: `e_goals, e_assists, p_cs * p_60plus, e_minutes, position flags,
saves_per_90 * minutes_frac, yellow_per_90 * minutes_frac, red_per_90 * minutes_frac, opp_lambda * minutes_frac,
penalty_share * 0.1 * minutes_frac, 0`. No importance logged. Metrics of record: MAE 4.19 BPS, R² 0.747
(Bonus model log §2, walk-forward train <= 2023-24 / test 2024-25).

**Training.** Season stack rows with `minutes >= 1`, seasons `<= train_until` (the harness passes `tr[-1]` =
2025-26) plus 2026-27 gameweeks < k. ~90k rows historically. Refit every build.

**Why deleted.** rho(exp_bonus, realised bonus) among starters ~ -0.03, top-30 -0.09 to -0.19; deletion raised
sliced rank +0.005 / +0.006 (three-season means) and lowered starter MAE in every season; known cost ~0.29
points per realised starter per week of understatement (bonus_delete_prereg §1-§3; KNOWN_ISSUES #20). The
`"outcome"` mode (the same tree evaluated at integer outcomes weighted by the equation's own Poisson
probabilities, caps goals 3 / assists 2 / conceded 4 / saves 8, no renormalisation) carried real signal at a
quarter of the true level and stays gated.

**Gates and constants.** `BONUS_MODE = "delete"` (assembly; alternatives `incumbent`, `outcome`), `_BONUS_CAPS`,
`TRAIN_UNTIL_SEASON = "2024-25"` (default, overridden), `PREDICT_SEASON = "2025-26"` (default, overridden), curve
bin width 5, min rows per bin 30.

---

## 7. The props hook — `squad/props_feature.py::PropsHook` (formula, not a fit; combined only)

**What it is.** A step-0 blend of the market's anytime-goalscorer price into `e_goals`, applied inside
`_finish_equation` after the D1 goals term and before the bonus inputs:

    P_b(appears) = p_play_any  for participation-void books (draftkings, betmgm, bovada; fanduel, onexbet ASSIGNED, unverified)
                 = p_start     for start-void books (betrivers, mybookieag, fanatics, rebet)
    p_cond       = mean over books of p_adj_b * P_b(appears)          # per (element, gw, fixture)
    lambda_mkt   = -ln(1 - clip(p_cond / PROPS_M, 0, 1 - 1e-6))       # PROPS_M = 1.396
    e_goals      = PROPS_W * lambda_mkt + (1 - PROPS_W) * e_goals     # PROPS_W = 0.75
    pts_goals    = e_goals * GOAL_PTS[position]                       # recomputed

Only rows with `gw == cutoff` move; goalkeepers never; a doubling player priced in one fixture only keeps the
model on both (counted); unpriced rows keep the model.

**Inputs.** `data/odds_props/props_consensus_book_2026-27.parquet` (gw, event_id, element, book, p_adj) from
`eval/build_props_consensus.py` (per book: implied probabilities from decimal prices; boards below 50% of the
fixture's largest dropped; each book scaled by mean_total / book_total over the shared element set, min 5 shared
elements; `P_CLIP = 0.99`; market `player_goal_scorer_anytime`; books without an established void rule
`{ballybet, betparx, espnbet, williamhill_us}` dropped and counted), keyed to fixtures through the manifest and
`props_crosswalk_2026-27.csv` (`eval/build_props_crosswalk.py`), pulled pre-deadline by `eval/pull_live_props.py`
(T-90..T-30, re-pulls replace). The appearance probabilities are the cutoff's own minutes frame.

**Outputs.** Modified `e_goals` (and therefore `pts_goals`, `e_points_core`, the bonus `goals_scored` input) on
step-0 outfield rows; counters `n_override`, `n_partial_excluded`, `n_gk_skipped`, `by_gw`. Stamps `props_active`,
`props_spec = "conditional: w = 0.75, m = 1.396"`.

**Verdict of record.** FAILED the pre-registered component test: likely starters +0.0094 against the +0.020 bar
(fourth miss at the same value; props_conditional_prereg.md CLOSE-OUT). `PROPS_ACTIVE = False`. Applied in the
production config regardless (section 11). Strict preflight raises if fewer than `PROPS_MIN_FIXTURE_COVERAGE =
0.80` of the deadline gameweek's fixtures have a consensus board, and if the hook overrides zero rows.

**Gates and constants.** `PROPS_ACTIVE = False`, `PROPS_W = 0.75`, `PROPS_M = 1.396`, `SUB_FLOOR = 0.30`, `EPS = 1e-6`,
`PARTICIPATION_BOOKS`, `START_BOOKS`, `EXCLUDED_BOOKS_NO_VOID_RULE`, `PROPS_MIN_FIXTURE_COVERAGE = 0.80`
(live_deadline), consensus `MIN_BOARD_SHARE = 0.50`, `MIN_SHARED = 5`, `P_CLIP = 0.99`, `assembly.PROPS_HOOK`
(module global; rests None, set and restored in a `finally` by `assemble_cutoff`).

---

## 8. The penalty term and the other D1 terms — `squad/assembly.py` (closed-form; no fit)

D1 = saves, goals conceded, cards, penalty share. `D1_TERMS_ACTIVE = True` (Variant B, adopted 2026-08-17,
d1_log.md).

**Penalty goals** (`PENALTY_FIX_ACTIVE = False`, the pre-fix formula reproduced deliberately):

    penalty_share  = (goals - npg) / (games + 1)     from understat_season_aggregates, PRIOR season (2025 for 2026-27)
                     fallback: mean by raw Understat position label (matches nothing but GK), then 0.05
    team_pen_rate  = sum(penalties_missed) / played gameweeks per (season, team), fallback 0.08
    e_pen_goals    = penalty_share * team_pen_rate * minutes_frac
    e_goals       += e_pen_goals

The term is a known defect (KNOWN_ISSUES #19): `penalty_share` is a per-game penalty-GOAL rate, not a share;
`team_pen_rate` is built from penalties MISSED (~0.02), so the product predicts ~1 penalty goal per season
league-wide against 70-96 realised, i.e. ~50x too small. The join year was moved to the prior season on
2026-08-27 in both gate states (leak fix; stamped `penalty_join_prior_season = True`). The gated fix
(`e_pen_goals = pen_rate_prior * minutes_frac`, first-letter position fallback, 0.0 default) FAILED its
pre-registered sliced-rank test (penalty_fix_prereg.md RESULTS) and stays off. `penalty_share` also feeds the
bonus input `penalties_missed = penalty_share * 0.1 * minutes_frac`.

**Saves** (GK only): `saves_per_90` = the player's rolling mean over the previous 5 gameweeks of
`saves / (minutes + 1) * 90` (same season, shifted); if that is 0 or missing, `0.3 x` the position mean of
`saves_per_90` over the predicted season's played rows. `pts_saves = E[floor(S / 3)]`, `S ~ Poisson(saves_per_90 *
minutes_frac)`, via `_expected_floor_div` (k up to 40).

**Goals conceded** (GK/DEF): `pts_conceded = -E[floor(C / 2)]`, `C ~ Poisson(opp_lambda * minutes_frac)`.

**Cards** (all positions, POSITION PRIOR ONLY by design -- the per-player rolling rate collapsed the GK margin
beta): `yellow_per_90`, `red_per_90` = realised cards per 90 by position over PRIOR seasons' played rows (GKP
folded into GK); `pts_cards = -(yellow_per_90 + 3 * red_per_90) * minutes_frac`.

Feature sources: the season stack (`saves, minutes, yellow_cards, red_cards, penalties_missed, position, team`),
`understat_season_aggregates.parquet` (`goals, npg, games, position`) joined via the crosswalk.

---

## 9. The assembly — `squad/assembly.py::assemble_fixtures` + `_finish_equation` + `collapse_to_gameweek` (arithmetic)

The single source of truth for the equation, evaluated once per PLAYER-FIXTURE and summed to (element, gw).

**Joins, in order.** Skeleton from the stack for `season`, positions != AM, `gws` in targets, exact duplicate
(element, gw, fixture) rows dropped; crosswalk (`player_id = element` when the file has no such column);
minutes on (element, gw); rates on Understat id with position-prior fallback; Dixon-Coles on (team, match_date)
after `TEAM_MAP`, with guards (global match < 90% raises; any team with >= 3 rows matched < 50% raises; residual
unmatched rows take `team_lambda = opp_lambda = 1.40`, `p_cs = exp(-1.40)`); DC hits on (player_id, gw,
fix_rank) with own-gameweek-mean then `DC_BASE` fallback; D1 features on (element, gw, fixture).

**The master equation, per fixture:**

    minutes_frac      = clip(e_minutes / 90, 0, 1)
    fixture_scale     = clip(team_lambda / 1.40, 0.5, 2.0)
    fixture_scale_cal = fixture_scale ** FIXTURE_SCALE_GAMMA if TOPEND_CAL_ACTIVE else fixture_scale   # gamma 1.0, gate off
    e_goals    = npxg90 * minutes_frac * fixture_scale_cal + e_pen_goals
    e_assists  = xa90   * minutes_frac * fixture_scale_cal
    pts_goals  = e_goals * GOAL_PTS[pos]          # FWD 4, MID 5, DEF 6, GK 6
    pts_assists = 3 * e_assists
    p_60plus   = p_start * p60
    p_play_any = p_start + (1 - p_start) * 0.30
    pts_appear = 2 * p_60plus + 1 * max(p_play_any - p_60plus, 0)
    pts_cs     = p_cs * CS_PTS[pos] * p_60plus     # FWD 0, MID 1, DEF 4, GK 4   (CS_UNIFIED = False: p_cs is the 0.2-blended DC/market value)
    pts_dc     = 2 * p_dc_hit * minutes_frac
    pts_saves, pts_conceded, pts_cards, e_pen_goals   as in section 8 (D1_TERMS_ACTIVE = True)
    [combined] PROPS_HOOK(a) rewrites e_goals on step-0 rows; pts_goals recomputed
    e_points_core = pts_appear + pts_goals + pts_assists + pts_cs + pts_dc + pts_saves + pts_conceded + pts_cards
    pred_bps   = bps_model.predict(bps_input)       # computed
    exp_bonus  = 0.0                                # BONUS_MODE = "delete"
    e_points   = e_points_core

**Collapse.** `SUM_COLS` (minutes, actual_points, e_minutes, minutes_frac, e_goals, e_pen_goals, e_assists, all
`pts_*`, e_points_core, exp_bonus, e_points) are summed over a player's fixtures; `MEAN_COLS` (p_start, p60,
p_60plus, p_play_any, npxg90, xa90, team_lambda, opp_lambda, p_cs, fixture_scale, fixture_scale_cal, p_dc_hit,
pred_bps, saves_per_90, yellow_per_90, red_per_90, penalty_share, team_pen_rate) are averaged; `n_fixtures` added.

**Provenance stamps on every row** (walkforward_season / stamp_arm_frame): `season_label, minutes_availability,
odds_horizon_gws, dgw_handling="per_fixture", dc_rule_active, d1_terms_active, cs_unified, penalty_fix_active,
penalty_join_prior_season, topend_cal_active, fixture_scale_gamma, bonus_mode, rate_blend_active, rate_blend_k,
synthetic_lambda_active, train_seasons, cutoff, horizon_step` and, combined only, `arm, props_active,
props_spec, horizon_minutes_active, horizon_levers`.

**Constants (assembly.py):** `GOAL_PTS`, `CS_PTS`, `LEAGUE_AVG_LAMBDA = 1.40`, `TEAM_MAP`, `DC_BASE`, unknown-position
DC fallback 0.10, `D1_TERMS_ACTIVE = True`, `CS_UNIFIED = False`, `PENALTY_FIX_ACTIVE = False`, `TOPEND_CAL_ACTIVE =
False`, `FIXTURE_SCALE_GAMMA = 1.0`, `BONUS_MODE = "delete"`, `_BONUS_CAPS = {goals 3, assists 2, conceded 4, saves
8}`, `PROPS_HOOK = None`, sub-appearance floor 0.30, fixture_scale clip 0.5-2.0, saves prior shrink 0.3,
team_pen_rate fallback 0.08, penalty_share fallback 0.05, bonus `penalties_missed` proxy 0.1, own_goals 0,
fixture-join guards 0.90 / 0.50 (teams with >= 3 rows), `FIXTURE_KEY`, `SUM_COLS`, `MEAN_COLS`.

**Downstream of the frame (not models).** `db_write.py` writes per (run, config, element, gw): `e_points,
e_points_core, exp_bonus, e_minutes, p_start, p_60plus, p_play_any, e_goals, e_assists, p_cs` + cutoff /
horizon_step, plus picks, players_live and the JSONB stamp. `squad/optimize.py` (single-gameweek MIP, the
production free-pick convention) reads `e_points` with `bench_weight = 0.2`, `VICE_WEIGHT = 0.001`, `BUDGET =
1000`, `MAX_PER_CLUB = 3`, MIP gap 0, `XI_TIEBREAK_P60 = False`. The transfer MIP (`DEFAULT_HORIZON = 6`,
`DEFAULT_DECAY = 0.45`, `HIT_COST = 4`, `EARLY_HIT_DISCOUNT_ACTIVE = False`) is not used live yet (no tracked squad
state).

---

## 10. Sources, by origin (what each upstream produced)

| origin | file(s) | producer | consumed by |
|---|---|---|---|
| minutes history, prices, labels, saves, cards, pens, DC counts | `all_seasons_with_2026_27.parquet` (+ `forward_skeleton_2026_27.parquet`) | vaastav archive + `eval/fetch_fpl_history.py` (data_checked gate) + `eval/build_forward_skeleton.py` | minutes, horizon, bonus, defensive (official), D1, assembly skeleton |
| availability | `data/availability_2627.parquet` | `eval/merge_live_availability.py` (D6 poller + fplcache; `asof_*`) | minutes, horizon |
| prior season (minutes) | the stack, via the `order` ladder | as above | minutes cold-start block |
| prior / current attacking rates | `understat_matches_2025_26/2026_27.parquet` | `eval/understat_matches.py` (npxG derived) | attacking_rates |
| penalty record | `understat_season_aggregates.parquet` (season 2025 for 2026-27) | `eval/build_understat_aggregates.py` | assembly penalty term, crosswalk builder |
| element -> Understat id | `crosswalk_2026_27.csv` | `eval/build_crosswalk.py` | assembly (rates, penalty) |
| fixtures + 1X2 market | `odds_all_seasons_with_2026_27.parquet` | `eval/fetch_fixtures.py` + `eval/fetch_live_odds.py` (12-book median) | dixon_coles |
| player props | `props_consensus_book_2026-27.parquet`, manifest, `props_crosswalk_2026-27.csv` | `eval/pull_live_props.py` -> `build_props_crosswalk.py` -> `build_props_consensus.py` | props hook (combined) |
| horizon minutes | `data/horizon/hmin_2026_27_refit.parquet` | `eval/run_horizon_minutes.py` | combined steps 1-5 |

---

## 11. Which models differ between combined and baseline

Identical in both: minutes (step 0), attacking rates, Dixon-Coles and the market inversion, defensive
contribution, bonus (fitted and zeroed), all D1 terms, the penalty term, the assembly and every constant in it,
the stack, crosswalk, availability and odds inputs.

| | baseline (shadow) | combined (production) |
|---|---|---|
| builder | `walkforward_season.walk_forward(cutoffs=[gw], horizon=6)` | `walkforward_arms.cutoff_components` -> `minutes_frames` -> `assemble_cutoff` -> `stamp_arm_frame` |
| minutes at steps 1-5 | the step-0 frame copied unchanged to each target gameweek | `p_start, p60, e_minutes` replaced by the horizon refit for elements with a refit row; stale copy otherwise |
| step-0 `e_goals` | model only | `PropsHook`: 0.75 x market conditional rate + 0.25 x model, outfield, priced fixtures |
| stamps | none of the arm stamps | `arm="both", props_active=True, props_spec, horizon_minutes_active=True, horizon_levers="refit"` |
| extra strict gates | -- | props coverage >= 80% at the deadline gw; hmin file present with the cutoff; > 0 props overrides; > 0 refit rows; `PROPS_HOOK` rests None |

Both levers FAILED their pre-registered tests (sections 2 and 7) and both module gates rest False. The choice of
combined as production is recorded only as the comment at the top of `live_deadline.py` ("the production arm;
baseline is the shadow"). Every other arm and gate in the repo is measured, closed and left OFF; these two are
closed as NOT ADOPTED in their logs and ON in production. The record should carry that plainly.

---

## 12. Fitted or built, but NOT active

1. **Horizon-minutes lever 1** at the module gate (`HORIZON_MINUTES_ACTIVE = False`) -- but its file is consumed by combined (section 2).
2. **Props conditional hook** at the module gate (`PROPS_ACTIVE = False`) -- but installed by combined (section 7).
3. **Bonus LightGBM + curve**: fitted and predicted on every build, zeroed by `BONUS_MODE = "delete"`. Modes `incumbent` and `outcome` are implemented and gated.
4. **Synthetic market lambda** LightGBM (`SYNTHETIC_LAMBDA_ACTIVE = False`); dataset ends at 2025-26.
5. **Legacy static pooled-shrinkage rates** (`RATE_BLEND_ACTIVE = False` path, k = 2 / 10).
6. **Penalty correctness fix** (`PENALTY_FIX_ACTIVE = False`; measured FAIL).
7. **Top-end calibration** `fixture_scale ** gamma` (`TOPEND_CAL_ACTIVE = False`, gamma tuned 0.2, measured FAIL; `FIXTURE_SCALE_GAMMA = 1.0` on disk).
8. **Unified clean-sheet / conceded distribution** (`CS_UNIFIED = False`; tested and reverted).
9. **DC core-insights source** (`DC_SOURCE = "core_insights"` path) and the `recency_weight = True` option.
10. **Availability-off minutes** (`availability=False` path; the pre-2026-08-13 model).
11. **MLflow logging** of every component (`log_mlflow=False` throughout the live path; the `--mlflow` CLI paths exist).
12. **Oracle minutes** (`ORACLE_MINUTES_ACTIVE = False`) -- an instrument that injects realised minutes; must never run in production.
13. Optimizer-side, measured and not adopted: `OPENING_HORIZON_ACTIVE`, `OPENING_ROBUST_ACTIVE` (simulator), `EARLY_HIT_DISCOUNT_ACTIVE` (transfer MIP), `BENCH_ORDER_BY_PLAY` (scoring), `XI_TIEBREAK_P60` (optimize); all False.
14. Never built: horizon levers 2-4; the defender shot-volume rate adjustment (+0.081 DEF) noted in attacking_rates.py; DC cold-start prior by team/position (DC log §10); richer core-insights defensive features.

---

## 13. Constants standing in for a model

1. **`p_play_any = p_start + (1 - p_start) * 0.30`.** The minutes model FITS `p_sub` (P(came on | benched), with
   isotonic calibration) and uses it inside `e_minutes`, then does not return it; assembly substitutes the flat
   0.30. Overstates appearances on the written-off band by ~40% (KNOWN_ISSUES #18). The model that could replace
   the constant already exists in `get_minutes.last_frame`.
2. **Defensive contribution at `DC_BASE` on every live row** (section 5): the per-player model exists and is fitted,
   but the live deadline gameweek has no played rows to score, so `{DEF 0.125, MID 0.136, FWD 0.058, GK 0}` is what
   production prices. Plus `FWD_BASE_RATE = 0.005` (by design, no signal) and the 0.13 / prior-mean cold-start values.
3. **Penalty term**: `penalty_share` fallback 0.05 (29% of 2025-26 step-0 rows carried it), `team_pen_rate`
   fallback 0.08, and the whole term ~50x too small (#19). No model of who takes penalties or how often a team wins them.
4. **Attacking position priors** for players with no crosswalk id or no Understat minutes (32-34% of rows at the
   no-prior fallback in the tuning study); goalkeepers take the DEF prior. No cross-league or market-value prior.
5. **Cards**: position rates from prior seasons only, deliberately (Variant B). No player model.
6. **Saves fallback**: 0.3 x the position mean where a keeper has no rolling history.
7. **Neutral fixture** for an unmatched Dixon-Coles join: lambda 1.40 both ways, `p_cs = exp(-1.40) = 0.247`.
8. **Steps 1-5 goal expectations**: pure Dixon-Coles because `ODDS_HORIZON_GWS = 0`; the synthetic model that
   would stand in for the market is gated off.
9. **`fixture_scale` linear in team lambda** (gamma 1.0): the diagnosis says goals do not scale linearly
   (topend_calibration_prereg §1); the calibrated gamma failed and the linear constant stands.
10. **Bonus = 0** for everyone (deleted; ~0.29 pts per starter per week understated by decision).
11. **`own_goals = 0`** and `penalties_missed = 0.1 x penalty_share` as bonus-model inputs (moot under delete).
12. **`bench_weight = 0.2`** in the optimizer: a constant standing in for an autosub model (memory: flat 0.2 is
    correct; the "principled" derived weight lost 187 points).
13. **`VICE_WEIGHT = 0.001`**: a tie-break standing in for P(captain does not play), which the minutes model could supply.
14. **DC threshold GK exclusion / `DC_BASE["GK"] = 0`**: correct by rule, not a gap.

---

## 14. Summary table

| model / term | type | inputs (origin) | outputs | consumed by | active: baseline | active: combined |
|---|---|---|---|---|---|---|
| Minutes (p_start, p60, p_sub, min_start, min_sub) | 5 x LightGBM + isotonic, refit per build | 11 minutes-history + 2 position/market + 5 prior-season + 3 starter-history + 9 availability | p_start, p60, e_minutes | pts_appear, minutes_frac, p_60plus, p_play_any, every gated term | yes (step 0; copied to steps 1-5) | yes (step 0) |
| Horizon-minutes refit (steps 1-5) | 5 x LightGBM + isotonic per step, refit per cutoff (weekly file) | same feature lists on lagged pairs | p_start, p60, e_minutes per step | steps 1-5 of the frame | no | yes (input substitution; gate constant False) |
| Dixon-Coles | MLE Poisson (L-BFGS-B), refit per build | match results, dates (odds archive) | dc_lam_h/a | lambda + CS where unpriced (steps 1-5); 0.2 of CS where priced | yes | yes |
| Market lambda inversion | numerical solve (Nelder-Mead), no fit | B365H/D/A (12-book live median) | mkt_lam_h/a, p_H/D/A | team_lambda, opp_lambda, 0.8 of p_cs at step 0 | yes | yes |
| Synthetic market lambda | LightGBM | 19 market-history / DC / schedule / availability features | syn_lam_h/a | would fill unpriced fixtures | no (gate False) | no |
| Attacking rate blend | formula (k = 8) | prior-season + current-season Understat per-match npxG, xA, minutes | npxg90, xa90, position priors | e_goals, e_assists | yes | yes |
| Defensive contribution | LightGBM per position per gameweek, within-season | 4 rolling DC features (FPL-official counts) | p_dc_hit | pts_dc | fitted; live rows fall to DC_BASE (section 5) | same |
| Bonus (BPS model + curve) | LightGBM regressor + empirical curve, refit per build | 13 realised-component features (expectations at predict) | pred_bps, exp_bonus | exp_bonus = 0 (delete) | runs, zeroed | runs, zeroed |
| Props hook | formula (w 0.75, m 1.396) | per-book anytime-scorer p_adj, p_start, p_play_any | e_goals (step 0) | pts_goals, e_points_core | no | yes (gate constant False) |
| Penalty term | formula (defective, pre-fix) | prior-season Understat pens, team penalties_missed | e_pen_goals | e_goals | yes (D1) | yes |
| Saves / conceded / cards | closed-form Poisson expectations + position priors | stack saves, opp_lambda, prior-season card rates | pts_saves, pts_conceded, pts_cards | e_points_core | yes (D1) | yes |
| Assembly | arithmetic | all of the above + crosswalk + skeleton | e_points_core = e_points, components, stamps | Postgres, optimizer | yes | yes |
| Single-gw MIP (downstream) | optimisation, bench_weight 0.2 | e_points, prices | XI, captain, vice, bench order | picks tables | yes | yes |

---

## 15. Items this inventory surfaced (for decision, not decided here)

**2026-09-11 addendum.** Item 1 was closed, and the leakage audit it triggered found two more terms of the same
shape: the D1 saves feature was not frozen at the cutoff (KNOWN_ISSUES #23) and P(60+ | start)'s starter-history
block was merged from the starts == 1 frame (#24, found by the new as-of guard on its first run). All three
closed the same day, the record rebuilt, the guard wired into the suite (`Tests/test_asof_reconstruction.py`).
Sections 1, 5 and 8 above describe the pre-fix constructions where they say "starter history (starters only;
filled 0 for everyone else)", "dc_out[gw == cutoff]" and "rolling mean over the previous 5 gameweeks (same season,
shifted)"; the fixed constructions are in `Logs/asof_rebuild_log.md` section 3. Item 5 below (the in-sample
isotonic fit) stands.

1. **VERIFIED 2026-09-10, recorded as KNOWN_ISSUES #22.** The defensive-contribution model cannot score a live
   deadline gameweek (section 5): the GW3 recovered frames carry 3,774 / 3,774 rows at `DC_BASE` in both configs
   at every step, with one `p_dc_hit` value per position; the 2025-26 canonical file carried 1,400-1,700 model
   rows per cutoff, including cutoff 3. Structural (`defensive.py` lines 90 / 244 / 318-320), not early-season.
   Cost on the 2025-26 decision partitions: mean |pts_dc diff| 0.17 (likely starters) / 0.22 (top 30), 0.25-0.40
   on defenders, max 1.28; top-30 Spearman -0.031. Postflight cannot raise on it (`findings.append`, not
   `_finding`). Fix direction and the backtest's own played-row selection effect are in #22.
2. The two production levers are stamped ON and logged NOT ADOPTED; nothing in the repo states the adoption
   decision except a code comment. A one-paragraph adoption note in the logs would close that gap.
3. The bonus model is fitted on every build for no consumer. Harmless, but it is the one fit whose cost buys nothing.
4. `run_horizon_minutes.py` is skip-if-exists and never appends; the weekly refresh must delete and refit, or the
   strict preflight fails at the deadline. The data-directory inventory log's description ("appends a cutoff per
   week") does not match the code.
5. The isotonic calibrator on `p_sub` is fitted in-sample in production, unlike the held-out protocol in the log.
6. Goalkeepers with no Understat id receive the DEFENDER attacking prior.
7. The `saves_per_90` fallback uses the predicted season's own position mean (played rows only, so no future
   leak live; a full-season mean in the backtest).
