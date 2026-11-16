"""Prompt R3 item 2 (16 Nov 2026): review_my_squad -- the whole-squad review, written by code.

Measured before it existed (eval/reports/r3_evidence_digest.md, R1's case B1, 0 of 3): the review was cut off after 11 of 15
players twice (C1, C2) and never written the third time (C3: 45 single-player lookups, cut); what was written read a fixture
score off the wrong club (W1), put two home games away (M11, M12) and called a 37% start "a coin flip" (M13).

V1  every number in the reply equals a whole-pool query: each player's points over the span, the fifteen's total, each chance
    of starting, each price; the sell prices are the squad record's;
V2  all fifteen are there, each once, grouped by position, best first within the group;
V3  "weakest 3 for their price" by brute force over the whole pool, under the owner's rule (16 Nov): the same position, within
    £0.5m, at least a 50% chance of starting the next gameweek -- and the player himself whatever his chance;
V4  the line-up's total with the captain's points counted twice is the line-up pick's own figure; the total before that is the
    eleven starters' points from the pool; the roles are the pick's;
V5  home / away and the opponents equal the calendar; a double shows both fixtures, a blank reads "no fixture";
V6  the span: default 3, 1-8 accepted, clipped to what exists and said so; the bank and the free transfers are the record's;
V7  no saved squad, a squad error, a line-up error and the draft chat give the model its usual result, never a reply;
V8  the closing question (USER DECISION 15 Nov).
Seeded pool (Tests/r3_seed.py); the squad record and the line-up pick are fakes built on it; no model, no network."""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

# a legal fifteen from the seed: 2 GK, 5 DEF, 5 MID, 3 FWD, at most 3 a club
SQUAD = {"GK": [101, 109], "DEF": [102, 104, 110, 118, 126], "MID": [105, 113, 121, 129, 137], "FWD": [107, 115, 123]}
IDS = [e for pos in ("GK", "DEF", "MID", "FWD") for e in SQUAD[pos]]
BENCH = [109, 126, 137, 123]                                 # in bench order
CAPTAIN, VICE = 107, 102
BANK, FREE = 1.3, 2
ROW = {p[0]: p for p in seed.PLAYERS}


def _sell(e):
    return round(ROW[e][4] / 10 - (0.1 if e % 3 == 0 else 0.0), 1)          # some sell for £0.1m less than today's price


@pytest.fixture
def squad(pool_db, monkeypatch):
    """A squad record and a line-up pick over the seeded players, as get_my_squad / get_my_xi return them."""
    def row(e):
        _, name, pos, club, price = ROW[e]
        return {"player_id": e, "name": name, "position": pos, "team": club, "purchase_price": price / 10,
                "current_price": price / 10, "sell_price": _sell(e)}
    sq = {"version_id": 77, "recorded_xi": [row(e) for e in IDS if e not in BENCH], "recorded_bench_in_order": [row(e) for e in BENCH],
          "bank": BANK, "free_transfers_now": FREE, "free_transfers_now_as_of_gw": seed.FIRST_GW}

    def xi_row(e):
        role = "CAPTAIN" if e == CAPTAIN else "VICE" if e == VICE else "bench" if e in BENCH else "start"
        return {"player_id": e, "name": ROW[e][1], "position": ROW[e][2], "team": ROW[e][3], "role": role,
                "bench_order": BENCH.index(e) + 1 if e in BENCH else None, "e_points": round(seed.e_points(e, seed.FIRST_GW), 2)}
    starters = [e for e in IDS if e not in BENCH]
    doubled = round(sum(seed.e_points(e, seed.FIRST_GW) for e in starters) + seed.e_points(CAPTAIN, seed.FIRST_GW), 2)
    xi = {"gw": seed.FIRST_GW, "xi": [xi_row(e) for e in starters], "bench_in_order": [xi_row(e) for e in BENCH],
          "predicted_xi_points": doubled}
    monkeypatch.setattr(mt, "get_my_squad", lambda user_id=None: dict(sq))
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: dict(xi))
    return {"sq": sq, "xi": xi, "db": pool_db, "starters": starters, "doubled": doubled}


