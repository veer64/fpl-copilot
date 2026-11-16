"""Prompt R3b item 2 (16 Nov 2026; USER DECISION): a comparison of players is written by code.

Measured before (eval/reports/r3_answers.md, Set B case 6, 1 of 3): the model wrote the comparison from two totals and slipped
twice -- "the gap reverses very slightly" for a gap that never changed sides, and "that's 80p cheaper" for £0.8m.

K1   two players: each total over the span equals a whole-pool query; the gap is the difference of the two shown totals and
     names who is ahead;
K2   the table has one row a gameweek -- each player's own figure and fixture, a blank said as "no fixture", a double with
     both opponents -- and the "Ahead" column is that gameweek's difference;
K3   the price difference is said in £m ("£0.8m cheaper"), never in pence; level prices are said as level;
K4   whether the gap widens, narrows, reverses or stays level is computed from the first and the last gameweek's figures,
     and the sentence shows both;
K5   three or more players: the same table, columns from the highest total to the lowest, the gameweek's top player named;
K6   the span: `horizon` gameweeks from the next deadline's; none given -> every gameweek the build covers; too many says so;
K7   FPL's flags lead the answer, before the table;
K8   the closing question (USER DECISION), two / several players, with and without a saved squad;
K9   a player the build has no rows for, a bad id, one player twice, too many: no code-built text;
K10  a draft chat's turn gets the result it always had -- the same keys, no text.
Seeded pool (Tests/r3_seed.py); no model, no network."""
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

ROW = {p[0]: p for p in seed.PLAYERS}
ALL = [11, 12, 13, 14, 15, 16]


def _pts(conn, e, g):
    r = seed.q(conn, "SELECT round(e_points::float8::numeric, 2) FROM model_predictions WHERE run_id = 1 AND config = 'baseline' "
                     "AND element = %s AND gw = %s", (e, g))
    return r[0][0] if r else Decimal("0.00")


def _total(conn, e, gws):
    return seed.q(conn, "SELECT round(COALESCE(sum(e_points::float8), 0)::numeric, 2) FROM model_predictions WHERE run_id = 1 "
                        "AND config = 'baseline' AND element = %s AND gw = ANY(%s)", (e, list(gws)))[0][0]


def _cmp(*ids, **kw):
    out = mt.compare_players(player_ids=list(ids), **kw) if len(ids) != 2 else mt.compare_players(ids[0], ids[1], **kw)
    assert "direct_reply_error" not in out, out.get("direct_reply_error")
    return out


def _ordered(conn, ids, gws):
    """The ids from the highest total to the lowest (level totals: the order named), with their totals."""
    tot = {e: _total(conn, e, gws) for e in ids}
    return sorted(ids, key=lambda e: (-tot[e], ids.index(e))), tot


def test_k1_totals_equal_a_pool_query_and_the_gap_names_who_is_ahead(pool_db):
    out = _cmp(107, 115)
    order, tot = _ordered(pool_db, [107, 115], ALL)
    a, b = order
    gap = tot[a] - tot[b]
    assert gap > 0
    assert out["direct_reply"].split("\n")[0] == (
        f"**{ROW[a][1]} against {ROW[b][1]} on predicted points, GW11–16 (6 gameweeks): {ROW[a][1]} {tot[a]:.2f}, {ROW[b][1]} {tot[b]:.2f}. "
        f"{ROW[a][1]} is ahead by {gap:.2f}.**")
    assert out["comparison"]["ahead_player_id"] == a and out["comparison"]["gameweeks"] == ALL
    assert [p["player_id"] for p in out["comparison"]["players"]] == order
    assert [Decimal(str(p["predicted_points_total"])) for p in out["comparison"]["players"]] == [tot[a], tot[b]]
    # the result the tool has always returned still travels (the a / b blocks, the verdict)
    assert out["a"]["player_id"] == 107 and out["b"]["player_id"] == 115 and out["verdict"] in ("a", "b")


