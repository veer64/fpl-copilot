"""Numeric grounding checker (numeric_grounding.py, 2026-10-02, LOG ONLY): every number the agent states must be
found -- as itself, x100 or /10, rounded to the claim's decimal places -- among the numbers the model could see this
turn (every user message and every tool_result block in the messages sent to it). Pinned here: the Doku case (an
invented 0.3 bonus), the three scalings, user-message numbers, every SKIP label, the result shape, the numeric_checks
table and the agent wiring: the reply is never altered and a checker exception is caught and logged. No network: a
scripted fake Anthropic client plays the agent's turns; the DB tests use the local Postgres (fpl_news_test)."""
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import news_store as ns  # noqa: E402
import numeric_grounding as ng  # noqa: E402

TEST_DB = "fpl_news_test"
DROP_ALL = ("DROP TABLE IF EXISTS numeric_checks; DROP TABLE IF EXISTS availability_comparisons; DROP TABLE IF EXISTS availability_claims; "
            "DROP TABLE IF EXISTS availability_extractions; DROP TABLE IF EXISTS citation_checks; DROP TABLE IF EXISTS search_log; "
            "DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; "
            "DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; "
            "DROP TABLE IF EXISTS news_relevance; DROP TABLE IF EXISTS llm_calls; "
            "DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    with c.cursor() as cur:
        cur.execute(DROP_ALL)
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


def msgs(user, *tool_results):
    """A conversation as agent.run_agent builds it: the user turn, one assistant tool_use turn, one tool_result turn
    per result (content = str(result), exactly as agent.py sends it)."""
    out = [{"role": "user", "content": user}]
    if tool_results:
        out.append({"role": "assistant", "content": [types.SimpleNamespace(type="tool_use", name="t", input={}, id="t1")]})
        out.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": str(r)}
                                                for i, r in enumerate(tool_results, 1)]})
    return out


DOKU_CARD = {"player_id": 335, "name": "Jérémy Doku", "team": "Man City", "status": "a", "chance": 100, "news": "",
             "updated_at": "2026-10-01 11:01:48+00:00",
             "prediction": {"gw": 6, "predictions": [{"gw": 6, "horizon_step": 1, "e_points": 1.8, "e_minutes": 39.2, "p_start": 0.35,
                                                       "q_p50": 1, "q_p90": 6, "exp_bonus": 0.0}]}}


def test_doku_case_flags_the_invented_bonus_and_grounds_the_rest():
    reply = ("Good news: FPL lists him as fully available (100% chance of playing) as of 1 October 11:01Z. The model's start "
             "probability for GW6 is only 35% with expected minutes of ~39. His expected points are 1.8 (the model doesn't "
             "include bonus points, which adds roughly 0.3 for a regular starter). P50 is 1 point; the ceiling (P90) is 6 points.")
    r = ng.check(reply, msgs("Is Doku close to returning?", DOKU_CARD))
    assert r["numbers_found"] == 7 and r["grounded"] == 6
    assert [u["text"] for u in r["ungrounded"]] == ["0.3"]
    u = r["ungrounded"][0]
    assert u["value"] == 0.3 and "adds roughly 0.3" in u["context"] and len(u["context"].split()) <= 12
    assert r["notebook_size"] >= 8


def test_the_three_scalings_round_to_the_claims_decimals():
    tool = {"e_points": 5.83, "p_start": 0.75, "price_tenths": 75, "p_cs": 0.284}
    r = ng.check("About 5.8 points, a 75% start chance; he costs £7.5m and keeps a clean sheet 28% of the time.", msgs("q", tool))
    assert r["numbers_found"] == 4 and r["grounded"] == 4 and r["ungrounded"] == []
    r = ng.check("About 5.9 points.", msgs("q", tool))                          # no other tolerance
    assert r["numbers_found"] == 1 and r["grounded"] == 0 and r["ungrounded"][0]["text"] == "5.9"
    r = ng.check("5.83 exactly, 7.5 for the price, 0.75 as a fraction.", msgs("q", tool))
    assert r["grounded"] == 3
    # rounding is conventional half-up on the decimal repr, not float round(): 0.35 -> 0.4, so an invented "0.3"
    # beside a 0.35 start chance is NOT grounded (float round(0.35, 1) == 0.3 would have hidden the Doku case)
    assert ng.check("a 0.4 start probability", msgs("q", {"p_start": 0.35}))["grounded"] == 1
    assert ng.check("adds roughly 0.3", msgs("q", {"p_start": 0.35}))["grounded"] == 0
    assert ng.check("28% clean sheets", msgs("q", {"p_cs": 0.284}))["grounded"] == 1


