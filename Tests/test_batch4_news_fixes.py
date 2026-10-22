"""Fix batch #4 (2026-10-22), news-pipeline fixes, failing tests first:

  N1  a Tavily extract that is a link list is never stored as the article body when the page gives nothing better
      (manutd.com answers the server's page fetch with 403, 37 of 37): the body is dropped, the headline kept; the
      page the laptop fetched on 21 Oct proves the page-derived body wins when a page IS available.
  N2  a language copy of an article (/pt/, /es/, /fr/ ...) is one article: its canonical guid is the English URL's and
      the search result drops it; a BBC item re-delivered under another guid fragment ('#0' / '#2') is the same row
      (the guid is the canonical link). The search-side collapse of identical-text chunks was built, measured against
      the locked RAG labels and dropped (it lowered recall@5 on every variant); it is not here.
  N3  the old-article guard accepts the date range the search requested (GW7 day 1: the search asked 13 -> 14 Oct,
      the guard kept 14 -> 17 Oct).
  N4  no undated retry: a dated search that returns nothing makes no second request.
  N5  every Tavily request's HTTP status goes into the ledger (tavily_calls.http_status; SCHEMA CHANGED).
"""
import gzip
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import chunking                                            # noqa: E402
import club_news as cn                                     # noqa: E402
import config_roles                                        # noqa: E402
import db_write                                            # noqa: E402
import news_store as ns                                    # noqa: E402

UTC = timezone.utc
PAGES = REPO / "Tests" / "fixtures" / "pages"
MANUTD = gzip.open(PAGES / "manutd_carrick_bournemouth_20261021.html.gz", "rb").read().decode("utf-8")
STADION_NOBODY = (PAGES / "stadion_nobody.html").read_text(encoding="utf-8")
JSONLD = (PAGES / "jsonld_article.html").read_text(encoding="utf-8")
SIDEBAR_EXTRACT = ("Team news for United v Fulham\nTeam news for United v Fulham\nStriker trains at Carrington\n"
                   "Striker trains at Carrington\nHow to watch and follow: Fulham v United\nHow to watch and follow: Fulham v United")
REAL_EXTRACT = ("The head coach reported no fresh injury concerns ahead of Saturday's league meeting at home. "
                "The winger, absent on Wednesday night with adductor issues, trained on Friday morning and is expected to be available for selection.\n"
                "Two long-term absentees remain sidelined and will be assessed again after the international break. "
                "The club confirmed the squad list on Friday afternoon and the manager spoke for twenty minutes about the coming fixtures.")
AS_OF = "2026-10-17 09:51:19.918536+00:00"


