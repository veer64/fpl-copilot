"""Prompt F1b Part 1 (2026-11-02): a thread belongs to the team that was active when it was created.

Accepted from F1a's report: after a team switch the model reused the old team's answer in the same thread (live T2: the
captain right by coincidence, the vice the old team's; T3 previewed the old team's fifteen against the new team). Fix on
the server: chat_threads.owner_key = fpl_teams.squad_owner_id(user) at the thread's creation (NULL = a thread made before
this column: the user's own id).

W1 /chat in a thread whose owner_key differs from the user's CURRENT owner -> 409 {"detail": "active team changed; start a
   new chat", "thread_id": <the user's default thread for the current owner>}: no model call, nothing written to that thread.
W2 POST /me/teams/{id}/activate also starts a new default thread bound to the new owner (returned as thread_id) and cancels the
   user's open preview tickets (count returned); the old thread stays readable (/messages).
W3 /chat with no thread id always runs in a default thread bound to the current owner (a first import activates a team:
   the old default stops being the default, a new one is made).
W4 /threads names each thread's team (its label) or null.
W5 zero-team users and off mode: the owner check never fires -- a legacy thread (owner_key NULL) and a new one (owner_key =
   the user's id) behave as before.
W6 the column: added by threads.ensure_owner_key (guarded, idempotent), legacy rows NULL.

Offline: the app on test_threads' test database, the brain as the model; teams only for test user 10001."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _history, _norm                  # noqa: E402,F401
from test_fpl_teams import teams, U                                                                # noqa: E402,F401
import thread_fakes as tf                                                                          # noqa: E402

SUB = "user_teams"
CHANGED = "active team changed; start a new chat"


@pytest.fixture
def tc(c, teams):
    """Clerk mode; user 10001 signed up, holding team 111 (active) and team 222 (teams' fixture)."""
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) "
                    "VALUES (%s, %s, 't@example.test', 'Teams T', 'email', now())", (U, SUB))
    c.keys = teams
    return c


def _h(sub=SUB):
    return bearer(mint(sub))


def _chat(c, message, thread_id=None, sub=SUB):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    return c.client.post("/chat", json=body, headers=_h(sub))


def _thread_rows(conn, user_id):
    return _q(conn, "SELECT thread_id, is_default, owner_key FROM chat_threads WHERE user_id = %s ORDER BY created_at", (user_id,))


