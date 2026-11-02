"""Prompt F1a Part 2 (2026-11-02): CORS for the website, and azp REQUIRED in clerk mode.

C1 CORS_ALLOWED_ORIGINS unset -> no CORS middleware at all: no access-control-* header on any response; a preflight meets
   the app's own key gate exactly as before (401).
C2 set -> only those origins get access-control-allow-origin; methods GET, POST, DELETE, OPTIONS; headers Authorization and
   Content-Type only (the shared key never travels cross-origin); no credentials (bearer tokens, no cookies); a refusal from
   the gate still carries the header, so the website can read it.
Z1 clerk mode: a token without azp, or with an azp not in CLERK_AUTHORIZED_PARTIES -> 401 before any model call or row.
Z2 clerk mode with CLERK_AUTHORIZED_PARTIES empty or unset -> the app refuses to start, with a clear log line; off mode
   starts either way.

Offline: main.app in process (TestClient); /health's body stubbed (test_api_gate's reason: it is slow and not under test)."""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_auth import app, tdb, c, mint, bearer, _all_counts, ORIGIN   # noqa: E402,F401  (fixtures)

KEY = "test-cors-key"
SITE = "https://fplcopilot.example"
LOCAL = "http://localhost:3000"
EVIL = "https://evil.example"


@pytest.fixture
def load(monkeypatch):
    """main reloaded under the given CORS_ALLOWED_ORIGINS (None = unset); reloaded once more at teardown with the variable
    unset, so no other test meets this test's middleware."""
    import model_tools
    monkeypatch.setattr(model_tools, "health", lambda: {"status": "stubbed by Tests/test_cors_azp.py"})
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.delenv("AUTH_MODE", raising=False)

    def _load(origins):
        if origins is None:
            monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        else:
            monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)
        import main
        return importlib.reload(main)
    yield _load
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    import main
    importlib.reload(main)


def _acl(r):
    return {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("access-control-")}


def _preflight(client, origin, headers="authorization,content-type", path="/chat"):
    return client.options(path, headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                         "Access-Control-Request-Headers": headers})


# ---- C1: unset -> no CORS at all ---------------------------------------------------------------------------------------

def test_c1_unset_means_no_cors_middleware_and_no_header_anywhere(load):
    main = load(None)
    assert not any(m.cls.__name__ == "CORSMiddleware" for m in main.app.user_middleware)
    client = TestClient(main.app, raise_server_exceptions=False)
    for r in (client.get("/health", headers={"Origin": SITE}),
              client.post("/reset", headers={"Origin": SITE}),
              client.post("/reset", headers={"Origin": SITE, "X-API-Key": KEY}),
              _preflight(client, SITE)):
        assert _acl(r) == {}, (r.request.method, r.request.url.path, r.status_code)
    assert _preflight(client, SITE).status_code == 401                 # the key gate answers, as before


@pytest.mark.parametrize("value", ["", " ", " , "])
def test_c1_an_empty_value_is_the_same_as_unset(load, value):
    main = load(value)
    assert not any(m.cls.__name__ == "CORSMiddleware" for m in main.app.user_middleware)


# ---- C2: set -> exactly those origins -----------------------------------------------------------------------------------

def test_c2_an_allowed_origin_gets_the_header_and_no_credentials(load):
    main = load(f" {SITE}/ , {LOCAL} ")                                  # spaces and a trailing slash are tolerated
    client = TestClient(main.app, raise_server_exceptions=False)
    for origin in (SITE, LOCAL):
        r = client.get("/health", headers={"Origin": origin})
        assert r.status_code == 200 and _acl(r).get("access-control-allow-origin") == origin
        assert "access-control-allow-credentials" not in _acl(r)


def test_c2_another_origin_gets_no_header(load):
    main = load(f"{SITE},{LOCAL}")
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get("/health", headers={"Origin": EVIL})
    assert r.status_code == 200 and "access-control-allow-origin" not in _acl(r)
    p = _preflight(client, EVIL)
    assert p.status_code == 400 and "access-control-allow-origin" not in _acl(p)


def test_c2_the_preflight_allows_exactly_the_listed_methods_and_headers(load):
    main = load(SITE)
    client = TestClient(main.app, raise_server_exceptions=False)
    p = _preflight(client, SITE)
    assert p.status_code == 200, p.text
    h = _acl(p)
    assert h["access-control-allow-origin"] == SITE
    assert {m.strip() for m in h["access-control-allow-methods"].split(",")} == {"GET", "POST", "DELETE", "OPTIONS"}
    assert {x.strip().lower() for x in h["access-control-allow-headers"].split(",")} >= {"authorization", "content-type"}
    assert "access-control-allow-credentials" not in h
    assert _preflight(client, SITE, headers="x-api-key").status_code == 400      # the shared key never goes cross-origin


def test_c2_a_refusal_from_the_gate_still_carries_the_header(load):
    main = load(SITE)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/reset", headers={"Origin": SITE})                   # no key, off mode: 401 from the gate
    assert r.status_code == 401 and _acl(r).get("access-control-allow-origin") == SITE


# ---- Z1: azp required in clerk mode -----------------------------------------------------------------------------------

@pytest.mark.parametrize("azp", [None, "", EVIL, ORIGIN + "/evil"])
def test_z1_a_token_without_the_right_azp_is_401_with_no_model_call_and_no_row(c, azp):
    before, calls = _all_counts(c.conn), c.brain.calls
    for path, body in (("/chat", {"message": "hello"}), ("/reset", {})):
        r = c.client.post(path, json=body, headers=bearer(mint("user_a9001", azp=azp)))
        assert r.status_code == 401, (azp, path, r.text)
    assert c.brain.calls == calls and _all_counts(c.conn) == before


def test_z1_the_listed_azp_is_accepted_with_or_without_a_trailing_slash(c):
    assert c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_a9001", azp=ORIGIN))).status_code == 200
    assert c.client.post("/chat", json={"message": "hello"}, headers=bearer(mint("user_a9001", azp=ORIGIN + "/"))).status_code == 200


def test_z1_verify_refuses_a_token_without_azp_even_with_parties_set(monkeypatch):
    import auth
    from test_auth import PUBLIC, ISSUER
    monkeypatch.setenv("CLERK_JWT_KEY", PUBLIC)
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", ORIGIN)
    auth._reset()
    try:
        assert auth.verify(mint("user_x", azp=ORIGIN))["sub"] == "user_x"
        with pytest.raises(auth.AuthError):
            auth.verify(mint("user_x", azp=None))
        monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "")
        with pytest.raises(auth.AuthError):                              # nothing listed: nothing is authorized
            auth.verify(mint("user_x", azp=ORIGIN))
    finally:
        auth._reset()


# ---- Z2: clerk mode needs CLERK_AUTHORIZED_PARTIES to start -------------------------------------------------------------

@pytest.mark.parametrize("parties", [None, "", " , "])
def test_z2_clerk_mode_without_authorized_parties_refuses_to_start(load, monkeypatch, capsys, parties):
    main = load(None)
    monkeypatch.setenv("AUTH_MODE", "clerk")
    if parties is None:
        monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)
    else:
        monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", parties)
    with pytest.raises(RuntimeError, match="CLERK_AUTHORIZED_PARTIES"):
        with TestClient(main.app):
            pass
    assert "CLERK_AUTHORIZED_PARTIES" in capsys.readouterr().out          # the clear log line


def test_z2_clerk_mode_with_parties_starts_and_off_mode_starts_without_them(load, monkeypatch):
    main = load(None)
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", SITE)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
    monkeypatch.delenv("AUTH_MODE")
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES")
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
