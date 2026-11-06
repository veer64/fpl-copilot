"""Prompt F1a Part 3 (2026-11-02): the website's thread and account endpoints (clerk mode only; 404 in off mode, like /admin).

E1 GET /me -> {user_id, is_admin, daily_cap_usd, spent_today_usd, active_team}.
E2 POST /threads -> {thread_id}: a new, non-default thread of this user; /chat runs in it.
E3 GET /threads -> this user's threads only: thread_id, created_at, last_active, is_default, title (the first question,
   [email] / [phone] masked, at most 60 characters).
E4 GET /threads/{id}/messages -> [{role, text, at}]: the user's questions and the answers as /chat delivered them (tool
   names replaced, citations rendered), in order -- no tool content, no fact-check note, no clock line. A thread stored
   before the transcript existed still lists its turns (the stored question and answer text, at null).
E5 another user's or an unknown thread -> 403 {"detail": "thread not found for this user"}, no model call, no row.
E6 a missing or bad token -> 401 on every endpoint, nothing written; off mode -> 404 (with the key) / 401 (without).
E7 60 requests a minute per user on these endpoints, then 429 (the admin is exempt, as for /chat).

Offline: the app in clerk mode on test_threads' test database (test_auth's `c`), the brain as the model."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _all_counts, _bad_tokens, _q   # noqa: E402,F401  (fixtures)
import thread_fakes as tf                                                                       # noqa: E402

A, B = "user_a9001", "user_b9002"
REFUSED = {"detail": "thread not found for this user"}


def _h(sub=A):
    return bearer(mint(sub))


def _chat(c, message, thread_id=None, sub=A):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    r = c.client.post("/chat", json=body, headers=_h(sub))
    assert r.status_code == 200, r.text
    return r.json()


ENDPOINTS = [("get", "/me"), ("get", "/threads"), ("post", "/threads"), ("get", "/threads/th_anything/messages")]


# ---- E1 ----------------------------------------------------------------------------------------------------------------

def test_e1_me_names_the_signed_in_user_their_cap_and_todays_spend(c):
    r = c.client.get("/me", headers=_h())
    assert r.status_code == 200, r.text
    assert r.json() == {"user_id": 9001, "is_admin": False, "daily_cap_usd": 1.0, "spent_today_usd": 0.0,
                        "active_team": None}
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_usage (turn_id, model, api_calls, usd, user_id) VALUES ('t_e1', 'm', 1, 0.25, 9001)")
    try:
        assert c.client.get("/me", headers=_h()).json()["spent_today_usd"] == 0.25
    finally:
        with c.conn.cursor() as cur:
            cur.execute("DELETE FROM chat_usage WHERE turn_id = 't_e1'")


# ---- E2 / E3 -----------------------------------------------------------------------------------------------------------

def test_e2_post_threads_makes_a_new_non_default_thread_and_chat_runs_in_it(c):
    r = c.client.post("/threads", headers=_h())
    assert r.status_code == 200 and set(r.json()) == {"thread_id"}
    tid = r.json()["thread_id"]
    assert _q(c.conn, "SELECT user_id, is_default FROM chat_threads WHERE thread_id = %s", (tid,)) == [(9001, False)]
    assert _chat(c, "About apple", tid)["thread_id"] == tid
    other = c.client.post("/threads", headers=_h()).json()["thread_id"]
    assert other != tid


def test_e3_threads_lists_only_this_users_threads_with_a_masked_title(c):
    first = "Email me at someone@example.com or ring +44 7700 900123 about my whole squad and the next six gameweeks"
    t1 = _chat(c, first)["thread_id"]                                       # the default thread
    _chat(c, "About banana", t1)
    t2 = c.client.post("/threads", headers=_h()).json()["thread_id"]        # a new thread, no turn yet
    tb = _chat(c, "About cherry", sub=B)["thread_id"]                        # another user's
    r = c.client.get("/threads", headers=_h())
    assert r.status_code == 200, r.text
    rows = r.json()
    print(f"E3 rows: count={len(rows)} first={rows[0]['thread_id'] if rows else None} last={rows[-1]['thread_id'] if rows else None}")
    by = {x["thread_id"]: x for x in rows}
    assert set(by) == {t1, t2} and tb not in by
    assert set(by[t1]) == {"thread_id", "created_at", "last_active", "is_default", "title", "team_label", "fpl_team_id"}   # F1b / W3
    assert by[t1]["team_label"] is None and by[t1]["fpl_team_id"] is None   # 9001 has no imported team
    assert by[t1]["is_default"] is True and by[t2]["is_default"] is False
    title = by[t1]["title"]
    assert len(title) <= 60 and "[email]" in title and "[phone]" in title and "example.com" not in title, title
    assert title.startswith("Email me at [email] or ring [phone]")
    assert by[t2]["title"] is None and by[t2]["last_active"] == by[t2]["created_at"]
    assert by[t1]["last_active"] >= by[t1]["created_at"]
    assert [x["thread_id"] for x in rows] == [t2, t1]                       # most recently active first


# ---- E4 ----------------------------------------------------------------------------------------------------------------

def test_e4_messages_are_the_questions_and_the_delivered_answers_only(c):
    q1, q2 = "tool: apple", "Tell me about get_my_squad please"            # a tool turn; an answer whose raw text names a tool
    a1 = _chat(c, q1)
    tid = a1["thread_id"]
    a2 = _chat(c, q2, tid)
    assert "get_my_squad" not in a2["answer"]                               # /chat delivered the rendered text
    r = c.client.get(f"/threads/{tid}/messages", headers=_h())
    assert r.status_code == 200, r.text
    msgs = r.json()
    assert [(m["role"], m["text"]) for m in msgs] == [("user", q1), ("assistant", a1["answer"]),
                                                      ("user", q2), ("assistant", a2["answer"])]
    assert all(set(m) == {"role", "text", "at"} and m["at"] for m in msgs)
    assert msgs[0]["at"] <= msgs[1]["at"] <= msgs[2]["at"] <= msgs[3]["at"]
    blob = str(msgs)
    for leak in ("tool_use", "tool_result", "- Now:", "Next deadline", "thread_seen", "automatic check"):
        assert leak not in blob, leak


def test_e4_a_thread_stored_before_the_transcript_still_lists_its_turns(c):
    import agent_graph
    import threads
    tid = threads.new_thread_id()
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_threads (thread_id, user_id) VALUES (%s, 9001)", (tid,))
    old = [{"role": "user", "content": "About plum"},
           {"role": "assistant", "content": [{"type": "text", "text": "Answer about get_my_xi"}]}]
    agent_graph.thread_graph().update_state(agent_graph._thread_config(tid), {"messages": old}, as_node="finalize")
    msgs = c.client.get(f"/threads/{tid}/messages", headers=_h()).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[0]["text"] == "About plum"
    assert "get_my_xi" not in msgs[1]["text"] and msgs[1]["text"].startswith("Answer about")
    assert msgs[0]["at"] is None and msgs[1]["at"] is None
    _chat(c, "About quince", tid)                                           # a new turn: the transcript starts here
    msgs = c.client.get(f"/threads/{tid}/messages", headers=_h()).json()
    assert [m["text"] for m in msgs[::2]] == ["About plum", "About quince"] and msgs[3]["at"] is not None


def test_e4_a_failed_turn_leaves_no_transcript_entry(c, monkeypatch):
    tid = _chat(c, "About apple")["thread_id"]
    real = c.brain.respond

    def respond(kw, q):
        if q == "tool: banana" and tf.after_tool(kw):
            raise RuntimeError("the model failed mid-turn")
        return real(kw, q)
    monkeypatch.setattr(c.brain, "respond", respond)
    with pytest.raises(RuntimeError):
        c.client.post("/chat", json={"message": "tool: banana", "thread_id": tid}, headers=_h())
    msgs = c.client.get(f"/threads/{tid}/messages", headers=_h()).json()
    assert [m["text"] for m in msgs] == ["About apple", "Answer to About apple"]


# ---- E5 ----------------------------------------------------------------------------------------------------------------

def test_e5_another_users_or_an_unknown_thread_is_403_with_no_model_call_and_no_row(c):
    tb = _chat(c, "About cherry", sub=B)["thread_id"]
    before, calls = _all_counts(c.conn), c.brain.calls
    for tid in (tb, "th_unknown", "nonsense"):
        r = c.client.get(f"/threads/{tid}/messages", headers=_h())
        assert r.status_code == 403 and r.json() == REFUSED, (tid, r.status_code, r.text)
    assert c.brain.calls == calls and _all_counts(c.conn) == before


# ---- E6 ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["missing", "expired", "wrong azp", "no azp", "another key"])
@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_e6_a_bad_token_is_401_on_every_endpoint_with_nothing_written(c, case, method, path):
    token = _bad_tokens()[case]
    before, calls = _all_counts(c.conn), c.brain.calls
    r = getattr(c.client, method)(path, headers=bearer(token) if token else {})
    assert r.status_code == 401, (case, path, r.status_code, r.text)
    assert c.brain.calls == calls and _all_counts(c.conn) == before


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_e6_off_mode_has_none_of_them(app, monkeypatch, method, path):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("AUTH_MODE", raising=False)
    r = getattr(app.client, method)(path)                                   # the app fixture sends the key
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    r = getattr(TestClient(app.main.app), method)(path)                      # no key: the gate answers first
    assert r.status_code == 401


# ---- E7 ----------------------------------------------------------------------------------------------------------------

def test_e7_sixty_requests_a_minute_then_429_and_the_admin_is_exempt(c, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(c.users, "monotonic", lambda: clock["t"])
    h = _h()
    codes = [c.client.get("/me", headers=h).status_code for _ in range(60)]
    assert codes == [200] * 60
    r = c.client.get("/threads", headers=h)
    assert r.status_code == 429 and "60" in r.json()["detail"]
    assert c.client.get("/me", headers=_h(B)).status_code == 200            # per user
    assert _chat(c, "About apple")["answer"] == "Answer to About apple"     # /chat keeps its own window
    clock["t"] += 61
    assert c.client.get("/me", headers=h).status_code == 200                # a minute later
    adm = bearer(mint("user_admin"))
    assert all(c.client.get("/me", headers=adm).status_code == 200 for _ in range(70))
