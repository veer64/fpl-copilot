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
# Prompt R3d (2026-11-16): the turn's own user message, so code can check the model's reading of the user's words (a transfer
# limit is applied only when the message names one). Kept apart from the turn dict, which callers compare whole.
_MESSAGE = contextvars.ContextVar("fpl_turn_user_message", default=None)
# Prompt F1 (2026-11-18): the user questions the request carries BEFORE this one (the user's own words earlier in the chat), and
# the names the turn holds unsettled -- {folded name: {"name", "ids", "candidates", "name_words", "team_words"}}, written by
# model_tools.resolve_player when a name the user wrote is ambiguous, read by the agent's guard and by set_my_squad.
_EARLIER = contextvars.ContextVar("fpl_turn_earlier_messages", default=())
_UNSETTLED = contextvars.ContextVar("fpl_turn_unsettled", default=None)
# Prompt F2 F (2026-11-18): the player ids the chat's tool results have given, handed by the agent to the ONE call it is about to
# run (set_my_squad checks its incoming players against them; None: no check -- outside the loop, or a chat with no lookup yet).
_KNOWN_IDS = contextvars.ContextVar("fpl_turn_known_ids", default=None)


def clock():
    return datetime.now(timezone.utc)


def begin(turn_id=None, started_at=None, thread_id=None, draft=None, consent=None, user_message=None, earlier_messages=None):
    """Open a turn (closing any earlier one in this context). Returns {"turn_id", "started_at"} (+ "thread_id" when the
    turn belongs to a stored thread; + "draft" -- {"user_id", "draft_key"} -- when it is the user's draft chat, Prompt W11:
    the squad tools then read and write the draft; + "consent" -- a preview ticket id -- Prompt X1: ONLY confirm_gate sets
    it, after the user's explicit yes to that preview; squad_previews.consume refuses a write without it)."""
    turn = {"turn_id": turn_id or uuid.uuid4().hex, "started_at": started_at or clock()}
    if thread_id is not None:
        turn["thread_id"] = str(thread_id)
    if draft is not None:
        turn["draft"] = dict(draft)
    if consent is not None:
        turn["consent"] = str(consent)
    _CURRENT.set(turn)
    _RECORD.set({})
    _LAST.set(None)
    _MESSAGE.set(None if user_message is None else str(user_message))
    _EARLIER.set(tuple(str(m) for m in (earlier_messages or ()) if m is not None))
    _UNSETTLED.set({})
    _KNOWN_IDS.set(None)
    return dict(turn)


def user_message():
    """The open turn's own user message (agent._begin_turn passes it), or None -- outside a turn, or a turn opened without it."""
    return _MESSAGE.get()


def earlier_messages():
    """Prompt F1: the user questions the request carries before the open turn's own (a tuple; empty outside a turn)."""
    return _EARLIER.get()


def unsettled():
    """Prompt F1: the names the open turn holds unsettled ({} outside a turn) -- a copy of the mapping."""
    held = _UNSETTLED.get()
    return dict(held) if held else {}


def hold(key, entry):
    """Prompt F1: hold a name unsettled for the rest of the open turn (a no-op outside a turn)."""
    held = _UNSETTLED.get()
    if held is not None:
        held[key] = entry


def settle(key):
    """Prompt F1: the user's own words settled the name -- it is no longer held."""
    held = _UNSETTLED.get()
    if held:
        held.pop(key, None)


def set_known_ids(ids):
    """Prompt F2 F: the ids the chat's tools have given, for the call about to run (None: no check)."""
    _KNOWN_IDS.set(None if ids is None else frozenset(int(i) for i in ids))


def known_ids():
    """Prompt F2 F: the ids handed to the running call, or None."""
    return _KNOWN_IDS.get()


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
    _MESSAGE.set(None)
    _EARLIER.set(())
    _UNSETTLED.set(None)
    _KNOWN_IDS.set(None)
    rec = _RECORD.get()
    _RECORD.set(None)
    _LAST.set(dict(rec) if rec else None)


def adhoc():
    """A turn for one direct call outside the loop; never stored."""
    return {"turn_id": uuid.uuid4().hex, "started_at": clock()}
