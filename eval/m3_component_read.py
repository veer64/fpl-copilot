"""M3 B2 -- ranking metrics of a crowd frame against the frame of record, step 0. PROBE CODE: read-only, nothing
in production imports it.

Definitions of record (M1's component read; X2 plan section 8; all on step-0 rows, one truth for both frames --
the de-duplicated history stack, points and minutes summed and starts maxed over a gameweek's fixtures):
  likely-starter Spearman   e_points vs realised points on the rows with p_start >= 0.75, pooled over the season
                            (EACH frame's own p_start decides its rows -- the convention of the values of record
                            0.3226 / 0.2950 / 0.2047)
  top-30 Spearman           e_points vs realised points on each frame's own 30 highest e_points per gameweek
                            (ties by first occurrence), pooled over the season
  top-10 yield              mean realised points of each frame's 10 highest e_points per gameweek, averaged over
                            gameweeks
  P(start) AUC / Brier      single-fixture rows, against the stack's `starts`
Delta = crowd - baseline, with a 95% interval from 2,000 bootstrap draws over gameweeks (whole gameweeks are
resampled; both frames are scored on the same draw). Also printed, no rule: the likely-starter Spearman with
the rows FIXED on the baseline frame's p_start (the same rows for both frames).

Usage:
    uv run python eval/m3_component_read.py --season 2025-26 --base data/walkforward_h6_2025_26.parquet \
        --crowd data/arms_crowd/walkforward_h6_2025_26_crowd.parquet [--out data/m3/b2_2025_26.json]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import brier_score_loss, roc_auc_score

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

NB = 2000
LS_THRESHOLD = 0.75
METRICS = ("ls_rho", "top30_rho", "top10_yield", "pstart_auc", "pstart_brier", "ls_rho_fixed_rows")


def truth(season, stack_path=None):
    """Realised points / minutes / starts per (element, gameweek) from the de-duplicated stack."""
    import season_stack
    h = pd.read_parquet(stack_path or season_stack.stack_path(),
                        columns=["season", "element", "GW", "fixture", "minutes", "total_points", "starts", "position"])
    h = h[(h["season"] == season) & (h["position"] != "AM")]
    assert not h.duplicated(["element", "fixture"]).any(), "the truth stack must be the de-duplicated one"
    return (h.groupby(["element", "GW"], as_index=False)
             .agg(pts=("total_points", "sum"), mins=("minutes", "sum"), starts=("starts", "max"))
             .rename(columns={"GW": "gw"}))


def step0(frame, tr):
    s0 = frame[frame["horizon_step"] == 0].merge(tr, on=["element", "gw"], how="left")
    assert s0["pts"].notna().all(), "a step-0 row without a truth row"
    return s0


def by_gameweek(d, fixed_keys):
    """Per gameweek, the rows each metric reads -- every selection (p_start >= 0.75, the 30 / 10 highest e_points,
    single-fixture rows) is made WITHIN a gameweek, so it does not depend on which other gameweeks a bootstrap
    draw holds. `fixed_keys` = the (element, gameweek) keys of the baseline frame's likely starters."""
    out = {}
    for gw, g in d.groupby("gw"):
        rank = g["e_points"].rank(ascending=False, method="first")
        ls, t30, t10 = g[g["p_start"] >= LS_THRESHOLD], g[rank <= 30], g[rank <= 10]
        fx = g[g["_key"].isin(fixed_keys)]
        s1 = g[(g["n_fixtures"] == 1) & g["starts"].notna()]
        out[int(gw)] = dict(ls=(ls["e_points"].to_numpy(float), ls["pts"].to_numpy(float)),
                            fixed=(fx["e_points"].to_numpy(float), fx["pts"].to_numpy(float)),
                            t30=(t30["e_points"].to_numpy(float), t30["pts"].to_numpy(float)),
                            t10=float(t10["pts"].mean()),
                            s1=(s1["p_start"].clip(0, 1).to_numpy(float), s1["starts"].clip(upper=1).to_numpy(int)),
                            n=len(g))
    return out


def _rho(e, p):
    if len(e) < 3 or np.ptp(e) == 0 or np.ptp(p) == 0:
        return float("nan")
    return float(spearmanr(e, p).statistic)


