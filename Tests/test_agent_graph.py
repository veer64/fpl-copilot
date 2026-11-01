"""Prompt A (2026-10-31): the LangGraph engine (agent_graph.py, AGENT_ENGINE=graph) against the loop (the default) on
the SAME scripted Anthropic responses.

G1-G14: per scenario both engines run one after the other and these must be equal -- the reply; every DB row the turn
writes (chat_usage, citation_checks, numeric_checks, fact_checks; squad_versions / squad_previews in G12-G13), ids, turn
ids, tickets and timestamps aside; the chat_usage cost; the history after the turn; the bytes of every request sent;
agent.LAST_TURN / LAST_FACT_CHECK and tracing.LAST_TURN (ids and timings aside); the trace's shape (every observation's
type, name and parent in order, the generations' metadata, the root's output and metadata, the scores) -- and the
graph's node path must be the expected one, the proof that the graph (not the loop) ran. G15, the payload, is in
Tests/test_agent_payload_equivalence.py.

Offline: a fake Anthropic client, test_tracing.py's fake Langfuse backend, stubbed tools, the clock frozen, the DB
writes captured at the record functions. G12-G13 run the REAL set_my_squad on test_confirm_lock.py's test database
(fpl_news_test, users 9001 / 9002 only), re-seeded before each engine."""
import importlib
import itertools
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2.extras                                                   # noqa: E402
import now_context                                                       # noqa: E402
import payload_fixture as pf                                             # noqa: E402
from test_tracing import (FakeLangfuse, _Block, _Resp, _Fake, XI, FIXTURES, NEWS, RIGHT, WRONG,   # noqa: E402
                          QUESTION, _text, _tool, UNREACHABLE)
from test_confirm_lock import (db, tool, _Dyn, _write, _ticket_in, _legal_document, CHANGE_A, CHANGE_B)    # noqa: E402,F401
import squad_previews as sp                                              # noqa: E402
import squad_store                                                       # noqa: E402
import turn_context                                                      # noqa: E402

FROZEN = datetime(2026, 10, 25, 14, 30, tzinfo=timezone.utc)
ENGINES = ("loop", "graph")


class BudgetExceeded(RuntimeError):
    """The eval runner's budget stop (matched by name in agent.py, like eval/run_agent_evals.BudgetExceeded)."""


# ---- the harness ------------------------------------------------------------------------------------------------------

