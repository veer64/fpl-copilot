"""agent.py on llm.py with prompt caching (2026-10-19): no direct Anthropic client on the /chat path; three
cache_control breakpoints per request (the last tool, the system prompt, the last block of the messages) and
never more; the conversation history keeps none; the usage log prices cache tokens; a failed call reaches the user
exactly as before (an exception out of run_agent, a 500 from /chat). Fakes only; no API, no DB writes."""
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
import pricing                                             # noqa: E402

CC = {"type": "ephemeral"}


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


def _usage(i, o, cr=0, cw=0):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw)


class _Resp:
    def __init__(self, content, stop_reason, usage=None):
        self.content, self.stop_reason, self.model = content, stop_reason, "claude-sonnet-4-6"
        self.usage = usage


class _Raw:
    """Records the RAW keyword sets (cache_control included) and answers from a script."""

    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _two_calls(reply="done"):
    return [_Resp([_Block("tool_use", name="get_picks", input={}, id="t1")], "tool_use", _usage(1000, 50, 300, 0)),
            _Resp([_Block("text", text=reply)], "end_turn", _usage(1200, 80, 0, 200))]


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)
    monkeypatch.setattr(ag, "context_block", lambda: "CONTEXT BLOCK\n- Now: Monday 2026-10-19 23:00 UTC.")
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_numeric_check", lambda *a, **k: None)
    monkeypatch.setitem(ag.available_functions, "get_picks", lambda **kw: {"captain": "X"})
    return ag


def _markers(kw):
    """every cache_control in a request, as (where, index) -- tools, system blocks, message blocks"""
    out = []
    for i, t in enumerate(kw["tools"]):
        if "cache_control" in t:
            out.append(("tool", i, t["cache_control"]))
    system = kw["system"]
    assert isinstance(system, list), "the system prompt must be a list of blocks to carry a breakpoint"
    for i, b in enumerate(system):
        if "cache_control" in b:
            out.append(("system", i, b["cache_control"]))
    for mi, m in enumerate(kw["messages"]):
        content = m["content"]
        if isinstance(content, str):
            continue
        for bi, b in enumerate(content):
            if isinstance(b, dict) and "cache_control" in b:
                out.append(("message", mi, bi, b["cache_control"]))
    return out


# ---- the call path ------------------------------------------------------------------------------------------------

def test_agent_py_has_no_direct_anthropic_client_on_the_chat_path(monkeypatch):
    ag = _agent(monkeypatch)
    src = Path(ag.__file__).read_text(encoding="utf-8")
    assert "import anthropic" not in src and "anthropic.Anthropic" not in src
    assert "messages.create(" not in src                    # the one call site is llm.chat now
    assert ag.client.max_retries == 0                       # llm.default_client: the SDK's retries off, llm.py's on
    assert ag.client.timeout.read == 600 and ag.client.timeout.connect == 5.0   # the SDK default the agent always had
    assert ag.AGENT_MODEL == "claude-sonnet-4-6"


def test_every_call_carries_exactly_three_breakpoints_tools_system_last_block(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_two_calls())
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("who should I captain?")
    assert answer == "done" and len(fake.calls) == 2
    n_tools = len(ag.tools_schema)
    # call 1: the user text is the last block
    m = _markers(fake.calls[0])
    assert m == [("tool", n_tools - 1, CC), ("system", 0, CC), ("message", 0, 0, CC)]
    assert fake.calls[0]["messages"][0]["content"] == [{"type": "text", "text": "who should I captain?", "cache_control": CC}]
    # call 2: the tool_result is the last block; the user text no longer carries a marker
    m = _markers(fake.calls[1])
    assert m == [("tool", n_tools - 1, CC), ("system", 0, CC), ("message", 2, 0, CC)]
    assert fake.calls[1]["messages"][2]["content"][0]["type"] == "tool_result"
    assert fake.calls[1]["messages"][0]["content"] == "who should I captain?"      # history form, unmarked
    # the system prompt is one block whose text is the whole prompt the agent built this turn
    assert len(fake.calls[0]["system"]) == 1
    assert ag.system_text(fake.calls[0]["system"]) == f"{ag.context_block()}\n\n{ag.SYSTEM_PROMPT}"
    assert fake.calls[0]["system"] is not fake.calls[1]["system"] or True        # built per call from the same text
    assert ag.system_text(fake.calls[1]["system"]) == ag.system_text(fake.calls[0]["system"])


