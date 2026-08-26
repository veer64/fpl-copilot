"""Pre-registered measurement of the player-prop feature (Logs/props_prereg.md sections 1-5 + ADDENDUM 1). Candidate: lambda = w * lambda_mkt(m) + (1 - w) * lambda_model at step 0, with lambda_mkt(m) = -ln(1 - p_consensus / m) from data/odds_props/props_consensus_{season}.parquet and lambda_model = the incumbent's own-cutoff e_goals from the walkforward. Population: single-fixture OUTFIELD player-gameweeks in the starter band (own-cutoff e_minutes >= 60) that the market prices, partial doubles excluded (amendments 2 and 3); the incumbent is scored on the same rows. Primary endpoint: Spearman(lambda, realised goals) pooled over the season on the two decision partitions (likely starters p_start >= .75; squad-relevant top 30 by own-cutoff e_points within the gameweek). Secondary: Brier / log loss on P(>= 1 goal), calibration, MAE / RMSE, outcome-band decomposition, the full starter band and the written-off band (p_start < .25, covered singles, no e_minutes floor -- otherwise empty).

  --tune            2024-25 GW8-38 ONLY. ADDENDUM 2 / amendment 4: m by CALIBRATION on the likely-starter partition
                    (m = mean market P(>=1) / mean realised, market alone, 3 dp), then w by RANK at that m (max MEAN
                    primary Spearman over the two decision partitions, ties -> lower w). Salah guard and leave-one-out
                    re-run the whole procedure; the four section-3 conditions are printed for the tuning season (not
                    evidence); a minutes floor is reported as information only. Reads no 2025-26 file.
  --holdout W M     sealed 2025-26, ONCE: refuses unless the exact line "w = W, m = M.MMM" is present in the LAST
                    PRE-REGISTERED VALUE section of Logs/props_prereg.md (mirrors eval/measure_rate_blend.py).

Usage: uv run python eval/measure_props_endpoint.py --tune
       uv run python eval/measure_props_endpoint.py --holdout 0.75 1.417   # example form only
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
    return f"w = {w:g}, m = {m:.3f}"


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


def calibrate_m(f, parts):
    """AMENDMENT 4: m = mean market P(>=1) / mean realised P(>=1) on the LIKELY-STARTER partition, market alone (w = 1,
    p_adj = p / m so the identity mean(p / m) = realised holds exactly on that partition). Rounded to 3 dp so the
    pre-registered line is reproducible from the command line."""
    mk = parts["likely starters"].to_numpy()
    p = f.loc[mk, "p_mkt_gw"].to_numpy(); y = (f.loc[mk, "goals"].to_numpy() >= 1).astype(float)
    return round(float(p.mean() / y.mean()), 3), float(p.mean()), float(y.mean()), int(mk.sum())


def w_surface(f, parts, m):
    rows = []
    for w in W_GRID:
        s = score(f, w, m, parts)
        rows.append(dict(w=w, m=m, likely=s["likely starters"][0], squad=s["squad-relevant"][0],
                         mean=(s["likely starters"][0] + s["squad-relevant"][0]) / 2, uncertain=s["uncertain"][0],
                         starter=s["full starter band"][0], written=s["written off (no e_minutes floor)"][0]))
    return pd.DataFrame(rows)


def procedure(f):
    """The whole amended tuning procedure on one frame: m by calibration, then w by rank at that m."""
    parts = partitions(f)
    m_cal, p_mean, y_mean, n = calibrate_m(f, parts)
    G = w_surface(f, parts, m_cal)
    return m_cal, p_mean, y_mean, n, G, select(G), parts


def pass_conditions(f, w, m, parts):
    """The four section-3 conditions evaluated on ONE season (here the tuning season -- not evidence)."""
    base = score(f, 0.0, 1.0, parts); cand = score(f, w, m, parts)
    lam0, lam1, g = blend(f, 0.0, 1.0), blend(f, w, m), f["goals"].to_numpy()
    d_like = cand["likely starters"][0] - base["likely starters"][0]; d_sq = cand["squad-relevant"][0] - base["squad-relevant"][0]
    d_wo = cand["written off (no e_minutes floor)"][0] - base["written off (no e_minutes floor)"][0]
    br = {}
    for name in ("likely starters", "squad-relevant"):
        mk = parts[name].to_numpy()
        br[name] = (secondary(lam0[mk], g[mk])["brier"], secondary(lam1[mk], g[mk])["brier"])
    c1 = d_like >= 0.020 and d_sq >= 0.020
    c1b = d_like >= 0 and d_sq >= 0
    c2 = d_wo >= -0.020
    c3 = all(b1 <= b0 for b0, b1 in br.values())
    print(f"  (1) +0.020 on BOTH decision partitions: likely {d_like:+.4f}, squad {d_sq:+.4f} -> {'PASS' if c1 else 'FAIL'}; "
          f"non-negative this season: {'yes' if c1b else 'NO'}")
    print(f"  (2) written-off band not worse by > 0.020: {d_wo:+.4f} -> {'PASS' if c2 else 'FAIL'}")
    print("  (3) Brier not worse on either decision partition: " + "; ".join(f"{k} {b0:.4f}->{b1:.4f}" for k, (b0, b1) in br.items())
          + f" -> {'PASS' if c3 else 'FAIL'}")
    print(f"  overall on this season: {'PASS' if (c1 and c1b and c2 and c3) else 'FAIL'}")
    return dict(d_like=d_like, d_sq=d_sq, d_wo=d_wo, brier=br, c1=c1, c1b=c1b, c2=c2, c3=c3)


def minutes_to_date(season):
    """Minutes played in this season BEFORE the gameweek (known at the cutoff). Whole-season minutes would be a leak."""
    h = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "element", "GW", "minutes"])
    h = h[h["season"] == season].groupby(["element", "GW"])["minutes"].sum().reset_index().sort_values(["element", "GW"])
    h["to_date"] = h.groupby("element")["minutes"].cumsum() - h["minutes"]
    return h.rename(columns={"GW": "gw"})[["element", "gw", "to_date"]]


def floor_information(f, w, m, parts, season):
    """INFORMATION ONLY (not adopted, not pre-registered): rows whose minutes-to-date are under the floor fall back to
    lambda_model; the endpoint is recomputed at the pre-registered pair."""
    td = minutes_to_date(season)
    ff = f.merge(td, on=["element", "gw"], how="left"); ff["to_date"] = ff["to_date"].fillna(0)
    g = ff["goals"].to_numpy(); lam0 = blend(ff, 0.0, 1.0); lam1 = blend(ff, w, m)
    print(f"\n  MINUTES FLOOR -- information only. Floor on minutes played THIS season before the gameweek (cutoff-known); "
          f"rows under the floor use lambda_model. Whole-season minutes (the sanity marker) would be a leak and are not used.")
    print(f"  {'floor':>6s} {'rows->model':>12s} | " + " ".join(f"{k[:14]:>14s}" for k in parts) + "   (delta Spearman vs incumbent)")
    for floor in (0, 90, 180):
        under = (ff["to_date"] < floor).to_numpy()
        lam = np.where(under, lam0, lam1)
        cells = []
        for name, mask in parts.items():
            mk = mask.to_numpy()
            cells.append(spearman(lam[mk], g[mk]) - spearman(lam0[mk], g[mk]))
        print(f"  {floor:6d} {int(under.sum()):12d} | " + " ".join(f"{c:+14.4f}" for c in cells))
    print("  note: at 2025-26 GW1 every player has 0 minutes to date, so any floor > 0 silences the feature for that gameweek "
          "(and 90 for most of GW2); prior-season minutes would be the fix and are a further design choice.")


def tune_main(a):
    season, (lo, hi) = TUNE_SEASON, TUNE_GW
    m_all = load(season)
    n_partial = int(m_all["partial_double"].eq(True).sum())
    f = population(m_all, lo, hi)
    print(f"TUNING on {season} GW{lo}-{hi} only (no 2025-26 file read). Outfield singles in window: {len(f):,}; "
          f"priced {int(f['priced'].sum()):,}. Partial doubles flagged in the season and excluded: {n_partial} (all doubles; the population is singles).")
    print("coverage of each partition by the market (share of partition rows the market prices): " + coverage_line(f))
    f = f[f["priced"]].copy()
    m_cal, p_mean, y_mean, n, G, best, parts = procedure(f)
    print(f"\nAMENDMENT 4 -- m by CALIBRATION on likely starters (market alone): mean market P(>=1) {p_mean:.4f} / mean realised "
          f"{y_mean:.4f} = {p_mean / y_mean:.4f} -> m = {m_cal:.3f} (n = {n}). "
          f"Not on all rows: the written-off band's placeholder prices would drag it up.")
    # post-hoc calibration of the market alone at m_cal, per partition, and reliability deciles on likely starters
    print("  post-hoc calibration of the MARKET ALONE at this m (mean p/m vs realised) by partition:")
    for name, mask in parts.items():
        mk = mask.to_numpy(); p = f.loc[mk, "p_mkt_gw"].to_numpy() / m_cal; y = (f.loc[mk, "goals"].to_numpy() >= 1).mean()
        print(f"    {name:34s} n {int(mk.sum()):5d}  mean p/m {p.mean():.4f}  realised {y:.4f}  ratio {p.mean() / y:.3f}")
    mk = parts["likely starters"].to_numpy()
    r = reliability(-np.log(1 - np.clip(f.loc[mk, 'p_mkt_gw'].to_numpy() / m_cal, 0, 1 - EPS)), f.loc[mk, "goals"].to_numpy())
    print("  reliability deciles, likely starters, market alone at m (is one multiplicative scalar adequate?): n, mean p/m, realised, ratio")
    for d in r.index:
        print(f"    d{d}: n {int(r.loc[d, 'n']):4d}  {r.loc[d, 'pred']:.3f} / {r.loc[d, 'real']:.3f}  ratio {r.loc[d, 'pred'] / max(r.loc[d, 'real'], 1e-9):.2f}")
    print_surface(G, f"FULL w SURFACE at m = {m_cal:.3f} -- pooled Spearman(lambda, goals), {season} GW{lo}-{hi}; "
                     f"n likely starters {int(parts['likely starters'].sum())}, n squad-relevant {int(parts['squad-relevant'].sum())}")
    ties = G[np.isclose(G["mean"], best["mean"], atol=1e-9)]
    print(f"\nSELECTED (max MEAN over the two decision partitions; ties -> lower w): {pair_line(best['w'], best['m'])}  mean {best['mean']:.4f}"
          + (f"  [{len(ties)} exact ties]" if len(ties) > 1 else ""))
    inc = G[G["w"] == 0].iloc[0]
    g75 = G[np.isclose(G["w"], 0.75)].iloc[0]; g100 = G[np.isclose(G["w"], 1.0)].iloc[0]
    print(f"incumbent: likely {inc['likely']:.4f}, squad {inc['squad']:.4f}, mean {inc['mean']:.4f}; selected pair delta: "
          f"likely {best['likely'] - inc['likely']:+.4f}, squad {best['squad'] - inc['squad']:+.4f}")
    print(f"w = 0.75 vs w = 1.0 gap in MEAN at this m: {g75['mean'] - g100['mean']:+.4f} (was +0.0009 at m = 1.00)")
    # ---- Salah guard: the WHOLE procedure (m and w) without him
    sal = f[f["name"].str.contains("Salah", case=False)]["element"].unique(); assert len(sal) == 1
    fx = f[f["element"] != sal[0]].copy()
    mx, _, _, _, Gx, bx, _ = procedure(fx)
    print_surface(Gx, f"ROBUSTNESS -- whole procedure without Salah (element {sal[0]}, {int((f['element'] == sal[0]).sum())} rows): m = {mx:.3f}")
    same = bool(np.isclose(bx["w"], best["w"]))
    print(f"  argmax without Salah: {pair_line(bx['w'], bx['m'])} -> " + ("SAME w as the full surface" if same else f"DIFFERENT w from the full-surface {pair_line(best['w'], best['m'])}"))
    # ---- concentration + leave-one-out of the whole procedure
    con = contributions(f, float(best["w"]), float(best["m"]), parts)
    loo = []
    for name, c in con.items():
        print(f"\n  {name}: rho(candidate) {c['rho']:.4f}, delta vs incumbent {c['delta']:+.4f} -- per-player shares (sum to the statistic)")
        print("    top 5 by contribution to rho(candidate):")
        for r_ in c["top_rho"].itertuples():
            print(f"      {r_.name:32s} rows {r_.rows:3d} goals {int(r_.goals):2d}  rho share {r_.rho_share:+.4f} ({r_.rho_share / c['rho']:+.1%})  delta share {r_.delta_share:+.4f}")
        print("    top 5 by |contribution to delta rho|:")
        for r_ in c["top_delta"].itertuples():
            print(f"      {r_.name:32s} rows {r_.rows:3d} goals {int(r_.goals):2d}  delta share {r_.delta_share:+.4f}  rho share {r_.rho_share:+.4f}")
        for r_ in pd.concat([c["top_rho"], c["top_delta"]]).drop_duplicates("element").itertuples():
            fl = f[f["element"] != r_.element].copy(); ml, _, _, _, _, bl, _ = procedure(fl)
            loo.append((name, r_.name, ml, pair_line(bl["w"], bl["m"]), bool(np.isclose(bl["w"], best["w"]))))
    wissa = f[f["name"].str.contains("Wissa", case=False)]["element"].unique()
    if len(wissa) == 1 and not any(who.lower().find("wissa") >= 0 for _, who, _, _, _ in loo):
        fl = f[f["element"] != wissa[0]].copy(); ml, _, _, _, _, bl, _ = procedure(fl)
        loo.append(("(named last time)", "Yoane Wissa", ml, pair_line(bl["w"], bl["m"]), bool(np.isclose(bl["w"], best["w"]))))
    print("\n  leave-one-out of the WHOLE procedure (m recalibrated, w re-selected) for every player listed above:")
    for name, who, ml, pr, ok in loo:
        print(f"    drop {who:32s} ({name:17s}) -> m {ml:.3f}, {pr}  {'same w' if ok else 'CHANGES w'}")
    # ---- the four pass conditions on the tuning season (not evidence)
    print(f"\nPASS CONDITIONS (section 3, UNCHANGED) evaluated on {season} -- the tuning season, NOT evidence:")
    pc = pass_conditions(f, float(best["w"]), float(best["m"]), parts)
    report_pair(f, float(best["w"]), float(best["m"]), f"{season} tuning season (NOT evidence)", n_partial)
    floor_information(f, float(best["w"]), float(best["m"]), parts, season)
    if same:
        print(f"\nSalah guard passed. Write '{pair_line(best['w'], best['m'])}' into a NEW dated '## PRE-REGISTERED VALUE' section of "
              "Logs/props_prereg.md (the guard reads the LAST such section) BEFORE running --holdout. 2025-26 has not been read.")
    else:
        print("\nSALAH GUARD TRIPPED: w changes when Salah is dropped. Do NOT write a PRE-REGISTERED VALUE until discussed.")


def coverage_line(f):
    parts = partitions(f)
    return "; ".join(f"{name} {f.loc[mask, 'priced'].mean():.1%} of {int(mask.sum())}" for name, mask in parts.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--holdout", nargs=2, type=float, metavar=("W", "M"))
    a = ap.parse_args()
    if a.tune:
        tune_main(a)
    elif a.holdout is not None:
        w, mm = a.holdout
        text = PREREG.read_text(encoding="utf-8") if PREREG.exists() else ""
        heads = list(re.finditer(r"^## PRE-REGISTERED VALUE", text, flags=re.M))   # real headings only; the LAST one governs
        if not heads or pair_line(w, mm) not in text[heads[-1].start():]:
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
