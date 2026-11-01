"""Prompt P6 Part 2 (2026-11-01): the round cap, on both engines.

The loop had no limit on model calls per turn (its guard is "no text and no tool call"). agent.MAX_TOOL_ROUNDS = max(12, 2 x
the most model calls one turn made in the Langfuse traces of production + eval, 30 Oct - 1 Nov: 6) = 12. When the turn has
made MAX_TOOL_ROUNDS model calls and the latest response still asks for a tool, the turn ends with agent.ROUND_CAP_REPLY: no
further model call, the response's tool calls are not run (no call would read their results), the history ends on the reply
(never on an unanswered tool call), [round cap: ...] is logged, the usage row is written, the trace's metadata says
round_cap=true, and there is no fact check (no span, no score) -- as with the loop guard.

RC1 an endless tool turn stops at the cap on both engines, the engines agreeing on everything test_agent_graph compares.
RC2 a turn below the cap is unchanged (the answer on the last allowed call; a send-back after it is not capped).
RC3 LangGraph's recursion limit is still far above the cap, and the cap -- not the limit -- ends an endless turn.
RC4 the value. RC5 at the cap, a response with no tool call still takes its old path (the answer, or the loop guard)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_agent_graph import h, _both, _Raw, ROUND, ANSWER          # noqa: E402,F401  (h: the harness fixture)
from test_tracing import _Block, _Resp, _text, _tool, XI, RIGHT, WRONG, QUESTION   # noqa: E402
import turn_context                                                  # noqa: E402

CAPPED_REPLY = "I couldn't finish that answer within the step limit. Please ask a narrower question."
LONGEST_TRACED_TURN = 6     # Part 0: the most llm_call generations in one trace (production max 4, eval max 6), 30 Oct - 1 Nov


def _root(s):
    return [o for o in s["trace"]["observations"] if o["parent"] is None][0]


def _endless(n):
    return lambda: [_tool("get_my_xi") for _ in range(n)]


def test_rc1_an_endless_tool_turn_stops_at_the_cap_on_both_engines(h, capsys):
    cap = h.ag.MAX_TOOL_ROUNDS
    ran = []
    h.mp.setitem(h.ag.available_functions, "get_my_xi", lambda **kw: ran.append(1) or XI)
    s = _both(h, _endless(cap + 5), ROUND * (cap - 1) + ["call_model", "round_cap"])
    assert s["answer"] == h.ag.ROUND_CAP_REPLY == CAPPED_REPLY
    assert len(s["requests"]) == cap                                   # no model call after the cap
    assert len(ran) == 2 * (cap - 1)                                   # both engines: the capped response's call never ran
    assert [w[0] for w in s["writes"]] == ["chat_usage"] and s["writes"][0][1][1] == cap   # the usage row: cap API calls
    hist = s["history"]
    assert hist[-1] == {"role": "assistant", "content": [{"type": "text", "text": CAPPED_REPLY}]}
    uses = [b["id"] for m in hist if m["role"] == "assistant" and isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_use"]
    results = [b["tool_use_id"] for m in hist if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    assert len(uses) == len(results) == cap - 1                        # every tool call in the history has its result
    assert s["last_turn"]["round_cap"] == {"rounds": cap, "pending_tools": ["get_my_xi"]}
    assert "guard" not in s["last_turn"] and s["last_fact_check"] == {}
    root = _root(s)
    assert root["metadata"]["round_cap"] is True and root["metadata"]["loop_guard"] is False
    assert root["output"] == CAPPED_REPLY and root["ended"]
    assert s["trace"]["scores"] == [] and not [o for o in s["trace"]["observations"] if o["name"] == "fact_check"]
    assert len([o for o in s["trace"]["observations"] if o["type"] == "generation"]) == cap
    assert capsys.readouterr().out.count("[round cap: ") == 2          # logged once per engine


def test_rc2_a_turn_below_the_cap_is_unchanged(h):
    cap = h.ag.MAX_TOOL_ROUNDS
    s = _both(h, lambda: _endless(cap - 1)() + [_text(RIGHT)], ROUND * (cap - 1) + ANSWER)
    assert s["answer"] == RIGHT and len(s["requests"]) == cap and s["last_fact_check"]["outcome"] == "clean"
    assert [w[0] for w in s["writes"]] == ["fact_checks", "citation_checks", "numeric_checks", "chat_usage"]
    assert "round_cap" not in s["last_turn"] and "round_cap" not in _root(s)["metadata"]


def test_rc2_the_send_back_after_the_last_allowed_call_is_not_capped(h):
    cap = h.ag.MAX_TOOL_ROUNDS
    s = _both(h, lambda: _endless(cap - 1)() + [_text(WRONG), _text(RIGHT)],
              ROUND * (cap - 1) + ["call_model", "fact_check", "send_back", "recheck", "finalize"])
    assert s["answer"] == RIGHT and len(s["requests"]) == cap + 1 and s["last_fact_check"]["outcome"] == "fixed"
    assert "round_cap" not in s["last_turn"]


def test_rc3_the_recursion_limit_is_still_far_above_the_cap(h):
    import agent_graph
    cap = h.ag.MAX_TOOL_ROUNDS
    assert agent_graph.RECURSION_LIMIT > 1000 * 2 * cap                # a capped turn takes 2 x cap super-steps
    h.mp.setenv("AGENT_ENGINE", "graph")
    h.mp.setattr(h.ag, "client", _Raw(_endless(cap + 5)()))
    answer, _ = agent_graph.run_turn(QUESTION, [], recursion_limit=2 * cap + 2)   # a limit just above the cap's steps
    turn_context.end()
    assert answer == CAPPED_REPLY and agent_graph.LAST_RUN["path"][-1] == "round_cap"


def test_rc4_the_cap_is_max_of_12_and_twice_the_longest_traced_turn(h):
    assert h.ag.MAX_TOOL_ROUNDS == max(12, 2 * LONGEST_TRACED_TURN) == 12


def test_rc5_at_the_cap_a_response_without_a_tool_call_takes_its_old_path(h):
    cap = h.ag.MAX_TOOL_ROUNDS
    guard = lambda: _Resp([_Block("thinking", thinking="", signature="sig")], "max_tokens")   # noqa: E731
    s = _both(h, lambda: _endless(cap - 1)() + [guard()], ROUND * cap + ["finalize"])
    assert s["answer"] == h.ag.GUARD_REPLY and "round_cap" not in s["last_turn"] and s["last_turn"]["guard"]
    mixed = lambda: _Resp([_Block("text", text="Done thinking."), ], "tool_use")              # noqa: E731
    s = _both(h, lambda: _endless(cap - 1)() + [mixed()], ROUND * cap + ["fact_check", "finalize"])
    assert s["answer"] == "Done thinking." and "round_cap" not in s["last_turn"]


# ---- RC6: a capped turn in a stored thread (Prompt B's /chat path, test_threads' app on its own test database) -----------

from test_threads import app, tdb, _chat, _history, _norm            # noqa: E402,F401  (app, tdb: fixtures)
import thread_fakes as tf                                            # noqa: E402


def test_rc6_a_capped_turn_in_a_stored_thread_is_stored_whole_and_the_thread_goes_on(app):
    import json
    cap = app.agent.MAX_TOOL_ROUNDS

    class Endless(tf.Brain):
        def respond(self, kw, q):
            if q == "endless":
                return tf.tool_use("get_my_xi", {}, f"t_{len(self.log)}")
            return super().respond(kw, q)
    brain = Endless()
    app.mp.setattr(app.agent, "client", brain)
    r = _chat(app, 9001, "endless")
    assert r.status_code == 200 and r.json()["answer"] == CAPPED_REPLY and brain.calls == cap
    tid = r.json()["thread_id"]
    hist = _norm(_history(tid))
    assert hist[-1] == {"role": "assistant", "content": [{"type": "text", "text": CAPPED_REPLY}]}
    r2 = _chat(app, 9001, "About apple", thread_id=tid)
    assert r2.status_code == 200 and r2.json()["answer"] == "Answer to About apple"
    sent = json.loads(brain.log[-1]["raw"])["messages"]               # the next turn carries the capped turn whole
    uses = [b["id"] for m in sent if m["role"] == "assistant" and isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_use"]
    results = [b["tool_use_id"] for m in sent if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    assert sorted(uses) == sorted(results) and len(uses) == cap - 1
