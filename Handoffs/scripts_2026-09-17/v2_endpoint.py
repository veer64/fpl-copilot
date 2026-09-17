"""Prereg v2 (Logs/dc_shrinkage_threshold_prereg_2026-09-17.md) sections 2 and 3, computed verbatim:
reference builds WITH the form (scratch ref_v2_{tag}.parquet + ref_v2_{tag}_fits.json, one LAST_FIT
per cutoff in cutoff order) against the current record (data/walkforward_h6_{tag}.parquet, no form).

Affected cells: cutoffs whose fit has a club below N or a club at a bound (all steps of that cutoff).
  (b) structural: every row of every UNAFFECTED cutoff bit-identical on every column (a tell if not);
      and movement somewhere in the affected cells (a tell if none).
  primary: sliced Spearman(e_points, actual_points) per (season, cutoff, step) on starters p_start >= .75
      and on the top 30 by e_points, steps 1-5, affected cells only, POOLED across seasons: paired mean
      delta (form - record) with SE = sd/sqrt(cells). FALSIFIED if mean < -2 SE on either slice.
  (d) step 0 p_cs: rows whose fixture involves no affected club bit-identical; the rest: mean and max
      |delta p_cs|, STOP if any > 0.15.
  (c) sanity: every team lambda in [0.15, 6.0] at every step of every cutoff; every fit converged;
  (e) no established club within 0.2 of a bound (LAST_FIT.min_margin_to_bound).
Reported, never judged: per-season and early-cutoff means, absolute figures, which cutoffs were boxed."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(r"C:\dev\fpl-copilot")
HERE = Path(__file__).resolve().parent
import os
PREFIX = os.environ.get("V2_PREFIX", "ref_v2")
SEASONS = sys.argv[1:] or ["2023-24", "2024-25", "2025-26"]
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs", "Sheffield United": "Sheffield Utd"}
LAM_LO, LAM_HI = 0.15, 6.0


def sliced(d):
    d = d.dropna(subset=["e_points", "actual_points"]).copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    d = d.dropna(subset=["actual_points"])
    out = []
    for (k, st), g in d.groupby(["cutoff", "horizon_step"]):
        s = g[g["p_start"] >= 0.75]
        t = g.nlargest(30, "e_points")
        rs = spearmanr(s["e_points"], s["actual_points"]).correlation if len(s) > 5 else np.nan
        rt = spearmanr(t["e_points"], t["actual_points"]).correlation if len(t) > 5 else np.nan
        out.append(dict(cutoff=int(k), step=int(st), starters=rs, top30=rt, n_starters=len(s)))
    return pd.DataFrame(out)


def opponent_map(season):
    """Calendar-based: the season's archive fixtures assigned to gameweeks by the stack's kickoff
    windows (as walk_forward assigns cutoff dates), names mapped to the frame's. (gw, team) -> set of
    opponents; a double gameweek gives two. The earlier lambda-swap pairing mis-paired fixtures with
    identical odds (first build: Brighton v Luton paired as Brighton v Wolves)."""
    for q in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
        if q not in sys.path:
            sys.path.insert(0, q)
    import dixon_coles as dc
    from season_stack import load_stack
    df = load_stack(columns=["season", "GW", "kickoff_time"])
    v = df[df["season"] == season].copy()
    v["kick"] = pd.to_datetime(v["kickoff_time"]).dt.tz_localize(None)
    gw_start = v.groupby("GW")["kick"].min().dt.normalize()
    gw_end = v.groupby("GW")["kick"].max().dt.normalize()
    m = dc._load_matches(season)
    m = m[m["season"] == season]
    out = {}
    unassigned = 0
    for _, r in m.iterrows():
        d = pd.Timestamp(r["date_parsed"]).normalize()
        gws = [int(g) for g in gw_start.index if gw_start.loc[g] <= d <= gw_end.loc[g]]
        if len(gws) != 1:
            unassigned += 1
            continue
        g = gws[0]
        h, a = TEAM_MAP.get(r["home"], r["home"]), TEAM_MAP.get(r["away"], r["away"])
        out.setdefault((g, h), set()).add(a); out.setdefault((g, a), set()).add(h)
    return out, unassigned


report = {"seasons": {}, "pooled": {}, "stops": [], "tells": []}
cells_all = []
for season in SEASONS:
    tag = season.replace("-", "_")
    ref = pd.read_parquet(HERE / f"{PREFIX}_{tag}.parquet")
    rec = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    fits = json.loads((HERE / f"{PREFIX}_{tag}_fits.json").read_text(encoding="utf-8"))
    cutoffs = sorted(ref["cutoff"].unique())
    assert len(fits) == len(cutoffs), (len(fits), len(cutoffs))
    fit_by_cut = dict(zip(cutoffs, fits))
    rec = rec[rec["cutoff"].isin(cutoffs)]
    assert len(ref) == len(rec), (len(ref), len(rec))
    S = {"n_rows": int(len(ref)), "cutoffs": len(cutoffs)}

    # which cutoffs are affected, and by whom (frame names)
    affected = {}
    for k, f in fit_by_cut.items():
        clubs = set(f.get("clubs_below_n") or {}) | set(f.get("at_bound") or {})
        if clubs:
            affected[k] = sorted(TEAM_MAP.get(c, c) for c in clubs)
    S["affected_cutoffs"] = {int(k): v for k, v in affected.items()}
    S["boxed_cutoffs"] = {int(k): f["at_bound"] for k, f in fit_by_cut.items() if f.get("boxed_refit")}
    S["methods"] = {m: sum(1 for f in fits if f.get("method") == m) for m in ("L-BFGS-B", "SLSQP")}
    S["all_converged"] = all(bool(f["converged"]) for f in fits)
    S["not_converged_cutoffs"] = [int(k) for k, f in fit_by_cut.items() if not f["converged"]]
    S["iterations_max"] = max(int(f["iterations"]) for f in fits)
    mm = min(((f["min_margin_to_bound"], f["min_margin_club"], int(k)) for k, f in fit_by_cut.items()
              if f.get("min_margin_to_bound") is not None), default=(None, None, None))
    S["min_margin_to_bound"] = {"margin": mm[0], "club": mm[1], "cutoff": mm[2]}
    S["league_mean_attack_range"] = [round(min(f["league_mean_attack"] for f in fits), 4), round(max(f["league_mean_attack"] for f in fits), 4)]
    S["max_centred_attack"] = round(max(f["max_abs_centred_attack"] for f in fits), 4)
    S["max_centred_defence"] = round(max(f["max_abs_centred_defence"] for f in fits), 4)
    if not S["all_converged"]:
        report["stops"].append(f"{season}: fit did not converge at cutoffs {S['not_converged_cutoffs']} (gate c)")
    if mm[0] is not None and mm[0] < 0.2:
        report["stops"].append(f"{season}: established club within 0.2 of a bound: {mm[1]} margin {mm[0]:.3f} at cutoff {mm[2]} (gate e)")

    # (b) structural: unaffected cutoffs bit-identical on every column
    key = ["cutoff", "gw", "element"]
    un = [k for k in cutoffs if k not in affected]
    a = ref[ref["cutoff"].isin(un)].sort_values(key).reset_index(drop=True)
    b = rec[rec["cutoff"].isin(un)].sort_values(key).reset_index(drop=True)
    moved_cols = []
    if len(a) != len(b) or not a[key].equals(b[key]):
        moved_cols.append("ROW UNIVERSE DIFFERS")
    else:
        for c in ref.columns:
            if c not in rec.columns:
                continue
            x, y = a[c].values, b[c].values
            if np.issubdtype(a[c].dtype, np.number):
                same = np.array_equal(x, y, equal_nan=True)
            else:
                same = (pd.Series(x).fillna("<na>") == pd.Series(y).fillna("<na>")).all()
            if not same:
                moved_cols.append(c)
    S["unaffected_cutoffs"] = [int(k) for k in un]
    S["unaffected_bit_identical"] = not moved_cols
    S["unaffected_moved_columns"] = moved_cols[:10]
    if moved_cols:
        report["tells"].append(f"{season}: unaffected cells NOT bit-identical (columns {moved_cols[:6]}) (gate b)")
    # movement in the affected cells
    af = [k for k in cutoffs if k in affected]
    a2 = ref[ref["cutoff"].isin(af)].sort_values(key).reset_index(drop=True)
    b2 = rec[rec["cutoff"].isin(af)].sort_values(key).reset_index(drop=True)
    d_ep = np.abs(a2["e_points"].values - b2["e_points"].values)
    S["affected_max_abs_delta_e_points"] = float(np.nanmax(d_ep)) if len(d_ep) else 0.0
    S["affected_rows_moved_share"] = float((d_ep > 0).mean()) if len(d_ep) else 0.0
    if len(af) and S["affected_max_abs_delta_e_points"] == 0.0:
        report["tells"].append(f"{season}: NO movement in the affected cells (too clean)")

    # (c) sanity: lambdas
    lam = ref.groupby(["cutoff", "gw", "team"])["team_lambda"].first().dropna()
    S["lambda_min"] = {"value": float(lam.min()), "at": [int(lam.idxmin()[0]), int(lam.idxmin()[1]), lam.idxmin()[2]]}
    S["lambda_max"] = {"value": float(lam.max()), "at": [int(lam.idxmax()[0]), int(lam.idxmax()[1]), lam.idxmax()[2]]}
    if lam.min() < LAM_LO or lam.max() > LAM_HI:
        report["stops"].append(f"{season}: lambda outside [{LAM_LO}, {LAM_HI}]: min {lam.min():.4f} max {lam.max():.4f} (gate c)")
    lam_rec = rec.groupby(["cutoff", "gw", "team"])["team_lambda"].first().dropna()
    S["record_lambda_min"] = float(lam_rec.min())
    # the affected clubs' lambdas before/after at their affected cutoffs (the cold-start cells)
    rows = []
    for k, clubs in affected.items():
        for c in clubs:
            lo = lam_rec.loc[k].xs(c, level="team") if c in lam_rec.loc[k].index.get_level_values("team") else None
            ln = lam.loc[k].xs(c, level="team") if c in lam.loc[k].index.get_level_values("team") else None
            if lo is not None and ln is not None:
                rows.append(dict(cutoff=int(k), club=c, rec_min=round(float(lo.min()), 4), new_min=round(float(ln.min()), 4),
                                 rec_mean=round(float(lo.mean()), 3), new_mean=round(float(ln.mean()), 3)))
    S["affected_clubs_lambda"] = rows

    # (d) step 0 p_cs
    rec0 = rec[rec["horizon_step"] == 0]
    ref0 = ref[ref["horizon_step"] == 0]
    opp, n_unassigned = opponent_map(season)
    m0 = rec0[key + ["team", "n_fixtures", "p_cs"]].merge(ref0[key + ["p_cs"]], on=key, suffixes=("_rec", "_new"))
    m0["opp"] = [",".join(sorted(opp[(g, t)])) if (g, t) in opp else None for g, t in zip(m0["gw"], m0["team"])]
    inv = [(t in affected.get(k, [])) or any(o in affected.get(k, []) for o in (os.split(",") if os else []))
           for k, t, os in zip(m0["cutoff"], m0["team"], m0["opp"])]
    m0["involves"] = inv
    m0["d"] = (m0["p_cs_new"] - m0["p_cs_rec"]).abs()
    unpaired = m0[(m0["n_fixtures"] == 1) & m0["opp"].isna() & (~m0["involves"])]   # never counted as clean
    clean = m0[(~m0["involves"]) & (m0["n_fixtures"] == 1) & m0["opp"].notna()]
    dgw = m0[m0["n_fixtures"] != 1]
    inv_rows = m0[m0["involves"]]
    S["step0_pcs"] = {"rows_no_affected_club": int(len(clean)), "bit_identical": bool((clean["d"] == 0).all()),
                      "max_delta_no_affected_club": float(clean["d"].max()) if len(clean) else 0.0,
                      "rows_involving_affected_club": int(len(inv_rows)),
                      "mean_abs_delta": float(inv_rows["d"].mean()) if len(inv_rows) else 0.0,
                      "max_abs_delta": float(inv_rows["d"].max()) if len(inv_rows) else 0.0,
                      "dgw_rows": int(len(dgw)), "dgw_max_abs_delta": float(dgw["d"].max()) if len(dgw) else 0.0,
                      "fixtures_unassigned_to_a_gw": int(n_unassigned), "unpaired_rows": int(len(unpaired)), "unpaired_max_abs_delta": float(unpaired["d"].max()) if len(unpaired) else 0.0,
                      "unpaired_at": [[int(a), int(b), c] for a, b, c in unpaired.sort_values("d", ascending=False)[["cutoff", "gw", "team"]].head(5).values.tolist()]}
    if len(clean) and clean["d"].max() > 0.01:
        report["tells"].append(f"{season}: step-0 p_cs moved by > 0.01 on a fixture with no affected club (max {clean['d'].max():.4f}) -- above the shared-parameter mechanism (v3 prereg section 3)")
    if len(inv_rows) and inv_rows["d"].max() > 0.15:
        report["stops"].append(f"{season}: step-0 |delta p_cs| {inv_rows['d'].max():.4f} > 0.15 (gate d)")

    # primary: sliced Spearman on the affected cells, steps 1-5
    sa, sb = sliced(rec), sliced(ref)
    m = sa.merge(sb, on=["cutoff", "step"], suffixes=("_rec", "_new"))
    m["season"] = season
    m["affected"] = m["cutoff"].isin(af)
    cells = m[(m["step"] >= 1) & m["affected"]].copy()
    for sl in ("starters", "top30"):
        cells[f"d_{sl}"] = cells[f"{sl}_new"] - cells[f"{sl}_rec"]
    S["affected_cells_per_slice"] = int(len(cells))
    S["season_own_se"] = {sl: {"delta": round(float(cells[f"d_{sl}"].mean()), 5), "se": round(float(cells[f"d_{sl}"].std(ddof=1) / np.sqrt(len(cells))), 5),
                               "delta_over_se": round(float(cells[f"d_{sl}"].mean() / (cells[f"d_{sl}"].std(ddof=1) / np.sqrt(len(cells)))), 2)}
                          for sl in ("starters", "top30")}
    S["season_means"] = {sl: {"record": round(float(cells[f"{sl}_rec"].mean()), 4), "form": round(float(cells[f"{sl}_new"].mean()), 4),
                              "delta": round(float(cells[f"d_{sl}"].mean()), 4)} for sl in ("starters", "top30")}
    early = cells[cells["cutoff"] <= 6]
    S["early_cutoff_1_6_delta"] = {sl: round(float(early[f"d_{sl}"].mean()), 4) for sl in ("starters", "top30")}
    S["by_step_delta"] = {int(st): {sl: round(float(g[f"d_{sl}"].mean()), 4) for sl in ("starters", "top30")} for st, g in cells.groupby("step")}
    cells_all.append(cells)
    report["seasons"][season] = S

pooled = pd.concat(cells_all, ignore_index=True)
P = {"cells": int(len(pooled))}
for sl in ("starters", "top30"):
    d = pooled[f"d_{sl}"].dropna()
    mean, sd = float(d.mean()), float(d.std(ddof=1))
    se = sd / np.sqrt(len(d))
    P[sl] = {"record_mean": round(float(pooled[f"{sl}_rec"].mean()), 4), "form_mean": round(float(pooled[f"{sl}_new"].mean()), 4),
             "delta": round(mean, 5), "se": round(se, 5), "delta_over_se": round(mean / se, 2) if se else None,
             "falsified": bool(mean < -2 * se), "share_cells_up": round(float((d > 0).mean()), 3),
             "share_cells_unchanged": round(float((d == 0).mean()), 3)}
    if mean < -2 * se:
        report["stops"].append(f"pooled {sl}: mean delta {mean:+.5f} < -2 SE ({-2 * se:+.5f}) (primary)")
report["pooled"] = P
# v3 prereg section 4: FALSIFIED (a stop), else MARGINAL if any pooled slice in [-2 SE, -1 SE) or any season's slice
# below -2 of its own SE or a tell, else PASS
marginal = []
for sl in ("starters", "top30"):
    if -2 <= P[sl]["delta_over_se"] < -1:
        marginal.append(f"pooled {sl} {P[sl]['delta_over_se']:+.2f} SE in [-2, -1)")
    for s_, S_ in report["seasons"].items():
        if S_["season_own_se"][sl]["delta_over_se"] < -2:
            marginal.append(f"{s_} {sl} {S_['season_own_se'][sl]['delta_over_se']:+.2f} of its own SE")
marginal += report["tells"]
report["marginal"] = marginal
report["verdict"] = "FALSIFIED" if report["stops"] else ("MARGINAL" if marginal else "PASS")
(HERE / f"v2_endpoint_{PREFIX}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
print(json.dumps(report, indent=1, default=str))
