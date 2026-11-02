"""Prompt P7 Part 1 (2026-11-01): Clerk session tokens, app_users, the admin link -- AUTH_MODE=off|clerk (default off).

USER DECISIONS (1 Nov): "Open sign-up: anyone can sign in." "Google and email sign-in only; I don't want to pay."

off   -> exactly the single-user behaviour of 13ebb8e: the turn's user is config_roles.DEFAULT_USER_ID(), an Authorization
         header is ignored, /admin does not exist (404), nothing reads or writes app_users.
clerk -> /chat, /reset and /admin* need `Authorization: Bearer <Clerk session token>`; a missing, malformed, expired,
         not-yet-valid, wrongly signed, wrong-issuer, wrong-azp or (Prompt F1a) azp-less token is 401 before any model
         call or any DB access.
         The turn's user is the token's user (app_users row, created on first sight from Clerk's Backend API profile,
         refreshed at most daily); new users get integer ids from 10001 up; the first sign-in whose VERIFIED email is
         ADMIN_EMAIL is linked to the existing user 1 (is_admin, is_exempt); a user id from the body or the model is
         never used (a tool's user_id argument is replaced by the token's user).

Offline: tokens minted here with a local RSA key (CLERK_JWT_KEY = its public PEM: Clerk's networkless option), profiles
from a fake Backend API, the brain as the model (thread_fakes), the app on test_threads' test database (tdb)."""
import json
import os
import sys
import time
import types
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_threads import app, tdb, _history, _norm, _counts, _tickets, _versions   # noqa: E402,F401  (fixtures)
import thread_fakes as tf                                                             # noqa: E402

ISSUER = "https://test-instance-42.clerk.accounts.dev"
ORIGIN = "http://localhost:3000"
ADMIN = "owner@example.test"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
OTHER_PRIVATE = _OTHER.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
PUBLIC = _KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def mint(sub, key=PRIVATE, alg="RS256", kid="ins_test", **claims):
    now = int(time.time())
    body = {"sub": sub, "sid": f"sess_{sub}", "iss": ISSUER, "iat": now, "nbf": now - 2, "exp": now + 60, "v": 2,
            "azp": ORIGIN}                    # Prompt F1a: a browser session token names its origin; azp is required
    body.update(claims)
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode(body, key, algorithm=alg, headers={"kid": kid})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


PROFILES = {
    "user_alice": {"email": "alice@example.test", "email_verified": True, "name": "Alice A", "sign_in_method": "google"},
    "user_bob": {"email": "bob@example.test", "email_verified": True, "name": "Bob B", "sign_in_method": "email"},
    "user_admin": {"email": ADMIN, "email_verified": True, "name": "The Owner", "sign_in_method": "google"},
    "user_fake_admin": {"email": ADMIN, "email_verified": False, "name": "Not Owner", "sign_in_method": "email"},
    "user_second_admin": {"email": ADMIN, "email_verified": True, "name": "Owner Again", "sign_in_method": "email"},
    "user_fresh": {"email": "fresh@example.test", "email_verified": True, "name": "Fresh F", "sign_in_method": "email"},
}


@pytest.fixture
def c(app, monkeypatch):
    """The app in clerk mode on the test database: users' schema present and empty, 9001 / 9002 linked to two Clerk users
    (existing integer ids kept), the profile fetch faked and counted, the limits reset."""
    import auth
    import db_write
    import users
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_JWT_KEY", PUBLIC)
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", ORIGIN)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN)
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    auth._reset()
    users._reset()
    db_write.ensure_schema(app.conn)
    users.ensure_schema(app.conn)
    with app.conn.cursor() as cur:
        cur.execute("TRUNCATE app_users")
        cur.execute("DELETE FROM chat_usage")
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) VALUES "
                    "(9001, 'user_a9001', 'a9001@example.test', 'Nine A', 'email', now()), "
                    "(9002, 'user_b9002', 'b9002@example.test', 'Nine B', 'email', now())")
    fetched = []

    def fake_profile(clerk_user_id):
        fetched.append(clerk_user_id)
        if clerk_user_id not in PROFILES:
            raise users.ProfileUnavailable(f"no such user {clerk_user_id}")
        return dict(PROFILES[clerk_user_id])
    monkeypatch.setattr(users, "fetch_profile", fake_profile)
    app.fetched = fetched
    app.users = users
    app.auth = auth
    yield app
    auth._reset()
    users._reset()


