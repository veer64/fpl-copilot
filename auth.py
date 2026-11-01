"""Clerk session tokens (Prompt P7, 2026-11-01). USER DECISIONS (1 Nov): "Open sign-up: anyone can sign in." "Google and
email sign-in only; I don't want to pay." (Clerk's free plan.)

AUTH_MODE (environment, read per request): "clerk" turns login on; anything else -- unset included -- is "off", which is
exactly the single-user app of 13ebb8e (the shared X-API-Key gate, the user from config_roles.DEFAULT_USER_ID()).

In clerk mode /chat, /reset and /admin* take `Authorization: Bearer <Clerk session token>` (main.py) and verify it here, with
no network call per request (Clerk's manual JWT verification, clerk.com/docs/guides/sessions/manual-jwt-verification):
- the signature, RS256 only, against the instance's key: CLERK_JWT_KEY (the PEM public key from the dashboard: fully
  networkless) if set, else the instance JWKS from the Backend API (https://api.clerk.com/v1/jwks, CLERK_SECRET_KEY), fetched
  once and cached per process; a kid not in the cache triggers at most one refetch per JWKS_REFETCH_S, so a stream of bad
  tokens can never hammer Clerk;
- exp and nbf (LEEWAY_S of clock skew, Clerk's default 5 s), iat, sub required;
- iss = the instance's Frontend API URL: CLERK_ISSUER if set, else decoded from CLERK_PUBLISHABLE_KEY;
- azp, when the token carries one, must be one of CLERK_AUTHORIZED_PARTIES (comma-separated origins); a token without azp
  (a backend-minted one) passes, as Clerk's guide says;
- sts "pending" (an incomplete session) is refused.
Any failure is AuthError -> 401 before any model call or any DB access. Measured on the dev instance 1 Nov: tokens carry
exp, fva, iat, iss, nbf, sid, sts, sub, v; header alg RS256 + kid; 60 s lifetime."""
import base64
import os
import threading
import time

import jwt

MODE_ENV = "AUTH_MODE"
JWKS_URL = "https://api.clerk.com/v1/jwks"
JWKS_REFETCH_S = 60.0                      # an unknown kid refetches the JWKS at most this often
LEEWAY_S = 5                               # clock skew allowed on exp / nbf (Clerk's default)
ALGORITHMS = ["RS256"]

_STATE = {"keys": None, "fetched_at": 0.0, "pem": None, "pem_src": None}
_LOCK = threading.Lock()


class AuthError(Exception):
    """A request that must be refused 401: no token, or one that does not verify."""


def mode():
    """"clerk" when AUTH_MODE=clerk (any case, spaces stripped), else "off"."""
    return "clerk" if os.environ.get(MODE_ENV, "").strip().lower() == "clerk" else "off"


def _reset():
    """Forget the cached keys (tests only)."""
    with _LOCK:
        _STATE.update(keys=None, fetched_at=0.0, pem=None, pem_src=None)


def issuer():
    """The expected iss: CLERK_ISSUER, else https://<Frontend API host> decoded from CLERK_PUBLISHABLE_KEY
    (pk_<env>_<base64 of "<host>$">)."""
    explicit = (os.environ.get("CLERK_ISSUER") or "").strip().rstrip("/")
    if explicit:
        return explicit
    pk = (os.environ.get("CLERK_PUBLISHABLE_KEY") or "").strip()
    try:
        enc = pk.split("_", 2)[2]
        host = base64.b64decode(enc + "=" * (-len(enc) % 4)).decode("utf-8").rstrip("$").strip()
    except Exception:                                    # noqa: BLE001 -- unset or malformed: no issuer, every token refused
        return None
    return f"https://{host}" if host else None


def authorized_parties():
    return [o.strip().rstrip("/") for o in (os.environ.get("CLERK_AUTHORIZED_PARTIES") or "").split(",") if o.strip()]


def _fetch_jwks():
    import requests
    secret = (os.environ.get("CLERK_SECRET_KEY") or "").strip()
    if not secret:
        raise AuthError("no CLERK_JWT_KEY and no CLERK_SECRET_KEY: cannot verify tokens")
    r = requests.get(JWKS_URL, headers={"Authorization": f"Bearer {secret}"}, timeout=10)
    r.raise_for_status()
    return r.json()


def _key_for(kid):
    pem = (os.environ.get("CLERK_JWT_KEY") or "").strip()
    if pem:                                              # networkless: the instance's one public key, whatever the kid
        with _LOCK:
            if _STATE["pem_src"] != pem:
                try:
                    _STATE.update(pem=_load_pem(pem), pem_src=pem)
                except Exception as e:                   # noqa: BLE001 -- a malformed key: nothing verifies
                    raise AuthError("CLERK_JWT_KEY is not a PEM public key") from e
            return _STATE["pem"]
    with _LOCK:
        keys = _STATE["keys"]
        stale = keys is None or (kid not in keys and time.monotonic() - _STATE["fetched_at"] >= JWKS_REFETCH_S)
        if stale:
            _STATE["fetched_at"] = time.monotonic()
            try:
                doc = _fetch_jwks()
            except AuthError:
                raise
            except Exception as e:                       # noqa: BLE001 -- Clerk unreachable: the token cannot be verified
                raise AuthError(f"the signing keys could not be fetched: {type(e).__name__}") from e
            keys = {k.get("kid"): jwt.algorithms.RSAAlgorithm.from_jwk(k) for k in doc.get("keys", [])
                    if k.get("kty") == "RSA"}
            _STATE["keys"] = keys
    if kid not in keys:
        raise AuthError("the token's signing key is unknown")
    return keys[kid]


def _load_pem(pem):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    text = pem.replace("\\n", "\n")                      # a PEM pasted into a one-line env value
    return load_pem_public_key(text.encode("utf-8"))


def verify(token):
    """The token's claims, or AuthError. Never a network call when CLERK_JWT_KEY is set or the JWKS is cached."""
    if not token or not isinstance(token, str):
        raise AuthError("no session token")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise AuthError("not a token") from e
    if header.get("alg") not in ALGORITHMS:
        raise AuthError("the token's algorithm is not RS256")
    iss = issuer()
    if not iss:
        raise AuthError("no issuer configured (CLERK_ISSUER / CLERK_PUBLISHABLE_KEY)")
    key = _key_for(header.get("kid"))
    try:
        claims = jwt.decode(token, key, algorithms=ALGORITHMS, issuer=iss, leeway=LEEWAY_S,
                            options={"require": ["exp", "nbf", "iat", "iss", "sub"], "verify_aud": False})
    except jwt.PyJWTError as e:
        raise AuthError(f"the token does not verify: {type(e).__name__}") from e
    azp = claims.get("azp")
    if azp and azp.rstrip("/") not in authorized_parties():
        raise AuthError("the token's authorized party is not allowed")
    if claims.get("sts") == "pending":
        raise AuthError("the session is not complete")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise AuthError("the token names no user")
    return claims


def bearer(headers):
    """The token of an `Authorization: Bearer <token>` header, else None."""
    value = (headers.get("authorization") or "").strip()
    if value[:7].lower() != "bearer ":
        return None
    return value[7:].strip() or None
