"""Prompt W11 (2026-11-12): non-draft turns send the SAME bytes as before the draft team (payload v5), and a draft chat's turn
differs ONLY by the reviewed draft wording appended to the turn's first text block.

1. The system prompt, the tool schema and the model parameters hash to their values at 984a62a (the commit W11 branched from).
2. A turn with no thread, an ordinary stored-thread turn and a team-bound thread's turn send requests equal to fixture v5's.
3. A draft chat's turn: the same request once "\\n" + prompts/draft_mode.md is removed from the first text block and its
   max_tokens (2,048, Prompt W11f V2) is put back to v5's 1,024 and its one extra tool (explain_my_draft, the last, Prompt
   W11g G1) is removed -- on the first call and on every call of a three-call tool turn; the stored history never carries it.
5. (W11f V2) the reply cap: 2,048 on a draft turn, 1,024 on every other, at both request sites (the call and the send-back).
Offline: a fake client, the v5 context block and clock (eval/payload_fixture.py)."""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                                               # noqa: E402

FIXTURE = REPO / "Tests" / "fixtures" / "agent_payloads_v5.json"
BASE_SYSTEM_PROMPT_SHA = "3acb1ee49f0dec5d8e58d31136c0ac3325b8cb083548621aa2c45cf757ae2fc5"    # 984a62a
BASE_TOOLS_SHA = "30a8355ed3540b72cf2a5d45f912b123fd0e63f5df1063bc5dfefdab38a9136e"            # 984a62a, 24 tools
DRAFT = {"user_id": 10001, "draft_key": 800_000_001}


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AGENT_ENGINE", "loop")       # a thread dict without the checkpointer: the loop builds the same bytes
    import importlib
    import agent as ag
    importlib.reload(ag)
    return ag


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _with_thread(monkeypatch, ag, thread):
    orig = ag.run_agent
    monkeypatch.setattr(ag, "run_agent",
                        lambda message, messages=None, **kw: orig(message, messages, thread=dict(thread) if thread else None))
    return orig


def _strip_draft(req, block):
    """The request with the draft wording removed from the question message's first text block and v5's reply cap back
    (a draft turn's is 2,048: W11f V2)."""
    out = json.loads(json.dumps(req))
    assert out["max_tokens"] == 2048, out["max_tokens"]
    out["max_tokens"] = 1024
    assert out["tools"][-1]["name"] == "explain_my_draft", out["tools"][-1]["name"]       # W11g G1: offered on draft turns only
    out["tools"] = out["tools"][:-1]
    for m in out["messages"]:
        c = m.get("content")
        if m.get("role") == "user" and isinstance(c, list) and c and c[0].get("type") == "text" and c[0]["text"].endswith(block):
            c[0]["text"] = c[0]["text"][: -len(block)]
    return out


def test_1_the_prompt_tools_and_model_are_unchanged_since_984a62a(monkeypatch):
    ag = _agent(monkeypatch)
    assert hashlib.sha256(ag.SYSTEM_PROMPT.encode("utf-8")).hexdigest() == BASE_SYSTEM_PROMPT_SHA
    tools = json.dumps(ag.tools_schema, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(tools).hexdigest() == BASE_TOOLS_SHA and len(ag.tools_schema) == 24
    assert ag.AGENT_MODEL == "claude-sonnet-4-6"
    assert "draft" not in ag.SYSTEM_PROMPT.lower()                         # the draft wording lives in its own file only


def test_2_ordinary_thread_turns_equal_fixture_v5(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    item = doc["first_calls"][0]
    for thread in ({}, {"thread_id": "th_plain", "user_id": 10001, "max_turns": 10},
                   {"thread_id": "th_team", "user_id": 10001, "max_turns": 10, "turn_id": "t" * 32}):
        _with_thread(monkeypatch, ag, thread)
        req = pf.capture(ag, item["question"], pf.reply_only(), doc["context_text"], now=doc["frozen_now"])[0]
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"], thread
        assert req["messages"] == item["messages"], thread
        monkeypatch.undo()
        ag = _agent(monkeypatch)


def test_3_a_draft_turn_differs_only_by_the_draft_wording_on_every_call(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    block = "\n" + ag.DRAFT_MODE_TEXT
    item = doc["first_calls"][0]
    _with_thread(monkeypatch, ag, {"thread_id": "th_draft", "user_id": 10001, "max_turns": 10, "draft": DRAFT})
    req = pf.capture(ag, item["question"], pf.reply_only(), doc["context_text"], now=doc["frozen_now"])[0]
    first = req["messages"][0]["content"][0]["text"]
    assert first.endswith(block) and "Draft mode." in first
    stripped = _strip_draft(req, block)
    assert {k: stripped[k] for k in stripped if k != "messages"} == doc["shared"]
    assert stripped["messages"] == item["messages"]
    turn = pf.capture(ag, doc["tool_turn"]["question"], pf.tool_turn(), doc["context_text"], now=doc["frozen_now"])
    assert len(turn) == 3
    for i, call in enumerate(turn):
        s = _strip_draft(call, block)
        assert {k: s[k] for k in s if k != "messages"} == doc["shared"], i
        assert s["messages"] == doc["tool_turn"]["calls"][i], i


def test_4_the_draft_wording_is_the_reviewed_file_and_names_no_numbers_beyond_the_rules():
    text = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    assert text.startswith("Draft mode.") and "£100.0m" in text and "never treat them as a constraint" in text
    import re
    nums = set(re.findall(r"\d+(?:\.\d+)?", text))
    assert nums <= {"15", "100.0", "2", "5", "3", "1"}, nums


def test_5_the_reply_cap_is_2048_on_a_draft_turn_and_1024_on_every_other_at_both_request_sites(monkeypatch):
    import inspect
    import turn_context
    ag = _agent(monkeypatch)
    assert _fixture()["shared"]["max_tokens"] == 1024                   # v5: every non-draft turn (test_2)
    assert ag._max_tokens() == 1024
    turn_context.begin("t" * 32, thread_id="th_draft", draft=DRAFT)
    try:
        assert ag._max_tokens() == 2048
    finally:
        turn_context.end()
    turn_context.begin("u" * 32, thread_id="th_plain")
    try:
        assert ag._max_tokens() == 1024
    finally:
        turn_context.end()
    for fn in (ag._call_model, ag._send_back):
        src = inspect.getsource(fn)
        assert '"max_tokens": _max_tokens()' in src and '"max_tokens": 1024' not in src, fn.__name__
        assert '"tools": _tools_for_request(_turn_tools())' in src, fn.__name__              # W11g G1
