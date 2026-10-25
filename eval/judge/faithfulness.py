"""Citation faithfulness -- the judge metric for the RAG answer eval (Prompt B2, 2026-10-25).

One row = one sentence of an agent reply that carries a citation, and the chunk it cites. The judge sees the sentence as
the agent wrote it and the cited chunk's text with its date -- nothing else: no user question, no other chunk, no label --
and answers with one of the user's three labels, quoting the chunk phrase it relied on (or "none"):

    y      = the article says it (different wording is fine)
    partly = some of it is in the article, some isn't
    n      = the article doesn't say it, or says something different

Same machinery as run_judge.judge_one: llm.complete with the examiner system prompt, temperature 0, the model's max
tokens, one retry on unparseable output, ERROR after; the budget's cap is checked before every call; an auth error or the
credit mark stops the run (StopRun). Rows are judged in the order given; the output rows carry only the row's ids, the
label, the quote, the reason and the cost -- never a user label or note (the comparison happens elsewhere).
"""
import json
import time
from datetime import datetime, timezone

import llm
from judge import run_judge as RJ

PURPOSE = "judge_faithfulness"
PROMPT_VERSION = "faithfulness_v1"
LABELS = ("y", "partly", "n")
DEFINITIONS = {
    "y": "the article says it (different wording is fine)",
    "partly": "some of it is in the article, some isn't",
    "n": "the article doesn't say it, or says something different",
}
INSTRUCTION = ("You are given ONE sentence from an answer and the ONE article passage it cites, with the passage's date. Does the "
               "article say what the sentence says? Judge only the sentence against the passage: not whether the sentence is true "
               "or useful, not anything you know from elsewhere. A citation marker such as [c993] in the sentence is just the "
               "reference to this passage. Your answer is one of:\n"
               + "\n".join(f"  {k} = {v}" for k, v in DEFINITIONS.items()))
OUTPUT_INSTRUCTION = ('Answer with strict JSON only, in this order: {"quote": "<the exact phrase of the passage you relied on>", '
                      '"label": "y" | "partly" | "n", "reason": "<one sentence>"}. When nothing in the passage supports the sentence, '
                      '"quote" is the word "none".')


def build_prompt(sentence, chunk):
    """The user message: the instruction with the three definitions, the sentence, the cited passage with its date."""
    date = chunk.get("date") or "date unknown"
    return "\n\n".join([INSTRUCTION,
                        RJ.tag("sentence", sentence or ""),
                        RJ.tag("article", chunk.get("text") or "", date=date),
                        OUTPUT_INSTRUCTION])


def parse_label(text):
    """(label, quote, reason) from the model's text, or None when it is not the strict JSON asked for."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(s[i:j + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    label, quote, reason = obj.get("label"), obj.get("quote"), obj.get("reason")
    if label not in LABELS or not isinstance(quote, str) or not isinstance(reason, str):
        return None
    return label, quote, reason


def judge_row(sentence, chunk, model, budget, client=None, conn=None, streak=None):
    """One (sentence, chunk): build, call, parse; one retry on unparseable output; ERROR after; NOT RUN (cap) before a
    call the budget cannot afford. Returns the judge row (label, quote, reason, tokens, usd, error)."""
    prompt = build_prompt(sentence, chunk)
    row = {"chunk_id": chunk.get("id"), "model": model, "label": None, "quote": None, "reason": None, "input_tokens": 0,
           "output_tokens": 0, "usd": 0.0, "latency_s": 0.0, "attempts": 0, "error": None, "prompt_chars": len(prompt),
           "at": datetime.now(timezone.utc).isoformat()}
    last_err = None
    for _attempt in (1, 2):
        if not budget.can_call():
            row["error"] = "NOT RUN (cap)"
            return row
        t0 = time.time()
        try:
            text, usage = llm.complete(PURPOSE, RJ.SYSTEM, prompt, model, RJ.JUDGE_MAX_TOKENS.get(model, RJ.DEFAULT_MAX_TOKENS),
                                       temperature=0, client=client, conn=conn, prompt_version=PROMPT_VERSION)
        except llm.LLMAuthError as e:
            raise RJ.StopRun(f"auth error, run stopped: {e}") from e
        except llm.LLMError as e:
            msg = str(e)
            row["latency_s"] = round(row["latency_s"] + time.time() - t0, 2)
            row["attempts"] += 1
            budget.calls += 1
            if any(m in msg.lower() for m in RJ.FATAL_MARKS):
                raise RJ.StopRun(f"credit exhausted, run stopped: {msg[:120]}") from e
            sig = (e.status, e.error_type)
            if streak is not None:
                streak["n"] = streak["n"] + 1 if streak.get("sig") == sig else 1
                streak["sig"] = sig
                if streak["n"] >= 3:
                    raise RJ.StopRun(f"the same error three times in a row: {sig}") from e
            row["error"] = f"ERROR: {msg[:200]}"
            return row
        row["latency_s"] = round(row["latency_s"] + time.time() - t0, 2)
        row["attempts"] += int(usage.get("attempts") or 1)
        row["input_tokens"] += int(usage.get("input_tokens") or 0)
        row["output_tokens"] += int(usage.get("output_tokens") or 0)
        c = budget.add(model, usage)
        if c is not None:
            row["usd"] = round(row["usd"] + c, 6)
        if streak is not None:
            streak["n"], streak["sig"] = 0, None
        if usage.get("stop_reason") in llm.REPLY_ERRORS:
            last_err = f"ERROR: reply {llm.REPLY_ERRORS[usage['stop_reason']]}"
            continue
        parsed = parse_label(text)
        if parsed is None:
            last_err = f"ERROR: unparseable output: {text[:120]!r}"
            continue
        row["label"], row["quote"], row["reason"] = parsed
        return row
    row["error"] = last_err or "ERROR"
    return row


def judge_rows(rows, chunks, model, budget, client=None, conn=None):
    """Every row ({row, answer_id, sentence, cited_chunk_ids, ...}) against its FIRST cited chunk (chunks: {id: chunk});
    a row whose chunk is missing gets an ERROR row. Output rows carry the row's ids and the judgement only."""
    out, streak = [], {"n": 0, "sig": None}
    for r in rows:
        ids = r.get("cited_chunk_ids") or []
        chunk = chunks.get(ids[0]) if ids else None
        base = {"row": r.get("row"), "answer_id": r.get("answer_id"), "question_id": r.get("question_id"), "cited_chunk_ids": ids}
        if chunk is None:
            out.append({**base, "chunk_id": ids[0] if ids else None, "label": None, "quote": None, "reason": None, "usd": 0.0,
                        "error": "ERROR: cited chunk not found"})
            continue
        out.append({**base, **judge_row(r.get("sentence") or "", chunk, model, budget, client=client, conn=conn, streak=streak)})
    return out
