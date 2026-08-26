"""Pre-registered measurement of the player-prop feature (Logs/props_prereg.md sections 1-5 + ADDENDUM 1). Candidate: lambda = w * lambda_mkt(m) + (1 - w) * lambda_model at step 0, with lambda_mkt(m) = -ln(1 - p_consensus / m) from data/odds_props/props_consensus_{season}.parquet and lambda_model = the incumbent's own-cutoff e_goals from the walkforward. Population: single-fixture OUTFIELD player-gameweeks in the starter band (own-cutoff e_minutes >= 60) that the market prices, partial doubles excluded (amendments 2 and 3); the incumbent is scored on the same rows. Primary endpoint: Spearman(lambda, realised goals) pooled over the season on the two decision partitions (likely starters p_start >= .75; squad-relevant top 30 by own-cutoff e_points within the gameweek). Secondary: Brier / log loss on P(>= 1 goal), calibration, MAE / RMSE, outcome-band decomposition, the full starter band and the written-off band (p_start < .25, covered singles, no e_minutes floor -- otherwise empty).

  --tune            2024-25 GW8-38 ONLY. ADDENDUM 2 / amendment 4: m by CALIBRATION on the likely-starter partition
                    (m = mean market P(>=1) / mean realised, market alone, 3 dp), then w by RANK at that m (max MEAN
                    primary Spearman over the two decision partitions, ties -> lower w). Salah guard and leave-one-out
                    re-run the whole procedure; the four section-3 conditions are printed for the tuning season (not
                    evidence); a minutes floor is reported as information only. Reads no 2025-26 file.
  --holdout W M     sealed 2025-26, ONCE: refuses unless the exact line "w = W, m = M.MMM" is present in the LAST
                    PRE-REGISTERED VALUE section of Logs/props_prereg.md (mirrors eval/measure_rate_blend.py).
  --spec conditional   the conditional-rate specification of Logs/props_conditional_prereg.md: P(scores) = P(appears) x
                    P(scores | appears), P(appears) per book by its verified rule (p_play_any: DraftKings/BetMGM/Bovada
                    and, assigned, FanDuel/1xBet; p_start: BetRivers/MyBookie), from props_consensus_book_{season}.parquet.
                    --tune: m by calibration on the conditioned quantity, w = 0.75 by prior with the pre-stated departure
                    rule, P2 ratio, section-3 conditions, the floor-refit diagnosis, the unverified-book sensitivity and the
                    two uniform diagnostics. --holdout W M: refuses unless "spec = conditional: w = W, m = M.MMM" is in the
                    LAST PRE-REGISTERED VALUE section of the conditional pre-registration (its own guard).

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
                                  "e_minutes", "e_goals", "n_fixtures", "p_play_any", "p_60plus"])
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


# ---------------------------------------------------------------------------------------------------------------
# CONDITIONAL-RATE SPECIFICATION (Logs/props_conditional_prereg.md). P(scores) = P(appears) x P(scores | appears):
# the market supplies the conditional term per book, the minutes model supplies P(appears) per that book's rule,
# the consensus is the equal-weight mean of the conditioned per-book probabilities, m then w exactly as before.
# ---------------------------------------------------------------------------------------------------------------
COND_PREREG = REPO / "Logs" / "props_conditional_prereg.md"
PARTICIPATION_BOOKS = {"draftkings", "betmgm", "bovada"}          # verified: void unless the player takes part
START_BOOKS = {"betrivers", "mybookieag"}                          # verified: void unless the player starts
UNVERIFIED_BOOKS = {"fanduel", "onexbet"}                          # assigned "takes part" unless --assign-unverified start
SUB_FLOOR = 0.30                                                   # squad/assembly.py: p_play_any = p_start + (1 - p_start) * 0.30


def cond_pair_line(w, m):
    return f"spec = conditional: w = {w:g}, m = {m:.3f}"


def load_conditional(season, assign_unverified="participation", mode="per-book", sub_floor=None):
    """Same frame as load(), with p_mkt_gw replaced by the CONDITIONED consensus probability (before m)."""
    base = load(season)
    pb = pd.read_parquet(REPO / "data" / "odds_props" / f"props_consensus_book_{season}.parquet")
    x = pb.merge(base[["gw", "element", "p_start", "p_play_any"]], on=["gw", "element"], how="inner")
    if sub_floor is not None:                                      # DIAGNOSTIC only: refit the flat substitute floor
        x["p_play_any"] = x["p_start"] + (1.0 - x["p_start"]) * sub_floor
    start_set = set(START_BOOKS) | (UNVERIFIED_BOOKS if assign_unverified == "start" else set())
    if mode == "per-book":
        P = np.where(x["book"].isin(start_set), x["p_start"], x["p_play_any"])
    elif mode == "all-p_start":
        P = x["p_start"].to_numpy()
    elif mode == "all-p_play_any":
        P = x["p_play_any"].to_numpy()
    else:
        raise ValueError(mode)
    x["p_cond"] = x["p_adj"] * P
    fixl = x.groupby(["gw", "event_id", "element"])["p_cond"].mean().reset_index()
    gwl = fixl.groupby(["gw", "element"])["p_cond"].agg(lambda s: 1.0 - float(np.prod(1.0 - s.to_numpy()))).reset_index()
    out = base.drop(columns=["p_mkt_gw"]).merge(gwl.rename(columns={"p_cond": "p_mkt_gw"}), on=["gw", "element"], how="left")
    assert out["p_mkt_gw"].notna().sum() == base["p_mkt_gw"].notna().sum(), "conditioned rows != priced rows"
    return out


def written_off_ratio(f, m):
    """P2: written-off band (no e_minutes floor), mean conditioned p / m against realised P(>= 1)."""
    g = f[f["p_start"] < 0.25]
    pred = (g["p_mkt_gw"] / m).mean(); real = (g["goals"] >= 1).mean()
    return pred / real, pred, real, len(g)


def cond_summary(label, f, w, parts):
    """One-line procedure on a frame: m by calibration, ratio, section-3 deltas at (w, m)."""
    m_cal, p_mean, y_mean, n = calibrate_m(f, parts)
    base = score(f, 0.0, 1.0, parts); cand = score(f, w, m_cal, parts)
    r, _, _, _ = written_off_ratio(f, m_cal)
    lam0, lam1, g = blend(f, 0.0, 1.0), blend(f, w, m_cal), f["goals"].to_numpy()
    br = {k: (secondary(lam0[parts[k].to_numpy()], g[parts[k].to_numpy()])["brier"], secondary(lam1[parts[k].to_numpy()], g[parts[k].to_numpy()])["brier"]) for k in ("likely starters", "squad-relevant")}
    d = {k: cand[k][0] - base[k][0] for k in parts}
    c1 = d["likely starters"] >= 0.02 and d["squad-relevant"] >= 0.02; c2 = d["written off (no e_minutes floor)"] >= -0.02
    c3 = all(b1 <= b0 for b0, b1 in br.values())
    print(f"  {label:44s} m {m_cal:.3f} | WO ratio {r:5.2f} | d likely {d['likely starters']:+.4f} squad {d['squad-relevant']:+.4f} "
          f"uncertain {d['uncertain']:+.4f} WO {d['written off (no e_minutes floor)']:+.4f} | (1) {'PASS' if c1 else 'FAIL'} (2) {'PASS' if c2 else 'FAIL'} (3) {'PASS' if c3 else 'FAIL'}")
    return dict(m=m_cal, ratio=r, d=d, c=(c1, c2, c3))


def conditional_main(a):
    season, (lo, hi) = TUNE_SEASON, TUNE_GW
    W_PRIOR = 0.75
    assign = a.assign_unverified
    m_all = load_conditional(season, assign_unverified=assign)
    n_partial = int(m_all["partial_double"].eq(True).sum())
    f = population(m_all, lo, hi)
    print(f"CONDITIONAL SPECIFICATION -- tuning on {season} GW{lo}-{hi} only (no 2025-26 file read). Unverified books (FanDuel, 1xBet) assigned: {assign}. "
          f"Outfield singles in window: {len(f):,}; priced {int(f['priced'].sum()):,}; partial doubles flagged and excluded: {n_partial}.")
    print("coverage: " + coverage_line(f))
    f = f[f["priced"]].copy()
    m_cal, p_mean, y_mean, n, G, best, parts = procedure(f)
    print(f"\nm by CALIBRATION on likely starters, market alone, on the CONDITIONED quantity: mean {p_mean:.4f} / realised {y_mean:.4f} -> m = {m_cal:.3f} (n = {n})")
    print("  post-hoc calibration of the conditioned market alone at this m, by partition (mean p_cond/m vs realised):")
    for name, mask in parts.items():
        mk = mask.to_numpy(); p = f.loc[mk, "p_mkt_gw"].to_numpy() / m_cal; y = (f.loc[mk, "goals"].to_numpy() >= 1).mean()
        print(f"    {name:34s} n {int(mk.sum()):5d}  mean p/m {p.mean():.4f}  realised {y:.4f}  ratio {p.mean() / y:.3f}")
    print_surface(G, f"w SURFACE at m = {m_cal:.3f} (information; w is set by prior unless the departure rule triggers)")
    # ---- departure rule (pre-stated): unique argmax, != 0.75, beats 0.75 by >= 0.020 in MEAN, survives every top-5 LOO on both partitions
    g75 = G[np.isclose(G["w"], W_PRIOR)].iloc[0]
    ties = G[np.isclose(G["mean"], best["mean"], atol=1e-9)]
    unique = len(ties) == 1; differs = not np.isclose(best["w"], W_PRIOR); beats = (best["mean"] - g75["mean"]) >= 0.020
    print(f"\nDEPARTURE RULE: rank argmax w = {best['w']:g} (mean {best['mean']:.4f}) vs prior w = 0.75 (mean {g75['mean']:.4f}); gap {best['mean'] - g75['mean']:+.4f}; "
          f"unique {unique}; differs {differs}; beats by >= 0.020 {beats}")
    survives = None
    if unique and differs and beats:
        con = contributions(f, float(best["w"]), float(best["m"]), parts); survives = True
        for name, c in con.items():
            for r_ in pd.concat([c["top_rho"], c["top_delta"]]).drop_duplicates("element").itertuples():
                fl = f[f["element"] != r_.element].copy(); _, _, _, _, _, bl, _ = procedure(fl)
                ok = bool(np.isclose(bl["w"], best["w"])); survives = survives and ok
                print(f"    LOO drop {r_.name:32s} ({name}) -> argmax w = {bl['w']:g} {'same' if ok else 'CHANGES'}")
    depart = bool(unique and differs and beats and survives)
    w_chosen = float(best["w"]) if depart else W_PRIOR
    print(f"  -> {'DEPARTS from the prior' if depart else 'does NOT depart'}: w = {w_chosen:g} (by {'rank' if depart else 'PRIOR'}), m = {m_cal:.3f}")
    # ---- Salah guard + whole-procedure LOO of the top contributors at the chosen pair
    sal = f[f["name"].str.contains("Salah", case=False)]["element"].unique(); assert len(sal) == 1
    fx_ = f[f["element"] != sal[0]].copy(); mx, _, _, _, Gx, bx, _ = procedure(fx_)
    gx75 = Gx[np.isclose(Gx["w"], W_PRIOR)].iloc[0]
    print(f"\nSALAH GUARD (whole procedure without him): m = {mx:.3f}; rank argmax w = {bx['w']:g} (mean {bx['mean']:.4f}) vs 0.75 (mean {gx75['mean']:.4f}), gap {bx['mean'] - gx75['mean']:+.4f} -> departure rule {'would trigger' if (bx['mean'] - gx75['mean'] >= 0.02 and not np.isclose(bx['w'], W_PRIOR)) else 'still does not trigger'}")
    con = contributions(f, w_chosen, m_cal, parts)
    print("  whole-procedure leave-one-out of the top-5 contributors at the chosen pair (m recalibrated; rank argmax reported):")
    for name, c in con.items():
        print(f"    {name}: rho(candidate) {c['rho']:.4f}, delta {c['delta']:+.4f}; top-5 by rho share: " + ", ".join(f"{r_.name} {r_.rho_share:+.4f}" for r_ in c["top_rho"].itertuples()))
        for r_ in pd.concat([c["top_rho"], c["top_delta"]]).drop_duplicates("element").itertuples():
            fl = f[f["element"] != r_.element].copy(); ml, _, _, _, Gl, bl, _ = procedure(fl)
            gl75 = Gl[np.isclose(Gl["w"], W_PRIOR)].iloc[0]
            print(f"      drop {r_.name:32s} -> m {ml:.3f}, rank argmax w = {bl['w']:g}, gap to 0.75 {bl['mean'] - gl75['mean']:+.4f}")
    # ---- P2 and the four conditions at the chosen pair
    r, pred, real, nwo = written_off_ratio(f, m_cal)
    print(f"\nP2 -- written-off band ratio after conditioning at m = {m_cal:.3f}: mean p/m {pred:.4f} vs realised {real:.4f} -> {r:.2f} (n {nwo}; was 7.33 unconditional). "
          f"Pre-registered: <= ~2.5 expected with the 0.30 floor; > ~5 under every variant falsifies the premise. -> {'MET (<= 2.5)' if r <= 2.5 else 'NOT MET (> 2.5)'}{'; ABOVE 5' if r > 5 else ''}")
    print(f"\nPASS CONDITIONS (section 3, UNCHANGED) on {season} at {cond_pair_line(w_chosen, m_cal)} -- tuning season, NOT evidence:")
    pass_conditions(f, w_chosen, m_cal, parts)
    report_pair(f, w_chosen, m_cal, f"{season} tuning season (NOT evidence), conditional spec", n_partial)
    # ---- the calibration defect P1 surfaced: p_play_any's flat 0.30 floor vs the realised appearance rate on the band (DIAGNOSIS ONLY)
    hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "element", "GW", "minutes"])
    hist = hist[hist["season"] == season].groupby(["element", "GW"])["minutes"].sum().reset_index().rename(columns={"GW": "gw"})
    wo = f[f["p_start"] < 0.25].merge(hist, on=["element", "gw"], how="left"); wo["minutes"] = wo["minutes"].fillna(0)
    played = (wo["minutes"] > 0).mean(); ps = wo["p_start"].mean(); ppa = wo["p_play_any"].mean()
    c_fit = (played - ps) / (1.0 - ps)
    print(f"\nDIAGNOSIS (not adopted; a minutes-model change needing its own pre-registration): on the written-off band p_play_any {ppa:.3f} vs realised took-part {played:.3f} "
          f"(p_start {ps:.3f} vs realised started -- see P1). Refitting the flat substitute floor so the band mean matches: 0.30 -> {c_fit:.3f}.")
    print(f"  {'variant':44s} {'m':>7s} | {'WO ratio':>8s} | section-3 deltas at w = {w_chosen:g} | conditions")
    cond_summary(f"ADOPTED: per-book, floor 0.30, unverified={assign}", f, w_chosen, parts)
    fd = population(load_conditional(season, assign_unverified=assign, sub_floor=c_fit), lo, hi); fd = fd[fd["priced"]].copy()
    cond_summary(f"diag: per-book, floor refit {c_fit:.3f}", fd, w_chosen, partitions(fd))
    # ---- unverified-book sensitivity and the two uniform diagnostics
    other = "start" if assign == "participation" else "participation"
    fo = population(load_conditional(season, assign_unverified=other), lo, hi); fo = fo[fo["priced"]].copy()
    so = cond_summary(f"sensitivity: unverified books -> {other}", fo, w_chosen, partitions(fo))
    for mode in ("all-p_play_any", "all-p_start"):
        fm = population(load_conditional(season, assign_unverified=assign, mode=mode), lo, hi); fm = fm[fm["priced"]].copy()
        cond_summary(f"diag: {mode} (not selectable)", fm, w_chosen, partitions(fm))
    print(f"\nWrite '{cond_pair_line(w_chosen, m_cal)}' into a dated '## PRE-REGISTERED VALUE' section of Logs/props_conditional_prereg.md BEFORE any "
          f"--spec conditional --holdout. 2025-26 has not been read; its per-book file is generated at holdout time by the same builder code.")


def conditional_holdout(a):
    w, mm = a.holdout
    text = COND_PREREG.read_text(encoding="utf-8") if COND_PREREG.exists() else ""
    heads = list(re.finditer(r"^## PRE-REGISTERED VALUE", text, flags=re.M))
    if not heads or cond_pair_line(w, mm) not in text[heads[-1].start():]:
        print(f"REFUSED: the line '{cond_pair_line(w, mm)}' is not present in the LAST PRE-REGISTERED VALUE section of {COND_PREREG}. "
              "Write it there first; the sealed season is run once with the pre-registered pair only.")
        sys.exit(2)
    season = HOLDOUT_SEASON
    book_file = REPO / "data" / "odds_props" / f"props_consensus_book_{season}.parquet"
    if not book_file.exists():
        print(f"REFUSED: {book_file} does not exist -- build it with eval/build_props_consensus.py --seasons {season} first."); sys.exit(2)
    m_all = load_conditional(season, assign_unverified=a.assign_unverified)
    n_partial = int(m_all["partial_double"].eq(True).sum())
    f = population(m_all, 1, 38)
    print(f"SEALED {season}, {cond_pair_line(w, mm)} (pre-registered). Outfield singles: {len(f):,}; priced {int(f['priced'].sum()):,}; partial doubles excluded: {n_partial}.")
    print("coverage: " + coverage_line(f))
    f = f[f["priced"]].copy(); parts = partitions(f)
    r, pred, real, nwo = written_off_ratio(f, mm)
    print(f"P2 on the sealed season: written-off ratio {r:.2f} (n {nwo})")
    print(f"\nPASS CONDITIONS (section 3) on {season} at {cond_pair_line(w, mm)}:")
    pass_conditions(f, w, mm, parts)
    report_pair(f, w, mm, f"SEALED {season}, conditional spec", n_partial)


def coverage_line(f):
    parts = partitions(f)
    return "; ".join(f"{name} {f.loc[mask, 'priced'].mean():.1%} of {int(mask.sum())}" for name, mask in parts.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--spec", choices=["unconditional", "conditional"], default="unconditional", help="conditional = Logs/props_conditional_prereg.md")
    ap.add_argument("--assign-unverified", choices=["participation", "start"], default="participation", help="conditional spec: rule assigned to FanDuel and 1xBet")
    ap.add_argument("--holdout", nargs=2, type=float, metavar=("W", "M"))
    ap.add_argument("--pair", nargs=2, type=float, metavar=("W", "M"), help="report the TUNING season at a given pair (no 2025-26 read)")
    a = ap.parse_args()
    if a.tune and a.spec == "conditional":
        conditional_main(a)
    elif a.tune:
        tune_main(a)
    elif a.pair is not None:
        w, mm = a.pair
        season, (lo, hi) = TUNE_SEASON, TUNE_GW
        m_all = load(season); n_partial = int(m_all["partial_double"].eq(True).sum())
        f = population(m_all, lo, hi); f = f[f["priced"]].copy(); parts = partitions(f)
        print(f"TUNING SEASON {season} GW{lo}-{hi} at the given pair {pair_line(w, mm)} (no 2025-26 file read)")
        print("  design-time appearance probabilities by partition (cutoff quantities, no outcomes): n, mean p_start, mean p_play_any, mean p_60plus, mean market p/m")
        for name, mask in parts.items():
            g = f[mask]
            print(f"    {name:34s} n {len(g):5d}  p_start {g['p_start'].mean():.3f}  p_play_any {g['p_play_any'].mean():.3f}  p_60plus {g['p_60plus'].mean():.3f}  p/m {(g['p_mkt_gw'] / mm).mean():.4f}")
        print(f"\nPASS CONDITIONS (section 3) on {season} at {pair_line(w, mm)} -- tuning season, NOT evidence:")
        pass_conditions(f, w, mm, parts)
        report_pair(f, w, mm, f"{season} tuning season (NOT evidence)", n_partial)
    elif a.holdout is not None and a.spec == "conditional":
        conditional_holdout(a)
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
        ap.error("--tune, --pair W M or --holdout W M")


if __name__ == "__main__":
    main()
