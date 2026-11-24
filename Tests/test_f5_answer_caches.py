"""Prompt F5 (24 Nov 2026): captain answers cheaper in CPU, every answer byte-identical (eval/reports/c_concurrency.md: ~0.9 s of
pure-Python CPU per captain turn, about half of it in captain_pick; one process, so simultaneous turns queue on the GIL).
The four costs C measured, and what this test pins:

  C1  the prediction rows the code-built answers' pool reads (_answer_pool: every row of the run, ~4,000 in production) -- read
      ONCE per run id and reused; a new run id (or another database) is a fresh read; players_live (prices, clubs) is still read
      every call; every call gets its OWN pool (captain_pick adds to it), so nothing one caller does reaches the next;
  C2  the fixture calendar (_answer_calendar: the forward skeleton + the club names from the newest bootstrap snapshot) -- built
      once per fixtures version: a changed skeleton file or a new snapshot is a fresh build; every call gets its own copy;
  C3  captain_pick's likely-range reads (one get_prediction per starter, 11) -- skipped when the run has no quantiles for the
      gameweek, which is exactly when every one of them comes back "not computed"; with quantiles they run as before;
  C4  row -> dict: the cached prediction rows keep only the five columns the pool uses (element, gw, e_points, p_start,
      p_60plus), as plain tuples.
Thread-safe: simultaneous first calls read once and all get the same answer. No model, no network; C3 uses the seeded pool."""
import gzip
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import draft_tools                                          # noqa: E402
import fixtures_tool as ft                                  # noqa: E402
import model_tools as mt                                    # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

def _reset():
    getattr(mt, "_reset_answer_caches", lambda: None)()          # (absent before F5: the failing-first run fails on its asserts)


T = datetime(2026, 11, 21, 10, 51, 24, tzinfo=timezone.utc)
LIVE = [{"element": 1, "name": "Ann One", "position": "MID", "team": "Arsenal", "price_tenths": 80},
        {"element": 2, "name": "Bob Two", "position": "FWD", "team": "Chelsea", "price_tenths": 95},
        {"element": 3, "name": "Cid Three", "position": "DEF", "team": "Fulham", "price_tenths": 45}]   # no prediction: never pooled


def _pred_rows(run_id):
    base = 1.0 if run_id == 7 else 2.0
    return [{"element": e, "gw": g, "e_points": base * e + g / 100, "p_start": 0.9, "p_60plus": None if e == 2 else 0.8}
            for e in (1, 2) for g in (12, 13)]


class FakeDB:
    """mt._q for the pool's two reads; counts the model_predictions reads (the one C1 caches)."""

    def __init__(self, delay=0.0):
        self.pred_reads, self.live, self.delay, self.lock = 0, [dict(r) for r in LIVE], delay, threading.Lock()

    def __call__(self, sql, params=()):
        if "FROM players_live" in sql:
            return [dict(r) for r in self.live]
        if "FROM model_predictions" in sql:
            with self.lock:
                self.pred_reads += 1
            time.sleep(self.delay)
            return [dict(r) for r in _pred_rows(params[0])]
        raise AssertionError(f"unexpected read: {sql}")


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(mt, "_q", fake)
    monkeypatch.setattr(mt, "_web_names", lambda: {1: "Ann"})
    _reset()
    yield fake
    _reset()


def _run(run_id):
    return {"run_id": run_id, "finished_at": T, "status": "SUCCESS"}


def test_c1_the_prediction_rows_are_read_once_per_run_id(db):
    first = mt._answer_pool(_run(7))
    second = mt._answer_pool(_run(7))
    assert db.pred_reads == 1
    assert first == second
    assert list(first) == [1, 2] and first[1]["name"] == "Ann" and first[2]["name"] == "Bob Two"
    assert first[1]["pts"] == {12: 1.12, 13: 1.13} and first[2]["p60"] == {12: None, 13: None}


