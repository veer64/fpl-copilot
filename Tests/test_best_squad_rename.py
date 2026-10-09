"""Part 3 of v4.2 (2026-10-09): get_best_squad -> best_squad_from_scratch, exactly as optimise became
build_squad_from_scratch -- the schema name, the dispatch key, the description and the prompt's reference; the
Python function keeps its name; the tool count stays 24."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_the_best_squad_tool_is_named_for_what_it_does():
    import agent
    names = [t["name"] for t in agent.tools_schema]
    assert "best_squad_from_scratch" in names and "get_best_squad" not in names and len(names) == 24
    schema = next(t for t in agent.tools_schema if t["name"] == "best_squad_from_scratch")
    assert schema["description"].startswith("The best brand-new 15 from scratch with a full £100m, ignoring the user's squad. "
                                            "For the user's own squad use propose_transfers or get_my_xi.")
    assert "budget" in schema["input_schema"]["properties"]
    fn = agent.available_functions["best_squad_from_scratch"]
    assert (fn.__module__, fn.__qualname__) == ("model_tools", "get_best_squad")
    assert "get_best_squad" not in agent.available_functions
    p = agent.SYSTEM_PROMPT
    assert "`get_best_squad`" not in p and "`best_squad_from_scratch`" in p
