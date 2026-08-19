"""Understat per-match player pull (D2). Backfill and weekly incremental are
the SAME code path: every run fetches only what is missing, so the first run
is the backfill and every later run is the increment.

    uv run python eval/understat_matches.py --season 2025-26
    uv run python eval/understat_matches.py --all          # 2022-23 .. 2025-26

Endpoints (the embedded-JSON pages died; the site now serves JSON directly):
    GET https://understat.com/getLeagueData/EPL/<start-year>   (dates/teams/players)
    GET https://understat.com/getMatchData/<match-id>          (rosters + shots)
Responses are gzipped JSON. Rate limit: 1 request/second, be polite.

DERIVATION NOTE (probe finding, 2026-08-17): npxG and npg are NOT provided
per player-match. The roster rows carry raw xG/goals only. Both are derived
here from the shots payload of the same response:
    npxG = xG   - sum of that player's penalty-shot xG in the match
    npg  = goals - that player's converted penalties in the match
(penalty shots are situation == "Penalty"; a converted one is result == "Goal").

RAW CACHE: data/history/understat_raw/EPL_<year>/match_<id>.json.gz. A failed
run resumes from the cache instead of restarting. File mtimes double as
first-seen timestamps, so DATA LAG becomes measurable in production simply by
running this after each gameweek. League listings are refetched every run
(1 request) because isResult flips as matches complete.

NUMERIC COERCION: Understat serves every number as a string (KNOWN_ISSUES #2).
Everything numeric is coerced before the parquet is written.

CROSSWALK TRAP (KNOWN_ISSUES #3): this file keys players by understat
player_id and does NOT touch the crosswalk. Whoever joins these rows through
data/history/player_id_crosswalk_final.csv MUST run the duplicate-id sweep
first -- one Understat ID claimed by two elements has already happened once
(Joao Gomes / Beto). Use assert_crosswalk_unique() below at integration time.

GAMEWEEK MAPPING: match date -> GW via vaastav kickoff_time dates for the same
season. Dates carrying fixtures from more than one GW (rearranged midweeks)
take the majority GW and are flagged gw_ambiguous=True rather than silently
assigned.
"""
import argparse
import gzip
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "data" / "history" / "understat_raw"
OUT_DIR = REPO / "data" / "history"
VAASTAV = REPO / "data" / "history" / "all_seasons_fixed.parquet"

SEASONS = {"2022-23": 2022, "2023-24": 2023, "2024-25": 2024, "2025-26": 2025}
RATE_SECONDS = 1.05
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}

NUMERIC = ["minutes", "goals", "own_goals", "npg", "assists", "shots",
           "key_passes", "xG", "xA", "npxG", "xGChain", "xGBuildup",
           "yellow_card", "red_card", "positionOrder"]


def _fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=30).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _league(year):
    return _fetch_json(f"https://understat.com/getLeagueData/EPL/{year}")


def _match_cache_path(year, match_id):
    return RAW_DIR / f"EPL_{year}" / f"match_{match_id}.json.gz"


def _fetch_match(year, match_id):
    """Fetch one match into the raw cache (skip if cached). Returns the dict."""
    p = _match_cache_path(year, match_id)
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    data = _fetch_json(f"https://understat.com/getMatchData/{match_id}")
    if not data.get("rosters") or not data["rosters"].get("h"):
        raise ValueError(f"match {match_id}: empty rosters")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(p)  # a killed run never leaves a half-written cache file
    time.sleep(RATE_SECONDS)
    return data


def _gw_lookup(season):
    """date -> (gw, ambiguous) from vaastav kickoff dates for the season."""
    v = pd.read_parquet(VAASTAV, columns=["season", "GW", "kickoff_time"])
    v = v[v["season"] == season].copy()
    v["date"] = pd.to_datetime(v["kickoff_time"]).dt.date
    out = {}
    for date, sub in v.groupby("date"):
        counts = sub["GW"].value_counts()
        out[date] = (int(counts.idxmax()), len(counts) > 1)
    return out


