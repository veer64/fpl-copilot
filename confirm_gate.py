"""Prompt X1 (13 Nov 2026): a squad or draft change is saved ONLY by the user's explicit yes to THAT preview -- decided by
code, never by the model.

WHAT HAPPENED. On 13 Nov the owner answered two draft previews (Doku -> Enzo Fernández at 17:45Z, Haaland -> Isak at
17:49Z) with "No" (the No button sends "No"); both times the model replied "Confirmed!" / "Got it -- confirming the swap
now", called set_my_squad(confirm=true) with the preview's ticket, and the draft was written. The lock (squad_previews)
checked the ticket -- earlier turn, same user and thread, same change, still open -- but never the user's answer.

THE RULE NOW.
- A preview's ticket keeps the change it showed (squad_previews.change_args). The user has at most one open ticket: the
  latest open preview (a new preview cancels the older ones).
- The Yes / No buttons (POST /me/preview/answer, answer_button) name the preview by its message id; no model is involved:
  Yes commits THAT ticket (if it is still the open one), No cancels it and the reply is "No change made." ($0).
- A typed message in a thread whose open ticket is there (answer_turn, called by agent.run_agent before any model call):
    yes      (a clear yes, the whole message: "yes", "yes please", "go ahead", "do it", "confirm", "save it", ...) -> the
             ticket is committed by code, the reply says what was saved ($0);
    no       (a no / negation / cancel / don't / keep my ... and nothing else) -> cancelled, "No change made." ($0);
    no_more  (a negation plus more, e.g. "no, bring in Salah instead") -> cancelled, then the turn goes to the model as
             usual (it can preview something new; it can never commit);
    ask      (anything else: "hmm", "maybe", "what about Salah instead?") -> nothing written, the ticket stays open, the
             reply is "Shall I make this change? Yes or No" ($0).
- The commit runs the SAME set_my_squad (team or draft) with confirm=true under a turn whose "consent" is that ticket;
  squad_previews.consume refuses any write without it (reason needs_yes) -- so a model's confirm=true never writes, and
  a ticket commits at most once (consume marks it used in the write's transaction).
- With no open ticket in the thread, nothing here runs and the turn is exactly what it was (payload v5).
A database failure here is printed and the turn goes to the model: safe, because the model cannot commit."""
import json
import re
import sys
import unicodedata
import uuid

NO_CHANGE_REPLY = "No change made."
ASK_REPLY = "Shall I make this change? Yes or No"
GONE_REPLY = "Nothing was saved: that preview is no longer open. Ask me for the change again and I'll show you a new preview."
ALREADY_REPLY = "That change is already saved."
ARG_KEYS = ("player_ids", "captain_id", "vice_id", "bench_order_ids", "gw", "note", "proposal_id")

# ---- the words ------------------------------------------------------------------------------------------------------------
# a negation anywhere in the message means it is not a yes (spec: "anything with a no / negation / cancel / don't / keep my")
NEG_WORDS = frozenset({"no", "nope", "nah", "naw", "nay", "n", "not", "dont", "didnt", "doesnt", "wont", "cant", "cannot",
                       "shouldnt", "wouldnt", "isnt", "arent", "never", "cancel", "cancelled", "canceled", "stop", "undo",
                       "decline", "declined", "reject", "rejected", "nevermind", "negative"})
NEG_PHRASES = (("do", "not"), ("keep", "my"), ("keep", "the"), ("keep", "it", "as"), ("leave", "it"), ("leave", "my"),
               ("never", "mind"), ("changed", "my", "mind"), ("rather", "not"), ("hold", "off"), ("no", "change"))
# a "pure" no: once the filler is gone, nothing but these words is left
NO_ONLY = NEG_WORDS | frozenset({"thanks", "thank", "you", "it", "that", "this", "change", "changes", "changed", "keep",
                                 "keeping", "my", "team", "squad", "draft", "side", "as", "is", "leave", "do", "the",
                                 "current", "same", "just", "for", "now", "mind", "i", "id", "im", "ive", "rather",
                                 "hold", "off", "bother", "make", "any", "swap", "swaps", "transfer", "transfers", "one",
                                 "way", "to", "go", "anything", "nothing", "want", "need", "like", "wanna"})
