# measure_market_lambda.py
# D4 Phase 1 -- baseline market-lambda model: tuning study + sealed holdout.
#
# Dataset: data/d4_market_lambda_dataset.parquet (eval/build_market_lambda_dataset.py).
# Burn-in rows (any market-history feature undefined) are dropped here.
#
# PROTOCOL (stated before the sweep ran; the rate_blend_log.md discipline):
#   - Expanding-window walk-forward by season: predicting season N trains on all
#     seasons strictly before N.
#   - Hyperparameters tuned on target seasons 2017-18 .. 2024-25 ONLY.
#   - SELECTION RULE, fixed in advance: the config maximising MEAN R2 over the
#     eight validation seasons; ties -> lower mean MAE.
#   - 2025-26 is the SEALED test season. `--holdout` runs it ONCE, and refuses
#     to run unless Logs/d4_market_lambda_log.md already carries a line
#     'PRE-REGISTERED: {json}'. The holdout uses the config FROM THAT LINE, so
#     the registered and executed configs cannot disagree.
#   - Baseline on every table: dc_lambda_pred (the walk-forward Dixon-Coles
#     model's own lambda), scored on the identical rows.
#
# Usage:
#   uv run python eval/measure_market_lambda.py            # tuning sweep + ablations
#   uv run python eval/measure_market_lambda.py --holdout  # sealed 2025-26, once

import json
import re
import sys
from itertools import product
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot")
DATA = BASE / "data" / "d4_market_lambda_dataset.parquet"
LOG = BASE / "Logs" / "d4_market_lambda_log.md"

SEALED = "2025-26"
VALID_SEASONS = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22",
                 "2022-23", "2023-24", "2024-25"]
AV_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25"]   # availability coverage

FEATURES = [
    "mh_own_l5", "mh_own_l10", "mh_own_s2d",
    "mh_conc_l5", "mh_conc_l10", "mh_conc_s2d",
    "mh_opp_own_l5", "mh_opp_own_l10", "mh_opp_conc_l5", "mh_opp_conc_l10",
    "dc_attack", "dc_defence_opp", "is_home",
    "sch_rest_days", "sch_m14", "sch_rest_days_opp", "sch_m14_opp",
    "av_top5_out", "av_top5_out_opp",
]
DC_FEATS = ["dc_attack", "dc_defence_opp"]      # is_home kept in both arms
AV_FEATS = ["av_top5_out", "av_top5_out_opp"]
TARGET = "market_lambda"

GRID = {
    "num_leaves": [15, 31, 63],
    "learning_rate": [0.03, 0.05, 0.1],
    "n_estimators": [300, 600],
    "min_child_samples": [20, 50],
}
FIXED = {"objective": "l2", "verbosity": -1, "n_jobs": -1, "seed": 42,
         "deterministic": True, "force_row_wise": True}


def load():
    df = pd.read_parquet(DATA)
    missing = [c for c in FEATURES if c not in df.columns]
    assert not missing, f"dataset missing feature columns: {missing}"
    n0 = len(df)
    df = df[~df["burn_in"]].copy()
    print(f"loaded {n0} rows, dropped {n0 - len(df)} burn-in -> {len(df)} usable")
    return df


def r2_mae(y, pred):
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot, float(np.abs(y - pred).mean())


def walkforward(df, feats, params, targets):
    """Predict each target season from a model trained on all earlier seasons.
    Returns {season: (r2, mae, n)} and the concatenated per-row predictions."""
    out, preds = {}, []
    for season in targets:
        tr = df[df["season"] < season]
        te = df[df["season"] == season]
        assert len(tr) and len(te), f"empty split for {season}"
        assert tr["match_date"].max() < te["match_date"].min(), \
            f"train/test dates overlap for {season}"
        model = lgb.LGBMRegressor(**FIXED, **params)
        model.fit(tr[feats], tr[TARGET])
        p = model.predict(te[feats])
        r2, mae = r2_mae(te[TARGET], p)
        out[season] = (r2, mae, len(te))
        preds.append(pd.DataFrame({"season": season, "y": te[TARGET].values,
                                   "pred": p}, index=te.index))
    return out, pd.concat(preds)


def baseline_by_season(df, targets):
    return {s: r2_mae(df.loc[df["season"] == s, TARGET],
                      df.loc[df["season"] == s, "dc_lambda_pred"])
            for s in targets}


def table(rows, header):
    print("\n" + header)
    print(f"{'season':<10} {'model R2':>9} {'model MAE':>10} {'DC R2':>8} "
          f"{'DC MAE':>8} {'n':>6}")
    for s, (mr2, mmae, n), (br2, bmae) in rows:
        print(f"{s:<10} {mr2:>9.4f} {mmae:>10.4f} {br2:>8.4f} {bmae:>8.4f} {n:>6}")


