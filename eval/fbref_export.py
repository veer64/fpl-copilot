"""fbref_export.py -- parse SAVED FBref competition pages from disk. Stage 2: many seasons.

ZERO REQUESTS. This module never fetches a URL: no requests, no urllib, no read_html against
an address, no browser automation. FBref sits behind a Cloudflare interactive challenge
(first-ever request from this project, 2026-09-20, robots.txt -> 403) and the decision is to
not go through it. The human saves each season's competition page in their own browser
(Ctrl+S, "Webpage, Complete") and passes a file or a folder. Tests assert the source imports
no HTTP client.

WHAT A SAVED COMPETITION PAGE HOLDS (measured on the 2026-27 page, 2026-09-20): ten squad
tables -- stats_squads_<category>_for and _against for standard, keeper, shooting,
playing_time, misc -- at 20 rows each; two results tables whose ids carry the season
(results2026-202791_overall / _home_away); and a `nations` table that appears TWICE with the
same id (a lazy-render copy inside an HTML comment, identical content). Everything is a
SEASON AGGREGATE, not per match. Possession is a COLUMN of stats_squads_standard_for, not a
page. xG appears nowhere (FBref lost its Opta licence in early 2026). No category list is
hardcoded as required: every file is inventoried for what it actually contains, and the
batch report says what each season had and lacked.

THE COMMENT TRAP. FBref lazy-renders tables inside <!-- ... -->. The markers are stripped
before parsing and every table is reported with whether it sat inside a comment as saved.

SEASON DETECTION. The live page's canonical link and title carry no season; the results
table id does. The season is read from the results ids, cross-checked against the page
heading, title and canonical wherever THEY carry one, and a disagreement STOPS the file.

TEAM NAMES. FBref spellings match neither FPL nor football-data ("Manchester Utd",
"Nottingham", "Leeds United"; "vs Arsenal" on the _against side). The bridge is
team_map.FBREF_TEAM_MAP (one module, beside TEAM_MAP), then the fit's own
dixon_coles.ARCHIVE_NAME_ALIAS as a per-season fallback because the FPL side itself drifts
("Ipswich" in 2024-25, "Ipswich Town" in 2026-27). The target club set per season is
MEASURED from the vaastav stack, and 0 unmapped is asserted per season: a season with an
unmapped name gets no CSVs and the run exits non-zero after processing every file.

Output: data/fbref/<season>/<category>/<table_id>.csv, UTF-8 (no BOM), accents intact,
metadata columns first on every row, FBref's data-stat names for the stats, id/href columns
beside the values. One provenance sidecar per season.

Usage:
  uv run python eval/fbref_export.py "<saved .html>"                  # one file
  uv run python eval/fbref_export.py --batch "<folder of saved .html>" # every file, one report
  options: --out data/fbref   --no-csv   --json <path>
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
from team_map import FBREF_TEAM_MAP                    # noqa: E402  (one module, never a copy)

DEFAULT_OUT = REPO / "data" / "fbref"
SCRIPT_VERSION = "fbref-export-2"
STAT_ID_PREFIXES = ("stats_", "keeper", "shooting", "playingtime", "playing_time", "misc")
SQUAD_ID_RE = re.compile(r"^stats_squads_(?P<category>[a-z_]+?)_(?P<side>for|against)$")
RESULTS_ID_RE = re.compile(r"^results(?P<season>\d{4}-\d{4})\d*_(?P<kind>overall|home_away)$")
SEASON_RE = re.compile(r"(\d{4})-(\d{4})")
SQUAD_HREF_RE = re.compile(r"/squads/([0-9a-f]{8})/")
SKIP_IDS = {"nations"}          # a nationality breakdown with a player list, not a squad stat table
META_COLS = ["season", "competition", "category", "table_type", "source_file", "saved_at",
             "team_fbref", "team", "team_fbref_id"]


class FbrefExportError(RuntimeError):
    """A file that must not be written: season mismatch, unknown season, unmapped club."""


# ------------------------------------------------------------------ the comment trap

def uncomment(html):
    """Strip HTML comment markers so lazy-rendered tables parse. Returns (html, ids of tables
    that were inside a comment block in the file as saved)."""
    wrapped = set()
    for block in re.findall(r"<!--(.*?)-->", html, flags=re.S):
        wrapped.update(re.findall(r'<table[^>]*\bid="([^"]+)"', block))
    return html.replace("<!--", "").replace("-->", ""), wrapped


# ------------------------------------------------------------------ tables

def _is_repeated_header(tr):
    cls = tr.get("class") or []
    if "thead" in cls or "over_header" in cls:
        return True
    first = tr.find(["th", "td"])
    return first is not None and first.get("data-stat") == "ranker" and first.get_text(strip=True) == "Rk"


def header_info(table):
    """(data-stat names in order, over-header group per name, header text per name) from the
    table's LAST header row -- the one carrying data-stat -- plus its over_header row."""
    thead = table.find("thead")
    if thead is None:
        return [], {}, {}
    rows = thead.find_all("tr")
    if not rows:
        return [], {}, {}
    main = rows[-1]
    names, text = [], {}
    for th in main.find_all(["th", "td"]):
        ds = th.get("data-stat")
        if ds is None:
            continue
        names.append(ds)
        text[ds] = th.get_text(strip=True)
    groups = {}
    over = [r for r in rows[:-1] if "over_header" in (r.get("class") or [])]
    if over:
        cells = []
        for th in over[-1].find_all(["th", "td"]):
            span = int(th.get("colspan") or 1)
            cells.extend([th.get_text(strip=True)] * span)
        for i, n in enumerate(names):
            groups[n] = cells[i] if i < len(cells) else ""
    return names, groups, text


