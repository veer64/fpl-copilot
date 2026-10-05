"""Group 5: squad-tool guards and four message wordings (measured 2026-10-04).

B40 -- the unaffordable refusal read "transfer set unaffordable: bank 4 + 54 - 119 = -61":
four numbers in tenths with no units, in a sentence a user reads as pounds-millions.

B42 -- optimise(lock_player_ids=[999999]) raised ValueError("Locked element 999999 not found
in GW data.") out of the solver and reached the model as a generic tool failure, while
ban_player_ids=[999999] solved happily and said nothing.

Departed locks -- optimise(lock_player_ids=[55]) solved WITH Ollie Watkins in the fifteen, a
player whose own FPL note says "Has joined Al Hilal permanently".

B45 -- get_my_squad reported total_points 0 for user 9001, whose squad_scores holds no row at
all: a season that has not been scored is indistinguishable from a season of nothing.

B35 / B20 / B21 -- three messages that said the right thing in the wrong words, or named the
wrong date.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import match_stats as ms                                   # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_state as ss                                   # noqa: E402
import squad_store as sst                                  # noqa: E402


# ---- B40: money in the refusals -------------------------------------------------------
def test_money_is_written_as_fpl_writes_it():
    assert ss.money(4) == "£0.4m"
    assert ss.money(119) == "£11.9m"
    assert ss.money(-61) == "-£6.1m"
    assert ss.money(1000) == "£100.0m"
    assert ss.money(0) == "£0.0m"


def _state(bank=4):
    rows = [{"element": i, "name": f"P{i}", "position": "MID", "team": f"C{i}",
             "value": 50, "purchase_price": 50} for i in range(1, 16)]
    return ss.SquadState(pd.DataFrame(rows), bank=bank, free_transfers=1)


def test_the_unaffordable_refusal_shows_pounds_not_tenths():
    st = _state(bank=4)
    in_rows = {99: {"element": 99, "position": "MID", "value": 119}}
    prices = {i: 50 for i in range(1, 16)}
    with pytest.raises(ValueError) as e:
        st.make_transfers([(1, 99)], in_rows, prices)
    msg = str(e.value)
    assert "£0.4m" in msg and "£5.0m" in msg and "£11.9m" in msg, msg
    assert "= -£6.5m" in msg, msg          # 0.4 + 5.0 - 11.9
    assert "bank 4 +" not in msg


def test_the_single_transfer_refusal_shows_pounds_too():
    st = _state(bank=4)
    row = pd.Series({"element": 99, "position": "MID", "value": 119})
    prices = {i: 50 for i in range(1, 16)}
    with pytest.raises(ValueError) as e:
        st.make_transfer(1, 99, row, prices)
    assert "£" in str(e.value) and "= -" in str(e.value).replace("= -£", "= -")


# ---- B42 and the departed lock --------------------------------------------------------
def test_an_id_that_matches_no_player_is_refused(monkeypatch):
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [])          # no such player
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    for kw in ({"lock": [999999]}, {"ban": [999999]}, {"lock": [1], "ban": [999999]}):
        err = mt._check_lock_ban(kw.get("lock") or [], kw.get("ban") or [])
        assert err is not None, kw
        assert "999999" in err["error"] and "match no player" in err["error"]
        assert "resolve_player" in err["error"]


def test_a_lock_on_a_player_who_cannot_play_is_refused(monkeypatch):
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        {"element": 55, "name": "Ollie Watkins"}])
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {
        55: {"available": False, "availability_note": "Has joined Al Hilal permanently"}})
    err = mt._check_lock_ban([55], [])
    assert err is not None
    assert "Watkins cannot be locked" in err["error"], err["error"]
    assert "Has joined Al Hilal permanently" in err["error"]
    # banning him is fine
    assert mt._check_lock_ban([], [55]) is None


def test_known_available_ids_pass(monkeypatch):
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [
        {"element": 12, "name": "Bukayo Saka"}, {"element": 411, "name": "Erling Haaland"}])
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    assert mt._check_lock_ban([12], [411]) is None


# ---- B45: a season that has not been scored ------------------------------------------
def _doc():
    rows = []
    plan = [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]
    el = 1
    for pos, n in plan:
        for _ in range(n):
            rows.append({"element": el, "name": f"P{el}", "position": pos, "team": f"C{el}",
                         "purchase_price": 40, "role": "start", "bench_order": None})
            el += 1
    for i, b in enumerate([rows[1], rows[6], rows[11], rows[14]], start=1):
        b["role"], b["bench_order"] = "bench", i
    rows[12]["role"], rows[13]["role"] = "CAPTAIN", "VICE"
    return sst.document(pd.DataFrame(rows), 400, 1, 0, "2026-27", {"kind": "test"})


def _record(doc):
    return {"version_id": 1, "user_id": 9001, "season": "2026-27", "gw": 6,
            "created_at": None, "is_active": True, "supersedes": None, "note": None,
            "squad_json": doc}


def test_an_unscored_season_is_null_not_zero():
    out = sst.summary(_record(_doc()), {}, scores=[])
    assert out["total_points"] is None
    assert "not scored yet" in (out.get("total_points_note") or ""), out.get("total_points_note")


def test_a_scored_season_is_unchanged():
    scores = [{"gw": 6, "points_net": 57, "hit": 4, "version_id": 1},
              {"gw": 7, "points_net": 44, "hit": 0, "version_id": 2}]
    out = sst.summary(_record(_doc()), {}, scores=scores)
    assert out["total_points"] == 101
    assert out.get("total_points_note") is None
    assert len(out["scored_gameweeks"]) == 2


# ---- B35 wording ---------------------------------------------------------------------
def _empty_rows():
    return ms.club_rows(pd.DataFrame(columns=["season", "date_parsed", "home", "away",
                                              "home_goals", "away_goals"]), "Arsenal")


def test_no_matches_at_all_in_the_window_says_so_in_one_sentence():
    h = ms.head_to_head(_empty_rows(), "Arsenal", "Chelsea",
                        window={"seasons": ["2026-27"], "as_of": "2026-08-01",
                                "last_n": None, "matches_in_window": 0})
    st = h["statement"]
    assert st == ("No meetings between Arsenal and Chelsea in 2026-27 as of 2026-08-01; "
                  "Arsenal played no matches in that window."), st
    assert "stated zero" not in st and "no data" not in st


def test_matches_but_none_against_that_opponent_keeps_the_short_sentence():
    h = ms.head_to_head(_empty_rows(), "Arsenal", "Everton",
                        window={"seasons": ["2026-27"], "as_of": "2026-09-25",
                                "last_n": None, "matches_in_window": 5})
    st = h["statement"]
    assert st == "No meetings between Arsenal and Everton in 2026-27 as of 2026-09-25.", st


# ---- B20 date ------------------------------------------------------------------------
def test_the_date_is_when_the_gameweek_comes_into_range(monkeypatch):
    monkeypatch.setattr(mt, "_gw_deadlines", lambda: {7: "2026-10-17", 12: "2026-11-27",
                                                      15: "2026-12-12", 20: "2027-01-05"})
    out = mt._horizon_check(12, 6, 11, 24)
    assert "comes into range around GW7 (deadline 2026-10-17)" in out["error"], out["error"]
    assert "2026-11-27" not in out["error"]                 # not GW12's own deadline
    out = mt._horizon_check(20, 6, 11, 24)
    assert "around GW15 (deadline 2026-12-12)" in out["error"], out["error"]
    assert "2027-01-05" not in out["error"]


def test_the_date_is_left_out_when_it_is_not_held(monkeypatch):
    monkeypatch.setattr(mt, "_gw_deadlines", lambda: {})
    out = mt._horizon_check(20, 6, 11, 24)
    assert out["error_kind"] == "too_far_ahead"
    assert "around GW15" in out["error"] and "deadline" not in out["error"]


# ---- B21 wording ---------------------------------------------------------------------
def _cal():
    return {(t, g): [{"opponent": "X", "opponent_id": 2, "home": True,
                      "kickoff": "2026-10-10T14:00:00Z"}]
            for t in ("Arsenal",) for g in (6, 7, 8)}


def test_a_gameweek_before_the_loaded_range_says_it_was_played():
    out = ft.build([], _cal(), 1, team="Arsenal", gw=3)
    assert out["error_kind"] == "already_played", out
    assert out["error"] == ("GW3 has already been played; fixtures loaded cover GW6-8."), out["error"]


def test_a_gameweek_after_the_loaded_range_is_still_out_of_range():
    out = ft.build([], _cal(), 1, team="Arsenal", gw=39)
    assert out["error_kind"] == "out_of_range"
    assert "fixtures loaded cover GW6-8" in out["error"]
