"""Prompt W9 (2026-11-12): GUEST MODE -- "Continue as guest" on the login page; a guest is signed out and ALL their data
deleted when they close the app (desktop) or after GUEST_IDLE_MINUTES idle. USER DECISIONS (11-12 Nov): guests can use
everything a signed-in user can; one guest session spends at most GUEST_CAP_USD; all guests together at most
GUEST_DAILY_BUDGET_USD per UTC day; at most GUEST_STARTS_PER_IP_PER_DAY starts per IP per UTC day; GUEST_MODE=on|off is an
emergency brake (off: new starts and guest turns refused with UNAVAILABLE, every guest ended within one sweep).

A guest is a real Clerk user this module creates with the Backend API (a synthetic address on GUEST_DOMAIN -- our own
subdomain, nothing mailable -- public_metadata.guest = true, no password) and signs in with a one-time sign-in token
(the website's card: signIn.ticket). Every page, token check, cap and limit then works unchanged: users.user_for_claims
makes the row a guest on first sight (is_guest, sign_in_method 'guest', daily_cap_usd = the guest cap).

Leaving: the client pings POST /me/ping while the user interacts (<= once a minute; also on load and when a tab becomes
visible) and, on a DESKTOP, sends POST /me/leave when the last tab closes (phones send no leave: backgrounding is not
closing -- checkpoint Q1). The reaper (sweep, every REAPER_EVERY_S from the app's lifespan, clerk mode only) deletes a
guest whose leave is older than LEAVE_GRACE_S with no ping since, or whose last ping is older than GUEST_IDLE_MINUTES +
SERVER_IDLE_SLACK_S (the client itself deletes at exactly GUEST_IDLE_MINUTES: the reaper is the backstop for a crashed
tab); unclaimed starts lose their Clerk user after UNCLAIMED_AFTER_S; IP hashes are dropped after IP_HASH_KEEP, start rows
after STARTS_KEEP.

DELETION SAFETY (overrides everything): only a row that is a guest in OUR database (is_guest, user_id >= FIRST_NEW_USER_ID,
never the owner) AND at Clerk (public_metadata.guest = true re-read at delete time; a 404 = already gone) is ever deleted
automatically, always through deletion.delete_account (one transaction, Clerk inside). A DB row flagged guest whose Clerk
user is not a guest is skipped and printed, never deleted. Database now() / users.clock() only -- never a client clock.

The IP (checkpoint Q6): X-Forwarded-For is trusted ONLY when the direct peer is the Caddy container (TRUSTED_PROXY_HOSTS,
default the compose service name fpl-caddy, resolved and cached); any other peer -- a direct :8000 caller -- counts as its
own address whatever it forwards. Stored only as a salted hash (the salt derives from APP_API_KEY) for IP_HASH_KEEP.

Guests' anonymised cost rows carry turn_id 'deleted-guest' (deletion.delete_account(guest=True)), so Admin shows them apart
from deleted real accounts and today's rows keep counting against the guest budget. Off mode: nothing here runs (main.py's
routes answer 404 there; the reaper thread is never started)."""
import hashlib
import os
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import psycopg2.extras
import requests

import db_write
import users

MODE_ENV = "GUEST_MODE"
IDLE_ENV, CAP_ENV, BUDGET_ENV, PER_IP_ENV = "GUEST_IDLE_MINUTES", "GUEST_CAP_USD", "GUEST_DAILY_BUDGET_USD", "GUEST_STARTS_PER_IP_PER_DAY"
TRUSTED_PROXY_ENV = "TRUSTED_PROXY_HOSTS"
DEFAULT_IDLE_MINUTES = 30
DEFAULT_CAP_USD = 0.25
DEFAULT_BUDGET_USD = 3.00
DEFAULT_STARTS_PER_IP = 3
DEFAULT_TRUSTED_PROXIES = "fpl-caddy"
LEAVE_GRACE_S = 120                        # a refresh or a closed last tab: the ping after a leave within this cancels it
TICKET_TTL_S = 600                         # the sign-in token's life
UNCLAIMED_AFTER_S = 600                    # a start never signed in: its Clerk user goes
SERVER_IDLE_SLACK_S = 60                   # the reaper's idle rule runs this much after the client's own 30:00 delete
REAPER_EVERY_S = 60
PROXY_CACHE_S = 60.0
IP_HASH_KEEP = timedelta(hours=24)
STARTS_KEEP = timedelta(days=7)
GUEST_DOMAIN = "guest.fplcopilot.app"
USER_AGENT = "fpl-copilot/guest (+https://fplcopilot.app)"    # Clerk's edge answers 403 to the default Python agents

