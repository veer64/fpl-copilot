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

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                               # noqa: E402

FIXTURE = REPO / "Tests" / "fixtures" / "agent_payloads_v9.json"   # v9 (2026-11-16, Prompt R3d): a NORMAL turn -- v8 plus the written lists (four tool descriptions, three prompt changes)
V8 = REPO / "Tests" / "fixtures" / "agent_payloads_v8.json"        # v8 (2026-11-16, Prompt R3c): a NORMAL turn -- v7 plus the written lists (captain_pick added, four tools changed, three prompt changes)
V7 = REPO / "Tests" / "fixtures" / "agent_payloads_v7.json"        # v7 (2026-11-16, Prompt R3b): a NORMAL turn -- v6 plus the written lists (five tool descriptions / schemas, two prompt changes); a draft turn still equals v5 (Tests/test_draft_payload.py)
V6 = REPO / "Tests" / "fixtures" / "agent_payloads_v6.json"        # v6 (2026-11-16, Prompt R3): max_tokens 2,048, two code-built tools, three tool descriptions, the written list of prompt changes
PROMPT_CHANGES_V7 = REPO / "Tests" / "fixtures" / "agent_prompt_v6_to_v7.json"   # the written list: every prompt change of R3b, old -> new
TOOL_CHANGES_V7 = REPO / "Tests" / "fixtures" / "agent_tools_v6_to_v7.json"      # the written list: every tool change of R3b, old -> new
PROMPT_CHANGES_V8 = REPO / "Tests" / "fixtures" / "agent_prompt_v7_to_v8.json"   # the written list: every prompt change of R3c, old -> new
TOOL_CHANGES_V8 = REPO / "Tests" / "fixtures" / "agent_tools_v7_to_v8.json"      # the written list: every tool change of R3c, old -> new
PROMPT_CHANGES_V9 = REPO / "Tests" / "fixtures" / "agent_prompt_v8_to_v9.json"   # the written list: every prompt change of R3d, old -> new
TOOL_CHANGES_V9 = REPO / "Tests" / "fixtures" / "agent_tools_v8_to_v9.json"      # the written list: every tool change of R3d, old -> new
V5 = REPO / "Tests" / "fixtures" / "agent_payloads_v5.json"        # v5 (2026-10-27, Prompt E): set_my_squad's ticket sentence + preview_ticket; v4 lives on the parked branch agent-sonnet5
PROMPT_CHANGES = REPO / "Tests" / "fixtures" / "agent_prompt_v5_to_v6.json"   # the written list: every prompt change of R3, old -> new
V1 = REPO / "Tests" / "fixtures" / "agent_payloads_v1.json"
V2 = REPO / "Tests" / "fixtures" / "agent_payloads_v2.json"
V3 = REPO / "Tests" / "fixtures" / "agent_payloads_v3.json"        # v3 (2026-10-26): the countdown line beside the Now line


def _first_block(doc):
    """The first text block of the question message: the Now line, then the code-computed countdown when one exists."""
    return doc["now_line"] + (f"\n{doc['countdown_line']}" if doc.get("countdown_line") else "")


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
    assert doc["shared"]["model"] == "claude-sonnet-4-6" and doc["shared"]["max_tokens"] == 2048   # R3: was 1,024 (v5)
    # v2: the clock is pinned beside the block, the block carries no clock line, the Now line is its own field
    assert doc["frozen_now"] and doc["now_line"].startswith("- Now: ")
    assert pf.now_from_context(doc["context_text"]) is None and "- Now:" not in doc["context_text"]
    assert pf.now_from_context(doc["now_line"]).strftime("%Y-%m-%dT%H:%M:00Z") == doc["frozen_now"]
    assert doc["countdown_line"].startswith("Next deadline: GW") and " UTC — in " in doc["countdown_line"]
    assert V1.exists() and V2.exists() and V3.exists() and V5.exists()     # the earlier records are kept


# ---- Prompt R3 (2026-11-16): v6 is v5 plus a WRITTEN list, and nothing else ---------------------------------------------------------
# The brief: "a test proves v6 differs from v5 ONLY by the new tools, the get_prediction schema and max_tokens". The owner
# accepted (checkpoint (d) 2, and "go" change 1) that the list is longer and must be written down: the two new tools; the
# descriptions / schemas of get_prediction, propose_transfers and get_price_movements; max_tokens; and the prompt changes of
# Tests/fixtures/agent_prompt_v5_to_v6.json. This test rebuilds v5 from v6 by undoing exactly that list.
R3_NEW_TOOLS = ["rank_players", "review_my_squad"]
R3_CHANGED_TOOLS = ["get_prediction", "propose_transfers", "get_price_movements"]


