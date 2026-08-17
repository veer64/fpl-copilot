#!/usr/bin/env python
"""
Gate 1: does availability actually improve the MINUTES model?

Trains the five minutes components with and without the availability feature block
and scores both on the sealed 2025-26 season. If the minutes model does not
improve, nothing downstream can, and the answer is no.

Calibration and discrimination are reported separately on purpose. A feature that
only sharpens the obvious zeros will move Brier and barely move AUC on the rows
where a squad decision is actually made.

Usage:
    uv run python eval/eval_minutes_av.py                 # baseline vs full block
    uv run python eval/eval_minutes_av.py --ablate        # leave-one-out per feature
    uv run python eval/eval_minutes_av.py --importance
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

# Lives in eval/, so the repo root is two levels up -- same convention as
# walkforward.py, which has always sat here.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import availability_features as avf  # noqa: E402
import minutes  # noqa: E402

AV_FEATS = list(avf.FEATURES)


def fit(availability=True, feats=None):
    """feats restricts the block for ablation; the module default is always restored."""
    try:
        avf.FEATURES = list(feats) if feats is not None else list(AV_FEATS)
        minutes.get_minutes(up_to_gw=None, availability=availability)
        return minutes.get_minutes.last_frame
    finally:
        avf.FEATURES = list(AV_FEATS)


def calibration(y, p, bins=10):
    """Reliability summary: mean |predicted - observed| across equal-count bins."""
    q = pd.qcut(pd.Series(p), bins, duplicates="drop", labels=False)
    t = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p), "q": q})
    g = t.groupby("q").agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
    return float((g.pred - g.obs).abs().mul(g.n).sum() / g.n.sum()), g


def score(pf, label):
    out = {"arm": label, "n": len(pf)}

    y, p = pf["starts"].astype(int), pf["p_start"]
    out["p_start_brier"] = brier_score_loss(y, p)
    out["p_start_auc"] = roc_auc_score(y, p)
    out["p_start_logloss"] = log_loss(y, np.clip(p, 1e-9, 1 - 1e-9))
    out["p_start_calib_err"], _ = calibration(y, p)

    st = pf[pf["starts"] == 1]
    y60 = (st["minutes_capped"] >= 60).astype(int)
    out["p60_brier"] = brier_score_loss(y60, st["p60"])
    out["p60_auc"] = roc_auc_score(y60, st["p60"]) if y60.nunique() > 1 else np.nan
    out["p60_calib_err"], _ = calibration(y60, st["p60"])

    err = pf["e_minutes"] - pf["minutes_capped"]
    out["emin_rmse"] = float(np.sqrt((err ** 2).mean()))
    out["emin_mae"] = float(err.abs().mean())
    out["emin_bias"] = float(err.mean())
    out["emin_spearman"] = float(spearmanr(pf["e_minutes"], pf["minutes_capped"]).statistic)
    return out


def subgroups(base_pf, av_pf):
    """Where the improvement lands. The aggregate can only mislead here: 66% of rows
    are unflagged players for whom nothing changed by construction."""
    b = base_pf.set_index(["element", "GW"])
    a = av_pf.set_index(["element", "GW"])
    idx = b.index.intersection(a.index)
    b, a = b.loc[idx], a.loc[idx]

    flagged = a["av_status_code"] > 0
    groups = {
        "all rows": slice(None),
        "unflagged (status a)": a["av_status_code"] == 0,
        "flagged (any)": flagged,
        "  first week flagged": a["av_just_flagged"] == 1,
        "  flagged 2+ weeks": flagged & (a["av_flag_duration"] >= 2),
        "  doubtful (d)": a["av_status_code"] == 1,
        "  injured (i)": a["av_status_code"] == 2,
        "  departed (u)": a["av_status_code"] == 5,
        "just cleared": a["av_just_cleared"] == 1,
    }
    rows = []
    for name, m in groups.items():
        bb, aa = (b, a) if isinstance(m, slice) else (b[m], a[m])
        if len(bb) < 30:
            continue
        y = bb["starts"].astype(int)
        r = {"subset": name, "n": len(bb), "start_rate": round(float(y.mean()), 3)}
        r["brier_base"] = round(brier_score_loss(y, bb["p_start"]), 4)
        r["brier_av"] = round(brier_score_loss(y, aa["p_start"]), 4)
        r["d_brier"] = round(r["brier_av"] - r["brier_base"], 4)
        r["rmse_base"] = round(float(np.sqrt(((bb.e_minutes - bb.minutes_capped) ** 2).mean())), 2)
        r["rmse_av"] = round(float(np.sqrt(((aa.e_minutes - aa.minutes_capped) ** 2).mean())), 2)
        r["d_rmse"] = round(r["rmse_av"] - r["rmse_base"], 2)
        r["emin_base"] = round(float(bb.e_minutes.mean()), 1)
        r["emin_av"] = round(float(aa.e_minutes.mean()), 1)
        r["emin_actual"] = round(float(bb.minutes_capped.mean()), 1)
        rows.append(r)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ablate", action="store_true")
    ap.add_argument("--importance", action="store_true")
    args = ap.parse_args()

    print("fitting baseline (no availability)...", flush=True)
    base_pf = fit(availability=False)
    print("fitting with availability...", flush=True)
    av_pf = fit(availability=True)

    print("\n" + "=" * 100)
    print("MINUTES MODEL, 2025-26 sealed (train: 2022-23..2024-25)")
    print("=" * 100)
    t = pd.DataFrame([score(base_pf, "baseline"), score(av_pf, "availability")])
    delta = t.iloc[1, 2:] - t.iloc[0, 2:]
    t = pd.concat([t, pd.DataFrame([{"arm": "delta", "n": 0, **delta.to_dict()}])])
    print(t.set_index("arm").round(5).T.to_string())
    print("\nlower is better: brier, logloss, calib_err, rmse, mae. "
          "higher is better: auc, spearman.")

    print("\n" + "=" * 100)
    print("WHERE THE CHANGE LANDS")
    print("=" * 100)
    print(subgroups(base_pf, av_pf).to_string(index=False))

    if args.importance:
        print("\n" + "=" * 100)
        print("FEATURE IMPORTANCE (gain), availability features highlighted")
        print("=" * 100)
        for name, (model, cols) in minutes.get_minutes.last_models.items():
            imp = (pd.Series(model.booster_.feature_importance("gain"), index=cols)
                     .sort_values(ascending=False))
            imp = (imp / imp.sum() * 100).round(2)
            print(f"\n{name}  (availability share: "
                  f"{imp[[c for c in cols if c.startswith('av_')]].sum():.1f}%)")
            print(imp.head(12).to_string())

    if args.ablate:
        print("\n" + "=" * 100)
        print("LEAVE-ONE-OUT ABLATION (p_start Brier / e_minutes RMSE)")
        print("=" * 100)
        rows = [{"dropped": "(none - full block)", **{k: score(av_pf, "x")[k]
                 for k in ("p_start_brier", "p60_brier", "emin_rmse")}}]
        for f in AV_FEATS:
            keep = [x for x in AV_FEATS if x != f]
            pf = fit(availability=True, feats=keep)
            s = score(pf, "x")
            rows.append({"dropped": f, **{k: s[k] for k in
                        ("p_start_brier", "p60_brier", "emin_rmse")}})
        d = pd.DataFrame(rows).set_index("dropped").round(5)
        full = d.loc["(none - full block)"]
        for c in d.columns:
            d[f"cost_{c.split('_')[0]}"] = (d[c] - full[c]).round(5)
        print(d.to_string())
        print("\npositive cost = dropping it made things worse = the feature carries signal.")


if __name__ == "__main__":
    main()