def _points(conn, e, gws):
    return seed.q(conn, "SELECT round(COALESCE(sum(e_points::float8), 0)::numeric, 2) FROM model_predictions WHERE run_id = 1 "
                        "AND config = 'baseline' AND element = %s AND gw = ANY(%s)", (e, list(gws)))[0][0]


def _rows(reply):
    """{player name without its mark: (the full first cell, the other cells)} over the four position tables, and the table list."""
    tabs = seed.tables(reply)
    out = {}
    for _head, rows in tabs:
        for cells in rows:
            name = cells[0].split(" (")[0]
            out[name] = cells
    return out, tabs


@pytest.mark.parametrize("horizon", [1, 3, 6])
def test_v1_every_number_equals_a_whole_pool_query(squad, horizon):
    out = mt.review_my_squad(horizon=horizon, user_id=4242)
    assert "error" not in out, out
    gws = list(range(seed.FIRST_GW, seed.FIRST_GW + horizon))
    rows, _ = _rows(out["direct_reply"])
    total = Decimal("0.00")
    for e in IDS:
        _, name, _pos, club, price = ROW[e]
        cells = rows[name]
        want = _points(squad["db"], e, gws)
        total += want
        assert cells[1] == club and cells[2] == f"£{price / 10:.1f}m" and cells[3] == f"£{_sell(e):.1f}m"
        assert cells[4] == f"{want:.2f}", (name, want)
        start = seed.q(squad["db"], "SELECT round((p_start::float8 * 100)::numeric, 0) FROM model_predictions WHERE run_id = 1 "
                                    "AND element = %s AND gw = %s", (e, seed.FIRST_GW))[0][0]
        assert cells[5] == f"{int(start)}%", (name, start)
    label = "GW11" if horizon == 1 else f"GW11–{10 + horizon}"
    assert out["direct_reply"].split("\n")[0] == (f"**Your 15 players over {label} ({horizon} gameweek{'s' if horizon > 1 else ''}): "
                                                  f"{total:.2f} predicted points between them.**")
    assert [Decimal(str(p["predicted_points"])) for p in out["players"]] == \
        [_points(squad["db"], p["player_id"], gws) for p in out["players"]]


def test_v2_all_fifteen_once_grouped_by_position_best_first(squad):
    out = mt.review_my_squad(horizon=3)
    reply = out["direct_reply"]
    rows, tabs = _rows(reply)
    assert len(rows) == 15 and len(tabs) == 4 and [len(t[1]) for t in tabs] == [2, 5, 5, 3]
    assert [ln for ln in reply.split("\n") if ln.startswith("**") and ln.endswith("**") and " " not in ln.strip("*")] == \
        ["**Goalkeepers**", "**Defenders**", "**Midfielders**", "**Forwards**"]
    for (head, trows), pos in zip(tabs, ("GK", "DEF", "MID", "FWD")):
        assert head == ["Player", "Club", "Price", "Sells for", "Predicted points GW11–13", "Chance of starting GW11",
                        "Fixtures GW11–13", "Flag"]
        names = [r[0].split(" (")[0] for r in trows]
        assert sorted(names) == sorted(ROW[e][1] for e in SQUAD[pos])
        pts = [Decimal(r[4]) for r in trows]
        assert pts == sorted(pts, reverse=True)
    assert sorted(p["player_id"] for p in out["players"]) == sorted(IDS)


def _group(conn, e, first=seed.FIRST_GW):
    """The owner's rule, in SQL: his position, within £0.5m, at least a 50% chance of starting the next gameweek -- and him."""
    return {r[0] for r in seed.q(conn, """
        SELECT l.element FROM players_live l JOIN players_live me ON me.element = %(e)s
        WHERE l.position = me.position AND l.price_tenths IS NOT NULL AND abs(l.price_tenths - me.price_tenths) <= 5
          AND (l.element = %(e)s OR EXISTS (SELECT 1 FROM model_predictions p WHERE p.run_id = 1 AND p.config = 'baseline'
                                            AND p.element = l.element AND p.gw = %(gw)s AND p.p_start >= 0.5))
          AND EXISTS (SELECT 1 FROM model_predictions p WHERE p.run_id = 1 AND p.element = l.element)""", {"e": e, "gw": first})}


