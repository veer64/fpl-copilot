"""The automatic fact check (Prompt H, M1, 2026-10-30): fact_check.py compares the final answer with THIS turn's tool rows
(tables: name, position, team, price; prose: "Name (POS)", appositives, position lists, a price in the clause; stat labels:
chance of playing / of starting), and agent.py sends a mismatch back ONCE (USER DECISION H1) with tool use off.
Pinned here, from the task: Havertz written as DEF; "Rayan Cherki" an unknown name; Mbeumo's 97% "chance of playing";
Isak's £8.9m sell price; a correct "bought £8.9m, sells £9.0m" sentence NOT flagged; the send-back note's text; a rewrite
that is still wrong is delivered and flagged with no second call; a tool call in the rewrite -> the original is delivered.
Offline: fake clients, stubbed tools and logs, no database."""
import importlib
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import fact_check as fc  # noqa: E402

BUILD = {"squad": [{"player_id": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City", "price": 15.7},
                   {"player_id": 165, "name": "João Pedro Junqueira de Jesus", "position": "FWD", "team": "Chelsea", "price": 7.9},
                   {"player_id": 22, "name": "Kai Havertz", "position": "FWD", "team": "Arsenal", "price": 7.5},
                   {"player_id": 70, "name": "Rayan Vitor Simplício Rocha", "position": "MID", "team": "Bournemouth", "price": 6.3},
                   {"player_id": 4, "name": "Gabriel dos Santos Magalhães", "position": "DEF", "team": "Arsenal", "price": 6.1},
                   {"player_id": 5, "name": "Riccardo Calafiori", "position": "DEF", "team": "Arsenal", "price": 6.0},
                   {"player_id": 15, "name": "Martin Ødegaard", "position": "MID", "team": "Arsenal", "price": 6.8}]}
XI = {"xi": [{"player_id": 411, "name": "Erling Haaland", "position": "FWD", "team": "Man City", "role": "CAPTAIN", "e_points": 7.47,
              "p_play_any": 0.97},
             {"player_id": 427, "name": "Bryan Mbeumo", "position": "MID", "team": "Man Utd", "role": "start", "e_points": 4.83,
              "p_play_any": 0.98}]}
PRED = {"player_id": 427, "name": "Bryan Mbeumo", "team": "Man Utd", "predictions": [{"gw": 9, "e_points": 4.83, "p_start": 0.970522}]}
SQUAD = {"recorded_xi": [{"player_id": 379, "name": "Alexander Isak", "position": "FWD", "team": "Liverpool", "purchase_price": 9.1,
                          "current_price": 9.0, "sell_price": 9.0}]}


def _calls(*pairs):
    return [(tool, {}, result) for tool, result in pairs]


# ---- the checks --------------------------------------------------------------------------------------------------------

def test_havertz_written_as_a_defender_in_a_table_is_a_position_mismatch():
    text = ("| Player | Club | Pos | Price |\n|---|---|---|---|\n| Erling Haaland (C) | Man City | FWD | £15.7m |\n"
            "| João Pedro | Chelsea | FWD | £7.9m |\n| Kai Havertz | Arsenal | DEF | £7.5m |\n")
    r = fc.check(text, _calls(("build_squad_from_scratch", BUILD)))
    assert r["mismatches"] == [{"phrase": "Kai Havertz | Arsenal | DEF", "tool": "build_squad_from_scratch", "field": "position",
                                "value": "FWD", "kind": "position"}]
    assert r["facts_checked"] >= 9


def test_cherki_is_an_unknown_name_and_the_tool_row_that_shares_a_word_is_named():
    text = ("| Pos | Player | Club | Price |\n|---|---|---|---|\n| FWD | Erling Haaland | Man City | £15.7m |\n"
            "| DEF | Riccardo Calafiori | Arsenal | £6.0m |\n| MID | Rayan Cherki | Bournemouth | £6.3m |\n")
    r = fc.check(text, _calls(("build_squad_from_scratch", BUILD)))
    assert r["mismatches"] == [{"phrase": "Rayan Cherki", "tool": "build_squad_from_scratch", "field": "name",
                                "value": "Rayan Vitor Simplício Rocha", "kind": "unknown_name"}]


def test_mbeumo_97_chance_of_playing_is_his_start_chance_not_his_chance_of_playing():
    text = "From your squad:\n- **Haaland** — 7.5 expected points, 97% chance of playing\n- **Mbeumo** — 4.8 expected points, 97% chance of playing\n"
    r = fc.check(text, _calls(("get_my_xi", XI), ("get_prediction", PRED)))
    assert r["mismatches"] == [{"phrase": "Mbeumo** — 4.8 expected points, 97% chance of playing", "tool": "get_my_xi",
                                "field": "p_play_any", "value": "98%", "kind": "stat"}]


def test_isak_sell_price_written_as_8_9_is_flagged():
    text = "Selling prices vs. purchase prices:\n- Isak: bought at £9.1m → sells for **£8.9m** (fallen in full — £0.1m loss)\n"
    r = fc.check(text, _calls(("get_my_squad", SQUAD)))
    assert r["mismatches"] == [{"phrase": "Isak: bought at £9.1m → sells for **£8.9m**", "tool": "get_my_squad", "field": "sell_price",
                                "value": "£9.0m", "kind": "price"}]


def test_a_correct_bought_and_sells_sentence_is_not_flagged():
    squad = {"recorded_xi": [{"player_id": 379, "name": "Alexander Isak", "position": "FWD", "team": "Liverpool", "purchase_price": 8.9,
                              "current_price": 9.1, "sell_price": 9.0}]}
    r = fc.check("Isak: bought £8.9m, sells £9.0m.", _calls(("get_my_squad", squad)))
    assert r["mismatches"] == [] and r["facts_checked"] == 2


def test_two_prices_with_unclear_labels_are_skipped_never_flagged():
    r = fc.check("Isak: £8.4m and £9.6m over the season.", _calls(("get_my_squad", SQUAD)))
    assert r["mismatches"] == [] and r["facts_checked"] == 0


def test_a_price_that_reads_as_a_difference_is_not_a_price():
    r = fc.check("Moving to Isak frees up £0.6m in the bank.", _calls(("get_my_squad", SQUAD)))
    assert r["mismatches"] == []


def test_a_position_list_names_odegaard_a_defender():
    text = "The build goes heavy on **Arsenal defenders** (Gabriel, Calafiori, Ødegaard — three from Arsenal, the maximum)."
    r = fc.check(text, _calls(("build_squad_from_scratch", BUILD)))
    assert [(m["field"], m["value"], m["kind"]) for m in r["mismatches"]] == [("position", "MID", "position")]
    assert "Ødegaard" in r["mismatches"][0]["phrase"]


def test_name_pos_in_prose_and_the_appositive():
    calls = _calls(("build_squad_from_scratch", BUILD))
    assert [m["value"] for m in fc.check("Bring in Havertz (Arsenal, DEF) for the run.", calls)["mismatches"]] == ["FWD"]
    assert [m["value"] for m in fc.check("Calafiori, a midfielder, starts.", calls)["mismatches"]] == ["DEF"]
    assert fc.check("Havertz (Arsenal, FWD, £7.5m) is the pick.", calls)["mismatches"] == []


def test_no_tool_rows_means_nothing_is_checked():
    r = fc.check("| Player | Pos |\n|---|---|\n| Kai Havertz | DEF |\n", [])
    assert r == {"facts_checked": 0, "mismatches": [], "n_rows": 0}


def test_a_shared_first_name_is_ambiguous_and_never_checked():
    rows = {"squad": [{"player_id": 1, "name": "Gabriel dos Santos Magalhães", "position": "DEF", "team": "Arsenal"},
                      {"player_id": 2, "name": "Gabriel Martinelli Silva", "position": "MID", "team": "Arsenal"}]}
    assert fc.check("Gabriel (DEF) starts.", _calls(("list_players", rows)))["mismatches"] == []


def test_saved_outputs_with_numpy_and_datetime_reprs_are_read():
    s = "{'name': 'Kai Havertz', 'position': 'FWD', 'price': np.float64(7.5), 'built': datetime.datetime(2026, 10, 23, 17, 21)}"
    got = fc.saved_output(s)
    assert got["price"] == 7.5 and got["built"].startswith("datetime.datetime(")


# ---- Prompt M-fix (2026-10-30): the two live misfires of H's gate, fixed definition-first ---------------------------------

RESOLVED = {"matches": [{"name": "Bryan Mbeumo", "position": "MID", "team": "Man Utd", "status": "a", "player_id": 427,
                         "price": 7.8, "web_name": "Mbeumo"}]}
RESOLVED_BRUNO = {"matches": [{"name": "Bruno Borges Fernandes", "position": "MID", "team": "Man Utd", "status": "a",
                               "player_id": 426, "price": 11.8, "web_name": "B.Fernandes"}]}
BUILD_F15 = {"squad": [{"player_id": 470, "name": "Caoimhín Kelleher", "position": "GK", "team": "Brentford", "price": 5.0},
                       {"player_id": 4, "name": "Gabriel dos Santos Magalhães", "position": "DEF", "team": "Arsenal", "price": 7.9},
                       {"player_id": 5, "name": "Riccardo Calafiori", "position": "DEF", "team": "Arsenal", "price": 6.0},
                       {"player_id": 566, "name": "António João Pereira de Albuquerque Tavares da Silva", "position": "DEF",
                        "team": "Bournemouth", "price": 5.0, "e_points": 4.37},
                       {"player_id": 70, "name": "Rayan Vitor Simplício Rocha", "position": "MID", "team": "Bournemouth", "price": 6.3}]}
F15_HEAD = "| Player | Club | Pos | Price | xPts (GW8) |\n|---|---|---|---|---|\n"
F15_ROWS = ("| Caoimhín Kelleher | Brentford | GK | £5.0m | 4.7 |\n| Gabriel | Arsenal | DEF | £7.9m | 6.2 |\n"
            "| Riccardo Calafiori | Arsenal | DEF | £6.0m | 5.2 |\n")


def test_f14_a_shortfall_amount_in_the_clause_is_not_the_players_price():
    # routing:21 (H's live gate): "leaves you £4.0m short" was read as Mbeumo's price (7.8) and sent back
    text = ("Here's the maths:\n- **Mbeumo sells for £7.8m**\n- **Bruno Fernandes costs £11.8m**\n- **Shortfall: £4.0m**\n"
            "- **Your bank: £0.0m**\n\nSo selling Mbeumo alone leaves you £4.0m short. You can't afford Bruno without raising "
            "more cash elsewhere — at least one more sale would be needed.\n")
    r = fc.check(text, _calls(("resolve_player", RESOLVED_BRUNO), ("resolve_player", RESOLVED)))
    assert r["mismatches"] == [] and r["facts_checked"] == 2           # £7.8m and £11.8m checked; the £4.0m never


def test_f14_each_listed_word_makes_the_clause_price_unchecked():
    calls = _calls(("resolve_player", RESOLVED))
    for word in ("short", "over", "left", "remaining", "bank", "budget", "gap", "need", "spare", "more"):
        text = f"The {word} question first: Mbeumo brings £5.5m."
        r = fc.check(text, calls)
        assert r["mismatches"] == [] and r["facts_checked"] == 0, word


def test_f14_a_clause_without_those_words_and_the_name_parenthesis_are_still_checked():
    calls = _calls(("resolve_player", RESOLVED))
    assert [m["value"] for m in fc.check("Mbeumo is priced at £7.5m.", calls)["mismatches"]] == ["£7.8m"]
    assert [m["value"] for m in fc.check("Sell Mbeumo (£7.5m) to leave more in the bank.", calls)["mismatches"]] == ["£7.8m"]


def test_f15_a_short_name_form_counts_as_its_tool_row():
    # forced_starters:6 (H's live gate): "Tav Silva" was an unknown name; the build's row carries only the legal name
    text = F15_HEAD + F15_ROWS + "| Tav Silva | Bournemouth | DEF | £5.0m | 4.4 |\n"
    r = fc.check(text, _calls(("build_squad_from_scratch", BUILD_F15)))
    assert r["mismatches"] == [] and r["facts_checked"] == 16          # 4 rows x name, club, position, price


def test_f15_the_fitted_row_has_its_fields_checked():
    text = F15_HEAD + F15_ROWS + "| Tav Silva | Bournemouth | MID | £5.0m | 4.4 |\n"
    r = fc.check(text, _calls(("build_squad_from_scratch", BUILD_F15)))
    assert r["mismatches"] == [{"phrase": "Tav Silva | Bournemouth | MID", "tool": "build_squad_from_scratch",
                                "field": "position", "value": "DEF", "kind": "position"}]


def test_f15_cherki_is_still_an_unknown_name_beside_a_fitted_short_name():
    text = (F15_HEAD + F15_ROWS + "| Tav Silva | Bournemouth | DEF | £5.0m | 4.4 |\n"
            "| Rayan Cherki | Bournemouth | MID | £6.3m | 4.6 |\n")
    r = fc.check(text, _calls(("build_squad_from_scratch", BUILD_F15)))
    assert r["mismatches"] == [{"phrase": "Rayan Cherki", "tool": "build_squad_from_scratch", "field": "name",
                                "value": "Rayan Vitor Simplício Rocha", "kind": "unknown_name"}]


def test_f15_two_fitting_rows_are_ambiguous_not_unknown_and_a_two_letter_prefix_does_not_fit():
    two = {"squad": BUILD_F15["squad"] + [{"player_id": 900, "name": "Tavio Silvano", "position": "MID", "team": "Everton",
                                           "price": 4.5}]}
    r = fc.check(F15_HEAD + F15_ROWS + "| Tav Silva | Bournemouth | DEF | £5.0m | 4.4 |\n", _calls(("build_squad_from_scratch", two)))
    assert r["mismatches"] == [] and r["facts_checked"] == 12          # the three exact rows only; Tav Silva not checked
    r = fc.check(F15_HEAD + F15_ROWS + "| Ta Silva | Bournemouth | DEF | £5.0m | 4.4 |\n",
                 _calls(("build_squad_from_scratch", BUILD_F15)))
    assert [(m["phrase"], m["kind"]) for m in r["mismatches"]] == [("Ta Silva", "unknown_name")]


def test_the_live_raya_catch_is_still_a_position_mismatch():
    # optimise:7 (H's live gate): Raya listed among three Arsenal defenders; the build says GK
    build = {"squad": BUILD["squad"] + [{"player_id": 1, "name": "David Raya Martín", "position": "GK", "team": "Arsenal", "price": 5.9}]}
    text = "- **Three Arsenal defenders** (Gabriel, Calafiori, Raya) and a **heavy Everton/Bournemouth tilt**."
    r = fc.check(text, _calls(("build_squad_from_scratch", build)))
    assert [(m["field"], m["value"]) for m in r["mismatches"]] == [("position", "GK")]
    assert "Raya" in r["mismatches"][0]["phrase"]


# ---- the note (H1) --------------------------------------------------------------------------------------------------------

def test_the_send_back_note_text_is_pinned():
    ms = [{"phrase": "Kai Havertz | Arsenal | DEF", "tool": "build_squad_from_scratch", "field": "position", "value": "FWD", "kind": "position"},
          {"phrase": "Mbeumo** — 4.8 expected points, 97% chance of playing", "tool": "get_my_xi", "field": "p_play_any", "value": "98%",
           "kind": "stat"},
          {"phrase": "Rayan Cherki", "tool": None, "field": "name", "value": None, "kind": "unknown_name"}]
    assert fc.note(ms) == (
        "Automatic fact check: your answer has 3 fact(s) that don't match this turn's tool output. Fix only these, keep everything "
        "else exactly as written, and don't add new facts.\n"
        '1. You wrote "Kai Havertz | Arsenal | DEF". build_squad_from_scratch says position: FWD. -> Use FWD.\n'
        '2. You wrote "Mbeumo** — 4.8 expected points, 97% chance of playing". get_my_xi says chance of playing: 98%. -> Use 98%.\n'
        '3. You wrote "Rayan Cherki". No tool output this turn has that player. -> Use only players from this turn\'s tool output.')


# ---- the send-back in the agent loop ------------------------------------------------------------------------------------------

class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason, self.model = content, stop_reason, "claude-sonnet-4-6"
        self.usage = types.SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class _Fake:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


WRONG = "From your squad:\n- **Mbeumo** — 4.8 expected points, 97% chance of playing."
RIGHT = "From your squad:\n- **Mbeumo** — 4.8 expected points, 98% chance of playing."


def _tool_then(*finals):
    return [_Resp([_Block("tool_use", name="get_my_xi", input={}, id="toolu_1")], "tool_use")] + list(finals)


def _text(s):
    return _Resp([_Block("text", text=s)], "end_turn")


@pytest.fixture
def ag(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    importlib.reload(agent)
    monkeypatch.setattr(agent, "context_block", lambda now=None: "CONTEXT BLOCK")
    monkeypatch.setattr(agent, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_numeric_check", lambda *a, **k: None)
    logged = []
    monkeypatch.setattr(agent, "_fact_check_log", lambda turn_id, info: logged.append(info))
    ran = []
    monkeypatch.setitem(agent.available_functions, "get_my_xi", lambda **kw: ran.append("get_my_xi") or XI)
    agent._test_logged, agent._test_ran = logged, ran
    return agent


def test_a_wrong_fact_is_sent_back_once_with_tool_use_off_and_the_rewrite_is_delivered(ag, monkeypatch):
    fake = _Fake(_tool_then(_text(WRONG), _text(RIGHT)))
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent("Who should I captain?", [])
    assert answer == RIGHT and len(fake.calls) == 3
    sb = fake.calls[2]
    assert sb["tool_choice"] == {"type": "none"} and "tool_choice" not in fake.calls[1]
    assert sb["tools"] == fake.calls[1]["tools"] and sb["system"] == fake.calls[1]["system"], "tools and system kept: the cache holds"
    last = sb["messages"][-1]
    assert last["role"] == "user" and last["content"][0]["text"].startswith("Automatic fact check: your answer has 1 fact(s)")
    assert '"Mbeumo** — 4.8 expected points, 97% chance of playing"' in last["content"][0]["text"]
    assert not any(isinstance(m["content"], str) and m["content"].startswith("Automatic fact check") for m in history), \
        "the note never enters the stored history"
    assert history[-1]["role"] == "assistant" and history[-1]["content"][0].text == RIGHT
    info = ag._test_logged[-1]
    assert info["outcome"] == "fixed" and info["sent_back"] and info["rewrite_mismatches"] == [] and len(info["mismatches"]) == 1
    assert ag.LAST_FACT_CHECK["outcome"] == "fixed" and ag.LAST_FACT_CHECK["original"] == WRONG


def test_a_rewrite_that_is_still_wrong_is_delivered_flagged_with_no_second_call(ag, monkeypatch):
    still = "From your squad:\n- **Mbeumo** — 4.8 expected points, 96% chance of playing."
    fake = _Fake(_tool_then(_text(WRONG), _text(still)))
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("Who should I captain?", [])
    assert answer == still and len(fake.calls) == 3
    info = ag._test_logged[-1]
    assert info["outcome"] == "still_wrong" and len(info["rewrite_mismatches"]) == 1


def test_a_tool_call_in_the_rewrite_delivers_the_original(ag, monkeypatch):
    fake = _Fake(_tool_then(_text(WRONG), _Resp([_Block("tool_use", name="get_my_xi", input={}, id="toolu_9")], "tool_use")))
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent("Who should I captain?", [])
    assert answer == WRONG and len(fake.calls) == 3
    assert ag._test_ran == ["get_my_xi"], "the rewrite's tool call is never run"
    assert ag._test_logged[-1]["outcome"] == "tool_call_in_rewrite"
    assert history[-1]["content"][0].text == WRONG


def test_a_clean_answer_makes_no_extra_call(ag, monkeypatch):
    fake = _Fake(_tool_then(_text(RIGHT)))
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("Who should I captain?", [])
    assert answer == RIGHT and len(fake.calls) == 2
    info = ag._test_logged[-1]
    assert info["outcome"] == "clean" and not info["sent_back"] and info["facts_checked"] >= 1


def test_a_turn_without_tools_is_logged_with_nothing_checked(ag, monkeypatch):
    fake = _Fake([_text("Hello! Ask me about your squad.")])
    monkeypatch.setattr(ag, "client", fake)
    ag.run_agent("hi", [])
    assert len(fake.calls) == 1 and ag._test_logged[-1]["facts_checked"] == 0 and ag._test_logged[-1]["outcome"] == "clean"


def test_the_loop_guard_reply_is_not_checked(ag, monkeypatch):
    fake = _Fake([_Resp([_Block("thinking", thinking="", signature="s")], "max_tokens")])
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("Who should I captain?", [])
    assert answer == ag.GUARD_REPLY and ag._test_logged == [] and len(fake.calls) == 1


def test_a_failed_send_back_delivers_the_original(ag, monkeypatch):
    class Boom(_Fake):
        def create(self, **kw):
            if len(self.calls) == 2:
                self.calls.append(kw)
                raise ConnectionError("network down")
            return super().create(**kw)
    fake = Boom(_tool_then(_text(WRONG)))
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent("Who should I captain?", [])
    assert answer == WRONG and ag._test_logged[-1]["outcome"] == "sendback_failed"


@pytest.mark.fact_check_log
def test_record_writes_one_fact_checks_row(monkeypatch):
    """the writer, against the news test database (never the developer's): ensure_schema is idempotent, the row holds
    the mismatches as JSON and the outcome"""
    import psycopg2
    import db_write
    monkeypatch.setenv("DB_NAME", "fpl_news_test")
    try:
        conn = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS fact_checks")
        conn.commit()
        monkeypatch.setattr(fc, "_SCHEMA_READY", [])
        info = {"facts_checked": 4, "mismatches": [{"phrase": "Kai Havertz | Arsenal | DEF", "tool": "t", "field": "position",
                                                    "value": "FWD", "kind": "position"}],
                "sent_back": True, "outcome": "fixed", "rewrite_mismatches": [], "extra_usd": 0.0123, "extra_seconds": 2.5}
        fc.record("turn-1", info, conn=conn)
        fc.ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT turn_id, facts_checked, mismatches, sent_back, outcome, rewrite_mismatches, extra_seconds FROM fact_checks")
            rows = cur.fetchall()
        assert len(rows) == 1 and rows[0][0] == "turn-1" and rows[0][1] == 4 and rows[0][2][0]["value"] == "FWD"
        assert rows[0][3] is True and rows[0][4] == "fixed" and rows[0][5] == [] and abs(rows[0][6] - 2.5) < 1e-6
    finally:
        conn.close()
