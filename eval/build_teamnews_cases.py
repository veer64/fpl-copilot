# build_teamnews_cases.py
# Team-news investigation, STEP 1 (of 5): the fixed case list.
#
# Reconstructs the "52 cases" from on-disk artefacts (the original analysis
# lived in a discarded scratchpad): every squad-gameweek in the three d45
# no-chip baseline paths (data/p1/p1log_{tag}_base.parquet -- same
# deterministic paths as the sweep d45 baselines) where the OWNED player was
# predicted >= 60 minutes at that gameweek's own cutoff and played 0.
#
# Per case: identifiers, predictions, captaincy, deadline (UTC + machine
# local), the asof availability row (status / chance / news / news stamp),
# minutes in gw-3..gw+3, and fixture context from the team's own calendar
# (midweek kickoff, days since previous / to next team match, post-break
# flag). First-pass grouping by STATED heuristics on this evidence only --
# no external news is fetched here (steps 2-3 do that against this fixed
# target list).
#
# Grouping rules (precedence order; each case gets exactly one):
#   flagged_at_deadline : asof_status != 'a' (the prior analysis says zero)
#   injury_emerging     : played 0 in gw+1 as well -- an absence STARTING
#                         here looks like a late fitness call / knock; the
#                         class least likely to be publicly signalled early
#   post_break_call     : returned next week; team's previous match >= 13
#                         days earlier (international/season break)
#   rotation_congested  : returned next week; midweek kickoff or a <= 4-day
#                         turnaround on either side
#   tactical_bench      : returned next week; no congestion, no break
#   unclear             : anything left (e.g. season-end truncation)
#
# Outputs: data/teamnews/case_list.parquet + Logs/teamnews_case_list.md
# Usage: uv run python eval/build_teamnews_cases.py

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "teamnews"
SEASONS = {"2023-24": ("2023_24", "2324"), "2024-25": ("2024_25", "2425"),
           "2025-26": ("2025_26", "2526")}

rows = []
for season, (tag, av_tag) in SEASONS.items():
    log = pd.read_parquet(REPO / "data" / "p1" / f"p1log_{tag}_base.parquet")
    log["elements"] = log["elements"].map(json.loads)
    wf = pd.read_parquet(
        REPO / "data" / f"walkforward_h6_{tag}.parquet",
        columns=["cutoff", "gw", "element", "name", "position", "team",
                 "e_minutes", "e_points", "minutes"])
    own = wf[wf["cutoff"] == wf["gw"]].copy()
    act = wf.drop_duplicates(subset=["gw", "element"]).copy()
    act["minutes"] = pd.to_numeric(act["minutes"], errors="coerce").fillna(0)
    mins = act.set_index(["gw", "element"])["minutes"]
    av = pd.read_parquet(REPO / "data" / f"availability_{av_tag}.parquet") \
        .set_index(["gw", "element"])
    # team calendar from vaastav (kickoff_time per team-gw; DGWs deduped to
    # first kickoff for the weekday flag, min/max for gaps)
    hist = pd.read_parquet(REPO / "data" / "history" / "all_seasons_fixed.parquet")
    hist = hist[hist["season"] == season].copy()
    hist["kickoff_time"] = pd.to_datetime(hist["kickoff_time"], utc=True)
    cal = (hist.groupby(["team", "round"])["kickoff_time"]
           .agg(["min", "max"]).reset_index()
           .rename(columns={"round": "gw", "min": "ko_first", "max": "ko_last"}))
    cal = cal.sort_values(["team", "gw"])
    cal["prev_ko"] = cal.groupby("team")["ko_last"].shift(1)
    cal["next_ko"] = cal.groupby("team")["ko_first"].shift(-1)

    for r in log.itertuples():
        gw = int(r.gw)
        own_gw = own[own["gw"] == gw].set_index("element")
        for e in r.elements:
            if e not in own_gw.index:
                continue
            em = own_gw.loc[e, "e_minutes"]
            if pd.isna(em) or float(em) < 60:
                continue
            if float(mins.get((gw, e), 0)) != 0:
                continue
            name = own_gw.loc[e, "name"]
            team = own_gw.loc[e, "team"]
            arow = av.loc[(gw, e)] if (gw, e) in av.index else None
            crow = cal[(cal["team"] == team) & (cal["gw"] == gw)]
            ko = crow["ko_first"].iloc[0] if len(crow) else pd.NaT
            prev_ko = crow["prev_ko"].iloc[0] if len(crow) else pd.NaT
            next_ko = crow["next_ko"].iloc[0] if len(crow) else pd.NaT
            days_prev = ((ko - prev_ko).days if pd.notna(ko)
                         and pd.notna(prev_ko) else None)
            days_next = ((next_ko - ko).days if pd.notna(ko)
                         and pd.notna(next_ko) else None)
            midweek = bool(ko.dayofweek in (1, 2, 3)) if pd.notna(ko) else None
            m = {f"min_gw{o:+d}": float(mins.get((gw + o, e), float("nan")))
                 for o in (-3, -2, -1, 1, 2, 3)}
            deadline = arow["deadline_time"] if arow is not None else pd.NaT
            rows.append({
                "season": season, "gw": gw, "player": name, "team": team,
                "element": int(e),
                "e_minutes": round(float(em), 1),
                "e_points": round(float(own_gw.loc[e, "e_points"]), 2),
                "actual_minutes": 0,
                "captained": bool(r.captain == name),
                "deadline_utc": deadline,
                "deadline_local": (deadline.to_pydatetime().astimezone()
                                   .strftime("%Y-%m-%d %H:%M %Z")
                                   if pd.notna(deadline) else None),
                "asof_status": arow["asof_status"] if arow is not None else None,
                "asof_chance": (arow["asof_chance_of_playing_this_round"]
                                if arow is not None else None),
                "asof_news": arow["asof_news"] if arow is not None else None,
                "asof_news_added": (arow["asof_news_added"]
                                    if arow is not None else pd.NaT),
                **m,
                "kickoff_utc": ko, "midweek": midweek,
                "days_since_prev_match": days_prev,
                "days_to_next_match": days_next,
            })

