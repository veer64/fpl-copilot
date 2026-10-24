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


# ================================================================ F2
def test_the_started_note_is_one_fixed_sentence_for_the_gameweek_in_progress():
    assert mt.gw_started_note(6, 6) == ("These figures are for GW6, which has already started. Our numbers are updated once "
                                        "GW6 is finished and FPL confirms the results.")
    assert mt.gw_started_note(7, 6) is None and mt.gw_started_note(6, None) is None and mt.gw_started_note(None, 6) is None


def test_optimise_and_the_other_frame_tools_say_when_their_gameweek_has_started(solver_env, monkeypatch):
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: 6)
    out = mt.optimise(lock_player_ids=[100])
    assert out["gw"] == 6 and out["note_gw_started"] == mt.gw_started_note(6, 6)
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    assert "note_gw_started" not in mt.optimise(lock_player_ids=[100])
    import inspect
    for fn in (mt.get_my_xi, mt.get_picks, mt.get_prediction, mt.compare_players, mt.get_wildcard_gap, mt.propose_transfers, mt.get_fixtures):
        assert "_with_started_note(" in inspect.getsource(fn), fn.__name__


def test_the_prompt_says_to_name_the_tools_gameweek_and_never_relabel():
    assert "name the gameweek the tool result gives" in PROMPT and "never relabel" in PROMPT
    assert "which has already started" in PROMPT


# ================================================================ F3
def test_probability_meanings_are_the_three_plain_phrases():
    assert mt.PROB_MEANINGS == {"p_play_any": "chance of playing at all (any minutes)", "p_start": "chance of starting",
                                "p_60plus": "chance of playing 60 minutes or more"}
    m = mt._meanings_for({"xi": [{"p_play_any": 0.9, "e_points": 4.0}], "solve_seconds": 1.2, "horizon_gws": [6, 7]})
    assert m["p_play_any"] == mt.PROB_MEANINGS["p_play_any"] and "solve_seconds" in m and "horizon_gws" in m
    assert mt._meanings_for({"gw": 6}) == {}


def test_the_prompt_translates_the_probability_keys_and_forbids_the_start_label():
    assert "p_play_any -> the chance of playing at all" in PROMPT
    assert "p_start -> the chance of starting" in PROMPT and "p_60plus -> the chance of playing 60 minutes or more" in PROMPT
    assert "never call the chance of playing at all a start probability" in PROMPT