def metrics(parts, gws):
    """The metrics of record over the gameweeks `gws` (a list; a gameweek may appear more than once)."""
    cat = lambda k, i: np.concatenate([parts[g][k][i] for g in gws])
    p, y = cat("s1", 0), cat("s1", 1)
    return dict(ls_rho=_rho(cat("ls", 0), cat("ls", 1)), top30_rho=_rho(cat("t30", 0), cat("t30", 1)),
                top10_yield=float(np.mean([parts[g]["t10"] for g in gws])),
                pstart_auc=float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else float("nan"),
                pstart_brier=float(brier_score_loss(y, p)),
                ls_rho_fixed_rows=_rho(cat("fixed", 0), cat("fixed", 1)),
                n=int(sum(parts[g]["n"] for g in gws)), n_ls=int(sum(len(parts[g]["ls"][0]) for g in gws)),
                n_single=int(sum(len(parts[g]["s1"][0]) for g in gws)))


def read(base, crowd, nb=NB, seed=0):
    """Point metrics for both frames, deltas (crowd - base), and bootstrap intervals over gameweeks."""
    for d in (base, crowd):
        d["_key"] = d["element"].astype(np.int64) * 100 + d["gw"].astype(np.int64)
    fixed = set(base.loc[base["p_start"] >= LS_THRESHOLD, "_key"])
    pb, pc = by_gameweek(base, fixed), by_gameweek(crowd, fixed)
    gws = sorted(pb)
    assert gws == sorted(pc)
    mb, mc = metrics(pb, gws), metrics(pc, gws)
    rng = np.random.default_rng(seed)
    draws = {m: np.empty(nb) for m in METRICS}
    for i in range(nb):
        pick = [gws[j] for j in rng.integers(0, len(gws), len(gws))]
        xb, xc = metrics(pb, pick), metrics(pc, pick)
        for m in METRICS:
            draws[m][i] = xc[m] - xb[m]
    out = {}
    for m in METRICS:
        out[m] = dict(base=mb[m], crowd=mc[m], delta=mc[m] - mb[m],
                      lo=float(np.nanpercentile(draws[m], 2.5)), hi=float(np.nanpercentile(draws[m], 97.5)))
    out["_n"] = dict(rows=mb["n"], ls_base=mb["n_ls"], ls_crowd=mc["n_ls"], single_fixture=mb["n_single"], gameweeks=len(gws))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--crowd", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    if a.out is not None and a.out.exists():
        raise FileExistsError(f"{a.out} exists -- a probe output is never written over")
    tr = truth(a.season)
    cols = ["cutoff", "gw", "horizon_step", "element", "name", "p_start", "e_points", "n_fixtures"]
    base, crowd = step0(pd.read_parquet(a.base, columns=cols), tr), step0(pd.read_parquet(a.crowd, columns=cols), tr)
    assert len(base) == len(crowd) and (base[["element", "gw"]].to_numpy() == crowd[["element", "gw"]].to_numpy()).all(), \
        "the two frames must hold the same step-0 rows"
    r = read(base, crowd)
    n = r["_n"]
    print(f"[{a.season}] step-0 rows {n['rows']:,} over {n['gameweeks']} gameweeks | likely starters: baseline {n['ls_base']:,}, crowd {n['ls_crowd']:,} "
          f"| single-fixture rows {n['single_fixture']:,} | base {a.base.name} | crowd {a.crowd.name}")
    label = {"ls_rho": "likely-starter Spearman", "top30_rho": "top-30 Spearman", "top10_yield": "top-10 yield (pts per player-gameweek)",
             "pstart_auc": "P(start) AUC", "pstart_brier": "P(start) Brier", "ls_rho_fixed_rows": "likely-starter Spearman, rows fixed on the baseline (side read)"}
    for m in METRICS:
        x = r[m]
        print(f"[{a.season}] {label[m]:62s} baseline {x['base']:.4f} | crowd {x['crowd']:.4f} | delta {x['delta']:+.4f} [{x['lo']:+.4f}, {x['hi']:+.4f}]")
    if a.out is not None:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"season": a.season, "base": a.base.name, "crowd": a.crowd.name, **r}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
