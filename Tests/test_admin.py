"""Prompt P7 Part 3 (2026-11-01): the admin page and the users CSV.

USER DECISIONS (1 Nov): "A list of who uses it: emails, names, counts." "A dashboard with number of users." "CSV button."

GET /admin (HTML) and GET /admin/users.csv exist only in clerk mode (off mode: 404); they need the session token of an
admin (app_users.is_admin: user 1, linked by ADMIN_EMAIL) -- no or a bad token 401, anyone else 403. The page: total users,
new sign-ups per day (last 30 days), active today / last 7 days, answers and $ per user (today, 7 days, all time), cap hits,
the sign-in method split. The CSV: one row per user -- name, email, sign-in method, joined, last active, answers, $ total;
a cell starting with = + - or @ is prefixed with ' (a spreadsheet would run it as a formula).

Prompt W7b (2026-11-11, USER: "we need to account for only real ones"): the numbers count REAL PEOPLE only -- accounts that
signed up through the site (user_id >= 10001). The owner (1) and the reserved eval accounts (9001 / 9002) appear nowhere:
not in the users list, the sign-ups, the active counts, the split, the cap hits or the CSV."""
import csv
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _bad_tokens   # noqa: E402,F401  (fixtures)

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)
CSV_HEADER = ["name", "email", "sign-in method", "joined", "last active", "answers", "$ total"]
R1, R2 = 10001, 10002                                    # two real people (signed up through the site)


@pytest.fixture
def adm(c, monkeypatch):
    """test_auth's clerk harness, the admin linked (user 1), a known population -- the owner, the two reserved accounts and
    two REAL users (10001 Alice, 10002 the formula-named one) -- the admin clock frozen at NOW."""
    import admin
    with c.conn.cursor() as cur:
        cur.execute("TRUNCATE cap_hits")
    assert c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_admin"))).status_code == 200
    with c.conn.cursor() as cur:
        cur.execute("DELETE FROM chat_usage")
        cur.execute("UPDATE app_users SET created_at = %s, last_active_at = %s WHERE user_id = 1",
                    (NOW - timedelta(days=40), NOW - timedelta(hours=1)))
        cur.execute("UPDATE app_users SET created_at = %s, last_active_at = %s, sign_in_method = 'google' WHERE user_id = 9001",
                    (NOW - timedelta(days=3), NOW - timedelta(days=2)))
        cur.execute("UPDATE app_users SET created_at = %s, last_active_at = %s WHERE user_id = 9002",
                    (NOW - timedelta(days=3), NOW - timedelta(days=10)))
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, created_at, last_active_at, profile_fetched_at) VALUES "
                    "(%s, 'user_alice', 'alice@example.test', 'Alice A', 'google', %s, %s, now()), "
                    "(%s, 'user_bob', 'bob@example.test', %s, 'email', %s, %s, now())",
                    (R1, NOW - timedelta(days=3), NOW - timedelta(hours=1),
                     R2, "=HYPERLINK(\"http://evil\")", NOW - timedelta(hours=2), NOW - timedelta(hours=2)))
        for uid, usd, at in ((1, 0.50, NOW - timedelta(hours=2)),                       # the owner's own use
                             (R1, 0.10, NOW - timedelta(hours=3)), (R1, 0.20, NOW - timedelta(days=2)),
                             (R2, 0.05, NOW - timedelta(hours=1)),
                             (9001, 0.40, NOW - timedelta(days=20))):                   # pre-launch testing
            cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) "
                        "VALUES (%s, %s, 'm', 1, %s, 0, %s)", (at, f"a{uid}{usd}", usd, uid))
        cur.execute("INSERT INTO cap_hits (user_id, hit_at, spent_usd, cap_usd) VALUES (%s, %s, 1.0, 1.0), (9002, %s, 1.0, 1.0)",
                    (R1, NOW - timedelta(hours=1), NOW - timedelta(days=5)))
    monkeypatch.setattr(admin, "clock", lambda: NOW)
    c.admin = admin
    return c


# ---- D1 off mode ------------------------------------------------------------------------------------------------------

