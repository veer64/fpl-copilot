"""News ingestion v1 (2026-09-25): BBC Premier League RSS and FPL availability news into
Postgres, ONE ROW PER VERSION of an item, plus the view that builds the exact text a later
embedding layer will see. No embedding, no pgvector, no relevance filter here.

"Team news" = whether a Premier League player is available for the next gameweek.

TABLE news_items (DDL below; the db_write.py pattern: idempotent CREATE ... IF NOT EXISTS
run by ensure_schema() on every connect, no migration tool exists in this repo):
  * (source, guid, version) is THE unique key. The versioning rule (bug 1, 2026-09-25): a
    candidate becomes a new version iff its content_hash differs from the LATEST stored
    version of that guid -- never "from every version". So the same raw input twice
    changes nothing (identical to the latest -> skipped), a new guid is v1, a change is
    v(n+1), and a flag that goes d -> cleared -> d with identical text is v1, v2, v3 with
    v3 ACTIVE. The first cut had UNIQUE (source, guid, content_hash) and lost exactly that
    re-flag; the constraint is dropped by the DDL on existing tables.
  * fetched_at is indexed for the as-of reads.

BBC: guid = <guid> text, falling back to the canonical <link>; content_hash over
(headline, body); published_at = pubDate as UTC (RFC 822 numeric offsets and the named
zones in NAMED_ZONES -- an unknown zone is an ERROR, never a guess); fetched_at = the
fetch time; raw_ref = the gzipped response saved BEFORE parsing (raw first). Fetches are
conditional (ETag / Last-Modified from the previous 200); a 304 stores nothing and writes
no file. The User-Agent names the project and the repo; it never impersonates a browser.

FPL: derived from the raw bootstrap-static archive (data/live/bootstrap_raw/<season>/,
every origin: poller polls, build fetches, news fetches), chronologically. guid
'fpl:<element_id>'; content_hash over (status, news, chance_of_playing_NEXT_round) -- the
chance column IS next_round (bug 2, 2026-09-25): measured over the server archive, the
news text's "<N>% chance" equals next_round in 819 of 819 rows and this_round alone in
none; this_round is the round already under way, next_round the deadline gameweek a
manager is picking for;
headline '<web_name> (<team short name>, <position>)'; published_at = news_added;
fetched_at = the snapshot time; raw_ref = the archive path of the snapshot. A player is
"flagged" when the news string is non-empty or the status is not 'a'. A CLEARED flag is a
new version with an empty body, the status and chance as reported, published_at NULL
(FPL does not bump news_added when it clears a flag, so its claim would be stale) and
fetched_at = the FIRST snapshot where the news was gone.

Raw RSS files live under data/news/raw/<source>/ -- on the model-data volume OUTSIDE
data/live/, so the off-site backup (eval/backup_b2.py, which excludes only live/) carries
them. The FPL raw_ref points into data/live/bootstrap_raw/, which the backup does NOT
carry (KNOWN_ISSUES #26).
"""
import gzip
import hashlib
import html
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_tz
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent
RAW_DIR = REPO / "data" / "news" / "raw"
USER_AGENT = "fpl-copilot news ingest (+https://github.com/veer64/fpl-copilot)"
BBC_URL = "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml"
SOURCES = ("bbc", "fpl", "club")
STATUS_WORDS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended",
                "u": "unavailable", "n": "not in squad"}
# RFC 822 named zones that feeds actually use. email.utils knows GMT/UT/UTC/Z and the US
# zones; BST (what Sky Sports stamps) it does not. Anything else is an error, not a guess.
NAMED_ZONES = {"GMT": 0, "UT": 0, "UTC": 0, "Z": 0, "BST": 3600, "IST": 3600, "WET": 0, "WEST": 3600,
               "CET": 3600, "CEST": 7200, "EET": 7200, "EEST": 10800,
               "EST": -18000, "EDT": -14400, "CST": -21600, "CDT": -18000,
               "MST": -25200, "MDT": -21600, "PST": -28800, "PDT": -25200}

