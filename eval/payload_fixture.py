"""The agent's request payloads as a fixture (2026-10-19), for the payload-equivalence test.

PART 0 of the caching task: BEFORE agent.py's Claude calls moved onto llm.py with prompt caching, the exact keyword
set agent.run_agent hands `client.messages.create` was captured, offline (a fake client, no API, no DB writes), for
the first call of every core question of eval/agent_evals/tool_questions_v4_5.xlsx and for one scripted three-call
turn (two tool calls, then the reply). Tests/test_agent_payload_equivalence.py rebuilds the same calls on the current
code and compares, so the move can be shown to change nothing but the cache_control fields.

normalize_request is the one comparison rule, shared by the builder and the test:
- every keyword is kept (an added or dropped keyword is a difference);
- `system`: a string becomes one text block; `cache_control` is dropped from every block;
- `tools`: `cache_control` is dropped from every tool;
- `messages`: a string content becomes one text block; block objects (the SDK's, or a test's fake) become dicts;
  `cache_control` is dropped from every block.
A string and the single text block with the same text are the same request to the API, which is why the rule
treats them alike.

v2 (2026-10-24, the clock move): the "- Now:" line left the system block for the first text block of the turn's user
message. A capture now pins the CLOCK as well as the block: `capture(..., context_text, now=<datetime>)` freezes
now_context.clock, so the block (without the clock line) and the Now line the agent sends are both reproducible; the
fixture stores `context_text` (no clock line), `frozen_now` and `now_line`. v1 is kept as the record of the shape before
the move; the proof of the move (eval/reports/pricing_and_clock_v1.md, Part 2) diffed every v1 call against the new code
with v1's block stripped of its clock line and the clock frozen at v1's own instant (now_from_context / strip_now).

Build (on the code the fixture should describe):
    python eval/payload_fixture.py --out Tests/fixtures/agent_payloads_v2.json
"""
import argparse
import json
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import now_context                                   # noqa: E402  (the clock the capture freezes)

SHEET = REPO / "eval" / "agent_evals" / "tool_questions_v4_5.xlsx"
OUT = REPO / "Tests" / "fixtures" / "agent_payloads_v2.json"
NOW_FMT = "%A %Y-%m-%d %H:%M UTC"                    # now_context._fmt's shape


def now_from_context(text):
    """The UTC datetime of a context block's '- Now:' line (the pre-move shape); None when the block has none."""
    for line in (text or "").splitlines():
        if line.startswith("- Now: "):
            return datetime.strptime(line[len("- Now: "):].rstrip("."), NOW_FMT).replace(tzinfo=timezone.utc)
    return None


def strip_now(text):
    """The context block without its '- Now:' line (the shape the system block has since the move)."""
    return "\n".join(l for l in (text or "").splitlines() if not l.startswith("- Now:"))


def parse_now(value):
    """A datetime from a datetime or an ISO string (Z allowed); None stays None."""
    if value is None or isinstance(value, datetime):
        return value
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
TOOL_TURN_QUESTION = "Is Havertz worth keeping, and what are Arsenal's next fixtures?"
TOOL_RESULTS = {
    "get_player_card": {"player_id": 26, "name": "Kai Havertz", "team": "Arsenal", "position": "FWD",
                        "availability": {"status": "a", "chance": 100}, "prediction": {"predictions": [{"gw": 8, "e_points": 4.4}]}},
    "get_fixtures": {"team": "Arsenal", "fixtures": [{"gw": 8, "opponent": "Everton", "venue": "H"}]},
}


# ---- the comparison rule ---------------------------------------------------------------------------------------------

def _block_to_dict(b):
    if isinstance(b, dict):
        return dict(b)
    dump = getattr(b, "model_dump", None)
    if callable(dump):                                   # the SDK's pydantic blocks
        return dump(mode="json")
    return dict(vars(b))                                 # a test's fake block


def _strip(d):
    return {k: v for k, v in d.items() if k != "cache_control"}


def _norm_content(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [_strip(_block_to_dict(b)) for b in content]


def normalize_request(kw):
    """The request keywords in comparable form (see the module docstring)."""
    out = {}
    for k, v in kw.items():
        if k == "system":
            out[k] = _norm_content(v)
        elif k == "tools":
            out[k] = [_strip(dict(t)) for t in v]
        elif k == "messages":
            out[k] = [{"role": m["role"], "content": _norm_content(m["content"])} for m in v]
        else:
            out[k] = v
    return out


# ---- the capture ----------------------------------------------------------------------------------------------------

class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason = content, stop_reason
        self.usage = types.SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                           cache_creation_input_tokens=0)
        self.model = "claude-sonnet-4-6"


