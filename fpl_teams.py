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

# ---- the import (Part 5): FPL is read FIRST, with no lock and no transaction open; the rows are written in ONE transaction
# under the user's advisory lock (the team row and its squad version commit together, or neither), so a slow or failing FPL
# leaves nothing behind (fpl_import: 404 -> FplNotFound, 5xx / timeout -> FplUnavailable, nothing written).

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


class AlreadyAdded(Exception):
    """The user already has this FPL team (refresh it instead)."""


class TooManyTeams(Exception):
    """The user already has MAX_TEAMS teams."""


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



def _season():
    import model_tools
    return model_tools._season_label()                 # the label every squad reader uses (squad_store.read_versions)


def _fetch_and_build(fpl_team_id, get=None):
    """(the squad document, info) for this FPL team, from FPL's public API (fpl_import). No database write."""
    import fpl_import
    raw = fpl_import.fetch_team(fpl_team_id, get=get)
    held = [int(p["element"]) for p in raw["picks"][raw["picks_gw"]].get("picks", [])]
    meta = fpl_import.players_live_meta(held)
    return fpl_import.build(raw, meta, _season())


def _note(fpl_team_id, info):
    return f"FPL import of team {int(fpl_team_id)} (picks GW{info['picks_gw']}, for GW{info['version_gw']})"


def add_team(user_id, fpl_team_id, label=None, get=None):
    """Import an FPL team for this user: its squad becomes a NEW squad record (its own squad_key), the first version of
    it written through squad_store.write_version (a direct user action, not the agent's preview lock). The user's FIRST
    team is made active. AlreadyAdded / TooManyTeams before any FPL request (and again under the lock); fpl_import's
    errors pass through with nothing written. Returns the team (PUBLIC_COLS) + version_id, picks_gw, estimated, notes."""
    import squad_store
    uid, fid = int(user_id), int(fpl_team_id)
    current = list_teams(uid, internal=True)
    if any(t["fpl_team_id"] == fid for t in current):
        raise AlreadyAdded(str(fid))
    if len(current) >= MAX_TEAMS:
        raise TooManyTeams(str(MAX_TEAMS))
    doc, info = _fetch_and_build(fid, get=get)
    name = (label if label is not None else info.get("entry_name")) or f"Team {fid}"
    name = " ".join(str(name).split())[:LABEL_MAX] or f"Team {fid}"
    conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_SPACE, uid))
            cur.execute("SELECT fpl_team_id FROM user_fpl_teams WHERE user_id = %s", (uid,))
            have = [r[0] for r in cur.fetchall()]
            if fid in have:
                raise AlreadyAdded(str(fid))
            if len(have) >= MAX_TEAMS:
                raise TooManyTeams(str(MAX_TEAMS))
            cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, is_active, last_imported_at, "
                        "last_imported_gw) VALUES (%s, %s, %s, %s, now(), %s) RETURNING squad_key",
                        (uid, fid, name, not have, info["version_gw"]))
            key = cur.fetchone()[0]
        row = squad_store.write_version(None, doc, info["version_gw"], _note(fid, info), True, conn=conn, user_id=key)
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    team = next(t for t in list_teams(uid) if t["fpl_team_id"] == fid)
    return {**team, "version_id": row["version_id"], "picks_gw": info["picks_gw"], "estimated": info["estimated"],
            "notes": info["notes"]}


def refresh_team(user_id, fpl_team_id, get=None):
    """Re-import one of the user's teams: a NEW version of its squad record (append-only; the old one superseded).
    TeamNotFound before any FPL request when the user has no such team."""
    import squad_store
    uid, fid = int(user_id), int(fpl_team_id)
    if not any(t["fpl_team_id"] == fid for t in list_teams(uid)):
        raise TeamNotFound(str(fid))
    doc, info = _fetch_and_build(fid, get=get)
    conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_SPACE, uid))
            cur.execute("UPDATE user_fpl_teams SET last_imported_at = now(), last_imported_gw = %s "
                        "WHERE user_id = %s AND fpl_team_id = %s RETURNING squad_key", (info["version_gw"], uid, fid))
            got = cur.fetchone()
            if got is None:
                raise TeamNotFound(str(fid))
        key = got[0]
        try:
            active = squad_store.read_active(key, conn=conn)
        except squad_store.NoSquadError:
            active = None
        row = squad_store.write_version(active, doc, info["version_gw"], _note(fid, info), True, conn=conn, user_id=key)
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    team = next(t for t in list_teams(uid) if t["fpl_team_id"] == fid)
    return {**team, "version_id": row["version_id"], "supersedes": row["supersedes"], "picks_gw": info["picks_gw"],
            "estimated": info["estimated"], "notes": info["notes"]}
