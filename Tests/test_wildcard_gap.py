"""The four features of 2026-10-08: past picks on get_picks (4a), get_prediction_history (4b),
get_wildcard_gap (4c) and get_fixtures' season summary of doubles and blanks (4d).

4a: get_picks with a played gameweek used to be told "already played" and sent elsewhere; now it
answers with the stored fifteen of the last run before that deadline and scores it through the
one scorer (scoring.score_gameweek on the stored actuals). 4b: one query over the stored runs,
oldest to newest, so "what changed overnight" never needs a run id. 4c: the same decayed-horizon
MIP propose_transfers runs, with its wildcard relief, against the current squad's best XI each
gameweek. 4d: the calendar already held every double and blank; the tool now says so for a club.

Pure except 4c, which runs one real small MIP on a synthetic horizon frame (~2 s). The IO helpers
are monkeypatched; nothing reads the database, the volume or the network.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402

UTC = timezone.utc


# ---------------------------------------------------------------- 4c
def _frame():
    from test_optimize import make_random_pool
    pool = make_random_pool(7)
    pool["p_play_any"] = 0.9
    pool["p_60plus"] = 0.8
    frames = []
    for gw in (6, 7):
        f = pool.copy()
        f["gw"] = gw
        f["cutoff"] = 6
        if gw == 7:
            f["e_points"] = (f["e_points"] * 0.9).round(2)
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def _owned(pool):
    from test_transfer_mip import a_squad
    return a_squad(pool)


@pytest.fixture
def gap_env(monkeypatch):
    df = _frame()
    pool6 = df[df["gw"] == 6]
    owned = _owned(pool6)
    rows = pool6[pool6["element"].isin(owned)]
    players = []
    xi = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
    bench_i = iter([1, 2, 3, 4])
    cap_done = vice_done = False
    for r in rows.sort_values(["position", "e_points"], ascending=[True, False]).itertuples():
        if xi[r.position] > 0:
            xi[r.position] -= 1
            role = "start"
            if r.position == "MID" and not cap_done:
                role, cap_done = "CAPTAIN", True
            elif r.position == "MID" and not vice_done:
                role, vice_done = "VICE", True
            bo = None
        else:
            role, bo = "bench", next(bench_i)
        players.append({"element": int(r.element), "name": r.name, "position": r.position, "team": r.team,
                        "purchase_price": int(r.value), "role": role, "bench_order": bo})
    gk_bench = [p for p in players if p["position"] == "GK" and p["role"] == "bench"]
    assert len(gk_bench) == 1
    # the bench GK must be bench 1: re-number
    others = sorted((p for p in players if p["role"] == "bench" and p["position"] != "GK"), key=lambda p: p["bench_order"])
    gk_bench[0]["bench_order"] = 1
    for i, p in enumerate(others, start=2):
        p["bench_order"] = i
    doc = {"schema": 1, "season": "2026-27", "players": players, "bank": 5, "free_transfers": 1, "total_points": 0,
           "provenance": {"kind": "test"}}
    squad_store.validate_document(doc)
    record = {"version_id": 2, "user_id": 9001, "season": "2026-27", "gw": 6, "created_at": datetime(2026, 10, 2, tzinfo=UTC),
              "is_active": True, "supersedes": None, "note": "t", "squad_json": doc}
    monkeypatch.setattr(squad_store, "read_active", lambda uid=None, conn=None: record)
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "_load_frame", lambda: (df, 6, datetime(2026, 10, 8, tzinfo=UTC)))
    monkeypatch.setattr(mt, "_frame_built", lambda cutoff: {"built": "built test", "next_run_expected": None})
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    prices = {int(r.element): int(r.value) for r in rows.itertuples()}
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        {"element": e, "name": f"Player{e}", "position": "x", "team": "x", "price_tenths": prices[e]} for e in params[0]])
    import db_write
    monkeypatch.setattr(db_write, "write_proposal", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote a proposal")))
    return df, doc


def test_the_wildcard_gap_compares_the_current_xi_with_the_free_pick_plan_per_gameweek(gap_env):
    out = mt.get_wildcard_gap(user_id=9001)
    assert "error" not in out, out
    assert out["gw"] == 6 and out["horizon_gws"] == [6, 7] and out["nothing_written"] is True
    assert [r["gw"] for r in out["per_gw"]] == [6, 7]
    for r in out["per_gw"]:
        assert r["gap"] == round(r["free_pick_xi_points"] - r["current_squad_xi_points"], 2)
        assert r["current_squad_captain"] and r["free_pick_captain"]
    t = out["totals"]
    assert t["gap"] == round(t["free_pick_xi_points"] - t["current_squad_xi_points"], 2)
    assert t["gap_decayed"] == round(t["free_pick_decayed"] - t["current_squad_decayed"], 2)
    assert out["per_gw"][0]["decay_weight"] == 1.0 and out["per_gw"][1]["decay_weight"] == out["decay"]
    assert 0 <= out["transfers_needed"] <= 15
    assert len(out["free_pick_squad"]["xi"]) == 11 and len(out["free_pick_squad"]["bench_in_order"]) == 4
    assert len(out["free_pick_squad"]["sells"]) == out["transfers_needed"] == len(out["free_pick_squad"]["buys"])
    assert out["refused"] is False and "the user's" in out["decision"]
    assert "the line-up solve" in out["basis"] and "the transfer plan" in out["basis"]   # Part 4a: no tool names
    assert "get_my_xi" not in out["basis"] and "propose_transfers" not in out["basis"]
    assert out["without_wildcard"]["transfers_needed"] == out["transfers_needed"]       # Part 5a


def test_the_current_side_is_get_my_xis_own_number(gap_env):
    """The current squad's figure for the deadline gameweek is exactly what get_my_xi reports."""
    df, doc = gap_env
    import simulator as sim
    out = mt.get_wildcard_gap(user_id=9001)
    state = squad_store.to_state(doc)
    prices = {p["element"]: p["purchase_price"] for p in doc["players"]}
    team, _ = squad_store.xi_over_fifteen(sim.gw_slice(df, 6, cutoff=6), state, prices)
    assert out["per_gw"][0]["current_squad_xi_points"] == squad_store.compare_roles(doc["players"], team)["optimal_xi_points"]


def test_a_degraded_model_withholds_the_gap_but_not_the_two_sides(gap_env, monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: {"run_id": 24, "gw": 6})
    monkeypatch.setattr(mt, "_model_degraded_reasons", lambda run: ["a runaway strength"])
    out = mt.get_wildcard_gap(user_id=9001)
    assert out["refused"] is True and "KNOWN_ISSUES #25" in out["refusal"]
    assert out["totals"]["gap"] is None and out["totals"]["gap_decayed"] is None
    assert out["totals"]["free_pick_xi_points"] is not None and out["per_gw"]


def test_no_squad_is_an_error_not_a_substitute(monkeypatch):
    monkeypatch.setattr(squad_store, "read_active", lambda uid=None, conn=None: (_ for _ in ()).throw(
        squad_store.SquadStateError("no active squad version for user 9001")))
    out = mt.get_wildcard_gap(user_id=9001)
    assert "no active squad version" in out["error"]




# ---------------------------------------------------------------- the surface
def test_the_two_new_tools_are_registered_and_the_count_is_24():
    import agent
    names = {t["name"] for t in agent.tools_schema}
    assert {"get_prediction_history", "get_wildcard_gap"} <= names
    assert len(agent.tools_schema) == 24 and len(agent.available_functions) == 24
    assert set(agent.available_functions) == names
    gp = next(t for t in agent.tools_schema if t["name"] == "get_picks")
    assert "past" in gp["description"].lower()