def test_v6_is_v5_with_the_written_list_of_changes_and_nothing_else():
    v5, v6 = json.loads(V5.read_text(encoding="utf-8")), json.loads(V6.read_text(encoding="utf-8"))   # R3b: v6 is a record now (was _fixture())
    changes = json.loads(PROMPT_CHANGES.read_text(encoding="utf-8"))["changes"]
    # 1. everything that is not `shared` (the 109 questions' messages, the tool turn, the clock, the context block) is v5's
    labels = ("built_at", "agent_head", "shared")
    assert {k: v for k, v in v6.items() if k not in labels} == {k: v for k, v in v5.items() if k not in labels}
    assert sorted(v6["shared"]) == sorted(v5["shared"]) == ["max_tokens", "model", "system", "tools"]
    assert v6["shared"]["model"] == v5["shared"]["model"]
    # 2. max_tokens
    assert (v5["shared"]["max_tokens"], v6["shared"]["max_tokens"]) == (1024, 2048)
    # 3. the tools: two appended, three changed, the other 21 identical and in the same order
    t5, t6 = v5["shared"]["tools"], v6["shared"]["tools"]
    assert [t["name"] for t in t6 if t["name"] not in R3_NEW_TOOLS] == [t["name"] for t in t5]
    assert [t["name"] for t in t6][-3:] == R3_NEW_TOOLS + ["search_news"]         # inserted before the last tool, which stays last
    t6 = [t for t in t6 if t["name"] not in R3_NEW_TOOLS]
    differing = [a["name"] for a, b in zip(t5, t6) if a != b]
    assert differing == R3_CHANGED_TOOLS
    for name in R3_CHANGED_TOOLS:
        a, b = next(t for t in t5 if t["name"] == name), next(t for t in t6 if t["name"] == name)
        assert set(a) == set(b) == {"name", "description", "input_schema"} and a["description"] != b["description"]
        assert a["input_schema"]["required"] == b["input_schema"]["required"]
    old_pred = next(t for t in t5 if t["name"] == "get_prediction")["input_schema"]["properties"]
    new_pred = next(t for t in t6 if t["name"] == "get_prediction")["input_schema"]["properties"]
    assert {k: v for k, v in new_pred.items() if k != "horizon"} == old_pred and "horizon" in new_pred    # the schema: + horizon
    for name in ("propose_transfers", "get_price_movements"):                # same arguments; a description of one of them reworded
        a, b = next(t for t in t5 if t["name"] == name), next(t for t in t6 if t["name"] == name)
        assert set(a["input_schema"]["properties"]) == set(b["input_schema"]["properties"])
        assert {k: v.get("type") for k, v in a["input_schema"]["properties"].items()} == \
            {k: v.get("type") for k, v in b["input_schema"]["properties"].items()}
    # 4. the system prompt: undo the written list, newest change first, each exactly once -> v5's text byte for byte
    s5, s6 = "".join(b["text"] for b in v5["shared"]["system"]), "".join(b["text"] for b in v6["shared"]["system"])
    assert len(v5["shared"]["system"]) == len(v6["shared"]["system"]) == 1
    text = s6
    for ch in reversed(changes):
        assert text.count(ch["new"]) == 1, ch["why"]
        text = text.replace(ch["new"], ch["old"])
    assert text == s5
    for ch in changes:
        assert s5.count(ch["old"]) == 1 and ch["old"] != ch["new"], ch["why"]
    assert len(changes) == 9


# ---- Prompt R3b (2026-11-16): v7 is v6 plus two WRITTEN lists, and nothing else ----------------------------------------------------
# The brief: "fixture v7 for normal turns; the test rebuilds v6 by undoing a written list of every change and asserts byte
# equality". The lists: Tests/fixtures/agent_tools_v6_to_v7.json (five tools: description edits, and the schema before and
# after for the three whose arguments changed) and Tests/fixtures/agent_prompt_v6_to_v7.json (two prompt changes). No tool is
# added, removed or moved; max_tokens, the model, every question's messages and the tool turn are v6's.
R3B_CHANGED_TOOLS = ["compare_players", "best_squad_from_scratch", "build_squad_from_scratch", "propose_transfers", "get_fixtures"]