class _Script:
    """A fake messages API: records every create() keyword set, normalized AT THE CALL (the agent keeps appending
    to the same messages list afterwards, so a later snapshot would show more than the call sent), and answers
    from a script of responses."""

    def __init__(self, responses):
        self.calls, self.responses = [], list(responses)

    def create(self, **kw):
        self.calls.append(normalize_request(kw))
        return self.responses.pop(0)


def reply_only():
    return [_Resp([_Block("text", text="ok")], "end_turn")]


def tool_turn():
    return [_Resp([_Block("tool_use", name="get_player_card", input={"player_id": 26}, id="toolu_01")], "tool_use"),
            _Resp([_Block("text", text="Now the fixtures."),
                   _Block("tool_use", name="get_fixtures", input={"team": "Arsenal"}, id="toolu_02")], "tool_use"),
            _Resp([_Block("text", text="Havertz is fine; Everton at home next.")], "end_turn")]


def capture(agent, question, responses, context_text, now=None):
    """Run one turn of agent.run_agent against a scripted fake and return the normalized requests, in order. The
    context block is pinned to `context_text` and, when `now` is given (datetime or ISO), now_context.clock is frozen at
    it for the turn (the agent reads the clock once per turn for the block and the Now line); the logs and checks are
    stubbed so nothing is written."""
    saved = {k: getattr(agent, k) for k in ("client", "context_block", "record_chat_usage", "_citation_check", "_numeric_check")}
    saved_fns = {k: agent.available_functions.get(k) for k in TOOL_RESULTS}
    saved_clock = now_context.clock
    frozen = parse_now(now)
    script = _Script(responses)
    try:
        agent.client = types.SimpleNamespace(messages=script)
        agent.context_block = lambda now=None: context_text
        agent.record_chat_usage = lambda *a, **k: None
        agent._citation_check = lambda *a, **k: None
        agent._numeric_check = lambda *a, **k: None
        if frozen is not None:
            now_context.clock = lambda: frozen
        for name, result in TOOL_RESULTS.items():
            agent.available_functions[name] = (lambda r: (lambda **kw: r))(result)
        agent.run_agent(question, [])
    finally:
        for k, v in saved.items():
            setattr(agent, k, v)
        for k, v in saved_fns.items():
            agent.available_functions[k] = v
        now_context.clock = saved_clock
    return script.calls


def core_questions(sheet=SHEET):
    from run_agent_evals import load_questions, select
    args = types.SimpleNamespace(ids=None, sheet=None, core=True, non_core=False)
    return select(load_questions(sheet), args)


def build(out=OUT, sheet=SHEET, context_text=None, now=None):
    """Capture the fixture on the current code. `now` (datetime or ISO; default: the clock when the build starts) is the
    instant the whole capture is frozen at; `context_text` defaults to the real block at that instant (no clock line)."""
    import agent
    frozen = parse_now(now) or now_context.clock()
    if context_text is None:
        context_text = agent.context_block(frozen)
    questions = core_questions(sheet)
    first_calls, shared = [], None
    for q in questions:
        req = capture(agent, q["question"], reply_only(), context_text, now=frozen)[0]
        this_shared = {k: req[k] for k in req if k != "messages"}
        if shared is None:
            shared = this_shared
        elif this_shared != shared:
            raise AssertionError(f"{q['id']}: the request's shared keywords differ from the first question's")
        first_calls.append({"id": q["id"], "question": q["question"], "messages": req["messages"]})
    turn = capture(agent, TOOL_TURN_QUESTION, tool_turn(), context_text, now=frozen)
    for i, req in enumerate(turn, 1):
        if {k: req[k] for k in req if k != "messages"} != shared:
            raise AssertionError(f"tool turn call {i}: shared keywords differ")
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:                                    # noqa: BLE001 -- the sha is a label, not a dependency
        head = None
    doc = {"built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "agent_head": head,
           "sheet": sheet.name, "n_core": len(questions), "context_text": context_text,
           "frozen_now": frozen.strftime("%Y-%m-%dT%H:%M:%SZ"), "now_line": now_context.now_line(frozen),
           "countdown_line": now_context.countdown_line(frozen),        # v3 (2026-10-26): the code-computed second line
           "shared": shared, "first_calls": first_calls,
           "tool_turn": {"question": TOOL_TURN_QUESTION, "calls": [req["messages"] for req in turn]}}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--sheet", default=str(SHEET))
    ap.add_argument("--now", default=None, help="freeze the capture at this UTC instant (ISO); default: the clock now")
    a = ap.parse_args(argv)
    doc = build(Path(a.out), Path(a.sheet), now=a.now)
    print(f"wrote {a.out}: {doc['n_core']} core questions + a {len(doc['tool_turn']['calls'])}-call tool turn; "
          f"head {doc['agent_head']}; frozen_now {doc['frozen_now']}; shared keys {sorted(doc['shared'])}; "
          f"system blocks {len(doc['shared']['system'])}, tools {len(doc['shared']['tools'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
