"""Citation faithfulness, rubric v2 (Prompt G Part 4, 2026-10-29; checker procedure, eval only).

DEFINITION: judge only the clause the citation is attached to, against EVERY chunk that clause cites; facts in the same
sentence that come from other tools (the FPL card, the context block, the clock) are out of scope.

B2's judge (faithfulness.py, v1) read the WHOLE sentence against the FIRST cited chunk: a sentence that folded in a card
fact ("... and his flag has since been fully cleared") or a second chunk came back "partly" where the user said y
(y-vs-not-y agreement 33.3%, NOT USABLE). v2 cuts the sentence into citation groups: the clause of a group is the text
from the end of the previous group (or the sentence start) to the group's first marker, with a leading connector
("and", "but", ", " ...) dropped; a group is one or more adjacent markers ("[c1][c2]", "[c1], [c2]", "(c1, c2)"). The
judge sees every clause with EVERY passage it cites (id + date), labels the ROW once (y when every clause is said by
its passages, partly when some are, n when none), quoting the phrase it relied on. The labels and the output shape are
v1's; the prompt_version is faithfulness_v2. v1 is untouched (its tests pin it).

citation_rows(raw) is the sheet builder's splitter: a bare citation line ("[c1173]" alone on a line) belongs to the
sentence before it -- B2's builder made it a row of its own."""
import re

from judge import faithfulness as F1
from judge import run_judge as RJ

PROMPT_VERSION_V2 = "faithfulness_v2"
INSTRUCTION_V2 = (
    "You are given one or more CLAIMS from an answer. Each claim is the clause of a sentence that a citation is attached to, "
    "and after it come every passage that claim cites (EVERY article passage, each with its id and date). Does each claim's passages say what "
    "the claim says? Judge only the claim against its own passages: not the rest of the sentence, not whether it is true or "
    "useful, not anything you know from elsewhere. These are out of scope and never a reason for 'partly' or 'n': words that restate FPL's "
    "own flag, status, chance or the time it was checked (they come from the FPL card, not the article), the model's own "
    "figures, and the clock. A citation marker such as [c993] is just the reference to a passage. Your answer is ONE label "
    "for the whole row:\n"
    + "\n".join(f"  {k} = {v}" for k, v in F1.DEFINITIONS.items())
    + "\nWith several claims: y when every claim is said by its passages, partly when some are and some are not, n when none is.")

_MARK = re.compile(r"\[c\d+(?:\s*,?\s*c\d+)*\]|\(c\d+(?:[^)]*?)\)|(?<![\w])c\d+(?![\w])")
_ID = re.compile(r"c\d+")
_LEAD = re.compile(r"^(?:[,;:—–\-\s]*(?:and|but|while|whereas|although|though|so)\b)?[,;:—–\-\s]*", re.I)
_TRAIL = re.compile(r"[\s,;:—–\-]+$")
_BARE_LINE = re.compile(r"^\s*(?:\[c\d+\]\s*|\(c\d+\)\s*|c\d+\s*)+$")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\*\"'(\[])|\n+")


def _groups(sentence):
    """[(start, end, [ids])]: citation markers merged when only whitespace / commas separate them."""
    out = []
    for m in _MARK.finditer(sentence or ""):
        ids = _ID.findall(m.group(0))
        if not ids:
            continue
        if out and not sentence[out[-1][1]:m.start()].strip(" ,;"):
            s, e, prev = out[-1]
            out[-1] = (s, m.end(), prev + [i for i in ids if i not in prev])
        else:
            out.append((m.start(), m.end(), ids))
    return out


def clauses(sentence):
    """[{"clause", "ids"}] -- one entry per citation group, each with the text attributed to it."""
    out, pos = [], 0
    for s, e, ids in _groups(sentence):
        text = (sentence or "")[pos:s]
        text = _LEAD.sub("", text, count=1)
        text = _TRAIL.sub("", text).strip()
        text = text.strip("*").strip()
        out.append({"clause": text, "ids": ids})
        pos = e
    return out


def claims_text(groups):
    """The claims as the judge reads them (no passages): 'CLAIM 1: ... (cites c1, c2)'."""
    return "\n".join(f"CLAIM {k}: {g['clause']} (cites {', '.join(g['ids'])})" for k, g in enumerate(groups, 1))


