"""Prompt S2 (12 Nov 2026): the old key-gated chat page is retired in clerk mode. The website is https://fplcopilot.app,
so in AUTH_MODE=clerk GET / (and HEAD /) answers 308 to it -- with or without the shared key, and the ?key= browser
handshake no longer sets a cookie -- and every /static/* path answers 404, key or no key. Off mode is byte-identical: the
laptop still serves the old page behind the key. /health stays open in both modes."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Tests"))

from test_api_gate import KEY, client, main_mod  # noqa: E402,F401  (fixtures)

PAGE = (ROOT / "static" / "index.html").read_bytes()
SITE = "https://fplcopilot.app"


@pytest.fixture
def clerk(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    return client


@pytest.fixture
def off(client, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    return client


# ---- clerk mode -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("headers", [{}, {"x-api-key": KEY}, {"accept": "text/html"}])
def test_clerk_root_is_a_308_to_the_website(clerk, headers):
    r = clerk.get("/", headers=headers, follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == SITE


def test_clerk_root_head_is_a_308_too(clerk):
    r = clerk.head("/", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == SITE


def test_clerk_key_handshake_on_root_redirects_and_sets_no_cookie(clerk):
    r = clerk.get(f"/?key={KEY}", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == SITE
    assert "set-cookie" not in r.headers


@pytest.mark.parametrize("path", ["/static/index.html", "/static/", "/static", "/static/app.js", "/static/nope.css"])
@pytest.mark.parametrize("headers", [{}, {"x-api-key": KEY}])
def test_clerk_static_is_gone(clerk, path, headers):
    r = clerk.get(path, headers=headers, follow_redirects=False)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_clerk_health_stays_open(clerk):
    assert clerk.get("/health").status_code == 200


def test_clerk_other_paths_are_untouched(clerk):
    """Only / and /static/* change: a gated route without the key is still the gate's 401."""
    r = clerk.get("/statistics", follow_redirects=False)        # a prefix that is NOT /static/
    assert r.status_code == 401


# ---- off mode: byte-identical ----------------------------------------------------------------------------------------------

def test_off_root_serves_the_old_page_behind_the_key(off):
    r = off.get("/", headers={"x-api-key": KEY})
    assert r.status_code == 200 and r.content == PAGE
    assert off.get("/").status_code == 401


def test_off_static_serves_the_files_behind_the_key(off):
    r = off.get("/static/index.html", headers={"x-api-key": KEY})
    assert r.status_code == 200 and r.content == PAGE
    assert off.get("/static/index.html").status_code == 401


def test_off_key_handshake_still_sets_the_cookie(off):
    r = off.get(f"/?key={KEY}", follow_redirects=False)
    assert r.status_code == 303 and "fpl_key=" in r.headers.get("set-cookie", "")