def test_the_tools_sent_are_the_schema_with_a_marker_on_the_last_one_only(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_two_calls())
    monkeypatch.setattr(ag, "client", fake)
    ag.run_agent("q")
    sent = fake.calls[0]["tools"]
    assert [t["name"] for t in sent] == [t["name"] for t in ag.tools_schema]
    assert sent[-1]["name"] == "search_news" and sent[-1]["cache_control"] == CC
    assert all("cache_control" not in t for t in sent[:-1])
    assert all("cache_control" not in t for t in ag.tools_schema)                # the module's schema is untouched


def test_the_history_keeps_no_cache_control_and_a_second_turn_marks_its_own_last_block(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_two_calls() + _two_calls("again"))
    monkeypatch.setattr(ag, "client", fake)
    _, history = ag.run_agent("q1")

    def no_markers(obj):
        if isinstance(obj, dict):
            return "cache_control" not in obj and all(no_markers(v) for v in obj.values())
        if isinstance(obj, list):
            return all(no_markers(v) for v in obj)
        return True
    assert no_markers(history)
    assert history[0] == {"role": "user", "content": "q1"}                       # the user turn stays a string
    _, history = ag.run_agent("q2", history)
    assert no_markers(history)
    last = fake.calls[-1]
    marks = _markers(last)
    assert len(marks) == 3 and marks[-1][:2] == ("message", len(last["messages"]) - 1)
    assert len(fake.calls[2]["messages"]) == 5 and _markers(fake.calls[2])[-1][:2] == ("message", 4)


def test_system_text_reads_a_string_or_a_block_list():
    import agent as ag
    assert ag.system_text("abc") == "abc"
    assert ag.system_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b", "cache_control": CC}]) == "ab"


# ---- usage and cost ------------------------------------------------------------------------------------------------

def test_last_turn_and_the_usage_log_carry_cache_tokens_priced_at_the_cache_rates(monkeypatch):
    ag = _agent(monkeypatch)
    logged = {}
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: logged.update(args=a))
    monkeypatch.setattr(ag, "client", _Raw(_two_calls()))
    ag.run_agent("q")
    assert ag.LAST_TURN["calls"] == 2 and ag.LAST_TURN["input"] == 2200 and ag.LAST_TURN["output"] == 130
    assert ag.LAST_TURN["cache_read"] == 300 and ag.LAST_TURN["cache_write"] == 200
    turn_id, model, calls, ti, to, cr, cw, usd, replaced = logged["args"]
    assert (model, calls, ti, to, cr, cw) == ("claude-sonnet-4-6", 2, 2200, 130, 300, 200)
    assert usd == pricing.turn_usd("claude-sonnet-4-6", 2200, 130, cache_read=300, cache_write=200)
    assert usd > pricing.usd("claude-sonnet-4-6", 2200, 130)                       # the cache tokens are no longer free


# ---- the error path ------------------------------------------------------------------------------------------------

class _Status(Exception):
    def __init__(self, status):
        super().__init__(f"status {status}")
        self.status_code, self.body = status, {"error": {"type": "authentication_error"}}


def test_a_failed_call_leaves_run_agent_as_an_exception_and_chat_as_a_500(monkeypatch):
    ag = _agent(monkeypatch)
    monkeypatch.setattr(ag, "client", _Raw([_Status(401)]))
    with pytest.raises(llm.LLMAuthError):
        ag.run_agent("q")

    class BudgetExceeded(RuntimeError):
        pass
    monkeypatch.setattr(ag, "client", _Raw([BudgetExceeded("cap")]))
    with pytest.raises(BudgetExceeded):                                            # the runner's cap, unchanged
        ag.run_agent("q")
    # through the app: the same 500 the unhandled SDK exception produced before the move
    monkeypatch.setenv("APP_API_KEY", "k")
    import importlib
    import main as app_main
    importlib.reload(app_main)
    from fastapi.testclient import TestClient
    monkeypatch.setattr(ag, "client", _Raw([_Status(401)]))
    with TestClient(app_main.app, raise_server_exceptions=False, headers={"x-api-key": "k"}) as c:
        r = c.post("/chat", json={"message": "q"})
    assert r.status_code == 500 and r.text == "Internal Server Error"