DDL = """
CREATE TABLE IF NOT EXISTS news_items (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL CHECK (source IN ('bbc', 'fpl', 'club')),
    guid          TEXT NOT NULL,
    version       INT  NOT NULL CHECK (version >= 1),
    url           TEXT,
    headline      TEXT NOT NULL,
    body          TEXT NOT NULL DEFAULT '',
    published_at  TIMESTAMPTZ,                      -- the source's claim, UTC; NULL when it has none
    fetched_at    TIMESTAMPTZ NOT NULL,             -- when WE observed this version
    content_hash  TEXT NOT NULL,
    raw_ref       TEXT NOT NULL,                    -- the raw file this version was parsed from
    element_id    INT,                              -- fpl only
    status        TEXT,                             -- fpl only
    chance        INT,                              -- fpl only: chance_of_playing_NEXT_round
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- the first cut's hash-unique constraint (dropped 2026-09-25, bug 1): a re-flag after a clear
-- repeats an earlier version's hash and must be stored
ALTER TABLE news_items DROP CONSTRAINT IF EXISTS news_items_source_guid_content_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS ux_news_items_version ON news_items (source, guid, version);
CREATE INDEX IF NOT EXISTS ix_news_items_fetched ON news_items (fetched_at);
-- 2026-09-25, club news: a third source, the club the row belongs to, and HOW the row is dated:
--   'feed' (RSS pubDate), 'source_field' (FPL news_added), 'url' (a day-level date in the URL),
--   'first_seen' (no claim; fetched_at is the only time), 'backlog' (seeded history, date unknown)
ALTER TABLE news_items DROP CONSTRAINT IF EXISTS news_items_source_check;
ALTER TABLE news_items ADD CONSTRAINT news_items_source_check CHECK (source IN ('bbc', 'fpl', 'club'));
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS club        TEXT;
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS date_source TEXT;
UPDATE news_items SET date_source = CASE
    WHEN source = 'bbc' THEN 'feed'
    WHEN source = 'fpl' AND published_at IS NOT NULL THEN 'source_field'
    WHEN source = 'fpl' THEN 'first_seen'
    END
WHERE date_source IS NULL AND source IN ('bbc', 'fpl');
CREATE INDEX IF NOT EXISTS ix_news_items_club ON news_items (club) WHERE club IS NOT NULL;

-- every Tavily call, with the credits it cost by Tavily's published rule (club_news.py's
-- credit guard sums this month's rows before any call)
CREATE TABLE IF NOT EXISTS tavily_calls (
    id         BIGSERIAL PRIMARY KEY,
    called_at  TIMESTAMPTZ NOT NULL,
    endpoint   TEXT NOT NULL,                       -- 'search' | 'extract'
    club       TEXT,
    query      TEXT,
    n_results  INT,
    credits    INT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tavily_calls_at ON tavily_calls (called_at);

-- The exact chunk string the embedding layer will see (2026-09-25 spec):
--   RSS: "[BBC Sport | YYYY-MM-DD HH:MMZ] <headline>\\n<body>"
--   FPL: "[FPL official | published_at, or fetched_at if null] <headline>\\n
--         Status: <word>. <chance>% chance of playing. <news>"   (chance sentence omitted when null;
--         a cleared version reads "Status: available. No injury news (flag cleared).")
--   club: "[<Club> official site | published_at as YYYY-MM-DD, or 'first seen <fetched_at date>',
--          or 'date unknown (backlog)'] <headline>\\n<body>"
CREATE OR REPLACE VIEW news_embed_text AS
SELECT id, source, guid, version, fetched_at, embed_text, length(embed_text) AS char_count
FROM (
    SELECT id, source, guid, version, fetched_at,
        CASE source
            WHEN 'bbc' THEN
                '[BBC Sport | ' || to_char(COALESCE(published_at, fetched_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
                || 'Z] ' || headline || E'\\n' || body
            WHEN 'fpl' THEN
                '[FPL official | ' || to_char(COALESCE(published_at, fetched_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
                || 'Z] ' || headline || E'\\n'
                || CASE
                     WHEN body = '' AND status = 'a' THEN 'Status: available. No injury news (flag cleared).'
                     ELSE rtrim('Status: '
                          || CASE status WHEN 'a' THEN 'available' WHEN 'd' THEN 'doubtful' WHEN 'i' THEN 'injured'
                                         WHEN 's' THEN 'suspended' WHEN 'u' THEN 'unavailable' WHEN 'n' THEN 'not in squad'
                                         ELSE COALESCE(status, 'unknown') END
                          || '.'
                          || CASE WHEN chance IS NOT NULL THEN ' ' || chance::text || '% chance of playing.' ELSE '' END
                          || ' ' || body)
                   END
            WHEN 'club' THEN
                '[' || COALESCE(club, 'Club') || ' official site | '
                || CASE
                     WHEN published_at IS NOT NULL THEN to_char(published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                     WHEN date_source = 'backlog' THEN 'date unknown (backlog)'
                     ELSE 'first seen ' || to_char(fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                   END
                || '] ' || headline || E'\\n' || body
        END AS embed_text
    FROM news_items
) t;
"""


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


