"""Sequences that a copied database left behind (2026-10-03).

Measured on the laptop: `model_transfer_plans` held 14 rows with MAX(proposal_id) = 14
while `model_transfer_plans_proposal_id_seq`.last_value was 13, and
`model_transfers` held 74 rows with a sequence that had never been called at all. Every
`propose_transfers` call therefore died on

    UniqueViolation: duplicate key value violates unique constraint
    "model_transfer_plans_pkey"  DETAIL: Key (proposal_id)=(1) already exists

because rows copied in with explicit ids do not advance a sequence. 13 of the eval's
propose_transfers calls failed that way. The repair belongs next to the schema: a
sequence that is behind its table's maximum is moved up, a healthy one is left alone.

Local Postgres (fpl_news_test); no network.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2                                            # noqa: E402
import db_write                                            # noqa: E402

TEST_DB = "fpl_news_test"
DROP = "DROP TABLE IF EXISTS model_transfers; DROP TABLE IF EXISTS model_transfer_plans"


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    with c.cursor() as cur:
        cur.execute(DROP)
    c.commit()
    db_write.ensure_schema(c)
    with c.cursor() as cur:                      # start from a clean, empty pair of tables
        cur.execute(DROP)
    c.commit()
    db_write.ensure_schema(c)
    yield c
    c.close()


def header(**over):
    h = {c: 0 for c in db_write.PLAN_COLS}
    h.update(source="test", user_id=9001, season="2026-27", gw=6, squad_version_id=1,
             run_id=None, config="baseline", frame_cutoff_gw=6, stale_by_gameweeks=0,
             horizon=6, effective_horizon=6, decay=0.45, hit_bar=4.0, locked=[], banned=[],
             status="Optimal", objective=1.0, n_transfers=0, hits=0, hit_cost_points=0,
             free_transfers_before=1, free_transfers_after=1, bank_before=0, bank_after=0,
             captain=None, vice=None, predicted_xi_points=1.0, hold_applied=False,
             solve_seconds=0.1, git_sha="test", note="test", plan_kind="move",
             paired_proposal_id=None)
    h.update(over)
    return h


def restore_style_row(conn, proposal_id):
    """A row copied in with an explicit id, as a dump restore leaves it."""
    cols = [c for c in db_write.PLAN_COLS]
    h = header()
    import json
    vals = [json.dumps(h[c]) if c in ("locked", "banned") else h[c] for c in cols]
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO model_transfer_plans (proposal_id, {', '.join(cols)}) "
                    f"VALUES (%s, {', '.join(['%s'] * len(cols))})", [proposal_id] + vals)
    conn.commit()


def last_value(conn, seq):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_sequence_last_value(%s::regclass)", (seq,))
        return cur.fetchone()[0]


def test_a_sequence_behind_its_table_is_moved_up_and_reported(conn):
    for pid in (1, 2, 3):
        restore_style_row(conn, pid)
    assert last_value(conn, "model_transfer_plans_proposal_id_seq") is None   # never called
    fixed = db_write.sync_sequences(conn)
    assert ("model_transfer_plans", "proposal_id") in {(f[0], f[1]) for f in fixed}, fixed
    assert last_value(conn, "model_transfer_plans_proposal_id_seq") == 3
    with conn.cursor() as cur:                       # the next default id no longer collides
        cur.execute("SELECT nextval('model_transfer_plans_proposal_id_seq')")
        assert cur.fetchone()[0] == 4


def test_a_healthy_sequence_is_left_alone(conn):
    restore_style_row(conn, 1)
    db_write.sync_sequences(conn)
    again = db_write.sync_sequences(conn)
    assert all(f[0] != "model_transfer_plans" for f in again), again


def test_write_proposal_twice_in_a_row_after_a_restore(conn):
    """The real path: two identical proposals must BOTH be stored, because the table is
    append-only and a second ask is a second decision, not a duplicate of the first."""
    restore_style_row(conn, 1)
    first = db_write.write_proposal(header(), [])
    second = db_write.write_proposal(header(), [])
    assert first > 1 and second > first, (first, second)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM model_transfer_plans")
        assert cur.fetchone()[0] == 3
