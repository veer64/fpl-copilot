"""Club-news ingestion v2, the final design (2026-09-25): generic query on the nine club
sites only, a deadline-window schedule gate, real publish dates from the page (JSON-LD, then
<time>), the URL, or a dateline; an old-article guard before Extract; replay from saved raw
files with zero Tavily calls and zero HTTP requests. No network in these tests.

Decided by measurement and not revisited here: the generic query (11 genuine GW5 items
against 3 for the fixture query); no press sources; Man City answers 403 to the honest
User-Agent and the UA is never changed to get around it; Chelsea's pages carry no date tags.
Needs a local Postgres for the run tests (skips loudly without one).
"""
import gzip
import json
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

UTC = timezone.utc
TEST_DB = "fpl_news_test"
GW5 = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)                 # a Friday-evening deadline
EVENTS = [{"id": 4, "deadline_time": "2026-09-12T12:30:00Z", "finished": True},
          {"id": 5, "deadline_time": "2026-09-18T17:30:00Z", "finished": True},
          {"id": 6, "deadline_time": "2026-10-10T10:00:00Z", "finished": False},
          {"id": 7, "deadline_time": "2026-10-17T10:00:00Z", "finished": False}]
TEAMS = [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 5, "name": "Brighton", "short_name": "BHA"},
         {"id": 4, "name": "Brentford", "short_name": "BRE"}, {"id": 6, "name": "Chelsea", "short_name": "CHE"},
         {"id": 16, "name": "Man Utd", "short_name": "MUN"}, {"id": 18, "name": "Nott'm Forest", "short_name": "NFO"},
         {"id": 19, "name": "Spurs", "short_name": "TOT"}, {"id": 11, "name": "Hull City", "short_name": "HUL"}]
WINDOW = (GW5 - timedelta(days=3), GW5)


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
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


# ---- the schedule gate --------------------------------------------------------------------------

@pytest.mark.parametrize("now,expect_open,gw,opens", [
    (datetime(2026, 9, 15, 17, 29, tzinfo=UTC), False, 5, datetime(2026, 9, 15, 17, 30, tzinfo=UTC)),
    (datetime(2026, 9, 15, 17, 30, tzinfo=UTC), True, 5, datetime(2026, 9, 15, 17, 30, tzinfo=UTC)),
    (datetime(2026, 9, 17, 15, 7, tzinfo=UTC), True, 5, datetime(2026, 9, 15, 17, 30, tzinfo=UTC)),
    (datetime(2026, 9, 18, 17, 30, tzinfo=UTC), True, 5, datetime(2026, 9, 15, 17, 30, tzinfo=UTC)),     # AT the Friday-evening deadline: still open
    (datetime(2026, 9, 18, 17, 31, tzinfo=UTC), False, 6, datetime(2026, 10, 7, 10, 0, tzinfo=UTC)),    # past it: next is GW6
    (datetime(2026, 9, 25, 15, 7, tzinfo=UTC), False, 6, datetime(2026, 10, 7, 10, 0, tzinfo=UTC)),     # the international break
    (datetime(2026, 10, 9, 15, 7, tzinfo=UTC), True, 6, datetime(2026, 10, 7, 10, 0, tzinfo=UTC)),
])
def test_gate(now, expect_open, gw, opens):
    g = cn.gate(now, EVENTS)
    assert (g["open"], g["gw"], g["opens_at"]) == (expect_open, gw, opens)
    assert g["window"] == (g["deadline"] - timedelta(days=3), g["deadline"])


def test_gate_with_no_future_deadline():
    g = cn.gate(datetime(2027, 7, 1, tzinfo=UTC), EVENTS)
    assert g["open"] is False and g["gw"] is None


# ---- aliases, opponents, the guard ------------------------------------------------------------------

