"""Scale pull of historical anytime-goalscorer boards (the-odds-api.com) for every EPL fixture from 2024-25 GW8 onward and all of 2025-26, at the LAST snapshot strictly before each gameweek's FPL deadline (deadline read from the FPL events array in fplcache and verified per fixture), regions eu (1xBet) and us. Raw JSON first: one file per (gw, event) written atomically, skip-if-exists, plus a manifest row per event with the snapshot timestamp, books, players priced and credits -- so an interruption neither corrupts nor re-spends. Stops if the burn rate implies exceeding the quota. Key from .env, never printed or logged. No crosswalk and no feature. Governed by Logs/props_prereg.md; result of record: Logs/player_props_coverage_log.md section 7.

Usage: uv run python eval/pull_player_props_history.py --season 2024-25 --from-gw 8
       uv run python eval/pull_player_props_history.py --season 2025-26
"""
import argparse
import csv
import glob
import json
import lzma
import os
from _replace_retry import replace_with_retry
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import probe_player_props_coverage as p  # noqa: E402  (get, load_key, SPORT, MARKET)

RAW = REPO / "data" / "odds_props" / "raw" / "scale"
SNAP = {"2024-25": "2025/5/30", "2025-26": "2026/5/30",
        "2026-27": None}          # live season: the NEWEST fplcache snapshot on disk
REGIONS = "eu,us,us2"             # us2 added 2026-08-31: bovada (and rebet) moved there;
                                  # 3 regions -> 30 credits/fixture on the historical endpoint
MIN_REMAINING = 1500          # never run the account below this
TOKENS = {"Man City": "Manchester City", "Man Utd": "Manchester United", "Spurs": "Tottenham",
          "Nott'm Forest": "Nottingham", "Wolves": "Wolverhampton", "Sheffield Utd": "Sheffield",
          "Newcastle": "Newcastle", "West Ham": "West Ham", "Brighton": "Brighton", "Leicester": "Leicester",
          "Ipswich": "Ipswich", "Southampton": "Southampton", "Luton": "Luton", "Burnley": "Burnley",
          "Leeds": "Leeds", "Sunderland": "Sunderland", "Crystal Palace": "Crystal Palace",
          "Coventry City": "Coventry", "Hull City": "Hull",   # promoted 2026-27

          "Aston Villa": "Aston Villa", "Bournemouth": "Bournemouth", "Brentford": "Brentford",
          "Chelsea": "Chelsea", "Everton": "Everton", "Fulham": "Fulham", "Liverpool": "Liverpool",
          "Arsenal": "Arsenal"}


def fpl_deadlines(season):
    pat = SNAP[season]
    snaps = (sorted(glob.glob(str(REPO / "fplcache" / "cache" / pat / "*.json.xz"))) if pat
             else sorted(glob.glob(str(REPO / "fplcache" / "cache" / "*" / "*" / "*" / "*.json.xz"))))
    with lzma.open(snaps[-1]) as f:
        return {int(e["id"]): e["deadline_time"] for e in json.load(f)["events"]}


def fixtures(season):
    sys.path.insert(0, str(REPO / "squad"))
    from season_stack import load_stack
    h = load_stack(columns=["season", "GW", "fixture", "team", "was_home", "kickoff_time"])
    h = h[h["season"] == season]
    h["kickoff_time"] = pd.to_datetime(h["kickoff_time"], utc=True)
    out = []
    for (gw, fx), g in h.groupby(["GW", "fixture"]):
        home = g.loc[g["was_home"] == True, "team"]; away = g.loc[g["was_home"] == False, "team"]  # noqa: E712
        if len(home) and len(away):
            out.append(dict(gw=int(gw), fixture=int(fx), home=home.iloc[0], away=away.iloc[0],
                            kickoff=g["kickoff_time"].min()))
    return pd.DataFrame(out)


def tok(name):
    return TOKENS.get(name, name).lower()


