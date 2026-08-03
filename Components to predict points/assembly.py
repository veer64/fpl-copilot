# assembly.py
# E[points] assembly orchestrator. Imports the five component modules, joins their
# outputs through the crosswalk, applies the master equation (with playing-probability
# gating), and validates against actuals. See ASSEMBLY_LOG.md for the full story.
#
# Run: `python assembly.py` (retrains all components — a few minutes).

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

from minutes import get_minutes_2526
from attacking_rates import get_rates_2526
from dixon_coles import get_fixtures_2526
from defensive import get_dc_2526
from bonus import get_bonus_model

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
GOAL_PTS = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}
CS_PTS   = {"FWD": 0, "MID": 1, "DEF": 4, "GK": 4}
LEAGUE_AVG_LAMBDA = 1.40
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs"}
DC_BASE = {"DEF": 0.125, "MID": 0.136, "FWD": 0.058, "GK": 0.0}


def build_predictions():
    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")

    # --- run the five components ---
    print("Running components...")
    mins_out = get_minutes_2526()
    rates, priors = get_rates_2526("2025")
    fixtures = get_fixtures_2526()
    dc_out = get_dc_2526()
    bps_model, bps_to_bonus, BPS_FEATURES = get_bonus_model()

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
    actual_bonus_mean = pd.to_numeric(df[df["season"] == "2025-26"]["bonus"], errors="coerce").mean()
    a["exp_bonus"] *= actual_bonus_mean / a["exp_bonus"].mean()
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
    a = build_predictions()
    predictions = a[["element", "player_id", "understat_id", "gw", "name", "position", "team",
                     "e_minutes", "e_points", "e_points_core", "exp_bonus",
                     "pts_goals", "pts_assists", "pts_cs", "pts_dc", "pts_appear"]].copy()
    print(f"\nFinal predictions: {len(predictions)} player-gameweeks")
    validate(a)
    out_path = BASE + r"\data\predictions_2526.parquet"
    predictions.to_parquet(out_path, index=False)
    print(f"\nSaved -> {out_path}")
    print("\nTop distinct players by peak E[points]:")
    print(predictions.sort_values("e_points", ascending=False).drop_duplicates("element")
          .head(10)[["name", "position", "team", "e_points"]].to_string(index=False))