"""Prompt R3 item 1 (16 Nov 2026): rank_players -- the true top N over the WHOLE player pool, written by code.

Measured before it existed (eval/reports/r3_evidence_digest.md, R1's Set B): "top 8 forwards" and "best-value defenders" were
answered from a price-ordered list of 25 or a few clubs' players and called "the best" (M3, M7, M15, M22, M27), in tables headed
"ranked by" that were not in that order (M8, M16, M21, M26), with sums the model added itself (W2, W5, W6), over the wrong
number of gameweeks (M20), after 32-45 single-player lookups in one response (C3, C4).

K1  every number and the order of the reply equal a whole-pool query (SQL over every seeded player, never the tool's own rows);
K2  the header states exactly what was ranked: how many of how many, the position, the price filter, the club, the gameweeks;
K3  the list is sorted, and ties are settled the same way every time (points: cheaper, then name; value: more points, cheaper);
K4  the span is exactly the gameweeks asked, counted from the next deadline's; fewer than asked says so in the second line;
K5  a double gameweek counts both fixtures and shows both; a blank counts nothing and reads "no fixture";
K6  the value sort is the shown points per £1m of today's price;
K7  flagged players are ranked and marked with FPL's own words; a player with no prediction row or no price is not in the pool;
K8  a bad argument, an unknown club and the draft chat come back as an error for the model, never a reply;
K9  the closing question (USER DECISION 15 Nov), with a squad and in General mode; nothing matching says so.
Seeded database (Tests/r3_seed.py); no model, no network."""
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

POS = {"GK": "goalkeepers", "DEF": "defenders", "MID": "midfielders", "FWD": "forwards", "any": "players"}


def whole_pool(conn, gws, position="any", sort="points", club=None, lo=None, hi=None):
    """The independent answer: every pool player through the filters, ordered in SQL."""
    where, params = [], {"gws": list(gws), "run": seed.RUN_ID}
    if position != "any":
        where.append("position = %(pos)s")
        params["pos"] = position
    if club:
        where.append("team = %(club)s")
        params["club"] = club
    if lo is not None:
        where.append("price_tenths >= %(lo)s")
        params["lo"] = lo
    if hi is not None:
        where.append("price_tenths <= %(hi)s")
        params["hi"] = hi
    order = "value DESC, total DESC, price_tenths, name, element" if sort == "value" else "total DESC, price_tenths, name, element"
    sql = seed.POOL_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order
    return seed.q(conn, sql, params)


def check_table(reply, want, position, sort, gws):
    """Every row of the reply's table against the whole-pool rows `want` (already the top n, in order)."""
    rows = seed.table_rows(reply)
    assert len(rows) == len(want)
    cal = seed.calendar()
    for i, (cells, (element, name, pos, team, price, total, value)) in enumerate(zip(rows, want), 1):
        it = iter(cells)
        assert next(it) == str(i)
        assert next(it) == name
        if position == "any":
            assert next(it) == pos
        assert next(it) == team
        assert next(it) == f"£{price / 10:.1f}m"
        assert next(it) == f"{total:.2f}", (name, total)
        if sort == "value":
            assert next(it) == f"{value:.2f}", (name, value)
        fx = next(it)
        assert fx == answers.fixtures_cell(cal, seed.SHORTS, team, gws)


CASES = [
    dict(position="FWD", horizon=4, n=8),
    dict(position="DEF", horizon=5, n=10, sort="value", max_price=4.9),
    dict(position="any", horizon=1, n=20),
    dict(position="MID", horizon=6, n=5, min_price=6.5),
    dict(position="GK", horizon=3, n=6, club="Charlie"),
    dict(position="any", horizon=2, n=7, sort="value", min_price=4.6, max_price=6.8),
    dict(position="DEF", horizon=3, n=20, club="Alpha"),
]


@pytest.mark.parametrize("case", CASES)
def test_k1_every_number_and_the_order_equal_a_whole_pool_query(pool_db, case):
    out = mt.rank_players(**case, user_id=4242)
    assert "error" not in out, out
    gws = list(range(seed.FIRST_GW, seed.FIRST_GW + case["horizon"]))
    lo = None if case.get("min_price") is None else int(round(case["min_price"] * 10))
    hi = None if case.get("max_price") is None else int(round(case["max_price"] * 10))
    want = whole_pool(pool_db, gws, case["position"], case.get("sort", "points"), case.get("club"), lo, hi)
    assert out["gameweeks"] == gws and out["ranked"] == len(want)
    check_table(out["direct_reply"], want[:case["n"]], case["position"], case.get("sort", "points"), gws)
    assert [r["player_id"] for r in out["rows"]] == [w[0] for w in want[:case["n"]]]
    assert [Decimal(str(r["predicted_points"])) for r in out["rows"]] == [w[5] for w in want[:case["n"]]]


