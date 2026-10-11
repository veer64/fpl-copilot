"""optimise:7 regression (2026-10-11): "What's the best squad for gameweek 10?" went to best_squad_from_scratch
(no gw argument exists) on the smoke-fix tree -- 0 of 3 at e71490f, 4 of 4 right on ddf9022 -- and the model
then told the user GW10 was "outside the model's range" although the run covered GW6-11, and offered GW7's squad
instead: an answer about the wrong gameweek. Nothing in the two from-scratch descriptions said which tool a
SPECIFIC gameweek belongs to: best_squad_from_scratch's name matches "best squad", build_squad_from_scratch's
description reads as the constrained variant ("force players in, ban players, or change the budget").

The fix is text in the descriptions, pinned here: best_squad_from_scratch says it has no gw and names the two
tools that take one; build_squad_from_scratch claims the "best squad for gameweek N" wording. The schemas are
unchanged (no gw on best_squad_from_scratch; gw on build_squad_from_scratch and get_picks), and the eval spec
(build_squad_from_scratch|get_picks) was not touched. No network: agent is imported with a dummy key.
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import agent  # noqa: E402

TOOLS = {t["name"]: t for t in agent.tools_schema}


def test_best_squad_from_scratch_says_it_has_no_gw_and_names_the_tools_that_do():
    d = TOOLS["best_squad_from_scratch"]["description"]
    assert "gw" not in TOOLS["best_squad_from_scratch"]["input_schema"]["properties"]
    assert "No gw" in d, d
    assert "build_squad_from_scratch with gw=N" in d and "get_picks with gw=N" in d, d
    assert "best squad for gameweek N" in d, d
    # a gameweek inside the run's range is never declared out of range by the model itself
    assert "never say a gameweek is out of range" in d, d
    # the schema-consistency rule: no "optional gw" promise on a tool without gw
    assert not re.search(r"\boptional\s+`?gw\b", d, re.I)


def test_build_squad_from_scratch_claims_the_specific_gameweek_wording():
    d = TOOLS["build_squad_from_scratch"]["description"]
    assert "gw" in TOOLS["build_squad_from_scratch"]["input_schema"]["properties"]
    assert "best squad for gameweek N" in d, d
    assert "constraints are optional" in d, d
    # the constrained from-scratch request goes here too, even with a doubtful id: the tool refuses and says why
    assert "ban player X from the squad" in d and "let the tool refuse" in d, d


def test_get_picks_still_takes_gw_and_the_spec_tools_are_unchanged():
    assert "gw" in TOOLS["get_picks"]["input_schema"]["properties"]
    assert len(agent.tools_schema) == 24