UNAVAILABLE = "Guest mode is unavailable"
IP_LIMIT = "Guest limit reached for today on this network — sign in with Google or email to keep going"
BUDGET_FULL = "Guest mode is full for today — sign in to continue"
CAP_REACHED = "Guest limit reached — sign in with Google or email to keep going"

DDL = """
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_guest           BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS guest_started_at   TIMESTAMPTZ;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS guest_last_seen_at TIMESTAMPTZ;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS guest_left_at      TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS guest_starts (
    id            BIGSERIAL   PRIMARY KEY,
    ip_hash       TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    clerk_user_id TEXT        UNIQUE,
    claimed_at    TIMESTAMPTZ,
    user_id       INT,
    ended_at      TIMESTAMPTZ,
    end_reason    TEXT,
    cap_hits      INT         NOT NULL DEFAULT 0,
    budget_hits   INT         NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_guest_starts_ip ON guest_starts (ip_hash, started_at);
CREATE INDEX IF NOT EXISTS ix_guest_starts_user ON guest_starts (user_id);
"""

_PROXY_CACHE = {}
_SALT_FALLBACK = secrets.token_hex(16)


class GuestRefused(Exception):
    """A start that must be refused: .status (403 / 429), .code, .detail."""

    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class ClerkFailed(Exception):
    """Clerk's Backend API did not do what a guest needs (create / token); nothing half-made is left behind."""


# ---- configuration ------------------------------------------------------------------------------------------------------------

def enabled():
    return (os.environ.get(MODE_ENV) or "").strip().lower() == "on"


def _number(env, default, kind=float):
    try:
        v = kind(os.environ.get(env, "") or default)
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


def idle_minutes():
    return _number(IDLE_ENV, DEFAULT_IDLE_MINUTES, int)


def cap_usd():
    return _number(CAP_ENV, DEFAULT_CAP_USD)


def daily_budget_usd():
    return _number(BUDGET_ENV, DEFAULT_BUDGET_USD)


def starts_per_ip():
    return _number(PER_IP_ENV, DEFAULT_STARTS_PER_IP, int)


def status():
    return {"enabled": enabled(), "idle_minutes": idle_minutes(), "cap_usd": cap_usd(), "leave_grace_seconds": LEAVE_GRACE_S}


def clock():
    return users.clock()


def _midnight(now):
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def ensure_schema(conn=None):
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
    finally:
        if own:
            conn.close()


# ---- the client's address (checkpoint Q6) ------------------------------------------------------------------------------------

def _resolve(host):
    try:
        return socket.gethostbyname_ex(host)[2]
    except OSError:
        return []


def trusted_proxy_ips():
    """The addresses X-Forwarded-For is trusted from: TRUSTED_PROXY_HOSTS (names resolved, cached PROXY_CACHE_S; literal
    addresses as they are)."""
    hosts = [h.strip() for h in (os.environ.get(TRUSTED_PROXY_ENV) or DEFAULT_TRUSTED_PROXIES).split(",") if h.strip()]
    now = time.monotonic()
    out = set()
    for h in hosts:
        if h.replace(".", "").replace(":", "").isalnum() and any(ch.isdigit() for ch in h) and not any(ch.isalpha() for ch in h):
            out.add(h)                                   # a literal address
            continue
        cached = _PROXY_CACHE.get(h)
        if cached is None or now - cached[0] > PROXY_CACHE_S:
            cached = (now, set(_resolve(h)))
            _PROXY_CACHE[h] = cached
        out |= cached[1]
    return out


