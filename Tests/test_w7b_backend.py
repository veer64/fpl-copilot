"""Prompt W7b (2026-11-11): the backend items behind the W7a readiness findings.

F3  refresh during an answer: at TURN START the question is written as a PENDING chat_messages row keyed by the turn's
    message_id (status 'pending', question, started_at); while the answer is written GET /threads lists the thread (its
    question as the title) and GET /threads/{id}/messages ends with the pending row; on success the row is the normal
    'done' row with the same id (the reply's message_id); a turn that raises removes it -- a failed turn leaves the thread
    unchanged, no transcript entry, no row, not listed.
F8  READS_PER_MINUTE 60 -> 120 (test-pinned; the 121st read in a minute is 429; nothing else changed).
F12 the console: main._utf8_console reconfigures a cp1252 text stream to UTF-8 with errors="replace", so a print of
    "→ ü ★" never raises; a stream already UTF-8/replace is left alone.

Offline: test_auth's clerk harness (the brain as the model). The "during the turn" view is taken from inside a wrapped
agent.run_agent on its own database connection -- exactly what a second request would see."""
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _bad_tokens   # noqa: E402,F401  (fixtures)

A = "user_a9001"


def _h(sub=A):
    return bearer(mint(sub))


def _chat(c, message, sub=A, thread_id=None):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    return c.client.post("/chat", json=body, headers=_h(sub))


def _pending_rows(conn, thread_id=None):
    import chat_messages
    chat_messages.ensure_schema(conn)
    sql = "SELECT message_id, thread_id, user_id, q, status, question, started_at FROM chat_messages WHERE status = 'pending'"
    return _q(conn, sql + (" AND thread_id = %s" if thread_id else ""), (thread_id,) if thread_id else ())


# ---- F3 the pending row ----------------------------------------------------------------------------------------------------

def test_f3_during_the_turn_the_question_is_pending_listed_and_shown(c, monkeypatch):
    import agent
    import agent_graph
    import db_write
    import threads
    seen = {}
    real = agent.run_agent

    def spying_run_agent(user_message, messages=None, *, thread=None):
        conn = db_write.connect()                        # what another request sees mid-turn
        try:
            seen["pending"] = _pending_rows(conn, thread["thread_id"])
        finally:
            conn.close()
        seen["listed"] = [t for t in threads.list_threads(thread["user_id"]) if t["thread_id"] == thread["thread_id"]]
        seen["messages"] = agent_graph.thread_messages(thread["thread_id"])
        seen["turn_id"] = thread.get("turn_id")
        return real(user_message, messages, thread=thread)
    monkeypatch.setattr(agent_graph.agent, "run_agent", spying_run_agent)
    r = _chat(c, "Who should I captain?")
    assert r.status_code == 200, r.text
    body = r.json()
    tid = body["thread_id"]
    [(mid, t, uid, q, status, question, started_at)] = seen["pending"]
    assert (t, uid, q, status, question) == (tid, 9001, 0, "pending", "Who should I captain?") and started_at is not None
    assert mid == seen["turn_id"] == body["message_id"]                           # one id from start to finish
    assert seen["listed"] and seen["listed"][0]["title"] == "Who should I captain?"   # listed from turn start
    assert seen["messages"][-1] == {"role": "pending", "text": "Who should I captain?", "started_at": threads.iso(started_at), "message_id": mid}
    # after the turn: the same id is the done row; nothing pending; the endpoint shows the normal pair
    assert _pending_rows(c.conn, tid) == []
    [(status, question, kept_start)] = _q(c.conn, "SELECT status, question, started_at FROM chat_messages WHERE message_id = %s", (mid,))
    assert status == "done" and question == "Who should I captain?" and kept_start == started_at
    rows = c.client.get(f"/threads/{tid}/messages", headers=_h()).json()
    assert [m["role"] for m in rows] == ["user", "assistant"] and rows[1]["message_id"] == mid
    assert "pending" not in {m["role"] for m in rows}
    listed = [t for t in c.client.get("/threads", headers=_h()).json() if t["thread_id"] == tid]
    assert listed and listed[0]["title"] == "Who should I captain?"


