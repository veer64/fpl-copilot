"""Prompt R3b item 1 (16 Nov 2026; USER DECISION): the best squad from scratch is written by code.

Measured before (eval/reports/r3_answers.md, Set B case 4, 1 of 3): the model wrote the fifteen itself from the build's rows and
slipped three times in two replies -- "Starting XI — 72.1 expected points (captain doubled)" for an XI whose total is 63.25
(its own sum), "Starting XI (£99.9m spent)" (the cost of all fifteen on the XI's header), a captain's mark on the vice-captain,
and a "(£5.0–5.5m)" price band nobody had asked for.

S1   the XI's total is stated both ways -- with the captain's points counted twice, and before that -- and both equal a
     whole-pool query over the eleven starters;
S2   the (C), (VC) and bench marks are the solver's own roles and bench order, one captain, one vice-captain;
S3   every one of the fifteen carries his own price (the solve's), predicted points, fixture and FPL flag;
S4   the spend is labelled separately for the XI, the bench, the fifteen and the bank, and the four add up;
S5   a budget is stated exactly as given and no price band appears;
S6   a price that has moved since the build is named, never silently swapped in;
S7   forced / left-out players, the forced-player warning and a planning-view note are carried in;
S8   the closing question (USER DECISION), with and without a saved squad;
S9   an error, a past squad and a draft chat's turn carry no code-built text;
S10  the stored build (best_squad_from_scratch at the full budget) and a real solve (build_squad_from_scratch) both return
     the text, the solve with the solver's own bench order.
Seeded pool (Tests/r3_seed.py); no model, no network."""
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
import squad_store                                          # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

ROW = {p[0]: p for p in seed.PLAYERS}
XI = [101, 102, 103, 110, 118, 105, 113, 121, 129, 107, 115]          # 107 the captain, 105 the vice-captain
BENCH = [109, 126, 137, 123]                                          # bench 1 (the reserve keeper) .. bench 4
ROLE = {**{e: "start" for e in XI}, 107: "CAPTAIN", 105: "VICE", **{e: "bench" for e in BENCH}}
GW = 11


def _row(e, price=None, bench_order=True):
    r = {"player_id": e, "name": ROW[e][1], "position": ROW[e][2], "team": ROW[e][3], "role": ROLE[e],
         "price": (ROW[e][4] if price is None else price) / 10, "e_points": seed.e_points(e, GW)}
    if bench_order:
        r["bench_order"] = BENCH.index(e) + 1 if e in BENCH else None
    return r


def _stored(price=None):
    """The stored build's result, shaped as get_picks returns it (xi + bench_in_order, each row with its bench order)."""
    price = price or {}
    return {"gw": GW, "config": "baseline (production)", "captain": ROW[107][1], "vice": ROW[105][1],
            "xi": [_row(e, price.get(e)) for e in XI], "bench_in_order": [_row(e, price.get(e)) for e in BENCH],
            "squad_cost": round(sum((price.get(e) or ROW[e][4]) for e in XI + BENCH) / 10, 1)}


def _text(out, **kw):
    got = mt._with_squad_answer(out, **kw)
    assert "direct_reply_error" not in got, got.get("direct_reply_error")
    return got["direct_reply"]


def _sum(conn, elements):
    return seed.q(conn, "SELECT round(sum(e_points::float8)::numeric, 2) FROM model_predictions WHERE run_id = 1 AND config = 'baseline' "
                        "AND gw = %s AND element = ANY(%s)", (GW, list(elements)))[0][0]


def test_s1_the_xi_total_is_stated_both_ways_and_both_equal_a_pool_query(pool_db):
    text = _text(_stored())
    once = _sum(pool_db, XI)
    cap = _sum(pool_db, [107])
    doubled = once + cap
    assert text.split("\n")[0] == (f"**Best 15 from scratch for GW11 on a £100.0m budget: the starting XI is predicted {doubled:.2f} points "
                                   f"with the captain's points counted twice, {once:.2f} before that.**")
    assert (f"The starting XI: {doubled:.2f} predicted points with the captain's points counted twice, {once:.2f} before that.") in text
    got = mt._with_squad_answer(_stored())
    assert got["xi_points"] == {"captain_counted_twice": float(doubled), "before_that": float(once)}
    # the two totals are the ONLY XI totals in the text, and no other number is called a total of the XI
    assert len(re.findall(r"with the captain's points counted twice", text)) == 2


