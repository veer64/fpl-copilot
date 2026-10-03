"""The configurable default user (2026-10-02).

ONE source of truth for "whose squad is this?": `config_roles.DEFAULT_USER_ID()`,
read from the env var FPL_USER_ID at CALL time and falling back to 1. The tools
take `user_id=None` and resolve it inside the body, because a default argument
is evaluated once at import and could never see an env var set afterwards.

Production is unaffected while the server's .env carries no FPL_USER_ID; the
eval runner sets it to 9001 for its own process only. Nothing here touches a
database: every test either calls the pure resolver or intercepts the first
squad read.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import config_roles                                        # noqa: E402
import model_tools                                         # noqa: E402
import squad_store                                         # noqa: E402

ENV = "FPL_USER_ID"


class _Cur:
    """A cursor that records every (sql, params) and returns no rows."""

    def __init__(self, seen):
        self.seen = seen

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.seen.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _Conn:
    def __init__(self):
        self.seen = []

    def cursor(self, *a, **k):
        return _Cur(self.seen)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_default_user_id_is_one_without_the_env_var(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert config_roles.DEFAULT_USER_ID() == 1


def test_default_user_id_reads_the_env_var_at_call_time(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert config_roles.DEFAULT_USER_ID() == 1
    monkeypatch.setenv(ENV, "9001")
    assert config_roles.DEFAULT_USER_ID() == 9001        # no re-import needed
    monkeypatch.delenv(ENV, raising=False)
    assert config_roles.DEFAULT_USER_ID() == 1


def test_an_unreadable_env_value_falls_back_to_one(monkeypatch):
    monkeypatch.setenv(ENV, "not-a-number")
    assert config_roles.DEFAULT_USER_ID() == 1
    monkeypatch.setenv(ENV, "")
    assert config_roles.DEFAULT_USER_ID() == 1


def test_read_active_default_follows_the_env_var(monkeypatch):
    monkeypatch.setenv(ENV, "9001")
    conn = _Conn()
    with pytest.raises(squad_store.SquadStateError) as e:
        squad_store.read_active(conn=conn)
    assert "user 9001" in str(e.value)
    assert conn.seen and conn.seen[0][1] == (9001,)
    monkeypatch.delenv(ENV, raising=False)
    conn = _Conn()
    with pytest.raises(squad_store.SquadStateError):
        squad_store.read_active(conn=conn)
    assert conn.seen[0][1] == (1,)


def test_write_version_default_follows_the_env_var(monkeypatch):
    monkeypatch.setenv(ENV, "9001")
    doc = _legal_document()
    conn = _Conn()
    with pytest.raises(squad_store.SquadStateError) as e:
        squad_store.write_version({"version_id": 1}, doc, 6, None, False, conn=conn)
    assert "user 9001" in str(e.value)
    assert conn.seen[0][1] == (1, 9001)                  # (version_id, user_id)


@pytest.mark.parametrize("call", ["get_my_squad", "get_my_xi", "set_my_squad",
                                  "propose_transfers", "get_price_movements"])
def test_every_tool_default_path_follows_the_env_var(monkeypatch, call):
    monkeypatch.setenv(ENV, "9001")
    seen = []

    def fake_read_active(user_id=None, conn=None):
        seen.append(user_id)
        raise squad_store.SquadStateError("intercepted by the test")

    monkeypatch.setattr(model_tools.squad_store, "read_active", fake_read_active)
    import prices_tool
    monkeypatch.setattr(prices_tool, "movements", lambda **kw: {"risers": [], "fallers": []})

    if call == "get_my_squad":
        out = model_tools.get_my_squad()
    elif call == "get_my_xi":
        out = model_tools.get_my_xi()
    elif call == "set_my_squad":
        out = model_tools.set_my_squad([1] * 15, 1, 2, [3, 4, 5, 6])
    elif call == "propose_transfers":
        out = model_tools.propose_transfers()
    else:
        out = model_tools.get_price_movements()

    assert seen == [9001], f"{call} resolved {seen}, not [9001]"
    assert isinstance(out, dict)


def _legal_document():
    """A minimal legal squad document, built from squad_store's own helpers so
    the test never hand-writes the shape."""
    import pandas as pd
    rows = []
    plan = [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]
    el = 1
    for pos, n in plan:
        for _ in range(n):
            rows.append({"element": el, "name": f"P{el}", "position": pos,
                         "team": f"Club{el}", "purchase_price": 40,
                         "role": "start", "bench_order": None})
            el += 1
    # XI: 1 GK, 4 DEF, 4 MID, 2 FWD; bench the rest in order
    bench = [rows[1], rows[6], rows[11], rows[14]]
    for i, b in enumerate(bench, start=1):
        b["role"] = "bench"
        b["bench_order"] = i
    rows[12]["role"] = "CAPTAIN"
    rows[13]["role"] = "VICE"
    return squad_store.document(pd.DataFrame(rows), 400, 1, 0, "2026-27",
                                {"kind": "test"})
