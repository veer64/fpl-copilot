"""Prompt R1 (2026-11-14): the site's daily wallet -- clerk mode only (off mode unchanged).

USER DECISION (13 Nov): "$50 will be the wallet" = $50.00/day across ALL signed-in users together. Each person's $1/day cap
stays. The owner (user 1) is exempt and his spend does not count; guests keep their own $3/day wallet and do not count.

- Spent today = chat_usage cost since 00:00 UTC of signed-in non-guest users, user 1 and the reserved ids (9001 / 9002)
  excluded. SITE_DAILY_BUDGET_USD (default 50.00, read per request; unparseable or negative -> 50.00; 0 = closed to everyone
  but the owner: the kill switch).
- Checked before any model call, next to the per-user cap: at or over the budget -> HTTP 200, 0 model calls, nothing in the
  thread, one cap_hits row with kind = 'site', and "FPL Copilot has reached its daily limit for everyone today. It resets at
  00:00 UTC (in <h> h <m> m)." with limit kind "site".
- Never blocked: the owner, guests, and the $0 endpoints (/me/preview/answer Yes and No, /me/draft build and rebuild,
  /me/draft/explain): a user can always say No.
Offline: test_auth's harness (tokens, fake profiles, the brain, the threads test database); test_drafts' draft API."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _q          # noqa: E402,F401  (fixtures)
from test_fpl_import import api, T1                           # noqa: E402,F401  (fixtures)
from test_drafts import league, dapi                          # noqa: E402,F401  (fixtures)

UTC = timezone.utc
NOON = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)          # 12 h to midnight
WALLET = "FPL Copilot has reached its daily limit for everyone today. It resets at 00:00 UTC (in {h} h {m} m)."


@pytest.fixture
def w(c, monkeypatch):
    """test_auth's clerk harness with cap_hits empty, the users clock frozen at NOON and the wallet at its default."""
    with c.conn.cursor() as cur:
        cur.execute("TRUNCATE cap_hits")
    monkeypatch.setattr(c.users, "clock", lambda: NOON)
    monkeypatch.delenv("SITE_DAILY_BUDGET_USD", raising=False)
    return c


def _uid(h, sub, cap=None):
    """The app_users id of `sub` (signed in once through GET /me); its own daily cap raised when `cap` is given, so the
    per-user $1 cap never decides a wallet test."""
    assert h.client.get("/me", headers=bearer(mint(sub))).status_code == 200
    uid = _q(h.conn, "SELECT user_id FROM app_users WHERE clerk_user_id = %s", (sub,))[0][0]
    if cap is not None:
        with h.conn.cursor() as cur:
            cur.execute("UPDATE app_users SET daily_cap_usd = %s WHERE user_id = %s", (cap, uid))
    return uid


def _spend(conn, user_id, usd, at=NOON):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) "
                    "VALUES (%s, %s, 'claude-sonnet-4-6', 1, %s, 0, %s)", (at, f"w{user_id}{usd}{at.timestamp()}", usd, user_id))


def _ask(h, sub, message="hello"):
    return h.client.post("/chat", json={"message": message}, headers=bearer(mint(sub)))


def _hits(conn):
    return [(u, float(s), float(cap), k) for u, s, cap, k in
            _q(conn, "SELECT user_id, spent_usd, cap_usd, kind FROM cap_hits ORDER BY id")]


# ---- W1-W2 under / at / over the budget ---------------------------------------------------------------------------------

def test_w1_under_the_budget_the_turn_runs(w):
    bob = _uid(w, "user_bob", cap=1000)
    _uid(w, "user_alice")
    _spend(w.conn, bob, 49.99)
    calls = w.brain.calls
    r = _ask(w, "user_alice")
    assert r.status_code == 200 and r.json()["answer"] == "Answer to hello" and w.brain.calls == calls + 1
    assert _hits(w.conn) == []


@pytest.mark.parametrize("spent", [50.00, 50.50])
def test_w2_at_or_over_the_budget_the_turn_is_refused_with_no_model_call_and_a_site_cap_hit(w, spent):
    bob = _uid(w, "user_bob", cap=1000)
    alice = _uid(w, "user_alice")
    _spend(w.conn, bob, spent)
    calls, threads0 = w.brain.calls, _q(w.conn, "SELECT count(*) FROM chat_threads")[0][0]
    r = _ask(w, "user_alice")
    body = r.json()
    assert r.status_code == 200 and body["answer"] == WALLET.format(h=12, m=0) and body["capped"] is True
    assert body["limit"]["kind"] == "site" and body["limit"]["reset_at"].startswith("2026-11-15T00:00")
    assert w.brain.calls == calls and _q(w.conn, "SELECT count(*) FROM chat_threads")[0][0] == threads0
    assert _hits(w.conn) == [(alice, spent, 50.0, "site")]


def test_w2_the_countdown_is_hours_and_minutes_to_midnight_utc(w, monkeypatch):
    monkeypatch.setattr(w.users, "clock", lambda: datetime(2026, 11, 14, 20, 54, 30, tzinfo=UTC))
    assert w.users.site_cap_reply() == WALLET.format(h=3, m=5)


def test_w2_the_users_own_cap_still_comes_first_and_keeps_its_wording(w):
    alice = _uid(w, "user_alice")
    _spend(w.conn, alice, 1.00)
    r = _ask(w, "user_alice")
    assert r.json()["answer"].startswith("You've reached today's limit.") and r.json()["limit"]["kind"] == "daily"
    assert _hits(w.conn) == [(alice, 1.0, 1.0, None)]                       # the per-user row: kind stays NULL