def client_ip_of(peer, headers):
    """The address a request counts as: the first X-Forwarded-For hop when the direct peer is a trusted proxy, else the
    peer itself."""
    peer = (peer or "").strip() or "unknown"
    if peer in trusted_proxy_ips():
        xff = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xff:
            return xff
    return peer


def client_ip(request):
    return client_ip_of(request.client.host if request.client else "", request.headers)


def ip_hash(ip):
    salt = (os.environ.get("APP_API_KEY") or "").strip() or _SALT_FALLBACK
    return hashlib.sha256(f"{salt}|{ip}".encode("utf-8")).hexdigest()[:32]


# ---- Clerk's Backend API (faked in the tests) ----------------------------------------------------------------------------------

def _secret():
    s = (os.environ.get("CLERK_SECRET_KEY") or "").strip()
    if not s:
        raise ClerkFailed("CLERK_SECRET_KEY is not set")
    return s


def _headers():
    return {"Authorization": f"Bearer {_secret()}", "Content-Type": "application/json", "User-Agent": USER_AGENT}


def clerk_create_user(address, metadata):
    r = requests.post(f"{users.BACKEND_API}/users", headers=_headers(), timeout=15,
                      json={"email_address": [address], "skip_password_requirement": True, "public_metadata": metadata, "first_name": "Guest"})
    if r.status_code != 200:
        raise ClerkFailed(f"create user: HTTP {r.status_code} {r.text[:160]}")
    return r.json()["id"]


def clerk_sign_in_token(clerk_user_id, ttl_s):
    r = requests.post(f"{users.BACKEND_API}/sign_in_tokens", headers=_headers(), timeout=15,
                      json={"user_id": clerk_user_id, "expires_in_seconds": int(ttl_s)})
    if r.status_code != 200:
        raise ClerkFailed(f"sign-in token: HTTP {r.status_code} {r.text[:160]}")
    return r.json()["token"]


def clerk_get_user(clerk_user_id):
    """The Clerk user object, or None when Clerk no longer has it (404). Anything else raises ClerkFailed."""
    r = requests.get(f"{users.BACKEND_API}/users/{clerk_user_id}", headers=_headers(), timeout=10)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise ClerkFailed(f"get user: HTTP {r.status_code}")
    return r.json()


def is_guest_profile(profile):
    return bool(profile.get("guest")) if profile else False


def clerk_user_is_guest(user_obj):
    return bool(((user_obj or {}).get("public_metadata") or {}).get("guest"))


# ---- starting ------------------------------------------------------------------------------------------------------------------

def starts_today(hashed, conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM guest_starts WHERE ip_hash = %s AND started_at >= %s", (hashed, _midnight(clock())))
        return int(cur.fetchone()[0])


def budget_used_today(conn=None):
    """Today's guest spend in USD: the live guests' rows + today's anonymised deleted-guest rows (never a real user's)."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT COALESCE(SUM(usd), 0) FROM chat_usage
                           WHERE ts >= %s AND (turn_id = 'deleted-guest'
                                               OR user_id IN (SELECT user_id FROM app_users WHERE is_guest))""", (_midnight(clock()),))
            return float(cur.fetchone()[0])
    finally:
        if own:
            conn.close()


def budget_open(conn=None):
    return budget_used_today(conn) < daily_budget_usd()


def start(ip, conn=None):
    """POST /guest/start: the switch, the per-IP limit, the daily budget, then the Clerk user + the sign-in token + the
    start row. Returns {ticket, expires_in_seconds}; GuestRefused (403 / 429) before anything is made; ClerkFailed after
    the half-made Clerk user was deleted again."""
    if not enabled():
        raise GuestRefused(403, "guest_off", UNAVAILABLE)
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        hashed = ip_hash(ip)
        if starts_today(hashed, conn) >= starts_per_ip():
            raise GuestRefused(429, "guest_ip_limit", IP_LIMIT)
        if not budget_open(conn):
            raise GuestRefused(429, "guest_budget", BUDGET_FULL)
        address = f"guest-{secrets.token_hex(6)}@{GUEST_DOMAIN}"
        started = clock()
        cid = clerk_create_user(address, {"guest": True, "started_at": started.isoformat()})
        try:
            ticket = clerk_sign_in_token(cid, TICKET_TTL_S)
        except Exception:
            try:
                users.delete_clerk_user(cid)
            except Exception as e:                       # noqa: BLE001 -- reported; the unclaimed clean-up would catch it anyway
                print(f"  [guest start: Clerk user {cid} could not be removed after the token failed: {e}]")
            raise
        with conn.cursor() as cur:
            cur.execute("INSERT INTO guest_starts (ip_hash, started_at, clerk_user_id) VALUES (%s, %s, %s)", (hashed, started, cid))
        conn.commit()
        return {"ticket": ticket, "expires_in_seconds": TICKET_TTL_S}
    finally:
        if own:
            conn.close()


