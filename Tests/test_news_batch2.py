"""News batch 2 (Prompt H, 2026-10-30): FPL-note dating by the last text change, club
duplicates stored as aliases, and the 7-day article-date rule for the conflict log.
Pinned here:
  * N2 an FPL note's date is when its TEXT last changed: a re-fetched, changed note takes the change date when FPL
    kept its old news_added (Nørgaard, 9 Oct); an unchanged re-fetch -- or a status / chance change with the same
    text -- keeps the old date; a bumped news_added and a first version keep FPL's own claim; a cleared flag is
    undated as before; the re-dating plan over stored rows finds exactly the rows the ingest rule would date
    differently, and applying it twice changes nothing;
  * N3 a club article whose cleaned body matches a same-club item from the last 14 days is stored as an alias (URL
    kept) of the first and never judged, extracted or embedded; the four Liverpool 7 Oct copies (1090 / 1091 / 1093 /
    1094, language copies of one page) group as 1 + 3 aliases; same headline with a different body stays separate
    and is listed as not merged; nothing is deleted;
  * N4 a claim counts for a gameweek only when its ARTICLE is dated within the 7 days before the deadline; older ->
    "too old to compare", listed, not scored; a duplicate's claims are skipped;
  * (N1, relevance v4, was BLOCKED after two red attempts and left out of this batch with its tests.)
Needs a local Postgres (skips loudly without one); its own database fpl_news_test.
"""
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import config_roles  # noqa: E402
import news_store as ns  # noqa: E402
import relevance as rv  # noqa: E402
import conflict_log as cl  # noqa: E402

UTC = timezone.utc
TEST_DB = "fpl_news_test"
DROP_ALL = ("DROP TABLE IF EXISTS availability_builds; DROP TABLE IF EXISTS availability_comparisons; DROP TABLE IF EXISTS availability_claims; "
            "DROP TABLE IF EXISTS availability_extractions; DROP TABLE IF EXISTS citation_checks; DROP TABLE IF EXISTS search_log; "
            "DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; "
            "DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; "
            "DROP TABLE IF EXISTS news_relevance; DROP TABLE IF EXISTS llm_calls; "
            "DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")


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


# ==== N2: FPL-note dating ==============================================================================================

def _doc(elements):
    return {"teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 7, "name": "Everton", "short_name": "EVE"}],
            "element_types": [{"id": 2, "singular_name_short": "DEF"}, {"id": 3, "singular_name_short": "MID"}],
            "events": [{"id": 8, "deadline_time": "2026-10-23T17:30:00Z", "finished": False}], "elements": elements}


def _el(i, web, team, et, status, chance, news, added):
    return {"id": i, "web_name": web, "team": team, "element_type": et, "status": status,
            "chance_of_playing_this_round": chance, "chance_of_playing_next_round": chance, "news": news, "news_added": added}


def _archive(tmp_path, snaps):
    d = tmp_path / "bootstrap_raw" / "2026-27"
    d.mkdir(parents=True)
    for ts, elements in snaps:
        (d / f"{ts:%Y%m%dT%H%M%SZ}.json.gz").write_bytes(gzip.compress(json.dumps(_doc(elements)).encode("utf-8")))
    return d


def _fpl(conn, guid):
    with conn.cursor() as cur:
        cur.execute("SELECT version, body, published_at, date_source, fetched_at, fpl_news_added FROM news_items "
                    "WHERE source = 'fpl' AND guid = %s ORDER BY version", (guid,))
        return cur.fetchall()


ADDED = "2026-08-15T20:00:06Z"
ADDED_DT = datetime(2026, 8, 15, 20, 0, 6, tzinfo=UTC)
# Nørgaard's real chain on the server (fpl:21): news_added stayed 15 Aug while the text changed three times
N1_ = datetime(2026, 8, 20, 14, 9, 56, tzinfo=UTC)
N2_ = datetime(2026, 8, 21, 18, 13, 53, tzinfo=UTC)
N3_ = datetime(2026, 9, 4, 13, 30, 7, tzinfo=UTC)
N4_ = datetime(2026, 10, 9, 16, 37, 6, tzinfo=UTC)
NORGAARD = [
    (N1_, [_el(21, "Nørgaard", 7, 3, "d", 25, "Unspecified injury - 25% chance of playing", ADDED)]),
    (N2_, [_el(21, "Nørgaard", 7, 3, "i", 0, "Unspecified injury - Unknown return date", ADDED)]),
    (N3_, [_el(21, "Nørgaard", 7, 3, "i", 0, "Groin injury - Unknown return date", ADDED)]),
    (N4_, [_el(21, "Nørgaard", 7, 3, "d", 50, "Groin injury - 50% chance of playing", ADDED)]),
]


