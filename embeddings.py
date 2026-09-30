"""The one Voyage call site (2026-09-30): embed(texts, kind) returns one vector per text, batched
under the API's per-request caps, paced within this account's rate limits, retried where that is
worth it, with one embedding_calls row per HTTP attempt so the spend is countable from the
database. The model and the dimension come from config (EMBED_MODEL, EMBED_DIM); kind is
"document" for stored chunks and "query" for searches, sent as Voyage's input_type.

Facts this file rests on (docs.voyageai.com, read 2026-09-30, and one test call the same day):
  * POST https://api.voyageai.com/v1/embeddings, body {input, model, input_type, output_dimension};
    reply data[i].embedding in input order plus usage.total_tokens (the token count of record);
    voyage-4: 32,000-token context, output_dimension 256 / 512 / 1024 (default) / 2048;
    at most 1,000 texts and 320K tokens per request (docs/embeddings, reference/embeddings-api).
  * Rate limits are per account: the docs' Tier 1 is 2000 RPM / 8M TPM, but the test call's
    x-api-warning header said this account has NO payment method and so 3 RPM / 10K TPM
    (config EMBED_RPM / EMBED_TPM; raise them when the dashboard says so). Pacing: a sliding
    60-second window of attempts and their tokens; a request waits until both fit. Tokens are
    estimated before a call (EMBED_CHARS_PER_TOKEN) and replaced by usage.total_tokens after it.
  * Price $0.06 per million tokens, the first 200M tokens free per account (docs/pricing).

Retry rule, as llm.py: up to RETRIES more attempts after a 429, a 5xx or a timeout, with a
1 s / 2 s backoff; any other 4xx is raised at once as EmbedError; 401 / 403 as EmbedAuthError
(its subclass) so the caller stops the whole run after the first one. A reply with the wrong
number of vectors or the wrong dimension is EmbedError "bad_response": nothing is returned from a
batch that is not exactly right. The repeated-error stop rule (three consecutive failures with
the same signature) lives in the caller, embed_pipeline.py, as it does in relevance.py.

The client is injectable (tests pass a fake with .embed(texts, model, input_type,
output_dimension) -> (vectors, total_tokens)); the default one is built lazily from
VOYAGE_API_KEY in the environment or the repo's .env (loaded by path), never printed.
"""
import os
import time
from pathlib import Path

import config_roles

REPO = Path(__file__).resolve().parent
API_URL = "https://api.voyageai.com/v1/embeddings"
PURPOSE = "news_chunks"
KINDS = ("document", "query")
RETRIES = 2                          # extra attempts after the first
BACKOFF_S = (1.0, 2.0)
WINDOW_S = 60.0                      # the rate-limit window


class EmbedError(RuntimeError):
    """No vectors for a batch: exhausted retries, a non-retryable error, or a bad reply.
    status / error_type: the signature of the last failure (see signature())."""

    def __init__(self, msg, status=None, error_type=None):
        super().__init__(msg)
        self.status, self.error_type = status, error_type


class EmbedAuthError(EmbedError):
    """HTTP 401 or 403: the key is rejected. Never retried; the caller stops the run."""


class EmbedRepeatedError(EmbedError):
    """Raised by a caller after 3 consecutive failures with the same signature: the run stops."""


class HTTPStatusError(Exception):
    """A non-200 reply from the API: .status_code and the first characters of the body."""

    def __init__(self, status_code, body=""):
        super().__init__(f"{status_code} {body[:200]}".strip())
        self.status_code, self.body = status_code, body


class VoyageClient:
    """The real client over requests; one HTTP request per embed(), no retries of its own."""

    def __init__(self, api_key, timeout_s=30, session=None):
        self._key, self.timeout_s, self._session = api_key, timeout_s, session

    def embed(self, texts, model, input_type, output_dimension):
        import requests
        s = self._session or requests
        r = s.post(API_URL, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                   json={"input": list(texts), "model": model, "input_type": input_type, "output_dimension": output_dimension},
                   timeout=self.timeout_s)
        if r.status_code != 200:
            raise HTTPStatusError(r.status_code, r.text or "")
        d = r.json()
        data = sorted(d.get("data") or [], key=lambda x: x.get("index", 0))
        return [x["embedding"] for x in data], (d.get("usage") or {}).get("total_tokens")


def default_client(timeout_s=30):
    if not os.environ.get("VOYAGE_API_KEY"):
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise EmbedAuthError("VOYAGE_API_KEY is not set (environment or .env)", None, "no_key")
    return VoyageClient(key, timeout_s)


def _is_timeout(exc):
    return type(exc).__name__.endswith("Timeout")


def signature(exc):
    """(status, error_type): the HTTP status and the exception class for status errors; timeouts
    are (None, "timeout"); anything else (None, class name)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status, type(exc).__name__
    if _is_timeout(exc):
        return None, "timeout"
    return None, type(exc).__name__


def classify(exc):
    """('retry' | 'auth' | 'fail', message)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        msg = f"HTTP {status}: {exc}"
        if status in (401, 403):
            return "auth", msg
        return ("retry" if status == 429 or status >= 500 else "fail"), msg
    if _is_timeout(exc):
        return "retry", f"timeout: {exc}"
    return "fail", f"{type(exc).__name__}: {exc}"


