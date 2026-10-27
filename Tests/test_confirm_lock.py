"""Prompt E (2026-10-27): the preview-ticket lock on every agent-reachable squad write, and the agent loop's guard
for a reply with neither text nor a tool call.

THE LOCK. set_my_squad(confirm=false) previews exactly as before and issues a ticket (squad_previews: random id, user,
the turn it was issued in, a fingerprint of the requested change, the active version it was previewed against, a
30-minute expiry). set_my_squad(confirm=true) needs preview_ticket: the ticket must exist for this user, come from an
EARLIER turn, carry the same fingerprint, match the still-active version, and be unused, uncancelled and unexpired;
otherwise NOTHING is written and the tool answers "No valid preview for this change (reason: ...)". The turn comes from
the agent loop's own channel (turn_context), never from the model's input. /reset cancels the user's tickets.

THE GUARD. A model response with no text block and no tool_use block (any stop_reason) ends the turn with the fixed
reply; the loop never sends a message with empty content (the HTTP 400 of the sonnet-5 gate, 27 Oct).

DB tests run on the local test database fpl_news_test (created if missing; the three squad tables are dropped and
rebuilt there, and dropped again at teardown); users 9001 / 9002 only. The real set_my_squad is exercised with its
market lookups stubbed (players_live rows, the current gameweek, the latest run, the summary): the lock, plan_change,
write_version and the ticket table are real. No network."""
import importlib
import json
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2                                            # noqa: E402
import db_write                                            # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_previews as sp                                # noqa: E402
import squad_store                                         # noqa: E402
import turn_context                                        # noqa: E402

TEST_DB = "fpl_news_test"
UTC = timezone.utc
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
# the seed: elements 1-15 (GK 1-2, DEF 3-7, MID 8-12, FWD 13-15), captain 13, vice 14, bench 2 / 7 / 12 / 15, £4.0m each
CHANGE_A = {"player_ids": list(range(1, 15)) + [16], "captain_id": 13, "vice_id": 14, "bench_order_ids": [2, 7, 12, 16]}
CHANGE_B = {"player_ids": list(range(1, 15)) + [17], "captain_id": 13, "vice_id": 14, "bench_order_ids": [2, 7, 12, 17]}


def _pos(e):
    return "GK" if e <= 2 else "DEF" if e <= 7 else "MID" if e <= 12 else "FWD"


def _legal_document():
    """The minimal legal document of Tests/test_default_user.py, built from squad_store's own helpers."""
    import pandas as pd
    rows = []
    el = 1
    for pos, n in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(n):
            rows.append({"element": el, "name": f"P{el}", "position": pos, "team": f"Club{el}", "purchase_price": 40,
                         "role": "start", "bench_order": None})
            el += 1
    for i, b in enumerate((rows[1], rows[6], rows[11], rows[14]), start=1):
        b["role"] = "bench"
        b["bench_order"] = i
    rows[12]["role"] = "CAPTAIN"
    rows[13]["role"] = "VICE"
    return squad_store.document(pd.DataFrame(rows), 400, 1, 0, "2026-27", {"kind": "test"})


# ---- fixtures ---------------------------------------------------------------------------------------------------

@pytest.fixture
def db(monkeypatch):
    """The test database with squad_versions (seeded: 9001 and 9002 each hold one active GW6 version) and
    squad_previews, both fresh; dropped again afterwards. FPL_USER_ID=9001 for the default user."""
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    monkeypatch.setenv("FPL_USER_ID", "9001")
    c = db_write.connect()

    def drop():
        with c.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS squad_previews")
            cur.execute("DROP TABLE IF EXISTS squad_scores")
            cur.execute("DROP TABLE IF EXISTS squad_versions CASCADE")
        c.commit()
    try:
        drop()
        squad_store.ensure_schema(c)
        sp.ensure_schema(c)
        doc = _legal_document()
        with c.cursor() as cur:
            for uid in (9001, 9002):
                cur.execute("INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, supersedes, note) "
                            "VALUES (%s, %s, %s, %s, TRUE, NULL, %s)", (uid, "2026-27", 6, json.dumps(doc), "confirm lock test seed"))
        c.commit()
        yield c
    finally:
        try:
            c.rollback()
            drop()
        finally:
            c.close()


