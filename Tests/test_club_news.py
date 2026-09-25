"""Club-news ingestion v1 (2026-09-25): nine official club sites through Tavily into
news_items as source 'club'. No network: the fixtures under Tests/fixtures/tavily/ are real
Tavily responses saved during the 2026-09-25 measurements (three basic searches, one
advanced search with off-domain leakage, one 19-URL basic extract).

Pinned here:
  * the domain filter keeps www./subdomains and rejects off-domain and look-alike hosts;
  * listing/index pages are dropped with a reason (page= query, /listing paths, bare
    /news paths); article URLs are kept;
  * the guid is the canonical URL; variants collapse to one guid;
  * a day-level date with a year in the URL becomes published_at with date_source 'url';
    a slug without a year gives no date;
  * --seed marks every new item 'backlog'; a normal run extracts only unseen URLs and
    marks them 'url' or 'first_seen';
  * the same search response twice is a no-op: no rows, no extract call;
  * the credit guard refuses to make ANY call once the month's recorded credits plus the
    planned ones exceed TAVILY_MONTHLY_LIMIT, and says why;
  * every Tavily call writes a tavily_calls row with the credits it cost by rule;
  * Markdown cleaning is deterministic and tested on an exact sample;
  * the view renders club rows with the three date forms.
Needs a local Postgres (skips loudly without one), like Tests/test_news_ingest.py.
"""
import gzip
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import config_roles  # noqa: E402
import news_store as ns  # noqa: E402
import club_news as cn  # noqa: E402

FX = REPO / "Tests" / "fixtures" / "tavily"
UTC = timezone.utc
NOW = datetime(2026, 9, 25, 19, 0, 0, tzinfo=UTC)
TEST_DB = "fpl_news_test"
THREE = {"Arsenal": "arsenal.com", "Chelsea": "chelseafc.com", "Crystal Palace": "cpfc.co.uk"}


def _fixture(name):
    return json.load(open(FX / name, encoding="utf-8"))


class FakeTavily:
    """Serves the saved responses and records every call it receives."""
    def __init__(self, extra_results=None, extract_extra=None):
        self.searches, self.extracts = [], []
        self.extra_results = extra_results or {}
        self.extract_pool = {r["url"]: r for r in _fixture("extract_basic_19urls.json")["response"]["results"]}
        self.extract_pool.update(extract_extra or {})

    def search(self, query, domain):
        self.searches.append((query, domain))
        resp = json.loads(json.dumps(_fixture(f"search_{domain}.json")["response"]))
        resp["results"] = resp["results"] + self.extra_results.get(domain, [])
        return resp

    def extract(self, urls):
        self.extracts.append(list(urls))
        return {"results": [self.extract_pool[u] for u in urls if u in self.extract_pool],
                "failed_results": [u for u in urls if u not in self.extract_pool], "response_time": 0.01}


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres for the club-news tests: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    with c.cursor() as cur:
        cur.execute("DROP VIEW IF EXISTS news_embed_text; DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


def _club_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT guid, version, club, date_source, published_at, fetched_at, headline, body, raw_ref, url "
                    "FROM news_items WHERE source = 'club' ORDER BY guid")
        return cur.fetchall()


def _calls(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT endpoint, club, query, n_results, credits, called_at FROM tavily_calls ORDER BY id")
        return cur.fetchall()


# ---- pure filters -------------------------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    ("https://www.arsenal.com/news/x", True),
    ("https://arsenal.com/news/x", True),
    ("https://m.arsenal.com/news/x", True),
    ("https://www.reddit.com/r/penguins", False),
    ("https://arsenal.com.evil.io/news/x", False),
    ("https://notarsenal.com/news/x", False),
    ("https://www.arsenal.com.example/news/x", False),
])
def test_domain_filter(url, ok):
    assert cn.on_domain(url, "arsenal.com") is ok


