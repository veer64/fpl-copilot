"""LangGraph engine v1 (Prompt A, 2026-10-31): agent._run_turn's loop as a LangGraph StateGraph, with the SAME behaviour.

Selected per turn by AGENT_ENGINE=graph (agent._run_turn's entry; the default is the loop). The graph's nodes are thin
wrappers around agent.py's own step functions -- the ones the loop calls, in the loop's order -- and its conditional
edges are the loop's branches, so the two engines cannot drift apart in what a turn does:

    START -> call_model --(a text reply: stop_reason not tool_use + a text block)--> fact_check
                        --(MAX_TOOL_ROUNDS model calls made and still a tool call: Prompt P6)--> round_cap --> END
                        --(otherwise)--> run_tools
             run_tools  --(tool calls ran: their results appended)--> call_model
                        --(no tool call, a text block: the loop guard's first branch)--> fact_check
                        --(no tool call, no text: the loop guard)--> finalize
             fact_check --(mismatches: the one send-back)--> send_back, else --> finalize
             send_back  --(text to re-check)--> recheck, else --> finalize
             recheck    --> finalize --> END

finalize = the fact check's log / scores, the reply's rendering, the usage row and the trace's end (or the loop guard's
fixed reply). The state is the turn's variables (agent._begin_turn) plus text_block, the loop's `block` / `text_block`
that the edges read. Every list and dict in it is the loop's own object, mutated in place by the steps exactly as the
loop mutates it; nodes return the keys they set (the default overwrite reducer). No checkpointer, no threads: one
invoke() per turn, the history in and out as the caller's list, as with the loop.

The request Anthropic receives is built by agent._call_model / agent._send_back: the same bytes on both engines
(Tests/test_agent_payload_equivalence.py, fixture v5). Anthropic is called inside the nodes through llm.chat with
agent.client -- no LangChain model or tool wrapper, no prebuilt agent. Tracing is tracing.py's own spans, opened by
agent._begin_turn (metadata engine=graph); no callback handler.

Since Prompt P6 (2026-11-01) a turn makes at most agent.MAX_TOOL_ROUNDS model calls (the round cap, 2 x MAX_TOOL_ROUNDS
super-steps); LangGraph's recursion limit stays far above that (RECURSION_LIMIT super-steps = ~RECURSION_LIMIT / 2 model
calls): our cap, our guard or the eval runner's budget always ends a turn first (Tests/test_agent_graph.py G14,
Tests/test_round_cap.py).

LAST_RUN (for the eval runner and the overhead measurement): the turn id, the node path, the seconds spent inside node
functions, invoke()'s wall time and the overhead outside the nodes."""
import time
from typing import Annotated, Any, TypedDict

from langgraph.channels import UntrackedValue
from langgraph.graph import END, START, StateGraph

import agent
import threads

RECURSION_LIMIT = 100_000
LAST_RUN = {}


_T = Annotated[Any, UntrackedValue(object)]          # Prompt B: a turn's working variable -- never checkpointed


class TurnState(TypedDict, total=False):
    # the thread's history: the ONE key a stored thread's checkpoint keeps (Prompt B)
    messages: list
    # agent._begin_turn: the loop's turn variables
    question_index: _T
    turn_id: _T
    trace: _T
    now: _T
    system: _T
    now_text: _T
    returned_ids: _T
    returned_results: _T
    usage: _T
    turn_calls: _T
    thread_id: _T
    max_turns: _T
    # the loop's latest response and its tool results
    response: _T
    tool_results: _T
    # the fact check (agent._fact_check_start / _send_back / _recheck)
    raw: _T
    info: _T
    res: _T
    fc_span: _T
    delivered: _T
    sb: _T
    t0: _T
    text2: _T
    reply: _T
    # the reply (agent._finish / agent._loop_guard / agent._round_cap)
    rendered: _T
    # Prompt P6: the tool loop's model calls so far (the round cap)
    rounds: _T
    # the loop's block / text_block: the text the fact check reads, read by the edges
    text_block: _T


def _timed(name, fn):
    """The node as LangGraph sees it: fn on a working copy of the state mapping (the same list / dict objects), timed
    (perf_counter) into this invoke's run record (config["configurable"]["agent_run"], one per turn), its name appended
    to the turn's path."""
    def node(state, config):
        run = config["configurable"]["agent_run"]
        t = time.perf_counter()
        try:
            return fn(dict(state))
        finally:
            run["node_s"] += time.perf_counter() - t
            run["path"].append(name)
    node.__name__ = name
    return node


# ---- the nodes: agent.py's steps, merged into a working view of the state, the keys they set returned ----------------

def call_model(st):
    out = agent._call_model(st)
    st.update(out)
    return {**out, "text_block": agent._final_text_block(st)}


def run_tools(st):
    out = agent._run_tools(st)
    st.update(out)
    if st["tool_results"]:
        out.update(agent._append_tool_results(st))
        return {**out, "text_block": None}
    return {**out, "text_block": agent._guard_text_block(st)}


def fact_check(st):
    return agent._fact_check_start(st, st["text_block"].text)


def send_back(st):
    out = agent._send_back(st)
    st.update(out)
    if not agent._has_rewrite(st):
        out.update(agent._send_back_done(st))
    return out