@pytest.fixture
def tool(monkeypatch, db):
    """The REAL model_tools.set_my_squad with its market lookups stubbed; returns the function."""
    def live_rows(sql, params=()):
        involved = list(params[0]) if params else []
        return [{"element": e, "name": f"P{e}", "position": _pos(e), "team": f"Club{e}", "price_tenths": 40,
                 "updated_at": datetime(2026, 10, 25, 14, 0, tzinfo=UTC)} for e in involved]
    monkeypatch.setattr(mt, "_q", live_rows)
    monkeypatch.setattr(mt, "_current_gw", lambda: 9)
    monkeypatch.setattr(mt, "_latest_run", lambda *a, **k: None)
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {})
    monkeypatch.setattr(mt, "_transfer_row_meta", lambda row, meta: row)
    monkeypatch.setattr(squad_store, "summary", lambda *a, **k: {"stub": True})
    turn_context.end()
    yield mt.set_my_squad
    turn_context.end()


def _versions(c, uid=9001):
    with c.cursor() as cur:
        cur.execute("SELECT count(*), max(version_id) FILTER (WHERE is_active) FROM squad_versions WHERE user_id = %s", (uid,))
        n, active = cur.fetchone()
    return n, active


def _ticket_row(c, tid):
    with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM squad_previews WHERE id = %s", (tid,))
        r = cur.fetchone()
    return dict(r) if r else None


def _turn(n):
    """Begin turn n of a conversation: distinct ids, strictly later start times."""
    return turn_context.begin(turn_id=f"turn{n:02d}", started_at=T0 + timedelta(minutes=n))


# ---- the pure parts ---------------------------------------------------------------------------------------------

def test_fingerprint_is_canonical_over_the_change_and_nothing_else():
    a = sp.fingerprint([3, 1, 2] + list(range(4, 16)), 13, 14, [2, 7, 12, 15], 9)
    b = sp.fingerprint(list(range(1, 16)), 13, 14, [2, 7, 12, 15], 9)
    assert a == b and re.fullmatch(r"[0-9a-f]{64}", a)                 # the fifteen is a set
    assert sp.fingerprint(list(range(1, 16)), 13, 14, [7, 2, 12, 15], 9) != a        # bench ORDER is the change
    assert sp.fingerprint(list(range(1, 16)), 14, 13, [2, 7, 12, 15], 9) != a        # captain / vice
    assert sp.fingerprint(list(range(1, 16)), 13, 14, [2, 7, 12, 15], 10) != a       # gameweek
    assert sp.fingerprint(list(range(1, 16)), 13, 14, [2, 7, 12, 15], 9, note="x") == a    # a note is not the change


def test_the_refusal_names_the_reason_and_the_ticket_sentence_names_the_id():
    for r in sp.REASONS:
        assert sp.refusal(r) == f"No valid preview for this change (reason: {r}). Show the user a preview first."
    assert sp.REASONS == ("missing", "same_turn", "different_change", "squad_changed", "used", "cancelled", "expired")
    s = sp.ticket_sentence("abc")
    assert s == ("Preview ticket abc. To apply it after the user says yes in their next message, call this tool again "
                 "with the same changes, confirm=true and preview_ticket=abc.")


def test_turn_context_is_the_loops_channel_not_the_models():
    turn_context.end()
    assert turn_context.current() is None
    t = turn_context.begin()
    assert re.fullmatch(r"[0-9a-f]{32}", t["turn_id"]) and t["started_at"].tzinfo is not None
    assert turn_context.current() == t
    u = turn_context.begin(turn_id="abc", started_at=T0)
    assert turn_context.current() == {"turn_id": "abc", "started_at": T0}
    turn_context.end()
    assert turn_context.current() is None
    ad = turn_context.adhoc()                                            # a direct call outside the loop is its own turn
    assert ad["turn_id"] != u["turn_id"] and turn_context.current() is None


