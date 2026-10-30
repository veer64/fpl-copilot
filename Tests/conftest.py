"""Shared test setup (Prompt H, 2026-10-30): agent turns run in tests never write fact_checks rows to the developer's
database. fact_check.record is replaced by a no-op for every test (the agent calls it through the module, so an
importlib.reload(agent) keeps the stub); a test that checks the writer itself opts out with @pytest.mark.fact_check_log."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def pytest_configure(config):
    config.addinivalue_line("markers", "fact_check_log: the test writes fact_checks rows itself (no stub)")


@pytest.fixture(autouse=True)
def _no_fact_check_log_writes(request, monkeypatch):
    if request.node.get_closest_marker("fact_check_log") is None:
        try:
            import fact_check
        except ImportError:
            fact_check = None
        if fact_check is not None:
            monkeypatch.setattr(fact_check, "record", lambda *a, **k: None)
    yield