def build_prompt_v2(sentence, groups, chunks):
    """The user message: the v2 instruction, each claim followed by every passage it cites (id + date), the output format."""
    parts = [INSTRUCTION_V2]
    for k, g in enumerate(groups, 1):
        parts.append(RJ.tag("claim", g["clause"], n=str(k), cites=", ".join(g["ids"])))
        for cid in g["ids"]:
            c = chunks.get(cid) or {}
            parts.append(RJ.tag("article", c.get("text") or "", id=cid, date=c.get("date") or "date unknown"))
    parts.append(F1.OUTPUT_INSTRUCTION)
    return "\n\n".join(parts)


def judge_row_v2(sentence, groups, chunks, model, budget, client=None, conn=None, streak=None):
    """One row (all its claims and passages in one prompt): the same call machinery as v1, prompt_version faithfulness_v2."""
    import time
    from datetime import datetime, timezone
    import llm
    prompt = build_prompt_v2(sentence, groups, chunks)
    row = {"prompt_version": PROMPT_VERSION_V2, "model": model, "label": None, "quote": None, "reason": None, "input_tokens": 0,
           "output_tokens": 0, "usd": 0.0, "latency_s": 0.0, "attempts": 0, "error": None, "prompt_chars": len(prompt),
           "claims": [g["clause"] for g in groups], "at": datetime.now(timezone.utc).isoformat()}
    last_err = None
    for _attempt in (1, 2):
        if not budget.can_call():
            row["error"] = "NOT RUN (cap)"
            return row
        t0 = time.time()
        try:
            text, usage = llm.complete(F1.PURPOSE, RJ.SYSTEM, prompt, model, RJ.JUDGE_MAX_TOKENS.get(model, RJ.DEFAULT_MAX_TOKENS),
                                       temperature=0, client=client, conn=conn, prompt_version=PROMPT_VERSION_V2)
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
        parsed = F1.parse_label(text)
        if parsed is None:
            last_err = f"ERROR: unparseable output: {text[:120]!r}"
            continue
        row["label"], row["quote"], row["reason"] = parsed
        return row
    row["error"] = last_err or "ERROR"
    return row


def judge_rows_v2(rows, chunks, model, budget, client=None, conn=None):
    """Every row against ALL its cited chunks, clause by clause; a row with a missing chunk is an ERROR row naming it.
    Output rows carry the row's ids and the judgement only (never a user label or note)."""
    out, streak = [], {"n": 0, "sig": None}
    for r in rows:
        ids = list(r.get("cited_chunk_ids") or [])
        sentence = r.get("sentence") or ""
        groups = clauses(sentence)
        if not groups and ids:                              # a marker shape the cutter did not see: one clause, all ids
            groups = [{"clause": sentence.strip(), "ids": ids}]
        wanted = [i for g in groups for i in g["ids"]]
        for i in ids:                                       # ids the row lists but the text no longer shows: still cited
            if i not in wanted:
                groups[-1]["ids"].append(i) if groups else groups.append({"clause": sentence.strip(), "ids": [i]})
                wanted.append(i)
        base = {"row": r.get("row"), "answer_id": r.get("answer_id"), "question_id": r.get("question_id"), "cited_chunk_ids": ids}
        missing = [i for i in wanted if i not in chunks]
        if missing:
            out.append({**base, "prompt_version": PROMPT_VERSION_V2, "label": None, "quote": None, "reason": None, "usd": 0.0,
                        "error": "ERROR: cited chunk not found: " + ", ".join(missing)})
            continue
        out.append({**base, **judge_row_v2(sentence, groups, chunks, model, budget, client=client, conn=conn, streak=streak)})
    return out


def citation_rows(raw):
    """[{"sentence", "ids"}] for a raw reply: one row per sentence / line that carries a citation; a line that is nothing
    but citation markers is appended to the sentence before it (the sheet builder's fix)."""
    parts = [p.strip() for p in _SENT_SPLIT.split(raw or "") if p and p.strip()]
    merged = []
    for p in parts:
        if _BARE_LINE.match(p) and merged:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    out = []
    for sent in merged:
        ids = []
        for i in _ID.findall(" ".join(m.group(0) for m in _MARK.finditer(sent))):
            if i not in ids:
                ids.append(i)
        if ids:
            out.append({"sentence": sent, "ids": ids})
    return out
