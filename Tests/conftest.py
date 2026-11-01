"""Shared test setup (Prompt H, 2026-10-30): agent turns run in tests never write fact_checks rows to the developer's
database. fact_check.record is replaced by a no-op for every test (the agent calls it through the module, so an
importlib.reload(agent) keeps the stub); a test that checks the writer itself opts out with @pytest.mark.fact_check_log."""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def pytest_configure(config):
    config.addinivalue_line("markers", "fact_check_log: the test writes fact_checks rows itself (no stub)")
    config.addinivalue_line("markers", "writes_dev_db: the test may leave rows in the developer's database (Prompt P6)")
    # Prompt L (2026-10-30): Langfuse tracing is OFF for the whole test process, whatever the developer's .env says
    # (load_dotenv never overrides a variable already set). A tracing test turns it on with monkeypatch and a fake client.
    os.environ["LANGFUSE_ENABLED"] = "0"


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


# Prompt P6 Part 5 (2026-11-01): no test leaves rows in the developer's database (`fpl`). Measured on the full suite of 1 Nov
# (a read-only plugin counting every table after every test): 7 tests left rows there -- test_agent_prompt (4) and
# test_now_context (2) one chat_usage, numeric_checks and citation_checks row per turn (their turns' logs were not stubbed),
# test_agent_caching's failed-call /chat and test_eval_clock's /chat a chat_threads row and checkpoints (the thread layer on
# the developer's database). After every test the row count of every table there (model_predictions aside: a build table no
# test writes, 199k rows, counted by the suite-level proof instead) must be what it was before it; a test that has to write
# there opts out with @pytest.mark.writes_dev_db (none does). Its own read-only connection (127.0.0.1); no local Postgres or no
# `fpl` database: the guard is off.
DEV_DB = "fpl"
UNGUARDED = {"model_predictions"}


def _dev_db_counts(conn, tables):
    with conn.cursor() as cur:
        cur.execute("SELECT " + ", ".join(f'(SELECT count(*) FROM public."{t}")' for t in tables))
        return dict(zip(tables, cur.fetchone()))


@pytest.fixture(scope="session")
def _dev_db():
    try:
        import psycopg2
        conn = psycopg2.connect(host="localhost", hostaddr="127.0.0.1", port=os.getenv("DB_PORT", "5432"), dbname=DEV_DB,
                                user=os.getenv("DB_USER", "postgres"), password=os.getenv("DB_PASSWORD", ""),
                                connect_timeout=5)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                        "AND table_type = 'BASE TABLE' ORDER BY 1")
            tables = [r[0] for r in cur.fetchall() if r[0] not in UNGUARDED]
    except Exception:                                    # noqa: BLE001 -- no developer database here: nothing to guard
        yield None
        return
    yield conn, tables
    conn.close()


@pytest.fixture(autouse=True)
def _no_rows_left_in_the_dev_db(request, _dev_db):
    if _dev_db is None or request.node.get_closest_marker("writes_dev_db") is not None:
        yield
        return
    conn, tables = _dev_db
    before = _dev_db_counts(conn, tables)
    yield
    after = _dev_db_counts(conn, tables)
    changed = {t: (before[t], after[t]) for t in tables if before[t] != after[t]}
    if changed:
        pytest.fail(f"the test left rows in the developer's database ({DEV_DB}): {changed}", pytrace=False)
