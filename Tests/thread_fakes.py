"""Test helpers for Prompt B (per-user threads): a scripted fake Anthropic client ("the brain"), the stubs a /chat turn
needs offline, and the test database's seed. Shared by Tests/test_threads.py (in process) and Tests/thread_app.py (the
app in a real process for the restart / concurrency / no-shared-memory tests). Not a test module.

The brain answers from the request alone, so any number of processes and threads can share one script:
- the turn's question is the user message whose first block is the clock line (only the question carries it);
- "Make Mbeumo my captain." -> set_my_squad(CHANGE_A, confirm=False), then "Here is the preview. Shall I apply it?";
- "Yes, do it." -> set_my_squad(CHANGE_A, confirm=True, preview_ticket=<the ticket in this request's tool results, or the
  brain's forced ticket>), then "Written." / "Not written.";
- a question starting "tool:" -> get_my_xi (stubbed: it reports the thread and user the turn channel names), then a reply;
- anything else -> "Answer to <question>."
Replies carry no digit and no player name, so the fact check never sends back."""
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import payload_fixture as pf                                   # noqa: E402

TEST_DB = "fpl_threads_test"
FROZEN = datetime(2026, 10, 25, 14, 30, tzinfo=timezone.utc)
CHANGE_A = {"player_ids": list(range(1, 15)) + [16], "captain_id": 13, "vice_id": 14, "bench_order_ids": [2, 7, 12, 16]}
PREVIEW_Q, YES_Q = "Make Mbeumo my captain.", "Yes, do it."


def _blocks(m):
    c = m.get("content")
    return [] if isinstance(c, str) else [pf._block_to_dict(b) for b in c]


def question_of(kw):
    """The turn's question: the user message whose first text block is the clock line."""
    for m in kw["messages"]:
        bl = _blocks(m)
        if m["role"] == "user" and len(bl) >= 2 and bl[0].get("type") == "text" and bl[0].get("text", "").startswith("- Now:"):
            return bl[1]["text"]
    return None


def after_tool(kw):
    """The last message is this turn's tool results (the model's second call of the turn)."""
    bl = _blocks(kw["messages"][-1])
    return kw["messages"][-1]["role"] == "user" and bool(bl) and bl[0].get("type") == "tool_result"


def last_tool_result(kw):
    return str(_blocks(kw["messages"][-1])[-1].get("content"))


def ticket_in(kw):
    for m in reversed(kw["messages"]):
        for b in reversed(_blocks(m)):
            if b.get("type") == "tool_result":
                found = re.search(r"'preview_ticket': '([^']+)'", str(b.get("content")))
                if found:
                    return found.group(1)
    return None


def text(s):
    return pf._Resp([pf._Block("text", text=s)], "end_turn")


def tool_use(name, inp, id_):
    return pf._Resp([pf._Block("tool_use", name=name, input=inp, id=id_)], "tool_use")


class Brain:
    """The fake messages API (agent.client = Brain(); its .messages is itself). Thread-safe; every request's raw json
    (and its question) is kept in .log and, when log_path is given, appended to that JSONL file."""

    def __init__(self, log_path=None, forced_ticket=None, delay=0.0):
        self.messages, self.log, self.log_path = self, [], log_path
        self.forced_ticket, self.delay = forced_ticket, delay
        self.lock = threading.Lock()

    @property
    def calls(self):
        return len(self.log)

    def create(self, **kw):
        raw = json.dumps(kw, default=pf._block_to_dict, ensure_ascii=False)
        q = question_of(kw)
        with self.lock:
            self.log.append({"question": q, "raw": raw})
            if self.log_path:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"question": q, "raw": raw}, ensure_ascii=False) + "\n")
        if self.delay:
            time.sleep(self.delay)
        return self.respond(kw, q or "")

    def respond(self, kw, q):
        if not after_tool(kw):
            if q == PREVIEW_Q:
                return tool_use("set_my_squad", {**CHANGE_A, "confirm": False}, "t_preview")
            if q == YES_Q:
                inp = {**CHANGE_A, "confirm": True}
                ticket = self.forced_ticket or ticket_in(kw)
                if ticket:
                    inp["preview_ticket"] = ticket
                return tool_use("set_my_squad", inp, "t_confirm")
            if q.startswith("tool:"):
                return tool_use("get_my_xi", {}, "t_xi")
            return text(f"Answer to {q}")
        result = last_tool_result(kw)
        if "'committed': True" in result:
            return text("Written.")
        if "'refused': True" in result:
            return text("Not written.")
        if "PREVIEW ONLY" in result:
            return text("Here is the preview. Shall I apply it?")
        return text(f"Answer to {q}")


