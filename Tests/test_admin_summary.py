"""Prompt W6 (2026-11-11): GET /admin/summary -- the JSON behind the website's /admin page, built from the P7 admin queries
(admin.stats) plus the totals the page needs; GET /admin (HTML) and GET /admin/users.csv stay byte-identical.

USER DECISIONS (10 Nov): "Admin page first, just a basic one as no one is going to see it." Contents: top numbers, 30-day
sign-ups chart, users table + CSV, daily-limit hits, sign-in split, thumbs up/down counts with recent thumbs-down answers.

S1  off mode: /admin/summary does not exist (404 {"detail": "Not Found"}), like /admin.
S2  clerk mode: a missing or bad token is 401 before any DB access; anyone but an admin 403 {"detail": "admin only"}; the
    admin gets JSON.
S3  the numbers: users total / sign-ups today + 7 days / active today + 7 days; answers today + total and $ today / this month
    / total over EVERY chat_usage row -- the anonymous rows of deleted accounts (user_id NULL) count in the totals and appear
    as one "Deleted accounts" line (spend only); sign-ups per UTC day over the last 30 days, zero-filled, today last; the
    daily-limit hits of the last 30 days newest first with the user's name; the sign-in split; the users table rows with the
    per-user numbers the CSV has (the per-user sums + the deleted line = the totals).
S4  feedback: thumbs up / down totals (all time + last 7 days, by feedback_at) and the 20 most recent thumbs-down answers:
    when, the user, the question and the answer (first 300 characters) from the thread's transcript entry matched by
    message_id -- never on text (two identical questions: the thumbed one is the one listed) --, the Langfuse trace id
    (tracing.trace_id_for) and the trace URL when the SDK can give one (tracing off here: null). A row whose thread has no
    transcript entry is still listed, with question / answer null.
S5  GET /me carries is_admin (true for the linked admin, false for everyone else) -- the account menu's "Admin" item.

Offline: test_admin's `adm` harness (test_auth's clerk mode on the test database, the admin linked, a known population, the
admin clock frozen at NOW) with two anonymous cost rows added and chat_messages' clock frozen too."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _bad_tokens   # noqa: E402,F401  (fixtures)
from test_admin import adm, NOW                                                # noqa: E402,F401  (fixture)

KEYS = {"at", "users_total", "sign_ups_today", "sign_ups_7_days", "active_today", "active_7_days", "answers_today",
        "answers_total", "usd_today", "usd_month", "usd_total", "sign_ups_per_day", "users", "deleted_accounts", "cap_hits",
        "cap_hits_today", "cap_hits_total", "sign_in_methods", "feedback", "langfuse"}
USER_KEYS = {"user_id", "name", "email", "sign_in_method", "joined", "last_active", "answers", "usd", "answers_today",
             "usd_today", "answers_7_days", "usd_7_days", "cap_hits", "is_admin"}
DOWN_KEYS = {"message_id", "thread_id", "at", "user_id", "name", "question", "answer", "answer_chars", "answer_truncated",
             "trace_id", "trace_url"}


def _iso(dt):
    import threads
    return threads.iso(dt)


def _get(c, path, sub="user_admin"):
    return c.client.get(path, headers=bearer(mint(sub)))


def _summary(c):
    r = _get(c, "/admin/summary")
    assert r.status_code == 200, r.text
    return r.json()


def _chat(c, message, sub="user_a9001", thread_id=None):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    r = c.client.post("/chat", json=body, headers=bearer(mint(sub)))
    assert r.status_code == 200, r.text
    return r.json()


def _ids(c, thread_id, sub="user_a9001"):
    """The answers' message ids of a thread, in order (the website's endpoint)."""
    rows = _get(c, f"/threads/{thread_id}/messages", sub).json()
    return [m["message_id"] for m in rows if m["role"] == "assistant"]


@pytest.fixture
def sm(adm, monkeypatch):
    """`adm` + two anonymous cost rows (a deleted account's: user_id NULL, turn_id 'deleted') and chat_messages' clock at NOW;
    Langfuse off."""
    import chat_messages
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    with adm.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES "
                    "(%s, 'deleted', 'm', 1, 0.30, 0, NULL), (%s, 'deleted', 'm', 1, 0.70, 0, NULL)",
                    (NOW - timedelta(hours=4), NOW - timedelta(days=25)))
    monkeypatch.setattr(chat_messages, "clock", lambda: NOW)
    return adm


# ---- S1 off mode -----------------------------------------------------------------------------------------------------------

def test_s1_off_mode_has_no_summary(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    r = app.client.get("/admin/summary")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


# ---- S2 who may call it ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", list(_bad_tokens()))
def test_s2_a_bad_token_is_401_with_no_row_and_no_model_call(c, monkeypatch, case):
    import users
    touched = []
    monkeypatch.setattr(users, "user_for_claims", lambda *a, **k: touched.append(1))
    token = _bad_tokens()[case]
    before, calls = _all_counts(c.conn), c.brain.calls
    r = c.client.get("/admin/summary", headers=bearer(token) if token else {})
    assert r.status_code == 401 and touched == [] and c.brain.calls == calls and _all_counts(c.conn) == before


def test_s2_a_non_admin_is_403(adm):
    r = _get(adm, "/admin/summary", "user_a9001")
    assert r.status_code == 403 and r.json() == {"detail": "admin only"}


def test_s2_the_admin_gets_json_with_every_section(adm):
    r = _get(adm, "/admin/summary")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    s = r.json()
    assert set(s) == KEYS
    assert s["at"] == _iso(NOW)
    assert set(s["feedback"]) == {"up_total", "down_total", "up_7_days", "down_7_days", "recent_down"}
    assert set(s["langfuse"]) == {"host", "project_id"}


# ---- S3 the numbers --------------------------------------------------------------------------------------------------------

def test_s3_the_top_numbers_count_the_anonymous_cost_rows(sm):
    s = _summary(sm)
    assert s["users_total"] == 3
    assert (s["sign_ups_today"], s["sign_ups_7_days"]) == (0, 2)                        # 9001 + 9002 joined 3 days ago
    assert (s["active_today"], s["active_7_days"]) == (1, 2)
    assert (s["answers_today"], s["answers_total"]) == (3, 7)                           # 2 users' rows today + 1 anonymous
    assert (round(s["usd_today"], 6), round(s["usd_month"], 6), round(s["usd_total"], 6)) == (0.90, 0.90, 2.25)
    assert (s["deleted_accounts"]["answers"], round(s["deleted_accounts"]["usd"], 6)) == (2, 1.00)
    assert sum(u["answers"] for u in s["users"]) + s["deleted_accounts"]["answers"] == s["answers_total"]
    assert round(sum(u["usd"] for u in s["users"]) + s["deleted_accounts"]["usd"], 6) == round(s["usd_total"], 6)


def test_s3_thirty_days_of_sign_ups_zero_filled_with_today_last(sm):
    days = _summary(sm)["sign_ups_per_day"]
    assert len(days) == 30 and all(set(d) == {"day", "n"} for d in days)
    assert days[-1]["day"] == NOW.date().isoformat() and days[0]["day"] == (NOW - timedelta(days=29)).date().isoformat()
    assert [d["n"] for d in days if d["day"] == (NOW - timedelta(days=3)).date().isoformat()] == [2]
    assert sum(d["n"] for d in days) == 2


def test_s3_the_limit_hits_of_the_last_30_days_newest_first_with_names(sm):
    with sm.conn.cursor() as cur:                                                   # an old hit: counted, not listed
        cur.execute("INSERT INTO cap_hits (user_id, hit_at, spent_usd, cap_usd) VALUES (9001, %s, 1.0, 1.0)", (NOW - timedelta(days=31),))
    s = _summary(sm)
    assert s["cap_hits"] == [
        {"user_id": 9001, "name": "Nine A", "email": "a9001@example.test", "at": _iso(NOW - timedelta(hours=1)), "spent_usd": 1.0, "cap_usd": 1.0},
        {"user_id": 9002, "name": '=HYPERLINK("http://evil")', "email": "b9002@example.test", "at": _iso(NOW - timedelta(days=5)), "spent_usd": 1.0, "cap_usd": 1.0}]
    assert (s["cap_hits_today"], s["cap_hits_total"]) == (1, 3)


def test_s3_the_sign_in_split_and_the_users_rows_match_the_csv(sm):
    import admin
    s = _summary(sm)
    assert s["sign_in_methods"] == {"google": 2, "email": 1}
    assert len(s["users"]) == 3 and all(set(u) == USER_KEYS for u in s["users"])
    per = {u["user_id"]: u for u in s["users"]}
    a = per[9001]
    assert (a["name"], a["email"], a["sign_in_method"], a["joined"], a["last_active"]) == (
        "Nine A", "a9001@example.test", "google", _iso(NOW - timedelta(days=3)), _iso(NOW - timedelta(days=2)))
    assert (a["answers"], round(a["usd"], 6), a["answers_today"], a["answers_7_days"], a["cap_hits"], a["is_admin"]) == (3, 0.70, 1, 2, 1, False)
    assert per[1]["is_admin"] is True and per[9002]["answers"] == 1
    # the P7 outputs are built from the same rows and are unchanged: the CSV has the 3 users (no deleted line) with the same numbers
    csv_rows = admin.users_csv(admin.stats()).splitlines()
    assert len(csv_rows) == 4 and csv_rows[0] == "name,email,sign-in method,joined,last active,answers,$ total"
    assert [r for r in csv_rows if r.startswith("Nine A,")] == ["Nine A,a9001@example.test,google,2026-10-30 12:00 UTC,2026-10-31 12:00 UTC,3,0.7000"]


# ---- S4 feedback -----------------------------------------------------------------------------------------------------------

def test_s4_feedback_counts_and_the_thumbed_down_answer_found_by_message_id_not_text(sm):
    import tracing
    q = "Who should I captain this week?"
    a1 = _chat(sm, q)
    tid = a1["thread_id"]
    a2 = _chat(sm, q, thread_id=tid)                                                # the same question twice
    m1, m2 = _ids(sm, tid)
    assert m1 and m2 and m1 != m2
    assert sm.client.post(f"/messages/{m2}/feedback", json={"score": "down"}, headers=bearer(mint("user_a9001"))).status_code == 200
    assert sm.client.post(f"/messages/{m1}/feedback", json={"score": "up"}, headers=bearer(mint("user_a9001"))).status_code == 200
    f = _summary(sm)["feedback"]
    assert (f["up_total"], f["down_total"], f["up_7_days"], f["down_7_days"]) == (1, 1, 1, 1)
    assert len(f["recent_down"]) == 1 and set(f["recent_down"][0]) == DOWN_KEYS
    row = f["recent_down"][0]
    assert row["message_id"] == m2 and row["thread_id"] == tid                       # the SECOND answer, by id
    assert (row["user_id"], row["name"], row["at"]) == (9001, "Nine A", _iso(NOW))
    assert row["question"] == q and row["answer"] == a2["answer"] and row["answer_truncated"] is False
    assert row["answer_chars"] == len(a2["answer"])
    assert row["trace_id"] == tracing.trace_id_for(m2) and row["trace_url"] is None
    # the thumb cleared: nothing to list
    assert sm.client.post(f"/messages/{m2}/feedback", json={"score": None}, headers=bearer(mint("user_a9001"))).status_code == 200
    f = _summary(sm)["feedback"]
    assert (f["down_total"], f["down_7_days"], f["recent_down"]) == (0, 0, [])


def test_s4_a_long_answer_is_cut_at_300_characters(sm):
    q = "captain " * 50                                                              # the brain echoes the question: > 300 chars
    a = _chat(sm, q)
    [mid] = _ids(sm, a["thread_id"])
    assert len(a["answer"]) > 300
    assert sm.client.post(f"/messages/{mid}/feedback", json={"score": "down"}, headers=bearer(mint("user_a9001"))).status_code == 200
    [row] = _summary(sm)["feedback"]["recent_down"]
    assert row["answer"] == a["answer"][:300] and row["answer_truncated"] is True and row["answer_chars"] == len(a["answer"])


def test_s4_twenty_most_recent_only_seven_day_window_and_a_row_without_a_transcript(sm):
    import chat_messages
    chat_messages.ensure_schema(sm.conn)
    with sm.conn.cursor() as cur:
        for i in range(25):                                                          # 20 within 7 days, 5 older
            at = NOW - timedelta(minutes=i) if i < 20 else NOW - timedelta(days=8, minutes=i)
            cur.execute("INSERT INTO chat_messages (message_id, thread_id, user_id, q, created_at, feedback, feedback_at) "
                        "VALUES (%s, 'th_no_such_thread', 9002, %s, %s, 'down', %s)", (f"ghost{i}", i, at, at))
    f = _summary(sm)["feedback"]
    assert (f["down_total"], f["down_7_days"]) == (25, 20)
    assert [r["message_id"] for r in f["recent_down"]] == [f"ghost{i}" for i in range(20)]   # newest first, 20 at most
    r0 = f["recent_down"][0]
    assert (r0["name"], r0["question"], r0["answer"], r0["answer_chars"], r0["answer_truncated"]) == ('=HYPERLINK("http://evil")', None, None, 0, False)
    assert r0["trace_id"] and r0["trace_url"] is None


# ---- S5 /me ----------------------------------------------------------------------------------------------------------------

def test_s5_me_says_is_admin_for_the_linked_admin_only(adm):
    assert _get(adm, "/me", "user_admin").json()["is_admin"] is True
    assert _get(adm, "/me", "user_a9001").json()["is_admin"] is False
