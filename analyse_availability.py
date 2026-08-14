#!/usr/bin/env python
"""
Characterise the availability signal extracted by build_availability.py.

Answers, in order:
  1. as-of provenance — how far before each deadline the snapshot actually lands
  2. element-ID reconciliation against data/walkforward_h6_2526.parquet
  3. status distribution, and how much of `u` is a departure rather than an injury
  4. realized P(0 mins) / P(60+) conditional on pre-deadline state
  5. the number that matters — how wrong the minutes model is on the FIRST gameweek
     of an absence, the case its backward-looking history cannot see

Read-only: touches no model code, writes nothing.

Usage: uv run python analyse_availability.py [--asof]
       --asof uses the deadline-accurate reconstruction instead of the raw snapshot.
"""

import argparse
import re

import pandas as pd

AVAIL = "data/availability_2526.parquet"
WALKFWD = "data/walkforward_h6_2526.parquet"
HISTORY = "data/history/all_seasons_fixed.parquet"
SEASON = "2025-26"

# FPL status codes. `d` is the only partial state; the rest are binary.
OUT_STATUSES = {"i", "s", "u", "n"}
STATUS_LABEL = {
    "a": "a  available",
    "d": "d  doubtful",
    "i": "i  injured",
    "s": "s  suspended",
    "u": "u  unavailable",
    "n": "n  not in squad",
}
# A departure is permanent and knowable; a knock is temporary. They should never
# share a feature.
DEPARTURE = re.compile(
    r"joined|signed by|on loan to|loan|permanently|departed the club|transferred", re.I
)


