"""Prompt W4 (2026-11-06): the backend behind the Chat page -- Data 1-6 of the brief + the approved 2,000-character cap.
Clerk mode only; off mode byte-identical for the model (payload v5 untouched: test_agent_payload_equivalence); existing
response fields unchanged (additions only); zero-team users unchanged; the daily-limit TEXT unchanged.

D0  /chat refuses a message over 2,000 characters with 422 before any model call or row (clerk and off mode); 2,000 is fine.
D1  sources[] on the answer: the news items the answer CITED (never the uncited ones -- checkpoint C4), {name, headline, date,
    url?}, FPL rows as name "FPL" with no url; plus FPL injury notes from this turn's player cards whose player the answer
    names, dated news_added; deduped, at most 6.
D2  the daily-limit reply keeps its text, capped: true and HTTP 200, and gains limit {kind: "daily", reset_at: next 00:00 UTC}.
D3  squad_preview from the turn's set_my_squad(confirm=false) call (arguments + result + ticket), never the answer text:
    transfer / captain / vice_captain / bench rows with Player objects, slot = the current card's slot of the OUT player (C2),
    impact numbers only ones the tools computed (pts_delta only from the same turn's propose_transfers); squad_applied from a
    committed confirm. Stored with the message, restored by GET /threads/{id}/messages.
D4  GET /me/teams/{id}/card: formation, bank, free transfers, team value, squad-as-of GW, predictions_updated_at, chips of the
    current half, 15 players (slot 1-15, C/VC, names, club code, position, price, form, next fixture, flag, prediction +
    source), next_gw, fpl_live; FPL calls cached per process behind a single-flight lock; the last cached copy past its TTL
    when FPL fails (C8), then the saved squad from players_live; one DB connection per request.
D5  POST /messages/{id}/feedback {score: up|down|null}: own messages only (404), stored first, then a Langfuse score with a
    fixed id (idempotent; null -> "none" + "cleared by the user"), returned by the messages endpoint.
D6  /threads rows gain team_name and updated_at; threads with no message are not listed.
C6  answers stored before W4 have no chat_messages row: message_id null, no sources / feedback. A failed turn leaves no row.

Offline: test_auth's `c` (clerk mode on the test database, thread_fakes' brain) with a W4 script; the card on test_fpl_import's
`api` fixture with the recorded FPL responses + Tests/fixtures/team_card (the 6 Nov local bootstrap snapshot trimmed to the
recorded team, fixtures/?future=1 recorded 6 Nov)."""
import copy
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fpl_import                                                                     # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q, _all_counts                      # noqa: E402,F401  (fixtures)
from test_fpl_import import api, Fpl, TID, NOW, T1, T2, _offline, _post, _get, load   # noqa: E402,F401  (fixtures)
import thread_fakes as tf                                                             # noqa: E402

A, B = "user_a9001", "user_b9002"
FIX = REPO / "Tests" / "fixtures" / "team_card"
CARD_NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)          # GW10's deadline passed (18:30), GW11 next (21 Nov)

NEWS_Q, UNCITED_Q, CARD_Q = "news: Saka", "news: nothing cited", "card: Palmer"
PLAN_Q, CAPTAIN_Q, BENCH_Q, REORDER_Q = "plan: two moves", "Make P14 my captain.", "bench: swap", "bench: reorder"
SEED = {"player_ids": list(range(1, 16)), "captain_id": 13, "vice_id": 14, "bench_order_ids": [2, 7, 12, 15]}
CHANGE_C = {**SEED, "captain_id": 14, "vice_id": 13}
CHANGE_B = {**SEED, "bench_order_ids": [2, 7, 11, 15]}
CHANGE_R = {**SEED, "bench_order_ids": [7, 2, 12, 15]}
NEWS = [{"id": "c1", "source": "Arsenal official site", "headline": "Saka a doubt for Sunderland trip", "url": "https://www.arsenal.com/news/saka",
         "date": "2026-11-03", "date_words": "Tue 3 Nov 2026", "date_basis": "publisher", "age": "3 days ago", "about_requested_player": True,
         "players": ["Bukayo Saka"], "text": "..."},
        {"id": "c2", "source": "FPL official", "headline": "Hamstring injury - 75% chance of playing", "url": None, "date": "2026-11-04",
         "date_words": "Wed 4 Nov 2026", "date_basis": "FPL", "age": "2 days ago", "about_requested_player": True, "players": ["Bukayo Saka"], "text": "..."},
        {"id": "c3", "source": "BBC Sport", "headline": "Arsenal injury round-up", "url": "https://www.bbc.co.uk/sport/1", "date": "2026-11-02",
         "date_words": "Mon 2 Nov 2026", "date_basis": "publisher", "age": "4 days ago", "about_requested_player": False, "players": [], "text": "..."}]
