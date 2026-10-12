"""Part C agent fixes (2026-10-12): the review of 38 calibration answers found the agent naming clubs from
memory (the optimise rows carried no team), labelling GW6 figures GW7, calling the chance of any appearance a
start probability, reasoning about an infeasible squad instead of naming the rule, inventing facts, and
echoing pipeline jargon (ingest, horizon, cutoff, solve, frame). Locks at the source, one per fix:

  F1 every player row in every tool output carries team and position; prompt line 11 covers clubs/positions
  F2 a gameweek that has already started is said so by the tool, in one fixed sentence
  F3 the probability keys travel with a meanings line; the prompt translates them
  F4 forced players are checked against FPL's squad rules BEFORE the solve; a budget nobody can meet is
     refused with the measured cheapest legal cost
  F5 no pipeline jargon in the tools' prose; the keys that stay get a meanings line
  F6 the prompt carries FPL's scoring basics from scoring.py and the invented-facts rules
  F7 the transfer plan's plain summary says it covers up to six gameweeks

Pure: synthetic pools and rows, a real small MIP solve (~1 s), the IO helpers monkeypatched.
"""
import ast
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402
import optimize                                            # noqa: E402
import scoring                                             # noqa: E402
import squad_store                                         # noqa: E402

PROMPT = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- a pool the MIP can solve
def pool():
    """3 GK, 8 DEF, 8 MID, 5 FWD over eight clubs (T0..T7); element 100 is a cheap midfielder."""
    rows, el = [], 1
    spec = [("GK", 3, 2.0), ("DEF", 8, 3.0), ("MID", 8, 4.0), ("FWD", 5, 5.0)]
    for pos, n, base in spec:
        for i in range(n):
            rows.append({"element": el, "name": f"{pos}{i}", "position": pos, "team": f"T{el % 8}",
                         "value": 45 + 5 * i, "e_points": base + 0.3 * i, "p_play_any": 0.9, "p_60plus": 0.8})
            el += 1
    rows.append({"element": 100, "name": "Benchwarmer", "position": "MID", "team": "T1", "value": 40,
                 "e_points": 0.5, "p_play_any": 0.5, "p_60plus": 0.2})
    return pd.DataFrame(rows)


@pytest.fixture
def solver_env(monkeypatch):
    df = pool()
    monkeypatch.setattr(mt, "_load_pool", lambda gw=None: (df, 6, datetime(2026, 10, 8, tzinfo=timezone.utc)))
    monkeypatch.setattr(mt, "_frame_built", lambda cutoff: {"built": "built test", "next_run_expected": None})
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    names = {int(r.element): r.name for r in df.itertuples()}
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        {"element": e, "name": names[e]} for e in (params[0] if params else []) if e in names])
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    return df


def fwd_ids(df, n):
    return [int(e) for e in df[df["position"] == "FWD"]["element"].head(n)]


# ================================================================ F1
def test_every_optimise_row_carries_team_and_position(solver_env):
    out = mt.optimise(lock_player_ids=[100])
    assert "error" not in out, out
    for r in out["squad"]:
        assert r.get("team") and r.get("position"), r
    assert mt.player_rows_missing_team_or_position(out) == []


def test_the_walker_finds_rows_without_team_or_position():
    out = {"xi": [{"player_id": 1, "name": "A", "position": "GK", "team": "T1"}, {"player_id": 2, "name": "B", "position": "DEF"}],
           "transfers": [{"out": "C", "out_id": 3, "in": "D", "in_id": 4, "team_in": "T2", "position_in": "MID"}]}
    missing = mt.player_rows_missing_team_or_position(out)
    assert [m["name"] for m in missing] == ["B", "C"] and missing[0]["lacks"] == ["team"]
    assert missing[1]["lacks"] == ["team_out", "position_out"]


