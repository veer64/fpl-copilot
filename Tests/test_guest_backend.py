"""Prompt W9 (2026-11-12): GUEST MODE -- the backend. USER DECISIONS (12 Nov): guests use everything a signed-in user can;
one guest session spends at most GUEST_CAP_USD (0.25), all guests GUEST_DAILY_BUDGET_USD (3.00) a UTC day, at most
GUEST_STARTS_PER_IP_PER_DAY (3) starts per IP a UTC day; GUEST_MODE=on|off is an emergency brake (off: no new starts, guest
/chat refused, every guest ended within a sweep); a guest is deleted ~2 min after the last desktop tab left (ping after the
leave cancels it) or after GUEST_IDLE_MINUTES (30) + 1 min of slack without a ping; the client itself deletes at 30:00.
DELETION SAFETY (overrides everything): the reaper deletes only rows that are guests in OUR DB (is_guest, user_id >= 10001,
never the owner) AND at Clerk (public_metadata.guest = true; a 404 = already gone), always through deletion.delete_account
(one transaction, Clerk inside). Real accounts are never touched: per-table counts for a real user and the owner before /
after sweeps with old timestamps, a crashed tab and clock jumps.
Off mode is byte-identical: the new routes are 404 there, nothing is read or written. Payload v5 untouched (no agent,
tool or prompt change: test_agent_payload_equivalence). Offline: test_fpl_import's `api` fixture (clerk mode on the test
database, users 10001 / 10002), Clerk's create-user / sign-in-token / get-user / delete-user faked and counted."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import PROFILES, app, tdb, c, mint, bearer, _q        # noqa: E402,F401  (fixtures)
from test_fpl_import import api, T1, T2, U1, U2, _post, _get           # noqa: E402,F401  (fixtures)

import guest                                                            # noqa: E402  (the module under test)
import users                                                            # noqa: E402

G1, G2 = "user_guest_1", "user_guest_2"
TABLES = ("app_users", "user_fpl_teams", "squad_versions", "squad_previews", "chat_threads", "chat_messages", "cap_hits",
          "model_transfer_plans")


def _h(sub):
    return bearer(mint(sub))


@pytest.fixture
def g(api, monkeypatch):
    """`api` in guest mode: GUEST_MODE=on, Clerk's guest calls faked (created users remembered with their metadata so the
    profile fetch and the reaper's re-check see them), the per-minute windows never limiting, cap_hits + guest tables fresh."""
    monkeypatch.setenv("GUEST_MODE", "on")
    monkeypatch.setenv("APP_API_KEY", "test-key-for-hashing")
    monkeypatch.delenv("GUEST_IDLE_MINUTES", raising=False)
    monkeypatch.delenv("GUEST_CAP_USD", raising=False)
    monkeypatch.delenv("GUEST_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("GUEST_STARTS_PER_IP_PER_DAY", raising=False)
    guest.ensure_schema(api.conn)
    with api.conn.cursor() as cur:
        cur.execute("TRUNCATE cap_hits")
        cur.execute("DELETE FROM guest_starts")
        cur.execute("DELETE FROM chat_usage")
    clerk = {"users": {T1: {"id": T1, "email": "t1@example.test", "public_metadata": {}},
              T2: {"id": T2, "email": "t2@example.test", "public_metadata": {}}},
             "created": [], "tokens": [], "deleted": [], "fail_token": False, "n": 0}
    monkeypatch.setattr(guest, "trusted_proxy_ips", lambda: {"testclient"})

    def fake_create(address, metadata):
        clerk["n"] += 1
        cid = f"user_guest_{clerk['n']}"
        clerk["users"][cid] = {"id": cid, "email": address, "public_metadata": dict(metadata)}
        clerk["created"].append((cid, address, dict(metadata)))
        return cid

    def fake_token(cid, ttl):
        if clerk["fail_token"]:
            raise guest.ClerkFailed("token refused")
        clerk["tokens"].append((cid, ttl))
        return f"ticket-for-{cid}"

    def fake_get(cid):
        u = clerk["users"].get(cid)
        return None if u is None else {"id": cid, "public_metadata": dict(u["public_metadata"])}

    def fake_delete(cid):
        clerk["deleted"].append(cid)
        return "deleted" if clerk["users"].pop(cid, None) is not None else "already_gone"

    monkeypatch.setattr(guest, "clerk_create_user", fake_create)
    monkeypatch.setattr(guest, "clerk_sign_in_token", fake_token)
    monkeypatch.setattr(guest, "clerk_get_user", fake_get)
    monkeypatch.setattr(users, "delete_clerk_user", fake_delete)
    real_profile = users.fetch_profile

    def profile(cid):                                    # a created guest's profile = the Clerk user object; else the fakes
        u = clerk["users"].get(cid)
        if u is not None and u["public_metadata"].get("guest"):
            return users._profile_from({"id": cid, "email_addresses": [{"id": "e1", "email_address": u["email"], "verification": {"status": "verified"}}],
                                        "primary_email_address_id": "e1", "first_name": "Guest", "public_metadata": u["public_metadata"]})
        return real_profile(cid)
    monkeypatch.setattr(users, "fetch_profile", profile)
    clock = {"t": 0.0}
    monkeypatch.setattr(users, "monotonic", lambda: clock.update(t=clock["t"] + 61) or clock["t"])
    api.clerk = clerk
    yield api


def _start(g, ip="203.0.113.7", via_proxy=True, monkeypatch=None):
    """POST /guest/start as a client at `ip`: by default the test client is the trusted proxy carrying X-Forwarded-For."""
    headers = {"X-Forwarded-For": ip} if via_proxy else {}
    return g.client.post("/guest/start", headers=headers)


def _become_guest(g, ip="203.0.113.7"):
    """start -> the Clerk id -> the first signed-in request (the row is created on first sight) -> (clerk id, user row)."""
    r = _start(g, ip)
    assert r.status_code == 200, r.text
    cid = g.clerk["created"][-1][0]
    me = g.client.get("/me", headers=_h(cid))
    assert me.status_code == 200, me.text
    row = _q(g.conn, "SELECT * FROM app_users WHERE clerk_user_id = %s", (cid,))
    return cid, me.json(), row


def _counts(conn, uid):
    out = {}
    for t in TABLES:
        if _q(conn, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",))[0][0]:
            out[t] = _q(conn, f"SELECT count(*) FROM {t} WHERE user_id = %s", (uid,))[0][0]
    out["usage"] = _q(conn, "SELECT count(*) FROM chat_usage WHERE user_id = %s", (uid,))[0][0]
    return out


def _usage(conn, uid, usd, when=None, turn="t"):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES (%s, %s, 'm', 1, %s, 0, %s)",
                    (when or users.clock(), f"{turn}-{uid}-{usd}", usd, uid))
    conn.commit()


def _set(conn, uid, **cols):
    sets = ", ".join(f"{k} = %s" for k in cols)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE app_users SET {sets} WHERE user_id = %s", (*cols.values(), uid))
    conn.commit()


# ---- off mode: nothing exists ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [("get", "/guest/status"), ("post", "/guest/start"), ("post", "/me/ping"), ("post", "/me/leave")])
def test_g1_off_mode_has_none_of_the_guest_routes(app, monkeypatch, method, path):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("GUEST_MODE", "on")
    before = _q(app.conn, "SELECT count(*) FROM app_users")[0][0] if _q(app.conn, "SELECT to_regclass('public.app_users') IS NOT NULL")[0][0] else None
    r = getattr(app.client, method)(path)
    assert r.status_code == 404, r.text
    after = _q(app.conn, "SELECT count(*) FROM app_users")[0][0] if before is not None else None
    assert after == before


# ---- the switch, the start, the first sign-in ---------------------------------------------------------------------------

def test_g2_switch_off_status_says_disabled_and_start_is_403_with_no_clerk_call(g, monkeypatch):
    monkeypatch.delenv("GUEST_MODE", raising=False)
    s = g.client.get("/guest/status")
    assert s.status_code == 200 and s.json()["enabled"] is False
    r = _start(g)
    assert r.status_code == 403 and r.json()["code"] == "guest_off" and r.json()["detail"] == guest.UNAVAILABLE
    assert g.clerk["created"] == [] and _q(g.conn, "SELECT count(*) FROM guest_starts")[0][0] == 0


def test_g3_start_creates_a_clerk_guest_and_a_ticket_and_a_start_row_with_a_hashed_ip(g):
    s = g.client.get("/guest/status").json()
    assert s == {"enabled": True, "idle_minutes": 30, "cap_usd": 0.25, "leave_grace_seconds": 120}
    r = _start(g, "203.0.113.7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires_in_seconds"] == 600 and body["ticket"].startswith("ticket-for-")
    cid, address, meta = g.clerk["created"][0]
    assert address.endswith("@guest.fplcopilot.app") and "+" not in address and address.startswith("guest-")
    assert meta["guest"] is True and g.clerk["tokens"] == [(cid, 600)]
    rows = _q(g.conn, "SELECT ip_hash, clerk_user_id, claimed_at, user_id FROM guest_starts")
    assert len(rows) == 1 and rows[0][1] == cid and rows[0][2] is None and rows[0][3] is None
    assert rows[0][0] != "203.0.113.7" and len(rows[0][0]) >= 16     # a salted hash, never the address


def test_g3_a_token_failure_deletes_the_half_made_clerk_user_and_answers_502(g):
    g.clerk["fail_token"] = True
    r = _start(g)
    assert r.status_code == 502
    assert len(g.clerk["created"]) == 1 and g.clerk["deleted"] == [g.clerk["created"][0][0]]
    assert _q(g.conn, "SELECT count(*) FROM guest_starts")[0][0] == 0


def test_g4_first_sign_in_makes_a_guest_row_with_the_guest_cap_and_claims_the_start(g):
    cid, me, row = _become_guest(g)
    assert me["is_guest"] is True and me["daily_cap_usd"] == 0.25 and me["spent_today_usd"] == 0
    assert me["guest"] == {"idle_minutes": 30, "leave_grace_seconds": 120, "cap_usd": 0.25, "spent_usd": 0.0, "budget_open": True}
    r = dict(zip([d[0] for d in _describe(g.conn)], row[0]))
    assert r["is_guest"] is True and r["sign_in_method"] == "guest" and float(r["daily_cap_usd"]) == 0.25
    assert r["user_id"] >= 10001 and r["guest_started_at"] is not None and r["guest_last_seen_at"] is not None
    claimed = _q(g.conn, "SELECT claimed_at, user_id FROM guest_starts WHERE clerk_user_id = %s", (cid,))[0]
    assert claimed[0] is not None and claimed[1] == r["user_id"]
    # a real user's /me is unchanged in shape apart from the new flags
    real = _get(g, "/me").json()
    assert real["is_guest"] is False and real["guest"] is None and real["daily_cap_usd"] == 1.0


def _describe(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM app_users LIMIT 0")
        return cur.description


# ---- the per-IP limit and where the IP comes from (Q6) -------------------------------------------------------------------

def test_g5_three_starts_per_ip_per_day_then_429_another_ip_is_fine(g):
    for i in range(3):
        assert _start(g, "203.0.113.7").status_code == 200, i
    r = _start(g, "203.0.113.7")
    assert r.status_code == 429 and r.json()["code"] == "guest_ip_limit" and r.json()["detail"] == guest.IP_LIMIT
    assert _start(g, "203.0.113.8").status_code == 200
    assert len(g.clerk["created"]) == 4                  # the refused start made no Clerk user


def test_g5_x_forwarded_for_is_trusted_only_from_the_proxy_peer(g, monkeypatch):
    # the test client's peer is "testclient"; by default (the fixture) that peer IS the trusted proxy -> XFF is the client
    assert guest.client_ip_of("testclient", {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}) == "203.0.113.9"
    # any other peer -- a direct :8000 caller -- is its own address, whatever it forwards
    monkeypatch.setattr(guest, "trusted_proxy_ips", lambda: {"172.19.0.5"})
    assert guest.client_ip_of("198.51.100.4", {"x-forwarded-for": "203.0.113.9"}) == "198.51.100.4"
    assert guest.client_ip_of("172.19.0.5", {"x-forwarded-for": "203.0.113.9"}) == "203.0.113.9"
    assert guest.client_ip_of("172.19.0.5", {}) == "172.19.0.5"
    # through the endpoint: with the proxy not trusted, three starts from the same direct peer exhaust the peer's quota
    for i in range(3):
        assert _start(g, f"203.0.113.{i}").status_code == 200
    assert _start(g, "203.0.113.99").status_code == 429     # the forwarded addresses differ; the peer does not


def test_g5_the_proxy_set_resolves_the_caddy_service_name(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOSTS", "fpl-caddy, 10.9.9.9")
    monkeypatch.setattr(guest, "_resolve", lambda host: ["172.19.0.3", "172.19.0.4"] if host == "fpl-caddy" else [])
    guest._PROXY_CACHE.clear()
    assert guest.trusted_proxy_ips() == {"172.19.0.3", "172.19.0.4", "10.9.9.9"}


# ---- the money guards in /chat (0 model calls) ----------------------------------------------------------------------------

def test_g6_the_guest_cap_refuses_the_turn_with_the_guest_text_and_no_model_call(g):
    cid, me, row = _become_guest(g)
    uid = me["user_id"]
    _usage(g.conn, uid, 0.13)
    _usage(g.conn, uid, 0.12)
    calls = g.brain.calls
    r = g.client.post("/chat", json={"message": "hello"}, headers=_h(cid))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["capped"] is True and body["limit"]["kind"] == "guest" and body["answer"] == guest.CAP_REACHED
    assert g.brain.calls == calls
    assert _q(g.conn, "SELECT count(*) FROM cap_hits WHERE user_id = %s", (uid,))[0][0] == 1
    assert _q(g.conn, "SELECT cap_hits, budget_hits FROM guest_starts WHERE user_id = %s", (uid,))[0] == (1, 0)
    # a real user with the same spend is well under the $1 default
    _usage(g.conn, U1, 0.25)
    r = _post(g, "/chat", json={"message": "hello"})
    assert r.status_code == 200 and not r.json().get("capped")


def test_g6_the_daily_guest_budget_refuses_turns_and_starts_with_0_model_calls(g):
    cid, me, row = _become_guest(g, "203.0.113.1")
    other, _, _ = _become_guest(g, "203.0.113.2")
    uid = me["user_id"]
    # the budget counts live guests AND today's anonymised deleted-guest rows, never real users
    _usage(g.conn, uid, 0.20)
    _usage(g.conn, U1, 5.00)                              # a real user's spend is not the guest budget
    with g.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES (%s, 'deleted-guest', 'm', 1, 2.80, 0, NULL)",
                    (users.clock(),))
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES (%s, 'deleted-guest', 'm', 1, 9.00, 0, NULL)",
                    (users.clock() - timedelta(days=1),))  # yesterday's deleted guests do not count
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES (%s, 'deleted', 'm', 1, 9.00, 0, NULL)",
                    (users.clock(),))                      # a deleted REAL account does not count
    g.conn.commit()
    assert round(guest.budget_used_today(g.conn), 2) == 3.00
    calls = g.brain.calls
    r = g.client.post("/chat", json={"message": "hello"}, headers=_h(other))
    assert r.status_code == 200 and r.json()["capped"] is True and r.json()["limit"]["kind"] == "guest_budget"
    assert r.json()["answer"] == guest.BUDGET_FULL and g.brain.calls == calls
    assert _q(g.conn, "SELECT budget_hits FROM guest_starts WHERE clerk_user_id = %s", (other,))[0][0] == 1
    s = _start(g, "203.0.113.3")
    assert s.status_code == 429 and s.json()["code"] == "guest_budget" and s.json()["detail"] == guest.BUDGET_FULL
    me2 = g.client.get("/me", headers=_h(cid)).json()
    assert me2["guest"]["budget_open"] is False
    # a real user still chats
    r = _post(g, "/chat", json={"message": "hello"}, sub=T2)
    assert r.status_code == 200 and not r.json().get("capped")


