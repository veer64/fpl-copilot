"""A user's imported FPL teams (Prompt F1a Part 4, 2026-11-02): which teams a user has, which one is active, and whose
squad_versions rows the squad tools read.

USER DECISIONS (2 Nov): "Yes, we will ask user to enter the team ID, we will keep the team ids visible to them ... by this
way we can let the user add in more than 1 team." Accepted defaults ("Okay"): each imported team = its own squad record;
one active team per user, switched in the UI; squad tools read the active team; the agent's request stays byte-identical.

THE TABLE (DDL; created by ensure_schema -- idempotent, the project's pattern): user_fpl_teams -- id, user_id, fpl_team_id,
label (<= LABEL_MAX), squad_key (UNIQUE, from its own sequence starting FIRST_SQUAD_KEY), is_active (at most one per user:
a partial unique index), created_at, last_imported_at, last_imported_gw; UNIQUE (user_id, fpl_team_id). A team id may be
imported by several users (FPL teams are public).

THE SQUAD RECORD. A team's squad lives in squad_versions under user_id = its squad_key -- a number no user can have (users
are 1, the eval users 9001 / 9002, and app_users from 10001 up; keys start at 900,000,001). squad_versions' DDL, its
one-active-per-user_id index and its append-only trigger are unchanged: each team is just another owner of versions.

ONE LOOKUP. squad_owner_id(user_id): the active team's squad_key when the user has an active team, else user_id itself.
Every squad tool resolves its owner through it (model_tools._squad_owner). A user with no team -- users 1, 9001, 9002
and everyone before an import -- gets their own id back, so their squad tools behave exactly as before; before the
deploy's schema step (no table) every user has no team. Preview tickets stay with the USER (squad_previews): a ticket
issued against team A's active version is refused (squad_changed) once team B is active."""
import os

import psycopg2
import psycopg2.errors
import psycopg2.extras

import db_write

FIRST_SQUAD_KEY = 900_000_001
LABEL_MAX = 40
MAX_TEAMS = 5
FPL_TEAM_ID_MAX = 99_999_999
LOCK_SPACE = 731_102                      # pg_advisory_xact_lock(LOCK_SPACE, user_id): one team change of a user at a time

DDL = f"""
CREATE SEQUENCE IF NOT EXISTS user_fpl_teams_squad_key_seq START WITH {FIRST_SQUAD_KEY} MINVALUE {FIRST_SQUAD_KEY};
CREATE TABLE IF NOT EXISTS user_fpl_teams (
    id                SERIAL      PRIMARY KEY,
    user_id           INT         NOT NULL,
    fpl_team_id       INT         NOT NULL CHECK (fpl_team_id BETWEEN 1 AND {FPL_TEAM_ID_MAX}),
    label             TEXT        CHECK (label IS NULL OR char_length(label) <= {LABEL_MAX}),
    squad_key         INT         NOT NULL UNIQUE DEFAULT nextval('user_fpl_teams_squad_key_seq'),
    is_active         BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_imported_at  TIMESTAMPTZ,
    last_imported_gw  INT,
    UNIQUE (user_id, fpl_team_id)
);
ALTER SEQUENCE user_fpl_teams_squad_key_seq OWNED BY user_fpl_teams.squad_key;
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_fpl_teams_one_active ON user_fpl_teams (user_id) WHERE is_active;
"""

PUBLIC_COLS = ("fpl_team_id", "label", "is_active", "last_imported_gw")

_SCHEMA_READY = set()


class TeamNotFound(Exception):
    """The user has no team with that FPL id."""


def _db_key():
    return tuple(os.getenv(k, "") for k in ("DB_HOST", "DB_PORT", "DB_NAME"))


def ensure_schema(conn=None):
    """The table, its sequence and its indexes. Idempotent."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
        _SCHEMA_READY.add(_db_key())
    finally:
        if own:
            conn.close()


def _ready(conn):
    if _db_key() not in _SCHEMA_READY:
        ensure_schema(conn)


def squad_owner_id(user_id, conn=None):
    """The squad_versions owner the squad tools read for this user: the active team's squad_key, else user_id itself
    (unchanged, whatever type it came in). Read-only; no table yet -> user_id. On a caller's connection nothing is
    committed (the caller rolls back, as after any read)."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT squad_key FROM user_fpl_teams WHERE user_id = %s AND is_active", (user_id,))
            row = cur.fetchone()
        return int(row[0]) if row else user_id
    except psycopg2.errors.UndefinedTable:
        return user_id                                   # before the schema step: nobody has a team
    finally:
        if own:
            conn.rollback()
            conn.close()


def list_teams(user_id, conn=None, internal=False):
    """The user's teams, oldest first: PUBLIC_COLS (+ squad_key, id, last_imported_at with internal=True)."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, fpl_team_id, label, is_active, last_imported_gw, last_imported_at, squad_key "
                        "FROM user_fpl_teams WHERE user_id = %s ORDER BY id", (int(user_id),))
            rows = [dict(r) for r in cur.fetchall()]
        return rows if internal else [{k: r[k] for k in PUBLIC_COLS} for r in rows]
    finally:
        if own:
            conn.rollback()
            conn.close()


def active_team(user_id, conn=None):
    """The user's active team (PUBLIC_COLS), or None."""
    return next((t for t in list_teams(user_id, conn=conn) if t["is_active"]), None)


def activate(user_id, fpl_team_id, conn=None):
    """Make this team the user's active one (the others inactive), in one transaction; TeamNotFound when the user has no
    such team. Returns the team (PUBLIC_COLS)."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_SPACE, int(user_id)))
            cur.execute("SELECT 1 FROM user_fpl_teams WHERE user_id = %s AND fpl_team_id = %s",
                        (int(user_id), int(fpl_team_id)))
            if cur.fetchone() is None:
                conn.rollback()
                raise TeamNotFound(str(fpl_team_id))
            cur.execute("UPDATE user_fpl_teams SET is_active = FALSE WHERE user_id = %s AND is_active "
                        "AND fpl_team_id <> %s", (int(user_id), int(fpl_team_id)))
            cur.execute("UPDATE user_fpl_teams SET is_active = TRUE WHERE user_id = %s AND fpl_team_id = %s",
                        (int(user_id), int(fpl_team_id)))
        conn.commit()
        return next(t for t in list_teams(user_id, conn=conn) if t["fpl_team_id"] == int(fpl_team_id))
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()

