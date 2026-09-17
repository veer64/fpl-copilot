"""What drives the top-30 delta in the affected cells: per (season, cutoff, step) the top-30 Spearman
record v form, how many of the affected club's players sit in each top 30, and the delta split by
whether the affected club has a player in either top 30."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(r"C:\dev\fpl-copilot")
HERE = Path(__file__).resolve().parent
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs", "Sheffield United": "Sheffield Utd"}
import os
PREFIX = os.environ.get("V2_PREFIX", "ref_v2")
for season in ["2023-24", "2024-25", "2025-26"]:
    tag = season.replace("-", "_")
    ref = pd.read_parquet(HERE / f"{PREFIX}_{tag}.parquet")
    rec = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    fits = json.loads((HERE / f"{PREFIX}_{tag}_fits.json").read_text(encoding="utf-8"))
    cutoffs = sorted(ref["cutoff"].unique())
    affected = {k: sorted(TEAM_MAP.get(c, c) for c in (set(f.get("clubs_below_n") or {}) | set(f.get("at_bound") or {})))
                for k, f in zip(cutoffs, fits) if (f.get("clubs_below_n") or f.get("at_bound"))}
    rows = []
    for k, clubs in affected.items():
        for st in range(1, 6):
            a = rec[(rec["cutoff"] == k) & (rec["horizon_step"] == st)].dropna(subset=["e_points", "actual_points"])
            b = ref[(ref["cutoff"] == k) & (ref["horizon_step"] == st)].dropna(subset=["e_points", "actual_points"])
            if len(a) < 30:
                continue
            ta, tb = a.nlargest(30, "e_points"), b.nlargest(30, "e_points")
            ra = spearmanr(ta["e_points"], ta["actual_points"]).correlation
            rb = spearmanr(tb["e_points"], tb["actual_points"]).correlation
            na, nb = int(ta["team"].isin(clubs).sum()), int(tb["team"].isin(clubs).sum())
            # the affected club's players' mean actual points when in the form's top 30
            pts_b = float(tb.loc[tb["team"].isin(clubs), "actual_points"].mean()) if nb else np.nan
            rows.append(dict(cutoff=k, step=st, gw=int(k + st), top30_rec=ra, top30_new=rb, d=rb - ra, n_club_rec=na, n_club_new=nb,
                             club_pts_in_new_top30=pts_b, top30_mean_pts_new=float(tb["actual_points"].mean())))
    d = pd.DataFrame(rows)
    print(f"===== {season}: affected clubs {sorted(set(sum(affected.values(), [])))}; cells {len(d)}")
    print(f"  mean top-30 delta {d['d'].mean():+.4f}; cells with the club in NEITHER top 30: {int(((d.n_club_rec == 0) & (d.n_club_new == 0)).sum())} "
          f"(delta there {d.loc[(d.n_club_rec == 0) & (d.n_club_new == 0), 'd'].mean():+.4f}); cells with the club in the FORM's top 30: "
          f"{int((d.n_club_new > 0).sum())} (delta there {d.loc[d.n_club_new > 0, 'd'].mean():+.4f})")
    print(f"  club players in top 30: record total {int(d.n_club_rec.sum())}, form total {int(d.n_club_new.sum())}; "
          f"their mean actual points when in the form's top 30 {d['club_pts_in_new_top30'].mean():.2f} v the top 30's mean {d['top30_mean_pts_new'].mean():.2f}")
    worst = d.sort_values("d").head(6)
    print("  six worst cells (cutoff, step, gw, top30 rec->new, club players rec->new):")
    for _, r in worst.iterrows():
        print(f"    {int(r.cutoff):2d} {int(r.step)} gw{int(r.gw):2d}  {r.top30_rec:+.3f} -> {r.top30_new:+.3f} ({r.d:+.3f})  {int(r.n_club_rec)} -> {int(r.n_club_new)}")
