"""News ingestion v1 (2026-09-25): BBC Premier League RSS + FPL availability news into
Postgres, one row per VERSION of an item, and the exact text the embedding layer will see.

Rules pinned here (the task's, verbatim where it matters):
  * idempotent: the same raw input twice changes nothing;
  * new guid -> v1; known guid + new hash -> v(n+1); same hash -> skip;
  * RSS guid falls back to the canonical link; all times UTC, RFC 822 offsets and the
    named zones GMT/BST parsed;
  * FPL: guid 'fpl:<element_id>', hash over (status, news, chance), headline
    '<web_name> (<team short name>, <position>)', published_at = news_added, fetched_at =
    the snapshot time; a CLEARED flag is a new version with an empty body, the status as
    reported, published_at NULL (FPL does not bump news_added when it clears a flag) and
    fetched_at = the FIRST snapshot where the news was gone;
  * raw first: the RSS response is saved gzipped before parsing and raw_ref points at it;
    a 304 stores nothing and writes no raw file;
  * the view news_embed_text builds the chunk string, tested on exact strings.

No network: the BBC fixture is one real response (2026-09-25 01:45Z, 50 items); the FPL
snapshots are synthetic documents in the raw archive's own file naming. The tests need a
local Postgres (db_write.connect defaults: localhost:5432, user postgres, empty password)
and use their own database `fpl_news_test`; without one they SKIP, never pass vacuously.
"""
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import news_store as ns  # noqa: E402

FIXTURE = REPO / "Tests" / "fixtures" / "bbc_premier_league_rss_2026-09-25.xml"
UTC = timezone.utc
TEST_DB = "fpl_news_test"
FETCHED = datetime(2026, 9, 25, 1, 45, 8, tzinfo=UTC)


@pytest.fixture
def conn(monkeypatch):
    """A fresh news schema in the test database. Skips (loudly) without a local Postgres."""
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres for the news tests: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    with c.cursor() as cur:
        cur.execute("DROP VIEW IF EXISTS news_embed_text; DROP TABLE IF EXISTS news_items")
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


def _rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, source, guid, version, url, headline, body, published_at, fetched_at, "
                    "content_hash, raw_ref, element_id, status, chance, inserted_at "
                    "FROM news_items ORDER BY id")
        return cur.fetchall()


def _view(conn, where="TRUE", params=()):
    with conn.cursor() as cur:
        cur.execute(f"SELECT id, source, guid, version, fetched_at, embed_text, char_count "
                    f"FROM news_embed_text WHERE {where} ORDER BY source, guid, version", params)
        return cur.fetchall()


# ---- parse ------------------------------------------------------------------------------

def test_parse_fixture_rows():
    items, errors = ns.parse_rss(FIXTURE.read_bytes())
    assert len(items) == 50 and errors == []
    first = items[0]
    assert first["guid"] == "https://www.bbc.co.uk/sport/football/articles/c639merx84jno#0"
    assert first["url"] == "https://www.bbc.co.uk/sport/football/articles/c639merx84jno?at_medium=RSS&at_campaign=rss"
    assert first["headline"] == "Uefa fears impact of Premier League spending on transfer market"
    assert first["body"] == ('Uefa believes "a clear two-speed system" is emerging in the transfer market due to '
                             'huge spending by Premier League clubs this summer.')
    assert first["published_at"] == datetime(2026, 9, 24, 22, 9, 28, tzinfo=UTC)
    stamps = [i["published_at"] for i in items]
    assert all(s.tzinfo is not None and s.utcoffset().total_seconds() == 0 for s in stamps)
    assert min(stamps) == datetime(2026, 6, 8, 10, 14, 49, tzinfo=UTC)
    assert max(stamps) == datetime(2026, 9, 24, 22, 22, 43, tzinfo=UTC)
    assert len({i["guid"] for i in items}) == 50


def test_rss_guid_falls_back_to_the_canonical_link():
    xml = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
           b'<item><title>A</title><link>https://example.org/a?utm=1</link><description>d</description>'
           b'<pubDate>Thu, 24 Sep 2026 22:09:28 GMT</pubDate></item></channel></rss>')
    items, errors = ns.parse_rss(xml)
    assert errors == [] and items[0]["guid"] == "https://example.org/a?utm=1" and items[0]["url"] == items[0]["guid"]


