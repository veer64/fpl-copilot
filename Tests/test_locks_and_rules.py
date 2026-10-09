"""Part 2 (2026-10-09): the ambiguity lock on resolve_player, the rename of the from-scratch solver, and the
two prompt rules on changed plans and line-up value.

2a. When several current players answer to a name, the tool used to return their ids beside the
"ask which" note, and the model would pick one. An ambiguous answer now carries name, club, position
and price but NO player_id, plus "ask the user which one"; an unambiguous query (a full name, or a
club that narrows it) still returns the id. Pure: the two reads are monkeypatched.

2b. optimise -> build_squad_from_scratch at the schema, the dispatch table, the description and the
prompt; the Python function keeps its name; the tool count stays 24.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402

LIVE = [
    {"element": 12, "name": "Bukayo Saka", "position": "MID", "team": "Arsenal", "price_tenths": 102, "status": "a"},
    {"element": 154, "name": "Cole Palmer", "position": "MID", "team": "Chelsea", "price_tenths": 105, "status": "d"},
    {"element": 301, "name": "Alex Palmer", "position": "GK", "team": "Ipswich Town", "price_tenths": 45, "status": "a"},
    {"element": 426, "name": "Bruno Borges Fernandes", "position": "MID", "team": "Man Utd", "price_tenths": 90, "status": "a"},
]
WEB = {12: "Saka", 154: "Palmer", 301: "Palmer", 426: "B.Fernandes"}


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: [dict(r) for r in LIVE])
    monkeypatch.setattr(mt, "_web_names", lambda: dict(WEB))
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})
    monkeypatch.setattr(mt, "_club_short_names", lambda: {})
    monkeypatch.setattr(mt, "_clubs_known_to_history", lambda: set())
    return mt


# ---------------------------------------------------------------- 2a
def test_an_ambiguous_name_returns_no_ids_and_asks_the_user(resolver):
    out = mt.resolve_player("Palmer")
    assert out["ambiguous"] is True and out["total_matches"] == 2
    assert out["action"] == "ask the user which one"
    for m in out["matches"]:
        assert "player_id" not in m, m
        assert set(m) >= {"name", "team", "position", "price"}
    assert {m["name"] for m in out["matches"]} == {"Cole Palmer", "Alex Palmer"}
    assert "ask which" in out["note"]


def test_a_full_name_or_a_club_still_returns_the_id(resolver):
    cole = mt.resolve_player("Cole Palmer")
    assert cole["ambiguous"] is False and [m["player_id"] for m in cole["matches"]] == [154] and "action" not in cole
    chelsea = mt.resolve_player("Palmer", club="Chelsea")
    assert chelsea["ambiguous"] is False and [m["player_id"] for m in chelsea["matches"]] == [154]
    saka = mt.resolve_player("Saka")
    assert saka["ambiguous"] is False and [m["player_id"] for m in saka["matches"]] == [12]


def test_the_wrong_club_keeps_the_ambiguity_and_the_lock(resolver):
    out = mt.resolve_player("Palmer", club="Arsenal")
    assert out["ambiguous"] is True and all("player_id" not in m for m in out["matches"])
    assert "not Arsenal" in out["note"] and out["action"] == "ask the user which one"


def test_the_only_consumer_of_the_tool_output_is_the_agent():
    """Internal callers that need ids use player_names / the database, never the tool's answer."""
    import re
    text = "\n".join(p.read_text(encoding="utf-8") for p in REPO.glob("*.py") if p.name not in ("model_tools.py", "tools.py", "agent.py"))
    text += "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "eval").glob("*.py"))
    assert not re.search(r"\bresolve_player\(", text), "a code path reads the tool's output for ids"


# ---------------------------------------------------------------- 2b
def test_the_from_scratch_solver_is_named_for_what_it_does():
    import agent
    names = [t["name"] for t in agent.tools_schema]
    assert "build_squad_from_scratch" in names and "optimise" not in names and len(names) == 24
    schema = next(t for t in agent.tools_schema if t["name"] == "build_squad_from_scratch")
    assert schema["description"].startswith("Builds a brand-new 15 from scratch with a full £100m, ignoring the user's squad.")
    assert set(schema["input_schema"]["properties"]) >= {"lock_player_ids", "start_player_ids", "ban_player_ids", "budget", "gw"}
    fn = agent.available_functions["build_squad_from_scratch"]
    assert (fn.__module__, fn.__qualname__) == ("model_tools", "optimise")
    assert "optimise" not in agent.available_functions
    p = agent.SYSTEM_PROMPT
    assert "`optimise`" not in p and "`build_squad_from_scratch`" in p


# ---------------------------------------------------------------- 2c / 2d
def test_the_prompt_carries_the_changed_plan_and_line_up_rules():
    import agent
    p = agent.SYSTEM_PROMPT
    assert ("If the user changes a proposed plan (drops or swaps a move), it is a new plan: call `set_my_squad` with "
            "`confirm=false` to preview it before asking for confirmation. Never compose a preview yourself.") in p
    assert ("give the gain from rearranging the current squad (`get_my_xi`), then ask whether they want it weighed "
            "against transfers or against the best possible squad, and only then call the matching tool") in p
    assert "give three expected-points numbers" not in p