# a clear yes: the whole message is these phrases (and filler)
YES_PHRASES = tuple(tuple(p.split()) for p in (
    "yes", "yeah", "yea", "yep", "yup", "ya", "yes yes", "y", "ok", "okay", "k", "sure", "confirm", "confirmed", "go ahead",
    "do it", "save it", "save", "apply it", "apply", "make it", "make the change", "make that change", "go for it",
    "proceed", "please do", "lets do it", "lets go", "do that", "go on", "absolutely", "definitely", "correct",
    "approve", "approved", "agreed", "sounds good", "looks good", "yes that", "that one", "make the swap", "do the swap"))
FILLER = frozenset({"please", "pls", "plz", "thanks", "thank", "you", "ty", "cheers", "mate", "now", "then", "and"})


def words(text):
    """The message as lower-case ASCII words (accents folded, apostrophes dropped: "don't" -> "dont")."""
    t = unicodedata.normalize("NFKD", str(text or "")).replace("’", "'").replace("‘", "'")
    t = t.encode("ascii", "ignore").decode("ascii").lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", t).split()


def _has(ws, phrase):
    n = len(phrase)
    return any(tuple(ws[i:i + n]) == phrase for i in range(len(ws) - n + 1))


def _segments_into(ws, phrases):
    """True when ws (filler already removed) is a sequence of the phrases, nothing else."""
    if not ws:
        return False
    ok = [True] + [False] * len(ws)
    for i in range(len(ws)):
        if ok[i]:
            for p in phrases:
                if tuple(ws[i:i + len(p)]) == p:
                    ok[i + len(p)] = True
    return ok[-1]


def classify(text):
    """'yes' | 'no' | 'no_more' | 'ask' (see the module docstring). Pure."""
    ws = words(text)
    if any(w in NEG_WORDS for w in ws) or any(_has(ws, p) for p in NEG_PHRASES):
        rest = [w for w in ws if w not in FILLER]
        return "no" if all(w in NO_ONLY for w in rest) else "no_more"
    core = [w for w in ws if w not in FILLER]
    return "yes" if _segments_into(core, YES_PHRASES) else "ask"


# ---- the replies (code-built) ---------------------------------------------------------------------------------------------

def _m(x):
    return f"£{float(x):.1f}m"


def saved_reply(res):
    """The reply to a committed Yes, from the write's own result: where it was saved, each move, the money after."""
    ch = res.get("change") or {}
    draft = bool(res.get("draft"))
    out = [f"Done — saved to your {'draft' if draft else 'squad'}."]
    moves = [f"{t['out']} out, {t['in']} in" for t in ch.get("transfers") or [] if t.get("out") and t.get("in")]
    if moves:
        out.append("; ".join(moves) + ".")
    roles = [w for k, w in (("captain_changed", "captain"), ("vice_changed", "vice-captain"), ("bench_changed", "bench"))
             if ch.get(k)]
    if roles:
        out.append(f"The {', '.join(roles[:-1]) + ' and ' + roles[-1] if len(roles) > 1 else roles[0]} as previewed.")
    if draft and ch.get("value_after") is not None and ch.get("left_after") is not None:
        out.append(f"The draft now costs {_m(ch['value_after'])} ({_m(ch['left_after'])} left).")
    elif not draft and ch.get("bank_after") is not None:
        out.append(f"Bank after: {_m(ch['bank_after'])}.")
        if ch.get("hit_cost_points"):
            out.append(f"It costs a {int(ch['hit_cost_points'])}-point hit.")
    return " ".join(out)


WHY = {"squad_changed": "your {thing} changed after that preview", "expired": "that preview expired (previews last 30 minutes)",
       "used": "that preview was already saved", "cancelled": "that preview was replaced or cancelled"}


def refused_reply(res, draft):
    reason = res.get("reason") if isinstance(res, dict) else None
    if reason == "used":
        return ALREADY_REPLY
    why = WHY.get(reason, "that preview can no longer be applied").format(thing="draft" if draft else "squad")
    return f"Nothing was saved: {why}. Ask me for the change again and I'll show you a new preview."


# ---- the decisions --------------------------------------------------------------------------------------------------------

def _say(text):
    try:
        print(text)
    except UnicodeEncodeError:                           # a cp1252 console never breaks a turn (W11g G6)
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def _args(ticket):
    a = ticket.get("change_args")
    if isinstance(a, str):
        a = json.loads(a)
    return {k: a.get(k) for k in ARG_KEYS} if isinstance(a, dict) and a.get("player_ids") else None


