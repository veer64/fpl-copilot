"""RAG answer eval, run half (Prompt B1, 2026-10-25): the code checks over one agent answer and the adapter that lets
eval/run_agent_evals.py run eval/rag_eval/answer_questions_v1.json.

The question file names 15 questions from eval/rag_eval/questions_v1.json, re-checked against the data AS OF the frozen
clock (2026-10-23T20:00:00Z), each with its situation and the expected facts (FPL flag with its time, the chunk ids and
dates a correct answer can draw on). The runner answers them with --now; this module then reads each record's tool log
(the question turn's calls: tool, input, output) and its RAW reply (c<id> citation tokens) and applies:

  C1  search_news called. An ambiguous question may skip it when the reply asks which player.
  C2  every cited id is among the ids search_news returned in that turn, over all its calls.
  C3  FPL's flag (status / chance) WITH ITS TIME (a date, "as of", "last checked", "<n> days ago") appears before the
      first news citation -- player questions only (current, name variant, conflict, stale, no news); without a
      citation the flag with its time still has to be there.
  S-nonews  (no-news questions) zero citations AND the reply says there is no recent news AND gives FPL's flag.
  S-ambig   (ambiguous questions) zero citations AND the reply asks which player AND gives no availability verdict.

Faithfulness (does the cited chunk say what the sentence says) and M3a are not judged here: the blind sheet goes to the
user, the judge runs in B2. A question passes a check only when every run of it passes (summarise).

CLI:  python eval/rag_eval/answer_eval.py --build-workbook            (answer_questions_v1.json -> .xlsx for the runner)
      python eval/rag_eval/answer_eval.py --check results.jsonl --out checks.json
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import news_search as NS                                  # noqa: E402  (cited_ids, citation_violations, the token regex)
from judge import metrics as M                            # noqa: E402  (parse_output: a tool output string -> dict)

QUESTIONS = REPO / "eval" / "rag_eval" / "answer_questions_v1.json"
WORKBOOK = REPO / "eval" / "rag_eval" / "answer_questions_v1.xlsx"
SHEET = "rag"
PLAYER_SITUATIONS = ("player_current_news", "name_variant", "conflict", "stale", "no_news")
CHECKS = ("C1", "C2", "C3", "S_nonews", "S_ambig")

# FPL's flag: "FPL ... flag / status / chance / available / injured / doubtful / suspended / 75%", or a bare "<n>% chance"
# / "chance of playing"; its time: a day-month, an ISO date, "as of", "last checked", "<n> hours/days ago", a weekday.
FLAG_RE = re.compile(r"(?i)(\bFPL\b[^.\n]{0,220}?\b(flag|status|chance|availab\w*|injur\w*|doubt\w*|suspend\w*|unavailab\w*|\d{1,3}\s?%)"
                     r"|\b\d{1,3}\s?%\s+chance\b|\bchance of playing\b)")
TIME_RE = re.compile(r"(?i)(\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b\d{4}-\d{2}-\d{2}\b|\bas of\b"
                     r"|\blast checked\b|\b\d+\s+(hours?|days?)\s+ago\b|\b(mon|tues|wednes|thurs|fri|satur|sun)day\b)")
NONEWS_RE = re.compile(r"(?i)(\bno (recent |new |fresh |other |current |club |press )?(news|articles?|reports?|items?|stories|coverage|updates?|results?|mentions?)\b"
                       r"|\bnothing (recent|new|newer|in the news|on record|reported)\b|\bhaven'?t (found|seen|got|come across) any\b"
                       r"|\bnot (found|seen|turned up) any\b|\bnot in the news\b|\bno (recent |new )?(press|club) (update|coverage)\b)")
ASK_RE = re.compile(r"(?i)(\bwhich (one|player|of (them|these|the two)|do you mean|.{0,40}do you mean)\b|\bdo you mean\b|\btwo players\b"
                    r"|\bmore than one player\b|\bclarify\b|\bcould you (confirm|specify|tell me which)\b|\bplease (confirm|specify)\b|\blet me know which\b)")
VERDICT_RE = re.compile(r"(?i)\b(is|isn'?t|is not|looks|should be|will be|remains|he'?s)\s+(fit|available|injured|out|a doubt|doubtful|suspended|unavailable)\b")
WINDOW = 250


# ---- reading a record -----------------------------------------------------------------------------------------------

def question_calls(rec):
    """The question turn's calls (the last turn), each {tool, input, output}."""
    turns = rec.get("turns") or []
    if turns:
        return list(turns[-1].get("calls") or [])
    return list(rec.get("calls") or [])


