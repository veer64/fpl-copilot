"""Piece 9, Part 2 (2026-10-01): the conflict log (conflict_log.py). Record and measure only (D9).
Pinned here:
  * every FPL and club status maps to its bucket as specified;
  * comparisons are built strictly as of the deadline: a claim fetched after it is ignored, a claim
    older than 7 days before it is ignored, the FPL state is the newest raw snapshot at or before it,
    the newest claim per player wins, and a rebuild gives identical rows;
  * outcomes and right_source for all nine bucket/outcome combinations;
  * update_conflict_log builds every passed deadline once, fills outcomes when results exist, is
    idempotent, and never writes to players_live or any model table.
Needs a local Postgres (skips loudly without one).
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
import config_roles  # noqa: E402
import news_store as ns  # noqa: E402
import relevance as rv  # noqa: E402
import conflict_log as cl  # noqa: E402

UTC = timezone.utc
TEST_DB = "fpl_news_test"
DROP_ALL = ("DROP TABLE IF EXISTS availability_comparisons; DROP TABLE IF EXISTS availability_claims; "
            "DROP TABLE IF EXISTS availability_extractions; DROP TABLE IF EXISTS citation_checks; DROP TABLE IF EXISTS search_log; "
            "DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; "
            "DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; "
            "DROP TABLE IF EXISTS news_relevance; DROP TABLE IF EXISTS llm_calls; "
            "DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")

D5 = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)
D6 = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
EVENTS = [{"id": 4, "deadline_time": "2026-09-12T12:30:00Z"}, {"id": 5, "deadline_time": "2026-09-18T17:30:00Z"},
          {"id": 6, "deadline_time": "2026-10-10T10:00:00Z"}]
TEAMS = [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 6, "name": "Chelsea", "short_name": "CHE"}]


def el(i, web, team, status, chance):
    return {"id": i, "web_name": web, "first_name": web, "second_name": web, "team": team, "status": status,
            "chance_of_playing_next_round": chance}


def boot(ts, elements):
    return (ts, {"elements": elements, "teams": TEAMS, "events": EVENTS})


# snapshots: Saka fit on the 16th, doubtful on the 18th at 09:00 (the newest at or before the GW5 deadline),
# available again on the 19th (after the deadline, must be ignored for GW5); Palmer out throughout
SNAPS = rv.Snapshots([
    boot(datetime(2026, 9, 16, 9, 0, tzinfo=UTC), [el(1, "Saka", 1, "a", None), el(3, "Palmer", 6, "i", 0), el(8, "Caicedo", 6, "a", None)]),
    boot(datetime(2026, 9, 18, 9, 0, tzinfo=UTC), [el(1, "Saka", 1, "d", 75), el(3, "Palmer", 6, "i", 0), el(8, "Caicedo", 6, "a", None)]),
    boot(datetime(2026, 9, 19, 9, 0, tzinfo=UTC), [el(1, "Saka", 1, "a", None), el(3, "Palmer", 6, "a", None), el(8, "Caicedo", 6, "a", None)]),
])


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


def add_claim(conn, element_id, status, fetched, *, published=None, headline=None, basis="report", evidence="x", return_hint=None, club="Arsenal"):
    headline = headline or f"item {element_id} {fetched:%Y%m%d%H%M}"
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, headline, body, published_at, fetched_at, content_hash, raw_ref, club, date_source) "
                    "VALUES ('club', %s, 1, %s, 'body', %s, %s, %s, 'test', %s, 'first_seen') RETURNING id",
                    (f"club:{headline}", headline, published, fetched, ns.content_hash(headline, fetched), club))
        item = cur.fetchone()[0]
        cur.execute("INSERT INTO availability_claims (news_item_id, element_id, status, return_hint, basis, evidence, prompt_version, model, "
                    "item_fetched_at, item_published_at) VALUES (%s, %s, %s, %s, %s, %s, 'extract_v1', %s, %s, %s) RETURNING id",
                    (item, element_id, status, return_hint, basis, evidence, config_roles.RELEVANCE_MODEL, fetched, published))
        cid = cur.fetchone()[0]
    conn.commit()
    return cid


def rows(conn, gw=5):
    with conn.cursor() as cur:
        cur.execute("SELECT gw, deadline, element_id, fpl_status, fpl_chance_next_round, fpl_snapshot_time, claim_id, club_status, "
                    "claim_published_at, claim_fetched_at, bucket_fpl, bucket_club, agree, minutes, started, played, right_source "
                    "FROM availability_comparisons WHERE gw = %s ORDER BY element_id", (gw,))
        return cur.fetchall()


# ---- buckets ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status,bucket", [("a", "FIT"), ("d", "DOUBT"), ("i", "OUT"), ("s", "OUT"), ("u", "OUT"), ("n", "OUT")])
def test_fpl_buckets(status, bucket):
    assert cl.bucket_fpl(status) == bucket


@pytest.mark.parametrize("status,bucket", [("available", "FIT"), ("doubtful", "DOUBT"), ("returning", "DOUBT"), ("out", "OUT"), ("suspended", "OUT")])
def test_club_buckets(status, bucket):
    assert cl.bucket_club(status) == bucket


def test_unknown_statuses_have_no_bucket():
    assert cl.bucket_fpl("x") is None and cl.bucket_club("injured") is None


# ---- comparisons as of the deadline ---------------------------------------------------------------------------------

def test_comparisons_are_built_as_of_the_deadline_with_the_7_day_window(conn):
    old = add_claim(conn, 1, "out", D5 - timedelta(days=7, hours=1))               # outside the window: ignored
    first = add_claim(conn, 1, "doubtful", D5 - timedelta(days=2))                 # inside, older
    newest = add_claim(conn, 1, "available", D5 - timedelta(hours=3), published=D5 - timedelta(hours=5))   # the newest at or before
    late = add_claim(conn, 1, "out", D5 + timedelta(minutes=1))                    # after the deadline: ignored
    palmer = add_claim(conn, 3, "returning", D5 - timedelta(days=1), club="Chelsea")
    n = cl.build_comparisons(conn, 5, D5, SNAPS)
    got = rows(conn)
    assert n == 2 and [r[2] for r in got] == [1, 3]
    saka, palmer_row = got
    assert saka[:4] == (5, D5, 1, "d") and saka[4] == 75 and saka[5] == datetime(2026, 9, 18, 9, 0, tzinfo=UTC)   # the 18th 09:00 snapshot, not the 19th
    assert saka[6] == newest and saka[7] == "available" and saka[8] == D5 - timedelta(hours=5) and saka[9] == D5 - timedelta(hours=3)
    assert saka[10:13] == ("DOUBT", "FIT", False)
    assert palmer_row[3] == "i" and palmer_row[6] == palmer and palmer_row[10:13] == ("OUT", "DOUBT", False)
    assert all(r[13] is None and r[16] is None for r in got)                       # no outcome yet
    # rebuild gives identical rows
    with conn.cursor() as cur:
        cur.execute("DELETE FROM availability_comparisons WHERE gw = 5")
    conn.commit()
    cl.build_comparisons(conn, 5, D5, SNAPS)
    assert rows(conn) == got
    assert cl.build_comparisons(conn, 5, D5, SNAPS) == 0 and rows(conn) == got      # building again adds nothing


def test_a_player_without_a_claim_in_the_window_has_no_row(conn):
    add_claim(conn, 8, "available", D5 - timedelta(days=10), club="Chelsea")
    assert cl.build_comparisons(conn, 5, D5, SNAPS) == 0 and rows(conn) == []


def test_a_player_missing_from_the_snapshot_has_no_row(conn):
    add_claim(conn, 999, "out", D5 - timedelta(days=1))
    assert cl.build_comparisons(conn, 5, D5, SNAPS) == 0


# ---- outcomes and right_source --------------------------------------------------------------------------------------

@pytest.mark.parametrize("bf,bc,played,expect", [
    ("FIT", "FIT", True, "tie"), ("FIT", "DOUBT", True, "fpl"), ("FIT", "OUT", True, "fpl"),
    ("DOUBT", "FIT", True, "club"), ("DOUBT", "DOUBT", True, "tie"), ("DOUBT", "OUT", True, "fpl"),
    ("OUT", "FIT", True, "club"), ("OUT", "DOUBT", True, "club"), ("OUT", "OUT", True, "tie"),
    ("FIT", "FIT", False, "tie"), ("FIT", "DOUBT", False, "club"), ("FIT", "OUT", False, "club"),
    ("DOUBT", "FIT", False, "fpl"), ("DOUBT", "DOUBT", False, "tie"), ("DOUBT", "OUT", False, "club"),
    ("OUT", "FIT", False, "fpl"), ("OUT", "DOUBT", False, "fpl"), ("OUT", "OUT", False, "tie"),
])
def test_right_source_all_combinations(bf, bc, played, expect):
    assert cl.right_source(bf, bc, played) == expect


def test_fill_outcomes_sets_minutes_started_played_and_right_source(conn):
    add_claim(conn, 1, "available", D5 - timedelta(hours=3))                       # FPL DOUBT vs club FIT
    add_claim(conn, 3, "returning", D5 - timedelta(days=1), club="Chelsea")        # FPL OUT vs club DOUBT
    cl.build_comparisons(conn, 5, D5, SNAPS)
    n = cl.fill_outcomes(conn, 5, {1: {"minutes": 90, "started": True}, 3: {"minutes": 0, "started": False}})
    assert n == 2
    saka, palmer = rows(conn)
    assert saka[13:17] == (90, True, True, "club")                                 # played: FIT beats DOUBT
    assert palmer[13:17] == (0, False, False, "fpl")                               # not played: OUT beats DOUBT
    assert cl.fill_outcomes(conn, 5, {1: {"minutes": 90, "started": True}}) == 0   # already filled: nothing rewritten


# ---- update_conflict_log --------------------------------------------------------------------------------------------

def test_update_conflict_log_builds_passed_deadlines_fills_outcomes_and_never_touches_model_tables(conn):
    db_write.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM players_live")
        cur.execute("INSERT INTO players_live (element, name, position, team, price_tenths, status, chance, news, updated_at) "
                    "VALUES (1, 'Bukayo Saka', 'MID', 'Arsenal', 100, 'a', NULL, '', %s)", (D5,))
    conn.commit()

    def counts():
        with conn.cursor() as cur:
            cur.execute("SELECT (SELECT count(*) FROM players_live), (SELECT max(updated_at) FROM players_live), "
                        "(SELECT count(*) FROM model_predictions), (SELECT count(*) FROM model_runs), (SELECT count(*) FROM model_picks)")
            return cur.fetchone()
    before = counts()
    add_claim(conn, 1, "available", D5 - timedelta(hours=3))
    results = {}
    log = []
    out = cl.update_conflict_log(conn, snapshots=SNAPS, events=EVENTS, results_loader=lambda gw: results.get(gw),
                                 now=datetime(2026, 9, 20, tzinfo=UTC), log=log.append)
    assert out["built"] == {5: 1} and out["filled"] == {} and rows(conn)[0][13] is None       # GW4 has no claims, GW6 is in the future
    results[5] = {1: {"minutes": 90, "started": True}}
    out2 = cl.update_conflict_log(conn, snapshots=SNAPS, events=EVENTS, results_loader=lambda gw: results.get(gw),
                                  now=datetime(2026, 9, 20, tzinfo=UTC), log=log.append)
    assert out2["built"] == {} and out2["filled"] == {5: 1} and rows(conn)[0][16] == "club"
    out3 = cl.update_conflict_log(conn, snapshots=SNAPS, events=EVENTS, results_loader=lambda gw: results.get(gw),
                                  now=datetime(2026, 9, 20, tzinfo=UTC), log=log.append)
    assert out3["built"] == {} and out3["filled"] == {}
    assert counts() == before                                                      # players_live and the model tables untouched


def test_results_loader_reads_the_history_parquet(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"element": [1, 1, 3], "GW": [5, 5, 5], "minutes": [45, 45, 0], "starts": [1.0, 0.0, 0.0]})
    p = tmp_path / "fpl_api_2026_27.parquet"
    df.to_parquet(p)
    assert cl.results_for_gw(5, path=p) == {1: {"minutes": 90, "started": True}, 3: {"minutes": 0, "started": False}}   # double gameweek summed
    assert cl.results_for_gw(6, path=p) is None
    assert cl.results_for_gw(5, path=tmp_path / "missing.parquet") is None
