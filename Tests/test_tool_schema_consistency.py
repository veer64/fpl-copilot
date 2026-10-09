"""Every tool's schema agrees with the function it dispatches to (2026-10-09).

Found by the agent eval: get_my_xi's description promised "Optional gw solves the XI for another
gameweek" and the function took gw, but the schema never listed it, so the model could not pass it.
Two rules, for every tool in agent.tools_schema:
  1. every schema property is a parameter of the registered function (a property the function
     cannot accept would be an argument thrown away or a TypeError inside call_tool);
  2. a description that offers an "optional gw" names gw in the schema (a promise the model
     cannot keep otherwise).
No network: agent is imported with a dummy key.
"""
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

OPTIONAL_GW = re.compile(r"\boptional\s+`?gw\b", re.I)


@pytest.fixture(scope="module")
def tools(monkeypatch_module=None):
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    return agent


def _names(tools):
    return [t["name"] for t in tools.tools_schema]


@pytest.mark.parametrize("name", [
    "resolve_player", "get_player_card", "get_prediction", "compare_players", "get_picks", "get_best_squad",
    "optimise", "get_my_squad", "get_my_xi", "explain_prediction", "compare_runs", "compare_predictions",
    "propose_transfers", "set_my_squad", "list_players", "get_fixtures", "get_price_movements",
    "get_league_table", "get_match_stats", "get_actual_points", "get_my_points", "get_prediction_history",
    "get_wildcard_gap", "search_news"])
def test_every_schema_property_is_a_parameter_of_the_function(tools, name):
    schema = next(t for t in tools.tools_schema if t["name"] == name)
    fn = tools.available_functions[name]
    params = inspect.signature(fn).parameters
    extra = [p for p in schema["input_schema"]["properties"] if p not in params]
    assert extra == [], f"{name}: schema names {extra}, which {fn.__qualname__} does not take"
    for req in schema["input_schema"].get("required", []):
        assert req in schema["input_schema"]["properties"], f"{name}: required {req} is not a property"


@pytest.mark.parametrize("name", [
    "resolve_player", "get_player_card", "get_prediction", "compare_players", "get_picks", "get_best_squad",
    "optimise", "get_my_squad", "get_my_xi", "explain_prediction", "compare_runs", "compare_predictions",
    "propose_transfers", "set_my_squad", "list_players", "get_fixtures", "get_price_movements",
    "get_league_table", "get_match_stats", "get_actual_points", "get_my_points", "get_prediction_history",
    "get_wildcard_gap", "search_news"])
def test_an_optional_gw_the_description_offers_is_in_the_schema(tools, name):
    schema = next(t for t in tools.tools_schema if t["name"] == name)
    if OPTIONAL_GW.search(schema["description"]):
        assert "gw" in schema["input_schema"]["properties"], f"{name}: the description offers an optional gw the schema lacks"
        fn = tools.available_functions[name]
        assert "gw" in inspect.signature(fn).parameters, f"{name}: the function takes no gw"


def test_the_three_solvers_and_get_my_xi_all_offer_gw(tools):
    for name in ("optimise", "get_picks", "get_my_xi"):
        schema = next(t for t in tools.tools_schema if t["name"] == name)
        assert OPTIONAL_GW.search(schema["description"]), name
        assert schema["input_schema"]["properties"]["gw"]["type"] == "integer", name


def test_the_registered_names_match_the_dispatch_table(tools):
    assert set(_names(tools)) == set(tools.available_functions)
    assert len(_names(tools)) == len(set(_names(tools)))