def commit(ticket, turn_id, thread_id, draft):
    """Write THIS ticket's change through set_my_squad under a turn whose consent is the ticket. Opens the turn (the caller
    closes it). Returns (reply, squad_applied or None, outcome)."""
    import model_tools
    import turn_context
    import turn_extras
    args = _args(ticket)
    turn_context.begin(turn_id, thread_id=thread_id, draft=draft, consent=ticket["id"])
    if args is None:                                     # a ticket from before X1: it never stored its change
        return GONE_REPLY, None, "no_args"
    res = model_tools.set_my_squad(**args, user_id=int(ticket["user_id"]), confirm=True, preview_ticket=ticket["id"])
    if isinstance(res, dict) and res.get("committed") is True:
        applied = turn_extras.applied([("set_my_squad", {**args, "confirm": True}, res)])
        return saved_reply(res), applied, "committed"
    reason = (res or {}).get("reason") if isinstance(res, dict) else None
    return refused_reply(res, draft is not None), None, f"refused:{reason or str((res or {}).get('error'))[:80]}"


def answer_turn(user_message, messages, thread):
    """agent.run_agent's first step: (reply, messages) when the message answers the thread's open preview (yes / no /
    ask), else None -- the model runs. A no_more message cancels the ticket and returns None."""
    import config_roles
    import db_write
    import psycopg2
    import squad_previews
    import turn_context
    thread = thread or {}
    thread_id = thread.get("thread_id")
    try:
        user_id = int(thread["user_id"]) if thread.get("user_id") is not None else int(config_roles.DEFAULT_USER_ID())
        conn = db_write.connect()
        try:
            try:
                ticket = squad_previews.open_for_thread(conn, user_id, thread_id)
            except psycopg2.errors.UndefinedTable:      # no preview was ever issued on this database
                conn.rollback()
                return None
            if ticket is None:
                return None
            kind = classify(user_message)
            if kind in ("no", "no_more"):
                squad_previews.cancel_one(conn, user_id, ticket["id"])
        finally:
            conn.close()
    except Exception as e:                               # noqa: BLE001 -- the model runs; it cannot commit (needs_yes)
        _say(f"  [confirm gate not run: {type(e).__name__}: {str(e)[:200]}]")
        return None
    _say(f"  [confirm gate: thread {thread_id} ticket {ticket['id'][:6]}… answer {kind}]")
    if kind == "no_more":
        return None
    turn_id = thread.get("turn_id") or uuid.uuid4().hex
    draft = thread.get("draft")
    applied, outcome = None, kind
    if kind == "yes":
        reply, applied, outcome = commit(ticket, turn_id, thread_id, draft)
    else:
        turn_context.begin(turn_id, thread_id=thread_id, draft=draft)
        reply = NO_CHANGE_REPLY if kind == "no" else ASK_REPLY
    _say(f"  [confirm gate: {outcome}]")
    if messages is None:
        messages = []
    messages.append({"role": "user", "content": user_message})
    messages.append({"role": "assistant", "content": reply})
    turn_context.note(message_id=turn_id, sources=[], squad_preview=None, squad_applied=applied, scripted=True)
    return reply, messages


def answer_button(user_id, thread_id, message_id, answer, draft):
    """POST /me/preview/answer: the Yes / No button of the preview shown in message `message_id` (= the turn that issued
    its ticket). Run under the thread's turn lock by the caller. Returns (user_text, reply, squad_applied, outcome)."""
    import db_write
    import squad_previews
    import turn_context
    conn = db_write.connect()
    try:
        squad_previews.ensure_schema(conn)
        now = squad_previews.clock()
        rows = squad_previews.of_message(conn, user_id, thread_id, message_id)
        latest = squad_previews.open_for_thread(conn, user_id, thread_id, now)
        mine = next((r for r in rows if latest is not None and r["id"] == latest["id"]), None)   # THIS preview's, still open
        if answer == "no" and mine is not None:
            squad_previews.cancel_one(conn, user_id, mine["id"], now)
    finally:
        conn.close()
    turn_id = uuid.uuid4().hex
    try:
        if answer == "no":
            turn_context.begin(turn_id, thread_id=thread_id, draft=draft)
            return "No", NO_CHANGE_REPLY, None, "cancelled" if mine is not None else "no_open_ticket"
        if mine is None:
            turn_context.begin(turn_id, thread_id=thread_id, draft=draft)
            used = any(r.get("used_at") is not None for r in rows)
            return "Yes", ALREADY_REPLY if used else GONE_REPLY, None, "already_used" if used else "no_open_ticket"
        reply, applied, outcome = commit(mine, turn_id, thread_id, draft)
        return "Yes", reply, applied, outcome
    finally:
        turn_context.end()
