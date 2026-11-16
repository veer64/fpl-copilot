"""Prompt R3c item 1 (16 Nov 2026; USER DECISION): the captain answer is written by code.

Measured before (eval/reports/r3b_answers.md, Set B case 5, 1 of 3): the model wrote it from the line-up pick and a breakdown and
slipped four times -- "The next best is Gabriel (5.97), then Isak (4.08)" with Lindelöf third at 4.59 (a player skipped), "more
than 3 points clear of anyone else" for a 1.18 margin, "a 94% chance of playing the full game" for the chance of 60 minutes or
more, and a 98% chance of playing at all under the heading "Start %".

P1  the header: the pick is the XI's top scorer by a whole-pool query, his points and his points with the armband (twice);
P2  the table lists the XI's top five by predicted points, ranked, with no starter above the fifth left out;
P3  every cell: points, the likely range as one phrase (the prediction tool's P10 / P50 / P90), the chance of starting and the
    chance of 60+ minutes each from its OWN source field under its own label, the fixture in words, FPL's flag;
P4  "Captaining A over B is worth x" -- x is the difference between their own points, never doubled; the vice is the next option;
P5  the upside sentence appears exactly when a lower-middle option has the higher top of the range;
P6  the biggest part of the pick's prediction, from the draft team's breakdown helper, with its share;
P7  named players ("X or Y as captain"): their own sentence; a bench player is said to be on the bench; a player outside the
    fifteen, a bad id or too many names are refused for the model;
P8  the bonus note, the later-gameweek sentence for a planning view, the closing question (USER DECISION);
P9  no squad / a line-up error goes back as it is; a draft chat's turn is refused.
Seeded pool (Tests/r3_seed.py) with its quantiles and 60-minute chances set here; no model, no network."""
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import draft_tools                                          # noqa: E402
import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

ROW = {p[0]: p for p in seed.PLAYERS}
XI = [101, 102, 103, 110, 118, 105, 113, 121, 129, 107, 115]
BENCH = [109, 126, 137, 123]
GW = 11


def _xi(captain=None, vice=None, gw=GW):
    pts = {e: seed.e_points(e, gw) or 0.0 for e in XI}
    cap = captain or max(XI, key=lambda e: pts[e])
    vic = vice or sorted(XI, key=lambda e: -pts[e])[1]
    row = lambda e, role, bo=None: {"player_id": e, "name": ROW[e][1], "position": ROW[e][2], "team": ROW[e][3], "role": role,  # noqa: E731
                                    "bench_order": bo, "e_points": round(pts.get(e, 0.0), 2)}
    return {"gw": gw, "xi": [row(e, "CAPTAIN" if e == cap else "VICE" if e == vic else "start") for e in XI],
            "bench_in_order": [row(e, "bench", k) for k, e in enumerate(BENCH, 1)], "predicted_xi_points": 0.0}


@pytest.fixture
def cap_env(pool_db, monkeypatch):
    """The seeded build with a 60-minute chance and a likely range on every row (q_p10 / q_p50 / q_p90), and the line-up pick
    over the seeded fifteen."""
    with pool_db.cursor() as cur:
        cur.execute("UPDATE model_predictions SET p_60plus = round((p_start * 0.83)::numeric, 4), "
                    "q_p10 = 1, q_p50 = round(e_points::numeric), q_p90 = round(e_points::numeric) + 4 + (element % 5), q_sd = 2, "
                    "q_degenerate = false, q_resid_sampling = 0, q_resid_structural = 0, q_tolerance = 0.1")
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: _xi(gw=gw or GW))
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    monkeypatch.setattr(draft_tools, "_breakdowns", lambda ids, gw: {e: {"parts": [{"part": "goals", "points": 1.11},
                                                                                {"part": "appearance", "points": 0.95}]} for e in ids})
    return pool_db


def _q(conn, sql, params=()):
    return seed.q(conn, sql, params)


def _facts(conn, ids, gw=GW):
    rows = _q(conn, "SELECT element, round(e_points::float8::numeric, 2), p_start, p_60plus, q_p10, q_p50, q_p90 FROM model_predictions "
                    "WHERE run_id = 1 AND config = 'baseline' AND gw = %s AND element = ANY(%s)", (gw, list(ids)))
    return {r[0]: {"pts": r[1], "start": r[2], "p60": r[3], "p10": r[4], "p50": r[5], "p90": r[6]} for r in rows}


