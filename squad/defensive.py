# defensive.py
# Defensive Contribution: P(hit DC threshold) per player-match.
# Module form for assembly: get_dc_2526() runs the walk-forward over every gameweek
# and returns the full-season dc_out that assembly.py joins on (player_id, gw).
#
# Full investigation (within-vs-cross-season persistence, Bug #7, base-rate drift,
# 4-fix comparison, CDM investigation, team-style feature) is in the DC log.
#
# Final config (verified against the log):
#   source : core_insights_matchstats.parquet, PL-only (-prem-), 2025-26 only
#            (Bug #7: 2024-25 recording inconsistent — unusable)
#   DEF/MID: LightGBM (150/15, min_child 40), WALK-FORWARD retrained per gameweek
#            (base rate drifts unpredictably -> must retrain on recent data = live op)
#   FWD    : no model — 0.4% hit rate, flat FWD_BASE_RATE (log §9)
#   features: rolling within-season, shift-then-roll (no leakage)
#
# Output: DataFrame[season, player_id, gw, position, p_dc_hit, dc_hit]

import pandas as pd
import numpy as np
import lightgbm as lgb

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
SEASON = "2025-2026"
FWD_BASE_RATE = 0.005
FEATURES = ["roll_dc90_3c", "roll_dc90_5c", "roll_hit_5", "roll_mins_3"]


def _mk():
    return lgb.LGBMClassifier(n_estimators=150, num_leaves=15, min_child_samples=40,
                              learning_rate=0.05, random_state=42, verbose=-1)


def _build_features():
    """Load matchstats, attach position, build target + rolling features for 2025-26."""
    ms = pd.read_parquet(BASE + r"\data\history\core_insights_matchstats.parquet")
    ms_pl = ms[ms["match_id"].str.contains("-prem-", na=False)].copy()
    for c in ["tackles", "interceptions", "recoveries", "blocks", "clearances", "minutes_played"]:
        ms_pl[c] = pd.to_numeric(ms_pl[c], errors="coerce")

    gwref = pd.read_parquet(BASE + r"\data\history\core_insights_gameweek_stats.parquet")
    pos_map = gwref[["id", "position"]].drop_duplicates("id").set_index("id")["position"]
    ms_pl["position"] = ms_pl["player_id"].map(pos_map)

    ms_pl["cbit"]  = ms_pl["clearances"] + ms_pl["blocks"] + ms_pl["interceptions"] + ms_pl["tackles"]
    ms_pl["cbirt"] = ms_pl["cbit"] + ms_pl["recoveries"]
    ms_pl["dc_metric"] = np.where(ms_pl["position"] == "Defender", ms_pl["cbit"], ms_pl["cbirt"])
    ms_pl["dc_threshold"] = np.where(ms_pl["position"] == "Defender", 10, 12)
    ms_pl["dc_hit"] = (ms_pl["dc_metric"] >= ms_pl["dc_threshold"]).astype(int)
    played = ms_pl[ms_pl["minutes_played"] >= 1].copy()

    d = played[played["season"] == SEASON].sort_values(["player_id", "gw"]).reset_index(drop=True)
    d["dc_per90"] = d["dc_metric"] / d["minutes_played"].clip(lower=1) * 90
    grp = d.groupby("player_id")
    rp = lambda c, w, h: grp[c].transform(lambda s: s.shift(1).rolling(w, min_periods=1).agg(h))
    d["roll_dc90_3"] = rp("dc_per90", 3, "mean")
    d["roll_dc90_5"] = rp("dc_per90", 5, "mean")
    d["roll_hit_5"]  = rp("dc_hit", 5, "mean")
    d["roll_mins_3"] = rp("minutes_played", 3, "mean")
    d["roll_dc90_3c"] = d["roll_dc90_3"].clip(upper=30)
    d["roll_dc90_5c"] = d["roll_dc90_5"].clip(upper=30)
    return d


def _predict_gw(frame, target_gw, recency_weight=False):
    """Walk-forward P(DC hit) for one gameweek, trained on all prior gameweeks."""
    out = []
    for pos in ["Defender", "Midfielder", "Forward"]:
        te = frame[(frame["gw"] == target_gw) & (frame["position"] == pos)].dropna(subset=FEATURES).copy()
        if len(te) == 0:
            continue
        if pos == "Forward":
            te["p_dc_hit"] = FWD_BASE_RATE
        else:
            prior = frame[(frame["gw"] < target_gw) & (frame["position"] == pos)].dropna(subset=FEATURES)
            if len(prior) < 150:
                te["p_dc_hit"] = prior["dc_hit"].mean() if len(prior) else 0.13
            else:
                m = _mk()
                if recency_weight:
                    w = 0.9 ** (target_gw - prior["gw"].values)
                    m.fit(prior[FEATURES], prior["dc_hit"], sample_weight=w)
                else:
                    m.fit(prior[FEATURES], prior["dc_hit"])
                te["p_dc_hit"] = m.predict_proba(te[FEATURES])[:, 1]
        out.append(te)
    if not out:                       # early gameweeks: no rolling features yet
        return None
    return pd.concat(out)[["season", "player_id", "gw", "position", "p_dc_hit", "dc_hit"]]


def get_dc_2526(recency_weight=False):
    """Run the walk-forward over every gameweek and return the full-season DC table.
    Returns DataFrame[season, player_id, gw, position, p_dc_hit, dc_hit]."""
    d = _build_features()
    preds = [_predict_gw(d, g, recency_weight) for g in sorted(d["gw"].unique())]
    preds = [p for p in preds if p is not None]      # drop early gameweeks with no features
    dc_out = pd.concat(preds, ignore_index=True)
    return dc_out


if __name__ == "__main__":
    dc_out = get_dc_2526()
    print(f"DC predictions for 2025-26: {len(dc_out)} player-gameweeks")
    print("\nTop P(DC hit) — should be defensive specialists:")
    print(dc_out.sort_values("p_dc_hit", ascending=False).head(6).to_string(index=False))