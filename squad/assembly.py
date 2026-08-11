# assembly.py
# E[points] assembly orchestrator. Imports the five component modules, joins their
# outputs through the crosswalk, applies the master equation (with playing-probability
# gating), and validates against actuals. See ASSEMBLY_LOG.md for the full story.
#
# Run: `python assembly.py` (retrains all components — a few minutes).
#
# CHANGE (2026-08): bonus.get_bonus_model() now returns a 4th value, bonus_mean —
# the recalibration constant, computed from cutoff-respecting data inside the bonus
# module. Previously assembly computed it from the FULL 2025-26 season, which is a
# leak in any walk-forward context. See LEAKAGE.md.

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

from minutes import get_minutes
from attacking_rates import get_rates
from dixon_coles import get_fixtures
from defensive import get_dc_2526
from bonus import get_bonus_model

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
GOAL_PTS = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}
CS_PTS   = {"FWD": 0, "MID": 1, "DEF": 4, "GK": 4}
LEAGUE_AVG_LAMBDA = 1.40
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs"}
DC_BASE = {"DEF": 0.125, "MID": 0.136, "FWD": 0.058, "GK": 0.0}

MLFLOW_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT = "fpl-components"

METRIC_GLOSSARY = """# Assembly — what these metrics mean

This is the PARENT run. The five component runs nested beneath it are the pieces;
this run scores what they produce once combined through the master equation.

Each component has its own glossary on its own run page. This one covers only the
final combined prediction: expected FPL points per player per gameweek.

**spearman** — rank correlation between predicted and actual points. 1.0 means the
ordering is perfect, 0.0 means no signal. Higher is better.
THIS IS THE HEADLINE METRIC, because the optimizer only needs the right ORDER of
players, not the exact point totals. Getting the ranking right is the whole job.

**pearson** — straight-line correlation between predicted and actual. Reported as
secondary. It is more sensitive to a few huge hauls than spearman is.

**mae** — typical error in predicted points, in actual FPL points. Lower is better.
Treat this as secondary too: a model that predicts 2.1 for everyone can win on MAE
while being useless for picking a squad.

**mae_fair_baseline** — the bar to beat. For each player it predicts their own
running average of past gameweeks. If `mae` is not below this, the model is adding
nothing over "just use their average so far."

**mean_predicted / mean_actual** — average predicted vs average real points.
Not quality scores. A calibration check: if predicted sits well above actual, the
model is systematically over-predicting, even if the ranking is fine.

**n_predictions** — player-gameweek rows produced. A tripwire: a full season is
about 29,338. A sharp drop means a join broke somewhere upstream.

**cal_pred_70plus / cal_actual_70plus** (and the other bands) — average predicted
vs average actual points, split by expected minutes. This is where over-prediction
hides. The 70+ band is the one that matters most: those are the players the
optimizer will actually pick. A gap there is a real, known issue.
"""


def _calibration_table(a):
    """Predicted vs actual points, bucketed by expected minutes. The band table is
    where systematic over- or under-prediction shows up."""
    v = a.dropna(subset=["actual_points", "e_points"]).copy()
    v["band"] = pd.cut(v["e_minutes"], [0, 15, 45, 70, 90], labels=["<15", "15-45", "45-70", "70+"])
    t = (v.groupby("band", observed=True)
         .agg(pred=("e_points", "mean"), actual=("actual_points", "mean"), n=("e_points", "size"))
         .reset_index())
    return t.round(3)


