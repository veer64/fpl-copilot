"""The one Anthropic call site for batch jobs (2026-09-26): complete() sends a system + user
prompt, retries what is worth retrying, and writes one llm_calls row per HTTP attempt so the
spend is countable from the database. agent.py keeps its own client for the chat loop.

temperature: sent as given (0 for the filter) to every model EXCEPT those in config
MODELS_WITHOUT_TEMPERATURE, which reject the parameter outright; each llm_calls row records
whether it was sent (temperature_sent). No retry-without-temperature on error (ruling 2026-09-27).
Each successful row also records the reply's stop_reason, its content block types in order and
the characters of thinking vs text; a reply stopped at max_tokens is marked error 'truncated', one the
API's classifier halted (stop_reason 'refusal', no content) error 'refusal' (ruling 2026-09-27).
item_id / prompt_version, when the caller gives them, link the row to what it was judging.

Retry rule: up to RETRIES more attempts after a 429, a 5xx or a timeout, with a 1 s / 2 s
backoff; any other 4xx (400 bad request, 404 model) is raised at once as LLMError, and a
401 / 403 as LLMAuthError (its subclass): the key is wrong, so callers stop the whole run
after the first one instead of failing every item the same way (94 identical 401s, 2026-09-26).
The SDK's own retries are OFF on the default client so every attempt is one row here.

The client is injectable (tests pass a fake with .messages.create); it is built lazily, so
importing this module or running a job with nothing to send never needs a key.
"""
import os
import time
from pathlib import Path

import config_roles

REPO = Path(__file__).resolve().parent
RETRIES = 2                          # extra attempts after the first
REPLY_ERRORS = {"max_tokens": "truncated", "refusal": "refusal"}   # stop reasons that make a reply unusable
BACKOFF_S = (1.0, 2.0)


class LLMError(RuntimeError):
    """The call did not produce a reply: exhausted retries, or a non-retryable error.
    status / error_type: the signature of the last failure (see signature()), for the callers'
    repeated-error rule."""

    def __init__(self, msg, status=None, error_type=None):
        super().__init__(msg)
        self.status, self.error_type = status, error_type


class LLMAuthError(LLMError):
    """HTTP 401 or 403: the key is rejected. Never retried; the caller stops the run."""


class LLMRepeatedError(LLMError):
    """Raised by a caller after 3 consecutive failures with the same signature: the run stops."""


def default_client(timeout_s=30):
    """anthropic.Anthropic() with the SDK's retries off; the key comes from the environment
    or the repo's .env (loaded here by path, never by search)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    import anthropic
    return anthropic.Anthropic(max_retries=0, timeout=timeout_s)


def signature(exc):
    """(status, error_type) of a failure: the HTTP status and the API error body's type
    (invalid_request_error, ...) when the SDK gives one, else the exception class; timeouts are
    (None, "timeout"). Two failures with the same signature are "the same error"."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        body = getattr(exc, "body", None)
        etype = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            etype = body["error"].get("type")
        return status, etype or type(exc).__name__
    if type(exc).__name__ == "APITimeoutError":
        return None, "timeout"
    return None, type(exc).__name__


def classify(exc):
    """('retry' | 'auth' | 'fail', message). Status errors carry .status_code (the SDK's
    APIStatusError and any fake); timeouts are the SDK's APITimeoutError or anything named so."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        msg = f"HTTP {status}: {exc}"
        if status in (401, 403):
            return "auth", msg
        return ("retry" if status == 429 or status >= 500 else "fail"), msg
    if type(exc).__name__ == "APITimeoutError":
        return "retry", f"timeout: {exc}"
    return "fail", f"{type(exc).__name__}: {exc}"


def _record(conn, purpose, model, ok, error=None, input_tokens=None, output_tokens=None, temperature_sent=None,
            stop_reason=None, content_block_types=None, thinking_chars=None, text_chars=None, item_id=None, prompt_version=None):
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute("INSERT INTO llm_calls (purpose, model, input_tokens, output_tokens, ok, error, temperature_sent, "
                    "stop_reason, content_block_types, thinking_chars, text_chars, news_item_id, prompt_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (purpose, model, input_tokens, output_tokens, ok, error, temperature_sent,
                     stop_reason, content_block_types, thinking_chars, text_chars, item_id, prompt_version))
    conn.commit()


def complete(purpose, system, user, model, max_tokens, temperature=0, timeout_s=30, *,
             client=None, conn=None, sleep=time.sleep, retries=RETRIES, item_id=None, prompt_version=None):
    """One completion. Returns (text, usage) where usage = {input_tokens, output_tokens,
    attempts, stop_reason, content_block_types, thinking_chars, text_chars}; text is the
    concatenated text blocks (a reply made only of thinking gives ""). Raises LLMError when
    no reply was obtained; every attempt is a row in llm_calls when conn is given."""
    if client is None:
        client = default_client(timeout_s)
    send_temperature = model not in config_roles.MODELS_WITHOUT_TEMPERATURE
    request = {"model": model, "max_tokens": max_tokens}
    if send_temperature:
        request["temperature"] = temperature
    request.update(system=system, messages=[{"role": "user", "content": user}], timeout=timeout_s)
    last = None
    for attempt in range(1, retries + 2):
        try:
            resp = client.messages.create(**request)
        except Exception as e:                       # noqa: BLE001 -- classified below
            kind, last = classify(e)
            status, etype = signature(e)
            _record(conn, purpose, model, False, error=last, temperature_sent=send_temperature, item_id=item_id, prompt_version=prompt_version)
            if kind == "auth":
                raise LLMAuthError(last, status, etype) from e
            if kind == "fail" or attempt == retries + 1:
                raise LLMError(last, status, etype) from e
            sleep(BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)])
            continue
        blocks = list(resp.content or [])
        text = "".join(getattr(b, "text", "") or "" for b in blocks if getattr(b, "type", "text") == "text")
        stop_reason = getattr(resp, "stop_reason", None)
        usage = {"input_tokens": getattr(resp.usage, "input_tokens", None),
                 "output_tokens": getattr(resp.usage, "output_tokens", None), "attempts": attempt,
                 "stop_reason": stop_reason,
                 "content_block_types": [str(getattr(b, "type", type(b).__name__)) for b in blocks],
                 "thinking_chars": sum(len(getattr(b, "thinking", "") or "") for b in blocks if getattr(b, "type", "") == "thinking"),
                 "text_chars": len(text)}
        _record(conn, purpose, model, True, error=REPLY_ERRORS.get(stop_reason),
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"], temperature_sent=send_temperature,
                stop_reason=stop_reason, content_block_types=usage["content_block_types"],
                thinking_chars=usage["thinking_chars"], text_chars=usage["text_chars"], item_id=item_id, prompt_version=prompt_version)
        return text, usage
    raise LLMError(last or "no attempt made")      # pragma: no cover -- the loop always returns or raises