def test_domain_filter_on_the_real_offdomain_leak():
    res = _fixture("search_ccfc.co.uk.advanced_offdomain.json")["response"]["results"]
    kept, dropped = cn.filter_results(res, "ccfc.co.uk")
    hosts = sorted({d[0].split("/")[2] for d in dropped if d[1].startswith("off-domain")})
    assert hosts == ["news.ycombinator.com", "www.cbsnews.com", "www.concordiacollege.edu", "www.reddit.com"]
    assert all(cn.on_domain(k["url"], "ccfc.co.uk") for k in kept)


@pytest.mark.parametrize("url,reason", [
    ("https://www.brentfordfc.com/en/news?page=1", "listing:page="),
    ("https://www.leedsunited.com/en/news?type=all&page=5", "listing:page="),
    ("https://www.brentfordfc.com/en/news/listing/all-news", "listing:/listing"),
    ("https://www.manutd.com/en/news/listing/mens-news?type=news&page=48", "listing:page="),
    ("https://www.ccfc.co.uk/news", "listing:index"),
    ("https://www.ccfc.co.uk/news/", "listing:index"),
    ("https://www.brentfordfc.com/en/news", "listing:index"),
    ("https://www.chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford", None),
    ("https://www.afcb.co.uk/news/2026/september/14/uefa-europa-league-2026-27-format-explained", None),
    ("https://www.cpfc.co.uk/news/first-team/team-news-sage-hints-at-possible-sarr-nketiah-returns", None),
])
def test_listing_filter(url, reason):
    assert cn.listing_reason(url) == reason


@pytest.mark.parametrize("url", [
    "https://www.chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford",
    "http://chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford/",
    "https://WWW.ChelseaFC.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford?utm=x#top",
    "https://www.chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford/#comments",
])
def test_canonical_guid_collapses_variants(url):
    assert cn.canonical_guid(url) == "https://chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford"


@pytest.mark.parametrize("url,expected", [
    ("https://www.afcb.co.uk/news/2026/september/14/uefa-europa-league-2026-27-format-explained", date(2026, 9, 14)),
    ("https://www.avfc.co.uk/news/2026/09/18/prematch-team-news", date(2026, 9, 18)),
    ("https://www.safc.com/news/2025/march/27/Le-Bris-provides-injury-update", date(2025, 3, 27)),
    ("https://www.manutd.com/en/news/baleba-closing-on-return-to-fitness-brighton-16-sept", None),      # no year
    ("https://www.cpfc.co.uk/news/match-reports/match-report-crystal-palace-lech-poznan-september-2026", None),  # no day
    ("https://www.chelseafc.com/en/news/article/brentford-vs-chelsea-all-you-need-to-know-26-27", None),
    ("https://www.arsenal.com/news/preview-ipswich-town-v-arsenal-abI8U2g5qIiy", None),
])
def test_url_date_parser(url, expected):
    assert cn.url_date(url) == expected


# ---- cleaning -----------------------------------------------------------------------------

SAMPLE_MD = """# Team News: Sage hints at possible Sarr & Nketiah returns
[Skip navigation](#main) [Crystal palace](/) [Crystal palace](/)
## [First-team](/news/first-team)
Pierre Sage says [Ismaïla Sarr](/players/sarr) and **Eddie Nketiah** could both return to the matchday squad on Thursday.
![Sarr training](https://img.example/x.jpg)
Share

Read more: https://www.cpfc.co.uk/news/x
“He could be in the team tomorrow,” Sage said.
"""
SAMPLE_TXT = ("Team News: Sage hints at possible Sarr & Nketiah returns\n"
              "Pierre Sage says Ismaïla Sarr and Eddie Nketiah could both return to the matchday squad on Thursday.\n"
              "“He could be in the team tomorrow,” Sage said.")


def test_clean_markdown_exact_sample():
    assert cn.clean_markdown(SAMPLE_MD) == SAMPLE_TXT
    assert cn.clean_markdown(SAMPLE_MD) == cn.clean_markdown(SAMPLE_MD), "deterministic"