def test_a_changed_note_takes_the_change_date_norgaard(conn, tmp_path):
    ns.derive_fpl(conn, _archive(tmp_path, NORGAARD), season="2026-27")
    v = _fpl(conn, "fpl:21")
    assert [r[0] for r in v] == [1, 2, 3, 4]
    assert v[0][2] == ADDED_DT and v[0][3] == "source_field", "the first version keeps FPL's own news_added"
    assert [r[2] for r in v[1:]] == [N2_, N3_, N4_], "each changed text is dated by the snapshot that first showed it"
    assert all(r[3] == "text_change" for r in v[1:])
    assert all(r[5] == ADDED_DT for r in v), "FPL's raw news_added is kept beside the date"
    assert v[3][2].date().isoformat() == "2026-10-09", "Nørgaard's 50% note moves to 9 Oct"


def test_an_unchanged_refetch_and_a_status_only_change_keep_the_old_date(conn, tmp_path):
    t1, t2, t3 = (datetime(2026, 9, 1, 12, tzinfo=UTC), datetime(2026, 9, 2, 12, tzinfo=UTC), datetime(2026, 9, 3, 12, tzinfo=UTC))
    snaps = [(t1, [_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)]),
             (t2, [_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)]),      # identical re-fetch
             (t3, [_el(6, "Saliba", 1, 2, "d", 50, "Knock - 75% chance of playing", ADDED)])]      # chance changed, same text
    ns.derive_fpl(conn, _archive(tmp_path, snaps), season="2026-27")
    v = _fpl(conn, "fpl:6")
    assert [r[0] for r in v] == [1, 2], "the identical re-fetch is no version; the chance change is"
    assert v[0][2] == ADDED_DT and v[1][2] == ADDED_DT and v[1][3] == "source_field", "same text, same date"


def test_a_bumped_news_added_is_kept(conn, tmp_path):
    t1, t2 = datetime(2026, 9, 1, 12, tzinfo=UTC), datetime(2026, 9, 2, 12, tzinfo=UTC)
    bumped = "2026-09-02T09:15:00Z"
    snaps = [(t1, [_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)]),
             (t2, [_el(6, "Saliba", 1, 2, "i", 0, "Hamstring injury - Unknown return date", bumped)])]
    ns.derive_fpl(conn, _archive(tmp_path, snaps), season="2026-27")
    v = _fpl(conn, "fpl:6")
    assert v[1][2] == datetime(2026, 9, 2, 9, 15, tzinfo=UTC) and v[1][3] == "source_field", "FPL bumped it: its own time stands"


def test_a_cleared_flag_stays_undated_and_a_reflag_with_the_old_news_added_is_dated_by_the_change(conn, tmp_path):
    t1, t2, t3 = (datetime(2026, 9, 1, 12, tzinfo=UTC), datetime(2026, 9, 2, 12, tzinfo=UTC), datetime(2026, 9, 3, 12, tzinfo=UTC))
    snaps = [(t1, [_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)]),
             (t2, [_el(6, "Saliba", 1, 2, "a", None, "", ADDED)]),
             (t3, [_el(6, "Saliba", 1, 2, "d", 75, "Knock - 75% chance of playing", ADDED)])]
    ns.derive_fpl(conn, _archive(tmp_path, snaps), season="2026-27")
    v = _fpl(conn, "fpl:6")
    assert v[1][1] == "" and v[1][2] is None and v[1][3] == "first_seen"
    assert v[2][2] == t3 and v[2][3] == "text_change", "back from cleared with FPL's old timestamp: dated by the snapshot"