df = pd.DataFrame(rows).sort_values(["season", "gw", "player"]) \
    .reset_index(drop=True)


def group(r):
    if r["asof_status"] is not None and r["asof_status"] != "a":
        return "flagged_at_deadline"
    nxt = r["min_gw+1"]
    if pd.isna(nxt):
        return "unclear"
    if nxt == 0:
        return "injury_emerging"
    if r["days_since_prev_match"] is not None \
            and r["days_since_prev_match"] >= 13:
        return "post_break_call"
    if (r["midweek"] is True
            or (r["days_since_prev_match"] is not None
                and r["days_since_prev_match"] <= 4)
            or (r["days_to_next_match"] is not None
                and r["days_to_next_match"] <= 4)):
        return "rotation_congested"
    return "tactical_bench"


df["group"] = df.apply(group, axis=1)

OUT_DIR.mkdir(parents=True, exist_ok=True)
df.to_parquet(OUT_DIR / "case_list.parquet", index=False)

lines = ["# Team-news investigation — step 1: the case list (2026-08-21)",
         "",
         f"{len(df)} squad-gameweeks across three d45 baseline paths where "
         "an owned player was predicted >= 60 minutes at his own cutoff and "
         "played 0. Built by eval/build_teamnews_cases.py (grouping "
         "heuristics in its header); parquet: data/teamnews/"
         "case_list.parquet. Steps 2-3 will establish what was publicly "
         "reported, against THIS fixed list.",
         "",
         "## Group counts",
         ""]
for g, n in df["group"].value_counts().items():
    lines.append(f"- {g}: {n}")
lines += ["", "## Cases", ""]
for season in SEASONS:
    sub = df[df["season"] == season]
    lines.append(f"### {season} ({len(sub)} cases)")
    lines.append("")
    lines.append("| gw | player | team | e_min | e_pts | cap | asof "
                 "status/chance/news | mins gw-3..gw+3 | fixture | group |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in sub.iterrows():
        newsbit = (f"{r['asof_status']}/"
                   f"{'' if pd.isna(r['asof_chance']) else int(r['asof_chance'])}/"
                   f"{(r['asof_news'] or '')[:40]}")
        seq = " ".join("-" if pd.isna(r[f"min_gw{o:+d}"])
                       else str(int(r[f"min_gw{o:+d}"]))
                       for o in (-3, -2, -1)) + " [0] " + \
              " ".join("-" if pd.isna(r[f"min_gw{o:+d}"])
                       else str(int(r[f"min_gw{o:+d}"]))
                       for o in (1, 2, 3))
        fx = (("midweek" if r["midweek"] else "weekend")
              + f", prev {r['days_since_prev_match']}d, next "
              f"{r['days_to_next_match']}d")
        lines.append(f"| {r['gw']} | {r['player']} | {r['team']} | "
                     f"{r['e_minutes']:.0f} | {r['e_points']:.1f} | "
                     f"{'C' if r['captained'] else ''} | {newsbit} | {seq} | "
                     f"{fx} | {r['group']} |")
    lines.append("")

(REPO / "Logs" / "teamnews_case_list.md").write_text(
    "\n".join(lines), encoding="utf-8")
print(f"{len(df)} cases -> {OUT_DIR / 'case_list.parquet'}")
print(df["group"].value_counts().to_string())
print(df.groupby("season").size().to_string())
print("captained cases:", int(df["captained"].sum()))
print("flagged at deadline:", int((df['asof_status'] != 'a').sum()))