@pytest.mark.parametrize("horizon", [1, 3, 5])
def test_v3_the_weakest_three_by_brute_force_under_the_owners_rule(squad, horizon):
    out = mt.review_my_squad(horizon=horizon)
    gws = list(range(seed.FIRST_GW, seed.FIRST_GW + horizon))
    brute = []
    for e in IDS:
        group = _group(squad["db"], e)
        mine = _points(squad["db"], e, gws)
        rank = 1 + sum(1 for x in group if x != e and _points(squad["db"], x, gws) > mine)
        brute.append((-(rank - 1) / max(1, len(group) - 1), mine, ROW[e][1], e, rank, len(group)))
    brute.sort()
    want = [(b[3], b[4], b[5], b[1]) for b in brute[:3]]
    got = [(w["player_id"], w["rank"], w["of"], Decimal(str(w["predicted_points"]))) for w in out["weakest_for_price"]]
    assert got == want
    reply = out["direct_reply"]
    label = "GW11" if horizon == 1 else f"GW11–{10 + horizon}"
    assert (f"**Weakest 3 for their price** (each of your players is ranked on predicted points {label} against the players in the "
            "game at his position, priced within £0.5m of him, who have at least a 50% chance of starting GW11; he is ranked "
            "against that group even when his own chance is lower):") in reply
    bullets = [ln for ln in reply.split("\n") if ln.startswith("- ")]
    assert len(bullets) == 3
    for line, (e, rank, n, pts) in zip(bullets, want):
        _, name, pos, _club, price = ROW[e]
        start = int(Decimal(str(seed.p_start(e, seed.FIRST_GW) * 100)).quantize(Decimal(1), rounding="ROUND_HALF_UP"))
        assert line == (f"- {name} ({pos}, £{price / 10:.1f}m, {start}% chance of starting GW11): {pts:.2f} predicted points, "
                        f"{answers.nth(rank)} of the {n} in his group ({answers.POS_WORDS[pos][1]} priced £{(price - 5) / 10:.1f}m to "
                        f"£{(price + 5) / 10:.1f}m).")


def test_v3b_a_player_under_fifty_percent_is_still_ranked_and_can_be_listed(squad):
    # the group is likely starters only, so a squad player who is not one is ranked against them and can come last
    low = [e for e in IDS if seed.p_start(e, seed.FIRST_GW) < 0.5]
    assert low, "the seed must hold a squad player under 50%"
    for e in low:
        group = _group(squad["db"], e)
        assert e in group and all(seed.p_start(x, seed.FIRST_GW) >= 0.5 for x in group if x != e)


def test_v4_the_line_up_total_both_ways_and_the_roles_are_the_picks(squad):
    out = mt.review_my_squad(horizon=3)
    reply = out["direct_reply"]
    once = seed.q(squad["db"], "SELECT round(sum(e_points::float8)::numeric, 2) FROM model_predictions WHERE run_id = 1 AND gw = 11 "
                               "AND element = ANY(%s)", (squad["starters"],))[0][0]
    doubled = Decimal(str(squad["doubled"]))
    bench = ", ".join(ROW[e][1] for e in BENCH)
    assert (f"**Line-up for GW11:** the (C), (VC) and bench marks above are the best XI from these 15 for GW11: {doubled:.2f} predicted "
            f"points with the captain's points counted twice ({once:.2f} before that). Captain {ROW[CAPTAIN][1]}, vice-captain "
            f"{ROW[VICE][1]}; bench in order: {bench}.") in reply
    assert out["lineup"] == {"gw": 11, "predicted_points_captain_doubled": float(doubled), "predicted_points_captain_once": float(once)}
    rows, _ = _rows(reply)
    assert rows[ROW[CAPTAIN][1]][0] == f"{ROW[CAPTAIN][1]} (C)" and rows[ROW[VICE][1]][0] == f"{ROW[VICE][1]} (VC)"
    for i, e in enumerate(BENCH, 1):
        assert rows[ROW[e][1]][0] == f"{ROW[e][1]} (bench {i})"
    plain = [e for e in IDS if e not in BENCH and e not in (CAPTAIN, VICE)]
    assert all(rows[ROW[e][1]][0] == ROW[e][1] for e in plain)