def _insert_old_style(conn, guid, version, body, published, fetched, status="d", chance=75):
    """a row as the pre-N2 ingest stored it: published_at = FPL's news_added whatever the text did"""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, headline, body, published_at, fetched_at, content_hash, raw_ref, "
                    "element_id, status, chance, date_source) VALUES ('fpl', %s, %s, 'Nørgaard (EVE, MID)', %s, %s, %s, %s, 'test', 21, %s, %s, %s) "
                    "RETURNING id", (guid, version, body, published, fetched, ns.content_hash(status, body, chance), status, chance,
                                     "source_field" if published else "first_seen"))
        rid = cur.fetchone()[0]
    conn.commit()
    return rid


def test_the_redate_plan_finds_the_old_rows_and_applying_it_twice_changes_nothing(conn):
    ids = [_insert_old_style(conn, "fpl:21", 1, "Unspecified injury - 25% chance of playing", ADDED_DT, N1_, "d", 25),
           _insert_old_style(conn, "fpl:21", 2, "Unspecified injury - Unknown return date", ADDED_DT, N2_, "i", 0),
           _insert_old_style(conn, "fpl:21", 3, "Groin injury - Unknown return date", ADDED_DT, N3_, "i", 0),
           _insert_old_style(conn, "fpl:21", 4, "Groin injury - 50% chance of playing", ADDED_DT, N4_, "d", 50),
           _insert_old_style(conn, "fpl:21", 5, "", None, datetime(2026, 10, 11, 12, 37, 6, tzinfo=UTC), "a", 100)]
    plan = ns.fpl_redate_plan(conn)
    assert [p["id"] for p in plan] == ids[1:4]
    assert plan[-1]["new_published_at"] == N4_ and plan[-1]["old_published_at"] == ADDED_DT and plan[-1]["new_date_source"] == "text_change"
    got = ns.apply_fpl_redate(conn, plan)
    assert got["updated"] == 3
    assert [r[2] for r in _fpl(conn, "fpl:21")][:4] == [ADDED_DT, N2_, N3_, N4_]
    assert all(r[5] == ADDED_DT for r in _fpl(conn, "fpl:21")[:4]), "the raw news_added is kept in fpl_news_added"
    assert ns.fpl_redate_plan(conn) == [], "idempotent: a second plan is empty"


def test_the_embed_text_shows_the_change_date(conn, tmp_path):
    ns.derive_fpl(conn, _archive(tmp_path, NORGAARD), season="2026-27")
    with conn.cursor() as cur:
        cur.execute("SELECT embed_text FROM news_embed_text WHERE guid = 'fpl:21' ORDER BY version DESC LIMIT 1")
        text = cur.fetchone()[0]
    assert text.startswith("[FPL official | 2026-10-09 16:37Z] Nørgaard (EVE, MID)")


# ==== N3: club duplicates =============================================================================================

LIV = "Liverpool"
EN_BODY = ("NewsAndoni Iraola on season so far, Liverpool v Manchester City and injury latest\n"
           "Facebook Twitter Email WhatsApp LinkedIn Telegram\n"
           "Andoni Iraola has delivered an appraisal of Liverpool's start to the season and explained why his team needs to be "
           "'very, very good' against Manchester City.\n"
           "The Reds return from the extended international break by hosting the current Premier League leaders at Anfield on Sunday. "
           "Seven competitive matches into his reign as head coach, Iraola has been pleased with what he has seen from his squad so far "
           "but outlined where improvements can be made, and he gave the latest on the fitness of several first-team players.\n"
           "Facebook Twitter Email WhatsApp LinkedIn Telegram")
PT_BODY = ("NotíciasAndoni Iraola fala sobre a temporada até agora, Liverpool x Manchester City e as últimas lesões\n"
           "Andoni Iraola fez uma avaliação do início da temporada do Liverpool e explicou por que sua equipe precisa ser muito, muito boa "
           "contra o Manchester City. Os Reds retornam da longa pausa internacional ao receber os atuais líderes da Premier League em Anfield.")