def _ranked(conn, gw=GW):
    f = _facts(conn, XI, gw)
    return sorted(XI, key=lambda e: (-f.get(e, {"pts": Decimal(0)})["pts"], ROW[e][1], e)), f


def _pct(x):
    return f"{int(Decimal(repr(float(x) * 100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))}%"


def _text(**kw):
    out = mt.captain_pick(**kw)
    assert "direct_reply" in out, out
    return out


def test_p1_the_header_is_the_xis_top_scorer_with_and_without_the_armband(cap_env):
    ranked, f = _ranked(cap_env)
    pick = ranked[0]
    out = _text()
    a = f[pick]["pts"]
    assert out["direct_reply"].split("\n")[0] == (f"**Captain for GW11: {ROW[pick][1]}, {a:.2f} predicted points; {2 * a:.2f} with the "
                                                  "armband (his points counted twice).**")
    assert out["captain_id"] == pick and out["vice_id"] == ranked[1]


def test_p2_the_top_five_with_no_starter_above_the_fifth_left_out(cap_env):
    ranked, f = _ranked(cap_env)
    head, rows = seed.tables(_text()["direct_reply"])[0]
    assert [r[0] for r in rows] == ["1", "2", "3", "4", "5"]
    assert [r[1] for r in rows] == [ROW[e][1] for e in ranked[:5]]
    fifth = f[ranked[4]]["pts"]
    assert all(f[e]["pts"] <= fifth for e in ranked[5:])                     # nobody outside the list scores more than the fifth


def test_p3_every_cell_from_its_own_source_field_under_its_own_label(cap_env):
    ranked, f = _ranked(cap_env)
    head, rows = seed.tables(_text()["direct_reply"])[0]
    assert head == ["#", "Player", "Club", "Predicted points GW11", "Likely range GW11 (P10 to P90, without the armband)",
                    "Chance of starting GW11", "Chance of playing 60+ minutes GW11", "Fixture GW11", "Flag"]
    cal = seed.calendar()
    for r, e in zip(rows, ranked[:5]):
        x = f[e]
        assert r[2] == ROW[e][3] and r[3] == f"{x['pts']:.2f}"
        n = lambda v: str(int(v)) if float(v) == int(v) else f"{float(v):.1f}"   # noqa: E731
        assert r[4] == f"{n(x['p10'])} to {n(x['p90'])} (middle {n(x['p50'])})"
        assert r[5] == _pct(x["start"]) and r[6] == _pct(x["p60"])           # starting <- p_start; 60+ minutes <- p_60plus
        assert r[5] != r[6] or x["start"] == x["p60"]
        fx = cal[(ROW[e][3], GW)][0]
        assert r[7] == (f"{fx['opponent']} at home" if fx["home"] else f"away at {fx['opponent']}")
    flags = {r[1]: r[8] for r in rows}
    if ROW[121][1] in flags:
        assert flags[ROW[121][1]].startswith("Injured — FPL:")


def test_p4_the_margin_is_the_difference_of_their_own_points_and_the_vice_is_the_next_option(cap_env):
    ranked, f = _ranked(cap_env)
    a, b = f[ranked[0]]["pts"], f[ranked[1]]["pts"]
    text = _text()["direct_reply"]
    assert (f"Captaining {ROW[ranked[0]][1]} over {ROW[ranked[1]][1]} is worth {a - b:.2f} predicted points — the difference between "
            f"their own scores ({a:.2f} against {b:.2f}).") in text
    assert f"Vice-captain: {ROW[ranked[1]][1]}, the next option ({b:.2f} predicted points)." in text
    assert f"{2 * (a - b):.2f}" not in text or 2 * (a - b) in (a, b, 2 * a)    # the doubled gap is never stated
    assert not re.search(r"doubl\w* (?:to|the gap|that gap)", text.lower())


