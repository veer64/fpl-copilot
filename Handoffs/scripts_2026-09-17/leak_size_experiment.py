"""
Size of the cutoff-day Dixon-Coles leak on the 2025-26 record's decision
partitions. READ-ONLY on the repo: the fit is patched in THIS process only,
to train on matches dated strictly before the cutoff DAY (the cutoff is the
day's first kickoff, so no match of that day had finished at the cutoff).
The record file is the unpatched side (proven bit-identical to the
in-process reference by the as-of guard).

Per cutoff: max |delta attack/defence| of the fit, and e_points deltas on
(a) all rows, (b) likely starters p_start >= .75, (c) the record's top 30 by
e_points within (cutoff, gw), per horizon step; top-30 set overlap and
Spearman of counterfactual vs record e_points on the record's top 30.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dixon_coles as dc                      # noqa: E402
import asof_reconstruction as ar              # noqa: E402

SEASON = "2025-26"
CUTOFFS = [int(x) for x in sys.argv[1:]] or [3, 4, 7, 17, 24, 31, 38]
OUT = Path(sys.argv[0]).resolve().parent / "leak_size_results.json"

FIT_LOG = {}
_orig_fit = dc._fit_dc_decay


def patched_fit(train_matches, all_teams, ref_date, half_life_days):
    day = pd.Timestamp(ref_date).normalize()
    keep = train_matches["date_parsed"] < day
    dropped = int((~keep).sum())
    p_full, idx, nt = _orig_fit(train_matches, all_teams, ref_date, half_life_days)
    p_cf, _, _ = _orig_fit(train_matches[keep], all_teams, ref_date, half_life_days)
    FIT_LOG["last"] = dict(dropped_cutoff_day_matches=dropped, n_train_full=int(len(train_matches)),
                           max_abs_d_attack=float(np.abs(p_cf[:nt] - p_full[:nt]).max()),
                           max_abs_d_defence=float(np.abs(p_cf[nt:2 * nt] - p_full[nt:2 * nt]).max()),
                           d_home_adv=float(p_cf[-2] - p_full[-2]))
    return p_cf, idx, nt


dc._fit_dc_decay = patched_fit
canon = pd.read_parquet(ar.canonical_path(SEASON, "baseline"))
results = {}
for k in CUTOFFS:
    t0 = time.time()
    FIT_LOG.clear()
    cf = ar.build_reference(SEASON, k, config="baseline", horizon=6)
    rec = canon[canon["cutoff"] == k]
    key = ["element", "gw"]
    m = rec.merge(cf[key + ["e_points", "team_lambda", "opp_lambda", "p_cs"]], on=key, suffixes=("_rec", "_cf"))
    m["d"] = (m["e_points_cf"] - m["e_points_rec"]).abs()
    m["step"] = m["gw"] - k
    per_step = {}
    for st, g in m.groupby("step"):
        starters = g[g["p_start"] >= 0.75]
        top = g.nlargest(30, "e_points_rec")
        top_cf = set(g.nlargest(30, "e_points_cf")["element"])
        sp = spearmanr(top["e_points_rec"], top["e_points_cf"]).correlation if len(top) > 2 else None
        per_step[int(st)] = dict(
            rows=int(len(g)), rows_changed=int((g["d"] > 1e-9).sum()),
            all_mean=float(g["d"].mean()), all_max=float(g["d"].max()),
            starters_n=int(len(starters)), starters_mean=float(starters["d"].mean()) if len(starters) else None,
            starters_max=float(starters["d"].max()) if len(starters) else None,
            top30_mean=float(top["d"].mean()), top30_max=float(top["d"].max()),
            top30_overlap=int(len(set(top["element"]) & top_cf)), top30_spearman=(None if sp is None else float(sp)),
            lambda_mean_abs_d=float((m.loc[g.index, "team_lambda_cf"] - m.loc[g.index, "team_lambda_rec"]).abs().mean()),
            p_cs_mean_abs_d=float((m.loc[g.index, "p_cs_cf"] - m.loc[g.index, "p_cs_rec"]).abs().mean()),
        )
    results[k] = dict(fit=dict(FIT_LOG.get("last", {})), rows_matched=int(len(m)), rows_record=int(len(rec)),
                      per_step=per_step, seconds=round(time.time() - t0, 1))
    print(f"cutoff {k}: fit {results[k]['fit']} | rows {len(m)}/{len(rec)} | "
          + " ".join(f"s{st}: all {v['all_mean']:.4f}/{v['all_max']:.3f} st {v['starters_mean'] if v['starters_mean'] is None else round(v['starters_mean'],4)} "
                     f"top30 {v['top30_mean']:.4f}/{v['top30_max']:.3f} ov {v['top30_overlap']} rho {v['top30_spearman'] if v['top30_spearman'] is None else round(v['top30_spearman'],3)}"
                     for st, v in per_step.items())
          + f" | {results[k]['seconds']}s", flush=True)
    OUT.write_text(json.dumps(results, indent=1), encoding="utf-8")
print("DONE ->", OUT)
