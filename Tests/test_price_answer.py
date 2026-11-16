"""Prompt R3 (16 Nov 2026; USER DECISION "go"): a squad's price moves are written by code.

Measured before (eval/reports/r3_evidence_digest.md, R1's case B7, 0 of 3): FPL's figure for Foden, +50.6, was written "50.6%
toward next fall" (M18); Guéhi's -64.9 was "the most negative of your squad" beside Mbeumo's -76.5 (M6); "Gabriel and Barry have
risen but their counter has reset, so you'd sell each at purchase price" (M19: it is the selling rule's rounding); and "none of
these rises put any extra money in your pocket yet" when Isak's had (M25).

R1  every row's words carry the sign of FPL's own figure: above zero "toward a rise", below zero "toward a fall", zero neither;
R2  the highest and the lowest figure named are the highest and the lowest, by brute force; the table is in that order;
R3  every "sells for" and every worked selling-rule line equals squad_state.sell_price (the one implementation);
R4  each move inside the window is listed with the sell price before and after it;
R5  the two what-if columns are sell_price at one tenth more and one tenth less;
R6  the figure is attributed to FPL and never turned into a forecast; the window's two readings are stated;
R7  no squad (General mode), include_squad=false, an error and the draft chat give the tool's usual result, never a reply;
R8  the closing question (USER DECISION).
Synthetic price snapshots in a temporary folder; no database, no model, no network."""
import gzip
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import model_tools as mt                                    # noqa: E402
import prices_tool as pt                                    # noqa: E402
from r3_seed import tables                                  # noqa: E402
from squad_state import sell_price                          # noqa: E402

#        element: (name, position, bought, price then, price now, FPL's progress figure)
SQUAD = {1: ("Foden", "MID", 69, 68, 68, 50.6), 2: ("Barry", "FWD", 56, 56, 57, 43.6), 3: ("Gakpo", "MID", 72, 71, 71, 32.3),
         4: ("Haaland", "FWD", 156, 158, 158, 17.7), 5: ("Gabriel", "DEF", 80, 80, 81, 15.8), 6: ("Lindelof", "DEF", 45, 45, 45, 14.5),
         7: ("Isak", "FWD", 91, 92, 93, 8.1), 8: ("Di Gregorio", "GK", 45, 45, 45, 0.0), 9: ("Collins", "DEF", 54, 54, 54, -8.4),
         10: ("Sangare", "MID", 49, 48, 47, -43.0), 11: ("Bijol", "DEF", 50, 50, 50, -59.5), 12: ("Grimes", "MID", 49, 48, 48, -62.4),
         13: ("Gillespie", "GK", 45, 45, 45, -62.6), 14: ("Guehi", "DEF", 60, 60, 60, -64.9), 15: ("Mbeumo", "MID", 79, 79, 79, -76.5)}
DOC = {"players": [{"element": e, "name": v[0], "position": v[1], "purchase_price": v[2]} for e, v in SQUAD.items()], "bank": 3}


def _snapshot(path, col):
    doc = {"elements": [{"id": e, "first_name": "", "second_name": v[0], "web_name": v[0], "now_cost": v[col],
                         "cost_change_start": 0, "cost_change_start_fall": 0, "price_change_percent": v[5]} for e, v in SQUAD.items()]
                       + [{"id": 99, "first_name": "Some", "second_name": "Riser", "web_name": "Riser", "now_cost": 61 if col == 4 else 60,
                           "cost_change_start": 1, "cost_change_start_fall": 0, "price_change_percent": 12.0}]}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)


@pytest.fixture
def snaps(tmp_path, monkeypatch):
    _snapshot(tmp_path / "bootstrap_20261104T163706Z.json.gz", 3)
    _snapshot(tmp_path / "bootstrap_20261108T110000Z.json.gz", 3)
    _snapshot(tmp_path / "bootstrap_20261111T163706Z.json.gz", 4)
    monkeypatch.setattr(pt, "BOOTSTRAP_DIR", tmp_path)
    monkeypatch.setattr(mt, "_web_names", lambda: {})
    monkeypatch.setattr(mt, "_squad_owner", lambda user_id: user_id)
    import squad_store
    monkeypatch.setattr(squad_store, "read_active", lambda user_id=None, conn=None: {"squad_json": DOC})
    return tmp_path


def _reply(**kw):
    out = mt.get_price_movements(user_id=4242, **kw)
    assert "direct_reply_error" not in out, out.get("direct_reply_error")
    return out


