"""The page-derived article body (2026-09-28, KNOWN_ISSUES #27): when Tavily's extract of a club page
is only the related-links sidebar, the body comes from the page we already fetched for dates --
JSON-LD articleBody first, then the article document embedded in the page's own script payload,
then the main-content text -- and news_items.body_source records which. A clean extract is left
untouched. Fixtures are synthetic copies of the measured page structures (Tests/fixtures/pages/).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import club_news as cn  # noqa: E402
import config_roles  # noqa: E402
import news_store as ns  # noqa: E402

UTC = timezone.utc
PAGES = REPO / "Tests" / "fixtures" / "pages"
STADION = (PAGES / "stadion_article.html").read_text(encoding="utf-8")
STADION_NOBODY = (PAGES / "stadion_nobody.html").read_text(encoding="utf-8")
JSONLD = (PAGES / "jsonld_article.html").read_text(encoding="utf-8")
PLAIN = (PAGES / "plain_article.html").read_text(encoding="utf-8")

SIDEBAR_EXTRACT = ("Team news for United v Fulham\nTeam news for United v Fulham\nStriker trains at Carrington\n"
                   "Striker trains at Carrington\nHow to watch and follow: Fulham v United\nHow to watch and follow: Fulham v United")
REAL_EXTRACT = ("The head coach reported no fresh injury concerns ahead of Saturday's league meeting at home. "
                "The winger, absent on Wednesday night with adductor issues, trained on Friday morning and is expected to be available for selection.\n"
                "Two long-term absentees remain sidelined and will be assessed again after the international break. "
                "The club confirmed the squad list on Friday afternoon and the manager spoke for twenty minutes about the coming fixtures.")


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'fpl_news_test'")
        if cur.fetchone() is None:
            cur.execute("CREATE DATABASE fpl_news_test")
    admin.close()
    monkeypatch.setenv("DB_NAME", "fpl_news_test")
    c = db_write.connect()
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS availability_comparisons; DROP TABLE IF EXISTS availability_claims; DROP TABLE IF EXISTS availability_extractions; DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; DROP TABLE IF EXISTS news_relevance; "
                    "DROP TABLE IF EXISTS llm_calls; DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


# ---- the link-list check ------------------------------------------------------------------------

@pytest.mark.parametrize("body,expected,why", [
    (SIDEBAR_EXTRACT, True, "short"),                                                     # under 400 chars
    ("\n".join(["Team news for United v Brighton"] * 3 + ["A real sentence about the squad that runs on for a while."] * 8), True, "repeated"),
    ("\n".join(["Ticket news", "Match centre", "Watch on club TV", "Fixtures", "Shop now", "Latest video"] + ["A proper paragraph of prose about the squad, the injuries and the manager's plans for the weekend."] * 4), True, "title-like"),
    (REAL_EXTRACT, False, ""),
])
def test_looks_like_link_list(body, expected, why):
    bad, reason = cn.looks_like_link_list(body)
    assert bad is expected
    if expected:
        assert why in reason


# ---- the page-derived body and its priority ------------------------------------------------------

def test_jsonld_article_body_wins():
    text, source = cn.page_article_body(JSONLD)
    assert source == "page_jsonld" and text.startswith("The defender was injured") and "four weeks" in text


def test_embedded_document_under_bodycopy_is_used_with_links_inline():
    text, source = cn.page_article_body(STADION)
    assert source == "page_embedded"
    assert text.startswith("The Netherlands international is yet to feature")
    assert "alongside Harry Example, in a boost" in text, "hyperlink text stays inline in its sentence"
    assert "Club TV offers" not in text and "watchlists" not in text, "the accordion boilerplate is not the article"
    assert "Related Content" not in text and "Striker trains at Carrington" not in text


def test_main_text_is_the_last_resort():
    text, source = cn.page_article_body(PLAIN)
    assert source == "page_html" and text.startswith("Injury update from the head coach")
    assert "adductor issues" in text and "Home" not in text.split("\n")[0]


def test_no_source_when_the_page_holds_only_the_sidebar():
    text, source = cn.page_article_body(STADION_NOBODY)
    assert (text, source) == ("", None)


# ---- through the pipeline -------------------------------------------------------------------------

def _res(url, title, content):
    return {"url": url, "title": title, "content": content, "score": 0.5}


class FakeTavily:
    def __init__(self, searches, extracts):
        self.by_domain, self.pool, self.requests, self.extract_calls = searches, extracts, [], []

    def search(self, query, domain, start_date=None, end_date=None):
        domains = [domain] if isinstance(domain, str) else list(domain)
        self.requests.append(cn.search_request(query, domains, start_date, end_date))
        return {"results": [dict(r) for r in self.by_domain.get(domains[0], [])]}

    def extract(self, urls):
        self.extract_calls.append(list(urls))
        return {"results": [self.pool[u] for u in urls if u in self.pool], "failed_results": [u for u in urls if u not in self.pool]}


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        return (404, url, "") if v is None else (200, url, v)


GW5 = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)
NOW = datetime(2026, 9, 17, 15, 7, tzinfo=UTC)
WINDOW = (GW5 - timedelta(days=3), GW5)
MUN_SIDEBAR = "https://www.manutd.com/en/news/team-news-for-united-v-fulham-injury-update"
MUN_NOBODY = "https://www.manutd.com/en/news/striker-closing-on-return-to-fitness"
NEW_CLEAN = f"https://www.{config_roles.CLUB_DOMAINS['Newcastle']}/news/latest-news/boss-gives-team-news-update-injury"
CLUBS = {"Man Utd": config_roles.CLUB_DOMAINS["Man Utd"], "Newcastle": config_roles.CLUB_DOMAINS["Newcastle"]}
OPPONENTS = {"Man Utd": ["Fulham"], "Newcastle": ["Hull City"]}


def _rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT url, version, length(body), body_source, left(body, 40) FROM news_items WHERE source = 'club' ORDER BY url, version")
        return cur.fetchall()


def test_run_uses_the_page_body_only_when_the_extract_is_a_link_list(conn, tmp_path):
    searches = {config_roles.CLUB_DOMAINS["Man Utd"]: [_res(MUN_SIDEBAR, "Team news for United v Fulham | Manchester United", "Injury update ahead of Fulham."),
                               _res(MUN_NOBODY, "Striker closing on return to fitness | Manchester United", "Injury update ahead of Fulham: back in training.")],
                config_roles.CLUB_DOMAINS["Newcastle"]: [_res(NEW_CLEAN, "Boss gives team news update | Newcastle United", "Injury update on the defender.")]}
    extracts = {MUN_SIDEBAR: {"url": MUN_SIDEBAR, "raw_content": SIDEBAR_EXTRACT},
                MUN_NOBODY: {"url": MUN_NOBODY, "raw_content": SIDEBAR_EXTRACT},
                NEW_CLEAN: {"url": NEW_CLEAN, "raw_content": REAL_EXTRACT}}
    http = FakeHttp({MUN_SIDEBAR: STADION, MUN_NOBODY: STADION_NOBODY, NEW_CLEAN: JSONLD})
    lines = []
    cn.run(conn, CLUBS, FakeTavily(searches, extracts), now=NOW, raw_dir=tmp_path / "raw", log=lines.append, http=http,
           window=WINDOW, opponents=OPPONENTS, aliases=cn.team_aliases([{"id": 14, "name": "Man Utd", "short_name": "MUN"},
                                                                           {"id": 15, "name": "Newcastle", "short_name": "NEW"}]))
    rows = {r[0]: r for r in _rows(conn)}
    assert rows[MUN_SIDEBAR][3] == "page_embedded" and rows[MUN_SIDEBAR][4].startswith("The Netherlands international")
    assert rows[MUN_NOBODY][3] == "tavily_extract" and rows[MUN_NOBODY][2] == len(SIDEBAR_EXTRACT), "nothing better on the page: the extract stays, flagged in the log"
    assert rows[NEW_CLEAN][3] == "tavily_extract" and rows[NEW_CLEAN][4].startswith("The head coach reported"), "a clean extract is never replaced, even though the page has JSON-LD"
    assert any("page_embedded" in ln and "manutd.com" in ln for ln in lines) and any("link list" in ln and "striker-closing" in ln for ln in lines)


def test_body_source_column_and_backfill(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, headline, body, fetched_at, content_hash, raw_ref, club, date_source, body_source) "
                    "VALUES ('club', 'g1', 1, 'h', 'old row', now(), 'x', 'r', 'Arsenal', 'backlog', NULL), "
                    "('bbc', 'g2', 1, 'h', 'feed row', now(), 'y', 'r', NULL, 'feed', NULL)")
    conn.commit()
    ns.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT source, body_source FROM news_items ORDER BY source")
        assert cur.fetchall() == [("bbc", None), ("club", "tavily_extract")], "existing club rows are extracts; feeds are not Tavily"


# ---- parse corrections (2026-09-28): the original fetched_at, and the view skips the superseded defect ----

def _insert_version(conn, guid, version, body, body_source, fetched_at, club="Man Utd"):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, url, headline, body, fetched_at, content_hash, raw_ref, club, date_source, body_source) "
                    "VALUES ('club', %s, %s, 'https://www.manutd.com/en/news/x', 'Headline', %s, %s, %s, 'r', %s, 'backlog', %s) RETURNING id",
                    (guid, version, body, fetched_at, f"h{guid}{version}", club, body_source))
        iid = cur.fetchone()[0]
        cur.execute("INSERT INTO news_relevance (news_item_id, prompt_version, model, stage, relevant, current, players, reason) "
                    "VALUES (%s, %s, %s, 'llm', TRUE, TRUE, '{}', 'keep')", (iid, config_roles.PROMPT_VERSION, config_roles.RELEVANCE_MODEL))
    conn.commit()
    return iid


def test_rederive_keeps_the_original_fetched_at(conn, tmp_path):
    import gzip, hashlib, json
    import rederive_club_bodies as rd
    fetched = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)
    guid = "manutd.com/en/news/team-news-for-united-v-fulham-injury-update"
    old_id = _insert_version(conn, guid, 1, SIDEBAR_EXTRACT, "tavily_extract", fetched)
    pages = tmp_path / "pages"; pages.mkdir()
    (pages / (hashlib.sha1(guid.encode()).hexdigest() + ".json.gz")).write_bytes(gzip.compress(json.dumps({"url": "u", "guid": guid, "html": STADION}).encode()))
    r = rd.rederive(conn, club="Man Utd", page_dirs=[pages], log=lambda m: None)
    assert [x[0] for x in r["rederived"]] == [old_id]
    with conn.cursor() as cur:
        cur.execute("SELECT version, fetched_at, body_source FROM news_items WHERE guid = %s ORDER BY version", (guid,))
        rows = cur.fetchall()
    assert [(v, s) for v, _, s in rows] == [(1, "tavily_extract"), (2, "page_embedded")]
    assert rows[1][1] == rows[0][1] == fetched, "a parse correction describes what we knew when the page was fetched"


def test_news_to_embed_skips_a_version_superseded_by_a_parse_correction(conn):
    t = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)
    defect = _insert_version(conn, "g-defect", 1, SIDEBAR_EXTRACT, "tavily_extract", t)                       # like 507
    fixed = _insert_version(conn, "g-defect", 2, REAL_EXTRACT, "page_embedded", t)                             # like 513
    change1 = _insert_version(conn, "g-change", 1, REAL_EXTRACT, "tavily_extract", t)                          # a normal edit
    change2 = _insert_version(conn, "g-change", 2, REAL_EXTRACT + "\nUpdated line.", "tavily_extract", t)
    solo = _insert_version(conn, "g-solo", 1, REAL_EXTRACT, "page_jsonld", t)                                  # a correction with no predecessor
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM news_to_embed ORDER BY id")
        ids = [r[0] for r in cur.fetchall()]
    assert defect not in ids and fixed in ids, "the superseded defect version is out, its correction is in"
    assert change1 in ids and change2 in ids, "a normal content-change version is not a parse correction"
    assert solo in ids