PAGE_BODY = ("The Reds return from the extended international break by hosting the current Premier League leaders at Anfield on Sunday.\n"
             "Seven competitive matches into his reign as head coach, Iraola has been pleased with what he has seen from his squad so far "
             "but outlined where improvements can be made, and he gave the latest on the fitness of several first-team players.\n")
PATH = "/news/andoni-iraola-season-so-far-liverpool-v-manchester-city-and-injury-latest"
FETCH_7OCT = datetime(2026, 10, 8, 15, 7, 2, tzinfo=UTC)
PUB_7OCT = datetime(2026, 10, 7, 14, 59, 11, tzinfo=UTC)


def _club(conn, guid, url, headline, body, fetched, club=LIV, published=PUB_7OCT):
    ns.upsert_versions(conn, "club", [{"guid": guid, "url": url, "headline": headline, "body": body, "published_at": published,
                                       "fetched_at": fetched, "raw_ref": "test", "content_hash": ns.content_hash(headline, body),
                                       "club": club, "date_source": "meta"}])
    with conn.cursor() as cur:
        cur.execute("SELECT id, duplicate_of FROM news_items WHERE source = 'club' AND guid = %s", (guid,))
        return cur.fetchone()


def _liverpool_copies(conn):
    """the four rows exactly as the server holds them: legacy guids with the language segment, stored at one fetch"""
    rows = [("https://liverpoolfc.com" + PATH, "https://www.liverpoolfc.com" + PATH,
             "Andoni Iraola on season so far, Liverpool v Manchester City and injury", EN_BODY),
            ("https://liverpoolfc.com/pt" + PATH, "https://www.liverpoolfc.com/pt" + PATH,
             "Andoni Iraola fala sobre a temporada até agora, Liverpool x Manchester", PT_BODY),
            ("https://liverpoolfc.com/es" + PATH, "https://www.liverpoolfc.com/es" + PATH,
             "Andoni Iraola habla de la temporada hasta ahora, el ...", PAGE_BODY + "Share\nAndoni Iraola Manchester City Premier League"),
            ("https://liverpoolfc.com/fr" + PATH, "https://www.liverpoolfc.com/fr" + PATH,
             "Andoni Iraola parle de la saison écoulée, Liverpool contre ...", PAGE_BODY + "[Share] [FR]\nAndoni Iraola Manchester City Premier League")]
    return [_club(conn, g, u, h, b, FETCH_7OCT)[0] for g, u, h, b in rows]


def test_the_four_liverpool_copies_group_as_one_plus_three_aliases(conn):
    ids = _liverpool_copies(conn)
    report = ns.duplicate_groups(conn)
    assert len(report["merged"]) == 1
    g = report["merged"][0]
    assert g["first"] == ids[0] and g["aliases"] == ids[1:], "the English page (no language segment) is the first"
    assert g["kind"] == "language_copy"
    got = ns.apply_duplicates(conn, report)
    assert got["marked"] == 3
    with conn.cursor() as cur:
        cur.execute("SELECT id, duplicate_of, url FROM news_items WHERE source = 'club' ORDER BY id")
        rows = cur.fetchall()
    assert [(r[0], r[1]) for r in rows] == [(ids[0], None), (ids[1], ids[0]), (ids[2], ids[0]), (ids[3], ids[0])]
    assert all(r[2] for r in rows), "the alias keeps its URL; nothing is deleted"
    assert ns.duplicate_groups(conn)["merged"] == [], "applied: the next plan has nothing left to merge"


def test_a_new_copy_with_the_same_cleaned_body_is_stored_as_an_alias(conn):
    first = _club(conn, "https://liverpoolfc.com/news/a", "https://www.liverpoolfc.com/news/a", "Injury latest", EN_BODY, FETCH_7OCT)
    # the same article under another path, a day later: case, spacing and the share lines differ only
    copy_body = EN_BODY.replace("Facebook Twitter Email WhatsApp LinkedIn Telegram", "Share").upper().replace(" ", "  ")
    second = _club(conn, "https://liverpoolfc.com/news/mens/a", "https://www.liverpoolfc.com/news/mens/a", "Injury latest",
                   copy_body, FETCH_7OCT + timedelta(days=1))
    assert first[1] is None and second[1] == first[0]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM news_to_embed")
        assert second[0] not in {r[0] for r in cur.fetchall()}
    assert second[0] not in {it["id"] for it in rv.unjudged(conn, "relevance_v3", "m")}, "an alias is never judged"


