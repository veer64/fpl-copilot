# measure_market_lambda_horizon.py
# D4 audit check 8 -- horizon degradation of the market-lambda model.
#
# The study model was trained with features fresh to the match. In production,
# a planner standing at gameweek p prices gameweek p+k with information frozen
# at p. This script rebuilds the feature set AS IT WOULD ACTUALLY LOOK at each
# horizon step and measures both deployment designs.
#
# STALENESS DEFINITION. Gameweeks are indexed by POSITION in the season's
# calendar-sorted label list (so 2019-20's 39-47 restart labels and 2022-23's
# missing GW7 cannot corrupt the arithmetic). For a target match at position t,
# step k freezes information at C = first match date of the gameweek at
# position t-k+1. Step 1 = priced at its own gameweek's deadline (closest to
# the built dataset); step 6 = five gameweeks stale.
#
# WHAT FREEZES, per block:
#   market history : windows over the team's matches with date < C
#   dixon-coles    : the CACHED walk-forward fit for the freeze gameweek
#                    (data/history/d4_dc_walkforward_params.parquet)
#   availability   : top-5 ranking by cumulative minutes < C; statuses at the
#                    FREEZE gameweek's deadline (that is what the planner has)
#   schedule       : unchanged -- the fixture calendar is public in advance
#                    (caveat: late postponements would not have been visible)
#   is_home        : known in advance
#
# EVALUATION. Common rows across all steps: target position >= 6 and the
# step-6 (stalest) market-history block fully defined for both sides -- so the
# curve measures staleness, not a changing row population. Two variants:
#   A: the study model (trained fresh, per target season, expanding window)
#      applied to stale features
#   B: one model PER STEP trained on stale features of earlier seasons --
#      the honest production design
# Baseline: DC frozen at the SAME cutoff (in production the fallback is also
# fit at the planning gameweek), scored on identical rows.
#
# 2025-26 (sealed) is NOT touched -- not as train, not as test. The curve is
# measured on the eight validation seasons.
#
# Usage: uv run python eval/measure_market_lambda_horizon.py

import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot")
sys.path.insert(0, str(BASE))

DATA = BASE / "data" / "d4_market_lambda_dataset.parquet"
DC_CACHE = BASE / "data" / "history" / "d4_dc_walkforward_params.parquet"
VAASTAV = BASE / "data" / "history" / "all_seasons_fixed.parquet"
AV_FILES = {"2021-22": "availability_2122.parquet",
            "2022-23": "availability_2223.parquet",
            "2023-24": "availability_2324.parquet",
            "2024-25": "availability_2425.parquet"}
UNAVAILABLE = {"i", "s", "u", "n"}

VALID = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22",
         "2022-23", "2023-24", "2024-25"]
SEASONS = ["2016-17"] + VALID          # sealed 2025-26 excluded entirely
STEPS = [1, 2, 3, 4, 5, 6]
CFG = {"num_leaves": 15, "learning_rate": 0.03, "n_estimators": 300,
       "min_child_samples": 20}
FIXED = {"objective": "l2", "verbosity": -1, "n_jobs": -1, "seed": 42,
         "deterministic": True, "force_row_wise": True}

FEATURES = [
    "mh_own_l5", "mh_own_l10", "mh_own_s2d",
    "mh_conc_l5", "mh_conc_l10", "mh_conc_s2d",
    "mh_opp_own_l5", "mh_opp_own_l10", "mh_opp_conc_l5", "mh_opp_conc_l10",
    "dc_attack", "dc_defence_opp", "is_home",
    "sch_rest_days", "sch_m14", "sch_rest_days_opp", "sch_m14_opp",
    "av_top5_out", "av_top5_out_opp",
]


