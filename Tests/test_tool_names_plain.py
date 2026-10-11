"""Part 4 of the smoke fixes (2026-10-10): tool names reaching users.

The wildcard answer ended "run the full proposed wildcard squad as a `build_squad_from_scratch`".
Section 9 of the prompt forbids tool names, but the tools' own strings carried them ("use
resolve_player", "call get_my_xi for that", "the number get_my_xi reports") and the model repeats
what it is handed. Three locks:

  (a) the tools' human-readable strings (errors, notes, captions) name no tool -- an ast scan of
      every string literal in the tool modules, with an allowlist of the few structured values
      that are not prose (provenance stamps, a payload's "tool" field, health diagnostics);
  (b) agent.replace_tool_names rewrites any exact tool name in the model's final text, with or
      without backticks or brackets, into a short plain phrase before the Sources list is added;
      the RAW reply (canary scoring, the numeric checker) is untouched. Every tool in tools_schema
      must have a phrase, so a new tool cannot be missed;
  (c) the prompt's tool-name rule says it covers every tool, old and new.

No network: agent is imported with a dummy key; the fake client answers from memory.
"""
import ast
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import agent                                               # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402

NAMES = [t["name"] for t in agent.tools_schema]
TOOL_NAME = re.compile(r"\b(" + "|".join(sorted(NAMES, key=len, reverse=True)) + r")\b")

# The tool modules whose strings travel to the model (and from there to the user).
TOOL_MODULES = ["model_tools.py", "squad_store.py", "fixtures_tool.py", "explain.py", "quantiles.py",
                "actuals_tool.py", "league_table.py", "match_stats.py", "prices_tool.py", "news_search.py",
                "now_context.py"]

# Structured values, never prose: provenance stamps, a payload's "tool" field, the health()
# diagnostics that Tests/test_model_degraded_health.py pins, SQL and a DB purpose label.
ALLOWED = (
    lambda s: s.startswith("model_tools."),                         # created_by provenance stamps
    lambda s: s in ("compare_runs", "set_my_squad", "search_news"),  # explain_with.tool, kind, purpose
    lambda s: s.startswith("tool surface: "),                       # health() reasons (diagnostics)
    lambda s: s.startswith("get_prediction only"),                  # health() covers line
    lambda s: s.lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "WITH")),
)


def _string_literals(path):
    """Every string literal in the module that is not a docstring (prose the model can see)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc_nodes.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_nodes:
            out.append((node.lineno, node.value))
    return out


def tool_name_strings(modules=TOOL_MODULES):
    """[(file, line, text)] of every non-docstring string literal that names a tool and is not allowed."""
    hits = []
    for name in modules:
        path = REPO / name
        if not path.exists():
            continue
        for lineno, s in _string_literals(path):
            if TOOL_NAME.search(s) and not any(ok(s) for ok in ALLOWED):
                hits.append((name, lineno, s))
    return hits


# ------------------------------------------------------------------ (a) the source strings
def test_no_tool_module_string_names_a_tool():
    hits = tool_name_strings()
    assert hits == [], "\n".join(f"{f}:{n}: {s[:120]!r}" for f, n, s in hits)


def test_the_known_strings_are_in_plain_words(monkeypatch):
    monkeypatch.setattr(mt, "_gw_deadlines", lambda: {})
    samples = [
        mt.BAD_ELEMENT_ID,
        mt._horizon_check(3, 6, 11, 24)["error"],
        mt._horizon_check(14, 6, 11, 24)["error"],
        squad_store.ROLES_MEANING,
        mt._not_played_yet(9, [1, 2, 3, 4, 5])["error"],
        mt.LINEUP_NEXT_STEP,
    ]
    for s in samples:
        assert not TOOL_NAME.search(s), s


# ------------------------------------------------------------------ (b) the lock
def test_every_tool_in_the_schema_has_a_plain_phrase():
    missing = [n for n in NAMES if n not in agent.TOOL_PLAIN_PHRASES]
    assert missing == [], missing
    for name, phrase in agent.TOOL_PLAIN_PHRASES.items():
        assert phrase.strip() and not TOOL_NAME.search(phrase), (name, phrase)


def test_names_are_replaced_with_or_without_backticks_and_brackets():
    text = ("I can run `build_squad_from_scratch` for you, or get_wildcard_gap() -- "
            "and (get_my_xi) is what gave the 9.4.")
    out, n = agent.replace_tool_names(text)
    assert n == 3, (n, out)
    assert not TOOL_NAME.search(out), out
    assert "`" not in out and "()" not in out, out
    assert agent.TOOL_PLAIN_PHRASES["build_squad_from_scratch"] in out
    assert agent.TOOL_PLAIN_PHRASES["get_wildcard_gap"] in out
    assert "(" + agent.TOOL_PLAIN_PHRASES["get_my_xi"] + ")" in out
    assert "9.4" in out


def test_a_reply_without_a_tool_name_is_untouched():
    text = "Haaland is expected to score 5.5 points in GW7; a likely range is 2 to 10."
    out, n = agent.replace_tool_names(text)
    assert (out, n) == (text, 0)


def test_a_name_inside_another_word_is_left_alone():
    out, n = agent.replace_tool_names("the list_players_v2 label and get_picksy")
    assert n == 0 and "list_players_v2" in out and "get_picksy" in out


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason = content, stop_reason


class _Reply:
    def __init__(self, text):
        self.text = text

    def create(self, **kw):
        return _Resp([_Block("text", text=self.text)], "end_turn")


def test_the_lock_rewrites_the_answer_and_leaves_the_raw_text_for_the_checks(monkeypatch):
    raw = "The gap is 55.9 points. I can run the full squad as a `build_squad_from_scratch` if you like."
    seen = {}
    monkeypatch.setattr(agent, "client", types.SimpleNamespace(messages=_Reply(raw)))
    monkeypatch.setattr(agent, "_citation_check", lambda turn_id, text, ids: seen.setdefault("citation", text))
    monkeypatch.setattr(agent, "_numeric_check", lambda turn_id, text, messages: seen.setdefault("numeric", text))
    monkeypatch.setattr(agent, "record_chat_usage", lambda *a, **k: None)
    answer, messages = agent.run_agent("Should I wildcard?")
    assert seen["citation"] == raw and seen["numeric"] == raw             # the checks see the raw text
    assert "build_squad_from_scratch" not in answer and "`" not in answer
    assert agent.TOOL_PLAIN_PHRASES["build_squad_from_scratch"] in answer
    assert "55.9" in answer
    assert agent.LAST_TURN["tool_names_replaced"] == 1
    assert messages[-1]["content"][0].text == raw                           # the history keeps the raw text


# ------------------------------------------------------------------ (c) the prompt
def test_the_prompt_rule_covers_every_tool_old_and_new():
    p = agent.SYSTEM_PROMPT
    assert "Never mention tool names, run ids, issue numbers, code, formulas, variable names or model jargon" in p
    assert "every tool, old and new" in p
    assert "a fresh squad build" in p and "the wildcard comparison" in p
