"""
Bar item 5 (Logs/dc_fix_prereg_2026-09-13.md section 5): the rebuilt 2025-26
canonical vs the preserved pre-fix record, per cutoff, per step, on the
decision partitions -- the SAME definitions as the step-1 leak measurement
(scratch leak_size_experiment.py, finding log section 8): top 30 = the OLD
record's top 30 by e_points within (cutoff, gw); likely starters = p_start
>= .75; Spearman on the top 30 of old vs new e_points. Plus the number of
cutoff-day matches the OLD filter admitted (dated ON the cutoff day, result
present) so "nothing moved at a cutoff with >= 5 admitted" can be applied.
Also the fingerprint (rows, step-0 Spearman/MAE vs actual_points) of both.

Usage: python rank_endpoint.py <season> [baseline|combined-frame path pair]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc            # noqa: E402
import season_stack                 # noqa: E402

season = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
tag = season.replace("-", "_")
new_p = REPO / "data" / f"walkforward_h6_{tag}.parquet"
old_p = REPO / "data" / f"walkforward_h6_{tag}_pre_dcfix.parquet"
new, old = pd.read_parquet(new_p), pd.read_parquet(old_p)

# admitted cutoff-day matches per cutoff (old filter: date_parsed < timed cutoff; new: < day)
stack = pd.read_parquet(season_stack.stack_path())
cur = stack[stack["season"] == season]
kick = pd.to_datetime(cur["kickoff_time"])
m = dc._load_matches(season)
m = m[m["season"] == season]
admitted = {}
for k in sorted(cur["GW"].unique()):
    cutoff = kick[cur["GW"] == k].min().tz_localize(None)
    old_ok = (m["date_parsed"] < cutoff) & m["home_goals"].notna()
    new_ok = dc.knowable_before(m, cutoff)
    admitted[int(k)] = int((old_ok & ~new_ok).sum())

key = ["element", "gw"]
out = {"season": season, "rows_old": int(len(old)), "rows_new": int(len(new)), "admitted": admitted, "cutoffs": {}}
stops, notes = [], []
for k in sorted(old["cutoff"].unique()):
    o = old[old["cutoff"] == k]; n = new[new["cutoff"] == k]
    mm = o.merge(n[key + ["e_points", "team_lambda"]], on=key, suffixes=("_old", "_new"), how="outer", indicator=True)
    rowset_ok = bool((mm["_merge"] == "both").all())
    mm = mm[mm["_merge"] == "both"].copy()
    mm["d"] = (mm["e_points_new"] - mm["e_points_old"]).abs()
    mm["step"] = mm["gw"] - k
    per = {}
    for st, g in mm.groupby("step"):
        top = g.nlargest(30, "e_points_old")
        starters = g[g["p_start"] >= 0.75]
        rho = float(spearmanr(top["e_points_old"], top["e_points_new"]).correlation) if len(top) > 2 else None
        per[int(st)] = dict(rows=int(len(g)), rows_changed=int((g["d"] > 1e-9).sum()),
                            top30_rho=rho, top30_mean=float(top["d"].mean()), top30_max=float(top["d"].max()),
                            top30_overlap=int(len(set(top["element"]) & set(g.nlargest(30, "e_points_new")["element"]))),
                            starters_n=int(len(starters)), starters_mean=(float(starters["d"].mean()) if len(starters) else None),
                            lambda_mean_abs_d=float((g["team_lambda_new"] - g["team_lambda_old"]).abs().mean()))
        # the bar, verbatim
        if st == 0:
            if rho is not None and rho < 0.99: stops.append(f"cutoff {k} step 0: top-30 rho {rho:.4f} < 0.99")
            if per[int(st)]["starters_mean"] is not None and per[int(st)]["starters_mean"] > 0.03:
                stops.append(f"cutoff {k} step 0: starters mean |d| {per[int(st)]['starters_mean']:.4f} > 0.03")
        else:
            if rho is not None and rho < 0.90: stops.append(f"cutoff {k} step {st}: top-30 rho {rho:.4f} < 0.90")
            if per[int(st)]["starters_mean"] is not None and per[int(st)]["starters_mean"] > 0.10:
                stops.append(f"cutoff {k} step {st}: starters mean |d| {per[int(st)]['starters_mean']:.4f} > 0.10")
    moved_any = any(v["rows_changed"] > 0 for s, v in per.items() if s >= 1)
    if admitted.get(int(k), 0) >= 5 and not moved_any:
        stops.append(f"cutoff {k}: {admitted[int(k)]} admitted cutoff-day matches but NOTHING moved at steps >= 1 (a too-clean result is a tell)")
    if admitted.get(int(k), 0) == 0 and moved_any:
        notes.append(f"cutoff {k}: 0 admitted cutoff-day matches yet steps >= 1 moved ({sum(v['rows_changed'] for s, v in per.items() if s >= 1)} rows) -- explain")
    out["cutoffs"][int(k)] = dict(rowset_identical=rowset_ok, admitted=admitted.get(int(k), 0), steps=per)

def fingerprint(d):
    s = d[d["horizon_step"] == 0] if "horizon_step" in d.columns else d[d["gw"] == d["cutoff"]]
    s = s.dropna(subset=["actual_points"])
    return dict(rows=int(len(d)), step0_rows=int(len(s)),
                spearman=float(spearmanr(s.e_points, s.actual_points).statistic),
                mae=float((s.e_points - s.actual_points).abs().mean()))
out["fingerprint_old"] = fingerprint(old); out["fingerprint_new"] = fingerprint(new)
out["stops"] = stops; out["notes"] = notes
Path(__file__).with_name(f"rank_endpoint_{tag}.json").write_text(json.dumps(out, indent=1))

print(f"{season}: rows old {len(old):,} new {len(new):,}; admitted cutoff-day matches total {sum(admitted.values())} over {len(admitted)} cutoffs")
print(f"fingerprint old {out['fingerprint_old']}")
print(f"fingerprint new {out['fingerprint_new']}")
print("cutoff adm | step0 rho / top30 mean / starters mean | steps1-5 rho min / top30 mean range / starters mean max / overlap min | rows changed s>=1")
for k, v in out["cutoffs"].items():
    st = v["steps"]; s0 = st.get(0, {})
    later = [st[s] for s in st if s >= 1]
    if later:
        rmin = min(x["top30_rho"] for x in later if x["top30_rho"] is not None)
        tm = (min(x["top30_mean"] for x in later), max(x["top30_mean"] for x in later))
        smax = max((x["starters_mean"] or 0) for x in later)
        ovl = min(x["top30_overlap"] for x in later)
        ch = sum(x["rows_changed"] for x in later)
        later_s = f"{rmin:.3f} / {tm[0]:.3f}-{tm[1]:.3f} / {smax:.3f} / {ovl} | {ch}"
    else:
        later_s = "(no later steps)"
    print(f"{k:>3} {v['admitted']:>3} | {s0.get('top30_rho', float('nan')):.4f} / {s0.get('top30_mean', 0):.4f} / {(s0.get('starters_mean') or 0):.4f} | {later_s}{'' if v['rowset_identical'] else '  ROWSET DIFFERS'}")
print("\nSTOPS:" if stops else "\nSTOPS: none")
for s in stops: print("  " + s)
for n in notes: print("  note: " + n)
