"""Data audit of what is knowable at horizon step k: fixture-calendar stability inside the walkforward horizon, suspensions derivable from vaastav cards vs availability status 's', status-'n' (international/AFCON) lead times, return-date language in fplcache news text, and same-position squad competition at cutoff. Result of record: Logs/horizon_minutes_scoping_log.md section 3. Read-only audit; no parser built."""
# Task 3: data audit -- what is actually knowable at step k. Read-only.
import re
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent  # repo root; rescued 2026-08-24 from a hardcoded absolute path
SEASONS = {"2023-24": "2324", "2024-25": "2425", "2025-26": "2526"}
hist_all = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet",
                           columns=["season", "element", "GW", "round", "team", "position",
                                    "minutes", "yellow_cards", "red_cards", "kickoff_time"])

print("=============== (a) FIXTURE CALENDAR in the walkforward, steps 1-5 ===============")
for season, short in SEASONS.items():
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "n_fixtures", "horizon_step"])
    own = wf[wf["horizon_step"] == 0].set_index(["gw", "element"])["n_fixtures"]
    line = []
    for k in range(1, 6):
        s = wf[wf["horizon_step"] == k].set_index(["gw", "element"])["n_fixtures"]
        common = s.index.intersection(own.index)
        agree = float((s.loc[common] == own.loc[common]).mean())
        dgw_own = own.loc[common] >= 2
        dgw_seen = float((s.loc[common][dgw_own] >= 2).mean()) if dgw_own.any() else np.nan
        pres = len(common) / len(own)
        line.append(f"k={k}: rows present {pres:.0%}, n_fixtures agrees {agree:.1%}, DGW already a DGW {dgw_seen:.0%}")
    print(f"  {season}: " + " | ".join(line))
print("  (n_fixtures at step k is what the model believed at that cutoff; agreement with the own-cutoff value "
      "is the calendar's stability inside the horizon)")

print("\n=============== (b) SUSPENSIONS derivable from cards ===============")
for season, short in SEASONS.items():
    h = hist_all[hist_all["season"] == season].copy()
    for c in ("minutes", "yellow_cards", "red_cards"):
        h[c] = pd.to_numeric(h[c], errors="coerce").fillna(0)
    h = h.sort_values(["element", "kickoff_time"])
    # team match index per fixture (1..38) for the yellow thresholds
    h["match_no"] = h.groupby("element").cumcount() + 1
    h["cum_y"] = h.groupby("element")["yellow_cards"].cumsum()
    derived = set()   # (gw, element) predicted banned for the NEXT gw
    for e, g in h.groupby("element"):
        g = g.sort_values("kickoff_time")
        gws = g["round"].tolist(); cy = g["cum_y"].tolist(); mn = g["match_no"].tolist(); rc = g["red_cards"].tolist()
        for i in range(len(g) - 1):
            ban = rc[i] >= 1
            if cy[i] >= 5 and mn[i] <= 19 and (i == 0 or cy[i - 1] < 5): ban = True
            if cy[i] >= 10 and mn[i] <= 32 and (i == 0 or cy[i - 1] < 10): ban = True
            if cy[i] >= 15 and (i == 0 or cy[i - 1] < 15): ban = True
            if ban:
                derived.add((int(gws[i + 1]), int(e)))
    av = pd.read_parquet(REPO / "data" / f"availability_{short}.parquet",
                         columns=["gw", "element", "asof_status"])
    susp = set(map(tuple, av.loc[av["asof_status"] == "s", ["gw", "element"]].astype(int).values))
    mins = h.groupby(["round", "element"])["minutes"].sum()
    zero = sum(1 for k in derived if mins.get(k, np.nan) == 0)
    print(f"  {season}: derived bans {len(derived)}; availability status 's' player-gws {len(susp)}; "
          f"overlap {len(derived & susp)} -> coverage of 's' {len(derived & susp) / max(len(susp), 1):.0%}, "
          f"precision vs 's' {len(derived & susp) / max(len(derived), 1):.0%}; derived bans that played 0 min "
          f"{zero}/{len(derived)} ({zero / max(len(derived), 1):.0%})")
print("  (thresholds: 5 yellows within the first 19 matches -> 1 ban; 10 within 32 -> 2; 15 -> 3; any red -> 1. "
      "Cup cards and ban lengths for reds are not on disk.)")