@pytest.fixture
def h(monkeypatch):
    """The agent with tracing on (the fake backend), the clock frozen, the context block pinned, three stubbed tools, and
    the DB writes captured where they leave the code (the record functions)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("FPL_USER_ID", "9001")
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    monkeypatch.setenv("LANGFUSE_LOG_USER_TEXT", "1")
    import agent
    importlib.reload(agent)
    import tracing
    import fact_check
    made = []

    def factory():
        fake = FakeLangfuse()
        made.append(fake)
        return fake, fake.propagate
    monkeypatch.setattr(tracing, "_make_backend", factory)
    tracing._reset()
    writes = []
    monkeypatch.setattr(agent, "context_block", lambda now=None: "CONTEXT BLOCK")
    monkeypatch.setattr(now_context, "clock", lambda: FROZEN)
    monkeypatch.setattr(agent, "record_chat_usage", lambda turn_id, *a, **k: writes.append(("chat_usage", list(a))))
    monkeypatch.setattr(agent, "record_citation_check",
                        lambda turn_id, cited, returned, violations, conn=None: writes.append(("citation_checks", [cited, returned, violations])))
    monkeypatch.setattr(agent, "record_numeric_check",
                        lambda turn_id, result, error, conn=None: writes.append(("numeric_checks", [result, error])))
    monkeypatch.setattr(fact_check, "record",
                        lambda turn_id, info, conn=None: writes.append(("fact_checks", {k: v for k, v in info.items() if k != "extra_seconds"})))
    monkeypatch.setitem(agent.available_functions, "get_my_xi", lambda **kw: XI)
    monkeypatch.setitem(agent.available_functions, "get_fixtures", lambda **kw: FIXTURES)
    monkeypatch.setitem(agent.available_functions, "search_news", lambda **kw: NEWS)
    yield types.SimpleNamespace(ag=agent, tracing=tracing, fact_check=fact_check, made=made, writes=writes, mp=monkeypatch)
    tracing._reset()


class _Raw:
    """A fake messages API that also keeps the raw bytes of every request (json at the call, cache_control and all)."""

    def __init__(self, steps):
        self.steps, self.calls, self.raw = list(steps), [], []
        self.messages = self

    def create(self, **kw):
        self.raw.append(json.dumps(kw, default=pf._block_to_dict, ensure_ascii=False))
        self.calls.append(kw)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step(kw) if callable(step) else step


def _block(b):
    if isinstance(b, dict):
        return b
    return {k: v for k, v in vars(b).items()}


def _history(messages):
    return [{"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else [_block(b) for b in m["content"]]}
            for m in messages]


_SKIP_TURN = {"turn_id", "trace_id", "tracing_ms"}


def _trace(lf, n_obs, n_scores):
    """The turn's trace shape: its observations in order (type, name, parent's name, ended, level, metadata without the
    ids, model, the root's output, usage and cost), and its scores (name, value, type, comment). The fake backend is built
    once and reused, so the turn's part is what it gained during the turn."""
    if lf is None:
        return None
    obs = []
    for o in lf.observations[n_obs:]:
        meta = {k: v for k, v in o.metadata().items() if k not in ("turn_id", "engine")}
        obs.append({"type": o.as_type, "name": o.name, "parent": o.parent.name if o.parent else None, "ended": o.ended,
                    "level": o.field("level"), "metadata": meta, "model": o.field("model"),
                    "output": o.field("output") if o.parent is None else None,
                    "usage": o.field("usage_details"), "cost": o.field("cost_details")})
    scores = [(sc["name"], sc["value"], sc.get("data_type"), sc.get("comment")) for sc in lf.scores[n_scores:]]
    return {"observations": obs, "scores": scores}


def _engine_tags(lf, n_obs):
    return sorted({o.metadata().get("engine") for o in lf.observations[n_obs:] if o.parent is None}) if lf else []


def _run(h, engine, steps, question=QUESTION, history=None, expect_raise=None):
    """One turn on `engine`; returns everything the engines must agree on, plus the graph's node path."""
    import agent_graph
    ag, tracing = h.ag, h.tracing
    h.mp.setenv("AGENT_ENGINE", engine)
    h.writes.clear()
    fake = _Raw(steps)
    h.mp.setattr(ag, "client", fake)
    ag.LAST_TURN.clear()
    ag.LAST_FACT_CHECK.clear()
    agent_graph.LAST_RUN.clear()
    lf0 = h.made[-1] if h.made else None
    n_obs, n_scores = (len(lf0.observations), len(lf0.scores)) if lf0 else (0, 0)
    hist = history if history is not None else []
    answer, raised = None, None
    if expect_raise is None:
        answer, out_hist = ag.run_agent(question, hist)
        assert out_hist is hist                                       # the caller's list, extended in place
    else:
        with pytest.raises(expect_raise) as e:
            ag.run_agent(question, hist)
        raised = (type(e.value).__name__, str(e.value))
    lf = h.made[-1] if h.made else None
    snap = {"answer": answer, "raised": raised, "history": _history(hist), "requests": fake.raw,
            "writes": json.loads(json.dumps(h.writes, default=str)),
            "last_turn": {k: v for k, v in ag.LAST_TURN.items() if k not in _SKIP_TURN},
            "last_fact_check": {k: v for k, v in ag.LAST_FACT_CHECK.items() if k != "extra_seconds"},
            "tracing_last_turn": {k: v for k, v in tracing.LAST_TURN.items() if k not in _SKIP_TURN},
            "trace": _trace(lf, n_obs, n_scores), "turn_closed": turn_context.current() is None}
    path = list(agent_graph.LAST_RUN.get("path") or [])
    return snap, path, _engine_tags(lf, n_obs)


