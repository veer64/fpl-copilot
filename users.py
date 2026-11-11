"""App users (Prompt P7, 2026-11-01): one row per signed-in Clerk user, keyed by the INTEGER user_id every table already uses
(squad_versions, chat_threads, squad_previews, ...). Used only in AUTH_MODE=clerk (auth.py); in off mode nothing here runs.

- A row is created on the user's first authenticated request, from their profile on Clerk's Backend API
  (GET https://api.clerk.com/v1/users/{id}, CLERK_SECRET_KEY; no webhook), and the profile is refreshed at most once a day
  (PROFILE_MAX_AGE; a failed refresh keeps the old one). A NEW user whose profile cannot be fetched is refused (503) and
  nothing is written, so the admin link below is never decided on a missing profile.
- New users get ids from FIRST_NEW_USER_ID (10001) up, from their own sequence: they collide with nothing that exists
  (user 1, the eval users 9001 / 9002 -- RESERVED_USER_IDS -- and every other id in use is below it).
- The admin link: the FIRST sign-in whose primary email is VERIFIED and equals ADMIN_EMAIL (case-insensitive) is mapped to
  the existing user 1 (is_admin, is_exempt). An unverified email never links; once user 1 is linked, a second account with
  the same email is an ordinary new user.
- sign_in_method: "google" when the account has a Google external account (oauth_google), else "email" (password, email
  code or email link: the Clerk free plan's other methods); "other" when there is no email at all.
Measured on the dev instance 1 Nov: the user object carries primary_email_address_id, email_addresses[].email_address /
.verification.status ("verified"), first_name, last_name, external_accounts[].provider, created_at in ms.

LIMITS (Prompt P7 Part 2; USER DECISION 1 Nov: "Daily cap" = $1/day per user, the admin is exempt). Before each signed-in
/chat turn (main.py): more than RATE_LIMIT_PER_MINUTE requests in a rolling minute -> 429; the user's chat_usage cost since
00:00 UTC (chat_usage.user_id, written with every signed-in turn) >= their cap (app_users.daily_cap_usd, else DAILY_CAP_USD,
default 1.00) -> the cap_reply() text with HTTP 200, no model call, a cap_hits row. is_exempt users skip both. A turn
already running finishes, so a day can end over the cap by at most the cost of one turn per request in flight. The rate
windows are process-local (one app process in production)."""
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import psycopg2.extras

import db_write

FIRST_NEW_USER_ID = 10001
RESERVED_USER_IDS = (1, 9001, 9002)
OWNER_USER_ID = 1                                        # Prompt W5: the owner = the row the ADMIN_EMAIL link maps to (user 1)
PROFILE_MAX_AGE = timedelta(days=1)
BACKEND_API = "https://api.clerk.com/v1"
DAILY_CAP_ENV = "DAILY_CAP_USD"
DEFAULT_DAILY_CAP_USD = 1.00
RATE_LIMIT_PER_MINUTE = 10
RATE_WINDOW_S = 60.0
READS_PER_MINUTE = 120                                   # Prompt F1a: the website's other endpoints (/me, /threads, ...); W7b: 60 -> 120 (a fast Home / Chat walk is 4 reads a page)
IMPORTS_PER_MINUTE = 5                                   # Prompt F1a: FPL team imports and refreshes (FPL's API is a guest's)
CAP_REPLY = "You've reached today's limit. It resets at 00:00 UTC (in {h} h {m} m)."

DDL = f"""
CREATE SEQUENCE IF NOT EXISTS app_users_user_id_seq START WITH {FIRST_NEW_USER_ID} MINVALUE {FIRST_NEW_USER_ID};
CREATE TABLE IF NOT EXISTS app_users (
    user_id            INT         PRIMARY KEY DEFAULT nextval('app_users_user_id_seq'),
    clerk_user_id      TEXT        UNIQUE,
    email              TEXT,
    name               TEXT,
    sign_in_method     TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at     TIMESTAMPTZ,
    profile_fetched_at TIMESTAMPTZ,
    is_admin           BOOLEAN     NOT NULL DEFAULT FALSE,
    is_exempt          BOOLEAN     NOT NULL DEFAULT FALSE
);
ALTER SEQUENCE app_users_user_id_seq OWNED BY app_users.user_id;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS daily_cap_usd NUMERIC(10, 4);
CREATE TABLE IF NOT EXISTS cap_hits (
    id         SERIAL         PRIMARY KEY,
    user_id    INT            NOT NULL,
    hit_at     TIMESTAMPTZ    NOT NULL DEFAULT now(),
    spent_usd  NUMERIC(12, 6),
    cap_usd    NUMERIC(10, 4)
);
CREATE INDEX IF NOT EXISTS ix_cap_hits_user ON cap_hits (user_id, hit_at);
ALTER TABLE chat_usage ADD COLUMN IF NOT EXISTS user_id INT;
CREATE INDEX IF NOT EXISTS ix_chat_usage_user_ts ON chat_usage (user_id, ts);
"""