def test_clean_markdown_keeps_editorial_brackets_and_unwraps_nested_links():
    """Quotes carry the source's own insertions -- "[Bruno] had a knock" -- which are text and
    stay. A link whose text holds such an insertion, [Dango [Ouattara]](url), unwraps to its
    text; the first live seed left a stray "](" from exactly this case."""
    md = 'On Sunday we played [Dango [Ouattara]](/players/ouattara) a little bit more, and "[Bruno] had a knock," he said.'
    assert cn.clean_markdown(md) == 'On Sunday we played Dango [Ouattara] a little bit more, and "[Bruno] had a knock," he said.'


def test_clean_markdown_unwraps_multiline_link_cards():
    """Man City's pages (live seed, 2026-09-25) carry link cards whose text spans lines; five
    stored bodies kept a stray "](/news/...)" until the cleaner unwrapped links over the
    whole text. The heading survives as text; the two-word label is a menu line and goes."""
    md = ("Further reading\n\n[![Players celebrating a goal.](https://x/img.png?w=1)\n\n\n\n"
          "### Semenyo up for Premier League Player of the Month\n\nMen's Team](/news/mens/semenyo-63925764)\n\n"
          "The City boss also provided the latest news on Ruben Dias ahead of the derby.")
    assert cn.clean_markdown(md) == ("Semenyo up for Premier League Player of the Month\n"
                                     "The City boss also provided the latest news on Ruben Dias ahead of the derby.")


def test_clean_markdown_on_the_real_extract():
    pool = {r["url"]: r["raw_content"] for r in _fixture("extract_basic_19urls.json")["response"]["results"]}
    txt = cn.clean_markdown(pool["https://www.chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford"])
    assert "However, Alonso insists they have not been ruled out of our next match." in txt
    assert "Joao Pedro" in txt and "(/en/teams" not in txt and "http" not in txt and "[" not in txt
    palace = cn.clean_markdown(pool["https://www.cpfc.co.uk/news/first-team/team-news-sage-hints-at-possible-sarr-nketiah-returns"])
    assert "Skip navigation" not in palace and "Crystal palace\nCrystal palace" not in palace
    assert "could both return to the matchday squad" in palace


# ---- the run: seed, normal, idempotent ------------------------------------------------------

def test_seed_run_marks_everything_backlog_and_records_calls(conn, tmp_path):
    tv = FakeTavily()
    summary = cn.run(conn, THREE, tv, now=NOW, seed=True, raw_dir=tmp_path / "raw")
    rows = _club_rows(conn)
    assert len(rows) == 14 and {r[3] for r in rows} == {"backlog"} and {r[1] for r in rows} == {1}
    assert {r[2] for r in rows} == {"Arsenal", "Chelsea", "Crystal Palace"}
    assert all(r[4] is None and r[5] == NOW for r in rows)
    assert all(r[7] and "http" not in r[7] for r in rows), "bodies are cleaned plain text"
    assert all(r[8].endswith(".extract.json.gz") for r in rows), "raw_ref is the extract file"
    assert all(r[0] == cn.canonical_guid(r[9]) for r in rows)
    # calls: three searches at 1 credit, one extract at ceil(14/5) = 3
    calls = _calls(conn)
    assert [(c[0], c[4]) for c in calls] == [("search", 1), ("search", 1), ("search", 1), ("extract", 3)]
    assert calls[0][1] == "Arsenal" and calls[0][2] == "Arsenal team news injury update" and calls[0][3] == 4
    assert calls[3][3] == 14 and summary["credits"] == 6
    assert len(tv.extracts) == 1 and len(tv.extracts[0]) == 14
    # raw files: three gzipped search responses and one extract
    raw = sorted(p.name for p in (tmp_path / "raw").rglob("*.gz"))
    assert len([n for n in raw if n.endswith(".search.json.gz")]) == 3 and len([n for n in raw if n.endswith(".extract.json.gz")]) == 1
    one = next(p for p in (tmp_path / "raw").rglob("*.search.json.gz"))
    saved = json.loads(gzip.decompress(one.read_bytes()))
    assert saved["request"]["include_domains"] and "results" in saved["response"], "raw file = request + the response as received"