def parse_table(table):
    """Rows as dicts keyed by data-stat, plus '<stat>_id' (data-append-csv) and '<stat>_href'
    columns where a cell carries them. Repeated header rows and 'Rk' rows are dropped."""
    names, groups, text = header_info(table)
    body = table.find("tbody")
    rows = []
    if body is None:
        return names, groups, text, rows
    for tr in body.find_all("tr"):
        if _is_repeated_header(tr) or "spacer" in (tr.get("class") or []):
            continue
        cells = tr.find_all(["th", "td"])
        if not cells or all(c.get_text(strip=True) == "" for c in cells):
            continue
        row = {}
        for c in cells:
            ds = c.get("data-stat")
            if ds is None:
                continue
            row[ds] = c.get_text(strip=True)
            if c.get("data-append-csv"):
                row[f"{ds}_id"] = c["data-append-csv"]
            a = c.find("a", href=True)
            if a is not None:
                row[f"{ds}_href"] = a["href"]
        if row:
            rows.append(row)
    return names, groups, text, rows


def classify(table_id, names, rows):
    """'stat' when the header carries data-stat names and the body has data rows; else 'other'
    (navigation, layout, junk). Both the id pattern and the structure count."""
    structural = bool(names) and len(rows) > 0
    by_id = bool(table_id) and table_id.startswith(STAT_ID_PREFIXES)
    if structural:
        return "stat" if by_id else "stat (unfamiliar id)"
    return "other"


def inventory(html_path):
    """Everything about one saved page: meta, every table (kind / rows / cols / comment
    flag), parsed rows of the stat tables. Duplicate ids are kept as separate entries here;
    process_file decides what to do with them."""
    raw = Path(html_path).read_text(encoding="utf-8", errors="replace")
    html, wrapped = uncomment(raw)
    soup = BeautifulSoup(html, "html.parser")
    meta = page_meta(soup, html_path)
    tables = []
    for i, t in enumerate(soup.find_all("table")):
        tid = t.get("id") or f"(no id #{i})"
        names, groups, text, rows = parse_table(t)
        kind = classify(t.get("id"), names, rows)
        entry = {"id": tid, "kind": kind, "n_rows": len(rows), "n_cols": len(names),
                 "wrapped_in_comment": t.get("id") in wrapped,
                 "class": " ".join(t.get("class") or []),
                 "caption": t.caption.get_text(strip=True) if t.caption else None}
        if kind != "other":
            populated = {n: sum(1 for r in rows if r.get(n, "") != "") for n in names}
            entry.update({"columns": names, "over_header": groups, "header_text": text,
                          "populated": populated,
                          "all_null_columns": [n for n in names if populated[n] == 0],
                          "extra_columns": sorted({k for r in rows for k in r} - set(names)),
                          "rows": rows})
        tables.append(entry)
    return {"meta": meta, "comment_blocks_with_tables": len(wrapped), "tables": tables}