def sweep(df):
    dv = df[df["season"] != SEALED]
    assert SEALED not in set(dv["season"]), "sealed season leaked into the sweep"

    configs = [dict(zip(GRID, v)) for v in product(*GRID.values())]
    print(f"sweep: {len(configs)} configs x {len(VALID_SEASONS)} seasons")
    results = []
    for i, cfg in enumerate(configs, 1):
        res, _ = walkforward(dv, FEATURES, cfg, VALID_SEASONS)
        mean_r2 = np.mean([v[0] for v in res.values()])
        mean_mae = np.mean([v[1] for v in res.values()])
        results.append((cfg, mean_r2, mean_mae, res))
        print(f"  [{i:>2}/{len(configs)}] {cfg}  mean R2 {mean_r2:.4f}  "
              f"mean MAE {mean_mae:.4f}", flush=True)

    # SELECTION RULE (pre-stated): max mean R2, ties -> lower mean MAE
    results.sort(key=lambda t: (-round(t[1], 6), round(t[2], 6)))
    best_cfg, best_r2, best_mae, best_res = results[0]
    print(f"\nBEST by pre-stated rule: {best_cfg}")
    print(f"  mean R2 {best_r2:.4f}, mean MAE {best_mae:.4f}")

    base = baseline_by_season(dv, VALID_SEASONS)
    table([(s, best_res[s], base[s]) for s in VALID_SEASONS],
          "Best config, per validation season vs Dixon-Coles-alone:")

    # --- ablation 1: do the DC features add anything over market history? ---
    abl_dc, _ = walkforward(dv, [f for f in FEATURES if f not in DC_FEATS],
                            best_cfg, VALID_SEASONS)
    table([(s, abl_dc[s], base[s]) for s in VALID_SEASONS],
          "Ablation -- WITHOUT dc_attack/dc_defence_opp (is_home kept):")
    d = np.mean([best_res[s][0] for s in VALID_SEASONS]) - \
        np.mean([abl_dc[s][0] for s in VALID_SEASONS])
    print(f"  mean R2 change from ADDING DC features: {d:+.4f}")

    # --- ablation 2: availability signal, 2021-22+ subset ---
    abl_av, _ = walkforward(dv, [f for f in FEATURES if f not in AV_FEATS],
                            best_cfg, AV_SEASONS)
    full_av = {s: best_res[s] for s in AV_SEASONS}
    print("\nAvailability ablation (2021-22+ targets), full vs without av_*:")
    print(f"{'season':<10} {'full R2':>9} {'no-av R2':>9} {'delta':>8}")
    for s in AV_SEASONS:
        print(f"{s:<10} {full_av[s][0]:>9.4f} {abl_av[s][0]:>9.4f} "
              f"{full_av[s][0] - abl_av[s][0]:>+8.4f}")

    # --- feature importance: chosen config trained on all validation data ---
    model = lgb.LGBMRegressor(**FIXED, **best_cfg)
    model.fit(dv[FEATURES], dv[TARGET])
    imp = (pd.Series(model.booster_.feature_importance("gain"), index=FEATURES)
             .sort_values(ascending=False))
    print("\nFeature importance (gain, train = all seasons < 2025-26):")
    print((imp / imp.sum() * 100).round(1).to_string())

    print("\nNEXT: write 'PRE-REGISTERED: " + json.dumps(best_cfg) +
          "' into Logs/d4_market_lambda_log.md, then run --holdout ONCE.")
    return best_cfg


def read_registered_config():
    if not LOG.exists():
        raise SystemExit(f"REFUSING holdout: {LOG} does not exist. "
                         f"Pre-register the config first (rate_blend_log.md pattern).")
    text = LOG.read_text(encoding="utf-8")
    # The log may MENTION the marker in prose (e.g. the protocol section);
    # the registration is the first occurrence that parses as valid JSON.
    for m in re.finditer(r"PRE-REGISTERED:\s*(\{.*?\})", text):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
    raise SystemExit("REFUSING holdout: no parseable 'PRE-REGISTERED: {json}' "
                     "line in the log. Write the chosen config into the log FIRST.")


def holdout(df):
    cfg = read_registered_config()
    print(f"SEALED 2025-26 run -- config from the log: {cfg}")
    res, _ = walkforward(df, FEATURES, cfg, [SEALED])
    base = baseline_by_season(df, [SEALED])
    table([(SEALED, res[SEALED], base[SEALED])],
          "Sealed 2025-26 (run once, config pre-registered):")


if __name__ == "__main__":
    frame = load()
    if "--holdout" in sys.argv:
        holdout(frame)
    else:
        sweep(frame)
