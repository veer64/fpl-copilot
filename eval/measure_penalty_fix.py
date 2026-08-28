#!/usr/bin/env python
"""Penalty-fix measurement -- Logs/penalty_fix_prereg.md Parts 3-4, exactly as written.

    uv run python eval/measure_penalty_fix.py
    uv run python eval/measure_penalty_fix.py --calibrated   # _cal vs _cal_penfix (Logs/topend_calibration_prereg.md section 4)

Compares data/walkforward_h6_{season}.parquet (canonical, gate off) against
data/walkforward_h6_{season}_penfix.parquet (gate on) on single-fixture step-0
rows joined to vaastav realised points. Partitions are defined on the CANONICAL
file's own view. Prints every pre-registered condition with PASS/FAIL.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
SEASONS = [("2023-24", "2023_24", 2023), ("2024-25", "2024_25", 2024), ("2025-26", "2025_26", 2025)]
STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling", "d1_terms_active",
          "cs_unified", "rate_blend_active", "rate_blend_k", "synthetic_lambda_active",
          "dc_rule_active"]
GOAL = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}
REALISED_PENS = {2022: 74, 2023: 96, 2024: 69, 2025: 77}   # Understat converted penalties, by start year


def rho(a, b):
    return float(spearmanr(a, b).correlation)


def brier_ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2)), float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def npxg_source_check():
    """Condition 4: npxG on the per-match file excludes penalties, and the blend reads it."""
    m = pd.read_parquet(REPO / "data" / "history" / "understat_matches_2024_25.parquet")
    for c in ["goals", "npg", "xG", "npxG"]:
        m[c] = pd.to_numeric(m[c])
    pen = m[m["goals"] > m["npg"]]
    assert len(pen) > 40, "expected converted penalties on the per-match file"
    assert (pen["npxG"] < pen["xG"] - 0.5).all(), "npxG does not strip the penalty xG (~0.76)"
    nopen = m[m["goals"] == m["npg"]]
    src = (REPO / "squad" / "attacking_rates.py").read_text(encoding="utf-8")
    assert 'npxG=("npxG", "sum")' in src, "blend path no longer reads the npxG column"
    print(f"[cond 4] npxG source: {len(pen)} player-matches with a converted penalty, all with "
          f"npxG < xG - 0.5 (mean gap {float((pen['xG'] - pen['npxG']).mean()):.3f}); "
          f"{len(nopen)} without: max |xG-npxG| {float((nopen['xG'] - nopen['npxG']).abs().max()):.3f}; "
          "attacking_rates reads npxG -> no double count. PASS")


def main():
    calibrated = "--calibrated" in sys.argv
    inc_sfx, fix_sfx = ("_cal", "_cal_penfix") if calibrated else ("", "_penfix")
    if calibrated:
        print("CALIBRATED INCUMBENT: canonical -> _cal, penfix -> _cal_penfix; penalty_fix_prereg.md section 4 UNCHANGED")
    h = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet")
    h = h[h["position"] != "AM"]
    us = pd.read_parquet(REPO / "data" / "history" / "understat_season_aggregates.parquet")
    for c in ["goals", "npg"]:
        us[c] = pd.to_numeric(us[c])
    us["pen"] = (us["goals"] - us["npg"]).clip(lower=0)
    us["yr"] = pd.to_numeric(us["understat_season"])
    npxg_source_check()

    verdict = {}
    for season, tag, yr in SEASONS:
        canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}{inc_sfx}.parquet")
        fix = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}{fix_sfx}.parquet")
        if calibrated:
            assert bool(canon["topend_cal_active"].iloc[0]) and bool(fix["topend_cal_active"].iloc[0])
            assert float(canon["fixture_scale_gamma"].iloc[0]) == float(fix["fixture_scale_gamma"].iloc[0])
        for s in STAMPS:
            assert canon[s].iloc[0] == fix[s].iloc[0], f"stamp {s} differs -- not a paired comparison"
        assert bool(fix["penalty_fix_active"].iloc[0]) is True
        assert "penalty_fix_active" not in canon.columns or not bool(canon["penalty_fix_active"].iloc[0])

        c0 = canon[(canon.horizon_step == 0) & (canon.n_fixtures == 1)]
        f0 = fix[(fix.horizon_step == 0) & (fix.n_fixtures == 1)]
        key = ["element", "gw"]
        d = c0.merge(f0[key + ["e_points", "e_goals", "e_pen_goals", "penalty_share"]],
                     on=key, suffixes=("", "_fix"), how="inner")
        assert len(d) == len(c0) == len(f0), (len(d), len(c0), len(f0))
        hs = (h[h["season"] == season].groupby(["element", "GW"])
              .agg(minutes_v=("minutes", "sum"), pts=("total_points", "sum"), goals=("goals_scored", "sum"),
                   nm=("name", "first")).reset_index().rename(columns={"GW": "gw"}))
        hs["element"] = hs["element"].astype(int)
        d = d.merge(hs, on=key, how="inner")
        print(f"\n================ {season}: paired rows {len(d)} ================")

        # sanity: league-wide penalty goals (ALL step-0 rows incl. doubles, per fixture-sum)
        c_all = canon[canon.horizon_step == 0]; f_all = fix[fix.horizon_step == 0]
        pen_c = float(c_all["e_pen_goals"].sum()) if "e_pen_goals" in c_all else float(
            (c_all["penalty_share"] * c_all["team_pen_rate"] * c_all["minutes_frac"]).sum())
        pen_f = float(f_all["e_pen_goals"].sum())
        real = REALISED_PENS[yr]
        ok2 = 35 <= pen_f <= 115 and pen_f <= 1.2 * real
        print(f"[cond 2] league-wide predicted penalty goals: as built {pen_c:.1f} -> fixed {pen_f:.1f}; "
              f"realised {real} (prior season {REALISED_PENS[yr-1]}); ratio fixed/realised {pen_f/real:.2f} "
              f"-> {'PASS' if ok2 else 'FAIL'}")
        fb = f0["penalty_share"]
        print(f"         fallback footprint (gate on): rows with penalty_share == 0: {(fb == 0).mean():.1%}; "
              f"> 0.1/game: {(fb > 0.1).mean():.2%}; max {fb.max():.3f}")

        parts = {
            "likely starters (p_start>=.75)": d.p_start >= 0.75,
            "squad-relevant (top30 canonical e_points)": d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30,
            "uncertain (.25<=p_start<.75)": (d.p_start >= 0.25) & (d.p_start < 0.75),
            "written off (p_start<.25)": d.p_start < 0.25,
            "full starter band (e_minutes>=60)": d.e_minutes >= 60,
            "realised started (minutes>=60)": d.minutes_v >= 60,
        }
        rows = []
        for name, m in parts.items():
            q = d[m]
            r_c, r_f = rho(q.e_points, q.pts), rho(q.e_points_fix, q.pts)
            pc, pf = 1 - np.exp(-q.e_goals), 1 - np.exp(-q.e_goals_fix)
            y = (q.goals >= 1).astype(float)
            bc, lc = brier_ll(pc, y); bf, lf = brier_ll(pf, y)
            mae_c = float(np.abs(q.e_points - q.pts).mean()); mae_f = float(np.abs(q.e_points_fix - q.pts).mean())
            band = {}
            for lo, hi, lab in [(0, 0, "0"), (1, 1, "1"), (2, 99, "2+")]:
                z = q[(q.goals >= lo) & (q.goals <= hi)]
                band[lab] = (float(np.abs(z.e_goals - z.goals).mean()), float(np.abs(z.e_goals_fix - z.goals).mean()))
            rows.append((name, len(q), r_c, r_f, r_f - r_c, bc, bf, lc, lf,
                         float(q.e_goals.mean()), float(q.e_goals_fix.mean()), float(q.goals.mean()), mae_c, mae_f, band))
        print(f"{'partition':44s} {'n':>6s} {'rho can':>8s} {'rho fix':>8s} {'delta':>8s} {'Brier c':>8s} {'Brier f':>8s} "
              f"{'LL c':>7s} {'LL f':>7s} {'Eg c':>6s} {'Eg f':>6s} {'real':>6s} {'MAE c':>6s} {'MAE f':>6s}")
        for r in rows:
            print(f"{r[0]:44s} {r[1]:6d} {r[2]:8.4f} {r[3]:8.4f} {r[4]:+8.4f} {r[5]:8.4f} {r[6]:8.4f} "
                  f"{r[7]:7.4f} {r[8]:7.4f} {r[9]:6.3f} {r[10]:6.3f} {r[11]:6.3f} {r[12]:6.3f} {r[13]:6.3f}")
            b = r[14]
            print(f"{'':44s} outcome-band MAE(e_goals) 0/1/2+: "
                  f"{b['0'][0]:.3f}->{b['0'][1]:.3f} / {b['1'][0]:.3f}->{b['1'][1]:.3f} / {b['2+'][0]:.3f}->{b['2+'][1]:.3f}")
        # reliability deciles on the full starter band
        q = d[d.e_minutes >= 60].copy()
        q["dec"] = pd.qcut(q.e_goals_fix.rank(method="first"), 10, labels=False)
        rel = q.groupby("dec").agg(n=("goals", "size"), pc=("e_goals", "mean"), pf=("e_goals_fix", "mean"), real=("goals", "mean"))
        print("reliability deciles, full starter band (mean e_goals canonical / fixed | realised goals):")
        print("  " + " ".join(f"d{i}:{r.pc:.2f}/{r.pf:.2f}|{r.real:.2f}" for i, r in rel.iterrows()))

        likely, squad = rows[0], rows[1]
        ok1 = likely[4] >= -0.003 and squad[4] >= -0.003
        ok3 = (likely[6] - likely[5] <= 0.001) and (squad[6] - squad[5] <= 0.001)
        # movers
        top = d[d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30].copy()
        top["dpts"] = top.e_points_fix - top.e_points
        # every season, 2025-26 included, uses the builder's file (2026-08-28 switch;
        # see walkforward_season.crosswalk_for)
        cw = pd.read_csv(REPO / "data" / "history" / f"crosswalk_{tag}.csv")
        cw["understat_id"] = pd.to_numeric(cw["understat_id"], errors="coerce")
        prior = us[us.yr == yr - 1][["id", "pen"]].copy(); prior["id"] = pd.to_numeric(prior["id"])
        mv = (top.groupby("element").agg(name=("nm", "first"), rows=("dpts", "size"),
                                         mean_dpts=("dpts", "mean"), sum_dpts=("dpts", "sum"))
              .reset_index().merge(cw[["element", "understat_id"]], on="element", how="left")
              .merge(prior, left_on="understat_id", right_on="id", how="left"))
        mv["prior_pens"] = mv["pen"].fillna(0).astype(int)
        mv = mv.sort_values("sum_dpts", ascending=False)
        print("\n[cond 5] top-30 movers by total e_points change (name, top30 rows, mean d e_points/row, sum, prior-season pen goals):")
        for r in mv.head(12).itertuples():
            print(f"   {str(r.name)[:32]:32s} rows {r.rows:3d}  mean {r.mean_dpts:+.3f}  sum {r.sum_dpts:+7.2f}  prior pens {r.prior_pens}")
        top10 = mv.head(10)
        takers = int((top10["prior_pens"] >= 3).sum())
        ok5 = takers >= 7
        print(f"         takers (>=3 prior-season pens) among top-10 movers: {takers}/10 -> {'PASS' if ok5 else 'FAIL'}")
        print(f"[cond 1] rank delta likely {likely[4]:+.4f}, squad-relevant {squad[4]:+.4f} (floor -0.003) -> {'PASS' if ok1 else 'FAIL'}")
        print(f"[cond 3] Brier delta likely {likely[6]-likely[5]:+.4f}, squad-relevant {squad[6]-squad[5]:+.4f} (cap +0.001) -> {'PASS' if ok3 else 'FAIL'}")
        verdict[season] = dict(rank=ok1, pens=ok2, brier=ok3, movers=ok5, d_likely=likely[4], d_squad=squad[4])

    print("\n================ VERDICT (Logs/penalty_fix_prereg.md section 4) ================")
    ml = np.mean([v["d_likely"] for v in verdict.values()]); ms = np.mean([v["d_squad"] for v in verdict.values()])
    mean_ok = ml >= 0 and ms >= 0
    print(f"three-season mean rank delta: likely {ml:+.4f}, squad-relevant {ms:+.4f} -> {'PASS' if mean_ok else 'FAIL'}")
    allok = mean_ok and all(all(v[k] for k in ("rank", "pens", "brier", "movers")) for v in verdict.values())
    for s, v in verdict.items():
        print(f"  {s}: rank {v['rank']} pens {v['pens']} brier {v['brier']} movers {v['movers']}")
    print("OVERALL:", "PASS -- recommend adoption (separate step)" if allok else "FAIL -- gate stays False")


if __name__ == "__main__":
    main()
