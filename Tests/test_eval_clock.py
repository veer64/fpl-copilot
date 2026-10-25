"""The eval runner can freeze the context block's clock (2026-10-24); production never reads the override.

eval/run_agent_evals.py gets `--now <ISO>` (default: the environment's FPL_EVAL_NOW, read by the runner alone):
freeze_clock() replaces now_context.clock in the runner's own process, so the context block, the Now line and every
tool that reads now_context.clock see the same frozen instant on both sides of a gate. Nothing under production
code reads the flag or the variable: /chat with FPL_EVAL_NOW set still stamps the real clock. Offline: fake client,
no API, no DB writes."""
import importlib
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import now_context as nc                                   # noqa: E402
import run_agent_evals as rae                              # noqa: E402

FROZEN = "2026-10-25T14:30:00Z"
FAR = "2031-01-01T00:00:00Z"                               # a date no real clock will show while this test lives
KEY = "test-key-" + "z" * 39


def test_freeze_clock_replaces_the_shared_clock_and_the_block_follows(monkeypatch):
    monkeypatch.setattr(nc, "clock", nc.clock)             # recorded, so teardown restores the real clock
    frozen = rae.freeze_clock(FROZEN)
    assert frozen == datetime(2026, 10, 25, 14, 30, tzinfo=timezone.utc)
    assert nc.clock() == frozen
    text, _ = nc.build(deadlines={9: datetime(2026, 10, 31, 11, 0, tzinfo=timezone.utc)}, finished=[1, 2, 3, 4, 5, 6, 7],
                       clubs=["Arsenal"], dispatch_state={}, policy=rae_policy())
    assert nc.now_line() == "- Now: Sunday 2026-10-25 14:30 UTC."          # the clock line (on the user message since 2026-10-24)
    assert "next deadline GW9, Saturday 2026-10-31 11:00 UTC" in text      # the block follows the same clock (seeded: GW9 only)


def rae_policy():
    import dispatch_policy
    return dispatch_policy


def test_the_runner_reads_the_override_from_its_flag_or_env_only(monkeypatch):
    monkeypatch.delenv("FPL_EVAL_NOW", raising=False)
    assert rae.frozen_now_from(types.SimpleNamespace(now=None)) is None           # default: unchanged behaviour
    assert rae.frozen_now_from(types.SimpleNamespace(now=FROZEN)) == FROZEN
    monkeypatch.setenv("FPL_EVAL_NOW", FAR)
    assert rae.frozen_now_from(types.SimpleNamespace(now=None)) == FAR
    assert rae.frozen_now_from(types.SimpleNamespace(now=FROZEN)) == FROZEN      # the flag wins over the variable
    assert "--now" in rae.build_parser().format_help()


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Fake:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(content=[_Block("text", text="ok")], stop_reason="end_turn",
                                     usage=types.SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                                                                 cache_creation_input_tokens=0), model="claude-sonnet-4-6")


def test_chat_ignores_the_override_variable(monkeypatch):
    """/chat with FPL_EVAL_NOW in the environment and no runner: the Now line carries today's real date."""
    monkeypatch.setenv("FPL_EVAL_NOW", FAR)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("APP_API_KEY", KEY)
    import agent as ag
    ag = importlib.reload(ag)
    import main
    main = importlib.reload(main)                          # binds run_agent from the reloaded agent
    main._hits_by_ip.clear()
    main._hits_global.clear()
    fake = _Fake()
    monkeypatch.setattr(ag, "client", fake)
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_numeric_check", lambda *a, **k: None)
    from fastapi.testclient import TestClient
    client = TestClient(main.app, headers={"x-api-key": KEY})
    before = datetime.now(timezone.utc)
    r = client.post("/chat", json={"message": "hello"})
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    assert len(fake.calls) == 1
    sent = fake.calls[0]
    stamped = " ".join([ag.system_text(sent["system"])] + [b.get("text", "") for m in sent["messages"]
                                                            for b in (m["content"] if isinstance(m["content"], list) else [{"text": m["content"]}])])
    assert "2031" not in stamped
    assert any(d.strftime("- Now: %A %Y-%m-%d") in stamped for d in (before, after))
    assert nc.clock().year != 2031 and abs((nc.clock() - after).total_seconds()) < 60