def test_v7_is_v6_with_the_written_lists_of_changes_and_nothing_else():
    v6, v7 = json.loads(V6.read_text(encoding="utf-8")), json.loads(V7.read_text(encoding="utf-8"))   # R3c: v7 is a record now (was _fixture())
    prompt_changes = json.loads(PROMPT_CHANGES_V7.read_text(encoding="utf-8"))["changes"]
    tool_changes = json.loads(TOOL_CHANGES_V7.read_text(encoding="utf-8"))["changes"]
    # 1. the tools: undo every listed change on v7's tools -> v6's tools
    tools = json.loads(json.dumps(v7["shared"]["tools"]))
    by_name = {t["name"]: t for t in tools}
    assert [c["tool"] for c in tool_changes] == R3B_CHANGED_TOOLS
    for ch in tool_changes:
        tool = by_name[ch["tool"]]
        for d in reversed(ch["description"]):
            assert tool["description"].count(d["new"]) == 1 and d["old"] != d["new"], ch["tool"]
            tool["description"] = tool["description"].replace(d["new"], d["old"])
        if "input_schema" in ch:
            assert tool["input_schema"] == ch["input_schema"]["new"] != ch["input_schema"]["old"], ch["tool"]
            tool["input_schema"] = ch["input_schema"]["old"]
    assert [ch["tool"] for ch in tool_changes if "input_schema" in ch] == ["compare_players", "propose_transfers", "get_fixtures"]
    # 2. the system prompt: undo the written list, newest change first, each exactly once
    assert len(v6["shared"]["system"]) == len(v7["shared"]["system"]) == 1
    text = v7["shared"]["system"][0]["text"]
    for ch in reversed(prompt_changes):
        assert text.count(ch["new"]) == 1 and ch["old"] != ch["new"], ch["why"]
        text = text.replace(ch["new"], ch["old"])
    assert len(prompt_changes) == 2
    # 3. v7 with both lists undone IS v6, byte for byte (the two labels that say when and where a fixture was built aside)
    rebuilt = {**v7, "shared": {**v7["shared"], "tools": tools, "system": [{**v7["shared"]["system"][0], "text": text}]}}
    labels = ("built_at", "agent_head")
    a = json.dumps({k: v for k, v in rebuilt.items() if k not in labels}, sort_keys=True, ensure_ascii=False)
    b = json.dumps({k: v for k, v in v6.items() if k not in labels}, sort_keys=True, ensure_ascii=False)
    assert a.encode("utf-8") == b.encode("utf-8")
    # 4. and the lists are not empty words: each tool they name differs between the two fixtures, and no other does
    t6, t7 = {t["name"]: t for t in v6["shared"]["tools"]}, {t["name"]: t for t in v7["shared"]["tools"]}
    assert [t["name"] for t in v6["shared"]["tools"]] == [t["name"] for t in v7["shared"]["tools"]]
    assert sorted(n for n in t6 if t6[n] != t7[n]) == sorted(R3B_CHANGED_TOOLS)
    assert (v6["shared"]["max_tokens"], v7["shared"]["max_tokens"], v6["shared"]["model"]) == (2048, 2048, v7["shared"]["model"])


# ---- Prompt R3c (2026-11-16): v8 is v7 plus two WRITTEN lists, and nothing else ----------------------------------------------------
# The brief: "fixture v8 for normal turns, the test rebuilds v7 by undoing a written list of every change". The lists:
# Tests/fixtures/agent_tools_v7_to_v8.json (captain_pick added before search_news; get_my_xi, set_my_squad, get_league_table,
# get_fixtures, compare_players and compare_predictions changed: a description edit each, and the schema before and after for the
# one whose arguments changed) and
# Tests/fixtures/agent_prompt_v7_to_v8.json (three prompt changes). max_tokens, the model, every question's messages and the tool
# turn are v7's.
R3C_ADDED_TOOLS = ["captain_pick"]
R3C_CHANGED_TOOLS = ["get_my_xi", "set_my_squad", "get_league_table", "get_fixtures", "compare_players", "compare_predictions"]


