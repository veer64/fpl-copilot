#!/usr/bin/env python
"""Top-end calibration measurement -- Logs/topend_calibration_prereg.md section 4, exactly as written.

    uv run python eval/measure_topend_cal.py                # tuning seasons only
    uv run python eval/measure_topend_cal.py --holdout      # adds 2025-26; refuses without the value line

Pairs: canonical vs _cal (calibration alone) and _penfix vs _cal_penfix (calibration with the penalty fix on),
so the calibration effect is read at both penalty states. Partitions on the incumbent's own view.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
PREREG = REPO / "Logs" / "topend_calibration_prereg.md"
TUNE = [("2023-24", "2023_24"), ("2024-25", "2024_25")]
HOLD = [("2025-26", "2025_26")]


def rho(a, b):
    return float(spearmanr(a, b).correlation)


def brier_ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2)), float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def registered_gamma():
    secs = PREREG.read_text(encoding="utf-8").split("## PRE-REGISTERED VALUE")
    if len(secs) < 2:
        return None
    m = re.search(r"GAMMA\s*=\s*([0-9.]+)", secs[-1]); return float(m.group(1)) if m else None


def actuals(season):
    h = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet")
    h = h[(h["season"] == season) & (h["position"] != "AM")]
    hs = (h.groupby(["element", "GW"]).agg(minutes_v=("minutes", "sum"), pts=("total_points", "sum"),
                                           goals=("goals_scored", "sum")).reset_index().rename(columns={"GW": "gw"}))
    hs["element"] = hs["element"].astype(int); return hs


def pair(season, tag, inc_suffix, cal_suffix):
    inc = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}{inc_suffix}.parquet")
    cal = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}{cal_suffix}.parquet")
    assert bool(cal["topend_cal_active"].iloc[0]) is True
    assert "topend_cal_active" not in inc.columns or not bool(inc["topend_cal_active"].iloc[0])
    pi = bool(inc["penalty_fix_active"].iloc[0]) if "penalty_fix_active" in inc.columns else False
    assert pi == bool(cal["penalty_fix_active"].iloc[0]), "penalty state differs within the pair"
    i0 = inc[(inc.horizon_step == 0) & (inc.n_fixtures == 1)]
    c0 = cal[(cal.horizon_step == 0) & (cal.n_fixtures == 1)]
    d = i0.merge(c0[["element", "gw", "e_points", "e_goals", "e_assists"]], on=["element", "gw"], suffixes=("", "_cal"))
    assert len(d) == len(i0) == len(c0)
    d = d.merge(actuals(season), on=["element", "gw"], how="inner")
    return d, float(cal["fixture_scale_gamma"].iloc[0])


def deciles(q, col):
    dec = pd.qcut(q[col].rank(method="first"), 10, labels=False)
    g = q.groupby(dec).agg(p=(col, "mean"), r=("goals", "mean"))
    return [float(a / b) if b > 0 else float("nan") for a, b in zip(g.p, g.r)]


def evaluate(season, tag, inc_suffix, cal_suffix, label):
    d, gamma = pair(season, tag, inc_suffix, cal_suffix)
    LS = d.p_start >= 0.75
    T30 = d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30
    print(f"\n--- {season} {label} (gamma {gamma}) ---")
    res = {}
    for name, m in [("likely starters", LS), ("squad-relevant", T30),
                    ("uncertain", (d.p_start >= 0.25) & (d.p_start < 0.75)), ("written off", d.p_start < 0.25),
                    ("full starter band", d.e_minutes >= 60)]:
        q = d[m]
        r_i, r_c = rho(q.e_points, q.pts), rho(q.e_points_cal, q.pts)
        y = (q.goals >= 1).astype(float)
        bi, li = brier_ll(1 - np.exp(-q.e_goals), y); bc, lc = brier_ll(1 - np.exp(-q.e_goals_cal), y)
        print(f"  {name:18s} n={len(q):6d}  rho {r_i:.4f} -> {r_c:.4f} ({r_c - r_i:+.4f})  Brier {bi:.4f} -> {bc:.4f}  LL {li:.4f} -> {lc:.4f}  "
              f"e_goals {q.e_goals.mean():.3f} -> {q.e_goals_cal.mean():.3f} vs real {q.goals.mean():.3f}")
        res[name] = (r_c - r_i)
    ls = d[LS].copy(); t30 = d[T30].copy()
    di, dc = deciles(ls, "e_goals"), deciles(ls.assign(e_goals=ls.e_goals_cal), "e_goals")
    print("  LS e_goals decile ratios incumbent: " + " ".join(f"{x:.2f}" for x in di))
    print("  LS e_goals decile ratios calibrated: " + " ".join(f"{x:.2f}" for x in dc))
    # high-fixture tercile of the LS top quintile (incumbent's view)
    lt = ls[ls.e_goals >= ls.e_goals.quantile(0.8)].copy()
    q1, q2 = lt.fixture_scale.quantile([1 / 3, 2 / 3])
    lt["ter"] = np.where(lt.fixture_scale <= q1, "low", np.where(lt.fixture_scale <= q2, "mid", "high"))
    ter = lt.groupby("ter").agg(pi=("e_goals", "mean"), pc=("e_goals_cal", "mean"), r=("goals", "mean"))
    print("  LS top-quintile by fixture tercile pred/real incumbent -> calibrated: " +
          " ".join(f"{k}: {v.pi / v.r:.2f} -> {v.pc / v.r:.2f}" for k, v in ter.iterrows()))
    t30_i, t30_c = t30.e_goals.mean() / t30.goals.mean(), t30.e_goals_cal.mean() / t30.goals.mean()
    sd_i, sd_c = t30.e_points.std(), t30.e_points_cal.std()
    sp_i = t30.e_goals.quantile(.9) - t30.e_goals.quantile(.1); sp_c = t30.e_goals_cal.quantile(.9) - t30.e_goals_cal.quantile(.1)
    print(f"  T30 e_goals ratio {t30_i:.2f} -> {t30_c:.2f}; T30 e_points sd {sd_i:.3f} -> {sd_c:.3f} ({sd_c / sd_i:.2f}); "
          f"T30 e_goals p90-p10 {sp_i:.3f} -> {sp_c:.3f} ({sp_c / sp_i:.2f})")
    d9_i, d9_c = di[9], dc[9]; hi_i, hi_c = ter.loc["high", "pi"] / ter.loc["high", "r"], ter.loc["high", "pc"] / ter.loc["high", "r"]
    c1 = res["likely starters"] >= -0.003 and res["squad-relevant"] >= -0.003
    half = lambda a, b: abs(b - 1) <= 0.5 * abs(a - 1)
    c2 = half(d9_i, d9_c) and half(hi_i, hi_c) and t30_c < t30_i
    c3 = sd_c / sd_i >= 0.85 and sp_c / sp_i >= 0.85
    print(f"  cond1 rank (dLS {res['likely starters']:+.4f}, dT30 {res['squad-relevant']:+.4f}) -> {'PASS' if c1 else 'FAIL'}; "
          f"cond2 level (d9 {d9_i:.2f}->{d9_c:.2f}, high-ter {hi_i:.2f}->{hi_c:.2f}, T30 {t30_i:.2f}->{t30_c:.2f}) -> {'PASS' if c2 else 'FAIL'}; "
          f"cond3 spread -> {'PASS' if c3 else 'FAIL'}")
    return c1 and c2 and c3


def main():
    holdout = "--holdout" in sys.argv
    if holdout and registered_gamma() is None:
        raise SystemExit("REFUSED: --holdout needs 'GAMMA = ...' in a '## PRE-REGISTERED VALUE' section of the prereg")
    seasons = TUNE + (HOLD if holdout else [])
    allok = True
    for season, tag in seasons:
        for inc, cal, label in [("", "_cal", "calibration alone (penalty OFF)"), ("_penfix", "_cal_penfix", "calibration with penalty fix ON")]:
            if not (REPO / "data" / f"walkforward_h6_{tag}{cal}.parquet").exists():
                print(f"\n--- {season} {label}: not built"); continue
            ok = evaluate(season, tag, inc, cal, label)
            if label.startswith("calibration alone"):
                allok = allok and ok
    print("\nVERDICT (calibration alone, all measured seasons):", "PASS" if allok else "FAIL")


if __name__ == "__main__":
    main()