def _table(text):
    head, rows = tables(text)[0]
    return head, {r[0]: r for r in rows}, [r[0] for r in rows]


def test_r1_every_rows_words_carry_the_sign_of_fpls_figure(snaps):
    head, rows, _ = _table(_reply()["direct_reply"])
    assert head == ["Player", "Pos", "FPL's progress figure", "Bought at", "Price now", "Sells for now", "Moved in this window",
                    "Sells for after one more rise", "Sells for after one fall"]
    for e, (name, pos, _b, _t, _n, pct) in SQUAD.items():
        cell = rows[name][2]
        if pct > 0:
            assert cell == f"{pct:.1f}% toward a rise"
        elif pct < 0:
            assert cell == f"{abs(pct):.1f}% toward a fall"
        else:
            assert cell == "0.0% (no progress either way)"
        assert rows[name][1] == pos
    assert rows["Foden"][2] == "50.6% toward a rise"                         # the R1 slip: "50.6% toward next fall"
    assert answers.progress_words(None) == "no figure" and answers.progress_words(-227.3) == "227.3% toward a fall"


def test_r2_the_highest_and_lowest_named_are_the_highest_and_lowest(snaps):
    text = _reply()["direct_reply"]
    _, _, order = _table(text)
    by_figure = [v[0] for v in sorted(SQUAD.values(), key=lambda v: -v[5])]
    assert order == by_figure
    top = max(SQUAD.values(), key=lambda v: v[5])
    low = min(SQUAD.values(), key=lambda v: v[5])
    assert (f"Listed from the highest figure to the lowest. Highest: {top[0]}, {top[5]:.1f}% toward a rise. "
            f"Lowest: {low[0]}, {abs(low[5]):.1f}% toward a fall.") in text
    assert low[0] == "Mbeumo" and "Lowest: Guehi" not in text                # the R1 slip: Guéhi called "the most negative"


def test_r3_sells_for_and_every_worked_line_equal_the_one_selling_rule(snaps):
    text = _reply()["direct_reply"]
    _, rows, _ = _table(text)
    for name, _pos, bought, _then, now, _pct in SQUAD.values():
        assert rows[name][3] == f"£{bought / 10:.1f}m" and rows[name][4] == f"£{now / 10:.1f}m"
        assert rows[name][5] == f"£{sell_price(bought, now) / 10:.1f}m", name
    worked = [ln for ln in text.split("\n") if ln.startswith("- ") and "bought at" in ln]
    changed = [v for v in SQUAD.values() if v[4] != v[2]]
    assert len(worked) == len(changed) == 8
    for name, _pos, bought, _then, now, _pct in changed:
        line = next(ln for ln in worked if ln.startswith(f"- {name}:"))
        sells = sell_price(bought, now)
        if now > bought:
            keep = sells - bought
            kept = f"£{keep / 10:.1f}m" if keep else "nothing yet"
            assert line == (f"- {name}: bought at £{bought / 10:.1f}m, now £{now / 10:.1f}m. You keep half of a rise, rounded down to "
                            f"£0.1m: half of £{(now - bought) / 10:.1f}m gives {kept}, so he sells for £{sells / 10:.1f}m.")
        else:
            assert line == (f"- {name}: bought at £{bought / 10:.1f}m, now £{now / 10:.1f}m. A fall is yours in full, so he sells for "
                            f"£{sells / 10:.1f}m.")
    assert "half of £0.1m gives nothing yet, so he sells for £8.0m." in text  # Gabriel: the rule's rounding, not "his counter"
    assert "counter" not in text.lower()


def test_r4_each_move_in_the_window_with_the_sell_price_before_and_after(snaps):
    text = _reply()["direct_reply"]
    _, rows, _ = _table(text)
    moved = [ln for ln in text.split("\n") if ln.startswith("- ") and (" rose from " in ln or " fell from " in ln)]
    want = {v[0]: v for v in SQUAD.values() if v[3] != v[4]}
    assert len(moved) == len(want) == 4
    for name, (_n, _pos, bought, then, now, _pct) in want.items():
        line = next(ln for ln in moved if ln.startswith(f"- {name} "))
        before, after = sell_price(bought, then), sell_price(bought, now)
        tail = f"stayed at £{after / 10:.1f}m." if before == after else f"went from £{before / 10:.1f}m to £{after / 10:.1f}m."
        assert line == f"- {name} {'rose' if now > then else 'fell'} from £{then / 10:.1f}m to £{now / 10:.1f}m: his sell price {tail}"
        assert rows[name][6] == ("+£0.1m" if now > then else "−£0.1m")
    assert "- Isak rose from £9.2m to £9.3m: his sell price went from £9.1m to £9.2m." in text      # the R1 slip (M25)
    assert "- Gabriel rose from £8.0m to £8.1m: his sell price stayed at £8.0m." in text
    assert all(rows[v[0]][6] == "no change" for v in SQUAD.values() if v[3] == v[4])