def rule(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def load(use_asof: bool):
    av = pd.read_parquet(AVAIL)
    if use_asof:
        for c in ("status", "chance_of_playing_this_round",
                  "chance_of_playing_next_round", "news", "news_added"):
            av[c] = av[f"asof_{c}"]

    wf = pd.read_parquet(WALKFWD)
    wf = wf[wf.horizon_step == 0]  # prediction made at that gameweek's own deadline

    hist = pd.read_parquet(HISTORY, columns=["season", "element", "GW", "minutes", "total_points"])
    hist = hist[hist.season == SEASON]
    # One row per player-fixture in the source; double gameweeks must be summed.
    actual = (hist.groupby(["GW", "element"], as_index=False)
                  .agg(minutes=("minutes", "sum"), points=("total_points", "sum"))
                  .rename(columns={"GW": "gw"}))
    return av, wf, actual


def section_provenance(av):
    rule("1. AS-OF PROVENANCE — gap between snapshot and deadline")
    g = av.groupby("gw").agg(
        snapshot=("snapshot_time", "first"),
        deadline=("deadline_time", "first"),
        hours=("hours_before_deadline", "first"),
        players=("element", "size"),
    )
    print(f"min={g.hours.min():.2f}h  median={g.hours.median():.2f}h  "
          f"mean={g.hours.mean():.2f}h  max={g.hours.max():.2f}h")
    print(f"gameweeks with gap > 6h: {(g.hours > 6).sum()}")
    print("\nlargest five gaps:")
    print(g.sort_values("hours", ascending=False).head(5).to_string())
    print("\nsmallest five gaps:")
    print(g.sort_values("hours").head(5).to_string())

    late = av[av.asof_source == "late_news"]
    print(f"\nnews published inside the blind window (after snapshot, before deadline): "
          f"{len(late)} rows across {late.gw.nunique()} gameweeks")
    flip = late[(late.status == "a") & (late.asof_status != "a")]
    print(f"  of which flip status a -> not-a: {len(flip)}")
    print(late.groupby("gw").size().rename("late_news").to_frame().T.to_string())


def section_ids(av, wf):
    rule("2. ELEMENT-ID RECONCILIATION vs walkforward_h6_2526.parquet")
    ea, ew = set(av.element), set(wf.element)
    print(f"elements: availability={len(ea)}  walkforward={len(ew)}  "
          f"intersection={len(ea & ew)}")
    print(f"  walkforward-only: {sorted(ew - ea)}")
    print(f"  availability-only: {sorted(ea - ew)}")

    pa, pw = set(zip(av.gw, av.element)), set(zip(wf.gw, wf.element))
    only_w = pd.DataFrame(sorted(pw - pa), columns=["gw", "element"])
    only_a = pd.DataFrame(sorted(pa - pw), columns=["gw", "element"])
    print(f"\n(gw, element) pairs: availability={len(pa)}  walkforward={len(pw)}")
    print(f"  in walkforward, not in availability: {len(only_w)} "
          f"({only_w.element.nunique()} distinct elements)")
    print(f"    -> registered by FPL after that gameweek's deadline; first-appearance "
          f"rows only: {(only_w.groupby('element').size() == 1).all()}")
    print(f"  in availability, not in walkforward: {len(only_a)}, "
          f"gameweeks {sorted(only_a.gw.unique())}  <- blank gameweeks, no fixture")


def section_status(av):
    rule("3. STATUS DISTRIBUTION, AND WHAT `u` ACTUALLY MEANS")
    tot = av.status.value_counts()
    share = (tot / len(av) * 100).round(2)
    print(pd.DataFrame({"rows": tot, "pct": share})
          .rename(index=STATUS_LABEL).to_string())

    u = av[av.status == "u"].copy()
    u["departure"] = u.news.fillna("").str.contains(DEPARTURE)
    print(f"\n`u` rows: {len(u)} across {u.element.nunique()} players")
    print(f"  departure (loan / permanent transfer / released): "
          f"{u.departure.sum()} ({u.departure.mean() * 100:.1f}%), "
          f"{u[u.departure].element.nunique()} players")
    print(f"  everything else: {(~u.departure).sum()} "
          f"({u[~u.departure].element.nunique()} players)")
    if (~u.departure).any():
        print(u[~u.departure].news.value_counts().head(10).to_string())

    i = av[av.status == "i"]
    print(f"\nfor contrast, `i` rows: {len(i)} across {i.element.nunique()} players "
          f"— none match the departure pattern: "
          f"{(~i.news.fillna('').str.contains(DEPARTURE)).all()}")

    print("\nper-gameweek counts by status:")
    piv = av.pivot_table(index="gw", columns="status", values="element",
                         aggfunc="size", fill_value=0)
    piv["not_a"] = piv.drop(columns="a").sum(axis=1)
    piv["pct_not_a"] = (piv["not_a"] / piv.sum(axis=1) * 100).round(1)
    print(piv.to_string())


def outcome_table(df, by):
    g = df.groupby(by, dropna=False)
    return pd.DataFrame({
        "n": g.size(),
        "players": g["element"].nunique(),
        "p_zero_mins": g["minutes"].apply(lambda s: (s == 0).mean()).round(3),
        "p_60plus": g["minutes"].apply(lambda s: (s >= 60).mean()).round(3),
        "mean_mins": g["minutes"].mean().round(1),
        "mean_pts": g["points"].mean().round(2),
    })


def section_outcomes(av, actual):
    rule("4. REALIZED OUTCOMES CONDITIONAL ON PRE-DEADLINE STATE")
    df = av.merge(actual, on=["gw", "element"], how="inner")
    print(f"joined {len(df):,} of {len(av):,} availability rows to 2025-26 actuals "
          f"(rest are blank gameweeks / unregistered)")

    print("\nby status:")
    t = outcome_table(df, "status")
    print(t.rename(index=STATUS_LABEL).to_string())

    print("\nby chance_of_playing_this_round (null = no news on file):")
    print(outcome_table(df, "chance_of_playing_this_round").to_string())

    print("\n`u` split by departure vs other:")
    u = df[df.status == "u"].copy()
    u["kind"] = u.news.fillna("").str.contains(DEPARTURE).map(
        {True: "departure", False: "other"})
    print(outcome_table(u, "kind").to_string())

    print("\nstatus x chance_of_playing_this_round (p_zero_mins, n in brackets):")
    cross = df.pivot_table(index="status", columns="chance_of_playing_this_round",
                           values="minutes", aggfunc=[lambda s: (s == 0).mean(), "size"],
                           dropna=False)
    cross.columns = [f"{'p0' if a.startswith('<') else 'n'}_{b}" for a, b in cross.columns]
    print(cross.round(3).to_string())


def section_first_gw(av, wf, actual):
    rule("5. THE FIRST GAMEWEEK OF AN ABSENCE — where the model is blind")
    av = av.sort_values(["element", "gw"]).copy()
    av["is_out"] = av.status.isin(OUT_STATUSES)
    av["departure"] = av.news.fillna("").str.contains(DEPARTURE)
    av["prev_out"] = av.groupby("element")["is_out"].shift()
    av["prev_gw"] = av.groupby("element")["gw"].shift()
    # A new absence: out now, present and not-out at the previous deadline. GW1 has no
    # previous deadline, so it can never qualify — noted below.
    av["new_out"] = av.is_out & (av.prev_out == False) & (av.prev_gw == av.gw - 1)

    df = (av.merge(wf[["gw", "element", "name", "e_points", "e_minutes", "p_start", "p60"]],
                   on=["gw", "element"], how="inner")
            .merge(actual, on=["gw", "element"], how="inner"))
    df["pts_error"] = df.e_points - df.points
    df["mins_error"] = df.e_minutes - df.minutes

    base = df[~df.is_out]
    new = df[df.new_out]
    ongoing = df[df.is_out & ~df.new_out]

    rows = []
    for label, sub in [("available/doubtful (baseline)", base),
                       ("absence, FIRST gameweek", new),
                       ("absence, FIRST gw — injury/susp only", new[~new.departure]),
                       ("absence, FIRST gw — departures", new[new.departure]),
                       ("absence, ongoing (model has zeros)", ongoing),
                       ("absence, ongoing — injury/susp", ongoing[~ongoing.departure]),
                       ("absence, ongoing — departures", ongoing[ongoing.departure])]:
        if not len(sub):
            continue
        rows.append({
            "case": label,
            "n": len(sub),
            "pred_mins": round(sub.e_minutes.mean(), 1),
            "act_mins": round(sub.minutes.mean(), 1),
            "mins_err": round(sub.mins_error.mean(), 1),
            "pred_pts": round(sub.e_points.mean(), 2),
            "act_pts": round(sub.points.mean(), 2),
            "pts_err": round(sub.pts_error.mean(), 2),
            "p_zero_mins": round((sub.minutes == 0).mean(), 3),
            "total_pts_overpred": round(sub.pts_error.sum(), 0),
        })
    print(pd.DataFrame(rows).to_string(index=False))

    print("\nfirst-gameweek absences by gameweek (injury/suspension only):")
    ni = new[~new.departure]
    per = ni.groupby("gw").agg(n=("element", "size"),
                               pred_pts=("e_points", "mean"),
                               overpred=("pts_error", "sum"))
    per["pred_pts"] = per.pred_pts.round(2)
    per["overpred"] = per.overpred.round(1)
    print(per.to_string())
    early = per[per.index <= 7]
    print(f"\nGW1-7: {early.n.sum()} cases, {early.overpred.sum():.0f} pts over-predicted")
    print(f"GW8+:  {per[per.index > 7].n.sum()} cases, "
          f"{per[per.index > 7].overpred.sum():.0f} pts over-predicted")

    # Raw over-prediction counts every fringe player. What actually costs points is a
    # player the optimiser would have picked, so re-cut on predicted-points thresholds.
    print("\nsame cases, restricted to squad-relevant predictions:")
    thr = []
    for t in (0.0, 2.0, 3.0, 4.0):
        s = ni[ni.e_points >= t]
        thr.append({"e_points >=": t, "n": len(s), "pred_pts": round(s.e_points.mean(), 2),
                    "act_pts": round(s.points.mean(), 2),
                    "total_overpred": round(s.pts_error.sum(), 0),
                    "n_gw1_7": (s.gw <= 7).sum(),
                    "overpred_gw1_7": round(s[s.gw <= 7].pts_error.sum(), 0)})
    print(pd.DataFrame(thr).to_string(index=False))

    print("\nworst individual first-gameweek misses (injury/suspension):")
    cols = ["gw", "name", "status", "chance_of_playing_this_round", "e_minutes",
            "e_points", "minutes", "points", "pts_error"]
    print(ni.nlargest(15, "pts_error")[cols].round(2).to_string(index=False))

    print("\nNOTE: GW1 is excluded by construction — no previous deadline to change from. "
          "Players already flagged at the GW1 deadline are counted here:")
    gw1 = df[(df.gw == 1) & df.is_out]
    if len(gw1):
        print(f"  {len(gw1)} flagged at GW1, predicted {gw1.e_points.mean():.2f} pts, "
              f"actual {gw1.points.mean():.2f}, over-prediction {gw1.pts_error.sum():.0f} pts total")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", action="store_true",
                    help="use the deadline-accurate reconstruction (asof_* columns)")
    args = ap.parse_args()
    print(f"source: {'asof_* reconstruction' if args.asof else 'raw pre-deadline snapshot'}")

    av, wf, actual = load(args.asof)
    section_provenance(av)
    section_ids(av, wf)
    section_status(av)
    section_outcomes(av, actual)
    section_first_gw(av, wf, actual)


if __name__ == "__main__":
    main()
