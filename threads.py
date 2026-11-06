"""Per-user conversation threads (Prompt B, 2026-10-31): who owns a thread, which thread is a user's default, and where
a thread's history lives -- LangGraph's Postgres checkpointer.

USER DECISIONS (31 Oct): "Confirm lock stays ticket-based in v1." "History trim: keep the last 10 turns per thread."
Defaults the user accepted: a ticket is bound to user + thread; no thread id -> the user's default thread; the graph is
the default engine, the loop a single-user fallback.

THE USER of a turn is server-side only: config_roles.DEFAULT_USER_ID() (FPL_USER_ID; user 1 on the server). It never
comes from the model or the request body. A thread id from a request is honoured only when chat_threads says that user
owns it; otherwise /chat refuses with 403 before any model call.

THE TABLES (the deploy's schema changes, created idempotently on first use):
- chat_threads (THREADS_DDL): thread_id, user_id, created_at, is_default; at most one default thread per user.
- the checkpointer's own tables (langgraph-checkpoint-postgres's PostgresSaver.setup(): checkpoint_migrations,
  checkpoints, checkpoint_blobs, checkpoint_writes + indexes), run under a Postgres advisory lock so two processes
  starting at once cannot race its migration table.
- squad_previews.thread_id (squad_previews.DDL): a preview ticket is spent only in the thread that issued it.

THE HISTORY: one channel per thread, `messages` -- the list agent.py keeps, exactly as a turn left it (the fact check's
note never in it, the clock line never in it). It is serialised by HistorySerde, JSON with an allowlist: str / numbers /
lists / str-keyed dicts as themselves, the Anthropic SDK's content blocks rebuilt with model_validate from exactly the
fields that were set (model_dump(exclude_unset=True)) -- so the SDK sends the same bytes for them on the next turn --
and any other plain object (a test's fake block) stored as its attributes and read back as a StoredObject carrying
exactly those attributes (its class is named but never imported or instantiated). Nothing is pickled. Anything else
(LangGraph's own bookkeeping) goes to LangGraph's JsonPlusSerializer.

The connection: psycopg 3 (the checkpointer's driver; the rest of the app keeps psycopg2), one pool per process, built
on first use and reused by every turn and thread, autocommit + dict_row + prepare_threshold=0 as
PostgresSaver.from_conn_string uses. Only "localhost" is pinned to its IPv4 address (libpq's hostaddr): on the laptop it
resolves to ::1 first, where nothing listens, and libpq 18 waited out its timeout before trying IPv4 (measured
2026-10-31: 8.0 s vs 0.03 s). Any other host (the server's fpl-postgres) goes to libpq unchanged (Prompt D2,
2026-11-01)."""
import atexit
import importlib
import json
import os
import secrets
import socket
import threading

import config_roles
import db_write

MAX_TURNS = 10                      # USER DECISION: keep the last 10 turns per thread (in the request; the store keeps all)
_SETUP_LOCK_KEY = 7_302_911_031     # pg_advisory_lock key for the checkpointer's setup()

THREADS_DDL = """
CREATE TABLE IF NOT EXISTS chat_threads (
    thread_id   TEXT        PRIMARY KEY,
    user_id     INT         NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_default  BOOLEAN     NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_threads_one_default ON chat_threads (user_id) WHERE is_default;
CREATE INDEX IF NOT EXISTS ix_chat_threads_user ON chat_threads (user_id);
"""


class ThreadRefused(Exception):
    """A thread id the user does not own (or that does not exist): refused before any model call."""


class TeamChanged(Exception):
    """Prompt F1b: the thread belongs to a team (squad owner) that is no longer the user's active one. Carries the user's
    default thread for the CURRENT owner (thread_id), where the conversation continues."""

    def __init__(self, thread_id):
        super().__init__(thread_id)
        self.thread_id = thread_id


