"""M2 -- confirm the crowd signal (model-upgrade plan step 2). PROBE CODE: nothing in production imports
this module and it changes no prediction. No adoption follows from it.

Question: do the five pre-deadline crowd features (eval/crowd_features.py -- Probe A's, X2 review PR-6) still
improve OUR P(start) model on 2026-27, a season no test has touched?

This is Probe A's walk-forward and scoring (C:\\dev\\research\\x2\\scripts\\pr6_probe_a.py), unchanged in
substance, with 2026-27 added and the M2 rule in place of Probe A's reading rule:

  MODEL     the production P(start) sub-model: squad/minutes.py's frame builders and the m_ps config (LightGBM
            300 trees / 31 leaves / lr 0.05 / seed 42), on get_minutes's own feature list xFP. Baseline arm =
            that list; treated arm = + the five crowd features. Nothing else differs between the arms.
  PROTOCOL  for each season S and gameweek k: train on the prior labelled seasons plus S's gameweeks < k,
            predict gameweek k with is_double_gw forced to 0 -- as the frames of record are built.
  SLICES    fixed on the BASELINE arm, so both arms are scored on identical rows: ALL; LS (p_base >= 0.75);
            UNCERTAIN (0.25 <= p_base < 0.75); LS-UNFLAGGED (LS and FPL status 'a').
  DELTAS    treated - baseline, 95% intervals from 2,000 bootstrap draws over gameweeks within a season; pooled
            across seasons by averaging the seasons' deltas draw by draw (Probe A's pooling).
  VERDICT   PASS = (a) on 2026-27 the LS AUC delta > 0 AND the ALL-rows Brier delta < 0, as point estimates,
            AND (b) the pooled ALL-rows Brier delta over 2024-25 + 2025-26 + 2026-27 has its 95% interval
            entirely below 0. FAIL = (a) fails. Anything else = INCONCLUSIVE.
  SKEW      the fplcache seasons' snapshot is hours before the deadline, the live season's minutes. If the
            medians differ by more than 2 h a secondary arm is also run -- the four flow features as
            within-gameweek percentile ranks (ownership unchanged). Reported only; it never changes the verdict.

2023-24 is run as a reproduction control only (same code, same random stream as X2, so its lines and
2024-25's must equal X2's log); it is not in the pooled figure.

Usage (outputs only under data/m2/, never written over):
    uv run python eval/m2_crowd_probe.py fit  --crowd data/m2/crowd_asof.parquet --out-dir data/m2
    uv run python eval/m2_crowd_probe.py read --rows data/m2/probe_rows.parquet
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import crowd_features as cf  # noqa: E402

NB = 2000
METRICS = ("brier", "logloss", "auc")
SLICES = ("ALL", "LS", "UNCERTAIN", "LS-UNFLAGGED")
CONTROL = "2023-24"                                   # reproduction control: run, never pooled
RULE_SEASONS = ["2024-25", "2025-26", "2026-27"]      # the pooled figure of the rule
TEST_SEASON = "2026-27"
SEASONS = [("2023-24", ["2022-23"]), ("2024-25", ["2022-23", "2023-24"]),
           ("2025-26", ["2022-23", "2023-24", "2024-25"]),
           ("2026-27", ["2022-23", "2023-24", "2024-25", "2025-26"])]
SKEW_HOURS = 2.0


# ------------------------------------------------------------------ small pure pieces
def needs_rank_arm(train_median_hours, test_median_hours):
    """The declared timing-skew trigger: medians more than 2 hours apart."""
    return abs(float(train_median_hours) - float(test_median_hours)) > SKEW_HOURS


def metrics(d, c):
    """Brier, log loss and AUC of column `c` against realised starts. Probe A's M()."""
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    y = d["starts"].astype(int).to_numpy()
    p = np.clip(d[c].to_numpy(float), 1e-6, 1 - 1e-6)
    return {"brier": brier_score_loss(y, p), "logloss": log_loss(y, p, labels=[0, 1]),
            "auc": roc_auc_score(y, p) if 0 < y.mean() < 1 else np.nan}


