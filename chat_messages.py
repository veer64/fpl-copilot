"""The Chat page's per-answer record (Prompt W4, 2026-11-06): what a /chat turn produced beside its text and what the user
said about it, keyed by the answer's message id (= the turn id: the id chat_usage, fact_checks and citation_checks already
carry; the Langfuse trace id derives from it, tracing.trace_id_for).

THE TABLE chat_messages (created idempotently on first use, the project's pattern): message_id, thread_id, user_id, q (the
turn's index in its thread, as the transcript counts it), created_at (the answer's instant), sources / squad_preview /
squad_applied (JSON, derived server-side from the turn's tool calls -- turn_extras; never from the answer text), feedback
("up" | "down" | NULL) + feedback_at. One row per delivered answer, written by agent_graph.run_thread_turn beside the
transcript entry -- so a failed turn writes nothing -- and joined back by message_id (checkpoint C6: the transcript entry
carries the id; the transcript is not model-visible). Answers from before W4 have no row.

Feedback is stored HERE first; the Langfuse score (tracing.score_feedback) is best effort and never gates the answer."""
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
"""
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


def record(message_id, thread_id, user_id, q, created_at, sources=None, squad_preview=None, squad_applied=None, conn=None):
    """One row per answer (a second write of the same id changes nothing). Commits on its own connection."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chat_messages (message_id, thread_id, user_id, q, created_at, sources, squad_preview, squad_applied) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (message_id) DO NOTHING",
                        (str(message_id), str(thread_id), int(user_id), int(q), created_at,
                         psycopg2.extras.Json(list(sources or [])),
                         None if squad_preview is None else psycopg2.extras.Json(squad_preview),
                         None if squad_applied is None else psycopg2.extras.Json(squad_applied)))
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
            cur.execute("SELECT message_id, sources, squad_preview, squad_applied, feedback FROM chat_messages WHERE thread_id = %s",
                        (str(thread_id),))
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
                        "RETURNING message_id, feedback, feedback_at", (score, clock(), str(message_id), int(user_id)))
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()