# Prompt F1b (2026-11-02): a thread belongs to the squad owner active when it was created (fpl_teams.squad_owner_id: the
# active imported FPL team's squad_key, else the user's own id). Added only when missing -- ALTER TABLE takes an ACCESS
# EXCLUSIVE lock even when the column exists (Prompt B's lesson). NULL = a thread made before the column: the user's own id.
OWNER_KEY_DDL = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = 'chat_threads' AND column_name = 'owner_key') THEN
        ALTER TABLE chat_threads ADD COLUMN owner_key INT;
    END IF;
END $$;
"""


# ---- chat_threads (psycopg2, like the rest of the app) -----------------------------------------------------------------

_SCHEMA_READY = set()


def ensure_schema(conn=None):
    """chat_threads + its indexes (+ owner_key, Prompt F1b), and squad_previews' thread column. Idempotent."""
    import squad_previews
    own = conn is None
    conn = conn or db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(THREADS_DDL)
        conn.commit()
        ensure_owner_key(conn)
        squad_previews.ensure_schema(conn)
    finally:
        if own:
            conn.close()


def ensure_owner_key(conn=None):
    """Prompt F1b's schema step: chat_threads.owner_key INT NULL (OWNER_KEY_DDL). Idempotent."""
    own = conn is None
    conn = conn or db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(OWNER_KEY_DDL)
        conn.commit()
    finally:
        if own:
            conn.close()


def current_owner(user_id):
    """The squad owner the user's squad tools read NOW (fpl_teams.squad_owner_id): the active team's key, else user_id."""
    import fpl_teams
    return int(fpl_teams.squad_owner_id(int(user_id)))


def _effective_owner(user_id, owner_key):
    return int(user_id) if owner_key is None else int(owner_key)


def _conn():
    key = os.getenv("DB_NAME", "fpl")
    conn = db_write.connect()
    if key not in _SCHEMA_READY:
        ensure_schema(conn)
        _SCHEMA_READY.add(key)
    return conn


def new_thread_id():
    return "th_" + secrets.token_urlsafe(18)


def default_thread(user_id, owner=None):
    """The user's default thread for the squad owner active now (`owner`, else current_owner), created on first use.
    Prompt F1b: a default thread of another owner (the user switched team) stops being the default -- it stays theirs and
    readable -- and a new one is made for the current owner."""
    uid = int(user_id)
    owner = current_owner(uid) if owner is None else int(owner)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id, owner_key FROM chat_threads WHERE user_id = %s AND is_default", (uid,))
            row = cur.fetchone()
            if row and _effective_owner(uid, row[1]) == owner:
                return row[0]
            if row:
                cur.execute("UPDATE chat_threads SET is_default = FALSE WHERE thread_id = %s", (row[0],))
            tid = new_thread_id()
            cur.execute("INSERT INTO chat_threads (thread_id, user_id, is_default, owner_key) VALUES (%s, %s, TRUE, %s) "
                        "ON CONFLICT DO NOTHING", (tid, uid, owner))
            conn.commit()
            cur.execute("SELECT thread_id FROM chat_threads WHERE user_id = %s AND is_default", (int(user_id),))
            return cur.fetchone()[0]                     # a concurrent first request may have won: use its thread
    finally:
        conn.close()