def slices(d):
    """The four slices, fixed on the BASELINE arm."""
    ls = d["p_base"] >= 0.75
    return {"ALL": d, "LS": d[ls], "UNCERTAIN": d[(d["p_base"] >= 0.25) & (d["p_base"] < 0.75)],
            "LS-UNFLAGGED": d[ls & (d["av_status_code"] == 0)]}


def bootstrap_deltas(sl, base_col, treat_col, rng, nb=NB):
    """treated - baseline on `nb` resamples of whole gameweeks. Probe A's loop, draw for draw."""
    groups = [x for _, x in sl.groupby("GW")]
    dr = {m: np.empty(nb) for m in METRICS}
    for i in range(nb):
        s = pd.concat([groups[g] for g in rng.integers(0, len(groups), len(groups))], ignore_index=True)
        mb, mt = metrics(s, base_col), metrics(s, treat_col)
        for m in dr:
            dr[m][i] = mt[m] - mb[m]
    return dr


def pooled(draws_by_season):
    """Seasons stacked: the mean of the seasons' deltas, draw by draw."""
    return np.mean(list(draws_by_season), axis=0)


def interval(draws):
    return float(np.nanpercentile(draws, 2.5)), float(np.nanpercentile(draws, 97.5))


def verdict(ls_auc_delta_2026, all_brier_delta_2026, pooled_all_brier_ci):
    """The pre-registered rule, and nothing else."""
    a = (ls_auc_delta_2026 > 0) and (all_brier_delta_2026 < 0)
    if not a:
        return "FAIL"
    return "PASS" if pooled_all_brier_ci[1] < 0 else "INCONCLUSIVE"


def write_new(df, path):
    """A probe output is never written over."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} exists -- a probe output is never written over")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


# ------------------------------------------------------------------ the walk-forward
def walk_forward_arms(cs, season, train_seasons, gws, arms, make_model, arms_for_gw=None, keep=None, on_fit=None):
    """Probe A's loop. For each gameweek k of `season`: train every arm on the prior seasons plus the season's
    labelled gameweeks < k, predict gameweek k as one ordinary fixture. Returns one row per predicted
    player-gameweek with p_<arm> per arm (NaN where an arm was not asked for that gameweek)."""
    import minutes as mm
    keep = [c for c in (keep or ["season", "element", "GW", "name", "starts", "av_status_code"]) if c in cs.columns]
    outs = []
    for k in gws:
        trc = cs[mm._train_mask(cs, k, train_seasons, season)]
        trc = trc[trc["starts"].notna()]                      # forward-skeleton rows carry no label
        pf = cs[(cs["season"] == season) & (cs["GW"] == k)].dropna(subset=mm.SUBF + mm.S1).copy()
        if pf.empty:
            continue
        pf["is_double_gw_orig"] = pf["is_double_gw"]
        pf["is_double_gw"] = 0
        rec = pf[keep + ["is_double_gw_orig"]].copy()
        for arm in (arms_for_gw(k) if arms_for_gw else list(arms)):
            X = arms[arm]
            m = make_model().fit(trc[X], trc["starts"])
            rec[f"p_{arm}"] = m.predict_proba(pf[X])[:, 1]
            if on_fit is not None:
                on_fit(season, k, arm, m, X, len(trc))
        outs.append(rec)
    res = pd.concat(outs, ignore_index=True)
    for arm in arms:
        if f"p_{arm}" not in res.columns:
            res[f"p_{arm}"] = np.nan
    return res


def m_ps():
    """The production P(start) sub-model's configuration (squad/minutes.py get_minutes, m_ps)."""
    import lightgbm as lgb
    return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1)


def build_frame(crowd):
    """get_minutes's own frame (stack + forward skeleton, availability attached) with the crowd columns joined
    on. The only step production does not take is cf.attach."""
    import availability_features as avf
    import minutes as mm
    from season_stack import load_stack
    col = avf.attach(mm._prepare(load_stack()))
    col = cf.attach(col, crowd, cols=cf.CROWD + cf.RANKED)
    cs, _, _ = mm._build_frames(col)
    fp = mm.S1 + ["has_no_history", "prev_start_rate", "prev_avg_minutes", "prev_games", "transfer_status"] + avf.FEATURES
    return cs, fp


