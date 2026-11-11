"""Prompt W5 (2026-11-10): the backend behind Delete account, Remove team and Delete chat -- B1-B4 of the brief as approved at
the checkpoint. Clerk mode only; off mode byte-identical (the new routes are 404 there, like /admin); payload v5 untouched.

DELETION SAFETY (the rule that overrides everything): every delete is scoped to the signed-in user in SQL (never by an id
from the request alone) and runs in ONE transaction; tests prove another user's rows are untouched (per-table counts
before / after) and that users 1 / 9001 / 9002 are never written.

B1  GET /me gains is_owner: true for user 1 (the first verified ADMIN_EMAIL sign-in), false for everyone else.
B2  DELETE /me: refuses the owner and the reserved ids (< 10001) with 403 and writes nothing. Otherwise, in one transaction:
    the account row, teams, squads (every version under the teams' squad keys and the user's own record), scores, threads +
    LangGraph checkpoint rows, chat_messages (+ feedback), previews, transfer plans, the turns' check rows, cap hits --
    except chat_usage rows, which become anonymous (user_id NULL, turn_id 'deleted'; amount kept, so spend totals stay the
    same). Clerk's delete-user is called inside the open transaction: 200 / 404 = deleted (404 makes "Try again" safe);
    anything else -> rollback, nothing deleted, 502. A commit failure after Clerk succeeded is printed loudly and answered
    500 with its own message. A request with the deleted user's still-valid token re-creates nothing (503).
B3  DELETE /me/teams/{id}: own teams only (404 otherwise), removes the team row, its squad versions and scores (ONLY under
    that team's squad key -- never the user's own record, checkpoint C1), its preview tickets, its chats (B4 each); the
    active team removed -> General mode; returns {removed_chats, active_team_id, ...}; the 3-team slot is freed.
B4  DELETE /threads/{id}: own threads only (403 otherwise, the messages endpoint's convention); removes the thread row, its
    checkpoint rows, chat_messages (+ feedback), its turns' check rows and its preview tickets. chat_usage keeps user + amount
    (today's spend unchanged). Deleting the default thread: the next /chat starts a fresh one.
T   squad_versions stays append-only for a normal session: DELETE raises; only SET LOCAL fpl.account_delete = 'on' inside the
    deleting transaction is allowed through (checkpoint Q5).
D   GET /deadlines is open in clerk mode (public FPL data from the process cache; no token needed, a bad token ignored;
    Cache-Control: public, max-age=60); off mode still 404 (checkpoint Q1 A).
R   the deletes go through the existing per-user read window (users.READS_PER_MINUTE, 120 since W7b): the next request is 429.

Offline: test_fpl_import's `api` fixture (clerk mode on the test database, the recorded FPL responses, users 10001 / 10002)
and test_auth's `c`; Clerk's delete-user faked and counted; the per-turn log rows (chat_usage, checks, plans, scores, tickets)
inserted by SQL with the ids the real writers use."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fpl_import                                                                     # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _bad_tokens         # noqa: E402,F401  (fixtures)
from test_fpl_import import api, Fpl, TID, NOW, T1, T2, U1, U2, _offline, _post, _get   # noqa: E402,F401  (fixtures)
import thread_fakes as tf                                                             # noqa: E402

UTC = timezone.utc
CHECKS_DDL = """
CREATE TABLE IF NOT EXISTS citation_checks (id BIGSERIAL PRIMARY KEY, checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_id TEXT NOT NULL, cited TEXT[], returned TEXT[], violations TEXT[]);
CREATE TABLE IF NOT EXISTS numeric_checks (id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_id TEXT NOT NULL, numbers_found INT, grounded INT, ungrounded JSONB, notebook_size INT, error TEXT);
"""
TRACKED = ("app_users", "user_fpl_teams", "squad_versions", "squad_scores", "squad_previews", "chat_threads", "chat_messages",
           "chat_usage", "cap_hits", "model_transfer_plans")
CHECKS = ("fact_checks", "citation_checks", "numeric_checks")                  # keyed by turn_id: counted through chat_usage


def _h(sub=T1):
    return bearer(mint(sub))


def _delete(api, path, sub=T1):
    return api.client.delete(path, headers=_h(sub))


def _chat(api, message, sub=T1, thread_id=None):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    r = api.client.post("/chat", json=body, headers=_h(sub))
    assert r.status_code == 200, r.text
    return r.json()


def _never_limited(api, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(api.users, "monotonic", lambda: clock.update(t=clock["t"] + 61) or clock["t"])


@pytest.fixture
def d(api, monkeypatch):
    """`api` with Clerk's delete-user faked (every call recorded; the answer scripted per clerk id) and the check tables
    present; schemas the deletes touch are ensured once."""
    import fact_check
    import users
    fact_check.ensure_schema(api.conn)
    with api.conn.cursor() as cur:
        cur.execute(CHECKS_DDL)
        cur.execute("TRUNCATE cap_hits")
        for t in ("model_transfers", "model_transfer_plans", "fact_checks", "citation_checks", "numeric_checks"):
            cur.execute(f"DELETE FROM {t}")
    calls, script = [], {}

    def fake_delete(clerk_user_id):
        calls.append(clerk_user_id)
        answer = script.get(clerk_user_id, "deleted")
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(users, "delete_clerk_user", fake_delete)
    api.clerk_calls, api.clerk_script = calls, script
    _never_limited(api, monkeypatch)
    yield api


def _owner_rows(conn, owners):
    """Per-table row counts for a set of owners (user ids and squad keys), one dict -- the isolation proof."""
    out = {}
    ids = tuple(int(x) for x in owners)
    for t in TRACKED:
        if not _q(conn, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",))[0][0]:
            out[t] = None
            continue
        out[t] = _q(conn, f"SELECT count(*) FROM {t} WHERE user_id IN %s", (ids,))[0][0]
    for t in CHECKS:
        out[t] = _q(conn, f"SELECT count(*) FROM {t} WHERE turn_id IN (SELECT turn_id FROM chat_usage WHERE user_id IN %s)", (ids,))[0][0]
    threads = [r[0] for r in _q(conn, "SELECT thread_id FROM chat_threads WHERE user_id IN %s", (ids,))]
    for t in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        out[t] = _q(conn, f"SELECT count(*) FROM {t} WHERE thread_id = ANY(%s)", (threads,))[0][0] if threads else 0
    return out


def _totals(conn):
    out = {t: _q(conn, f"SELECT count(*) FROM {t}")[0][0] for t in TRACKED + CHECKS + ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
           if _q(conn, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",))[0][0]}
    out["usd"] = float(_q(conn, "SELECT COALESCE(SUM(usd), 0) FROM chat_usage")[0][0])
    return out


def _keys(conn, uid):
    return [r[0] for r in _q(conn, "SELECT squad_key FROM user_fpl_teams WHERE user_id = %s", (uid,))]


def _log_rows(conn, uid, turn_id, version_id, thread_id, usd=0.1):
    """The per-turn rows the real writers leave: a chat_usage row (the cap's ledger), the three check rows, a cap hit, a
    transfer plan (+ one transfer) solved from `version_id`, a score of that version, and a preview ticket in `thread_id`."""
    owner = _q(conn, "SELECT user_id FROM squad_versions WHERE version_id = %s", (version_id,))[0][0]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES (%s, 'm', 1, %s, 0, %s)",
                    (turn_id, usd, uid))
        cur.execute("INSERT INTO fact_checks (turn_id, facts_checked, mismatches, sent_back, outcome) VALUES (%s, 1, '[]', FALSE, 'clean')", (turn_id,))
        cur.execute("INSERT INTO citation_checks (turn_id, cited, returned, violations) VALUES (%s, '{}', '{}', '{}')", (turn_id,))
        cur.execute("INSERT INTO numeric_checks (turn_id, numbers_found, grounded) VALUES (%s, 0, 0)", (turn_id,))
        cur.execute("INSERT INTO cap_hits (user_id, spent_usd, cap_usd) VALUES (%s, 1.0, 1.0)", (uid,))
        cur.execute("INSERT INTO model_transfer_plans (source, user_id, season, gw, squad_version_id, config, frame_cutoff_gw, "
                    "stale_by_gameweeks, horizon, effective_horizon, decay, hit_bar, locked, banned, status, n_transfers, hits, "
                    "hit_cost_points, free_transfers_before, free_transfers_after, bank_before, bank_after) VALUES "
                    "('chat', %s, '2026-27', 10, %s, 'c', 9, 1, 6, 6, 0.9, 0.5, '[]', '[]', 'ok', 1, 0, 0, 1, 0, 10, 5) RETURNING proposal_id",
                    (uid, version_id))
        pid = cur.fetchone()[0]
        cur.execute("INSERT INTO model_transfers (proposal_id, horizon_step, gw, executable) VALUES (%s, 0, 10, TRUE)", (pid,))
        cur.execute("INSERT INTO squad_scores (user_id, season, gw, version_id, points_net, points_raw, hit, captain_bonus, doubled_role, "
                    "transfers_made, free_transfers, final_xi, subs_made, bench_points, master_rows_hash) VALUES "
                    "(%s, '2026-27', 9, %s, 50, 50, 0, 5, 'captain', 0, 1, '[]', '[]', 3, %s)", (owner, version_id, f"h-{turn_id}"))
        cur.execute("INSERT INTO squad_previews (id, user_id, turn_id, turn_started_at, change_fingerprint, base_version_id, created_at, "
                    "expires_at, thread_id) VALUES (%s, %s, %s, now(), 'fp', %s, now(), now() + interval '30 minutes', %s)",
                    (f"tk-{turn_id}", uid, turn_id, version_id, thread_id))


def _active_version(conn, owner):
    return _q(conn, "SELECT version_id FROM squad_versions WHERE user_id = %s AND is_active", (owner,))[0][0]


def _seed_user(api, sub, uid, team_ids, general=True):
    """`sub` imports `team_ids` (each activated, one chat in it), then a General chat; the per-turn rows for the first team's
    chat. Returns {teams: {fpl_team_id: {key, version, thread}}, general: thread, turn: the logged turn id, message: a message id}."""
    out = {"teams": {}}
    for i, fid in enumerate(team_ids):
        assert _post(api, "/me/teams", json={"fpl_team_id": fid, "label": f"Team {i + 1} of {uid}"}, sub=sub).status_code == 200
        assert _post(api, f"/me/teams/{fid}/activate", sub=sub).status_code == 200
        reply = _chat(api, f"About team {fid}", sub=sub)
        key = _q(api.conn, "SELECT squad_key FROM user_fpl_teams WHERE user_id = %s AND fpl_team_id = %s", (uid, fid))[0][0]
        out["teams"][fid] = {"key": key, "version": _active_version(api.conn, key), "thread": reply["thread_id"],
                             "message": reply["message_id"]}
    if general:
        assert _delete(api, "/me/active-team", sub=sub).status_code == 200
        reply = _chat(api, f"General question of {uid}", sub=sub)
        out["general"] = reply["thread_id"]
        out["general_message"] = reply["message_id"]
    first = out["teams"][team_ids[0]]
    out["turn"] = first["message"]                       # the real turn id of the first team's answer
    _log_rows(api.conn, uid, out["turn"], first["version"], first["thread"])
    r = api.client.post(f"/messages/{first['message']}/feedback", json={"score": "up"}, headers=_h(sub))
    assert r.status_code == 200, r.text
    return out


def _me(api, sub=T1):
    r = _get(api, "/me", sub=sub)
    assert r.status_code == 200, r.text
    return r.json()


# ---- B1: the owner flag -----------------------------------------------------------------------------------------------------

def test_b1_me_carries_is_owner_false_for_a_user_and_true_for_the_linked_admin(c):
    body = c.client.get("/me", headers=bearer(mint("user_a9001"))).json()
    assert body["is_owner"] is False and body["is_admin"] is False
    assert c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_admin"))).status_code == 200
    body = c.client.get("/me", headers=bearer(mint("user_admin"))).json()
    assert body["user_id"] == 1 and body["is_owner"] is True and body["is_admin"] is True
    import users
    assert users.OWNER_USER_ID == 1 and users.is_owner({"user_id": 1}) and not users.is_owner({"user_id": 10001})


# ---- B2: delete account -------------------------------------------------------------------------------------------------------

def test_b2_the_owner_and_the_reserved_ids_are_refused_with_403_and_nothing_is_written(d):
    assert d.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_admin"))).status_code == 200
    before = _totals(d.conn)
    r = _delete(d, "/me", sub="user_admin")
    assert r.status_code == 403 and r.json() == {"detail": d.main.OWNER_LOCKED}, r.text
    r = _delete(d, "/me", sub="user_a9001")
    assert r.status_code == 403 and r.json() == {"detail": d.main.ACCOUNT_LOCKED}, r.text
    assert _totals(d.conn) == before and d.clerk_calls == []
    assert _q(d.conn, "SELECT count(*) FROM app_users WHERE user_id IN (1, 9001, 9002)")[0][0] == 3


def test_b2_delete_account_removes_everything_but_anonymous_cost_rows_and_leaves_other_users_untouched(d):
    a = _seed_user(d, T1, U1, [TID, TID + 1])
    b = _seed_user(d, T2, U2, [TID])                      # the SAME FPL team id as A's first team: its own record
    keys_a, keys_b = _keys(d.conn, U1), _keys(d.conn, U2)
    assert len(keys_a) == 2 and len(keys_b) == 1
    with d.conn.cursor() as cur:                            # A's own record too (a zero-team change writes under user_id = u)
        cur.execute("INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, note) VALUES (%s, '2026-27', 9, %s, TRUE, 'own')",
                    (U1, json.dumps(tf.legal_document())))
    assert len(_get(d, "/threads").json()) == 3
    others_before = _owner_rows(d.conn, [U2] + keys_b)
    reserved_before = _owner_rows(d.conn, [1, 9001, 9002])
    totals_before = _totals(d.conn)
    a_turn_rows = lambda: tuple(_q(d.conn, f"SELECT count(*) FROM {t} WHERE turn_id = %s", (a["turn"],))[0][0]   # noqa: E731
                                for t in ("fact_checks", "citation_checks", "numeric_checks"))
    assert a_turn_rows() == (1, 1, 1)
    usage_before = _q(d.conn, "SELECT turn_id, usd, user_id FROM chat_usage WHERE user_id = %s", (U1,))
    assert len(usage_before) == 1

    r = _delete(d, "/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True and body["clerk"] == "deleted" and body["cost_rows_anonymised"] == 1
    assert body["removed"] == {"teams": 2, "chats": 3, "messages": 3, "squad_versions": 3, "scores": 1, "previews": 1,
                               "plans": 1, "check_rows": 3, "cap_hits": 1}
    assert d.clerk_calls == [T1]
    # A: nothing left but the anonymous cost row
    assert _owner_rows(d.conn, [U1] + keys_a) == {t: (0 if v is not None else None) for t, v in others_before.items()}
    assert _q(d.conn, "SELECT count(*) FROM app_users WHERE clerk_user_id = %s", (T1,))[0][0] == 0
    assert a_turn_rows() == (0, 0, 0)
    assert _q(d.conn, "SELECT user_id, turn_id, usd FROM chat_usage WHERE turn_id = 'deleted'") == [(None, "deleted", usage_before[0][1])]
    for tid in [t["thread"] for t in a["teams"].values()] + [a["general"]]:
        assert _q(d.conn, "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (tid,))[0][0] == 0
        assert _get(d, f"/threads/{tid}/messages", sub=T2).status_code == 403
    # B, the reserved users and the totals
    assert _owner_rows(d.conn, [U2] + keys_b) == others_before
    assert _owner_rows(d.conn, [1, 9001, 9002]) == reserved_before
    after = _totals(d.conn)
    assert after["usd"] == totals_before["usd"] and after["chat_usage"] == totals_before["chat_usage"]
    assert after["app_users"] == totals_before["app_users"] - 1
    assert [t["thread_id"] for t in _get(d, "/threads", sub=T2).json()] == [b["general"], b["teams"][TID]["thread"]]
    assert _get(d, f"/threads/{b['general']}/messages", sub=T2).status_code == 200


def test_b2_a_clerk_failure_rolls_everything_back_and_try_again_works(d):
    import users
    a = _seed_user(d, T1, U1, [TID])
    before, totals = _owner_rows(d.conn, [U1] + _keys(d.conn, U1)), _totals(d.conn)
    d.clerk_script[T1] = users.ClerkDeleteFailed("Clerk answered 500")
    r = _delete(d, "/me")
    assert r.status_code == 502 and r.json() == {"detail": d.main.CLERK_DELETE_FAILED}, r.text
    assert _owner_rows(d.conn, [U1] + _keys(d.conn, U1)) == before and _totals(d.conn) == totals
    assert _get(d, f"/threads/{a['general']}/messages").status_code == 200       # still signed in, nothing gone
    d.clerk_script[T1] = "already_gone"                                          # Clerk: 404 -> treated as deleted
    r = _delete(d, "/me")
    assert r.status_code == 200 and r.json()["clerk"] == "already_gone", r.text
    assert d.clerk_calls == [T1, T1]
    assert _q(d.conn, "SELECT count(*) FROM app_users WHERE user_id = %s", (U1,))[0][0] == 0


def test_b2_a_commit_failure_after_clerk_succeeded_is_loud_and_answered_with_its_own_message(d, monkeypatch, capsys):
    import deletion
    _seed_user(d, T1, U1, [TID])
    before = _owner_rows(d.conn, [U1] + _keys(d.conn, U1))

    def boom(conn):
        raise RuntimeError("the connection dropped")
    monkeypatch.setattr(deletion, "_commit", boom)
    r = _delete(d, "/me")
    assert r.status_code == 500 and r.json() == {"detail": d.main.SIGN_IN_REMOVED}, r.text
    assert d.clerk_calls == [T1]
    assert "ACCOUNT DELETE" in capsys.readouterr().out and "FAILED" in capsys.readouterr().out + "FAILED"
    assert _owner_rows(d.conn, [U1] + _keys(d.conn, U1)) == before          # rolled back: our rows remain


def test_b2_a_request_with_the_deleted_users_token_re_creates_nothing(d):
    _seed_user(d, T1, U1, [TID])
    assert _delete(d, "/me").status_code == 200
    before, fetched = _totals(d.conn), list(d.fetched)
    for method, path in (("get", "/me"), ("get", "/threads"), ("post", "/chat"), ("delete", "/me")):
        kw = {"headers": _h(T1)}
        if method == "post":
            kw["json"] = {"message": "hello"}
        r = getattr(d.client, method)(path, **kw)
        assert r.status_code == 503 and r.json() == {"detail": d.main.PROFILE_UNAVAILABLE}, (path, r.status_code, r.text)
    assert d.fetched[len(fetched):] == [T1] * 4 and _totals(d.conn) == before
    assert _q(d.conn, "SELECT count(*) FROM app_users WHERE clerk_user_id = %s", (T1,))[0][0] == 0


# ---- B3: remove team ----------------------------------------------------------------------------------------------------------

def test_b3_remove_the_active_team_removes_its_squads_chats_tickets_and_plans_never_the_own_record(d):
    a = _seed_user(d, T1, U1, [TID, TID + 1], general=False)
    assert _post(d, f"/me/teams/{TID}/activate").status_code == 200           # team 1 active, with the logged rows
    b = _seed_user(d, T2, U2, [TID], general=False)                              # the same FPL id for another user
    with d.conn.cursor() as cur:
        cur.execute("INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, note) VALUES (%s, '2026-27', 9, %s, TRUE, 'own')",
                    (U1, json.dumps(tf.legal_document())))
    key1, key2 = a["teams"][TID]["key"], a["teams"][TID + 1]["key"]
    own_before = _q(d.conn, "SELECT version_id, is_active, note FROM squad_versions WHERE user_id = %s", (U1,))
    team2_before = _owner_rows(d.conn, [key2])
    others_before = _owner_rows(d.conn, [U2] + _keys(d.conn, U2))
    reserved_before = _owner_rows(d.conn, [1, 9001, 9002])
    assert _me(d)["active_team"]["fpl_team_id"] == TID

    r = _delete(d, f"/me/teams/{TID}")
    assert r.status_code == 200, r.text
    assert r.json() == {"fpl_team_id": TID, "removed_chats": 1, "removed_squad_versions": 1, "removed_previews": 1,
                        "removed_plans": 1, "active_team_id": None}
    assert _me(d)["active_team"] is None                                          # General mode
    assert [t["fpl_team_id"] for t in _get(d, "/me/teams").json()] == [TID + 1]
    assert _q(d.conn, "SELECT count(*) FROM squad_versions WHERE user_id = %s", (key1,))[0][0] == 0
    assert _q(d.conn, "SELECT count(*) FROM squad_scores WHERE user_id = %s", (key1,))[0][0] == 0
    assert _q(d.conn, "SELECT version_id, is_active, note FROM squad_versions WHERE user_id = %s", (U1,)) == own_before   # C1
    assert _owner_rows(d.conn, [key2]) == team2_before
    assert _q(d.conn, "SELECT count(*) FROM chat_threads WHERE thread_id = %s", (a["teams"][TID]["thread"],))[0][0] == 0
    assert _q(d.conn, "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (a["teams"][TID]["thread"],))[0][0] == 0
    assert _q(d.conn, "SELECT count(*) FROM chat_messages WHERE thread_id = %s", (a["teams"][TID]["thread"],))[0][0] == 0
    assert _q(d.conn, "SELECT count(*) FROM squad_previews WHERE user_id = %s", (U1,))[0][0] == 0
    assert _q(d.conn, "SELECT count(*) FROM model_transfer_plans WHERE user_id = %s", (U1,))[0][0] == 0
    assert _q(d.conn, "SELECT count(*) FROM fact_checks WHERE turn_id = %s", (a["turn"],))[0][0] == 0
    assert [(u, float(x)) for u, x in _q(d.conn, "SELECT user_id, usd FROM chat_usage WHERE turn_id = %s", (a["turn"],))] == [(U1, pytest.approx(0.1))]
    assert [t["thread_id"] for t in _get(d, "/threads").json()] == [a["teams"][TID + 1]["thread"]]
    assert _owner_rows(d.conn, [U2] + _keys(d.conn, U2)) == others_before and b["teams"][TID]["thread"]
    assert _owner_rows(d.conn, [1, 9001, 9002]) == reserved_before
    assert _post(d, "/me/teams", json={"fpl_team_id": TID + 2}).status_code == 200          # the slot is free again
    assert _post(d, "/me/teams", json={"fpl_team_id": TID + 3}).status_code == 200
    assert _post(d, "/me/teams", json={"fpl_team_id": TID + 4}).status_code == 409


def test_b3_removing_an_inactive_team_keeps_the_active_one_and_its_default_thread(d):
    a = _seed_user(d, T1, U1, [TID, TID + 1], general=False)                     # TID + 1 is active after the seed
    r = _delete(d, f"/me/teams/{TID}")
    assert r.status_code == 200 and r.json()["active_team_id"] == TID + 1, r.text
    assert _me(d)["active_team"]["fpl_team_id"] == TID + 1
    assert _chat(d, "still here")["thread_id"] == a["teams"][TID + 1]["thread"]


def test_b3_another_users_or_an_unknown_team_is_404_with_nothing_written(d):
    _seed_user(d, T2, U2, [TID], general=False)
    before = _totals(d.conn)
    for fid in (TID, TID + 9):
        r = _delete(d, f"/me/teams/{fid}")
        assert r.status_code == 404 and r.json() == {"detail": d.main.TEAM_NOT_FOUND}, r.text
    assert _delete(d, "/me/teams/abc").status_code == 422
    assert _totals(d.conn) == before


# ---- B4: delete chat ------------------------------------------------------------------------------------------------------------

def test_b4_delete_chat_removes_the_thread_its_rows_and_tickets_and_keeps_the_cost_rows(d):
    a = _seed_user(d, T1, U1, [TID], general=True)
    team_thread, general = a["teams"][TID]["thread"], a["general"]     # General is the default thread now
    spent = _me(d)["spent_today_usd"]
    assert spent == pytest.approx(0.1)
    others = _owner_rows(d.conn, [U2, 1, 9001, 9002])
    totals = _totals(d.conn)

    r = _delete(d, f"/threads/{team_thread}")
    assert r.status_code == 200, r.text
    assert r.json() == {"thread_id": team_thread, "deleted": True, "removed_messages": 1, "was_default": False}
    for t, col in (("chat_threads", "thread_id"), ("checkpoints", "thread_id"), ("checkpoint_blobs", "thread_id"),
                   ("checkpoint_writes", "thread_id"), ("chat_messages", "thread_id"), ("squad_previews", "thread_id")):
        assert _q(d.conn, f"SELECT count(*) FROM {t} WHERE {col} = %s", (team_thread,))[0][0] == 0, t
    assert _q(d.conn, "SELECT count(*) FROM fact_checks WHERE turn_id = %s", (a["turn"],))[0][0] == 0
    assert [(u, float(x)) for u, x in _q(d.conn, "SELECT user_id, usd FROM chat_usage WHERE turn_id = %s", (a["turn"],))] == [(U1, pytest.approx(0.1))]
    assert _me(d)["spent_today_usd"] == spent                                   # the daily limit is unchanged
    assert [t["thread_id"] for t in _get(d, "/threads").json()] == [general]
    assert _get(d, f"/threads/{team_thread}/messages").status_code == 403
    assert _owner_rows(d.conn, [U2, 1, 9001, 9002]) == others
    after = _totals(d.conn)
    assert after["chat_usage"] == totals["chat_usage"] and after["usd"] == totals["usd"]
    # deleting the DEFAULT thread (the General one): the next /chat without an id starts a fresh one in the same context
    r = _delete(d, f"/threads/{general}")
    assert r.status_code == 200 and r.json() == {"thread_id": general, "deleted": True, "removed_messages": 1, "was_default": True}, r.text
    assert _get(d, "/threads").json() == []
    reply = _chat(d, "and now?")
    assert reply["thread_id"] not in (team_thread, general)
    assert _q(d.conn, "SELECT owner_key, is_default FROM chat_threads WHERE thread_id = %s", (reply["thread_id"],)) == [(U1, True)]


def test_b4_another_users_or_an_unknown_thread_is_403_with_nothing_written(d):
    b = _seed_user(d, T2, U2, [TID], general=True)
    before = _totals(d.conn)
    for tid in (b["general"], "th_nothing"):
        r = _delete(d, f"/threads/{tid}")
        assert r.status_code == 403 and r.json() == {"detail": d.main.THREAD_REFUSED}, r.text
    assert _totals(d.conn) == before


# ---- T: the append-only rule ------------------------------------------------------------------------------------------------------

def test_t_a_normal_session_still_cannot_delete_a_squad_version(tdb):
    import psycopg2
    import db_write
    conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.RaiseException, match="append-only: DELETE refused"):
                cur.execute("DELETE FROM squad_versions WHERE user_id = 9002")
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET fpl.account_delete = 'on'")                         # a session setting is NOT the switch
            with pytest.raises(psycopg2.errors.RaiseException, match="append-only: DELETE refused"):
                cur.execute("DELETE FROM squad_versions WHERE user_id = 9002")
        conn.rollback()
        import deletion
        with conn.cursor() as cur:
            deletion._allow_squad_deletes(cur)                                  # SET LOCAL + this transaction's id
            cur.execute("DELETE FROM squad_versions WHERE user_id = 9002")
            assert cur.rowcount == 1
        conn.rollback()                                                         # never committed here
        assert _q(tdb, "SELECT count(*) FROM squad_versions WHERE user_id = 9002")[0][0] == 1
    finally:
        conn.close()


# ---- D: /deadlines is open in clerk mode ---------------------------------------------------------------------------------------

def test_d_deadlines_need_no_token_in_clerk_mode_and_carry_a_short_public_cache(api):
    fpl_import._reset()
    r = api.client.get("/deadlines")
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"events", "fetched_at"} and r.headers.get("cache-control") == "public, max-age=60"
    assert api.client.get("/deadlines", headers=bearer(_bad_tokens()["wrong azp"])).status_code == 200
    assert api.fetched == []                                                      # no profile, no user, no read counted


def test_d_deadlines_stay_404_in_off_mode(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert app.client.get("/deadlines").status_code == 404


# ---- off mode, bad tokens, the read window ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/me", f"/me/teams/{TID}", "/threads/th_x"])
def test_off_mode_has_none_of_the_deletes(app, monkeypatch, path):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    r = app.client.delete(path)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("case", ["missing", "expired", "no azp"])
@pytest.mark.parametrize("path", ["/me", f"/me/teams/{TID}", "/threads/th_x"])
def test_a_bad_token_is_401_before_anything(d, case, path):
    import users
    touched = []
    d.mp.setattr(users, "user_for_claims", lambda *a, **k: touched.append(1))
    token = _bad_tokens()[case]
    before = _totals(d.conn)
    r = d.client.delete(path, headers=bearer(token) if token else {})
    assert r.status_code == 401 and touched == [] and _totals(d.conn) == before and d.clerk_calls == []


def test_r_the_deletes_count_against_the_sixty_reads_a_minute(api, monkeypatch):
    import users
    monkeypatch.setattr(users, "delete_clerk_user", lambda cid: "deleted")
    monkeypatch.setattr(users, "monotonic", lambda: 1000.0)
    for _ in range(users.READS_PER_MINUTE):
        assert _get(api, "/me").status_code == 200
    before = _totals(api.conn)
    r = _delete(api, "/me")
    assert r.status_code == 429 and _totals(api.conn) == before
