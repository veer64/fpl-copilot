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
import time
from collections import deque

from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import admin                                            # Prompt P7: the admin dashboard + users CSV (clerk mode)
import agent_graph                                      # Prompt B: /chat turns run in stored threads
import auth                                             # Prompt P7: AUTH_MODE, Clerk session tokens
import config_roles
import squad_previews                                   # Prompt E (2026-10-27): /reset cancels the user's preview tickets
import threads                                         # Prompt B (2026-10-31): per-user threads, the checkpointer
import tracing                                          # Prompt L (2026-10-30): Langfuse traces, flushed on shutdown
import users                                            # Prompt P7: app_users (clerk mode only)


AUTHORIZED_PARTIES_MISSING = ("startup refused: AUTH_MODE=clerk needs CLERK_AUTHORIZED_PARTIES (the website's origins, "
                              "comma-separated); with none listed no session token could ever be accepted")


@contextlib.asynccontextmanager
async def _lifespan(app):
    if auth.mode() == "clerk" and not auth.authorized_parties():     # Prompt F1a: azp is required, so a list is too
        print(f"  [{AUTHORIZED_PARTIES_MISSING}]", flush=True)
        raise RuntimeError(AUTHORIZED_PARTIES_MISSING)
    yield
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
                ("GET", "/me/squad"), ("GET", "/me/teams"), ("POST", "/me/teams")}
CLERK_ROUTE_PATTERNS = [("GET", re.compile(r"^/threads/[^/]+/messages$")),
                        ("POST", re.compile(r"^/me/teams/[^/]+/(activate|refresh)$"))]


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


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if (request.method, request.url.path) in OPEN_ENDPOINTS:
        return await call_next(request)
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
TOKEN_REFUSED = "missing or invalid session token"
PROFILE_UNAVAILABLE = "your account profile could not be loaded; please try again shortly"
RATE_LIMITED = f"rate limit: at most {users.RATE_LIMIT_PER_MINUTE} messages a minute; please wait a moment"


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
    if users.rate_limited(user):                        # Prompt P7 Part 2: 10 a minute per user (exempt: never)
        return JSONResponse({"detail": RATE_LIMITED}, status_code=429)
    refused, reply = users.capped(user)                 # $1/day per user (exempt: never): no model call, a cap_hits row
    if refused:
        return {"answer": reply, "thread_id": request.thread_id, "capped": True}
    with config_roles.acting_user(user_id):             # every tool, ticket and trace of the turn answers for this user
        try:
            thread_id = threads.resolve(user_id, request.thread_id)
        except threads.ThreadRefused:
            return JSONResponse({"detail": THREAD_REFUSED}, status_code=403)
        answer = agent_graph.run_thread_turn(user_id, thread_id, request.message)
    return {"answer": answer, "thread_id": thread_id}


@app.post("/chat")
def chat(request: ChatRequest, http: Request):
    if auth.mode() == "clerk":
        return _chat_signed_in(request, http)
    user_id = config_roles.DEFAULT_USER_ID()            # server-side only: never from the request body or the model
    try:
        thread_id = threads.resolve(user_id, request.thread_id)
    except threads.ThreadRefused:                       # another user's thread (or none): refused before any model call
        return JSONResponse({"detail": THREAD_REFUSED}, status_code=403)
    answer = agent_graph.run_thread_turn(user_id, thread_id, request.message)
    return {"answer": answer, "thread_id": thread_id}


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
    return {"user_id": uid, "is_admin": bool(user.get("is_admin")), "daily_cap_usd": users.cap_for(user),
            "spent_today_usd": round(users.spent_today(uid), 6), "active_team": _active_team(uid)}


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
        return JSONResponse({"detail": f"at most {fpl_teams.MAX_TEAMS} FPL teams per user"}, status_code=409)
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
    import fpl_teams
    return _team_call(http, lambda: (fpl_teams.list_teams, ()))


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


@app.post("/me/teams/{fpl_team_id}/activate")
def activate_team(fpl_team_id: str, http: Request):
    import fpl_teams
    return _team_call(http, lambda: (fpl_teams.activate, (_team_id(fpl_team_id, path=True),)))


@app.post("/me/teams/{fpl_team_id}/refresh")
def refresh_team(fpl_team_id: str, http: Request):
    import fpl_teams
    return _team_call(http, lambda: (fpl_teams.refresh_team, (_team_id(fpl_team_id, path=True),)), imports=True)


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