def test_k2_the_header_states_exactly_what_was_ranked(pool_db):
    n_fwd = len(whole_pool(pool_db, [11, 12, 13, 14], "FWD"))
    head = mt.rank_players(position="FWD", horizon=4, n=8)["direct_reply"].split("\n")[0]
    assert head == f"**Top 8 of {n_fwd} forwards by predicted points, GW11–14 (4 gameweeks).**" and n_fwd == 11   # 12 seeded, one has no price
    n_def = len(whole_pool(pool_db, [11, 12, 13, 14, 15], "DEF", hi=49))
    reply = mt.rank_players(position="DEF", max_price=4.9, horizon=5, sort="value", n=3)["direct_reply"]
    assert reply.split("\n")[0] == f"**Top 3 of {n_def} defenders priced £4.9m or less by predicted points per £1m, GW11–15 (5 gameweeks).**"
    assert f"All {n_def} defenders priced £4.9m or less in the game were ranked, flagged players included." in reply
    assert mt.rank_players(position="MID", min_price=6.5, max_price=7.0, n=2)["direct_reply"].startswith(
        "**Top 2 of ") and "midfielders priced £6.5m to £7.0m by predicted points, GW11 (1 gameweek).**" in \
        mt.rank_players(position="MID", min_price=6.5, max_price=7.0, n=2)["direct_reply"].split("\n")[0]
    club = mt.rank_players(club="Charlie", n=20, horizon=2)["direct_reply"].split("\n")[0]
    assert club == "**All 8 Charlie players, by predicted points, GW11–12 (2 gameweeks).**"         # n covers everyone: "All"
    one = mt.rank_players(position="GK", n=1)["direct_reply"]
    assert one.split("\n")[0] == "**Top 1 of 6 goalkeepers by predicted points, GW11 (1 gameweek).**"
    assert "every fixture in that gameweek counted" in one
    assert one.split("\n")[1] == f"Predictions from the update of Wed 11 Nov 2026, 11:01 UTC. Next update: {seed.NEXT_UPDATE}."


def test_k3_sorted_and_ties_settled_the_same_way_every_time(pool_db):
    out = mt.rank_players(position="any", horizon=6, n=20)
    totals = [r["predicted_points"] for r in out["rows"]]
    assert totals == sorted(totals, reverse=True)
    # 104 / 112 are level on points every gameweek at different prices; 105 / 113 level on points AND price
    rows = {r[0]: r for r in whole_pool(pool_db, [11], "any")}
    assert rows[104][5] == rows[112][5] and rows[104][4] != rows[112][4]
    assert rows[105][5] == rows[113][5] and rows[105][4] == rows[113][4]
    order = [r[0] for r in whole_pool(pool_db, [11], "DEF")]
    listed = [r["player_id"] for r in mt.rank_players(position="DEF", n=20)["rows"]]
    assert listed == order[:20]
    cheap, dear = sorted((104, 112), key=lambda e: rows[e][4])
    assert listed.index(cheap) < listed.index(dear)                          # level totals: the cheaper player first
    mids = [r["player_id"] for r in mt.rank_players(position="MID", n=20)["rows"]]
    assert mids == [r[0] for r in whole_pool(pool_db, [11], "MID")][:20]
    by_name = sorted((105, 113), key=lambda e: rows[e][1])
    assert mids.index(by_name[0]) + 1 == mids.index(by_name[1])              # level totals and prices: by name
    assert mt.rank_players(position="DEF", n=20)["direct_reply"] == mt.rank_players(position="DEF", n=20)["direct_reply"]
    assert "level totals go to the cheaper player, then by name" in mt.rank_players(position="DEF", n=20)["direct_reply"]


def test_k4_the_span_is_exactly_the_gameweeks_asked_and_a_shorter_one_says_so(pool_db):
    for h in range(1, 7):
        out = mt.rank_players(position="FWD", horizon=h, n=3)
        assert out["gameweeks"] == list(range(11, 11 + h))
        assert "Predictions exist for" not in out["direct_reply"]
    out = mt.rank_players(position="FWD", horizon=8, n=3)
    lines = out["direct_reply"].split("\n")
    assert out["gameweeks"] == [11, 12, 13, 14, 15, 16]
    assert lines[0].endswith("GW11–16 (6 gameweeks).**")
    assert lines[1] == "Predictions exist for GW11–16 only, so this covers 6 gameweeks, not 8."
    check_table(out["direct_reply"], whole_pool(pool_db, [11, 12, 13, 14, 15, 16], "FWD")[:3], "FWD", "points", out["gameweeks"])


