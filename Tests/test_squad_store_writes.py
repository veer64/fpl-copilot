"""
Tests for the WRITE side of squad_store.py (set_my_squad, step 4) and the
DDL pin.

Pure Python, no database: plan_change is a pure function of the active
record, the requested fifteen + roles, and a players_live snapshot; the
money moves through squad_state.SquadState.make_transfers (the one
implementation of FPL's sell rule), and this file pins what that implies --
a riser recovers half the rise rounded down, a faller loses it all, a set of
transfers pools its money, an unaffordable set is refused rather than
clamped, hits are charged beyond the free allowance, and total wealth is
conserved by any affordable move (a Hypothesis property). write_version is
exercised through a fake connection: flip first, insert with supersedes,
commit only on confirm, refuse if the row was superseded meanwhile.

The trigger itself cannot be tested here (no Postgres on the laptop); it was
exercised on the server on 2026-09-12 (Logs/squad_state_log.md).

Run:
    uv run pytest Tests/test_squad_store_writes.py -v
"""

import copy
import hashlib
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import squad_store                                         # noqa: E402
from scoring import HIT_COST                               # noqa: E402
from squad_state import sell_price                         # noqa: E402
from test_squad_store import legal_doc, _row               # noqa: E402


# ---------------------------------------------------------------- fixtures
def _live(extra=None, **price_over):
    """players_live rows for the legal_doc fifteen (element i at 40+i, the
    purchase price -> no rise) plus candidate signings. Overrides by element."""
    d = legal_doc()
    live = {p["element"]: {"name": p["name"], "position": p["position"],
                           "team": p["team"], "price_tenths": p["purchase_price"]}
            for p in d["players"]}
    live.update({
        99: {"name": "NewDef", "position": "DEF", "team": "Z", "price_tenths": 45},
        95: {"name": "NewDef2", "position": "DEF", "team": "Y", "price_tenths": 49},
        98: {"name": "NewMid", "position": "MID", "team": "Z", "price_tenths": 60},
        97: {"name": "NewGk", "position": "GK", "team": "Y", "price_tenths": 50},
    })
    if extra:
        live.update(extra)
    for e, p in price_over.items():
        live[int(e)]["price_tenths"] = p
    return live


def _active(bank=7, ft=1, gw=4):
    d = legal_doc()
    d["bank"], d["free_transfers"] = bank, ft
    return _row(d, version_id=1, gw=gw)


IDS = list(range(1, 16))
CAP, VICE, BENCH = 13, 9, [2, 7, 11, 12]     # as legal_players() assigns them


def _plan(active, ids, live, captain=CAP, vice=VICE, bench=BENCH, gw=4):
    return squad_store.plan_change(active, ids, captain, vice, bench, gw, live,
                                   priced_from="test", created_by="test")


# ------------------------------------------------------------- the money
def test_no_change_re_versions_roles_and_keeps_the_money():
    doc, change = _plan(_active(), IDS, _live(), captain=14, vice=13)
    assert change["n_transfers"] == 0 and change["hits"] == 0
    assert change["bank_after"] == 7 and doc["bank"] == 7
    assert doc["free_transfers"] == 1                       # nothing consumed
    by = {p["element"]: p for p in doc["players"]}
    assert by[14]["role"] == "CAPTAIN" and by[13]["role"] == "VICE" and by[9]["role"] == "start"
    assert {p["element"]: p["purchase_price"] for p in doc["players"]} == {i: 40 + i for i in IDS}
    assert doc["provenance"]["from_version"] == 1 and doc["provenance"]["kind"] == "set_my_squad"


def test_one_transfer_at_an_unchanged_price():
    ids = [i for i in IDS if i != 3] + [99]                  # DEF 3 (bought 43) -> DEF 99 (45)
    doc, change = _plan(_active(), ids, _live())
    assert change["transfers"] == [{"out": 3, "out_name": "P3", "sold_for": 43,
                                    "in": 99, "in_name": "NewDef", "bought_for": 45}]
    assert change["bank_after"] == 7 + 43 - 45 == 5 == doc["bank"]
    assert change["free_transfers_used"] == 1 and change["free_transfers_after"] == 0
    assert change["hits"] == 0 and change["hit_cost_points"] == 0
    new = next(p for p in doc["players"] if p["element"] == 99)
    assert new["purchase_price"] == 45 and new["name"] == "NewDef" and new["role"] == "start"
    assert 3 not in {p["element"] for p in doc["players"]}


