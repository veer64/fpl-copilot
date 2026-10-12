"""Judge Part C (2026-10-12): the fixes the calibration review asked for.

J1 the shared block carries the SETUP turn's tool calls and outputs, labelled as earlier-turn evidence.
J2 the M3b verifier: numbers inside identifiers / GW labels / word numbers count as present in a quote;
   "..." quotes are checked as ordered segments of one source; approximate claims match within
   max(0.5, 5%); a COUNT item is checked by code (len == number, every listed thing quoted); DERIVED
   inputs may be well-known constants without a quote and nest; extraction skips numbers that only
   echo the user's words, table row numbers and bench numbering; chunks of 8, 8192 tokens, 300 s.
J3 definitions: M1's allowed and jargon lists, M3a's club / reason claims, M4's narrower trigger
   (predicted points / recommendation / captaincy / lock of the flagged player), M5's fixtures reminder.
J5 tool outputs with np.float64(...) and datetime.datetime(...) reprs parse.
No network: llm.complete is mocked.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
from judge import metrics as M                             # noqa: E402
from judge import number_claims as N                       # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

CARD = {"player_id": 411, "name": "Erling Haaland", "team": "Man City", "position": "FWD", "status": "a", "chance": 100,
        "price": 15.6, "prediction": {"predictions": [{"gw": 7, "e_points": 9.24, "p_start": 0.95, "p_60plus": 0.88}]}}
XI = {"gw": 7, "predicted_xi_points": 57.8, "xi": [{"player_id": 411, "name": "Erling Haaland", "team": "Man City", "position": "FWD",
                                                     "e_points": 9.24, "p_play_any": 0.39}]}


def _record(reply, calls=None, question="How is Haaland looking?", qid="get_player_card:1", sheet="get_player_card",
            setup=None, setup_calls=None):
    calls = calls if calls is not None else [{"tool": "get_player_card", "args": {"player_id": 411}, "error": None, "output": str(CARD)}]
    ctx = "CONTEXT BLOCK\n- Now: Saturday 2026-10-11 10:00 UTC.\n- Gameweeks: GW6 in progress; next deadline GW7."
    turns = []
    if setup:
        turns.append({"kind": "setup", "message": setup, "reply": "Here is your best XI ... Haaland captain.",
                      "calls": setup_calls or [], "context_block": ctx})
    turns.append({"kind": "question", "message": question, "reply": reply, "calls": calls, "context_block": ctx})
    return {"id": qid, "sheet": sheet, "question": question, "setup": setup, "turns": turns, "calls": calls,
            "rendered_reply": reply, "raw_reply": reply, "result": "PASS"}


# ------------------------------------------------------------------ J1
def test_the_setup_turns_tool_outputs_are_in_the_shared_block_as_earlier_evidence():
    r = _record("Done: Haaland is your captain.", setup="Who should I start this week?",
                setup_calls=[{"tool": "get_my_xi", "args": {}, "error": None, "output": str(XI)}])
    p = RJ.build_prompt(r, "M2")
    assert "<setup_turn>" in p and "turn=\"setup (earlier turn)\"" in p
    assert str(XI) in p and p.index('turn="setup') < p.index("<tool_result name=\"get_player_card\"")
    assert "Who should I start this week?" in p


# ------------------------------------------------------------------ J2a: numbers in the quote
@pytest.mark.parametrize("number,decimals,quote,ok", [
    (60, 0, "'p_60plus': 0.88", True),                 # a digit inside an identifier
    (7, 0, "next deadline GW7", True),                 # a GW label
    (5, 0, "five extra transfers", True),              # a word number
    (6, 0, "a six-week plan", True),                   # hyphenated word number
    (2, 0, "the captain scores double", True),         # double = 2
    (2, 0, "counted twice", True),
    (3, 0, "triple captain", True),
    (0.5, 1, "half of the rise", True),
    (8, 0, "'p_60plus': 0.88", False),
])
def test_numbers_hidden_in_identifiers_labels_and_words_count(number, decimals, quote, ok):
    assert N.number_in_quote(number, decimals, quote, False) is ok


# ------------------------------------------------------------------ J2b: ellipsis quotes
def test_a_quote_with_an_ellipsis_is_checked_as_ordered_segments_of_one_source():
    src = "{'squad': [{'name': 'Erling Haaland', 'price': 15.6}, {'name': 'Alexander Isak', 'price': 9.1}]}"
    assert N.quote_found("'price': 15.6 ... 'price': 9.1", [src]) is True
    assert N.quote_found("'Erling Haaland' … 'price': 9.1", [src]) is True
    assert N.quote_found("'price': 9.1 ... 'price': 15.6", [src]) is False        # wrong order
    assert N.quote_found("'price': 15.6 ... 'price': 7.7", [src]) is False         # second segment absent
    assert N.quote_found("'price': 15.6 ... 'price': 9.1", ["'price': 15.6", "'price': 9.1"]) is False   # two sources


# ------------------------------------------------------------------ J2c: approximate claims
def test_approximate_claims_match_within_half_a_point_or_five_percent():
    assert N.number_in_quote(9, 0, "'e_points': 9.4", True) is True              # within 0.5
    assert N.number_in_quote(57, 0, "'optimal_xi_points': 58.9", True) is True   # within 5% of 58.9 (2.9)
    assert N.number_in_quote(50, 0, "'optimal_xi_points': 58.9", True) is False
    assert N.number_in_quote(9, 0, "'e_points': 9.4", False) is True             # exact rule: 9.4 rounds to 9 anyway
    assert N.number_in_quote(9.5, 1, "'e_points': 9.4", False) is False          # exact rule is strict
    cs = N.extract_claims("Expect ≈30% to start, ~9 points, roughly 16–18 points over two weeks, exactly 7.1.")
    flags = {c["text"]: c["about"] for c in cs}
    assert flags["30%"] is True and flags["9"] is True and flags["16"] is True and flags["18"] is True and flags["7.1"] is False
    assert flags["two"] is False


# ------------------------------------------------------------------ J2d: COUNT items
class _Fake:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def complete(self, purpose, system, user, model, max_tokens, temperature=0, **kw):
        self.prompts.append(user)
        text = self.replies.pop(0)
        return text, {"input_tokens": 3000, "output_tokens": 300, "attempts": 1, "stop_reason": "end_turn"}


def _answer(items, verdict="PASS", reason="ok"):
    return json.dumps({"items": items, "reason": reason, "verdict": verdict})


SQUAD = {"squad": [{"name": "Erling Haaland", "team": "Man City", "position": "FWD"}, {"name": "Alexander Isak", "team": "Liverpool", "position": "FWD"},
                   {"name": "Bukayo Saka", "team": "Arsenal", "position": "MID"}]}


def test_a_count_is_checked_by_code_against_the_listed_items(monkeypatch):
    calls = [{"tool": "build_squad_from_scratch", "args": {}, "error": None, "output": str(SQUAD)}]
    r = _record("Two forwards are forced in, plus three Arsenal players.", calls=calls, sheet="forced_starters")
    good = {"id": "c1", "number": 2, "about": "forwards forced in", "type": "COUNT",
            "items": [{"item": "Haaland", "quote": "'name': 'Erling Haaland', 'team': 'Man City', 'position': 'FWD'"},
                      {"item": "Isak", "quote": "'name': 'Alexander Isak', 'team': 'Liverpool', 'position': 'FWD'"}], "quote": "", "why": "two FWD rows"}
    bad = {"id": "c2", "number": 3, "about": "Arsenal players", "type": "COUNT",
           "items": [{"item": "Saka", "quote": "'name': 'Bukayo Saka', 'team': 'Arsenal'"}], "quote": "", "why": "only one Arsenal row"}
    fake = _Fake([_answer([good, bad])])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = N.judge_numbers(r, "claude-opus-5-5", RJ.Budget(10, 5.0))
    finals = {i["id"]: (i["final"], i["code"].get("count_ok")) for i in row["items"]}
    assert finals["c1"] == ("COUNT", True) and finals["c2"][0] == "UNSUPPORTED" and finals["c2"][1] is False
    assert "COUNT" in fake.prompts[0]


def test_a_count_that_rests_on_an_unsupported_attribute_is_unsupported(monkeypatch):
    calls = [{"tool": "build_squad_from_scratch", "args": {}, "error": None, "output": str({"squad": [{"name": "Bukayo Saka"}]})}]
    r = _record("Three Arsenal players.", calls=calls, sheet="forced_starters")
    item = {"id": "c1", "number": 3, "about": "Arsenal players", "type": "COUNT", "unsupported_attribute": "club",
            "items": [{"item": "Saka", "quote": "'name': 'Bukayo Saka'"}, {"item": "Gabriel", "quote": "x"}, {"item": "Calafiori", "quote": "y"}], "quote": "", "why": ""}
    fake = _Fake([_answer([item])])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = N.judge_numbers(r, "claude-opus-5-5", RJ.Budget(10, 5.0))
    assert row["items"][0]["final"] == "UNSUPPORTED" and row["verdict"] == "FAIL"


# ------------------------------------------------------------------ J2e: constants and nesting
def test_derived_inputs_may_be_constants_and_nest():
    assert N.recompute("x", [7, 4], 28, 0) is True
    inputs = [{"number": 7, "quote": "'extra_transfers': 7"}, {"number": 4, "constant": "points per extra transfer"}]
    ok, nums = N.resolve_inputs(inputs, ["'extra_transfers': 7"])
    assert ok is True and nums == [7.0, 4.0]
    bad = [{"number": 7, "quote": "'extra_transfers': 7"}, {"number": 9, "constant": "made up"}]
    assert N.resolve_inputs(bad, ["'extra_transfers': 7"])[0] is False
    nested = [{"op": "+", "inputs": [{"number": 15.6, "quote": "'price': 15.6"}, {"number": 9.1, "quote": "'price': 9.1"},
                                    {"number": 5.0, "quote": "'price': 5.0"}, {"number": 4.5, "quote": "'price': 4.5"}]},
              {"number": 100.0, "constant": "budget"}]
    src = ["'price': 15.6, 'price': 9.1, 'price': 5.0, 'price': 4.5"]
    ok, nums = N.resolve_inputs(nested, src)
    assert ok is True and nums == [34.2, 100.0]
    assert N.recompute("-", [100.0, 34.2], 65.8, 1) is True


# ------------------------------------------------------------------ J2f: extraction skips
def test_extraction_skips_echoed_user_numbers_table_row_numbers_and_bench_numbering():
    reply = ("| # | Player | Pts |\n| 1 | Haaland | 9.2 |\n| 2 | Saka | 6.1 |\n\nBench 1: Raya, Bench 2: Collins.\n"
             "You asked for 40 million; the cheapest legal squad costs 75.5 million. One more thing: one of them is injured.")
    cs = N.extract_claims(reply, user_text="Best fifteen for 40 million?")
    texts = [c["text"] for c in cs]
    assert texts == ["9.2", "6.1", "75.5"], texts


def test_chunk_size_and_budget_are_the_part_c_values():
    assert N.CHUNK == 8 and N.MAX_TOKENS == 8192 and N.TIMEOUT_S == 300


# ------------------------------------------------------------------ J3
def test_the_definitions_carry_the_review_changes():
    m1 = M.metric_text("M1")
    for w in ("objective", "market odds", "expected goals rate", "fitted"):
        assert w in m1
    for w in ("ingest", "horizon", "cutoff", "optimiser", "frame", "raw status codes"):
        assert w in m1
    m3a = M.metric_text("M3a")
    assert "club and position" in m3a and "reasons" in m3a
    assert "price-only mention" in M.metric_text("M4")
    assert "last two paragraphs" in M.metric_question("M5", "fixture_scores") and "last two paragraphs" in M.metric_question("M5", "get_fixtures")


def test_m4_applies_only_when_the_flagged_player_is_given_points_recommended_captained_or_locked():
    flagged = dict(CARD, status="i", chance=0)
    calls = [{"tool": "get_player_card", "args": {"player_id": 411}, "error": None, "output": str(flagged)}]
    assert M.applicable("M4", _record("Haaland is expected to score 9.2 points this week.", calls=calls)) is True
    assert M.applicable("M4", _record("Captain Haaland; he is the pick.", calls=calls)) is True
    assert M.applicable("M4", _record("That squad is infeasible: four forwards break the rule. Haaland costs £15.6m and Isak £9.1m.", calls=calls)) is False
    assert M.applicable("M4", _record("Nothing to report on the Man City squad.", calls=calls)) is False


# ------------------------------------------------------------------ J5
def test_tool_outputs_with_numpy_and_datetime_reprs_parse():
    out = "{'gw': 6, 'squad': [{'player_id': 1, 'name': 'A', 'e_points': np.float64(5.71), 'status': 'd', 'chance': np.int64(75)}], 'built': datetime.datetime(2026, 10, 10, 9, 51, 16), 'x': nan}"
    d = M.parse_output(out)
    assert d is not None and d["squad"][0]["e_points"] == 5.71 and d["squad"][0]["chance"] == 75
    assert "2026, 10, 10" in str(d["built"]) and d["x"] is None
    assert M.flagged_players([out]) and M.flagged_players([out])[0][0] == "A"
    assert M.parse_output("Timestamp('2026-10-10 09:51:16+0000', tz='UTC')") == "2026-10-10 09:51:16+0000"


# ------------------------------------------------------------------ club claims (gold rule 4 / eval code check)
def test_club_claims_are_sourced_from_the_turns_tool_outputs_else_unsourced():
    from judge import club_claims as CC
    players = [{"element": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City"},
               {"element": 5, "name": "Nordi Mukiele", "position": "DEF", "team": "Man City"},
               {"element": 7, "name": "Pedro Neto", "position": "MID", "team": "Chelsea"},
               {"element": 8, "name": "Gabriel dos Santos Magalhaes", "position": "DEF", "team": "Arsenal"},
               {"element": 9, "name": "Gabriel Martinelli", "position": "MID", "team": "Arsenal"},
               {"element": 10, "name": "Mohamed Salah", "position": "MID", "team": "Liverpool"},
               {"element": 11, "name": "Micky van de Ven", "position": "DEF", "team": "Spurs"}]
    reply = ("| Pos | Player | Club | Price |\n|---|---|---|---|\n| FWD | **Erling Haaland** | Man City | £15.6m |\n"
             "| DEF | Mukiele | Man Utd | £5.4m |\n| MID | Pedro Neto | Chelsea | £6.5m |\n| DEF | Gabriel | Arsenal | £8.0m |\n\n"
             "Isak (Liverpool) is doubtful. Tottenham's Vicario is out.")
    out = str({"squad": [{"player_id": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City"},
                         {"player_id": 5, "name": "Nordi Mukiele", "position": "DEF"},
                         {"player_id": 8, "name": "Gabriel dos Santos Magalhaes", "position": "DEF"}]})
    rec = {"id": "x", "question": "q", "setup": None, "rendered_reply": reply, "turns": [], "calls": [{"tool": "build_squad_from_scratch", "args": {}, "output": out}]}
    rows = CC.check(rec, players)
    by = {r["player_text"]: r for r in rows}
    assert by["Erling Haaland"]["status"] == "sourced_ok" and by["Erling Haaland"]["club"] == "Man City"
    assert by["Mukiele"]["status"] == "unsourced" and by["Mukiele"]["db_differs"] is True and by["Mukiele"]["db_club"] == "Man City"
    assert by["Pedro Neto"]["status"] == "unsourced" and by["Pedro Neto"]["db_differs"] is False
    assert by["Gabriel"]["player"] == "Gabriel dos Santos Magalhaes" and by["Gabriel"]["resolved_by"] == "tool"   # the tool rows disambiguate
    assert by["Isak"]["status"] == "unknown_player" and by["Vicario"]["club"] == "Spurs"
    assert CC.norm_club("Ipswich", ["Ipswich Town"]) == "Ipswich Town" and CC.norm_club("Wigan/Brighton", ["Brighton"]) is None
    s = CC.summary(rows)
    assert s["claims"] == 6 and s["sourced_ok"] == 1 and s["unsourced"] == 3 and s["unsourced_db_differs"] == 1


# ------------------------------------------------------------------ J2 follow-ups found on run 3 (2026-10-12)
def test_a_list_length_counts_as_a_number_in_the_quote_and_constants_need_no_quote():
    assert N.number_in_quote(4, 0, "'gameweeks': [6, 7, 8, 9]", False) is True          # the list has four entries
    assert N.number_in_quote(5, 0, "'gameweeks': [6, 7, 8, 9]", False) is False
    src = ["'attack_score': 7, 'x': 1", "'attack_score': 9"]
    ok, nums = N.resolve_inputs([{"op": "sum", "inputs": [{"number": 7, "quote": "'attack_score': 7"}, {"number": 9, "quote": "'attack_score': 9"}]},
                                 {"number": 2, "quote": "'gameweeks': [6, 7]"}], src)
    assert ok and nums == [16.0, 2.0] and N.recompute("/", nums, 8.0, 1)
    ok, nums = N.resolve_inputs([{"number": 32, "quote": "'total': 32"}, {"number": 4, "quote": "'made up': none"}], ["'total': 32"])
    assert ok and nums == [32.0, 4.0]                                                 # 4 is an allowed constant
    ok, _ = N.resolve_inputs([{"number": 32, "quote": "'total': 32"}, {"number": 13, "quote": "'made up': none"}], ["'total': 32"])
    assert ok is False


def test_an_approximate_derived_claim_passes_within_the_tolerance():
    assert N.recompute("/", [445.8, 24], 18, 0, about=True) is True                    # 18.6 -> "about 18 days"
    assert N.recompute("/", [445.8, 24], 18, 0, about=False) is False
    assert N.recompute("/", [445.8, 24], 16, 0, about=True) is False