@pytest.mark.parametrize("text,expected", [
    ("Thu, 24 Sep 2026 22:09:28 GMT", datetime(2026, 9, 24, 22, 9, 28, tzinfo=UTC)),
    ("Wed, 23 Sep 2026 23:20:00 BST", datetime(2026, 9, 23, 22, 20, 0, tzinfo=UTC)),
    ("Wed, 23 Sep 2026 23:20:00 +0100", datetime(2026, 9, 23, 22, 20, 0, tzinfo=UTC)),
    ("Wed, 23 Sep 2026 18:20:00 -0400", datetime(2026, 9, 23, 22, 20, 0, tzinfo=UTC)),
    ("Wed, 23 Sep 2026 22:20:00 UTC", datetime(2026, 9, 23, 22, 20, 0, tzinfo=UTC)),
])
def test_timezones_parse_to_utc(text, expected):
    got = ns.parse_rfc822(text)
    assert got == expected and got.tzinfo is not None and got.utcoffset().total_seconds() == 0


def test_unknown_zone_is_an_error_not_a_guess():
    assert ns.parse_rfc822("Wed, 23 Sep 2026 22:20:00 XYZ") is None
    xml = (b'<rss version="2.0"><channel><item><guid>g1</guid><title>A</title><description>d</description>'
           b'<pubDate>Wed, 23 Sep 2026 22:20:00 XYZ</pubDate></item></channel></rss>')
    items, errors = ns.parse_rss(xml)
    assert items[0]["published_at"] is None and len(errors) == 1 and "g1" in errors[0]


# ---- store: BBC -------------------------------------------------------------------------

def test_ingest_fixture_expected_rows(conn):
    counts = ns.ingest_rss(conn, FIXTURE.read_bytes(), raw_ref="data/news/raw/bbc/20260925T014508Z.xml.gz",
                           fetched_at=FETCHED, source="bbc")
    assert counts == {"fetched": 50, "new": 50, "new_versions": 0, "skipped": 0, "errors": 0}
    rows = _rows(conn)
    assert len(rows) == 50
    assert {r[1] for r in rows} == {"bbc"} and {r[3] for r in rows} == {1}
    items, _ = ns.parse_rss(FIXTURE.read_bytes())
    assert [r[2] for r in rows] == [i["guid"] for i in items]
    assert [r[7] for r in rows] == [i["published_at"] for i in items]
    assert {r[8] for r in rows} == {FETCHED} and {r[10] for r in rows} == {"data/news/raw/bbc/20260925T014508Z.xml.gz"}
    assert all(r[11] is None and r[12] is None and r[13] is None for r in rows)


def test_ingest_twice_changes_nothing(conn):
    ns.ingest_rss(conn, FIXTURE.read_bytes(), raw_ref="r1", fetched_at=FETCHED)
    before = _rows(conn)
    counts = ns.ingest_rss(conn, FIXTURE.read_bytes(), raw_ref="r2",
                           fetched_at=datetime(2026, 9, 25, 5, 45, tzinfo=UTC))
    assert counts == {"fetched": 50, "new": 0, "new_versions": 0, "skipped": 50, "errors": 0}
    assert _rows(conn) == before, "a second ingest of the same input changed the table"


def test_edit_makes_v2_and_keeps_v1(conn):
    raw = FIXTURE.read_bytes()
    ns.ingest_rss(conn, raw, raw_ref="r1", fetched_at=FETCHED)
    old = 'Uefa believes "a clear two-speed system" is emerging'
    new = 'Uefa now says "a clear two-speed system" has emerged'
    assert raw.count(old.encode("utf-8")) == 1
    edited = raw.replace(old.encode("utf-8"), new.encode("utf-8"))
    later = datetime(2026, 9, 25, 5, 45, tzinfo=UTC)
    counts = ns.ingest_rss(conn, edited, raw_ref="r2", fetched_at=later)
    assert counts == {"fetched": 50, "new": 0, "new_versions": 1, "skipped": 49, "errors": 0}
    guid = "https://www.bbc.co.uk/sport/football/articles/c639merx84jno#0"
    with conn.cursor() as cur:
        cur.execute("SELECT version, body, fetched_at, raw_ref FROM news_items WHERE guid = %s ORDER BY version", (guid,))
        v = cur.fetchall()
    assert [x[0] for x in v] == [1, 2]
    assert v[0][1].startswith(old) and v[0][2] == FETCHED and v[0][3] == "r1"
    assert v[1][1].startswith(new) and v[1][2] == later and v[1][3] == "r2"
    assert len(_rows(conn)) == 51


