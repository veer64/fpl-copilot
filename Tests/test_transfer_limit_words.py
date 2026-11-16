"""Prompt R3d item 1 (16 Nov 2026; USER DECISION): a transfer limit is applied only when the user's OWN message names a number
of transfers -- code checks the model's reading of the user's words, as the confirm gate does.

Measured before (eval/reports/r3c_answers.md, Set B case 2, 3 of 3): "Using only my free transfers, what moves should I make
across the next three gameweeks?" -- the model passed max_transfers=3 (the three gameweeks), the plan stopped at 3 moves with 5
free transfers available, and the code-built text said "Using at most 3 transfers across the whole plan, as you asked".

W1  the PHRASING TABLE (written before the code): for each message, the numbers of transfers it names -- numbers of gameweeks,
    prices, gameweek labels, dates, squad counts and points hits never count;
W2  the check: a limit named in the message is applied (the model's own value when it matches, the user's number when it does
    not, the user's number when the model passed none); a limit the message does not name is ignored, with a note for the trace;
    outside a chat turn (no message to check) the argument is honoured as before;
W3  propose_transfers passes the checked limit to the planner and carries the check as `limit_check` (never shown to the user);
W4  no code-built template says "as you asked" / "you asked for" except the plan's limit line, which is reached only with a
    limit the user's words named; the forced-player warning no longer says it.
No model, no network; the planner is stopped by a spy (W3)."""
import inspect
import re
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

# (message, the numbers of transfers it names)
PHRASINGS = [
    # it names a number of transfers
    ("What's the best squad I can reach from here with two transfers?", [2]),
    ("Make two transfers for me this week.", [2]),
    ("Make 2 transfers", [2]),
    ("I only want to make one transfer. What's the best move?", [1]),
    ("What's the best single transfer for this week?", [1]),
    ("Give me a single move for GW11", [1]),
    ("Which one move should I make?", [1]),
    ("Plan three swaps over the next few weeks", [3]),
    ("make 2 changes to my team", [2]),
    ("No more than three moves, please", [3]),
    ("At most 2 transfers over the next 3 gameweeks", [2]),
    ("Use my two free transfers", [2]),
    ("I have 3 free transfers, what should I do?", [3]),
    ("A two-transfer plan please", [2]),
    ("1 transfer only", [1]),
    ("Four moves across the next six gameweeks", [4]),
    ("Make two changes over the next 3 weeks and take no hits", [2]),
    ("Two transfers now and one transfer next week", [2, 1]),
    ("Make 0 transfers this week and show me what that scores", [0]),
    # it names no number of transfers
    ("Using only my free transfers, what moves should I make across the next three gameweeks?", []),
    ("What transfers should I make over the next five gameweeks?", []),
    ("Plan my next 3 gameweeks", []),
    ("What's the best squad I could build with £100m?", []),
    ("Who should I bring in for GW11?", []),
    ("Show me 15 players I could pick", []),
    ("What transfers should I make with no hits?", []),
    ("Plan my transfers from GW12 to GW14", []),
    ("Is a 4-point hit worth it for Haaland?", []),
    ("What transfers should I make before the deadline on 21 November?", []),
    ("What transfers should I make?", []),
    ("Should I roll my free transfer?", []),
    ("Swap Bijol for Konsa.", []),
    ("Two of my players are injured, what transfers should I make?", []),
    ("Which defenders under £5.0m are the best value over the next 5 gameweeks?", []),
    ("Top 8 forwards for the next 4 gameweeks", []),
]


@pytest.mark.parametrize("message,named", PHRASINGS, ids=[f"{i:02d}" for i in range(1, len(PHRASINGS) + 1)])
def test_w1_the_phrasing_table(message, named):
    assert answers.transfers_named(message) == named


def test_w1b_the_table_is_at_least_25_phrasings_both_ways():
    assert len(PHRASINGS) >= 25 and sum(1 for _m, n in PHRASINGS if n) >= 10 and sum(1 for _m, n in PHRASINGS if not n) >= 10


@pytest.mark.parametrize("message,asked,applied,why", [
    ("Using only my free transfers, what moves should I make across the next three gameweeks?", 3, None, "not named"),
    ("What's the best squad I can reach from here with two transfers?", 2, 2, "named"),
    ("What's the best squad I can reach from here with two transfers?", None, 2, "named, not passed"),
    ("What's the best squad I can reach from here with two transfers?", 3, 2, "corrected"),
    ("Two transfers now and one transfer next week", 3, 3, "named"),            # the total of the two
    ("Two transfers now and one transfer next week", 2, 2, "named"),
    ("Two transfers now and one transfer next week", 5, None, "not named"),
    ("What transfers should I make?", None, None, None),                        # nothing asked, nothing named: no note
    ("Make 0 transfers this week and show me what that scores", 0, 0, "named"),
])
def test_w2_the_check(message, asked, applied, why):
    got, note = answers.verified_transfer_limit(message, asked)
    assert got == applied
    if why is None:
        assert note is None
    else:
        assert note["why"] == why and note["asked"] == asked and note["applied"] == applied
        assert note["named"] == answers.transfers_named(message)