# ---- pure helpers -----------------------------------------------------------------------

def content_hash(*parts):
    """sha256 over the parts, None and '' distinct from each other only by position, never
    by absence: every part is always present, joined by a unit separator."""
    h = hashlib.sha256()
    for p in parts:
        h.update(("" if p is None else str(p)).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def parse_rfc822(text):
    """RFC 822 date -> aware UTC datetime, or None when it cannot be read. Numeric offsets
    and the named zones in NAMED_ZONES; '-0000' (RFC 5322: UTC, local unknown) is UTC."""
    if not text:
        return None
    t = str(text).strip()
    parsed = parsedate_tz(t)
    if parsed is None:
        return None
    # The zone is read HERE, not from parsedate_tz: that function treats an alphabetic zone
    # it does not know (BST, XYZ, ...) as offset zero, which is exactly the silent guess this
    # parser refuses to make.
    zone = t.split()[-1].strip()
    if re.fullmatch(r"[+-]\d{4}", zone):
        sign = -1 if zone[0] == "-" else 1
        offset = sign * (int(zone[1:3]) * 3600 + int(zone[3:5]) * 60)
    elif zone.upper() in NAMED_ZONES:
        offset = NAMED_ZONES[zone.upper()]
    else:
        return None
    try:
        local = datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return local - timedelta(seconds=offset)


def parse_iso_utc(text):
    if not text:
        return None
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(s):
    """Tags removed, entities unescaped, whitespace collapsed. The body is text to embed."""
    if s is None:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", str(s)))).strip()


def parse_rss(xml_bytes):
    """RSS 2.0 bytes -> ([item dict], [error string]). An item without guid AND link is an
    error and is dropped; an unparseable pubDate is an error and the item keeps
    published_at None."""
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    nodes = (channel if channel is not None else root).findall("item")
    items, errors = [], []
    for i, it in enumerate(nodes):
        guid = (it.findtext("guid") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not guid and not link:
            errors.append(f"item {i}: no guid and no link; dropped")
            continue
        guid = guid or link
        pub_text = (it.findtext("pubDate") or "").strip()
        published = parse_rfc822(pub_text) if pub_text else None
        if pub_text and published is None:
            errors.append(f"{guid}: unparseable pubDate {pub_text!r}; published_at left NULL")
        items.append({"guid": guid, "url": link or guid,
                      "headline": strip_html(it.findtext("title")),
                      "body": strip_html(it.findtext("description")),
                      "published_at": published})
    return items, errors


# ---- the versioned store ----------------------------------------------------------------

_COLS = ("source", "guid", "version", "url", "headline", "body", "published_at", "fetched_at",
         "content_hash", "raw_ref", "element_id", "status", "chance", "club", "date_source")
_DEFAULT_DATE_SOURCE = {"bbc": "feed"}          # fpl is decided per row: source_field when it has a claim, else first_seen


def upsert_versions(conn, source, candidates):
    """Each candidate: guid, url, headline, body, published_at, fetched_at, content_hash,
    raw_ref, element_id, status, chance. A candidate is compared against the version that
    was CURRENT at its own fetched_at (the newest stored version observed at or before it):
    same hash -> skipped, else it is stored as the next version number. When the archive is
    processed chronologically that reference is simply the latest version, so d -> cleared
    -> d with identical text is v1, v2, v3; and re-processing a snapshot that was already
    processed is a no-op, because each of its candidates meets the version it created.
    Returns {new, new_versions, skipped}. One transaction; candidates for one guid within a
    call are applied in order."""
    assert source in SOURCES, source
    counts = {"new": 0, "new_versions": 0, "skipped": 0}
    with conn.cursor() as cur:
        for c in candidates:
            cur.execute("SELECT content_hash FROM news_items WHERE source = %s AND guid = %s AND fetched_at <= %s "
                        "ORDER BY fetched_at DESC, version DESC LIMIT 1", (source, c["guid"], c["fetched_at"]))
            ref = cur.fetchone()
            if ref is not None and ref[0] == c["content_hash"]:
                counts["skipped"] += 1
                continue
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM news_items WHERE source = %s AND guid = %s",
                        (source, c["guid"]))
            version = int(cur.fetchone()[0]) + 1
            date_source = c.get("date_source") or _DEFAULT_DATE_SOURCE.get(source) or \
                ("source_field" if c.get("published_at") is not None else "first_seen")
            row = (source, c["guid"], version, c.get("url"), c["headline"], c.get("body") or "",
                   c.get("published_at"), c["fetched_at"], c["content_hash"], c["raw_ref"],
                   c.get("element_id"), c.get("status"), c.get("chance"), c.get("club"), date_source)
            cur.execute(f"INSERT INTO news_items ({', '.join(_COLS)}) VALUES ({', '.join(['%s'] * len(_COLS))}) "
                        f"ON CONFLICT (source, guid, version) DO NOTHING RETURNING id", row)
            if cur.fetchone() is None:
                counts["skipped"] += 1
            elif version == 1:
                counts["new"] += 1
            else:
                counts["new_versions"] += 1
    conn.commit()
    return counts


def ingest_rss(conn, xml_bytes, raw_ref, fetched_at, source="bbc"):
    """Parse one saved RSS response and store its items as versions.
    Returns {fetched, new, new_versions, skipped, errors}."""
    items, errors = parse_rss(xml_bytes)
    cands = [{**it, "fetched_at": fetched_at, "raw_ref": raw_ref,
              "content_hash": content_hash(it["headline"], it["body"])} for it in items]
    counts = upsert_versions(conn, source, cands)
    return {"fetched": len(items), **counts, "errors": len(errors)}


# ---- fetching: raw first, conditional GET, honest UA ----------------------------------------

def _http_get(url, headers):
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except HTTPError as e:
        if e.code == 304:
            return 304, dict(e.headers), b""
        raise


def _hdr(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def raw_ref_for(path):
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def fetch_rss(url, raw_dir, now=None, http=None, state_path=None):
    """One conditional GET. 200 -> the response is gzipped to <raw_dir>/<utc-ts>.xml.gz BEFORE
    anything parses it, and the validators are kept for the next call; 304 -> nothing is
    written, nothing is stored. Returns {status, raw_path, raw_ref, body, headers}."""
    raw_dir = Path(raw_dir)
    now = now or datetime.now(timezone.utc)
    state_path = Path(state_path) if state_path else raw_dir / "state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml;q=0.9"}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    status, resp_headers, body = (http or _http_get)(url, headers)
    if status == 304:
        return {"status": 304, "raw_path": None, "raw_ref": None, "body": None, "headers": resp_headers}
    if status != 200:
        raise RuntimeError(f"HTTP {status} from {url}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{now:%Y%m%dT%H%M%SZ}.xml.gz"
    if not path.exists():                                    # never overwrite a raw file
        _write_atomic(path, gzip.compress(body))
    state = {"url": url, "etag": _hdr(resp_headers, "ETag"), "last_modified": _hdr(resp_headers, "Last-Modified"),
             "last_status": 200, "last_fetched_at": now.isoformat(), "last_raw": path.name}
    _write_atomic(state_path, json.dumps(state, indent=1).encode("utf-8"))
    return {"status": 200, "raw_path": path, "raw_ref": raw_ref_for(path), "body": body, "headers": resp_headers}


# ---- FPL: versions derived from the raw snapshot archive -------------------------------------

def snapshot_time(name):
    return datetime.strptime(str(name).split(".")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _load_gz_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def fpl_candidates(doc, fetched_at, raw_ref):
    """(flagged: {guid: candidate}, reported: {guid: (status, chance, headline)}) for one
    bootstrap-static document. Flagged = news non-empty or status != 'a'."""
    teams = {int(t["id"]): str(t.get("short_name") or t.get("name") or t["id"]) for t in doc.get("teams", [])}
    types = {int(e["id"]): str(e.get("singular_name_short") or e["id"]) for e in doc.get("element_types", [])}
    flagged, reported = {}, {}
    for e in doc.get("elements", []):
        el = int(e["id"])
        guid = f"fpl:{el}"
        status = e.get("status")
        chance = e.get("chance_of_playing_next_round")           # NOT this_round (bug 2)
        chance = int(chance) if chance is not None else None
        news = (e.get("news") or "").strip()
        headline = f"{e.get('web_name', el)} ({teams.get(int(e.get('team', 0)), '?')}, {types.get(int(e.get('element_type', 0)), '?')})"
        reported[guid] = (status, chance, headline)
        if not news and status == "a":
            continue
        flagged[guid] = {"guid": guid, "url": None, "headline": headline, "body": news,
                         "published_at": parse_iso_utc(e.get("news_added")), "fetched_at": fetched_at,
                         "raw_ref": raw_ref, "content_hash": content_hash(status, news, chance),
                         "element_id": el, "status": status, "chance": chance}
    return flagged, reported


def _latest_fpl_state(conn):
    """guid -> active? from the newest stored version (active = not a cleared version)."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ON (guid) guid, body, status FROM news_items "
                    "WHERE source = 'fpl' ORDER BY guid, version DESC")
        return {g: not (b == "" and s == "a") for g, b, s in cur.fetchall()}


def derive_fpl(conn, snapshot_dir, season):
    """Walk every snapshot in the archive directory in time order and store the versions
    it implies. raw_ref is the snapshot's canonical archive path
    data/live/bootstrap_raw/<season>/<file>, whatever directory the copy is read from.
    Returns {snapshots, fetched, new, new_versions, skipped, errors}."""
    d = Path(snapshot_dir)
    files = sorted((snapshot_time(p.name), p.name, p) for p in d.glob("*.json.gz"))
    counts = {"snapshots": 0, "fetched": 0, "new": 0, "new_versions": 0, "skipped": 0, "errors": 0}
    for ts, name, path in files:
        try:
            doc = _load_gz_json(path)
        except (OSError, ValueError) as e:
            counts["errors"] += 1
            continue
        raw_ref = f"data/live/bootstrap_raw/{season}/{name}"
        flagged, reported = fpl_candidates(doc, ts, raw_ref)
        cands = list(flagged.values())
        for guid, active in _latest_fpl_state(conn).items():
            if active and guid not in flagged and guid in reported:
                status, chance, headline = reported[guid]
                cands.append({"guid": guid, "url": None, "headline": headline, "body": "",
                              "published_at": None, "fetched_at": ts, "raw_ref": raw_ref,
                              "content_hash": content_hash(status, "", chance),
                              "element_id": int(guid[4:]), "status": status, "chance": chance})
        c = upsert_versions(conn, "fpl", cands)
        counts["snapshots"] += 1
        counts["fetched"] += len(cands)
        for k in ("new", "new_versions", "skipped"):
            counts[k] += c[k]
    return counts