def test_numbers_from_the_user_message_are_in_the_notebook():
    r = ng.check("With 2.3 in the bank and 1 free transfer you can afford him.", msgs("I have 2.3 in the bank and 1 free transfer."))
    assert r["numbers_found"] == 2 and r["grounded"] == 2 and r["notebook_size"] == 2


def test_every_skip_label_is_ignored_and_a_real_number_beside_them_still_counts():
    reply = ("For GW6 and gameweek 7 (deadline 10 Oct, also Oct 10 and 2026-10-10 at 14:00 and 10:00Z, as in 2019 and 2026) "
             "see [1] and c702; he was 1st then 2nd; more at https://x.example/a/12/b?x=3 .\n1. first item\n2) second item\n"
             "He scores 7.1 points.")
    r = ng.check(reply, msgs("q"))
    assert r["numbers_found"] == 1 and r["grounded"] == 0 and r["ungrounded"][0]["text"] == "7.1"
    assert ng.check("Nothing numeric here, GW6 aside.", msgs("q"))["numbers_found"] == 0


def test_json_values_count_and_booleans_do_not_and_the_shape_holds():
    out = [{"role": "user", "content": "q"},
           {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "price 4.5"}]},
                                        {"type": "tool_result", "tool_use_id": "t2", "content": {"flag": True, "n": 3, "nested": [{"v": 0.25}]}}]}]
    r = ng.check("4.5, 3 and 25% but not 1.", out)                     # True is not a number; nothing rounds to 1
    assert r["numbers_found"] == 4 and r["grounded"] == 3 and [u["text"] for u in r["ungrounded"]] == ["1"]
    assert r["notebook_size"] == 3 and set(r) == {"numbers_found", "grounded", "ungrounded", "notebook_size"}
    assert ng.check("", out) == {"numbers_found": 0, "grounded": 0, "ungrounded": [], "notebook_size": 3}
    assert ng.check("7 points", [])["ungrounded"][0]["value"] == 7.0


# ---- the table and the agent wiring ------------------------------------------------------------------------------

class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason = content, stop_reason


class _FakeMessages:
    """turn 1: call get_player_card; turn 2: reply with the given text"""

    def __init__(self, reply):
        self.turn, self.reply = 0, reply

    def create(self, **kw):
        self.turn += 1
        if self.turn == 1:
            return _Resp([_Block("tool_use", name="get_player_card", input={"player_id": 26}, id="t1")], "tool_use")
        return _Resp([_Block("text", text=self.reply)], "end_turn")


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)
    monkeypatch.setitem(ag.available_functions, "get_player_card",
                        lambda **kw: {"player_id": 26, "name": "Kai Havertz", "prediction": {"predictions": [{"e_points": 3.7, "p_start": 0.61}]}})
    return ag


def test_numeric_check_is_logged_with_the_turn_id_and_the_reply_is_untouched(conn, monkeypatch):
    ag = _agent(monkeypatch)
    reply = "Havertz is projected 3.7 points with a 61% start chance; bonus would add about 0.3 on top."
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_FakeMessages(reply)))
    answer, messages = ag.run_agent("Is Havertz fit for GW6?")
    assert answer == reply
    with conn.cursor() as cur:
        cur.execute("SELECT turn_id, numbers_found, grounded, ungrounded, notebook_size, error FROM numeric_checks ORDER BY id DESC LIMIT 1")
        turn_id, found, grounded, ungrounded, notebook_size, error = cur.fetchone()
        cur.execute("SELECT turn_id FROM citation_checks ORDER BY id DESC LIMIT 1")
        assert cur.fetchone()[0] == turn_id                                    # the same turn id as the citation check
    assert found == 3 and grounded == 2 and error is None and notebook_size >= 3
    assert [u["text"] for u in ungrounded] == ["0.3"] and ungrounded[0]["value"] == 0.3


def test_a_checker_exception_leaves_the_reply_unchanged_and_is_logged(conn, monkeypatch):
    ag = _agent(monkeypatch)
    reply = "Havertz is projected 3.7 points."
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_FakeMessages(reply)))

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(ag, "numeric_check", boom)
    answer, _ = ag.run_agent("Is Havertz fit?")
    assert answer == reply
    with conn.cursor() as cur:
        cur.execute("SELECT numbers_found, grounded, ungrounded, error FROM numeric_checks ORDER BY id DESC LIMIT 1")
        assert cur.fetchone() == (None, None, None, "RuntimeError: boom")
    # even the logging failing never touches the reply
    monkeypatch.setattr(ag, "record_numeric_check", boom)
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=_FakeMessages(reply)))
    answer, _ = ag.run_agent("again")
    assert answer == reply