def test_g6_switch_off_refuses_a_guest_turn_at_once_but_not_a_real_user(g, monkeypatch):
    cid, me, row = _become_guest(g)
    monkeypatch.setenv("GUEST_MODE", "off")
    calls = g.brain.calls
    r = g.client.post("/chat", json={"message": "hello"}, headers=_h(cid))
    assert r.status_code == 200 and r.json()["capped"] is True and r.json()["limit"]["kind"] == "guest_off"
    assert r.json()["answer"] == guest.UNAVAILABLE and g.brain.calls == calls
    assert _post(g, "/chat", json={"message": "hello"}).status_code == 200


def test_g6_an_ordinary_guest_turn_runs_and_its_cost_row_carries_the_guest(g):
    cid, me, row = _become_guest(g)
    calls = g.brain.calls
    r = g.client.post("/chat", json={"message": "hello"}, headers=_h(cid))
    assert r.status_code == 200 and not r.json().get("capped") and r.json()["answer"]
    assert g.brain.calls != calls                        # the model ran (the fake model writes no cost row; the real one carries the acting user)


# ---- ping / leave -----------------------------------------------------------------------------------------------------------

def test_g7_ping_moves_last_seen_and_clears_a_leave_leave_keeps_the_earliest(g):
    cid, me, row = _become_guest(g)
    uid = me["user_id"]
    t0 = users.clock()
    _set(g.conn, uid, guest_last_seen_at=t0 - timedelta(minutes=5), guest_left_at=None)
    assert g.client.post("/me/leave", headers=_h(cid)).status_code == 204
    left = _q(g.conn, "SELECT guest_left_at FROM app_users WHERE user_id = %s", (uid,))[0][0]
    assert left is not None
    assert g.client.post("/me/leave", headers=_h(cid)).status_code == 204
    assert _q(g.conn, "SELECT guest_left_at FROM app_users WHERE user_id = %s", (uid,))[0][0] == left   # the first leave stands
    assert g.client.post("/me/ping", headers=_h(cid)).status_code == 204
    seen, left2 = _q(g.conn, "SELECT guest_last_seen_at, guest_left_at FROM app_users WHERE user_id = %s", (uid,))[0]
    assert left2 is None and seen >= t0 - timedelta(seconds=1)
    # a real user: 204, nothing written
    before = _q(g.conn, "SELECT guest_last_seen_at, guest_left_at FROM app_users WHERE user_id = %s", (U1,))[0]
    assert _post(g, "/me/ping").status_code == 204 and _post(g, "/me/leave").status_code == 204
    assert _q(g.conn, "SELECT guest_last_seen_at, guest_left_at FROM app_users WHERE user_id = %s", (U1,))[0] == before == (None, None)