def test_k4b_between_deadlines_the_span_starts_at_the_next_deadline(pool_db, monkeypatch):
    monkeypatch.setattr(mt, "_current_gw", lambda: 12)                        # GW11's deadline has passed; the build is GW11's
    out = mt.rank_players(position="MID", horizon=2, n=4)
    assert out["gameweeks"] == [12, 13]
    check_table(out["direct_reply"], whole_pool(pool_db, [12, 13], "MID")[:4], "MID", "points", [12, 13])
    assert "GW11 is priced off the betting market" not in out["direct_reply"]
    assert "GW12–13 are longer-range estimates from team strengths" in out["direct_reply"]
    monkeypatch.setattr(mt, "_current_gw", lambda: 17)                        # nothing predicted for the next deadline yet
    assert "error" in mt.rank_players(position="MID") and "direct_reply" not in mt.rank_players(position="MID")


def test_k5_a_double_counts_both_fixtures_and_a_blank_counts_nothing(pool_db):
    alpha = mt.rank_players(club="Alpha", n=20, horizon=2)
    for r in alpha["rows"]:
        assert " + FOX (A)" in r["fixtures"]                                  # GW12: two fixtures, both shown
        want = seed.q(pool_db, "SELECT round(sum(e_points::float8)::numeric, 2) FROM model_predictions WHERE run_id = 1 AND element = %s "
                               "AND gw IN (11, 12)", (r["player_id"],))[0][0]
        assert Decimal(str(r["predicted_points"])) == want                    # the double's row holds both fixtures' points
    bravo = mt.rank_players(club="Bravo", n=20, horizon=3)
    for r in bravo["rows"]:
        assert r["fixtures"].endswith(", no fixture")                         # GW13: a blank
        want = seed.q(pool_db, "SELECT round(sum(e_points::float8)::numeric, 2) FROM model_predictions WHERE run_id = 1 AND element = %s "
                               "AND gw IN (11, 12)", (r["player_id"],))[0][0]
        assert Decimal(str(r["predicted_points"])) == want                    # GW13 adds nothing
    only_blank = mt.rank_players(club="Bravo", n=3, horizon=1)                # a one-gameweek span that is NOT the blank
    assert "no fixture" not in only_blank["direct_reply"]


def test_k6_the_value_sort_is_the_shown_points_per_million(pool_db):
    out = mt.rank_players(position="any", horizon=3, sort="value", n=20)
    for r in out["rows"]:
        want = (Decimal(str(r["predicted_points"])) / Decimal(str(r["price"]))).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        assert Decimal(str(r["points_per_million"])) == want
    vals = [r["points_per_million"] for r in out["rows"]]
    assert vals == sorted(vals, reverse=True)
    assert "| Points per £1m |" in out["direct_reply"] and "Ranked by predicted points per £1m of today's price" in out["direct_reply"]
    assert "Points per £1m" not in mt.rank_players(position="any", horizon=3, n=5)["direct_reply"]


def test_k7_flagged_players_are_ranked_and_marked_and_the_pool_is_the_builds(pool_db):
    out = mt.rank_players(position="any", horizon=1, n=20, club="Alpha")
    flags = {r["player_id"]: r["flag"] for r in out["rows"]}
    assert flags[106] == 'Doubtful — FPL: "Knock - 75% chance of playing" (as of Wed 11 Nov)'
    assert all(v is None for e, v in flags.items() if e not in seed.FLAGS)
    everyone = mt.rank_players(position="any", horizon=1, n=20, sort="value", min_price=4.0)
    assert everyone["ranked"] == 47                                            # 48 seeded - the one without a price; 999 has no row
    listed = [r[0] for r in whole_pool(pool_db, [11])]
    assert 999 not in listed and seed.NO_PRICE not in listed and len(listed) == 47
    injured = mt.rank_players(club="Charlie", n=20)["rows"]
    assert next(r for r in injured if r["player_id"] == 121)["flag"].startswith('Injured — FPL: "Hamstring injury')
    no_news = mt.rank_players(club="Bravo", n=20)["rows"]
    assert next(r for r in no_news if r["player_id"] == 109)["flag"] == "Doubtful — FPL: 50% chance of playing (as of Wed 11 Nov)"


