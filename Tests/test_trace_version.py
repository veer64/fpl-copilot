"""Prompt P6 Part 4 (2026-11-01): every trace carries version = the deployed git sha -- db_write.git_sha(), the value /health
reports (model_tools.health) -- on every observation of the turn (propagated, the root included), and the Langfuse client's
release is the same value. No sha (no .git, an unreadable HEAD, an exception) -> "unknown": never an error, never a change
to the turn."""
import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import db_write                                                      # noqa: E402
from test_tracing import ag, _tracing_on, _run, _tool, _text, RIGHT, WRONG, FakeLangfuse, UNREACHABLE   # noqa: E402,F401


def _capture_client(monkeypatch):
    import langfuse
    import tracing
    seen = []

    class Capture(FakeLangfuse):
        def __init__(self, **kw):
            super().__init__(**kw)
            seen.append(kw)
    monkeypatch.setattr(langfuse, "Langfuse", Capture)
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    tracing._reset()
    tracing.init()
    tracing._reset()
    return seen


def test_v1_every_observation_of_a_turn_carries_the_sha_as_its_version(ag, monkeypatch):
    monkeypatch.setattr(db_write, "git_sha", lambda: "abc123def")
    tracing, made = _tracing_on(monkeypatch)
    answer, _ = _run(ag, monkeypatch, [_tool("get_my_xi", "get_fixtures"), _text(WRONG), _text(RIGHT)])
    lf = made[-1]
    kinds = sorted({o.as_type for o in lf.observations})
    assert kinds == ["agent", "generation", "span", "tool"]           # root, calls, the fact check (+ send-back), tools
    assert all(o.propagated.get("version") == "abc123def" for o in lf.observations)
    assert lf.roots()[0].kw.get("version") == "abc123def"
    assert answer == RIGHT and tracing.LAST_TURN["errors"] == 0


def test_v1_the_client_release_is_the_sha(monkeypatch):
    monkeypatch.setattr(db_write, "git_sha", lambda: "abc123def")
    seen = _capture_client(monkeypatch)
    assert len(seen) == 1 and seen[0]["release"] == "abc123def"


def test_v1_the_version_is_the_value_health_reports():
    import model_tools
    import tracing
    assert tracing.version() == (db_write.git_sha() or "unknown")
    assert "sha = db_write.git_sha()" in inspect.getsource(model_tools.health)   # /health's git_sha is the same call


@pytest.mark.parametrize("sha", [None, "", "raise"])
def test_v2_no_sha_is_unknown_never_an_error(ag, monkeypatch, sha):
    def git_sha():
        if sha == "raise":
            raise OSError("no .git here")
        return sha
    monkeypatch.setattr(db_write, "git_sha", git_sha)
    tracing, made = _tracing_on(monkeypatch)
    answer, _ = _run(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    lf = made[-1]
    assert answer == RIGHT and tracing.LAST_TURN["errors"] == 0 and tracing.version() == "unknown"
    assert lf.observations and all(o.propagated.get("version") == "unknown" for o in lf.observations)
    assert tracing._client_kwargs(None)["release"] == "unknown"       # what the client is built with
