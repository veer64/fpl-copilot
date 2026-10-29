"""Fix batch #4 follow-up S1 (2026-10-22), failing test first: the search_news description invites club team-news and
manager / press-conference questions, with or without player names (search_news:2 made no search 3/3 in the batch-4
gate: "I don't have access to press conferences, manager quotes ..."); it names the club when one is named, searches
with the query alone when the person named is not a player and the club is not stated (no guessed club, no clarifying
question first), and does not invite the tool for prediction, comparison, who-to-pick or transfer questions. The tool
itself already searches with clubs only or the query only (news_search.search_news, the "clubs or query only" branch):
the second test pins that path on the seeded corpus."""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location("tns_helpers", Path(__file__).with_name("test_news_search.py"))
tns = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tns)
conn = tns.conn                                                          # the fixture (fpl_news_test, schema rebuilt)


def _description():
    import agent
    return next(t for t in agent.tools_schema if t["name"] == "search_news")["description"]


def test_s1_the_description_invites_club_and_manager_questions_without_player_names(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    d = _description().lower()
    # Prompt G (2026-10-29), V1: a question naming no player and no club is NOT searched with the query alone any more --
    # the tool answers with an ask-which text; a manager / press-conference question names its club in `clubs`.
    for must in ("manager", "press conference", "`clubs`", "no player and no club", "ask-which", "never guess the club", "always pass the player names",
                 "injury", "fitness", "availability", "suspension", "team-news", "fpl status"):
        assert must in d, must
    assert "not for prediction" in d and "comparison" in d and "transfer" in d, "the description must keep the tool off the other tools' questions"
    assert "query alone" not in d and "never ask first" not in d, "the old search-anyway sentence must be gone (V1)"
    assert "ask the user which player, club or team" in d


def test_s1_the_tool_searches_with_a_club_only_and_with_the_query_only(conn):
    tns.seed(conn)
    out = tns.search(conn, "What has the Arsenal manager said in his latest press conference?", (), ("Arsenal",))
    assert out["search_mode"] == "hybrid" and out["results"], out
    assert all(r["about_requested_player"] is False for r in out["results"]) and out["no_news_for"] == []
    out2 = tns.search(conn, "What did the head coach say about the injury situation?", (), ())
    assert out2["search_mode"] == "dense_only" and out2["results"] and out2["ambiguous_players"] == {}