def test_f3_a_failed_turn_removes_the_pending_row_and_leaves_the_thread_unchanged(c, monkeypatch):
    import agent_graph
    import db_write
    tid = c.client.post("/threads", headers=_h()).json()["thread_id"]
    seen = {}

    def exploding(user_message, messages=None, *, thread=None):
        conn = db_write.connect()
        try:
            seen["pending"] = _pending_rows(conn, thread["thread_id"])
        finally:
            conn.close()
        raise RuntimeError("the model is down")
    monkeypatch.setattr(agent_graph.agent, "run_agent", exploding)
    before = _q(c.conn, "SELECT count(*) FROM chat_messages")[0][0]
    with pytest.raises(RuntimeError):
        _chat(c, "boom?", thread_id=tid)
    assert len(seen["pending"]) == 1                                                # it was there during the turn
    assert _pending_rows(c.conn, tid) == []                                          # and is gone after the failure
    assert _q(c.conn, "SELECT count(*) FROM chat_messages WHERE thread_id = %s", (tid,))[0][0] == 0
    assert c.client.get(f"/threads/{tid}/messages", headers=_h()).json() == []
    assert [t for t in c.client.get("/threads", headers=_h()).json() if t["thread_id"] == tid] == []   # not listed
    assert _q(c.conn, "SELECT count(*) FROM chat_messages")[0][0] == before


def test_f3_a_second_turn_keeps_the_first_answer_visible_while_pending(c, monkeypatch):
    import agent_graph
    import db_write
    first = _chat(c, "First question?").json()
    tid = first["thread_id"]
    seen = {}
    real = agent_graph.agent.run_agent

    def spying(user_message, messages=None, *, thread=None):
        seen["messages"] = agent_graph.thread_messages(thread["thread_id"])
        conn = db_write.connect()
        try:
            seen["listed"] = [t for t in __import__("threads").list_threads(thread["user_id"]) if t["thread_id"] == thread["thread_id"]]
        finally:
            conn.close()
        return real(user_message, messages, thread=thread)
    monkeypatch.setattr(agent_graph.agent, "run_agent", spying)
    _chat(c, "Second question?", thread_id=tid)
    roles = [m["role"] for m in seen["messages"]]
    assert roles == ["user", "assistant", "pending"] and seen["messages"][2]["text"] == "Second question?"
    assert seen["listed"][0]["title"] == "First question?"                          # the title stays the first question
    assert seen["messages"][1]["text"] == first["answer"]


# ---- F8 the reads window -------------------------------------------------------------------------------------------------

def test_f8_one_hundred_and_twenty_reads_a_minute_then_429(c, monkeypatch):
    import users
    assert users.READS_PER_MINUTE == 120
    assert (users.RATE_LIMIT_PER_MINUTE, users.IMPORTS_PER_MINUTE, users.DEFAULT_DAILY_CAP_USD) == (10, 5, 1.00)   # nothing else changed
    clock = {"t": 1000.0}
    monkeypatch.setattr(c.users, "monotonic", lambda: clock["t"])
    codes = [c.client.get("/me", headers=_h()).status_code for _ in range(120)]
    assert codes == [200] * 120
    r = c.client.get("/threads", headers=_h())
    assert r.status_code == 429 and "120" in r.json()["detail"]
    clock["t"] += 61
    assert c.client.get("/me", headers=_h()).status_code == 200


# ---- F12 the console -------------------------------------------------------------------------------------------------------

def test_f12_a_cp1252_console_never_raises_on_an_arrow_an_umlaut_or_a_star():
    import main
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    with pytest.raises(UnicodeEncodeError):
        print("→ ü ★", file=stream)
    main._utf8_console(stream)
    print("  [raw reply: → ü ★]", file=stream)                                       # the line that crashed the W7a turn
    assert stream.encoding.lower().replace("-", "") == "utf8" and stream.errors == "replace"
    assert "→ ü ★".encode("utf-8") in raw.getvalue()
    main._utf8_console(stream)                                                      # idempotent: a UTF-8/replace stream is left alone
    main._utf8_console(object())                                                    # something without reconfigure: no error
    assert stream.encoding.lower().replace("-", "") == "utf8"