# ------------------------------------------------------------------ fit
def cmd_fit(a):
    crowd = pd.read_parquet(a.crowd)
    timing = cf.timing_table(crowd)
    train_med = float(crowd[crowd["season"] != TEST_SEASON].drop_duplicates(["season", "GW"])["hours_before_deadline"].median())
    lab = crowd[(crowd["season"] == TEST_SEASON) & (crowd["GW"] <= a.last_labelled)].drop_duplicates(["season", "GW"])
    test_med = float(lab["hours_before_deadline"].median())
    rank_arm = needs_rank_arm(train_med, test_med)
    print("snapshot timing, hours before the deadline:\n" + timing.to_string())
    print(f"median over the fplcache seasons' gameweeks {train_med:.3f} h; over {TEST_SEASON} gameweeks 1-{a.last_labelled} {test_med:.3f} h; "
          f"difference {abs(train_med - test_med):.3f} h -> secondary rank arm {'RUN' if rank_arm else 'not run'}", flush=True)

    cs, fp = build_frame(crowd)
    arms = {"base": fp, "crowd": fp + cf.CROWD}
    if rank_arm:
        arms["rank"] = fp + ["cs_own_pct"] + cf.RANKED
    print("feature counts:", {k: len(v) for k, v in arms.items()}, "| crowd coverage on labelled rows by season:",
          cs[cs.starts.notna()].groupby("season")["cs_own_pct"].apply(lambda s: round(float(s.notna().mean()), 3)).to_dict(), flush=True)

    imps = {}

    def on_fit(season, k, arm, m, X, n_train):
        if arm != "base" and k == last[season]:
            imps[f"{season}|gw{k}|{arm}"] = {
                "n_train": int(n_train), "features": list(X),
                "split": [int(v) for v in m.feature_importances_],
                "gain": [float(v) for v in m.booster_.feature_importance(importance_type="gain")]}

    keep = ["season", "element", "GW", "name", "position", "team", "starts", "minutes", "av_status_code"] + cf.CROWD + cf.RANKED
    outs, last, t0 = [], {}, time.time()
    for season, tr in SEASONS:
        gws = sorted(int(g) for g in cs.loc[cs.season == season, "GW"].unique())
        labelled = sorted(int(g) for g in cs.loc[(cs.season == season) & cs.starts.notna(), "GW"].unique())
        last[season] = labelled[-1]
        if season == TEST_SEASON:
            assert labelled == list(range(1, a.last_labelled + 1)), f"{season}: labelled gameweeks {labelled}"
            gws = labelled + [labelled[-1] + 1]            # + the next deadline, baseline arm only (exactness check)
        season_arms = [x for x in arms if not (season == CONTROL and x == "rank")]
        res = walk_forward_arms(cs, season, tr, gws, {x: arms[x] for x in season_arms}, m_ps,
                                arms_for_gw=lambda k: season_arms if k <= last[season] else ["base"],
                                keep=keep, on_fit=on_fit)
        outs.append(res)
        print(f"[{season}] gameweeks predicted {len(gws)} (first {gws[0]}, last {gws[-1]}; labelled to {last[season]}); "
              f"arms {season_arms}; rows {len(res):,}; done {time.time() - t0:.0f}s", flush=True)
    res = pd.concat(outs, ignore_index=True)
    out_dir = Path(a.out_dir)
    write_new(res, out_dir / "probe_rows.parquet")
    p = out_dir / "probe_importances.json"
    if p.exists():
        raise FileExistsError(p)
    p.write_text(json.dumps({"rank_arm": rank_arm, "train_median_hours": train_med, "test_median_hours": test_med,
                             "importances": imps}, indent=1), encoding="utf-8")
    print(f"rows {len(res):,} -> {out_dir / 'probe_rows.parquet'}; importances -> {p}; total {time.time() - t0:.0f}s")