def _checkpoints(conn, tid):
    return _q(conn, "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (tid,))[0][0]


# ---- W1 / W2: the switch ----------------------------------------------------------------------------------------------

def test_w1_after_a_switch_the_old_thread_is_409_with_no_model_call_and_nothing_written(tc):
    r = _chat(tc, "About apple")
    assert r.status_code == 200, r.text
    old = r.json()["thread_id"]
    assert _q(tc.conn, "SELECT owner_key FROM chat_threads WHERE thread_id = %s", (old,)) == [(tc.keys[111],)]
    a = tc.client.post("/me/teams/222/activate", headers=_h())
    assert a.status_code == 200, a.text
    new = a.json()["thread_id"]
    assert new != old and _q(tc.conn, "SELECT owner_key, is_default FROM chat_threads WHERE thread_id = %s", (new,)) == [
        (tc.keys[222], True)]
    before, calls, cps, hist = _all_counts(tc.conn), tc.brain.calls, _checkpoints(tc.conn, old), _norm(_history(old))
    r = _chat(tc, "Who is my captain?", old)
    assert r.status_code == 409 and r.json() == {"detail": CHANGED, "thread_id": new}, r.text
    assert tc.brain.calls == calls and _all_counts(tc.conn) == before
    assert _checkpoints(tc.conn, old) == cps and _norm(_history(old)) == hist
    msgs = tc.client.get(f"/threads/{old}/messages", headers=_h())
    assert msgs.status_code == 200 and [m["text"] for m in msgs.json()] == ["About apple", "Answer to About apple"]


def test_w1_the_new_thread_carries_none_of_the_old_teams_conversation(tc):
    """F1a's T2, offline: the old team's tool output is in the old thread; the new team's first request has none of it."""
    old = _chat(tc, "tool: apple").json()["thread_id"]                          # a tool turn: its result is in the old thread
    new = tc.client.post("/me/teams/222/activate", headers=_h()).json()["thread_id"]
    r = _chat(tc, "About banana", new)
    assert r.status_code == 200 and r.json()["thread_id"] == new
    sent = json.loads(tc.brain.log[-1]["raw"])["messages"]
    assert len(sent) == 1 and "tool_result" not in json.dumps(sent)              # only the new question
    assert _norm(_history(old))[0]["content"] == "tool: apple"


def test_w2_activate_cancels_the_users_open_preview_tickets(tc):
    tid = _chat(tc, tf.PREVIEW_Q).json()["thread_id"]
    assert _q(tc.conn, "SELECT count(*) FROM squad_previews WHERE user_id = %s AND cancelled_at IS NULL AND used_at IS NULL", (U,)) == [(1,)]
    a = tc.client.post("/me/teams/222/activate", headers=_h()).json()
    assert a["preview_tickets_cancelled"] == 1 and a["is_active"] is True and a["fpl_team_id"] == 222
    assert _q(tc.conn, "SELECT count(*) FROM squad_previews WHERE user_id = %s AND cancelled_at IS NULL AND used_at IS NULL", (U,)) == [(0,)]
    r = _chat(tc, tf.YES_Q, tid)                                                 # "yes" in the old thread: refused before any call
    assert r.status_code == 409


def test_w2_switching_back_does_not_reopen_the_old_thread_as_default(tc):
    old = _chat(tc, "About apple").json()["thread_id"]
    tc.client.post("/me/teams/222/activate", headers=_h())
    back = tc.client.post("/me/teams/111/activate", headers=_h()).json()["thread_id"]
    assert back != old                                                           # a fresh default for team 111
    r = _chat(tc, "About cherry", old)                                           # the old thread's team is active again
    assert r.status_code == 200 and r.json()["thread_id"] == old


# ---- W3: no thread id ----------------------------------------------------------------------------------------------

def test_w3_no_thread_id_runs_in_a_default_thread_of_the_current_owner(tc):
    import fpl_teams
    with tc.conn.cursor() as cur:                                               # no team active: the user's own record
        cur.execute("UPDATE user_fpl_teams SET is_active = FALSE WHERE user_id = %s", (U,))
    own = _chat(tc, "About apple").json()["thread_id"]
    assert _q(tc.conn, "SELECT owner_key FROM chat_threads WHERE thread_id = %s", (own,)) == [(U,)]
    fpl_teams.activate(U, 111)                                                   # e.g. a first import activates a team
    r = _chat(tc, "About banana")
    assert r.status_code == 200 and r.json()["thread_id"] != own
    rows = {t: (d, o) for t, d, o in _thread_rows(tc.conn, U)}
    assert rows[own] == (False, U) and rows[r.json()["thread_id"]] == (True, tc.keys[111])
    assert _chat(tc, "About cherry", own).status_code == 409


# ---- W4: /threads names the team ------------------------------------------------------------------------------------

def test_w4_threads_name_their_team(tc):
    old = _chat(tc, "About apple").json()["thread_id"]
    new = tc.client.post("/me/teams/222/activate", headers=_h()).json()["thread_id"]
    legacy = "th_legacy_w4"
    with tc.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_threads (thread_id, user_id) VALUES (%s, %s)", (legacy, U))
    _chat(tc, "About banana", new)                                              # Prompt W4: a thread with no message is not listed
    rows = {x["thread_id"]: x for x in tc.client.get("/threads", headers=_h()).json()}
    assert rows[old]["team_label"] == "Team 111" and rows[new]["team_label"] == "Team 222"
    assert legacy not in rows                                                   # empty: hidden (W4)
    assert set(rows[old]) == {"thread_id", "created_at", "last_active", "is_default", "title", "team_label", "fpl_team_id",
                              "team_name", "updated_at", "is_draft"}            # W4: + team_name, updated_at; W11: + is_draft
    assert (rows[old]["fpl_team_id"], rows[new]["fpl_team_id"]) == (111, 222)   # W3
    assert (rows[old]["team_name"], rows[new]["team_name"]) == ("Team 111", "Team 222")   # W4: the label (else the FPL name)


# ---- W5: zero-team users and off mode ---------------------------------------------------------------------------------

def test_w5_a_zero_team_users_legacy_and_new_threads_never_hit_the_owner_check(app):
    legacy = "th_legacy_w5"
    with app.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_threads (thread_id, user_id) VALUES (%s, 9001)", (legacy,))
    app.mp.setenv("FPL_USER_ID", "9001")
    r = app.client.post("/chat", json={"message": "About apple", "thread_id": legacy})
    assert r.status_code == 200 and {k: r.json()[k] for k in ("answer", "thread_id")} == {"answer": "Answer to About apple", "thread_id": legacy}
    r = app.client.post("/chat", json={"message": "About banana"})
    assert r.status_code == 200 and set(r.json()) == {"answer", "thread_id", "message_id", "sources", "squad_preview", "squad_applied"}   # W4
    assert _q(app.conn, "SELECT owner_key FROM chat_threads WHERE thread_id = %s", (r.json()["thread_id"],)) == [(9001,)]
    r2 = app.client.post("/chat", json={"message": "About cherry", "thread_id": r.json()["thread_id"]})
    assert r2.status_code == 200


def test_w5_off_mode_has_no_activate_route(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    r = app.client.post("/me/teams/111/activate")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


# ---- W6: the column ---------------------------------------------------------------------------------------------------

def test_w6_owner_key_is_added_once_and_legacy_rows_are_null(tdb):
    import threads
    with tdb.cursor() as cur:
        cur.execute("ALTER TABLE chat_threads DROP COLUMN IF EXISTS owner_key")
        cur.execute("INSERT INTO chat_threads (thread_id, user_id) VALUES ('th_w6', 9001)")
    threads.ensure_owner_key(tdb)
    threads.ensure_owner_key(tdb)                                                # idempotent
    assert _q(tdb, "SELECT data_type, is_nullable FROM information_schema.columns WHERE table_name = 'chat_threads' "
                   "AND column_name = 'owner_key'") == [("integer", "YES")]
    assert _q(tdb, "SELECT owner_key FROM chat_threads WHERE thread_id = 'th_w6'") == [(None,)]
    src = (REPO / "threads.py").read_text(encoding="utf-8")
    assert "IF NOT EXISTS (SELECT 1 FROM information_schema.columns" in src     # guarded: no ACCESS EXCLUSIVE lock each run