PALMER_CARD = {"player_id": 154, "name": "Cole Palmer", "web_name": "Palmer", "position": "MID", "team": "Chelsea", "price": 9.8,
               "status": "d", "chance": 75, "news": "Knock - 75% chance of playing",
               "availability": {"status": "d", "status_word": "doubtful", "chance_of_playing_next_round": 75,
                                "news": "Knock - 75% chance of playing", "as_of": "2026-11-05 20:30:09+00:00"}}
PLAN = {"proposal_id": 77, "effective_horizon": 6, "hold_comparison": {"refused": False, "gap_objective": 2.6, "gap_this_gw": 0.4},
        "apply_with": {**tf.CHANGE_A, "gw": 9, "proposal_id": 77, "confirm": True}}


class W4Brain(tf.Brain):
    """thread_fakes' script + the W4 questions: a news turn that cites c1 and c2 (and an unknown c99), an uncited news turn,
    a player-card turn, a plan-then-preview turn, and three squad-change previews (captain, bench swap, bench reorder)."""

    def respond(self, kw, q):
        if not tf.after_tool(kw):
            if q in (NEWS_Q, UNCITED_Q):
                return tf.tool_use("search_news", {"query": "Saka", "players": ["Saka"]}, "t_news")
            if q == CARD_Q:
                return tf.tool_use("get_player_card", {"player_id": 154}, "t_card")
            if q == PLAN_Q:
                return tf.tool_use("propose_transfers", {}, "t_plan")
            if q == CAPTAIN_Q:
                return tf.tool_use("set_my_squad", {**CHANGE_C, "confirm": False}, "t_cap")
            if q == BENCH_Q:
                return tf.tool_use("set_my_squad", {**CHANGE_B, "confirm": False}, "t_bench")
            if q == REORDER_Q:
                return tf.tool_use("set_my_squad", {**CHANGE_R, "confirm": False}, "t_reorder")
            return super().respond(kw, q)
        result = tf.last_tool_result(kw)
        if q == NEWS_Q:
            return tf.text("Saka is a doubt c1 and FPL agrees c2. Nothing on c99.")
        if q == UNCITED_Q:
            return tf.text("Saka is fine, nothing to report.")
        if q == CARD_Q:
            return tf.text("Palmer has a knock. Haaland is fine.")
        if q == PLAN_Q and "'proposal_id': 77" in result and "PREVIEW ONLY" not in result:
            return tf.tool_use("set_my_squad", {**tf.CHANGE_A, "confirm": False, "proposal_id": 77}, "t_plan_preview")
        if q in (PLAN_Q, CAPTAIN_Q, BENCH_Q, REORDER_Q) and "PREVIEW ONLY" in result:
            return tf.text("Here is the preview. Shall I apply it?")
        return super().respond(kw, q)


