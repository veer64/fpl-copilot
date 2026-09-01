"""LIVE PRE-DEADLINE MATCH ODDS (the-odds-api, uk h2h) -> the 2026-27 odds fixture
slice. Closes the odds-prices input gap for the LIVE deadline gameweek.

THE INPUT CHANGE, stated plainly: the backtest consumed Bet365 CLOSING 1X2 prices
(football-data). Bet365 is not carried by this provider (0/20 events), and a live
pull is a PRE-DEADLINE snapshot, not closing -- so this input cannot be
parity-tested against 2025-26. The chosen construction is a de-margined MEDIAN
CONSENSUS over a FIXED 12-BOOK PANEL (the books present on every event at probe
time: betfair_ex_uk, betway, boylesports, casumo, grosvenor, leovegas,
livescorebet, skybet, sport888, unibet_uk, virginbet, williamhill). Why consensus
over a single substitute book: the model de-margins whatever it reads (proportional
normalisation in dixon_coles), so a single book's margin structure is removed
anyway, and a book that disappears mid-season would silently change a single-book
source -- the panel degrades GRACEFULLY AND COUNTABLY instead (a fixture priced by
fewer than MIN_BOOKS panel members is left UNPRICED and counted, never thinly
priced). The consensus odds are written into the B365H/D/A columns because those
are the only price columns the model reads; dixon_coles' odds_source stamp and
this file's provenance record what they actually carry.

Mechanics: one pull prices every event the provider lists (~2 gameweeks ahead).
Cadence: run in the pre-deadline build sequence (with fetch_fixtures and
build_forward_skeleton). Post-deadline odds movement is irrelevant to a committed
decision; later gameweeks are re-priced by the next deadline's pull. Steps 1+ of a
horizon build use pure DC regardless (ODDS_HORIZON_GWS = 0 -- the same convention
the backtests ran).

Conventions: updates data/history/odds_fixtures_2026_27.parquet IN ITS SCHEMA
(prices only; fixture universe untouched), regenerates the combined file via
fetch_fixtures.combine, atomic writes, provenance sidecar with the per-fixture
snapshot detail (odds move -- WHICH snapshot produced a number is provenance),
retries with backoff, real User-Agent, loud failure on any unmapped club or any
event that matches no fixture row. Key from .env (ODDS_API_KEY), never printed.

Usage: uv run python eval/fetch_live_odds.py --season 2026-27
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot live odds; per-deadline; contact: repo owner)"}

# the fixed panel (probe 2026-08-31: present on 20/20 events) and the floor below
# which a fixture is left unpriced-and-counted rather than thinly priced
PANEL = ["betfair_ex_uk", "betway", "boylesports", "casumo", "grosvenor", "leovegas",
         "livescorebet", "skybet", "sport888", "unibet_uk", "virginbet", "williamhill"]
MIN_BOOKS = 5

# the-odds-api club names -> the 2026-27 odds fixture slice's spellings. ALL 20
# must resolve; an unmapped club RAISES -- a dropped fixture is the #14 class.
NAME_MAP = {
    "Arsenal": "Arsenal", "Aston Villa": "Aston Villa", "Bournemouth": "Bournemouth",
    "Brentford": "Brentford", "Brighton and Hove Albion": "Brighton", "Chelsea": "Chelsea",
    "Coventry City": "Coventry City", "Crystal Palace": "Crystal Palace", "Everton": "Everton",
    "Fulham": "Fulham", "Hull City": "Hull City", "Ipswich Town": "Ipswich Town",
    "Leeds United": "Leeds", "Liverpool": "Liverpool", "Manchester City": "Man City",
    "Manchester United": "Man United", "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest", "Sunderland": "Sunderland",
    "Tottenham Hotspur": "Tottenham",
}


class ClubNameError(RuntimeError):
    """A club that does not resolve. Loud, never a dropped fixture."""


def _api_key():
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ODDS_API_KEY="):
            return line.strip().split("=", 1)[1]
    raise SystemExit("ODDS_API_KEY not found in .env")


def pull_events():
    """One h2h pull (1 credit), 3 tries with backoff. Returns (events, headers)."""
    q = urllib.parse.urlencode(dict(apiKey=_api_key(), regions="uk", markets="h2h",
                                    oddsFormat="decimal"))
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds?{q}"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                hdr = {k.lower(): v for k, v in r.headers.items()}
                return json.loads(r.read().decode("utf-8")), hdr
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"the-odds-api pull failed after 3 tries: {last}")


def map_club(name):
    if name not in NAME_MAP:
        raise ClubNameError(f"the-odds-api club {name!r} has no mapping -- an unmapped club "
                            f"silently drops its fixture (the #14 class); extend NAME_MAP")
    return NAME_MAP[name]


def consensus(event, panel=PANEL, min_books=MIN_BOOKS):
    """De-margined median consensus over the panel books present on this event.
    Returns dict(h, d, a, n_books, updated_min, updated_max) or None when fewer
    than min_books panel members price it (UNPRICED, counted -- never thin)."""
    home, away = event["home_team"], event["away_team"]
    probs, updates = [], []
    for b in event.get("bookmakers", []):
        if b["key"] not in panel:
            continue
        m = next((m for m in b.get("markets", []) if m["key"] == "h2h"), None)
        if m is None:
            continue
        o = {x["name"]: float(x["price"]) for x in m["outcomes"]}
        if not ({home, away, "Draw"} <= set(o)) or min(o.values()) <= 1.0:
            continue
        inv = [1 / o[home], 1 / o["Draw"], 1 / o[away]]
        s = sum(inv)
        probs.append([p / s for p in inv])           # de-margin per book (proportional)
        updates.append(b.get("last_update"))
    if len(probs) < min_books:
        return None
    med = [statistics.median(p[i] for p in probs) for i in range(3)]
    s = sum(med)
    med = [p / s for p in med]                       # renormalise the medians to sum 1
    return dict(h=round(1 / med[0], 4), d=round(1 / med[1], 4), a=round(1 / med[2], 4),
                n_books=len(probs), updated_min=min(updates), updated_max=max(updates))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026-27")
    a = ap.parse_args()
    tag = a.season.replace("-", "_")
    slice_p = HIST / f"odds_fixtures_{tag}.parquet"
    df = pd.read_parquet(slice_p)
    valid = set(df["HomeTeam"]) | set(df["AwayTeam"])
    for v in NAME_MAP.values():
        if v not in valid:
            raise ClubNameError(f"NAME_MAP target {v!r} is not a club in {slice_p.name}")

    events, hdr = pull_events()
    pulled_at = datetime.now(timezone.utc).isoformat()
    df = df.set_index(["HomeTeam", "AwayTeam", "Date"])
    per_fixture, priced, thin = {}, 0, []
    for e in events:
        h, w = map_club(e["home_team"]), map_club(e["away_team"])
        ko = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        key = (h, w, ko.strftime("%d/%m/%Y"))
        if key not in df.index:
            raise RuntimeError(f"event {e['home_team']} vs {e['away_team']} @ {e['commence_time']} "
                               f"matches NO fixture row {key} -- the fixture slice is stale; "
                               f"run eval/fetch_fixtures.py first")
        c = consensus(e)
        if c is None:
            thin.append(key)
            continue
        df.loc[key, ["B365H", "B365D", "B365A"]] = [c["h"], c["d"], c["a"]]
        per_fixture[f"{key[2]} {h} v {w}"] = c
        priced += 1
    df = df.reset_index()[list(pd.read_parquet(slice_p).columns)]  # original column order
    tmp = slice_p.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, slice_p)

    import fetch_fixtures
    fetch_fixtures.combine(a.season)                 # regenerate the *_with_* file

    unpriced = int(df[["B365H", "B365D", "B365A"]].isna().any(axis=1).sum())
    prov = dict(
        season=a.season, pulled_at=pulled_at,
        credits=dict(used=hdr.get("x-requests-used"), remaining=hdr.get("x-requests-remaining")),
        construction=f"de-margined median consensus, fixed {len(PANEL)}-book panel, min {MIN_BOOKS}",
        panel=PANEL, source_note="NOT Bet365, NOT closing -- pre-deadline snapshot",
        events=len(events), fixtures_priced=priced, thin_unpriced=[" v ".join(k[:2]) for k in thin],
        slice_rows_unpriced=unpriced,
        post_deadline_note="odds keep moving after the deadline; irrelevant to a committed "
                           "decision -- later gameweeks are re-priced by the next deadline's pull",
        per_fixture=per_fixture,
    )
    (slice_p.parent / f"odds_live_pull_{tag}.provenance.json").write_text(
        json.dumps(prov, indent=1), encoding="utf-8")
    print(f"-> {slice_p.name}: {priced}/{len(events)} events priced "
          f"(thin-panel unpriced: {len(thin)}); {unpriced}/{len(df)} slice rows remain unpriced "
          f"(future gws beyond the provider's listing -> pure DC, counted); "
          f"credits remaining {hdr.get('x-requests-remaining')}")


if __name__ == "__main__":
    main()