# ================================================================ F4
def test_four_forced_forwards_are_refused_by_the_rule_before_any_solve(solver_env, monkeypatch):
    df = solver_env
    monkeypatch.setattr(mt, "solve_mip_entry", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the solver ran")), raising=False)
    out = mt.optimise(lock_player_ids=fwd_ids(df, 4), budget=80.0)
    assert out["error_kind"] == "squad_rule" and out["error"] == "FPL allows at most 3 forwards; you asked to force 4"
    out = mt.optimise(start_player_ids=fwd_ids(df, 4))
    assert out["error_kind"] == "squad_rule" and "at most 3 forwards" in out["error"]
    four_t1 = [int(e) for e in df[df["team"] == "T1"]["element"].head(4)]
    out = mt.optimise(lock_player_ids=four_t1)
    assert out["error_kind"] == "squad_rule" and out["error"] == "FPL allows at most 3 players from one club; you asked to force 4 from T1"


def test_a_budget_nobody_can_meet_is_refused_with_the_measured_cheapest_legal_cost(solver_env):
    df = solver_env
    cheapest = optimize.cheapest_squad_cost(df)
    assert cheapest == sum(sorted(df[df.position == "GK"]["value"])[:2]) + sum(sorted(df[df.position == "DEF"]["value"])[:5]) \
        + sum(sorted(df[df.position == "MID"]["value"])[:5]) + sum(sorted(df[df.position == "FWD"]["value"])[:3])   # no club clash in this pool
    out = mt.optimise(budget=40.0)
    assert out["error_kind"] == "budget_infeasible" and out["cheapest_legal_cost"] == round(cheapest / 10, 1)
    assert out["error"] == (f"no legal squad fits £40.0m: the cheapest legal squad costs £{cheapest / 10:.1f}m")
    locked = fwd_ids(df, 1)
    with_lock = optimize.cheapest_squad_cost(df, locked_elements=locked)
    out = mt.optimise(lock_player_ids=locked, budget=40.0)
    assert out["cheapest_legal_cost"] == round(with_lock / 10, 1) and "including the players you forced in" in out["error"]
    assert "solve status" not in out["error"]


def test_a_normal_request_is_unchanged_by_the_rule_checks(solver_env):
    df = solver_env
    out = mt.optimise(lock_player_ids=[100])
    assert "error" not in out and "cheapest_legal_cost" not in out and set(out["constraints"]) == {"locked", "banned", "budget"}
    prob, sol = optimize.optimize_squad(df, locked_elements=[100])
    picked = {int(df.loc[i, "element"]) for i, v in sol["pick"].items() if v.value() > 0.5}
    assert {r["player_id"] for r in out["squad"]} == picked


# ================================================================ F6
def test_section_0_carries_the_scoring_basics_from_scoring_py():
    sec = PROMPT.split("# 1. ")[0]
    assert f"costs {scoring.HIT_COST} points" in sec
    assert f"at least {scoring.MIN_FORMATION['DEF']} DEF, at least {scoring.MIN_FORMATION['MID']} MID, at least {scoring.MIN_FORMATION['FWD']} FWD" in sec
    assert f"Each gameweek {scoring.XI_SIZE} start" in sec
    assert "captain scores double" in sec and "triple captain" in sec.lower()
    assert "forward gets no clean-sheet points" in sec or "forwards get no clean-sheet points" in sec
    assert "Never credit a forward with a clean sheet" in sec
    assert "autosub" in sec.lower()


def test_the_penalty_sentence_does_not_call_the_player_a_taker_and_invented_facts_are_forbidden():
    assert "for a regular taker treat it as a floor" not in PROMPT
    assert "if a tool says he takes penalties" in PROMPT
    assert "Never state a fact about a player, club, fixture or result that no tool result or the context block gives" in PROMPT
    assert "the reason behind a number" in PROMPT


# ================================================================ F7
def test_the_transfer_summary_says_the_plan_covers_up_to_six_gameweeks():
    s = mt._transfer_summary(7, {"n_transfers": 1, "hits": 0, "transfers": [{"out_name": "A", "in_name": "B"}]},
                             {"gap_objective": 1.2, "gap_this_gw": 0.4, "refused": False}, 2)
    assert s.startswith("For GW7: 1 transfer, 0 hits (A out, B in)")
    assert s.endswith("This plan covers up to six gameweeks; check back each week.")
    hold = mt._transfer_summary(7, {"n_transfers": 0, "hits": 0, "transfers": []}, {"gap_objective": 0.0, "gap_this_gw": 0.0, "refused": False}, 1)
    assert hold.startswith("For GW7: hold, no transfer") and "This plan covers up to six gameweeks; check back each week." in hold
    import inspect
    assert '"summary_plain": _transfer_summary(' in inspect.getsource(mt.propose_transfers)
    assert "This plan covers up to six gameweeks; check back each week." in PROMPT


# ================================================================ F5
TOOL_MODULES = ["model_tools.py", "squad_store.py", "fixtures_tool.py", "explain.py", "league_table.py", "match_stats.py",
                "quantiles.py", "actuals_tool.py", "prices_tool.py", "news_search.py", "now_context.py"]
JARGON = re.compile(r"\b(ingest(?:ed|ion|s)?|post-ingest|horizon|cutoff|cut-off|solve[sd]?|solver|optimi[sz]er|frame)\b"
                    r"|\brun \d+\b|\bthe run\b|\bstatus[:=]? ?['\"]?[udaisn]['\"]?\b", re.I)
# Structured values, never prose: health() diagnostics (Tests/test_model_degraded_health.py pins them; /health
# only), SQL, provenance stamps, a stored plan's path label, and the one sentence that quotes FPL's own
# "ingested" status word.
ALLOWED = (
    lambda s: s.lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "WITH", "DELETE", "CREATE")),
    lambda s: s.startswith(("weekly ingest", "tool surface: ")),
    lambda s: s.startswith("model_tools."),
    lambda s: s.startswith("OPERATIONAL evidence only"),              # squad_store.RULE_1_COMMENT, a stored evidence note
)


def _prose_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
        if isinstance(node, ast.Dict):
            skip.update(id(k) for k in node.keys if isinstance(k, ast.Constant))
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            skip.add(id(node.slice))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            out.append((node.lineno, "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append((node.lineno, node.value))
    return [(ln, s) for ln, s in out if len(s.strip()) >= 12 and " " in s.strip()]


def test_no_pipeline_jargon_in_the_tools_prose():
    hits = []
    for m in TOOL_MODULES:
        for ln, s in _prose_literals(REPO / m):
            if JARGON.search(s) and not any(ok(s) for ok in ALLOWED):
                hits.append(f"{m}:{ln}: {JARGON.findall(s)[:3]} {s.strip()[:90]!r}")
    assert hits == [], "\n".join(hits)


def test_the_jargon_keys_that_stay_have_plain_twins():
    for k in ("horizon_gws", "predictions_as_of_cutoff_gw", "solve_seconds", "frame_built_at", "effective_horizon", "horizon_step", "stale_by_gameweeks"):
        assert k in mt.KEY_MEANINGS and not JARGON.search(mt.KEY_MEANINGS[k]), k
    assert "ingest" in PROMPT.lower() and "horizon -> the next six gameweeks" in PROMPT and "cutoff -> " in PROMPT
    assert "status codes" in PROMPT and "u, i, d, s, n" in PROMPT
