"""Friday gate v2 fixes (2026-10-16), the two open candidates of the targeted gate that would trace to a changed line.

F18 -- get_player_card:4 "What's Reece James' chance of playing in this round?" answered "That flag was set on 15
October 2026": the card showed only the build's as-of time (players_live.updated_at), and the agent read it as the day
FPL set the flag (FPL added the news on 10 Oct). The card now says both dates in plain words, "FPL flag set <date>,
last checked <date>", with FPL's own news_added from the raw bootstrap the build took; only "last checked <date>" when
no flag is up (FPL keeps an old news_added after clearing one) or the set date cannot be read. The chance line keeps
its gameweek, unchanged.

F19 -- compare_players:2 "Who's better over the next six weeks, Haaland or Isak?" went to player cards instead of
compare_players (base calls it): a comparison looked like it needed the cards for the players' flags. Both comparison
tools now carry each player's FPL status word and chance of playing (with its gameweek), and their descriptions say
they are the route for comparing players -- compare_players over the coming weeks, compare_predictions for one
gameweek -- so no card is needed. get_player_card's first line stays scoped to ONE named player's availability."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "squad"), str(ROOT / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import agent                                               # noqa: E402
import model_tools as mt                                   # noqa: E402

AS_OF = datetime(2026, 10, 15, 11, 1, 55, tzinfo=timezone.utc)
DEADLINES = {7: "2026-10-17T10:00:00Z", 8: "2026-10-24T10:00:00Z"}
JAMES_NEWS = "Unspecified injury - 75% chance of playing"


def _desc(name):
    return {t["name"]: t["description"] for t in agent.tools_schema}[name]


# ---- F18 ------------------------------------------------------------------------------------------------
def test_f18_flag_dates_words_say_both_dates_in_plain_words():
    assert mt.flag_dates_words("2026-10-10T13:30:08.699019Z", AS_OF, True) == "FPL flag set 10 Oct 2026, last checked 15 Oct 2026"
    assert mt.flag_dates_words(None, AS_OF, True) == "last checked 15 Oct 2026"               # set date unknown
    assert mt.flag_dates_words("2026-09-13T17:00:09Z", AS_OF, False) == "last checked 15 Oct 2026"   # no flag up


def _card(monkeypatch, row, snapshot_news):
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [dict(row)] if "FROM players_live" in sql else [])
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: {"error": "not needed here"})
    monkeypatch.setattr(mt, "_gw_deadline_times", lambda: DEADLINES)
    monkeypatch.setattr(mt, "_snapshot_news", lambda as_of=None: snapshot_news)
    return mt.get_player_card(row["element"])


def _james():
    return {"element": 142, "name": "Reece James", "position": "DEF", "team": "Chelsea", "price_tenths": 55,
            "status": "d", "chance": 75, "news": JAMES_NEWS, "updated_at": AS_OF}


def test_f18_the_card_shows_when_fpl_set_the_flag_and_when_it_was_last_checked(monkeypatch):
    card = _card(monkeypatch, _james(), {142: (JAMES_NEWS, "2026-10-10T13:30:08.699019Z")})
    assert card["flag_dates"] == "FPL flag set 10 Oct 2026, last checked 15 Oct 2026"
    assert card["availability"]["flag_dates"] == card["flag_dates"]
    assert card["chance_words"] == "chance of playing in GW7: 75%, FPL as of 15 Oct 2026"     # the chance line keeps its gameweek


def test_f18_a_set_date_for_different_news_is_not_used(monkeypatch):
    card = _card(monkeypatch, _james(), {142: ("Knock - 50% chance of playing", "2026-10-12T09:00:00Z")})
    assert card["flag_dates"] == "last checked 15 Oct 2026"


def test_f18_a_player_without_a_flag_is_only_last_checked(monkeypatch):
    row = {"element": 398, "name": "Phil Foden", "position": "MID", "team": "Man City", "price_tenths": 68,
           "status": "a", "chance": 100, "news": None, "updated_at": AS_OF}
    card = _card(monkeypatch, row, {398: ("", "2026-09-13T17:00:09.433455Z")})
    assert card["flag_dates"] == "last checked 15 Oct 2026"


# ---- F19 ------------------------------------------------------------------------------------------------
def test_f19_player_status_gives_every_player_a_status_word_and_a_labelled_chance(monkeypatch):
    rows = [{"element": 142, "status": "d", "chance": 75, "updated_at": AS_OF},
            {"element": 411, "status": "a", "chance": None, "updated_at": AS_OF}]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: rows)
    monkeypatch.setattr(mt, "_gw_deadline_times", lambda: DEADLINES)
    st = mt._player_status([142, 411])
    assert st[142] == {"status_word": "doubtful", "chance": 75, "chance_words": "chance of playing in GW7: 75%, FPL as of 15 Oct 2026"}
    assert st[411] == {"status_word": "available", "chance": None}


def _pred(pid):
    return {"player_id": pid, "model_version": "x/baseline", "built_at": "2026-10-15 11:01:01+00:00", "built": "built",
            "next_run_expected": None, "recovered_post_deadline": False,
            "predictions": [{"gw": 7, "horizon_step": 0, "e_points": 6.0, "p_start": 0.9}], "horizon_e_points_sum": 6.0}


def test_f19_compare_players_carries_each_players_status(monkeypatch):
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: _pred(pid))
    monkeypatch.setattr(mt, "_current_gw", lambda: 7)
    monkeypatch.setattr(mt, "_gw_deadline_times", lambda: DEADLINES)

    def fake_q(sql, params=None):
        if "status" in sql:
            return [{"element": 411, "status": "a", "chance": None, "updated_at": AS_OF},
                    {"element": 379, "status": "i", "chance": 0, "updated_at": AS_OF}]
        return [{"element": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City"},
                {"element": 379, "name": "Alexander Isak", "position": "FWD", "team": "Liverpool"}]
    monkeypatch.setattr(mt, "_q", fake_q)
    c = mt.compare_players(411, 379)
    assert c["a"]["status_word"] == "available" and "chance_words" not in c["a"]
    assert c["b"]["status_word"] == "injured" and c["b"]["chance_words"] == "chance of playing in GW7: 0%, FPL as of 15 Oct 2026"


def test_f19_compare_predictions_carries_each_players_status_on_the_real_frame():
    try:
        out = mt.compare_predictions(411, 379)
    except Exception as e:                       # noqa: BLE001 -- no frame on this machine
        pytest.skip(f"no production frame: {e}")
    if "error" in out:
        pytest.skip(f"no production frame: {out['error'][:80]}")
    for side in ("a", "b"):
        assert out[side].get("status_word"), out[side]
        if out[side].get("chance") is not None:
            assert out[side]["chance_words"].startswith("chance of playing in GW")


def test_f19_the_comparison_tools_say_they_are_the_route_and_need_no_card():
    cp, cpr = _desc("compare_players"), _desc("compare_predictions")
    assert "the route for comparing two players over the coming weeks" in cp and "needs no player card" in cp
    assert "the route for comparing players for one gameweek" in cpr and "needs no player card" in cpr
    assert "six-gameweek" in cp and "'X or Y this week' prefer compare_predictions" in cp      # the horizon split stays


def test_f19_the_card_first_line_stays_scoped_to_one_player_and_names_both_compare_routes():
    d = _desc("get_player_card")
    assert d.index("ONE named player") < d.index("call this FIRST") < d.index('"X or Y"')
    assert "compare_predictions" in d and "compare_players" in d