def test_v5_home_away_and_opponents_equal_the_calendar(squad):
    out = mt.review_my_squad(horizon=3)
    rows, _ = _rows(out["direct_reply"])
    cal = seed.calendar()
    for e in IDS:
        _, name, _pos, club, _price = ROW[e]
        want = []
        for g in (11, 12, 13):
            fx = cal.get((club, g)) or []
            want.append(" + ".join(f"{seed.SHORTS[f['opponent']]} ({'H' if f['home'] else 'A'})" for f in fx) if fx else "no fixture")
        assert rows[name][6] == ", ".join(want), name
    assert " + FOX (A)" in rows[ROW[102][1]][6]                              # Alpha's double in GW12
    assert rows[ROW[110][1]][6].endswith("no fixture")                       # Bravo's blank in GW13


def test_v5b_an_unreadable_calendar_never_reads_no_fixture(squad, monkeypatch):
    monkeypatch.setattr(mt, "_answer_calendar", lambda: None)
    rows, _ = _rows(mt.review_my_squad(horizon=2)["direct_reply"])
    assert {r[6] for r in rows.values()} == {"not known"}


def test_v6_the_span_the_bank_and_the_free_transfers(squad, monkeypatch):
    default = mt.review_my_squad()
    assert default["gameweeks"] == [11, 12, 13]                              # the default is three gameweeks
    assert "**Money and transfers:** £1.3m in the bank; 2 free transfers for the GW11 deadline." in default["direct_reply"]
    eight = mt.review_my_squad(horizon=8)["direct_reply"].split("\n")
    assert eight[0].startswith("**Your 15 players over GW11–16 (6 gameweeks):")
    assert eight[1] == "Predictions exist for GW11–16 only, so this covers 6 gameweeks, not 8."
    assert eight[2] == f"Predictions from the update of Wed 11 Nov 2026, 11:01 UTC. Next update: {seed.NEXT_UPDATE}."
    assert "error" in mt.review_my_squad(horizon=9) and "error" in mt.review_my_squad(horizon=0)
    one = dict(squad["sq"], free_transfers_now=1, bank=0.0)
    monkeypatch.setattr(mt, "get_my_squad", lambda user_id=None: one)
    assert "£0.0m in the bank; 1 free transfer for the GW11 deadline." in mt.review_my_squad()["direct_reply"]
    flagged = mt.review_my_squad()["players"]
    assert next(p for p in flagged if p["player_id"] == 121)["flag"].startswith('Injured — FPL: "Hamstring injury')


def test_v7_no_squad_an_error_and_the_draft_chat_are_the_models_to_report(squad, monkeypatch):
    note = {"no_squad": True, "note": mt.NO_SQUAD_NOTE}
    monkeypatch.setattr(mt, "get_my_squad", lambda user_id=None: dict(note))
    assert mt.review_my_squad() == note                                       # General mode: the usual result, no reply
    monkeypatch.setattr(mt, "get_my_squad", lambda user_id=None: {"error": "2 active squad versions"})
    assert mt.review_my_squad() == {"error": "2 active squad versions"}
    monkeypatch.setattr(mt, "get_my_squad", lambda user_id=None: dict(squad["sq"]))
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: {"error": "the predictions and the database disagree"})
    assert mt.review_my_squad() == {"error": "the predictions and the database disagree"}
    monkeypatch.setattr(mt, "get_my_xi", lambda user_id=None, gw=None: dict(squad["xi"], gw=12))
    assert "error" in mt.review_my_squad() and "direct_reply" not in mt.review_my_squad()
    import turn_context
    turn_context.begin("v" * 32, thread_id="th_draft", draft={"user_id": 10001, "draft_key": 800_000_001})
    try:
        out = mt.review_my_squad()
    finally:
        turn_context.end()
    assert "error" in out and "direct_reply" not in out


def test_v8_the_closing_question(squad):
    lines = mt.review_my_squad()["direct_reply"].split("\n")
    assert lines[-1] == "Which player would you like me to go into, or is there anyone you'd like to bring in?"
    assert lines[-2] == "" and lines[-3] == answers.BONUS_NOTE
    assert lines[-4] == ("GW11 is priced off the betting market. GW12–13 are longer-range estimates from team strengths, with no odds, "
                         "lineups or team news yet, so the order will move before then.")
