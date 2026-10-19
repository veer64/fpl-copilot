"""RAG retrieval scorer (2026-10-19): the pooled retrieval variants scored against the user's locked labels.

Reads two files and nothing else -- the candidate pool (eval/reports/rag_pool_v2.json, gitignored) and the label
workbook (eval/rag_eval/labels/rag_labels_v2.xlsx, the committed copy of the lock 7f57b71998cd). No database, no
Voyage, no Anthropic, no network. It reproduces the table in eval/reports/rag_retrieval_eval_v1.md.

Definitions (as in that report):
- a variant's answer for a question is its top 5 chunk ids from the pool (`per_variant_ids`);
- the four language copies of the Liverpool story (items 1090 / 1091 / 1093 / 1094) are ONE unit: keys are
  de-duplicated in rank order and only then cut at five, and a y on any copy makes the unit relevant;
- recall@5 = relevant units in the top five / relevant units; MRR = mean of 1 / rank of the first relevant unit (0 when
  none in the top five); hit@5 = the share of questions with at least one relevant unit in the top five;
- a question is scored when at least one of its candidates is labelled y; dense_ungated is scored on the scored
  questions that carry that variant (the gated ones);
- a tool-outcome row ("tool" in the cand# column) is correct when its label is y.

Usage: python eval/rag_eval/score_rag.py [--pool P] [--labels L] [--json OUT]
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from rag_eval import build_pool as bp                      # noqa: E402  (the seeded shuffle that laid out the sheet)

POOL_PATH = REPO / "eval" / "reports" / "rag_pool_v2.json"
LABELS_PATH = REPO / "eval" / "rag_eval" / "labels" / "rag_labels_v2.xlsx"
VARIANTS = ("dense_only", "keyword_only", "hybrid_no_recency", "hybrid_production", "dense_ungated")
DUP_ITEMS = frozenset({1090, 1091, 1093, 1094})
DUP_CANON = 1090
TOP = 5
LABEL_SHEET = "label"
LABEL_HEADER_ROWS = 2            # row 1 the labelling rule, row 2 the column names


# ---- the metrics (pure) ----------------------------------------------------------------------------------------------

def recall_at_k(ranked, relevant, k=TOP):
    """relevant keys among the first k / relevant keys; 0 when nothing is relevant"""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def reciprocal_rank(ranked, relevant, k=TOP):
    """1 / rank of the first relevant key within the first k; 0 when none"""
    for i, key in enumerate(ranked[:k], 1):
        if key in relevant:
            return 1.0 / i
    return 0.0


def hit_at_k(ranked, relevant, k=TOP):
    return 1.0 if any(key in relevant for key in ranked[:k]) else 0.0


def score_question(ranked, relevant, k=TOP):
    """{recall, rr, hit} for one question, or None when it has no relevant key (unscored)"""
    if not relevant:
        return None
    return {"recall": recall_at_k(ranked, relevant, k), "rr": reciprocal_rank(ranked, relevant, k), "hit": hit_at_k(ranked, relevant, k)}


def summarise(per):
    """per-question metrics -> the row of the table"""
    n = len(per)
    if not n:
        return {"n": 0, "recall@5": 0.0, "MRR": 0.0, "hit@5": 0.0, "hits": 0}
    return {"n": n, "recall@5": sum(m["recall"] for m in per.values()) / n, "MRR": sum(m["rr"] for m in per.values()) / n,
            "hit@5": sum(m["hit"] for m in per.values()) / n, "hits": int(round(sum(m["hit"] for m in per.values())))}


# ---- the story collapse (pure) ----------------------------------------------------------------------------------------

def story_key(chunk_id, item_of, dup_items=DUP_ITEMS, canon=DUP_CANON):
    """the unit a chunk counts as: the one story for the language copies, the chunk itself otherwise"""
    return ("story", canon) if item_of.get(chunk_id) in dup_items else ("chunk", chunk_id)


def dedup(keys):
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return out


def top_keys(chunk_ids, item_of, top=TOP):
    """a variant's ranked units: keys in rank order, duplicates dropped, then cut at `top`"""
    return dedup(story_key(c, item_of) for c in chunk_ids)[:top]


# ---- the files ------------------------------------------------------------------------------------------------------

