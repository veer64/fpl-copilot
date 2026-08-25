"""Pre-registered measurement of the player-prop feature (Logs/props_prereg.md sections 1-5 + ADDENDUM 1). Candidate: lambda = w * lambda_mkt(m) + (1 - w) * lambda_model at step 0, with lambda_mkt(m) = -ln(1 - p_consensus / m) from data/odds_props/props_consensus_{season}.parquet and lambda_model = the incumbent's own-cutoff e_goals from the walkforward. Population: single-fixture OUTFIELD player-gameweeks in the starter band (own-cutoff e_minutes >= 60) that the market prices, partial doubles excluded (amendments 2 and 3); the incumbent is scored on the same rows. Primary endpoint: Spearman(lambda, realised goals) pooled over the season on the two decision partitions (likely starters p_start >= .75; squad-relevant top 30 by own-cutoff e_points within the gameweek). Secondary: Brier / log loss on P(>= 1 goal), calibration, MAE / RMSE, outcome-band decomposition, the full starter band and the written-off band (p_start < .25, covered singles, no e_minutes floor -- otherwise empty).

  --tune            2024-25 GW8-38 ONLY: the full w x m grid, selection = max MEAN primary Spearman over the two
                    decision partitions, ties -> lower w then lower m. Reads no 2025-26 file.
  --holdout W M     sealed 2025-26, ONCE: refuses unless the exact line "w = W, m = M" is already present in the
                    PRE-REGISTERED VALUE section of Logs/props_prereg.md (mirrors eval/measure_rate_blend.py).

Usage: uv run python eval/measure_props_endpoint.py --tune
       uv run python eval/measure_props_endpoint.py --holdout 0.5 1.10
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
PREREG = REPO / "Logs" / "props_prereg.md"
W_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
M_GRID = [1.00, 1.10, 1.20, 1.30]
TUNE_SEASON, TUNE_GW = "2024-25", (8, 38)
HOLDOUT_SEASON = "2025-26"
TOP = 30
EPS = 1e-6


def pair_line(w, m):
    return f"w = {w:g}, m = {m:.2f}"


def load(season):
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "name", "position", "team", "e_points", "p_start",
                                  "e_minutes", "e_goals", "n_fixtures"])
    own = wf[wf["cutoff"] == wf["gw"]].copy()
    own["rk"] = own.groupby("gw")["e_points"].rank(ascending=False, method="first")   # on the incumbent's full view
    cons = pd.read_parquet(REPO / "data" / "odds_props" / f"props_consensus_{season}.parquet")
    assert (cons["method"] == "addendum1_shared_set").all(), "consensus file is not the ADDENDUM 1 build"
    m = own.merge(cons[["gw", "element", "p_mkt_gw", "n_fixtures_priced", "partial_double", "n_books_mean"]],
                  on=["gw", "element"], how="left")
    hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "element", "GW", "goals_scored"])
    hist = hist[hist["season"] == season].groupby(["element", "GW"])["goals_scored"].sum().rename("goals").reset_index()
    m = m.merge(hist.rename(columns={"GW": "gw"}), on=["element", "gw"], how="left")
    m["goals"] = m["goals"].fillna(0).astype(int)
    return m


def population(m, gw_lo, gw_hi):
    """Rows in the priced window, outfield singles, partial doubles excluded; `priced` marks the common population."""
    f = m[(m["gw"] >= gw_lo) & (m["gw"] <= gw_hi) & (m["n_fixtures"] == 1) & (m["position"] != "GK")].copy()
    n_partial = int(f["partial_double"].eq(True).sum())   # singles cannot be partial; asserted below
    assert n_partial == 0
    f["priced"] = f["p_mkt_gw"].notna()
    return f


def blend(f, w, m):
    p_adj = np.clip(f["p_mkt_gw"].to_numpy() / m, 0.0, 1.0 - EPS)
    lam_mkt = -np.log(1.0 - p_adj)
    return w * lam_mkt + (1.0 - w) * f["e_goals"].to_numpy()


def spearman(x, y):
    return float(pd.Series(x).corr(pd.Series(y), method="spearman"))


def partitions(f):
    starter = f["e_minutes"] >= 60
    return {"likely starters": starter & (f["p_start"] >= 0.75),
            "squad-relevant": starter & (f["rk"] <= TOP),
            "uncertain": starter & (f["p_start"] >= 0.25) & (f["p_start"] < 0.75),
            "full starter band": starter,
            "written off (no e_minutes floor)": f["p_start"] < 0.25}


def secondary(lam, goals):
    p1 = 1.0 - np.exp(-lam); y = (goals >= 1).astype(float)
    pc = np.clip(p1, EPS, 1 - EPS)
    out = dict(brier=float(np.mean((p1 - y) ** 2)), logloss=float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))),
               mean_pred=float(np.mean(p1)), realised=float(np.mean(y)), mae=float(np.mean(np.abs(lam - goals))),
               rmse=float(np.sqrt(np.mean((lam - goals) ** 2))))
    for band, mask in (("0", goals == 0), ("1", goals == 1), ("2+", goals >= 2)):
        out[f"mae_{band}"] = float(np.mean(np.abs(lam[mask] - goals[mask]))) if mask.any() else float("nan")
    return out


def reliability(lam, goals, k=10):
    p1 = 1.0 - np.exp(-lam); y = (goals >= 1).astype(float)
    d = pd.DataFrame(dict(p=p1, y=y))
    d["dec"] = pd.qcut(d["p"].rank(method="first"), k, labels=False)
    return d.groupby("dec").agg(n=("y", "size"), pred=("p", "mean"), real=("y", "mean"))


def score(f, w, m, parts):
    lam = blend(f, w, m); g = f["goals"].to_numpy()
    return {name: (spearman(lam[mask.to_numpy()], g[mask.to_numpy()]), int(mask.sum())) for name, mask in parts.items()}


def report_pair(f, w, m, label, excluded_partial):
    parts = partitions(f)
    print(f"\n--- {label}: {pair_line(w, m)} vs incumbent (w = 0) on the common population; partial doubles excluded: {excluded_partial} ---")
    base = score(f, 0.0, 1.0, parts); cand = score(f, w, m, parts)
    print(f"  {'partition':34s} {'n':>6s}  {'Spearman inc':>13s} {'Spearman cand':>14s} {'delta':>8s}")
    for name in parts:
        print(f"  {name:34s} {cand[name][1]:6d}  {base[name][0]:13.4f} {cand[name][0]:14.4f} {cand[name][0] - base[name][0]:+8.4f}")
    lam0 = blend(f, 0.0, 1.0); lam1 = blend(f, w, m); g = f["goals"].to_numpy()
    print("  secondary (incumbent -> candidate):")
    for name, mask in parts.items():
        mk = mask.to_numpy()
        if mk.sum() < 30:
            continue
        s0, s1 = secondary(lam0[mk], g[mk]), secondary(lam1[mk], g[mk])
        print(f"    {name:34s} Brier {s0['brier']:.4f}->{s1['brier']:.4f}  logloss {s0['logloss']:.4f}->{s1['logloss']:.4f}  "
              f"mean pred/realised {s0['mean_pred']:.3f}/{s0['realised']:.3f}->{s1['mean_pred']:.3f}/{s1['realised']:.3f}  "
              f"MAE {s0['mae']:.4f}->{s1['mae']:.4f}  RMSE {s0['rmse']:.4f}->{s1['rmse']:.4f}  "
              f"MAE by outcome 0/1/2+ {s0['mae_0']:.3f}/{s0['mae_1']:.3f}/{s0['mae_2+']:.3f} -> {s1['mae_0']:.3f}/{s1['mae_1']:.3f}/{s1['mae_2+']:.3f}")
    mk = parts["full starter band"].to_numpy()
    print("  reliability deciles, full starter band (incumbent | candidate): n, mean predicted P(>=1), realised")
    r0, r1 = reliability(lam0[mk], g[mk]), reliability(lam1[mk], g[mk])
    for d in r0.index:
        print(f"    d{d}: n {int(r0.loc[d, 'n']):4d}  {r0.loc[d, 'pred']:.3f}/{r0.loc[d, 'real']:.3f} | {r1.loc[d, 'pred']:.3f}/{r1.loc[d, 'real']:.3f}")
    return base, cand


def surface(f, parts):
    grid = []
    for w in W_GRID:
        for mm in M_GRID:
            s = score(f, w, mm, parts)
            grid.append(dict(w=w, m=mm, likely=s["likely starters"][0], squad=s["squad-relevant"][0],
                             mean=(s["likely starters"][0] + s["squad-relevant"][0]) / 2,
                             uncertain=s["uncertain"][0], starter=s["full starter band"][0],
                             written=s["written off (no e_minutes floor)"][0]))
    return pd.DataFrame(grid)


def select(G):
    """Pre-registered rule: max MEAN over the two decision partitions; ties -> lower w, then lower m."""
    return G.sort_values(["mean", "w", "m"], ascending=[False, True, True]).iloc[0]


def print_surface(G, title):
    print(f"\n{title}")
    print(f"  {'w':>5s} {'m':>5s} | {'likely':>8s} {'squad':>8s} {'MEAN':>8s} | {'uncertain':>9s} {'starter':>8s} {'writtenoff':>10s}")
    for g in G.itertuples():
        print(f"  {g.w:5.2f} {g.m:5.2f} | {g.likely:8.4f} {g.squad:8.4f} {g.mean:8.4f} | {g.uncertain:9.4f} {g.starter:8.4f} {g.written:10.4f}")


def rank_terms(x, y):
    """Per-row terms of Pearson-on-ranks (= Spearman with average ties, as pandas computes it); they sum to rho."""
    rx = pd.Series(x).rank(method="average").to_numpy(); ry = pd.Series(y).rank(method="average").to_numpy()
    cx, cy = rx - rx.mean(), ry - ry.mean()
    return cx * cy / np.sqrt((cx ** 2).sum() * (cy ** 2).sum())


def contributions(f, w, m, parts, k=5):
    """Top-k players by summed contribution to rho(candidate) and to delta rho (candidate - incumbent), per decision partition."""
    out = {}
    lam0, lam1, g = blend(f, 0.0, 1.0), blend(f, w, m), f["goals"].to_numpy()
    for name in ("likely starters", "squad-relevant"):
        mk = parts[name].to_numpy()
        t0, t1 = rank_terms(lam0[mk], g[mk]), rank_terms(lam1[mk], g[mk])
        d = pd.DataFrame(dict(element=f.loc[mk, "element"].to_numpy(), name=f.loc[mk, "name"].to_numpy(),
                              t_cand=t1, t_delta=t1 - t0, goals=g[mk]))
        per = d.groupby(["element", "name"]).agg(rows=("goals", "size"), goals=("goals", "sum"), rho_share=("t_cand", "sum"),
                                                 delta_share=("t_delta", "sum")).reset_index()
        out[name] = dict(rho=float(t1.sum()), delta=float((t1 - t0).sum()),
                         top_rho=per.sort_values("rho_share", ascending=False).head(k),
                         top_delta=per.reindex(per["delta_share"].abs().sort_values(ascending=False).index).head(k))
    return out


def coverage_line(f):
    parts = partitions(f)
    return "; ".join(f"{name} {f.loc[mask, 'priced'].mean():.1%} of {int(mask.sum())}" for name, mask in parts.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--holdout", nargs=2, type=float, metavar=("W", "M"))
    a = ap.parse_args()
    if a.tune:
        season, (lo, hi) = TUNE_SEASON, TUNE_GW
        m = load(season)
        n_partial = int(m["partial_double"].eq(True).sum())
        f = population(m, lo, hi)
        print(f"TUNING on {season} GW{lo}-{hi} only (no 2025-26 file read). Outfield singles in window: {len(f):,}; "
              f"priced {int(f['priced'].sum()):,}. Partial doubles flagged in the season and excluded: {n_partial} (all doubles; the population is singles).")
        print("coverage of each partition by the market (share of partition rows the market prices): " + coverage_line(f))
        f = f[f["priced"]].copy()
        parts = partitions(f)
        G = surface(f, parts)
        print_surface(G, f"FULL GRID -- pooled Spearman(lambda, goals) on the common population, {season} GW{lo}-{hi}; "
                         f"n likely starters {int(parts['likely starters'].sum())}, n squad-relevant {int(parts['squad-relevant'].sum())}")
        best = select(G)
        ties = G[np.isclose(G["mean"], best["mean"], atol=1e-9)]
        print(f"\nSELECTED by the pre-registered rule (max MEAN over the two decision partitions; ties -> lower w, lower m): "
              f"{pair_line(best['w'], best['m'])}  mean {best['mean']:.4f}" + (f"  [{len(ties)} exact ties at this mean]" if len(ties) > 1 else ""))
        inc = G[(G["w"] == 0)].iloc[0]
        print(f"incumbent (w = 0): likely {inc['likely']:.4f}, squad {inc['squad']:.4f}, mean {inc['mean']:.4f}; "
              f"delta of the selected pair: likely {best['likely'] - inc['likely']:+.4f}, squad {best['squad'] - inc['squad']:+.4f}")
        # ---- robustness guard (not a change to the selection rule): the surface without Salah
        sal = f[f["name"].str.contains("Salah", case=False)]["element"].unique()
        assert len(sal) == 1, f"Salah element not unique: {sal}"
        fx = f[f["element"] != sal[0]].copy(); px = partitions(fx)
        Gx = surface(fx, px); bx = select(Gx)
        print_surface(Gx, f"ROBUSTNESS -- the same grid with Salah (element {sal[0]}) EXCLUDED; his rows: "
                          f"{int((f['element'] == sal[0]).sum())} (likely {int((parts['likely starters'] & (f['element'] == sal[0])).sum())}, "
                          f"squad {int((parts['squad-relevant'] & (f['element'] == sal[0])).sum())})")
        same = bool(np.isclose(bx["w"], best["w"]) and np.isclose(bx["m"], best["m"]))
        print(f"  argmax without Salah: {pair_line(bx['w'], bx['m'])} mean {bx['mean']:.4f} -> "
              + ("SAME pair as the full surface" if same else f"DIFFERENT from the full-surface pair {pair_line(best['w'], best['m'])}"))
        # ---- concentration: top-5 contributors to rho and to delta rho on each decision partition, plus leave-one-out argmax
        con = contributions(f, float(best["w"]), float(best["m"]), parts)
        loo_flags = []
        for name, c in con.items():
            print(f"\n  {name}: rho(candidate) {c['rho']:.4f}, delta vs incumbent {c['delta']:+.4f} -- per-player shares (sum to the statistic)")
            print("    top 5 by contribution to rho(candidate):")
            for r in c["top_rho"].itertuples():
                print(f"      {r.name:32s} rows {r.rows:3d} goals {int(r.goals):2d}  rho share {r.rho_share:+.4f} ({r.rho_share / c['rho']:+.1%} of rho)  delta share {r.delta_share:+.4f}")
            print("    top 5 by |contribution to delta rho| (candidate - incumbent):")
            for r in c["top_delta"].itertuples():
                print(f"      {r.name:32s} rows {r.rows:3d} goals {int(r.goals):2d}  delta share {r.delta_share:+.4f}  rho share {r.rho_share:+.4f}")
            for r in pd.concat([c["top_rho"], c["top_delta"]]).drop_duplicates("element").itertuples():
                fl = f[f["element"] != r.element].copy(); bl = select(surface(fl, partitions(fl)))
                loo_flags.append((name, r.name, pair_line(bl["w"], bl["m"]), bool(np.isclose(bl["w"], best["w"]) and np.isclose(bl["m"], best["m"]))))
        print("\n  leave-one-out argmax for every player listed above:")
        for name, who, pr, ok in loo_flags:
            print(f"    drop {who:32s} ({name:15s}) -> {pr}  {'same' if ok else 'CHANGES the argmax'}")
        report_pair(f, float(best["w"]), float(best["m"]), f"{season} tuning season (NOT evidence)", n_partial)
        if same:
            print("\nSalah guard passed (argmax unchanged without him). Write the selected pair into a dated '## PRE-REGISTERED VALUE' "
                  f"section of Logs/props_prereg.md as the exact line '{pair_line(best['w'], best['m'])}' BEFORE running --holdout. 2025-26 has not been read.")
        else:
            print("\nSALAH GUARD TRIPPED: the argmax changes when Salah is dropped. Do NOT write a PRE-REGISTERED VALUE until this has been discussed.")
    elif a.holdout is not None:
        w, mm = a.holdout
        text = PREREG.read_text(encoding="utf-8") if PREREG.exists() else ""
        hit = re.search(r"^## PRE-REGISTERED VALUE", text, flags=re.M)     # a real heading, not the section-5 mention in backticks
        if hit is None or pair_line(w, mm) not in text[hit.start():]:
            print(f"REFUSED: the line '{pair_line(w, mm)}' is not present in the PRE-REGISTERED VALUE section of {PREREG}. "
                  "Write it there first (props_prereg.md section 5); the sealed season is run once with the pre-registered pair only.")
            sys.exit(2)
        season = HOLDOUT_SEASON
        m = load(season)
        n_partial = int(m["partial_double"].eq(True).sum())
        f = population(m, 1, 38)
        print(f"SEALED {season}, {pair_line(w, mm)} (pre-registered). Outfield singles: {len(f):,}; priced {int(f['priced'].sum()):,}; "
              f"partial doubles excluded: {n_partial}.")
        print("coverage: " + coverage_line(f))
        f = f[f["priced"]].copy()
        report_pair(f, w, mm, f"SEALED {season}", n_partial)
    else:
        ap.error("--tune or --holdout W M")


if __name__ == "__main__":
    main()
