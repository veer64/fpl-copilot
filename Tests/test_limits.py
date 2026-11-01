"""Prompt P7 Part 2 (2026-11-01): the $1/day per-user cap and the 10/min per-user rate limit -- clerk mode only (off mode is
exactly 13ebb8e: no cap, the old per-IP / global hourly limiter).

USER DECISION (1 Nov): "Daily cap" = $1/day per user; the admin is exempt.

- Before each /chat turn: the user's chat_usage cost since 00:00 UTC today >= their cap (app_users.daily_cap_usd, else
  DAILY_CAP_USD, default 1.00) and the user is not exempt -> HTTP 200 with "You've reached today's limit. It resets at 00:00
  UTC (in <h> h <m> m).", no model call, nothing in the thread, one cap_hits row. A turn already running finishes (its cost
  can take the day over the cap by at most one turn's cost).
- More than 10 /chat requests in 60 s from one user -> 429, no model call. Exempt users skip both.
- Every turn of a signed-in user writes its chat_usage row with user_id (the cap's ledger); off mode writes the row exactly
  as before (no user_id).
Offline: test_auth's harness (tokens, fake profiles, the brain, the threads test database)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _q, _all_counts   # noqa: E402,F401  (fixtures)
import thread_fakes as tf                                            # noqa: E402

UTC = timezone.utc
NOON = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)                   # 12 h to midnight


@pytest.fixture
def lim(c, monkeypatch):
    """test_auth's clerk harness with cap_hits empty and the users clock frozen at NOON."""
    with c.conn.cursor() as cur:
        cur.execute("TRUNCATE cap_hits")
    monkeypatch.setattr(c.users, "clock", lambda: NOON)
    return c


def _spend(conn, user_id, usd, at=NOON):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) "
                    "VALUES (%s, %s, 'claude-sonnet-4-6', 1, %s, 0, %s)", (at, f"t{user_id}{usd}{at.timestamp()}", usd, user_id))


def _ask(h, sub, message="hello", thread_id=None):
    body = {"message": message}
    if thread_id:
        body["thread_id"] = thread_id
    return h.client.post("/chat", json=body, headers=bearer(mint(sub)))


# ---- L1-L5 the daily cap -----------------------------------------------------------------------------------------------

def test_l1_at_the_cap_the_turn_is_refused_with_no_model_call_and_one_cap_hit(lim):
    _spend(lim.conn, 9001, 0.60)
    _spend(lim.conn, 9001, 0.40)
    calls, threads0 = lim.brain.calls, _q(lim.conn, "SELECT count(*) FROM chat_threads")[0][0]
    r = _ask(lim, "user_a9001")
    assert r.status_code == 200
    assert r.json()["answer"] == "You've reached today's limit. It resets at 00:00 UTC (in 12 h 0 m)."
    assert lim.brain.calls == calls and _q(lim.conn, "SELECT count(*) FROM chat_threads")[0][0] == threads0
    assert [(u, float(s), float(cap)) for u, s, cap in _q(lim.conn, "SELECT user_id, spent_usd, cap_usd FROM cap_hits")] == \
        [(9001, 1.0, 1.0)]


def test_l1_below_the_cap_the_turn_runs(lim):
    _spend(lim.conn, 9001, 0.99)
    calls = lim.brain.calls
    r = _ask(lim, "user_a9001")
    assert r.status_code == 200 and r.json()["answer"] == "Answer to hello" and lim.brain.calls == calls + 1
    assert _q(lim.conn, "SELECT count(*) FROM cap_hits")[0][0] == 0


def test_l2_the_cap_counts_only_since_midnight_utc_and_only_this_user(lim):
    _spend(lim.conn, 9001, 5.00, at=NOON.replace(hour=0, minute=0) - timedelta(seconds=1))   # yesterday 23:59:59
    _spend(lim.conn, 9002, 5.00)                                                              # another user
    assert _ask(lim, "user_a9001").json()["answer"] == "Answer to hello"


def test_l2_the_reset_countdown_is_hours_and_minutes_to_midnight_utc(lim, monkeypatch):
    monkeypatch.setattr(lim.users, "clock", lambda: datetime(2026, 11, 2, 20, 54, 30, tzinfo=UTC))
    assert lim.users.cap_reply() == "You've reached today's limit. It resets at 00:00 UTC (in 3 h 5 m)."
    monkeypatch.setattr(lim.users, "clock", lambda: datetime(2026, 11, 2, 23, 59, 50, tzinfo=UTC))
    assert lim.users.cap_reply() == "You've reached today's limit. It resets at 00:00 UTC (in 0 h 0 m)."


