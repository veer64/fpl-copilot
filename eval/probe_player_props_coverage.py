"""Step-1 free-tier coverage probe for player-prop odds (the-odds-api.com): for a handful of ORDINARY mid-season EPL fixtures across 2023-24 / 2024-25 / 2025-26, pulls the historical anytime-goalscorer market (player_goal_scorer_anytime) at deadline - 1h for the uk region (eu on a subset if quota allows), stores raw JSON to data/odds_props/raw/ BEFORE parsing, and reports per fixture which bookmakers price the market, how many players are on the board, the snapshot timestamp relative to the FPL deadline (previous/next snapshot), and credits used. Key read from .env (ODDS_API_KEY) and never printed, written or logged. No parser, feature or crosswalk is built; no purchase decision. Result of record: Logs/player_props_coverage_log.md.

Usage: uv run python eval/probe_player_props_coverage.py
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "odds_props" / "raw"
SPORT = "soccer_epl"
MARKET = "player_goal_scorer_anytime"
BASE = "https://api.the-odds-api.com/v4"

# (season, gw, deadline UTC, home token, away token) -- ordinary Saturday games
FIXTURES = [
    ("2023-24", 13, "2023-11-25T11:00:00Z", "Luton", "Crystal Palace"),
    ("2023-24", 27, "2024-03-02T13:30:00Z", "Everton", "West Ham"),
    ("2024-25", 16, "2024-12-14T13:30:00Z", "Wolverhampton", "Ipswich"),
    ("2025-26", 15, "2025-12-06T11:00:00Z", "Everton", "Nottingham"),
    ("2024-25", 15, "2024-12-07T11:00:00Z", "Brentford", "Newcastle"),
]
EU_ON = {("2023-24", 13), ("2025-26", 15)}     # eu region on two fixtures, quota permitting
MIN_REMAINING_FOR_EU = 300


def load_key():
    env = REPO / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ODDS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ODDS_API_KEY not found in .env")


def get(path, params, key):
    """GET with the key in the query; the URL is never printed or logged."""
    q = dict(params); q["apiKey"] = key
    url = f"{BASE}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "fpl-copilot props-coverage probe"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
            hdr = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"    HTTP {e.code} on {path.split('?')[0]}: {body[:200]}")
        return None, {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
    quota = {k: hdr.get(k) for k in ("x-requests-used", "x-requests-remaining", "x-requests-last")}
    return json.loads(body), quota


def save(obj, name):
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / name
    p.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return p


def minus_1h(iso):
    from datetime import datetime, timedelta, timezone
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(hours=1)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_odds(payload):
    """bookmakers -> (n_players, last_update); snapshot timestamps."""
    data = payload.get("data", payload)
    out = {}
    for bk in data.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != MARKET:
                continue
            outcomes = mk.get("outcomes", [])
            names = {o.get("description") or o.get("name") for o in outcomes}
            out[bk["key"]] = (len(names), bk.get("last_update"), bk.get("title"))
    return out, payload.get("timestamp"), payload.get("previous_timestamp"), payload.get("next_timestamp")


BIG_SIX = ("Arsenal", "Chelsea", "Liverpool", "Manchester City", "Manchester United", "Tottenham")


def main_live(key, max_events=5):
    """Free-tier substitute: the CURRENT market for upcoming ordinary EPL
    fixtures (events list is free; odds cost 1 credit per region per market).
    Answers which books price the market and how deep the board is; it
    cannot answer historical depth or pre-deadline snapshot cadence."""
    print("LIVE probe (historical endpoints are paid-only on this plan)\n")
    ev, quota = get(f"/sports/{SPORT}/events", {}, key)
    if ev is None:
        raise SystemExit("events call failed")
    print(f"upcoming EPL events: {len(ev)}; events call cost {quota['x-requests-last']}, remaining {quota['x-requests-remaining']}")
    save(ev, "live_events.json")
    ordinary = [e for e in ev if not any(b in e["home_team"] or b in e["away_team"] for b in BIG_SIX)]
    picks = sorted(ordinary, key=lambda e: e["commence_time"])[:max_events]
    report, remaining = [], quota["x-requests-remaining"]
    for e in picks:
        print(f"=== {e['home_team']} v {e['away_team']} (commence {e['commence_time']}) ===")
        rec = dict(fixture=f"{e['home_team']} v {e['away_team']}", commence=e["commence_time"], regions={})
        for region in ("uk", "eu"):
            od, quota = get(f"/sports/{SPORT}/events/{e['id']}/odds",
                            {"regions": region, "markets": MARKET, "oddsFormat": "decimal"}, key)
            if od is None:
                rec["regions"][region] = {"error": "odds call failed"}; continue
            remaining = quota["x-requests-remaining"]
            print(f"    odds[{region}]: cost {quota['x-requests-last']}, remaining {remaining}")
            save(od, f"live_odds_{e['home_team']}_{e['away_team']}_{region}.json".replace(" ", "_"))
            books, _, _, _ = summarize_odds(od)
            if books:
                for bk, (n, lu, title) in sorted(books.items(), key=lambda kv: -kv[1][0]):
                    print(f"      {bk:18s} {title:22s} players priced {n:3d}  last_update {lu}")
            else:
                print("      NO bookmaker returned the market")
            rec["regions"][region] = {bk: dict(players=n, last_update=lu, title=title) for bk, (n, lu, title) in books.items()}
            time.sleep(1.0)
        report.append(rec)
    save(report, "_live_coverage_summary.json")
    print(f"\nremaining credits after the live probe: {remaining}")


# Step 2 (paid tier): ordinary fixtures incl. congested periods; deadlines read
# from the FPL events array (fplcache) and cross-checked against the
# availability parquet -- never assumed.
STEP2 = [
    ("2023-24", 13, "2023-11-25T11:00:00Z", "Luton", "Crystal Palace", "ordinary Saturday"),
    ("2023-24", 34, "2024-04-20T12:30:00Z", "Wolverhampton", "Bournemouth", "DOUBLE gw, midweek 2nd fixture (Wed 24 Apr), 4 days after the deadline"),
    ("2024-25", 16, "2024-12-14T13:30:00Z", "Wolverhampton", "Ipswich", "ordinary Saturday"),
    ("2024-25", 28, "2025-03-08T11:00:00Z", "Brighton", "Fulham", "ordinary Saturday"),
    ("2024-25", 33, "2025-04-19T12:30:00Z", "Crystal Palace", "Bournemouth", "DOUBLE gw (Sat fixture)"),
    ("2025-26", 15, "2025-12-06T11:00:00Z", "Everton", "Nottingham", "ordinary Saturday"),
    ("2025-26", 21, "2026-01-06T18:30:00Z", "Everton", "Wolverhampton", "MIDWEEK round (Wed 7 Jan)"),
]
BUDGET = 100


def minus_seconds(iso, s):
    from datetime import datetime, timedelta, timezone
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(seconds=s)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main_step2(key):
    from datetime import datetime
    print("STEP 2 (paid tier): historical board depth + snapshot-before-deadline, uk region\n")
    start_remaining = None
    report = []
    for season, gw, deadline, home, away, note in STEP2:
        date = minus_seconds(deadline, 60)          # last snapshot STRICTLY before the deadline
        print(f"=== {season} GW{gw}: {home} v {away} -- {note}; FPL deadline {deadline}; query {date} ===")
        ev, quota = get(f"/historical/sports/{SPORT}/events", {"date": date}, key)
        if ev is None:
            report.append(dict(season=season, gw=gw, fixture=f"{home} v {away}", note=note, error="events call failed")); continue
        if start_remaining is None:
            start_remaining = int(quota["x-requests-remaining"]) + int(quota["x-requests-last"] or 0)
        print(f"    events: cost {quota['x-requests-last']}, remaining {quota['x-requests-remaining']}")
        save(ev, f"step2_events_{season}_gw{gw}_{home}_{away}.json".replace(" ", "_"))
        events = ev.get("data", ev)
        match = [e for e in events if home.lower() in e["home_team"].lower() and away.lower() in e["away_team"].lower()]
        if not match:
            print(f"    fixture NOT in the events snapshot ({len(events)} events listed: "
                  + "; ".join(f"{e['home_team']} v {e['away_team']}" for e in events[:14]) + ")")
            report.append(dict(season=season, gw=gw, fixture=f"{home} v {away}", note=note,
                               error="event not listed at deadline-60s", n_events=len(events))); continue
        e = match[0]
        if int(quota["x-requests-remaining"]) < start_remaining - BUDGET + 10:
            print("    budget guard: stopping before the odds call"); break
        od, quota = get(f"/historical/sports/{SPORT}/events/{e['id']}/odds",
                        {"date": date, "regions": "uk", "markets": MARKET, "oddsFormat": "decimal"}, key)
        if od is None:
            report.append(dict(season=season, gw=gw, fixture=f"{home} v {away}", note=note, error="odds call failed")); continue
        print(f"    odds[uk]: cost {quota['x-requests-last']}, remaining {quota['x-requests-remaining']}")
        save(od, f"step2_odds_{season}_gw{gw}_{home}_{away}_uk.json".replace(" ", "_"))
        books, ts, prev, nxt = summarize_odds(od)
        dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        gap = (dl - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 60 if ts else None
        cad = None
        if ts and nxt:
            cad = (datetime.fromisoformat(nxt.replace("Z", "+00:00")) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 60
        print(f"    snapshot {ts}  prev {prev}  next {nxt}  -> gap to deadline {gap:.0f} min"
              + (f", snapshot-to-next {cad:.0f} min" if cad is not None else ""))
        if books:
            for bk, (n, lu, title) in sorted(books.items(), key=lambda kv: -kv[1][0]):
                print(f"      {bk:18s} {title:22s} players priced {n:3d}")
        else:
            print("      MARKET EMPTY at this snapshot")
        report.append(dict(season=season, gw=gw, fixture=f"{e['home_team']} v {e['away_team']}", note=note,
                           deadline=deadline, commence=e["commence_time"], snapshot=ts, previous=prev, next=nxt,
                           gap_min=gap, books={bk: n for bk, (n, lu, title) in books.items()}))
        time.sleep(1.0)
    save(report, "_step2_summary.json")
    print(f"\ncredits: started {start_remaining}, remaining {quota.get('x-requests-remaining')}")


def main():
    import sys
    key = load_key()
    if "--live" in sys.argv:
        main_live(key)
        return
    if "--step2" in sys.argv:
        main_step2(key)
        return
    print("player-prop coverage probe -- key loaded from .env (not shown)\n")
    report = []
    remaining = None
    for season, gw, deadline, home, away in FIXTURES:
        date = minus_1h(deadline)
        print(f"=== {season} GW{gw}: {home} v {away}; deadline {deadline}; query date {date} ===")
        ev, quota = get(f"/historical/sports/{SPORT}/events", {"date": date}, key)
        if ev is None:
            report.append(dict(season=season, gw=gw, fixture=f"{home} v {away}", error="events call failed")); continue
        print(f"    events call: cost {quota['x-requests-last']}, used {quota['x-requests-used']}, remaining {quota['x-requests-remaining']}")
        save(ev, f"events_{season}_gw{gw}_{home}_{away}.json".replace(" ", "_"))
        events = ev.get("data", ev)
        match = [e for e in events if home.lower() in e["home_team"].lower() and away.lower() in e["away_team"].lower()]
        if not match:
            print(f"    fixture not found among {len(events)} events at that snapshot: "
                  + "; ".join(f"{e['home_team']} v {e['away_team']}" for e in events[:12]))
            report.append(dict(season=season, gw=gw, fixture=f"{home} v {away}", error="event not in snapshot")); continue
        e = match[0]
        print(f"    event {e['id']}: {e['home_team']} v {e['away_team']} commence {e['commence_time']}")
        rec = dict(season=season, gw=gw, fixture=f"{e['home_team']} v {e['away_team']}", deadline=deadline,
                   commence=e["commence_time"], regions={})
        regions = ["uk"] + (["eu"] if (season, gw) in EU_ON else [])
        for region in regions:
            if region == "eu" and remaining is not None and int(remaining) < MIN_REMAINING_FOR_EU:
                print(f"    skipping eu (remaining {remaining} < {MIN_REMAINING_FOR_EU})"); continue
            od, quota = get(f"/historical/sports/{SPORT}/events/{e['id']}/odds",
                            {"date": date, "regions": region, "markets": MARKET, "oddsFormat": "decimal"}, key)
            if od is None:
                rec["regions"][region] = {"error": "odds call failed"}; continue
            remaining = quota["x-requests-remaining"]
            print(f"    odds[{region}] call: cost {quota['x-requests-last']}, used {quota['x-requests-used']}, remaining {remaining}")
            save(od, f"odds_{season}_gw{gw}_{home}_{away}_{region}.json".replace(" ", "_"))
            books, ts, prev, nxt = summarize_odds(od)
            before = (ts is not None and ts < deadline)
            print(f"    snapshot {ts} (prev {prev}, next {nxt}) -> strictly before the deadline: {before}")
            if books:
                for bk, (n, lu, title) in sorted(books.items(), key=lambda kv: -kv[1][0]):
                    print(f"      {bk:18s} {title:22s} players priced {n:3d}  last_update {lu}")
            else:
                print("      NO bookmaker returned the market at this snapshot")
            rec["regions"][region] = dict(snapshot=ts, previous=prev, next=nxt, before_deadline=before,
                                          books={bk: dict(players=n, last_update=lu, title=title) for bk, (n, lu, title) in books.items()})
            time.sleep(1.0)
        report.append(rec)
        time.sleep(1.0)
    save(report, "_coverage_summary.json")
    print(f"\nremaining credits after the probe: {remaining}")


if __name__ == "__main__":
    main()
