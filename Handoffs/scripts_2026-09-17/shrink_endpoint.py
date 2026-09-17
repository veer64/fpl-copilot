"""The pre-registered endpoint (Logs/dc_shrinkage_prereg_2026-09-13.md section 4), computed
verbatim: reference builds WITH the prior (scratch ref_shrink_k4_*.parquet) vs the current
record (data/walkforward_h6_*.parquet, the 2026-09-13 DC-fix rebuild, no prior).

Sliced Spearman(e_points, actual_points) per (cutoff, step) on (i) likely starters
p_start >= .75 and (ii) the top 30 by e_points within the gameweek (of each frame, its own
ranking); means over cutoffs at steps 1-5 (primary, six numbers) and at step 0.
Section 3's tells: movement at the early cutoffs; established clubs at mid-season.
Sanity: every team lambda within [0.15, 6.0]. Falsifier: any primary delta < -0.005."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(r"C:\dev\fpl-copilot")
HERE = Path(__file__).resolve().parent
K = int(sys.argv[1]) if len(sys.argv) > 1 else 4
SEASONS = sys.argv[2:] or ["2023-24", "2024-25", "2025-26"]


def sliced(d):
    """per (cutoff, step): spearman on starters and on the top 30 by e_points."""
    d = d.dropna(subset=["e_points", "actual_points"]).copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    d = d.dropna(subset=["actual_points"])
    d["step"] = d["gw"] - d["cutoff"]
    out = []
    for (k, st), g in d.groupby(["cutoff", "step"]):
        s = g[g["p_start"] >= 0.75]
        t = g.nlargest(30, "e_points")
        rs = spearmanr(s["e_points"], s["actual_points"]).correlation if len(s) > 5 else np.nan
        rt = spearmanr(t["e_points"], t["actual_points"]).correlation if len(t) > 5 else np.nan
        out.append(dict(cutoff=int(k), step=int(st), starters=rs, top30=rt, n_starters=len(s)))
    return pd.DataFrame(out)


summary = {}
stops, notes = [], []
for season in SEASONS:
    tag = season.replace("-", "_")
    ref = pd.read_parquet(HERE / f"ref_shrink_k{K}_{tag}.parquet")
    rec = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    rec = rec[rec["cutoff"].isin(ref["cutoff"].unique())]          # a cutoff-subset build compares on its cutoffs only
    assert len(ref) == len(rec), (len(ref), len(rec))
    a, b = sliced(rec), sliced(ref)
    m = a.merge(b, on=["cutoff", "step"], suffixes=("_rec", "_new"))
    later, s0 = m[m["step"] >= 1], m[m["step"] == 0]
    prim = {sl: (float(later[f"{sl}_new"].mean() - later[f"{sl}_rec"].mean())) for sl in ("starters", "top30")}
    st0 = {sl: (float(s0[f"{sl}_new"].mean() - s0[f"{sl}_rec"].mean())) for sl in ("starters", "top30")}
    early = later[later["cutoff"] <= 6]
    early_d = {sl: float(early[f"{sl}_new"].mean() - early[f"{sl}_rec"].mean()) for sl in ("starters", "top30")}
    # lambdas: bounds, and movement by cutoff band
    key = ["cutoff", "gw", "team"]
    ln = ref.groupby(key)["team_lambda"].first(); lo = rec.groupby(key)["team_lambda"].first()
    lam = pd.concat([lo.rename("rec"), ln.rename("new")], axis=1).dropna()
    lam["d"] = (lam["new"] - lam["rec"]).abs(); lam = lam.reset_index(); lam["step"] = lam["gw"] - lam["cutoff"]
    lam1 = lam[lam["step"] >= 1]
    bounds_ok = bool((ln.dropna() >= 0.15).all() and (ln.dropna() <= 6.0).all())
    early_move = float(lam1[lam1["cutoff"] <= 6]["d"].mean()); mid_move = float(lam1[lam1["cutoff"] >= 10]["d"].max())
    big_mid = lam1[(lam1["cutoff"] >= 10) & (lam1["d"] > 0.05)]
    fixed_cells = lam1[lam1["rec"] < 0.15]
    summary[season] = dict(primary_delta=prim, step0_delta=st0, early_cutoffs_delta=early_d,
                           rec_means={sl: float(later[f"{sl}_rec"].mean()) for sl in ("starters", "top30")},
                           new_means={sl: float(later[f"{sl}_new"].mean()) for sl in ("starters", "top30")},
                           lambda_bounds_ok=bounds_ok, lambda_min_new=float(ln.min()), lambda_max_new=float(ln.max()),
                           early_cutoffs_mean_abs_dlambda=early_move, mid_season_max_abs_dlambda=mid_move,
                           mid_season_cells_over_0_05=int(len(big_mid)),
                           cold_start_cells_fixed=fixed_cells[["cutoff", "team", "rec", "new"]].drop_duplicates(["cutoff", "team"]).to_dict("records"))
    for sl, v in prim.items():
        if v < -0.005:
            stops.append(f"{season} FALSIFIED: steps 1-5 {sl} mean Spearman moved {v:+.4f} (< -0.005)")
    for sl, v in st0.items():
        if abs(v) > 0.002:
            stops.append(f"{season} step 0 {sl} moved {v:+.4f} (|d| > 0.002)")
    if not bounds_ok:
        stops.append(f"{season}: a team lambda outside [0.15, 6.0] after the prior ({ln.min():.4f}..{ln.max():.4f})")
    if early_move < 1e-4:
        stops.append(f"{season}: NOTHING moved at the early cutoffs (mean |d lambda| {early_move:.5f}) -- a too-clean result")
    if len(big_mid):
        stops.append(f"{season}: {len(big_mid)} established-club cells at cutoffs >= 10 moved by > 0.05 in lambda (max {mid_move:.3f}) -- the prior is stronger than stated")
    print(f"\n=== {season} (k={K}) ===")
    print(f"  steps 1-5 mean Spearman  starters: {later['starters_rec'].mean():.4f} -> {later['starters_new'].mean():.4f} ({prim['starters']:+.4f})"
          f" | top30: {later['top30_rec'].mean():.4f} -> {later['top30_new'].mean():.4f} ({prim['top30']:+.4f})")
    print(f"  step 0    mean Spearman  starters: {s0['starters_rec'].mean():.4f} -> {s0['starters_new'].mean():.4f} ({st0['starters']:+.4f})"
          f" | top30: {s0['top30_rec'].mean():.4f} -> {s0['top30_new'].mean():.4f} ({st0['top30']:+.4f})")
    print(f"  early cutoffs 1-6, steps 1-5: starters {early_d['starters']:+.4f}, top30 {early_d['top30']:+.4f} (reported, not judged)")
    print(f"  lambda: bounds ok {bounds_ok} (min {ln.min():.4f} max {ln.max():.4f}); early-cutoff mean |d| {early_move:.4f}; "
          f"mid-season max |d| {mid_move:.4f}, cells > 0.05: {len(big_mid)}")
    print(f"  cold-start cells (rec < 0.15) -> new: {summary[season]['cold_start_cells_fixed']}")
    per_cut = later.groupby("cutoff")[["starters_rec", "starters_new", "top30_rec", "top30_new"]].mean()
    per_cut["d_starters"] = per_cut["starters_new"] - per_cut["starters_rec"]; per_cut["d_top30"] = per_cut["top30_new"] - per_cut["top30_rec"]
    print("  per-cutoff delta (steps 1-5), cutoffs 1-8: " + ", ".join(f"{int(c)}: {r.d_starters:+.3f}/{r.d_top30:+.3f}" for c, r in per_cut.head(8).iterrows()))
(HERE / f"shrink_endpoint_k{K}.json").write_text(json.dumps(dict(summary=summary, stops=stops), indent=1, default=float))
print("\nSTOPS / FALSIFIERS:" if stops else "\nSTOPS / FALSIFIERS: none")
for s in stops:
    print("  " + s)
