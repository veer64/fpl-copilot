"""fill_e0_stats.py -- fill the LIVE season's match-stat columns from football-data.co.uk's E0
file. Join, don't append; fill only what is null; never touch a score, a date or an odds column.

THE GAP (audit 2026-09-19/20): data/history/odds_all_seasons_with_{tag}.parquet carries HS/AS,
HST/AST, HC/AC, HF/AF, HY/AY, HR/AR, the half-time score and the referee for every archive
season, 380 of 380 -- and 0 of 380 for the live season, because the live rows are written by
fetch_fixtures.py from FPL's fixtures endpoint, which has none of those fields. The archive
seasons came from football-data's E0 files, which do, and football-data publishes the current
season's E0 file during the season, updated weekly.

WHAT THIS DOES. Navigates football-data's England page each run to find the season's Premier
League file (the URL is never constructed from memory -- their layout has changed before),
fetches it, caches the raw CSV beside the historical ones, and fills the FILL_COLS below on the
season's EXISTING rows of the combined archive, keyed on (date, home, away) after both sides
are mapped to FPL names through squad/team_map.py (TEAM_MAP, plus E0_PROMOTED_ALIAS for the
promoted clubs whose E0 spelling does not round-trip). Assertions BEFORE any write: every E0
match hits exactly one archive row; 0 unmapped names; the two sources agree on every joined
score (a disagreement means the join is wrong -- stop, do not pick a side); row count
unchanged; every column outside FILL_COLS byte-identical to before.

WHAT IT NEVER WRITES. Scores, dates, Div/Time, and ANY odds column. The live season's B365-named
columns hold the de-margined consensus pull (odds_live_pull provenance), not Bet365's prices;
the E0 file's B365 columns ARE Bet365's. Writing one over the other would mix two quantities
in one column. The provenance sidecar states the two origins explicitly.

RE-RUNNABLE. Fill only nulls, key on the match, never append: a second run fills 0 cells and
leaves the parquet byte-identical (measured). A new file is written and swapped in atomically
(tmp + os.replace, the repo's pattern); the archive is never mutated in place.

NOT DURABLE ACROSS THE WEEKLY INGEST -- by design of that ingest, not this script:
fetch_fixtures.combine() rebuilds the combined file from the frozen archive plus a slice that
is regenerated from the FPL API every newly-final gameweek, preserving only B365H/D/A
(fetch_fixtures.py, "PRESERVE PRICES ALREADY HELD"). So this fill is wiped by each ingest and
must run AFTER it. Whether fetch_fixtures should preserve these columns too is a separate
decision.

Usage:
  uv run python eval/fill_e0_stats.py --season 2026-27            # fetch, assert, fill, swap
  uv run python eval/fill_e0_stats.py --season 2026-27 --dry-run  # everything but the write
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))
from _replace_retry import replace_with_retry        # noqa: E402
from team_map import TEAM_MAP, e0_to_fpl             # noqa: E402  (the same map, not a copy)

SCRIPT_VERSION = "fill-e0-1"
SITE = "https://www.football-data.co.uk/"
INDEX_URL = SITE + "data.php"           # the site's data index; it links "England Football Results"
ENGLAND_URL = SITE + "englandm.php"     # navigated each run; the season's Premier League href is read here
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot ingestion; weekly; contact: repo owner)"}
TIMEOUT = 30

# The ONLY columns this script may write. Everything else is asserted unchanged after the fill.
FILL_COLS = ["HTHG", "HTAG", "HTR", "Referee",
             "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"]
KEY_SRC = ["Date", "HomeTeam", "AwayTeam"]


class E0FillError(RuntimeError):
    """Any assertion failure: reported, nothing written."""


# ------------------------------------------------------------------ discovery + fetch

def find_premier_league_href(html, season):
    """The Premier League CSV href under the England page's "Season YYYY/YYYY" heading for
    `season` ('2026-27' -> '2026/2027'). Read from the page, never constructed. Raises when
    the season heading or its Premier League link is absent (their layout has changed before)."""
    y0, y1 = season.split("-")
    label = f"Season {y0}/{y0[:2]}{y1}"
    heads = [(m.start(), m.group(0)) for m in re.finditer(r"Season \d{4}/\d{4}", html)]
    for i, (pos, text) in enumerate(heads):
        if text != label:
            continue
        end = heads[i + 1][0] if i + 1 < len(heads) else len(html)
        seg = html[pos:end]
        m = re.search(r"href=[\"']([^\"']+)[\"'][^>]*>\s*Premier League\s*<", seg, re.I)
        if not m:
            raise E0FillError(f"{ENGLAND_URL}: heading {label!r} found but no 'Premier League' "
                              f"link under it -- the page layout has changed; stopping")
        return m.group(1)
    raise E0FillError(f"{ENGLAND_URL}: no heading {label!r} on the England page (found "
                      f"{[h[1] for h in heads[:4]]}); the season's file is not listed; stopping")


def _get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    if r.status_code in (403, 429) or r.status_code >= 500:
        raise E0FillError(f"GET {url} -> HTTP {r.status_code}; stopping, not retrying")
    if r.status_code != 200:
        raise E0FillError(f"GET {url} -> HTTP {r.status_code}; stopping")
    return r


def fetch_e0(season, log=print):
    """Navigate England page -> season's Premier League href -> the CSV. Returns
    (raw bytes, url, response headers, navigation record)."""
    t0 = time.perf_counter()
    page = _get(ENGLAND_URL)
    href = find_premier_league_href(page.text, season)
    url = href if href.startswith("http") else SITE + href.lstrip("/")
    csv = _get(url)
    if not csv.content.startswith(b"\xef\xbb\xbf") and b"HomeTeam" not in csv.content[:2000]:
        raise E0FillError(f"{url}: response does not look like an E0 CSV (no header row); stopping")
    nav = {"index": INDEX_URL, "england_page": ENGLAND_URL, "href_on_page": href, "csv_url": url,
           "fetch_seconds": round(time.perf_counter() - t0, 2)}
    log(f"navigated {ENGLAND_URL} -> {href!r} -> GET {url}: {len(csv.content)} bytes, "
        f"last-modified {csv.headers.get('Last-Modified')}")
    return csv.content, url, dict(csv.headers), nav


def parse_e0(raw):
    """The E0 CSV as a frame with the archive's parsing conventions: utf-8 with BOM, and the
    SAME date parser as dixon_coles._load_matches -- format="mixed", dayfirst=True -- so a
    date here means what it means in the fit."""
    import io
    df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    df = df.dropna(subset=["HomeTeam", "AwayTeam"], how="any")          # trailing blank lines
    df["date_parsed"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    return df


# ------------------------------------------------------------------ the join and the fill

def _key(df, home_col, away_col, mapper):
    return pd.MultiIndex.from_arrays([df["date_parsed"].dt.normalize(),
                                      df[home_col].map(mapper), df[away_col].map(mapper)],
                                     names=["day", "home", "away"])


def plan_fill(archive, e0, season):
    """PURE. `archive` is the whole combined frame; `e0` the parsed E0 frame. Returns
    (filled frame, report). Raises E0FillError on any assertion; writes nothing."""
    is_season = archive["season"] == season
    arc = archive.loc[is_season].copy()
    if arc.empty:
        raise E0FillError(f"the archive holds no {season} rows; nothing to fill")
    # the archive's own date convention, applied to the season's rows
    arc["date_parsed"] = pd.to_datetime(arc["Date"], format="mixed", dayfirst=True)

    clubs = {TEAM_MAP.get(n, n) for n in set(arc["HomeTeam"]) | set(arc["AwayTeam"])}
    e0_names = set(e0["HomeTeam"]) | set(e0["AwayTeam"])
    unmapped = sorted(n for n in e0_names if e0_to_fpl(n) not in clubs)
    if unmapped:
        raise E0FillError(f"{len(unmapped)} E0 club name(s) map to no {season} archive club: "
                          f"{unmapped}; refusing to join (extend team_map.E0_PROMOTED_ALIAS "
                          f"only if the club is real and the spelling is new)")

    ak = _key(arc, "HomeTeam", "AwayTeam", lambda n: TEAM_MAP.get(n, n))
    ek = _key(e0, "HomeTeam", "AwayTeam", e0_to_fpl)
    if ak.duplicated().any():
        raise E0FillError(f"archive {season} rows are not unique on (day, home, away): "
                          f"{ak[ak.duplicated()].tolist()[:3]}")
    if ek.duplicated().any():
        raise E0FillError(f"E0 rows are not unique on (day, home, away): {ek[ek.duplicated()].tolist()[:3]}")

    arc_pos = pd.Series(range(len(arc)), index=ak)
    hit = arc_pos.reindex(ek)                              # E0 row -> archive position
    missing = [tuple(k) for k, v in zip(ek, hit.values) if pd.isna(v)]
    if missing:
        raise E0FillError(f"{len(missing)} E0 match(es) match NO archive row on (day, home, away): "
                          f"{[(str(d.date()), h, a) for d, h, a in missing[:5]]}; a rescheduled "
                          f"fixture or a spelling -- stopping, not guessing")
    pos = hit.values.astype(int)
    a_rows = arc.iloc[pos]

    # scores: where the archive has a result it must agree, else the join is wrong
    has_result = a_rows["FTHG"].notna().values & a_rows["FTAG"].notna().values
    e_h, e_a = e0["FTHG"].values.astype(float), e0["FTAG"].values.astype(float)
    disagree = has_result & ((a_rows["FTHG"].values != e_h) | (a_rows["FTAG"].values != e_a))
    if disagree.any():
        bad = [(str(d.date()), h, a, (int(x), int(y)), (int(p), int(q)))
               for (d, h, a), x, y, p, q in zip(ek[disagree], a_rows["FTHG"].values[disagree],
                                                 a_rows["FTAG"].values[disagree], e_h[disagree], e_a[disagree])]
        raise E0FillError(f"{int(disagree.sum())} joined match(es) DISAGREE on the score "
                          f"(archive vs E0): {bad[:5]}; the join is wrong -- stopping")

    # the lag, both ways: reported, never an error
    e0_ahead = int((~has_result).sum())                    # E0 has a result, the archive not yet
    arc_results = arc["FTHG"].notna() & arc["FTAG"].notna()
    archive_ahead = int(arc_results.sum() - has_result.sum())   # archive results E0 lacks

    # the fill: only rows with an agreed result, only FILL_COLS, only where null
    fill_rows = has_result
    filled = {}
    out = archive.copy()
    arc_index = arc.index[pos]                             # labels into the combined frame
    for c in FILL_COLS:
        if c not in out.columns or c not in e0.columns:
            filled[c] = None
            continue
        src = e0[c].values
        tgt_null = out.loc[arc_index, c].isna().values
        do = fill_rows & tgt_null & pd.notna(src)
        labels = arc_index[do]
        if len(labels):
            vals = pd.Series(src[do], index=labels)
            if out[c].dtype.kind == "f":
                vals = vals.astype("float64")
            out.loc[labels, c] = vals
        filled[c] = int(do.sum())

    # invariants: same rows, and nothing outside FILL_COLS moved
    if len(out) != len(archive):
        raise E0FillError("row count changed -- refusing to write")
    other = [c for c in archive.columns if c not in FILL_COLS]
    if not out[other].equals(archive[other]):
        raise E0FillError("a column outside FILL_COLS changed -- refusing to write")

    report = {
        "season": season, "e0_rows": int(len(e0)),
        "e0_date_range": [f"{e0['date_parsed'].min():%Y-%m-%d}", f"{e0['date_parsed'].max():%Y-%m-%d}"],
        "archive_rows_for_season": int(len(arc)), "archive_results": int(arc_results.sum()),
        "joined": int(len(e0)), "joined_with_agreed_result": int(has_result.sum()),
        "score_disagreements": 0, "unmapped_names": 0,
        "e0_ahead_of_archive": e0_ahead, "archive_ahead_of_e0": archive_ahead,
        "filled_per_column": filled, "cells_filled": int(sum(v for v in filled.values() if v)),
        "e0_only_columns_not_written": [c for c in e0.columns if c not in archive.columns and c != "date_parsed"],
        "populated_after": {c: int(out.loc[is_season, c].notna().sum()) for c in FILL_COLS if c in out.columns},
    }
    return out, report


# ------------------------------------------------------------------ entry point

def run(season, dry_run=False, log=print):
    t0 = time.perf_counter()
    tag = season.replace("-", "_")
    target = HIST / f"odds_all_seasons_with_{tag}.parquet"
    if not target.exists():
        raise E0FillError(f"{target.name} is missing; run fetch_fixtures --combine first")

    raw, url, headers, nav = fetch_e0(season, log=log)
    fetched_at = datetime.now(timezone.utc)
    raw_path = HIST / "odds" / f"E0_{season[2:4]}{season[5:7]}.csv"   # beside E0_1617.csv .. E0_2526.csv
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_raw = raw_path.with_suffix(".tmp.csv")
    tmp_raw.write_bytes(raw)
    replace_with_retry(tmp_raw, raw_path)
    e0 = parse_e0(raw)

    archive = pd.read_parquet(target)
    before_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    out, report = plan_fill(archive, e0, season)

    changed = report["cells_filled"] > 0
    if changed and not dry_run:
        tmp = target.with_suffix(".tmp.parquet")
        out.to_parquet(tmp, index=False)
        replace_with_retry(tmp, target)
    after_hash = hashlib.sha256(target.read_bytes()).hexdigest()

    prov = {
        "script": "eval/fill_e0_stats.py", "script_version": SCRIPT_VERSION,
        "season": season, "fetched_at": fetched_at.isoformat(),
        "source": "football-data.co.uk, current-season E0 (Premier League) CSV",
        "navigation": nav, "source_url": url,
        "source_last_modified": headers.get("Last-Modified"), "source_etag": headers.get("ETag"),
        "raw_cache": str(raw_path.relative_to(REPO)), "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "target": str(target.relative_to(REPO)),
        "target_sha256_before": before_hash, "target_sha256_after": after_hash,
        "wrote_target": bool(changed and not dry_run), "dry_run": dry_run,
        "columns_written": FILL_COLS,
        "origins_statement": (
            f"For {season}, the match-stat columns {FILL_COLS} come from football-data.co.uk's "
            f"E0 file (this script). The ODDS columns of the same rows -- B365H/B365D/B365A -- "
            f"come from the project's live odds pull (odds_live_pull_{tag}.provenance.json: a "
            f"de-margined multi-book consensus, NOT Bet365) and were NOT written by this script. "
            f"The E0 file's own B365 columns (real Bet365 prices) were deliberately not copied; "
            f"that is a separate column set and a separate decision. Scores and dates come from "
            f"fetch_fixtures.py (FPL's fixtures endpoint) and were only CHECKED here, never written."),
        "durability_note": ("fetch_fixtures.combine() rebuilds this file from the frozen archive plus "
                            "a slice regenerated every newly-final gameweek, preserving only B365H/D/A; "
                            "this fill is wiped by each ingest and must run after it."),
        "wall_clock_seconds": round(time.perf_counter() - t0, 2),
        **report,
    }
    prov_path = HIST / f"e0_live_stats_{tag}.provenance.json"
    prov_path.write_text(json.dumps(prov, indent=1), encoding="utf-8")
    log(f"{'DRY RUN: ' if dry_run else ''}{season}: E0 {report['e0_rows']} matches "
        f"({report['e0_date_range'][0]}..{report['e0_date_range'][1]}), archive results "
        f"{report['archive_results']}, joined {report['joined']}, filled {report['cells_filled']} cells "
        f"over {report['joined_with_agreed_result']} rows; E0 ahead {report['e0_ahead_of_archive']}, "
        f"archive ahead {report['archive_ahead_of_e0']}; unmapped 0; disagreements 0; "
        f"{'wrote' if prov['wrote_target'] else 'did not write'} {target.name}; "
        f"{prov['wall_clock_seconds']} s")
    return prov


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        run(a.season, dry_run=a.dry_run)
    except E0FillError as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
