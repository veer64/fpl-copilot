# audit_market_lambda_leakage.py
# INDEPENDENT leakage audit of data/d4_market_lambda_dataset.parquet.
#
# Deliberately does NOT trust the builder's audit columns or assert_no_leakage()
# -- those were written by the same code that built the features. Every check
# here either goes back to raw sources or perturbs the learning problem in a
# way that exposes a leak regardless of what the audit columns claim.
#
# Checks:
#   1 shuffle      : permute target within season, refit -> R2 must collapse
#   2 reconstruct  : recompute all 19 features by hand for 5 fixtures from raw
#   3 single       : each feature alone -> any single-feature R2 > ~0.7 is suspect
#   4 reversal     : train later->predict earlier vs forward, same test seasons
#   5 gap          : drop all market-history features -> R2 from the rest alone
#   6 dc-cutoff    : per-GW fit training window vs the GW's first match, raw dates
#   7 avail-timing : asof_news_added <= deadline_time, sampled timestamps
#
# Usage: uv run python eval/audit_market_lambda_leakage.py

import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot")
sys.path.insert(0, str(BASE))
from squad.dixon_coles import _implied_lambdas, _fit_dc_decay  # noqa: E402

DATA = BASE / "data" / "d4_market_lambda_dataset.parquet"
ODDS = BASE / "data" / "history" / "odds_all_seasons.parquet"
VAASTAV = BASE / "data" / "history" / "all_seasons_fixed.parquet"

ALIAS = {"Man United": "Man Utd", "Sheffield United": "Sheffield Utd",
         "Tottenham": "Spurs"}
UNAVAILABLE = {"i", "s", "u", "n"}
AV_FILES = {"2021-22": "availability_2122.parquet",
            "2022-23": "availability_2223.parquet",
            "2023-24": "availability_2324.parquet",
            "2024-25": "availability_2425.parquet",
            "2025-26": "availability_2526.parquet"}

FEATURES = [
    "mh_own_l5", "mh_own_l10", "mh_own_s2d",
    "mh_conc_l5", "mh_conc_l10", "mh_conc_s2d",
    "mh_opp_own_l5", "mh_opp_own_l10", "mh_opp_conc_l5", "mh_opp_conc_l10",
    "dc_attack", "dc_defence_opp", "is_home",
    "sch_rest_days", "sch_m14", "sch_rest_days_opp", "sch_m14_opp",
    "av_top5_out", "av_top5_out_opp",
]
MH = [f for f in FEATURES if f.startswith("mh_")]
VALID = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22",
         "2022-23", "2023-24", "2024-25"]
CFG = {"num_leaves": 15, "learning_rate": 0.03, "n_estimators": 300,
       "min_child_samples": 20}
FIXED = {"objective": "l2", "verbosity": -1, "n_jobs": -1, "seed": 42,
         "deterministic": True, "force_row_wise": True}