def test_team_aliases_and_naming():
    a = cn.team_aliases(TEAMS)
    assert {"Tottenham", "Spurs", "TOT", "THFC"} <= set(a["Spurs"])
    assert cn.names_team("De Zerbi previews the trip to Tottenham on Saturday", "Spurs", a)
    assert cn.names_team("Spurs are next", "Spurs", a) and cn.names_team("ARS v TOT preview", "Spurs", a)
    assert not cn.names_team("a total of five changes", "Spurs", a), "'TOT' inside 'total' is not the club"
    assert not cn.names_team("Newcastle United beat Leeds United", "Man Utd", a), "bare 'United' is nobody"
    assert cn.names_team("Nottingham Forest visit next", "Nott'm Forest", a)


def test_opponents_from_fixture_rows():
    rows = [{"team": "Arsenal", "opponent_team": 5, "GW": 5}, {"team": "Brighton", "opponent_team": 1, "GW": 5},
            {"team": "Spurs", "opponent_team": 1, "GW": 5}, {"team": "Spurs", "opponent_team": 6, "GW": 5},   # a double
            {"team": "Arsenal", "opponent_team": 5, "GW": 5}]                                                   # duplicate row (per player)
    opp = cn.opponents_from_rows(rows, TEAMS)
    assert opp["Arsenal"] == ["Brighton"] and opp["Spurs"] == ["Arsenal", "Chelsea"] and "Chelsea" not in opp


def test_guard_rules_including_a_double():
    a = cn.team_aliases(TEAMS)
    inside, outside = datetime(2026, 9, 17, 9, 0, tzinfo=UTC), datetime(2026, 1, 16, 13, 45, tzinfo=UTC)
    assert cn.guard("anything", inside, WINDOW, ["Spurs"], a) == (True, "dated inside window")
    assert cn.guard("Tottenham are next", outside, WINDOW, ["Spurs"], a) == (False, "dated outside window")
    assert cn.guard("Arteta on the trip to Spurs on Saturday", None, WINDOW, ["Spurs"], a) == (True, "undated, opponent named")
    assert cn.guard("Arteta on the trip to Tottenham", None, WINDOW, ["Spurs"], a) == (True, "undated, opponent named")
    assert cn.guard("Arteta on the squad's fitness", None, WINDOW, ["Spurs"], a) == (False, "undated, opponent not named")
    assert cn.guard("Chelsea next, then Arsenal", None, WINDOW, ["Arsenal", "Chelsea"], a) == (True, "undated, opponent named")
    assert cn.guard("Brighton next", None, WINDOW, ["Arsenal", "Chelsea"], a) == (False, "undated, opponent not named")
    assert cn.guard("Tottenham are next", None, WINDOW, [], a) == (False, "undated, opponent not named"), "a blank gameweek names nobody"


# ---- the date chain --------------------------------------------------------------------------------

LD = '<html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-17T09:00:00+01:00"}</script></head><body><time datetime="2026-09-01T00:00:00Z">x</time></body></html>'
TIME = '<html><body><time datetime="2026-09-15T10:00:00Z">15 Sep</time></body></html>'


def test_hidden_date_jsonld_beats_time():
    assert cn.hidden_date(LD) == (datetime(2026, 9, 17, 8, 0, tzinfo=UTC), "jsonld")
    assert cn.hidden_date(TIME) == (datetime(2026, 9, 15, 10, 0, tzinfo=UTC), "time")
    assert cn.hidden_date("<html></html>") == (None, None) and cn.hidden_date("") == (None, None)
    nested = '<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},{"@type":"NewsArticle","datePublished":"2026-09-16"}]}</script>'
    assert cn.hidden_date(nested) == (datetime(2026, 9, 16, tzinfo=UTC), "jsonld")


def test_page_date_is_a_dateline_not_prose():
    fetched = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
    body = "Manchester City Official App Manchester City FC Ltd\nInjury update: Pep delivers latest team news\nFri 16 Jan 2026, 13:45\nPep says he is unsure."
    assert cn.page_date(body, fetched) == datetime(2026, 1, 16, tzinfo=UTC)
    assert cn.page_date("Line one.\nLine two.\nLine three.\nLine four.\nLine five.\nCarvalho last played on 28 October 2025.", fetched) is None
    assert cn.page_date("Published 14 Sep 26\nBody.", fetched) is None, "two-digit years are not years"
    assert cn.page_date("Tuesday 29 September 2026\nBody.", fetched) is None, "after fetched_at: rejected"
    assert cn.page_date("Wed 16 Sep 2026, 10:48\nShare", fetched) == datetime(2026, 9, 16, tzinfo=UTC)
    assert cn.page_date("14 September 2026\nBody.", fetched) == datetime(2026, 9, 14, tzinfo=UTC)