def claim(clerk_user_id, user_id, cur):
    """The first signed-in request of a started guest: the start row learns its user (same transaction as the row)."""
    cur.execute("UPDATE guest_starts SET claimed_at = now(), user_id = %s WHERE clerk_user_id = %s AND claimed_at IS NULL",
                (int(user_id), clerk_user_id))
    return cur.rowcount


# ---- the session's signals -----------------------------------------------------------------------------------------------------

def ping(user_id, conn=None):
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_users SET guest_last_seen_at = %s, guest_left_at = NULL WHERE user_id = %s AND is_guest",
                        (clock(), int(user_id)))
        conn.commit()
    finally:
        if own:
            conn.close()


def leave(user_id, conn=None):
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_users SET guest_left_at = COALESCE(guest_left_at, %s) WHERE user_id = %s AND is_guest",
                        (clock(), int(user_id)))
        conn.commit()
    finally:
        if own:
            conn.close()


def record_hit(user_id, kind, conn=None):
    """A guest refusal (kind 'cap' or 'budget') counted on the start row -- it survives the guest's deletion for Admin."""
    col = "cap_hits" if kind == "cap" else "budget_hits"
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE guest_starts SET {col} = {col} + 1 WHERE user_id = %s", (int(user_id),))
        conn.commit()
    finally:
        if own:
            conn.close()


def me_block(user, conn=None):
    """GET /me's `guest` object for a guest row; None for anyone else."""
    if not user.get("is_guest"):
        return None
    return {"idle_minutes": idle_minutes(), "leave_grace_seconds": LEAVE_GRACE_S, "cap_usd": users.cap_for(user),
            "spent_usd": round(users.spent_today(user["user_id"], conn), 6), "budget_open": budget_open(conn)}


# ---- the reaper -----------------------------------------------------------------------------------------------------------------