def r2(y, p):
    return 1 - float(((y - p) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())


def wf(df, feats, targets, ycol="market_lambda", backward=False):
    out = {}
    for s in targets:
        tr = df[df["season"] > s] if backward else df[df["season"] < s]
        if backward:
            tr = tr[tr["season"] != "2025-26"]     # sealed season: not even as train
        te = df[df["season"] == s]
        if len(tr) == 0:
            continue
        mdl = lgb.LGBMRegressor(**FIXED, **CFG)
        mdl.fit(tr[feats], tr[ycol])
        out[s] = (r2(te[ycol], mdl.predict(te[feats])), len(tr))
    return out


def load_raw():
    o = pd.read_parquet(ODDS)
    m = o[["Date", "HomeTeam", "AwayTeam", "season",
           "B365H", "B365D", "B365A"]].copy()
    m.columns = ["date", "home", "away", "season", "b365h", "b365d", "b365a"]
    m["match_date"] = pd.to_datetime(m["date"], format="mixed", dayfirst=True)
    m["home"] = m["home"].map(lambda t: ALIAS.get(t, t))
    m["away"] = m["away"].map(lambda t: ALIAS.get(t, t))
    return m.sort_values("match_date").reset_index(drop=True)


_lam_cache = {}


def match_lambdas(row):
    key = (row["season"], row["home"], row["away"])
    if key not in _lam_cache:
        inv = 1.0 / np.array([row["b365h"], row["b365d"], row["b365a"]])
        _lam_cache[key] = _implied_lambdas(*(inv / inv.sum()))
    return _lam_cache[key]


def team_history(m, team, before):
    """That team's matches strictly before `before`, oldest first, with own and
    conceded market lambda recomputed from the odds."""
    h = m[((m["home"] == team) | (m["away"] == team))
          & (m["match_date"] < before)].copy()
    own, conc = [], []
    for _, r in h.iterrows():
        lh, la = match_lambdas(r)
        is_h = r["home"] == team
        own.append(lh if is_h else la)
        conc.append(la if is_h else lh)
    h["own"], h["conc"] = own, conc
    return h


# ----------------------------------------------------------- check 1 ----

def check_shuffle(df):
    print("\n=== CHECK 1: shuffle test (target permuted within season) ===")
    rng = np.random.default_rng(7)
    sh = df.copy()
    sh["y_sh"] = (sh.groupby("season")["market_lambda"]
                    .transform(lambda s: rng.permutation(s.values)))
    res = wf(sh, FEATURES, VALID, ycol="y_sh")
    for s, (r, _) in res.items():
        print(f"  {s}: R2 {r:+.4f}")
    print(f"  mean: {np.mean([r for r, _ in res.values()]):+.4f}  "
          f"(pass requires ~0)")


# ----------------------------------------------------------- check 2 ----

def check_reconstruct(df, m):
    print("\n=== CHECK 2: future-blind reconstruction, 5 fixtures ===")
    va = pd.read_parquet(VAASTAV, columns=["season", "team", "element",
                                           "minutes", "kickoff_time", "GW"])
    va = va.dropna(subset=["team"])
    va["kick_date"] = pd.to_datetime(va["kickoff_time"], utc=True).dt.date

    av = pd.concat([pd.read_parquet(BASE / "data" / f,
                                    columns=["season", "gw", "element",
                                             "asof_status"])
                    for f in AV_FILES.values()], ignore_index=True)
    av_idx = av.set_index(["season", "gw", "element"])["asof_status"]

    teams = sorted(set(m["home"]) | set(m["away"]))
    rng = np.random.default_rng(11)
    picks = []
    for season in ["2017-18", "2019-20", "2021-22", "2023-24", "2025-26"]:
        pool = df[(df["season"] == season) & (~df["burn_in"])
                  & (df["gw"].between(15, 25))]
        picks.append(pool.iloc[int(rng.integers(len(pool)))])

    worst = 0.0
    for row in picks:
        season, team, opp = row["season"], row["team"], row["opponent"]
        mdate = pd.Timestamp(row["match_date"])
        rec = {}

        th = team_history(m, team, mdate)
        oh = team_history(m, opp, mdate)
        rec["mh_own_l5"] = th["own"].tail(5).mean()
        rec["mh_own_l10"] = th["own"].tail(10).mean()
        rec["mh_conc_l5"] = th["conc"].tail(5).mean()
        rec["mh_conc_l10"] = th["conc"].tail(10).mean()
        ts = th[th["season"] == season]
        rec["mh_own_s2d"] = ts["own"].mean()
        rec["mh_conc_s2d"] = ts["conc"].mean()
        rec["mh_opp_own_l5"] = oh["own"].tail(5).mean()
        rec["mh_opp_own_l10"] = oh["own"].tail(10).mean()
        rec["mh_opp_conc_l5"] = oh["conc"].tail(5).mean()
        rec["mh_opp_conc_l10"] = oh["conc"].tail(10).mean()

        # schedule, straight from raw dates
        rec["sch_rest_days"] = (mdate - th["match_date"].iloc[-1]).days
        rec["sch_m14"] = int((th["match_date"] >= mdate - pd.Timedelta(days=14)).sum())
        rec["sch_rest_days_opp"] = (mdate - oh["match_date"].iloc[-1]).days
        rec["sch_m14_opp"] = int((oh["match_date"] >= mdate - pd.Timedelta(days=14)).sum())

        # is_home from the raw fixture row
        fx = m[(m["season"] == season) & (m["match_date"] == mdate)
               & ((m["home"] == team) | (m["away"] == team))].iloc[0]
        rec["is_home"] = int(fx["home"] == team)

        # gw independently from vaastav, then the DC refit from raw
        gw = int(va[(va["season"] == season) & (va["team"] == team)
                    & (va["kick_date"] == mdate.date())]["GW"].iloc[0])
        ms = m[m["season"] == season].copy()
        ms["kd"] = ms["match_date"].dt.date
        gw_dates = ms.merge(
            va[(va["season"] == season)][["team", "kick_date", "GW"]]
            .drop_duplicates(), left_on=["home", "kd"],
            right_on=["team", "kick_date"])
        gw_first = pd.to_datetime(
            gw_dates[gw_dates["GW"] == gw]["match_date"]).min()
        train = (m[m["match_date"] < gw_first]
                 .merge(pd.read_parquet(ODDS)[["Date", "HomeTeam", "FTHG", "FTAG"]]
                        .assign(match_date=lambda d: pd.to_datetime(
                            d["Date"], format="mixed", dayfirst=True),
                            home=lambda d: d["HomeTeam"].map(
                                lambda t: ALIAS.get(t, t)))
                        [["match_date", "home", "FTHG", "FTAG"]],
                        on=["match_date", "home"], how="left")
                 .rename(columns={"match_date": "date_parsed",
                                  "FTHG": "home_goals", "FTAG": "away_goals"}))
        params, idx, nt = _fit_dc_decay(train, teams, gw_first, 365)
        rec["dc_attack"] = params[idx[team]]
        rec["dc_defence_opp"] = params[nt + idx[opp]]

        # availability from raw minutes + asof status
        for side, tname, col in [("team", team, "av_top5_out"),
                                 ("opp", opp, "av_top5_out_opp")]:
            if season in AV_FILES:
                vt = va[(va["season"] == season) & (va["team"] == tname)
                        & (va["kick_date"] < mdate.date())]
                top5 = (vt.groupby("element")["minutes"].sum()
                          .sort_values(ascending=False).head(5).index)
                sts = [av_idx.get((season, gw, e)) for e in top5]
                rec[col] = float(sum(1 for s_ in sts
                                     if isinstance(s_, str) and s_ in UNAVAILABLE))
            else:
                rec[col] = np.nan

        # recompute the TARGET too
        lh, la = match_lambdas(fx)
        rec_target = lh if rec["is_home"] else la

        diffs = {f: abs(rec[f] - row[f]) for f in FEATURES
                 if not (pd.isna(rec[f]) and pd.isna(row[f]))}
        tdiff = abs(rec_target - row["market_lambda"])
        mx = max(list(diffs.values()) + [tdiff])
        worst = max(worst, mx)
        status = "MATCH" if mx < 1e-6 else "MISMATCH"
        print(f"  {season} {team} vs {opp} ({mdate.date()}): {status} "
              f"(max |diff| {mx:.2e}, target |diff| {tdiff:.2e})")
        if mx >= 1e-6:
            for f, d in sorted(diffs.items(), key=lambda t: -t[1])[:6]:
                print(f"      {f}: dataset {row[f]:.6f} recomputed {rec[f]:.6f}")
    print(f"  worst |diff| across all fixtures/features: {worst:.2e}")


# ----------------------------------------------------------- check 3 ----

def check_single(df):
    print("\n=== CHECK 3: single-feature R2 (walk-forward, validation seasons) ===")
    rows = []
    for f in FEATURES:
        res = wf(df, [f], VALID)
        rows.append((f, np.mean([r for r, _ in res.values()])))
    for f, r in sorted(rows, key=lambda t: -t[1]):
        flag = "  <-- SUSPECT (> 0.7)" if r > 0.7 else ""
        print(f"  {f:<20} {r:+.4f}{flag}")


# ----------------------------------------------------------- check 4 ----

def check_reversal(df):
    print("\n=== CHECK 4: time reversal (2025-26 excluded even from training) ===")
    targets = VALID[:-1]                     # 2024-25 has no later non-sealed train
    fwd = wf(df, FEATURES, targets)
    bwd = wf(df, FEATURES, targets, backward=True)
    print(f"  {'season':<10} {'fwd R2':>8} {'n_tr':>6} {'bwd R2':>8} {'n_tr':>6}")
    for s in targets:
        print(f"  {s:<10} {fwd[s][0]:>8.4f} {fwd[s][1]:>6} "
              f"{bwd[s][0]:>8.4f} {bwd[s][1]:>6}")
    print(f"  mean fwd {np.mean([fwd[s][0] for s in targets]):.4f}  "
          f"mean bwd {np.mean([bwd[s][0] for s in targets]):.4f}")


# ----------------------------------------------------------- check 5 ----

def check_gap(df):
    print("\n=== CHECK 5: gap test (no market-history features) ===")
    feats = [f for f in FEATURES if f not in MH]
    res = wf(df, feats, VALID)
    for s, (r, _) in res.items():
        print(f"  {s}: R2 {r:.4f}")
    print(f"  mean without market history: "
          f"{np.mean([r for r, _ in res.values()]):.4f}  "
          f"(full model was 0.8757; if these approach 0.85 something is wrong)")


# ----------------------------------------------------------- check 6 ----

def check_dc_cutoff(df, m):
    print("\n=== CHECK 6: DC cutoff vs gameweek matches, raw dates ===")
    va = pd.read_parquet(VAASTAV, columns=["season", "team", "kickoff_time", "GW"])
    va = va.dropna(subset=["team"])
    va["kick_date"] = pd.to_datetime(va["kickoff_time"], utc=True).dt.date
    fx = va.drop_duplicates(["season", "team", "kick_date"])
    mm = m.merge(fx.rename(columns={"team": "home", "GW": "gw"})
                 [["season", "home", "kick_date", "gw"]],
                 left_on=["season", "home", m["match_date"].dt.date.rename("kd")],
                 right_on=["season", "home", "kick_date"])
    rng = np.random.default_rng(3)
    cells = mm[["season", "gw"]].drop_duplicates().sample(10, random_state=3)
    ok = True
    for _, c in cells.iterrows():
        gwm = mm[(mm["season"] == c["season"]) & (mm["gw"] == c["gw"])]
        first = gwm["match_date"].min()
        train = mm[mm["match_date"] < first]
        overlap = len(set(train.index) & set(gwm.index))
        tmax = train["match_date"].max()
        stat = "OK" if (overlap == 0 and (pd.isna(tmax) or tmax < first)) else "FAIL"
        ok &= stat == "OK"
        print(f"  {c['season']} GW{int(c['gw']):>2}: train_max {tmax.date() if pd.notna(tmax) else 'none':} "
              f"< first_match {first.date()}  own-GW matches in train: {overlap}  [{stat}]")
    print(f"  {'ALL OK' if ok else 'FAILURES PRESENT'}")


# ----------------------------------------------------------- check 7 ----

def check_avail_timing():
    print("\n=== CHECK 7: availability asof timing vs deadline ===")
    for season, fname in AV_FILES.items():
        a = pd.read_parquet(BASE / "data" / fname)
        a["deadline_time"] = pd.to_datetime(a["deadline_time"], utc=True)
        a["asof_news_added"] = pd.to_datetime(a["asof_news_added"], utc=True)
        stamped = a[a["asof_news_added"].notna()]
        viol = (stamped["asof_news_added"] > stamped["deadline_time"]).sum()
        flips = (a["status"] != a["asof_status"]).sum()
        print(f"  {season}: {len(stamped)} stamped rows, "
              f"asof_news_added > deadline: {viol}, status flips: {flips}")
    a = pd.read_parquet(BASE / "data" / AV_FILES["2024-25"])
    a["deadline_time"] = pd.to_datetime(a["deadline_time"], utc=True)
    a["asof_news_added"] = pd.to_datetime(a["asof_news_added"], utc=True)
    a["news_added"] = pd.to_datetime(a["news_added"], utc=True)
    fl = a[(a["status"] != a["asof_status"])].head(5)
    print("  sample flip rows (2024-25) -- snapshot vs recovered deadline state:")
    for _, r in fl.iterrows():
        print(f"    gw{int(r['gw']):>2} el{int(r['element']):>4}  "
              f"snap_status {r['status']} -> asof {r['asof_status']}  "
              f"news_added {r['asof_news_added']}  deadline {r['deadline_time']}")


if __name__ == "__main__":
    t0 = time.time()
    frame = pd.read_parquet(DATA)
    usable = frame[~frame["burn_in"]].copy()
    raw = load_raw()
    check_shuffle(usable)
    check_reconstruct(frame, raw)
    check_single(usable)
    check_reversal(usable)
    check_gap(usable)
    check_dc_cutoff(usable, raw)
    check_avail_timing()
    print(f"\naudit complete in {time.time()-t0:.0f}s")
