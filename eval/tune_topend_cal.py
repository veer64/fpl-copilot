#!/usr/bin/env python
"""Tune FIXTURE_SCALE_GAMMA on 2023-24 + 2024-25 ONLY (Logs/topend_calibration_prereg.md section 3).

No rebuild: e_goals / e_assists are recomputed from the STORED canonical columns
at each gamma. The bonus term is held at its canonical value (stated
approximation). 2025-26 is never opened here.

    uv run python eval/tune_topend_cal.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
TUNE = [("2023-24", "2023_24"), ("2024-25", "2024_25")]
GRID = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.0]
GOAL = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}


def rho(a, b):
    return float(spearmanr(a, b).correlation)


def load(season, tag):
    h = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet")
    h = h[(h["season"] == season) & (h["position"] != "AM")]
    hs = (h.groupby(["element", "GW"]).agg(minutes_v=("minutes", "sum"), pts=("total_points", "sum"),
                                           goals=("goals_scored", "sum"), assists=("assists", "sum"))
          .reset_index().rename(columns={"GW": "gw"}))
    hs["element"] = hs["element"].astype(int)
    w = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    w = w[(w.horizon_step == 0) & (w.n_fixtures == 1)]
    d = w.merge(hs, on=["element", "gw"], how="inner").copy()
    if "e_pen_goals" not in d.columns:
        d["e_pen_goals"] = d["penalty_share"] * d["team_pen_rate"] * d["minutes_frac"]
    d["ls"] = d.p_start >= 0.75
    d["t30"] = d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30
    ls = d[d.ls]
    thr = ls.e_goals.quantile(0.8)
    d["ls_top"] = d.ls & (d.e_goals >= thr)
    lt = d[d.ls_top]
    q1, q2 = lt.fixture_scale.quantile([1 / 3, 2 / 3])
    d["fs_ter"] = np.where(d.fixture_scale <= q1, "low", np.where(d.fixture_scale <= q2, "mid", "high"))
    d["gpts"] = d.position.map(GOAL)
    return d


def at_gamma(d, g):
    fs = d.fixture_scale ** g
    eg = d.npxg90 * d.minutes_frac * fs + d.e_pen_goals
    ea = d.xa90 * d.minutes_frac * fs
    ep = d.e_points - d.pts_goals - d.pts_assists + eg * d.gpts + ea * 3
    return eg, ea, ep


def main():
    data = {s: load(s, t) for s, t in TUNE}
    print("gamma | pooled LS-top-quintile pred/real by fixture_scale tercile: low / mid / high | objective | "
          "per-season: LS d9 ratio, T30 ratio, T30 e_points sd, rho LS, rho T30")
    best = None
    for g in GRID:
        num = {"low": [0, 0], "mid": [0, 0], "high": [0, 0]}
        per = []
        for s, d in data.items():
            eg, ea, ep = at_gamma(d, g)
            lt = d.ls_top
            for k in num:
                m = lt & (d.fs_ter == k)
                num[k][0] += float(eg[m].sum()); num[k][1] += float(d.goals[m].sum())
            ls = d.ls; t30 = d.t30
            dec = pd.qcut(eg[ls].rank(method="first"), 10, labels=False)
            d9 = float(eg[ls][dec == 9].mean() / d.goals[ls][dec == 9].mean())
            t30r = float(eg[t30].mean() / d.goals[t30].mean())
            per.append((s, d9, t30r, float(ep[t30].std()), rho(ep[ls], d.pts[ls]), rho(ep[t30], d.pts[t30])))
        r = {k: v[0] / v[1] for k, v in num.items()}
        obj = abs(r["high"] - 1) + abs(r["low"] - 1)
        print(f"{g:4.1f} | {r['low']:.3f} / {r['mid']:.3f} / {r['high']:.3f} | {obj:.3f} | " +
              "  ".join(f"{s}: d9 {d9:.2f} T30 {t:.2f} sd {sd:.2f} rhoLS {rl:.4f} rhoT30 {rt:.4f}" for s, d9, t, sd, rl, rt in per))
        if best is None or obj < best[1] - 1e-12:
            best = (g, obj)
    print(f"\nSELECTION (min |high-1| + |low-1|, ties -> larger gamma): GAMMA = {best[0]}")
    print("Write 'GAMMA = <value>' into a dated '## PRE-REGISTERED VALUE' section of Logs/topend_calibration_prereg.md "
          "BEFORE building 2025-26.")


if __name__ == "__main__":
    main()
