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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import run_agent

app = FastAPI()

# Read once at import. Supplied by docker compose from the untracked
# /root/fpl-copilot/.env (`env_file: .env`), so it is never in the repo and a
# change needs a container recreate to take effect.
API_KEY = (os.getenv("APP_API_KEY") or "").strip()
API_KEY_HEADER = "x-api-key"

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

    presented = request.headers.get(API_KEY_HEADER, "")
    if not (presented and secrets.compare_digest(presented, API_KEY)):
        return JSONResponse(
            {"detail": f"missing or invalid {API_KEY_HEADER} header"},
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
