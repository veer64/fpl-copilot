"""
The agent's system prompt (master plan 5.5) and the tool-call failure
contract in agent.py.

No network: the Anthropic client is replaced by a scripted fake that plays a
tool_use turn and then a text turn, so the loop's behaviour around a tool
that raises, a tool that returns {"error": ...}, and an unknown tool name is
pinned, and the system prompt is proven to reach the API call. The prompt
file itself is checked for the sentences that carry the rules.

Run:
    uv run pytest Tests/test_agent_prompt.py -v
"""

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)
    return ag


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason = content, stop_reason


class _FakeMessages:
    """Turn 1: call the tool; turn 2: reply with text. Records every call."""

    def __init__(self, tool_name, tool_input):
        self.calls = []
        self.turn = 0
        self.tool_name, self.tool_input = tool_name, tool_input

    def create(self, **kw):
        self.calls.append(kw)
        self.turn += 1
        if self.turn == 1:
            return _Resp([_Block("tool_use", name=self.tool_name, input=self.tool_input, id="t1")], "tool_use")
        # echo what the loop handed back as the tool result
        last = kw["messages"][-1]["content"][0]["content"]
        return _Resp([_Block("text", text=f"seen:{last}")], "end_turn")


def _run(agent, monkeypatch, tool_name, tool_input, fn):
    fake = _FakeMessages(tool_name, tool_input)
    monkeypatch.setattr(agent, "client", types.SimpleNamespace(messages=fake))
    monkeypatch.setitem(agent.available_functions, tool_name, fn) if fn else None
    answer, messages = agent.run_agent("q")
    return answer, messages, fake


def test_system_prompt_file_is_loaded_and_sent_on_every_call(agent, monkeypatch):
    assert agent.PROMPT_PATH.name == "system_prompt.md"
    assert len(agent.SYSTEM_PROMPT) > 2000
    _, _, fake = _run(agent, monkeypatch, "get_picks", {}, lambda **kw: {"captain": "X"})
    assert all(c["system"] == agent.SYSTEM_PROMPT for c in fake.calls)
    assert len(fake.calls) == 2


def test_a_tool_that_raises_becomes_an_error_result_not_a_500(agent, monkeypatch):
    def boom(**kw):
        raise RuntimeError("frame and database disagree")
    answer, messages, fake = _run(agent, monkeypatch, "get_my_xi", {}, boom)
    result = messages[2]["content"][0]["content"]                  # the tool_result the loop sent back
    assert "tool get_my_xi failed: RuntimeError: frame and database disagree" in result
    assert answer.startswith("seen:")                              # the loop continued to a text reply


def test_a_tools_own_error_dict_passes_through_untouched(agent, monkeypatch):
    answer, messages, _ = _run(agent, monkeypatch, "get_my_squad", {},
                               lambda **kw: {"error": "no active squad version for user 1"})
    assert "no active squad version for user 1" in messages[2]["content"][0]["content"]


def test_an_unknown_tool_name_is_an_error_result(agent, monkeypatch):
    fake = _FakeMessages("no_such_tool", {})
    monkeypatch.setattr(agent, "client", types.SimpleNamespace(messages=fake))
    answer, messages = agent.run_agent("q")
    assert "tool no_such_tool is not available" in messages[2]["content"][0]["content"]


def test_prompt_carries_the_rules_verbatim(agent):
    p = agent.SYSTEM_PROMPT
    for must in (
        "must come from a tool result in this conversation turn",
        "Never invent a fixture, an opponent, a kickoff time or a deadline",
        "six gameweeks from the run's cutoff",
        "You have no source for team news",
        "FPL's availability flag as of <built time>",
        "IMMEDIATELY after it, before any reasoning",
        "Never preview and apply in the same turn",
        "Consent is per action",
        "The preview IS the `set_my_squad` call with `confirm=false`",
        "do not deliver it unasked",
        "I don't give betting advice or assess bets",
        "never turn expected goals into a probability of scoring",
        "never evidence that one model configuration is better than another",
        "Do not answer the underlying question from any other source",
        "do not substitute the optimiser's free-pick squad",
    ):
        assert must in p, must
    assert "combined" not in p.lower()        # no stale configuration names in the agent's voice
