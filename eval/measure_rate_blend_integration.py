"""Measures the rate-blend INTEGRATION: _prerateblend (before) vs canonical (after) -- aggregate rho/MAE, starter-band rho and margin beta, top-k realised points with 2SE resolution, and top-k agreement. Result of record: Logs/rate_blend_log.md §8 items 3-5. Distinct from measure_rate_blend.py (the D2 tuning study). NOTE: canonical has since been rebuilt (#15, 2026-08-19), so figures will differ slightly from the logged record.

Rate-blend integration: before (_prerateblend) vs after, per season, step 0.
Aggregate rho/MAE; starter-band rho + margin beta by position; top-k realized
points (k=1,3,5, both pools, per-gw spread, 2SE resolution); agreement."""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
POSITIONS = ["GK", "DEF", "MID", "FWD"]
KS = [1, 3, 5]
SEASONS = ["2025-26", "2024-25", "2023-24"]

def step0(path):
    df = pd.read_parquet(path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

def beta(g, col="e_points"):
    num = den = 0.0
    for _, grp in g.groupby("gw"):
        n = len(grp)
        if n < 2: continue
        x = grp[col].to_numpy(float); y = grp["actual_points"].to_numpy(float)
        num += n*(x*y).sum() - x.sum()*y.sum(); den += n*(x*x).sum() - x.sum()**2
    return num/den if den > 0 else np.nan

n_res, n_tot = 0, 0
for season in SEASONS:
    tag = season.replace("-", "_")
    before = step0(BASE + rf"\data\walkforward_h6_{tag}_prerateblend.parquet")
    after = step0(BASE + rf"\data\walkforward_h6_{tag}.parquet")
    stamp = after["rate_blend_active"].iloc[0] if "rate_blend_active" in after.columns else "ABSENT"
    kval = after["rate_blend_k"].iloc[0] if "rate_blend_k" in after.columns else "?"
    print(f"\n================ {season} ================ (after stamp: rate_blend_active={stamp}, k={kval})")

    for name, d in (("before", before), ("after", after)):
        rho = spearmanr(d["e_points"], d["actual_points"]).statistic
        mae = (d["e_points"] - d["actual_points"]).abs().mean()
        print(f"  {name}: aggregate rho {rho:.4f}  MAE {mae:.4f}  (n={len(d)})")

    print(f"  {'starter band':14s} {'pos':4s} {'rho_b':>8s} {'rho_a':>8s} {'d_rho':>8s} {'beta_b':>8s} {'beta_a':>8s} {'d_beta':>8s}")
    for pos in POSITIONS:
        gb = before[(before.e_minutes >= 60) & (before.position == pos)]
        ga = after[(after.e_minutes >= 60) & (after.position == pos)]
        rb_ = spearmanr(gb.e_points, gb.actual_points).statistic
        ra_ = spearmanr(ga.e_points, ga.actual_points).statistic
        bb_, ba_ = beta(gb), beta(ga)
        print(f"  {'':14s} {pos:4s} {rb_:8.4f} {ra_:8.4f} {ra_-rb_:+8.4f} {bb_:8.4f} {ba_:8.4f} {ba_-bb_:+8.4f}")

    # top-k + agreement, per gw/pos
    m = before.merge(after[["element", "gw", "e_points"]], on=["element", "gw"],
                     suffixes=("_b", "_a"), how="inner")
    tk = {}
    agree = {}
    for (gw, pos), g in m.groupby(["gw", "position"]):
        if pos not in POSITIONS: continue
        started = g[g["minutes"] >= 60]
        for k in KS:
            tb = g.nlargest(min(k, len(g)), "e_points_b")
            ta = g.nlargest(min(k, len(g)), "e_points_a")
            tk.setdefault((pos, k, "all", "b"), {})[gw] = tb["actual_points"].mean()
            tk.setdefault((pos, k, "all", "a"), {})[gw] = ta["actual_points"].mean()
            sb_ = started.nlargest(min(k, len(started)), "e_points_b")
            sa_ = started.nlargest(min(k, len(started)), "e_points_a")
            tk.setdefault((pos, k, "started", "b"), {})[gw] = sb_["actual_points"].mean() if len(sb_) else np.nan
            tk.setdefault((pos, k, "started", "a"), {})[gw] = sa_["actual_points"].mean() if len(sa_) else np.nan
            agree.setdefault((pos, k), []).append(len(set(tb.index) & set(ta.index)))
        agree.setdefault((pos, "same1"), []).append(
            int(g.nlargest(1, "e_points_b").index[0] == g.nlargest(1, "e_points_a").index[0]))

    print(f"\n  top-k realised pts:  pos k pool   before(SD)      after(SD)       delta[2SE]")
    for pool in ("all", "started"):
        for pos in POSITIONS:
            for k in KS:
                sb_ = pd.Series(tk[(pos, k, pool, "b")]); sa_ = pd.Series(tk[(pos, k, pool, "a")])
                dd = (sa_ - sb_).dropna()
                se2 = 2 * dd.std() / np.sqrt(len(dd))
                res = abs(dd.mean()) > se2
                n_tot += 1; n_res += int(res)
                print(f"    {pos:4s} {k} {pool:7s} {sb_.mean():6.3f} ({sb_.std():5.3f}) "
                      f"{sa_.mean():6.3f} ({sa_.std():5.3f}) {dd.mean():+6.3f} [{se2:5.3f}] {'RES' if res else '.'}")

    print(f"\n  agreement:  pos  same#1   ovl@3    ovl@5")
    for pos in POSITIONS:
        s1 = np.mean(agree[(pos, "same1")])
        o3 = np.mean(agree[(pos, 3)]); o5 = np.mean(agree[(pos, 5)])
        print(f"    {pos:4s} {s1:7.2%} {o3:7.3f}/3 {o5:6.3f}/5")

print(f"\nTOP-K RESOLUTION: {n_res} of {n_tot} cells resolve (>2SE)")
