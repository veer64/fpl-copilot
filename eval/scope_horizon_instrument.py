"""Per-horizon-step component endpoints for minutes on the canonical walkforwards (E[min] MAE and Spearman; P(play)/P(60+)/P(start) Brier and AUC at steps 0-5 on a common population), the frozen-across-steps check, a cross-step consistency measure (sd, range, flip rate), and a degradation ladder (truth / fresh / stale-k / shrunk / shuffled) proving the endpoints separate. Result of record: Logs/horizon_minutes_scoping_log.md section 2. Read-only; no model."""
# Task 2: per-horizon-step component endpoints for minutes, a cross-step
# consistency measure, and a degradation ladder that must separate. Read-only.
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, rankdata

REPO = Path(__file__).resolve().parent.parent  # repo root; rescued 2026-08-24 from a hardcoded absolute path
SEASONS = ["2023-24", "2024-25", "2025-26"]
rng = np.random.default_rng(20260824)


def auc(y, p):
    y = np.asarray(y, bool); p = np.asarray(p, float)
    if y.all() or (~y).all():
        return np.nan
    r = rankdata(p)
    return (r[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum())


def brier(y, p):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def metrics(pred_min, true_min, p_play, p60, p_start, starts):
    """Probability columns are NaN on 2-4% of rows at steps 1-5 (players
    without a minutes-model row at that cutoff); those rows are dropped per
    metric, and the drop is reported by the caller."""
    played = true_min > 0; sixty = true_min >= 60
    out = dict(mae=float(np.abs(pred_min - true_min).mean()),
               rho=float(spearmanr(pred_min, true_min).statistic))
    ok = ~np.isnan(p_play)
    out["brier_play"] = brier(played[ok], p_play[ok]); out["auc_play"] = auc(played[ok], p_play[ok])
    ok = ~np.isnan(p60)
    out["brier_60"] = brier(sixty[ok], p60[ok]); out["auc_60"] = auc(sixty[ok], p60[ok])
    ok = ~np.isnan(starts) & ~np.isnan(p_start)
    out["brier_start"] = brier(starts[ok] == 1, p_start[ok]); out["auc_start"] = auc(starts[ok] == 1, p_start[ok])
    out["n_prob"] = int(ok.sum())
    return out


hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet",
                       columns=["season", "element", "GW", "starts"])
hist["starts"] = pd.to_numeric(hist["starts"], errors="coerce")
starts_lookup = hist.groupby(["season", "element", "GW"])["starts"].max()