def _both(h, steps_factory, path, **kw):
    """Run the scenario on both engines (fresh scripted responses for each) and compare."""
    loop, loop_path, loop_tags = _run(h, "loop", steps_factory(), **kw)
    graph, graph_path, graph_tags = _run(h, "graph", steps_factory(), **kw)
    assert loop_path == []                                            # the loop ran the loop
    assert graph_path == path                                         # the graph ran, through the expected nodes
    assert loop_tags == ["loop"] and graph_tags == ["graph"]          # Part 5: each trace carries its engine
    for key in loop:
        assert _norm_ids(graph[key]) == _norm_ids(loop[key]), f"{key} differs between the engines"
    return loop


ANSWER = ["call_model", "fact_check", "finalize"]
ROUND = ["call_model", "run_tools"]


# ---- G1-G11 -----------------------------------------------------------------------------------------------------------

def test_g1_plain_answer_no_tools(h):
    s = _both(h, lambda: [_text("Ask me about your squad and I'll check it.")], ANSWER)
    assert s["answer"] == "Ask me about your squad and I'll check it." and len(s["requests"]) == 1
    assert [w[0] for w in s["writes"]] == ["fact_checks", "citation_checks", "numeric_checks", "chat_usage"]


def test_g2_one_tool_round(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(RIGHT)], ROUND + ANSWER)
    assert s["answer"] == RIGHT and len(s["requests"]) == 2 and s["last_fact_check"]["outcome"] == "clean"


def test_g3_two_tools_in_one_model_call(h):
    s = _both(h, lambda: [_tool("get_my_xi", "get_fixtures"), _text(RIGHT)], ROUND + ANSWER)
    assert [o["name"] for o in s["trace"]["observations"] if o["type"] == "tool"] == ["get_my_xi", "get_fixtures"]


def test_g4_three_tool_rounds_with_a_citation(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _tool("get_fixtures"), _tool("search_news"), _text(RIGHT + " Fit for Everton [c901].")],
              ROUND * 3 + ANSWER)
    assert len(s["requests"]) == 4 and "Sources" in s["answer"]
    assert ["citation_checks", [["c901"], ["c901"], []]] in s["writes"]


def test_g5_a_tool_raises(h):
    def boom(**kw):
        raise ValueError("fixture feed down")
    h.mp.setitem(h.ag.available_functions, "get_fixtures", boom)
    s = _both(h, lambda: [_tool("get_fixtures"), _text("The fixture list failed, so I can't say yet.")], ROUND + ANSWER)
    assert "tool get_fixtures failed: ValueError: fixture feed down" in s["history"][2]["content"][0]["content"]


def test_g6_the_loop_guard_trips(h):
    guard = lambda: _Resp([_Block("thinking", thinking="", signature="sig")], "max_tokens")   # noqa: E731
    s = _both(h, lambda: [_tool("get_my_xi"), guard()], ROUND + ROUND + ["finalize"])
    assert s["answer"] == h.ag.GUARD_REPLY and s["last_turn"]["guard"]["stop_reason"] == "max_tokens"
    assert [w[0] for w in s["writes"]] == ["chat_usage"] and s["trace"]["scores"] == []


def test_g7_send_back_fixed(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)], ROUND + ["call_model", "fact_check", "send_back", "recheck", "finalize"])
    assert s["answer"] == RIGHT and s["last_fact_check"]["outcome"] == "fixed" and len(s["requests"]) == 3


def test_g8_send_back_flagged_the_rewrite_fails(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), _text(WRONG)], ROUND + ["call_model", "fact_check", "send_back", "recheck", "finalize"])
    assert s["answer"] == WRONG and s["last_fact_check"]["outcome"] == "still_wrong"


def test_g9_the_rewrite_asks_for_a_tool_and_the_original_is_delivered(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), _tool("get_my_xi")], ROUND + ["call_model", "fact_check", "send_back", "finalize"])
    assert s["answer"] == WRONG and s["last_fact_check"]["outcome"] == "tool_call_in_rewrite"


def test_g10_the_fact_check_crashes(h):
    def crash(*a, **k):
        raise RuntimeError("checker bug")
    h.mp.setattr(h.fact_check, "check", crash)
    s = _both(h, lambda: [_tool("get_my_xi"), _text(RIGHT)], ROUND + ANSWER)
    assert s["answer"] == RIGHT and s["last_fact_check"]["outcome"] == "check_error"
    assert [sc[0] for sc in s["trace"]["scores"]] == ["fact_check"]


