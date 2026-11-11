"""The Chat page's per-answer record (Prompt W4, 2026-11-06): what a /chat turn produced beside its text and what the user
said about it, keyed by the answer's message id (= the turn id: the id chat_usage, fact_checks and citation_checks already
carry; the Langfuse trace id derives from it, tracing.trace_id_for).

THE TABLE chat_messages (created idempotently on first use, the project's pattern): message_id, thread_id, user_id, q (the
turn's index in its thread, as the transcript counts it), created_at (the answer's instant), sources / squad_preview /
squad_applied (JSON, derived server-side from the turn's tool calls -- turn_extras; never from the answer text), feedback
("up" | "down" | NULL) + feedback_at. One row per delivered answer, written by agent_graph.run_thread_turn beside the
transcript entry -- so a failed turn writes nothing -- and joined back by message_id (checkpoint C6: the transcript entry
carries the id; the transcript is not model-visible). Answers from before W4 have no row.

Feedback is stored HERE first; the Langfuse score (tracing.score_feedback) is best effort and never gates the answer.

Prompt W7b (2026-11-11, F3 "refresh during an answer"): the row is written at TURN START as a PENDING entry (status
'pending', question = the user's text, started_at), keyed by the turn's message_id (agent_graph passes the id into the
turn); on success record() turns it into the normal row (status 'done'); on failure drop_pending() removes it, so a failed
turn still leaves the thread unchanged. /threads lists a thread with a pending row (its question as the title) and
/threads/{id}/messages ends with {"role": "pending", "text", "started_at", "message_id"} while the answer is being written.
SCHEMA CHANGE: chat_messages + status TEXT NOT NULL DEFAULT 'done', question TEXT, started_at TIMESTAMPTZ (idempotent ALTERs)."""
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

import db_write

DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id     TEXT        PRIMARY KEY,
    thread_id      TEXT        NOT NULL,
    user_id        INT         NOT NULL,
    q              INT         NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    sources        JSONB       NOT NULL DEFAULT '[]'::jsonb,
    squad_preview  JSONB,
    squad_applied  JSONB,
    feedback       TEXT,
    feedback_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_chat_messages_thread ON chat_messages (thread_id, q);
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'done';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS question TEXT;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
"""
PENDING, DONE = "pending", "done"
SCORES = ("up", "down")
_SCHEMA_READY = set()


def clock():
    return datetime.now(timezone.utc)


def ensure_schema(conn):
    """chat_messages + its index; idempotent, no parameters."""
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def _ready(conn):
    import os
    key = os.getenv("DB_NAME", "fpl")
    if key not in _SCHEMA_READY:
        ensure_schema(conn)
        _SCHEMA_READY.add(key)


def _reset():
    _SCHEMA_READY.clear()


def begin_pending(message_id, thread_id, user_id, q, question, started_at=None, conn=None):
    """Prompt W7b: the turn's in-flight entry, written at turn start (status 'pending'). Commits on its own connection."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        at = started_at or clock()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chat_messages (message_id, thread_id, user_id, q, created_at, status, question, started_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (message_id) DO NOTHING",
                        (str(message_id), str(thread_id), int(user_id), int(q), at, PENDING, question, at))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def drop_pending(message_id, conn=None):
    """Prompt W7b: a failed turn removes its pending entry (a done row is never touched). Returns the rows removed."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_messages WHERE message_id = %s AND status = %s", (str(message_id), PENDING))
            n = cur.rowcount
        conn.commit()
        return n
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def pending_of_thread(thread_id, conn=None):
    """Prompt W7b: the thread's pending entries, oldest first: [{message_id, q, question, started_at}]."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT message_id, q, question, started_at FROM chat_messages WHERE thread_id = %s AND status = %s "
                        "ORDER BY started_at, q", (str(thread_id), PENDING))
            rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()
        return rows
    finally:
        if own:
            conn.close()


def record(message_id, thread_id, user_id, q, created_at, sources=None, squad_preview=None, squad_applied=None, conn=None):
    """One row per answer. Prompt W7b: the pending row of the same id becomes the done row (its question and started_at
    kept); a second write of a DONE id changes nothing. Commits on its own connection."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chat_messages (message_id, thread_id, user_id, q, created_at, sources, squad_preview, squad_applied, status) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (message_id) DO UPDATE SET "
                        "status = EXCLUDED.status, q = EXCLUDED.q, created_at = EXCLUDED.created_at, sources = EXCLUDED.sources, "
                        "squad_preview = EXCLUDED.squad_preview, squad_applied = EXCLUDED.squad_applied "
                        "WHERE chat_messages.status = %s",
                        (str(message_id), str(thread_id), int(user_id), int(q), created_at,
                         psycopg2.extras.Json(list(sources or [])),
                         None if squad_preview is None else psycopg2.extras.Json(squad_preview),
                         None if squad_applied is None else psycopg2.extras.Json(squad_applied), DONE, PENDING))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def by_thread(thread_id, conn=None):
    """{message_id: {sources, squad_preview, squad_applied, feedback}} of a thread's answers."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT message_id, sources, squad_preview, squad_applied, feedback FROM chat_messages "
                        "WHERE thread_id = %s AND status = %s", (str(thread_id), DONE))
            rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()
        return {r["message_id"]: r for r in rows}
    finally:
        if own:
            conn.close()


def set_feedback(user_id, message_id, score, conn=None):
    """The user's verdict on their own answer: "up" / "down" / None (cleared). Returns the row (message_id, feedback,
    feedback_at) or None when the message is not this user's (or does not exist) -- the two answer alike."""
    if score is not None and score not in SCORES:
        raise ValueError(f"score must be one of {SCORES} or null")
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("UPDATE chat_messages SET feedback = %s, feedback_at = %s WHERE message_id = %s AND user_id = %s "
                        "AND status = %s RETURNING message_id, feedback, feedback_at", (score, clock(), str(message_id), int(user_id), DONE))
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()
