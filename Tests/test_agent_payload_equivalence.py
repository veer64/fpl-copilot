"""Payload equivalence (2026-10-19): the requests agent.run_agent sends today equal the fixture captured before the
move onto llm.py + prompt caching, apart from cache_control (eval/payload_fixture.py holds the one comparison rule).
Offline: a fake client, a pinned context block, no DB writes."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                               # noqa: E402

FIXTURE = REPO / "Tests" / "fixtures" / "agent_payloads_v1.json"


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


def test_the_normalizer_treats_a_string_and_its_single_text_block_alike():
    a = pf.normalize_request({"system": "s", "messages": [{"role": "user", "content": "q"}], "tools": [{"name": "t"}]})
    b = pf.normalize_request({"system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}],
                              "messages": [{"role": "user", "content": [{"type": "text", "text": "q", "cache_control": {"type": "ephemeral"}}]}],
                              "tools": [{"name": "t", "cache_control": {"type": "ephemeral"}}]})
    assert a == b
    c = pf.normalize_request({"system": "s", "messages": [{"role": "user", "content": "q"}], "tools": [{"name": "t"}], "temperature": 0})
    assert c != a                                                  # an added keyword is a difference


def test_first_call_of_every_core_question_matches_the_fixture(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    shared = doc["shared"]
    diffs = []
    for item in doc["first_calls"]:
        req = pf.capture(ag, item["question"], pf.reply_only(), doc["context_text"])[0]
        if {k: req[k] for k in req if k != "messages"} != shared or req["messages"] != item["messages"]:
            diffs.append(item["id"])
    assert diffs == [], f"{len(diffs)} first calls differ from the fixture: {diffs[:10]}"


def test_the_three_call_tool_turn_matches_the_fixture(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    turn = pf.capture(ag, doc["tool_turn"]["question"], pf.tool_turn(), doc["context_text"])
    assert len(turn) == 3
    for i, req in enumerate(turn):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"], f"call {i + 1}: shared keywords differ"
        assert req["messages"] == doc["tool_turn"]["calls"][i], f"call {i + 1}: messages differ"


def test_the_shared_parts_are_the_prompt_file_and_the_tool_schema(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    system_text = "".join(b["text"] for b in doc["shared"]["system"])
    assert system_text == f"{doc['context_text']}\n\n{ag.SYSTEM_PROMPT}"
    assert [t["name"] for t in doc["shared"]["tools"]] == [t["name"] for t in ag.tools_schema]