def test_s2_the_marks_and_the_bench_order_are_the_solvers(pool_db):
    text = _text(_stored())
    rows = [r for _h, body in seed.tables(text) for r in body]
    assert len(rows) == 15
    marks = {r[0]: r[0] for r in rows}
    assert sum(1 for r in rows if r[0].endswith(" (C)")) == 1 and f"{ROW[107][1]} (C)" in marks
    assert sum(1 for r in rows if r[0].endswith(" (VC)")) == 1 and f"{ROW[105][1]} (VC)" in marks
    for k, e in enumerate(BENCH, 1):
        assert f"{ROW[e][1]} (bench {k})" in marks
    for e in XI:
        if e not in (107, 105):
            assert ROW[e][1] in marks                                        # a starter carries no mark
    assert (f"Captain {ROW[107][1]}, vice-captain {ROW[105][1]}; bench in order: " + ", ".join(ROW[e][1] for e in BENCH) + ".") in text
    # grouped by position, in FPL's order, starters before the bench
    titles = [ln for ln in text.split("\n") if ln in ("**Goalkeepers**", "**Defenders**", "**Midfielders**", "**Forwards**")]
    assert titles == ["**Goalkeepers**", "**Defenders**", "**Midfielders**", "**Forwards**"]
    gk = seed.tables(text)[0][1]
    assert [r[0] for r in gk] == [ROW[101][1], f"{ROW[109][1]} (bench 1)"]


def test_s3_every_row_is_the_players_own_price_points_fixture_and_flag(pool_db):
    text = _text(_stored())
    cal = seed.calendar()
    want = {r[0]: r for r in seed.q(pool_db, "SELECT l.element, l.name, l.team, l.price_tenths, round(p.e_points::float8::numeric, 2) "
                                             "FROM players_live l JOIN model_predictions p ON p.element = l.element AND p.run_id = 1 "
                                             "AND p.config = 'baseline' AND p.gw = 11 WHERE l.element = ANY(%s)", (XI + BENCH,))}
    seen = 0
    for head, body in seed.tables(text):
        assert head == ["Player", "Club", "Price", "Predicted points GW11", "Fixtures GW11", "Flag"]
        for r in body:
            e = next(x for x in XI + BENCH if r[0].split(" (")[0] == ROW[x][1])
            _e, _name, team, price, pts = want[e]
            fx = cal[(team, 11)][0]
            assert r[1] == team and r[2] == f"£{price / 10:.1f}m" and r[3] == f"{pts:.2f}"
            assert r[4] == f"{seed.SHORTS[fx['opponent']]} ({'H' if fx['home'] else 'A'})"
            seen += 1
    assert seen == 15
    flags = {r[0].split(" (")[0]: r[5] for _h, body in seed.tables(text) for r in body}
    assert flags[ROW[121][1]] == 'Injured — FPL: "Hamstring injury - Expected back 05 Dec" (as of Wed 11 Nov)'
    assert flags[ROW[109][1]] == "Doubtful — FPL: 50% chance of playing (as of Wed 11 Nov)"
    assert flags[ROW[107][1]] == ""


def test_s4_spend_is_labelled_for_the_xi_the_bench_the_fifteen_and_the_bank(pool_db):
    got = mt._with_squad_answer(_stored())
    xi, bench = sum(ROW[e][4] for e in XI), sum(ROW[e][4] for e in BENCH)
    assert (f"**Spend:** the starting XI costs £{xi / 10:.1f}m and the bench £{bench / 10:.1f}m; all 15 cost £{(xi + bench) / 10:.1f}m, "
            f"which leaves £{(1000 - xi - bench) / 10:.1f}m of the £100.0m budget in the bank.") in got["direct_reply"]
    assert got["spend"] == {"xi": xi / 10, "bench": bench / 10, "all_15": (xi + bench) / 10, "bank": round((1000 - xi - bench) / 10, 1),
                            "budget": 100.0}
    head = got["direct_reply"].split("\n")[0]
    assert "spent" not in head and "cost" not in head                        # R3's slip: the fifteen's cost on the XI's header


