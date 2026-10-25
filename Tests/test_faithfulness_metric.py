"""Citation faithfulness, the judge metric for the RAG answer eval (Prompt B2, 2026-10-25; eval/judge/faithfulness.py).

The judge had no citation-faithfulness metric (M4 is "availability first"), so one is added with EXACTLY the user's
definitions: y = the article says it (different wording is fine); partly = some of it is in the article, some isn't;
n = the article doesn't say it, or says something different. The judge sees, per row, the sentence as the agent wrote it
and the cited chunk's text with its date -- nothing else (no question, no other chunks, no label) -- and must quote the
chunk phrase it relied on, or say "none". Offline: llm.complete is mocked."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
from judge import faithfulness as F                        # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

CHUNK = {"id": "c993", "text": "De Ligt is getting there, Carrick said. He will be assessed on Friday before the squad is named.",
         "date": "2026-10-08", "source": "Man Utd official site", "headline": "De Ligt shares positive recovery update"}


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


def test_the_definitions_are_the_users_words_and_the_prompt_carries_only_the_sentence_and_the_chunk():
    assert F.DEFINITIONS == {"y": "the article says it (different wording is fine)",
                             "partly": "some of it is in the article, some isn't",
                             "n": "the article doesn't say it, or says something different"}
    p = F.build_prompt("He will be assessed on Friday [c993].", CHUNK)
    for d in F.DEFINITIONS.values():
        assert d in p
    assert "He will be assessed on Friday [c993]." in p and CHUNK["text"] in p and "2026-10-08" in p
    assert "question" not in p.lower().replace("the one question", "")      # no user question, no label, no other chunk
    assert "label" not in p.lower().split("answer with strict json")[0]
    assert '"quote"' in p and '"none"' in p


def test_parse_label_accepts_y_partly_n_with_a_quote_and_rejects_the_rest():
    assert F.parse_label('{"quote": "assessed on Friday", "label": "y", "reason": "same fact"}') == ("y", "assessed on Friday", "same fact")
    assert F.parse_label('text before {"quote": "none", "label": "n", "reason": "not there"} after') == ("n", "none", "not there")
    assert F.parse_label('{"quote": "x", "label": "PASS", "reason": "r"}') is None
    assert F.parse_label('{"label": "y", "reason": "r"}') is None             # the quote is required
    assert F.parse_label("not json") is None


def test_concept_example_assessed_on_friday_vs_out_for_three_weeks_is_n(monkeypatch):
    fake = _Fake(['{"quote": "none", "label": "n", "reason": "the article says assessed on Friday, not out for three weeks"}'])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = F.judge_row("He is out for three weeks [c993].", CHUNK, "claude-opus-5-5", RJ.Budget(10, 5.0))
    assert row["label"] == "n" and row["quote"] == "none" and row["error"] is None
    assert fake.last["system"] == RJ.SYSTEM and fake.last["temperature"] == 0 and fake.last["purpose"] == F.PURPOSE
    assert "out for three weeks" in fake.last["user"] and CHUNK["text"] in fake.last["user"]
    assert "the article doesn't say it" in fake.last["user"]                   # the user's definition, verbatim


def test_concept_example_assessed_on_friday_is_y(monkeypatch):
    fake = _Fake(['{"quote": "He will be assessed on Friday", "label": "y", "reason": "the same fact, other words"}'])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = F.judge_row("The club says he'll be assessed on Friday [c993].", CHUNK, "claude-opus-5-5", RJ.Budget(10, 5.0))
    assert row["label"] == "y" and row["quote"] == "He will be assessed on Friday"
    assert row["input_tokens"] == 500 and row["usd"] == RJ.price("claude-opus-5-5", 500, 30)


def test_concept_example_supported_and_invented_parts_is_partly(monkeypatch):
    fake = _Fake(['{"quote": "He will be assessed on Friday", "label": "partly", "reason": "the assessment is there; the hamstring is not"}'])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = F.judge_row("He'll be assessed on Friday after his hamstring scan [c993].", CHUNK, "claude-opus-5-5", RJ.Budget(10, 5.0))
    assert row["label"] == "partly"


def test_malformed_output_is_retried_once_then_error_and_the_cap_stops_a_call(monkeypatch):
    fake = _Fake(["not json", "still not json"])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = F.judge_row("x [c993].", CHUNK, "claude-opus-5-5", RJ.Budget(10, 5.0))
    assert row["label"] is None and row["error"].startswith("ERROR: unparseable") and fake.calls == 2
    fake = _Fake(['{"quote": "none", "label": "n", "reason": "r"}'])
    monkeypatch.setattr(llm, "complete", fake.complete)
    row = F.judge_row("x [c993].", CHUNK, "claude-opus-5-5", RJ.Budget(10, 0.0))
    assert row["error"] == "NOT RUN (cap)" and fake.calls == 0


def test_auth_error_stops_the_run(monkeypatch):
    fake = _Fake([llm.LLMAuthError("HTTP 401", 401, "authentication_error")])
    monkeypatch.setattr(llm, "complete", fake.complete)
    with pytest.raises(RJ.StopRun):
        F.judge_row("x [c993].", CHUNK, "claude-opus-5-5", RJ.Budget(10, 5.0))


def test_judge_rows_scores_every_row_and_carries_only_ids_back(monkeypatch):
    fake = _Fake(['{"quote": "a", "label": "y", "reason": "r"}', '{"quote": "none", "label": "n", "reason": "r"}'])
    monkeypatch.setattr(llm, "complete", fake.complete)
    rows = [{"row": 1, "answer_id": "rag:6#r1", "sentence": "s1 [c993].", "cited_chunk_ids": ["c993"]},
            {"row": 2, "answer_id": "rag:6#r2", "sentence": "s2 [c993].", "cited_chunk_ids": ["c993"]}]
    out = F.judge_rows(rows, {"c993": CHUNK}, "claude-opus-5-5", RJ.Budget(10, 5.0))
    assert [o["label"] for o in out] == ["y", "n"] and [o["row"] for o in out] == [1, 2]
    assert "label_user" not in out[0] and "note" not in out[0]