def _parse(output):
    if isinstance(output, dict):
        return output
    try:
        out = M.parse_output(output)
    except Exception:                                      # noqa: BLE001 -- an unparsable output is an empty dict here
        return {}
    return out if isinstance(out, dict) else {}


def search_calls(rec):
    return [c for c in question_calls(rec) if c.get("tool") == "search_news"]


def returned_ids(rec):
    """Every result id search_news returned this turn, over all its calls, first-seen order."""
    out = []
    for c in search_calls(rec):
        for r in _parse(c.get("output")).get("results") or []:
            cid = str((r or {}).get("id") or "")
            if cid and cid not in out:
                out.append(cid)
    return out


def cited(rec):
    return NS.cited_ids(rec.get("raw_reply") or "")


def flag_position(text):
    """Start of the first FPL-flag mention that has a time within WINDOW characters; None when there is none."""
    for m in FLAG_RE.finditer(text or ""):
        window = text[max(0, m.start() - WINDOW): m.end() + WINDOW]
        if TIME_RE.search(window):
            return m.start()
    return None


def first_citation_position(text):
    m = NS._CITE_TOKEN.search(text or "")
    return m.start() if m else None


# ---- the checks ---------------------------------------------------------------------------------------------------------

def check_record(rec, q):
    """{check: {applicable, pass, why, ...evidence}} for one runner record and its question (situation, players, checks)."""
    raw = rec.get("raw_reply") or ""
    situation = q.get("situation")
    flags = q.get("checks") or {}
    searched = search_calls(rec)
    ret, cit = returned_ids(rec), cited(rec)
    asks = bool(ASK_RE.search(raw))
    out = {}
    c1 = bool(searched) or (situation == "ambiguous" and asks)
    out["C1"] = {"applicable": True, "pass": c1, "n_search_calls": len(searched),
                 "why": "" if c1 else "search_news was not called" + (" and the reply does not ask which player" if situation == "ambiguous" else "")}
    violations = NS.citation_violations(cit, ret)
    out["C2"] = {"applicable": True, "pass": not violations, "cited": cit, "returned": ret, "violations": violations,
                 "why": "" if not violations else f"cited {violations} but search_news returned {ret or 'nothing'} this turn"}
    c3_applicable = bool(flags.get("C3", situation in PLAYER_SITUATIONS))
    fp, cp = flag_position(raw), first_citation_position(raw)
    if not c3_applicable:
        out["C3"] = {"applicable": False, "pass": None, "why": "not a player question"}
    else:
        if fp is None:
            ok, why = False, "no FPL flag (status / chance) with its time in the reply"
        elif cp is not None and cp < fp:
            ok, why = False, f"the first citation (at {cp}) comes before the FPL flag (at {fp})"
        else:
            ok, why = True, ""
        out["C3"] = {"applicable": True, "pass": ok, "flag_at": fp, "first_citation_at": cp, "why": why}
    if situation == "no_news":
        says_none, has_flag = bool(NONEWS_RE.search(raw)), bool(FLAG_RE.search(raw))
        why = []
        if cit:
            why.append(f"a citation {cit} where no news exists")
        if not says_none:
            why.append("does not say there is no recent news")
        if not has_flag:
            why.append("gives no FPL flag")
        out["S_nonews"] = {"applicable": True, "pass": not why, "cited": cit, "says_no_news": says_none, "gives_flag": has_flag, "why": "; ".join(why)}
    else:
        out["S_nonews"] = {"applicable": False, "pass": None, "why": "not a no-news question"}
    if situation == "ambiguous":
        verdict = bool(FLAG_RE.search(raw) or VERDICT_RE.search(raw))
        why = []
        if cit:
            why.append(f"a citation {cit}")
        if not asks:
            why.append("does not ask which player")
        if verdict:
            why.append("answers for one player (an availability verdict or flag)")
        out["S_ambig"] = {"applicable": True, "pass": not why, "cited": cit, "asks_which": asks, "answers_for_one": verdict, "why": "; ".join(why)}
    else:
        out["S_ambig"] = {"applicable": False, "pass": None, "why": "not an ambiguous question"}
    return out