def test_g11a_the_eval_budget_stop_in_the_loop(h):
    s = _both(h, lambda: [_tool("get_my_xi"), BudgetExceeded("Anthropic call cap 1 reached")], ROUND + ["call_model"],
              expect_raise=BudgetExceeded)
    assert s["raised"] == ("BudgetExceeded", "Anthropic call cap 1 reached") and s["turn_closed"]
    assert s["writes"] == [] and s["trace"]["observations"][0]["level"] == "ERROR"


def test_g11b_the_eval_budget_stop_in_the_send_back(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), BudgetExceeded("USD cap 0.1 reached")],
              ROUND + ["call_model", "fact_check", "send_back"], expect_raise=BudgetExceeded)
    assert s["raised"] == ("BudgetExceeded", "USD cap 0.1 reached") and s["writes"] == [] and s["turn_closed"]


# ---- G12-G13: the confirm flow on the test database (users 9001 / 9002) ---------------------------------------------

def _reseed(c):
    """test_confirm_lock's seed again: fresh squad tables, 9001 and 9002 each one active GW6 version."""
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS squad_previews")
        cur.execute("DROP TABLE IF EXISTS squad_scores")
        cur.execute("DROP TABLE IF EXISTS squad_versions CASCADE")
    c.commit()
    squad_store.ensure_schema(c)
    sp.ensure_schema(c)
    doc = _legal_document()
    with c.cursor() as cur:
        for uid in (9001, 9002):
            cur.execute("INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, supersedes, note) "
                        "VALUES (%s, %s, %s, %s, TRUE, NULL, %s)", (uid, "2026-27", 6, json.dumps(doc), "confirm lock test seed"))
    c.commit()


_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?")
_TICKET = re.compile(r"(?i)preview[_ ]ticket[\\'\"]*\s*[:=]?\s*[\\'\"]*([A-Za-z0-9_-]{16,})")   # quotes / escaping backslashes around


def _norm_ids(obj):
    """A compared value with what a turn DRAWS replaced by placeholders -- preview tickets (every token a "preview ticket"
    / preview_ticket names, replaced wherever it recurs), 32-hex turn and trace ids, ISO timestamps -- the rule's
    "excluding ids and timestamps" applied inside strings too (tool outputs, requests, spans). CHECKER MISFIRE 2026-10-31:
    G12's first run differed only by the ticket each preview draws."""
    text = json.dumps(obj, default=str, sort_keys=True, ensure_ascii=False)
    for t in sorted(set(_TICKET.findall(text)), key=len, reverse=True):
        text = text.replace(t, "<ticket>")
    text = re.sub(r"\b[0-9a-f]{32}\b", "<hex32>", text)
    return json.loads(_ISO.sub("<ts>", text))


def _squad_rows(c):
    """squad_versions + squad_previews as written, with tickets, turn ids (32 hex) and timestamps replaced by placeholders
    and version ids by their order."""
    with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM squad_versions ORDER BY version_id")
        versions = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM squad_previews ORDER BY created_at, id")
        previews = [dict(r) for r in cur.fetchall()]
    order = {v["version_id"]: i for i, v in enumerate(versions)}
    tickets = [p["id"] for p in previews]
    text = json.dumps({"versions": versions, "previews": previews}, default=str, sort_keys=True)
    for i, t in enumerate(tickets):
        text = text.replace(str(t), f"<ticket{i}>")
    text = re.sub(r"\b[0-9a-f]{32}\b", "<hex32>", text)                 # turn ids in provenance
    out = json.loads(_ISO.sub("<ts>", text))
    for v in out["versions"]:
        v["version_id"] = order.get(int(v["version_id"]))
        v["supersedes"] = order.get(int(v["supersedes"])) if v.get("supersedes") is not None else None
    for p in out["previews"]:
        p["base_version_id"] = order.get(int(p["base_version_id"])) if p.get("base_version_id") is not None else None
    return out


