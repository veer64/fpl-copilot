"""Part 7c of the smoke fixes (2026-10-10): /chat usage per turn, log only.

Until now the agent's Anthropic calls were logged nowhere (llm_calls covers the news pipeline),
so every production check reported the cost as NOT DETERMINED. One chat_usage row per reply,
created by db_write.ensure_schema: the same turn id numeric_checks and citation_checks carry, the
model, the number of API calls, the input / output / cache-read / cache-write tokens, the usd
priced from pricing.USD_PER_MTOK (the eval runner's table; NULL when the model has no price there)
and how many tool names the reply lock replaced. Any exception is caught and printed; /chat never
fails because of it.

Local Postgres (fpl_news_test); no network: the client is a fake that carries usage.
"""
import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2                                            # noqa: E402
import db_write                                            # noqa: E402
import news_store as ns                                    # noqa: E402
import pricing                                             # noqa: E402

TEST_DB = "fpl_news_test"
DROP = "DROP TABLE IF EXISTS chat_usage"


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
        cur.execute(DROP)
    c.commit()
    ns.ensure_schema(c)                       # numeric_checks / citation_checks, for the shared turn id
    db_write.ensure_schema(c)                 # chat_usage
    yield c
    c.close()


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason, model="claude-sonnet-4-6", usage=None):
        self.content, self.stop_reason, self.model = content, stop_reason, model
        self.usage = usage


def _usage(i, o, cr=0, cw=0):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o,
                                 cache_read_input_tokens=cr, cache_creation_input_tokens=cw)


class _TwoCalls:
    """turn 1: a tool call; turn 2: the reply. Both carry usage."""

    def __init__(self, reply, model="claude-sonnet-4-6"):
        self.turn, self.reply, self.model = 0, reply, model

    def create(self, **kw):
        self.turn += 1
        if self.turn == 1:
            return _Resp([_Block("tool_use", name="get_player_card", input={"player_id": 26}, id="t1")],
                         "tool_use", self.model, _usage(1000, 50, 300, 0))
        return _Resp([_Block("text", text=self.reply)], "end_turn", self.model, _usage(1200, 80, 0, 200))


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)
    monkeypatch.setitem(ag.available_functions, "get_player_card",
                        lambda **kw: {"player_id": 26, "name": "Kai Havertz",
                                      "prediction": {"predictions": [{"e_points": 3.7, "p_start": 0.61}]}})
    return ag


def _last_row(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT turn_id, model, api_calls, input_tokens, output_tokens, cache_read_tokens, "
                    "cache_write_tokens, usd, tool_names_replaced FROM chat_usage ORDER BY id DESC LIMIT 1")
        return cur.fetchone()


def test_the_table_exists_with_its_columns(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'chat_usage' "
                    "ORDER BY ordinal_position")
        cols = [r[0] for r in cur.fetchall()]
    assert cols == ["id", "ts", "turn_id", "model", "api_calls", "input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens", "usd", "tool_names_replaced"]


def test_one_row_per_reply_with_the_shared_turn_id_and_the_runners_price(conn, monkeypatch):
    ag = _agent(monkeypatch)
    reply = "Havertz is projected 3.7 points; `get_my_xi` would say more."
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_TwoCalls(reply)))
    answer, _ = ag.run_agent("Is Havertz fit for GW6?")
    assert "get_my_xi" not in answer                                     # the Part 4 lock ran
    turn_id, model, calls, ti, to, cr, cw, usd, replaced = _last_row(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT turn_id FROM numeric_checks ORDER BY id DESC LIMIT 1")
        assert cur.fetchone()[0] == turn_id
        cur.execute("SELECT turn_id FROM citation_checks ORDER BY id DESC LIMIT 1")
        assert cur.fetchone()[0] == turn_id
    assert (model, calls, ti, to, cr, cw, replaced) == ("claude-sonnet-4-6", 2, 2200, 130, 300, 200, 1)
    # since 2026-10-19 the cache tokens are priced too (write x1.25, read x0.10 of the $3 input rate)
    want = pricing.turn_usd("claude-sonnet-4-6", 2200, 130, cache_read=300, cache_write=200)
    assert want == round(2200 / 1e6 * 3.00 + 200 / 1e6 * 3.00 * 1.25 + 300 / 1e6 * 3.00 * 0.10 + 130 / 1e6 * 15.00, 6)
    assert want > pricing.usd("claude-sonnet-4-6", 2200, 130)             # the old line undercounted a cached turn
    assert float(usd) == want


def test_a_model_with_no_price_stores_null_usd(conn, monkeypatch):
    ag = _agent(monkeypatch)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_TwoCalls("ok", model="claude-test-unpriced")))
    ag.run_agent("again")
    turn_id, model, calls, ti, to, cr, cw, usd, replaced = _last_row(conn)
    assert model == "claude-test-unpriced" and calls == 2 and usd is None
    assert pricing.usd("claude-test-unpriced", 1, 1) is None


def test_the_eval_runner_prices_from_the_same_table():
    sys.path.insert(0, str(REPO / "eval"))
    import run_agent_evals as r
    assert r.USD_IN_PER_MTOK == pricing.USD_PER_MTOK["claude-sonnet-4-6"]["input"]
    assert r.USD_OUT_PER_MTOK == pricing.USD_PER_MTOK["claude-sonnet-4-6"]["output"]


def test_a_logging_failure_never_touches_the_reply(conn, monkeypatch, capsys):
    ag = _agent(monkeypatch)
    reply = "Havertz is projected 3.7 points."

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(ag, "record_chat_usage", boom)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_TwoCalls(reply)))
    answer, _ = ag.run_agent("Is Havertz fit?")
    assert answer == reply
    assert "usage not logged" in capsys.readouterr().out
    # a response with no usage at all (older fakes, a provider hiccup) still logs the call, with the
    # tokens and the cost NULL -- undetermined, never a false zero
    class _NoUsage:
        def create(self, **kw):
            return types.SimpleNamespace(content=[_Block("text", text=reply)], stop_reason="end_turn")
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_NoUsage()))
    monkeypatch.setattr(ag, "record_chat_usage", db_write.record_chat_usage)
    answer, _ = ag.run_agent("once more")
    assert answer == reply
    turn_id, model, calls, ti, to, cr, cw, usd, replaced = _last_row(conn)
    assert model == ag.AGENT_MODEL and calls == 1 and replaced == 0
    assert ti is None and to is None and cr is None and cw is None and usd is None