# ---- fetch: raw first, conditional GET, honest UA ------------------------------------------

class _Http:
    """A stand-in for the network: records the request headers, returns what it is told."""
    def __init__(self, status, headers=None, body=b""):
        self.status, self.headers, self.body, self.requests = status, headers or {}, body, []

    def __call__(self, url, headers):
        self.requests.append((url, dict(headers)))
        return self.status, dict(self.headers), self.body


def test_304_stores_nothing_and_writes_no_raw_file(conn, tmp_path):
    raw_dir = tmp_path / "raw" / "bbc"
    http = _Http(304)
    r = ns.fetch_rss("https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml", raw_dir,
                     now=FETCHED, http=http)
    assert r["status"] == 304 and r["raw_path"] is None and r["body"] is None
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == []
    assert _rows(conn) == []


def test_200_saves_raw_before_parsing_and_sends_conditional_headers(tmp_path):
    raw_dir = tmp_path / "raw" / "bbc"
    body = FIXTURE.read_bytes()
    http = _Http(200, {"ETag": 'W/"abc"', "Last-Modified": "Thu, 25 Sep 2026 01:45:08 GMT"}, body)
    r = ns.fetch_rss("https://feeds.bbci.co.uk/x.xml", raw_dir, now=FETCHED, http=http)
    assert r["status"] == 200
    assert r["raw_path"].name == "20260925T014508Z.xml.gz" and gzip.decompress(r["raw_path"].read_bytes()) == body
    ua = http.requests[0][1]["User-Agent"]
    assert "fpl-copilot" in ua and "https://github.com/veer64/fpl-copilot" in ua and "Mozilla" not in ua
    assert "If-None-Match" not in http.requests[0][1]
    # the next fetch carries the validators the first response gave
    http2 = _Http(304)
    ns.fetch_rss("https://feeds.bbci.co.uk/x.xml", raw_dir, now=FETCHED, http=http2)
    h = http2.requests[0][1]
    assert h["If-None-Match"] == 'W/"abc"' and h["If-Modified-Since"] == "Thu, 25 Sep 2026 01:45:08 GMT"


# ---- store: FPL from raw snapshots ----------------------------------------------------------

def _doc(elements):
    return {"teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 2, "name": "Aston Villa", "short_name": "AVL"}],
            "element_types": [{"id": 1, "singular_name_short": "GKP"}, {"id": 2, "singular_name_short": "DEF"},
                              {"id": 3, "singular_name_short": "MID"}, {"id": 4, "singular_name_short": "FWD"}],
            "events": [{"id": 6, "deadline_time": "2026-10-10T10:00:00Z", "finished": False}],
            "elements": elements}


def _el(i, web, team, et, status, chance, news, added):
    return {"id": i, "web_name": web, "team": team, "element_type": et, "status": status,
            "chance_of_playing_this_round": chance, "chance_of_playing_next_round": chance,
            "news": news, "news_added": added}