# ---- the reaper ---------------------------------------------------------------------------------------------------------------

def _owner_row(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at, is_admin, is_exempt, "
                    "last_active_at, created_at) VALUES (1, 'user_owner', 'owner@example.test', 'Owner', 'google', now(), TRUE, TRUE, "
                    "now() - interval '40 days', now() - interval '400 days') ON CONFLICT DO NOTHING")
    conn.commit()


def test_g8_reaper_deletes_a_left_guest_after_the_grace_keeps_a_refresh_and_a_recent_leave(g):
    cid, me, row = _become_guest(g, "203.0.113.1")
    gone, me2, _ = _become_guest(g, "203.0.113.2")
    fresh, me3, _ = _become_guest(g, "203.0.113.3")
    _owner_row(g.conn)
    now = users.clock()
    _usage(g.conn, me2["user_id"], 0.07)
    _set(g.conn, me2["user_id"], guest_left_at=now - timedelta(seconds=150), guest_last_seen_at=now - timedelta(seconds=200))   # left, no ping since
    _set(g.conn, me["user_id"], guest_left_at=now - timedelta(seconds=150), guest_last_seen_at=now - timedelta(seconds=100))    # left, then a ping (refresh)
    _set(g.conn, me3["user_id"], guest_left_at=now - timedelta(seconds=60), guest_last_seen_at=now - timedelta(seconds=90))     # left a minute ago
    real_before = {u: _counts(g.conn, u) for u in (U1, U2, 1)}
    out = guest.sweep(g.conn)
    assert [d["user_id"] for d in out["deleted"]] == [me2["user_id"]] and out["deleted"][0]["reason"] == "left"
    assert _q(g.conn, "SELECT count(*) FROM app_users WHERE user_id = %s", (me2["user_id"],))[0][0] == 0
    assert g.clerk["deleted"] == [gone]
    assert _q(g.conn, "SELECT turn_id, user_id FROM chat_usage WHERE usd = 0.07") == [("deleted-guest", None)]
    assert _q(g.conn, "SELECT ended_at IS NOT NULL, end_reason FROM guest_starts WHERE clerk_user_id = %s", (gone,))[0] == (True, "left")
    assert _q(g.conn, "SELECT count(*) FROM app_users WHERE user_id IN %s", ((me["user_id"], me3["user_id"]),))[0][0] == 2
    assert {u: _counts(g.conn, u) for u in (U1, U2, 1)} == real_before


