"""The agent loop's turn channel (Prompt E, 2026-10-27).

One turn = one incoming user message: one /chat request, one agent.run_agent call. The loop opens the turn before its
first API call (begin) and closes it when the reply is returned (end, in a finally); a tool that needs to know WHICH
turn it runs in reads current(). The model never supplies this: it is not a tool parameter, and nothing in a tool's
input can set it. That is the point of the channel -- the preview-ticket lock (squad_previews) refuses a squad write
whose ticket was issued in the same turn, and the turn it compares against must come from the loop, not from the
model. Outside the loop (a script or a test calling a tool directly) there is no current turn: adhoc() gives such a call
a turn of its own, so a preview and a confirm from two separate direct calls are two turns, as two /chat requests are.
Process-global, like main.py's conversation history (one conversation per process)."""
import uuid
from datetime import datetime, timezone

_CURRENT = {}


def clock():
    return datetime.now(timezone.utc)


def begin(turn_id=None, started_at=None):
    """Open a turn (closing any earlier one). Returns {"turn_id", "started_at"}."""
    _CURRENT.clear()
    _CURRENT.update(turn_id=turn_id or uuid.uuid4().hex, started_at=started_at or clock())
    return dict(_CURRENT)


def current():
    """The open turn as a dict copy, or None when no turn is open."""
    return dict(_CURRENT) if _CURRENT else None


def end():
    _CURRENT.clear()


def adhoc():
    """A turn for one direct call outside the loop; never stored."""
    return {"turn_id": uuid.uuid4().hex, "started_at": clock()}