# ---- the stubs a /chat turn needs offline -----------------------------------------------------------------------------

def _pos(e):
    return "GK" if e <= 2 else "DEF" if e <= 7 else "MID" if e <= 12 else "FWD"


def stub_agent(agent, brain, setattr_=setattr):
    """agent with the brain as its client, the context block pinned, the clock frozen, the logs stubbed, get_my_xi
    reporting the turn channel; the REAL set_my_squad with its market lookups stubbed (test_confirm_lock's stubs)."""
    import fact_check
    import model_tools as mt
    import now_context
    import squad_store
    import threads
    import turn_context
    import config_roles
    setattr_(agent, "client", brain)
    setattr_(agent, "context_block", lambda now=None: "CONTEXT BLOCK")
    setattr_(now_context, "clock", lambda: FROZEN)
    setattr_(agent, "record_chat_usage", lambda *a, **k: None)
    setattr_(agent, "record_citation_check", lambda *a, **k: None)
    setattr_(agent, "record_numeric_check", lambda *a, **k: None)
    setattr_(fact_check, "record", lambda *a, **k: None)

    def xi(**kw):
        t = turn_context.current() or {}
        return {"thread_seen": t.get("thread_id"), "user_seen": config_roles.DEFAULT_USER_ID()}
    agent.available_functions["get_my_xi"] = xi

    def live_rows(sql, params=()):
        involved = list(params[0]) if params else []
        return [{"element": e, "name": f"P{e}", "position": _pos(e), "team": f"Club{e}", "price_tenths": 40,
                 "updated_at": datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)} for e in involved]
    setattr_(mt, "_q", live_rows)
    setattr_(mt, "_current_gw", lambda: 9)
    setattr_(mt, "_latest_run", lambda *a, **k: None)
    setattr_(mt, "_player_meta", lambda ids: {})
    setattr_(mt, "_transfer_row_meta", lambda row, meta: row)
    setattr_(squad_store, "summary", lambda *a, **k: {"stub": True})


# ---- the test database ------------------------------------------------------------------------------------------------

def legal_document():
    """test_confirm_lock's seed squad: elements 1-15, captain 13, vice 14, bench 2 / 7 / 12 / 15."""
    import pandas as pd
    import squad_store
    rows, el = [], 1
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


def reseed(conn):
    """Fresh squad tables (9001 and 9002 each one active GW6 version), empty ticket / thread / checkpoint tables."""
    import squad_previews as sp
    import squad_store
    import threads
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS squad_previews")
        cur.execute("DROP TABLE IF EXISTS squad_scores")
        cur.execute("DROP TABLE IF EXISTS squad_versions CASCADE")
    conn.commit()
    squad_store.ensure_schema(conn)
    sp.ensure_schema(conn)
    threads.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chat_threads")
        for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            cur.execute(f"DELETE FROM {t}")
        doc = legal_document()
        for uid in (9001, 9002):
            cur.execute("INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, supersedes, note) "
                        "VALUES (%s, %s, %s, %s, TRUE, NULL, %s)", (uid, "2026-27", 6, json.dumps(doc), "threads test seed"))
    conn.commit()
