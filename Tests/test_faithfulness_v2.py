"""Citation faithfulness rubric v2 (Prompt G Part 4, 2026-10-29; eval/judge/faithfulness.py; checker procedure, eval only).

DEFINITION: judge only the clause the citation is attached to, against EVERY chunk that clause cites; facts in the same
sentence that come from other tools (the FPL card, the context block, the clock) are out of scope. B2's judge (v1) read
the whole sentence against the FIRST cited chunk, so a sentence that folded in a card fact or a second chunk came back
"partly" where the user said y (33.3% y-vs-not-y agreement, NOT USABLE). v1 stays as it was (its own tests pin it);
v2 is the rubric of record. Offline: llm.complete is mocked."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
from judge import faithfulness as F                        # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

# B2 row 1 (rag:17 run 2, user label y; v1 said partly because "fully cleared" is the FPL card's fact, not the article's)
ROW1 = "The Liverpool fitness update from 15 October left the door open for his return [c1173], and his flag has since been fully cleared."
# B2 row 2 (rag:18 run 1, user y; v1 partly): the whole sentence is the clause and FPL's flag words are out of scope
ROW2 = "**FPL's official flag (as of 23 Oct 17:21 UTC): fully available, no injury flag, 100% chance of playing in GW8.** [c1218]"
# a two-chunk row (B2 rows 12 / 19 cite c1175 and c1176 together)
ROW3 = "Hincapié trained with the group on Thursday and is in contention for Sunday [c1175][c1176]."
CH = {"c1173": {"id": "c1173", "text": "I leave the chance open this time, yes. We will see how he is on Friday.", "date": "2026-10-15"},
      "c1218": {"id": "c1218", "text": "Gakpo (LIV, MID) Status: available. 100% chance of playing.", "date": "2026-10-23"},
      "c1175": {"id": "c1175", "text": "Hincapie trained with the group on Thursday.", "date": "2026-10-16"},
      "c1176": {"id": "c1176", "text": "The defender is in contention for Sunday's match.", "date": "2026-10-16"}}


class _Fake:
    def __init__(self, replies):
        self.replies, self.calls, self.last = list(replies), 0, None

    def complete(self, purpose, system, user, model, max_tokens, temperature=0, **kw):
        self.calls += 1
        self.last = {"purpose": purpose, "system": system, "user": user, "model": model, "max_tokens": max_tokens, "temperature": temperature, **kw}
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item, {"input_tokens": 500, "output_tokens": 30, "attempts": 1, "stop_reason": "end_turn"}


# ---------------------------------------------------------------- the attributed clause
def test_the_clause_stops_at_the_citation_and_the_card_fact_after_it_is_out_of_scope():
    groups = F.clauses(ROW1)
    assert groups == [{"clause": "The Liverpool fitness update from 15 October left the door open for his return", "ids": ["c1173"]}]
    prompt = F.build_prompt_v2(ROW1, groups, CH)
    assert "left the door open for his return" in prompt and "fully cleared" not in prompt.split("<article", 1)[0].split("</claim")[-1] if "<claim" in prompt else True
    assert "fully cleared" not in F.claims_text(groups)


def test_a_card_fact_sentence_is_one_clause_and_the_instruction_puts_fpl_words_out_of_scope():
    groups = F.clauses(ROW2)
    assert len(groups) == 1 and groups[0]["ids"] == ["c1218"] and "100% chance of playing in GW8" in groups[0]["clause"]
    assert "FPL" in F.INSTRUCTION_V2 and "out of scope" in F.INSTRUCTION_V2 and "every passage" in F.INSTRUCTION_V2.lower()
    assert F.PROMPT_VERSION_V2 == "faithfulness_v2" and F.PROMPT_VERSION == "faithfulness_v1"


def test_a_two_chunk_clause_cites_both_and_the_prompt_carries_both_passages():
    groups = F.clauses(ROW3)
    assert groups == [{"clause": "Hincapié trained with the group on Thursday and is in contention for Sunday", "ids": ["c1175", "c1176"]}]
    prompt = F.build_prompt_v2(ROW3, groups, CH)
    assert "Hincapie trained with the group on Thursday." in prompt and "in contention for Sunday's match" in prompt
    assert prompt.count("<article") == 2 and "c1175" in prompt and "c1176" in prompt


def test_two_citation_groups_give_two_claims_each_with_its_own_chunks():
    s = "Isak missed the Brentford game [c1173], and Slot said he would be assessed on Friday [c1175], [c1176]."
    groups = F.clauses(s)
    assert [g["ids"] for g in groups] == [["c1173"], ["c1175", "c1176"]]
    assert groups[0]["clause"] == "Isak missed the Brentford game"
    assert groups[1]["clause"] == "Slot said he would be assessed on Friday"


def test_judge_rows_v2_hands_every_cited_chunk_and_labels_once_per_row(monkeypatch):
    fake = _Fake(['{"quote": "I leave the chance open", "label": "y", "reason": "the article leaves the return open"}'])
    monkeypatch.setattr(llm, "complete", fake.complete)          # the v1 tests mock llm.complete the same way
    budget = RJ.Budget(max_calls=10, max_usd=1.0)
    rows = [{"row": 1, "answer_id": "rag:17#r2", "question_id": "rag:17", "sentence": ROW1, "cited_chunk_ids": ["c1173"]}]
    out = F.judge_rows_v2(rows, CH, "claude-opus-5-5", budget)
    assert out[0]["label"] == "y" and out[0]["cited_chunk_ids"] == ["c1173"] and out[0]["prompt_version"] == "faithfulness_v2"
    assert fake.last["prompt_version"] == "faithfulness_v2" and fake.last["temperature"] == 0
    assert "fully cleared" not in fake.last["user"].split("<article")[0].split("CLAIM")[-1]
    missing = F.judge_rows_v2([{"row": 2, "sentence": ROW3, "cited_chunk_ids": ["c1175", "c9999"]}], CH, "claude-opus-5-5", budget)
    assert missing[0]["error"].startswith("ERROR: cited chunk not found") and "c9999" in missing[0]["error"] and fake.calls == 1


# ---------------------------------------------------------------- the sheet builder: a bare citation line stays with its sentence
def test_a_bare_citation_line_belongs_to_the_sentence_before_it():
    raw = "**Isak is fit.** He trained fully on Thursday.\n[c1173]\nSlot confirmed it [c1175].\n- bullet one [c1176]\n[c1218]"
    rows = F.citation_rows(raw)
    assert rows == [{"sentence": "**Isak is fit.** He trained fully on Thursday. [c1173]", "ids": ["c1173"]},   # the bold unit is one sentence to the splitter
                    {"sentence": "Slot confirmed it [c1175].", "ids": ["c1175"]},
                    {"sentence": "- bullet one [c1176] [c1218]", "ids": ["c1176", "c1218"]}]
