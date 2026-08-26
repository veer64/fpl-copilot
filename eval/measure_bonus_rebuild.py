#!/usr/bin/env python
"""Bonus rebuild measurement -- Logs/bonus_rebuild_prereg.md sections 4-5, exactly as written.

    uv run python eval/measure_bonus_rebuild.py

Three arms on the SAME rows: incumbent (canonical), DELETE (e_points = e_points_core, read off the canonical),
REBUILD (_bonusow). Partitions on the incumbent's own view. Prints the three-arm rank table, the bias table,
and the section-5 verdict incl. the decision rule.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
SEASONS = [("2023-24", "2023_24"), ("2024-25", "2024_25"), ("2025-26", "2025_26")]
STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling", "d1_terms_active", "cs_unified",
          "rate_blend_active", "rate_blend_k", "synthetic_lambda_active", "dc_rule_active"]


def rho(a, b):
    return float(spearmanr(a, b).correlation)


def actuals(season):
    h = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet")
    h = h[(h["season"] == season) & (h["position"] != "AM")]
    hs = (h.groupby(["element", "GW"]).agg(minutes_v=("minutes", "sum"), pts=("total_points", "sum"),
                                           bonus=("bonus", "sum"), bps=("bps", "sum"))
          .reset_index().rename(columns={"GW": "gw"}))
    hs["element"] = hs["element"].astype(int); return hs


def main():
    verdict = {}
    for season, tag in SEASONS:
        canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
        ow = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}_bonusow.parquet")
        for s in STAMPS:
            assert canon[s].iloc[0] == ow[s].iloc[0], f"stamp {s} differs"
        assert ow["bonus_mode"].iloc[0] == "outcome"
        assert not bool(ow["penalty_fix_active"].iloc[0]) and not bool(ow["topend_cal_active"].iloc[0])
        c0 = canon[(canon.horizon_step == 0) & (canon.n_fixtures == 1)]
        o0 = ow[(ow.horizon_step == 0) & (ow.n_fixtures == 1)]
        key = ["element", "gw"]
        d = c0.merge(o0[key + ["e_points", "exp_bonus", "pred_bps"]], on=key, suffixes=("", "_ow"), how="inner")
        assert len(d) == len(c0) == len(o0), (len(d), len(c0), len(o0))
        assert np.allclose(d["e_points"], d["e_points_core"] + d["exp_bonus"])
        d["e_points_del"] = d["e_points_core"]
        d = d.merge(actuals(season), on=key, how="inner")
        LS = d.p_start >= 0.75
        T30 = d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30
        ST = d.minutes_v >= 60
        print(f"\n================ {season}: paired rows {len(d)} ================")
        # --- primary: three-arm rank on every partition
        parts = [("likely starters", LS), ("squad-relevant (top30)", T30), ("uncertain", (d.p_start >= .25) & (d.p_start < .75)),
                 ("written off", d.p_start < .25), ("full starter band", d.e_minutes >= 60), ("realised started", ST)]
        R = {}
        print(f"{'partition':26s} {'n':>6s} {'incumbent':>10s} {'DELETE':>10s} {'REBUILD':>10s} {'reb-inc':>9s} {'reb-del':>9s} {'del-inc':>9s}")
        for name, m in parts:
            q = d[m]
            ri, rd, ro = rho(q.e_points, q.pts), rho(q.e_points_del, q.pts), rho(q.e_points_ow, q.pts)
            R[name] = (ri, rd, ro)
            print(f"{name:26s} {len(q):6d} {ri:10.4f} {rd:10.4f} {ro:10.4f} {ro - ri:+9.4f} {ro - rd:+9.4f} {rd - ri:+9.4f}")
        # --- bonus signal
        st, t30 = d[ST], d[T30]
        sig = dict(st_inc=rho(st.exp_bonus, st.bonus), st_ow=rho(st.exp_bonus_ow, st.bonus),
                   t30_inc=rho(t30.exp_bonus, t30.bonus), t30_ow=rho(t30.exp_bonus_ow, t30.bonus))
        print(f"rho(exp_bonus, realised bonus): started incumbent {sig['st_inc']:+.3f} -> rebuild {sig['st_ow']:+.3f}; "
              f"top30 incumbent {sig['t30_inc']:+.3f} -> rebuild {sig['t30_ow']:+.3f}   | rho(pred_bps, bps) started {rho(st.pred_bps, st.bps):+.3f} -> {rho(st.pred_bps_ow, st.bps):+.3f}")
        # --- bias table
        print("top-30 mean predicted vs realised bonus by position (incumbent / rebuild | realised; ratio inc -> reb):")
        bias = {}
        for p in ["FWD", "MID", "DEF", "GK"]:
            q = t30[t30.position == p]
            if len(q) == 0:
                continue
            bi, bo, br = q.exp_bonus.mean(), q.exp_bonus_ow.mean(), q.bonus.mean()
            bias[p] = (bi / br if br > 0 else np.nan, bo / br if br > 0 else np.nan)
            print(f"   {p} n={len(q):4d}: {bi:.2f} / {bo:.2f} | {br:.2f}   ratio {bias[p][0]:.2f} -> {bias[p][1]:.2f}")
        print("likely-starter mean bonus by position (incumbent / rebuild | realised): " + "  ".join(
            f"{p} {d[LS & (d.position == p)].exp_bonus.mean():.2f}/{d[LS & (d.position == p)].exp_bonus_ow.mean():.2f}|{d[LS & (d.position == p)].bonus.mean():.2f}"
            for p in ["FWD", "MID", "DEF", "GK"]))
        print(f"level: started mean exp_bonus incumbent {st.exp_bonus.mean():.3f} rebuild {st.exp_bonus_ow.mean():.3f} realised {st.bonus.mean():.3f}; "
              f"all rows {d.exp_bonus.mean():.3f} / {d.exp_bonus_ow.mean():.3f} / {d.bonus.mean():.3f}")
        q = st.copy(); q["dec"] = pd.qcut(q.exp_bonus_ow.rank(method="first"), 10, labels=False)
        rel = q.groupby("dec").agg(p=("exp_bonus_ow", "mean"), r=("bonus", "mean"))
        print("rebuild reliability deciles (started): " + " ".join(f"{r.p:.2f}|{r.r:.2f}" for _, r in rel.iterrows()))
        print(f"MAE e_points started: incumbent {np.abs(st.e_points - st.pts).mean():.3f} delete {np.abs(st.e_points_del - st.pts).mean():.3f} rebuild {np.abs(st.e_points_ow - st.pts).mean():.3f}")
        # --- section 5 conditions
        c1 = sig["st_ow"] >= 0.10 and sig["t30_ow"] >= 0.10
        ri_l, rd_l, ro_l = R["likely starters"]; ri_s, rd_s, ro_s = R["squad-relevant (top30)"]
        c2 = (ro_l - ri_l >= -0.003) and (ro_s - ri_s >= -0.003) and (ro_l - rd_l >= -0.003) and (ro_s - rd_s >= -0.003)
        f_inc, f_reb = bias["FWD"]
        c3 = all(0.6 <= bias[p][1] <= 1.5 for p in ["FWD", "MID", "DEF"] if p in bias) and (abs(f_reb - 1) <= 0.5 * abs(f_inc - 1))
        del_ok = (rd_l - ri_l >= -0.003) and (rd_s - ri_s >= -0.003)
        print(f"[cond 1] bonus signal >= +0.10 started & top30 -> {'PASS' if c1 else 'FAIL'}")
        print(f"[cond 2] rank vs incumbent (likely {ro_l - ri_l:+.4f}, squad {ro_s - ri_s:+.4f}) and vs DELETE (likely {ro_l - rd_l:+.4f}, squad {ro_s - rd_s:+.4f}) -> {'PASS' if c2 else 'FAIL'}")
        print(f"[cond 3] top-30 position bias FWD {f_inc:.2f} -> {f_reb:.2f} (halfway to 1: {'yes' if abs(f_reb-1) <= 0.5*abs(f_inc-1) else 'no'}); all in [0.6,1.5]: "
              f"{'yes' if all(0.6 <= bias[p][1] <= 1.5 for p in ['FWD','MID','DEF'] if p in bias) else 'no'} -> {'PASS' if c3 else 'FAIL'}")
        print(f"[delete arm] vs incumbent likely {rd_l - ri_l:+.4f}, squad {rd_s - ri_s:+.4f} -> {'not worse' if del_ok else 'WORSE'}")
        verdict[season] = dict(c1=c1, c2=c2, c3=c3, del_ok=del_ok, reb_del_l=ro_l - rd_l, reb_del_s=ro_s - rd_s, del_inc_l=rd_l - ri_l, del_inc_s=rd_s - ri_s)
    print("\n================ VERDICT (Logs/bonus_rebuild_prereg.md section 5) ================")
    ml = np.mean([v["reb_del_l"] for v in verdict.values()]); ms = np.mean([v["reb_del_s"] for v in verdict.values()])
    reb_pass = all(v["c1"] and v["c2"] and v["c3"] for v in verdict.values()) and ml >= 0 and ms >= 0
    dl = np.mean([v["del_inc_l"] for v in verdict.values()]); ds = np.mean([v["del_inc_s"] for v in verdict.values()])
    del_pass = all(v["del_ok"] for v in verdict.values()) and dl > 0 and ds > 0
    for s, v in verdict.items():
        print(f"  {s}: cond1 {v['c1']} cond2 {v['c2']} cond3 {v['c3']} | delete not-worse {v['del_ok']}")
    print(f"three-season mean rebuild - DELETE: likely {ml:+.4f}, squad {ms:+.4f}; DELETE - incumbent: likely {dl:+.4f}, squad {ds:+.4f}")
    if reb_pass:
        print("DECISION: REBUILD PASSES -> recommend adoption of BONUS_MODE='outcome' (separate step)")
    elif del_pass:
        print("DECISION: REBUILD FAILS; DELETE beats the incumbent -> recommend BONUS_MODE='delete'")
    else:
        print("DECISION: REBUILD FAILS and DELETE does not beat the incumbent -> keep incumbent; both negatives recorded")


if __name__ == "__main__":
    main()