def test_w2b_outside_a_chat_turn_the_argument_is_honoured_as_before():
    assert turn_context.user_message() is None
    assert mt._checked_transfer_limit(3, "chat") == (3, None)                  # no turn open: nothing to check against
    turn_context.begin("t" * 32, user_message="Plan my next 3 gameweeks")
    try:
        assert turn_context.user_message() == "Plan my next 3 gameweeks"
        assert mt._checked_transfer_limit(3, "chat")[0] is None
        assert mt._checked_transfer_limit(3, "proof") == (3, None)             # a maintainer's run is never checked
    finally:
        turn_context.end()
    assert turn_context.user_message() is None                                 # closed with the turn


def _stop_planner(monkeypatch):
    import pandas as pd
    import simulator
    import squad_store
    from test_optimize import make_random_pool
    from test_transfer_mip import a_squad
    pool = make_random_pool(3)
    for c, v in (("p_play_any", 0.9), ("p_60plus", 0.8)):
        pool[c] = v
    squad = a_squad(pool)
    by_pos = {pos: [e for e in squad if pool.loc[pool["element"] == e, "position"].iloc[0] == pos] for pos in ("GK", "DEF", "MID", "FWD")}
    bench = [by_pos["GK"][1], by_pos["DEF"][4], by_pos["MID"][4], by_pos["FWD"][2]]
    rows = []
    for e in squad:
        r = pool[pool["element"] == e].iloc[0]
        role = "bench" if e in bench else "CAPTAIN" if e == by_pos["FWD"][0] else "VICE" if e == by_pos["MID"][0] else "start"
        rows.append({"element": int(e), "name": r["name"], "position": r["position"], "team": r["team"], "purchase_price": int(r["value"]),
                     "role": role, "bench_order": bench.index(e) + 1 if e in bench else None})
    doc = squad_store.document(pd.DataFrame(rows), 20, 1, 0, "2026-27", {"kind": "test"})
    record = {"squad_json": doc, "season": "2026-27", "gw": 11, "version_id": 7, "created_at": "2026-11-10T00:00:00Z"}
    df = pd.concat([pool.assign(gw=g, cutoff=11) for g in (11, 12, 13)], ignore_index=True)
    live = [{"element": int(r.element), "name": r.name, "position": r.position, "team": r.team, "price_tenths": int(r.value), "updated_at": None}
            for r in pool.itertuples()]
    monkeypatch.setattr(mt, "_draft_turn", lambda: None)
    monkeypatch.setattr(mt, "_squad_owner", lambda user_id: user_id)
    monkeypatch.setattr(mt, "_read_active", lambda user_id: record)
    monkeypatch.setattr(mt, "_current_gw", lambda: 11)
    monkeypatch.setattr(mt, "_load_frame", lambda: (df, 11, None))
    monkeypatch.setattr(mt.squad_store, "free_transfers_at", lambda rec, gw: 5)
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [r for r in live if r["element"] in set(params[0])])
    seen = {}

    def stop(*a, **kw):
        seen.update(kw)
        raise RuntimeError("stopped by the test")
    monkeypatch.setattr(simulator, "decide_gameweek_mip", stop)
    return seen


@pytest.mark.parametrize("message,asked,want", [
    ("Using only my free transfers, what moves should I make across the next three gameweeks?", 3, None),
    ("Make two transfers for me this week.", 2, 2),
    ("Make two transfers for me this week.", None, 2),
    ("What transfers should I make over the next five gameweeks?", 5, None),
])
def test_w3_propose_transfers_passes_the_checked_limit(monkeypatch, message, asked, want):
    seen = _stop_planner(monkeypatch)
    turn_context.begin("r3d" + "t" * 29, user_message=message)
    try:
        out = mt.propose_transfers(horizon=3, max_transfers=asked, user_id=424242)
    finally:
        turn_context.end()
    assert seen["max_transfers"] == want
    assert "error" in out and ("a limit of" in out["error"]) == (want is not None)


def test_w4_no_template_claims_the_users_words_unchecked():
    src = inspect.getsource(answers) + inspect.getsource(mt)
    hits = [m.start() for m in re.finditer(r"as you asked|you asked for|because you forced", src)]
    lines = [src[src.rfind("\n", 0, h) + 1:src.find("\n", h)].strip() for h in hits]
    assert all("across the whole plan, as you asked" in ln for ln in lines), lines
    assert len(lines) == 2                                                     # the two forms of the plan's limit line
    flags = {379: {"name": "Alexander Isak", "status": "i", "status_word": "injured", "chance": 0,
                   "chance_words": "chance of playing in GW11: 0%, FPL as of Sun 15 Nov 2026", "news": "Knee injury", "as_of": None}}
    w = mt.forced_availability_warning([379], flags)
    assert w == ("Alexander Isak is in the squad as a forced pick, but FPL lists him as injured: chance of playing in GW11: 0%, FPL as "
                 "of Sun 15 Nov 2026 (FPL's note: Knee injury). The squad is built with him in it.")