T1, T2, T3 = (datetime(2026, 9, 1, 12, 0, tzinfo=UTC), datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
              datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
ADDED = "2026-07-23T12:01:23.289376Z"


def _archive(tmp_path):
    d = tmp_path / "bootstrap_raw" / "2026-27"
    d.mkdir(parents=True)
    docs = {
        # t1: Saliba injured; Watkins doubtful; Raya fit
        f"{T1:%Y%m%dT%H%M%SZ}.json.gz": _doc([
            _el(6, "Saliba", 1, 2, "i", 0, "Back injury - Unknown return date", ADDED),
            _el(400, "Watkins", 2, 4, "d", 75, "Knock - 75% chance of playing", "2026-08-30T09:00:00Z"),
            _el(1, "Raya", 1, 1, "a", None, "", None)]),
        # t2 (a build fetch): Saliba's flag changes; Watkins CLEARED (news gone, status a)
        f"{T2:%Y%m%dT%H%M%SZ}.build_fetch.json.gz": _doc([
            _el(6, "Saliba", 1, 2, "d", 75, "Back injury - 75% chance of playing", ADDED),
            _el(400, "Watkins", 2, 4, "a", None, "", "2026-08-30T09:00:00Z"),
            _el(1, "Raya", 1, 1, "a", None, "", None)]),
        # t3: Saliba CLEARED; Watkins still clear (nothing new)
        f"{T3:%Y%m%dT%H%M%SZ}.json.gz": _doc([
            _el(6, "Saliba", 1, 2, "a", None, "", ADDED),
            _el(400, "Watkins", 2, 4, "a", None, "", "2026-08-30T09:00:00Z"),
            _el(1, "Raya", 1, 1, "a", None, "", None)]),
    }
    for name, doc in docs.items():
        (d / name).write_bytes(gzip.compress(json.dumps(doc).encode("utf-8")))
    return d


def test_fpl_set_changed_cleared_versions(conn, tmp_path):
    d = _archive(tmp_path)
    counts = ns.derive_fpl(conn, d, season="2026-27")
    assert counts["snapshots"] == 3 and counts["errors"] == 0
    assert counts["new"] == 2 and counts["new_versions"] == 3           # Saliba v1 v2 v3, Watkins v1 v2
    with conn.cursor() as cur:
        cur.execute("SELECT guid, version, headline, body, published_at, fetched_at, status, chance, raw_ref, element_id "
                    "FROM news_items WHERE source = 'fpl' ORDER BY guid, version")
        rows = cur.fetchall()
    assert [(r[0], r[1]) for r in rows] == [("fpl:400", 1), ("fpl:400", 2), ("fpl:6", 1), ("fpl:6", 2), ("fpl:6", 3)]
    s1, s2, s3 = rows[2], rows[3], rows[4]
    assert s1[2] == "Saliba (ARS, DEF)" and s1[3] == "Back injury - Unknown return date"
    assert s1[4] == datetime(2026, 7, 23, 12, 1, 23, 289376, tzinfo=UTC) and s1[5] == T1
    assert s1[6] == "i" and s1[7] == 0 and s1[9] == 6
    assert s1[8] == f"data/live/bootstrap_raw/2026-27/{T1:%Y%m%dT%H%M%SZ}.json.gz"
    assert s2[3] == "Back injury - 75% chance of playing" and s2[6] == "d" and s2[7] == 75 and s2[5] == T2
    assert s2[8].endswith(".build_fetch.json.gz")
    assert s3[3] == "" and s3[6] == "a" and s3[7] is None and s3[4] is None and s3[5] == T3, "cleared = empty body, status as reported, no claim, first snapshot where the news was gone"
    w1, w2 = rows[0], rows[1]
    assert w1[2] == "Watkins (AVL, FWD)" and w1[5] == T1 and w2[3] == "" and w2[5] == T2
    assert "fpl:1" not in {r[0] for r in rows}, "a player with no news has no row"


def test_fpl_rederive_changes_nothing(conn, tmp_path):
    d = _archive(tmp_path)
    ns.derive_fpl(conn, d, season="2026-27")
    before = _rows(conn)
    counts = ns.derive_fpl(conn, d, season="2026-27")
    # the 3 flagged candidates are re-proposed and skipped on their hashes; the 2 cleared
    # versions are not re-proposed at all, because the stored state is already "cleared"
    assert counts["new"] == 0 and counts["new_versions"] == 0 and counts["skipped"] == 3
    assert _rows(conn) == before


# ---- the exact text to be embedded ---------------------------------------------------------

def test_embed_text_exact_strings(conn, tmp_path):
    ns.ingest_rss(conn, FIXTURE.read_bytes(), raw_ref="r1", fetched_at=FETCHED)
    ns.derive_fpl(conn, _archive(tmp_path), season="2026-27")
    bbc = _view(conn, "source = 'bbc' AND guid = %s", ("https://www.bbc.co.uk/sport/football/articles/c639merx84jno#0",))
    assert len(bbc) == 1
    expected_bbc = ("[BBC Sport | 2026-09-24 22:09Z] Uefa fears impact of Premier League spending on transfer market\n"
                    'Uefa believes "a clear two-speed system" is emerging in the transfer market due to huge spending '
                    "by Premier League clubs this summer.")
    assert bbc[0][5] == expected_bbc and bbc[0][6] == len(expected_bbc)
    fpl = _view(conn, "source = 'fpl' AND guid = 'fpl:6'")
    assert [r[3] for r in fpl] == [1, 2, 3]
    assert fpl[0][5] == ("[FPL official | 2026-07-23 12:01Z] Saliba (ARS, DEF)\n"
                         "Status: injured. 0% chance of playing. Back injury - Unknown return date")
    assert fpl[1][5] == ("[FPL official | 2026-07-23 12:01Z] Saliba (ARS, DEF)\n"
                         "Status: doubtful. 75% chance of playing. Back injury - 75% chance of playing")
    assert fpl[2][5] == ("[FPL official | 2026-09-03 12:00Z] Saliba (ARS, DEF)\n"
                         "Status: available. No injury news (flag cleared).")
    assert all(r[6] == len(r[5]) for r in fpl)
    assert fpl[2][4] == T3


def test_embed_text_omits_the_chance_sentence_when_null(conn, tmp_path):
    d = tmp_path / "bootstrap_raw" / "2026-27"
    d.mkdir(parents=True)
    (d / f"{T1:%Y%m%dT%H%M%SZ}.json.gz").write_bytes(gzip.compress(json.dumps(_doc([
        _el(9, "Jesus", 1, 4, "s", None, "Suspended until 17 Oct", "2026-09-01T10:00:00Z")])).encode("utf-8")))
    ns.derive_fpl(conn, d, season="2026-27")
    v = _view(conn, "guid = 'fpl:9'")
    assert v[0][5] == "[FPL official | 2026-09-01 10:00Z] Jesus (ARS, FWD)\nStatus: suspended. Suspended until 17 Oct"


# ---- the schema itself ------------------------------------------------------------------

def test_schema_constraints(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'news_items'")
        defs = " ".join(r[0] for r in cur.fetchall())
    # (source, guid, version) is THE unique key (2026-09-25, bug 1); content_hash is not unique:
    # a re-flag after a clear repeats an earlier version's hash and must still be stored
    assert "UNIQUE INDEX ux_news_items_version ON public.news_items USING btree (source, guid, version)" in defs
    unique_defs = [d for d in defs.split("CREATE ") if d.startswith("UNIQUE")]
    assert not any("content_hash" in d for d in unique_defs), unique_defs
    assert "(fetched_at)" in defs
    with conn.cursor() as cur:
        cur.execute("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'news_items'")
        cols = dict(cur.fetchall())
    assert set(cols) == {"id", "source", "guid", "version", "url", "headline", "body", "published_at", "fetched_at",
                         "content_hash", "raw_ref", "element_id", "status", "chance", "inserted_at",
                         "club", "date_source"}                       # club/date_source added 2026-09-25 (club news)
    assert cols["published_at"] == "YES" and cols["fetched_at"] == "NO"


# ---- BUG 1 (2026-09-25): a re-flag after a clear must be a NEW version -------------------------
# The rule is "differs from the LATEST stored version", never "differs from every version".
# The unique key is (source, guid, version); (source, guid, content_hash) is NOT unique.

def test_reflag_after_clear_with_identical_text_is_v3_and_active(conn, tmp_path):
    d = tmp_path / "bootstrap_raw" / "2026-27"
    d.mkdir(parents=True)
    docs = {
        f"{T1:%Y%m%dT%H%M%SZ}.json.gz": _doc([_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)]),
        f"{T2:%Y%m%dT%H%M%SZ}.json.gz": _doc([_el(6, "Saliba", 1, 2, "a", None, "", ADDED)]),
        f"{T3:%Y%m%dT%H%M%SZ}.json.gz": _doc([_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)]),
    }
    for name, doc in docs.items():
        (d / name).write_bytes(gzip.compress(json.dumps(doc).encode("utf-8")))
    counts = ns.derive_fpl(conn, d, season="2026-27")
    assert counts["new"] == 1 and counts["new_versions"] == 2 and counts["skipped"] == 0, counts
    with conn.cursor() as cur:
        cur.execute("SELECT version, body, status, fetched_at, content_hash FROM news_items WHERE guid = 'fpl:6' ORDER BY version")
        v = cur.fetchall()
    assert [x[0] for x in v] == [1, 2, 3], "d -> cleared -> d (same text) must be three versions"
    assert v[0][1] == v[2][1] == "Knock - 75% chance of playing" and v[1][1] == ""
    assert v[2][2] == "d" and v[2][3] == T3, "the latest version must be the ACTIVE re-flag, not the clear"
    assert v[0][4] == v[2][4], "same content, same hash: the hash is not what makes a version, the change is"
    assert ns._latest_fpl_state(conn) == {"fpl:6": True}


