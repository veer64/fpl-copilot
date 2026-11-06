"""Prompt B (2026-10-31): LangGraph v2 -- per-user threads, the Postgres checkpointer, the 10-turn trim.

USER DECISIONS (31 Oct): "Confirm lock stays ticket-based in v1." "History trim: keep the last 10 turns per thread."
Accepted defaults: a ticket is bound to user + thread; no thread id -> the user's default thread; the graph is the
default engine, the loop a single-user fallback.

T1 the request is unchanged: a turn in a stored thread of <= 10 turns sends the same bytes as Prompt A's graph over a
   list (fixture v5's 109 first calls + its 3-call tool turn) and as the 3-turn fixture recorded from langgraph-a.
T2 users never see each other's turns. T3 another user's thread id is refused (403) before any model call, nothing
written. T4 a preview ticket is spent only by its user in its thread. T5 a thread survives an app restart, and a "yes"
after it spends the pre-restart ticket. T6 a 12-turn thread sends exactly its last 10 turns and stores all 12. T7 the
default thread; /reset. T8 2 users x 5 parallel turns: no cross-talk, every checkpoint consistent. T9 no process-global
history. T10 the trace's session is the thread, its user the turn's user. T11 no LangSmith. T12 AGENT_ENGINE=loop
still works; the graph is the default.

Offline: thread_fakes.Brain is the model; the real set_my_squad with its market lookups stubbed; the test database
fpl_threads_test (created if missing; users 9001 / 9002 only). T5 / T8 / T9 run the app in real processes
(Tests/thread_app.py)."""
import importlib
import json
import os
import socket
import subprocess
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2                                                          # noqa: E402
import db_write                                                          # noqa: E402
import now_context                                                       # noqa: E402
import payload_fixture as pf                                             # noqa: E402
import thread_fakes as tf                                                # noqa: E402
from test_tracing import FakeLangfuse, UNREACHABLE                       # noqa: E402

KEY = "test-threads-key"
V5 = REPO / "Tests" / "fixtures" / "agent_payloads_v5.json"
FIX3 = REPO / "Tests" / "fixtures" / "agent_payloads_threads_v1.json"
PY = sys.executable


# ---- fixtures ---------------------------------------------------------------------------------------------------------