def test_c1_a_new_run_id_is_a_fresh_read(db):
    mt._answer_pool(_run(7))
    newer = mt._answer_pool(_run(8))
    assert db.pred_reads == 2
    assert newer[1]["pts"] == {12: 2.12, 13: 2.13}               # run 8's rows, never run 7's


def test_c1_the_same_run_id_rebuilt_is_a_fresh_read(db):
    mt._answer_pool(_run(7))
    mt._answer_pool({**_run(7), "finished_at": datetime(2026, 11, 24, 21, 22, 22, tzinfo=timezone.utc)})
    assert db.pred_reads == 2                                     # same id, another build (a restored or reseeded database)


def test_c1_another_database_is_a_fresh_read(db, monkeypatch):
    mt._answer_pool(_run(7))
    monkeypatch.setenv("DB_NAME", "fpl_other_test")
    mt._answer_pool(_run(7))
    assert db.pred_reads == 2


def test_c1_players_live_is_still_read_every_call(db):
    mt._answer_pool(_run(7))
    db.live[1]["price_tenths"] = 96                               # a price change between two builds
    assert mt._answer_pool(_run(7))[2]["price_tenths"] == 96


def test_c1_every_call_gets_its_own_pool(db):
    p = mt._answer_pool(_run(7))
    p[1]["pts"][12] = 99.0
    p[1]["name"] = "changed"
    p[42] = {"element": 42}                                       # captain_pick adds owned players the build has no row for
    q = mt._answer_pool(_run(7))
    assert q[1]["pts"][12] == 1.12 and q[1]["name"] == "Ann" and 42 not in q


def test_c1_simultaneous_first_calls_read_once(monkeypatch):
    fake = FakeDB(delay=0.05)
    monkeypatch.setattr(mt, "_q", fake)
    monkeypatch.setattr(mt, "_web_names", lambda: {})
    _reset()
    out, start = [None] * 8, threading.Barrier(8)

    def one(i):
        start.wait()
        out[i] = mt._answer_pool(_run(7))
    ths = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    _reset()
    assert fake.pred_reads == 1
    assert all(o == out[0] for o in out) and len({id(o) for o in out}) == 8


def test_c4_the_cached_rows_are_five_column_tuples(db):
    mt._answer_pool(_run(7))
    (rows,) = mt._PRED_ROWS.values()
    assert all(isinstance(r, tuple) and len(r) == 5 for r in rows) and len(rows) == 4


# ---- C2: the fixture calendar --------------------------------------------------------------------------------------------

def _snapshot(path, names):
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"teams": [{"id": i, "name": n} for i, n in names.items()]}, fh)


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    skel = tmp_path / "forward_skeleton.parquet"
    pd.DataFrame([dict(element=1, GW=12, team="Arsenal", opponent_team=2, was_home=True, kickoff_time="2026-11-28T15:00:00Z"),
                  dict(element=2, GW=12, team="Chelsea", opponent_team=1, was_home=False, kickoff_time="2026-11-28T15:00:00Z")]) \
        .to_parquet(skel, index=False)
    boot = tmp_path / "bootstrap"
    boot.mkdir()
    _snapshot(boot / "2026-11-24T18-00-00Z.json.gz", {1: "Arsenal", 2: "Chelsea"})
    monkeypatch.setattr(ft, "SKELETON", skel)
    monkeypatch.setattr(ft, "BOOTSTRAP_DIR", boot)
    builds = []
    real = ft.calendar

    def counted(*a, **k):
        builds.append(1)
        return real(*a, **k)
    monkeypatch.setattr(ft, "calendar", counted)
    _reset()
    yield skel, boot, builds
    _reset()


def test_c2_the_calendar_is_built_once_per_fixtures_version(fixtures):
    _skel, _boot, builds = fixtures
    a = mt._answer_calendar()
    b = mt._answer_calendar()
    assert len(builds) == 1
    assert a == b == {("Arsenal", 12): [{"opponent": "Chelsea", "opponent_id": 2, "home": True, "kickoff": "2026-11-28T15:00:00Z"}],
                      ("Chelsea", 12): [{"opponent": "Arsenal", "opponent_id": 1, "home": False, "kickoff": "2026-11-28T15:00:00Z"}]}