def test_compare_players_sides_carry_team_and_position_and_a_meanings_line(monkeypatch):
    def _pred(pid):
        return {"player_id": pid, "model_version": "x", "built_at": "b", "built": "built", "next_run_expected": None,
                "recovered_post_deadline": False, "horizon_e_points_sum": 10.0,
                "predictions": [{"gw": 6, "horizon_step": 0, "e_points": 5.0, "p_start": 0.9}]}
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: _pred(pid))
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [{"element": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City"},
                                                           {"element": 379, "name": "Alexander Isak", "position": "FWD", "team": "Liverpool"}])
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    c = mt.compare_players(411, 379)
    assert c["a"]["team"] == "Man City" and c["a"]["position"] == "FWD" and c["b"]["team"] == "Liverpool"
    assert c["meanings"]["first_gw_p_start"] == mt.PROB_MEANINGS["p_start"]


def test_prediction_history_carries_team_and_position(monkeypatch):
    monkeypatch.setattr(mt, "_element_id", lambda v: 411)
    monkeypatch.setattr(mt, "_horizon_check", lambda *a, **k: None)
    monkeypatch.setattr(mt, "_player_name", lambda e: "Haaland")
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {411: {"name": "Erling Haaland", "position": "FWD", "team": "Man City"}})
    rows = [{"run_id": 7, "kind": "nightly", "slot": None, "finished_at": "2026-10-01", "cutoff": 6, "horizon_step": 0,
             "e_points": 5.1, "p_start": 0.9, "e_minutes": 80.0, "terms_recorded": True}]
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): rows)

    class _DP:
        @staticmethod
        def _fmt(x):
            return str(x)
    monkeypatch.setattr(mt, "_dp", lambda: _DP)
    out = mt.get_prediction_history(411, 6)
    assert out["team"] == "Man City" and out["position"] == "FWD"
    assert out["meanings"]["p_start"] == mt.PROB_MEANINGS["p_start"]


def test_compare_roles_changes_carry_team_and_position():
    team = pd.DataFrame([
        {"element": 1, "name": "A", "position": "GK", "team": "T1", "value": 45, "e_points": 4.0, "role": "start", "bench_order": pd.NA},
        {"element": 2, "name": "B", "position": "DEF", "team": "T2", "value": 50, "e_points": 3.0, "role": "bench", "bench_order": 1},
    ])
    doc = [{"element": 1, "name": "A", "role": "bench", "bench_order": 1}, {"element": 2, "name": "B", "role": "start", "bench_order": None}]
    out = squad_store.compare_roles(doc, team)
    assert out["differ"] is True and all(c["team"] and c["position"] for c in out["changes"]), out


def test_squad_rows_from_the_team_frame_and_transfer_rows_carry_club_and_position():
    team = pd.DataFrame([
        {"element": 1, "name": "A", "position": "GK", "team": "T1", "value": 45, "e_points": 4.0, "role": "CAPTAIN", "bench_order": pd.NA},
        {"element": 2, "name": "B", "position": "DEF", "team": "T2", "value": 50, "e_points": 3.0, "role": "bench", "bench_order": 1},
    ])
    rows = mt._squad_rows_from_team(team, {1: ("CAPTAIN", None), 2: ("bench", 1)}, {1: "A", 2: "B"})
    assert [(r["name"], r["team"], r["position"]) for r in rows] == [("A", "T1", "GK"), ("B", "T2", "DEF")]
    meta = {3: {"team": "T3", "position": "MID"}, 4: {"team": "T4", "position": "MID"}}
    t = mt._transfer_row_meta({"out": "C", "out_id": 3, "in": "D", "in_id": 4}, meta)
    assert t["team_out"] == "T3" and t["position_out"] == "MID" and t["team_in"] == "T4" and t["position_in"] == "MID"
    t2 = mt._transfer_row_meta({"out": "C", "out_id": 3, "in": None, "in_id": None}, meta)
    assert t2["team_in"] is None and t2["position_in"] is None


def test_prompt_line_11_covers_clubs_and_positions():
    line = PROMPT.splitlines()[10]
    assert line.startswith("- Every number you state")
    assert "club" in line and "position" in line and "must come from a tool result in this conversation turn" in line