@pytest.fixture
def conn(monkeypatch):
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
        cur.execute("DROP TABLE IF EXISTS availability_comparisons; DROP TABLE IF EXISTS availability_claims; DROP TABLE IF EXISTS availability_extractions; "
                    "DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; "
                    "DROP TABLE IF EXISTS news_relevance; DROP TABLE IF EXISTS llm_calls; DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


# ================================================================ N1: a link list is never the stored body
def test_n1_the_fetched_manutd_page_gives_the_article_body():
    text, source = cn.page_article_body(MANUTD)
    assert source == "page_embedded" and len(text) > 1000
    assert "Mazraoui" in text and "You might also like" not in text


def test_n1_an_empty_body_chunks_to_the_headline_alone():
    chunks = chunking.chunk_embed_text("[Man Utd official site | 2026-10-08] De Ligt shares positive recovery update\n")
    assert [c.text for c in chunks] == ["[Man Utd official site | 2026-10-08] De Ligt shares positive recovery update"]


class _Tavily:
    def __init__(self, searches, extracts):
        self.by_domain, self.pool, self.requests, self.extract_calls = searches, extracts, [], []

    def search(self, query, domain, start_date=None, end_date=None):
        domains = [domain] if isinstance(domain, str) else list(domain)
        self.requests.append(cn.search_request(query, domains, start_date, end_date))
        return {"results": [dict(r) for r in self.by_domain.get(domains[0], [])]}

    def extract(self, urls):
        self.extract_calls.append(list(urls))
        return {"results": [self.pool[u] for u in urls if u in self.pool], "failed_results": [u for u in urls if u not in self.pool]}


class _Http:
    def __init__(self, pages, status_when_missing=403):
        self.pages, self.calls, self.missing = pages, [], status_when_missing

    def get(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        return (self.missing, url, "") if v is None else (200, url, v)


def _res(url, title, content):
    return {"url": url, "title": title, "content": content, "score": 0.5}


GW5 = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)
NOW = datetime(2026, 9, 17, 15, 7, tzinfo=UTC)
WINDOW = (GW5 - timedelta(days=3), GW5)
MUN = config_roles.CLUB_DOMAINS["Man Utd"]
MUN_403 = f"https://www.{MUN}/en/news/team-news-for-united-v-fulham-injury-update"
MUN_PAGE = f"https://www.{MUN}/en/news/michael-carrick-delivers-team-news-for-man-utd-trip-to-bournemouth"
MUN_NOBODY = f"https://www.{MUN}/en/news/striker-closing-on-return-to-fitness"
ALIASES = cn.team_aliases([{"id": 14, "name": "Man Utd", "short_name": "MUN"}])


def _rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT url, length(body), body_source, left(body, 40) FROM news_items WHERE source = 'club' ORDER BY url")
        return {r[0]: r for r in cur.fetchall()}


SHORT_PROSE = "16 September 2026\nThe head coach confirmed the defender trained fully on Monday and will be assessed again on Thursday."


def test_n1_a_link_list_extract_is_dropped_not_stored_when_the_page_gives_nothing(conn, tmp_path):
    short_url = f"https://www.{MUN}/en/news/short-update"
    searches = {MUN: [_res(MUN_403, "Team news for United v Fulham | Manchester United", "Injury update ahead of Fulham."),
                      _res(MUN_NOBODY, "Striker closing on return to fitness | Manchester United", "Injury update ahead of Fulham: back in training."),
                      _res(short_url, "Short update | Manchester United", "Injury update ahead of Fulham.")]}
    extracts = {MUN_403: {"url": MUN_403, "raw_content": SIDEBAR_EXTRACT}, MUN_NOBODY: {"url": MUN_NOBODY, "raw_content": SIDEBAR_EXTRACT},
                short_url: {"url": short_url, "raw_content": SHORT_PROSE}}
    http = _Http({MUN_NOBODY: STADION_NOBODY})                                   # MUN_403 / short_url: the server's case, a 403 and no html
    lines = []
    cn.run(conn, {"Man Utd": MUN}, _Tavily(searches, extracts), now=NOW, raw_dir=tmp_path / "raw", log=lines.append, http=http,
           window=WINDOW, opponents={"Man Utd": ["Fulham"]}, aliases=ALIASES)
    rows = _rows(conn)
    assert rows[MUN_403][2] == "link_list_dropped" and rows[MUN_403][1] == 0
    assert rows[MUN_NOBODY][2] == "link_list_dropped" and rows[MUN_NOBODY][1] == 0
    assert rows[short_url][2] == "tavily_extract" and rows[short_url][1] > 60, "merely short prose is the article: kept (its dateline line dates the row)"
    assert any("body dropped" in ln and "team-news-for-united" in ln for ln in lines)
    with conn.cursor() as cur:                                                   # the headline still reaches the embed text
        cur.execute("SELECT embed_text FROM news_embed_text WHERE guid = %s", (cn.canonical_guid(MUN_403),))
        [(embed,)] = cur.fetchall()
    assert embed.endswith("Team news for United v Fulham\n") and "You might also like" not in embed


def test_n1_only_a_navigation_signature_drops_a_body():
    mci = ("Manchester City Official App Manchester City FC Ltd\nMaresca provides injury update and team news\nWed 16 Sep 2026, 10:48\n"
           "Enzo Maresca says Jeremy Doku is closing in on a return.")
    assert cn.looks_like_link_list(mci)[0] is True                                 # short and title-like ...
    assert cn.structural_link_list(mci) == (False, "")                             # ... but no signature: kept
    assert cn.structural_link_list(SIDEBAR_EXTRACT)[0] is True                     # each related piece listed twice
    assert cn.structural_link_list("One day to go! Be ready for PL tickets\nYou might also like\nWhen is Carrick's press conference?")[0] is True


def test_n1_the_page_body_wins_when_the_page_is_there(conn, tmp_path):
    """the laptop-fetched manutd.com page (21 Oct, HTTP 200); its JSON-LD dates it 18 Mar 2026, so that is the window"""
    now = datetime(2026, 3, 19, 15, 7, tzinfo=UTC)
    window = (datetime(2026, 3, 16, 17, 30, tzinfo=UTC), datetime(2026, 3, 19, 17, 30, tzinfo=UTC))
    searches = {MUN: [_res(MUN_PAGE, "Michael Carrick delivers team news | Manchester United", "Injury update ahead of Bournemouth.")]}
    extracts = {MUN_PAGE: {"url": MUN_PAGE, "raw_content": SIDEBAR_EXTRACT}}
    cn.run(conn, {"Man Utd": MUN}, _Tavily(searches, extracts), now=now, raw_dir=tmp_path / "raw", log=lambda m: None, http=_Http({MUN_PAGE: MANUTD}),
           window=window, opponents={"Man Utd": ["Bournemouth"]}, aliases=ALIASES)
    rows = _rows(conn)
    assert rows[MUN_PAGE][2] == "page_embedded" and rows[MUN_PAGE][1] > 1000



# ================================================================ N2: language copies and identical chunks
def test_n2_canonical_guid_strips_a_language_path_but_keeps_en():
    en = "https://www.liverpoolfc.com/news/andoni-iraola-season-so-far"
    assert cn.canonical_guid("https://www.liverpoolfc.com/pt/news/andoni-iraola-season-so-far") == cn.canonical_guid(en)
    assert cn.canonical_guid("https://www.liverpoolfc.com/es/news/andoni-iraola-season-so-far") == cn.canonical_guid(en)
    assert cn.canonical_guid("https://www.liverpoolfc.com/fr/news/andoni-iraola-season-so-far/") == "https://liverpoolfc.com/news/andoni-iraola-season-so-far"
    assert cn.canonical_guid("https://www.manutd.com/en/news/some-story") == "https://manutd.com/en/news/some-story"   # /en/ is the stored form


def test_n2_filter_results_drops_language_copies():
    kept, dropped = cn.filter_results([_res("https://www.liverpoolfc.com/news/x", "x", "c"), _res("https://www.liverpoolfc.com/pt/news/x", "x", "c"),
                                       _res("https://www.liverpoolfc.com/ja/news/x", "x", "c")], "liverpoolfc.com")
    assert [r["url"] for r in kept] == ["https://www.liverpoolfc.com/news/x"]
    assert sorted(why for _, why in dropped) == ["language copy: /ja/", "language copy: /pt/"]


def test_n2_a_bbc_item_redelivered_with_another_guid_fragment_is_the_same_row(conn):
    """BBC's RSS <guid> is the link plus a position fragment ('#0', '#2') that changes between feed fetches, so one
    article became a new row on every re-delivery (125 BBC URLs with 2+ guids on the laptop copy of 21 Oct; the
    RAG labels hold three such pairs). The guid is now the canonical link: fragment and query dropped."""
    rss = ("<rss><channel>"
           "<item><guid>https://www.bbc.co.uk/sport/football/articles/c63r5w20ez3do#0</guid>"
           "<link>https://www.bbc.co.uk/sport/football/articles/c63r5w20ez3do?at_medium=RSS</link><title>Hincapie injury</title>"
           "<description>Heroics and battling performances.</description><pubDate>Fri, 10 Oct 2026 15:44:14 GMT</pubDate></item>"
           "</channel></rss>").encode("utf-8")
    items, errors = ns.parse_rss(rss)
    assert errors == [] and items[0]["guid"] == "https://bbc.co.uk/sport/football/articles/c63r5w20ez3do"
    rss2 = rss.replace(b"c63r5w20ez3do#0", b"c63r5w20ez3do#2")
    assert ns.parse_rss(rss2)[0][0]["guid"] == items[0]["guid"]


# ================================================================ N3: the guard accepts the search's own range
W7 = (datetime(2026, 10, 14, 10, 0, tzinfo=UTC), datetime(2026, 10, 17, 10, 0, tzinfo=UTC))


def test_n3_search_window_on_day_one_pulls_the_start_back_and_the_guard_accepts_it():
    start, end, accept_from = cn.search_window(W7, datetime(2026, 10, 14, 15, 7, tzinfo=UTC))
    assert (start, end, accept_from) == ("2026-10-13", "2026-10-14", date(2026, 10, 13))
    article = datetime(2026, 10, 13, 18, 0, tzinfo=UTC)
    assert cn.guard("Hull City preview", article, W7, ["Hull City"], ALIASES, accept_from=accept_from) == (True, "dated inside window")
    assert cn.guard("Hull City preview", article, W7, ["Hull City"], ALIASES) == (False, "dated outside window")
    start, end, accept_from = cn.search_window(W7, datetime(2026, 10, 15, 15, 7, tzinfo=UTC))
    assert (start, end, accept_from) == ("2026-10-14", "2026-10-15", date(2026, 10, 14))


def test_n3_the_run_passes_the_search_start_to_the_guard(conn, tmp_path):
    now = datetime(2026, 10, 14, 15, 7, tzinfo=UTC)
    url = f"https://www.{MUN}/en/news/team-news-before-hull"
    searches = {MUN: [_res(url, "Team news before Hull | Manchester United", "13 October 2026\nInjury update before Hull.")]}
    extracts = {url: {"url": url, "raw_content": "13 October 2026\n" + REAL_EXTRACT}}
    http = _Http({url: JSONLD.replace("2026-09-16", "2026-10-13")})
    lines = []
    tv = _Tavily(searches, extracts)
    cn.run(conn, {"Man Utd": MUN}, tv, now=now, raw_dir=tmp_path / "raw", log=lines.append, http=http,
           window=W7, opponents={"Man Utd": ["Hull City"]}, aliases=ALIASES)
    assert (tv.requests[0].get("start_date"), tv.requests[0].get("end_date")) == ("2026-10-13", "2026-10-14")
    assert url in _rows(conn), "an article dated on the search's first day is kept"


# ================================================================ N4: no undated retry
class _DatedEmpty:
    def __init__(self):
        self.requests = []

    def search(self, query, domain, start_date=None, end_date=None):
        self.requests.append(cn.search_request(query, [domain], start_date, end_date))
        return {"results": []} if start_date else {"results": [_res(f"https://www.{domain}/news/x", "x", "c")]}

    def extract(self, urls):
        return {"results": [], "failed_results": list(urls)}


def test_n4_zero_results_make_no_second_request():
    tv = _DatedEmpty()
    plan = cn.search_plan(tv, "Arsenal team news injury update", "arsenal.com", "2026-10-13", "2026-10-14")
    assert len(tv.requests) == 1 and plan["results"] == [] and plan["credits"] == cn.SEARCH_CREDITS
    assert plan.get("retried_without_dates", False) is False
    assert cn.planned_credits(9) == 9 * cn.SEARCH_CREDITS + cn.extract_credits(cn.MAX_RESULTS * 9)


# ================================================================ N5: the HTTP status in the ledger
def test_n5_the_ledger_has_an_http_status_column_and_record_call_fills_it(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'tavily_calls' ORDER BY ordinal_position")
        assert "http_status" in [r[0] for r in cur.fetchall()]
    cn.record_call(conn, "search", "Spurs", "q", 5, 1, called_at=NOW, http_status=200)
    cn.record_call(conn, "extract", None, None, 0, 1, called_at=NOW)
    with conn.cursor() as cur:
        cur.execute("SELECT endpoint, http_status FROM tavily_calls ORDER BY id")
        assert cur.fetchall() == [("search", 200), ("extract", None)]


def test_n5_the_client_records_the_status_of_every_request(monkeypatch):
    import io
    from urllib.error import HTTPError

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(cn, "urlopen", lambda req, timeout=None, context=None: _Resp(b'{"results": []}'))
    tv = cn.TavilyClient(key="k")
    tv.search("q", "arsenal.com")
    assert tv.last_status == 200

    def boom(req, timeout=None, context=None):
        raise HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"slow down"))
    monkeypatch.setattr(cn, "urlopen", boom)
    with pytest.raises(RuntimeError):
        tv.extract(["https://www.arsenal.com/news/x"])
    assert tv.last_status == 429


def test_n5_the_run_writes_the_status_the_client_saw(conn, tmp_path):
    url = f"https://www.{MUN}/en/news/team-news-x"
    tv = _Tavily({MUN: [_res(url, "Team news x | Manchester United", "Injury update ahead of Fulham.")]}, {url: {"url": url, "raw_content": REAL_EXTRACT}})
    tv.last_status = 200
    cn.run(conn, {"Man Utd": MUN}, tv, now=NOW, raw_dir=tmp_path / "raw", log=lambda m: None, http=_Http({url: JSONLD}),
           window=WINDOW, opponents={"Man Utd": ["Fulham"]}, aliases=ALIASES)
    with conn.cursor() as cur:
        cur.execute("SELECT endpoint, http_status FROM tavily_calls ORDER BY id")
        assert cur.fetchall() == [("search", 200), ("extract", 200)]