def candidates(conn, now):
    """(user row, reason) for every guest whose session is over by the rule in the module docstring; with the switch off,
    every guest ('switch_off')."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if not enabled():
            cur.execute("SELECT * FROM app_users WHERE is_guest AND user_id >= %s AND user_id <> %s ORDER BY user_id",
                        (users.FIRST_NEW_USER_ID, users.OWNER_USER_ID))
            return [(dict(r), "switch_off") for r in cur.fetchall()]
        cur.execute("""
            SELECT *,
                   (guest_left_at IS NOT NULL AND guest_left_at < %(leave_before)s
                    AND (guest_last_seen_at IS NULL OR guest_last_seen_at <= guest_left_at))            AS left_for_good,
                   (COALESCE(guest_last_seen_at, guest_started_at, created_at) < %(idle_before)s)        AS idle_for_good
            FROM app_users
            WHERE is_guest AND user_id >= %(min)s AND user_id <> %(owner)s
            ORDER BY user_id""",
                    {"leave_before": now - timedelta(seconds=LEAVE_GRACE_S),
                     "idle_before": now - timedelta(minutes=idle_minutes(), seconds=SERVER_IDLE_SLACK_S),
                     "min": users.FIRST_NEW_USER_ID, "owner": users.OWNER_USER_ID})
        out = []
        for r in cur.fetchall():
            r = dict(r)
            left, idle = r.pop("left_for_good"), r.pop("idle_for_good")
            if left:
                out.append((r, "left"))
            elif idle:
                out.append((r, "idle"))
        return out


def sweep(conn=None, now=None):
    """One reaper pass: {deleted: [{user_id, reason, clerk}], skipped: [{user_id, why}], unclaimed_deleted, pruned}."""
    import deletion
    own = conn is None
    if own:
        conn = db_write.connect()
    now = now or clock()
    out = {"deleted": [], "skipped": [], "unclaimed_deleted": 0, "pruned": 0}
    try:
        for row, reason in candidates(conn, now):
            uid = int(row["user_id"])
            if not users.deletable(row):                 # belt and braces: the owner / a reserved id can never get here
                out["skipped"].append({"user_id": uid, "why": "not deletable"})
                continue
            try:
                at_clerk = clerk_get_user(row["clerk_user_id"]) if row.get("clerk_user_id") else None
            except ClerkFailed as e:
                out["skipped"].append({"user_id": uid, "why": f"clerk unreachable: {e}"})
                continue
            if at_clerk is not None and not clerk_user_is_guest(at_clerk):
                print(f"  [guest reaper: user {uid} is flagged guest here but NOT at Clerk -- left alone]", flush=True)
                out["skipped"].append({"user_id": uid, "why": "clerk metadata is not guest"})
                continue
            try:
                res = deletion.delete_account(row, guest=True, guest_reason=reason)
                out["deleted"].append({"user_id": uid, "reason": reason, "clerk": res.get("clerk")})
            except Exception as e:                       # noqa: BLE001 -- one bad row must not stop the sweep
                print(f"  [guest reaper: user {uid} not deleted: {type(e).__name__}: {str(e)[:160]}]", flush=True)
                out["skipped"].append({"user_id": uid, "why": f"delete failed: {type(e).__name__}"})
        # unclaimed starts: the Clerk user nobody ever signed in with
        with conn.cursor() as cur:
            cur.execute("SELECT id, clerk_user_id FROM guest_starts WHERE claimed_at IS NULL AND ended_at IS NULL "
                        "AND clerk_user_id IS NOT NULL AND started_at < %s", (now - timedelta(seconds=UNCLAIMED_AFTER_S),))
            stale = cur.fetchall()
        for sid, cid in stale:
            try:
                users.delete_clerk_user(cid)
            except Exception as e:                       # noqa: BLE001 -- try again next sweep
                print(f"  [guest reaper: unclaimed Clerk user {cid} not deleted: {e}]")
                continue
            with conn.cursor() as cur:
                cur.execute("UPDATE guest_starts SET ended_at = %s, end_reason = 'unclaimed' WHERE id = %s", (now, sid))
            conn.commit()
            out["unclaimed_deleted"] += 1
        with conn.cursor() as cur:
            cur.execute("UPDATE guest_starts SET ip_hash = NULL WHERE ip_hash IS NOT NULL AND started_at < %s", (now - IP_HASH_KEEP,))
            cur.execute("DELETE FROM guest_starts WHERE started_at < %s", (now - STARTS_KEEP,))
            out["pruned"] = cur.rowcount
        conn.commit()
        return out
    finally:
        if own:
            conn.close()


_REAPER = {"thread": None, "stop": None}


def _loop(stop):
    while not stop.wait(REAPER_EVERY_S):
        try:
            res = sweep()
            if res["deleted"] or res["skipped"] or res["unclaimed_deleted"]:
                print(f"  [guest reaper: {res}]", flush=True)
        except Exception as e:                           # noqa: BLE001 -- the loop must survive a bad tick
            print(f"  [guest reaper: sweep failed: {type(e).__name__}: {str(e)[:160]}]", flush=True)


def start_reaper():
    """The background sweep (main.py's lifespan, clerk mode only). Idempotent."""
    if _REAPER["thread"] is not None and _REAPER["thread"].is_alive():
        return
    stop = threading.Event()
    t = threading.Thread(target=_loop, args=(stop,), name="guest-reaper", daemon=True)
    _REAPER.update(thread=t, stop=stop)
    t.start()


def stop_reaper():
    if _REAPER["stop"] is not None:
        _REAPER["stop"].set()
    _REAPER.update(thread=None, stop=None)