def test_normal_run_after_seed_extracts_only_unseen(conn, tmp_path):
    tv = FakeTavily()
    cn.run(conn, THREE, tv, now=NOW, seed=True, raw_dir=tmp_path / "raw")
    dated = "https://www.arsenal.com/news/2026/september/17/every-word-of-the-injury-update"
    undated = "https://www.arsenal.com/news/gabriel-gives-fitness-update-abc123"
    extra = {"arsenal.com": [{"url": dated, "title": "Every word of the injury update", "content": "x", "score": 0.5},
                             {"url": undated, "title": "Gabriel gives fitness update", "content": "y", "score": 0.4},
                             {"url": "https://www.arsenal.com/news?page=2", "title": "News", "content": "z", "score": 0.1}]}
    pool = {dated: {"url": dated, "raw_content": "Gabriel is fit again, Arteta confirmed on Thursday."},
            undated: {"url": undated, "raw_content": "Gabriel has returned to full training."}}
    tv2 = FakeTavily(extra_results=extra, extract_extra=pool)
    later = NOW + timedelta(days=1)
    summary = cn.run(conn, THREE, tv2, now=later, seed=False, raw_dir=tmp_path / "raw")
    assert tv2.extracts == [[dated, undated]], "only the two unseen article URLs are extracted"
    rows = {r[0]: r for r in _club_rows(conn)}
    assert len(rows) == 16
    d = rows[cn.canonical_guid(dated)]
    assert d[3] == "url" and d[4] == datetime(2026, 9, 17, tzinfo=UTC) and d[5] == later
    u = rows[cn.canonical_guid(undated)]
    assert u[3] == "first_seen" and u[4] is None and u[5] == later
    assert summary["clubs"]["Arsenal"]["already_seen"] == 4 and summary["clubs"]["Arsenal"]["new"] == 2
    assert summary["clubs"]["Arsenal"]["dropped"] == [("https://www.arsenal.com/news?page=2", "listing:page=")]
    assert summary["credits"] == 3 + 1                                   # 3 searches + ceil(2/5)


def test_same_response_twice_is_a_noop(conn, tmp_path):
    tv = FakeTavily()
    cn.run(conn, THREE, tv, now=NOW, seed=True, raw_dir=tmp_path / "raw")
    before = _club_rows(conn)
    tv2 = FakeTavily()
    summary = cn.run(conn, THREE, tv2, now=NOW + timedelta(hours=6), seed=False, raw_dir=tmp_path / "raw")
    assert _club_rows(conn) == before
    assert tv2.extracts == [] and summary["extracted"] == 0 and summary["new"] == 0 and summary["already_seen"] == 14
    assert summary["credits"] == 3


def test_credit_guard_refuses_before_any_call(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config_roles, "TAVILY_MONTHLY_LIMIT", 20)
    monkeypatch.setattr(cn, "TAVILY_MONTHLY_LIMIT", 20)
    cn.record_call(conn, "search", "Spurs", "q", 5, 18, called_at=NOW - timedelta(days=3))
    cn.record_call(conn, "search", "Spurs", "q", 5, 18, called_at=NOW - timedelta(days=40))   # last month: not counted
    assert cn.month_credits(conn, NOW) == 18
    tv = FakeTavily()
    log = []
    with pytest.raises(cn.CreditLimit) as e:
        cn.run(conn, THREE, tv, now=NOW, seed=True, raw_dir=tmp_path / "raw", log=log.append)
    assert tv.searches == [] and tv.extracts == [], "no call may be made once the guard refuses"
    assert "18" in str(e.value) and "20" in str(e.value) and "TAVILY_MONTHLY_LIMIT" in str(e.value)
    assert any("TAVILY_MONTHLY_LIMIT" in l for l in log)
    assert _club_rows(conn) == [] and len(_calls(conn)) == 2