pooled = []
for season in SEASONS:
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "position", "e_minutes", "minutes",
                                  "p_start", "p_play_any", "p_60plus", "horizon_step", "n_fixtures"])
    wf = wf[wf["n_fixtures"] == 1]          # singles only: minutes/e_minutes on one-match scale
    # common population: (gw, element) present at all six steps
    cnt = wf.groupby(["gw", "element"])["horizon_step"].nunique()
    keep = cnt[cnt == 6].index
    w = wf.set_index(["gw", "element"]).loc[keep].reset_index()
    st = starts_lookup.loc[season]
    w["starts"] = [st.get((e, g), np.nan) for e, g in zip(w["element"], w["gw"])]
    print(f"\n================ {season} ================  common population: {len(keep):,} (gw, element) pairs x 6 steps")

    # --- frozen check: from cutoff c, is e_minutes for c+k identical to c?
    piv = w.pivot_table(index=["cutoff", "element"], columns="horizon_step", values="e_minutes")
    piv = piv.dropna()
    same = {k: float((piv[k] == piv[0]).mean()) for k in range(1, 6)}
    dif = {k: float((piv[k] - piv[0]).abs().mean()) for k in range(1, 6)}
    print("  frozen check (e_minutes at step k vs step 0 from the SAME cutoff): share identical / mean |diff|: "
          + "; ".join(f"k={k}: {same[k]:.0%} / {dif[k]:.1f}" for k in range(1, 6)))

    # --- per-step endpoints
    print(f"  {'step':>4s} {'MAE':>6s} {'rho':>6s} | {'Brier play':>10s} {'AUC play':>8s} | {'Brier 60+':>9s} {'AUC 60+':>7s} | {'Brier start':>11s} {'AUC start':>9s}")
    by_step = {}
    for k, g in w.groupby("horizon_step"):
        m = metrics(g["e_minutes"].values, g["minutes"].values, g["p_play_any"].values,
                    g["p_60plus"].values, g["p_start"].values, g["starts"].values)
        by_step[k] = m
        print(f"  {k:4d} {m['mae']:6.2f} {m['rho']:6.3f} | {m['brier_play']:10.4f} {m['auc_play']:8.3f} | "
              f"{m['brier_60']:9.4f} {m['auc_60']:7.3f} | {m['brier_start']:11.4f} {m['auc_start']:9.3f}")

    # --- consistency across steps for the same player-week
    pw = w.pivot_table(index=["gw", "element"], columns="horizon_step", values="e_minutes")
    sd = pw.std(axis=1); rng_ = pw.max(axis=1) - pw.min(axis=1)
    flip = ((pw[0] < 15) & (pw[[1, 2, 3, 4, 5]].max(axis=1) >= 60)) | \
           ((pw[0] >= 60) & (pw[[1, 2, 3, 4, 5]].min(axis=1) < 15))
    print(f"  cross-step consistency (same player-week seen from 6 cutoffs): mean sd {sd.mean():.2f} min, "
          f"median range {rng_.median():.1f}, share with range >= 60: {(rng_ >= 60).mean():.1%}, "
          f"flip rate (step 0 vs any of 1-5 on opposite sides of 15/60): {flip.mean():.1%}")

    # --- degradation ladder on the common population, per step
    fresh = w[w["horizon_step"] == 0].set_index(["gw", "element"])
    print("  ladder (MAE / rho / Brier-play / AUC-play), same rows at every rung:")
    ladder_rows = []
    for k in range(0, 6):
        g = w[w["horizon_step"] == k].set_index(["gw", "element"]).loc[fresh.index]
        true_min = g["minutes"].values; played = true_min > 0
        variants = {
            "truth": (true_min.astype(float), played.astype(float)),
            "fresh (step 0 for this gw)": (fresh["e_minutes"].values, fresh["p_play_any"].values),
            f"stale (step {k} as built)": (g["e_minutes"].values, g["p_play_any"].values),
        }
        posmean = fresh.groupby("position")["e_minutes"].transform("mean").values
        variants["shrunk 75% to position mean"] = (0.25 * fresh["e_minutes"].values + 0.75 * posmean,
                                                   0.25 * fresh["p_play_any"].values + 0.75 * fresh["p_play_any"].mean())
        idx = np.arange(len(fresh))
        perm = fresh.groupby(["gw", "position"]).cumcount().values * 0  # placeholder
        shuf_min = fresh["e_minutes"].values.copy(); shuf_p = fresh["p_play_any"].values.copy()
        for _, ix in fresh.reset_index().groupby(["gw", "position"]).indices.items():
            pr = rng.permutation(ix); shuf_min[ix] = shuf_min[pr]; shuf_p[ix] = shuf_p[pr]
        variants["shuffled within (gw, position)"] = (shuf_min, shuf_p)
        for name, (pm, pp) in variants.items():
            mae = float(np.abs(pm - true_min).mean()); rho = float(spearmanr(pm, true_min).statistic)
            b = brier(played, np.clip(pp, 0, 1)); a = auc(played, pp)
            ladder_rows.append((k, name, mae, rho, b, a))
    lad = pd.DataFrame(ladder_rows, columns=["k", "variant", "mae", "rho", "brier", "auc"])
    for k in (1, 3, 5):
        print(f"    step {k}:")
        for _, r in lad[lad["k"] == k].iterrows():
            print(f"      {r['variant']:34s} MAE {r['mae']:6.2f}  rho {r['rho']:6.3f}  Brier {r['brier']:.4f}  AUC {r['auc']:.3f}")
    # separation: fresh vs stale gap per k
    gap = {k: (lad[(lad.k == k) & (lad.variant.str.startswith("stale"))]["mae"].iloc[0]
               - lad[(lad.k == k) & (lad.variant.str.startswith("fresh"))]["mae"].iloc[0]) for k in range(1, 6)}
    print("  fresh-vs-stale MAE gap by step (what a horizon model has to close): "
          + ", ".join(f"k={k}: {v:+.2f}" for k, v in gap.items()))
    pooled.append((season, by_step, gap))