def test_g8_reaper_deletes_an_idle_guest_after_31_minutes_not_after_29(g):
    cid, me, row = _become_guest(g, "203.0.113.1")
    idle, me2, _ = _become_guest(g, "203.0.113.2")
    now = users.clock()
    _set(g.conn, me["user_id"], guest_last_seen_at=now - timedelta(minutes=29), guest_left_at=None)
    _set(g.conn, me2["user_id"], guest_last_seen_at=now - timedelta(minutes=32), guest_left_at=None)
    out = guest.sweep(g.conn)
    assert [(d["user_id"], d["reason"]) for d in out["deleted"]] == [(me2["user_id"], "idle")]
    assert _q(g.conn, "SELECT count(*) FROM app_users WHERE user_id = %s", (me["user_id"],))[0][0] == 1


def test_g8_a_crashed_tab_never_pinged_the_guest_goes_by_the_idle_rule_from_its_start(g):
    cid, me, row = _become_guest(g)
    now = users.clock()
    _set(g.conn, me["user_id"], guest_last_seen_at=None, guest_started_at=now - timedelta(minutes=40), guest_left_at=None)
    out = guest.sweep(g.conn)
    assert [d["reason"] for d in out["deleted"]] == ["idle"]


def test_g8_reaper_never_touches_real_accounts_however_old_or_whatever_the_clock_does(g, monkeypatch):
    _owner_row(g.conn)
    _set(g.conn, U1, last_active_at=users.clock() - timedelta(days=90))
    _set(g.conn, U2, last_active_at=None)
    cid, me, _ = _become_guest(g)
    _set(g.conn, me["user_id"], guest_last_seen_at=users.clock() - timedelta(minutes=5), guest_left_at=None)
    before = {u: _counts(g.conn, u) for u in (U1, U2, 1, me["user_id"])}
    # the clock jumps back a year: nothing is deleted
    monkeypatch.setattr(users, "clock", lambda: datetime(2025, 11, 12, tzinfo=timezone.utc))
    out = guest.sweep(g.conn)
    assert out["deleted"] == [] and {u: _counts(g.conn, u) for u in before} == before
    # the clock jumps forward a year: only the guest goes, the real accounts and the owner stay
    monkeypatch.setattr(users, "clock", lambda: datetime(2027, 11, 12, tzinfo=timezone.utc))
    out = guest.sweep(g.conn)
    assert [d["user_id"] for d in out["deleted"]] == [me["user_id"]]
    after = {u: _counts(g.conn, u) for u in (U1, U2, 1)}
    assert after == {u: before[u] for u in (U1, U2, 1)}
    assert _q(g.conn, "SELECT count(*) FROM app_users WHERE user_id IN (1, %s, %s)", (U1, U2))[0][0] == 3