def start_new_default(user_id):
    """/reset: the user's current default thread stops being the default (it stays theirs, reachable by id); the next
    /chat without a thread id creates a fresh default. Returns how many rows changed (0 or 1)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE chat_threads SET is_default = FALSE WHERE user_id = %s AND is_default", (int(user_id),))
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def owner(thread_id):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM chat_threads WHERE thread_id = %s", (str(thread_id),))
            row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def create_thread(user_id):
    """Prompt F1a: a new, NON-default thread of the user (the website's "new chat"); its id. Prompt F1b: bound to the squad
    owner active now."""
    owner = current_owner(user_id)
    conn = _conn()
    try:
        tid = new_thread_id()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chat_threads (thread_id, user_id, is_default, owner_key) VALUES (%s, %s, FALSE, %s)",
                        (tid, int(user_id), owner))
        conn.commit()
        return tid
    finally:
        conn.close()


TITLE_MAX = 60
_LIST_SQL = """
SELECT t.thread_id, t.created_at, t.is_default, lc.ts AS last_ts,
       (SELECT convert_from(b.blob, 'UTF8')::jsonb -> 0
          FROM checkpoint_blobs b
         WHERE b.thread_id = t.thread_id AND b.checkpoint_ns = '' AND b.channel = 'messages'
           AND b.version = lc.mv AND b.type = %s) AS first_message,
       {team_label} AS team_label,
       {team_id} AS fpl_team_id,
       {team_name} AS team_name
  FROM chat_threads t
  LEFT JOIN LATERAL (SELECT c.checkpoint ->> 'ts' AS ts, c.checkpoint -> 'channel_versions' ->> 'messages' AS mv
                       FROM checkpoints c
                      WHERE c.thread_id = t.thread_id AND c.checkpoint_ns = ''
                      ORDER BY c.checkpoint_id DESC LIMIT 1) lc ON TRUE
 WHERE t.user_id = %s
"""
# Prompt F1b: the thread's team -- the label of the user's imported team whose squad_key is the thread's owner_key (none for
# a thread of the user's own record, a legacy thread, or before user_fpl_teams exists).
_TEAM_LABEL = "(SELECT f.label FROM user_fpl_teams f WHERE f.user_id = t.user_id AND f.squad_key = t.owner_key LIMIT 1)"
# Prompt W3: and its FPL id, so the Home page's recent chats can name the team (null for the user's own record).
_TEAM_ID = "(SELECT f.fpl_team_id FROM user_fpl_teams f WHERE f.user_id = t.user_id AND f.squad_key = t.owner_key LIMIT 1)"


def iso(dt):
    """A UTC instant as the website reads it: ISO 8601, milliseconds, "Z"."""
    from datetime import datetime, timezone
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def thread_title(text):
    """The first question as a thread's title: [email] / [phone] masked (tracing.mask, the traces' own rule), whitespace
    collapsed, at most TITLE_MAX characters."""
    if not isinstance(text, str) or not text.strip():
        return None
    import tracing
    t = " ".join(tracing.mask(text).split())
    return t if len(t) <= TITLE_MAX else t[:TITLE_MAX - 1].rstrip() + "\u2026"


# Prompt W4 (2026-11-06): the Chat page's tag -- the label, else the FPL team's own name (entry_name, a W3 summary column that
# the guarded DDL adds on first use; absent on a database that never built a team card: then the label alone).
_TEAM_NAME = "(SELECT COALESCE(f.label, f.entry_name) FROM user_fpl_teams f WHERE f.user_id = t.user_id AND f.squad_key = t.owner_key LIMIT 1)"


def list_threads(user_id):
    """Prompt F1a: the user's threads, most recently active first: thread_id, created_at, last_active (the thread's
    latest checkpoint, else its creation), is_default, title (thread_title of the first question), team_label, fpl_team_id
    (W3), team_name and updated_at (W4: the label else the FPL team name; = last_active). Prompt W4 (USER DECISION at the
    checkpoint, no flag): a thread with no message yet is NOT listed. One query: the latest checkpoint of each thread and
    the first element of its stored history (HistorySerde's JSON, read in the database -- the history is never loaded here)."""
    checkpointer()                                       # the checkpoint tables exist (set up once per process)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.user_fpl_teams') IS NOT NULL")
            teams = cur.fetchone()[0]
            named = False
            if teams:
                cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                            "AND table_name = 'user_fpl_teams' AND column_name = 'entry_name'")
                named = cur.fetchone() is not None
            cur.execute(_LIST_SQL.format(team_label=_TEAM_LABEL if teams else "NULL::text",
                                         team_id=_TEAM_ID if teams else "NULL::int",
                                         team_name=_TEAM_NAME if named else (_TEAM_LABEL if teams else "NULL::text")),
                        (TAG, int(user_id)))
            rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for tid, created, is_default, last_ts, first, team_label, fpl_team_id, team_name in rows:
        title = None
        if first is None:
            continue                                     # W4: no message yet -> not listed
        try:
            m = _dec(first)
            if isinstance(m, dict) and m.get("role") == "user":
                title = thread_title(m.get("content"))
        except (ValueError, KeyError, TypeError):
            title = None
        out.append({"thread_id": tid, "created_at": iso(created), "last_active": iso(last_ts or created),
                    "is_default": bool(is_default), "title": title, "team_label": team_label,
                    "fpl_team_id": None if fpl_team_id is None else int(fpl_team_id),
                    "team_name": team_name, "updated_at": iso(last_ts or created)})
    out.sort(key=lambda r: r["last_active"], reverse=True)
    return out