def test_s5_a_budget_is_stated_exactly_and_no_price_band_appears(pool_db):
    out = {"gw": GW, "constraints": {"locked": [], "banned": [], "budget": 95.5}, "captain": ROW[107][1], "vice": ROW[105][1],
           "squad": [_row(e, bench_order=False) for e in XI + BENCH], "squad_cost": 0}
    roles = {e: (ROLE[e], BENCH.index(e) + 1 if e in BENCH else None) for e in XI + BENCH}
    text = _text(out, roles=roles)
    cost = sum(ROW[e][4] for e in XI + BENCH)
    assert text.startswith("**Best 15 from scratch for GW11 on a £95.5m budget: ")
    assert f"which leaves £{(955 - cost) / 10:.1f}m of the £95.5m budget in the bank." in text
    assert not re.search(r"£\d+\.\d–\d+\.\dm|£\d+\.\dm ?(?:to|-|–) ?£\d+\.\dm", text)   # no "(£5.0–5.5m)" band: nothing was filtered by price
    assert "£100.0m" not in text


def test_s6_a_price_that_moved_since_the_build_is_named(pool_db):
    moved = _stored(price={107: ROW[107][4] - 1, 118: ROW[118][4] + 2})     # the build paid 0.1 less / 0.2 more than today's price
    text = _text(moved)
    rows = {r[0].split(" (")[0]: r for _h, body in seed.tables(text) for r in body}
    assert rows[ROW[107][1]][2] == f"£{(ROW[107][4] - 1) / 10:.1f}m"        # the row shows the price the build used
    assert (f"Prices are the ones the build used. Since then: {ROW[118][1]} is now £{ROW[118][4] / 10:.1f}m; "
            f"{ROW[107][1]} is now £{ROW[107][4] / 10:.1f}m.") in text or \
           (f"Prices are the ones the build used. Since then: {ROW[107][1]} is now £{ROW[107][4] / 10:.1f}m; "
            f"{ROW[118][1]} is now £{ROW[118][4] / 10:.1f}m.") in text
    assert "Since then" not in _text(_stored())


def test_s7_forced_left_out_warning_and_planning_note_are_carried(pool_db):
    out = {"gw": 13, "note": "Planning view for GW13 from today's predictions: GW13 is inside the model's range, so this is a real "
                             "prediction, but availability and predictions will change before then.",
           "forced_availability_warning": f"{ROW[121][1]} is flagged injured by FPL; he is in the squad because you asked.",
           "constraints": {"locked": [121, 107], "banned": [108], "budget": 100.0, "start": [107]},
           "squad": [{**_row(e, bench_order=False), "e_points": seed.e_points(e, 13) or 0.0} for e in XI + BENCH]}
    roles = {e: (ROLE[e], BENCH.index(e) + 1 if e in BENCH else None) for e in XI + BENCH}
    text = _text(out, roles=roles)
    lines = text.split("\n")
    assert lines[0].startswith("**Best 15 from scratch for GW13 on a £100.0m budget: ")
    assert lines[1] == out["forced_availability_warning"] and lines[2] == out["note"]
    assert f"Forced in: {ROW[121][1]}, {ROW[107][1]} (to start: {ROW[107][1]}). Left out: {ROW[108][1]}." in text
    assert ("GW13 is a longer-range estimate from team strengths, with no odds, lineups or team news yet, so these picks will move "
            "before then.") in text
    bravo = [r for _h, body in seed.tables(text) for r in body if r[1] == "Bravo"]
    assert bravo and all(r[3] == "0.00" and r[4] == "no fixture" for r in bravo)   # Bravo's blank gameweek: nothing predicted, said as such


def test_s8_the_closing_question(pool_db, monkeypatch):
    assert _text(_stored()).split("\n")[-1] == "Want me to explain any of these picks, or compare any of them with your players?"
    monkeypatch.setattr(mt, "_has_saved_squad", lambda user_id: False)
    text = _text(_stored())
    assert text.split("\n")[-1] == "Want me to explain any of these picks?"
    assert answers.BONUS_NOTE in text and "No other reasons are available." in text