def test_confirm_without_a_ticket_is_refused_before_the_database_is_touched(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("read_active must not run")
    monkeypatch.setattr(squad_store, "read_active", boom)
    out = mt.set_my_squad(**CHANGE_A, confirm=True)
    assert out["refused"] and out["reason"] == "missing" and out["error"] == sp.refusal("missing")


def test_the_locked_tools_schema_gains_the_ticket_sentence_and_the_parameter():
    import agent
    t = next(t for t in agent.tools_schema if t["name"] == "set_my_squad")
    assert t["description"].endswith(
        " A preview issues a ticket: confirm=true needs preview_ticket from a preview shown in an EARLIER turn for the "
        "same change, else nothing is written.")
    assert "ALWAYS call with confirm=false first" in t["description"]          # the earlier wording stays
    props = t["input_schema"]["properties"]
    assert props["preview_ticket"] == {"type": "string", "description": "The preview ticket from the earlier confirm=false call for this same change (required with confirm=true)"}
    assert t["input_schema"]["required"] == ["player_ids", "captain_id", "vice_id", "bench_order_ids"]
    assert [n for n in agent.tools_schema if "preview_ticket" in n["input_schema"]["properties"]] == [t]


# ---- the lock on the real tool (test DB) ------------------------------------------------------------------------

def test_no_ticket_writes_nothing(tool, db):
    _turn(1)
    n0 = _versions(db)
    out = tool(**CHANGE_A, confirm=True)
    assert out["refused"] and out["reason"] == "missing"
    assert _versions(db) == n0


def test_a_preview_issues_a_ticket_and_the_same_turn_cannot_spend_it(tool, db):
    _turn(1)
    n0 = _versions(db)
    pv = tool(**CHANGE_A, confirm=False)
    assert pv["preview"] and not pv["committed"] and pv["preview_ticket"]
    assert pv["message"].endswith(sp.ticket_sentence(pv["preview_ticket"]))
    row = _ticket_row(db, pv["preview_ticket"])
    assert row["user_id"] == 9001 and row["turn_id"] == "turn01" and row["base_version_id"] == n0[1]
    assert row["expires_at"] - row["created_at"] == timedelta(minutes=30)
    assert row["used_at"] is None and row["cancelled_at"] is None
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    assert out["refused"] and out["reason"] == "same_turn"
    assert _versions(db) == n0 and _ticket_row(db, pv["preview_ticket"])["used_at"] is None


def test_a_different_change_is_refused(tool, db):
    _turn(1)
    n0 = _versions(db)
    pv = tool(**CHANGE_A, confirm=False)
    _turn(2)
    out = tool(**CHANGE_B, confirm=True, preview_ticket=pv["preview_ticket"])
    assert out["refused"] and out["reason"] == "different_change"
    assert _versions(db) == n0


def test_a_squad_changed_since_the_preview_is_refused(tool, db):
    _turn(1)
    pv = tool(**CHANGE_A, confirm=False)
    active = squad_store.read_active(9001)                                   # a non-agent write meanwhile
    squad_store.write_version(active, active["squad_json"], 6, "moved on", True, user_id=9001)
    n1 = _versions(db)
    _turn(2)
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    assert out["refused"] and out["reason"] == "squad_changed"
    assert _versions(db) == n1


def test_the_valid_two_turn_flow_writes_once_and_marks_the_ticket_used(tool, db):
    _turn(1)
    n0 = _versions(db)
    pv = tool(**CHANGE_A, confirm=False)
    assert _versions(db) == n0                                                # the preview wrote nothing
    _turn(2)
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    assert out["committed"] and not out["preview"] and out["change"]["transfers"][0]["in_id"] == 16
    n1 = _versions(db)
    assert n1[0] == n0[0] + 1 and n1[1] == out["version_id"] and out["supersedes"] == n0[1]
    row = _ticket_row(db, pv["preview_ticket"])
    assert row["used_at"] is not None and row["cancelled_at"] is None
    assert "preview_ticket" not in out                                        # a write issues no ticket
    prov = squad_store.read_active(9001)["squad_json"]["provenance"]          # the written record names its ticket and turn
    assert prov["preview_ticket"] == pv["preview_ticket"] and prov["turn_id"] == "turn02"
    assert prov["turn_started_at"] == (T0 + timedelta(minutes=2)).isoformat()
    assert row["turn_id"] == "turn01" and row["turn_started_at"] < T0 + timedelta(minutes=2)
    _turn(3)
    again = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])    # used twice
    assert again["refused"] and again["reason"] == "used"
    assert _versions(db) == n1


def test_an_expired_ticket_is_refused(tool, db, monkeypatch):
    _turn(1)
    n0 = _versions(db)
    pv = tool(**CHANGE_A, confirm=False)
    _turn(2)
    monkeypatch.setattr(sp, "clock", lambda: datetime.now(UTC) + timedelta(minutes=31))     # 31 min after the preview
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    assert out["refused"] and out["reason"] == "expired"
    assert _versions(db) == n0


def test_a_newer_preview_cancels_the_older_ticket(tool, db):
    _turn(1)
    n0 = _versions(db)
    a = tool(**CHANGE_A, confirm=False)
    _turn(2)
    b = tool(**CHANGE_B, confirm=False)
    assert _ticket_row(db, a["preview_ticket"])["cancelled_at"] is not None
    assert _ticket_row(db, b["preview_ticket"])["cancelled_at"] is None
    _turn(3)
    out = tool(**CHANGE_A, confirm=True, preview_ticket=a["preview_ticket"])
    assert out["refused"] and out["reason"] == "cancelled"
    assert _versions(db) == n0