def test_selling_a_riser_recovers_half_the_rise_rounded_down():
    """P3 bought 43, now 48: sell = 43 + 5 // 2 = 45, not 48."""
    ids = [i for i in IDS if i != 3] + [99]
    doc, change = _plan(_active(), ids, _live(**{"3": 48}))
    assert change["transfers"][0]["sold_for"] == 45 == sell_price(43, 48)
    assert doc["bank"] == 7 + 45 - 45 == 7


def test_selling_a_faller_takes_the_whole_loss():
    ids = [i for i in IDS if i != 3] + [99]
    doc, change = _plan(_active(), ids, _live(**{"3": 40}))
    assert change["transfers"][0]["sold_for"] == 40
    assert doc["bank"] == 7 + 40 - 45 == 2


def test_unaffordable_move_is_refused_not_clamped():
    ids = [i for i in IDS if i != 3] + [99]
    with pytest.raises(ValueError) as ei:
        _plan(_active(bank=0), ids, _live(**{"99": 60}))    # 0 + 43 - 60 < 0
    assert "unaffordable" in str(ei.value)


def test_two_transfers_pool_the_money_like_fpl_settles_them():
    """Sell 3 (43) and 4 (44) = 87; buy 99 (45) and 95 (49) = 94; bank 7 -> 0.
    Done one at a time the second leg fails; as a set it is legal."""
    ids = [i for i in IDS if i not in (3, 4)] + [99, 95]
    doc, change = _plan(_active(bank=7, ft=2), ids, _live())
    assert change["n_transfers"] == 2 and change["bank_after"] == 0 == doc["bank"]
    assert change["proceeds"] == 87 and change["purchases"] == 94
    assert change["hits"] == 0 and doc["free_transfers"] == 0


def test_transfers_beyond_free_are_hits_at_four_points():
    ids = [i for i in IDS if i not in (3, 4)] + [99, 95]
    doc, change = _plan(_active(bank=7, ft=1), ids, _live())
    assert change["free_transfers_used"] == 1 and change["hits"] == 1
    assert change["hit_cost_points"] == HIT_COST == 4
    assert doc["provenance"]["hits"] == 1 and doc["total_points"] == 0   # reported, not deducted


@settings(max_examples=150, deadline=None)
@given(drift=st.integers(min_value=-6, max_value=12),
       buy=st.integers(min_value=38, max_value=70),
       bank=st.integers(min_value=0, max_value=40))
def test_wealth_is_conserved_by_any_affordable_move(drift, buy, bank):
    """Sell value at current prices + bank is unchanged by a transfer, for
    any price drift on the outgoing player and any purchase price. The
    property behind squad_state's test, re-asserted through the store."""
    live = _live(**{"3": max(38, 43 + drift), "99": buy})
    ids = [i for i in IDS if i != 3] + [99]
    active = _active(bank=bank)
    old = squad_store.to_state(active["squad_json"])
    prices = {e: live[e]["price_tenths"] for e in live}
    wealth_before = old.sell_value(prices) + bank
    try:
        doc, change = _plan(active, ids, live)
    except ValueError as e:
        assert "unaffordable" in str(e)
        return
    new = squad_store.to_state(doc)
    assert new.sell_value(prices) + doc["bank"] == wealth_before
    assert change["wealth_after"] == change["wealth_before"] == wealth_before


# ------------------------------------------------------------ refusals
def test_position_shape_must_be_kept():
    ids = [i for i in IDS if i != 3] + [98]                  # DEF out, MID in
    with pytest.raises(ValueError) as ei:
        _plan(_active(), ids, _live())
    assert "2 GK / 5 DEF / 5 MID / 3 FWD" in str(ei.value) and "DEF" in str(ei.value)


def test_fifteen_distinct_ids_required():
    with pytest.raises(ValueError):
        _plan(_active(), IDS[:14], _live())
    with pytest.raises(ValueError):
        _plan(_active(), IDS[:14] + [14], _live())


def test_unknown_or_unpriced_element_is_refused():
    ids = [i for i in IDS if i != 3] + [1234]
    with pytest.raises(ValueError) as ei:
        _plan(_active(), ids, _live())
    assert "1234" in str(ei.value)
    live = _live()
    live[3]["price_tenths"] = None                            # owned but unpriced today
    with pytest.raises(ValueError):
        _plan(_active(), IDS, live)