def load_pool(path=POOL_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_labels(workbook_path, pool):
    """the label sheet -> {labels: qid -> chunk_id -> 'y'/'n'/'', tool_rows: qid -> label, mismatches, blank,
    label_counts}. A candidate row's cand# is its 1-based position in the pool's seeded shuffle for that question; the
    row's chunk text is checked against the pool's (a mismatch means the sheet and the pool disagree)."""
    entries = {e["qid"]: e for e in pool["questions"]}
    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    ws = wb[LABEL_SHEET]
    labels = defaultdict(dict)
    tool_rows = {}
    mismatches, blank = [], []
    for row in ws.iter_rows(min_row=LABEL_HEADER_ROWS + 1, values_only=True):
        row = tuple(row) + (None,) * (11 - len(row))
        qid, _question, _as_of, cand, _source, _pub, _age, _head, text, ans, _note = row[:11]
        if not qid:
            continue
        lab = str(ans).strip().lower() if ans not in (None, "") else ""
        if str(cand).strip().lower() == "tool":
            tool_rows[qid] = lab
            continue
        shuffled = bp.shuffle_candidates(entries[qid]["candidates"], bp.SHUFFLE_SEED, qid)
        cand_row = shuffled[int(cand) - 1]
        if (cand_row.get("chunk_text") or "") != (text or ""):
            mismatches.append((qid, cand, cand_row["chunk_id"]))
        if lab == "":
            blank.append((qid, cand, cand_row["chunk_id"]))
        labels[qid][cand_row["chunk_id"]] = lab
    wb.close()
    return {"labels": {q: dict(d) for q, d in labels.items()}, "tool_rows": tool_rows, "mismatches": mismatches, "blank": blank,
            "label_counts": dict(Counter(l for d in labels.values() for l in d.values()))}


# ---- the scoring ------------------------------------------------------------------------------------------------------

def score_pool(pool, lab, variants=VARIANTS, top=TOP):
    entries = {e["qid"]: e for e in pool["questions"]}
    item_of = {c["chunk_id"]: c["item_id"] for e in pool["questions"] for c in e["candidates"]}
    labels = lab["labels"]
    y_chunks = {q: sorted(c for c, l in labels.get(q, {}).items() if l == "y") for q in entries}
    relevant = {q: {story_key(c, item_of) for c in cs} for q, cs in y_chunks.items()}
    scored = sorted(q for q in entries if y_chunks[q])
    unscored = sorted(q for q in entries if not y_chunks[q])
    variants_out = {}
    for v in variants:
        per = {}
        for q in scored:
            ids = entries[q]["per_variant_ids"].get(v)
            if ids is None:                       # the variant was not run for this question (dense_ungated on ungated ones)
                continue
            per[q] = score_question(top_keys(ids, item_of, top), relevant[q], top)
        row = summarise(per)
        row["per"] = per
        variants_out[v] = row
    tool_rows = dict(lab["tool_rows"])
    n_tool_right = sum(1 for l in tool_rows.values() if l == "y")
    return {"n_scored": len(scored), "scored": scored, "unscored": unscored, "y_chunks": y_chunks, "variants": variants_out,
            "tool_rows": tool_rows, "tool_correct": (n_tool_right, len(tool_rows)),
            "lock": {"mismatches": lab["mismatches"], "blank": lab["blank"], "label_counts": lab["label_counts"]}}


def table(res):
    """the report's table, one line per variant, plus the tool-outcome line"""
    lines = [f"{'variant':20} {'n':>3} {'recall@5':>9} {'MRR':>6} {'hit@5':>6} hits"]
    for v, r in res["variants"].items():
        lines.append(f"{v:20} {r['n']:>3} {r['recall@5']:>9.3f} {r['MRR']:>6.3f} {r['hit@5']:>6.3f} {r['hits']}/{r['n']}")
    lines.append(f"tool-outcome rows: {res['tool_correct'][0]}/{res['tool_correct'][1]} correct")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", default=str(POOL_PATH))
    ap.add_argument("--labels", default=str(LABELS_PATH))
    ap.add_argument("--json", default=None, help="write the full result (per-question metrics included) here")
    a = ap.parse_args(argv)
    pool = load_pool(a.pool)
    lab = read_labels(a.labels, pool)
    res = score_pool(pool, lab)
    print(f"labels: {lab['label_counts']}  blank: {len(lab['blank'])}  chunk-text mismatches: {len(lab['mismatches'])}")
    print(f"scored questions: {res['n_scored']} {res['scored']}")
    print(f"unscored: {res['unscored']}")
    print(table(res))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