def test_v8_is_v7_with_the_written_lists_of_changes_and_nothing_else():
    v7, v8 = json.loads(V7.read_text(encoding="utf-8")), json.loads(V8.read_text(encoding="utf-8"))   # R3d: v8 is a record now (was _fixture())
    prompt_changes = json.loads(PROMPT_CHANGES_V8.read_text(encoding="utf-8"))["changes"]
    tool_changes = json.loads(TOOL_CHANGES_V8.read_text(encoding="utf-8"))["changes"]
    tools = json.loads(json.dumps(v8["shared"]["tools"]))
    assert [c["tool"] for c in tool_changes if "tool_json" in c] == R3C_ADDED_TOOLS
    assert sorted(c["tool"] for c in tool_changes if "tool_json" not in c) == sorted(R3C_CHANGED_TOOLS)
    for ch in tool_changes:                                              # 1. undo every listed tool change
        if "tool_json" in ch:
            assert tools[ch["added_at"]] == ch["tool_json"]
            del tools[ch["added_at"]]
            continue
        tool = next(t for t in tools if t["name"] == ch["tool"])
        for d in reversed(ch.get("description") or []):
            assert tool["description"].count(d["new"]) == 1 and d["old"] != d["new"], ch["tool"]
            tool["description"] = tool["description"].replace(d["new"], d["old"])
        if "input_schema" in ch:
            assert tool["input_schema"] == ch["input_schema"]["new"] != ch["input_schema"]["old"], ch["tool"]
            tool["input_schema"] = ch["input_schema"]["old"]
    assert [c["tool"] for c in tool_changes if "input_schema" in c] == ["get_league_table"]
    text = v8["shared"]["system"][0]["text"]                             # 2. undo the prompt's written list, newest first
    for ch in reversed(prompt_changes):
        assert text.count(ch["new"]) == 1 and ch["old"] != ch["new"], ch["why"]
        text = text.replace(ch["new"], ch["old"])
    assert len(prompt_changes) == 3 and len(v7["shared"]["system"]) == len(v8["shared"]["system"]) == 1
    rebuilt = {**v8, "shared": {**v8["shared"], "tools": tools, "system": [{**v8["shared"]["system"][0], "text": text}]}}
    labels = ("built_at", "agent_head")                                  # 3. ... IS v7, byte for byte
    a = json.dumps({k: v for k, v in rebuilt.items() if k not in labels}, sort_keys=True, ensure_ascii=False)
    b = json.dumps({k: v for k, v in v7.items() if k not in labels}, sort_keys=True, ensure_ascii=False)
    assert a.encode("utf-8") == b.encode("utf-8")
    t7, t8 = {t["name"]: t for t in v7["shared"]["tools"]}, {t["name"]: t for t in v8["shared"]["tools"]}
    assert sorted(n for n in t7 if t7[n] != t8[n]) == sorted(R3C_CHANGED_TOOLS)
    assert [t["name"] for t in v8["shared"]["tools"]][-2:] == ["captain_pick", "search_news"]


# ---- Prompt R3d (2026-11-16): v9 is v8 plus two WRITTEN lists, and nothing else ----------------------------------------------------
# The brief: "fixture v9 for normal turns; the test rebuilds v8 by undoing a written list of every change". The lists:
# Tests/fixtures/agent_tools_v8_to_v9.json (four descriptions: compare_players, get_player_card, set_my_squad, propose_transfers;
# no tool added, removed or moved, no schema changed) and Tests/fixtures/agent_prompt_v8_to_v9.json (three prompt changes).
R3D_CHANGED_TOOLS = ["compare_players", "get_player_card", "set_my_squad", "propose_transfers"]


def test_v9_is_v8_with_the_written_lists_of_changes_and_nothing_else():
    v8, v9 = json.loads(V8.read_text(encoding="utf-8")), _fixture()
    prompt_changes = json.loads(PROMPT_CHANGES_V9.read_text(encoding="utf-8"))["changes"]
    tool_changes = json.loads(TOOL_CHANGES_V9.read_text(encoding="utf-8"))["changes"]
    tools = json.loads(json.dumps(v9["shared"]["tools"]))
    assert sorted(c["tool"] for c in tool_changes) == sorted(R3D_CHANGED_TOOLS) and not any("input_schema" in c for c in tool_changes)
    for ch in tool_changes:
        tool = next(t for t in tools if t["name"] == ch["tool"])
        for d in reversed(ch["description"]):
            assert tool["description"].count(d["new"]) == 1 and d["old"] != d["new"], ch["tool"]
            tool["description"] = tool["description"].replace(d["new"], d["old"])
    text = v9["shared"]["system"][0]["text"]
    for ch in reversed(prompt_changes):
        assert text.count(ch["new"]) == 1 and ch["old"] != ch["new"], ch["why"]
        text = text.replace(ch["new"], ch["old"])
    assert len(prompt_changes) == 3 and len(v8["shared"]["system"]) == len(v9["shared"]["system"]) == 1
    rebuilt = {**v9, "shared": {**v9["shared"], "tools": tools, "system": [{**v9["shared"]["system"][0], "text": text}]}}
    labels = ("built_at", "agent_head")
    a = json.dumps({k: v for k, v in rebuilt.items() if k not in labels}, sort_keys=True, ensure_ascii=False)
    b = json.dumps({k: v for k, v in v8.items() if k not in labels}, sort_keys=True, ensure_ascii=False)
    assert a.encode("utf-8") == b.encode("utf-8")
    t8, t9 = {t["name"]: t for t in v8["shared"]["tools"]}, {t["name"]: t for t in v9["shared"]["tools"]}
    assert [t["name"] for t in v8["shared"]["tools"]] == [t["name"] for t in v9["shared"]["tools"]]
    assert sorted(n for n in t8 if t8[n] != t9[n]) == sorted(R3D_CHANGED_TOOLS)