# ---- W3-W5 who counts and who is never blocked --------------------------------------------------------------------------

def test_w3_the_owner_is_exempt_and_his_spend_does_not_count(w):
    bob = _uid(w, "user_bob", cap=1000)
    _ask(w, "user_admin")                                                   # links user 1
    _spend(w.conn, 1, 60.00)
    assert _ask(w, "user_bob").json()["answer"] == "Answer to hello"         # the owner's $60 does not count
    _spend(w.conn, bob, 50.00)
    calls = w.brain.calls
    assert _ask(w, "user_admin").json()["answer"] == "Answer to hello" and w.brain.calls == calls + 1
    assert [h[3] for h in _hits(w.conn)] == []


def test_w4_reserved_ids_and_guests_do_not_count(w):
    _uid(w, "user_alice")
    with w.conn.cursor() as cur:
        cur.execute("UPDATE app_users SET daily_cap_usd = 1000 WHERE user_id IN (9001, 9002)")
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at, is_guest) "
                    "VALUES (10900, 'user_guest_w4', NULL, 'Guest', 'guest', now(), TRUE)")
    _spend(w.conn, 9001, 30.00)
    _spend(w.conn, 9002, 30.00)
    _spend(w.conn, 10900, 60.00)
    assert w.users.site_spent_today() == 0.0
    assert _ask(w, "user_alice").json()["answer"] == "Answer to hello"


def test_w4_a_guest_is_never_blocked_by_the_site_wallet(w, monkeypatch):
    monkeypatch.setenv("SITE_DAILY_BUDGET_USD", "0")
    assert w.users.site_capped({"user_id": 10900, "is_guest": True}) == (False, None)
    assert w.users.site_capped({"user_id": 1, "is_exempt": True, "is_admin": True}) == (False, None)
    assert _hits(w.conn) == []


def test_w5_the_budget_counts_only_since_midnight_utc(w):
    bob = _uid(w, "user_bob", cap=1000)
    _uid(w, "user_alice")
    _spend(w.conn, bob, 50.00, at=NOON.replace(hour=0, minute=0) - timedelta(seconds=1))      # yesterday 23:59:59
    assert _ask(w, "user_alice").json()["answer"] == "Answer to hello"
    _spend(w.conn, bob, 50.00, at=NOON.replace(hour=0, minute=0))                             # today 00:00:00
    assert _ask(w, "user_alice").json()["limit"]["kind"] == "site"


# ---- W6 the setting --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,budget", [(None, 50.0), ("10", 10.0), ("12.5", 12.5), ("abc", 50.0), ("-5", 50.0), ("0", 0.0)])
def test_w6_the_budget_setting(w, monkeypatch, value, budget):
    if value is None:
        monkeypatch.delenv("SITE_DAILY_BUDGET_USD", raising=False)
    else:
        monkeypatch.setenv("SITE_DAILY_BUDGET_USD", value)
    assert w.users.site_budget() == budget


def test_w6_an_override_moves_the_line(w, monkeypatch):
    monkeypatch.setenv("SITE_DAILY_BUDGET_USD", "10")
    bob = _uid(w, "user_bob", cap=1000)
    alice = _uid(w, "user_alice")
    _spend(w.conn, bob, 10.00)
    assert _ask(w, "user_alice").json()["limit"]["kind"] == "site"
    assert _hits(w.conn) == [(alice, 10.0, 10.0, "site")]


def test_w6_zero_closes_it_to_everyone_but_the_owner(w, monkeypatch):
    monkeypatch.setenv("SITE_DAILY_BUDGET_USD", "0")
    alice = _uid(w, "user_alice")
    calls = w.brain.calls
    assert _ask(w, "user_alice").json()["answer"] == WALLET.format(h=12, m=0) and w.brain.calls == calls
    assert _ask(w, "user_admin").json()["answer"] == "Answer to hello" and w.brain.calls == calls + 1
    assert _hits(w.conn) == [(alice, 0.0, 0.0, "site")]


# ---- W7 the $0 endpoints, W8 off mode ------------------------------------------------------------------------------------

def test_w7_the_zero_dollar_endpoints_never_consult_the_wallet(dapi, monkeypatch):
    import users
    monkeypatch.setenv("SITE_DAILY_BUDGET_USD", "0")                       # closed to everyone but the owner
    seen = []
    real = users.site_capped
    monkeypatch.setattr(users, "site_capped", lambda user: seen.append(user["user_id"]) or real(user))
    hdr = bearer(mint(T1))
    built = dapi.client.post("/me/draft", headers=hdr)
    assert built.status_code == 200
    thread_id = built.json()["thread_id"]
    assert dapi.client.post("/me/draft/rebuild", headers=hdr).status_code == 200
    explain = dapi.client.post("/me/draft/explain", headers=hdr, json={"thread_id": thread_id, "question": "Why these players?"})
    assert explain.status_code == 200
    for answer in ("no", "yes"):
        r = dapi.client.post("/me/preview/answer", headers=hdr,
                             json={"thread_id": thread_id, "message_id": "m" * 32, "answer": answer})
        assert r.status_code == 200 and "daily limit for everyone" not in str(r.json())
    assert seen == []


def test_w8_off_mode_has_no_site_wallet(app, monkeypatch):
    import main
    import users
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("SITE_DAILY_BUDGET_USD", "0")
    monkeypatch.setattr(users, "site_spent_today", lambda *a, **k: 999.0)
    main._hits_by_ip.clear()
    main._hits_global.clear()
    r = app.client.post("/chat", json={"message": "hello"})
    assert r.status_code == 200 and "daily limit for everyone" not in r.json()["answer"]
