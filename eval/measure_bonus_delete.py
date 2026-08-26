#!/usr/bin/env python
"""Adoption measurement for BONUS_MODE='delete' -- Logs/bonus_delete_prereg.md sections 2-5, exactly as written.

    uv run python eval/measure_bonus_delete.py

DELETE (walkforward_h6_{season}_bonusdel.parquet) vs incumbent (canonical), common population, three seasons.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
SEASONS = [("2023-24", "2023_24"), ("2024-25", "2024_25"), ("2025-26", "2025_26")]
POS = ["FWD", "MID", "DEF", "GK"]


def rho(a, b):
    return float(spearmanr(a, b).correlation)


def actuals(season):
    h = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet")
    h = h[(h["season"] == season) & (h["position"] != "AM")]
    hs = (h.groupby(["element", "GW"]).agg(minutes_v=("minutes", "sum"), pts=("total_points", "sum"), bonus=("bonus", "sum"))
          .reset_index().rename(columns={"GW": "gw"}))
    hs["element"] = hs["element"].astype(int); return hs


def main():
    verdict = {}
    for season, tag in SEASONS:
        canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
        dele = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}_bonusdel.parquet")
        assert (dele["bonus_mode"] == "delete").all(), "DELETE frame not stamped on every row"
        assert "bonus_mode" not in canon.columns or (canon["bonus_mode"] == "incumbent").all()
        c0 = canon[(canon.horizon_step == 0) & (canon.n_fixtures == 1)]
        d0 = dele[(dele.horizon_step == 0) & (dele.n_fixtures == 1)]
        d = c0.merge(d0[["element", "gw", "e_points"]], on=["element", "gw"], suffixes=("", "_del"))
        assert len(d) == len(c0) == len(d0)
        assert np.allclose(d["e_points_del"], d["e_points_core"])
        d = d.merge(actuals(season), on=["element", "gw"], how="inner")
        LS = d.p_start >= 0.75; T30 = d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30; ST = d.minutes_v >= 60
        print(f"\n================ {season}: paired rows {len(d)}; DELETE rows stamped bonus_mode='delete': {len(dele):,} ================")
        R = {}
        for name, m in [("likely starters", LS), ("squad-relevant (top30)", T30), ("uncertain", (d.p_start >= .25) & (d.p_start < .75)),
                        ("written off", d.p_start < .25), ("realised started", ST)]:
            q = d[m]; ri, rd = rho(q.e_points, q.pts), rho(q.e_points_del, q.pts); R[name] = rd - ri
            print(f"  {name:24s} n={len(q):6d}  rho incumbent {ri:.4f}  DELETE {rd:.4f}  delta {rd - ri:+.4f}")
        st = d[ST]
        mae_i, mae_d = float(np.abs(st.e_points - st.pts).mean()), float(np.abs(st.e_points_del - st.pts).mean())
        print(f"  [cond 2] e_points MAE on realised starters: incumbent {mae_i:.3f} -> DELETE {mae_d:.3f} ({mae_d - mae_i:+.3f})")
        # level, overall
        for name, q in [("likely starters", d[LS]), ("realised started", st), ("top30", d[T30]), ("all rows", d)]:
            print(f"  level {name:18s}: e_points {q.e_points.mean():.3f} -> {q.e_points_del.mean():.3f} vs realised {q.pts.mean():.3f} "
                  f"(ratio {q.e_points.mean() / q.pts.mean():.3f} -> {q.e_points_del.mean() / q.pts.mean():.3f}); realised bonus on these rows {q.bonus.mean():.3f}")
        # level by position + spread (cond 3)
        spreads = {}
        for pname, m in [("likely starters", LS), ("top30", T30)]:
            errs_i, errs_d = {}, {}
            line = []
            for p in POS:
                q = d[m & (d.position == p)]
                if len(q) < 20:
                    continue
                ei, ed = q.e_points.mean() - q.pts.mean(), q.e_points_del.mean() - q.pts.mean()
                errs_i[p], errs_d[p] = ei, ed
                line.append(f"{p} n={len(q)}: pred {q.e_points.mean():.2f}->{q.e_points_del.mean():.2f} real {q.pts.mean():.2f} err {ei:+.2f}->{ed:+.2f} (deleted term {q.exp_bonus.mean():.2f}, realised bonus {q.bonus.mean():.2f})")
            outf = [p for p in ["FWD", "MID", "DEF"] if p in errs_i]
            sp_i = max(errs_i[p] for p in outf) - min(errs_i[p] for p in outf); sp_d = max(errs_d[p] for p in outf) - min(errs_d[p] for p in outf)
            spreads[pname] = (sp_i, sp_d)
            print(f"  by position, {pname}: " + " | ".join(line))
            print(f"    spread of position errors (max-min over FWD/MID/DEF): incumbent {sp_i:.3f} -> DELETE {sp_d:.3f}")
        # within-position rank on likely starters
        wp = {p: (rho(d[LS & (d.position == p)].e_points, d[LS & (d.position == p)].pts), rho(d[LS & (d.position == p)].e_points_del, d[LS & (d.position == p)].pts)) for p in POS}
        print("  within-position rank on likely starters (incumbent -> DELETE): " + "  ".join(f"{p} {a:.3f}->{b:.3f}" for p, (a, b) in wp.items()))
        c1 = R["likely starters"] >= -0.003 and R["squad-relevant (top30)"] >= -0.003
        c2 = mae_d <= mae_i + 1e-9
        c3 = spreads["likely starters"][1] <= spreads["likely starters"][0] + 1e-9
        print(f"  [cond 1] rank likely {R['likely starters']:+.4f}, squad {R['squad-relevant (top30)']:+.4f} -> {'PASS' if c1 else 'FAIL'}; "
              f"[cond 2] MAE -> {'PASS' if c2 else 'FAIL'}; [cond 3] position spread on likely starters {spreads['likely starters'][0]:.3f} -> {spreads['likely starters'][1]:.3f} -> {'PASS' if c3 else 'FAIL'}")
        verdict[season] = dict(c1=c1, c2=c2, c3=c3, dl=R["likely starters"], ds=R["squad-relevant (top30)"])
    ml = np.mean([v["dl"] for v in verdict.values()]); ms = np.mean([v["ds"] for v in verdict.values()])
    ok = all(v["c1"] and v["c2"] and v["c3"] for v in verdict.values()) and ml > 0 and ms > 0
    print("\n================ VERDICT (Logs/bonus_delete_prereg.md section 2) ================")
    for s, v in verdict.items():
        print(f"  {s}: cond1 {v['c1']} cond2 {v['c2']} cond3 {v['c3']}")
    print(f"three-season mean rank delta: likely {ml:+.4f}, squad-relevant {ms:+.4f} (must be > 0)")
    print("OVERALL:", "PASS -> ADOPT BONUS_MODE='delete'" if ok else "FAIL -> incumbent stays")


if __name__ == "__main__":
    main()
