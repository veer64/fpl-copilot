"""Prompt P6 Part 1 (2026-11-01): the slow tools -- get_player_card, get_my_squad, build_squad_from_scratch (optimise),
propose_transfers -- made faster WITHOUT changing a byte of their output.

Measured (eval/reports/backlog_p6.md, Part 1): every model_tools read opened its own psycopg2 connection (_q), 6 per
get_player_card, 5 per get_my_squad, up to 7 per build and 11 per propose_transfers. On the laptop "localhost" resolves to ::1
first and each connect waited 2.05 s for that attempt to fail (127.0.0.1: 0.008 s), so the connects were ~99% of every call;
in production (fpl-postgres) a connect costs 17.6 ms, ~60% of a 174 ms player card.

S1 db_write.connect_kwargs: only "localhost" is pinned to its IPv4 address (libpq's hostaddr, threads.conninfo's rule); any
   other host is passed through unchanged, with no lookup. db_write.connect and model_tools._conn both use it.
S2 one connection per tool call: the four tools open ONE connection for all their reads (a call that reads nothing opens
   none); a nested call reuses it; each read is still its own transaction, rolled back after it (a read never commits); a
   failing read does not poison the next; a dead connection is replaced; the connection is closed when the call returns.
S3 outputs unchanged: each tool's output through the new path equals the old path's (fn.__wrapped__: one connection per
   read), byte for byte as canonical JSON, on the laptop's own data (read-only calls; propose_transfers writes proposal rows,
   so its 10 fixed inputs are compared by the gate's script, not here).
S4 the production frame is loaded once per process while its build is unchanged: a new build (the file rewritten, or its
   sidecar's run id changed) invalidates it; every caller gets its own copy."""
import json
import os
import socket
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import db_write                                                    # noqa: E402
import model_tools as mt                                           # noqa: E402

TOOLS = ("get_player_card", "get_my_squad", "optimise", "propose_transfers")


def _canon(x):
    return json.dumps(x, sort_keys=True, default=str, ensure_ascii=False)


class _Spy:
    """psycopg2.connect, counted (the real connect underneath)."""

    def __init__(self, monkeypatch):
        self.calls, self.real = [], psycopg2.connect
        monkeypatch.setattr(psycopg2, "connect", self)

    def __call__(self, *a, **kw):
        self.calls.append(kw)
        conn = self.real(*a, **kw)
        return conn


# ---- S1: the localhost pin ---------------------------------------------------------------------------------------------