def test_rss_edit_then_revert_is_v3(conn):
    raw = FIXTURE.read_bytes()
    old = 'Uefa believes "a clear two-speed system" is emerging'
    new = 'Uefa now says "a clear two-speed system" has emerged'
    ns.ingest_rss(conn, raw, raw_ref="r1", fetched_at=FETCHED)
    ns.ingest_rss(conn, raw.replace(old.encode(), new.encode()), raw_ref="r2", fetched_at=datetime(2026, 9, 25, 5, 45, tzinfo=UTC))
    counts = ns.ingest_rss(conn, raw, raw_ref="r3", fetched_at=datetime(2026, 9, 25, 9, 45, tzinfo=UTC))
    assert counts == {"fetched": 50, "new": 0, "new_versions": 1, "skipped": 49, "errors": 0}, counts
    with conn.cursor() as cur:
        cur.execute("SELECT version, raw_ref FROM news_items WHERE guid = %s ORDER BY version",
                    ("https://www.bbc.co.uk/sport/football/articles/c639merx84jno#0",))
        assert cur.fetchall() == [(1, "r1"), (2, "r2"), (3, "r3")]


def test_same_hash_as_latest_is_still_skipped(conn):
    """The other half of the rule: identical to the LATEST version -> skipped, so ingesting
    the same feed twice is still a no-op (test_ingest_twice_changes_nothing) and a
    snapshot that repeats the previous one adds nothing."""
    ns.ingest_rss(conn, FIXTURE.read_bytes(), raw_ref="r1", fetched_at=FETCHED)
    before = _rows(conn)
    ns.ingest_rss(conn, FIXTURE.read_bytes(), raw_ref="r2", fetched_at=datetime(2026, 9, 25, 9, 45, tzinfo=UTC))
    assert _rows(conn) == before


