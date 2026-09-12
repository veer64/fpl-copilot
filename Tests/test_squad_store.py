"""
Tests for squad_store.py -- the squad-versions document, its legality check,
and the round trip to squad_state.SquadState.

Pure Python: the laptop has no Postgres, so the table itself is exercised on
the server (Logs/squad_state_log.md); what CAN be pinned here is that no
illegal document can be built, that a legal one survives the trip into
SquadState and back, and that the GW4 seed the server was given is legal and
costs what the seed record says.

Run:
    uv run pytest Tests/test_squad_store.py -v
"""

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import squad_store                                         # noqa: E402
import seed_squad_gw4                                      # noqa: E402
from squad_state import SquadState, sell_price             # noqa: E402


# ---------------------------------------------------------------- fixtures
def legal_players():
    """A legal fifteen: 2/5/5/3, three clubs of three, 4-3-3 XI."""
    spec = [("GK", "A"), ("GK", "B"), ("DEF", "A"), ("DEF", "A"), ("DEF", "B"),
            ("DEF", "C"), ("DEF", "D"), ("MID", "B"), ("MID", "C"), ("MID", "C"),
            ("MID", "D"), ("MID", "E"), ("FWD", "D"), ("FWD", "E"), ("FWD", "F")]
    roles = ["start", "bench", "start", "start", "start", "start", "bench",
             "start", "VICE", "start", "bench", "bench", "CAPTAIN", "start", "start"]
    bench_order = iter([1, 2, 3, 4])
    out = []
    for i, ((pos, team), role) in enumerate(zip(spec, roles), start=1):
        out.append({"element": i, "name": f"P{i}", "position": pos, "team": team,
                    "purchase_price": 40 + i, "role": role,
                    "bench_order": next(bench_order) if role == "bench" else None})
    return out


def legal_doc():
    return {"schema": 1, "season": "2026-27", "players": legal_players(),
            "bank": 7, "free_transfers": 1, "total_points": 0, "provenance": {"kind": "test"}}


def expect_illegal(doc, fragment):
    with pytest.raises(ValueError) as ei:
        squad_store.validate_document(doc)
    assert fragment in str(ei.value), str(ei.value)


# ------------------------------------------------------------ legality
def test_legal_document_validates():
    squad_store.validate_document(legal_doc())


def test_fourteen_players_is_illegal():
    d = legal_doc()
    d["players"] = d["players"][:14]
    expect_illegal(d, "14 players")


def test_position_quota_is_exact():
    d = legal_doc()
    d["players"][1]["position"] = "DEF"          # 1 GK, 6 DEF
    expect_illegal(d, "GK: 1 in squad")
    expect_illegal(d, "DEF: 6 in squad")


def test_club_cap_is_three():
    d = legal_doc()
    d["players"][4]["team"] = "A"                 # A now has four
    expect_illegal(d, "A: 4 players, max 3")


def test_duplicate_element_is_illegal():
    d = legal_doc()
    d["players"][1]["element"] = d["players"][0]["element"]
    expect_illegal(d, "duplicate elements")


def test_exactly_one_captain_and_one_vice():
    d = legal_doc()
    d["players"][0]["role"] = "CAPTAIN"           # two captains
    expect_illegal(d, "2 captains")
    d = legal_doc()
    d["players"][8]["role"] = "start"             # no vice
    expect_illegal(d, "0 vice-captains")


def test_bench_order_must_be_one_to_four_once_each():
    d = legal_doc()
    bench = [p for p in d["players"] if p["role"] == "bench"]
    bench[0]["bench_order"] = 2                   # 2,2,3,4
    expect_illegal(d, "bench_order must be exactly 1..4")


def test_starter_may_not_carry_bench_order():
    d = legal_doc()
    d["players"][0]["bench_order"] = 1
    expect_illegal(d, "carries bench_order")


def test_xi_formation_bounds():
    """Bench the only starting GK and start the bench GK's slot with a DEF
    -> XI has 0 GK, which no formation allows."""
    d = legal_doc()
    gk_start = next(p for p in d["players"] if p["position"] == "GK" and p["role"] == "start")
    gk_bench = next(p for p in d["players"] if p["position"] == "GK" and p["role"] == "bench")
    gk_start["role"], gk_start["bench_order"] = "bench", gk_bench["bench_order"]
    gk_bench["role"], gk_bench["bench_order"] = "bench", 1
    # now 5 bench rows and 10 in the XI; fix the count by starting a bench DEF
    d_bench = next(p for p in d["players"] if p["position"] == "DEF" and p["role"] == "bench")
    d_bench["role"], d_bench["bench_order"] = "start", None
    gk_start["bench_order"] = d_bench["bench_order"] or 2
    # re-number bench 1..4 deterministically
    for i, p in enumerate(sorted((p for p in d["players"] if p["role"] == "bench"),
                                 key=lambda p: p["element"]), start=1):
        p["bench_order"] = i
    expect_illegal(d, "XI has 0 GK")