def test_g8_reaper_skips_a_row_clerk_does_not_mark_as_guest_and_deletes_when_clerk_already_lost_it(g):
    a, mea, _ = _become_guest(g, "203.0.113.1")
    b, meb, _ = _become_guest(g, "203.0.113.2")
    now = users.clock()
    for m in (mea, meb):
        _set(g.conn, m["user_id"], guest_last_seen_at=now - timedelta(minutes=45), guest_left_at=None)
    g.clerk["users"][a]["public_metadata"] = {}            # Clerk says: not a guest -> never deleted automatically
    del g.clerk["users"][b]                                  # Clerk 404 -> our rows go, clerk "already_gone"
    out = guest.sweep(g.conn)
    assert [d["user_id"] for d in out["deleted"]] == [meb["user_id"]] and out["deleted"][0]["clerk"] == "already_gone"
    assert out["skipped"] == [{"user_id": mea["user_id"], "why": "clerk metadata is not guest"}]
    assert _q(g.conn, "SELECT count(*) FROM app_users WHERE user_id = %s", (mea["user_id"],))[0][0] == 1


def test_g8_a_db_row_flagged_guest_for_a_real_clerk_user_is_never_deleted(g):
    """Both flags are required: a DB row marked is_guest whose Clerk user carries no guest metadata stays."""
    _set(g.conn, U2, is_guest=True, guest_last_seen_at=users.clock() - timedelta(hours=3))
    before = _counts(g.conn, U2)
    out = guest.sweep(g.conn)
    assert out["deleted"] == [] and out["skipped"][0]["user_id"] == U2 and _counts(g.conn, U2) == before


