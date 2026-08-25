"""Coverage check for horizon lever 3 (return dates from fplcache asof_news), run BEFORE the feature is built: parses explicit return language ("Expected back DD Mon", "Suspended until DD Mon", "unknown return date") from asof_news only, maps each date to the first gameweek whose DEADLINE falls on/after it (the deadline calendar is fixed at season start -- no final-fixture-calendar caveat), and counts, per horizon step k = 1..5, the (cutoff, gw, element) rows where the feature would flip the stale belief from absent to expected-back, as a share of all rows, of squad-relevant rows (top 30 by the incumbent's own step-k e_points), and among top-30-calibre players (top 30 by own-cutoff e_points in any of the 5 gameweeks before the cutoff -- knowable at the cutoff). Realised minutes are never read: the club's date is a forecast and its accuracy must not enter (D7 rule). Result of record: Logs/horizon_minutes_log.md section 4. Read-only.

Usage: uv run python eval/scope_horizon_returns_coverage.py
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SEASONS = {"2023-24": "2324", "2024-25": "2425", "2025-26": "2526"}
FLAGGED = {"i", "d", "s", "n"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RE = re.compile(r"\b(?:expected back|back|until|return[s]? on|returns)\s+(\d{1,2})\s+([a-z]{3})", re.I)
UNKNOWN_RE = re.compile(r"unknown return", re.I)
TOP = 30


def parse_news(text, deadline):
    """-> ('date', Timestamp) | ('unknown', None) | ('none', None). Year is
    inferred from the deadline: a month more than 6 months behind the deadline
    rolls into the next year; more than 6 ahead rolls back."""
    if not isinstance(text, str) or not text.strip():
        return "none", None
    m = DATE_RE.search(text)
    if m:
        day, mon = int(m.group(1)), MONTHS.get(m.group(2).lower())
        if mon:
            year = deadline.year
            if mon - deadline.month < -6:
                year += 1
            elif mon - deadline.month > 6:
                year -= 1
            try:
                return "date", pd.Timestamp(year=year, month=mon, day=day, tz="UTC")
            except ValueError:
                return "none", None
    if UNKNOWN_RE.search(text):
        return "unknown", None
    return "none", None


def main():
    print("COVERAGE CHECK -- lever 3 (return dates from asof_news). No outcomes read.\n")
    grand = []
    for season, short in SEASONS.items():
        tag = season.replace("-", "_")
        av = pd.read_parquet(REPO / "data" / f"availability_{short}.parquet",
                             columns=["gw", "element", "asof_status", "asof_news", "deadline_time"])
        av["deadline_time"] = pd.to_datetime(av["deadline_time"], utc=True)
        deadlines = av.groupby("gw")["deadline_time"].first().sort_index()
        gws = deadlines.index.astype(int).tolist()

        def gw_for(date):
            later = deadlines[deadlines >= date - pd.Timedelta(days=1)]
            return int(later.index[0]) if len(later) else 99     # 99 = beyond the season
        fl = av[av["asof_status"].isin(FLAGGED)].copy()
        parsed = [parse_news(t, d) for t, d in zip(fl["asof_news"], fl["deadline_time"])]
        fl["kind"] = [p[0] for p in parsed]
        fl["ret_date"] = [p[1] for p in parsed]
        fl["ret_gw"] = [gw_for(d) if d is not None else np.nan for d in fl["ret_date"]]
        n_all = len(av); n_fl = len(fl)
        kinds = fl["kind"].value_counts()
        print(f"================ {season} ================")
        print(f"  availability rows {n_all:,}; flagged (i/d/s/n) {n_fl:,} ({n_fl / n_all:.1%}); "
              f"of flagged: explicit date {kinds.get('date', 0):,} ({kinds.get('date', 0) / n_fl:.0%}), "
              f"unknown return {kinds.get('unknown', 0):,} ({kinds.get('unknown', 0) / n_fl:.0%}), "
              f"no return language {kinds.get('none', 0):,} ({kinds.get('none', 0) / n_fl:.0%})")
        dated = fl[fl["kind"] == "date"].copy()
        dated["lead_gws"] = dated["ret_gw"] - dated["gw"]          # gws until expected return
        lead = dated["lead_gws"].clip(upper=99)
        print(f"  dated rows: expected return in the SAME gw {int((lead <= 0).sum()):,}, 1 gw {int((lead == 1).sum()):,}, "
              f"2 {int((lead == 2).sum()):,}, 3 {int((lead == 3).sum()):,}, 4 {int((lead == 4).sum()):,}, 5 {int((lead == 5).sum()):,}, "
              f"beyond the horizon (>5) {int((lead > 5).sum()):,}; distinct players {dated['element'].nunique()}")
        # the rows the feature would FLIP: at cutoff c, step k, the player is
        # flagged at c with a return gw j, and c + k >= j (expected back by then)
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "e_points"])
        own = wf[wf["cutoff"] == wf["gw"]]
        own = own.assign(rk=own.groupby("gw")["e_points"].rank(ascending=False, method="first"))
        top_own = own[own["rk"] <= TOP][["gw", "element"]]
        # top-30 calibre at cutoff c: in the own-cutoff top 30 in any of gws c-5..c-1
        calibre = set()
        for g, e in top_own.itertuples(index=False):
            for c in range(g + 1, g + 6):
                calibre.add((int(c), int(e)))
        print(f"  {'k':>2s} {'rows':>7s} {'flip rows':>9s} {'share':>6s} | {'relevant rows':>13s} {'flip in top30':>13s} {'share':>6s} | "
              f"{'flip & top30-calibre':>20s} {'flip & fresh top30':>18s} | {'unknown-return rows':>19s}")
        rows_k = []
        for k in range(1, 6):
            st = wf[wf["gw"] - wf["cutoff"] == k].copy()
            st["rk"] = st.groupby("gw")["e_points"].rank(ascending=False, method="first")
            n_rows = len(st)
            # join the cutoff-c flag row (the cutoff is the stale frame's gw)
            m = st.merge(dated[["gw", "element", "ret_gw"]].rename(columns={"gw": "cutoff"}),
                         on=["cutoff", "element"], how="inner")
            flip = m[m["gw"] >= m["ret_gw"]]
            n_flip = len(flip)
            rel = st[st["rk"] <= TOP]
            flip_top = flip[flip["rk"] <= TOP]
            cal = sum(1 for c, e in zip(flip["cutoff"], flip["element"]) if (int(c), int(e)) in calibre)
            fresh_top = set(map(tuple, top_own.astype(int).values))
            ftop = sum(1 for g, e in zip(flip["gw"], flip["element"]) if (int(g), int(e)) in fresh_top)
            unk = st.merge(fl.loc[fl["kind"] == "unknown", ["gw", "element"]].rename(columns={"gw": "cutoff"}),
                           on=["cutoff", "element"], how="inner")
            print(f"  {k:2d} {n_rows:7,d} {n_flip:9,d} {n_flip / n_rows:6.2%} | {len(rel):13,d} {len(flip_top):13,d} "
                  f"{len(flip_top) / max(len(rel), 1):6.2%} | {cal:20,d} {ftop:18,d} | {len(unk):19,d}")
            rows_k.append((season, k, n_rows, n_flip, len(rel), len(flip_top), cal, ftop, len(unk)))
        grand += rows_k
        print()
    g = pd.DataFrame(grand, columns=["season", "k", "rows", "flip", "rel", "flip_top", "calibre", "fresh_top", "unknown"])
    print("POOLED over seasons, k >= 3 (where the feature is supposed to act):")
    s = g[g["k"] >= 3].groupby("k")[["rows", "flip", "rel", "flip_top", "calibre", "fresh_top", "unknown"]].sum()
    for k, r in s.iterrows():
        print(f"  k={k}: flip rows {int(r['flip']):,} of {int(r['rows']):,} ({r['flip'] / r['rows']:.2%}); "
              f"in the incumbent's top 30: {int(r['flip_top'])} of {int(r['rel']):,} relevant rows ({r['flip_top'] / r['rel']:.2%}); "
              f"top-30-calibre players: {int(r['calibre'])}; would be in the fresh top 30: {int(r['fresh_top'])}; "
              f"unknown-return rows {int(r['unknown']):,}")
    print("\nDefinitions: flip row = (cutoff, gw=cutoff+k, element) where the player is flagged at the cutoff with a parsed "
          "return date whose gameweek <= gw (stale belief: absent; feature: expected back). Squad-relevant = top 30 by the "
          "incumbent's own step-k e_points in that gw. Top-30-calibre = in the own-cutoff top 30 in any of the 5 gws before "
          "the cutoff (knowable). 'Fresh top 30' is descriptive only (uses the target gw's own-cutoff prediction). "
          "No realised minutes were read.")


if __name__ == "__main__":
    main()