def test_k7b_a_player_fpl_lists_without_a_prediction_is_said_to_be_unranked(pool_db):
    # 999 (Echo, MID, £5.0m) is in players_live and in no build: he cannot be ranked, and "all ... were ranked" must not claim him
    mids = mt.rank_players(position="MID", n=3)["direct_reply"]
    n = len(whole_pool(pool_db, [11], "MID"))
    assert (f"All {n} midfielders with a prediction were ranked, flagged players included; 1 more that FPL lists has no prediction in "
            "this update and is not ranked.") in mids
    assert mids.split("\n")[0] == f"**Top 3 of {n} midfielders by predicted points, GW11 (1 gameweek).**"
    fwds = mt.rank_players(position="FWD", n=3)["direct_reply"]             # no forward is unrated: the sentence as approved
    assert "All 11 forwards in the game were ranked, flagged players included." in fwds and "no prediction in this update" not in fwds
    dear = mt.rank_players(position="MID", min_price=6.0, n=3)["direct_reply"]   # he is outside this price filter: not counted
    assert "no prediction in this update" not in dear
    with pool_db.cursor() as cur:
        cur.execute("INSERT INTO players_live (element, name, position, team, price_tenths, status, updated_at) VALUES "
                    "(998, 'Another Unrated', 'MID', 'Echo', 55, 'a', now())")
    assert "2 more that FPL lists have no prediction in this update and are not ranked." in mt.rank_players(club="Echo")["direct_reply"]


@pytest.mark.parametrize("args,needle", [
    ({"position": "wingers"}, "is not one of GK, DEF, MID, FWD or any"),
    ({"n": 0}, "n must be a whole number from 1 to 20"), ({"n": 21}, "n must be a whole number from 1 to 20"),
    ({"horizon": 0}, "the number of gameweeks must be a whole number from 1 to 8"), ({"horizon": 9}, "from 1 to 8"),
    ({"sort": "form"}, "sort must be 'points' or 'value'"), ({"min_price": 7.0, "max_price": 5.0}, "is above max_price"),
    ({"max_price": "cheap"}, "must be a price in £m"), ({"club": "Narnia"}, "no club matches 'Narnia'"),
])
def test_k8_a_bad_argument_is_an_error_for_the_model_never_a_reply(pool_db, args, needle):
    out = mt.rank_players(**args)
    assert needle in out["error"] and "direct_reply" not in out


def test_k8b_position_words_and_club_aliases_are_understood(pool_db):
    assert mt.rank_players(position="striker", n=2)["direct_reply"].startswith("**Top 2 of 11 forwards")
    assert mt.rank_players(position="Goalkeepers", n=2)["direct_reply"].startswith("**Top 2 of 6 goalkeepers")
    assert mt.rank_players(position=None, n=2)["direct_reply"].startswith("**Top 2 of 47 players")


def test_k8c_not_in_the_draft_chat(pool_db):
    import turn_context
    turn_context.begin("r" * 32, thread_id="th_draft", draft={"user_id": 10001, "draft_key": 800_000_001})
    try:
        out = mt.rank_players(position="FWD")
    finally:
        turn_context.end()
    assert "error" in out and "direct_reply" not in out


def test_k9_the_closing_question_and_an_empty_result(pool_db, monkeypatch):
    with_squad = mt.rank_players(position="FWD", n=3)["direct_reply"].split("\n")
    assert with_squad[-1] == "Want me to compare any of these, or check one against your squad?" == answers.RANK_FOLLOW_UP
    assert with_squad[-2] == "" and with_squad[-3] == answers.BONUS_NOTE
    monkeypatch.setattr(mt, "_has_saved_squad", lambda user_id: False)        # General mode: no squad to check against
    assert mt.rank_players(position="FWD", n=3)["direct_reply"].split("\n")[-1] == "Want me to compare any of these?"
    none = mt.rank_players(position="GK", max_price=3.0)
    cheapest = seed.q(pool_db, "SELECT min(price_tenths) FROM players_live WHERE position = 'GK' AND element < 900")[0][0]
    assert none["rows"] == [] and none["direct_reply"].split("\n")[:2] == [
        "**No goalkeepers priced £3.0m or less in the game.**", f"The cheapest of the goalkeepers costs £{cheapest / 10:.1f}m."]
    assert none["direct_reply"].split("\n")[-1] == answers.RANK_FOLLOW_UP_NONE


def test_k10_the_bonus_note_is_the_reviewed_sentence():
    import draft_tools
    assert answers.BONUS_NOTE == draft_tools.BONUS_NOTE and answers.REVIEW_FOLLOW_UP == draft_tools.EXPLAIN_FOLLOW_UP
