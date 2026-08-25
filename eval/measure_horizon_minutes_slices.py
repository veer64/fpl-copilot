"""Slices the lever-1 acceptance test (eval/measure_horizon_minutes.py) on partitions that were KNOWABLE AT THE CUTOFF -- the stale p_start band (>=0.75 likely starter / 0.25-0.75 uncertain / <0.25 written off), squad relevance (top 30 by the incumbent's own step-k e_points within the target gameweek), and position -- and reports stale / new / fresh with MAE, RMSE, bias, Spearman, Brier and AUC for P(start)/P(play)/P(60+), gap closed under MAE and RMSE, the outcome-band decomposition and the flip rate per slice, to locate where MAE and RMSE disagree. Never slices on the realised outcome (that conditions on the answer and flatters the over-confident stale frame). Result of record: Logs/horizon_minutes_log.md section 3. Measurement only; no rebuild, no simulation.

Usage: uv run python eval/measure_horizon_minutes_slices.py --levers refit [--append-log]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))
import measure_horizon_minutes as base  # noqa: E402  (score, labels, SEASONS)

BANDS = [("likely starter (stale p_start >= 0.75)", lambda p: p >= 0.75),
         ("uncertain (0.25 <= stale p_start < 0.75)", lambda p: (p >= 0.25) & (p < 0.75)),
         ("written off (stale p_start < 0.25)", lambda p: p < 0.25)]
POS = ["GK", "DEF", "MID", "FWD"]
TOP = 30


def gap(ms, mn, mf, key):
    d = ms[key] - mf[key]
    return (ms[key] - mn[key]) / d if abs(d) > 1e-12 else np.nan


def row_md(k, n, ms, mn, mf):
    b = lambda d, key: d["mae_band"][key]  # noqa: E731
    return (f"| {k} | {n:,} | {ms['mae']:.2f} / {mn['mae']:.2f} / {mf['mae']:.2f} | **{gap(ms, mn, mf, 'mae'):+.0%}** | "
            f"{ms['rmse']:.2f} / {mn['rmse']:.2f} / {mf['rmse']:.2f} | **{gap(ms, mn, mf, 'rmse'):+.0%}** | "
            f"{ms['bias']:+.1f} / {mn['bias']:+.1f} | {ms['rho']:.3f} / {mn['rho']:.3f} / {mf['rho']:.3f} | "
            f"{ms['brier_start']:.4f} / {mn['brier_start']:.4f} / {mf['brier_start']:.4f} | "
            f"{ms['auc_start']:.3f} / {mn['auc_start']:.3f} / {mf['auc_start']:.3f} | "
            f"{ms['auc_play']:.3f} / {mn['auc_play']:.3f} | {ms['auc_60']:.3f} / {mn['auc_60']:.3f} | "
            f"{ms['share_band']['0']:.0%} / {ms['share_band']['1-59']:.0%} / {ms['share_band']['60+']:.0%} | "
            f"{b(ms, '0'):.1f}→{b(mn, '0'):.1f} / {b(ms, '1-59'):.1f}→{b(mn, '1-59'):.1f} / {b(ms, '60+'):.1f}→{b(mn, '60+'):.1f} |")


HEAD = ("| k | n | MAE st/new/fr | gap MAE | RMSE st/new/fr | gap RMSE | bias st/new | Spearman st/new/fr | "
        "Brier(start) st/new/fr | AUC(start) st/new/fr | AUC(play) st/new | AUC(60+) st/new | outcome share 0/1-59/60+ | "
        "band MAE st→new 0 / 1-59 / 60+ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def flip_rates(h, h0, members):
    """Flip rate (step 0 vs any of 1-5 across 15/60 on e_minutes) for today's
    copied frame and the new model, restricted to the member (gw, element)s."""
    piv_new = h.pivot_table(index=["gw", "element"], columns="horizon_step", values="e_minutes").dropna()
    parts = [h0["e_minutes"].rename(0)]
    for k in range(1, 6):
        s = h0.reset_index(); s["gw"] = s["gw"] + k
        parts.append(s.set_index(["gw", "element"])["e_minutes"].rename(k))
    piv_old = pd.concat(parts, axis=1).dropna()
    idx = piv_old.index.intersection(piv_new.index).intersection(members)
    piv_old, piv_new = piv_old.loc[idx], piv_new.loc[idx]

    def flip(pv):
        hi = pv[[1, 2, 3, 4, 5]].max(axis=1); lo = pv[[1, 2, 3, 4, 5]].min(axis=1)
        return float((((pv[0] < 15) & (hi >= 60)) | ((pv[0] >= 60) & (lo < 15))).mean())
    return len(idx), flip(piv_old), flip(piv_new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levers", default="refit")
    ap.add_argument("--append-log", action="store_true")
    a = ap.parse_args()
    lab_all = base.labels()
    md = []
    md.append("## 3. Lever 1 sliced on cutoff-knowable partitions (2026-08-24; measurement only, no rebuild)\n")
    md.append("Why NOT slice on realised minutes: conditioning on the outcome flatters the "
              "stale frame, which is over-confident exactly on the players who turned out to "
              "start, and it removes the failure mode that matters most (85 minutes predicted, "
              "0 played -- the Gvardiol case). Every partition below was knowable at the cutoff: "
              "the STALE p_start band (the incumbent's own view, so both arms are scored on the "
              "same rows), squad relevance = the top 30 by the incumbent's step-k e_points "
              "within the target gameweek (ranked over every walkforward row at that cutoff, "
              "then intersected with the singles population), and position. Common population "
              "per slice and step; st = stale, new = step-k refit, fr = fresh. Gap closed = "
              "(st - new)/(st - fr). Flip-rate membership uses the k=1 stale view.\n")
    pooled = {}   # (slice, k) -> list of (gapMAE, gapRMSE)
    rho_rows = []  # (season, slice, k, n, rho_stale, rho_new, rho_fresh)
    for season in base.SEASONS:
        tag = season.replace("-", "_")
        p = REPO / "data" / "horizon" / f"hmin_{tag}_{a.levers.replace(',', '+')}.parquet"
        if not p.exists():
            print(f"{season}: {p.name} missing"); continue
        h = pd.read_parquet(p)
        lab = lab_all[(lab_all["season"] == season) & (lab_all["is_double_gw"] == 0)] \
            .set_index(["GW", "element"]).rename_axis(["gw", "element"])
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "e_points"])
        h0 = h[h["horizon_step"] == 0].set_index(["gw", "element"])
        rows = h.set_index(["gw", "element"])
        md.append(f"### {season}\n")
        print(f"\n================ {season} ================")
        slices_k = {}     # k -> {slice name: index}
        frames_k = {}
        for k in range(1, 6):
            new = rows[rows["horizon_step"] == k]
            st = h0.reset_index().copy(); st["gw"] = st["gw"] + k
            st = st.set_index(["gw", "element"])
            common = new.index.intersection(st.index).intersection(h0.index).intersection(lab.index)
            st, new_c, fr = st.loc[common], new.loc[common], h0.loc[common]
            # relevance: top-30 by the incumbent's own step-k e_points within the gw
            w = wf[wf["gw"] - wf["cutoff"] == k]
            w = w.assign(rk=w.groupby("gw")["e_points"].rank(ascending=False, method="first"))
            top = set(map(tuple, w.loc[w["rk"] <= TOP, ["gw", "element"]].astype(int).values))
            sl = {}
            for name, f in BANDS:
                sl[name] = common[f(st["p_start"].values)]
            sl[f"squad-relevant (top {TOP} by stale step-k e_points in gw)"] = pd.MultiIndex.from_tuples(
                [t for t in common if t in top], names=["gw", "element"]) if any(t in top for t in common) else common[:0]
            for pos in POS:
                sl[f"position {pos}"] = common[(new_c["position"] == pos).values]
            slices_k[k] = sl; frames_k[k] = (st, new_c, fr)
        for name in slices_k[1].keys():
            md.append(f"**{name}**\n"); md.append(HEAD)
            print(f"  --- {name} ---")
            for k in range(1, 6):
                idx = slices_k[k][name]
                st, new_c, fr = frames_k[k]
                if len(idx) < 50:
                    md.append(f"| {k} | {len(idx)} | (too few rows) | | | | | | | | | | | |"); continue
                ms, mn, mf = (base.score(x.loc[idx], lab.loc[idx]) for x in (st, new_c, fr))
                md.append(row_md(k, len(idx), ms, mn, mf))
                pooled.setdefault((name, k), []).append((gap(ms, mn, mf, "mae"), gap(ms, mn, mf, "rmse")))
                rho_rows.append((season, name, k, len(idx), ms["rho"], mn["rho"], mf["rho"]))
                print(f"    k={k} n={len(idx):6,d} MAE {ms['mae']:6.2f}/{mn['mae']:6.2f}/{mf['mae']:6.2f} gap {gap(ms, mn, mf, 'mae'):+5.0%} | "
                      f"RMSE {ms['rmse']:6.2f}/{mn['rmse']:6.2f}/{mf['rmse']:6.2f} gap {gap(ms, mn, mf, 'rmse'):+5.0%} | "
                      f"bias {ms['bias']:+5.1f}/{mn['bias']:+5.1f} | AUCstart {ms['auc_start']:.3f}/{mn['auc_start']:.3f} | "
                      f"bands st {ms['mae_band']['0']:.1f}|{ms['mae_band']['1-59']:.1f}|{ms['mae_band']['60+']:.1f} "
                      f"new {mn['mae_band']['0']:.1f}|{mn['mae_band']['1-59']:.1f}|{mn['mae_band']['60+']:.1f} "
                      f"share {ms['share_band']['0']:.0%}|{ms['share_band']['1-59']:.0%}|{ms['share_band']['60+']:.0%}")
            n_f, f_old, f_new = flip_rates(h, h0, slices_k[1][name])
            md.append(f"\nFlip rate in this slice (k=1 membership, n={n_f:,}): today {f_old:.1%} → new {f_new:.1%}.\n")
            print(f"    flip rate: today {f_old:.1%} -> new {f_new:.1%} (n={n_f:,})")
    md.append("### Pooled gap closed (mean over seasons)\n")
    md.append("| slice | k=1 MAE / RMSE | k=2 | k=3 | k=4 | k=5 |\n|---|---|---|---|---|---|")
    names = []
    for (name, k) in pooled:
        if name not in names:
            names.append(name)
    for name in names:
        cells = []
        for k in range(1, 6):
            v = pooled.get((name, k), [])
            cells.append(f"{np.nanmean([x[0] for x in v]):+.0%} / {np.nanmean([x[1] for x in v]):+.0%}" if v else "–")
        md.append(f"| {name} | " + " | ".join(cells) + " |")
    print("\nPOOLED gap closed (MAE / RMSE), mean over seasons:")
    for line in md[-len(names):]:
        print("  " + line)
    # ---- Spearman per slice: the endpoint the optimizer consumes (rank) ----
    sp = ["### Spearman per slice (the rank endpoint the optimizer consumes; added 2026-08-24)\n",
          "Spearman(e_minutes, minutes_capped) stale / new / fresh, and gap closed = "
          "(new - stale)/(fresh - stale). Aggregate rank correlation in this project has "
          "repeatedly measured \"will they play\" rather than \"who plays more\"; the slices "
          "separate the two.\n"]
    rho = pd.DataFrame(rho_rows, columns=["season", "slice", "k", "n", "st", "new", "fr"])
    rho["gap"] = (rho["new"] - rho["st"]) / (rho["fr"] - rho["st"])
    for season, g in rho.groupby("season", sort=False):
        sp.append(f"**{season}**\n")
        sp.append("| slice | k=1 st/new/fr (gap) | k=2 | k=3 | k=4 | k=5 |\n|---|---|---|---|---|---|")
        for name in g["slice"].unique():
            cells = []
            for k in range(1, 6):
                r = g[(g["slice"] == name) & (g["k"] == k)]
                cells.append(f"{r['st'].iloc[0]:.3f}/{r['new'].iloc[0]:.3f}/{r['fr'].iloc[0]:.3f} ({r['gap'].iloc[0]:+.0%})"
                             if len(r) else "–")
            sp.append(f"| {name} | " + " | ".join(cells) + " |")
        sp.append("")
    sp.append("**Pooled (mean over seasons): gap closed on Spearman**\n")
    sp.append("| slice | k=1 | k=2 | k=3 | k=4 | k=5 | mean delta new-stale (k=1..5) |\n|---|---|---|---|---|---|---|")
    for name in rho["slice"].unique():
        g = rho[rho["slice"] == name]
        cells = [f"{g[g['k'] == k]['gap'].mean():+.0%}" for k in range(1, 6)]
        sp.append(f"| {name} | " + " | ".join(cells) + f" | {(g['new'] - g['st']).mean():+.3f} |")
    sp_text = "\n".join(sp) + "\n"
    print("\n" + sp_text)
    text = "\n".join(md) + "\n"
    if a.append_log:
        # idempotent: each block is appended once, keyed on its own heading
        log = REPO / "Logs" / "horizon_minutes_log.md"
        for heading, block in (("## 3. Lever 1 sliced", text),
                               ("### Spearman per slice", sp_text)):
            cur = log.read_text(encoding="utf-8")
            if heading in cur:
                print(f"log already has '{heading}' -- not appended twice")
            else:
                log.write_text(cur.rstrip("\n") + "\n\n" + block, encoding="utf-8")
                print(f"appended '{heading}' to {log}")


if __name__ == "__main__":
    main()
