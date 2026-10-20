"""llm.chat (2026-10-19): the agent's path through llm.py -- tools and a multi-turn message list in, the full
response out -- with complete()'s retry and fail-fast rules, the request passed through verbatim, and the ledger
rule (no llm_calls row without a connection; the caller's purpose tags every row when there is one).
No API, no DB: fakes only."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402


class _Status(Exception):
    """An SDK-shaped status error: .status_code and a body with an error type."""

    def __init__(self, status, etype="api_error"):
        super().__init__(f"status {status}")
        self.status_code, self.body = status, {"error": {"type": etype}}


class APITimeoutError(Exception):                           # llm.classify goes by the class NAME
    pass


class _Resp:
    def __init__(self, text="ok"):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.stop_reason, self.model = "end_turn", "claude-sonnet-4-6"
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 3})()


class _Fake:
    """Answers from a script: an exception instance is raised, anything else returned."""

    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _Conn:
    """Records every INSERT's parameters; commit is a no-op."""

    def __init__(self):
        self.rows = []

    def cursor(self):
        conn = self

        class _Cur:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def execute(self_, sql, params):
                assert "INSERT INTO llm_calls" in sql
                conn.rows.append(params)
        return _Cur()

    def commit(self):
        pass


REQUEST = {"model": "claude-sonnet-4-6", "max_tokens": 1024, "system": [{"type": "text", "text": "s"}],
           "tools": [{"name": "t", "input_schema": {"type": "object"}}],
           "messages": [{"role": "user", "content": "q"}]}


def test_the_request_goes_through_verbatim_and_the_response_comes_back_whole():
    resp = _Resp("hello")
    fake = _Fake([resp])
    out = llm.chat("agent", dict(REQUEST), client=fake)
    assert out is resp                                     # the full response object: content, stop_reason, usage
    assert fake.calls == [REQUEST]                         # no temperature, no timeout, nothing added or dropped


def test_429_5xx_and_timeouts_are_retried_with_the_same_backoff_as_complete():
    slept = []
    fake = _Fake([_Status(429, "rate_limit_error"), APITimeoutError("slow"), _Resp()])
    out = llm.chat("agent", dict(REQUEST), client=fake, sleep=slept.append)
    assert out.stop_reason == "end_turn" and len(fake.calls) == 3
    assert slept == list(llm.BACKOFF_S)
    fake = _Fake([_Status(500), _Status(502), _Status(503)])
    with pytest.raises(llm.LLMError) as e:
        llm.chat("agent", dict(REQUEST), client=fake, sleep=lambda s: None)
    assert len(fake.calls) == llm.RETRIES + 1 and e.value.status == 503
    assert not isinstance(e.value, llm.LLMAuthError)


def test_auth_and_bad_requests_fail_fast():
    fake = _Fake([_Status(401, "authentication_error")])
    with pytest.raises(llm.LLMAuthError) as e:
        llm.chat("agent", dict(REQUEST), client=fake, sleep=lambda s: pytest.fail("no sleep on auth"))
    assert len(fake.calls) == 1 and e.value.status == 401
    fake = _Fake([_Status(400, "invalid_request_error")])
    with pytest.raises(llm.LLMError) as e:
        llm.chat("agent", dict(REQUEST), client=fake, sleep=lambda s: pytest.fail("no sleep on 400"))
    assert len(fake.calls) == 1 and e.value.status == 400 and e.value.error_type == "invalid_request_error"


def test_a_non_api_exception_is_re_raised_unchanged():
    class BudgetExceeded(RuntimeError):                     # the eval runner's cap, raised inside its counting client
        pass
    fake = _Fake([BudgetExceeded("USD cap 5 reached")])
    with pytest.raises(BudgetExceeded):
        llm.chat("agent", dict(REQUEST), client=fake, sleep=lambda s: pytest.fail("no retry"))
    assert len(fake.calls) == 1


def test_no_ledger_row_without_a_connection_and_a_tagged_row_per_attempt_with_one():
    fake = _Fake([_Status(500), _Resp("fine")])
    llm.chat("agent", dict(REQUEST), client=fake, conn=None, sleep=lambda s: None)   # conn=None: nothing to write to
    conn = _Conn()
    fake = _Fake([_Status(500), _Resp("fine")])
    llm.chat("agent", dict(REQUEST), client=fake, conn=conn, sleep=lambda s: None)
    assert len(conn.rows) == 2
    assert [r[0] for r in conn.rows] == ["agent", "agent"]            # purpose: the caller's tag
    assert [r[4] for r in conn.rows] == [False, True]                 # ok per attempt
    assert conn.rows[1][2] == 10 and conn.rows[1][3] == 3             # the tokens of the reply


def test_the_ledger_rule_is_written_in_llm_py():
    assert "chat_usage" in llm.__doc__ and "conn=None" in llm.__doc__