def _q(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _all_counts(conn):
    out = _counts(conn)
    for t in ("app_users", "chat_usage"):
        out[t] = _q(conn, f"SELECT count(*) FROM {t}")[0][0]
    return out


# ---- A1: the default mode is off, and off is today ---------------------------------------------------------------------

def test_a1_the_default_mode_is_off(monkeypatch):
    import auth
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert auth.mode() == "off"
    for v in ("", "OFF", "nonsense", "jwt"):
        monkeypatch.setenv("AUTH_MODE", v)
        assert auth.mode() == "off"
    monkeypatch.setenv("AUTH_MODE", "clerk")
    assert auth.mode() == "clerk"


def test_a1_off_mode_ignores_a_bearer_header_and_never_touches_app_users(app, monkeypatch):
    import users
    monkeypatch.delenv("AUTH_MODE", raising=False)
    touched = []
    monkeypatch.setattr(users, "user_for_claims", lambda *a, **k: touched.append(1))
    r = app.client.post("/chat", json={"message": "tool:xi"}, headers=bearer("garbage.token.here"))
    assert r.status_code == 200 and touched == []
    sent = json.loads(app.brain.log[-1]["raw"])
    seen = [b for m in sent["messages"] if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]
            if b.get("type") == "tool_result"]
    assert "'user_seen': 9001" in seen[-1]["content"]                     # FPL_USER_ID, as today
    assert app.client.get("/admin").status_code == 404 and app.client.get("/admin/users.csv").status_code == 404