print("\n=============== (c) AFCON / international absence: status 'n' lead time ===============")
for season, short in SEASONS.items():
    av = pd.read_parquet(REPO / "data" / f"availability_{short}.parquet")
    av["deadline_time"] = pd.to_datetime(av["deadline_time"], utc=True)
    av["asof_news_added"] = pd.to_datetime(av["asof_news_added"], utc=True, errors="coerce")
    n = av[av["asof_status"] == "n"].sort_values(["element", "gw"])
    if not len(n):
        print(f"  {season}: no status-n rows"); continue
    # first gw of each run of 'n'
    n["run_start"] = n.groupby("element")["gw"].diff().fillna(99) > 1
    starts = n[n["run_start"]]
    lead = (starts["deadline_time"] - starts["asof_news_added"]).dt.total_seconds() / 86400
    prev = av.set_index(["element", "gw"])["asof_status"]
    seen_prev = [prev.get((e, g - 1), None) for e, g in zip(starts["element"], starts["gw"])]
    seen_prev_n = sum(1 for s in seen_prev if s == "n")
    runlen = n.groupby("element").size()
    mins = hist_all[hist_all["season"] == season].groupby(["round", "element"])["minutes"].sum()
    played = sum(1 for e, g in zip(n["element"], n["gw"]) if pd.to_numeric(mins.get((g, e), 0)) > 0)
    print(f"  {season}: status-n rows {len(n)} ({n['element'].nunique()} players, {len(starts)} absence starts); "
          f"played >0 min while 'n': {played}; lead time (deadline - news_added) at absence start: "
          f"min {lead.min():.1f}d, median {lead.median():.1f}d, max {lead.max():.1f}d; "
          f"flagged >= 7d before the deadline: {(lead >= 7).mean():.0%}; already 'n' at the PREVIOUS deadline: {seen_prev_n}/{len(starts)}; "
          f"run length median {runlen.median():.0f} gws")
    gw_counts = starts["gw"].value_counts().sort_index()
    print(f"     absence starts by gw: " + ", ".join(f"GW{g}:{c}" for g, c in gw_counts.items()))

print("\n=============== (d) NEWS TEXT: return-date language (read-only audit) ===============")
MONTH = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
PAT = {"explicit date (day + month)": re.compile(r"\b\d{1,2}\s+" + MONTH[2:], re.I),
       "month named": re.compile(MONTH, re.I),
       "'expected back' / 'return'": re.compile(r"expected back|return|back in", re.I),
       "'unknown return date'": re.compile(r"unknown return", re.I),
       "chance % phrasing": re.compile(r"\d{1,3}% chance", re.I),
       "suspended / ban": re.compile(r"suspend|ban", re.I),
       "international / afcon": re.compile(r"international|afcon|nations|cup of nations|duty", re.I)}
for season, short in SEASONS.items():
    av = pd.read_parquet(REPO / "data" / f"availability_{short}.parquet", columns=["asof_status", "asof_news"])
    txt = av["asof_news"].fillna("").astype(str)
    nonempty = txt.str.len() > 0
    print(f"  {season}: rows {len(av):,}; non-empty news {nonempty.sum():,} ({nonempty.mean():.1%})")
    flagged = av[av["asof_status"].isin(["i", "d", "s", "n"])]
    ft = flagged["asof_news"].fillna("").astype(str)
    print(f"     among flagged (i/d/s/n) rows n={len(flagged):,}: non-empty {(ft.str.len() > 0).mean():.0%}; "
          + "; ".join(f"{k} {ft.str.contains(p).mean():.0%}" for k, p in PAT.items()))
    ex = ft[ft.str.contains(PAT["explicit date (day + month)"])].drop_duplicates().head(3).tolist()
    print(f"     examples with explicit dates: {ex}")

print("\n=============== (e) SQUAD COMPETITION: same-position teammates unavailable at cutoff ===============")
for season, short in SEASONS.items():
    av = pd.read_parquet(REPO / "data" / f"availability_{short}.parquet", columns=["gw", "element", "asof_status"])
    h = hist_all[hist_all["season"] == season][["element", "GW", "team", "position"]].drop_duplicates(["element", "GW"])
    m = av.merge(h, left_on=["element", "gw"], right_on=["element", "GW"], how="inner")
    m["unav"] = m["asof_status"].isin(["i", "s", "n", "d"])
    m = m[m["position"] != "AM"]
    grp = m.groupby(["gw", "team", "position"])["unav"].sum()
    sq = m.groupby(["gw", "team", "position"]).size()
    print(f"  {season}: joined {len(m):,} of {len(av):,} availability rows to (team, position); positions {sorted(m['position'].unique())}; "
          f"squad size per (team, position) median {sq.median():.0f} (DEF {sq.xs('DEF', level=2).median():.0f}, MID {sq.xs('MID', level=2).median():.0f}); "
          f"same-position teammates unavailable at cutoff: mean {grp.mean():.2f}, share of (gw,team,pos) with >=1: {(grp >= 1).mean():.0%}, >=2: {(grp >= 2).mean():.0%}")
print("  (computable at cutoff k for the CURRENT gw only -- asof flags carry no future dates; "
      "for step k>0 the feature is an extrapolation. Position labels are FPL's four classes: a 'DEF' covers "
      "full-backs and centre-backs, a 'MID' covers holders and wingers.)")
