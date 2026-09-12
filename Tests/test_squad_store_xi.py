"""
Tests for the roles contract (step 5a, 2026-09-12): recorded roles are a
record, never a recommendation, and the live XI is SOLVED over the owned
fifteen.

The bug this pins: on GW4 the app showed the seed's roles (copied from the
GW3 solve, written 05:24Z) next to run 5's GW4 predictions (11:01Z) -- four
defenders starting, a 4.04-point midfielder on the bench -- and presented it
as advice. Both halves were right; the join was wrong.

Pure Python plus one real single-gameweek MIP solve (~1 s) on a synthetic
fifteen. No database, no network, no model-path code.

Run:
    uv run pytest Tests/test_squad_store_xi.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import squad_store                                         # noqa: E402
from test_squad_store import legal_doc, _row               # noqa: E402

T0 = datetime(2026, 9, 12, 5, 24, 53, tzinfo=timezone.utc)


# --------------------------------------------------------- roles status
def _run(gw, finished_at, run_id=5):
    return {"run_id": run_id, "gw": gw, "finished_at": finished_at}


def test_roles_are_stale_when_a_run_landed_after_they_were_recorded():
    rec = _row(legal_doc(), gw=4, created_at=T0)
    st = squad_store.roles_status(rec, _run(4, T0 + timedelta(hours=5)))
    assert st["status"] == "STALE"
    assert "not a recommendation for GW4" in st["warning"] and "get_my_xi" in st["warning"]
    assert st["as_of_gw"] == 4 and st["latest_run"]["run_id"] == 5


def test_roles_are_stale_when_the_latest_run_is_a_later_gameweek():
    rec = _row(legal_doc(), gw=4, created_at=T0 + timedelta(hours=8))
    st = squad_store.roles_status(rec, _run(5, T0 + timedelta(hours=6)))     # GW5 run, earlier clock
    assert st["status"] == "STALE"


def test_roles_are_current_when_recorded_after_the_latest_run_for_that_gw():
    rec = _row(legal_doc(), gw=4, created_at=T0 + timedelta(hours=8))
    st = squad_store.roles_status(rec, _run(4, T0 + timedelta(hours=6)))
    assert st["status"] == "current" and st["warning"] is None


def test_roles_status_accepts_postgres_style_strings():
    rec = _row(legal_doc(), gw=4, created_at="2026-09-12 05:24:53.200336+00")
    st = squad_store.roles_status(rec, _run(4, "2026-09-12 11:01:01.624851+00"))
    assert st["status"] == "STALE"


def test_roles_status_without_a_run_is_unknown_not_current():
    st = squad_store.roles_status(_row(legal_doc()), None)
    assert st["status"] == "UNKNOWN" and st["warning"]


def test_summary_labels_roles_as_recorded_and_carries_the_status():
    d = legal_doc()
    out = squad_store.summary(_row(d, gw=4, created_at=T0), {},
                              latest_run=_run(4, T0 + timedelta(hours=5)))
    assert out["roles"]["status"] == "STALE"
    assert out["roles"]["meaning"] == squad_store.ROLES_MEANING
    assert "recorded_captain" in out and "captain" not in out          # no unlabelled roles
    assert "recorded_xi" in out and "xi" not in out
    assert all("recorded_role" in r for r in out["recorded_xi"] + out["recorded_bench_in_order"])


# ------------------------------------------------------------ the XI solve
def _pool_for(doc, points, pplay=None):
    """One gameweek's pool for the fifteen in `doc` (optimize's shape)."""
    rows = []
    for p in doc["players"]:
        e = p["element"]
        rows.append({"element": e, "name": p["name"], "position": p["position"],
                     "team": p["team"], "value": p["purchase_price"],
                     "e_points": float(points[e]),
                     "p_play_any": float((pplay or {}).get(e, 0.9)),
                     "p_60plus": float((pplay or {}).get(e, 0.9))})
    return pd.DataFrame(rows)


def _collins_gomez_points():
    """legal_doc: GK 1,2; DEF 3..7; MID 8..12; FWD 13..15. Recorded roles start
    DEF 3,4,5,6 (four defenders) and bench MID 11 -- the GW4 shape. Give the
    fourth starting DEF (6) 2.46 and the benched MID (11) 4.04."""
    pts = {1: 3.4, 2: 2.6, 3: 4.4, 4: 4.3, 5: 4.2, 6: 2.46, 7: 2.8,
           8: 4.6, 9: 3.8, 10: 4.6, 11: 4.04, 12: 2.3, 13: 5.9, 14: 4.5, 15: 4.3}
    return pts


def test_xi_solve_benches_the_fourth_defender_for_the_better_midfielder():
    d = legal_doc()
    pts = _collins_gomez_points()
    state = squad_store.to_state(d)
    team, missing = squad_store.xi_over_fifteen(_pool_for(d, pts), state, {})
    assert missing == []
    roles = squad_store.roles_from_team(team)
    assert roles[6][0] == "bench" and roles[11][0] != "bench"          # Collins out, Gomez in
    assert roles[13][0] == "CAPTAIN"                                    # 5.9, the top scorer
    assert roles[8][0] == "VICE" or roles[10][0] == "VICE"              # 4.6 tie for second
    starters = [e for e, (r, _) in roles.items() if r != "bench"]
    assert len(starters) == 11
    pos = {p["element"]: p["position"] for p in d["players"]}
    assert sum(pos[e] == "DEF" for e in starters) == 3
    assert sorted(bo for r, bo in roles.values() if r == "bench") == [1, 2, 3, 4]
    assert roles[2] == ("bench", 1)                                     # bench GK is slot 1


def test_compare_roles_reports_the_change_and_the_points_left_on_the_table():
    d = legal_doc()
    pts = _collins_gomez_points()
    team, _ = squad_store.xi_over_fifteen(_pool_for(d, pts), squad_store.to_state(d), {})
    cmp = squad_store.compare_roles(d["players"], team)
    assert cmp["differ"] is True
    changed = {c["player_id"]: (c["recorded"], c["optimal"]) for c in cmp["changes"]}
    assert changed[6][0] == "start" and changed[6][1].startswith("bench")
    assert changed[11][0] == "bench 3" and changed[11][1] in ("start", "VICE")
    # recorded XI: 1,3,4,5,6,8,9(V),10,13(C),14,15 ; optimal swaps 6 (2.46) for 11 (4.04)
    assert cmp["expected_gain_vs_recorded"] == pytest.approx(4.04 - 2.46, abs=1e-9)
    assert cmp["optimal_xi_points"] == pytest.approx(cmp["recorded_xi_points"] + 1.58, abs=1e-9)


def test_compare_roles_is_empty_when_recorded_roles_are_already_optimal():
    d = legal_doc()
    pts = _collins_gomez_points()
    team, _ = squad_store.xi_over_fifteen(_pool_for(d, pts), squad_store.to_state(d), {})
    adopted = squad_store.roles_from_team(team)
    for p in d["players"]:
        p["role"], p["bench_order"] = adopted[p["element"]]
    squad_store.validate_document(d)                                    # the adopted roles are legal
    cmp = squad_store.compare_roles(d["players"], team)
    assert cmp["differ"] is False and cmp["changes"] == [] and cmp["expected_gain_vs_recorded"] == 0


def test_owned_player_missing_from_the_frame_is_injected_at_zero_and_reported():
    d = legal_doc()
    pts = _collins_gomez_points()
    pool = _pool_for(d, pts)
    pool = pool[pool["element"] != 13]                                  # the 5.9 forward has no row
    team, missing = squad_store.xi_over_fifteen(pool, squad_store.to_state(d), {})
    assert missing == [13]
    roles = squad_store.roles_from_team(team)
    assert roles[13][0] == "bench"                                      # 0 points -> benched
    assert float(team.loc[team["element"] == 13, "e_points"].iloc[0]) == 0.0


def test_bench_order_convention_mapping():
    assert squad_store.doc_bench_order(0) == 1 and squad_store.doc_bench_order(3) == 4
    assert squad_store.doc_bench_order(None) is None
    assert squad_store.doc_bench_order(float("nan")) is None