def test_best_date_priority_and_future_rejection():
    fetched = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
    url_dated = "https://www.afcb.co.uk/news/2026/september/14/x"
    body = "Fri 16 Jan 2026, 13:45\nProse."
    meta = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    assert cn.best_date(meta, url_dated, body, fetched) == (meta, "meta")
    assert cn.best_date(None, url_dated, body, fetched) == (datetime(2026, 9, 14, tzinfo=UTC), "url")
    assert cn.best_date(None, "https://x/news/no-date", body, fetched) == (datetime(2026, 1, 16, tzinfo=UTC), "page")
    assert cn.best_date(None, "https://x/news/no-date", "Prose only.", fetched) == (None, "first_seen")
    assert cn.best_date(datetime(2026, 9, 30, tzinfo=UTC), url_dated, body, fetched) == (datetime(2026, 9, 14, tzinfo=UTC), "url")
    assert cn.best_date(None, "https://x/news/2026/12/25/y", body, fetched) == (datetime(2026, 1, 16, tzinfo=UTC), "page"), "a future URL date is rejected too"


# ---- fakes ------------------------------------------------------------------------------------------

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
        if v is None:
            return 404, url, ""
        if v == "403":
            return 403, url, ""
        return 200, url, v


ARS_IN = "https://www.arsenal.com/news/arteta-previews-brighton-trip-abc"
ARS_OLD = "https://www.arsenal.com/news/january-piece"
ARS_OPP = "https://www.arsenal.com/news/team-news-albion-away"
ARS_NO = "https://www.arsenal.com/news/academy-round-up"
MCI_403 = "https://www.mancity.com/news/mens/maresca-injury-update-63925149"
CHE_NO = "https://www.chelseafc.com/en/news/article/alonso-confirms-team-news-for-brentford"
SEARCHES = {
    "arsenal.com": [
        _res(ARS_IN, "Arteta previews Brighton trip | Arsenal FC Official Website", "Arteta on Saliba's fitness."),
        _res(ARS_OLD, "A January piece | Arsenal.com", "Fri 16 Jan 2026, 13:45 Manchester derby."),   # the dateline rides in the snippet, as on mancity.com
        _res(ARS_OPP, "Team news: Albion away | Arsenal.com", "Arteta on the trip to Brighton & Hove Albion."),
        _res(ARS_NO, "Academy round-up | Arsenal.com", "The under-18s won."),
        _res("https://www.arsenal.com/news?page=2", "News", "listing")],
    "mancity.com": [_res(MCI_403, "Maresca provides injury update and team news", "Manchester City FC Wed 16 Sep 2026, 10:48 Enzo Maresca says Jeremy Doku is closing in on a return")],
    "chelseafc.com": [_res(CHE_NO, "Xabi Alonso confirms Chelsea team news for Brentford | News | Official Site | Chelsea Football Club",
                           "Alonso confirmed that Joao Pedro remains in contention to face Brentford.")],
}
EXTRACTS = {
    ARS_IN: {"url": ARS_IN, "raw_content": "Mikel Arteta gave an update on William Saliba before Saturday's trip to Brighton.\n\nSaliba is training again."},
    ARS_OLD: {"url": ARS_OLD, "raw_content": "Fri 16 Jan 2026, 13:45\n\nPep is unsure."},
    ARS_OPP: {"url": ARS_OPP, "raw_content": "Arteta on the trip to Brighton & Hove Albion.\n\nEverybody is fit."},
    ARS_NO: {"url": ARS_NO, "raw_content": "The under-18s won 3-0 at Hale End."},
    MCI_403: {"url": MCI_403, "raw_content": "![crest](/x.svg)\n\nManchester City Official App Manchester City FC Ltd\n\n# Maresca provides injury update and team news\n\nWed 16 Sep 2026, 10:48\n\nEnzo Maresca says Jeremy Doku is closing in on a return."},
    CHE_NO: {"url": CHE_NO, "raw_content": "Xabi Alonso confirmed that Joao Pedro and Reece James remain in contention to face Brentford."},
}
PAGES = {ARS_IN: LD, ARS_OLD: "<html></html>", ARS_OPP: "<html></html>", ARS_NO: "<html></html>",
         MCI_403: "403", CHE_NO: "<html><head><title>x</title></head></html>"}