def test_l3_the_admin_is_exempt(lim):
    lim.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_admin")))   # links user 1
    _spend(lim.conn, 1, 7.50)
    assert _ask(lim, "user_admin").json()["answer"] == "Answer to hello"
    assert _q(lim.conn, "SELECT count(*) FROM cap_hits")[0][0] == 0


def test_l4_a_users_own_cap_overrides_the_default(lim):
    with lim.conn.cursor() as cur:
        cur.execute("UPDATE app_users SET daily_cap_usd = 0.01 WHERE user_id = 9002")
    _spend(lim.conn, 9002, 0.02)
    calls = lim.brain.calls
    assert _ask(lim, "user_b9002").json()["answer"].startswith("You've reached today's limit.")
    assert lim.brain.calls == calls
    assert _ask(lim, "user_a9001").json()["answer"] == "Answer to hello"                       # the default for 9001


def test_l4_the_default_cap_comes_from_daily_cap_usd(lim, monkeypatch):
    monkeypatch.setenv("DAILY_CAP_USD", "0.25")
    _spend(lim.conn, 9001, 0.30)
    assert _ask(lim, "user_a9001").json()["answer"].startswith("You've reached today's limit.")
    monkeypatch.delenv("DAILY_CAP_USD")
    assert lim.users.default_cap() == 1.00


# ---- L5 the rate limit -------------------------------------------------------------------------------------------------

def test_l5_the_eleventh_message_in_a_minute_is_429_with_no_model_call(lim, monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(lim.users, "monotonic", lambda: t["now"])
    for i in range(10):
        assert _ask(lim, "user_a9001").status_code == 200
        t["now"] += 1
    calls = lim.brain.calls
    r = _ask(lim, "user_a9001")
    assert r.status_code == 429 and lim.brain.calls == calls
    assert _ask(lim, "user_b9002").status_code == 200                                         # another user is not limited
    t["now"] += 51                                                                            # the first one left the window
    assert _ask(lim, "user_a9001").status_code == 200


def test_l5_the_admin_is_not_rate_limited(lim, monkeypatch):
    monkeypatch.setattr(lim.users, "monotonic", lambda: 1000.0)
    assert all(_ask(lim, "user_admin").status_code == 200 for _ in range(12))


def test_l5_a_bad_token_never_spends_a_users_quota(lim, monkeypatch):
    monkeypatch.setattr(lim.users, "monotonic", lambda: 1000.0)
    for _ in range(15):
        assert lim.client.post("/chat", json={"message": "x"}, headers=bearer("bad.token.x")).status_code == 401
    assert _ask(lim, "user_a9001").status_code == 200


# ---- L6 the ledger: chat_usage carries the signed-in user --------------------------------------------------------------

def test_l6_a_signed_in_turn_logs_its_usage_with_the_user_id(lim, monkeypatch):
    seen = []
    monkeypatch.setattr(lim.agent, "record_chat_usage", lambda *a, **k: seen.append(k))
    assert _ask(lim, "user_b9002").status_code == 200
    assert seen and seen[-1].get("user_id") == 9002


def test_l6_off_mode_logs_usage_exactly_as_before(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    seen = []
    monkeypatch.setattr(app.agent, "record_chat_usage", lambda *a, **k: seen.append(k))
    assert app.client.post("/chat", json={"message": "hello"}).status_code == 200
    assert seen == [{}]                                                                       # no user_id argument at all


def test_l6_record_chat_usage_writes_user_id_only_when_given(lim):
    import db_write
    db_write.record_chat_usage("turn-with-user", "claude-sonnet-4-6", 1, 10, 2, 0, 0, 0.001, 0, conn=lim.conn, user_id=9001)
    db_write.record_chat_usage("turn-without", "claude-sonnet-4-6", 1, 10, 2, 0, 0, 0.001, 0, conn=lim.conn)
    rows = dict(_q(lim.conn, "SELECT turn_id, user_id FROM chat_usage WHERE turn_id IN ('turn-with-user', 'turn-without')"))
    assert rows == {"turn-with-user": 9001, "turn-without": None}


# ---- L7 off mode has neither -------------------------------------------------------------------------------------------

def test_l7_off_mode_has_no_daily_cap_and_no_per_user_rate_limit(app, monkeypatch):
    import users
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setattr(users, "spent_today", lambda *a, **k: 99.0)
    monkeypatch.setattr(users, "monotonic", lambda: 1000.0)
    import main
    main._hits_by_ip.clear()
    main._hits_global.clear()
    assert all(app.client.post("/chat", json={"message": "hello"}).status_code == 200 for _ in range(12))