@pytest.fixture
def w4(c, monkeypatch):
    """`c` with the W4 brain and the three stubbed tools; the preview's player objects built from the recorded bootstrap
    (no network inside a turn: team_card reads only its caches and the local snapshot); FPL-note dates from a stubbed
    snapshot map."""
    import agent
    import model_tools
    import team_card
    brain = W4Brain()
    monkeypatch.setattr(agent, "client", brain)
    c.brain = brain
    saved = dict(agent.available_functions)
    agent.available_functions["search_news"] = lambda query, players=None, clubs=None: {"as_of": "2026-11-06T12:00:00Z", "results": copy.deepcopy(NEWS)}
    agent.available_functions["get_player_card"] = lambda player_id: copy.deepcopy(PALMER_CARD)
    agent.available_functions["propose_transfers"] = lambda **kw: copy.deepcopy(PLAN)
    monkeypatch.setattr(model_tools, "_snapshot_news", lambda as_of=None: {154: ("Knock - 75% chance of playing", "2026-11-05T20:30:09.025008Z")})
    boot = json.loads((FIX / "bootstrap.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(team_card, "_bootstrap", lambda get=None, now=None, allow_fetch=True: (boot, True))
    monkeypatch.setattr(team_card, "_fixtures", lambda get=None, allow_fetch=True: (None, False))
    monkeypatch.setattr(team_card, "_pool", lambda next_gw: (None, None))
    yield c
    agent.available_functions.clear()
    agent.available_functions.update(saved)


def _h(sub=A):
    return bearer(mint(sub))


def _chat(c, message, thread_id=None, sub=A, status=200):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    r = c.client.post("/chat", json=body, headers=_h(sub))
    assert r.status_code == status, r.text
    return r.json()


def _messages(c, tid, sub=A):
    r = c.client.get(f"/threads/{tid}/messages", headers=_h(sub))
    assert r.status_code == 200, r.text
    return r.json()


def _counts(c):
    with c.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chat_messages")
        return cur.fetchone()[0]


# ---- D0: the 2,000-character cap -----------------------------------------------------------------------------------------

def test_d0_a_message_over_2000_characters_is_422_before_any_model_call_or_row(c):
    before, calls = _all_counts(c.conn), c.brain.calls
    r = c.client.post("/chat", json={"message": "x" * 2001}, headers=_h())
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": "message too long: at most 2,000 characters"}
    assert c.brain.calls == calls and _all_counts(c.conn) == before
    assert c.client.post("/chat", json={"message": "y" * 2000}, headers=_h()).status_code == 200     # exactly 2,000 is fine


def test_d0_off_mode_refuses_the_same_way(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    calls = app.brain.calls
    r = app.client.post("/chat", json={"message": "x" * 2001})                            # the client carries the key
    assert r.status_code == 422 and r.json() == {"detail": "message too long: at most 2,000 characters"}
    assert app.brain.calls == calls
    assert app.client.post("/chat", json={"message": "tool:xi"}).status_code == 200


# ---- D1: sources -----------------------------------------------------------------------------------------------------------

def test_d1_sources_are_the_cited_news_items_and_fpl_rows_carry_no_url(w4):
    a = _chat(w4, NEWS_Q)
    assert set(a) >= {"answer", "thread_id", "message_id", "sources", "squad_preview", "squad_applied"}
    assert "trace_id" not in a                                                           # C5: server-side only
    assert a["sources"] == [{"name": "Arsenal official site", "headline": "Saka a doubt for Sunderland trip", "date": "2026-11-03",
                             "url": "https://www.arsenal.com/news/saka"},
                            {"name": "FPL", "headline": "Hamstring injury - 75% chance of playing", "date": "2026-11-04"}]
    assert "[1]" in a["answer"] and "[unverified]" in a["answer"]                         # the rendered text is as before
    msgs = _messages(w4, a["thread_id"])
    assert msgs[1]["message_id"] == a["message_id"] and msgs[1]["sources"] == a["sources"]
    assert set(msgs[0]) == {"role", "text", "at"}                                         # user rows unchanged
    assert set(msgs[1]) == {"role", "text", "at", "message_id", "sources", "squad_preview", "squad_applied", "feedback"}


def test_d1_nothing_cited_means_no_source_chips(w4):
    a = _chat(w4, UNCITED_Q)
    assert a["sources"] == [] and a["squad_preview"] is None and a["squad_applied"] is None


def test_d1_an_fpl_note_from_a_player_card_the_answer_names_is_a_source_dated_news_added(w4):
    a = _chat(w4, CARD_Q)
    assert a["sources"] == [{"name": "FPL", "headline": "Knock - 75% chance of playing", "date": "2026-11-05"}]


# ---- D2: the daily limit ---------------------------------------------------------------------------------------------------

def test_d2_the_capped_reply_keeps_its_text_and_gains_a_structured_limit(c, monkeypatch):
    import users
    frozen = datetime(2026, 11, 6, 20, 48, tzinfo=timezone.utc)
    monkeypatch.setattr(users, "clock", lambda: frozen)
    with c.conn.cursor() as cur:
        cur.execute("UPDATE app_users SET daily_cap_usd = 0 WHERE user_id = 9001")
    calls = c.brain.calls
    a = _chat(c, "Anything")
    assert c.brain.calls == calls
    assert a["answer"] == "You've reached today's limit. It resets at 00:00 UTC (in 3 h 12 m)."
    assert a["capped"] is True and a["limit"] == {"kind": "daily", "reset_at": "2026-11-07T00:00:00.000Z"}
    assert "message_id" not in a and "sources" not in a


# ---- D3: the squad-change preview and the applied write --------------------------------------------------------------------

def _player_keys():
    return {"slot", "id", "short_name", "full_name", "club", "position", "price", "form", "role", "next", "flag", "pred", "in_squad"}


def test_d3_a_transfer_preview_is_derived_from_the_tool_call_with_the_out_players_slot(w4):
    a = _chat(w4, tf.PREVIEW_Q)                                                          # CHANGE_A: P15 out, P16 in (bench 4)
    pv = a["squad_preview"]
    assert pv is not None and a["squad_applied"] is None
    assert set(pv) == {"gw", "expires_at", "changes", "impact"} and pv["gw"] == 9
    assert pv["expires_at"].endswith("Z") and "ticket" not in json.dumps(pv).lower()     # no ticket id exposed
    assert len(pv["changes"]) == 1
    ch = pv["changes"][0]
    assert ch["type"] == "transfer" and ch["slot"] == 15                                 # C2: the OUT player's current slot
    assert set(ch["out"]) == _player_keys() and set(ch["in"]) == _player_keys()
    assert (ch["out"]["id"], ch["out"]["slot"], ch["out"]["in_squad"]) == (15, 15, True)
    assert (ch["in"]["id"], ch["in"]["slot"], ch["in"]["in_squad"]) == (16, 15, False)
    assert ch["in"]["position"] == "FWD" and ch["in"]["price"] == 4.0
    assert pv["impact"] == {"pts_delta": None, "pts_horizon_gws": None, "bank_after": 40.0,
                            "ft_before": pv["impact"]["ft_before"], "ft_after": pv["impact"]["ft_before"] - 1, "hit_pts": 0}
    msgs = _messages(w4, a["thread_id"])
    assert msgs[1]["squad_preview"] == pv                                                # survives a reload


def test_d3_the_plans_gain_rides_only_when_the_preview_carries_its_proposal_id(w4):
    pv = _chat(w4, PLAN_Q)["squad_preview"]
    assert pv["impact"]["pts_delta"] == 2.6 and pv["impact"]["pts_horizon_gws"] == 6
    assert [ch["type"] for ch in pv["changes"]] == ["transfer"]


def test_d3_captain_and_vice_changes_keep_both_players_in_place(w4):
    pv = _chat(w4, CAPTAIN_Q)["squad_preview"]
    rows = [(ch["type"], ch["out"]["id"], ch["in"]["id"], ch["slot"]) for ch in pv["changes"]]
    assert rows == [("captain", 13, 14, None), ("vice_captain", 14, 13, None)]
    assert pv["changes"][0]["out"]["role"] == "C" and pv["changes"][0]["in"]["role"] == "VC"


def test_d3_an_xi_bench_swap_is_one_bench_row_at_the_xi_players_slot(w4):
    pv = _chat(w4, BENCH_Q)["squad_preview"]                                             # P11 (XI, slot 9) <-> P12 (bench 3)
    rows = [(ch["type"], ch["out"]["id"], ch["in"]["id"], ch["slot"]) for ch in pv["changes"]]
    assert rows == [("bench", 11, 12, 9)]


def test_d3_a_bench_reorder_is_one_row_per_changed_bench_position(w4):
    pv = _chat(w4, REORDER_Q)["squad_preview"]                                           # bench 1 <-> 2
    rows = [(ch["type"], ch["out"]["id"], ch["in"]["id"], ch["slot"]) for ch in pv["changes"]]
    assert rows == [("bench", 2, 7, 12), ("bench", 7, 2, 13)]


def test_d3_a_committed_confirm_is_squad_applied_and_the_turn_has_no_preview(w4):
    a1 = _chat(w4, tf.PREVIEW_Q)
    a2 = _chat(w4, tf.YES_Q, a1["thread_id"])
    assert a2["answer"] == "Written." and a2["squad_preview"] is None
    assert set(a2["squad_applied"]) == {"gw", "version_id"} and a2["squad_applied"]["gw"] == 9
    assert isinstance(a2["squad_applied"]["version_id"], int)
    msgs = _messages(w4, a1["thread_id"])
    assert msgs[1]["squad_preview"] is not None and msgs[3]["squad_applied"] == a2["squad_applied"]
    with w4.conn.cursor() as cur:
        cur.execute("SELECT message_id, thread_id, user_id, q FROM chat_messages WHERE thread_id = %s ORDER BY created_at", (a1["thread_id"],))
        rows = cur.fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [(a1["message_id"], a1["thread_id"], 9001, 0), (a2["message_id"], a1["thread_id"], 9001, 1)]


def test_d3_a_failed_turn_leaves_no_message_row(c, monkeypatch):
    tid = _chat(c, "About apple")["thread_id"]
    n = _counts(c)
    real = c.brain.respond

    def respond(kw, q):
        if q == "tool: banana" and tf.after_tool(kw):
            raise RuntimeError("the model failed mid-turn")
        return real(kw, q)
    monkeypatch.setattr(c.brain, "respond", respond)
    with pytest.raises(RuntimeError):
        c.client.post("/chat", json={"message": "tool: banana", "thread_id": tid}, headers=_h())
    assert _counts(c) == n and [m["text"] for m in _messages(c, tid)] == ["About apple", "Answer to About apple"]


# ---- D4: the team card -------------------------------------------------------------------------------------------------------

class CardFpl(Fpl):
    """The recorded transport + the team-card fixtures: the 6 Nov bootstrap (Palmer flagged by the test) and fixtures/?future=1."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.card_boot = json.loads((FIX / "bootstrap.json").read_text(encoding="utf-8"))
        for e in self.card_boot["elements"]:
            if e["id"] == 154:
                e.update(status="d", chance_of_playing_next_round=75, news="Knock - 75% chance of playing", news_added="2026-11-05T20:30:09.025008Z")
        self.fixtures = json.loads((FIX / "fixtures_future.json").read_text(encoding="utf-8"))
        self.delay = 0.0

    def __call__(self, url):
        path = url.split("/api/", 1)[1]
        if self.delay:
            time.sleep(self.delay)
        if self.status is not None:
            self.asked.append(path)
            return self.status, None
        if path == "bootstrap-static/":
            self.asked.append(path)
            return 200, self.card_boot
        if path == "fixtures/?future=1":
            self.asked.append(path)
            return 200, self.fixtures
        return super().__call__(url)


@pytest.fixture
def card(api, monkeypatch):
    """The recorded team imported (at NOW, GW10 next), then the clock moved past GW10's deadline for the card; predictions
    stubbed to one 'ours' row (Haaland)."""
    import team_card
    r = _post(api, "/me/teams", json={"fpl_team_id": TID, "label": "Main"})
    assert r.status_code == 200, r.text
    fpl = CardFpl()
    monkeypatch.setattr(fpl_import, "_http_get", fpl)
    monkeypatch.setattr(fpl_import, "clock", lambda: CARD_NOW)
    monkeypatch.setattr(team_card, "_pool", lambda next_gw: ({411: 7.2} if next_gw == 11 else None, datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)))
    fpl_import._reset()
    api.card_fpl = fpl
    yield api


def _card(api, sub=T1, tid=TID):
    return _get(api, f"/me/teams/{tid}/card", sub=sub)


def test_d4_the_card_carries_the_squad_the_fixtures_the_flags_the_chips_and_the_predictions(card):
    r = _card(card)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"team", "version_id", "squad_as_of_gw", "squad_updated_at", "formation", "bank", "free_transfers", "team_value",
                         "next_gw", "next_deadline", "predictions_gw", "predictions_updated_at", "chips", "players", "fpl_live", "fetched_at"}
    assert body["team"] == {"fpl_team_id": TID, "name": "Main", "entry_name": body["team"]["entry_name"], "manager_name": body["team"]["manager_name"]}
    assert body["team"]["entry_name"] and body["team"]["manager_name"]
    assert (body["next_gw"], body["next_deadline"]) == (11, "2026-11-21T11:00:00Z")
    assert body["squad_as_of_gw"] == 9 and body["formation"] == "3-4-3" and body["bank"] == 2.3
    assert isinstance(body["free_transfers"], int) and body["fpl_live"] is True
    assert (body["predictions_gw"], body["predictions_updated_at"]) == (11, "2026-11-06T09:00:00.000Z")
    players = body["players"]
    assert len(players) == 15 and sorted(p["slot"] for p in players) == list(range(1, 16))
    assert all(set(p) == _player_keys() for p in players)
    by = {p["id"]: p for p in players}
    assert by[496]["slot"] == 1 and by[496]["position"] == "GK" and by[411]["slot"] == 10 and by[305]["slot"] == 15
    assert (by[411]["role"], by[166]["role"], by[496]["role"]) == ("C", "VC", None)
    assert by[411]["next"] == {"opp": "FUL", "home": True, "n": 1} and by[1]["next"] == {"opp": "NEW", "home": False, "n": 1}
    assert by[411]["pred"] == {"points": 7.2, "source": "ours"} and by[496]["pred"] == {"points": 5.0, "source": "fpl_est"}
    assert by[154]["flag"] == {"chance": 75, "news": "Knock - 75% chance of playing", "news_date": "2026-11-05"} and by[411]["flag"] is None
    assert (by[411]["short_name"], by[411]["full_name"], by[411]["club"], by[411]["price"], by[411]["form"]) == ("Haaland", "Erling Haaland", "MCI", 15.8, 7.2)
    assert body["team_value"] == round(sum(p["price"] for p in players), 1)
    assert body["chips"]["half"] == {"from": 1, "to": 19} and (body["chips"]["used"], body["chips"]["left"]) == (4, 0)
    assert [(ch["code"], ch["used_gw"]) for ch in body["chips"]["items"]] == [("WC", 9), ("FH", 3), ("BB", 2), ("TC", 7)]
    assert all(set(p["next"]) == {"opp", "home", "n"} for p in players)


def test_d4_the_fpl_calls_are_cached_per_process_behind_one_lock(card):
    fpl = card.card_fpl
    assert _card(card).status_code == 200
    asked = list(fpl.asked)
    assert asked.count("bootstrap-static/") == 1 and asked.count("fixtures/?future=1") == 1 and asked.count(f"entry/{TID}/history/") == 1
    assert _card(card).status_code == 200 and fpl.asked == asked                       # warm: no request at all
    fpl_import._reset()
    fpl.delay = 0.15
    out = []
    ts = [threading.Thread(target=lambda: out.append(fpl_import.bootstrap())) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert fpl.asked.count("bootstrap-static/") == 2 and len(out) == 3                 # the three concurrent calls: ONE fetch


def test_d4_when_fpl_fails_the_last_cached_copy_is_served_then_the_saved_squad(card, monkeypatch):
    fpl = card.card_fpl
    assert _card(card).json()["fpl_live"] is True
    fpl.status = 503
    assert _card(card).json()["fpl_live"] is True                                       # within the TTL: no fetch, still live
    monkeypatch.setattr(fpl_import, "CACHE_TTL_S", 0)
    monkeypatch.setattr(fpl_import, "BOOTSTRAP_TTL_S", 0)
    body = _card(card).json()
    assert body["fpl_live"] is False and len(body["players"]) == 15                     # C8: the copy past its TTL
    assert body["players"][0]["next"] is not None and body["chips"]["used"] == 4
    fpl_import._reset()
    body = _card(card).json()
    assert body["fpl_live"] is False and len(body["players"]) == 15 and body["chips"] is None
    by = {p["id"]: p for p in body["players"]}
    assert by[411]["next"] is None and by[411]["short_name"] and by[411]["position"] == "FWD" and by[411]["slot"] == 10


def test_d4_one_database_connection_per_request_and_the_usual_refusals(card, monkeypatch):
    import team_card
    opened = []
    real = team_card._connect

    def counted():
        opened.append(1)
        return real()
    monkeypatch.setattr(team_card, "_connect", counted)
    assert _card(card).status_code == 200 and len(opened) == 1
    assert _card(card, sub=T2).status_code == 404                                       # not this user's team
    assert _card(card, tid=4242425).status_code == 404
    assert card.client.get(f"/me/teams/{TID}/card").status_code == 401


def test_d4_off_mode_has_no_card_route(app, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert app.client.get("/me/teams/1/card").status_code == 404
    assert app.client.post("/messages/abc/feedback", json={"score": "up"}).status_code == 404


# ---- D5: feedback ------------------------------------------------------------------------------------------------------------

def test_d5_feedback_is_stored_first_restored_on_reload_and_idempotent(w4):
    a = _chat(w4, "About apple")
    mid, tid = a["message_id"], a["thread_id"]
    r = w4.client.post(f"/messages/{mid}/feedback", json={"score": "up"}, headers=_h())
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"message_id", "feedback", "feedback_at", "langfuse"}
    assert (r.json()["feedback"], r.json()["langfuse"]) == ("up", "skipped")             # tracing off: no score
    assert _messages(w4, tid)[1]["feedback"] == "up"
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": "up"}, headers=_h()).json()["feedback"] == "up"
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": "down"}, headers=_h()).json()["feedback"] == "down"
    r = w4.client.post(f"/messages/{mid}/feedback", json={"score": None}, headers=_h())
    assert r.json()["feedback"] is None and _messages(w4, tid)[1]["feedback"] is None
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": "meh"}, headers=_h()).status_code == 422
    assert w4.client.post(f"/messages/{mid}/feedback", json={}, headers=_h()).status_code == 422
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": "up"}, headers=_h(B)).status_code == 404
    assert w4.client.post("/messages/no_such_message/feedback", json={"score": "up"}, headers=_h()).status_code == 404
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": "up"}).status_code == 401


def test_d5_the_langfuse_score_has_a_fixed_id_and_null_neutralises_it(w4, monkeypatch):
    import tracing
    sent = []

    class FakeClient:
        def create_score(self, **kw):
            sent.append(kw)

        def flush(self):
            pass
    monkeypatch.setattr(tracing, "switch_on", lambda: True)
    monkeypatch.setattr(tracing, "keys_present", lambda: True)
    monkeypatch.setattr(tracing, "_backend", lambda: (FakeClient(), None))
    mid = _chat(w4, "About pear")["message_id"]
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": "up"}, headers=_h()).json()["langfuse"] == "sent"
    assert w4.client.post(f"/messages/{mid}/feedback", json={"score": None}, headers=_h()).json()["langfuse"] == "sent"
    trace_id = tracing.trace_id_for(mid)
    assert [s["trace_id"] for s in sent] == [trace_id, trace_id]
    assert {s["score_id"] for s in sent} == {tracing.score_id(trace_id, "user_feedback")}  # one score, updated
    assert [(s["name"], s["value"], s["data_type"]) for s in sent] == [("user_feedback", "up", "CATEGORICAL"), ("user_feedback", "none", "CATEGORICAL")]
    assert sent[1]["comment"] == "cleared by the user"


# ---- D6: /threads ------------------------------------------------------------------------------------------------------------

def test_d6_threads_carry_team_name_and_updated_at_and_hide_empty_threads(c):
    tid = _chat(c, "About apple")["thread_id"]
    empty = c.client.post("/threads", headers=_h()).json()["thread_id"]
    rows = c.client.get("/threads", headers=_h()).json()
    assert [x["thread_id"] for x in rows] == [tid]                                      # the empty thread is not listed
    row = rows[0]
    assert set(row) == {"thread_id", "created_at", "last_active", "is_default", "title", "team_label", "fpl_team_id", "team_name", "updated_at",
                        "is_draft"}                                     # W11 (2026-11-12): the draft chat's DRAFT tag
    assert row["team_name"] is None and row["updated_at"] == row["last_active"] and row["is_draft"] is False
    _chat(c, "About banana", empty)
    assert [x["thread_id"] for x in c.client.get("/threads", headers=_h()).json()] == [empty, tid]


def test_d6_team_name_is_the_label_else_the_fpl_entry_name(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID})                                  # no label: the FPL name
    tid = api.client.post("/chat", json={"message": "About apple"}, headers=bearer(mint(T1))).json()["thread_id"]
    rows = {x["thread_id"]: x for x in _get(api, "/threads").json()}
    card = _get(api, "/me/teams").json()[0]
    assert rows[tid]["team_name"] == card["entry_name"] and rows[tid]["team_label"] == card["label"] == card["entry_name"]


# ---- C6: answers stored before W4 --------------------------------------------------------------------------------------------

def test_c6_a_pre_w4_thread_lists_its_answers_with_no_message_id(c):
    import agent_graph
    import threads
    tid = threads.new_thread_id()
    with c.conn.cursor() as cur:
        cur.execute("INSERT INTO chat_threads (thread_id, user_id) VALUES (%s, 9001)", (tid,))
    old = [{"role": "user", "content": "About plum"}, {"role": "assistant", "content": [{"type": "text", "text": "Plum answer."}]}]
    entry = {"q": 0, "user": "About plum", "user_at": "2026-11-01T10:00:00.000Z", "answer": "Plum answer.", "answer_at": "2026-11-01T10:00:12.000Z"}
    agent_graph.thread_graph().update_state(agent_graph._thread_config(tid), {"messages": old, "transcript": [entry]}, as_node="finalize")
    msgs = _messages(c, tid)
    assert msgs[1] == {"role": "assistant", "text": "Plum answer.", "at": "2026-11-01T10:00:12.000Z", "message_id": None,
                       "sources": [], "squad_preview": None, "squad_applied": None, "feedback": None}
    assert c.client.post("/messages/x/feedback", json={"score": "up"}, headers=_h()).status_code == 404
    a = _chat(c, "About quince", tid)                                                     # a W4 turn in the same thread
    assert _messages(c, tid)[3]["message_id"] == a["message_id"]