def summarise(records, questions):
    """{check: {passing, applicable}} over questions: a question is applicable to a check when the check applies to it, and
    passes only when every one of its records passes."""
    by_q = defaultdict(list)
    for rec in records:
        if rec.get("id") in questions:
            by_q[rec["id"]].append(check_record(rec, questions[rec["id"]]))
    table = {c: {"passing": 0, "applicable": 0} for c in CHECKS}
    for qid, results in by_q.items():
        for c in CHECKS:
            if results and all(r[c]["applicable"] for r in results):
                table[c]["applicable"] += 1
                if all(r[c]["pass"] for r in results):
                    table[c]["passing"] += 1
    return table


# ---- the question file and the runner workbook --------------------------------------------------------------------------

def load_questions(path=QUESTIONS):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {q["id"]: q for q in doc["questions"]}


def to_workbook(src=QUESTIONS, out=WORKBOOK):
    """answer_questions_v1.json -> a workbook in the runner's column order (sheet 'rag', one row per question; must call
    = search_news, or 'any' for an ambiguous question, which may ask which player instead). Returns the rows."""
    from openpyxl import Workbook
    doc = json.loads(Path(src).read_text(encoding="utf-8"))
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(["#", "question", "exploits", "must call", "must NOT call", "setup turn", "needs squad", "core", "bug"])
    rows = []
    for q in doc["questions"]:
        num = int(q["id"].split(":")[1])
        must = "any" if q["situation"] == "ambiguous" else "search_news"
        ws.append([num, q["question"], q["situation"], must, "", "", "N", "Y", ""])
        rows.append({"id": f"{SHEET}:{num}", "question": q["question"], "must_call": must, "situation": q["situation"]})
    wb.save(out)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-workbook", action="store_true")
    ap.add_argument("--check", help="a runner results .jsonl to check")
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.build_workbook:
        rows = to_workbook(Path(a.questions), WORKBOOK)
        print(f"wrote {WORKBOOK}: {len(rows)} rows, sheet {SHEET}")
    if a.check:
        questions = load_questions(a.questions)
        records = [json.loads(l) for l in Path(a.check).read_text(encoding="utf-8").splitlines() if l.strip()]
        per = [{"id": r.get("id"), "run": r.get("run"), "checks": check_record(r, questions[r["id"]])} for r in records if r.get("id") in questions]
        table = summarise(records, questions)
        doc = {"table": table, "per_record": per}
        if a.out:
            Path(a.out).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        for c in CHECKS:
            print(f"{c:9s} {table[c]['passing']} / {table[c]['applicable']} questions pass")
        for p in per:
            fails = [c for c in CHECKS if p["checks"][c]["applicable"] and not p["checks"][c]["pass"]]
            if fails:
                print(f"  FAIL {p['id']} run {p.get('run')}: " + "; ".join(f"{c}: {p['checks'][c]['why']}" for c in fails))
    return 0


if __name__ == "__main__":
    sys.exit(main())