class ProfileUnavailable(Exception):
    """Clerk's Backend API did not give us the user's profile."""


class ClerkDeleteFailed(Exception):
    """Prompt W5: Clerk's Backend API did not delete the user (anything but 200 / 404, or unreachable)."""


def is_owner(user):
    """Prompt W5 (B1): the owner account -- user 1, the row the first verified ADMIN_EMAIL sign-in is linked to."""
    return int(user["user_id"]) == OWNER_USER_ID


def deletable(user):
    """Prompt W5 (B2): an account that may delete itself -- never the owner, never a reserved id (anything below
    FIRST_NEW_USER_ID: 1, the eval users 9001 / 9002)."""
    return not is_owner(user) and int(user["user_id"]) >= FIRST_NEW_USER_ID


def delete_clerk_user(clerk_user_id):
    """Prompt W5 (B2): delete the sign-in account at Clerk (DELETE /v1/users/{id}, CLERK_SECRET_KEY). "deleted" on 200,
    "already_gone" on 404 (a retry after a failed commit); ClerkDeleteFailed otherwise -- the caller rolls back."""
    import requests
    secret = (os.environ.get("CLERK_SECRET_KEY") or "").strip()
    if not secret:
        raise ClerkDeleteFailed("CLERK_SECRET_KEY is not set")
    try:
        r = requests.delete(f"{BACKEND_API}/users/{clerk_user_id}", headers={"Authorization": f"Bearer {secret}"}, timeout=15)
    except Exception as e:                               # noqa: BLE001
        raise ClerkDeleteFailed(f"Clerk unreachable: {type(e).__name__}") from e
    if r.status_code == 200:
        return "deleted"
    if r.status_code == 404:
        return "already_gone"
    raise ClerkDeleteFailed(f"Clerk answered {r.status_code}")


_WINDOWS = {}                                            # user_id -> deque of monotonic request times (the last minute)
_READ_WINDOWS = {}                                       # the same, for reads_limited (Prompt F1a): its own window
_IMPORT_WINDOWS = {}                                     # the same, for imports_limited (Prompt F1a)
_WINDOWS_LOCK = threading.Lock()


def clock():
    return datetime.now(timezone.utc)


def monotonic():
    return time.monotonic()


def _reset():
    """Forget the rate-limit windows (tests only)."""
    with _WINDOWS_LOCK:
        _WINDOWS.clear()
        _READ_WINDOWS.clear()
        _IMPORT_WINDOWS.clear()


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


def _profile_from(u):
    """{email, email_verified, name, sign_in_method} from a Backend API user object."""
    emails = u.get("email_addresses") or []
    primary = next((e for e in emails if e.get("id") == u.get("primary_email_address_id")), emails[0] if emails else None)
    email = (primary or {}).get("email_address")
    verified = ((primary or {}).get("verification") or {}).get("status") == "verified"
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u.get("username") or None
    providers = {str(x.get("provider") or "") for x in (u.get("external_accounts") or [])}
    method = "google" if providers & {"oauth_google", "google"} else ("email" if email else "other")
    return {"email": email, "email_verified": bool(verified), "name": name, "sign_in_method": method}


def fetch_profile(clerk_user_id):
    """The user's profile from Clerk's Backend API, or ProfileUnavailable."""
    import requests
    secret = (os.environ.get("CLERK_SECRET_KEY") or "").strip()
    if not secret:
        raise ProfileUnavailable("CLERK_SECRET_KEY is not set")
    try:
        r = requests.get(f"{BACKEND_API}/users/{clerk_user_id}", headers={"Authorization": f"Bearer {secret}"}, timeout=10)
    except Exception as e:                               # noqa: BLE001
        raise ProfileUnavailable(f"Clerk unreachable: {type(e).__name__}") from e
    if r.status_code != 200:
        raise ProfileUnavailable(f"Clerk answered {r.status_code}")
    return _profile_from(r.json())


def _is_admin_email(profile):
    admin = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    email = (profile.get("email") or "").strip().lower()
    return bool(admin) and bool(profile.get("email_verified")) and email == admin


