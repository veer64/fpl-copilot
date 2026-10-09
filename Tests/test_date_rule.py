"""Part 4 of v4.2 (2026-10-09): the over-eager date question. "Show me the full maths behind Haaland's number" was
answered with "which gameweek?" although the context block made GW6 the obvious one. The prompt now says: if the
block makes the gameweek clear, don't ask; before a deadline "this week", "next game" and "next week" mean the next
deadline's gameweek; ask only when a time could genuinely mean two gameweeks."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_the_prompt_tells_the_model_not_to_ask_when_the_block_is_clear():
    import agent
    p = agent.SYSTEM_PROMPT
    assert "If the context block makes the gameweek clear, don't ask." in p
    assert "Before a deadline, \"this week\", \"next game\" and \"next week\" mean the next deadline's gameweek." in p
    assert ("Ask only when a time could genuinely mean two gameweeks (between a deadline and the end of that gameweek's "
            "matches).") in p
    assert "If a time reference is still ambiguous (e.g. between a deadline and the end of that gameweek), ask which gameweek." not in p
    line = next(l for l in p.splitlines() if "\"This week\" means the next deadline's gameweek" in l)
    assert "don't ask" in line                                   # merged into the line that owns the rule