def test_purchase_price_must_be_positive_int_tenths():
    d = legal_doc()
    d["players"][0]["purchase_price"] = 5.0       # millions, not tenths -> refused
    expect_illegal(d, "purchase_price must be a positive int")


def test_bank_cannot_be_negative_and_free_transfers_are_capped():
    d = legal_doc()
    d["bank"] = -1
    expect_illegal(d, "bank must be a non-negative int")
    d = legal_doc()
    d["free_transfers"] = 6
    expect_illegal(d, "free_transfers must be an int in 0..5")


def test_all_problems_are_listed_at_once():
    d = legal_doc()
    d["bank"] = -1
    d["players"][0]["role"] = "CAPTAIN"
    d["players"][4]["team"] = "A"
    with pytest.raises(ValueError) as ei:
        squad_store.validate_document(d)
    msg = str(ei.value)
    assert "bank" in msg and "captains" in msg and "max 3" in msg


def test_wrong_schema_version_is_refused():
    d = legal_doc()
    d["schema"] = 2
    expect_illegal(d, "schema must be 1")


# ---------------------------------------------------------- round trip
def test_document_to_state_and_back_is_identity():
    d = legal_doc()
    state = squad_store.to_state(d)
    assert isinstance(state, SquadState)
    assert state.bank == 7 and state.free_transfers == 1 and state.total_points == 0
    assert sorted(state.elements) == list(range(1, 16))
    back = squad_store.document(state.squad, state.bank, state.free_transfers,
                                state.total_points, d["season"], d["provenance"])
    assert back == d
    json.dumps(back)                                 # plain Python throughout


def test_state_from_document_applies_the_sell_price_rule():
    """The purchase price in the document is what the sell rule reads. A
    player bought at 41 now priced 45 sells for 43 -- half the rise, not the
    market price. This is why the document stores purchase_price."""
    state = squad_store.to_state(legal_doc())
    assert state.element_sell_price(1, {1: 45}) == sell_price(41, 45) == 43
    assert state.element_sell_price(1, {1: 38}) == 38


def test_document_refuses_an_illegal_state_frame():
    d = legal_doc()
    d["players"][1]["position"] = "DEF"
    with pytest.raises(ValueError):
        squad_store.document(d["players"], 7, 1, 0, "2026-27", {})


# ------------------------------------------------------------- the seed
def test_gw4_seed_is_legal_and_costs_99_6():
    doc = seed_squad_gw4.build_document()
    squad_store.validate_document(doc)
    assert doc["season"] == "2026-27"
    cost = sum(p["purchase_price"] for p in doc["players"])
    assert cost == 996                                # 99.6m in tenths
    assert doc["bank"] == 4                           # 100.0 - 99.6
    assert cost + doc["bank"] == 1000
    assert doc["free_transfers"] == 1 and doc["total_points"] == 0
    roles = {p["role"]: p["name"] for p in doc["players"] if p["role"] in ("CAPTAIN", "VICE")}
    assert roles == {"CAPTAIN": "Erling Haaland", "VICE": "Phil Foden"}
    assert doc["provenance"]["hypothetical"] is True
    assert doc["provenance"]["seeded_from"]["model_runs.run_id"] == 4


def test_gw4_seed_sql_embeds_the_document_and_the_cross_check():
    doc = seed_squad_gw4.build_document()
    sql = seed_squad_gw4.emit_sql(doc)
    assert sql.startswith("BEGIN;") and sql.rstrip().endswith("COMMIT;")
    assert "RAISE EXCEPTION 'seed cross-check failed" in sql
    assert "refusing to seed" in sql
    payload = sql.split("$json$")[1]
    assert json.loads(payload) == doc                 # what runs is what was validated
    assert "INSERT INTO squad_versions" in sql and "RETURNING version_id" in sql


def test_seed_document_round_trips_through_state():
    doc = seed_squad_gw4.build_document()
    state = squad_store.to_state(doc)
    assert state.bank == 4
    assert state.sell_value({}) == 996                # no prices -> valued at cost
    back = squad_store.document(state.squad, state.bank, state.free_transfers,
                                state.total_points, doc["season"], doc["provenance"])
    assert back == doc