# ------------------------------------------------------------------ read
def scored(res, season):
    d = res[(res.season == season) & res.starts.notna()].copy()
    d["starts"] = d["starts"].clip(upper=1)
    return d


def score_arm(res, seasons, treat, rng, label):
    """Per-season lines in Probe A's format, and the draws."""
    draws, points = {}, {}
    for season in seasons:
        d = scored(res, season)
        d = d[d[f"p_{treat}"].notna()]
        for sn, sl in slices(d).items():
            b, t = metrics(sl, "p_base"), metrics(sl, f"p_{treat}")
            dr = bootstrap_deltas(sl, "p_base", f"p_{treat}", rng)
            draws[(season, sn)] = dr
            points[(season, sn)] = {m: (b[m], t[m], t[m] - b[m], *interval(dr[m])) for m in METRICS}
            points[(season, sn)]["n"] = len(sl)
            points[(season, sn)]["start_rate"] = float(sl.starts.mean())
            print(f"[{season}] {sn:13s} n={len(sl):6d} start rate {sl.starts.mean():.3f} | "
                  + " | ".join(f"{m} base {b[m]:.4f} {label} {t[m]:.4f} delta {t[m]-b[m]:+.4f} "
                               f"[{np.nanpercentile(dr[m], 2.5):+.4f}, {np.nanpercentile(dr[m], 97.5):+.4f}]"
                               for m in METRICS), flush=True)
    return draws, points


def print_pooled(draws, seasons, tag):
    out = {}
    for sn in SLICES:
        for m in METRICS:
            p = pooled([draws[(s, sn)][m] for s in seasons])
            lo, hi = interval(p)
            out[(sn, m)] = (float(np.nanmean(p)), lo, hi)
            print(f"[{tag}] {sn:13s} {m:8s} delta {np.nanmean(p):+.4f} [{lo:+.4f}, {hi:+.4f}]   (5 dp: {np.nanmean(p):+.5f} [{lo:+.5f}, {hi:+.5f}])")
    return out


def cmd_read(a):
    res = pd.read_parquet(a.rows)
    meta = json.loads((Path(a.rows).parent / "probe_importances.json").read_text(encoding="utf-8"))
    has_rank = bool(meta["rank_arm"])
    seasons = [s for s, _ in SEASONS]
    print(f"rows {len(res):,} | by season {res.groupby('season').size().to_dict()} | arms "
          f"{[c for c in res.columns if c.startswith('p_')]} | rank arm run: {has_rank}")

    print("\n=== PRIMARY ARM: baseline vs + the five crowd features (Probe A's format; random stream as X2) ===")
    rng = np.random.default_rng(0)
    draws, pts = score_arm(res, seasons, "crowd", rng, "crowd")
    print("--- pooled by the M2 rule: 2024-25 + 2025-26 + 2026-27 ---")
    pool = print_pooled(draws, RULE_SEASONS, "pooled ")
    print("--- for comparison with X2's log only: X2's own pooling, 2023-24 + 2024-25 + 2025-26 ---")
    print_pooled(draws, ["2023-24", "2024-25", "2025-26"], "x2-pool")

    ls_auc = pts[(TEST_SEASON, "LS")]["auc"][2]
    all_brier = pts[(TEST_SEASON, "ALL")]["brier"][2]
    ci = pool[("ALL", "brier")][1:]
    print("\n=== VERDICT BY THE PRE-REGISTERED RULE ===")
    print(f"(a) {TEST_SEASON} LS AUC delta {ls_auc:+.5f} (> 0: {ls_auc > 0}); ALL-rows Brier delta {all_brier:+.5f} (< 0: {all_brier < 0})")
    print(f"(b) pooled ALL-rows Brier delta {pool[('ALL', 'brier')][0]:+.5f}, 95% interval [{ci[0]:+.5f}, {ci[1]:+.5f}] (entirely below 0: {ci[1] < 0})")
    print("VERDICT:", verdict(ls_auc, all_brier, ci))

    if has_rank:
        print("\n=== SECONDARY ARM (reported only): baseline vs ownership + the four flow features as within-gameweek ranks ===")
        rdraws, rpts = score_arm(res, RULE_SEASONS, "rank", np.random.default_rng(1), "rank")
        rpool = print_pooled(rdraws, RULE_SEASONS, "pooled ")
        r_auc, r_brier, rci = rpts[(TEST_SEASON, "LS")]["auc"][2], rpts[(TEST_SEASON, "ALL")]["brier"][2], rpool[("ALL", "brier")][1:]
        print(f"the rule's two reads on this arm (it has no verdict): (a) LS AUC delta {r_auc:+.5f}, ALL Brier delta {r_brier:+.5f}; "
              f"(b) pooled ALL Brier {rpool[('ALL', 'brier')][0]:+.5f} [{rci[0]:+.5f}, {rci[1]:+.5f}] -> would read {verdict(r_auc, r_brier, rci)}")

    print("\n=== 2026-27 by gameweek (ALL rows; LS rows) ===")
    d = scored(res, TEST_SEASON)
    for gw, g in d.groupby("GW"):
        ls = g[g.p_base >= 0.75]
        line = f"GW{int(gw):2d} n {len(g):4d} starts {int(g.starts.sum()):3d} | Brier base {metrics(g, 'p_base')['brier']:.4f} crowd {metrics(g, 'p_crowd')['brier']:.4f}"
        if has_rank:
            line += f" rank {metrics(g, 'p_rank')['brier']:.4f}"
        line += (f" | LS n {len(ls):3d} did not start {int((ls.starts == 0).sum()):3d} AUC base {metrics(ls, 'p_base')['auc']:.4f} "
                 f"crowd {metrics(ls, 'p_crowd')['auc']:.4f}")
        if has_rank:
            line += f" rank {metrics(ls, 'p_rank')['auc']:.4f}"
        print(line + f" | crowd features present {int(g.cs_own_pct.notna().sum())} of {len(g)}")

    side_reads(res, meta, has_rank)