def _eval_metrics(a):
    """Score the final combined prediction. See METRIC_GLOSSARY."""
    a = a.copy()
    a["actual_points"] = pd.to_numeric(a["actual_points"], errors="coerce")
    val = a.dropna(subset=["actual_points", "e_points"]).copy()

    m = {
        "spearman": float(spearmanr(val["e_points"], val["actual_points"]).correlation),
        "pearson": float(val["e_points"].corr(val["actual_points"])),
        "mae": float((val["e_points"] - val["actual_points"]).abs().mean()),
        "mean_predicted": float(val["e_points"].mean()),
        "mean_actual": float(val["actual_points"].mean()),
        "n_predictions": float(len(val)),
    }

    # The bar to beat: each player's own running average of past gameweeks.
    vs = val.sort_values(["element", "gw"])
    vs["fair"] = vs.groupby("element")["actual_points"].transform(lambda s: s.shift(1).expanding().mean())
    f = vs.dropna(subset=["fair"])
    if len(f):
        m["mae_fair_baseline"] = float((f["fair"] - f["actual_points"]).abs().mean())
        m["mae_on_baseline_rows"] = float((f["e_points"] - f["actual_points"]).abs().mean())

    # Calibration by minutes band, flattened so each band is its own metric.
    for _, r in _calibration_table(a).iterrows():
        tag = str(r["band"]).replace("-", "_").replace("<", "under").replace("+", "plus")
        m[f"cal_pred_{tag}"] = float(r["pred"])
        m[f"cal_actual_{tag}"] = float(r["actual"])

    return m


