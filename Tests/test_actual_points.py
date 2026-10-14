"""Actual points for a past gameweek: a player (get_actual_points) and the user's
team (get_my_points), plus the gw option on the three solver tools.

Discovered 2026-10-05 before any of this was written: the 2026-27 actuals are
ALREADY stored with the whole breakdown in data/history/fpl_api_2026_27.parquet
(74 columns per element-fixture, GW1-5), written by eval/fetch_fpl_history.py as
step 1 of every weekly ingest and already the input eval/score_squads.py scores
from. So nothing here creates a second store, and nothing here re-implements a
scoring rule: the team score is squad_store.score_gameweek_for, which is
squad/scoring.py's scorer (autosubs, armband with vice fallback, hits deducted).

Pure where it can be: the master is built by hand here, the two IO helpers are
monkeypatched. The three tests that need the real file are marked by reading it
through actuals_tool and skipping nothing -- they assert on shape, not on a
score that a later FPL correction would move.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import actuals_tool as at                                  # noqa: E402
import model_tools as mt                                   # noqa: E402

SAKA = 12
HAALAND = 411


def master(rows):
    """rows: (element, GW, fixture, minutes, total_points, *breakdown overrides)."""
    out = []
    for element, gw, fixture, minutes, pts in rows:
        r = {"element": element, "GW": gw, "fixture": fixture, "minutes": minutes,
             "total_points": pts}
        for c in at.BREAKDOWN_COLS:
            r.setdefault(c, 0)
        r["minutes"] = minutes
        for c in at.EXPECTED_COLS:
            r[c] = 0.0
        out.append(r)
    return pd.DataFrame(out)


# ---- the reader -----------------------------------------------------------------------
def test_the_breakdown_columns_all_exist_in_the_real_master():
    """If FPL renames a stat the tool must fail loudly here, not answer with a hole."""
    m = at.load_master("2026-27")
    assert m is not None, "data/history/fpl_api_2026_27.parquet is missing"
    missing = [c for c in at.BREAKDOWN_COLS + at.EXPECTED_COLS + at.MASTER_COLS
               if c not in m.columns]
    assert missing == [], missing


def test_a_double_gameweek_is_one_row_with_both_fixtures_counted():
    m = master([(SAKA, 3, 29, 89, 2), (SAKA, 3, 30, 45, 6)])
    out = at.player_gameweek(m, SAKA, 3)
    assert out["total_points"] == 8 and out["minutes"] == 134
    assert out["n_fixtures"] == 2 and out["fixtures"] == [29, 30]


def test_a_player_who_was_in_the_game_and_did_not_play_is_reported_not_dropped():
    m = master([(SAKA, 3, 29, 0, 0)])
    out = at.player_gameweek(m, SAKA, 3)
    assert out is not None and out["minutes"] == 0 and out["total_points"] == 0


def test_a_player_with_no_row_in_that_gameweek_is_none():
    m = master([(SAKA, 3, 29, 89, 2)])
    assert at.player_gameweek(m, HAALAND, 3) is None


def test_gws_held_is_the_set_of_answerable_gameweeks():
    m = master([(SAKA, 1, 1, 90, 9), (SAKA, 2, 20, 90, 11), (SAKA, 3, 29, 89, 2)])
    assert at.gws_held(m) == [1, 2, 3]
    assert at.gws_held(None) == [] and at.gws_held(master([])[:0]) == []


def test_provisional_is_unknown_without_a_sidecar_and_false_when_fpl_checked_it():
    assert at.provisional_for({}, 3) == (None, None)
    prov = {3: {"finished": True, "data_checked": True, "pulled_at": "2026-09-11T22:20:57Z"},
            4: {"finished": True, "data_checked": False, "pulled_at": "2026-09-13T01:00:00Z"}}
    assert at.provisional_for(prov, 3) == (False, "2026-09-11T22:20:57Z")
    assert at.provisional_for(prov, 4) == (True, "2026-09-13T01:00:00Z")


def test_the_actuals_frame_delegates_the_aggregation_to_squad_store():
    import squad_store
    m = master([(SAKA, 3, 29, 89, 2), (SAKA, 3, 30, 45, 6), (HAALAND, 3, 31, 90, 12)])
    got = at.actuals_frame(m, 3)
    want = squad_store.actuals_from_master(m, 3)
    assert got.equals(want)
    assert set(got.columns) == {"element", "minutes", "total_points"}


# ---- A1 get_actual_points -------------------------------------------------------------
def _patch_master(monkeypatch, m, prov=None):
    monkeypatch.setattr(mt, "_actuals_master", lambda: (m, prov or {}))


def test_get_actual_points_gives_one_gameweek_with_its_breakdown(monkeypatch):
    m = master([(SAKA, 3, 29, 89, 2)])
    _patch_master(monkeypatch, m, {3: {"finished": True, "data_checked": True,
                                       "pulled_at": "2026-09-11T22:20:57Z"}})
    monkeypatch.setattr(mt, "_player_name", lambda el: "Saka")
    monkeypatch.setattr(mt, "_prediction_before", lambda el, gw: None)
    out = mt.get_actual_points(SAKA, gw=3)
    assert "error" not in out, out
    assert out["gw"] == 3 and out["total_points"] == 2 and out["minutes"] == 89
    assert out["provisional"] is False
    assert out["fetched_at"] == "2026-09-11T22:20:57Z"
    assert out["name"] == "Saka" and out["season"] == mt._season_label()


def test_get_actual_points_with_no_gw_gives_every_finished_gameweek(monkeypatch):
    m = master([(SAKA, 1, 1, 67, 9), (SAKA, 2, 20, 90, 11), (SAKA, 3, 29, 89, 2)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_player_name", lambda el: "Saka")
    monkeypatch.setattr(mt, "_prediction_before", lambda el, gw: None)
    out = mt.get_actual_points(SAKA)
    assert [g["gw"] for g in out["gameweeks"]] == [1, 2, 3]
    assert out["total_points"] == 22
    assert out["gameweeks_covered"] == [1, 3]


def test_a_gameweek_not_played_yet_is_refused_with_its_own_error_kind(monkeypatch):
    m = master([(SAKA, 3, 29, 89, 2)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_player_name", lambda el: "Saka")
    out = mt.get_actual_points(SAKA, gw=9)
    assert out["error_kind"] == "not_played_yet", out
    assert "GW9" in out["error"] and "has not been played" in out["error"]
    assert "GW3" in out["error"]                        # what IS answerable


def test_a_number_that_is_not_a_gameweek_is_refused_the_same_way_as_everywhere(monkeypatch):
    _patch_master(monkeypatch, master([(SAKA, 3, 29, 89, 2)]))
    monkeypatch.setattr(mt, "_player_name", lambda el: "Saka")
    for gw in (0, 39, -1):
        out = mt.get_actual_points(SAKA, gw=gw)
        assert out["error_kind"] == "invalid_gw", (gw, out)


def test_an_unknown_player_is_refused_by_the_shared_helper(monkeypatch):
    _patch_master(monkeypatch, master([(SAKA, 3, 29, 89, 2)]))
    monkeypatch.setattr(mt, "_player_name", lambda el: None)
    out = mt.get_actual_points(999999, gw=3)
    assert out["error_kind"] == "unknown_player_id", out


def test_the_stored_pre_deadline_prediction_rides_along_when_one_exists(monkeypatch):
    m = master([(SAKA, 3, 29, 89, 2)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_player_name", lambda el: "Saka")
    monkeypatch.setattr(mt, "_prediction_before", lambda el, gw: {
        "run_id": 3, "e_points": 4.89, "cutoff": 3, "config": "baseline"})
    out = mt.get_actual_points(SAKA, gw=3)
    assert out["predicted"]["e_points"] == 4.89 and out["predicted"]["run_id"] == 3
    # the comparison is stated, not left to the reader
    assert out["predicted_minus_actual"] == round(4.89 - 2, 2)


def test_no_stored_prediction_is_said_not_silently_omitted(monkeypatch):
    m = master([(SAKA, 1, 1, 67, 9)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_player_name", lambda el: "Saka")
    monkeypatch.setattr(mt, "_prediction_before", lambda el, gw: None)
    out = mt.get_actual_points(SAKA, gw=1)
    assert out["predicted"] is None
    assert "no build" in out["predicted_note"].lower()           # Part C (2026-10-12): "build", not "run", in tool prose


# ---- A2 get_my_points -----------------------------------------------------------------
def test_get_my_points_scores_through_squad_stores_own_scorer(monkeypatch):
    """The returned row must be score_gameweek_for's, field for field: if this tool
    ever grew its own arithmetic the two would drift."""
    import squad_store
    from test_squad_store import legal_doc, _row
    v = _row(legal_doc(), version_id=1, gw=3, created_at="2026-09-04 10:00:00+00")
    m = master([(e, 3, 100 + e, 90, 2) for e in range(1, 16)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_squad_versions_for", lambda user_id: [v])
    monkeypatch.setattr(mt, "_deadline_at", lambda gw: pd.Timestamp("2026-09-04T17:30:00Z"))
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {int(e): {"name": f"Player {e}"} for e in ids})
    out = mt.get_my_points(gw=3)
    want = squad_store.score_gameweek_for([v], 3, pd.Timestamp("2026-09-04T17:30:00Z"),
                                          at.actuals_frame(m, 3))
    assert "error" not in out, out
    for k in ("points_net", "points_raw", "hit",
              "doubled_role", "transfers_made", "free_transfers",
              "bench_points", "version_id"):
        assert out[k] == want[k], k
    # batch 3 F7 (2026-10-14): the scorer's ids travel as NAMES -- the same players, field for field
    assert out["final_xi"] == [f"Player {e}" for e in want["final_xi"]]
    assert out["substitutions"] == [{"off": f"Player {o}", "on": f"Player {i}"} for o, i in want["subs_made"]]
    assert out["doubled"] == (f"Player {want['doubled']}" if want["doubled"] is not None else None)
    assert "subs_made" not in out
    # 2026-10-10: the scorer's captain_bonus travels as captain_doubled_added (Tests/test_captain_wording.py)
    assert out["captain_doubled_added"] == want["captain_bonus"]
    assert out["autosubs_applied"] is True          # the scorer does them; say so


def test_no_squad_at_that_deadline_is_its_own_error_kind(monkeypatch):
    from test_squad_store import legal_doc, _row
    v = _row(legal_doc(), version_id=1, gw=6)       # seeded at GW6, after GW3
    m = master([(e, 3, 100 + e, 90, 2) for e in range(1, 16)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_squad_versions_for", lambda user_id: [v])
    monkeypatch.setattr(mt, "_deadline_at", lambda gw: pd.Timestamp("2026-09-04T17:30:00Z"))
    out = mt.get_my_points(gw=3)
    assert out["error_kind"] == "no_squad_for_gw", out
    assert "GW3" in out["error"]


def test_a_gameweek_not_played_yet_is_refused_for_the_team_too(monkeypatch):
    from test_squad_store import legal_doc, _row
    v = _row(legal_doc(), version_id=1, gw=3)
    m = master([(e, 3, 100 + e, 90, 2) for e in range(1, 16)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_squad_versions_for", lambda user_id: [v])
    out = mt.get_my_points(gw=9)
    assert out["error_kind"] == "not_played_yet", out


def test_get_my_points_with_no_gw_gives_every_gameweek_it_can_score(monkeypatch):
    from test_squad_store import legal_doc, _row
    v = _row(legal_doc(), version_id=1, gw=1, created_at="2026-08-21 10:00:00+00")
    rows = [(e, g, 100 + e, 90, 2) for e in range(1, 16) for g in (1, 2)]
    m = master(rows)
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_squad_versions_for", lambda user_id: [v])
    monkeypatch.setattr(mt, "_deadline_at",
                        lambda gw: pd.Timestamp(f"2026-08-{14 + 7 * gw}T17:30:00Z"))
    out = mt.get_my_points()
    assert [g["gw"] for g in out["gameweeks"]] == [1, 2]
    assert out["total_points"] == sum(g["points_net"] for g in out["gameweeks"])


# ---- A3 the already_played messages point at the new tool ------------------------------
def test_the_horizon_refusal_now_names_the_tool_that_can_answer():
    out = mt._horizon_check(3, 6, 11, 24)
    assert out["error_kind"] == "already_played"
    # 2026-10-10 (Part 4a): the refusal still points at the answer, in plain words, never by tool name
    assert "actual points" in out["error"] and "team's score" in out["error"], out["error"]
    assert "get_actual_points" not in out["error"]
    assert "aren't available yet" not in out["error"]      # the old, now-false sentence


def test_the_fixtures_refusal_now_names_the_tool_that_can_answer():
    import fixtures_tool as ft
    cal = {("Arsenal", g): [{"opponent": "Chelsea", "opponent_id": 2, "home": True,
                             "kickoff": "2026-10-11T14:00:00Z"}] for g in (6, 7, 8)}
    rows = [{"team": "Arsenal", "gw": g, "team_lambda": 1.8, "opp_lambda": 0.9,
             "p_cs": 0.33, "horizon_step": g - 6} for g in (6, 7, 8)]
    out = ft.build(rows, cal, 1, team="Arsenal", gw=3)
    assert out["error_kind"] == "already_played"
    assert "actual points" in out["error"] and "get_actual_points" not in out["error"], out["error"]   # Part 4a


# ======================================================================================
# PART B: a gameweek option on the three solver tools (2026-10-05)
#
# The frame already holds every gameweek of the horizon (4002 rows, cutoff 6, gw 6-11)
# and _load_pool already takes a gw, so this is a parameter reaching code that was
# always there -- not a new solve path. What is new is the refusal outside the horizon
# and the planning-view note, because a GW9 answer from today's frame has no GW9 odds,
# lineups or team news behind it.
# ======================================================================================
PLANNING = "Planning view for GW"


def _fake_pool(gw=6):
    """A pool the REAL mixed-integer solver can actually satisfy: 2/5/5/3 needs enough
    of every position and no more than 3 from a club, so this is 6 GK, 10 DEF, 10 MID
    and 6 FWD spread over 11 clubs at 5.0m each -- 15 of them cost 75.0m of the 100.0m.
    The solve is real on purpose: a stubbed solver would not prove the gw reached it."""
    shape = [("GK", 6), ("DEF", 10), ("MID", 10), ("FWD", 6)]
    rows, el = [], 1
    for pos, n in shape:
        for i in range(n):
            rows.append({"gw": gw, "element": el, "cutoff": 6, "name": f"{pos}{i}",
                         "position": pos, "team": f"Club{i % 11}", "value": 50,
                         "e_points": 5.0 + gw / 100 + el / 1000})
            el += 1
    return pd.DataFrame(rows)


def test_the_planning_note_is_only_added_beyond_the_next_deadline(monkeypatch):
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    assert mt._planning_note(6, 6) is None
    note = mt._planning_note(9, 6)
    assert note.startswith(PLANNING + "9")
    assert "availability and predictions will change before then" in note


def test_a_gameweek_option_outside_the_horizon_uses_the_shared_error_kinds(monkeypatch):
    """The three tools must refuse with the same vocabulary get_prediction uses, so one
    question asked of four tools does not get four different explanations."""
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    for gw, kind in ((12, "too_far_ahead"), (3, "already_played"), (39, "invalid_gw"),
                     (0, "invalid_gw")):
        assert mt._solver_gw(gw)[1]["error_kind"] == kind, (gw, mt._solver_gw(gw))


def test_the_solver_gameweek_helper_passes_a_gameweek_inside_the_horizon(monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    for gw in (6, 9, 11):
        target, err = mt._solver_gw(gw)
        assert err is None and target == gw


# ---- B2: the default must not move ----------------------------------------------------
def test_optimise_with_no_gw_is_byte_identical_to_before(monkeypatch):
    """The pin that matters: adding the option must not change one byte of the answer the
    tool already gives. Both calls run the same stubbed solver; the dicts must match."""
    import json
    calls = []

    def fake_load_pool(gw=None):
        calls.append(gw)
        return _fake_pool(6), 6, "2026-10-02T00:00:00"

    monkeypatch.setattr(mt, "_load_pool", fake_load_pool)
    monkeypatch.setattr(mt, "_check_lock_ban", lambda a, b, pool_elements=None: None)
    monkeypatch.setattr(mt, "_frame_built", lambda c: {"built": "x"})
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    out_default = mt.optimise()
    out_explicit = mt.optimise(gw=6)
    assert "error" not in out_default, out_default
    assert "note" not in out_default                      # no note for the deadline gameweek
    assert calls[0] is None, "the default must still call _load_pool with no gw"
    d1 = dict(out_default); d2 = dict(out_explicit)
    for d in (d1, d2):
        d.pop("solve_seconds", None)
    assert json.dumps(d1, sort_keys=True, default=str) == \
           json.dumps(d2, sort_keys=True, default=str)


def test_optimise_for_a_later_gameweek_solves_that_gameweek_and_says_it_is_planning(monkeypatch):
    seen = []

    def fake_load_pool(gw=None):
        seen.append(gw)
        return _fake_pool(9), 6, "2026-10-02T00:00:00"

    monkeypatch.setattr(mt, "_load_pool", fake_load_pool)
    monkeypatch.setattr(mt, "_check_lock_ban", lambda a, b, pool_elements=None: None)
    monkeypatch.setattr(mt, "_frame_built", lambda c: {"built": "x"})
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    out = mt.optimise(gw=9)
    assert out["gw"] == 9, out
    assert 9 in seen, seen
    assert out["note"].startswith(PLANNING + "9")


def test_get_picks_computes_a_gameweek_it_has_no_stored_solve_for(monkeypatch):
    """The stored solve is the run's own gameweek only. Another gameweek inside the
    horizon is COMPUTED, and the answer says so rather than implying a stored record."""
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "optimise", lambda gw=None, **kw: {
        "gw": gw, "captain": "P411", "vice": "P12", "squad_cost": 100.0,
        "note": mt._planning_note(gw, 6), "solve_seconds": 2.0,
        "squad": [{"player_id": 411, "name": "P411", "position": "FWD", "price": 7.0,
                   "e_points": 5.1, "role": "CAPTAIN"},
                  {"player_id": 12, "name": "P12", "position": "MID", "price": 7.0,
                   "e_points": 5.0, "role": "bench"}]})
    out = mt.get_picks(gw=9)
    assert out["gw"] == 9 and out["computed"] is True
    assert out["stored"] is False
    assert out["captain"] == "P411"
    assert [r["player_id"] for r in out["xi"]] == [411]
    assert [r["player_id"] for r in out["bench_in_order"]] == [12]
    assert out["note"].startswith(PLANNING + "9")


def test_get_picks_with_no_gw_still_reads_the_stored_solve(monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_meta", lambda r, config=None: {"run_id": 24, "gw": 6})
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        {"player_id": 411, "name": "Haaland", "position": "FWD", "team": "Man City",
         "role": "CAPTAIN", "bench_order": None, "price_tenths": 156, "e_points": 6.0}])
    out = mt.get_picks()
    # B2: not one new key on the default path -- no stored, no computed, no note
    assert "computed" not in out and "stored" not in out and "note" not in out
    assert out["captain"] == "Haaland"
    # asked for the run's own gameweek explicitly, it says the solve was the stored one
    explicit = mt.get_picks(gw=6)
    assert explicit["stored"] is True and "computed" not in explicit


def test_get_my_xi_takes_a_gameweek_and_keeps_its_default(monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    target_default, err = mt._solver_gw(None)
    assert err is None and target_default == 6, "no gw must still mean the next deadline"
    target_9, err9 = mt._solver_gw(9)
    assert err9 is None and target_9 == 9