def test_r5_the_what_if_columns_are_the_rule_one_tenth_either_way(snaps):
    _, rows, _ = _table(_reply()["direct_reply"])
    for name, _pos, bought, _then, now, _pct in SQUAD.values():
        sells = sell_price(bought, now)
        for col, alt in ((7, sell_price(bought, now + 1)), (8, sell_price(bought, now - 1))):
            d = alt - sells
            delta = "no change" if d == 0 else (f"+£{d / 10:.1f}m" if d > 0 else f"−£{abs(d) / 10:.1f}m")
            assert rows[name][col] == f"£{alt / 10:.1f}m ({delta})", (name, col)
    assert rows["Isak"][7] == "£9.2m (no change)" and rows["Gabriel"][7] == "£8.1m (+£0.1m)" and rows["Foden"][8] == "£6.7m (−£0.1m)"


def test_r6_the_figure_is_fpls_and_the_window_is_stated(snaps):
    out = _reply()
    lines = out["direct_reply"].split("\n")
    assert lines[0] == "**Your 15 players: FPL's price-change progress, and what each sells for.**"
    assert lines[1] == ('Prices seen from Wed 4 Nov 2026 16:37 UTC to Wed 11 Nov 2026 16:37 UTC (3 price readings; "no change" means no '
                        "net change between those two readings).")
    assert ("The figure is FPL's own published progress toward a price change, not ours; it says what has happened so far and cannot "
            "say whether a price will change next.") in out["direct_reply"]
    low = out["direct_reply"].lower()
    for forecast in ("will rise", "will fall", "about to", "likely to", "expected to", "tonight"):
        assert forecast not in low
    assert out["fpl_price_change_percent"]["sign"] == mt.PRICE_FIGURE_SIGN and out["my_squad"]["bank"] == 0.3


def test_r7_no_squad_market_only_an_error_and_the_draft_chat_give_no_reply(snaps, monkeypatch):
    market = mt.get_price_movements(include_squad=False)
    assert "direct_reply" not in market and "my_squad" not in market and market["n_moved"] == 5
    assert market["fpl_price_change_percent"]["sign"] == mt.PRICE_FIGURE_SIGN         # General mode reads which way it points
    import squad_store

    def no_squad(user_id=None, conn=None):
        raise squad_store.NoSquadError("no active squad version")
    monkeypatch.setattr(squad_store, "read_active", no_squad)
    general = mt.get_price_movements()
    assert "direct_reply" not in general and "my_squad_unavailable" in general
    assert mt._with_price_answer({"error": "no price snapshots"}, DOC, 7) == {"error": "no price snapshots"}
    broken = mt._with_price_answer({"my_squad": {"players": [{"player_id": 1}]}, "observation": {}}, DOC, 7)
    assert "direct_reply" not in broken and "direct_reply_error" in broken


def test_r7b_a_player_the_latest_reading_has_no_price_for(snaps):
    players = [{"element": 1, "name": "A", "position": "MID", "bought": 50, "now": None, "then": None, "pct": None},
               {"element": 2, "name": "B", "position": "DEF", "bought": 45, "now": 46, "then": None, "pct": 3.0}]
    text = answers.prices(players, sell_price, seen_from="Mon", seen_to="Tue", readings=1)
    _, rows, order = _table(text)
    assert order == ["B", "A"] and rows["A"][2:] == ["no figure", "£5.0m", "not known", "not known", "—", "—", "—"]
    assert rows["B"][6] == "—" and "(1 price reading;" in text and "Highest: B, 3.0% toward a rise. Lowest: B, 3.0% toward a rise." in text


def test_r8_the_closing_question(snaps):
    lines = _reply()["direct_reply"].split("\n")
    assert lines[-1] == "Want me to look at a replacement for any of them?" == answers.PRICE_FOLLOW_UP and lines[-2] == ""