def test_k2_one_row_a_gameweek_with_each_players_own_figure_fixture_and_the_difference(pool_db):
    out = _cmp(102, 110)                                                      # an Alpha defender (double in GW12) and a Bravo one (blank in GW13)
    order, tot = _ordered(pool_db, [102, 110], ALL)
    head, body = seed.tables(out["direct_reply"])[0]
    assert head == ["Gameweek"] + [f"{ROW[e][1]} ({ROW[e][3]}, {ROW[e][2]})" for e in order] + ["Ahead"]
    cal = seed.calendar()

    def fx(e, g):
        f = cal.get((ROW[e][3], g))
        return "no fixture" if not f else " + ".join(f"{seed.SHORTS[x['opponent']]} ({'H' if x['home'] else 'A'})" for x in f)

    assert [r[0] for r in body] == [f"GW{g}" for g in ALL] + ["**Total GW11–16**"]
    for r, g in zip(body, ALL):
        pa, pb = _pts(pool_db, order[0], g), _pts(pool_db, order[1], g)
        assert r[1] == f"{pa:.2f} — {fx(order[0], g)}" and r[2] == f"{pb:.2f} — {fx(order[1], g)}"
        d = pa - pb
        assert r[3] == ("level" if d == 0 else f"{ROW[order[0] if d > 0 else order[1]][1]} by {abs(d):.2f}")
    assert body[-1][1:3] == [f"**{tot[order[0]]:.2f}**", f"**{tot[order[1]]:.2f}**"]
    assert body[-1][3] == f"{ROW[order[0]][1]} by {tot[order[0]] - tot[order[1]]:.2f}"
    cells = {(r[0], i): r[i] for r in body for i in (1, 2)}
    col = {e: order.index(e) + 1 for e in order}
    assert cells[("GW13", col[110])] == "0.00 — no fixture"                   # the blank: nothing predicted, said as such
    assert " + " in cells[("GW12", col[102])]                                # the double: both opponents in the cell


@pytest.mark.parametrize("a,b", [(107, 115), (105, 113), (101, 109)])
def test_k3_the_price_difference_is_in_pounds_million_never_pence(pool_db, a, b):
    out = _cmp(a, b)
    order, _tot = _ordered(pool_db, [a, b], ALL)
    pa, pb = ROW[order[0]][4], ROW[order[1]][4]
    each = f"**Price:** {ROW[order[0]][1]} £{pa / 10:.1f}m, {ROW[order[1]][1]} £{pb / 10:.1f}m: "
    if pa == pb:
        assert each + "they cost the same." in out["direct_reply"]
    else:
        cheaper = ROW[order[1] if pa > pb else order[0]][1]
        assert each + f"{cheaper} is £{abs(pa - pb) / 10:.1f}m cheaper." in out["direct_reply"]
    low = out["direct_reply"].lower()
    assert "80p" not in low and "pence" not in low and not __import__("re").search(r"\b\d+p\b", low)


def test_k3b_level_prices_are_said_as_level(pool_db):
    assert ROW[105][4] == ROW[113][4]                                        # the seed's level pair
    assert "they cost the same." in _cmp(105, 113)["direct_reply"]


def test_k4_gap_trend_is_computed_from_the_first_and_the_last_gameweek():
    t = answers.gap_trend
    assert t("0.50", "1.20") == "widens" and t("1.20", "0.50") == "narrows" and t("0.75", "0.75") == "level"
    assert t("0.50", "-0.10") == "reverses" and t("-0.40", "0.30") == "reverses"
    assert t("0.00", "0.30") == "widens" and t("0.30", "0.00") == "narrows" and t("0.00", "0.00") == "level"
    assert t("-0.20", "-0.90") == "widens" and t("-0.90", "-0.20") == "narrows"      # the trailing player's lead, measured the same way
    assert t("0.01", "-0.01") == "reverses"                                  # only a change of sides is a reversal


