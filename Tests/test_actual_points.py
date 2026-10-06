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
    assert "no run" in out["predicted_note"].lower()


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
    out = mt.get_my_points(gw=3)
    want = squad_store.score_gameweek_for([v], 3, pd.Timestamp("2026-09-04T17:30:00Z"),
                                          at.actuals_frame(m, 3))
    assert "error" not in out, out
    for k in ("points_net", "points_raw", "hit", "captain_bonus", "doubled",
              "doubled_role", "transfers_made", "free_transfers", "final_xi",
              "subs_made", "bench_points", "version_id"):
        assert out[k] == want[k], k
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
    assert "get_actual_points" in out["error"], out["error"]
    assert "aren't available yet" not in out["error"]      # the old, now-false sentence


def test_the_fixtures_refusal_now_names_the_tool_that_can_answer():
    import fixtures_tool as ft
    cal = {("Arsenal", g): [{"opponent": "Chelsea", "opponent_id": 2, "home": True,
                             "kickoff": "2026-10-11T14:00:00Z"}] for g in (6, 7, 8)}
    rows = [{"team": "Arsenal", "gw": g, "team_lambda": 1.8, "opp_lambda": 0.9,
             "p_cs": 0.33, "horizon_step": g - 6} for g in (6, 7, 8)]
    out = ft.build(rows, cal, 1, team="Arsenal", gw=3)
    assert out["error_kind"] == "already_played"
    assert "get_actual_points" in out["error"], out["error"]