def atomic_write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    replace_with_retry(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--from-gw", type=int, default=1)
    ap.add_argument("--to-gw", type=int, default=38)
    a = ap.parse_args()
    key = p.load_key()
    dl = fpl_deadlines(a.season)
    fx = fixtures(a.season)
    out_dir = RAW / a.season
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.csv"
    have = set()
    if manifest.exists():
        with open(manifest, newline="", encoding="utf-8") as f:
            have = {(int(r["gw"]), r["event_id"]) for r in csv.DictReader(f)}
    new_manifest = not manifest.exists()
    mf = open(manifest, "a", newline="", encoding="utf-8")
    w = csv.writer(mf)
    if new_manifest:
        w.writerow(["season", "gw", "fixture", "home", "away", "kickoff", "deadline", "event_id", "query_date",
                    "snapshot", "next_snapshot", "gap_min", "books", "players_by_book", "cost", "remaining"])
    remaining = None; spent = 0; t0 = time.time()
    print(f"{a.season}: GW{a.from_gw}-{a.to_gw}, regions {REGIONS}, {len(fx)} fixtures on file; resuming past {len(have)} done", flush=True)
    for gw in range(a.from_gw, a.to_gw + 1):
        if gw not in dl:
            print(f"GW{gw}: no FPL deadline in events[] -- skipped", flush=True); continue
        deadline = dl[gw]
        d0 = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        query = (d0 - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ffx = fx[fx["gw"] == gw]
        todo = list(ffx.itertuples())
        # events list at deadline-60s (1 credit)
        ev_path = out_dir / f"gw{gw:02d}_events.json"
        if ev_path.exists():
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        else:
            ev, q = p.get(f"/historical/sports/{p.SPORT}/events", {"date": query}, key)
            if ev is None:
                print(f"GW{gw}: events call failed -- stopping", flush=True); break
            atomic_write(ev_path, ev)
            remaining = int(q["x-requests-remaining"]); spent += int(q["x-requests-last"] or 0)
        events = ev.get("data", ev)
        matched = 0
        for r in todo:
            cands = [e for e in events if tok(r.home) in e["home_team"].lower() and tok(r.away) in e["away_team"].lower()]
            if len(cands) != 1:
                print(f"GW{gw} {r.home} v {r.away}: {len(cands)} event matches at {query} -- recorded, skipped", flush=True)
                w.writerow([a.season, gw, r.fixture, r.home, r.away, r.kickoff.isoformat(), deadline, "", query, "", "", "",
                            f"UNMATCHED({len(cands)})", "", 0, remaining]); mf.flush()
                continue
            e = cands[0]
            if (gw, e["id"]) in have:
                continue
            # sanity: the event must kick off after the deadline
            ko = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
            assert ko > d0, f"GW{gw} {r.home} v {r.away}: kickoff {e['commence_time']} before deadline {deadline}"
            od_path = out_dir / f"gw{gw:02d}_{e['id']}_{REGIONS.replace(',', '')}.json"
            if od_path.exists():
                od = json.loads(od_path.read_text(encoding="utf-8")); cost = 0
            else:
                if remaining is not None and remaining < MIN_REMAINING:
                    print(f"remaining {remaining} < {MIN_REMAINING}: STOPPING", flush=True); mf.close(); return
                od, q = p.get(f"/historical/sports/{p.SPORT}/events/{e['id']}/odds",
                              {"date": query, "regions": REGIONS, "markets": p.MARKET, "oddsFormat": "decimal"}, key)
                if od is None:
                    print(f"GW{gw} {r.home} v {r.away}: odds call failed -- recorded, continuing", flush=True)
                    w.writerow([a.season, gw, r.fixture, r.home, r.away, r.kickoff.isoformat(), deadline, e["id"], query, "", "", "",
                                "CALL_FAILED", "", 0, remaining]); mf.flush(); continue
                atomic_write(od_path, od)
                cost = int(q["x-requests-last"] or 0); remaining = int(q["x-requests-remaining"]); spent += cost
                time.sleep(0.6)
            books, ts, prev, nxt = p.summarize_odds(od)
            gap = (d0 - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 60 if ts else ""
            w.writerow([a.season, gw, r.fixture, r.home, r.away, r.kickoff.isoformat(), deadline, e["id"], query, ts, nxt,
                        f"{gap:.1f}" if gap != "" else "", "|".join(sorted(books)),
                        "|".join(f"{b}:{n}" for b, (n, _, _) in sorted(books.items())), cost, remaining])
            mf.flush(); have.add((gw, e["id"])); matched += 1
        print(f"GW{gw}: deadline {deadline}, {len(todo)} fixtures, {matched} pulled; spent {spent}, remaining {remaining}, "
              f"{(time.time() - t0) / 60:.1f} min", flush=True)
    mf.close()
    print(f"DONE {a.season}: spent {spent} credits, remaining {remaining}", flush=True)


if __name__ == "__main__":
    main()