@pytest.mark.parametrize("a,b", [(107, 115), (102, 110), (121, 129), (104, 112), (131, 139)])
def test_k4b_the_gap_sentence_shows_both_ends_and_the_count_of_gameweeks(pool_db, a, b):
    out = _cmp(a, b)
    order, _tot = _ordered(pool_db, [a, b], ALL)
    lead, other = order
    n1, n2 = ROW[lead][1], ROW[other][1]
    d = {g: _pts(pool_db, lead, g) - _pts(pool_db, other, g) for g in ALL}
    na, nb = sum(1 for g in ALL if d[g] > 0), sum(1 for g in ALL if d[g] < 0)
    nl = 6 - na - nb
    first, last = d[11], d[16]
    if (first > 0 > last) or (first < 0 < last):
        word = "reverses"
    elif abs(first) == abs(last):
        word = "stays level"
    else:
        word = "widens" if abs(last) > abs(first) else "narrows"

    def ahead(x):
        return "level" if x == 0 else f"{n1 if x > 0 else n2} ahead by {abs(x):.2f}"

    want = (f"**The gap ({n1} and {n2}):** {n1} has the higher figure in {na} of the 6 gameweeks, {n2} in {nb}"
            + (f", and they are level in {nl}" if nl else "") + f". From GW11 to GW16 it {word}: {ahead(first)} in GW11, {ahead(last)} in GW16 "
            "(the first and the last gameweek compared).")
    assert want in out["direct_reply"]


def test_k5_three_or_more_players_ordered_by_total(pool_db):
    ids = [123, 107, 115, 131]
    out = _cmp(*ids, horizon=4)
    gws = [11, 12, 13, 14]
    order, tot = _ordered(pool_db, ids, gws)
    text = out["direct_reply"]
    lead = order[0]
    gaps = "; ".join((f"{ROW[lead][1]} and {ROW[e][1]} are level" if tot[lead] == tot[e] else
                      f"{ROW[lead][1]} is ahead of {ROW[e][1]} by {tot[lead] - tot[e]:.2f}") for e in order[1:])
    assert text.split("\n")[0] == ("**4 players on predicted points, GW11–14 (4 gameweeks), highest total first: "
                                   + ", ".join(f"{ROW[e][1]} {tot[e]:.2f}" for e in order) + f". {gaps}.**")
    head, body = seed.tables(text)[0]
    assert head == ["Gameweek"] + [f"{ROW[e][1]} ({ROW[e][3]}, {ROW[e][2]})" for e in order] + ["Most"]
    for r, g in zip(body, gws):
        pts = {e: _pts(pool_db, e, g) for e in order}
        top = [ROW[e][1] for e in order if pts[e] == max(pts.values())]
        assert r[-1] == (top[0] if len(top) == 1 else " and ".join(top) + " level")
    assert body[-1][0] == "**Total GW11–14**" and body[-1][1:-1] == [f"**{tot[e]:.2f}**" for e in order]
    bits = [f"{ROW[lead][1]} £{ROW[lead][4] / 10:.1f}m"]
    for e in order[1:]:
        d = ROW[e][4] - ROW[lead][4]
        rel = "the same price" if d == 0 else f"£{abs(d) / 10:.1f}m {'cheaper' if d < 0 else 'more expensive'} than {ROW[lead][1]}"
        bits.append(f"{ROW[e][1]} £{ROW[e][4] / 10:.1f}m ({rel})")
    assert "**Price:** " + "; ".join(bits) + "." in text
    assert text.count("**The gap (") == 3                                    # each other player against the leader
    assert "direct_reply" in out and "a" not in out and out["comparison"]["gameweeks"] == gws