def test_same_headline_different_body_stays_separate_and_is_listed(conn):
    a = _club(conn, "https://liverpoolfc.com/news/a", "https://www.liverpoolfc.com/news/a", "Injury latest", EN_BODY, FETCH_7OCT)
    b = _club(conn, "https://liverpoolfc.com/news/b", "https://www.liverpoolfc.com/news/b", "Injury latest",
              PAGE_BODY + "A different closing paragraph about the academy and the women's team schedule.", FETCH_7OCT + timedelta(days=2))
    assert b[1] is None
    report = ns.duplicate_groups(conn)
    assert report["merged"] == []
    assert [sorted(x["ids"]) for x in report["not_merged"]] == [sorted([a[0], b[0]])]


def test_no_alias_after_14_days_or_across_clubs(conn):
    a = _club(conn, "https://liverpoolfc.com/news/a", "https://www.liverpoolfc.com/news/a", "Injury latest", EN_BODY, FETCH_7OCT)
    late = _club(conn, "https://liverpoolfc.com/news/c", "https://www.liverpoolfc.com/news/c", "Injury latest", EN_BODY,
                 FETCH_7OCT + timedelta(days=15))
    other = _club(conn, "https://evertonfc.com/news/a", "https://www.evertonfc.com/news/a", "Injury latest", EN_BODY,
                  FETCH_7OCT + timedelta(days=1), club="Everton")
    assert late[1] is None and other[1] is None and a[1] is None


def test_a_short_or_empty_body_never_makes_an_alias(conn):
    _club(conn, "https://liverpoolfc.com/news/a", "https://www.liverpoolfc.com/news/a", "Team news", "Team news.", FETCH_7OCT)
    b = _club(conn, "https://liverpoolfc.com/news/b", "https://www.liverpoolfc.com/news/b", "Team news", "Team news.", FETCH_7OCT)
    _club(conn, "https://liverpoolfc.com/news/c", "https://www.liverpoolfc.com/news/c", "Link list", "", FETCH_7OCT)
    d = _club(conn, "https://liverpoolfc.com/news/d", "https://www.liverpoolfc.com/news/d", "Link list", "", FETCH_7OCT)
    assert b[1] is None and d[1] is None
    assert ns.body_fingerprint("", "x") is None and ns.body_fingerprint("Team news.", "x") is None


# ==== N4: the 7-day article-date rule =================================================================================

D8 = datetime(2026, 10, 23, 17, 30, tzinfo=UTC)
TEAMS = [{"id": 12, "name": "Liverpool", "short_name": "LIV"}]
SNAPS = rv.Snapshots([(datetime(2026, 10, 23, 17, 20, tzinfo=UTC), {
    "elements": [{"id": 401, "web_name": "Gravenberch", "first_name": "Ryan", "second_name": "Gravenberch", "team": 12, "status": "d",
                  "chance_of_playing_next_round": 75},
                 {"id": 402, "web_name": "Szoboszlai", "first_name": "Dominik", "second_name": "Szoboszlai", "team": 12, "status": "a",
                  "chance_of_playing_next_round": None}],
    "teams": TEAMS, "events": [{"id": 8, "deadline_time": "2026-10-23T17:30:00Z"}]})])


def _claim(conn, element_id, status, fetched, published, headline, duplicate_of=None):
    import extraction
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, headline, body, published_at, fetched_at, content_hash, raw_ref, club, "
                    "date_source, duplicate_of) VALUES ('club', %s, 1, %s, 'body', %s, %s, %s, 'test', 'Liverpool', %s, %s) RETURNING id",
                    (f"club:{headline}", headline, published, fetched, ns.content_hash(headline, fetched),
                     "meta" if published else "first_seen", duplicate_of))
        item = cur.fetchone()[0]
        cur.execute("INSERT INTO availability_claims (news_item_id, element_id, status, basis, evidence, prompt_version, model, "
                    "item_fetched_at, item_published_at) VALUES (%s, %s, %s, 'report', 'x', %s, %s, %s, %s) RETURNING id",
                    (item, element_id, status, extraction.PROMPT_VERSION, extraction.model(), fetched, published))
        cid = cur.fetchone()[0]
    conn.commit()
    return item, cid