def user_for_claims(claims, conn=None):
    """The app_users row (a dict) of a verified token's user: found, or created from the Clerk profile (the admin link
    first). last_active_at is set to now; a profile older than PROFILE_MAX_AGE is refreshed (best effort).
    ProfileUnavailable for a NEW user whose profile cannot be fetched: nothing is written then."""
    sub = claims["sub"]
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM app_users WHERE clerk_user_id = %s", (sub,))
            row = cur.fetchone()
            if row is not None:
                fetched = row.get("profile_fetched_at")
                if fetched is None or datetime.now(timezone.utc) - fetched > PROFILE_MAX_AGE:
                    try:
                        p = fetch_profile(sub)
                        cur.execute("UPDATE app_users SET email = %s, name = %s, sign_in_method = %s, profile_fetched_at = now() "
                                    "WHERE user_id = %s", (p["email"], p["name"], p["sign_in_method"], row["user_id"]))
                    except ProfileUnavailable as e:
                        print(f"  [profile of user {row['user_id']} not refreshed: {e}]")
                cur.execute("UPDATE app_users SET last_active_at = now() WHERE user_id = %s RETURNING *", (row["user_id"],))
                row = cur.fetchone()
                conn.commit()
                return dict(row)
            profile = fetch_profile(sub)                 # a new user: no profile, no row
            row = None
            if _is_admin_email(profile):
                cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, last_active_at, "
                            "profile_fetched_at, is_admin, is_exempt) VALUES (1, %s, %s, %s, %s, now(), now(), TRUE, TRUE) "
                            "ON CONFLICT DO NOTHING RETURNING *",
                            (sub, profile["email"], profile["name"], profile["sign_in_method"]))
                row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO app_users (clerk_user_id, email, name, sign_in_method, last_active_at, profile_fetched_at) "
                            "VALUES (%s, %s, %s, %s, now(), now()) ON CONFLICT (clerk_user_id) DO NOTHING RETURNING *",
                            (sub, profile["email"], profile["name"], profile["sign_in_method"]))
                row = cur.fetchone()
            if row is None:                              # created by a concurrent first request of the same user
                cur.execute("SELECT * FROM app_users WHERE clerk_user_id = %s", (sub,))
                row = cur.fetchone()
            conn.commit()
            return dict(row)
    except BaseException:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


# ---- limits (Part 2) --------------------------------------------------------------------------------------------------

def default_cap():
    """DAILY_CAP_USD as a float, else 1.00 (an unparseable value falls back too: a cap must never vanish)."""
    try:
        v = float(os.environ.get(DAILY_CAP_ENV, "") or DEFAULT_DAILY_CAP_USD)
        return v if v >= 0 else DEFAULT_DAILY_CAP_USD
    except (TypeError, ValueError):
        return DEFAULT_DAILY_CAP_USD


def cap_for(user):
    own = user.get("daily_cap_usd")
    return float(own) if own is not None else default_cap()


def _midnight(now):
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def spent_today(user_id, conn=None):
    """The user's chat_usage cost since 00:00 UTC today (users.clock), in USD."""
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(usd), 0) FROM chat_usage WHERE user_id = %s AND ts >= %s",
                        (int(user_id), _midnight(clock())))
            return float(cur.fetchone()[0])
    finally:
        if own:
            conn.close()


def record_cap_hit(user_id, spent, cap, conn=None):
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO cap_hits (user_id, hit_at, spent_usd, cap_usd) VALUES (%s, %s, %s, %s)",
                        (int(user_id), clock(), spent, cap))
        conn.commit()
    finally:
        if own:
            conn.close()


def cap_reply():
    """The refusal, with the time left until 00:00 UTC in whole hours and minutes (rounded down)."""
    now = clock()
    left = int((_midnight(now) + timedelta(days=1) - now).total_seconds())
    return CAP_REPLY.format(h=left // 3600, m=(left % 3600) // 60)


def cap_reset_at(now=None):
    """Prompt W4: the instant the daily cap resets -- the next 00:00 UTC (the same clock cap_reply reads)."""
    return _midnight(now or clock()) + timedelta(days=1)


def capped(user):
    """(True, the reply) when this user's turn must be refused for the day (a cap_hits row written), else (False, None)."""
    if user.get("is_exempt"):
        return False, None
    cap, spent = cap_for(user), spent_today(user["user_id"])
    if spent >= cap:
        record_cap_hit(user["user_id"], spent, cap)
        return True, cap_reply()
    return False, None


def _limited(windows, user, limit):
    if user.get("is_exempt"):
        return False
    now = monotonic()
    with _WINDOWS_LOCK:
        dq = windows.setdefault(int(user["user_id"]), deque())
        while dq and now - dq[0] >= RATE_WINDOW_S:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        return False


def rate_limited(user):
    """True when this request is the user's (RATE_LIMIT_PER_MINUTE + 1)th in a rolling minute (it is not counted then)."""
    return _limited(_WINDOWS, user, RATE_LIMIT_PER_MINUTE)


def reads_limited(user):
    """Prompt F1a: the same rule for the website's other endpoints (/me, /threads, ...), READS_PER_MINUTE in their own
    window -- /chat's ten a minute are counted apart."""
    return _limited(_READ_WINDOWS, user, READS_PER_MINUTE)


def imports_limited(user):
    """Prompt F1a: FPL team imports and refreshes, IMPORTS_PER_MINUTE a minute per user -- for EVERY user, the admin
    included: each one costs FPL four or more requests."""
    return _limited(_IMPORT_WINDOWS, {**user, "is_exempt": False}, IMPORTS_PER_MINUTE)
