"""LLM judge Part D (2026-10-12): J6 a WRONG count the judge lists items for is checked by code (its own list can
only confirm or contradict it); J7 the sentences the agent is required to say are allowed facts and cannot drift
from the prompt / tool sources; J8 the eval runner's --judge hook judges the TRUSTED metrics only, re-judges a FAIL
twice, and never spends past its own cap (llm mocked)."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
from judge import metrics as M                             # noqa: E402
from judge import number_claims as N                       # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

SRC = ["'name': 'Bryan Mbeumo', 'team': 'Man Utd'", "'name': 'Bruno Borges Fernandes', 'team': 'Man Utd'", "'name': 'Iliman Ndiaye', 'team': 'Man City'"]


# ------------------------------------------------------------------ J6
def _claim(text, value):
    return {"id": "c1", "text": text, "value": float(value), "decimals": 0, "start": 0, "end": 1, "context": text, "about": False}


def test_a_wrong_count_whose_listed_items_contradict_the_claim_stays_wrong_with_the_count_recorded():
    item = {"id": "c1", "number": 3, "about": "Man Utd players", "type": "WRONG", "quote": "", "why": "only two",
            "items": [{"item": "Mbeumo", "quote": "'name': 'Bryan Mbeumo', 'team': 'Man Utd'"},
                      {"item": "Bruno", "quote": "'name': 'Bruno Borges Fernandes', 'team': 'Man Utd'"}]}
    rows, _, _ = N.verify([_claim("three", 3)], [item], SRC)
    assert rows[0]["final"] == "WRONG" and rows[0]["code"]["count_ok"] is False


def test_a_wrong_count_whose_listed_items_equal_the_claim_is_overridden_to_count():
    item = {"id": "c1", "number": 2, "about": "Man Utd players", "type": "WRONG", "quote": "", "why": "I think it is three",
            "items": [{"item": "Mbeumo", "quote": "'name': 'Bryan Mbeumo', 'team': 'Man Utd'"},
                      {"item": "Bruno", "quote": "'name': 'Bruno Borges Fernandes', 'team': 'Man Utd'"}]}
    rows, _, _ = N.verify([_claim("two", 2)], [item], SRC)
    assert rows[0]["final"] == "COUNT" and rows[0]["code"]["count_ok"] is True and rows[0]["why"].startswith("code:")
    bad = dict(item, items=[{"item": "x", "quote": "not in any source"}, {"item": "y", "quote": "nor this"}])
    rows, _, _ = N.verify([_claim("two", 2)], [bad], SRC)
    assert rows[0]["final"] == "WRONG"                                     # unquoted items cannot rescue a WRONG


def test_the_instructions_ask_for_items_on_a_wrong_count():
    assert "For a count or word-number claim that is WRONG, still fill \"items\"" in N.INSTRUCTIONS


# ------------------------------------------------------------------ J7
def test_every_required_sentence_is_in_its_source_and_in_the_allowed_facts():
    prompt = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    for src, s in RJ.REQUIRED_SENTENCES:
        text = prompt if src == "prompt" else (REPO / src).read_text(encoding="utf-8")
        assert s in text, (src, s)
    facts = RJ.allowed_general_facts()
    assert "Sentences the agent is REQUIRED to say" in facts
    assert "Our model doesn't account for bonus points" in facts and "any Premier League side can beat anyone" in facts
    assert "FPL allows at most <n> <n>; you asked to force <n>" in facts and "These figures are for GW<n>, which has already started" in facts
    assert "never unsupported claims" in M.metric_text("M3a")
