"""B14 and B20 (measured 2026-10-04).

B14 -- 105 of the 667 players carry FPL status 'u', whose news reads "Has joined Al Hilal
permanently" or "Has joined Borussia Dortmund on loan for the rest of the season": they
cannot play for the club they are listed under. Every tool still answered with a price and a
full six-gameweek forecast and said nothing (Watkins: horizon 1.8 points, no flag), so the
only signal was a bare status letter the agent had to notice. A player who cannot play is
now flagged BEFORE any number, and the flag carries FPL's own words. Injured, doubtful and
suspended (i, d, s) are temporary and unchanged.

B20 -- run 24 covers GW6-11. Every gameweek outside it, past or future or not a gameweek at
all, came back as the same sentence: "no prediction rows for player 12 in run 24 (not in the
pool at that cutoff)" from get_prediction, and "the frame on the volume has no predictions
for GW20" from the other two. One helper now distinguishes a gameweek already played, one
too far ahead, and one that is not a gameweek, and says which.

Pure: the frames and rows are built here, the two IO helpers are monkeypatched.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402

LEFT = {"element": 55, "name": "Ollie Watkins", "status": "u",
        "news": "Has joined Al Hilal permanently"}
HERE = {"element": 12, "name": "Bukayo Saka", "status": "a", "news": None}


# ---- the one availability helper ------------------------------------------------------
def test_only_the_codes_that_mean_he_cannot_play_are_flagged(monkeypatch):
    rows = [dict(LEFT), dict(HERE),
            {"element": 6, "name": "Saliba", "status": "i", "news": "Back injury"},
            {"element": 10, "name": "White", "status": "d", "news": "Groin - 75%"},
            {"element": 398, "name": "Foden", "status": "s", "news": "Suspended until 17 Oct"},
            {"element": 999, "name": "Loanee", "status": "n", "news": None}]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        r for r in rows if r["status"] in mt.UNAVAILABLE_STATUSES])
    flags = mt._availability_for([r["element"] for r in rows])
    assert sorted(flags) == [55, 999], flags
    assert flags[55] == {"available": False,
                         "availability_note": "Has joined Al Hilal permanently"}
    assert flags[999]["availability_note"] == "not in squad"     # no news: the status word
    assert 12 not in flags and 6 not in flags and 10 not in flags and 398 not in flags


def test_the_flag_leads_the_result(monkeypatch):
    flags = {55: {"available": False, "availability_note": "Has joined Al Hilal permanently"}}
    out = mt._lead_with_availability({"price": 7.8, "e_points": 0.3}, 55, flags)
    assert list(out)[:2] == ["available", "availability_note"], list(out)
    assert out["price"] == 7.8
    plain = mt._lead_with_availability({"price": 9.5}, 12, flags)
    assert list(plain) == ["price"] and "available" not in plain


# ---- the one horizon helper ----------------------------------------------------------
@pytest.mark.parametrize("gw", [6, 9, 11])
def test_a_gameweek_inside_the_horizon_passes(gw):
    assert mt._horizon_check(gw, 6, 11, 24) is None


@pytest.mark.parametrize("gw,about", [(12, 7), (20, 15), (38, 33)])
def test_a_gameweek_after_the_horizon_says_when_it_comes_into_range(gw, about):
    out = mt._horizon_check(gw, 6, 11, 24)
    assert out["error_kind"] == "too_far_ahead", out
    assert f"Run 24 covers GW6-11" in out["error"]
    assert f"GW{gw} is too far ahead" in out["error"]
    assert f"about GW{about}" in out["error"], out["error"]


def test_a_gameweek_before_the_horizon_says_it_was_played():
    out = mt._horizon_check(3, 6, 11, 24)
    assert out["error_kind"] == "already_played"
    assert "GW3 has already been played" in out["error"]
    assert "This run predicts GW6-11" in out["error"]
    assert "aren't available yet" in out["error"]


@pytest.mark.parametrize("gw", [0, -1, 39, 100])
def test_a_number_that_is_not_a_gameweek_is_refused(gw):
    out = mt._horizon_check(gw, 6, 11, 24)
    assert out["error_kind"] == "invalid_gw", out
    assert "1" in out["error"] and "38" in out["error"]


def test_the_deadline_is_named_when_local_data_holds_it(monkeypatch):
    monkeypatch.setattr(mt, "_gw_deadlines", lambda: {20: "2027-01-05"})
    assert "2027-01-05" in mt._horizon_check(20, 6, 11, 24)["error"]
    monkeypatch.setattr(mt, "_gw_deadlines", lambda: {})
    out = mt._horizon_check(20, 6, 11, 24)
    assert out["error_kind"] == "too_far_ahead" and "2027" not in out["error"]


# ---- the three tools -----------------------------------------------------------------
def _frame(gws=(6, 7, 8, 9, 10, 11), elements=(12, 411)):
    rows = []
    for gw in gws:
        for el in elements:
            rows.append({"gw": gw, "element": el, "cutoff": 6, "name": f"P{el}",
                         "position": "MID", "team": "Arsenal", "e_points": 5.0,
                         "pts_goals": 1.0, "pts_appear": 2.0, "pts_assists": 0.5,
                         "pts_cs": 0.0, "pts_dc": 0.1, "pts_saves": 0.0,
                         "pts_conceded": 0.0, "pts_cards": -0.1, "exp_bonus": 0.0,
                         "e_points_core": 5.0})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("gw,kind", [(9, None), (11, None), (12, "too_far_ahead"),
                                     (20, "too_far_ahead"), (3, "already_played"),
                                     (0, "invalid_gw"), (39, "invalid_gw")])
def test_get_prediction_classifies_every_gameweek(monkeypatch, gw, kind):
    run = {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"}
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: dict(run))
    monkeypatch.setattr(mt, "_run_meta", lambda r, config=None: {"run_id": 24, "gw": 6})
    monkeypatch.setattr(mt, "_table_columns", lambda t, ttl=None: set())
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "_quantile_block", lambda rows: {"computed": False})

    def fake_q(sql, params=None):
        if "model_predictions" in sql:
            want = params[-1] if "AND gw" in sql else None
            return ([{"gw": want or 6, "e_points": 5.0, "horizon_step": 0}]
                    if (want is None or 6 <= want <= 11) else [])
        return [{"team": "Arsenal"}]

    monkeypatch.setattr(mt, "_q", fake_q)
    out = mt.get_prediction(12, gw=gw)
    if kind is None:
        assert "error" not in out, out
        assert out["predictions"]
    else:
        assert out.get("error_kind") == kind, out


def test_explain_and_compare_classify_the_same_way(monkeypatch):
    monkeypatch.setattr(mt, "_frame_raw", lambda: (_frame(), 6, "2026-10-02"))
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 24, "gw": 6, "season": "2026-27"})
    monkeypatch.setattr(mt, "_frame_built", lambda cutoff: {"built": "x"})
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [])
    for gw, kind in ((12, "too_far_ahead"), (3, "already_played"), (39, "invalid_gw")):
        e = mt.explain_prediction(12, gw=gw)
        assert e.get("error_kind") == kind, (gw, e)
        c = mt.compare_predictions(12, 411, gw=gw)
        assert c.get("error_kind") == kind, (gw, c)


def test_an_unavailable_player_is_flagged_first_in_a_prediction(monkeypatch):
    run = {"run_id": 24, "gw": 6, "season": "2026-27", "status": "SUCCESS"}
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: dict(run))
    monkeypatch.setattr(mt, "_run_meta", lambda r, config=None: {"run_id": 24})
    monkeypatch.setattr(mt, "_table_columns", lambda t, ttl=None: set())
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (6, 11))
    monkeypatch.setattr(mt, "_quantile_block", lambda rows: {"computed": False})
    monkeypatch.setattr(mt, "_availability_for", lambda els: {
        55: {"available": False, "availability_note": "Has joined Al Hilal permanently"}})
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: (
        [{"gw": 6, "e_points": 0.3, "horizon_step": 0}] if "model_predictions" in sql
        else [{"team": "Aston Villa"}]))
    out = mt.get_prediction(55, gw=6)
    assert list(out)[:2] == ["available", "availability_note"], list(out)[:4]
    assert out["available"] is False
    assert out["availability_note"] == "Has joined Al Hilal permanently"
    assert out["predictions"][0]["e_points"] == 0.3          # the number is still there
