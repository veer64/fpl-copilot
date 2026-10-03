"""B15 (2026-10-03): a tool argument of the wrong type must not reach the database, and a
database exception must not carry SQL back to the model.

Measured before the fix: `get_player_card("Saka")` raised

    InvalidTextRepresentation: invalid input syntax for type integer: "Saka"
    LINE 1: SELECT * FROM players_live WHERE element = 'Saka'
                                                       ^

and agent.call_tool passed all three lines, SELECT included, straight into the
conversation. The id is now checked before any query, and the wrapper keeps only the first
line of a psycopg2 error.

No database and no network: the one query get_player_card would make is monkeypatched.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2                                            # noqa: E402
import agent                                               # noqa: E402
import model_tools as mt                                   # noqa: E402

BAD_ID = "player_id must be a number; use resolve_player to find it"


@pytest.fixture
def no_db(monkeypatch):
    """Record what get_player_card would have asked the database for."""
    asked = []

    def fake_q(sql, params=None):
        asked.append(params)
        return [{"element": 12, "name": "Cole Palmer", "position": "MID", "team": "Chelsea",
                 "price_tenths": 97, "status": "a", "chance": None, "news": None,
                 "updated_at": None}]

    monkeypatch.setattr(mt, "_q", fake_q)
    monkeypatch.setattr(mt, "get_prediction", lambda pid, gw=None: {"error": "not needed here"})
    return asked


@pytest.mark.parametrize("bad", ["Saka", "", "  ", "12.5", "abc12", None, 12.5, [12], {"id": 12}])
def test_a_non_whole_number_id_is_refused_before_any_query(no_db, bad):
    out = mt.get_player_card(bad)
    assert out == {"error": BAD_ID}, (bad, out)
    assert no_db == [], f"{bad!r} reached the database: {no_db}"


@pytest.mark.parametrize("good,want", [(12, 12), ("12", 12), (" 12 ", 12), (12.0, 12), (True, 1)])
def test_a_whole_number_id_still_works_and_arrives_as_an_int(no_db, good, want):
    out = mt.get_player_card(good)
    assert "error" not in out, out
    assert out["player_id"] == 12 and out["name"] == "Cole Palmer"
    assert no_db and no_db[0] == (want,), (good, no_db)


def test_the_refusal_names_no_sql_and_no_table(no_db):
    text = str(mt.get_player_card("Saka"))
    for leak in ("SELECT", "players_live", "LINE 1", "element ="):
        assert leak not in text, (leak, text)


# ---- the generic wrapper in agent.py -------------------------------------------------
PG_MESSAGE = ('invalid input syntax for type integer: "Saka"\n'
              "LINE 1: SELECT * FROM players_live WHERE element = 'Saka'\n"
              "                                                   ^")


def test_a_database_exception_reaches_the_model_as_its_first_line_only(monkeypatch):
    def boom(**kw):
        raise psycopg2.errors.InvalidTextRepresentation(PG_MESSAGE)

    monkeypatch.setitem(agent.available_functions, "boom_db", boom)
    out = agent.call_tool("boom_db", {})
    assert "SELECT" not in out["error"] and "LINE 1" not in out["error"], out["error"]
    assert out["error"].count("\n") == 0, out["error"]
    assert 'invalid input syntax for type integer: "Saka"' in out["error"]
    assert "boom_db" in out["error"] and out["tool"] == "boom_db"


def test_a_plain_exception_keeps_its_message(monkeypatch):
    """Only database errors are cut to one line: a tool's own multi-line explanation is
    information the model needs."""
    def boom(**kw):
        raise RuntimeError("line one\nline two with detail")

    monkeypatch.setitem(agent.available_functions, "boom_plain", boom)
    out = agent.call_tool("boom_plain", {})
    assert "line two with detail" in out["error"]
