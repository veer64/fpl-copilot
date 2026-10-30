"""Langfuse tracing v1 (Prompt L, 2026-10-30): one Langfuse trace per agent turn, recorded BY HAND from the loop's own
request and response. Nothing here wraps, patches or proxies the Anthropic client, and no OpenTelemetry instrumentor is
installed: agent.py calls the functions below around the calls it already makes, and the request it sends is the same
object either way (Tests/test_agent_payload_equivalence.py, tracing ON and OFF, byte for byte).

USER DECISIONS (30 Oct): "Langfuse Cloud, not self-hosted." "Log user messages, behind a switch
(LANGFUSE_LOG_USER_TEXT=1 now; revisit before the frontend)."

Switches (environment, read at call time):
- LANGFUSE_ENABLED=1 turns tracing on; unset, 0 or anything else is OFF and the client is never built (zero calls).
- LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL (or LANGFUSE_HOST) must all be set, else OFF (logged once).
- LANGFUSE_LOG_USER_TEXT=1 puts the user's message in the trace input; anything else (unset included) puts
  "[redacted, <n> chars]" there instead.
- LANGFUSE_TRACING_ENVIRONMENT names the environment (dev / eval / production); the eval runner sets "eval".

The tree of one turn (trace id = Langfuse.create_trace_id(seed=turn_id), i.e. sha256(turn_id) as 32 hex characters):
  agent-turn (as_type agent; input = the user message per the switch, output = the reply as delivered; user = the
      turn's user, config_roles.DEFAULT_USER_ID(); metadata turn_id, user_id, loop_guard)
    llm_call (generation) per Anthropic call of the loop: model, max_tokens, usage (input, output, cache read, cache
        write -- the API's buckets are already exclusive), cost from pricing.cost_details (omitted, never 0, for a model
        pricing.py has no row for), stop_reason; input = the request's SHAPE only (message count, the last message's
        kind, tool count, system length) -- never the messages, so neither the user's text nor any tool output rides on it
    <tool name> (as_type tool) per tool call: args, output trimmed (search_news: ids, titles, dates, source -- never a
        chunk body; anything else over OUTPUT_MAX_CHARS as JSON is cut with "[truncated <n> chars]"), ERROR level when
        the tool returned {"error": ...}
    fact_check (span): the check's result; child fact_check_send_back (generation, metadata send_back=true) when the
        answer was sent back; plus a trace score "fact_check" = pass | sent_back_fixed | sent_back_flagged (| check_error
        when the checker itself failed). The loop-guard reply has no fact check, so no span and no score.

Failure contract: every function here catches its own exceptions -- a tracing failure never breaks, blocks or changes a
turn -- and the first failure is printed once per process ("[tracing ...]"), never once per call. The SDK sends in its
own background threads only; the client is built once (~1 s) by init() at agent import, never inside a turn. shutdown()
flushes with a short timeout at process end (the app's lifespan, the eval runner, an atexit hook); the SDK's own exit
hook is replaced by it so an unreachable host cannot hold the process. The SDK gets a PRIVATE OpenTelemetry
TracerProvider: the global one is never set, so no other library's spans can reach Langfuse through it."""
import atexit
import functools
import hashlib
import json
import os
import sys
import threading
import time

import pricing

ENABLED_ENV = "LANGFUSE_ENABLED"
LOG_USER_TEXT_ENV = "LANGFUSE_LOG_USER_TEXT"
ENVIRONMENT_ENV = "LANGFUSE_TRACING_ENVIRONMENT"
OUTPUT_MAX_CHARS = 8000                  # a tool output longer than this as JSON is cut (search_news is trimmed first)
SHUTDOWN_TIMEOUT_S = 3.0                 # the flush at process end never holds the process longer than this
TRACE_NAME = "agent-turn"
NEWS_RESULT_KEYS = ("id", "source", "headline", "url", "date", "date_words", "date_basis", "age", "about_requested_player",
                    "players")           # a search_news result as traced: everything but "text", the chunk body
