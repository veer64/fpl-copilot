"""The Now line moves from the system block to the latest user message (2026-10-24, Prompt A Part 2).

Before: the context block's second line was "- Now: <weekday> <date> <HH:MM> UTC.", so the system block (one cached text
block of ~50k characters) changed every minute and was written to the cache fresh on most turns. After: the system block
carries the context block WITHOUT the Now line, and the same line text, unchanged, is the first text block of the turn's
user message at send time -- on every call of the turn, never in the stored history. The three cache markers stay where
they were: the last tool, the system block, the last block of the last message. Offline: fake client, no API, no DB."""
import importlib
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import now_context as nc                                   # noqa: E402

UTC = timezone.utc
FROZEN = datetime(2026, 10, 25, 14, 30, tzinfo=UTC)        # a Sunday
NOW_LINE = "- Now: Sunday 2026-10-25 14:30 UTC."
CC = {"type": "ephemeral"}
BLOCK = "CONTEXT BLOCK (test)\n- Gameweeks: GW7 is the last finished gameweek; GW8 is in progress."


def _usage(i, o, cr=0, cw=0):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw)


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason, self.usage, self.model = content, stop_reason, _usage(10, 5), "claude-sonnet-4-6"


class _Raw:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=lambda b: dict(vars(b)))))   # a deep copy at the call
        return self.script.pop(0)


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(nc, "clock", lambda: FROZEN)
    monkeypatch.setattr(nc, "_load_deadlines", lambda: {})          # no deadline known -> no countdown line (Tests/test_time_batch.py covers it)
    import agent as ag
    ag = importlib.reload(ag)
    monkeypatch.setattr(ag, "context_block", lambda now=None: BLOCK)
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_numeric_check", lambda *a, **k: None)
    monkeypatch.setitem(ag.available_functions, "get_picks", lambda **kw: {"captain": "X"})
    return ag


def _tool_turn():
    return [_Resp([_Block("tool_use", name="get_picks", input={}, id="t1")], "tool_use"),
            _Resp([_Block("text", text="done")], "end_turn")]


# ---- (a) the system block carries no Now line ------------------------------------------------------------------------

def test_the_context_block_has_no_now_line_and_now_line_is_its_own_piece():
    import dispatch_policy as dp
    text, omitted = nc.build(FROZEN, deadlines={9: datetime(2026, 10, 31, 11, 0, tzinfo=UTC)}, finished=[1, 2, 3, 4, 5, 6, 7],
                             clubs=["Arsenal", "Chelsea"], dispatch_state={}, policy=dp)
    assert text.startswith(nc.TITLE)
    assert "- Now:" not in text and "2026-10-25" not in text
    assert "next deadline GW9, Saturday 2026-10-31 11:00 UTC" in text    # the clock still drives the gameweek line
    assert nc.now_line(FROZEN) == NOW_LINE
    assert omitted == {}


def test_the_system_prompt_sent_has_no_now_line(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_tool_turn())
    monkeypatch.setattr(ag, "client", fake)
    ag.run_agent("who should I captain?")
    for call in fake.calls:
        system = ag.system_text(call["system"])
        assert "- Now:" not in system and "2026-10-25" not in system
        assert system == f"{BLOCK}\n\n{ag.SYSTEM_PROMPT}"


# ---- (b) the latest user message starts with it, on every call of the turn --------------------------------------------

def test_the_turns_user_message_starts_with_the_now_line_on_every_call(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_tool_turn())
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("who should I captain?")
    assert answer == "done" and len(fake.calls) == 2
    # call 1: [Now line, question(marker)]
    m0 = fake.calls[0]["messages"]
    assert m0[0]["role"] == "user"
    assert m0[0]["content"] == [{"type": "text", "text": NOW_LINE},
                                {"type": "text", "text": "who should I captain?", "cache_control": CC}]
    # call 2: the same question message, unmarked now; the tool_result message is the last block carrier
    m1 = fake.calls[1]["messages"]
    assert m1[0]["content"] == [{"type": "text", "text": NOW_LINE}, {"type": "text", "text": "who should I captain?"}]
    assert m1[2]["content"][0]["type"] == "tool_result" and m1[2]["content"][0]["cache_control"] == CC
    assert m1[2]["content"][0]["content"] == str({"captain": "X"})       # a tool result is not prefixed


def test_the_now_line_is_the_frozen_clocks_text(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw([_Resp([_Block("text", text="ok")], "end_turn")])
    monkeypatch.setattr(ag, "client", fake)
    ag.run_agent("hi")
    assert fake.calls[0]["messages"][0]["content"][0]["text"] == nc.now_line(FROZEN) == NOW_LINE


# ---- (c) the stored history never carries it ----------------------------------------------------------------------------

def test_the_stored_history_has_no_now_line_and_a_second_turn_moves_it(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_tool_turn() + [_Resp([_Block("text", text="again")], "end_turn")])
    monkeypatch.setattr(ag, "client", fake)
    _, history = ag.run_agent("q1")
    assert history[0] == {"role": "user", "content": "q1"}                # the question stays a string
    assert "- Now:" not in json.dumps(history, default=str)
    _, history = ag.run_agent("q2", history)
    assert "- Now:" not in json.dumps(history, default=str)
    sent = fake.calls[-1]["messages"]
    assert sent[0]["content"] == "q1"                                     # the earlier question goes plain
    assert sent[-1]["content"] == [{"type": "text", "text": NOW_LINE}, {"type": "text", "text": "q2", "cache_control": CC}]


# ---- the markers stay where they were ------------------------------------------------------------------------------------

def _markers(kw):
    out = []
    for i, t in enumerate(kw["tools"]):
        if "cache_control" in t:
            out.append(("tool", i))
    for i, b in enumerate(kw["system"]):
        if "cache_control" in b:
            out.append(("system", i))
    for mi, m in enumerate(kw["messages"]):
        if isinstance(m["content"], list):
            for bi, b in enumerate(m["content"]):
                if isinstance(b, dict) and "cache_control" in b:
                    out.append(("message", mi, bi))
    return out


def test_three_breakpoints_in_the_same_places(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw(_tool_turn())
    monkeypatch.setattr(ag, "client", fake)
    ag.run_agent("who should I captain?")
    n = len(ag.tools_schema)
    assert _markers(fake.calls[0]) == [("tool", n - 1), ("system", 0), ("message", 0, 1)]   # the question block, after the Now line
    assert _markers(fake.calls[1]) == [("tool", n - 1), ("system", 0), ("message", 2, 0)]