# ---- BUG 2 (2026-09-25): chance reads chance_of_playing_NEXT_round -------------------------
# Measured on the server archive (53 snapshots): the news text's "<N>% chance" equals
# next_round in 819 of 819 rows and this_round ALONE in 0. this_round is the round already
# under way; the deadline gameweek a manager is picking for is next_round.

def test_chance_is_next_round_and_part_of_the_hash(conn, tmp_path):
    d = tmp_path / "bootstrap_raw" / "2026-27"
    d.mkdir(parents=True)
    e1 = _el(400, "Doku", 2, 3, "d", 0, "Calf injury - 75% chance of playing", "2026-08-18T17:00:08Z")
    e1["chance_of_playing_next_round"] = 75                       # this_round 0 (stale), next_round 75
    e2 = dict(e1, chance_of_playing_next_round=50)                # only next_round moves
    e3 = dict(e2, chance_of_playing_this_round=25)                # only this_round moves
    for name, el in ((f"{T1:%Y%m%dT%H%M%SZ}.json.gz", e1), (f"{T2:%Y%m%dT%H%M%SZ}.json.gz", e2),
                     (f"{T3:%Y%m%dT%H%M%SZ}.json.gz", e3)):
        (d / name).write_bytes(gzip.compress(json.dumps(_doc([el])).encode("utf-8")))
    counts = ns.derive_fpl(conn, d, season="2026-27")
    with conn.cursor() as cur:
        cur.execute("SELECT version, chance FROM news_items WHERE guid = 'fpl:400' ORDER BY version")
        v = cur.fetchall()
    assert v == [(1, 75), (2, 50)], f"chance must be next_round, and a this_round-only move is not a version: {v}"
    assert counts["new"] == 1 and counts["new_versions"] == 1 and counts["skipped"] == 1
    got = _view(conn, "guid = 'fpl:400'")
    assert got[0][5].endswith("Status: doubtful. 75% chance of playing. Calf injury - 75% chance of playing")
    assert got[1][5].endswith("Status: doubtful. 50% chance of playing. Calf injury - 75% chance of playing")