def test_s9_no_text_for_an_error_a_past_squad_or_a_draft_turn(pool_db, monkeypatch):
    for res in ({"error": "no legal squad fits £60.0m", "error_kind": "budget_infeasible"},
                {**_stored(), "past": True}, {"gw": GW, "xi": [], "bench_in_order": []}):
        assert "direct_reply" not in mt._with_squad_answer(dict(res))
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    assert mt._with_squad_answer(_stored()) == _stored()                     # a draft chat's turn: the result it always had


def test_s10a_the_stored_build_returns_the_text(pool_db, monkeypatch):
    with pool_db.cursor() as cur:
        for e in XI + BENCH:
            cur.execute("INSERT INTO model_picks (run_id, config, element, name, position, team, role, bench_order, price_tenths, e_points) "
                        "VALUES (1, 'baseline', %s, %s, %s, %s, %s, %s, %s, %s)",
                        (e, ROW[e][1], ROW[e][2], ROW[e][3], ROLE[e], BENCH.index(e) + 1 if e in BENCH else None, ROW[e][4], seed.e_points(e, GW)))
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    monkeypatch.setattr(mt, "_fixture_counts", lambda gw, elements: {})
    out = mt.get_best_squad()
    assert "error" not in out and "direct_reply_error" not in out, out
    once = _sum(pool_db, XI)
    doubled = once + _sum(pool_db, [107])
    assert out["direct_reply"].startswith(f"**Best 15 from scratch for GW11 on a £100.0m budget: the starting XI is predicted {doubled:.2f} points ")
    assert len(out["xi"]) == 11 and len(out["bench_in_order"]) == 4          # the rows a follow-up needs still travel
    assert f"bench in order: {', '.join(ROW[e][1] for e in BENCH)}." in out["direct_reply"]


def test_s10b_a_real_solve_returns_the_text_with_the_solvers_own_bench_order(pool_db, monkeypatch):
    df = pd.DataFrame([{"element": e, "name": name, "position": pos, "team": club, "value": price, "e_points": seed.e_points(e, GW),
                        "p_play_any": 0.9, "p_60plus": 0.8} for e, name, pos, club, price in seed.PLAYERS if e != seed.NO_PRICE])
    monkeypatch.setattr(mt, "_load_pool", lambda gw=None: (df, GW, datetime(2026, 11, 11, tzinfo=timezone.utc)))
    monkeypatch.setattr(mt, "_frame_built", lambda cutoff: {"built": "built test", "next_run_expected": None})
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    monkeypatch.setattr(mt, "_fixture_counts", lambda gw, elements: {})
    seen = {}
    real = squad_store.roles_from_team

    def spy(team):
        seen["roles"] = real(team)
        return seen["roles"]

    monkeypatch.setattr(squad_store, "roles_from_team", spy)
    out = mt.optimise(budget=90.0)
    assert "error" not in out and "direct_reply_error" not in out, out
    text = out["direct_reply"]
    assert text.startswith("**Best 15 from scratch for GW11 on a £90.0m budget: ")
    roles = seen["roles"]
    bench = [e for e, (role, bo) in sorted(roles.items(), key=lambda kv: (kv[1][1] or 0)) if role == "bench"]
    assert f"bench in order: {', '.join(ROW[e][1] for e in bench)}." in text
    xi = [e for e, (role, _bo) in roles.items() if role != "bench"]
    cap = next(e for e, (role, _bo) in roles.items() if role == "CAPTAIN")
    once = sum(Decimal(str(seed.e_points(e, GW))) for e in xi)
    assert f"is predicted {once + Decimal(str(seed.e_points(cap, GW))):.2f} points with the captain's points counted twice, {once:.2f} before that." in text
    cost = sum(ROW[e][4] for e in roles)
    assert cost <= 900 and f"all 15 cost £{cost / 10:.1f}m, which leaves £{(900 - cost) / 10:.1f}m of the £90.0m budget in the bank." in text
    assert [r["player_id"] for r in out["squad"]] and all("bench_order" not in r for r in out["squad"])   # the rows are what they were