NOW = datetime(2026, 9, 17, 15, 7, tzinfo=UTC)
CLUBS = {"Arsenal": "arsenal.com", "Man City": "mancity.com", "Chelsea": "chelseafc.com"}
OPPONENTS = {"Arsenal": ["Brighton"], "Man City": ["Sunderland"], "Chelsea": ["Brentford"]}


def _run(conn, tv, http, raw, **kw):
    return cn.run(conn, CLUBS, tv, now=NOW, raw_dir=raw, http=http, window=WINDOW, opponents=OPPONENTS,
                  aliases=cn.team_aliases(TEAMS), **kw)


def _rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT guid, source, club, date_source, published_at, body FROM news_items ORDER BY guid")
        return {r[0]: r for r in cur.fetchall()}


def test_run_guard_dates_and_the_403_fall_through(conn, tmp_path):
    tv, http = FakeTavily(SEARCHES, EXTRACTS), FakeHttp(PAGES)
    summary = _run(conn, tv, http, tmp_path / "raw")
    rows = _rows(conn)
    assert set(rows) == {cn.canonical_guid(u) for u in (ARS_IN, ARS_OPP, MCI_403, CHE_NO)}
    assert rows[cn.canonical_guid(ARS_IN)][3] == "meta" and rows[cn.canonical_guid(ARS_IN)][4] == datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    assert rows[cn.canonical_guid(ARS_OPP)][3] == "first_seen" and rows[cn.canonical_guid(ARS_OPP)][4] is None
    m = rows[cn.canonical_guid(MCI_403)]
    assert m[3] == "page" and m[4] == datetime(2026, 9, 16, tzinfo=UTC), "403 on the page: the dateline in the body dates it"
    assert rows[cn.canonical_guid(CHE_NO)][3] == "first_seen", "no tags, no URL date, no dateline: first_seen, kept because it names Brentford"
    dropped = {(u, why) for _, u, why in summary["dropped"]}
    assert (ARS_OLD, "dated outside window") in dropped and (ARS_NO, "undated, opponent not named") in dropped
    assert ("https://www.arsenal.com/news?page=2", "listing:page=") in dropped
    # requests: the generic query, club domains only, the window start and today as the dates
    assert [r["query"] for r in tv.requests] == ["Arsenal team news injury update", "Man City team news injury update", "Chelsea team news injury update"]
    assert all(r["include_domains"] in (["arsenal.com"], ["mancity.com"], ["chelseafc.com"]) for r in tv.requests)
    assert all(r["start_date"] == "2026-09-15" and r["end_date"] == "2026-09-17" and r["max_results"] == 10 for r in tv.requests)
    # one page GET per new kept URL, before Extract; no retry on the 403
    assert sorted(http.calls) == sorted([ARS_IN, ARS_OLD, ARS_OPP, ARS_NO, MCI_403, CHE_NO])
    assert http.calls.count(MCI_403) == 1
    assert sorted(tv.extract_calls[0]) == sorted([ARS_IN, ARS_OPP, MCI_403, CHE_NO])
    assert summary["credits"] == 3 + 1
    raw = tmp_path / "raw"
    assert len(list(raw.glob("*.search.json.gz"))) == 3 and len(list(raw.glob("*.extract.json.gz"))) == 1
    assert len(list((raw / "pages").glob("*.json.gz"))) == 6, "every page fetch is saved, the 403 included"


