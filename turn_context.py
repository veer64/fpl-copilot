"""The agent loop's turn channel (Prompt E, 2026-10-27).

One turn = one incoming user message: one /chat request, one agent.run_agent call. The loop opens the turn before its
first API call (begin) and closes it when the reply is returned (end, in a finally); a tool that needs to know WHICH
turn it runs in reads current(). The model never supplies this: it is not a tool parameter, and nothing in a tool's
input can set it. That is the point of the channel -- the preview-ticket lock (squad_previews) refuses a squad write
whose ticket was issued in the same turn, and the turn it compares against must come from the loop, not from the
model. Outside the loop (a script or a test calling a tool directly) there is no current turn: adhoc() gives such a call
a turn of its own, so a preview and a confirm from two separate direct calls are two turns, as two /chat requests are.
Prompt B (2026-10-31): per request, not process-global -- a ContextVar, so concurrent /chat turns (FastAPI runs each
sync request in its own worker context; LangGraph runs the nodes in the caller's thread) never see each other's turn;
a stored thread's turn also names its thread (the preview tickets are bound to user + thread)."""
import contextvars
import uuid
from datetime import datetime, timezone

_CURRENT = contextvars.ContextVar("fpl_turn", default=None)
# Prompt W4 (2026-11-06): what the turn produced for the Chat page beside its text -- message_id, sources, squad_preview,
# squad_applied -- noted by the loop's reply steps (agent._finish and the fixed replies), read by agent_graph.run_thread_turn
# after the turn and by /chat for its response. Per request (a ContextVar), never process-global; end() keeps the record of
# the turn that just closed so the caller can read it after run_agent returned.
_RECORD = contextvars.ContextVar("fpl_turn_record", default=None)
_LAST = contextvars.ContextVar("fpl_turn_last", default=None)


def clock():
    return datetime.now(timezone.utc)


def begin(turn_id=None, started_at=None, thread_id=None, draft=None):
    """Open a turn (closing any earlier one in this context). Returns {"turn_id", "started_at"} (+ "thread_id" when the
    turn belongs to a stored thread; + "draft" -- {"user_id", "draft_key"} -- when it is the user's draft chat, Prompt W11:
    the squad tools then read and write the draft)."""
    turn = {"turn_id": turn_id or uuid.uuid4().hex, "started_at": started_at or clock()}
    if thread_id is not None:
        turn["thread_id"] = str(thread_id)
    if draft is not None:
        turn["draft"] = dict(draft)
    _CURRENT.set(turn)
    _RECORD.set({})
    _LAST.set(None)
    return dict(turn)


def note(**fields):
    """Record what the open turn produced for the Chat page (merged into the turn's record); a no-op outside a turn."""
    rec = _RECORD.get()
    if rec is not None:
        rec.update(fields)


def last():
    """The record of the turn that closed most recently in this context (a dict copy), or None."""
    rec = _LAST.get()
    return dict(rec) if rec else None


def current():
    """The open turn as a dict copy, or None when no turn is open."""
    turn = _CURRENT.get()
    return dict(turn) if turn else None


def end():
    _CURRENT.set(None)
    rec = _RECORD.get()
    _RECORD.set(None)
    _LAST.set(dict(rec) if rec else None)


def adhoc():
    """A turn for one direct call outside the loop; never stored."""
    return {"turn_id": uuid.uuid4().hex, "started_at": clock()}
