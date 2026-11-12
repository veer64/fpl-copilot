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

THREADS (Prompt B, 2026-10-31 -- closes the shared-history hole this docstring used to
list as STILL OPEN). There is no process-global conversation any more: every /chat turn
runs in a stored thread owned by one user (threads.py; LangGraph's Postgres checkpointer
holds the history). The user is server-side only -- config_roles.DEFAULT_USER_ID() -- never
the request body. /chat {"message", "thread_id"?}: no thread id -> the user's default
thread; a thread id the user does not own -> 403 before any model call; the response
carries the thread id. /reset: the next /chat without a thread id starts a fresh default
thread (the old one stays the user's), and the user's open preview tickets are cancelled.

LOGIN (Prompt P7, 2026-11-01): AUTH_MODE=off|clerk (auth.py; default off). off is everything above,
unchanged. clerk: POST /chat and POST /reset (CLERK_ROUTES) take `Authorization: Bearer <Clerk session
token>` INSTEAD of the shared key -- with open sign-up the token is the credential -- and a missing or
bad token is 401 before any model call or DB access; the request's user is the token's (users.py:
app_users, created on first sight), set for the whole turn (config_roles.acting_user), never the body's
or the model's. Every other route keeps the shared-key gate in both modes. GET /admin and GET /admin/users.csv
(admin.py; clerk mode only, 404 in off mode) take the token too and answer only an admin (403 otherwise).

THE WEBSITE (Prompt F1a, 2026-11-02). CORS_ALLOWED_ORIGINS (comma-separated origins): unset or empty -> no CORS middleware
at all, every response exactly as before; set -> only those origins may call the API from a browser (methods GET, POST,
DELETE, OPTIONS; headers Authorization and Content-Type -- the shared key never travels cross-origin; no credentials:
bearer tokens, no cookies). In clerk mode a session token must name its origin (azp, auth.py), and the app refuses to
START when CLERK_AUTHORIZED_PARTIES lists none.
"""
import contextlib
import os
import re
import secrets
import sys
import time
from collections import deque

from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel



def _utf8_console(*streams):
    """Prompt W7b (F12): a print must never raise on a cp1252 console (a Windows dev server: a reply with an arrow or an
    umlaut crashed the turn in the print of the raw reply). Each text stream that can be reconfigured gets UTF-8 with
    errors="replace"; a stream already in UTF-8 with that policy (production's Docker) is left as it is."""
    for stream in streams:
        try:
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if enc != "utf8" or getattr(stream, "errors", "") != "replace":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_utf8_console(sys.stdout, sys.stderr)

import admin                                            # Prompt P7: the admin dashboard + users CSV (clerk mode)
import agent_graph                                      # Prompt B: /chat turns run in stored threads
import auth                                             # Prompt P7: AUTH_MODE, Clerk session tokens
import config_roles
import guest                                           # Prompt W9: guest mode (start / ping / leave / the reaper)
import squad_previews                                   # Prompt E (2026-10-27): /reset cancels the user's preview tickets
import threads                                         # Prompt B (2026-10-31): per-user threads, the checkpointer
import tracing                                          # Prompt L (2026-10-30): Langfuse traces, flushed on shutdown
import turn_context                                     # Prompt W4 (2026-11-06): the turn's record for the Chat page
import users                                            # Prompt P7: app_users (clerk mode only)


AUTHORIZED_PARTIES_MISSING = ("startup refused: AUTH_MODE=clerk needs CLERK_AUTHORIZED_PARTIES (the website's origins, "
                              "comma-separated); with none listed no session token could ever be accepted")


@contextlib.asynccontextmanager
async def _lifespan(app):
    if auth.mode() == "clerk" and not auth.authorized_parties():     # Prompt F1a: azp is required, so a list is too
        print(f"  [{AUTHORIZED_PARTIES_MISSING}]", flush=True)
        raise RuntimeError(AUTHORIZED_PARTIES_MISSING)
    if auth.mode() == "clerk":                           # Prompt W9: the guest schema (idempotent) + the reaper, clerk mode only
        try:
            guest.ensure_schema()
        except Exception as e:                           # noqa: BLE001 -- reported; the explicit schema step covers it
            print(f"  [guest schema not ensured at startup: {type(e).__name__}: {str(e)[:160]}]", flush=True)
        guest.start_reaper()
    yield
    guest.stop_reaper()
    tracing.shutdown()                                  # flush the traces at shutdown, bounded (tracing.SHUTDOWN_TIMEOUT_S)
    threads._reset()                                    # Prompt B: close the checkpointer's connection pool


app = FastAPI(lifespan=_lifespan)

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

# A browser that navigates here without the cookie should be told what to do, not
# handed raw JSON. Carries no secret; it only names the mechanism, which the 401
# already reveals. API clients (Accept: */*) still get the JSON body.
UNAUTHORIZED_HTML = """<!DOCTYPE html>
<html><head><title>FPL Copilot - authentication required</title><style>
body{font-family:sans-serif;max-width:640px;margin:60px auto;padding:0 20px;line-height:1.5}
code{background:#f3f3f3;padding:2px 5px;border-radius:3px}
</style></head><body>
<h1>Authentication required</h1>
<p>This app sits behind a shared key. Open it <b>once</b> as
<code>/?key=YOUR_KEY</code> to set a session cookie for this browser; after that the
page and everything it calls work normally for 30 days.</p>
<p>The key is only on the server, as <code>APP_API_KEY</code> in
<code>/root/fpl-copilot/.env</code>. Programmatic clients send it as the
<code>X-API-Key</code> header instead. <code>/health</code> is the one route that
needs no key.</p>
</body></html>"""

# The only routes that need no credential. GET and HEAD because uptime monitors
# use either; everything else on this app is gated.
OPEN_ENDPOINTS = {("GET", "/health"), ("HEAD", "/health")}

# Prompt P7: in AUTH_MODE=clerk these routes authenticate with the Clerk session token (the handler checks it) instead of
# the shared key; in off mode they are gated by the key like everything else.
CLERK_ROUTES = {("POST", "/chat"), ("POST", "/reset"), ("GET", "/admin"), ("GET", "/admin/users.csv"),
                ("GET", "/me"), ("GET", "/threads"), ("POST", "/threads"),      # Prompt F1a: the website's endpoints
                ("GET", "/me/squad"), ("GET", "/me/teams"), ("POST", "/me/teams"),
                ("DELETE", "/me/active-team"), ("GET", "/deadlines"),           # Prompt W3: the Home page
                ("DELETE", "/me"),                                              # Prompt W5: delete account
                ("GET", "/admin/summary"),                                      # Prompt W6: the admin page's JSON
                ("GET", "/guest/status"), ("POST", "/guest/start"),             # Prompt W9: guest mode (public; 404 in off mode)
                ("POST", "/me/ping"), ("POST", "/me/leave")}                    # Prompt W9: the guest session's signals
CLERK_ROUTE_PATTERNS = [("GET", re.compile(r"^/threads/[^/]+/messages$")),
                        ("POST", re.compile(r"^/me/teams/[^/]+/(activate|refresh)$")),
                        ("GET", re.compile(r"^/me/teams/[^/]+/card$")),                 # Prompt W4: the Chat page
                        ("POST", re.compile(r"^/messages/[^/]+/feedback$")),
                        ("DELETE", re.compile(r"^/me/teams/[^/]+$")),                   # Prompt W5: remove team
                        ("DELETE", re.compile(r"^/threads/[^/]+$"))]                    # Prompt W5: delete chat


def _clerk_route(method, path):
    return (method, path) in CLERK_ROUTES or any(m == method and rx.match(path) for m, rx in CLERK_ROUTE_PATTERNS)

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


WEBSITE_URL = "https://fplcopilot.app"


def _retired_in_clerk_mode(method, path):
    """Prompt S2 (2026-11-12): the old key-gated chat page (static/index.html at /) is retired in clerk mode -- the website
    is WEBSITE_URL. GET / and HEAD / answer 308 there (key or no key; the ?key= handshake sets no cookie) and every
    /static/* path answers 404 (key or no key). Off mode never calls this, so the laptop's old page is byte-identical."""
    if path == "/" and method in ("GET", "HEAD"):
        return RedirectResponse(url=WEBSITE_URL, status_code=308)
    if path == "/static" or path.startswith("/static/"):
        return JSONResponse(NOT_FOUND, status_code=404)
    return None


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if (request.method, request.url.path) in OPEN_ENDPOINTS:
        return await call_next(request)
    if auth.mode() == "clerk":
        retired = _retired_in_clerk_mode(request.method, request.url.path)
        if retired is not None:
            return retired
    if auth.mode() == "clerk" and _clerk_route(request.method, request.url.path):
        return await call_next(request)                 # Prompt P7: the handler verifies the session token

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
        # A person in a browser gets a page telling them how to authenticate; an
        # API client gets the JSON body it can parse.
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(UNAUTHORIZED_HTML, status_code=401)
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


# Prompt F1a: CORS for the website, added AFTER the key gate so it is the outermost layer: a preflight (OPTIONS, no
# credential) is answered here, and the gate's own refusals still carry the header the browser needs to read them.
CORS_ENV = "CORS_ALLOWED_ORIGINS"
CORS_METHODS = ["GET", "POST", "DELETE", "OPTIONS"]
CORS_HEADERS = ["Authorization", "Content-Type"]


def cors_origins():
    return [o.strip().rstrip("/") for o in (os.getenv(CORS_ENV) or "").split(",") if o.strip().rstrip("/")]


if cors_origins():                                      # read once at import, like APP_API_KEY: a change needs a restart
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=CORS_METHODS,
                       allow_headers=CORS_HEADERS, allow_credentials=False)


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
    thread_id: str | None = None                        # Prompt B: optional; none -> the user's default thread


THREAD_REFUSED = "thread not found for this user"
TEAM_CHANGED = "active team changed; start a new chat"      # Prompt F1b: a thread belongs to the team active at its creation


def _team_changed(e):
    """409 for a thread of a team that is no longer active: no model call, nothing written to that thread; the body names
    the user's default thread for the active team, where the conversation continues."""
    return JSONResponse({"detail": TEAM_CHANGED, "thread_id": e.thread_id}, status_code=409)
TOKEN_REFUSED = "missing or invalid session token"
PROFILE_UNAVAILABLE = "your account profile could not be loaded; please try again shortly"
RATE_LIMITED = f"rate limit: at most {users.RATE_LIMIT_PER_MINUTE} messages a minute; please wait a moment"
# Prompt W4 (2026-11-06; approved at the checkpoint): the page's 2,000-character box has a server-side twin -- a longer
# message is 422 before any model call or row, in both modes (the model's request for a message within it is unchanged).
MESSAGE_MAX = 2000
MESSAGE_TOO_LONG = "message too long: at most 2,000 characters"


def _too_long(request):
    if len(request.message or "") > MESSAGE_MAX:
        return JSONResponse({"detail": MESSAGE_TOO_LONG}, status_code=422)
    return None


def _turn_fields():
    """Prompt W4: the fields a delivered /chat reply carries beside its text -- message_id and the structured extras noted on
    the turn channel (turn_extras); trace ids stay server-side (checkpoint C5)."""
    rec = turn_context.last() or {}
    return {"message_id": rec.get("message_id"), "sources": list(rec.get("sources") or []),
            "squad_preview": rec.get("squad_preview"), "squad_applied": rec.get("squad_applied")}


def _signed_in(http):
    """Prompt P7 (clerk mode): (the app_users row, None) for a verified session token, else (None, the refusal): 401 for a
    missing or bad token -- before any DB access --, 503 when a new user's profile cannot be fetched (nothing written)."""
    try:
        claims = auth.verify(auth.bearer(http.headers))
    except auth.AuthError:
        return None, JSONResponse({"detail": TOKEN_REFUSED}, status_code=401)
    try:
        return users.user_for_claims(claims), None
    except users.ProfileUnavailable as e:
        print(f"  [sign-in refused: {e}]")
        return None, JSONResponse({"detail": PROFILE_UNAVAILABLE}, status_code=503)


def _chat_signed_in(request, http):
    user, refusal = _signed_in(http)
    if refusal is not None:
        return refusal
    user_id = int(user["user_id"])
    too_long = _too_long(request)                       # Prompt W4: after the token, before the windows and the cap
    if too_long is not None:
        return too_long
    if users.rate_limited(user):                        # Prompt P7 Part 2: 10 a minute per user (exempt: never)
        return JSONResponse({"detail": RATE_LIMITED}, status_code=429)
    if user.get("is_guest"):                            # Prompt W9: the switch and the shared daily guest budget, 0 model calls
        refusal = _guest_refusal(user, request)
        if refusal is not None:
            return refusal
    refused, reply = users.capped(user)                 # $1/day per user (exempt: never): no model call, a cap_hits row
    if refused:                                         # Prompt W4 Data 2: the same text + the structured limit
        return {"answer": reply, "thread_id": request.thread_id, "capped": True,
                "limit": {"kind": "guest" if user.get("is_guest") else "daily", "reset_at": threads.iso(users.cap_reset_at())}}
    with config_roles.acting_user(user_id):             # every tool, ticket and trace of the turn answers for this user
        try:
            thread_id = threads.resolve(user_id, request.thread_id)
        except threads.ThreadRefused:
            return JSONResponse({"detail": THREAD_REFUSED}, status_code=403)
        except threads.TeamChanged as e:
            return _team_changed(e)
        answer = agent_graph.run_thread_turn(user_id, thread_id, request.message)
    return {"answer": answer, "thread_id": thread_id, **_turn_fields()}


def _guest_refusal(user, request):
    """Prompt W9: a guest's turn is refused -- in the chat's own system-message shape -- when GUEST_MODE is off (the brake) or
    when every guest's spend today has reached GUEST_DAILY_BUDGET_USD (a cap_hits row + the start row's counter). None = go."""
    if not guest.enabled():
        return {"answer": guest.UNAVAILABLE, "thread_id": request.thread_id, "capped": True, "limit": {"kind": "guest_off", "reset_at": None}}
    if not guest.budget_open():
        uid = int(user["user_id"])
        users.record_cap_hit(uid, guest.budget_used_today(), guest.daily_budget_usd())
        guest.record_hit(uid, "budget")
        return {"answer": guest.BUDGET_FULL, "thread_id": request.thread_id, "capped": True,
                "limit": {"kind": "guest_budget", "reset_at": threads.iso(users.cap_reset_at())}}
    return None


@app.post("/chat")
def chat(request: ChatRequest, http: Request):
    if auth.mode() == "clerk":
        return _chat_signed_in(request, http)
    too_long = _too_long(request)
    if too_long is not None:
        return too_long
    user_id = config_roles.DEFAULT_USER_ID()            # server-side only: never from the request body or the model
    try:
        thread_id = threads.resolve(user_id, request.thread_id)
    except threads.ThreadRefused:                       # another user's thread (or none): refused before any model call
        return JSONResponse({"detail": THREAD_REFUSED}, status_code=403)
    except threads.TeamChanged as e:                    # Prompt F1b: never fires for a user with no team
        return _team_changed(e)
    answer = agent_graph.run_thread_turn(user_id, thread_id, request.message)
    return {"answer": answer, "thread_id": thread_id, **_turn_fields()}


@app.post("/reset")
def reset_conversation(http: Request):
    if auth.mode() == "clerk":
        user, refusal = _signed_in(http)
        if refusal is not None:
            return refusal
        with config_roles.acting_user(int(user["user_id"])):
            return _reset_for_default_user()
    return _reset_for_default_user()


def _reset_for_default_user():
    try:
        threads.start_new_default(config_roles.DEFAULT_USER_ID())   # Prompt B: the next /chat starts a fresh default thread
    except Exception as e:  # noqa: BLE001 -- as the ticket cancel below: reported, never fatal to /reset
        print(f"  [default thread not reset: {type(e).__name__}: {str(e)[:200]}]")
    cancelled = squad_previews.cancel_for_default_user()     # Prompt E: a fresh conversation holds no open preview ticket
    return {"status": "conversation reset", "preview_tickets_cancelled": cancelled}


ADMIN_ONLY = "admin only"


def _admin(http):
    """Prompt P7 Part 3: (the admin's row, None) or (None, the refusal): 404 in off mode (the routes do not exist there),
    401 for a missing or bad token, 403 for anyone but an admin."""
    if auth.mode() != "clerk":
        return None, JSONResponse({"detail": "Not Found"}, status_code=404)
    user, refusal = _signed_in(http)
    if refusal is not None:
        return None, refusal
    if not user.get("is_admin"):
        return None, JSONResponse({"detail": ADMIN_ONLY}, status_code=403)
    return user, None


@app.get("/admin")
def admin_page(http: Request):
    _, refusal = _admin(http)
    if refusal is not None:
        return refusal
    return HTMLResponse(admin.render_html(admin.stats()))


@app.get("/admin/users.csv")
def admin_users_csv(http: Request):
    _, refusal = _admin(http)
    if refusal is not None:
        return refusal
    return Response(content=admin.users_csv(admin.stats()), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="users.csv"'})


@app.get("/admin/summary")
def admin_summary(http: Request):
    """Prompt W6 (2026-11-11): the JSON the website's /admin page reads (admin.summary): the P7 numbers plus the totals over
    every cost row, the 30 days zero-filled, the limit hits with names, the sign-in split and the feedback section. The
    same guard as /admin: 404 in off mode, 401 for a bad token, 403 for anyone but an admin."""
    _, refusal = _admin(http)
    if refusal is not None:
        return refusal
    return admin.summary()


# ---- the website's endpoints (Prompt F1a, 2026-11-02): clerk mode only (404 in off mode, like /admin); the token's user
# only; READS_PER_MINUTE requests a minute per user (users.reads_limited; the admin is exempt, as for /chat) -------------

NOT_FOUND = {"detail": "Not Found"}
READS_LIMITED = f"rate limit: at most {users.READS_PER_MINUTE} requests a minute; please wait a moment"


def _account(http):
    """(the signed-in user's row, None) or (None, the refusal): 404 in off mode, then 401 / 503 as for /chat, then 429."""
    if auth.mode() != "clerk":
        return None, JSONResponse(NOT_FOUND, status_code=404)
    user, refusal = _signed_in(http)
    if refusal is not None:
        return None, refusal
    if users.reads_limited(user):
        return None, JSONResponse({"detail": READS_LIMITED}, status_code=429)
    return user, None


def _active_team(user_id):
    import fpl_teams                                    # Part 4: the user's active imported FPL team, or None
    return fpl_teams.active_team(user_id)


@app.get("/me")
def me(http: Request):
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    uid = int(user["user_id"])
    return {"user_id": uid, "is_admin": bool(user.get("is_admin")), "is_owner": users.is_owner(user),   # is_owner: Prompt W5 B1
            "daily_cap_usd": users.cap_for(user), "spent_today_usd": round(users.spent_today(uid), 6),
            "active_team": _active_team(uid),
            "is_guest": bool(user.get("is_guest")), "guest": guest.me_block(user)}                      # Prompt W9


# ---- Prompt W9 (2026-11-12): guest mode (guest.py) -- clerk mode only (404 in off mode) ----------------------------------------
GUEST_START_FAILED = "guest sign-in could not be prepared; please try again"


@app.get("/guest/status")
def guest_status():
    """Public: the login card's switch. {enabled, idle_minutes, cap_usd, leave_grace_seconds}."""
    if auth.mode() != "clerk":
        return JSONResponse(NOT_FOUND, status_code=404)
    return guest.status()


@app.post("/guest/start")
def guest_start(http: Request):
    """Public: a one-time Clerk sign-in token for a brand-new guest -- after the switch, the per-IP limit (X-Forwarded-For
    only behind Caddy, stored hashed), the daily guest budget and the global limit (GUEST_STARTS_PER_10_MIN, Prompt S1).
    {ticket, expires_in_seconds}; 403 guest_off; 429 guest_ip_limit / guest_budget / guest_busy; 502 when Clerk failed
    (nothing half-made is left)."""
    if auth.mode() != "clerk":
        return JSONResponse(NOT_FOUND, status_code=404)
    try:
        return guest.start(guest.client_ip(http))
    except guest.GuestRefused as e:
        return JSONResponse({"detail": e.detail, "code": e.code}, status_code=e.status)
    except guest.ClerkFailed as e:
        print(f"  [guest start failed: {e}]", flush=True)
        return JSONResponse({"detail": GUEST_START_FAILED, "code": "guest_clerk"}, status_code=502)


@app.post("/me/ping")
def guest_ping(http: Request):
    """A guest's activity (<= once a minute from the client, on load and when a tab becomes visible): the idle clock
    restarts and a pending leave is cancelled. 204 for anyone signed in (a non-guest: nothing written)."""
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    if user.get("is_guest"):
        guest.ping(user["user_id"])
    return Response(status_code=204)


@app.post("/me/leave")
def guest_leave(http: Request):
    """The last desktop tab of a guest closed (fetch keepalive): the leave grace starts; a ping within it cancels it. 204."""
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    if user.get("is_guest"):
        guest.leave(user["user_id"])
    return Response(status_code=204)


# ---- Prompt W5 (2026-11-10): delete account / remove team / delete chat (deletion.py) ---------------------------------------
# Clerk mode only (404 in off mode), the token's user only, through the read window (users.reads_limited) like every other
# read of the website; the rows go in one transaction each, scoped to the user in SQL. The owner and the reserved ids are
# refused before any write.

OWNER_LOCKED = "The owner account can't be deleted here."
ACCOUNT_LOCKED = "this account can't be deleted here"
CLERK_DELETE_FAILED = "the sign-in account could not be deleted; nothing was removed — try again"
SIGN_IN_REMOVED = ("your sign-in was removed but our copy of your data could not be deleted; email veersanghavi8@gmail.com "
                   "and we'll finish it for you")


@app.delete("/me")
def delete_account(http: Request):
    import deletion
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    if users.is_owner(user):
        return JSONResponse({"detail": OWNER_LOCKED}, status_code=403)
    if not users.deletable(user):
        return JSONResponse({"detail": ACCOUNT_LOCKED}, status_code=403)
    try:
        return deletion.delete_account(user, guest=bool(user.get("is_guest")))   # W9: a guest's own "End guest session"
    except deletion.NotDeletable:
        return JSONResponse({"detail": ACCOUNT_LOCKED}, status_code=403)
    except users.ClerkDeleteFailed as e:
        print(f"  [account delete of user {user['user_id']}: Clerk refused: {e}; rolled back]")
        return JSONResponse({"detail": CLERK_DELETE_FAILED}, status_code=502)
    except deletion.CommitFailedAfterClerk:
        return JSONResponse({"detail": SIGN_IN_REMOVED}, status_code=500)


@app.delete("/me/teams/{fpl_team_id}")
def remove_team(fpl_team_id: str, http: Request):
    import deletion
    return _team_call(http, lambda: (deletion.delete_team, (_team_id(fpl_team_id, path=True),)))


@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, http: Request):
    import deletion
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    try:
        return deletion.delete_thread(int(user["user_id"]), thread_id)
    except threads.ThreadRefused:                       # another user's or no such thread: the same answer
        return JSONResponse({"detail": THREAD_REFUSED}, status_code=403)


@app.get("/me/squad")
def my_squad(http: Request):
    """The active squad as get_my_squad reads it (the active FPL team's record, else the user's own); no squad -> null."""
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    import model_tools
    uid = int(user["user_id"])
    with config_roles.acting_user(uid):
        out = model_tools.get_my_squad(user_id=uid)
    if isinstance(out, dict) and out.get("no_squad"):
        return {"squad": None}
    if not isinstance(out, dict) or "error" in out:
        print(f"  [/me/squad of user {uid}: {str((out or {}).get('error') if isinstance(out, dict) else out)[:200]}]")
        return JSONResponse({"detail": "your squad could not be read; please try again shortly"}, status_code=503)
    return {"squad": out}


# ---- the imported FPL teams (Prompt F1a Part 5). The token is checked BEFORE the input (a request without a valid token
# is 401 whatever it carries; off mode is 404), so the ids and the body are validated by hand, not by FastAPI. ----------

TEAM_NOT_FOUND = "team not found for this user"
TOO_MANY_TEAMS = "You can add up to 3 teams"             # Prompt W3 (USER DECISION 5 Nov: 3 teams per user), the page's wording
TEAM_ID_INVALID = "fpl_team_id must be an integer from 1 to 99,999,999"
LABEL_INVALID = "label must be text of at most 40 characters"
IMPORTS_LIMITED = f"rate limit: at most {users.IMPORTS_PER_MINUTE} team imports or refreshes a minute; please wait a moment"
_DIGITS = re.compile(r"^[0-9]{1,8}$")


class _Bad(Exception):
    """Invalid input for a team endpoint: 422 with this text (raised after the token check)."""


def _team_id(value, path=False):
    """An FPL team id (1..99,999,999): a JSON integer in a body, ASCII digits in a path (path=True); else _Bad."""
    if path and isinstance(value, str) and _DIGITS.match(value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 99_999_999:
        raise _Bad(TEAM_ID_INVALID)
    return value


def _import_refusal(e):
    """An import / refresh / activate failure as its HTTP answer (nothing was written in any of them), else None."""
    import fpl_import
    import fpl_teams
    if isinstance(e, fpl_import.FplNotFound):
        return JSONResponse({"detail": "FPL team not found"}, status_code=404)
    if isinstance(e, fpl_import.FplUnavailable):
        print(f"  [FPL import: {e}]")
        return JSONResponse({"detail": "FPL could not be reached; nothing was saved. Please try again shortly."},
                            status_code=503)
    if isinstance(e, fpl_import.ImportRefused):
        return JSONResponse({"detail": str(e)}, status_code=409)
    if isinstance(e, fpl_teams.AlreadyAdded):
        return JSONResponse({"detail": "this FPL team is already added; refresh it instead"}, status_code=409)
    if isinstance(e, fpl_teams.TooManyTeams):
        return JSONResponse({"detail": TOO_MANY_TEAMS}, status_code=409)
    if isinstance(e, fpl_teams.TeamNotFound):
        return JSONResponse({"detail": TEAM_NOT_FOUND}, status_code=404)
    if isinstance(e, ValueError):                       # fpl_import.build: the squad is not legal here
        return JSONResponse({"detail": f"the imported squad could not be saved: {str(e)[:300]}"}, status_code=409)
    return None


def _team_call(http, work, imports=False):
    """The signed-in user (404 off mode / 401 / 503 / 429 as _account), then the input (`work()` -> (fn, args); 422 on
    _Bad), the import window for imports and refreshes, then fn(user_id, *args) with the known refusals answered."""
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    try:
        fn, args = work()
    except _Bad as e:
        return JSONResponse({"detail": str(e)}, status_code=422)
    if imports and users.imports_limited(user):
        return JSONResponse({"detail": IMPORTS_LIMITED}, status_code=429)
    try:
        return fn(int(user["user_id"]), *args)
    except Exception as e:                              # noqa: BLE001 -- the known refusals answered; anything else raises
        answer = _import_refusal(e)
        if answer is None:
            raise
        return answer


@app.get("/me/teams")
def my_teams(http: Request):
    """Prompt W3: each team as a Home card -- the F1a fields plus the stored score summary and last_used_at (fpl_teams.CARD_COLS)."""
    import fpl_teams
    return _team_call(http, lambda: (fpl_teams.team_cards, ()))


@app.post("/me/teams")
def add_team(http: Request, payload: Any = Body(default=None)):
    import fpl_teams

    def work():
        body = payload if isinstance(payload, dict) else {}
        label = body.get("label")
        if label is not None and (not isinstance(label, str) or len(label.strip()) > 40):
            raise _Bad(LABEL_INVALID)
        return fpl_teams.add_team, (_team_id(body.get("fpl_team_id")), label)
    return _team_call(http, work, imports=True)


def _cancel_tickets(user_id):
    import db_write
    conn = db_write.connect()
    try:
        squad_previews.ensure_schema(conn)
        return squad_previews.cancel_for_user(conn, user_id)
    finally:
        conn.close()


def _activate(user_id, fpl_team_id):
    """Prompt F1b: the team made active, then a NEW default thread bound to it (the old threads stay the user's and readable;
    a /chat in one of another team gets 409) and the user's open preview tickets cancelled (a ticket names a version of the
    team it was issued for). Prompt W3: activating the team that is ALREADY active (Home's "Ask about this team" on the
    team in use) keeps its default thread and its tickets -- only last_used_at moves (fpl_teams.activate sets it)."""
    import fpl_teams
    current = fpl_teams.active_team(user_id)
    already = current is not None and int(current["fpl_team_id"]) == int(fpl_team_id)
    team = fpl_teams.activate(user_id, fpl_team_id)
    if already:
        return {**team, "thread_id": threads.default_thread(user_id), "preview_tickets_cancelled": 0}
    threads.start_new_default(user_id)
    thread_id = threads.default_thread(user_id)
    return {**team, "thread_id": thread_id, "preview_tickets_cancelled": _cancel_tickets(user_id)}


def _deactivate(user_id):
    """Prompt W3 ("general / no team" mode): no team active -> the squad tools read the user's own record (zero-team behaviour),
    a NEW default thread bound to the user's own id, the open preview tickets cancelled. With no team active already: nothing
    changes (the current default thread, 0 cancelled)."""
    import fpl_teams
    was = fpl_teams.deactivate(user_id)
    if was is None:
        return {"active_team": None, "deactivated": None, "thread_id": threads.default_thread(user_id), "preview_tickets_cancelled": 0}
    threads.start_new_default(user_id)
    thread_id = threads.default_thread(user_id)
    return {"active_team": None, "deactivated": was, "thread_id": thread_id, "preview_tickets_cancelled": _cancel_tickets(user_id)}


@app.post("/me/teams/{fpl_team_id}/activate")
def activate_team(fpl_team_id: str, http: Request):
    return _team_call(http, lambda: (_activate, (_team_id(fpl_team_id, path=True),)))


@app.delete("/me/active-team")
def clear_active_team(http: Request):
    return _team_call(http, lambda: (_deactivate, ()))


FPL_DOWN = "FPL could not be reached for the deadlines; please try again shortly"


DEADLINES_CACHE = "public, max-age=60"


@app.get("/deadlines")
def deadlines(http: Request):
    """Prompt W3: the upcoming gameweek deadlines from FPL's bootstrap (fpl_import.bootstrap, cached BOOTSTRAP_TTL_S per
    process): {"events": [{gw, deadline_time, finished}, ...soonest first], "fetched_at"}. Prompt W5 (checkpoint Q1 A): OPEN
    in clerk mode -- public FPL data only, no token needed (one is ignored), no user and no read counted -- so the About
    page's chips can name the next gameweek for a signed-out visitor; off mode 404 as before."""
    if auth.mode() != "clerk":
        return JSONResponse(NOT_FOUND, status_code=404)
    import fpl_import
    try:
        boot = fpl_import.bootstrap()
    except fpl_import.FplUnavailable as e:
        print(f"  [/deadlines: {e}]")
        return JSONResponse({"detail": FPL_DOWN}, status_code=503)
    return JSONResponse({"events": fpl_import.upcoming_events(boot), "fetched_at": threads.iso(fpl_import.clock())},
                        headers={"Cache-Control": DEADLINES_CACHE})


@app.post("/me/teams/{fpl_team_id}/refresh")
def refresh_team(fpl_team_id: str, http: Request):
    import fpl_teams
    return _team_call(http, lambda: (fpl_teams.refresh_team, (_team_id(fpl_team_id, path=True),)), imports=True)


# ---- the Chat page (Prompt W4, 2026-11-06): the team card and the answer feedback ---------------------------------------------

SQUAD_UNREADABLE = "this team's squad could not be read; please try again shortly"
MESSAGE_NOT_FOUND = "message not found for this user"
SCORE_INVALID = 'score must be "up", "down" or null'


def _card(user_id, fpl_team_id):
    import squad_store
    import team_card
    try:
        return team_card.build(user_id, fpl_team_id)
    except team_card.TeamNotFound:
        return JSONResponse({"detail": TEAM_NOT_FOUND}, status_code=404)
    except squad_store.SquadStateError as e:
        print(f"  [team card of {fpl_team_id} for user {user_id}: {str(e)[:200]}]")
        return JSONResponse({"detail": SQUAD_UNREADABLE}, status_code=503)


@app.get("/me/teams/{fpl_team_id}/card")
def team_card_route(fpl_team_id: str, http: Request):
    """Data 4: the Chat page's team card for any of the user's teams (opening a chat is read-only -- the team is activated on
    send). Reads count against the 60-a-minute window; FPL is read through the single-flight cache (team_card)."""
    return _team_call(http, lambda: (_card, (_team_id(fpl_team_id, path=True),)))


@app.post("/messages/{message_id}/feedback")
def message_feedback(message_id: str, http: Request, payload: Any = Body(default=None)):
    """Data 5: {"score": "up" | "down" | null} on one of the user's own answers (else 404, nothing written): the row first,
    then the Langfuse score (best effort: "sent" | "skipped" | "failed"); the messages endpoint returns it again."""
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    body = payload if isinstance(payload, dict) else {}
    if "score" not in body or body["score"] not in ("up", "down", None):
        return JSONResponse({"detail": SCORE_INVALID}, status_code=422)
    import chat_messages
    row = chat_messages.set_feedback(int(user["user_id"]), message_id, body["score"])
    if row is None:
        return JSONResponse({"detail": MESSAGE_NOT_FOUND}, status_code=404)
    value = row["feedback"] or "none"
    status = tracing.score_feedback(tracing.trace_id_for(message_id), value,
                                    comment="cleared by the user" if row["feedback"] is None else None)
    return {"message_id": message_id, "feedback": row["feedback"], "feedback_at": threads.iso(row["feedback_at"]), "langfuse": status}


@app.get("/threads")
def list_threads(http: Request):
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    return threads.list_threads(int(user["user_id"]))


@app.post("/threads")
def new_thread(http: Request):
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    return {"thread_id": threads.create_thread(int(user["user_id"]))}


@app.get("/threads/{thread_id}/messages")
def thread_messages(thread_id: str, http: Request):
    user, refusal = _account(http)
    if refusal is not None:
        return refusal
    if threads.owner(thread_id) != int(user["user_id"]):        # another user's or no such thread: the same answer
        return JSONResponse({"detail": THREAD_REFUSED}, status_code=403)
    return agent_graph.thread_messages(thread_id)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")