def recheck(st):
    out = agent._recheck(st)
    st.update(out)
    out.update(agent._send_back_done(st))
    return out


def round_cap(st):
    return agent._round_cap(st)


def finalize(st):
    if st.get("info") is None:                       # no fact check ran: the loop guard's fixed reply
        return agent._loop_guard(st)
    st.update(agent._fact_check_end(st))
    return agent._finish(st, st["delivered"])


# ---- the edges: the loop's branches ---------------------------------------------------------------------------------

def after_model(state):
    if state.get("text_block") is not None:
        return "fact_check"
    return "round_cap" if agent._round_capped(state) else "run_tools"


def after_tools(state):
    if state["tool_results"]:
        return "call_model"
    return "fact_check" if state.get("text_block") is not None else "finalize"


def after_fact_check(state):
    return "send_back" if agent._needs_send_back(state) else "finalize"


def after_send_back(state):
    return "recheck" if agent._has_rewrite(state) else "finalize"


def build(checkpointer=None):
    g = StateGraph(TurnState)
    for name, fn in (("call_model", call_model), ("run_tools", run_tools), ("fact_check", fact_check),
                     ("send_back", send_back), ("recheck", recheck), ("finalize", finalize), ("round_cap", round_cap)):
        g.add_node(name, _timed(name, fn))
    g.add_edge(START, "call_model")
    g.add_conditional_edges("call_model", after_model, ["fact_check", "run_tools", "round_cap"])
    g.add_conditional_edges("run_tools", after_tools, ["call_model", "fact_check", "finalize"])
    g.add_conditional_edges("fact_check", after_fact_check, ["send_back", "finalize"])
    g.add_conditional_edges("send_back", after_send_back, ["recheck", "finalize"])
    g.add_edge("recheck", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("round_cap", END)
    return g.compile(checkpointer=checkpointer)


GRAPH = build()                                   # a caller's own list (the eval runner, the tests): no checkpointer
_THREAD_GRAPHS = {}


def thread_graph():
    """The same graph compiled with this process's Postgres checkpointer (threads.checkpointer()), one per database."""
    saver = threads.checkpointer()
    g = _THREAD_GRAPHS.get(id(saver))
    if g is None:
        g = _THREAD_GRAPHS[id(saver)] = build(checkpointer=saver)
    return g


def _thread_config(thread_id):
    return {"configurable": {"thread_id": str(thread_id)}}


def load_history(thread_id):
    """A stored thread's history (a fresh list), [] for a thread with no turn yet."""
    st = thread_graph().get_state(_thread_config(thread_id))
    return list((st.values or {}).get("messages") or [])


def run_thread_turn(user_id, thread_id, user_message):
    """One /chat turn in a stored thread (Prompt B): the thread's history loaded from the checkpointer, the turn run on
    the engine AGENT_ENGINE names (the graph checkpoints itself; the loop's result is stored the same way), the
    request trimmed to the last threads.MAX_TURNS turns, the stored thread kept whole. A turn that raises leaves the
    thread as it was (its partial history is overwritten by the history before the turn) and re-raises. Turns of one
    thread run one at a time (threads.turn_lock). Returns the rendered reply."""
    thread = {"thread_id": str(thread_id), "user_id": int(user_id), "max_turns": threads.MAX_TURNS}
    with threads.turn_lock(thread_id):
        g = thread_graph()
        cfg = _thread_config(thread_id)
        before = load_history(thread_id)
        history = list(before)
        try:
            answer, history = agent.run_agent(user_message, history, thread=thread)
        except BaseException:
            try:
                g.update_state(cfg, {"messages": before}, as_node="finalize")
            except Exception as e:                       # noqa: BLE001 -- the turn's own exception is the one to raise
                print(f"  [thread {thread_id}: the failed turn was not rolled back: {type(e).__name__}: {str(e)[:200]}]")
            raise
        if agent._engine() == "loop":                    # the loop does not checkpoint; its history is stored here
            g.update_state(cfg, {"messages": history}, as_node="finalize")
        return answer


def run_turn(user_message, messages=None, *, thread=None, recursion_limit=RECURSION_LIMIT):
    """One turn on the graph: (rendered reply, the history) -- the history is the caller's list, extended in place, as
    with the loop. A stored thread's turn (Prompt B) runs on the checkpointed graph under its thread id and is
    persisted when the run exits (durability "exit": one checkpoint per turn, only `messages`)."""
    st = agent._begin_turn(user_message, messages, engine="graph", thread=thread)
    run = {"node_s": 0.0, "path": []}
    LAST_RUN.clear()
    t = time.perf_counter()
    try:
        if thread is None:
            out = GRAPH.invoke(st, config={"recursion_limit": recursion_limit, "configurable": {"agent_run": run}})
        else:
            cfg = _thread_config(thread["thread_id"])
            cfg["configurable"]["agent_run"] = run
            out = thread_graph().invoke(st, config={"recursion_limit": recursion_limit, **cfg}, durability="exit")
    finally:
        wall = time.perf_counter() - t
        LAST_RUN.update(turn_id=st["turn_id"], path=list(run["path"]), node_s=round(run["node_s"], 6),
                        invoke_s=round(wall, 6), overhead_ms=round((wall - run["node_s"]) * 1000, 3))
    return out["rendered"], st["messages"]