def resolve(user_id, thread_id=None):
    """The thread a /chat turn runs in: the user's default (for the squad owner active now) when no id is given; a given
    id only when the user owns it (else ThreadRefused -- an unknown id and another user's id are refused alike, so the
    answer tells nothing) AND it belongs to the squad owner active now (else TeamChanged, carrying the default thread for
    the current owner: Prompt F1b -- a thread never mixes two teams' squads). For a user with no team the owner is always
    the user's own id, so the check never fires."""
    current = current_owner(user_id)
    if thread_id is None or str(thread_id).strip() == "":
        return default_thread(user_id, current)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, owner_key FROM chat_threads WHERE thread_id = %s", (str(thread_id),))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or row[0] != int(user_id):
        raise ThreadRefused(str(thread_id))
    if _effective_owner(row[0], row[1]) != current:
        raise TeamChanged(default_thread(user_id, current))
    return str(thread_id)


def turn_user():
    """The user of a turn: server-side only (config_roles.DEFAULT_USER_ID, FPL_USER_ID)."""
    return config_roles.DEFAULT_USER_ID()


# ---- the history serializer ----------------------------------------------------------------------------------------

TAG = "fpl_history_json_v1"
_SDK_PREFIX = "anthropic."


class StoredObject:
    """A non-SDK object read back from a stored history (in practice a test's fake content block): exactly the
    attributes it was stored with (its __dict__ holds nothing else, so vars() of it equals vars() of the original).
    `_stored_class` (a slot) names the class it came from; that class is never imported or instantiated."""
    __slots__ = ("__dict__", "_stored_class")

    def __init__(self, stored_class, attrs):
        self.__dict__.update(attrs)
        self._stored_class = stored_class

    def __repr__(self):
        return f"StoredObject({self._stored_class}, {vars(self)})"


def _is_sdk_model(v):
    try:
        import pydantic
    except ImportError:                                   # pragma: no cover
        return False
    return isinstance(v, pydantic.BaseModel) and type(v).__module__.startswith(_SDK_PREFIX)


def _enc(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, list):
        return [_enc(x) for x in v]
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise TypeError("a non-string key")
        return {"__d": {k: _enc(x) for k, x in v.items()}}
    if _is_sdk_model(v):
        return {"__m": f"{type(v).__module__}:{type(v).__qualname__}", "v": v.model_dump(mode="json", exclude_unset=True)}
    attrs = getattr(v, "__dict__", None)
    if isinstance(v, StoredObject):
        return {"__o": v._stored_class, "v": {k: _enc(x) for k, x in vars(v).items()}}
    if isinstance(attrs, dict) and not callable(v):
        return {"__o": f"{type(v).__module__}:{type(v).__qualname__}", "v": {k: _enc(x) for k, x in attrs.items()}}
    raise TypeError(f"not storable in a thread history: {type(v).__module__}:{type(v).__qualname__}")


