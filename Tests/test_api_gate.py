"""The access gate on main.py (added 2026-09-17).

Until that day every endpoint on port 8000 was reachable from the internet with no
credential: POST /chat ran the agent against the server's ANTHROPIC_API_KEY, and its
toolset can write squad state. Nothing in the suite covered main.py at all, so the
hole could have come back in a refactor without a single test going red. These are
the tests that make that impossible.

No live server and no network: fastapi's TestClient drives the ASGI app in-process.
No agent call either -- every /chat case here either fails the key check or sends a
body that fails schema validation, and both return before run_agent is reached. The
one route that touches Postgres is /health, and the assertion on it is only that the
gate let it through (it is allowed to fail for lack of a database on a laptop).
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

KEY = "test-key-" + "z" * 39          # 48 chars, matches the production shape
WRONG = "test-key-" + "z" * 38 + "y"  # same length, differs in the last byte


@pytest.fixture()
def main_mod(monkeypatch):
    """main.py imported with a known APP_API_KEY, and its module-level rate-limit
    state cleared, so tests cannot leak counters into each other."""
    monkeypatch.setenv("APP_API_KEY", KEY)
    import main
    main = importlib.reload(main)     # API_KEY is read at import time
    main._hits_by_ip.clear()
    main._hits_global.clear()
    yield main
    main._hits_by_ip.clear()
    main._hits_global.clear()


@pytest.fixture()
def client(main_mod):
    return TestClient(main_mod.app, raise_server_exceptions=False)


# every gated route, with a body where the verb needs one
GATED = [("GET", "/", None),
         ("GET", "/docs", None),
         ("GET", "/redoc", None),
         ("GET", "/openapi.json", None),
         ("GET", "/static/index.html", None),
         ("POST", "/chat", {"message": "who should I captain?"}),
         ("POST", "/reset", {})]


@pytest.mark.parametrize("method,path,body", GATED)
def test_gated_route_without_a_key_is_refused(client, method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code == 401, f"{method} {path} returned {r.status_code}, not 401"


@pytest.mark.parametrize("method,path,body", GATED)
def test_gated_route_with_a_wrong_key_is_refused(client, method, path, body):
    r = client.request(method, path, json=body, headers={"x-api-key": WRONG})
    assert r.status_code == 401, f"{method} {path} returned {r.status_code}, not 401"


def test_a_key_that_is_a_prefix_of_the_real_one_is_refused(client):
    """compare_digest, not startswith: a truncated key must not pass."""
    r = client.get("/openapi.json", headers={"x-api-key": KEY[:-1]})
    assert r.status_code == 401


def test_the_right_key_passes_the_gate(client):
    assert client.get("/openapi.json", headers={"x-api-key": KEY}).status_code == 200
    assert client.get("/", headers={"x-api-key": KEY}).status_code == 200
    assert client.post("/reset", headers={"x-api-key": KEY}).status_code == 200


def test_the_right_key_reaches_chat_without_invoking_the_agent(client):
    """422 proves the key was accepted and the request got as far as schema
    validation. An empty body is rejected by pydantic BEFORE the handler, so
    run_agent is never called and no API spend occurs."""
    r = client.post("/chat", headers={"x-api-key": KEY}, json={})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "message"]


def test_health_is_open_without_a_key(client):
    """The one deliberate exception: the external uptime monitor polls it, and it
    publishes nothing the public repo does not already document. It may fail for
    want of a database here -- what matters is that the gate did not refuse it."""
    r = client.get("/health")
    assert r.status_code != 401
    assert r.status_code != 503


def test_health_is_the_only_open_route(client, main_mod):
    assert main_mod.OPEN_ENDPOINTS == {("GET", "/health"), ("HEAD", "/health")}


def test_unset_api_key_fails_closed_and_does_not_open_the_app(client, main_mod):
    """A missing secret must refuse everything gated, never pass through."""
    main_mod.API_KEY = ""
    try:
        for method, path, body in GATED:
            r = client.request(method, path, json=body, headers={"x-api-key": KEY})
            assert r.status_code == 503, f"{method} {path} -> {r.status_code}, not 503"
        assert client.get("/health").status_code != 503   # still open
    finally:
        main_mod.API_KEY = KEY


def test_blank_key_presented_against_blank_config_is_still_refused(client, main_mod):
    """The degenerate case: empty == empty must not authenticate."""
    main_mod.API_KEY = ""
    try:
        r = client.get("/openapi.json", headers={"x-api-key": ""})
        assert r.status_code == 503
    finally:
        main_mod.API_KEY = KEY


def test_browser_handshake_exchanges_the_key_for_a_cookie(client, main_mod):
    """?key=<secret> on a GET sets an HttpOnly cookie and redirects to the clean
    path, because a top-level navigation cannot carry a header and the secret must
    not be baked into the tracked static file."""
    r = client.get("/?key=" + KEY, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    cookie = r.cookies.get(main_mod.COOKIE_NAME)
    assert cookie == KEY
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie


def test_a_wrong_key_in_the_query_does_not_set_a_cookie(client, main_mod):
    r = client.get("/?key=" + WRONG, follow_redirects=False)
    assert r.status_code == 401
    assert main_mod.COOKIE_NAME not in r.cookies


def test_the_cookie_authenticates_later_requests_including_chat(client, main_mod):
    """What makes the browser UI work: the page's fetch() calls send the cookie."""
    client.cookies.set(main_mod.COOKIE_NAME, KEY)
    assert client.get("/").status_code == 200
    assert client.post("/chat", json={}).status_code == 422      # gate passed
    client.cookies.set(main_mod.COOKIE_NAME, WRONG)
    assert client.post("/chat", json={}).status_code == 401