def build_predictions(log_mlflow=False):
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")

    # --- run the five components (each logs a NESTED child run if enabled) ---
    print("Running components...")
    mins_out = get_minutes(up_to_gw=None, log_mlflow=log_mlflow)
    rates, priors = get_rates("2025-26", log_mlflow=log_mlflow)
    fixtures = get_fixtures(cutoff_date=None, log_mlflow=log_mlflow)
    dc_out = get_dc_2526(log_mlflow=log_mlflow)
    bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = get_bonus_model(log_mlflow=log_mlflow)

    # --- 1. skeleton (one row per player-gw, all IDs) ---
    cw = pd.read_csv(BASE + r"\data\history\player_id_crosswalk_final.csv")
    v = df[(df["season"] == "2025-26") & (df["position"] != "AM")].copy()
    skel = v[["element", "GW", "name", "position", "team", "minutes", "total_points"]].copy()
    skel["element"] = pd.to_numeric(skel["element"], errors="coerce").astype(int)
    skel = skel.rename(columns={"GW": "gw", "total_points": "actual_points"})
    skel = skel.merge(cw[["element", "player_id", "understat_id"]], on="element", how="left")
    asm = (skel.sort_values(["element", "gw"]).groupby(["element", "gw"], as_index=False)
           .agg({"name": "first", "position": "first", "team": "first", "minutes": "sum",
                 "actual_points": "sum", "player_id": "first", "understat_id": "first"}))

    # --- 2. minutes ---
    asm = asm.merge(mins_out[["element", "gw", "p_start", "p60", "e_minutes"]], on=["element", "gw"], how="left")

    # --- 3. attacking rates (dedupe + fallback) ---
    rates_clean = rates.sort_values("npxg90", ascending=False).drop_duplicates("understat_id", keep="first")
    asm["understat_id_num"] = pd.to_numeric(asm["understat_id"], errors="coerce")
    rates_clean["understat_id"] = pd.to_numeric(rates_clean["understat_id"], errors="coerce")
    asm = asm.merge(rates_clean, left_on="understat_id_num", right_on="understat_id", how="left", suffixes=("", "_r"))
    pos_lab = {"FWD": "F", "MID": "M", "DEF": "D", "GK": "D"}
    def fb(row, stat):
        return priors.get(pos_lab.get(row["position"], "M"), priors["M"])[stat]
    nn = asm["npxg90"].isna(); nx = asm["xa90"].isna()
    asm.loc[nn, "npxg90"] = asm[nn].apply(lambda r: fb(r, "npxg"), axis=1)
    asm.loc[nx, "xa90"]   = asm[nx].apply(lambda r: fb(r, "xa"), axis=1)
    assert asm.duplicated(["element", "gw"]).sum() == 0

    # --- 4. Dixon-Coles fixtures (team-name map + date bridge) ---
    fixtures["home"] = fixtures["home"].map(lambda t: TEAM_MAP.get(t, t))
    fixtures["away"] = fixtures["away"].map(lambda t: TEAM_MAP.get(t, t))
    home = fixtures[["home", "match_date", "lam_home", "lam_away", "p_home_cs"]].copy()
    home.columns = ["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]
    away = fixtures[["away", "match_date", "lam_away", "lam_home", "p_away_cs"]].copy()
    away.columns = ["team", "match_date", "team_lambda", "opp_lambda", "p_cs"]
    tf = pd.concat([home, away], ignore_index=True)
    vv = df[df["season"] == "2025-26"].copy()
    vv["match_date"] = pd.to_datetime(vv["kickoff_time"]).dt.date
    tgd = vv[["team", "GW", "match_date"]].drop_duplicates().rename(columns={"GW": "gw"})
    tf["match_date"] = pd.to_datetime(tf["match_date"]).dt.date
    tgd["match_date"] = pd.to_datetime(tgd["match_date"]).dt.date
    tf = tf.merge(tgd, on=["team", "match_date"], how="left")
    asm = asm.merge(tf[["team", "gw", "team_lambda", "opp_lambda", "p_cs"]].drop_duplicates(["team", "gw"]),
                    on=["team", "gw"], how="left")

    # --- 5. defensive contribution (dedupe + fallback) ---
    asm = asm.merge(dc_out[["player_id", "gw", "p_dc_hit"]], on=["player_id", "gw"], how="left")
    need = asm["p_dc_hit"].isna()
    asm.loc[need, "p_dc_hit"] = asm.loc[need, "position"].map(DC_BASE).fillna(0.10)
    asm = (asm.sort_values("p_dc_hit", ascending=False).drop_duplicates(["element", "gw"], keep="first")
           .sort_values(["element", "gw"]).reset_index(drop=True))
    assert asm.duplicated(["element", "gw"]).sum() == 0

    # --- 6. master equation (every performance term GATED by playing probability) ---
    a = asm.copy()
    a["minutes_frac"] = (a["e_minutes"] / 90.0).clip(0, 1)
    a["fixture_scale"] = (a["team_lambda"] / LEAGUE_AVG_LAMBDA).fillna(1.0).clip(0.5, 2.0)
    a["e_goals"]   = a["npxg90"] * a["minutes_frac"] * a["fixture_scale"]
    a["e_assists"] = a["xa90"]   * a["minutes_frac"] * a["fixture_scale"]
    a["pts_goals"]   = a["e_goals"]   * a["position"].map(GOAL_PTS)
    a["pts_assists"] = a["e_assists"] * 3
    a["p_60plus"]   = a["p_start"] * a["p60"]
    a["p_play_any"] = a["p_start"] + (1 - a["p_start"]) * 0.30
    a["pts_appear"] = a["p_60plus"] * 2 + (a["p_play_any"] - a["p_60plus"]).clip(lower=0) * 1
    a["pts_cs"] = a["p_cs"] * a["position"].map(CS_PTS) * a["p_60plus"]
    a["pts_dc"] = a["p_dc_hit"] * 2 * a["minutes_frac"]
    a["e_points_core"] = a["pts_appear"] + a["pts_goals"] + a["pts_assists"] + a["pts_cs"] + a["pts_dc"]

    # --- 7. bonus (gated + recalibrated) ---
    bps_input = pd.DataFrame({
        "goals_scored": a["e_goals"], "assists": a["e_assists"],
        "clean_sheets": a["p_cs"] * a["p_60plus"], "minutes": a["e_minutes"],
        "is_def": (a["position"] == "DEF").astype(int), "is_mid": (a["position"] == "MID").astype(int),
        "is_gk": (a["position"] == "GK").astype(int),
        "saves": 0, "yellow_cards": 0, "red_cards": 0, "goals_conceded": 0, "penalties_missed": 0, "own_goals": 0})
    a["pred_bps"] = bps_model.predict(bps_input[BPS_FEATURES])
    a["exp_bonus"] = bps_to_bonus(a["pred_bps"].values) * a["minutes_frac"]

    # Recalibration constant comes from bonus.py (cutoff-respecting, no leak).
    #
    # NORMALISED PER GAMEWEEK, not across the whole frame. Scaling by the mean of
    # everything assembled together makes a gameweek's prediction depend on WHICH
    # OTHER GAMEWEEKS happened to be in the same batch -- harmless when the batch
    # is always the full season, but indefensible under walk-forward, where the
    # harness assembles a rolling window. It showed up as gameweek k's prediction
    # shifting by ~0.03 points depending on what k+1..k+5 contained.
    #
    # Per-gameweek normalisation makes each gameweek self-contained: bonus points
    # are a fixed per-match quantity (three per fixture: 3, 2, 1), so the mean is
    # a per-gameweek property in the first place. This is the more correct
    # normalisation on its own terms, not merely the more convenient one.
    gw_mean = a.groupby("gw")["exp_bonus"].transform("mean")
    a["exp_bonus"] = np.where(gw_mean > 0,
                              a["exp_bonus"] * bonus_mean / gw_mean,
                              a["exp_bonus"])
    a["e_points"] = a["e_points_core"] + a["exp_bonus"]
    return a


def validate(a):
    a["actual_points"] = pd.to_numeric(a["actual_points"], errors="coerce")
    val = a.dropna(subset=["actual_points", "e_points"]).copy()
    print("\n=== VALIDATION ===")
    print(f"Spearman (rank): {spearmanr(val['e_points'], val['actual_points']).correlation:.3f}")
    print(f"Pearson:         {val['e_points'].corr(val['actual_points']):.3f}")
    print(f"MAE:             {(val['e_points'] - val['actual_points']).abs().mean():.2f}")
    print(f"Mean pred / actual: {val['e_points'].mean():.2f} / {val['actual_points'].mean():.2f}")
    vs = val.sort_values(["element", "gw"])
    vs["fair"] = vs.groupby("element")["actual_points"].transform(lambda s: s.shift(1).expanding().mean())
    f = vs.dropna(subset=["fair"])
    print(f"MAE model {(f['e_points']-f['actual_points']).abs().mean():.2f} vs fair baseline {(f['fair']-f['actual_points']).abs().mean():.2f}")
    val["band"] = pd.cut(val["e_minutes"], [0, 15, 45, 70, 90], labels=["<15", "15-45", "45-70", "70+"])
    print("\nCalibration by minutes band:")
    print(val.groupby("band", observed=True).agg(pred=("e_points", "mean"), actual=("actual_points", "mean")).round(2))


if __name__ == "__main__":
    import sys
    log = "--mlflow" in sys.argv

    PRED_COLS = ["element", "player_id", "understat_id", "gw", "name", "position", "team",
                 "e_minutes", "e_points", "e_points_core", "exp_bonus",
                 "pts_goals", "pts_assists", "pts_cs", "pts_dc", "pts_appear"]
    out_path = BASE + r"\data\predictions_2526.parquet"

    if log:
        # Open the PARENT run FIRST, so every component run nests inside it.
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        with mlflow.start_run(run_name="assembly_static") as parent:
            mlflow.set_tag("component", "assembly")
            mlflow.set_tag("mlflow.note.content", METRIC_GLOSSARY)
            mlflow.log_params({
                "predict_season": "2025-26",
                "league_avg_lambda": LEAGUE_AVG_LAMBDA,
                "goal_pts": str(GOAL_PTS),
                "cs_pts": str(CS_PTS),
                "dc_base_fallback": str(DC_BASE),
                "p_sub_appearance_assumption": 0.30,
                "fixture_scale_clip": "0.5 to 2.0",
                "gating": "all performance terms multiplied by playing probability",
            })

            a = build_predictions(log_mlflow=True)
            predictions = a[PRED_COLS].copy()
            print(f"\nFinal predictions: {len(predictions)} player-gameweeks")
            validate(a)
            predictions.to_parquet(out_path, index=False)
            print(f"\nSaved -> {out_path}")

            mlflow.log_metrics(_eval_metrics(a))
            mlflow.log_text(METRIC_GLOSSARY, "METRICS_README.md")
            mlflow.log_text(_calibration_table(a).to_csv(index=False), "calibration_by_band.csv")
            print(f"\nMLflow parent run: {parent.info.run_id}")
    else:
        a = build_predictions(log_mlflow=False)
        predictions = a[PRED_COLS].copy()
        print(f"\nFinal predictions: {len(predictions)} player-gameweeks")
        validate(a)
        predictions.to_parquet(out_path, index=False)
        print(f"\nSaved -> {out_path}")

    print("\nTop distinct players by peak E[points]:")
    print(predictions.sort_values("e_points", ascending=False).drop_duplicates("element")
          .head(10)[["name", "position", "team", "e_points"]].to_string(index=False))