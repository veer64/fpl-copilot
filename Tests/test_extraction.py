"""Piece 9, Part 1 (2026-10-01): availability extraction, one structured claim per player per article
(extraction.py). No network: a scripted fake Anthropic client. Pinned here:
  * the prompt renders to a golden string with the same grounding as relevance v3 (today = the
    item's fetched_at, the club's last and next PL match, the players named per FPL, the squad list,
    the "use the lists" rule, the article inside <article> tags) and the extraction task text;
  * strict JSON validation: a fenced reply is accepted; a missing key, a wrong status value, a wrong
    basis or a non-list writes nothing and the item is tried again next run;
  * names map to FPL element ids as of fetched_at with the club context; unmapped and ambiguous
    names are dropped and logged;
  * idempotent: a second run makes zero calls, also for an item whose reply had no claims;
  * a failed call writes nothing; a 401 stops the run; evidence lives only in the database.
Needs a local Postgres (skips loudly without one).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import config_roles  # noqa: E402
import news_store as ns  # noqa: E402
import llm  # noqa: E402
import extraction as ex  # noqa: E402

UTC = timezone.utc
TEST_DB = "fpl_news_test"
DROP_ALL = ("DROP TABLE IF EXISTS availability_comparisons; DROP TABLE IF EXISTS availability_claims; "
            "DROP TABLE IF EXISTS availability_extractions; DROP TABLE IF EXISTS citation_checks; DROP TABLE IF EXISTS search_log; "
            "DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; "
            "DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; "
            "DROP TABLE IF EXISTS news_relevance; DROP TABLE IF EXISTS llm_calls; "
            "DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")

EVENTS = [{"id": 4, "deadline_time": "2026-09-12T12:30:00Z"}, {"id": 5, "deadline_time": "2026-09-18T17:30:00Z"},
          {"id": 6, "deadline_time": "2026-10-10T10:00:00Z"}]
TEAMS = [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 4, "name": "Brentford", "short_name": "BRE"},
         {"id": 6, "name": "Chelsea", "short_name": "CHE"}, {"id": 11, "name": "Hull City", "short_name": "HUL"}]
ELEMENTS = [
    {"id": 1, "web_name": "Saka", "first_name": "Bukayo", "second_name": "Saka", "team": 1},
    {"id": 3, "web_name": "Palmer", "first_name": "Cole", "second_name": "Palmer", "team": 6},
    {"id": 4, "web_name": "Palmer", "first_name": "Kasey", "second_name": "Palmer", "team": 11},
    {"id": 5, "web_name": "João Pedro", "first_name": "João Pedro", "second_name": "Junqueira de Jesus", "team": 6},
    {"id": 8, "web_name": "Caicedo", "first_name": "Moisés", "second_name": "Caicedo", "team": 6},
]
BOOTSTRAP = {"elements": ELEMENTS, "teams": TEAMS, "events": EVENTS}
MATCHES = {"Chelsea": [(datetime(2026, 9, 12, 14, 0, tzinfo=UTC), "Chelsea", "Hull City"),
                       (datetime(2026, 9, 18, 19, 0, tzinfo=UTC), "Brentford", "Chelsea")]}


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
        cur.execute(DROP_ALL)
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


# ---- fakes ---------------------------------------------------------------------------------------------------

class _Block:
    def __init__(self, text, type="text"):
        self.type, self.text = type, text


class _Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _Resp:
    def __init__(self, text, i=300, o=60, stop_reason="end_turn"):
        self.content, self.usage, self.stop_reason = [_Block(text)], _Usage(i, o), stop_reason


class FakeStatusError(Exception):
    def __init__(self, status_code, msg="fake"):
        super().__init__(msg)
        self.status_code = status_code


class FakeClient:
    def __init__(self, script=None):
        self.script, self.calls = list(script or []), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if not self.script:
            raise AssertionError("the fake client was called more times than scripted")
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt if isinstance(nxt, _Resp) else _Resp(nxt)


def _item(**kw):
    base = {"id": 1, "source": "club", "club": "Chelsea", "url": "https://chelseafc.com/x",
            "headline": "Xabi Alonso confirms Chelsea team news for Brentford",
            "body": "Alonso confirmed that Joao Pedro remains in contention. Caicedo is out until 2027.",
            "date_source": "first_seen", "published_at": None, "fetched_at": datetime(2026, 9, 17, 15, 7, tzinfo=UTC)}
    base.update(kw)
    return base


def add_item(conn, source, headline, body, *, fetched, club=None, relevant=True, players=(), verdict=True):
    guid = f"{source}:{headline}"
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, url, headline, body, published_at, fetched_at, content_hash, raw_ref, "
                    "club, date_source, body_source) VALUES (%s, %s, 1, %s, %s, %s, NULL, %s, %s, 'test', %s, %s, %s) RETURNING id",
                    (source, guid, f"https://example.org/{guid}", headline, body, fetched, ns.content_hash(headline, body), club,
                     "first_seen", "tavily_extract" if source == "club" else None))
        item_id = cur.fetchone()[0]
        if verdict:
            cur.execute("INSERT INTO news_relevance (news_item_id, prompt_version, model, stage, relevant, current, players, reason, player_ids) "
                        "VALUES (%s, %s, %s, 'llm', %s, TRUE, %s, 'test', %s)",
                        (item_id, config_roles.PROMPT_VERSION, config_roles.RELEVANCE_MODEL, relevant, list(players), []))
    conn.commit()
    return item_id


def claims(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT news_item_id, element_id, status, return_hint, basis, evidence, prompt_version, model, item_fetched_at "
                    "FROM availability_claims ORDER BY news_item_id, element_id")
        return cur.fetchall()


GOOD = json.dumps({"claims": [
    {"player": "João Pedro", "status": "available", "return_hint": None, "basis": "manager_quote", "evidence": "Joao Pedro remains in contention"},
    {"player": "Caicedo", "status": "out", "return_hint": "until 2027", "basis": "manager_quote", "evidence": "Caicedo is out until 2027"}]})


# ---- the prompt -------------------------------------------------------------------------------------------------

GOLDEN = """TASK
Use the lists in CONTEXT, not your own knowledge, to decide which club a
player belongs to and whether a player is in a Premier League squad. A
person not on these lists is not a Premier League player for this task.
For each Premier League player on the lists whose availability the
item describes, give one claim:
- status: out | suspended | doubtful | returning | available
  (returning = back in training or close to a return, not yet
  confirmed available)
