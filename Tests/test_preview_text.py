"""Prompt R3c item 2 (16 Nov 2026; USER DECISION): the text sent with a squad-change preview is written by code.

Measured before (eval/reports/r3b_answers.md, Set B case 9 run 1): the model wrote "Free transfers: 5 used → 1 used, 4 remaining"
beside a correct card. The card, the ticket and the confirm gate are unchanged; only the text beside the card is code-built now.

V1  through the real set_my_squad preview: who goes out and in, bought at / price now / sells for, what he costs -- each equal
    to the ticket's own change (change_args) and the squad state (purchase prices, today's prices, FPL's sell rule);
V2  the bank before and after, and the free transfers in words: "This uses 1 of your 5 free transfers: 4 left, no hit" --
    never "5 used → 1 used"; with no free transfer, or more transfers than free ones, the hit in points;
V3  the predicted gain over the span against keeping the outgoing player equals a whole-pool query;
V4  it ends with the confirm gate's own question; the result keeps its ticket, its change and its card fields;
V5  a confirmed write, a refusal, a preview that moves no player, and a draft chat's preview carry no code-built text.
Seeded pool (Tests/r3_seed.py) plus a squad saved in the same test database; no model, no network."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import confirm_gate                                         # noqa: E402
import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
import squad_previews                                       # noqa: E402
import squad_store                                          # noqa: E402
import turn_context                                         # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)
from squad_state import sell_price                          # noqa: E402

ROW = {p[0]: p for p in seed.PLAYERS}
UID = 10951
XI = [101, 102, 110, 118, 126, 105, 113, 121, 129, 123, 131]   # a legal fifteen: 2 GK, 5 DEF, 5 MID, 3 FWD, three a club
BENCH = [109, 134, 137, 139]
BOUGHT = {105: ROW[105][4] - 3, 131: ROW[131][4] + 2}       # one has risen since he was bought, one has fallen


def _doc(free_transfers=1, bank=12):
    rows = []
    for e in XI + BENCH:
        role = "CAPTAIN" if e == 131 else "VICE" if e == 105 else "bench" if e in BENCH else "start"
        rows.append({"element": e, "name": ROW[e][1], "position": ROW[e][2], "team": ROW[e][3],
                     "purchase_price": BOUGHT.get(e, ROW[e][4]), "role": role, "bench_order": BENCH.index(e) + 1 if e in BENCH else None})
    import pandas as pd
    return squad_store.document(pd.DataFrame(rows), bank, free_transfers, 0, "2026-27", {"kind": "test"})


@pytest.fixture
def sq(pool_db, monkeypatch):
    """A saved squad for a test user in the seeded database, at GW11 (the next deadline)."""
    import db_write
    c = db_write.connect()
    squad_store.ensure_schema(c)
    squad_previews.ensure_schema(c)
    c.commit()
    c.close()
    _clear()
    monkeypatch.setattr(mt, "_squad_owner", lambda user_id: user_id)
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)

    def save(**kw):
        conn = db_write.connect()
        try:
            squad_store.write_version(None, _doc(**kw), 11, "R3c test squad", True, conn=conn, user_id=UID)
        finally:
            conn.close()
        return squad_store.read_active(UID)
    yield save
    _clear()


def _clear():
    """The test user's previews and squad versions in the TEST database, removed the way account deletion removes them
    (squad_versions is append-only by trigger; a delete is admitted only with fpl.account_delete and this transaction's id
    set in the transaction)."""
    import db_write
    c = db_write.connect()
    try:
        with c.cursor() as cur:
            cur.execute("SET LOCAL fpl.account_delete = 'on'")
            cur.execute("SELECT set_config('fpl.account_delete_txn', txid_current()::text, true)")
            cur.execute("DELETE FROM squad_previews WHERE user_id = %s", (UID,))
            cur.execute("DELETE FROM squad_versions WHERE user_id = %s", (UID,))
        c.commit()
    finally:
        c.close()


def _preview(swaps, captain=131, vice=105):
    ids = [dict(swaps).get(e, e) for e in XI + BENCH]
    bench = [dict(swaps).get(e, e) for e in BENCH]
    turn_context.begin("r3c" + "t" * 29, thread_id="th_r3c")
    try:
        return mt.set_my_squad(ids, dict(swaps).get(captain, captain), dict(swaps).get(vice, vice), bench, confirm=False, user_id=UID)
    finally:
        turn_context.end()


def _ticket(conn):
    r = seed.q(conn, "SELECT change_args FROM squad_previews WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (UID,))[0][0]
    return json.loads(r) if isinstance(r, (str, bytes)) else r


def _pts(conn, e, gws):
    return seed.q(conn, "SELECT round(COALESCE(sum(e_points::float8), 0)::numeric, 2) FROM model_predictions WHERE run_id = 1 "
                        "AND config = 'baseline' AND element = %s AND gw = ANY(%s)", (e, list(gws)))[0][0]


def test_v1_v3_every_figure_against_the_ticket_and_the_squad_state(sq, pool_db):
    active = sq(free_transfers=5)
    out = _preview([(105, 145)])                                                 # MID 105 (Alpha) out, MID 145 (Foxtrot) in
    assert out.get("preview") is True and "direct_reply" in out, out
    text = out["direct_reply"]
    args = _ticket(pool_db)
    doc_ids = {int(p["element"]) for p in active["squad_json"]["players"]}
    outs, ins = sorted(doc_ids - set(args["player_ids"])), sorted(set(args["player_ids"]) - doc_ids)
    assert (outs, ins) == ([105], [145])
    head, rows = seed.tables(text)[0]
    assert head == ["Out", "Bought at", "Price now", "Sells for", "In", "Costs", "Predicted gain GW11–16 against keeping him"]
    (r,) = rows
    bought, now = BOUGHT[105], ROW[105][4]
    assert r[0] == f"{ROW[105][1]} (Alpha, MID)" and r[1] == f"£{bought / 10:.1f}m" and r[2] == f"£{now / 10:.1f}m"
    assert r[3] == f"£{sell_price(bought, now) / 10:.1f}m"
    assert r[4] == f"{ROW[145][1]} (Foxtrot, MID)" and r[5] == f"£{ROW[145][4] / 10:.1f}m"
    gws = [11, 12, 13, 14, 15, 16]
    a, b = _pts(pool_db, 145, gws), _pts(pool_db, 105, gws)
    sign = "+" if a > b else "−" if a < b else ""
    assert r[6] == f"{sign}{abs(a - b):.2f} ({a:.2f} against {b:.2f})"
    assert text.split("\n")[0] == f"**Preview: {ROW[105][1]} out, {ROW[145][1]} in.**"


def test_v2_the_bank_and_free_transfers_in_words(sq, pool_db):
    sq(free_transfers=5, bank=12)
    out = _preview([(105, 145)])
    ch = out["change"]
    text = out["direct_reply"]
    sold, cost = sell_price(BOUGHT[105], ROW[105][4]), ROW[145][4]
    assert (f"**Bank:** £1.2m before, £{(12 + sold - cost) / 10:.1f}m after (£{sold / 10:.1f}m from sales, £{cost / 10:.1f}m on "
            "purchases).") in text
    assert float(ch["bank_after"]) == round((12 + sold - cost) / 10, 1)
    assert "**Free transfers:** This uses 1 of your 5 free transfers: 4 left, no hit." in text
    assert "used →" not in text and "5 used" not in text


@pytest.mark.parametrize("ft,swaps,want", [
    (0, [(105, 145)], "You have no free transfers, so this costs a 4-point hit (1 transfer beyond your free ones)."),
    (1, [(105, 145), (102, 142)], "This uses your 1 free transfer: 0 left, and costs a 4-point hit (1 transfer beyond your free ones)."),
    (2, [(105, 145), (102, 142), (110, 143)], "This uses all 2 of your free transfers: 0 left, and costs a 4-point hit (1 transfer beyond "
                                              "your free ones)."),
    (1, [(105, 145)], "This uses 1 of your 1 free transfer: 0 left, no hit."),
])
def test_v2b_hits_said_in_points(sq, pool_db, ft, swaps, want):
    sq(free_transfers=ft, bank=60)
    out = _preview(swaps)
    assert out["change"]["hits"] * 4 == out["change"]["hit_cost_points"]
    assert f"**Free transfers:** {want}" in out["direct_reply"]


def test_v4_the_closing_question_and_the_result_keeps_its_ticket_and_card_fields(sq, pool_db):
    sq(free_transfers=5)
    out = _preview([(105, 145)])
    assert out["direct_reply"].split("\n")[-1] == "Shall I make this change? Yes or No" == confirm_gate.ASK_REPLY == answers.PREVIEW_QUESTION
    assert out["preview_ticket"] and out["change"]["transfers"] and out["preview"] is True and out["committed"] is False
    assert "Nothing is saved until you say yes." in out["direct_reply"]


def test_v4b_a_captain_change_in_the_same_preview_is_said(sq, pool_db):
    sq(free_transfers=5)
    out = _preview([(131, 147)], captain=147, vice=105)                          # the captain is sold; the incoming forward takes it
    assert f"Also in this change: the armband moves from {ROW[131][1]} to {ROW[147][1]}." in out["direct_reply"]


def test_v5_no_text_for_a_write_a_refusal_a_role_change_or_a_draft(sq, pool_db, monkeypatch):
    sq(free_transfers=5)
    assert "direct_reply" not in _preview([], captain=105, vice=131)            # roles only: no transfer
    refused = _preview([(105, 147)])                                             # a midfielder out, a forward in: an illegal shape
    assert "error" in refused and "direct_reply" not in refused
    assert "direct_reply" not in mt.set_my_squad(XI + BENCH, 131, 105, BENCH, confirm=True, user_id=UID)
    import draft_tools
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    monkeypatch.setattr(draft_tools, "set_my_squad", lambda d, **kw: {"preview": True, "draft": True, "change": {"transfers": [1]}})
    assert "direct_reply" not in _preview([(105, 145)])