def r2_mae(y, p):
    ss = 1 - float(((y - p) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())
    return ss, float(np.abs(y - p).mean())


def build_freeze_tables(df):
    """Per (season, team, freeze position q): market-history stats and the
    availability count, using only information strictly before C(q)."""
    # gameweek positions and cutoff dates
    pos_maps, cutoffs = {}, {}
    for s in SEASONS:
        labels = sorted(df[df["season"] == s]["gw"].unique())
        pos_maps[s] = {g: i + 1 for i, g in enumerate(labels)}
        first = df[df["season"] == s].groupby("gw")["match_date"].min()
        cutoffs[s] = {pos_maps[s][g]: d for g, d in first.items()}
    label_at = {s: {p: g for g, p in pos_maps[s].items()} for s in SEASONS}

    va = pd.read_parquet(VAASTAV, columns=["season", "team", "element",
                                           "minutes", "kickoff_time"])
    va = va.dropna(subset=["team"])
    va["kick_date"] = (pd.to_datetime(va["kickoff_time"], utc=True)
                       .dt.tz_localize(None))   # naive, comparable to cutoffs
    av = pd.concat([pd.read_parquet(BASE / "data" / f,
                                    columns=["season", "gw", "element",
                                             "asof_status"])
                    for f in AV_FILES.values()], ignore_index=True)
    av_idx = av.set_index(["season", "gw", "element"])["asof_status"]

    rows = []
    hist_all = df.sort_values("match_date")     # team-match rows, both sides
    for s in SEASONS:
        for team, th in hist_all[hist_all["team"].notna()].groupby("team"):
            th_s = th[th["season"] == s]
            if len(th_s) == 0:
                continue
            vt = va[(va["season"] == s) & (va["team"] == team)]
            for q, C in cutoffs[s].items():
                prior = th[th["match_date"] < C]
                own, conc = prior["market_lambda"], prior["market_lambda_conceded"]
                sprior = prior[prior["season"] == s]
                rec = {"season": s, "team": team, "q": q,
                       "f_own_l5": own.tail(5).mean() if len(own) >= 5 else np.nan,
                       "f_own_l10": own.tail(10).mean() if len(own) >= 10 else np.nan,
                       "f_conc_l5": conc.tail(5).mean() if len(conc) >= 5 else np.nan,
                       "f_conc_l10": conc.tail(10).mean() if len(conc) >= 10 else np.nan,
                       "f_own_s2d": sprior["market_lambda"].mean()
                       if len(sprior) else np.nan,
                       "f_conc_s2d": sprior["market_lambda_conceded"].mean()
                       if len(sprior) else np.nan}
                # availability at the freeze gameweek's deadline
                if s in AV_FILES:
                    pm = vt[vt["kick_date"] < C]
                    if len(pm):
                        top5 = (pm.groupby("element")["minutes"].sum()
                                  .sort_values(ascending=False).head(5).index)
                        sts = [av_idx.get((s, label_at[s][q], e)) for e in top5]
                        found = [x for x in sts if isinstance(x, str)]
                        rec["f_av"] = (float(sum(1 for x in found
                                                 if x in UNAVAILABLE))
                                       if found else np.nan)
                    else:
                        rec["f_av"] = np.nan
                else:
                    rec["f_av"] = np.nan
                rows.append(rec)
    ft = pd.DataFrame(rows)
    return ft, pos_maps, label_at


def assemble_step(df, ft, pos_maps, label_at, dc, k):
    """The 19 features as they would look at horizon step k."""
    d = df[df["season"].isin(SEASONS)].copy()
    d["t_pos"] = [pos_maps[s][g] for s, g in zip(d["season"], d["gw"])]
    d["q"] = d["t_pos"] - (k - 1)
    d = d[d["q"] >= 1].copy()
    d["q_label"] = [label_at[s][q] for s, q in zip(d["season"], d["q"])]

    own = ft.rename(columns={
        "f_own_l5": "mh_own_l5", "f_own_l10": "mh_own_l10",
        "f_own_s2d": "mh_own_s2d", "f_conc_l5": "mh_conc_l5",
        "f_conc_l10": "mh_conc_l10", "f_conc_s2d": "mh_conc_s2d",
        "f_av": "av_top5_out"})
    opp = ft.rename(columns={
        "team": "opponent", "f_own_l5": "mh_opp_own_l5",
        "f_own_l10": "mh_opp_own_l10", "f_conc_l5": "mh_opp_conc_l5",
        "f_conc_l10": "mh_opp_conc_l10", "f_av": "av_top5_out_opp"})
    d = d.drop(columns=[c for c in FEATURES if c not in
                        ("is_home", "sch_rest_days", "sch_m14",
                         "sch_rest_days_opp", "sch_m14_opp")], errors="ignore")
    d = d.merge(own[["season", "team", "q", "mh_own_l5", "mh_own_l10",
                     "mh_own_s2d", "mh_conc_l5", "mh_conc_l10", "mh_conc_s2d",
                     "av_top5_out"]], on=["season", "team", "q"], how="left")
    d = d.merge(opp[["season", "opponent", "q", "mh_opp_own_l5",
                     "mh_opp_own_l10", "mh_opp_conc_l5", "mh_opp_conc_l10",
                     "av_top5_out_opp"]],
                on=["season", "opponent", "q"], how="left")

    # frozen DC: the cached fit for the freeze gameweek
    dco = dc.rename(columns={"attack": "dc_attack", "gw": "q_label"})
    dcd = dc.rename(columns={"team": "opponent", "defence": "dc_defence_opp",
                             "gw": "q_label"})
    d = d.merge(dco[["season", "q_label", "team", "dc_attack", "hadv"]],
                on=["season", "q_label", "team"], how="left")
    d = d.merge(dcd[["season", "q_label", "opponent", "dc_defence_opp"]],
                on=["season", "q_label", "opponent"], how="left")
    assert d["dc_attack"].notna().all(), f"frozen DC join failed at step {k}"
    d["dc_frozen_pred"] = np.exp(d["dc_attack"] + d["dc_defence_opp"]
                                 + d["hadv"] * d["is_home"])
    return d


def main():
    t0 = time.time()
    df = pd.read_parquet(DATA)
    dc = pd.read_parquet(DC_CACHE)
    print("building freeze tables (per season/team/gameweek position)...")
    ft, pos_maps, label_at = build_freeze_tables(df)
    print(f"  {len(ft)} freeze cells in {time.time()-t0:.0f}s")

    steps = {k: assemble_step(df, ft, pos_maps, label_at, dc, k)
             for k in STEPS}

    # common evaluation rows: valid at the stalest step, identical across steps
    s6 = steps[6]
    ok6 = s6[s6["mh_own_l10"].notna() & s6["mh_opp_own_l10"].notna()
             & (s6["season"].isin(VALID))]
    eval_ids = set(zip(ok6["match_id"], ok6["team"]))
    print(f"common evaluation rows (valid at step 6): {len(eval_ids)}")

    # variant A: study model per target season, trained on FRESH features
    fresh = df[(~df["burn_in"]) & (df["season"].isin(SEASONS))]
    models_a = {}
    for s in VALID:
        tr = fresh[fresh["season"] < s]
        mdl = lgb.LGBMRegressor(**FIXED, **CFG)
        mdl.fit(tr[FEATURES], tr["market_lambda"])
        models_a[s] = mdl

    per_step = {}
    for k in STEPS:
        dk = steps[k]
        dk = dk[[ (m, t) in eval_ids for m, t in zip(dk["match_id"], dk["team"]) ]]
        res_a, res_b, res_dc = {}, {}, {}
        for s in VALID:
            te = dk[dk["season"] == s]
            y = te["market_lambda"]
            res_a[s] = r2_mae(y, models_a[s].predict(te[FEATURES]))
            # variant B: trained on stale-at-k features of EARLIER seasons
            trb = steps[k]
            trb = trb[(trb["season"] < s) & trb["mh_own_l10"].notna()
                      & trb["mh_opp_own_l10"].notna()]
            mdl = lgb.LGBMRegressor(**FIXED, **CFG)
            mdl.fit(trb[FEATURES], trb["market_lambda"])
            res_b[s] = r2_mae(y, mdl.predict(te[FEATURES]))
            res_dc[s] = r2_mae(y, te["dc_frozen_pred"])
        per_step[k] = (res_a, res_b, res_dc)
        ma = np.mean([v[0] for v in res_a.values()])
        mb = np.mean([v[0] for v in res_b.values()])
        md = np.mean([v[0] for v in res_dc.values()])
        print(f"step {k}: mean R2  A(fresh-trained) {ma:.4f}  "
              f"B(stale-trained) {mb:.4f}  DC-frozen {md:.4f}", flush=True)

    print("\n=== per-season detail ===")
    for k in STEPS:
        res_a, res_b, res_dc = per_step[k]
        print(f"\n-- step {k} --")
        print(f"{'season':<10} {'A R2/MAE':>16} {'B R2/MAE':>16} "
              f"{'DCfroz R2/MAE':>16}")
        for s in VALID:
            print(f"{s:<10} {res_a[s][0]:>8.4f}/{res_a[s][1]:.4f} "
                  f"{res_b[s][0]:>8.4f}/{res_b[s][1]:.4f} "
                  f"{res_dc[s][0]:>8.4f}/{res_dc[s][1]:.4f}")

    print("\n=== crossover vs the frozen-DC fallback (mean over seasons) ===")
    for k in STEPS:
        res_a, res_b, res_dc = per_step[k]
        for name, res in [("A", res_a), ("B", res_b)]:
            m = np.mean([v[0] for v in res.values()])
            d = m - np.mean([v[0] for v in res_dc.values()])
            n_worse = sum(res[s][0] < res_dc[s][0] for s in VALID)
            print(f"  step {k} variant {name}: mean R2 {m:.4f}, vs DC-frozen "
                  f"{d:+.4f}, worse than DC in {n_worse}/8 seasons")
    print(f"\ndone in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