def test_d1_off_mode_has_no_admin(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    for path in ("/admin", "/admin/users.csv"):
        r = app.client.get(path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


# ---- D2 who may call it ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", list(_bad_tokens()))
@pytest.mark.parametrize("path", ["/admin", "/admin/users.csv"])
def test_d2_a_bad_token_is_401_with_no_row_and_no_model_call(c, monkeypatch, case, path):
    import users
    touched = []
    monkeypatch.setattr(users, "user_for_claims", lambda *a, **k: touched.append(1))
    token = _bad_tokens()[case]
    before, calls = _all_counts(c.conn), c.brain.calls
    r = c.client.get(path, headers=bearer(token) if token else {})
    assert r.status_code == 401 and touched == [] and c.brain.calls == calls and _all_counts(c.conn) == before


@pytest.mark.parametrize("path", ["/admin", "/admin/users.csv"])
def test_d2_a_non_admin_is_403(adm, path):
    r = adm.client.get(path, headers=bearer(mint("user_a9001")))
    assert r.status_code == 403 and r.json() == {"detail": "admin only"}


# ---- D3 the dashboard --------------------------------------------------------------------------------------------------

def test_d3_the_numbers_count_real_people_only(adm):
    s = adm.admin.stats()
    assert s["total_users"] == 2                                                # 10001 + 10002; never 1 / 9001 / 9002
    assert s["active_today"] == 2 and s["active_7_days"] == 2
    assert s["sign_ups_per_day"] == [((NOW - timedelta(days=3)).date().isoformat(), 1), (NOW.date().isoformat(), 1)]
    assert s["sign_in_methods"] == {"google": 1, "email": 1}
    assert (s["cap_hits_today"], s["cap_hits_total"]) == (1, 1)                  # 9002's hit is not counted
    per = {u["user_id"]: u for u in s["users"]}
    assert set(per) == {R1, R2}
    assert (per[R1]["answers_today"], per[R1]["usd_today"]) == (1, 0.10)
    assert (per[R1]["answers_7_days"], round(per[R1]["usd_7_days"], 6)) == (2, 0.30)
    assert (per[R1]["answers_total"], round(per[R1]["usd_total"], 6), per[R1]["cap_hits"], per[R1]["is_admin"]) == (2, 0.30, 1, False)
    assert (per[R2]["answers_today"], per[R2]["usd_today"], per[R2]["cap_hits"]) == (1, 0.05, 0)


def test_d3_the_page_shows_them_and_escapes_names(adm):
    r = adm.client.get("/admin", headers=bearer(mint("user_admin")))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    for needle in ("Total users", ">2<", "Active today", "Active in the last 7 days", "Sign-ups per day", "Cap hits",
                   "Sign-in methods", "google", "0.3000", "users.csv"):
        assert needle in html, needle
    assert "=HYPERLINK(&quot;http://evil&quot;)" in html and '=HYPERLINK("http://evil")' not in html
    for absent in ("owner@example.test", "a9001@example.test", "b9002@example.test"):   # the owner and the eval accounts
        assert absent not in html, absent


# ---- D4 the CSV --------------------------------------------------------------------------------------------------------

def test_d4_the_csv_columns_and_rows(adm):
    r = adm.client.get("/admin/users.csv", headers=bearer(mint("user_admin")))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == CSV_HEADER and len(rows) == 3
    by_email = {row[1]: row for row in rows[1:]}
    assert by_email["alice@example.test"] == ["Alice A", "alice@example.test", "google", "2026-10-30 12:00 UTC", "2026-11-02 11:00 UTC", "2", "0.3000"]
    assert by_email["bob@example.test"][5:] == ["1", "0.0500"]
    assert "owner@example.test" not in by_email and "a9001@example.test" not in by_email


def test_d4_formula_cells_are_prefixed(adm):
    rows = list(csv.reader(io.StringIO(adm.client.get("/admin/users.csv", headers=bearer(mint("user_admin"))).text)))
    names = [row[0] for row in rows[1:]]
    assert "'=HYPERLINK(\"http://evil\")" in names
    import admin
    for raw, want in (("=1+1", "'=1+1"), ("+44 7700", "'+44 7700"), ("-2", "'-2"), ("@SUM(A1)", "'@SUM(A1)"),
                      ("Alice", "Alice"), ("", ""), (None, "")):
        assert admin.csv_cell(raw) == want