def _flow(h, db, engine, second_question, second_steps, tickets=None, at=FROZEN):
    """One engine's confirm flow on a fresh seed: turn 1 previews CHANGE_A (a ticket is issued), turn 2 answers it. The
    tickets come from `tickets`, else from one fixed sequence restarted here, so both engines draw the same ones; the
    ticket table's clock (issue, expiry, use) reads `at`, one instant for every flow (the turns keep their own clock)."""
    _reseed(db)
    draws = iter(tickets) if tickets is not None else (f"seededticket{n:012d}" for n in itertools.count(1))
    h.mp.setattr(sp, "new_id", lambda: next(draws))
    h.mp.setattr(sp, "clock", lambda: at)
    hist = []
    t1, p1, tags1 = _run(h, engine, [lambda kw: _write(CHANGE_A, False), lambda kw: _text("Here is the preview. Shall I apply it?")],
                         question="Swap P15 for P16.", history=hist)
    t2, p2, tags2 = _run(h, engine, second_steps, question=second_question, history=hist)
    return {"turn1": t1, "turn2": t2, "rows": _squad_rows(db)}, [p1, p2], tags1 + tags2


def _yes(reply="Written.", change=CHANGE_A):
    return lambda: [lambda kw: _write(change, True, _ticket_in(kw), id_="t2"), lambda kw: _text(reply)]


def _confirm_both(h, db, second_question, second_steps_factory, paths):
    loop = _flow(h, db, "loop", second_question, second_steps_factory())
    graph = _flow(h, db, "graph", second_question, second_steps_factory())
    assert loop[1] == [[], []] and graph[1] == paths
    assert loop[2] == ["loop", "loop"] and graph[2] == ["graph", "graph"]
    for key in ("turn1", "turn2"):
        for k in loop[0][key]:
            assert _norm_ids(graph[0][key][k]) == _norm_ids(loop[0][key][k]), f"{key}.{k} differs between the engines"
    assert graph[0]["rows"] == loop[0]["rows"], "the squad rows written differ between the engines"
    return loop[0]


def test_g12_misfire_validation_drawn_ids_never_differ_between_the_engines_a_real_difference_does(h, tool, db):
    """CHECKER MISFIRE -- definition: the engines must agree on every compared field "excluding ids and timestamps". A
    preview ticket is DRAWN per preview (squad_previews.new_id), so (1, 16:4xZ) it differs between any two runs whatever the
    engine -- in tool outputs, requests, spans -- and (2, 17:34Z, G13 in the full suite) its characters reach a DERIVED field:
    the numeric check counts the numbers in the turn's tool outputs (notebook_size 15 vs 16). A placeholder cannot hide (2),
    so the harness draws the SAME ticket sequence for both engines (restarted per flow) and keeps the placeholders for
    the rest. Validation set: two different draws on the SAME engine differ raw and, after the placeholders, still in
    numeric_checks (the misfire's mechanism); with the shared sequence two runs on the same engine are equal (the misfire
    PASSES); a real difference -- another reply, another change confirmed -- still FAILS."""
    a, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes()(), tickets=["AAAAAAAAAAAAAAAAAAAAAAAA"])
    b, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes()(), tickets=["AAAA-1234-5678-9012-AAAA"])
    assert a["turn1"]["history"] != b["turn1"]["history"]                 # raw: two draws, two tickets

    def numeric(s):
        return [w for w in _norm_ids(s)["turn1"]["writes"] if w[0] == "numeric_checks"]
    assert numeric(a) != numeric(b)                                       # the draw's digits reach the numeric check
    # (3, 17:43Z, G12 3 of 6 repeats): the preview names its expiry in words at minute precision ("Sat 31 Oct 2026 18:12
    # UTC", squad_previews.clock + 30 min), so two runs either side of a minute differ; the flows share one clock instant
    a2, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes()(), at=datetime(2026, 10, 25, 14, 29, 59, tzinfo=timezone.utc))
    b2, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes()(), at=datetime(2026, 10, 25, 14, 30, 0, tzinfo=timezone.utc))
    assert _norm_ids(a2)["turn1"]["history"] != _norm_ids(b2)["turn1"]["history"]
    c, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes()())
    d, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes()())
    assert _norm_ids(c) == _norm_ids(d)                                   # the shared sequence: the same flow, equal
    e, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes("Written!")())
    assert _norm_ids(e) != _norm_ids(c)                                   # a different reply still fails
    f, _, _ = _flow(h, db, "loop", "Yes, apply it.", _yes(change=CHANGE_B)())
    assert _norm_ids(f) != _norm_ids(c) and f["rows"] != c["rows"]        # a different change confirmed still fails