def test_p5_the_upside_sentence_appears_exactly_when_a_lower_middle_option_has_the_higher_top(cap_env):
    ranked, f = _ranked(cap_env)
    pick, third = ranked[0], ranked[2]
    with cap_env.cursor() as cur:
        cur.execute("UPDATE model_predictions SET q_p50 = 6, q_p90 = 12 WHERE run_id = 1 AND gw = 11 AND element = %s", (pick,))
        cur.execute("UPDATE model_predictions SET q_p50 = 3, q_p90 = 15 WHERE run_id = 1 AND gw = 11 AND element = %s", (third,))
        cur.execute("UPDATE model_predictions SET q_p50 = 2, q_p90 = 5 WHERE run_id = 1 AND gw = 11 AND element = ANY(%s)",
                    ([e for e in ranked[1:5] if e != third],))
    text = _text()["direct_reply"]
    assert (f"{ROW[third][1]} has the higher top of the range (1 to 15 (middle 3) against {ROW[pick][1]}'s 1 to 12 (middle 6)), though "
            "his middle is lower.") in text
    with cap_env.cursor() as cur:
        cur.execute("UPDATE model_predictions SET q_p90 = 11 WHERE run_id = 1 AND gw = 11 AND element = %s", (third,))
    assert "has the higher top of the range" not in _text()["direct_reply"]


def test_p6_the_biggest_part_of_the_picks_prediction(cap_env, monkeypatch):
    ranked, f = _ranked(cap_env)
    pick = ranked[0]
    a = f[pick]["pts"]
    monkeypatch.setattr(draft_tools, "_breakdowns", lambda ids, gw: {e: {"parts": [{"part": "goals", "points": float(a) - 0.5},
                                                                                {"part": "appearance", "points": 0.5}]} for e in ids})
    pct = int((Decimal(f"{float(a) - 0.5:.2f}") * 100 / a).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    assert (f"The biggest part of {ROW[pick][1]}'s {a:.2f} predicted points is goals: {float(a) - 0.5:.2f} ({pct}%)."
            in _text()["direct_reply"])
    monkeypatch.setattr(draft_tools, "_breakdowns", lambda ids, gw: {})
    assert "The biggest part" not in _text()["direct_reply"]


def test_p7_named_players(cap_env):
    ranked, f = _ranked(cap_env)
    x, y = ranked[3], ranked[4]
    text = _text(player_ids=[y, x])["direct_reply"]
    d = f[x]["pts"] - f[y]["pts"]
    assert (f"Of the two you named, captaining {ROW[x][1]} over {ROW[y][1]} is worth {d:.2f} predicted points — the difference between "
            f"their own scores ({f[x]['pts']:.2f} against {f[y]['pts']:.2f}).") in text or d == 0
    low = ranked[7]
    t2 = _text(player_ids=[ranked[0], low])["direct_reply"]
    assert f"| {ROW[low][1]} (named) |" in t2 and "| 8 |" in t2                 # outside the top five: his own row, his own rank
    t3 = _text(player_ids=[BENCH[1]])["direct_reply"]
    assert f"{ROW[BENCH[1]][1]} is on your bench in this line-up: a captain must start." in t3 and "| bench |" in t3
    out = mt.captain_pick(player_ids=[147])
    assert "error" in out and out["not_in_squad"] == [147] and "direct_reply" not in out
    assert "error" in mt.captain_pick(player_ids=["Haaland"])
    assert "error" in mt.captain_pick(player_ids=[101, 102, 103, 105])


def test_p8_notes_and_the_closing_question(cap_env):
    text = _text()["direct_reply"]
    assert text.split("\n")[-1] == "Want me to go into either of them?" and answers.BONUS_NOTE in text
    assert text.split("\n")[1] == f"Predictions from the update of Wed 11 Nov 2026, 11:01 UTC. Next update: {seed.NEXT_UPDATE}."
    assert "longer-range estimate" not in text
    later = _text(gw=13)["direct_reply"]
    assert later.startswith("**Captain for GW13: ") and ("GW13 is a longer-range estimate from team strengths, with no odds, lineups or "
                                                         "team news yet, so these will move before then.") in later


def test_p9_no_squad_errors_and_a_draft_turn(cap_env, monkeypatch):
    note = {"no_squad": True, "user_id": 10001, "status": "no squad saved yet", "note": "…"}
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: dict(note))
    assert mt.captain_pick() == note
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: {"error": "the predictions and the database disagree"})
    assert mt.captain_pick() == {"error": "the predictions and the database disagree"}
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    assert mt.captain_pick() == {"error": mt.R3_NOT_IN_DRAFT}


def test_p10_the_range_comes_through_the_draft_teams_captain_helper(cap_env, monkeypatch):
    seen = []
    real = draft_tools._captain_range

    def spy(pid, gw):
        seen.append((pid, gw))
        return real(pid, gw)
    monkeypatch.setattr(draft_tools, "_captain_range", spy)
    _text()
    assert sorted(p for p, _g in seen) == sorted(XI) and {g for _p, g in seen} == {GW}