# ------------------------------------------------------------------ page metadata + season

def page_meta(soup, path):
    title = soup.title.get_text(strip=True) if soup.title else None
    canon = soup.find("link", rel="canonical")
    url = canon.get("href") if canon else None
    h1 = soup.find("h1")
    heading = " ".join(h1.get_text(" ", strip=True).split()) if h1 else None
    competition = None
    for text in (heading, title):
        if text:
            m = re.search(r"(?:\d{4}-\d{4}\s+)?(.+?)\s+Stats", text)
            if m:
                competition = m.group(1).strip()
                break
    p = Path(path)
    st = p.stat()
    return {"saved_file": str(p), "saved_bytes": st.st_size,
            "saved_mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "title": title, "canonical_url": url, "heading": heading, "competition": competition}


def _season_in(text):
    m = SEASON_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def detect_season(inv):
    """The season from the results table ids, cross-checked against heading, title and
    canonical wherever they carry one. Disagreement or no evidence -> FbrefExportError."""
    from_results = sorted({m.group("season") for t in inv["tables"]
                           for m in [RESULTS_ID_RE.match(t["id"])] if m})
    meta = inv["meta"]
    others = {k: _season_in(meta.get(k)) for k in ("heading", "title", "canonical_url")}
    evidence = {"results_ids": from_results, **others}
    if len(from_results) > 1:
        raise FbrefExportError(f"results table ids name more than one season {from_results}: {evidence}")
    candidates = set(from_results) | {v for v in others.values() if v}
    if not candidates:
        raise FbrefExportError(f"no season on the page: no results table id, and heading/title/"
                               f"canonical carry none ({evidence}); refusing to guess")
    if len(candidates) > 1:
        raise FbrefExportError(f"season DISAGREES between sources {evidence}; stopping rather than guessing")
    return candidates.pop(), evidence


# ------------------------------------------------------------------ team names

def club_sets():
    """{season: set of FPL/vaastav club names} measured from the stack -- the target side of
    the bridge, per season, because the FPL side itself drifts across seasons."""
    from season_stack import load_stack
    df = load_stack(columns=["season", "team"]).dropna()
    return {s: set(g["team"].unique()) for s, g in df.groupby("season")}


def bridge_name(raw, season, clubs):
    """(FPL name or None, fbref spelling without the 'vs ' prefix). FBREF_TEAM_MAP first, then
    the fit's ARCHIVE_NAME_ALIAS for a season whose FPL spelling is the archive's ("Ipswich"),
    then None -- never a guess."""
    name = raw[3:] if raw.startswith("vs ") else raw
    mapped = FBREF_TEAM_MAP.get(name, name)
    if clubs is None:
        return mapped, name
    if mapped in clubs:
        return mapped, name
    from dixon_coles import ARCHIVE_NAME_ALIAS
    alt = ARCHIVE_NAME_ALIAS.get(mapped)
    if alt in clubs:
        return alt, name
    return None, name


# ------------------------------------------------------------------ one file

def stack_season(season):
    """FBref writes '2026-2027'; the stack keys '2026-27'. One normalisation, used for the
    club-set lookup only -- the CSVs keep FBref's own season string."""
    m = SEASON_RE.fullmatch(season or "")
    return f"{m.group(1)}-{m.group(2)[2:]}" if m else season


def _table_type(tid):
    m = SQUAD_ID_RE.match(tid)
    if m:
        return f"squad_{m.group('side')}", m.group("category")
    r = RESULTS_ID_RE.match(tid)
    if r:
        return f"results_{r.group('kind')}", "results"
    return None, None


def _dedupe(entries):
    """Same id twice: identical rows -> keep one and note it; different rows -> keep both,
    the second suffixed, and note it loudly. Never silently the first."""
    by_id, notes, out = {}, [], []
    for e in entries:
        by_id.setdefault(e["id"], []).append(e)
    for tid, group in by_id.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        first = group[0]
        out.append(first)
        def _values(e):                                   # hrefs differ between the rendered copy
            return [{k: v for k, v in r.items() if not k.endswith("_href")}   # (absolute) and the
                    for r in e.get("rows", [])]                               # commented one (relative)
        for k, other in enumerate(group[1:], 2):
            same = _values(other) == _values(first) and other.get("columns") == first.get("columns")
            if same:
                notes.append(f"{tid}: {len(group)} copies with identical content, one kept")
            else:
                dup = dict(other, id=f"{tid}__dup{k}")
                out.append(dup)
                notes.append(f"{tid}: copy {k} DIFFERS from the first, kept as {dup['id']}")
    return out, notes


def process_file(html_path, clubs_by_season=None, out_root=DEFAULT_OUT, write=True):
    """Inventory -> season -> bridge -> CSVs + sidecar for one saved page. Returns the report.
    Raises FbrefExportError on a season problem. Unmapped names are returned in the report
    (write skipped), not raised, so a batch can finish and report every file."""
    t0 = time.perf_counter()
    inv = inventory(html_path)
    season, evidence = detect_season(inv)
    meta = inv["meta"]
    clubs = None
    if clubs_by_season is not None:
        clubs = clubs_by_season.get(stack_season(season))
        if clubs is None:
            raise FbrefExportError(f"no club set for {season} ({stack_season(season)}) in the stack; "
                                   f"team names cannot be verified for this season -- stopping")
    stat_tables = [t for t in inv["tables"] if t["kind"] != "other"]
    kept, dup_notes = _dedupe(stat_tables)
    skipped = [t["id"] for t in kept if t["id"].split("__dup")[0] in SKIP_IDS]
    kept = [t for t in kept if t["id"].split("__dup")[0] not in SKIP_IDS]

    unmapped = {}
    tables_out = []
    for t in kept:
        ttype, category = _table_type(t["id"].split("__dup")[0])
        if ttype is None:
            skipped.append(t["id"])
            continue
        rows = []
        for r in t["rows"]:
            raw = r.get("team", "")
            fpl, fb = bridge_name(raw, season, clubs)
            if fpl is None:
                unmapped.setdefault(fb, []).append(t["id"])
            href = r.get("team_href", "")
            m = SQUAD_HREF_RE.search(href)
            row = dict(r)                                   # the stats, as parsed
            row.update({"season": season, "competition": meta["competition"], "category": category,
                        "table_type": ttype, "source_file": Path(html_path).name,
                        "saved_at": meta["saved_mtime"], "team_fbref": fb, "team": fpl,
                        "team_fbref_id": m.group(1) if m else None})   # metadata wins: `team` is the FPL name
            rows.append(row)
        tables_out.append({"id": t["id"], "category": category, "table_type": ttype,
                           "n_rows": len(rows), "columns": t["columns"], "over_header": t["over_header"],
                           "header_text": t["header_text"], "populated": t["populated"],
                           "all_null_columns": t["all_null_columns"], "extra_columns": t["extra_columns"],
                           "wrapped_in_comment": t["wrapped_in_comment"], "rows": rows})

    categories = sorted({t["category"] for t in tables_out if t["category"] != "results"})
    std = next((t for t in tables_out if t["id"] == "stats_squads_standard_for"), None)
    possession = (std["populated"].get("possession", 0) if std else 0, std["n_rows"] if std else 0)
    written = []
    if write and not unmapped:
        written = write_season(season, meta, tables_out, out_root, evidence, categories, possession,
                               skipped, dup_notes, html_path)
    report = {"file": str(html_path), "season": season, "season_evidence": evidence,
              "competition": meta["competition"], "categories": categories,
              "tables": [{k: v for k, v in t.items() if k != "rows"} for t in tables_out],
              "n_tables": len(tables_out), "skipped_tables": skipped, "duplicate_notes": dup_notes,
              "unmapped": {k: sorted(set(v)) for k, v in unmapped.items()},
              "possession_populated": possession, "written": [str(p) for p in written],
              "seconds": round(time.perf_counter() - t0, 2)}
    return report


def write_season(season, meta, tables_out, out_root, evidence, categories, possession, skipped,
                 dup_notes, html_path):
    out_dir = Path(out_root) / season
    written = []
    for t in tables_out:
        d = out_dir / t["category"]
        d.mkdir(parents=True, exist_ok=True)
        cols = META_COLS + [c for c in t["columns"] if c not in META_COLS] \
            + [c for c in t["extra_columns"] if c not in META_COLS]
        p = d / f"{t['id']}.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in t["rows"]:
                w.writerow(r)
        written.append(p)
    prov = {
        "source": "FBref (fbref.com), MANUAL browser save by the human -- no request made by code",
        "script": "eval/fbref_export.py", "script_version": SCRIPT_VERSION,
        "season": season, "season_evidence": evidence, "competition": meta["competition"],
        "page_title": meta["title"], "page_heading": meta["heading"], "page_url": meta["canonical_url"],
        "saved_file": meta["saved_file"], "saved_at": meta["saved_mtime"], "saved_bytes": meta["saved_bytes"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "categories_captured": categories,
        "tables": {t["id"]: {"category": t["category"], "table_type": t["table_type"], "rows": t["n_rows"],
                             "columns": len(t["columns"]), "all_null_columns": t["all_null_columns"],
                             "was_inside_html_comment": t["wrapped_in_comment"]} for t in tables_out},
        "skipped_tables": skipped, "duplicate_id_notes": dup_notes,
        "possession_populated": f"{possession[0]} of {possession[1]} squads (stats_squads_standard_for)",
        "statement": ("SEASON AGGREGATES, NOT PER-MATCH. xG is UNAVAILABLE on these pages (FBref lost "
                      "its Opta licence in early 2026) -- no xG column exists here and none was "
                      "omitted. POSSESSION is sourced from the Standard table's `possession` column; "
                      "there is no Possession page and no Passing page as of 2026-09-20. Team names in "
                      "`team` are FPL spellings via team_map.FBREF_TEAM_MAP (+ the fit's archive alias "
                      "where a season's FPL spelling is the archive's); `team_fbref` is FBref's own."),
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=1, ensure_ascii=False), encoding="utf-8")
    return written + [out_dir / "provenance.json"]


# ------------------------------------------------------------------ batch + reports

def batch(folder, out_root=DEFAULT_OUT, write=True):
    t0 = time.perf_counter()
    files = sorted(Path(folder).glob("*.html")) + sorted(Path(folder).glob("*.htm"))
    if not files:
        raise FbrefExportError(f"no .html files in {folder}")
    clubs = club_sets()
    reports, failures = [], []
    for f in files:
        try:
            reports.append(process_file(f, clubs, out_root, write=write))
        except FbrefExportError as e:
            failures.append({"file": str(f), "error": str(e)})
    result = {"reports": reports, "failures": failures, "seconds": round(time.perf_counter() - t0, 2)}
    if write:
        write_root_provenance(result, clubs, out_root)
    return result


def write_root_provenance(result, clubs, out_root):
    """<out>/provenance.json: what the batch covered and, explicitly, where coverage STARTS and
    why -- team names can only be verified against seasons the stack holds, so a saved page
    for an earlier season is refused by the guard, not silently accepted."""
    first = min(clubs) if clubs else None
    on_disk = sorted(p.parent.name for p in Path(out_root).glob("*/provenance.json"))
    prov = {
        "source": "FBref (fbref.com), MANUAL browser saves by the human -- no request made by code",
        "script": "eval/fbref_export.py", "script_version": SCRIPT_VERSION,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "seasons_on_disk": on_disk,                       # every season folder with a sidecar, however it got there
        "seasons_written_this_run": sorted(r["season"] for r in result["reports"] if r["written"]),
        "seasons_withheld_unmapped": {r["season"]: sorted(r["unmapped"]) for r in result["reports"] if r["unmapped"]},
        "files_refused": [{"file": Path(f["file"]).name, "reason": f["error"]} for f in result["failures"]],
        "coverage_statement": (
            f"Coverage starts at {first} (stack season key), the first season the vaastav stack "
            f"holds, because a club name can only be verified against the season's club set "
            f"measured from the stack; the odds archive starts there too. Saved pages for earlier "
            f"seasons are REFUSED by the name-verification guard and listed in files_refused -- "
            f"not processed with unverified names, and no hand-written club list substitutes."),
        "wall_clock_seconds": result["seconds"],
    }
    Path(out_root).mkdir(parents=True, exist_ok=True)
    (Path(out_root) / "provenance.json").write_text(json.dumps(prov, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")


def summary_text(result):
    reports, failures = result["reports"], result["failures"]
    lines = []
    all_cats = sorted({c for r in reports for c in r["categories"]})
    lines.append(f"{'season':10s} {'category':14s} {'for':>4s} {'against':>8s}  null columns")
    for r in sorted(reports, key=lambda r: r["season"]):
        by = {(t["category"], t["table_type"]): t for t in r["tables"]}
        for c in all_cats:
            f_, a_ = by.get((c, "squad_for")), by.get((c, "squad_against"))
            nulls = sorted(set((f_ or {}).get("all_null_columns", [])) | set((a_ or {}).get("all_null_columns", [])))
            lines.append(f"{r['season']:10s} {c:14s} {(f_['n_rows'] if f_ else '-')!s:>4s} "
                         f"{(a_['n_rows'] if a_ else '-')!s:>8s}  {', '.join(nulls) if nulls else ''}")
        for t in r["tables"]:
            if t["category"] == "results":
                lines.append(f"{r['season']:10s} {t['id']:38s} {t['n_rows']:>4d}")
    lines.append("")
    lines.append("missing categories per season:")
    for r in sorted(reports, key=lambda r: r["season"]):
        miss = [c for c in all_cats if c not in r["categories"]]
        lines.append(f"  {r['season']}: {', '.join(miss) if miss else 'none (all of ' + ', '.join(all_cats) + ')'}")
    lines.append("")
    lines.append("possession populated (stats_squads_standard_for):")
    for r in sorted(reports, key=lambda r: r["season"]):
        n, d = r["possession_populated"]
        lines.append(f"  {r['season']}: {n} of {d}")
    lines.append("")
    lines.append("unmapped team names per season (CSVs withheld where non-empty):")
    for r in sorted(reports, key=lambda r: r["season"]):
        lines.append(f"  {r['season']}: {r['unmapped'] if r['unmapped'] else 0}")
    for r in reports:
        if r["duplicate_notes"] or r["skipped_tables"]:
            lines.append(f"  {r['season']}: skipped {r['skipped_tables']}; {'; '.join(r['duplicate_notes'])}")
    if failures:
        lines.append("")
        lines.append("FAILED files:")
        for f in failures:
            lines.append(f"  {f['file']}: {f['error']}")
    lines.append("")
    lines.append(f"wall-clock: {result['seconds']} s for {len(reports) + len(failures)} file(s)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Inventory and export the tables of SAVED FBref pages (no requests).")
    ap.add_argument("html", nargs="?", help="one saved .html file")
    ap.add_argument("--batch", help="a folder of saved .html files")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--json", help="write the report here as well")
    a = ap.parse_args()
    if not a.html and not a.batch:
        ap.error("give a file or --batch <folder>")
    if a.batch:
        result = batch(a.batch, a.out, write=not a.no_csv)
    else:
        try:
            rep = process_file(a.html, club_sets(), a.out, write=not a.no_csv)
            result = {"reports": [rep], "failures": [], "seconds": rep["seconds"]}
        except FbrefExportError as e:
            result = {"reports": [], "failures": [{"file": a.html, "error": str(e)}], "seconds": 0}
    print(summary_text(result))
    for r in result["reports"]:
        for p in r["written"]:
            print(f"-> {p}")
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    bad = result["failures"] or any(r["unmapped"] for r in result["reports"])
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
