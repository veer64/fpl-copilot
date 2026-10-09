"""Part 3 answer shapes (2026-10-08): forced STARTERS on optimise (3a) and the 1-10 fixture scores
that replaced the easy / average / hard bands (3d, closes B24).

3a: "build me a squad with X forced in" means X in the line-up. optimise's lock put him in the
fifteen and let the solver bench him. start_player_ids forces the XI, through the same MIP and the
same refusals as a lock (unknown id, a player who cannot play for his club).

3d: the bands came from fixed thresholds (1.0 / 1.8 expected goals, 0.20 / 0.35 clean-sheet
probability) and said nothing about where a fixture sat among the others. The scores are decile
ranks among EVERY fixture the run priced, attack and defence separately, never combined.

Pure: synthetic pools and rows, a real small MIP solve (~1 s), the two IO helpers monkeypatched.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import model_tools as mt                                   # noqa: E402
from optimize import optimize_squad                        # noqa: E402


# ---------------------------------------------------------------- a pool the MIP can solve
def pool():
    """3 GK, 8 DEF, 8 MID, 5 FWD over eight clubs; element 100 is a cheap, low-scoring midfielder the
    solver would never start on its own."""
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


def roles(df, sol):
    starters = {int(df.loc[i, "element"]) for i, v in sol["start"].items() if v.value() > 0.5}
    picked = {int(df.loc[i, "element"]) for i, v in sol["pick"].items() if v.value() > 0.5}
    return picked, starters


# ---------------------------------------------------------------- 3a: the solver
def test_a_forced_starter_is_in_the_xi_not_just_the_squad():
    df = pool()
    _, sol = optimize_squad(df, locked_elements=[100])
    picked, starters = roles(df, sol)
    assert 100 in picked and 100 not in starters                    # a lock alone benches him
    _, sol2 = optimize_squad(df, start_elements=[100])
    picked2, starters2 = roles(df, sol2)
    assert 100 in starters2 and 100 in picked2 and len(starters2) == 11 and len(picked2) == 15


def test_no_start_elements_emits_nothing_and_the_solve_is_unchanged():
    df = pool()
    _, a = optimize_squad(df)
    _, b = optimize_squad(df, start_elements=[])
    _, c = optimize_squad(df, start_elements=None)
    assert roles(df, a) == roles(df, b) == roles(df, c)


def test_a_start_element_the_pool_does_not_hold_is_refused_like_a_lock():
    with pytest.raises(ValueError, match="Start element 999 not found"):
        optimize_squad(pool(), start_elements=[999])


# ---------------------------------------------------------------- 3a: the tool
@pytest.fixture
def solver_env(monkeypatch):
    df = pool()
    monkeypatch.setattr(mt, "_load_pool", lambda gw=None: (df, 6, datetime(2026, 10, 8, tzinfo=timezone.utc)))
    monkeypatch.setattr(mt, "_frame_built", lambda cutoff: {"built": "built test", "next_run_expected": None})
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    names = {int(r.element): r.name for r in df.itertuples()}
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        {"element": e, "name": names[e]} for e in (params[0] if params else []) if e in names])
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {
        5: {"available": False, "availability_note": "Has joined Al Hilal permanently"}} if 5 in ids else {})
    return df


def test_optimise_forces_the_named_players_to_start_and_echoes_them(solver_env):
    out = mt.optimise(start_player_ids=[100])
    assert "error" not in out, out
    row = next(r for r in out["squad"] if r["player_id"] == 100)
    assert row["role"] in ("start", "CAPTAIN", "VICE")
    assert out["constraints"]["start"] == [100]
    assert len([r for r in out["squad"] if r["role"] != "bench"]) == 11
    assert len([r for r in out["squad"] if r["role"] == "bench"]) == 4


def test_optimise_without_start_players_adds_no_key_and_benches_the_same_lock(solver_env):
    out = mt.optimise(lock_player_ids=[100])
    assert "start" not in out["constraints"]
    assert next(r for r in out["squad"] if r["player_id"] == 100)["role"] == "bench"


def test_a_starter_who_is_unknown_or_cannot_play_is_refused_the_way_a_lock_is(solver_env):
    out = mt.optimise(start_player_ids=[999999])
    assert out["error_kind"] == "unknown_player_id" and "999999" in out["error"]
    out = mt.optimise(start_player_ids=[5])
    assert out["error_kind"] == "locked_player_unavailable" and "cannot be locked" in out["error"]


def test_the_optimise_schema_advertises_start_player_ids():
    import agent
    schema = next(t for t in agent.tools_schema if t["name"] == "build_squad_from_scratch")
    props = schema["input_schema"]["properties"]
    assert "start_player_ids" in props and props["start_player_ids"]["type"] == "array"
    assert "START" in schema["description"]


# ---------------------------------------------------------------- 3d: the scores
def test_rank_scores_are_deciles_among_all_values_with_ties_shared():
    s = ft.rank_scores({i: float(i) for i in range(1, 11)})
    assert [s[i] for i in range(1, 11)] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    s = ft.rank_scores({"a": 1.0, "b": 1.0, "c": 2.0, "d": 3.0})
    assert s["a"] == s["b"] == 3 and s["c"] == 7 and s["d"] == 9
    s = ft.rank_scores({"a": 1.0, "b": None, "c": float("nan"), "d": 2.0})
    assert s["b"] is None and s["c"] is None and s["a"] == 3 and s["d"] == 8
    assert ft.rank_scores({"only": 4.2}) == {"only": 5}
    assert ft.rank_scores({}) == {}


def test_fixture_scores_rank_attack_and_defence_separately_and_never_combine():
    rows = [{"team": f"T{i}", "gw": 6, "team_lambda": 0.8 + 0.1 * i, "p_cs": 0.40 - 0.03 * i} for i in range(10)]
    s = ft.fixture_scores(rows)
    assert s[("T9", 6)] == {"attack": 10, "defence": 1}        # most goals, least clean sheet
    assert s[("T0", 6)] == {"attack": 1, "defence": 10}
    assert set(s[("T5", 6)]) == {"attack", "defence"}


def test_build_carries_the_scores_on_every_fixture_and_in_the_compact_rows(monkeypatch):
    skel = pd.DataFrame([(1, 6, "Newcastle", 7, True, "2026-10-10T14:00:00Z"),
                         (2, 6, "Coventry City", 14, False, "2026-10-10T14:00:00Z")], columns=ft.SKELETON_COLS)
    monkeypatch.setattr(ft, "_team_names", lambda: {7: "Coventry City", 14: "Newcastle"})
    cal, n = ft.calendar(df=skel)
    rows = [{"team": "Newcastle", "gw": 6, "team_lambda": 2.1, "opp_lambda": 0.9, "p_cs": 0.40, "horizon_step": 0,
             "odds_horizon_gws": 1, "n_fixtures": 1},
            {"team": "Coventry City", "gw": 6, "team_lambda": 0.9, "opp_lambda": 2.1, "p_cs": 0.15, "horizon_step": 0,
             "odds_horizon_gws": 1, "n_fixtures": 1}]
    # eight other priced team-gameweeks, so the two above sit at the extremes of a ten-fixture ranking
    rows += [{"team": f"Other{i}", "gw": 7, "team_lambda": 1.0 + 0.1 * i, "opp_lambda": 1.2, "p_cs": 0.18 + 0.02 * i,
              "horizon_step": 1, "odds_horizon_gws": 1, "n_fixtures": 1} for i in range(8)]
    one = ft.build(rows, cal, n, team="Newcastle", gw=6)
    d = one["fixtures"][0]["fixtures"][0]["difficulty"]
    assert d["attacking"]["score"] == 10 and d["defensive"]["score"] == 10
    assert not any(k in d for k in ("score", "fdr", "overall", "composite"))     # still no single number
    compact = ft.build(rows, cal, n, gw=6)
    cov = next(r for r in compact["fixtures"] if r["team"] == "Coventry City")
    assert cov["attack_score"] == 1 and cov["defence_score"] == 1
    # with only two priced fixtures the deciles compress (neither is "the hardest of all"): 3 and 8, by the formula
    two = ft.build(rows[:2], cal, n, gw=6)
    assert {r["team"]: r["attack_score"] for r in two["fixtures"]} == {"Newcastle": 8, "Coventry City": 3}
    assert "attack_score" in compact["compact_columns"] and "two scores, never one" in compact["compact_columns"]
    assert "1 (hardest) to 10 (easiest)" in compact["scores"]