def test_s1_localhost_is_pinned_to_an_ipv4_address(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    kw = db_write.connect_kwargs()
    assert kw["host"] == "localhost"
    socket.inet_pton(socket.AF_INET, kw["hostaddr"])                # an IPv4 address, never ::1
    assert {k: kw[k] for k in ("port", "dbname", "user")} == {"port": os.getenv("DB_PORT", "5432"),
                                                              "dbname": os.getenv("DB_NAME", "fpl"),
                                                              "user": os.getenv("DB_USER", "postgres")}


def test_s1_localhost_is_looked_up_once_per_process_not_per_connect(monkeypatch):
    """test_threads F3: no host lookup per turn. The address is resolved at the first connect and reused; a failed lookup
    is not remembered (the next connect tries again)."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setattr(db_write, "_HOSTADDR", {})
    looked = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: looked.append(a[0]) or real(*a, **k))
    first, second, third = (db_write.connect_kwargs() for _ in range(3))
    assert looked == ["localhost"] and first == second == third and "hostaddr" in first

    def broken(*a, **k):
        looked.append(a[0])
        raise socket.gaierror("no answer")
    monkeypatch.setattr(db_write, "_HOSTADDR", {})
    monkeypatch.setattr(socket, "getaddrinfo", broken)
    assert "hostaddr" not in db_write.connect_kwargs() and "hostaddr" not in db_write.connect_kwargs()
    assert looked == ["localhost", "localhost", "localhost"]          # a failure is retried, never cached


@pytest.mark.parametrize("host", ["fpl-postgres", "db.example.internal", "10.1.2.3"])
def test_s1_any_other_host_is_passed_through_unchanged_with_no_lookup(monkeypatch, host):
    looked = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: looked.append(a) or real(*a, **k))
    monkeypatch.setenv("DB_HOST", host)
    kw = db_write.connect_kwargs()
    assert kw["host"] == host and "hostaddr" not in kw and looked == []


def test_s1_both_connect_functions_use_the_pinned_arguments(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    seen = []
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: seen.append(kw))
    db_write.connect()
    mt._conn()
    assert seen == [db_write.connect_kwargs(), db_write.connect_kwargs()] and "hostaddr" in seen[0]


# ---- S2: one connection per tool call ----------------------------------------------------------------------------------

@pytest.mark.parametrize("name", TOOLS)
def test_s2_the_four_tools_share_one_connection_per_call(name):
    fn = getattr(mt, name)
    assert getattr(fn, "one_connection_per_call", False) is True and callable(fn.__wrapped__)


def test_s2_a_player_card_opens_one_connection(monkeypatch):
    spy = _Spy(monkeypatch)
    card = mt.get_player_card(411)
    assert "error" not in card and len(spy.calls) == 1


def test_s2_my_squad_opens_one_connection(monkeypatch):
    spy = _Spy(monkeypatch)
    out = mt.get_my_squad(9001)
    assert "error" not in out and len(spy.calls) == 1


def test_s2_a_build_opens_one_connection(monkeypatch):
    spy = _Spy(monkeypatch)
    out = mt.optimise(lock_player_ids=[411])
    assert "error" not in out and len(spy.calls) == 1


def test_s2_reads_share_one_connection_nested_calls_reuse_it_and_it_is_closed_after(monkeypatch):
    spy = _Spy(monkeypatch)
    conns = []

    @mt.one_connection_per_call
    def inner():
        conns.append(mt._call_connection())
        return mt._q("SELECT 2 AS v")[0]["v"]

    @mt.one_connection_per_call
    def outer():
        a = mt._q("SELECT 1 AS v")[0]["v"]
        conns.append(mt._call_connection())
        return a, inner(), mt._q("SELECT 3 AS v")[0]["v"]

    assert outer() == (1, 2, 3) and len(spy.calls) == 1
    assert conns[0] is conns[1] and conns[0].closed                  # one connection, closed when the call returned
    assert mt._call_connection() is None                             # nothing left open outside a call
    assert mt._q("SELECT 4 AS v")[0]["v"] == 4 and len(spy.calls) == 2   # outside a call: one connection per read, as before


def test_s2_a_call_that_reads_nothing_opens_no_connection(monkeypatch):
    spy = _Spy(monkeypatch)
    out = mt.get_player_card("not an id")
    assert "error" in out and spy.calls == []


def test_s2_each_read_is_its_own_transaction_rolled_back_after_it(monkeypatch):
    @mt.one_connection_per_call
    def call():
        # a session setting made inside a read's transaction is undone when that transaction is rolled back
        made = mt._q("SELECT set_config('p6.probe', 'set', false) AS v")[0]["v"]
        status = mt._call_connection().get_transaction_status()
        after = mt._q("SELECT current_setting('p6.probe', true) AS v")[0]["v"]
        return made, status, after

    made, status, after = call()
    assert made == "set" and status == psycopg2.extensions.TRANSACTION_STATUS_IDLE and after in (None, "")


def test_s2_a_failing_read_does_not_poison_the_next(monkeypatch):
    @mt.one_connection_per_call
    def call():
        with pytest.raises(psycopg2.errors.UndefinedColumn):
            mt._q("SELECT no_such_column FROM players_live LIMIT 1")
        return mt._q("SELECT 7 AS v")[0]["v"]

    assert call() == 7


def test_s2_a_dead_connection_is_replaced(monkeypatch):
    spy = _Spy(monkeypatch)

    @mt.one_connection_per_call
    def call():
        mt._q("SELECT 1 AS v")
        mt._call_connection().close()                                # the server went away mid-call
        return mt._q("SELECT 8 AS v")[0]["v"]

    assert call() == 8 and len(spy.calls) == 2


# ---- S3: outputs unchanged (the laptop's data, read-only) -------------------------------------------------------------

CARD_IDS = (411, 398, 12, 154, 427, 379, 397, 1, 55, 356)
SQUAD_USERS = (9001, 9002, None, 1, 9003, 0, 42, 9999, 123456, 7)
BUILDS = ({}, {"budget": 95.5}, {"lock_player_ids": [411]}, {"ban_player_ids": [411]}, {"start_player_ids": [397]},
          {"lock_player_ids": [411, 379], "ban_player_ids": [398]}, {"gw": 9}, {"gw": 10, "budget": 98.0},
          {"lock_player_ids": [55]}, {"lock_player_ids": [99999]})
VOLATILE = ("solve_seconds", "total_seconds")      # wall-clock measures of the solve itself: never equal from run to run


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


@pytest.mark.parametrize("pid", CARD_IDS)
def test_s3_player_card_output_is_unchanged(monkeypatch, pid):
    monkeypatch.setenv("FPL_USER_ID", "9001")
    assert _canon(mt.get_player_card(pid)) == _canon(mt.get_player_card.__wrapped__(pid))


@pytest.mark.parametrize("user", SQUAD_USERS)
def test_s3_my_squad_output_is_unchanged(monkeypatch, user):
    monkeypatch.setenv("FPL_USER_ID", "9001")
    assert _canon(mt.get_my_squad(user)) == _canon(mt.get_my_squad.__wrapped__(user))


@pytest.mark.parametrize("i", range(len(BUILDS)))
def test_s3_build_output_is_unchanged(monkeypatch, i):
    monkeypatch.setenv("FPL_USER_ID", "9001")
    new, old = mt.optimise(**BUILDS[i]), mt.optimise.__wrapped__(**BUILDS[i])
    assert _canon(_strip(new)) == _canon(_strip(old))


# ---- S4: the frame, once per build ---------------------------------------------------------------------------------------

@pytest.fixture
def frame_dir(tmp_path, monkeypatch):
    """A copy of the production frame, prices and sidecar in a temp dir, PROD_FRAME pointed at it, the cache emptied."""
    src = mt.PROD_FRAME
    frame = tmp_path / "data" / "live" / src.name
    frame.parent.mkdir(parents=True)
    frame.write_bytes(src.read_bytes())
    prices = src.parent / "_tmp_prices_2026_27.parquet"
    (frame.parent / prices.name).write_bytes(prices.read_bytes())
    side = src.with_suffix(".provenance.json")
    if side.exists():
        frame.with_suffix(".provenance.json").write_bytes(side.read_bytes())
    monkeypatch.setattr(mt, "PROD_FRAME", frame)
    monkeypatch.setattr(mt, "REPO", tmp_path)
    mt._FRAME_CACHE.clear()
    yield frame
    mt._FRAME_CACHE.clear()


def _count_reads(monkeypatch):
    import simulator as sim
    n = {"season": 0, "raw": 0}
    inside = []
    real_season, real_raw = sim.load_season, pd.read_parquet

    def season(*a, **k):
        n["season"] += 1
        inside.append(1)
        try:
            return real_season(*a, **k)
        finally:
            inside.pop()

    def raw(path, *a, **k):
        if Path(str(path)).name == mt.PROD_FRAME.name and not inside:    # the raw frame, not load_season's own read
            n["raw"] += 1
        return real_raw(path, *a, **k)
    monkeypatch.setattr(sim, "load_season", season)
    monkeypatch.setattr(pd, "read_parquet", raw)
    return n


def test_s4_the_frame_is_read_once_while_its_build_is_unchanged(frame_dir, monkeypatch):
    n = _count_reads(monkeypatch)
    a, b = mt._load_frame(), mt._load_frame()
    r1, r2 = mt._frame_raw(), mt._frame_raw()
    assert n == {"season": 1, "raw": 1}
    assert a[1:] == b[1:] and a[0].equals(b[0]) and a[0] is not b[0]      # equal, but each caller gets its own copy
    assert r1[1:] == r2[1:] and r1[0].equals(r2[0]) and r1[0] is not r2[0]


def test_s4_a_caller_mutating_its_frame_changes_nothing_for_the_next(frame_dir, monkeypatch):
    df, _, _ = mt._load_frame()
    df["e_points"] = -1.0
    df.drop(df.index, inplace=True)
    again, _, _ = mt._load_frame()
    assert len(again) > 0 and (again["e_points"] != -1.0).any()


def test_s4_a_new_build_invalidates_the_cache(frame_dir, monkeypatch):
    n = _count_reads(monkeypatch)
    old, _, _ = mt._frame_raw()
    old_season, _, _ = mt._load_frame()
    assert n == {"season": 1, "raw": 1}
    new = old.copy()
    new["e_points"] = new["e_points"] + 1.0                           # the next build writes the file again
    new.to_parquet(frame_dir)
    os.utime(frame_dir, ns=(frame_dir.stat().st_atime_ns, frame_dir.stat().st_mtime_ns + 10**9))
    fresh, _, _ = mt._frame_raw()
    season, _, _ = mt._load_frame()
    assert n == {"season": 2, "raw": 2}                               # both shapes are rebuilt from the new file
    assert (fresh["e_points"].values == old["e_points"].values + 1.0).all()
    assert not season["e_points"].equals(old_season["e_points"])


def test_s4_a_new_sidecar_run_id_invalidates_the_cache(frame_dir, monkeypatch):
    side = frame_dir.with_suffix(".provenance.json")
    doc = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    monkeypatch.setattr(mt, "_check_sidecar", lambda frame_p, cutoff: None)
    n = _count_reads(monkeypatch)
    mt._frame_raw()
    doc["run_id"] = int(doc.get("run_id") or 0) + 1000
    side.write_text(json.dumps(doc), encoding="utf-8")
    mt._frame_raw()
    assert n["raw"] == 2


def test_s4_the_sidecar_check_still_runs_on_every_call(frame_dir, monkeypatch):
    checked = []
    monkeypatch.setattr(mt, "_check_sidecar", lambda frame_p, cutoff: checked.append(cutoff))
    mt._load_frame()
    mt._load_frame()
    mt._frame_raw()
    assert len(checked) == 3