def _rows(conn, gw=8):
    with conn.cursor() as cur:
        cur.execute("SELECT element_id, claim_id FROM availability_comparisons WHERE gw = %s ORDER BY element_id", (gw,))
        return cur.fetchall()


def test_a_claim_from_an_article_older_than_7_days_is_too_old_to_compare(conn):
    # Gravenberch: an 11 Oct article fetched on the 20th (inside the old fetch window) -- 12 days before the GW8 deadline
    _, old = _claim(conn, 401, "out", datetime(2026, 10, 20, 15, 7, tzinfo=UTC), datetime(2026, 10, 11, 9, 0, tzinfo=UTC), "Gravenberch 11 Oct")
    assert cl.build_comparisons(conn, 8, D8, SNAPS) == 0 and _rows(conn) == []
    too_old = cl.too_old_claims(conn, 8, D8)
    assert [(t["claim_id"], t["element_id"]) for t in too_old] == [(old, 401)]
    assert too_old[0]["article_date"] == datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def test_a_fresh_article_wins_over_an_older_article_fetched_later(conn):
    _, fresh = _claim(conn, 401, "doubtful", datetime(2026, 10, 20, 9, 0, tzinfo=UTC), datetime(2026, 10, 19, 12, 0, tzinfo=UTC), "fresh")
    _, stale = _claim(conn, 401, "out", datetime(2026, 10, 22, 9, 0, tzinfo=UTC), datetime(2026, 10, 10, 12, 0, tzinfo=UTC), "stale")
    assert cl.build_comparisons(conn, 8, D8, SNAPS) == 1
    assert _rows(conn) == [(401, fresh)]
    assert [t["claim_id"] for t in cl.too_old_claims(conn, 8, D8)] == [stale]


def test_an_undated_article_counts_by_its_fetch_time(conn):
    _, cid = _claim(conn, 402, "available", datetime(2026, 10, 21, 9, 0, tzinfo=UTC), None, "undated")
    assert cl.build_comparisons(conn, 8, D8, SNAPS) == 1 and _rows(conn) == [(402, cid)]


def test_a_duplicates_claims_are_skipped(conn):
    first, _ = _claim(conn, 402, "available", datetime(2026, 10, 21, 9, 0, tzinfo=UTC), datetime(2026, 10, 21, 8, 0, tzinfo=UTC), "first")
    _claim(conn, 401, "out", datetime(2026, 10, 21, 9, 0, tzinfo=UTC), datetime(2026, 10, 21, 8, 0, tzinfo=UTC), "copy", duplicate_of=first)
    assert cl.build_comparisons(conn, 8, D8, SNAPS) == 1 and [r[0] for r in _rows(conn)] == [402]
    assert cl.too_old_claims(conn, 8, D8) == []


def test_the_report_lists_too_old_claims_without_scoring_them(conn):
    sys.path.insert(0, str(REPO / "eval"))
    import availability_conflict_report as acr
    _claim(conn, 401, "out", datetime(2026, 10, 20, 15, 7, tzinfo=UTC), datetime(2026, 10, 11, 9, 0, tzinfo=UTC), "Gravenberch 11 Oct")
    assert cl.rebuild_gameweek(conn, 8, D8, SNAPS, results_loader=lambda gw: None) == 0
    text = acr.build_report(conn, 8)
    assert "Rows 0:" in text
    assert "## Too old to compare (not scored)" in text and "Gravenberch 11 Oct" in text and "2026-10-11" in text


# ==== N2 in search ==================================================================================================

def test_search_dates_a_text_change_note_by_its_published_at():
    """N2: a re-dated FPL note keeps its date in search (basis FPL), also on a later status-only version that carries it"""
    import news_search as nsr
    changed, seen_later = datetime(2026, 10, 9, 16, 37, tzinfo=UTC), datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    assert nsr.date_basis({"date_source": "text_change", "published_at": changed, "fetched_at": seen_later}) == (changed, "FPL")
