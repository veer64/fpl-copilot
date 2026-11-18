"""Prompt F2c (18 Nov 2026; USER DECISION): the ranking answers for the one player the user named.

Measured before: F2b's gate (C:\\dev\\fpl-backups\\f2b_files\\gate\\results_L.json), "Is Haaland worth his price?" x2: the model looked
Haaland up, opened his card and called rank_players(FWD, value, 10) -- whose code-built top 10 is the reply and left Haaland out
altogether: a non-answer, both runs.

Q1  the one player the message names, not in the listed top N: his own row and his rank among every player ranked follow the
    table ("**Haaland** (Man City): £15.8m, 7.15 predicted points GW11, 0.45 per £1m — #9 of 9 forwards.");
Q2  the named player already in the list, no player named, or two named: the reply is exactly what it was;
Q3  a player the filters leave out (another position): his row, said to be outside them;
Q4  through rank_players on the seeded pool: in a turn whose message names him, outside a turn as before, a draft turn never.
Seeded database for Q4 (Tests/r3_seed.py); no model, no network."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import model_tools as mt                                    # noqa: E402
import turn_context                                         # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

GWS = [11]


def _p(e, name, team, pos, price, pts):
    return e, {"element": e, "name": name, "full_name": name, "position": pos, "team": team, "price_tenths": price,
               "pts": {11: pts}, "start": {11: 0.95}}


POOL = dict([_p(411, "Haaland", "Man City", "FWD", 158, 7.15), _p(249, "Barry", "Everton", "FWD", 57, 3.68),
             _p(50, "Kostoulas", "Brighton", "FWD", 58, 3.52), _p(51, "Evanilson", "Bournemouth", "FWD", 65, 3.63),
             _p(26, "Havertz", "Arsenal", "FWD", 74, 3.97), _p(12, "Saka", "Arsenal", "MID", 94, 0.34)])


def _rank(named=None, n=3, sort="value", position="FWD"):
    return answers.rank(POOL, GWS, position=position, sort=sort, n=n, named=named)


def test_q1_his_row_and_rank_follow_the_table():
    out = _rank(named=411)
    line = "**Haaland** (Man City): £15.8m, 7.15 predicted points GW11, 0.45 per £1m — #5 of 5 forwards."
    assert line in out["direct_reply"] and out["named_player"] == {"player_id": 411, "line": line}
    text = out["direct_reply"].split("\n")
    assert text.index(line) > max(i for i, s in enumerate(text) if s.startswith("|"))      # after the table, before the notes
    assert [r["player_id"] for r in out["rows"]] == [249, 50, 51]                          # the listed top 3 are unchanged
    by_points = answers.rank(POOL, GWS, position="FWD", sort="points", n=1, named=249)["direct_reply"]
    assert "**Barry** (Everton): £5.7m, 3.68 predicted points GW11 — #3 of 5 forwards." in by_points   # no "per £1m" by points


@pytest.mark.parametrize("named", [None, 249])
def test_q2_otherwise_the_reply_is_exactly_what_it_was(named):
    plain = _rank()
    assert _rank(named=named) == plain                           # no player named / the named player already listed
    assert "named_player" not in plain


def test_q3_a_player_the_filters_leave_out():
    out = _rank(named=12)
    assert "**Saka** (Arsenal, MID): £9.4m, 0.34 predicted points GW11, 0.04 per £1m — not among the forwards ranked here." in out["direct_reply"]


# ---- Q4: through rank_players on the seeded pool -------------------------------------------------------------------------------
def _in_turn(message, draft=None, **kw):
    turn_context.begin("f2c" + "q" * 29, user_message=message, **({"draft": draft} if draft else {}))
    try:
        return mt.rank_players(**kw)
    finally:
        turn_context.end()


def test_q4_rank_players_in_a_turn_that_names_one_player(pool_db, monkeypatch):
    monkeypatch.setattr(mt, "_web_names", lambda: {})
    kw = dict(position="FWD", sort="value", n=2, horizon=1)
    plain = mt.rank_players(**kw)                                           # outside a turn: as before
    listed = [r["player_id"] for r in plain["rows"]]
    fwds = [r for r in mt.rank_players(position="FWD", sort="value", n=12, horizon=1)["rows"]]
    outside = next(r for r in fwds if r["player_id"] not in listed)
    rank_of = [r["player_id"] for r in fwds].index(outside["player_id"]) + 1
    out = _in_turn(f"Is {outside['name']} worth his price?", **kw)
    assert out["named_player"]["player_id"] == outside["player_id"]
    assert f"**{outside['name']}** ({outside['team']}): " in out["direct_reply"] and f"— #{rank_of} of " in out["direct_reply"]
    assert out["direct_reply"].replace("\n\n" + out["named_player"]["line"], "") == plain["direct_reply"]   # only the line added
    inside = _in_turn(f"Is {fwds[0]['name']} worth his price?", **kw)
    assert inside["direct_reply"] == plain["direct_reply"] and "named_player" not in inside               # already listed
    nobody = _in_turn("Which forwards are the best value?", **kw)
    assert nobody["direct_reply"] == plain["direct_reply"] and "named_player" not in nobody
