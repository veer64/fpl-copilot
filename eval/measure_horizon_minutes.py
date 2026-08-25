"""Acceptance test for the horizon minutes model (Logs/horizon_minutes_log.md): per step k = 1..5, on the common population of (gw, element) singles that carry a NEW step-k prediction, the STALE prediction (the cutoff's step-0 frame, i.e. today's behaviour) and the FRESH prediction (step 0 at the target's own cutoff) -- E[min] MAE and Spearman, Brier and AUC for P(start), P(play) and P(60+), share of the fresh-vs-stale gap closed, step-0 exact-reproduction check, and the cross-step flip rate vs today's. Read-only; no simulation.

Usage: uv run python eval/measure_horizon_minutes.py --levers refit [--baseline-levers refit]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
import minutes as mm  # noqa: E402

SEASONS = ["2023-24", "2024-25", "2025-26"]
SUB_RATE = 0.30    # assembly's P(play) composite: p_start + (1 - p_start) * 0.30


def auc(y, p):
    y = np.asarray(y, bool); p = np.asarray(p, float)
    if y.all() or (~y).all():
        return np.nan
    r = rankdata(p)
    return float((r[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum()))


def brier(y, p):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def score(f, lab):
    """f: frame with p_start, p60, e_minutes indexed like lab (gw, element)."""
    m = lab.join(f[["p_start", "p60", "e_minutes"]], how="inner")
    pp = m["p_start"] + (1 - m["p_start"]) * SUB_RATE
    p60 = m["p_start"] * m["p60"]
    err = m["e_minutes"] - m["minutes_capped"]
    band = pd.cut(m["minutes_capped"], [-1, 0, 59, 200], labels=["0", "1-59", "60+"])
    return dict(n=len(m),
                mae=float(err.abs().mean()),
                rmse=float(np.sqrt((err ** 2).mean())),
                bias=float(err.mean()),                       # mean predicted - mean actual (calibration)
                mae_band={b: float(err.abs()[band == b].mean()) for b in ("0", "1-59", "60+")},
                share_band={b: float((band == b).mean()) for b in ("0", "1-59", "60+")},
                rho=float(spearmanr(m["e_minutes"], m["minutes_capped"]).statistic),
                brier_start=brier(m["starts"] == 1, m["p_start"]), auc_start=auc(m["starts"] == 1, m["p_start"]),
                brier_play=brier(m["minutes"] > 0, pp), auc_play=auc(m["minutes"] > 0, pp),
                brier_60=brier(m["minutes_capped"] >= 60, p60), auc_60=auc(m["minutes_capped"] >= 60, p60))


def labels():
    df = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet")
    col = mm._prepare(df)
    return col[["season", "element", "GW", "starts", "minutes", "minutes_capped", "is_double_gw"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levers", default="refit")
    ap.add_argument("--baseline-levers", default=None,
                    help="an earlier hmin file to compare against (default: none)")
    a = ap.parse_args()
    lab_all = labels()
    print(f"ACCEPTANCE TEST -- levers '{a.levers}' vs STALE (today's copied step-0 frame) and FRESH (step 0 at the target's cutoff)\n")
    pooled = {k: [] for k in range(1, 6)}
    for season in SEASONS:
        tag = season.replace("-", "_")
        p = REPO / "data" / "horizon" / f"hmin_{tag}_{a.levers.replace(',', '+')}.parquet"
        if not p.exists():
            print(f"{season}: {p.name} not on disk -- skipped"); continue
        h = pd.read_parquet(p)
        assert h["horizon_minutes_active"].all() and h["horizon_levers"].nunique() == 1
        lab = lab_all[(lab_all["season"] == season) & (lab_all["is_double_gw"] == 0)] \
            .set_index(["GW", "element"]).rename_axis(["gw", "element"])
        # step-0 reproduction vs the canonical walkforward
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "name", "p_start", "p60", "e_minutes", "n_fixtures"])
        # singles only: on double gameweeks the walkforward's e_minutes is
        # assembly's per-fixture SUM (x2), not the minutes model's output
        w0 = wf[(wf["cutoff"] == wf["gw"]) & (wf["n_fixtures"] == 1)].set_index(["gw", "element"])
        h0 = h[h["horizon_step"] == 0].set_index(["gw", "element"])
        j = w0.join(h0[["p_start", "p60", "e_minutes"]], rsuffix="_h", how="inner")
        d_prob = max((j[c] - j[c + "_h"]).abs().max() for c in ("p_start", "p60"))
        de = (j["e_minutes"] - j["e_minutes_h"]).abs()
        # Known canonical artefact: a duplicated fixture join makes assembly SUM
        # two identical fixture rows for a handful of players (e_minutes exactly
        # 2x the model's, p_start/p60 untouched, n_fixtures still 1). That is a
        # canonical-file defect, not a step-0 movement -- counted and named, not
        # hidden.
        twice = (de > 1e-9) & ((j["e_minutes"] / j["e_minutes_h"].replace(0, np.nan) - 2).abs() < 1e-6)
        other = (de > 1e-9) & ~twice
        verdict = "UNTOUCHED" if (d_prob < 1e-9 and not other.any()) else "STEP 0 MOVED -- FAIL"
        print(f"================ {season} ================  step-0 rows {len(h0):,}; canonical single rows {len(w0):,} "
              f"(joined {len(j):,}); max |diff| p_start/p60 = {d_prob:.2e}; e_minutes rows differing: "
              f"{int(twice.sum())} exactly-2x canonical duplication artefact"
              + (f" ({', '.join(sorted(set(j.loc[twice, 'name'])))})" if twice.any() else "")
              + f", {int(other.sum())} other -> {verdict}")
        # fresh = step 0 of the target's own cutoff (from the hmin file itself; identical to canonical)
        fresh = h0
        step_rows = h.set_index(["gw", "element"])
        print(f"  {'k':>2s} {'n':>6s} | {'MAE stale':>9s} {'MAE new':>8s} {'MAE fresh':>9s} {'gap closed':>10s} | "
              f"{'rho st/new/fr':>17s} | {'Brier start st/new/fr':>24s} | {'AUC start st/new/fr':>22s} | {'AUC play st/new/fr':>21s} | {'AUC 60 st/new/fr':>19s}")
        for k in range(1, 6):
            new = step_rows[step_rows["horizon_step"] == k]
            # stale: the cutoff's step-0 frame applied to gw = cutoff + k
            st = h0.reset_index().copy(); st["gw"] = st["gw"] + k
            st = st.set_index(["gw", "element"])
            common = new.index.intersection(st.index).intersection(fresh.index).intersection(lab.index)
            ms = score(st.loc[common], lab.loc[common]); mn = score(new.loc[common], lab.loc[common]); mf = score(fresh.loc[common], lab.loc[common])
            gap = (ms["mae"] - mn["mae"]) / (ms["mae"] - mf["mae"]) if ms["mae"] != mf["mae"] else np.nan
            print(f"  {k:2d} {len(common):6,d} | {ms['mae']:9.2f} {mn['mae']:8.2f} {mf['mae']:9.2f} {gap:10.0%} | "
                  f"{ms['rho']:.3f}/{mn['rho']:.3f}/{mf['rho']:.3f} | {ms['brier_start']:.4f}/{mn['brier_start']:.4f}/{mf['brier_start']:.4f} | "
                  f"{ms['auc_start']:.3f}/{mn['auc_start']:.3f}/{mf['auc_start']:.3f} | {ms['auc_play']:.3f}/{mn['auc_play']:.3f}/{mf['auc_play']:.3f} | "
                  f"{ms['auc_60']:.3f}/{mn['auc_60']:.3f}/{mf['auc_60']:.3f}")
            pooled[k].append(dict(season=season, gap=gap, ms=ms, mn=mn, mf=mf))
            gap_rmse = (ms["rmse"] - mn["rmse"]) / (ms["rmse"] - mf["rmse"]) if ms["rmse"] != mf["rmse"] else np.nan
            print(f"       RMSE st/new/fr {ms['rmse']:.2f}/{mn['rmse']:.2f}/{mf['rmse']:.2f} (gap closed {gap_rmse:.0%}); "
                  f"bias st/new/fr {ms['bias']:+.2f}/{mn['bias']:+.2f}/{mf['bias']:+.2f}; "
                  f"MAE by outcome band [0 | 1-59 | 60+] (share {ms['share_band']['0']:.0%}|{ms['share_band']['1-59']:.0%}|{ms['share_band']['60+']:.0%}): "
                  f"stale {ms['mae_band']['0']:.1f}|{ms['mae_band']['1-59']:.1f}|{ms['mae_band']['60+']:.1f}  "
                  f"new {mn['mae_band']['0']:.1f}|{mn['mae_band']['1-59']:.1f}|{mn['mae_band']['60+']:.1f}  "
                  f"fresh {mf['mae_band']['0']:.1f}|{mf['mae_band']['1-59']:.1f}|{mf['mae_band']['60+']:.1f}")
        # flip rate: same player-week seen from its 6 cutoffs -- new vs today's
        piv_new = h.pivot_table(index=["gw", "element"], columns="horizon_step", values="e_minutes").dropna()
        st_pv = {k: h0.reset_index().assign(gw=lambda d, k=k: d["gw"] + k).set_index(["gw", "element"])["e_minutes"] for k in range(1, 6)}
        piv_old = pd.concat([h0["e_minutes"].rename(0)] + [st_pv[k].rename(k) for k in range(1, 6)], axis=1).dropna()
        piv_old = piv_old.loc[piv_old.index.intersection(piv_new.index)]; piv_new = piv_new.loc[piv_old.index]

        def flip(pv):
            hi = pv[[1, 2, 3, 4, 5]].max(axis=1); lo = pv[[1, 2, 3, 4, 5]].min(axis=1)
            return float((((pv[0] < 15) & (hi >= 60)) | ((pv[0] >= 60) & (lo < 15))).mean())
        print(f"  flip rate (step 0 vs any of 1-5 across 15/60): today {flip(piv_old):.1%} -> new {flip(piv_new):.1%} "
              f"({'OK' if flip(piv_new) <= flip(piv_old) + 1e-9 else 'ABOVE TODAY -- FAIL'}); n={len(piv_new):,}")
        print()
    print("POOLED gap closed (mean over seasons) by step: "
          + ", ".join(f"k={k}: {np.mean([r['gap'] for r in v]):.0%}" for k, v in pooled.items() if v))
    print("Framing: component endpoints on singles, common population per step; no season totals. "
          "Step 0 must be untouched; flip rate must not rise; a lever that fails stops the build.")


if __name__ == "__main__":
    main()
