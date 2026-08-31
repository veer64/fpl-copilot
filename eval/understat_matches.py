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

SEASONS = {"2022-23": 2022, "2023-24": 2023, "2024-25": 2024, "2025-26": 2025,
           "2026-27": 2026}
RATE_SECONDS = 1.05
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
FETCH_RETRIES = 3

NUMERIC = ["minutes", "goals", "own_goals", "npg", "assists", "shots",
           "key_passes", "xG", "xA", "npxG", "xGChain", "xGBuildup",
           "yellow_card", "red_card", "positionOrder"]


def _fetch_json(url):
    """Polite fetch: 1 req/s spacing lives at the call sites; here, 3 retries with
    backoff for transient errors, and an IMMEDIATE hard stop on 403/429 -- if
    Understat is blocking or rate-limiting, hammering it is the one wrong answer."""
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            raw = urllib.request.urlopen(req, timeout=30).read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise RuntimeError(
                    f"{url} -> HTTP {e.code}: Understat is blocking/rate-limiting. STOP; wait "
                    f"and retry later at 1 req/s. Do not reduce the spacing.") from e
            if attempt == FETCH_RETRIES:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == FETCH_RETRIES:
                raise
            time.sleep(2 ** attempt)


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
    """date -> (gw, ambiguous) from kickoff dates for the season, plus the
    per-gw fixture counts (for completeness checks on a live season).

    Source: vaastav rows in all_seasons_fixed.parquet where the season exists
    there (the archive); otherwise the FPL-API season file
    data/history/fpl_api_{tag}.parquet (2026-27+; built by
    eval/fetch_fpl_history.py, which only ever contains data_checked-FINAL
    gameweeks -- so a date that maps to nothing is a not-yet-final gameweek,
    which is exactly the deferral signal pull_season uses). Neither present ->
    raise; a silent empty lookup would send every row to gw=None."""
    v = pd.read_parquet(VAASTAV, columns=["season", "GW", "kickoff_time"])
    v = v[v["season"] == season].copy()
    source = "vaastav"
    if len(v) == 0:
        api = OUT_DIR / f"fpl_api_{season.replace('-', '_')}.parquet"
        if not api.exists():
            raise LookupError(
                f"no kickoff source for {season}: no rows in {VAASTAV.name} and no "
                f"{api.name}. Run eval/fetch_fpl_history.py first -- without a kickoff "
                f"calendar every Understat match would land gw=None.")
        v = pd.read_parquet(api, columns=["season", "GW", "kickoff_time"])
        v = v[v["season"] == season].copy()
        source = api.name
    v["date"] = pd.to_datetime(v["kickoff_time"]).dt.date
    out = {}
    for date, sub in v.groupby("date"):
        counts = sub["GW"].value_counts()
        out[date] = (int(counts.idxmax()), len(counts) > 1)
    fixture_counts = (v.assign(fx=v["kickoff_time"])
                      .groupby("GW")["fx"].nunique().astype(int).to_dict())
    return out, fixture_counts, source


def split_final_deferred(df, lookup, fixture_counts, live_season):
    """Assign gameweeks and split (final_rows, deferred_matches).

    Live season (FPL-API kickoff source, final gameweeks only): a match whose
    date maps to no gameweek, or whose gameweek is not fully covered by
    Understat results yet, is DEFERRED -- returned separately, never written to
    the season file, listed match-by-match. Archive season: every date must
    map; a residual gw=None RAISES (it can never silently pass through)."""
    mapped = df["match_date"].map(lambda d: lookup.get(d, (None, True)))
    df = df.copy()
    df["gw"] = [m[0] for m in mapped]
    df["gw_ambiguous"] = [m[1] for m in mapped]
    if not live_season:
        bad = df[df["gw"].isna()]
        if len(bad):
            raise ValueError(
                f"{bad['match_id'].nunique()} match(es) map to no gameweek on an archive "
                f"season -- refusing to write gw=None rows: "
                f"{bad[['match_id', 'match_date', 'team']].drop_duplicates('match_id').head(10).to_dict('records')}")
        return df, pd.DataFrame(columns=df.columns)
    deferred_mask = df["gw"].isna()
    # completeness per mapped gameweek: all of the gameweek's fixtures must be present
    have = df[~deferred_mask].groupby("gw")["match_id"].nunique()
    incomplete = [int(g) for g, n in have.items() if n < fixture_counts.get(int(g), 10 ** 9)]
    deferred_mask |= df["gw"].isin(incomplete)
    return df[~deferred_mask].copy(), df[deferred_mask].copy()


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
        lookup, fixture_counts, source = _gw_lookup(season)
        live_season = source != "vaastav"
        df, deferred = split_final_deferred(df, lookup, fixture_counts, live_season)
        for frame in (df, deferred):
            for c in NUMERIC:
                if len(frame):
                    frame[c] = pd.to_numeric(frame[c], errors="coerce")
        df["match_date"] = pd.to_datetime(df["match_date"])
        # the split carries None gws before filtering, which floats the column;
        # the written season file holds final gameweeks only, so int64 like the
        # archive seasons' files
        df["gw"] = df["gw"].astype("int64")
        df["gw_ambiguous"] = df["gw_ambiguous"].astype(bool)
        df["pulled_at"] = pd.Timestamp.now(tz=timezone.utc).isoformat()
        tag = season.replace("-", "_")
        out = OUT_DIR / f"understat_matches_{tag}.parquet"
        tmp = out.with_suffix(".tmp.parquet")
        df.to_parquet(tmp, index=False)
        tmp.replace(out)
        if verbose:
            print(f"  -> {out.name}: {len(df)} rows, "
                  f"{df['match_id'].nunique()} matches, "
                  f"gw range {int(df['gw'].min())}-{int(df['gw'].max())}, "
                  f"ambiguous-gw rows: {int(df['gw_ambiguous'].sum())} "
                  f"(kickoff source: {source})", flush=True)
        if live_season:
            for r in deferred.drop_duplicates("match_id").itertuples():
                print(f"  DEFERRED match {r.match_id} {pd.Timestamp(r.match_date).date()} "
                      f"{r.team} vs {r.opponent}: gameweek not yet FINAL in the FPL-API "
                      f"file (or gameweek incomplete on Understat) -- will be written "
                      f"when it finalises", flush=True)
            prov = {"season": season, "pulled_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
                    "kickoff_source": source,
                    "final_gws": {int(g): int(n) for g, n in
                                  df.groupby("gw")["match_id"].nunique().items()},
                    "deferred_matches": deferred.drop_duplicates("match_id")[
                        ["match_id", "team", "opponent"]].to_dict("records")}
            (OUT_DIR / f"understat_matches_{tag}.provenance.json").write_text(
                json.dumps(prov, indent=1, default=str), encoding="utf-8")
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