def test_v9s_prompt_and_v5s_prompt_are_the_two_prompt_files(monkeypatch):
    """R3d: was test_v8s_prompt_and_v5s_prompt_are_the_two_prompt_files (R3c; v7 in R3b, v6 in R3) -- the NORMAL turn's
    fixture is v9 now."""
    ag = _agent(monkeypatch)
    v5, v9 = json.loads(V5.read_text(encoding="utf-8")), _fixture()
    assert "".join(b["text"] for b in v9["shared"]["system"]) == f"{v9['context_text']}\n\n{ag.SYSTEM_PROMPT}"
    assert "".join(b["text"] for b in v5["shared"]["system"]) == f"{v5['context_text']}\n\n{ag.DRAFT_SYSTEM_PROMPT}"   # the frozen copy
    assert v5["shared"]["tools"] == [pf._strip(t) for t in ag.DRAFT_BASE_TOOLS]                                       # the frozen tools
    assert v9["shared"]["tools"] == [pf._strip(t) for t in ag.tools_schema]


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
        assert content[0] == {"type": "text", "text": _first_block(doc)}, item["id"]
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
        assert call[0]["content"][0] == {"type": "text", "text": _first_block(doc)}
        assert all(m["content"][0]["type"] == "tool_result" for m in call[1:] if m["role"] == "user")


def test_the_shared_parts_are_the_prompt_file_and_the_tool_schema(monkeypatch):
    ag = _agent(monkeypatch)
    doc = _fixture()
    system_text = "".join(b["text"] for b in doc["shared"]["system"])
    assert system_text == f"{doc['context_text']}\n\n{ag.SYSTEM_PROMPT}"
    assert [t["name"] for t in doc["shared"]["tools"]] == [t["name"] for t in ag.tools_schema]


# ---- Prompt L (2026-10-30): Langfuse tracing ON and OFF send the same bytes (T1) -------------------------------------------
# The request agent.run_agent hands the client is captured RAW at the call (json of the keyword set, cache_control and all)
# with tracing OFF and ON -- ON once with an in-memory fake Langfuse client and once with the real SDK pointed at a closed
# local port -- and the two must be byte-identical; ON must also equal fixture v5 under the comparison rule above.

class _FakeObs:
    def __init__(self, backend):
        self.backend, self.trace_id, self.id = backend, "0" * 32, "0" * 16

    def start_observation(self, **kw):
        self.backend.n += 1
        return _FakeObs(self.backend)

    def update(self, **kw):
        self.backend.n += 1
        return self

    def end(self, **kw):
        self.backend.n += 1
        return self

    def score_trace(self, **kw):
        self.backend.n += 1


class _FakeLangfuse:
    def __init__(self):
        self.n = 0

    def start_observation(self, **kw):
        self.n += 1
        return _FakeObs(self)

    def flush(self):
        pass

    def shutdown(self):
        pass

    def propagate(self, **kw):
        import contextlib
        self.n += 1
        return contextlib.nullcontext()


_ORIGINAL_SCRIPT = pf._Script                              # subclass the original, never a patched one


def _raw_script(sink):
    class RawScript(_ORIGINAL_SCRIPT):
        def create(self, **kw):
            sink.append(json.dumps(kw, default=pf._block_to_dict, ensure_ascii=False))
            return super().create(**kw)
    return RawScript