def test_k6_the_span(pool_db):
    three = _cmp(107, 115, horizon=3)
    assert "GW11–13 (3 gameweeks)" in three["direct_reply"].split("\n")[0] and three["comparison"]["gameweeks"] == [11, 12, 13]
    order, tot = _ordered(pool_db, [107, 115], [11, 12, 13])
    assert f"{ROW[order[0]][1]} {tot[order[0]]:.2f}, {ROW[order[1]][1]} {tot[order[1]]:.2f}" in three["direct_reply"].split("\n")[0]
    one = _cmp(107, 115, horizon=1)
    assert "GW11 (1 gameweek)" in one["direct_reply"].split("\n")[0] and "**The gap (" not in one["direct_reply"]   # one gameweek has no trend
    clipped = _cmp(107, 115, horizon=8)
    assert clipped["direct_reply"].split("\n")[1] == "Predictions exist for GW11–16 only, so this covers 6 gameweeks, not 8."
    assert _cmp(107, 115)["comparison"]["gameweeks"] == ALL                    # no number named: every gameweek the build covers
    bad = mt.compare_players(107, 115, horizon=0)
    assert "error" in bad and "direct_reply" not in bad


def test_k7_fpl_flags_lead_the_answer(pool_db):
    text = _cmp(121, 129)["direct_reply"]                                    # 121 is flagged injured
    lines = text.split("\n")
    flag = next(i for i, ln in enumerate(lines) if ln.startswith("Flags: "))
    assert flag < next(i for i, ln in enumerate(lines) if ln.startswith("| Gameweek"))
    assert lines[flag] == f'Flags: {ROW[121][1]}: Injured — FPL: "Hamstring injury - Expected back 05 Dec" (as of Wed 11 Nov).'
    assert "Neither is flagged by FPL." in _cmp(107, 115)["direct_reply"]
    assert "None of them is flagged by FPL." in _cmp(107, 115, 123)["direct_reply"]


def test_k8_the_closing_question(pool_db, monkeypatch):
    assert _cmp(107, 115)["direct_reply"].split("\n")[-1] == "Want me to check either of them against your squad?"
    assert _cmp(107, 115, 123)["direct_reply"].split("\n")[-1] == "Want me to check any of them against your squad?"
    monkeypatch.setattr(mt, "_has_saved_squad", lambda user_id: False)
    assert _cmp(107, 115)["direct_reply"].split("\n")[-1] == "Want me to compare either of them with anyone else?"
    assert _cmp(107, 115, 123)["direct_reply"].split("\n")[-1] == "Want me to compare any of them with anyone else?"
    text = _cmp(107, 115)["direct_reply"]
    s1, s2 = seed.p_start(107, 11), seed.p_start(115, 11)
    order, _ = _ordered(pool_db, [107, 115], ALL)
    starts = {107: s1, 115: s2}
    assert ("**Chance of starting GW11:** " + ", ".join(f"{ROW[e][1]} {int(Decimal(str(starts[e] * 100)).quantize(Decimal(1), rounding='ROUND_HALF_UP'))}%"
                                                         for e in order) + ".") in text
    assert answers.BONUS_NOTE in text


def test_k9_no_text_without_two_rated_players(pool_db):
    unrated = mt.compare_players(107, 999)                                   # 999 is in players_live, in no build
    assert "direct_reply" not in unrated
    assert "direct_reply" not in mt.compare_players(107, "Haaland") and "error" in mt.compare_players(107, "Haaland")
    assert "error" in mt.compare_players(107, 107) and "error" in mt.compare_players(107)
    many = mt.compare_players(player_ids=[101, 102, 103, 104, 105, 106, 107])
    assert "error" in many and "at most 6 players" in many["error"]
    three = mt.compare_players(player_ids=[107, 115, 999])
    assert "error" in three and "direct_reply" not in three


def test_k10_a_draft_chats_turn_gets_the_result_it_always_had(pool_db, monkeypatch):
    normal = _cmp(107, 115)
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    draft = mt.compare_players(107, 115)
    assert "direct_reply" not in draft and "comparison" not in draft and "note_reply" not in draft
    assert set(draft) == set(normal) - {"direct_reply", "comparison", "note_reply", "run_id"} or set(draft) == set(normal) - {"direct_reply", "comparison", "note_reply"}
    assert draft["a"] == normal["a"] and draft["b"] == normal["b"] and draft["verdict"] == normal["verdict"]
    with pytest.raises(TypeError):
        mt.compare_players(107)                                              # a draft chat's schema requires both ids, as before