def test_captain_and_vice_must_start_and_differ():
    with pytest.raises(ValueError):
        _plan(_active(), IDS, _live(), captain=2)             # 2 is bench
    with pytest.raises(ValueError):
        _plan(_active(), IDS, _live(), captain=13, vice=13)
    with pytest.raises(ValueError):
        _plan(_active(), IDS, _live(), bench=[2, 7, 11])      # three on the bench


def test_gw_cannot_go_backwards():
    with pytest.raises(ValueError) as ei:
        _plan(_active(gw=4), IDS, _live(), gw=3)
    assert "gw" in str(ei.value)


def test_active_record_is_not_mutated_by_planning():
    active = _active()
    before = copy.deepcopy(active)
    ids = [i for i in IDS if i != 3] + [99]
    _plan(active, ids, _live(**{"3": 48}))
    assert active == before


# ------------------------------------------------------------- the write
class _WriteCursor:
    def __init__(self, results):
        self.results, self.executed = list(results), []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.results.pop(0)

    def fetchone(self):
        return self.results.pop(0)


class _WriteConn:
    def __init__(self, results):
        self.cur, self.commits, self.rollbacks = _WriteCursor(results), 0, 0

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _inserted_row(version_id=2):
    return {"version_id": version_id, "user_id": 1, "season": "2026-27", "gw": 4,
            "created_at": "t", "is_active": True, "supersedes": 1, "note": "n"}


def test_write_version_flips_then_inserts_with_supersedes_and_commits_on_confirm():
    active, (doc, _) = _active(), _plan(_active(), IDS, _live())
    conn = _WriteConn([[{"version_id": 1}], _inserted_row()])
    row = squad_store.write_version(active, doc, 4, "n", confirm=True, conn=conn)
    (upd, upd_p), (ins, ins_p) = conn.cur.executed
    assert upd.startswith("UPDATE squad_versions SET is_active = FALSE") and "AND is_active" in upd
    assert upd_p == (1, 1)
    assert ins.startswith("INSERT INTO squad_versions") and ins_p[4] == 1 and ins_p[2] == 4
    assert conn.commits == 1 and conn.rollbacks == 0
    assert row["committed"] is True and row["supersedes"] == 1 and row["squad_json"] == doc


def test_write_version_preview_runs_the_same_statements_and_rolls_back():
    active, (doc, _) = _active(), _plan(_active(), IDS, _live())
    conn = _WriteConn([[{"version_id": 1}], _inserted_row()])
    row = squad_store.write_version(active, doc, 4, "n", confirm=False, conn=conn)
    assert len(conn.cur.executed) == 2
    assert conn.commits == 0 and conn.rollbacks == 1
    assert row["committed"] is False


def test_write_version_refuses_when_the_active_row_was_superseded_meanwhile():
    active, (doc, _) = _active(), _plan(_active(), IDS, _live())
    conn = _WriteConn([[]])                                  # UPDATE flipped nothing
    with pytest.raises(squad_store.SquadStateError) as ei:
        squad_store.write_version(active, doc, 4, "n", confirm=True, conn=conn)
    assert "no longer the active squad" in str(ei.value)
    assert len(conn.cur.executed) == 1 and conn.commits == 0 and conn.rollbacks >= 1


def test_write_version_validates_before_touching_the_database():
    active = _active()
    bad = legal_doc()
    bad["players"][0]["role"] = "CAPTAIN"
    conn = _WriteConn([])
    with pytest.raises(ValueError):
        squad_store.write_version(active, bad, 4, "n", confirm=True, conn=conn)
    assert conn.cur.executed == []


# ------------------------------------------------------------ the DDL pin
DDL_SHA256 = "c53561a600a38070a5104da96b06009ad7d8729478aab7c12afc7c33d73d00ff"


def test_ddl_is_stable():
    """The schema of record applied to the server on 2026-09-12. A change
    here must be deliberate: re-pin AND re-apply (ensure_schema is
    idempotent for the table and index; the trigger body is replaced)."""
    assert hashlib.sha256(squad_store.DDL.encode("utf-8")).hexdigest() == DDL_SHA256
    for must in ("CREATE TABLE IF NOT EXISTS squad_versions", "ux_squad_versions_one_active",
                 "trg_squad_versions_append_only", "BEFORE UPDATE OR DELETE",
                 "supersedes  INT         REFERENCES squad_versions(version_id)"):
        assert must in squad_store.DDL, must