def side_reads(res, meta, has_rank):
    print("\n=== SIDE READS (no rule) ===")
    for key, v in meta["importances"].items():
        f = pd.DataFrame({"feature": v["features"], "split": v["split"], "gain": v["gain"]})
        f["split_rank"] = f["split"].rank(ascending=False, method="min").astype(int)
        f["gain_rank"] = f["gain"].rank(ascending=False, method="min").astype(int)
        c = f[f["feature"].str.startswith("cs_")]
        print(f"[importance] {key} (n_train {v['n_train']:,}; {len(f)} features): "
              + "; ".join(f"{r.feature} split #{r.split_rank} gain #{r.gain_rank} ({r.gain / f['gain'].sum():.1%} of gain)" for r in c.itertuples())
              + f" | top 5 by gain: {f.sort_values('gain', ascending=False)['feature'].head(5).tolist()}")

    d = scored(res, TEST_SEASON)
    for arm in ["crowd"] + (["rank"] if has_rank else []):
        p = f"p_{arm}"
        d[f"move_{arm}"] = d[p] - d["p_base"]
        top = d.reindex(d[f"move_{arm}"].abs().sort_values(ascending=False).index).head(20)
        print(f"\n[movers] the 20 biggest {TEST_SEASON} P(start) moves, baseline -> {arm} "
              f"(moved the right way: {int(((top[f'move_{arm}'] > 0) == (top.starts == 1)).sum())} of 20):")
        for r in top.itertuples():
            print(f"   GW{int(r.GW):2d} {str(r.name)[:28]:28s} {str(getattr(r, 'team', ''))[:14]:14s} {getattr(r, 'p_base'):.3f} -> {getattr(r, p):.3f} "
                  f"({getattr(r, f'move_{arm}'):+.3f})  started: {'yes' if r.starts == 1 else 'no'}  "
                  f"status code {int(r.av_status_code)}  own {r.cs_own_pct:.1f}%  out/owners {r.cs_out_ratio:.3f}  in/owners {r.cs_in_ratio:.3f}")
        ls = d[d.p_base >= 0.75]
        no, yes = ls[ls.starts == 0], ls[ls.starts == 1]
        below = d[d.p_base < 0.75]
        print(f"[0.75 line, {arm}] {TEST_SEASON} likely starters (baseline >= 0.75): {len(ls)} rows, {len(no)} did not start, {len(yes)} started. "
              f"Did NOT start and fell below 0.75: {int((no[p] < 0.75).sum())} of {len(no)}. "
              f"DID start and were pushed below 0.75: {int((yes[p] < 0.75).sum())} of {len(yes)}. "
              f"The other way -- baseline below 0.75, lifted to >= 0.75: started {int(((below[p] >= 0.75) & (below.starts == 1)).sum())}, "
              f"did not start {int(((below[p] >= 0.75) & (below.starts == 0)).sum())}.")
        fr = d[(d.p_base >= 0.40) & (d.p_base <= 0.70)]
        print(f"[fringe band, {arm}] baseline 0.40-0.70: {len(fr)} rows; mean P(start) baseline {fr.p_base.mean():.4f}, {arm} {fr[p].mean():.4f}; "
              f"actual start rate {fr.starts.mean():.4f}; Brier baseline {metrics(fr, 'p_base')['brier']:.4f}, {arm} {metrics(fr, p)['brier']:.4f}")