def test_seed_marks_backlog_only_when_nothing_dates_the_row(conn, tmp_path):
    tv, http = FakeTavily(SEARCHES, EXTRACTS), FakeHttp(PAGES)
    _run(conn, tv, http, tmp_path / "raw", seed=True)
    rows = _rows(conn)
    assert rows[cn.canonical_guid(ARS_IN)][3] == "meta" and rows[cn.canonical_guid(MCI_403)][3] == "page"
    assert rows[cn.canonical_guid(ARS_OPP)][3] == "backlog" and rows[cn.canonical_guid(CHE_NO)][3] == "backlog"


def test_replay_makes_zero_tavily_calls_and_zero_http_requests(conn, tmp_path):
    tv, http = FakeTavily(SEARCHES, EXTRACTS), FakeHttp(PAGES)
    _run(conn, tv, http, tmp_path / "raw")
    with conn.cursor() as cur:
        cur.execute("SELECT guid, source, club, date_source, published_at, content_hash, headline FROM news_items ORDER BY guid")
        before = cur.fetchall()
        cur.execute("DELETE FROM news_items; SELECT count(*) FROM tavily_calls")
        n_calls = cur.fetchone()[0]
    conn.commit()
    rt, rh = cn.ReplayTavily(tmp_path / "raw"), cn.ReplayHttp(tmp_path / "raw")
    summary = cn.run(conn, CLUBS, rt, now=NOW, raw_dir=tmp_path / "raw", http=rh, window=WINDOW, opponents=OPPONENTS,
                     aliases=cn.team_aliases(TEAMS), replay=True)
    with conn.cursor() as cur:
        cur.execute("SELECT guid, source, club, date_source, published_at, content_hash, headline FROM news_items ORDER BY guid")
        assert cur.fetchall() == before
        cur.execute("SELECT count(*) FROM tavily_calls")
        assert cur.fetchone()[0] == n_calls, "replay writes no ledger rows"
    assert summary["credits"] == 0 and summary["replay"] is True
    assert rh.requests == 0 and rt.network == 0, "replay touched the network"
    assert not hasattr(rt, "_key")


def test_no_request_ever_goes_to_a_non_club_domain():
    for bad in ("bbc.co.uk", "skysports.com", "theguardian.com", "www.bbc.co.uk"):
        with pytest.raises(AssertionError):
            cn.search_request("x", [bad])
    for dom in config_roles.CLUB_DOMAINS.values():
        assert cn.search_request("x", [dom])["include_domains"] == [dom]


def test_runner_gate_outside_window(conn, tmp_path, monkeypatch, capsys):
    import fetch_club_news as runner
    tv = FakeTavily(SEARCHES, EXTRACTS)
    monkeypatch.setattr(runner, "make_tavily", lambda: tv)
    monkeypatch.setattr(runner, "make_http", lambda raw_dir: FakeHttp(PAGES))
    monkeypatch.setattr(runner, "load_events", lambda: EVENTS)
    monkeypatch.setattr(runner, "load_teams", lambda: TEAMS)
    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sys, "argv", ["fetch_club_news.py", "--now", "2026-09-25T15:07:00Z"])
    with pytest.raises(SystemExit) as e:
        runner.main()
    assert e.value.code == 0 and tv.requests == []
    assert "outside window, next window opens 2026-10-07T10:00:00Z" in capsys.readouterr().out


def test_runner_inside_window_searches_the_nine_clubs_only(conn, tmp_path, monkeypatch):
    import fetch_club_news as runner
    tv = FakeTavily(SEARCHES, EXTRACTS)
    monkeypatch.setattr(runner, "make_tavily", lambda: tv)
    monkeypatch.setattr(runner, "make_http", lambda raw_dir: FakeHttp(PAGES))
    monkeypatch.setattr(runner, "load_events", lambda: EVENTS)
    monkeypatch.setattr(runner, "load_teams", lambda: TEAMS)
    monkeypatch.setattr(runner, "load_opponents", lambda gw, teams: OPPONENTS)
    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sys, "argv", ["fetch_club_news.py", "--now", "2026-09-17T15:07:00Z"])
    runner.main()
    assert len(tv.requests) == len(config_roles.CLUB_NEWS_CLUBS) == 9
    assert {d for r in tv.requests for d in r["include_domains"]} <= set(config_roles.CLUB_DOMAINS.values())
