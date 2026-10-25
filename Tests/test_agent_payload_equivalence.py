"""Payload equivalence: the requests agent.run_agent sends today equal the fixture, apart from cache_control
(eval/payload_fixture.py holds the one comparison rule). v1 (2026-10-19) pinned the shape before the move onto llm.py +
prompt caching; v2 (2026-10-24) pins the shape after the clock move: the context block without its "- Now:" line in the
system prompt, and that line as the first text block of the turn's user message, captured with the clock frozen at the
fixture's own instant. v1 stays on disk as the record of the earlier shape (the proof of the move diffed every v1 call
against the new code: eval/reports/pricing_and_clock_v1.md, Part 2). Offline: a fake client, a pinned context block and
clock, no DB writes."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                               # noqa: E402

FIXTURE = REPO / "Tests" / "fixtures" / "agent_payloads_v2.json"
V1 = REPO / "Tests" / "fixtures" / "agent_payloads_v1.json"


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)
    return ag


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_describes_the_core_set():
    doc = _fixture()
    assert doc["n_core"] == len(doc["first_calls"]) == 109
    assert len(doc["tool_turn"]["calls"]) == 3
    assert sorted(doc["shared"]) == ["max_tokens", "model", "system", "tools"]
    assert doc["shared"]["model"] == "claude-sonnet-4-6" and doc["shared"]["max_tokens"] == 1024
    # v2: the clock is pinned beside the block, the block carries no clock line, the Now line is its own field
    assert doc["frozen_now"] and doc["now_line"].startswith("- Now: ")
    assert pf.now_from_context(doc["context_text"]) is None and "- Now:" not in doc["context_text"]
    assert pf.now_from_context(doc["now_line"]).strftime("%Y-%m-%dT%H:%M:00Z") == doc["frozen_now"]
    assert V1.exists()                                     # the pre-move record is kept


def test_the_normalizer_treats_a_string_and_its_single_text_block_alike():
    a = pf.normalize_request({"system": "s", "messages": [{"role": "user", "content": "q"}], "tools": [{"name": "t"}]})
    b = pf.normalize_request({"system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}],
                              "messages": [{"role": "user", "content": [{"type": "text", "text": "q", "cache_control": {"type": "ephemeral"}}]}],
                              "tools": [{"name": "t", "cache_control": {"type": "ephemeral"}}]})
    assert a == b
    c = pf.normalize_request({"system": "s", "messages": [{"role": "user", "content": "q"}], "tools": [{"name": "t"}], "temperature": 0})
    assert c != a                                                  # an added keyword is a difference


def test_strip_now_and_now_from_context_read_the_v1_shape():
    doc1 = json.loads(V1.read_text(encoding="utf-8"))
    now = pf.now_from_context(doc1["context_text"])
    assert now is not None and now.strftime("%A %Y-%m-%d %H:%M") == "Thursday 2026-10-22 16:44"
    stripped = pf.strip_now(doc1["context_text"])
    assert "- Now:" not in stripped and stripped.splitlines()[0] == doc1["context_text"].splitlines()[0]
    assert len(stripped.splitlines()) == len(doc1["context_text"].splitlines()) - 1


def test_first_call_of_every_core_question_matches_the_fixture(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    shared = doc["shared"]
    diffs = []
    for item in doc["first_calls"]:
        req = pf.capture(ag, item["question"], pf.reply_only(), doc["context_text"], now=doc["frozen_now"])[0]
        if {k: req[k] for k in req if k != "messages"} != shared or req["messages"] != item["messages"]:
            diffs.append(item["id"])
    assert diffs == [], f"{len(diffs)} first calls differ from the fixture: {diffs[:10]}"


def test_every_first_call_opens_with_the_now_line_and_the_system_has_none():
    doc = _fixture()
    for item in doc["first_calls"]:
        content = item["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": doc["now_line"]}, item["id"]
        assert content[1]["text"] == item["question"]
    assert "- Now:" not in "".join(b["text"] for b in doc["shared"]["system"])


def test_the_three_call_tool_turn_matches_the_fixture(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    turn = pf.capture(ag, doc["tool_turn"]["question"], pf.tool_turn(), doc["context_text"], now=doc["frozen_now"])
    assert len(turn) == 3
    for i, req in enumerate(turn):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"], f"call {i + 1}: shared keywords differ"
        assert req["messages"] == doc["tool_turn"]["calls"][i], f"call {i + 1}: messages differ"
    # the Now line stays on the question message on every call of the turn; a tool_result message never carries it
    for call in doc["tool_turn"]["calls"]:
        assert call[0]["content"][0] == {"type": "text", "text": doc["now_line"]}
        assert all(m["content"][0]["type"] == "tool_result" for m in call[1:] if m["role"] == "user")


def test_the_shared_parts_are_the_prompt_file_and_the_tool_schema(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    system_text = "".join(b["text"] for b in doc["shared"]["system"])
    assert system_text == f"{doc['context_text']}\n\n{ag.SYSTEM_PROMPT}"
    assert [t["name"] for t in doc["shared"]["tools"]] == [t["name"] for t in ag.tools_schema]