def test_g12_confirm_flow_preview_then_yes_writes_once(h, tool, db):
    s = _confirm_both(h, db, "Yes, apply it.", _yes(), [ROUND + ANSWER, ROUND + ANSWER])
    assert s["turn2"]["answer"] == "Written."
    users = [v["user_id"] for v in s["rows"]["versions"]]
    assert users.count(9001) == 2 and users.count(9002) == 1                              # one write, user 9001
    assert len(s["rows"]["previews"]) == 1 and s["rows"]["previews"][0]["used_at"] == "<ts>"


def test_g13_confirm_flow_preview_then_no_writes_nothing(h, tool, db):
    s = _confirm_both(h, db, "No, leave it as it is.",
                      lambda: [lambda kw: _text("Understood, no change made.")],
                      [ROUND + ANSWER, ANSWER])
    users = [v["user_id"] for v in s["rows"]["versions"]]
    assert users.count(9001) == 1 and users.count(9002) == 1                              # nothing written
    assert len(s["rows"]["previews"]) == 1 and s["rows"]["previews"][0]["used_at"] is None


# ---- G14: our loop guard, never LangGraph's recursion limit, ends a long turn --------------------------------------

def test_g14_the_recursion_limit_is_never_reached_before_our_guard(h):
    import agent_graph
    from langgraph.errors import GraphRecursionError
    rounds = 60                                                       # 122 super-steps: past LangGraph's old default of 25
    guard = lambda: _Resp([_Block("thinking", thinking="", signature="sig")], "max_tokens")   # noqa: E731
    # Prompt P6 (2026-11-01): our round cap now ends the turn at MAX_TOOL_ROUNDS model calls -- before P6 this script ran
    # all 60 rounds and ended on the loop guard (61 requests, GUARD_REPLY); the cap is ours too, never LangGraph's limit
    cap = h.ag.MAX_TOOL_ROUNDS
    s = _both(h, lambda: [_tool("get_my_xi") for _ in range(rounds)] + [guard()], ROUND * (cap - 1) + ["call_model", "round_cap"])
    assert s["answer"] == h.ag.ROUND_CAP_REPLY and len(s["requests"]) == cap
    # the limit is far above any turn the eval runner allows (--max-calls 40 -> at most ~82 super-steps)
    assert agent_graph.RECURSION_LIMIT >= 1000 * (2 * 40 + 4)
    # and it is the limit that would stop a turn otherwise: the same script under a small limit raises
    h.mp.setenv("AGENT_ENGINE", "graph")
    h.mp.setattr(h.ag, "client", _Raw([_tool("get_my_xi") for _ in range(rounds)] + [guard()]))
    with pytest.raises(GraphRecursionError):
        agent_graph.run_turn(QUESTION, [], recursion_limit=20)
    turn_context.end()


def test_g14b_the_engine_switch_defaults_to_the_graph_since_prompt_b(h):
    """Prompt A pinned the loop as the default; Prompt B (31 Oct, accepted by the user) made the graph the default and
    the loop the fallback (AGENT_ENGINE=loop). Both directions pinned."""
    import agent_graph
    h.mp.delenv("AGENT_ENGINE", raising=False)
    h.mp.setattr(h.ag, "client", _Raw([_text("Ask me about your squad and I'll check it.")]))
    agent_graph.LAST_RUN.clear()
    answer, _ = h.ag.run_agent(QUESTION, [])
    assert answer == "Ask me about your squad and I'll check it." and agent_graph.LAST_RUN.get("path") == ANSWER
    h.mp.setenv("AGENT_ENGINE", "loop")
    h.mp.setattr(h.ag, "client", _Raw([_text("Ask me about your squad and I'll check it.")]))
    agent_graph.LAST_RUN.clear()
    answer, _ = h.ag.run_agent(QUESTION, [])
    assert answer == "Ask me about your squad and I'll check it." and agent_graph.LAST_RUN == {}