def test_chat_is_rate_limited_per_ip(main_mod):
    main_mod._hits_by_ip.clear()
    main_mod._hits_global.clear()
    n = main_mod.CHAT_PER_IP_PER_HOUR
    assert all(not main_mod._rate_limited("1.2.3.4") for _ in range(n))
    assert main_mod._rate_limited("1.2.3.4") is True


def test_chat_has_a_global_ceiling_when_per_ip_buckets_do_not_bind(main_mod):
    """Docker's published port can present every client as the bridge gateway, so
    the global ceiling is what actually bounds the spend."""
    main_mod._hits_by_ip.clear()
    main_mod._hits_global.clear()
    allowed = sum(not main_mod._rate_limited(f"10.0.0.{i}")
                  for i in range(40) for _ in range(5))
    assert allowed == main_mod.CHAT_GLOBAL_PER_HOUR


def test_the_rate_limit_is_counted_only_after_the_key_check(client, main_mod):
    """An unauthenticated caller must never be able to consume the quota."""
    main_mod._hits_by_ip.clear()
    main_mod._hits_global.clear()
    for _ in range(main_mod.CHAT_GLOBAL_PER_HOUR + 5):
        assert client.post("/chat", json={"message": "x"}).status_code == 401
    assert len(main_mod._hits_global) == 0


def test_rate_limited_caller_gets_429_not_a_model_call(client, main_mod):
    main_mod._hits_by_ip.clear()
    main_mod._hits_global.clear()
    for _ in range(main_mod.CHAT_PER_IP_PER_HOUR):
        main_mod._rate_limited("testclient")
    r = client.post("/chat", headers={"x-api-key": KEY}, json={"message": "x"})
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"]


# A real browser's Accept header, verbatim from Chrome.
HTML_ACCEPT = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def test_browser_style_get_without_a_key_returns_the_html_notice(client):
    """A person who navigates here unauthenticated must be told what to do. Raw
    JSON in the viewport is what sent the last round of confusion (2026-09-17)."""
    r = client.get("/", headers=HTML_ACCEPT)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text.lower()
    assert "Authentication required" in r.text
    assert "?key=" in r.text          # it names the way in


def test_api_style_get_without_a_key_returns_json(client):
    """An API client must keep getting a body it can parse."""
    r = client.get("/", headers={"accept": "*/*"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert isinstance(r.json()["detail"], str)
    assert "<html" not in r.text.lower()


def test_a_client_that_sends_no_accept_header_gets_json(client):
    r = client.get("/")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("accept", ["text/html", "*/*", "application/json"])
def test_no_401_body_ever_contains_the_secret(client, accept):
    """Whichever branch answers, the key must not be in the response."""
    r = client.get("/", headers={"accept": accept})
    assert r.status_code == 401
    assert KEY not in r.text


def test_the_html_notice_names_the_mechanism_but_holds_no_secret(main_mod):
    page = main_mod.UNAUTHORIZED_HTML
    assert KEY not in page
    assert "APP_API_KEY=" not in page        # the NAME may appear, never an assignment
    assert "X-API-Key" in page and "/health" in page


def test_the_html_branch_is_get_only_so_posts_still_get_json(client):
    """The page's own fetch() calls are POSTs; they must receive JSON to parse."""
    r = client.post("/chat", headers=HTML_ACCEPT, json={"message": "x"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert isinstance(r.json()["detail"], str)


def test_health_is_still_open_to_a_browser_accept_header(client):
    r = client.get("/health", headers=HTML_ACCEPT)
    assert r.status_code not in (401, 503)


def test_a_browser_with_a_valid_key_gets_the_app_not_the_notice(client):
    r = client.get("/", headers={**HTML_ACCEPT, "x-api-key": KEY})
    assert r.status_code == 200
    assert "Authentication required" not in r.text
    assert "FPL Copilot" in r.text


def test_the_secret_is_not_hardcoded_anywhere_in_the_tree(main_mod):
    """The gate is worthless if the key is committed. static/index.html in
    particular must stay free of it -- this repository is public."""
    import pathlib
    root = pathlib.Path(main_mod.__file__).resolve().parent
    for rel in ["main.py", "static/index.html", "docker-compose.yml", "Dockerfile"]:
        p = root / rel
        if p.exists():
            assert "APP_API_KEY=" not in p.read_text(encoding="utf-8", errors="replace")