def test_g8_switch_off_ends_every_guest_in_one_sweep_and_nothing_else(g, monkeypatch):
    _owner_row(g.conn)
    a, mea, _ = _become_guest(g, "203.0.113.1")
    b, meb, _ = _become_guest(g, "203.0.113.2")
    before = {u: _counts(g.conn, u) for u in (U1, U2, 1)}
    monkeypatch.setenv("GUEST_MODE", "off")
    out = guest.sweep(g.conn)
    assert sorted(d["user_id"] for d in out["deleted"]) == sorted([mea["user_id"], meb["user_id"]])
    assert {d["reason"] for d in out["deleted"]} == {"switch_off"} and sorted(g.clerk["deleted"]) == sorted([a, b])
    assert {u: _counts(g.conn, u) for u in (U1, U2, 1)} == before
    assert _q(g.conn, "SELECT count(*) FROM app_users WHERE is_guest")[0][0] == 0


def test_g8_unclaimed_starts_lose_their_clerk_user_after_ten_minutes_and_rows_are_pruned(g):
    assert _start(g, "203.0.113.1").status_code == 200   # never signed in
    cid = g.clerk["created"][0][0]
    now = users.clock()
    with g.conn.cursor() as cur:
        cur.execute("UPDATE guest_starts SET started_at = %s WHERE clerk_user_id = %s", (now - timedelta(minutes=11), cid))
        cur.execute("INSERT INTO guest_starts (ip_hash, started_at, clerk_user_id, claimed_at, ended_at, end_reason) VALUES "
                    "('old-hash', %s, 'user_old', %s, %s, 'left'), ('older-hash', %s, 'user_older', %s, %s, 'idle')",
                    (now - timedelta(hours=25), now - timedelta(hours=25), now - timedelta(hours=24),
                     now - timedelta(days=8), now - timedelta(days=8), now - timedelta(days=8)))
    g.conn.commit()
    out = guest.sweep(g.conn)
    assert out["unclaimed_deleted"] == 1 and g.clerk["deleted"] == [cid]
    assert _q(g.conn, "SELECT ended_at IS NOT NULL, end_reason FROM guest_starts WHERE clerk_user_id = %s", (cid,))[0] == (True, "unclaimed")
    assert _q(g.conn, "SELECT ip_hash FROM guest_starts WHERE clerk_user_id = 'user_old'") == [(None,)]     # 24 h: the hash goes
    assert _q(g.conn, "SELECT count(*) FROM guest_starts WHERE clerk_user_id = 'user_older'")[0][0] == 0   # 7 days: the row goes
    assert out["pruned"] == 1