def test_c2_a_changed_skeleton_is_a_fresh_build(fixtures):
    skel, _boot, builds = fixtures
    mt._answer_calendar()
    st = skel.stat()
    os.utime(skel, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))    # the ingest rewrote the skeleton
    mt._answer_calendar()
    assert len(builds) == 2


def test_c2_a_new_snapshot_is_a_fresh_build_with_its_names(fixtures):
    _skel, boot, builds = fixtures
    mt._answer_calendar()
    _snapshot(boot / "2026-11-25T00-00-00Z.json.gz", {1: "Arsenal FC", 2: "Chelsea FC"})
    st = boot.stat()
    os.utime(boot, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))    # coarse-clock file systems: the folder changed
    cal = mt._answer_calendar()
    assert len(builds) == 2 and cal[("Arsenal", 12)][0]["opponent"] == "Chelsea FC"


def test_c2_the_newest_snapshot_rewritten_in_place_is_a_fresh_build(fixtures):
    _skel, boot, builds = fixtures
    mt._answer_calendar()
    snap = boot / "2026-11-24T18-00-00Z.json.gz"
    _snapshot(snap, {1: "Arsenal", 2: "Chelsea London"})
    st = snap.stat()
    os.utime(snap, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert mt._answer_calendar()[("Arsenal", 12)][0]["opponent"] == "Chelsea London" and len(builds) == 2


def test_c2_every_call_gets_its_own_calendar(fixtures):
    a = mt._answer_calendar()
    a[("Arsenal", 12)][0]["opponent"] = "changed"
    a[("Arsenal", 12)].append({"opponent": "extra"})
    a[("Nobody", 1)] = []
    b = mt._answer_calendar()
    assert b[("Arsenal", 12)] == [{"opponent": "Chelsea", "opponent_id": 2, "home": True, "kickoff": "2026-11-28T15:00:00Z"}]
    assert ("Nobody", 1) not in b


def test_c2_no_skeleton_reads_not_known_and_is_not_kept(fixtures):
    skel, _boot, builds = fixtures
    skel.unlink()
    assert mt._answer_calendar() is None                          # "not known", never "no fixture" -- as before
    assert mt._answer_calendar() is None and len(builds) == 0     # (the read fails before a build)


# ---- C3: captain_pick's likely-range reads -------------------------------------------------------------------------------

@pytest.fixture
def plain_env(pool_db, monkeypatch):
    """The seeded build with NO quantiles (the t10 slot's case and run 91's), the line-up pick over the seeded fifteen."""
    import test_captain_answer as tca
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: tca._xi(gw=gw or tca.GW))
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    monkeypatch.setattr(draft_tools, "_breakdowns", lambda ids, gw: {e: {"parts": [{"part": "goals", "points": 1.11}]} for e in ids})
    _reset()
    yield pool_db
    _reset()


def test_c3_the_range_reads_are_skipped_when_the_run_has_no_quantiles(plain_env, monkeypatch):
    seen = []
    real = draft_tools._captain_range

    def spy(pid, gw):
        seen.append(pid)
        return real(pid, gw)
    monkeypatch.setattr(draft_tools, "_captain_range", spy)
    skipped = mt.captain_pick()["direct_reply"]
    assert seen == []
    monkeypatch.setattr(mt, "_run_quantile_gws", lambda run: frozenset({11}))     # force the reads: the old path
    read = mt.captain_pick()["direct_reply"]
    assert len(seen) == 11 and skipped == read                     # every range "not computed" either way: byte-identical


def test_c3_the_quantile_check_is_one_read_per_run(plain_env, monkeypatch):
    calls = []
    real = mt._q

    def q(sql, params=()):
        if "q_p50 IS NOT NULL" in sql:
            calls.append(sql)
        return real(sql, params)
    monkeypatch.setattr(mt, "_q", q)
    mt.captain_pick()
    mt.captain_pick()
    assert len(calls) == 1