@pytest.fixture
def tdb(monkeypatch):
    """The test database (created if missing), its checkpointer tables set up, everything re-seeded; user 9001."""
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (tf.TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {tf.TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", tf.TEST_DB)
    monkeypatch.setenv("FPL_USER_ID", "9001")
    import threads
    threads._reset()
    threads.checkpointer()
    c = db_write.connect()
    c.autocommit = True                                  # the test's own reads never hold a lock across an app turn
    tf.reseed(c)
    yield c
    c.close()
    threads._reset()


@pytest.fixture
def app(tdb, monkeypatch):
    """main.app in process on the test database, the brain as the model, tracing off, the default engine."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    monkeypatch.delenv("AGENT_ENGINE", raising=False)
    import agent
    importlib.reload(agent)
    import tracing
    tracing._reset()
    brain = tf.Brain()
    tf.stub_agent(agent, brain, setattr_=monkeypatch.setattr)
    import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    client = TestClient(main.app, headers={"x-api-key": KEY})
    yield types.SimpleNamespace(client=client, brain=brain, agent=agent, main=main, mp=monkeypatch, conn=tdb)
    tracing._reset()


def _chat(h, user, message, thread_id=None):
    h.mp.setenv("FPL_USER_ID", str(user))
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    return h.client.post("/chat", json=body)


def _history(thread_id):
    import agent_graph
    return agent_graph.load_history(thread_id)


def _norm(x):
    return json.loads(json.dumps(x, default=pf._block_to_dict, ensure_ascii=False))


def _versions(conn, uid):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM squad_versions WHERE user_id = %s", (uid,))
        return cur.fetchone()[0]


def _tickets(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, user_id, thread_id, used_at IS NOT NULL, cancelled_at IS NOT NULL FROM squad_previews ORDER BY created_at")
        return cur.fetchall()


def _counts(conn):
    out = {}
    with conn.cursor() as cur:
        for t in ("chat_threads", "checkpoints", "checkpoint_blobs", "checkpoint_writes", "squad_versions", "squad_previews"):
            cur.execute(f"SELECT count(*) FROM {t}")
            out[t] = cur.fetchone()[0]
    return out


def _request_messages(entry):
    return json.loads(entry["raw"])["messages"]


def _questions_in(messages):
    """The questions a request carries, in order: earlier ones as plain strings, the turn's own after its clock line."""
    out = []
    for m in messages:
        if m["role"] != "user":
            continue
        c = m["content"]
        if isinstance(c, str):
            out.append(c)
        elif c and c[0].get("type") == "text" and c[0].get("text", "").startswith("- Now:"):
            out.append(c[1]["text"])
    return out


# ---- T1 the request is unchanged ------------------------------------------------------------------------------------

class _RawScript:
    def __init__(self, responses, sink):
        self.responses, self.sink = list(responses), sink
        self.messages = self

    def create(self, **kw):
        self.sink.append(json.dumps(kw, default=pf._block_to_dict, ensure_ascii=False))
        return self.responses.pop(0)


def _pin(ag, mp, context_text, frozen, tool_results):
    mp.setattr(ag, "context_block", lambda now=None: context_text)
    mp.setattr(now_context, "clock", lambda: frozen)
    mp.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    mp.setattr(ag, "_citation_check", lambda *a, **k: None)
    mp.setattr(ag, "_numeric_check", lambda *a, **k: None)
    mp.setattr(ag, "_fact_check_log", lambda *a, **k: None)
    for name, result in tool_results.items():
        mp.setitem(ag.available_functions, name, (lambda r: (lambda **kw: r))(result))


def test_t1_a_stored_thread_sends_the_bytes_of_prompt_a_and_fixture_v5(tdb, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    import agent as ag
    importlib.reload(ag)
    import agent_graph
    import threads
    doc = json.loads(V5.read_text(encoding="utf-8"))
    _pin(ag, monkeypatch, doc["context_text"], pf.parse_now(doc["frozen_now"]), pf.TOOL_RESULTS)
    cases = [("tool_turn", doc["tool_turn"]["question"], pf.tool_turn)] + [(i["id"], i["question"], pf.reply_only) for i in doc["first_calls"]]
    print(f"T1 v5 cases: count={len(cases)} first={cases[0][0]} last={cases[-1][0]}")
    assert len(cases) == 110
    listed, threaded = [], []
    for k, (cid, question, script) in enumerate(cases):
        monkeypatch.setenv("AGENT_ENGINE", "graph")
        monkeypatch.setattr(ag, "client", _RawScript(script(), listed))
        ag.run_agent(question, [])                                        # Prompt A: the graph over the caller's list
        monkeypatch.setattr(ag, "client", _RawScript(script(), threaded))
        agent_graph.run_thread_turn(9001, f"t1-v5-{k}", question)         # Prompt B: a stored thread
    assert len(threaded) == len(listed) == 3 + 109
    assert threaded == listed, "a stored thread changed the bytes of a request"
    norm = [pf.normalize_request(json.loads(x)) for x in threaded]
    for i, req in enumerate(norm[:3]):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"] and req["messages"] == doc["tool_turn"]["calls"][i]
    for item, req in zip(doc["first_calls"], norm[3:]):
        assert {k: req[k] for k in req if k != "messages"} == doc["shared"] and req["messages"] == item["messages"], item["id"]


def test_t1_the_three_turn_fixture_from_langgraph_a_is_sent_byte_for_byte_by_a_stored_thread(tdb, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    import agent as ag
    importlib.reload(ag)
    import agent_graph
    import threads
    fx = json.loads(FIX3.read_text(encoding="utf-8"))
    assert fx["recorded_from"].startswith("75cc993") and fx["n_calls"] == 6 and len(fx["turns"]) == 3
    _pin(ag, monkeypatch, fx["context_text"], pf.parse_now(fx["frozen_now"]), fx["tool_results"])
    raw = []
    for t in fx["turns"]:
        resps = [pf._Resp([pf._Block(b["type"], **{k: v for k, v in b.items() if k != "type"}) for b in r["content"]], r["stop_reason"])
                 for r in t["script"]]
        monkeypatch.setattr(ag, "client", _RawScript(resps, raw))
        answer = agent_graph.run_thread_turn(9001, "t1-three-turns", t["question"])
        assert answer == fx["replies"][fx["turns"].index(t)]
    assert raw == fx["raw_requests"], "the 3-turn thread's requests differ from langgraph-a's"
    assert _norm(_history("t1-three-turns")) == fx["history_after"]


# ---- T2 isolation ---------------------------------------------------------------------------------------------------

def test_t2_two_users_interleaved_never_see_each_others_turns(app):
    words = {9001: ["apple", "banana"], 9002: ["cherry", "damson"]}
    seen = {9001: set(), 9002: set()}
    for i in range(2):
        for u in (9001, 9002):
            r = _chat(app, u, f"About {words[u][i]}")
            assert r.status_code == 200, r.text
            seen[u].add(r.json()["thread_id"])
    assert all(len(v) == 1 for v in seen.values()) and seen[9001] != seen[9002]
    for u, other in ((9001, 9002), (9002, 9001)):
        stored = json.dumps(_norm(_history(next(iter(seen[u])))))
        assert all(w in stored for w in words[u]) and not any(w in stored for w in words[other])
    for entry in app.brain.log:
        mine = 9001 if any(w in entry["question"] for w in words[9001]) else 9002
        theirs = words[9002 if mine == 9001 else 9001]
        assert not any(w in entry["raw"] for w in theirs), "a request carried the other user's turn"


# ---- T3 thread ownership --------------------------------------------------------------------------------------------

def test_t3_another_users_thread_is_refused_before_any_model_call_and_nothing_is_written(app):
    r = _chat(app, 9001, "About apple")
    tid = r.json()["thread_id"]
    before, calls, counts = _norm(_history(tid)), app.brain.calls, _counts(app.conn)
    r2 = _chat(app, 9002, "About cherry", thread_id=tid)
    assert r2.status_code == 403 and r2.json() == {"detail": app.main.THREAD_REFUSED}
    r3 = _chat(app, 9002, "About cherry", thread_id="th_no_such_thread")
    assert r3.status_code == 403 and r3.json() == r2.json()                 # unknown and foreign: the same answer
    assert app.brain.calls == calls                                          # no model call
    assert _norm(_history(tid)) == before and _counts(app.conn) == counts    # nothing written


# ---- T4 tickets: user + thread ------------------------------------------------------------------------------------

def test_t4_a_ticket_is_spent_only_by_its_user_in_its_thread(app):
    thread_b = _chat(app, 9001, "About apple").json()["thread_id"]
    assert app.client.post("/reset").json() == {"status": "conversation reset", "preview_tickets_cancelled": 0}
    r = _chat(app, 9001, tf.PREVIEW_Q)
    thread_a = r.json()["thread_id"]
    assert thread_a != thread_b and r.json()["answer"] == "Here is the preview. Shall I apply it?"
    (ticket, uid, tthread, used, cancelled), = _tickets(app.conn)
    assert (uid, tthread, used, cancelled) == (9001, thread_a, False, False)
    n1, n2 = _versions(app.conn, 9001), _versions(app.conn, 9002)
    app.brain.forced_ticket = ticket
    assert _chat(app, 9002, tf.YES_Q).json()["answer"] == "Not written."                     # 9002's own thread
    assert _chat(app, 9001, tf.YES_Q, thread_id=thread_b).json()["answer"] == "Not written."  # another 9001 thread
    refusals = [e["raw"] for e in app.brain.log if "(reason: missing)" in e["raw"]]
    assert len(refusals) == 2
    assert (_versions(app.conn, 9001), _versions(app.conn, 9002)) == (n1, n2) and not _tickets(app.conn)[0][3]
    app.brain.forced_ticket = None
    assert _chat(app, 9001, tf.YES_Q, thread_id=thread_a).json()["answer"] == "Written."      # the same thread
    assert (_versions(app.conn, 9001), _versions(app.conn, 9002)) == (n1 + 1, n2)
    assert _tickets(app.conn)[0][3] is True


# ---- T5 / T8 / T9: the app in real processes ----------------------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Proc:
    """The app (Tests/thread_app.py) in its own process for one user; .post() talks to it over HTTP."""

    def __init__(self, user, log_path, delay=0.0):
        self.port, self.user, self.log_path = _free_port(), user, Path(log_path)
        env = dict(os.environ, DB_NAME=tf.TEST_DB, FPL_USER_ID=str(user), APP_API_KEY=KEY, LANGFUSE_ENABLED="0",
                   ANTHROPIC_API_KEY="test-key-not-used", PYTHONIOENCODING="utf-8")
        env.pop("AGENT_ENGINE", None)
        self.err = open(str(log_path) + ".stderr", "w", encoding="utf-8")
        self.p = subprocess.Popen([PY, str(REPO / "Tests" / "thread_app.py"), str(self.port), str(log_path), str(delay)],
                                  cwd=str(REPO), env=env, stdout=self.err, stderr=subprocess.STDOUT)
        import httpx
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", headers={"x-api-key": KEY}, timeout=120)
        t0 = time.time()
        while True:
            try:
                if self.http.get("/").status_code == 200:
                    break
            except Exception:                                            # noqa: BLE001
                pass
            if self.p.poll() is not None or time.time() - t0 > 90:
                raise RuntimeError(f"the app process did not start (rc {self.p.poll()})")
            time.sleep(0.3)

    def post(self, message, thread_id=None):
        body = {"message": message}
        if thread_id is not None:
            body["thread_id"] = thread_id
        return self.http.post("/chat", json=body)

    def log(self):
        return [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines() if x.strip()] if self.log_path.exists() else []

    def stop(self):
        self.http.close()
        self.p.terminate()
        try:
            self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.p.kill()
        self.err.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def test_t5_a_thread_survives_an_app_restart_and_a_yes_after_it_spends_the_pre_restart_ticket(tdb, tmp_path):
    import threads
    with _Proc(9001, tmp_path / "a.jsonl") as a:
        r = a.post(tf.PREVIEW_Q)
        assert r.status_code == 200, r.text
        tid = r.json()["thread_id"]
    stored_before = _norm(_history(tid))                                    # the history the first process left
    assert len(stored_before) == 4 and _tickets(tdb)[0][2] == tid
    n1 = _versions(tdb, 9001)
    with _Proc(9001, tmp_path / "b.jsonl") as b:                            # a NEW process: nothing in memory
        r = b.post(tf.YES_Q, thread_id=tid)
        assert r.status_code == 200 and {k: r.json()[k] for k in ("answer", "thread_id")} == {"answer": "Written.", "thread_id": tid}   # W4: + the record fields
        first = b.log()[0]
    assert _request_messages(first)[:-1] == stored_before                   # the restarted process sent the same history
    assert _versions(tdb, 9001) == n1 + 1 and _tickets(tdb)[0][3] is True    # the pre-restart ticket was spent once
    assert len(_history(tid)) == 8


def test_t8_two_users_five_parallel_turns_each_no_cross_talk_every_checkpoint_consistent(tdb, tmp_path):
    import threads
    names = {9001: "ann", 9002: "bob"}
    words = ["alpha", "bravo", "charlie", "delta", "echo"]
    tids = {u: [] for u in names}
    with tdb.cursor() as cur:
        for u in names:
            for _ in range(6):                                               # 5 threads + 1 shared by two parallel turns
                tid = threads.new_thread_id()
                cur.execute("INSERT INTO chat_threads (thread_id, user_id) VALUES (%s, %s)", (tid, u))
                tids[u].append(tid)
    tdb.commit()
    jobs = []
    for u in names:
        for k, w in enumerate(words):
            jobs.append((u, tids[u][k], f"tool: {names[u]} {w}"))
        jobs += [(u, tids[u][5], f"tool: {names[u]} shared one"), (u, tids[u][5], f"tool: {names[u]} shared two")]
    print(f"T8 jobs: count={len(jobs)} first={jobs[0][2]} last={jobs[-1][2]}")
    with _Proc(9001, tmp_path / "u1.jsonl", delay=0.3) as p1, _Proc(9002, tmp_path / "u2.jsonl", delay=0.3) as p2:
        procs = {9001: p1, 9002: p2}
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            results = list(ex.map(lambda j: (j, procs[j[0]].post(j[2], thread_id=j[1])), jobs))
    for (u, tid, q), r in results:
        assert r.status_code == 200, r.text
        assert {k: r.json()[k] for k in ("answer", "thread_id")} == {"answer": f"Answer to {q}", "thread_id": tid}
    for u in names:
        for k, w in enumerate(words):
            h = _norm(_history(tids[u][k]))
            assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"] and h[0]["content"] == f"tool: {names[u]} {w}"
            seen = h[2]["content"][0]["content"]
            assert f"'thread_seen': '{tids[u][k]}'" in seen and f"'user_seen': {u}" in seen    # the turn channel, per request
            assert h[3]["content"][0]["text"] == f"Answer to tool: {names[u]} {w}"
        shared = _norm(_history(tids[u][5]))
        assert len(shared) == 8 and sorted(m["content"] for m in shared[0::4]) == sorted(
            [f"tool: {names[u]} shared one", f"tool: {names[u]} shared two"])          # both turns, one after the other
        assert [m["role"] for m in shared] == ["user", "assistant"] * 4


def test_t9_no_process_global_history_is_left_in_the_code():
    src = (REPO / "main.py").read_text(encoding="utf-8")
    assert "conversation_history" not in src
    import ast
    for name in ("main.py", "agent.py", "agent_graph.py", "threads.py"):
        tree = ast.parse((REPO / name).read_text(encoding="utf-8"))
        for node in tree.body:                                              # module-level assignments only
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        assert "history" not in t.id.lower() and "messages" != t.id.lower(), f"{name}: {t.id}"


def test_t9_two_app_processes_share_nothing_in_memory(tdb, tmp_path):
    import threads
    with _Proc(9001, tmp_path / "a.jsonl") as a, _Proc(9001, tmp_path / "b.jsonl") as b:
        tid = a.post("About apple").json()["thread_id"]
        assert b.post("About banana", thread_id=tid).status_code == 200
        assert a.post("About cherry", thread_id=tid).status_code == 200
        b_first, a_last = b.log()[0], a.log()[-1]
    assert _questions_in(_request_messages(b_first)) == ["About apple", "About banana"]       # B saw A's turn: from Postgres
    assert _questions_in(_request_messages(a_last)) == ["About apple", "About banana", "About cherry"]   # A saw B's turn


# ---- T6 the trim ------------------------------------------------------------------------------------------------------

def test_t6_a_twelve_turn_thread_sends_its_last_ten_turns_and_stores_all_twelve(app):
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
    qs = [f"tool: {w}" if i % 3 == 0 else f"About {w}" for i, w in enumerate(words)]
    tid = None
    for q in qs:
        r = _chat(app, 9001, q, thread_id=tid)
        assert r.status_code == 200, r.text
        tid = r.json()["thread_id"]
    first_call = {}
    for e in app.brain.log:
        first_call.setdefault(e["question"], e)
    for n, q in enumerate(qs, start=1):                                   # turn n's first request
        msgs = _request_messages(first_call[q])
        want = qs[max(0, n - 10):n]
        assert _questions_in(msgs) == want, f"turn {n}"
        assert msgs[0]["role"] == "user" and (msgs[0]["content"] == want[0] or n == 1)          # cut at a question
        ids_use = [b["id"] for m in msgs if m["role"] == "assistant" and isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_use"]
        ids_res = [b["tool_use_id"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_result"]
        assert ids_use == ids_res                                         # no orphan tool_use / tool_result
    stored = _norm(_history(tid))
    assert _questions_in(stored) == qs                                    # the stored thread keeps all 12


# ---- T7 the default thread; /reset ---------------------------------------------------------------------------------

def test_t7_no_thread_id_uses_the_default_thread_reset_starts_a_new_one_and_cancels_the_tickets(app):
    r1 = _chat(app, 9001, "About apple")
    assert r1.status_code == 200 and set(r1.json()) == {"answer", "thread_id", "message_id", "sources", "squad_preview", "squad_applied"}   # W4
    t1 = r1.json()["thread_id"]
    assert _chat(app, 9001, "About banana").json()["thread_id"] == t1
    assert _chat(app, 9001, tf.PREVIEW_Q).json()["thread_id"] == t1
    assert app.client.post("/reset").json() == {"status": "conversation reset", "preview_tickets_cancelled": 1}
    assert _tickets(app.conn)[0][4] is True                               # the open ticket was cancelled
    t2 = _chat(app, 9001, "About cherry").json()["thread_id"]
    assert t2 != t1 and _questions_in(_norm(_history(t2))) == ["About cherry"]
    assert _chat(app, 9001, "About damson", thread_id=t1).json()["thread_id"] == t1          # the old thread is still theirs
    assert _questions_in(_norm(_history(t1))) == ["About apple", "About banana", tf.PREVIEW_Q, "About damson"]
    assert _chat(app, 9001, "About echo").json()["thread_id"] == t2       # the default is the new one


# ---- T10 Langfuse ------------------------------------------------------------------------------------------------------

def test_t10_the_traces_session_is_the_thread_and_its_user_the_turns_user(app):
    import tracing
    app.mp.setenv("LANGFUSE_ENABLED", "1")
    app.mp.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    app.mp.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    app.mp.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    made = []

    def factory():
        fake = FakeLangfuse()
        made.append(fake)
        return fake, fake.propagate
    app.mp.setattr(tracing, "_make_backend", factory)
    tracing._reset()
    t1 = _chat(app, 9001, "tool: apple").json()["thread_id"]
    t2 = _chat(app, 9002, "About cherry").json()["thread_id"]
    lf = made[-1]
    roots = [o for o in lf.observations if o.parent is None]
    assert [(r.propagated.get("session_id"), r.propagated.get("user_id")) for r in roots] == [(t1, "9001"), (t2, "9002")]
    for o in lf.observations:                                             # every span of a turn carries its session
        root = o
        while root.parent is not None:
            root = root.parent
        assert o.propagated.get("session_id") == root.propagated.get("session_id")


# ---- T11 no LangSmith ---------------------------------------------------------------------------------------------

def test_t11_no_langsmith_client_and_no_request_to_a_langsmith_host(app, monkeypatch):
    for k in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGSMITH_TRACING_V2"):
        assert k not in os.environ
    import langsmith
    import langsmith.client
    import requests
    import httpx
    made, urls = [], []
    real_init = langsmith.client.Client.__init__

    def spy_init(self, *a, **k):
        made.append(1)
        return real_init(self, *a, **k)
    monkeypatch.setattr(langsmith.client.Client, "__init__", spy_init)
    real_send = requests.Session.send
    monkeypatch.setattr(requests.Session, "send", lambda self, req, **k: (urls.append(req.url), real_send(self, req, **k))[1])
    real_hsend = httpx.Client.send
    monkeypatch.setattr(httpx.Client, "send", lambda self, req, **k: (urls.append(str(req.url)), real_hsend(self, req, **k))[1])
    r = _chat(app, 9001, "tool: apple")
    assert r.status_code == 200
    from langsmith import utils as ls_utils
    assert made == [] and not ls_utils.tracing_is_enabled()
    assert not [u for u in urls if "smith" in u or "langchain" in u]


# ---- T12 the loop fallback; the default engine --------------------------------------------------------------------

def test_t12_the_loop_still_works_single_user_and_the_graph_is_the_default(app):
    import agent_graph
    assert app.agent._engine() == "graph"
    agent_graph.LAST_RUN.clear()
    t = _chat(app, 9001, "About apple").json()["thread_id"]
    assert agent_graph.LAST_RUN.get("path")                               # the graph ran
    app.mp.setenv("AGENT_ENGINE", "loop")
    for w in ("banana", "cherry"):
        agent_graph.LAST_RUN.clear()
        r = _chat(app, 9001, f"About {w}")
        assert r.status_code == 200 and r.json()["thread_id"] == t and agent_graph.LAST_RUN == {}   # the loop ran
    last = [e for e in app.brain.log if e["question"] == "About cherry"][0]
    assert _questions_in(_request_messages(last)) == ["About apple", "About banana", "About cherry"]
    assert _questions_in(_norm(_history(t))) == ["About apple", "About banana", "About cherry"]


# ---- T13 (D-B3): a failed turn leaves the thread as it was ----------------------------------------------------------

def test_t13_a_turn_that_raises_leaves_the_thread_as_it_was_and_the_next_turn_runs(app):
    """LangGraph checkpoints a run that raises (durability "exit") with its half turn -- here an assistant tool_use whose
    result never came -- which would break every later request of the thread. run_thread_turn writes the history from
    before the turn back. Measured with the model failing on its second call of the turn."""
    t = _chat(app, 9001, "About apple").json()["thread_id"]
    before = _norm(_history(t))

    class Boom(RuntimeError):
        pass
    real = app.brain.respond

    def respond(kw, q):
        if q == "tool: banana" and tf.after_tool(kw):
            raise Boom("the model failed mid-turn")
        return real(kw, q)
    app.mp.setattr(app.brain, "respond", respond)
    with pytest.raises(Boom):
        _chat(app, 9001, "tool: banana", thread_id=t)
    assert _norm(_history(t)) == before                                   # no half turn stored
    r = _chat(app, 9001, "About cherry", thread_id=t)
    assert r.status_code == 200 and r.json()["answer"] == "Answer to About cherry"
    last = [e for e in app.brain.log if e["question"] == "About cherry"][0]
    assert _questions_in(_request_messages(last)) == ["About apple", "About cherry"]
    assert _questions_in(_norm(_history(t))) == ["About apple", "About cherry"]


# ---- F1-F3 (Prompt D2, 2026-11-01): the checkpointer's connection -------------------------------------------------

def _conninfo_dict(monkeypatch, host):
    from psycopg.conninfo import conninfo_to_dict
    import threads
    monkeypatch.setenv("DB_HOST", host)
    return conninfo_to_dict(threads.conninfo())


def test_f1_localhost_is_pinned_to_an_ipv4_address(monkeypatch):
    import ipaddress
    d = _conninfo_dict(monkeypatch, "localhost")
    assert d["host"] == "localhost"
    assert isinstance(ipaddress.ip_address(d["hostaddr"]), ipaddress.IPv4Address)


@pytest.mark.parametrize("host", ["fpl-postgres", "db.example.internal", "10.1.2.3"])
def test_f2_any_other_host_is_passed_through_unchanged_with_no_lookup(monkeypatch, host):
    looked = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (looked.append(a[0] if a else k.get("host")), real(*a, **k))[1])
    d = _conninfo_dict(monkeypatch, host)
    assert d["host"] == host and "hostaddr" not in d
    assert looked == []                                                    # the resolver is never called


def test_f3_one_pool_per_process_reused_by_every_turn_and_thread_with_no_per_turn_lookup(app):
    import psycopg_pool
    import threads
    saver = threads.checkpointer()                                        # built by the fixture
    pool = saver.conn
    host = os.environ.get("DB_HOST", "localhost")
    looked, made = [], []
    real_gai = socket.getaddrinfo

    def spy_gai(*a, **k):
        if (a[0] if a else k.get("host")) == host:
            looked.append(1)
        return real_gai(*a, **k)
    app.mp.setattr(socket, "getaddrinfo", spy_gai)
    real_pool = psycopg_pool.ConnectionPool

    class CountingPool(real_pool):
        def __init__(self, *a, **k):
            made.append(1)
            super().__init__(*a, **k)
    app.mp.setattr(psycopg_pool, "ConnectionPool", CountingPool)
    t1 = _chat(app, 9001, "About apple").json()["thread_id"]
    r2 = _chat(app, 9001, "About banana", thread_id=t1)
    t2 = _chat(app, 9002, "About cherry").json()["thread_id"]
    assert r2.status_code == 200 and t1 != t2
    assert _questions_in(_norm(_history(t1))) == ["About apple", "About banana"]
    assert made == []                                                      # no pool built by a turn
    assert looked == []                                                    # no host lookup by a turn
    assert threads.checkpointer() is saver and saver.conn is pool         # the same pool object throughout