def estimate_tokens(text):
    """chars / EMBED_CHARS_PER_TOKEN plus EMBED_TOKENS_PER_TEXT: the API counts a fixed overhead per
    text (its input_type prefix; fitted 21.5 on 2026-09-30, 24 by ruling), so short texts cost far
    more than their characters suggest."""
    return len(text) // config_roles.EMBED_CHARS_PER_TOKEN + 1 + config_roles.EMBED_TOKENS_PER_TEXT


def request_token_budget():
    """Estimated tokens one request may carry: the API cap, or EMBED_REQUEST_TPM_SHARE of the TPM
    when that is smaller (a request near the whole minute's allowance gets 429s; ruling 2026-09-30)."""
    return min(config_roles.EMBED_MAX_TOKENS_PER_REQUEST, int(config_roles.EMBED_TPM * config_roles.EMBED_REQUEST_TPM_SHARE))


def batches(texts, max_texts, max_tokens, chars_per_token, per_text=0):
    """Index groups in order: a group closes when the next text would exceed max_texts or the
    estimated max_tokens; a single text over the budget is a group on its own."""
    groups, cur, cur_tokens = [], [], 0
    for i, t in enumerate(texts):
        est = len(t) // chars_per_token + 1 + per_text
        if cur and (len(cur) >= max_texts or cur_tokens + est > max_tokens):
            groups.append(cur)
            cur, cur_tokens = [], 0
        cur.append(i)
        cur_tokens += est
    if cur:
        groups.append(cur)
    return groups


class Pacer:
    """Keeps attempts within rpm requests and tpm tokens per sliding 60-second window."""

    def __init__(self, rpm, tpm, clock=time.monotonic, sleep=time.sleep):
        self.rpm, self.tpm, self.clock, self.sleep = rpm, tpm, clock, sleep
        self.events = []                                    # (time, tokens) of every attempt

    def _prune(self, now):
        self.events = [(t, n) for t, n in self.events if now - t < WINDOW_S]

    def wait(self, est_tokens):
        while True:
            now = self.clock()
            self._prune(now)
            n, used = len(self.events), sum(k for _, k in self.events)
            if n < self.rpm and (n == 0 or used + est_tokens <= self.tpm):
                return
            self.sleep(max(0.0, self.events[0][0] + WINDOW_S - now))

    def record(self, tokens):
        self.events.append((self.clock(), int(tokens or 0)))


def _record(conn, purpose, model, kind, n_texts, tokens, ok, error=None):
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute("INSERT INTO embedding_calls (purpose, model, kind, n_texts, tokens, ok, error) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (purpose, model, kind, n_texts, tokens, ok, error))
    conn.commit()


def _embed_batch(client, batch, kind, model, dim, conn, purpose, sleep, retries, pacer, stats):
    est = sum(estimate_tokens(t) for t in batch)
    last = None
    for attempt in range(1, retries + 2):
        pacer.wait(est)
        if stats is not None:
            stats["attempts"] = stats.get("attempts", 0) + 1
        try:
            vecs, tokens = client.embed(batch, model, kind, dim)
        except Exception as e:                       # noqa: BLE001 -- classified below
            pacer.record(est)
            what, last = classify(e)
            status, etype = signature(e)
            _record(conn, purpose, model, kind, len(batch), None, False, last)
            if what == "auth":
                raise EmbedAuthError(last, status, etype) from e
            if what == "fail" or attempt == retries + 1:
                raise EmbedError(last, status, etype) from e
            sleep(BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)])
            continue
        pacer.record(tokens if tokens is not None else est)
        dims = sorted({len(v) for v in vecs})
        if len(vecs) != len(batch) or dims != [dim]:
            msg = f"bad response: {len(vecs)} vectors for {len(batch)} texts, dimension {dims} (expected {dim})"
            _record(conn, purpose, model, kind, len(batch), tokens, False, msg)
            raise EmbedError(msg, None, "bad_response")
        _record(conn, purpose, model, kind, len(batch), tokens, True)
        if stats is not None:
            stats["calls"] = stats.get("calls", 0) + 1
            stats["texts"] = stats.get("texts", 0) + len(batch)
            stats["tokens"] = stats.get("tokens", 0) + (tokens or 0)
        return vecs
    raise EmbedError(last or "no attempt made")      # pragma: no cover -- the loop always returns or raises


def embed(texts, kind, *, model=None, dim=None, client=None, conn=None, purpose=PURPOSE, sleep=time.sleep,
          clock=time.monotonic, retries=RETRIES, pacer=None, stats=None):
    """One vector per text, in order. kind: "document" | "query". Raises EmbedError when a batch
    gets no vectors (nothing partial is returned); every attempt is an embedding_calls row when
    conn is given; stats (a dict) accumulates calls / attempts / texts / tokens."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    texts = list(texts)
    if not texts:
        return []
    model = model or config_roles.EMBED_MODEL
    dim = dim or config_roles.EMBED_DIM
    if client is None:
        client = default_client()
    if pacer is None:
        pacer = Pacer(config_roles.EMBED_RPM, config_roles.EMBED_TPM, clock, sleep)
    out = [None] * len(texts)
    for idx in batches(texts, config_roles.EMBED_MAX_TEXTS_PER_REQUEST, request_token_budget(), config_roles.EMBED_CHARS_PER_TOKEN,
                       config_roles.EMBED_TOKENS_PER_TEXT):
        vecs = _embed_batch(client, [texts[i] for i in idx], kind, model, dim, conn, purpose, sleep, retries, pacer, stats)
        for i, v in zip(idx, vecs):
            out[i] = v
    return out