def test_runner_exits_non_zero_on_the_guard(conn, tmp_path, monkeypatch):
    import fetch_club_news as runner
    monkeypatch.setattr(cn, "TAVILY_MONTHLY_LIMIT", 1)
    cn.record_call(conn, "search", "Spurs", "q", 5, 1, called_at=NOW)
    monkeypatch.setattr(runner, "make_tavily", lambda: FakeTavily())
    monkeypatch.setattr(runner, "make_http", lambda raw_dir: None)
    # v2 gate: give the runner a deadline one day ahead of its clock so the window is open
    monkeypatch.setattr(runner, "load_events", lambda: [{"id": 6, "deadline_time": (NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "finished": False}])
    monkeypatch.setattr(runner, "load_teams", lambda: [])
    monkeypatch.setattr(runner, "load_opponents", lambda gw, teams: {})
    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sys, "argv", ["fetch_club_news.py", "--seed", "--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ")])
    with pytest.raises(SystemExit) as e:
        runner.main()
    assert e.value.code == 2, "the credit guard refused: exit 2, nothing called"


# ---- schema and the view ----------------------------------------------------------------------

def test_date_source_backfilled_for_existing_sources(conn):
    ns.ingest_rss(conn, (REPO / "Tests" / "fixtures" / "bbc_premier_league_rss_2026-09-25.xml").read_bytes(),
                  raw_ref="r1", fetched_at=NOW)
    with conn.cursor() as cur:
        cur.execute("UPDATE news_items SET date_source = NULL")
        conn.commit()
    ns.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date_source FROM news_items WHERE source = 'bbc'")
        assert cur.fetchall() == [("feed",)]
        cur.execute("INSERT INTO news_items (source, guid, version, headline, body, published_at, fetched_at, content_hash, raw_ref, element_id, status, chance) "
                    "VALUES ('fpl', 'fpl:1', 1, 'A (ARS, GKP)', '', NULL, %s, 'h', 'r', 1, 'a', NULL), "
                    "('fpl', 'fpl:2', 1, 'B (ARS, DEF)', 'Knock', %s, %s, 'h2', 'r', 2, 'd', 75)", (NOW, NOW, NOW))
        conn.commit()
    ns.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT guid, date_source FROM news_items WHERE source = 'fpl' ORDER BY guid")
        assert cur.fetchall() == [("fpl:1", "first_seen"), ("fpl:2", "source_field")]


def test_view_renders_club_rows_with_the_three_date_forms(conn, tmp_path):
    tv = FakeTavily()
    cn.run(conn, {"Chelsea": "chelseafc.com"}, tv, now=NOW, seed=True, raw_dir=tmp_path / "raw")
    dated = "https://www.arsenal.com/news/2026/september/17/every-word-of-the-injury-update"
    undated = "https://www.arsenal.com/news/gabriel-gives-fitness-update-abc123"
    extra = {"arsenal.com": [{"url": dated, "title": "Every word of the injury update", "content": "x", "score": 0.5},
                             {"url": undated, "title": "Gabriel gives fitness update", "content": "y", "score": 0.4}]}
    pool = {dated: {"url": dated, "raw_content": "Gabriel is fit again, Arteta confirmed on Thursday."},
            undated: {"url": undated, "raw_content": "Gabriel has returned to full training."}}
    cn.run(conn, {"Arsenal": "arsenal.com"}, FakeTavily(extra_results=extra, extract_extra=pool),
           now=datetime(2026, 9, 26, 7, 7, tzinfo=UTC), seed=False, raw_dir=tmp_path / "raw")
    with conn.cursor() as cur:
        cur.execute("SELECT guid, embed_text, char_count FROM news_embed_text WHERE source = 'club' ORDER BY guid")
        v = {g: (t, c) for g, t, c in cur.fetchall()}
    t, c = v[cn.canonical_guid(dated)]
    assert t == "[Arsenal official site | 2026-09-17] Every word of the injury update\nGabriel is fit again, Arteta confirmed on Thursday." and c == len(t)
    t, _ = v[cn.canonical_guid(undated)]
    assert t == "[Arsenal official site | first seen 2026-09-26] Gabriel gives fitness update\nGabriel has returned to full training."
    t, _ = v["https://chelseafc.com/en/news/article/xabi-alonso-confirms-chelsea-team-news-for-brentford"]
    assert t.startswith("[Chelsea official site | date unknown (backlog)] Xabi Alonso confirms Chelsea team news for Brentford")
    assert "However, Alonso insists they have not been ruled out of our next match." in t


