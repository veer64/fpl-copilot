"""eval/run_agent_evals.py with cache tokens (2026-10-19): the budget prices every call at pricing.turn_usd (cache
write and read included, so --max-usd stays honest once the agent caches) and keeps a per-call usage log the turn
record can be cut from. Fakes only."""
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pricing                                             # noqa: E402
import run_agent_evals as rae                              # noqa: E402


def _usage(i, o, cr=0, cw=0):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw)


class _Inner:
    def __init__(self):
        self.messages = self
        self.n = 0

    def create(self, **kw):
        self.n += 1
        u = _usage(1000, 50, 0, 20000) if self.n == 1 else _usage(100, 80, 20000, 500)
        return types.SimpleNamespace(content=[], stop_reason="end_turn", usage=u, model=kw["model"])


def test_the_budget_prices_cache_tokens_and_logs_every_call():
    b = rae.Budget(max_calls=10, max_usd=5.0, max_voyage=0)
    c = rae.CountingClient(_Inner(), b)
    c.messages.create(model="claude-sonnet-4-6", max_tokens=1, messages=[])
    c.messages.create(model="claude-sonnet-4-6", max_tokens=1, messages=[])
    assert b.calls == 2 and b.tok_in == 1100 and b.tok_out == 130
    assert b.cache_read == 20000 and b.cache_write == 20500
    expected = (pricing.turn_usd("claude-sonnet-4-6", 1000, 50, cache_read=0, cache_write=20000)
                + pricing.turn_usd("claude-sonnet-4-6", 100, 80, cache_read=20000, cache_write=500))
    assert b.usd == pytest.approx(expected)
    assert [(x["input"], x["output"], x["cache_read"], x["cache_write"]) for x in b.call_log] == \
        [(1000, 50, 0, 20000), (100, 80, 20000, 500)]
    snap = b.snapshot()
    assert snap["cache_read_tokens"] == 20000 and snap["cache_write_tokens"] == 20500 and snap["api_calls_logged"] == 2
