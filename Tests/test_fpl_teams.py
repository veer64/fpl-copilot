"""Prompt F1a Part 4 (2026-11-02): several imported FPL teams per user, one active; the squad tools read the active team.

USER DECISIONS (2 Nov): "... we will keep the team ids visible to them ... by this way we can let the user add in more than
1 team." Accepted defaults: each imported team = its own squad record; one active team per user; squad tools read the
active team; the agent's request stays byte-identical.

M1 user_fpl_teams: the sequence starts at 900,000,001; one active team per user; a team id once per user, any number of
   users; ensure_schema is idempotent; squad_versions' DDL is untouched (test_squad_store_writes::test_ddl_is_stable).
M2 squad_owner_id: no team -> the user id itself (the same object); an active team -> its squad_key; no table -> the user id.
M3 every squad tool resolves its owner through model_tools._squad_owner (the one lookup): the owner id reaches the squad
   read (and the write), the user id stays the user's in the output and on the preview ticket.
M4 zero-team users (1, 9001, 9002): every read-only squad tool's output is byte-identical with the lookup in place and
   with it replaced by the identity (the laptop's own data, read-only, as Prompt P6's S3).
M5 the confirm lock: a preview on team A, team B activated, "yes" -> nothing written (squad_changed); without the switch
   the same "yes" writes to team A's record.
M6 GET /me/squad (clerk mode; 404 in off mode): the active squad from get_my_squad's read path; no squad -> {"squad": null}.

Teams are created only for new test users (>= 10001) on test_threads' test database, never for users 1, 9001, 9002."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                                              # noqa: E402
import squad_store                                                                    # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q, _all_counts                      # noqa: E402,F401  (fixtures)
import thread_fakes as tf                                                             # noqa: E402

U = 10_001                                                     # a new test user: teams are never made for 1 / 9001 / 9002
REAL_SUMMARY = squad_store.summary
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def _canon(x):
    return json.dumps(x, sort_keys=True, default=str, ensure_ascii=False)


@pytest.fixture
def teams(tdb):
    """user_fpl_teams fresh on the test database; U has team 111 (active) and team 222, each with one squad version (the
    seed squad), keyed by its squad_key."""
    import fpl_teams
    with tdb.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS user_fpl_teams")
        cur.execute("DROP SEQUENCE IF EXISTS user_fpl_teams_squad_key_seq")
    fpl_teams._SCHEMA_READY.clear()
    fpl_teams.ensure_schema(tdb)
    doc = tf.legal_document()
    keys = {}
    with tdb.cursor() as cur:
        for fid, active in ((111, True), (222, False)):
            cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, is_active, last_imported_gw) "
                        "VALUES (%s, %s, %s, %s, 9) RETURNING squad_key", (U, fid, f"Team {fid}", active))
            keys[fid] = cur.fetchone()[0]
            cur.execute("INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, supersedes, note) "
                        "VALUES (%s, '2026-27', 6, %s, TRUE, NULL, 'teams test seed')", (keys[fid], json.dumps(doc)))
    yield keys
    fpl_teams._SCHEMA_READY.clear()


def _versions(conn, owner):
    return _q(conn, "SELECT count(*) FROM squad_versions WHERE user_id = %s", (owner,))[0][0]


# ---- M1 ----------------------------------------------------------------------------------------------------------------

def test_m1_the_table_its_sequence_and_its_indexes(tdb, teams):
    import fpl_teams
    assert sorted(teams.values()) == [900_000_001, 900_000_002]
    fpl_teams.ensure_schema(tdb)                                                   # idempotent
    idx = {r[0] for r in _q(tdb, "SELECT indexname FROM pg_indexes WHERE tablename = 'user_fpl_teams'")}
    assert "ux_user_fpl_teams_one_active" in idx
    import psycopg2
    with pytest.raises(psycopg2.errors.UniqueViolation):                           # one active team per user
        with tdb.cursor() as cur:
            cur.execute("UPDATE user_fpl_teams SET is_active = TRUE WHERE fpl_team_id = 222")
    with pytest.raises(psycopg2.errors.UniqueViolation):                           # a team once per user
        with tdb.cursor() as cur:
            cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id) VALUES (%s, 111)", (U,))
    with tdb.cursor() as cur:                                                      # ... but by any number of users
        cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id) VALUES (10002, 111) RETURNING squad_key")
        assert cur.fetchone()[0] > 900_000_002                                     # a fresh key (refused inserts leave gaps)


def test_m1_the_sync_sequences_rule_leaves_the_squad_key_sequence_alone(tdb, teams):
    import db_write
    db_write.sync_sequences(tdb)
    assert _q(tdb, "SELECT last_value FROM user_fpl_teams_squad_key_seq")[0][0] == 900_000_002


# ---- M2 ----------------------------------------------------------------------------------------------------------------

def test_m2_no_team_gives_the_user_id_itself_and_an_active_team_its_key(tdb, teams):
    import fpl_teams
    for uid in (9001, "9001", 1, 9002, 10_002):
        assert fpl_teams.squad_owner_id(uid) is uid
    assert fpl_teams.squad_owner_id(U) == teams[111]
    assert fpl_teams.activate(U, 222)["is_active"] is True
    assert fpl_teams.squad_owner_id(U) == teams[222]
    assert [t["fpl_team_id"] for t in fpl_teams.list_teams(U) if t["is_active"]] == [222]
    with pytest.raises(fpl_teams.TeamNotFound):
        fpl_teams.activate(U, 333)
    with pytest.raises(fpl_teams.TeamNotFound):
        fpl_teams.activate(9001, 111)                                              # another user's team id


def test_m2_no_table_means_no_team(tdb):
    import fpl_teams
    with tdb.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS user_fpl_teams")
    fpl_teams._SCHEMA_READY.clear()
    assert fpl_teams.squad_owner_id(9001) == 9001 and fpl_teams.squad_owner_id(U) == U


# ---- M3: every squad call site resolves its owner through the one lookup -------------------------------------------------

KEY = 900_000_042


@pytest.fixture
def routed(monkeypatch):
    """fpl_teams.squad_owner_id: U -> KEY, anyone else -> themselves; every squad read intercepted (no database)."""
    import fpl_teams
    import prices_tool
    asked, seen = [], []
    monkeypatch.setattr(fpl_teams, "squad_owner_id", lambda uid, conn=None: (asked.append(uid), KEY if uid == U else uid)[1])

    def fake_read_active(user_id=None, conn=None):
        seen.append(("read_active", user_id))
        raise squad_store.SquadStateError("intercepted by the test")

    def fake_read_versions(conn, user_id, season):
        seen.append(("read_versions", user_id))
        return []
    monkeypatch.setattr(mt.squad_store, "read_active", fake_read_active)
    monkeypatch.setattr(mt.squad_store, "read_versions", fake_read_versions)
    monkeypatch.setattr(prices_tool, "movements", lambda **kw: {"risers": [], "fallers": []})
    monkeypatch.setattr(mt, "_actuals_master", lambda: (object(), {}))
    import actuals_tool
    monkeypatch.setattr(actuals_tool, "gws_held", lambda master: [8])
    monkeypatch.setattr(mt, "_season_label", lambda: "2026-27")
    return asked, seen


CALLS = {
    "get_my_squad": lambda uid: mt.get_my_squad(user_id=uid),
    "get_my_xi": lambda uid: mt.get_my_xi(user_id=uid),
    "set_my_squad": lambda uid: mt.set_my_squad([1] * 15, 1, 2, [3, 4, 5, 6], user_id=uid),
    "propose_transfers": lambda uid: mt.propose_transfers(user_id=uid),
    "get_my_points": lambda uid: mt.get_my_points(user_id=uid),
    "get_price_movements": lambda uid: mt.get_price_movements(user_id=uid),
    "get_wildcard_gap": lambda uid: mt.get_wildcard_gap(user_id=uid),
}


@pytest.mark.parametrize("tool", list(CALLS))
def test_m3_every_squad_tool_reads_the_active_teams_record(routed, tool):
    asked, seen = routed
    out = CALLS[tool](U)
    assert asked == [U], (tool, asked)
    assert [s[1] for s in seen] == [KEY], (tool, seen)
    if out.get("no_squad"):
        assert out["user_id"] == U                                                 # the user, never the team's key


@pytest.mark.parametrize("tool", list(CALLS))
def test_m3_a_zero_team_user_reads_their_own_record_as_before(routed, tool):
    asked, seen = routed
    CALLS[tool](9001)
    assert asked == [9001] and [s[1] for s in seen] == [9001], (tool, asked, seen)


def test_m3_a_confirm_without_a_ticket_is_refused_before_any_lookup(routed):
    asked, seen = routed
    out = mt.set_my_squad([1] * 15, 1, 2, [3, 4, 5, 6], confirm=True, user_id=U)
    assert out["reason"] == "missing" and asked == [] and seen == []


def test_m3_get_my_squad_shows_the_user_not_the_teams_key(monkeypatch):
    import fpl_teams
    monkeypatch.setattr(fpl_teams, "squad_owner_id", lambda uid, conn=None: KEY if uid == U else uid)
    doc = tf.legal_document()
    record = {"version_id": 77, "user_id": KEY, "season": "2026-27", "gw": 6, "created_at": T0, "is_active": True,
              "supersedes": None, "note": None, "squad_json": doc}
    monkeypatch.setattr(mt, "_read_active", lambda owner: dict(record) if owner == KEY else (_ for _ in ()).throw(AssertionError(owner)))
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [])
    monkeypatch.setattr(mt, "_current_gw", lambda: 9)
    monkeypatch.setattr(mt, "_latest_run", lambda *a, **k: None)
    monkeypatch.setattr(mt, "_with_flags", lambda out: out)
    out = mt.get_my_squad(user_id=U)
    assert out["user_id"] == U and out["version_id"] == 77


# ---- M4: zero-team users' outputs are byte-identical (the laptop's own data, read-only) ---------------------------------

READ_ONLY = {
    "get_my_squad": lambda uid: mt.get_my_squad(user_id=uid),
    "get_my_xi": lambda uid: mt.get_my_xi(user_id=uid),
    "get_my_points": lambda uid: mt.get_my_points(user_id=uid),
    "get_price_movements": lambda uid: mt.get_price_movements(user_id=uid),
}


def _dev_db_or_skip():
    import db_write
    import psycopg2
    try:
        db_write.connect().close()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")


@pytest.mark.parametrize("user", [1, 9001, 9002])
@pytest.mark.parametrize("tool", list(READ_ONLY))
def test_m4_zero_team_outputs_are_byte_identical(monkeypatch, user, tool):
    _dev_db_or_skip()
    import fpl_teams
    assert fpl_teams.squad_owner_id(user) is user                                  # no team for the reserved users
    new = _canon(READ_ONLY[tool](user))
    monkeypatch.setattr(mt, "_squad_owner", lambda uid: uid)                       # the code before Part 4: no lookup
    old = _canon(READ_ONLY[tool](user))
    assert new == old, tool


# ---- M5: the confirm lock across a team switch ----------------------------------------------------------------------------

def _turn(n):
    import turn_context
    return turn_context.begin(turn_id=f"m5turn{n:02d}", started_at=T0 + timedelta(minutes=n))


def _ask(change, n, **kw):
    import turn_context
    _turn(n)
    try:
        return mt.set_my_squad(**change, user_id=U, **kw)
    finally:
        turn_context.end()


CHANGE = dict(tf.CHANGE_A)


def test_m5_a_preview_on_team_a_then_team_b_activated_then_yes_writes_nothing(app, teams):
    import fpl_teams
    before = (_versions(app.conn, teams[111]), _versions(app.conn, teams[222]), _versions(app.conn, U))
    p = _ask(CHANGE, 1)
    assert p.get("preview") is True and p.get("preview_ticket"), p
    assert _q(app.conn, "SELECT user_id FROM squad_previews WHERE id = %s", (p["preview_ticket"],)) == [(U,)]   # the user's ticket
    fpl_teams.activate(U, 222)
    y = _ask(CHANGE, 2, confirm=True, preview_ticket=p["preview_ticket"])
    assert y.get("refused") is True and y["reason"] == "squad_changed", y
    assert (_versions(app.conn, teams[111]), _versions(app.conn, teams[222]), _versions(app.conn, U)) == before


def test_m5_without_the_switch_the_same_yes_writes_to_team_a(app, teams):
    before_b, before_u = _versions(app.conn, teams[222]), _versions(app.conn, U)
    n_a = _versions(app.conn, teams[111])
    p = _ask(CHANGE, 1)
    y = _ask(CHANGE, 2, confirm=True, preview_ticket=p["preview_ticket"])
    assert y.get("committed") is True, y
    assert _versions(app.conn, teams[111]) == n_a + 1                               # team A's record, append-only
    assert (_versions(app.conn, teams[222]), _versions(app.conn, U)) == (before_b, before_u)
    assert _q(app.conn, "SELECT user_id FROM squad_versions WHERE version_id = %s", (y["version_id"],)) == [(teams[111],)]


# ---- M6: GET /me/squad -------------------------------------------------------------------------------------------------

def test_m6_me_squad_is_get_my_squads_read_and_null_without_a_squad(c, teams, monkeypatch):
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) "
                    "VALUES (%s, 'user_teams', 't@example.test', 'Teams T', 'email', now()), "
                    "(10002, 'user_noteam', 'n@example.test', 'No Team', 'email', now())", (U,))
    seen = []

    def fake_get_my_squad(user_id=None):
        seen.append(user_id)
        return mt._no_squad(user_id) if user_id == 10002 else {"version_id": 1, "user_id": user_id, "squad": "stub"}
    monkeypatch.setattr(mt, "get_my_squad", fake_get_my_squad)
    r = c.client.get("/me/squad", headers=bearer(mint("user_teams")))
    assert r.status_code == 200 and r.json() == {"squad": {"version_id": 1, "user_id": U, "squad": "stub"}}
    r = c.client.get("/me/squad", headers=bearer(mint("user_noteam")))
    assert r.status_code == 200 and r.json() == {"squad": None}
    assert seen == [U, 10002]
    assert c.client.get("/me/squad").status_code == 401


def test_m6_me_squad_does_not_exist_in_off_mode(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    r = app.client.get("/me/squad")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_m6_me_names_the_active_team(c, teams):
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) "
                    "VALUES (%s, 'user_teams', 't@example.test', 'Teams T', 'email', now())", (U,))
    me = c.client.get("/me", headers=bearer(mint("user_teams"))).json()
    assert me["user_id"] == U and me["active_team"] == {"fpl_team_id": 111, "label": "Team 111", "is_active": True,
                                                        "last_imported_gw": 9}
    assert c.client.get("/me", headers=bearer(mint("user_a9001"))).json()["active_team"] is None
