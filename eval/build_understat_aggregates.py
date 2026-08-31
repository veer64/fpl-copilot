"""Builder for the Understat SEASON AGGREGATES -- the file data/history/
understat_season_aggregates.parquet never had a builder script (hand/notebook-assembled,
seasons '2016'..'2025'). The crosswalk builder and the penalty prior-year join read it.

WHAT THE FILE IS (established 2026-08-31): one row per (id, understat_season), 19 columns,
every value a VERBATIM Understat string (KNOWN_ISSUES #2 -- the site serves numbers as
strings and the stored file preserves them, e.g. xG '28.795336209237576'). The shape is
exactly the `players` block of GET https://understat.com/getLeagueData/EPL/<year> -- the
same endpoint eval/understat_matches.py already reads for its match list. It is NOT
derived from the per-match files: per-match sums reproduce games/time/goals/assists
exactly and xG/xA only to rounding, but `position` season labels ('F S'), `team_title`
and the full-precision strings are endpoint-native. So the builder PULLS THE ENDPOINT
(one polite request per season) rather than deriving, and --reproduce proves it against
a stored season.

FINALITY: a season aggregate is a RUNNING as-of snapshot -- Understat updates it after
each analysed match, so it is never 'final' until the season ends. Finality here is
represented by provenance, not by file membership: the sidecar records pulled_at and the
completed-match count at pull time, and refreshing is idempotent (re-run, re-combine).

APPEND, DO NOT REBUILD: the stored parquet is never touched. The season pull writes
understat_season_aggregates_{tag}.parquet; --combine writes
understat_season_aggregates_with_{tag}.parquet = stored + season rows, schema asserted,
refusing if the season is already in the stored file.

Usage:
  uv run python eval/build_understat_aggregates.py --reproduce 2024-25
  uv run python eval/build_understat_aggregates.py --season 2026-27
  uv run python eval/build_understat_aggregates.py --season 2026-27 --combine
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
STORED = HIST / "understat_season_aggregates.parquet"

sys.path.insert(0, str(REPO / "eval"))
from understat_matches import SEASONS, RATE_SECONDS, _fetch_json  # noqa: E402  (same endpoint, same politeness)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] build_understat_aggregates: {msg}", flush=True)


def stored_schema():
    empty = pd.read_parquet(STORED).iloc[0:0]
    return list(empty.columns), empty.dtypes


def fetch_players_block(season):
    if season not in SEASONS:
        raise KeyError(f"{season!r} not in understat_matches.SEASONS -- extend that map first "
                       f"(single source of truth for Understat season years)")
    year = SEASONS[season]
    data = _fetch_json(f"https://understat.com/getLeagueData/EPL/{year}")
    time.sleep(RATE_SECONDS)
    players = data.get("players")
    if not players:
        raise RuntimeError(f"getLeagueData/EPL/{year} returned no players block -- endpoint changed?")
    completed = sum(1 for d in data.get("dates", []) if d.get("isResult"))
    return players, year, completed


def to_frame(players, year):
    cols, dtypes = stored_schema()
    df = pd.DataFrame(players)
    df["understat_season"] = str(year)
    missing = [c for c in cols if c not in df.columns]
    extra = [c for c in df.columns if c not in cols]
    if missing:
        raise RuntimeError(f"players block is missing stored column(s) {missing} -- endpoint schema changed")
    if extra:
        log(f"dropping {len(extra)} endpoint-only column(s) not in the stored schema: {extra}")
    df = df[cols]
    for c in cols:                       # stored file is all-object verbatim strings
        df[c] = df[c].astype(dtypes[c])
    assert not df.duplicated(["id", "understat_season"]).any()
    return df


def reproduce(season):
    """The trust proof: pull the endpoint for a stored season and compare column by
    column against the stored file. Exact string match demanded; differences are
    REPORTED (Understat retro-corrects its models sometimes), never tolerated silently."""
    players, year, completed = fetch_players_block(season)
    fresh = to_frame(players, year)
    stored = pd.read_parquet(STORED)
    st = stored[stored["understat_season"].astype(str) == str(year)].copy()
    j = st.merge(fresh, on="id", suffixes=("_stored", "_fresh"), how="outer", indicator=True)
    print(f"\nREPRODUCE {season} (understat_season {year}): stored {len(st)} rows, fresh {len(fresh)}, "
          f"matched {(j['_merge'] == 'both').sum()}, stored-only {(j['_merge'] == 'left_only').sum()}, "
          f"fresh-only {(j['_merge'] == 'right_only').sum()}; completed matches {completed}")
    b = j[j["_merge"] == "both"]
    all_exact = (j["_merge"] == "both").all()
    for c in [c for c in st.columns if c not in ("id",)]:
        eq = b[f"{c}_stored"].astype(str) == b[f"{c}_fresh"].astype(str)
        if not eq.all():
            all_exact = False
            ex = b.loc[~eq, ["id", f"{c}_stored", f"{c}_fresh"]].head(3).to_dict("records")
            print(f"  {c:20s} {eq.mean():8.2%}   e.g. {ex}")
        else:
            print(f"  {c:20s} {eq.mean():8.2%}")
    print(f"REPRODUCE: {'EXACT -- the builder reproduces the stored file' if all_exact else 'NOT exact -- differences reported above'}")
    report = {"season": season, "year": year, "checked_at": datetime.now(timezone.utc).isoformat(),
              "rows_stored": len(st), "rows_fresh": len(fresh), "exact": bool(all_exact)}
    (HIST / "understat_aggregates_repro_check.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return all_exact


def build_season(season):
    players, year, completed = fetch_players_block(season)
    df = to_frame(players, year)
    tag = season.replace("-", "_")
    out = HIST / f"understat_season_aggregates_{tag}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(out)
    prov = {"season": season, "understat_season": str(year),
            "pulled_at": datetime.now(timezone.utc).isoformat(), "rows": len(df),
            "completed_matches_at_pull": completed,
            "note": "running as-of snapshot; Understat updates after each analysed match"}
    out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    log(f"-> {out.name}: {len(df)} rows as of {completed} completed matches")
    return df


def combine(season):
    tag = season.replace("-", "_")
    add = pd.read_parquet(HIST / f"understat_season_aggregates_{tag}.parquet")
    base = pd.read_parquet(STORED)
    assert list(add.columns) == list(base.columns), "schema drift vs the stored aggregates"
    assert (add.dtypes == base.dtypes).all(), "dtype drift vs the stored aggregates"
    year = add["understat_season"].iloc[0]
    assert year not in set(base["understat_season"].astype(str)), \
        f"understat_season {year} already in the stored file -- refusing to double-append"
    out = HIST / f"understat_season_aggregates_with_{tag}.parquet"
    combined = pd.concat([base, add], ignore_index=True)
    tmp = out.with_suffix(".tmp.parquet")
    combined.to_parquet(tmp, index=False)
    tmp.replace(out)
    log(f"COMBINED -> {out.name}: {len(base)} stored rows (untouched) + {len(add)} new")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season")
    ap.add_argument("--reproduce", metavar="SEASON")
    ap.add_argument("--combine", action="store_true")
    a = ap.parse_args()
    if a.reproduce:
        ok = reproduce(a.reproduce)
        sys.exit(0 if ok else 1)
    if a.combine:
        assert a.season, "--combine needs --season"
        combine(a.season)
        return
    assert a.season, "--season or --reproduce required"
    build_season(a.season)


if __name__ == "__main__":
    main()