def _rows_for_match(entry, match_data, season):
    """Flatten one match's rosters into player rows, deriving npg/npxG from shots."""
    match_id = str(entry["id"])
    dt = datetime.strptime(entry["datetime"], "%Y-%m-%d %H:%M:%S")
    titles = {"h": entry["h"]["title"], "a": entry["a"]["title"]}

    pen_xg, pen_goals = {}, {}
    for side in ("h", "a"):
        for s in match_data.get("shots", {}).get(side, []):
            if s.get("situation") == "Penalty":
                pid = str(s["player_id"])
                pen_xg[pid] = pen_xg.get(pid, 0.0) + float(s["xG"] or 0)
                if s.get("result") == "Goal":
                    pen_goals[pid] = pen_goals.get(pid, 0) + 1

    rows = []
    for side in ("h", "a"):
        for r in match_data["rosters"].get(side, {}).values():
            pid = str(r["player_id"])
            xg = float(r["xG"] or 0)
            goals = float(r["goals"] or 0)
            rows.append({
                "season": season,
                "match_id": match_id,
                "match_datetime": dt,
                "match_date": dt.date(),
                "understat_player_id": pid,
                "player_name": r["player"],
                "team": titles[side],
                "opponent": titles["a" if side == "h" else "h"],
                "h_a": side,
                "position": r["position"],
                "positionOrder": r.get("positionOrder"),
                "minutes": r["time"],
                "goals": goals,
                "own_goals": r["own_goals"],
                "npg": goals - pen_goals.get(pid, 0),
                "assists": r["assists"],
                "shots": r["shots"],
                "key_passes": r["key_passes"],
                "xG": xg,
                "xA": r["xA"],
                "npxG": max(xg - pen_xg.get(pid, 0.0), 0.0),
                "xGChain": r["xGChain"],
                "xGBuildup": r["xGBuildup"],
                "yellow_card": r["yellow_card"],
                "red_card": r["red_card"],
            })
    return rows


def pull_season(season, verbose=True):
    """Fetch whatever is missing for one season and (re)write its parquet.
    Returns (n_rows, n_matches, failures)."""
    year = SEASONS[season]
    league = _league(year)
    time.sleep(RATE_SECONDS)
    completed = [d for d in league["dates"] if d.get("isResult")]
    if verbose:
        print(f"{season}: {len(league['dates'])} fixtures listed, "
              f"{len(completed)} completed", flush=True)

    cached = {p.name[len("match_"):-len(".json.gz")]
              for p in (RAW_DIR / f"EPL_{year}").glob("match_*.json.gz")}
    todo = [d for d in completed if str(d["id"]) not in cached]
    if verbose and todo:
        print(f"  fetching {len(todo)} missing matches "
              f"(~{len(todo) * RATE_SECONDS / 60:.0f} min)", flush=True)

    failures = []
    rows = []
    for i, entry in enumerate(completed):
        try:
            data = _fetch_match(year, str(entry["id"]))
            rows.extend(_rows_for_match(entry, data, season))
        except Exception as e:  # noqa: BLE001 -- record and continue; report at end
            failures.append((str(entry["id"]), entry["datetime"], repr(e)))
        if verbose and todo and (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(completed)}", flush=True)

    df = pd.DataFrame(rows)
    if len(df):
        lookup = _gw_lookup(season)
        mapped = df["match_date"].map(lambda d: lookup.get(d, (None, True)))
        df["gw"] = [m[0] for m in mapped]
        df["gw_ambiguous"] = [m[1] for m in mapped]
        for c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["match_date"] = pd.to_datetime(df["match_date"])
        df["pulled_at"] = pd.Timestamp.now(tz=timezone.utc).isoformat()
        out = OUT_DIR / f"understat_matches_{season.replace('-', '_')}.parquet"
        df.to_parquet(out, index=False)
        if verbose:
            print(f"  -> {out.name}: {len(df)} rows, "
                  f"{df['match_id'].nunique()} matches, "
                  f"gw range {int(df['gw'].min())}-{int(df['gw'].max())}, "
                  f"ambiguous-gw rows: {int(df['gw_ambiguous'].sum())}", flush=True)
    for mid, dt, err in failures:
        print(f"  FAILED match {mid} ({dt}): {err}", flush=True)
    return len(df), df["match_id"].nunique() if len(df) else 0, failures


def assert_crosswalk_unique(crosswalk):
    """KNOWN_ISSUES #3 guard for integration time: no Understat ID may be
    claimed by two elements, and vice versa. Raises with the offenders."""
    cw = crosswalk.dropna(subset=["understat_id"])
    for col in ("understat_id", "element"):
        dup = cw[cw.duplicated(col, keep=False)]
        if len(dup):
            raise AssertionError(
                f"crosswalk has duplicate {col} claims (KNOWN_ISSUES #3):\n"
                + dup.sort_values(col).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", choices=sorted(SEASONS))
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    seasons = sorted(SEASONS) if args.all else ([args.season] if args.season else [])
    if not seasons:
        ap.error("pass --season YYYY-YY or --all")
    any_failed = False
    for s in seasons:
        _, _, failures = pull_season(s)
        any_failed |= bool(failures)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
