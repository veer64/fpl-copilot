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
issued against team A's active version is refused (squad_changed) once team B is active.

THE HOME PAGE (Prompt W3, 2026-11-05). USER DECISIONS (5 Nov): "per user you can only enter 3 teams" (MAX_TEAMS 5 -> 3);
general questions with no team ("not against any team": deactivate -- no team active, the user's own record again); team
scores from FPL's public history (total from GW1), refreshed weekly (eval/refresh_team_scores.py); squads refresh only when
the user taps Refresh (refresh_team, which also updates the summary). The SUMMARY columns (SUMMARY_DDL, guarded -- added
once, never ALTERed again): entry_name, manager_name, total_points, overall_rank, last_gw, last_gw_points (the last FINISHED
gameweek by FPL's bootstrap flags and the team's points in it), updated_after_gw (the finished gameweek the summary reflects),
summary_updated_at, last_used_at (set whenever a chat opens with that team: activate). Stored at import from the responses the
import already fetched (fpl_import.team_summary: entry + history + bootstrap; no extra request), on refresh, and by the
weekly job (history only, ONE request per distinct team, every user's row of it). team_cards() is what GET /me/teams returns."""
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.errors
import psycopg2.extras

import db_write

FIRST_SQUAD_KEY = 900_000_001
LABEL_MAX = 40
MAX_TEAMS = 3                             # USER DECISION (5 Nov 2026): "per user you can only enter 3 teams" (was 5)
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

# Prompt W3: the summary columns, added only when missing -- ALTER TABLE takes an ACCESS EXCLUSIVE lock even when the column
# exists (Prompt B's lesson; threads.OWNER_KEY_DDL is the same pattern). NULL = a row from before the columns.
SUMMARY_COLS = ("entry_name", "manager_name", "total_points", "overall_rank", "last_gw", "last_gw_points",
                "updated_after_gw", "summary_updated_at", "last_used_at")
SUMMARY_DDL = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = 'user_fpl_teams' AND column_name = 'last_used_at') THEN
        ALTER TABLE user_fpl_teams
            ADD COLUMN IF NOT EXISTS entry_name         TEXT,
            ADD COLUMN IF NOT EXISTS manager_name       TEXT,
            ADD COLUMN IF NOT EXISTS total_points       INT,
            ADD COLUMN IF NOT EXISTS overall_rank       INT,
            ADD COLUMN IF NOT EXISTS last_gw            INT,
            ADD COLUMN IF NOT EXISTS last_gw_points     INT,
            ADD COLUMN IF NOT EXISTS updated_after_gw   INT,
            ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_used_at       TIMESTAMPTZ;
    END IF;
END $$;
"""

PUBLIC_COLS = ("fpl_team_id", "label", "is_active", "last_imported_gw")
CARD_COLS = PUBLIC_COLS + SUMMARY_COLS + ("created_at", "last_imported_at")       # GET /me/teams (Prompt W3)
_TIMES = ("summary_updated_at", "last_used_at", "created_at", "last_imported_at")

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
            cur.execute(SUMMARY_DDL)
        conn.commit()
        _SCHEMA_READY.add(_db_key())
    finally:
        if own:
            conn.close()


def _iso(dt):
    """A UTC instant as the website reads it (threads.iso's format): ISO 8601, milliseconds, "Z"; None stays None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def team_cards(user_id, conn=None):
    """Prompt W3: the user's teams as the Home page shows them (CARD_COLS, timestamps as ISO strings), oldest first."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT " + ", ".join(CARD_COLS) + " FROM user_fpl_teams WHERE user_id = %s ORDER BY id", (int(user_id),))
            rows = [dict(r) for r in cur.fetchall()]
        return [{k: (_iso(r[k]) if k in _TIMES else r[k]) for k in CARD_COLS} for r in rows]
    finally:
        if own:
            conn.rollback()
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
            # Prompt W3: a chat opens with this team now -- last_used_at (the Home page's LAST USED tag)
            cur.execute("UPDATE user_fpl_teams SET is_active = TRUE, last_used_at = now() WHERE user_id = %s AND fpl_team_id = %s",
                        (int(user_id), int(fpl_team_id)))
        conn.commit()
        return next(t for t in list_teams(user_id, conn=conn) if t["fpl_team_id"] == int(fpl_team_id))
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def deactivate(user_id, conn=None):
    """Prompt W3 ("general / no team" mode): no team of the user active any more -- the squad tools read the user's own record
    again (squad_owner_id = user_id, the zero-team behaviour). Returns the fpl_team_id that was active, or None."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_SPACE, int(user_id)))
            cur.execute("UPDATE user_fpl_teams SET is_active = FALSE WHERE user_id = %s AND is_active RETURNING fpl_team_id",
                        (int(user_id),))
            row = cur.fetchone()
        conn.commit()
        return int(row[0]) if row else None
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


# ---- the summary (Prompt W3) ----------------------------------------------------------------------------------------------

_SUMMARY_SET = ("entry_name = COALESCE(%(entry_name)s, entry_name), manager_name = COALESCE(%(manager_name)s, manager_name), "
                "total_points = %(total_points)s, overall_rank = %(overall_rank)s, last_gw = %(last_gw)s, "
                "last_gw_points = %(last_gw_points)s, updated_after_gw = %(updated_after_gw)s, summary_updated_at = now()")


def _summary_params(summary):
    s = dict(summary or {})
    return {k: s.get(k) for k in ("entry_name", "manager_name", "total_points", "overall_rank", "last_gw", "last_gw_points",
                                  "updated_after_gw")}


def write_summary(fpl_team_id, summary, conn=None, user_id=None):
    """Store a team's score summary (fpl_import.team_summary / fetch_summary) on every user's row of that FPL team -- or on one
    user's row with user_id given. Names are kept when the summary has none (the weekly job reads history only). Returns the
    number of rows updated. Never touches squad_versions."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        params = {**_summary_params(summary), "fid": int(fpl_team_id), "uid": None if user_id is None else int(user_id)}
        with conn.cursor() as cur:
            cur.execute("UPDATE user_fpl_teams SET " + _SUMMARY_SET + " WHERE fpl_team_id = %(fid)s "
                        "AND (%(uid)s::int IS NULL OR user_id = %(uid)s)", params)
            n = cur.rowcount
        conn.commit()
        return n
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def all_team_ids(conn=None):
    """Every imported FPL team id, once, with the OLDEST updated_after_gw among its rows (None when any row has none):
    the weekly job's work list."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        _ready(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT fpl_team_id, CASE WHEN bool_or(updated_after_gw IS NULL) THEN NULL ELSE min(updated_after_gw) END "
                        "FROM user_fpl_teams GROUP BY fpl_team_id ORDER BY fpl_team_id")
            return [(int(r[0]), None if r[1] is None else int(r[1])) for r in cur.fetchall()]
    finally:
        if own:
            conn.rollback()
            conn.close()



def _season():
    import model_tools
    return model_tools._season_label()                 # the label every squad reader uses (squad_store.read_versions)


def _fetch_and_build(fpl_team_id, get=None):
    """(the squad document, info, the score summary) for this FPL team, from FPL's public API (fpl_import). No database
    write. The summary (Prompt W3) is read from the same responses: no extra request."""
    import fpl_import
    raw = fpl_import.fetch_team(fpl_team_id, get=get)
    held = [int(p["element"]) for p in raw["picks"][raw["picks_gw"]].get("picks", [])]
    meta = fpl_import.players_live_meta(held)
    doc, info = fpl_import.build(raw, meta, _season())
    return doc, info, fpl_import.team_summary(raw)


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
    doc, info, summary = _fetch_and_build(fid, get=get)
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
            cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, is_active, last_imported_at, last_imported_gw, "
                        "entry_name, manager_name, total_points, overall_rank, last_gw, last_gw_points, updated_after_gw, "
                        "summary_updated_at) VALUES (%(uid)s, %(fid)s, %(name)s, %(active)s, now(), %(gw)s, %(entry_name)s, "
                        "%(manager_name)s, %(total_points)s, %(overall_rank)s, %(last_gw)s, %(last_gw_points)s, "
                        "%(updated_after_gw)s, now()) RETURNING squad_key",
                        {**_summary_params(summary), "uid": uid, "fid": fid, "name": name, "active": not have,
                         "gw": info["version_gw"]})
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
    doc, info, summary = _fetch_and_build(fid, get=get)
    conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_SPACE, uid))
            cur.execute("UPDATE user_fpl_teams SET last_imported_at = now(), last_imported_gw = %(gw)s, " + _SUMMARY_SET +
                        " WHERE user_id = %(uid)s AND fpl_team_id = %(fid)s RETURNING squad_key",
                        {**_summary_params(summary), "gw": info["version_gw"], "uid": uid, "fid": fid})
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
