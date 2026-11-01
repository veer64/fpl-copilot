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
.verification.status ("verified"), first_name, last_name, external_accounts[].provider, created_at in ms."""
import os
from datetime import datetime, timedelta, timezone

import psycopg2.extras

import db_write

FIRST_NEW_USER_ID = 10001
RESERVED_USER_IDS = (1, 9001, 9002)
PROFILE_MAX_AGE = timedelta(days=1)
BACKEND_API = "https://api.clerk.com/v1"

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
"""


class ProfileUnavailable(Exception):
    """Clerk's Backend API did not give us the user's profile."""


def _reset():
    """Nothing cached in this module yet (tests call it; Prompt P7 Part 2 adds the rate-limit windows)."""


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