def _dec(v):
    if isinstance(v, list):
        return [_dec(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "__d" in v:
        return {k: _dec(x) for k, x in v["__d"].items()}
    if "__m" in v:
        mod, name = v["__m"].split(":", 1)
        if not mod.startswith(_SDK_PREFIX):
            raise ValueError(f"refused to rebuild {v['__m']}")
        cls = getattr(importlib.import_module(mod), name)
        return cls.model_validate(v["v"])
    if "__o" in v:
        return StoredObject(v["__o"], {k: _dec(x) for k, x in v["v"].items()})
    raise ValueError("an unmarked object in a stored history")


class HistorySerde:
    """LangGraph's SerializerProtocol: the thread history as allowlisted JSON (see the module docstring); anything this
    cannot encode goes to LangGraph's own JsonPlusSerializer."""

    def __init__(self):
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        self.fallback = JsonPlusSerializer()

    def dumps_typed(self, obj):
        try:
            return TAG, json.dumps(_enc(obj), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except TypeError:
            return self.fallback.dumps_typed(obj)

    def loads_typed(self, data):
        typ, blob = data
        if typ == TAG:
            return _dec(json.loads(blob.decode("utf-8") if isinstance(blob, (bytes, bytearray, memoryview)) else blob))
        return self.fallback.loads_typed(data)


# ---- the checkpointer (psycopg 3) ------------------------------------------------------------------------------------

_SAVERS = {}
_SAVERS_LOCK = threading.Lock()
_ATEXIT = []


def _settings():
    """db_write's five settings (DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD, the same defaults)."""
    return (os.getenv("DB_HOST", "localhost"), os.getenv("DB_PORT", "5432"), os.getenv("DB_NAME", "fpl"),
            os.getenv("DB_USER", "postgres"), os.getenv("DB_PASSWORD", ""))


def conninfo():
    """The app's database as a psycopg 3 conninfo. Only "localhost" is pinned to its IPv4 address (hostaddr); any
    other host goes to libpq unchanged, with no lookup here."""
    from psycopg.conninfo import make_conninfo
    host, port, dbname, user, password = _settings()
    kw = dict(host=host, port=port, dbname=dbname, user=user, password=password)
    if host == "localhost":
        try:
            kw["hostaddr"] = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        except (OSError, ValueError):
            pass
    return make_conninfo(**kw)


def checkpointer():
    """This process's PostgresSaver (one pool), set up once and reused by every turn and thread. Keyed by the five
    settings themselves, so a turn makes no host lookup; a second key only appears when the settings change (tests
    switching DB_NAME)."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from langgraph.checkpoint.postgres import PostgresSaver
    key = _settings()
    with _SAVERS_LOCK:
        saver = _SAVERS.get(key)
        if saver is not None:
            return saver
        pool = ConnectionPool(conninfo(), min_size=1, max_size=8, open=True,
                              kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        saver = PostgresSaver(pool, serde=HistorySerde())
        with pool.connection() as c:
            c.execute("SELECT pg_advisory_lock(%s)", (_SETUP_LOCK_KEY,))
            try:
                saver.setup()
            finally:
                c.execute("SELECT pg_advisory_unlock(%s)", (_SETUP_LOCK_KEY,))
        _SAVERS[key] = saver
        if not _ATEXIT:                                  # close the pools before the interpreter tears down their workers
            atexit.register(_reset)
            _ATEXIT.append(True)
        return saver


def _reset():
    """Tests: close every pool and forget the savers (the next use builds them again)."""
    with _SAVERS_LOCK:
        for saver in _SAVERS.values():
            try:
                saver.conn.close()
            except Exception:                            # noqa: BLE001
                pass
        _SAVERS.clear()
    _SCHEMA_READY.clear()


# ---- one turn at a time per thread ---------------------------------------------------------------------------------

_TURN_LOCKS = {}
_TURN_LOCKS_GUARD = threading.Lock()


def turn_lock(thread_id):
    """A process-local lock per thread: two turns of one thread never interleave (the second waits), so neither
    overwrites the other's history. Different threads run in parallel."""
    with _TURN_LOCKS_GUARD:
        return _TURN_LOCKS.setdefault(str(thread_id), threading.Lock())