SCORE_NAME = "fact_check"
SCORE_VALUES = {"clean": "pass", "fixed": "sent_back_fixed", "check_error": "check_error"}   # any other outcome was sent
                                         # back and delivered still flagged (still_wrong, tool_call_in_rewrite, no_text,
                                         # sendback_failed) -> "sent_back_flagged"

# What the latest turn's tracing did, for the process that ran it (the eval runner saves it per turn): enabled, trace_id,
# turn_id, user_id, generations, send_back_generations, tools, fact_check, score, loop_guard, tracing_ms, errors.
LAST_TURN = {}

_STATE = {"backend": None, "tried": False, "logged": False, "errors": 0, "turn": None, "atexit": False}


# ---- switches --------------------------------------------------------------------------------------------------------------

def switch_on():
    return os.environ.get(ENABLED_ENV, "").strip() == "1"


def keys_present():
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
                and (os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")))


def log_user_text():
    return os.environ.get(LOG_USER_TEXT_ENV, "").strip() == "1"


def user_input(message):
    """The trace input: the user's message when LANGFUSE_LOG_USER_TEXT=1, else its length only."""
    text = message if isinstance(message, str) else str(message)
    return text if log_user_text() else f"[redacted, {len(text)} chars]"


def trace_id_for(turn_id):
    """The trace id of a turn: the SDK's seed helper (sha256(seed), 16 bytes as hex), or the same digest computed here."""
    try:
        from langfuse import Langfuse
        return Langfuse.create_trace_id(seed=str(turn_id))
    except Exception:                                    # noqa: BLE001 -- the package may be missing: same algorithm
        return hashlib.sha256(str(turn_id).encode("utf-8")).hexdigest()[:32]


# ---- the client ------------------------------------------------------------------------------------------------------------

def _say_once(text):
    if not _STATE["logged"]:
        _STATE["logged"] = True
        print(f"  [tracing {text} -- logged once per process]")


def _fail(where, exc):
    _STATE["errors"] += 1
    _say_once(f"error in {where}: {type(exc).__name__}: {str(exc)[:200]}; the turn is unaffected")


def _client_kwargs(tracer_provider):
    return {"public_key": os.environ.get("LANGFUSE_PUBLIC_KEY"), "secret_key": os.environ.get("LANGFUSE_SECRET_KEY"),
            "base_url": os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST"),
            "environment": os.environ.get(ENVIRONMENT_ENV) or None, "tracer_provider": tracer_provider}


def _make_backend():
    """(client, propagate_attributes). The tests replace this with a fake."""
    from langfuse import Langfuse, propagate_attributes
    from opentelemetry.sdk.trace import TracerProvider
    client = Langfuse(**_client_kwargs(TracerProvider(shutdown_on_exit=False)))   # private: never the global provider
    return client, propagate_attributes


def _backend():
    if _STATE["backend"] is not None:
        return _STATE["backend"]
    if _STATE["tried"]:
        return None
    _STATE["tried"] = True
    try:
        _STATE["backend"] = _make_backend()
    except Exception as e:                               # noqa: BLE001 -- an import or constructor failure: tracing stays off
        _fail("building the client", e)
        return None
    if not _STATE["atexit"]:
        _STATE["atexit"] = True
        atexit.register(shutdown)
    return _STATE["backend"]


def init():
    """Build the client now (agent import) when tracing is on, so no turn ever pays for it. Never raises."""
    try:
        if switch_on() and keys_present():
            _backend()
    except Exception as e:                               # noqa: BLE001
        _fail("init", e)


def shutdown(timeout_s=None):
    """Flush and stop the client, waiting at most `timeout_s` (SHUTDOWN_TIMEOUT_S); later turns are not traced. The SDK's
    own exit hook is unregistered first, so an unreachable host cannot hold the process past the timeout."""
    backend = _STATE.get("backend")
    if backend is None:
        return
    _STATE["backend"] = None
    client = backend[0]
    try:
        res = getattr(client, "_resources", None)
        if res is not None and hasattr(res, "shutdown"):
            atexit.unregister(res.shutdown)
    except Exception:                                    # noqa: BLE001
        pass

    def run():
        try:
            client.shutdown()
        except Exception as e:                           # noqa: BLE001
            _fail("shutdown", e)
    try:
        th = threading.Thread(target=run, name="langfuse-shutdown", daemon=True)
        th.start()
        th.join(SHUTDOWN_TIMEOUT_S if timeout_s is None else timeout_s)
    except Exception as e:                               # noqa: BLE001
        _fail("shutdown", e)


def _reset():
    """Forget the client and the once-per-process log (tests only; it does not stop a running client)."""
    _STATE.update(backend=None, tried=False, logged=False, errors=0, turn=None)
    LAST_TURN.clear()


# ---- what goes into a trace ------------------------------------------------------------------------------------------------

def _dumps(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:                                    # noqa: BLE001
        return str(value)


def _news_without_bodies(result):
    out = {k: v for k, v in result.items() if k != "results"}
    out["results"] = [{k: r[k] for k in NEWS_RESULT_KEYS if k in r} if isinstance(r, dict) else "?"
                      for r in (result.get("results") or [])]
    return out


def trim_output(tool, result):
    """A tool's output as traced: search_news without chunk bodies; anything longer than OUTPUT_MAX_CHARS as JSON becomes
    that JSON cut at OUTPUT_MAX_CHARS plus "[truncated <n> chars]" (n = the characters cut); anything else unchanged."""
    if tool == "search_news" and isinstance(result, dict):
        result = _news_without_bodies(result)
    s = result if isinstance(result, str) else _dumps(result)
    if len(s) > OUTPUT_MAX_CHARS:
        return s[:OUTPUT_MAX_CHARS] + f"[truncated {len(s) - OUTPUT_MAX_CHARS} chars]"
    return result


def _block_type(b):
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", None)


def _request_shape(request):
    """The request without its content: how many messages, what the last one is, how many tools, how long the system."""
    msgs = request.get("messages") or []
    last = msgs[-1] if msgs else {}
    content = last.get("content") if isinstance(last, dict) else None
    blocks = content if isinstance(content, list) else []
    n_results = sum(1 for b in blocks if _block_type(b) == "tool_result")
    system = request.get("system")
    sys_chars = len(system) if isinstance(system, str) else sum(len(b.get("text", "")) for b in (system or []) if isinstance(b, dict))
    return {"messages": len(msgs), "last_message": f"tool results x{n_results}" if n_results else "user text",
            "tools": len(request.get("tools") or []), "system_chars": sys_chars}


def _model_parameters(request):
    out = {"max_tokens": request.get("max_tokens")}
    choice = request.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type"):
        out["tool_choice"] = str(choice["type"])
    return {k: v for k, v in out.items() if v is not None}


def _response_output(response):
    out = []
    for b in list(getattr(response, "content", None) or []):
        t = getattr(b, "type", None)
        if t == "text":
            text = getattr(b, "text", "") or ""
            out.append({"type": "text", "text": text if len(text) <= OUTPUT_MAX_CHARS
                        else text[:OUTPUT_MAX_CHARS] + f"[truncated {len(text) - OUTPUT_MAX_CHARS} chars]"})
        elif t == "tool_use":
            out.append({"type": "tool_use", "name": getattr(b, "name", None),
                        "input": trim_output("", getattr(b, "input", None))})
        elif t == "thinking":
            out.append({"type": "thinking", "chars": len(getattr(b, "thinking", "") or "")})
        else:
            out.append({"type": str(t)})
    return out


def _usage(response):
    """{input, output, cache_read_input_tokens, cache_creation_input_tokens} from the response, or None without usage."""
    u = getattr(response, "usage", None)
    if u is None:
        return None
    out = {}
    for key, attr in (("input", "input_tokens"), ("output", "output_tokens"),
                      ("cache_read_input_tokens", "cache_read_input_tokens"),
                      ("cache_creation_input_tokens", "cache_creation_input_tokens")):
        try:
            out[key] = int(getattr(u, attr, 0) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    return out


def _user_id():
    try:
        import config_roles
        return str(config_roles.DEFAULT_USER_ID())
    except Exception:                                    # noqa: BLE001
        return "1"


# ---- one turn --------------------------------------------------------------------------------------------------------------

_PUBLISHING = ("generation_done", "tool_done", "fact_check_done", "end", "abort")


def _guarded(fn):
    """Every call into the SDK: timed into the turn's tracing_ms, and an exception counted, logged once, swallowed."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        t0 = time.perf_counter()
        try:
            return fn(self, *a, **kw)
        except Exception as e:                           # noqa: BLE001 -- tracing never breaks a turn
            self.errors += 1
            _fail(fn.__name__, e)
            return None
        finally:
            self.spent += time.perf_counter() - t0
            if fn.__name__ in _PUBLISHING:
                self._publish()
    return wrapper


class _Noop:
    """Tracing off: every call does nothing."""
    trace_id = None

    def generation(self, *a, **kw):
        return None

    def generation_done(self, *a, **kw):
        return None

    def tool(self, *a, **kw):
        return None

    def tool_done(self, *a, **kw):
        return None

    def fact_check(self, *a, **kw):
        return None

    def fact_check_done(self, *a, **kw):
        return None

    def end(self, *a, **kw):
        return None


NOOP = _Noop()


class Turn:
    def __init__(self, backend, turn_id, user_id, user_message):
        self.client, self.propagate = backend
        self.turn_id, self.user_id = str(turn_id), str(user_id)
        self.trace_id = trace_id_for(self.turn_id)
        self.prop = {"user_id": self.user_id, "trace_name": TRACE_NAME,
                     "metadata": {"turn_id": self.turn_id, "user_id": self.user_id}}
        self.root, self.open, self.parent_of, self.model_of, self.ended = None, [], {}, {}, False
        self.spent, self.errors = 0.0, 0
        self.n = {"generations": 0, "send_back_generations": 0, "tools": 0, "fact_check": False, "score": None,
                  "loop_guard": False}
        try:
            with self.propagate(**self.prop):
                self.root = self.client.start_observation(trace_context={"trace_id": self.trace_id}, name=TRACE_NAME,
                                                          as_type="agent", input=user_input(user_message),
                                                          metadata={"turn_id": self.turn_id, "user_id": self.user_id})
        except Exception as e:                           # noqa: BLE001
            self.errors += 1
            _fail("opening the trace", e)

    def _child(self, parent, **kw):
        if self.root is None:
            return None
        with self.propagate(**self.prop):
            obs = (parent or self.root).start_observation(**kw)
        self.open.append(obs)
        self.parent_of[id(obs)] = parent
        return obs

    def _close(self, obs, **update):
        if obs is None:
            return
        if update:
            obs.update(**update)
        obs.end()
        if obs in self.open:
            self.open.remove(obs)

    def _close_open(self, note, parent=None):
        for obs in [o for o in self.open if parent is None or self.parent_of.get(id(o)) is parent]:
            self._close(obs, level="ERROR", status_message=note)

    def _publish(self):
        LAST_TURN.clear()
        LAST_TURN.update(enabled=True, trace_id=self.trace_id, turn_id=self.turn_id, user_id=self.user_id,
                         tracing_ms=round(self.spent * 1000, 3), errors=self.errors, **self.n)

    @_guarded
    def generation(self, request, send_back=False, parent=None):
        self.n["generations"] += 1
        if send_back:
            self.n["send_back_generations"] += 1
        obs = self._child(parent, name="fact_check_send_back" if send_back else "llm_call", as_type="generation",
                          model=request.get("model"), model_parameters=_model_parameters(request),
                          input=_request_shape(request),
                          metadata={"send_back": bool(send_back), "call_index": self.n["generations"]})
        if obs is not None:
            self.model_of[id(obs)] = request.get("model")
        return obs

    @_guarded
    def generation_done(self, obs, response):
        if obs is None:
            return
        model = getattr(response, "model", None)
        model = model if isinstance(model, str) and model else self.model_of.get(id(obs))
        usage = _usage(response)
        update = {"output": _response_output(response),
                  "metadata": {"stop_reason": str(getattr(response, "stop_reason", None))}}
        if model:
            update["model"] = model
        if usage is not None:
            update["usage_details"] = usage
            cost = pricing.cost_details(model or "", usage["input"], usage["output"],
                                        cache_read=usage["cache_read_input_tokens"],
                                        cache_write=usage["cache_creation_input_tokens"])
            if cost is not None:                         # a model with no price row: no cost at all, never 0
                update["cost_details"] = cost
        self._close(obs, **update)

    @_guarded
    def tool(self, name, args):
        self.n["tools"] += 1
        return self._child(None, name=str(name), as_type="tool", input=trim_output("", args or {}))

    @_guarded
    def tool_done(self, obs, name, result):
        if obs is None:
            return
        update = {"output": trim_output(name, result)}
        if isinstance(result, dict) and "error" in result:
            update.update(level="ERROR", status_message=str(result.get("error"))[:500])
        self._close(obs, **update)

    @_guarded
    def fact_check(self):
        self.n["fact_check"] = True
        return self._child(None, name="fact_check", as_type="span")

    @_guarded
    def fact_check_done(self, obs, info):
        info = info or {}
        outcome = info.get("outcome") or "clean"
        value = SCORE_VALUES.get(outcome, "sent_back_flagged")
        self.n["score"] = value
        if obs is not None:
            self._close_open("the send-back call returned no response", parent=obs)
            self._close(obs, output={k: info.get(k) for k in ("facts_checked", "mismatches", "sent_back", "outcome",
                                                               "rewrite_mismatches", "extra_usd", "error")},
                        metadata={"outcome": outcome, "score": value})
        if self.root is not None:
            self.root.score_trace(name=SCORE_NAME, value=value, data_type="CATEGORICAL",
                                  comment=f"outcome {outcome}; facts checked {info.get('facts_checked')}; "
                                          f"mismatches {len(info.get('mismatches') or [])}")

    def _finish(self):
        self.ended = True
        if _STATE.get("turn") is self:
            _STATE["turn"] = None

    @_guarded
    def end(self, reply, guard=None):
        """The reply as delivered (the loop guard's fixed reply with `guard` = {stop_reason, block_types})."""
        if self.ended:
            return
        self._finish()
        self.n["loop_guard"] = bool(guard)
        self._close_open("the turn ended before this observation did")
        if self.root is not None:
            meta = {"loop_guard": bool(guard)}
            if guard:
                meta.update(guard_stop_reason=str(guard.get("stop_reason")),
                            guard_block_types=[str(b) for b in (guard.get("block_types") or [])])
            self.root.update(output=reply, metadata=meta)
            self.root.end()

    @_guarded
    def abort(self, exc):
        """The turn raised before it replied: close everything, the root at ERROR level."""
        if self.ended:
            return
        self._finish()
        note = f"the turn raised {type(exc).__name__}: {str(exc)[:300]}" if exc is not None else "the turn ended without a reply"
        self._close_open(note)
        if self.root is not None:
            self.root.update(level="ERROR", status_message=note, metadata={"loop_guard": False})
            self.root.end()


def start_turn(turn_id, user_message):
    """The tracer for one turn: a Turn when tracing is on and the client exists, else NOOP. Never raises."""
    try:
        LAST_TURN.clear()
        if not switch_on():
            LAST_TURN.update(enabled=False, trace_id=None)
            return NOOP
        if not keys_present():
            _say_once("off: LANGFUSE_ENABLED=1 but LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL is missing")
            LAST_TURN.update(enabled=False, trace_id=None, reason="keys missing")
            return NOOP
        backend = _backend()
        if backend is None:
            LAST_TURN.update(enabled=False, trace_id=None, reason="client not built")
            return NOOP
        t0 = time.perf_counter()
        turn = Turn(backend, turn_id, _user_id(), user_message)
        turn.spent += time.perf_counter() - t0
        turn._publish()
        _STATE["turn"] = turn
        return turn
    except Exception as e:                               # noqa: BLE001
        _fail("start_turn", e)
        return NOOP


def close_open():
    """Called in agent.run_agent's finally: a turn that raised before it replied is closed (the root at ERROR level)."""
    try:
        turn = _STATE.get("turn")
        if turn is not None:
            turn.abort(sys.exc_info()[1])
    except Exception as e:                               # noqa: BLE001
        _fail("close_open", e)