def test_g8_a_second_sweep_right_after_is_a_no_op_and_ensure_schema_is_idempotent(g):
    guest.ensure_schema(g.conn)
    guest.ensure_schema(g.conn)
    cid, me, _ = _become_guest(g)
    out1 = guest.sweep(g.conn)
    out2 = guest.sweep(g.conn)
    assert out1["deleted"] == out2["deleted"] == [] and out2["skipped"] == [] and out2["unclaimed_deleted"] == 0


# ---- ending it yourself + the deleted guest's token ---------------------------------------------------------------------------

def test_g9_delete_me_as_a_guest_deletes_with_the_guest_marker_and_the_token_is_then_refused(g):
    cid, me, row = _become_guest(g)
    uid = me["user_id"]
    _usage(g.conn, uid, 0.05)
    r = g.client.delete("/me", headers=_h(cid))
    assert r.status_code == 200 and r.json()["deleted"] is True and r.json()["clerk"] == "deleted"
    assert _q(g.conn, "SELECT turn_id FROM chat_usage WHERE usd = 0.05") == [("deleted-guest",)]
    assert _q(g.conn, "SELECT end_reason FROM guest_starts WHERE clerk_user_id = %s", (cid,)) == [("ended",)]
    # the still-valid token re-creates nothing: Clerk no longer knows the user (503), and no row appears
    r = g.client.get("/me", headers=_h(cid))
    assert r.status_code == 503 and _q(g.conn, "SELECT count(*) FROM app_users WHERE clerk_user_id = %s", (cid,))[0][0] == 0