# ------------------------------------------------------------------ check (the run is void if (1) or (2) fails)
def _maxdiff(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    both_nan = np.isnan(a) & np.isnan(b)
    d = np.abs(a - b)
    d[both_nan] = 0.0
    return float(np.nanmax(d)) if len(d) else 0.0, int((np.isnan(a) != np.isnan(b)).sum())


def cmd_check(a):
    res = pd.read_parquet(a.rows)
    tol, ok = 1e-6, {}

    print("=== EXACTNESS CHECK 1: the baseline arm's 2026-27 p_start vs M1's new-stack builds (step 0 of each cutoff) ===")
    m1 = pd.read_parquet(a.m1_build, columns=["cutoff", "gw", "element", "horizon_step", "p_start", "n_fixtures"])
    m1 = m1[m1.horizon_step == 0]
    worst = 0.0
    for cutoff in sorted(int(c) for c in m1.cutoff.unique()):
        o = m1[m1.cutoff == cutoff]
        mine = res[(res.season == TEST_SEASON) & (res.GW == cutoff)]
        j = mine.merge(o, left_on=["element", "GW"], right_on=["element", "gw"], how="outer", indicator=True)
        both = j[j._merge == "both"]
        s1, s2 = both[both.n_fixtures == 1], both[both.n_fixtures > 1]
        d1 = float((s1.p_base - s1.p_start).abs().max()) if len(s1) else float("nan")
        d2 = float((s2.p_base - s2.p_start).abs().max()) if len(s2) else 0.0
        worst = max(worst, d1)
        els = sorted(int(e) for e in both.element)
        print(f"cutoff {cutoff}: probe rows {len(mine)}, M1 build rows {len(o)}, joined {len(both)} (only probe {int((j._merge == 'left_only').sum())}, "
              f"only M1 {int((j._merge == 'right_only').sum())}); element ids count {len(els)} first {els[0]} last {els[-1]} | "
              f"single-fixture rows {len(s1)} max |p_base - p_start| = {d1:.3e} | double rows {len(s2)} max |diff| {d2:.3e}")
        ok[f"1:cutoff{cutoff}"] = (len(both) == len(mine) == len(o)) and d1 <= tol
    print(f"CHECK 1: {'PASS' if all(v for k, v in ok.items() if k.startswith('1:')) else 'FAIL -- THE RUN IS VOID'} (worst single-fixture difference {worst:.3e}, tolerance {tol:.0e})")

    print("\n=== EXACTNESS CHECK 2: Probe A re-run vs X2's own rows (2024-25; 2023-24 as a further control) ===")
    x2 = pd.read_parquet(a.x2_rows)
    for season in ("2024-25", CONTROL):
        mine, theirs = res[res.season == season], x2[x2.season == season]
        j = mine.merge(theirs, on=["season", "element", "GW"], how="outer", suffixes=("", "_x2"), indicator=True)
        both = j[j._merge == "both"]
        parts = []
        bad = False
        for c in ["p_base", "p_crowd", "starts", "is_double_gw_orig", "av_status_code"] + cf.CROWD:
            md, nan_mismatch = _maxdiff(both[c], both[c + "_x2"])
            parts.append(f"{c} {md:.2e}" + (f" (NaN on one side only: {nan_mismatch})" if nan_mismatch else ""))
            bad = bad or md > tol or nan_mismatch > 0
        print(f"[{season}] rows probe {len(mine)}, X2 {len(theirs)}, joined {len(both)} (only probe {int((j._merge == 'left_only').sum())}, "
              f"only X2 {int((j._merge == 'right_only').sum())}) | max |diff|: " + "; ".join(parts))
        ok[f"2:{season}"] = (len(both) == len(mine) == len(theirs)) and not bad
    print(f"CHECK 2: {'PASS' if ok['2:2024-25'] else 'FAIL -- THE RUN IS VOID'} on 2024-25 (control 2023-24: {'same' if ok['2:' + CONTROL] else 'DIFFERS'}). "
          "The printed metric lines are compared with X2's log separately.")

    print("\n=== FOR THE RECORD: the baseline arm vs the frames of record (step 0) ===")
    for season in ("2024-25", "2025-26"):
        p = REPO / "data" / f"walkforward_h6_{season.replace('-', '_')}.parquet"
        o = pd.read_parquet(p, columns=["element", "gw", "horizon_step", "p_start", "n_fixtures"])
        o = o[o.horizon_step == 0]
        mine = res[res.season == season]
        j = mine.merge(o, left_on=["element", "GW"], right_on=["element", "gw"], how="inner")
        s1, s2 = j[j.n_fixtures == 1], j[j.n_fixtures > 1]
        print(f"[{season}] {p.name}: rows probe {len(mine)} record {len(o)} joined {len(j)} | single-fixture max |p_base - p_start| = "
              f"{float((s1.p_base - s1.p_start).abs().max()):.3e} | double rows {len(s2)} max |diff| {float((s2.p_base - s2.p_start).abs().max()) if len(s2) else 0:.3e}")

    print("\n=== COVERAGE: predicted rows with / without a snapshot row for the player ===")
    for season in [s for s, _ in SEASONS]:
        d = res[res.season == season]
        g = d.groupby("GW").agg(rows=("element", "size"), with_snapshot=("cs_own_pct", lambda s: int(s.notna().sum())))
        g["without"] = g["rows"] - g["with_snapshot"]
        print(f"[{season}] gameweeks {len(g)} (first {int(g.index.min())}, last {int(g.index.max())}); rows {int(g.rows.sum()):,}; with a snapshot row "
              f"{int(g.with_snapshot.sum()):,}; without {int(g.without.sum()):,} ({g.without.sum() / g.rows.sum():.2%}); "
              f"gameweeks with any row missing {int((g.without > 0).sum())}; most missing in one gameweek {int(g.without.max())} (GW{int(g.without.idxmax())})")
        if season == TEST_SEASON:
            print(g.T.to_string())
    void = not (all(v for k, v in ok.items() if k.startswith("1:")) and ok["2:2024-25"])
    print("\nRUN STATUS:", "VOID" if void else "VALID -- both exactness checks hold")
    sys.exit(2 if void else 0)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--crowd", type=Path, required=True)
    f.add_argument("--out-dir", type=Path, required=True)
    f.add_argument("--last-labelled", type=int, default=10, help="the last 2026-27 gameweek with realised starts")
    c = sub.add_parser("check")
    c.add_argument("--rows", type=Path, required=True)
    c.add_argument("--m1-build", type=Path, required=True, help="M1's 2026-27 frame built on the de-duplicated stack")
    c.add_argument("--x2-rows", type=Path, required=True, help="X2's Probe A per-row predictions")
    r = sub.add_parser("read")
    r.add_argument("--rows", type=Path, required=True)
    a = ap.parse_args()
    {"fit": cmd_fit, "check": cmd_check, "read": cmd_read}[a.cmd](a)


if __name__ == "__main__":
    main()
