"""FPL Copilot API.

ACCESS CONTROL (added 2026-09-17). Until today every endpoint on port 8000 was
unauthenticated and reachable from the internet. POST /chat ran the agent against
the server's ANTHROPIC_API_KEY with no credential, no quota and no rate limit, and
the agent's toolset can WRITE squad state (set_my_squad) and start a 10-40 s MIP
solve (propose_transfers) on a 2-vCPU droplet with no swap. /docs, /redoc and
/openapi.json published the whole surface. ufw allows 8000 from anywhere and the
host is scanned continuously (33,451 failed/invalid ssh auth lines in seven days),
so "nobody knows the URL" was never a control.

THE GATE. Every request must carry

    X-API-Key: <APP_API_KEY>

except GET/HEAD /health, which stays open: the external uptime monitor polls it,
and it publishes nothing the public repo does not already document.

For a browser, which cannot set a header on a top-level navigation, a GET with
?key=<secret> exchanges the key for an HttpOnly cookie once (see COOKIE_NAME).
The static page is therefore unchanged and carries no secret.

FAILS CLOSED. If APP_API_KEY is unset or empty every gated route returns 503. A
missing secret must not silently restore the hole -- silent fallbacks are the enemy.

WHAT THIS CONTROL DOES NOT DO, stated so nobody over-trusts it:
  * There is no TLS on this host -- plain http on a bare IP (master plan 7.2). The
    key travels in cleartext and is readable by anyone on the path. This stops
    internet-wide scanning and opportunistic abuse, which is what was actually
    burning the API spend. It does NOT stop a network attacker.
  * It is ONE shared secret, not per-user auth. Rotating it is an edit to .env plus
    a container recreate.
  * The rate limit is process-local. A container restart resets the window, and if
    the app ever runs more than one worker each worker keeps its own counters.

STILL OPEN, deliberately NOT fixed here: `conversation_history` below is a single
process-global list shared by every caller, so concurrent callers read and write
each other's turns. Closing that is the LangGraph checkpointing work keyed
(user_id, thread_id) (master plan 5.2 Phase 2) -- a real change to how the agent
holds state, not a patch to this file. The gate reduces its blast radius to holders
of the key; it does not fix it.
"""
import os
import secrets
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import run_agent

app = FastAPI()

# Read once at import. Supplied by docker compose from the untracked
# /root/fpl-copilot/.env (`env_file: .env`), so it is never in the repo and a
# change needs a container recreate to take effect.
API_KEY = (os.getenv("APP_API_KEY") or "").strip()
API_KEY_HEADER = "x-api-key"

# Browser entry point. A top-level navigation cannot set a custom header, so the
# page itself could never be fetched with X-API-Key -- and hardcoding the secret
# into static/index.html is not an option, because this repository is PUBLIC and
# that file is tracked: it would publish the key and undo the gate. Instead a GET
# carrying ?key=<secret> exchanges it for an HttpOnly cookie and redirects to the
# clean URL; every later request, including the page's fetch() calls to /chat and
# /reset, authenticates on that cookie with no change to the static file and no
# secret in the repo.
#
# Cost, stated plainly: the key appears once in a URL, so it lands in the browser
# history and the container access log. Use it once per browser. It is not marked
# Secure because there is no TLS on this host -- a Secure cookie would never be
# sent over http. Same cleartext caveat as the header.
COOKIE_NAME = "fpl_key"
COOKIE_MAX_AGE_S = 60 * 60 * 24 * 30

# Single shared conversation history -- see the STILL OPEN note in the module
# docstring. In-memory, process-global, shared by every caller.
conversation_history = []

# The only routes that need no credential. GET and HEAD because uptime monitors
# use either; everything else on this app is gated.
OPEN_ENDPOINTS = {("GET", "/health"), ("HEAD", "/health")}

# --- crude rate limit on the one endpoint that spends money ------------------
# Per-IP AND global. The global ceiling matters because Docker's published port
# can present every external client as the bridge gateway, which would collapse
# the per-IP buckets into one; the global limit bounds the spend either way,
# which is the point. Counted AFTER the key check, so an unauthenticated caller
# can never consume the quota.
CHAT_PER_IP_PER_HOUR = 30
CHAT_GLOBAL_PER_HOUR = 60
WINDOW_S = 3600
_hits_by_ip = {}
_hits_global = deque()


def _key_ok(candidate):
    """Constant-time comparison against the configured secret."""
    return bool(candidate) and secrets.compare_digest(candidate, API_KEY)


def _prune(dq, now):
    while dq and now - dq[0] > WINDOW_S:
        dq.popleft()


def _rate_limited(ip):
    """True if this call should be refused. Sliding window, monotonic clock."""
    now = time.monotonic()
    _prune(_hits_global, now)
    bucket = _hits_by_ip.setdefault(ip, deque())
    _prune(bucket, now)
    if len(_hits_global) >= CHAT_GLOBAL_PER_HOUR or len(bucket) >= CHAT_PER_IP_PER_HOUR:
        return True
    bucket.append(now)
    _hits_global.append(now)
    if len(_hits_by_ip) > 1000:                      # bound the table
        for k in [k for k, v in _hits_by_ip.items() if not v]:
            del _hits_by_ip[k]
    return False


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if (request.method, request.url.path) in OPEN_ENDPOINTS:
        return await call_next(request)

    if not API_KEY:
        return JSONResponse(
            {"detail": "server misconfigured: APP_API_KEY is not set, so every "
                       "authenticated route is refused (fail closed)"},
            status_code=503)

    # one-time browser handshake: ?key=<secret> -> HttpOnly cookie, then redirect
    # to the same path without the query so the secret leaves the URL bar.
    if request.method == "GET" and _key_ok(request.query_params.get("key", "")):
        response = RedirectResponse(url=request.url.path, status_code=303)
        response.set_cookie(COOKIE_NAME, API_KEY, httponly=True, samesite="strict",
                            max_age=COOKIE_MAX_AGE_S, path="/")
        return response

    presented = (request.headers.get(API_KEY_HEADER, "")
                 or request.cookies.get(COOKIE_NAME, ""))
    if not _key_ok(presented):
        return JSONResponse(
            {"detail": f"missing or invalid {API_KEY_HEADER} header "
                       f"(or {COOKIE_NAME} cookie)"},
            status_code=401)

    if request.method == "POST" and request.url.path == "/chat":
        client = request.client.host if request.client else "unknown"
        if _rate_limited(client):
            return JSONResponse(
                {"detail": f"rate limit: at most {CHAT_PER_IP_PER_HOUR} /chat calls per "
                           f"hour per client and {CHAT_GLOBAL_PER_HOUR} per hour in total"},
                status_code=429)

    return await call_next(request)


@app.get("/health")
def health_check():
    # The master plan's contract: {status, git_sha, model_versions,
    # data_freshness_by_source, db_ok} -- plus last_run and reasons, so a
    # failed or missing pipeline run surfaces HERE instead of only in an
    # unread status file. The old one-liner returned ok while Postgres was
    # unreachable (observed live 2026-08-31); this one touches the DB.
    from model_tools import health
    return health()


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat(request: ChatRequest):
    global conversation_history
    answer, conversation_history = run_agent(request.message, conversation_history)
    return {"answer": answer}


@app.post("/reset")
def reset_conversation():
    global conversation_history
    conversation_history = []
    return {"status": "conversation reset"}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")