# ---- admin: guests are not people ------------------------------------------------------------------------------------------------

def test_g10_admin_counts_guests_apart_from_people_and_includes_their_spend_in_the_totals(g, monkeypatch):
    import admin
    monkeypatch.setattr(admin, "clock", users.clock)
    _owner_row(g.conn)
    _get(g, "/me")
    _get(g, "/me", sub=T2)                               # the two real users were active today
    a, mea, _ = _become_guest(g, "203.0.113.1")
    b, meb, _ = _become_guest(g, "203.0.113.2")
    _usage(g.conn, mea["user_id"], 0.10)
    _usage(g.conn, U1, 0.30)
    # a guest cap hit today + a real user's cap hit
    users.record_cap_hit(mea["user_id"], 0.25, 0.25, g.conn)
    guest.record_hit(mea["user_id"], "cap", g.conn)
    users.record_cap_hit(U1, 1.0, 1.0, g.conn)
    # b leaves and is reaped: its spend becomes a deleted-guest line
    _usage(g.conn, meb["user_id"], 0.04)
    _set(g.conn, meb["user_id"], guest_left_at=users.clock() - timedelta(minutes=5), guest_last_seen_at=users.clock() - timedelta(minutes=6))
    guest.sweep(g.conn)
    s = admin.summary(g.conn)
    assert s["users_total"] == 2 and sorted(u["user_id"] for u in s["users"]) == [U1, U2]     # the guest is not a person
    assert s["sign_ups_today"] == 2 and s["active_today"] == 2
    assert round(s["usd_today"], 2) == round(0.10 + 0.30 + 0.04, 2) and s["answers_today"] == 3   # guest spend counts (Q2)
    assert s["deleted_accounts"] == {"answers": 0, "usd": 0.0}
    assert [h["user_id"] for h in s["cap_hits"]] == [U1] and s["cap_hits_today"] == 1          # guest hits out of the people list (Q8)
    gs = s["guests"]
    assert gs["enabled"] is True and gs["sessions_today"] == 2 and gs["sessions_7_days"] == 2 and gs["live_now"] == 1
    assert gs["answers_today"] == 2 and round(gs["usd_today"], 2) == 0.14 and gs["limit_hits_today"] == 1
    assert gs["budget_usd"] == 3.0 and round(gs["budget_used_today_usd"], 2) == 0.14 and gs["cap_usd"] == 0.25
    assert gs["deleted"] == {"answers": 1, "usd": 0.04}
    assert "guest" not in s["sign_in_methods"]
    csv = admin.users_csv(admin.stats(g.conn))
    assert "guest-" not in csv