def test_another_users_ticket_is_missing_for_this_user(tool, db):
    _turn(1)
    pv = tool(**CHANGE_A, confirm=False, user_id=9001)
    n0 = _versions(db, 9002)
    _turn(2)
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"], user_id=9002)
    assert out["refused"] and out["reason"] == "missing"
    assert _versions(db, 9002) == n0 and _ticket_row(db, pv["preview_ticket"])["used_at"] is None


def test_reset_cancels_the_users_tickets(tool, db, monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "test-key")
    import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    client = TestClient(main.app, headers={"x-api-key": "test-key"})
    _turn(1)
    n0 = _versions(db)
    pv = tool(**CHANGE_A, confirm=False)
    r = client.post("/reset")
    assert r.status_code == 200 and r.json() == {"status": "conversation reset", "preview_tickets_cancelled": 1}
    assert _ticket_row(db, pv["preview_ticket"])["cancelled_at"] is not None
    _turn(2)
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    assert out["refused"] and out["reason"] == "cancelled"
    assert _versions(db) == n0
    assert client.post("/reset").json()["preview_tickets_cancelled"] == 0


# ---- through the REAL agent loop (fake model, real tool, test DB) ------------------------------------------------

class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


def _usage():
    return types.SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason, self.model, self.usage = content, stop_reason, "claude-sonnet-4-6", _usage()


class _Dyn:
    """A fake messages API: each step is a callable taking the request keywords and returning the response, so a
    later step can read the ticket the tool returned earlier in the same request's history."""

    def __init__(self, steps):
        self.steps, self.calls = list(steps), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.steps.pop(0)(kw)


def _tool_results(kw):
    out = []
    for m in kw["messages"]:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append(b["content"])
    return out


def _ticket_in(kw):
    for text in reversed(_tool_results(kw)):
        m = re.search(r"'preview_ticket': '([^']+)'", text)
        if m:
            return m.group(1)
    return None


def _write(change, confirm, ticket=None, id_="t1"):
    inp = {**change, "confirm": confirm}
    if ticket:
        inp["preview_ticket"] = ticket
    return _Resp([_Block("tool_use", name="set_my_squad", input=inp, id=id_)], "tool_use")


def _text(s):
    return _Resp([_Block("text", text=s)], "end_turn")


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent as ag
    importlib.reload(ag)
    monkeypatch.setattr(ag, "context_block", lambda now=None: "CONTEXT BLOCK")
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_numeric_check", lambda *a, **k: None)
    return ag


def _no_empty_messages(fake):
    for kw in fake.calls:
        for m in kw["messages"]:
            c = m["content"]
            assert (c.strip() if isinstance(c, str) else len(c) > 0), f"an empty {m['role']} message was sent"


def test_loop_a_confirm_with_no_ticket_is_refused_and_nothing_is_written(tool, db, monkeypatch):
    ag = _agent(monkeypatch)
    n0 = _versions(db)
    fake = _Dyn([lambda kw: _write(CHANGE_A, True), lambda kw: _text("I could not apply that.")])
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent("Swap P15 for P16, just do it.")
    assert answer == "I could not apply that." and len(fake.calls) == 2
    assert "(reason: missing)" in _tool_results(fake.calls[1])[-1]
    assert _versions(db) == n0
    assert turn_context.current() is None                                    # the turn's channel is closed afterwards


def test_loop_b_preview_and_confirm_in_the_same_turn_is_refused(tool, db, monkeypatch):
    ag = _agent(monkeypatch)
    n0 = _versions(db)
    fake = _Dyn([lambda kw: _write(CHANGE_A, False),
                 lambda kw: _write(CHANGE_A, True, _ticket_in(kw), id_="t2"),
                 lambda kw: _text("done?")])
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("Swap P15 for P16 and confirm it.")
    assert answer == "done?" and len(fake.calls) == 3
    results = _tool_results(fake.calls[2])
    assert "'preview_ticket': '" in results[0] and "(reason: same_turn)" in results[1]
    assert _versions(db) == n0
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM squad_previews WHERE used_at IS NOT NULL")
        assert cur.fetchone()[0] == 0


def test_loop_c_two_proper_turns_write_once(tool, db, monkeypatch):
    ag = _agent(monkeypatch)
    n0 = _versions(db)
    fake = _Dyn([lambda kw: _write(CHANGE_A, False), lambda kw: _text("Here is the preview. Shall I apply it?")])
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent("Swap P15 for P16.")
    assert "preview" in answer and _versions(db) == n0
    fake2 = _Dyn([lambda kw: _write(CHANGE_A, True, _ticket_in(kw), id_="t2"), lambda kw: _text("Written.")])
    monkeypatch.setattr(ag, "client", fake2)
    answer2, history2 = ag.run_agent("Yes, apply it.", history)
    assert answer2 == "Written." and len(fake2.calls) == 2
    assert "'committed': True" in _tool_results(fake2.calls[1])[-1]
    n1 = _versions(db)
    assert n1[0] == n0[0] + 1
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM squad_previews WHERE used_at IS NOT NULL")
        assert cur.fetchone()[0] == 1