def _set_tracing(monkeypatch, mode):
    import tracing
    if mode == "off":
        monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    else:
        monkeypatch.setenv("LANGFUSE_ENABLED", "1")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test-payload-" + mode)
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")
        monkeypatch.setenv("LANGFUSE_LOG_USER_TEXT", "1")
    tracing._reset()
    fake = None
    if mode == "fake":
        fake = _FakeLangfuse()
        monkeypatch.setattr(tracing, "_make_backend", lambda: (fake, fake.propagate))
    return tracing, fake


def _capture_all(ag, monkeypatch, doc, sink):
    monkeypatch.setattr(pf, "_Script", _raw_script(sink))
    turn = pf.capture(ag, doc["tool_turn"]["question"], pf.tool_turn(), doc["context_text"], now=doc["frozen_now"])
    firsts = [pf.capture(ag, item["question"], pf.reply_only(), doc["context_text"], now=doc["frozen_now"])[0]
              for item in doc["first_calls"]]
    return turn, firsts


@pytest.mark.parametrize("mode", ["fake", "sdk_unreachable"])
def test_tracing_on_and_off_send_byte_identical_requests_equal_to_v5(monkeypatch, mode):
    ag = _agent(monkeypatch)
    doc = _fixture()
    import tracing
    _set_tracing(monkeypatch, "off")
    raw_off = []
    _capture_all(ag, monkeypatch, doc, raw_off)
    assert tracing.LAST_TURN.get("enabled") is False
    _, fake = _set_tracing(monkeypatch, mode)
    raw_on = []
    try:
        turn, firsts = _capture_all(ag, monkeypatch, doc, raw_on)
        assert tracing.LAST_TURN.get("enabled") is True and tracing.LAST_TURN.get("errors") == 0
        if fake is not None:
            assert fake.n > 0                                   # the fake client was really called
    finally:
        tracing.shutdown(timeout_s=1.0)
        tracing._reset()
    assert len(raw_on) == len(raw_off) == 3 + len(doc["first_calls"])
    assert raw_on == raw_off, "tracing changed the bytes of a request"
    for i, req in enumerate(turn):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"] and req["messages"] == doc["tool_turn"]["calls"][i]
    for item, req in zip(doc["first_calls"], firsts):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"] and req["messages"] == item["messages"], item["id"]


# ---- Prompt A (2026-10-31): the LangGraph engine sends the same bytes (G15) --------------------------------------------
# AGENT_ENGINE=graph runs agent_graph.py's StateGraph over the loop's own step functions. Every request it hands the
# client must be byte-identical to the loop's (the raw json of the keyword set, cache_control and all) and equal fixture
# v5 under the comparison rule above, with tracing off and on (the fake client); every capture must really have gone
# through the graph.

@pytest.mark.parametrize("mode", ["off", "fake"])
def test_g15_the_graph_engine_sends_byte_identical_requests_equal_to_v5(monkeypatch, mode):
    ag = _agent(monkeypatch)
    doc = _fixture()
    import tracing
    import agent_graph
    ran = []
    real_run_turn = agent_graph.run_turn

    def counting(*a, **k):
        ran.append(1)
        return real_run_turn(*a, **k)
    monkeypatch.setattr(agent_graph, "run_turn", counting)
    _set_tracing(monkeypatch, "off")
    monkeypatch.setenv("AGENT_ENGINE", "loop")
    raw_loop = []
    _capture_all(ag, monkeypatch, doc, raw_loop)
    assert ran == []                                           # the loop ran the loop
    _, fake = _set_tracing(monkeypatch, mode)
    monkeypatch.setenv("AGENT_ENGINE", "graph")
    raw_graph = []
    try:
        turn, firsts = _capture_all(ag, monkeypatch, doc, raw_graph)
        if fake is not None:
            assert fake.n > 0 and tracing.LAST_TURN.get("errors") == 0
    finally:
        tracing.shutdown(timeout_s=1.0)
        tracing._reset()
    assert len(ran) == 1 + len(doc["first_calls"])             # every capture went through the graph
    assert len(raw_graph) == len(raw_loop) == 3 + len(doc["first_calls"])
    assert raw_graph == raw_loop, "the graph engine changed the bytes of a request"
    for i, req in enumerate(turn):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"] and req["messages"] == doc["tool_turn"]["calls"][i]
    for item, req in zip(doc["first_calls"], firsts):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"] and req["messages"] == item["messages"], item["id"]