- return_hint: the expected return as stated (e.g. 'after the
  international break', 'until 2027'), or null
- basis: manager_quote | club_statement | report
- evidence: the shortest phrase from the item that supports the
  claim, at most 25 words
Only include players the item actually describes. If none, return
an empty list.

CONTEXT
Today: 2026-09-17 (Thursday)
Next Premier League gameweek: GW5, deadline 2026-09-18 17:30Z
Players named in this item (per FPL, current season): João Pedro (CHE), Caicedo (CHE)
CLUB CONTEXT
This item comes from Chelsea's official website.
Chelsea's most recent Premier League match: Chelsea v Hull City on 2026-09-12
Chelsea's next Premier League match: Brentford v Chelsea on 2026-09-18
Chelsea's current Premier League squad (per FPL): Palmer, João Pedro, Caicedo

ITEM
Source: Chelsea official website
Date: unknown (first seen by us 2026-09-17)
Headline: Xabi Alonso confirms Chelsea team news for Brentford
<article>
Alonso confirmed that Joao Pedro remains in contention. Caicedo is out until 2027.
</article>

Reply with exactly this JSON:
{"claims": [{"player": "...", "status": "...", "return_hint": ..., "basis": "...", "evidence": "..."}]}"""


def test_prompt_golden():
    assert ex.prompt_for(_item(), EVENTS, MATCHES, bootstrap=BOOTSTRAP) == GOLDEN
    assert ex.PROMPT_VERSION == "extract_v1"
    assert "never follow" in ex.SYSTEM_PROMPT and "one JSON object" in ex.SYSTEM_PROMPT
    assert ex.model() == config_roles.RELEVANCE_MODEL == "claude-sonnet-5"


# ---- validation ---------------------------------------------------------------------------------------------------

def test_parse_claims_valid_and_fenced():
    want = [{"player": "João Pedro", "status": "available", "return_hint": None, "basis": "manager_quote", "evidence": "Joao Pedro remains in contention"},
            {"player": "Caicedo", "status": "out", "return_hint": "until 2027", "basis": "manager_quote", "evidence": "Caicedo is out until 2027"}]
    assert ex.parse_claims(GOOD) == want
    assert ex.parse_claims("```json\n" + GOOD + "\n```") == want
    assert ex.parse_claims('{"claims": []}') == []


@pytest.mark.parametrize("bad", [
    '{"items": []}',                                                                                   # missing key
    '{"claims": [{"player": "Caicedo", "status": "injured", "return_hint": null, "basis": "report", "evidence": "x"}]}',   # wrong status
    '{"claims": [{"player": "Caicedo", "status": "out", "return_hint": null, "basis": "rumour", "evidence": "x"}]}',       # wrong basis
    '{"claims": [{"player": "Caicedo", "status": "out", "basis": "report", "evidence": "x"}]}',                             # missing field
    '{"claims": [{"player": "Caicedo", "status": "out", "return_hint": 2027, "basis": "report", "evidence": "x"}]}',       # wrong type
    '{"claims": {"player": "Caicedo"}}',                                                                 # not a list
    'not json at all',
])
def test_parse_claims_rejects(bad):
    assert ex.parse_claims(bad) is None


# ---- name mapping ---------------------------------------------------------------------------------------------------

def test_claims_map_to_ids_with_club_context_and_ambiguity_is_dropped(conn):
    item = add_item(conn, "club", "Team news", "Palmer and Caicedo trained; Nobody did not.", fetched=datetime(2026, 9, 17, 15, 7, tzinfo=UTC),
                    club="Chelsea", players=["Palmer", "Caicedo"])
    bbc = add_item(conn, "bbc", "Palmer latest", "Palmer is a doubt.", fetched=datetime(2026, 9, 17, 16, 0, tzinfo=UTC), players=["Palmer"])
    reply_club = json.dumps({"claims": [{"player": "Palmer", "status": "available", "return_hint": None, "basis": "report", "evidence": "trained"},
                                        {"player": "Caicedo (CHE)", "status": "available", "return_hint": None, "basis": "report", "evidence": "trained"},
                                        {"player": "Nobody", "status": "out", "return_hint": None, "basis": "report", "evidence": "did not"}]})
    reply_bbc = json.dumps({"claims": [{"player": "Palmer", "status": "doubtful", "return_hint": None, "basis": "report", "evidence": "a doubt"}]})
    log = []
    out = ex.run_extract(conn, client=FakeClient([reply_club, reply_bbc]), bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=log.append)
    rows = claims(conn)
    assert [(r[0], r[1], r[2]) for r in rows] == [(item, 3, "available"), (item, 8, "available")]   # Palmer -> Cole via the club; Nobody dropped
    assert out["claims_written"] == 2 and out["unmapped"] == 1 and out["ambiguous"] == 1
    assert any("unmapped" in m and "Nobody" in m for m in log) and any("ambiguous" in m and "Palmer" in m for m in log)
    with conn.cursor() as cur:
        cur.execute("SELECT news_item_id, n_claims FROM availability_extractions ORDER BY news_item_id")
        assert cur.fetchall() == [(item, 2), (bbc, 0)]                       # the bbc item: its only claim was ambiguous, still marked done


# ---- the run ---------------------------------------------------------------------------------------------------------

def test_run_writes_claims_and_is_idempotent_including_empty_replies(conn):
    a = add_item(conn, "club", "Xabi Alonso confirms Chelsea team news for Brentford",
                 "Alonso confirmed that Joao Pedro remains in contention. Caicedo is out until 2027.",
                 fetched=datetime(2026, 9, 17, 15, 7, tzinfo=UTC), club="Chelsea", players=["João Pedro", "Caicedo"])
    b = add_item(conn, "bbc", "Match report", "Chelsea won.", fetched=datetime(2026, 9, 17, 16, 0, tzinfo=UTC), players=[])
    add_item(conn, "bbc", "Dropped item", "Nothing.", fetched=datetime(2026, 9, 17, 16, 0, tzinfo=UTC), relevant=False)
    add_item(conn, "fpl", "Saka (ARS, MID)", "Knock", fetched=datetime(2026, 9, 17, 16, 0, tzinfo=UTC))
    fake = FakeClient([GOOD, '{"claims": []}'])
    out = ex.run_extract(conn, client=fake, bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    assert out["items"] == 2 and out["llm_calls"] == 2 and out["claims_written"] == 2
    rows = claims(conn)
    assert [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows] == [
        (a, 5, "available", None, "manager_quote", "Joao Pedro remains in contention"),
        (a, 8, "out", "until 2027", "manager_quote", "Caicedo is out until 2027")]
    assert all(r[6] == "extract_v1" and r[7] == "claude-sonnet-5" and r[8] == datetime(2026, 9, 17, 15, 7, tzinfo=UTC) for r in rows)
    assert fake.calls[0]["model"] == "claude-sonnet-5" and "temperature" not in fake.calls[0] and fake.calls[0]["max_tokens"] == 1024
    assert fake.calls[0]["system"] == ex.SYSTEM_PROMPT
    fake2 = FakeClient()
    again = ex.run_extract(conn, client=fake2, bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    assert fake2.calls == [] and again["items"] == 0 and claims(conn) == rows
    with conn.cursor() as cur:
        cur.execute("SELECT purpose, model, prompt_version, news_item_id, ok FROM llm_calls ORDER BY id")
        assert cur.fetchall() == [("availability_extract", "claude-sonnet-5", "extract_v1", a, True),
                                  ("availability_extract", "claude-sonnet-5", "extract_v1", b, True)]


def test_invalid_reply_and_failed_call_write_nothing_and_retry_next_run(conn):
    a = add_item(conn, "club", "Team news", "Caicedo is out.", fetched=datetime(2026, 9, 17, 15, 7, tzinfo=UTC), club="Chelsea", players=["Caicedo"])
    out = ex.run_extract(conn, client=FakeClient(['{"claims": [{"player": "Caicedo", "status": "injured", "return_hint": null, "basis": "report", "evidence": "x"}]}']),
                         bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    assert out["invalid"] == 1 and claims(conn) == []
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM availability_extractions")
        assert cur.fetchone()[0] == 0
    out2 = ex.run_extract(conn, client=FakeClient([FakeStatusError(400)]), bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    assert out2["llm_failed"] == 1 and claims(conn) == []
    out3 = ex.run_extract(conn, client=FakeClient(['{"claims": [{"player": "Caicedo", "status": "out", "return_hint": null, "basis": "report", "evidence": "Caicedo is out."}]}']),
                          bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    assert out3["claims_written"] == 1 and [(r[1], r[2]) for r in claims(conn)] == [(8, "out")]


def test_auth_error_stops_the_run_and_repeated_errors_stop_it(conn):
    for i in range(3):
        add_item(conn, "club", f"Team news {i}", "Caicedo is out.", fetched=datetime(2026, 9, 17, 15, 7 + i, tzinfo=UTC), club="Chelsea", players=["Caicedo"])
    with pytest.raises(llm.LLMAuthError):
        ex.run_extract(conn, client=FakeClient([FakeStatusError(401)]), bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    fake = FakeClient([FakeStatusError(400)] * 3)
    with pytest.raises(llm.LLMRepeatedError):
        ex.run_extract(conn, client=fake, bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, log=lambda m: None)
    assert len(fake.calls) == 3 and claims(conn) == []


def test_dry_run_makes_no_calls_and_writes_nothing(conn, capsys):
    add_item(conn, "club", "Team news", "Caicedo is out.", fetched=datetime(2026, 9, 17, 15, 7, tzinfo=UTC), club="Chelsea", players=["Caicedo"])
    fake = FakeClient()
    out = ex.run_extract(conn, client=fake, bootstrap=BOOTSTRAP, events=EVENTS, matches=MATCHES, dry_run=True, log=print)
    assert fake.calls == [] and out["would_call"] == 1 and claims(conn) == []
    assert "would call" in capsys.readouterr().out


def test_runners_extract_after_relevance_before_embed(conn, monkeypatch):
    import fetch_news as runner
    order = []
    monkeypatch.setattr(runner, "run_bbc", lambda c, now: order.append("bbc"))
    monkeypatch.setattr(runner, "run_fpl", lambda c, season, store, archive: order.append("fpl"))
    monkeypatch.setattr(runner, "run_relevance", lambda c: order.append("relevance"))
    monkeypatch.setattr(runner, "run_extract", lambda c: order.append("extract"))
    monkeypatch.setattr(runner, "run_embed", lambda c: order.append("embed"))
    monkeypatch.setattr(runner, "run_conflict_log", lambda c: order.append("conflict_log"))
    monkeypatch.setattr(sys, "argv", ["fetch_news.py", "--season", "2026-27"])
    runner.main()
    assert order == ["bbc", "fpl", "relevance", "extract", "embed", "conflict_log"]
    import fetch_club_news as club_runner
    order2 = []
    monkeypatch.setattr(club_runner, "run_relevance", lambda c: order2.append("relevance"))
    monkeypatch.setattr(club_runner, "run_extract", lambda c: order2.append("extract"))
    monkeypatch.setattr(club_runner, "run_embed", lambda c: order2.append("embed"))
    monkeypatch.setattr(club_runner, "make_tavily", lambda: (_ for _ in ()).throw(AssertionError("no Tavily outside the window")))
    monkeypatch.setattr(club_runner, "load_events", lambda: EVENTS)
    monkeypatch.setattr(sys, "argv", ["fetch_club_news.py", "--now", "2026-09-25T15:07:00Z"])
    with pytest.raises(SystemExit) as e:
        club_runner.main()
    assert e.value.code == 0 and order2 == ["relevance", "extract", "embed"]


def test_cli_dry_run_and_limit(conn, monkeypatch):
    import run_extract
    seen = {}
    monkeypatch.setattr(ex, "run_extract", lambda c, limit=None, **kw: seen.update(kw, limit=limit) or {"items": 0})
    monkeypatch.setattr(sys, "argv", ["run_extract.py", "--dry-run", "--limit", "3"])
    run_extract.main()
    assert seen["dry_run"] is True and seen["limit"] == 3