# ---- the loop guard ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("content, stop_reason", [
    ([_Block("thinking", thinking="", signature="sig")], "max_tokens"),          # the sonnet-5 gate's shape
    ([], "end_turn"),
    ([_Block("thinking", thinking="", signature="sig")], "tool_use"),            # stop_reason tool_use, no tool call
])
def test_a_reply_with_no_text_and_no_tool_call_ends_the_turn_with_the_fixed_reply(monkeypatch, capsys, content, stop_reason):
    ag = _agent(monkeypatch)
    fake = _Dyn([lambda kw: _Resp(content, stop_reason)])
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent("Which Tottenham players should I be looking at?")
    assert answer == "I couldn't finish that answer. Please ask again." == ag.GUARD_REPLY
    assert len(fake.calls) == 1                                               # no second request with an empty message
    _no_empty_messages(fake)
    assert history[-1] == {"role": "assistant", "content": [{"type": "text", "text": ag.GUARD_REPLY}]}
    assert ag.LAST_TURN["guard"] == {"stop_reason": stop_reason, "block_types": [b.type for b in content]}
    assert ag.LAST_TURN["turn_id"] and ag.LAST_TURN["calls"] == 1
    out = capsys.readouterr().out
    assert f"[loop guard: no text and no tool_use (stop_reason={stop_reason}); turn {ag.LAST_TURN['turn_id']}" in out


def test_the_v5_fixture_is_v3_plus_the_locked_tools_change_and_nothing_else():
    """Part 3's proof, pinned: the request payloads of commit E equal v3's except set_my_squad's ticket sentence and
    its preview_ticket property (eval/payload_fixture.py; the proof itself re-captured every call on the code)."""
    fx = REPO / "Tests" / "fixtures"
    v3 = json.loads((fx / "agent_payloads_v3.json").read_text(encoding="utf-8"))
    v5 = json.loads((fx / "agent_payloads_v5.json").read_text(encoding="utf-8"))
    assert v5["n_core"] == v3["n_core"] == 109 and v5["frozen_now"] == v3["frozen_now"] and v5["context_text"] == v3["context_text"]
    assert v5["shared"]["system"] == v3["shared"]["system"] and v5["shared"]["model"] == v3["shared"]["model"] == "claude-sonnet-4-6"
    assert v5["shared"]["max_tokens"] == v3["shared"]["max_tokens"] == 1024 and sorted(v5["shared"]) == sorted(v3["shared"])
    assert [c["messages"] for c in v5["first_calls"]] == [c["messages"] for c in v3["first_calls"]]
    assert v5["tool_turn"] == v3["tool_turn"]
    t5 = {t["name"]: t for t in v5["shared"]["tools"]}
    t3 = {t["name"]: t for t in v3["shared"]["tools"]}
    assert list(t5) == list(t3)
    for name in t3:
        if name != "set_my_squad":
            assert t5[name] == t3[name], name
    a, b = t5["set_my_squad"], t3["set_my_squad"]
    assert a["description"] == b["description"] + (" A preview issues a ticket: confirm=true needs preview_ticket from a preview "
                                                   "shown in an EARLIER turn for the same change, else nothing is written.")
    assert set(a["input_schema"]["properties"]) - set(b["input_schema"]["properties"]) == {"preview_ticket"}
    assert {k: v for k, v in a["input_schema"]["properties"].items() if k != "preview_ticket"} == b["input_schema"]["properties"]
    assert a["input_schema"]["required"] == b["input_schema"]["required"]


def test_the_guard_leaves_a_normal_turn_and_a_tool_turn_alone(monkeypatch):
    ag = _agent(monkeypatch)
    monkeypatch.setitem(ag.available_functions, "get_picks", lambda **kw: {"captain": "X"})
    fake = _Dyn([lambda kw: _Resp([_Block("tool_use", name="get_picks", input={}, id="t1")], "tool_use"),
                 lambda kw: _text("Captain X.")])
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent("who should I captain?")
    assert answer == "Captain X." and len(fake.calls) == 2 and "guard" not in ag.LAST_TURN
    _no_empty_messages(fake)