def test_config_names_the_nine_clubs_and_the_limit():
    assert len(config_roles.CLUB_NEWS_CLUBS) == 9
    assert set(config_roles.CLUB_NEWS_CLUBS) <= set(config_roles.CLUB_DOMAINS)
    assert {config_roles.CLUB_DOMAINS[c] for c in config_roles.CLUB_NEWS_CLUBS} == {
        "arsenal.com", "brentfordfc.com", "chelseafc.com", "cpfc.co.uk", "liverpoolfc.com", "mancity.com",
        "manutd.com", "newcastleunited.com", "tottenhamhotspur.com"}
    assert config_roles.TAVILY_MONTHLY_LIMIT == 800
    assert cn.extract_credits(14) == 3 and cn.extract_credits(5) == 1 and cn.extract_credits(0) == 0 and cn.SEARCH_CREDITS == 1

# ---- v2 Part A (2026-09-25): headline trim, ten results per search --------------------------

@pytest.mark.parametrize("title,expected", [
    ("Xabi Alonso confirms Chelsea team news for Brentford | News | Official Site | Chelsea Football Club",
     "Xabi Alonso confirms Chelsea team news for Brentford"),
    ("Liverpool's injury list, suspensions and availability - Liverpool FC",
     "Liverpool's injury list, suspensions and availability"),
    ("Liverpool v Tottenham Hotspur: Team news - Liverpool FC", "Liverpool v Tottenham Hotspur: Team news"),
    ("Preview: Ipswich Town v Arsenal | Arsenal FC Official Website | Arsenal.com", "Preview: Ipswich Town v Arsenal"),
    ("Team news for United v Brighton | Manchester United", "Team news for United v Brighton"),
    ("Matthias Jaissle's team news update: Elanga latest ahead of Hull visit | NUFC",
     "Matthias Jaissle's team news update: Elanga latest ahead of Hull visit"),
    ("Bijol selected for Slovenia's upcoming internationals - Leeds United", "Bijol selected for Slovenia's upcoming internationals"),
    ("Loan Report: Start of 2026/27 Season - Hull City", "Loan Report: Start of 2026/27 Season"),
    ("Man City and the 115 charges - key questions answered", "Man City and the 115 charges - key questions answered"),
    ("Report: Eagles ease past Poznan in excellent Europa debut", "Report: Eagles ease past Poznan in excellent Europa debut"),
    ("Injury update: Pep delivers latest team news ahead of Manchester derby", "Injury update: Pep delivers latest team news ahead of Manchester derby"),
])
def test_headline_trim_drops_site_suffixes_only(title, expected):
    assert cn.trim_headline(title) == expected


def test_headline_trim_on_every_fixture_title():
    """No fixture title keeps a trailing site segment, and none loses its real words."""
    for name in ("search_arsenal.com.json", "search_chelseafc.com.json", "search_cpfc.co.uk.json"):
        for r in _fixture(name)["response"]["results"]:
            t = cn.trim_headline(r["title"])
            assert t and not re.search(r"(Official Site|Official Website|Football Club|\| NUFC|- Liverpool FC|Arsenal\.com)\s*$", t), (r["title"], t)
            assert t == t.strip() and len(t) <= len(r["title"])


def test_search_asks_for_ten_results():
    assert cn.MAX_RESULTS == 10
    body = cn.search_request("Chelsea team news injury update", ["chelseafc.com"])
    assert body["max_results"] == 10 and body["search_depth"] == "basic" and body["include_domains"] == ["chelseafc.com"]
