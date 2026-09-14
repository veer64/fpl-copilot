"""compare_players names the gameweek its first-row figures belong to and says when that
gameweek has already been played (2026-09-14: GW4's figures were called 'next gameweek'
while GW5 was the next deadline). Database and bootstrap stubbed."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import model_tools as mt                                   # noqa: E402


def _pred(pid, gws, pts):
    return {"player_id": pid, "model_version": "x/baseline", "built_at": "2026-09-12 11:01:01+00:00",
            "built": "built Sat 12 Sep 11:01Z (deadline, run 5)", "next_run_expected": {"kind": "post_ingest", "at": None,
                                                                                         "condition": "GW4 confirmed"},
            "recovered_post_deadline": False,
            "predictions": [{"gw": g, "horizon_step": i, "e_points": p, "p_start": 0.9} for i, (g, p) in enumerate(zip(gws, pts))],
            "horizon_e_points_sum": round(sum(pts), 2)}


def test_first_gameweek_is_named_and_flagged_stale_between_deadlines(monkeypatch):
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: _pred(pid, [4, 5, 6], [5.9, 5.1, 4.4] if pid == 411 else [4.5, 3.0, 3.6]))
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [{"element": 411, "name": "Erling Haaland"}, {"element": 379, "name": "Alexander Isak"}])
    monkeypatch.setattr(mt, "_current_gw", lambda: 5)
    c = mt.compare_players(411, 379)
    assert c["a"]["first_gw"] == 4 and c["a"]["first_gw_e_points"] == 5.9 and c["a"]["horizon_gws"] == [4, 5, 6]
    assert "next_gw_e_points" not in c["a"]
    assert c["verdict"] == "a" and c["verdict_basis"] == "horizon_e_points_sum"
    assert "GW4" in c["note_stale"] and "has been played" in c["note_stale"] and "gw=5" in c["note_stale"]
    assert c["built"].startswith("built Sat 12 Sep") and c["next_run_expected"]["condition"] == "GW4 confirmed"


def test_no_stale_note_when_the_run_is_for_the_next_deadline(monkeypatch):
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: _pred(pid, [5, 6], [5.1, 4.4]))
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [{"element": 411, "name": "A"}, {"element": 379, "name": "B"}])
    monkeypatch.setattr(mt, "_current_gw", lambda: 5)
    c = mt.compare_players(411, 379)
    assert "note_stale" not in c and c["a"]["first_gw"] == 5