def test_a1_off_mode_passes_a_model_supplied_user_id_through_as_today(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    seen = []
    monkeypatch.setitem(app.agent.available_functions, "get_my_squad", lambda user_id=None: seen.append(user_id) or {"ok": 1})

    class Asks(tf.Brain):
        def respond(self, kw, q):
            if q == "whose squad" and not tf.after_tool(kw):
                return tf.tool_use("get_my_squad", {"user_id": 9002}, "t_sq")
            return super().respond(kw, q)
    monkeypatch.setattr(app.agent, "client", Asks())
    assert app.client.post("/chat", json={"message": "whose squad"}).status_code == 200
    assert seen == [9002]


# ---- A2: a valid token -------------------------------------------------------------------------------------------------

def test_a2_a_valid_token_runs_the_turn_as_its_user(c):
    r = c.client.post("/chat", json={"message": "tool:xi"}, headers=bearer(mint("user_a9001")))
    assert r.status_code == 200, r.text
    sent = json.loads(c.brain.log[-1]["raw"])
    results = [b["content"] for m in sent["messages"] if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    assert "'user_seen': 9001" in results[-1]
    assert c.fetched == []                                                 # linked and fresh: no profile fetch


def test_a2_the_turn_user_comes_from_the_token_never_from_the_body(c, monkeypatch):
    r = c.client.post("/chat", json={"message": "tool:xi", "user_id": 9001}, headers=bearer(mint("user_b9002")))
    assert r.status_code == 200
    sent = json.loads(c.brain.log[-1]["raw"])
    results = [b["content"] for m in sent["messages"] if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    assert "'user_seen': 9002" in results[-1]


def test_a2_a_tool_user_id_from_the_model_is_replaced_by_the_token_user(c, monkeypatch):
    seen = []
    monkeypatch.setitem(c.agent.available_functions, "get_my_squad", lambda user_id=None: seen.append(user_id) or {"ok": 1})

    class Asks(tf.Brain):
        def respond(self, kw, q):
            if q == "whose squad" and not tf.after_tool(kw):
                return tf.tool_use("get_my_squad", {"user_id": 9002}, "t_sq")
            return super().respond(kw, q)
    monkeypatch.setattr(c.agent, "client", Asks())
    r = c.client.post("/chat", json={"message": "whose squad"}, headers=bearer(mint("user_a9001")))
    assert r.status_code == 200 and seen == [9001]


def test_a2_a_new_user_gets_a_new_integer_id_above_10000_and_a_profile(c):
    r = c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_alice")))
    assert r.status_code == 200, r.text
    (uid, email, name, method, admin, exempt, fetched_at, active), = _q(
        c.conn, "SELECT user_id, email, name, sign_in_method, is_admin, is_exempt, profile_fetched_at, last_active_at "
                "FROM app_users WHERE clerk_user_id = 'user_alice'")
    assert uid > 10000 and uid not in (1, 9001, 9002)
    assert (email, name, method, admin, exempt) == ("alice@example.test", "Alice A", "google", False, False)
    assert fetched_at is not None and active is not None and c.fetched == ["user_alice"]
    r2 = c.client.post("/chat", json={"message": "hello again"}, headers=bearer(mint("user_alice")))
    assert r2.status_code == 200 and c.fetched == ["user_alice"]          # refreshed at most daily
    assert _q(c.conn, "SELECT count(*) FROM app_users WHERE clerk_user_id = 'user_alice'")[0][0] == 1


def test_a2_the_profile_is_refreshed_when_a_day_old(c):
    c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_alice")))
    with c.conn.cursor() as cur:
        cur.execute("UPDATE app_users SET profile_fetched_at = now() - interval '25 hours', name = 'Old Name' "
                    "WHERE clerk_user_id = 'user_alice'")
    c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_alice")))
    assert c.fetched == ["user_alice", "user_alice"]
    assert _q(c.conn, "SELECT name FROM app_users WHERE clerk_user_id = 'user_alice'")[0][0] == "Alice A"


def test_a2_a_new_user_whose_profile_cannot_be_fetched_is_refused_and_nothing_is_written(c):
    before, calls = _all_counts(c.conn), c.brain.calls
    r = c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_unknown_to_clerk")))
    assert r.status_code == 503 and c.brain.calls == calls and _all_counts(c.conn) == before


# ---- A3: every failure is 401 before any model call or DB access -------------------------------------------------------

def _bad_tokens():
    now = int(time.time())
    return {
        "missing": None,
        "not a jwt": "not-a-jwt",
        "expired": mint("user_a9001", iat=now - 600, nbf=now - 600, exp=now - 300),
        "not yet valid": mint("user_a9001", nbf=now + 300, exp=now + 600),
        "wrong issuer": mint("user_a9001", iss="https://evil.clerk.accounts.dev"),
        "wrong azp": mint("user_a9001", azp="https://evil.example"),
        "no azp": mint("user_a9001", azp=None),            # Prompt F1a: azp is required in clerk mode
        "tampered signature": mint("user_a9001")[:-6] + ("AAAAAA" if not mint("user_a9001").endswith("AAAAAA") else "BBBBBB"),
        "another key": mint("user_a9001", key=OTHER_PRIVATE),
        "HS256 with the public key": jwt.encode({"sub": "user_a9001", "iss": ISSUER, "iat": now, "nbf": now, "exp": now + 60},
                                                 "a-shared-secret-of-sufficient-length-32b", algorithm="HS256"),
        "no sub": mint(None),
        "no exp": mint("user_a9001", exp=None),
        "pending session": mint("user_a9001", sts="pending"),
    }


@pytest.mark.parametrize("case", list(_bad_tokens()))
@pytest.mark.parametrize("route", [("post", "/chat"), ("post", "/reset")])
def test_a3_a_bad_token_is_401_with_no_model_call_and_no_row(c, monkeypatch, case, route):
    import users
    touched = []
    monkeypatch.setattr(users, "user_for_claims", lambda *a, **k: touched.append(1))
    token = _bad_tokens()[case]
    before, calls = _all_counts(c.conn), c.brain.calls
    method, path = route
    kw = {"headers": bearer(token) if token else {}}
    if method == "post":
        kw["json"] = {"message": "hello"} if path == "/chat" else {}
    r = getattr(c.client, method)(path, **kw)
    assert r.status_code == 401, (case, r.status_code, r.text)
    assert c.brain.calls == calls and touched == [] and _all_counts(c.conn) == before


def test_a3_a_good_token_with_the_right_azp_is_accepted(c):
    r = c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_a9001", azp=ORIGIN)))
    assert r.status_code == 200


def test_a3_the_jwks_is_fetched_once_and_an_unknown_kid_cannot_hammer_it(c, monkeypatch):
    auth = c.auth
    monkeypatch.delenv("CLERK_JWT_KEY")
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_not_used")
    auth._reset()
    from jwt.algorithms import RSAAlgorithm
    jwk = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    jwk.update(kid="ins_test", alg="RS256", use="sig")
    fetches = []
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: fetches.append(1) or {"keys": [jwk]})
    for _ in range(3):
        assert c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_a9001"))).status_code == 200
    assert fetches == [1]                                                 # cached
    unknown = lambda: c.client.post("/chat", json={"message": "hello"},   # noqa: E731
                                    headers=bearer(mint("user_a9001", kid="ins_unknown"))).status_code
    assert [unknown() for _ in range(5)] == [401] * 5 and fetches == [1]  # inside the cool-down: no refetch at all
    auth._STATE["fetched_at"] -= auth.JWKS_REFETCH_S + 1                  # the cool-down has passed
    assert [unknown() for _ in range(5)] == [401] * 5 and len(fetches) == 2   # one refetch, then cool-down again


# ---- A4: the admin link ------------------------------------------------------------------------------------------------

def test_a4_the_first_verified_admin_email_is_linked_to_user_1(c):
    r = c.client.post("/chat", json={"message": "tool:xi"}, headers=bearer(mint("user_admin")))
    assert r.status_code == 200
    assert _q(c.conn, "SELECT user_id, is_admin, is_exempt FROM app_users WHERE clerk_user_id = 'user_admin'") == [(1, True, True)]
    sent = json.loads(c.brain.log[-1]["raw"])
    results = [b["content"] for m in sent["messages"] if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    assert "'user_seen': 1" in results[-1]


def test_a4_an_unverified_admin_email_never_links(c):
    c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_fake_admin")))
    (uid, admin, exempt), = _q(c.conn, "SELECT user_id, is_admin, is_exempt FROM app_users WHERE clerk_user_id = 'user_fake_admin'")
    assert uid > 10000 and not admin and not exempt
    assert _q(c.conn, "SELECT count(*) FROM app_users WHERE user_id = 1")[0][0] == 0


def test_a4_only_the_first_verified_sign_in_links_a_second_is_an_ordinary_user(c):
    c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_admin")))
    c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_second_admin")))
    (uid, admin), = _q(c.conn, "SELECT user_id, is_admin FROM app_users WHERE clerk_user_id = 'user_second_admin'")
    assert uid > 10000 and not admin
    assert _q(c.conn, "SELECT clerk_user_id FROM app_users WHERE user_id = 1") == [("user_admin",)]


def test_a4_new_ids_collide_with_nothing(c):
    import users
    for sub in ("user_alice", "user_bob", "user_fresh"):
        c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint(sub)))
    ids = [r[0] for r in _q(c.conn, "SELECT user_id FROM app_users ORDER BY user_id")]
    assert len(ids) == len(set(ids)) and all(i > 10000 for i in ids if i not in (9001, 9002))
    assert users.FIRST_NEW_USER_ID == 10001 and set(users.RESERVED_USER_IDS) >= {1, 9001, 9002}


# ---- A5: two users isolated (Prompt B's T2-T4 with tokens) -------------------------------------------------------------

def _tchat(h, sub, message, thread_id=None):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    return h.client.post("/chat", json=body, headers=bearer(mint(sub)))


def test_a5_two_users_interleaved_never_see_each_others_turns(c):
    words = {"user_a9001": ["apple", "banana"], "user_b9002": ["cherry", "damson"]}
    seen = {k: set() for k in words}
    for i in range(2):
        for u in words:
            r = _tchat(c, u, f"About {words[u][i]}")
            assert r.status_code == 200, r.text
            seen[u].add(r.json()["thread_id"])
    assert all(len(v) == 1 for v in seen.values()) and seen["user_a9001"] != seen["user_b9002"]
    for u, other in (("user_a9001", "user_b9002"), ("user_b9002", "user_a9001")):
        stored = json.dumps(_norm(_history(next(iter(seen[u])))))
        assert all(w in stored for w in words[u]) and not any(w in stored for w in words[other])


def test_a5_another_users_thread_is_403_before_any_model_call_and_nothing_is_written(c):
    tid = _tchat(c, "user_a9001", "About apple").json()["thread_id"]
    before, calls, counts = _norm(_history(tid)), c.brain.calls, _all_counts(c.conn)
    r = _tchat(c, "user_b9002", "About cherry", thread_id=tid)
    assert r.status_code == 403 and r.json() == {"detail": c.main.THREAD_REFUSED}
    assert c.brain.calls == calls and _norm(_history(tid)) == before
    after = _all_counts(c.conn)
    assert {k: v for k, v in after.items() if k != "app_users"} == {k: v for k, v in counts.items() if k != "app_users"}


def test_a5_a_ticket_is_spent_only_by_its_user_in_its_thread(c):
    thread_b = _tchat(c, "user_a9001", "About apple").json()["thread_id"]
    r = c.client.post("/reset", headers=bearer(mint("user_a9001")))
    assert r.json() == {"status": "conversation reset", "preview_tickets_cancelled": 0}
    r = _tchat(c, "user_a9001", tf.PREVIEW_Q)
    thread_a = r.json()["thread_id"]
    assert thread_a != thread_b and r.json()["answer"] == "Here is the preview. Shall I apply it?"
    (ticket, uid, tthread, used, cancelled), = _tickets(c.conn)
    assert (uid, tthread, used, cancelled) == (9001, thread_a, False, False)
    n1, n2 = _versions(c.conn, 9001), _versions(c.conn, 9002)
    c.brain.forced_ticket = ticket
    assert _tchat(c, "user_b9002", tf.YES_Q).json()["answer"] == "Not written."                     # the other user
    assert _tchat(c, "user_a9001", tf.YES_Q, thread_id=thread_b).json()["answer"] == "Not written."  # another thread
    assert (_versions(c.conn, 9001), _versions(c.conn, 9002)) == (n1, n2)
    c.brain.forced_ticket = None
    assert _tchat(c, "user_a9001", tf.YES_Q, thread_id=thread_a).json()["answer"] == "Written."
    assert (_versions(c.conn, 9001), _versions(c.conn, 9002)) == (n1 + 1, n2)


def test_a5_reset_resets_only_the_token_users_default_thread(c):
    a = _tchat(c, "user_a9001", "About apple").json()["thread_id"]
    b = _tchat(c, "user_b9002", "About cherry").json()["thread_id"]
    assert c.client.post("/reset", headers=bearer(mint("user_b9002"))).status_code == 200
    assert _tchat(c, "user_a9001", "About banana").json()["thread_id"] == a
    assert _tchat(c, "user_b9002", "About damson").json()["thread_id"] != b


# ---- A6: users with no squad -------------------------------------------------------------------------------------------

def test_a6_show_me_my_squad_for_a_fresh_user_is_a_clear_no_squad_result(c, monkeypatch):
    import model_tools as mt
    monkeypatch.setitem(c.agent.available_functions, "get_my_squad", mt.get_my_squad)

    class Asks(tf.Brain):
        def respond(self, kw, q):
            if q == "Show me my squad" and not tf.after_tool(kw):
                return tf.tool_use("get_my_squad", {}, "t_sq")
            if q == "Show me my squad":
                return tf.text("You haven't saved a squad yet.")
            return super().respond(kw, q)
    monkeypatch.setattr(c.agent, "client", Asks())
    r = c.client.post("/chat", json={"message": "Show me my squad"}, headers=bearer(mint("user_fresh")))
    assert r.status_code == 200 and r.json()["answer"] == "You haven't saved a squad yet."
    sent = json.loads(c.agent.client.log[-1]["raw"])
    result = [b["content"] for m in sent["messages"] if m["role"] == "user" and isinstance(m["content"], list)
              for b in m["content"] if b.get("type") == "tool_result"][-1]
    assert "'no_squad': True" in result and "'error'" not in result and "no squad saved yet" in result


# ---- A7: the new-user sequence and db_write.sync_sequences -------------------------------------------------------------

def test_a7_sync_sequences_never_moves_the_new_user_sequence_below_its_start(c):
    """db_write.ensure_schema (every pipeline build) runs sync_sequences, which moved a never-called sequence to its table's
    max id: with only users 1 / 9001 / 9002 in app_users that was setval(9002) below MINVALUE 10001 -- an error that would
    have failed the next build once the admin was linked. A sequence starting above every id in its table is not behind."""
    import db_write
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id) VALUES (1, 'user_linked_admin')")
    fixed = db_write.sync_sequences(c.conn)
    assert not [f for f in fixed if f[0] == "app_users"]
    c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_alice")))
    (uid,), = _q(c.conn, "SELECT user_id FROM app_users WHERE clerk_user_id = 'user_alice'")
    assert uid >= 10001
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id) VALUES (%s, 'user_restored')", (uid + 5,))
    assert [f[3] for f in db_write.sync_sequences(c.conn) if f[0] == "app_users"] == [uid + 5]   # a real gap is still repaired
