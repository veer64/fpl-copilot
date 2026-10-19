"""RAG retrieval scorer (eval/rag_eval/score_rag.py, 2026-10-19): the pure metrics on tiny hand-made cases, the
story-collapse key, the label-sheet reader on a tiny workbook, and -- when the gitignored pool is on disk -- the exact
reproduction of eval/reports/rag_retrieval_eval_v1.md against the committed copy of the user's locked labels. No
database, no network, no Voyage, no Anthropic."""
import hashlib
import json
import sys
from pathlib import Path

import openpyxl
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from rag_eval import build_pool as bp                      # noqa: E402
from rag_eval import score_rag as sr                       # noqa: E402

POOL = REPO / "eval" / "reports" / "rag_pool_v2.json"
LABELS = REPO / "eval" / "rag_eval" / "labels" / "rag_labels_v2.xlsx"
LABELS_SHA12 = "7f57b71998cd"          # the user's lock, 2026-10-14 13:51Z


# ---- the metrics ---------------------------------------------------------------------------------------------------

def test_recall_at_5_counts_only_the_top_five():
    rel = {"a", "f"}
    assert sr.recall_at_k(["a", "b", "c", "d", "e", "f"], rel) == 0.5     # f sits at rank 6
    assert sr.recall_at_k(["f", "a", "b"], rel) == 1.0
    assert sr.recall_at_k(["x", "y"], rel) == 0.0
    assert sr.recall_at_k([], rel) == 0.0


def test_recall_counts_a_relevant_key_once_even_if_ranked_twice():
    assert sr.recall_at_k(["a", "a", "b"], {"a", "c"}) == 0.5


def test_reciprocal_rank_is_one_over_the_first_relevant_rank():
    assert sr.reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert sr.reciprocal_rank(["a", "x"], {"a", "x"}) == 1.0
    assert sr.reciprocal_rank(["x", "y"], {"a"}) == 0.0
    assert sr.reciprocal_rank(["x", "y", "z", "w", "v", "a"], {"a"}) == 0.0   # beyond the top five


def test_hit_at_5_is_one_when_any_of_the_top_five_is_relevant():
    assert sr.hit_at_k(["x", "y", "z", "w", "a"], {"a"}) == 1.0
    assert sr.hit_at_k(["x", "y", "z", "w", "v", "a"], {"a"}) == 0.0
    assert sr.hit_at_k([], {"a"}) == 0.0


def test_score_question_needs_at_least_one_relevant_key():
    assert sr.score_question(["a"], set()) is None
    m = sr.score_question(["x", "a", "b"], {"a", "b", "c"})
    assert m == {"recall": pytest.approx(2 / 3), "rr": 0.5, "hit": 1.0}


def test_summarise_averages_over_the_questions():
    per = {"q1": {"recall": 1.0, "rr": 1.0, "hit": 1.0}, "q2": {"recall": 0.5, "rr": 0.5, "hit": 1.0},
           "q3": {"recall": 0.0, "rr": 0.0, "hit": 0.0}}
    s = sr.summarise(per)
    assert s["n"] == 3 and s["hits"] == 2
    assert s["recall@5"] == pytest.approx(0.5) and s["MRR"] == pytest.approx(0.5) and s["hit@5"] == pytest.approx(2 / 3)
    assert sr.summarise({})["n"] == 0


# ---- the story collapse ----------------------------------------------------------------------------------------------

def test_story_key_collapses_the_language_copies_to_one_unit():
    item_of = {1: 1090, 2: 1091, 3: 1093, 4: 1094, 5: 777}
    keys = [sr.story_key(c, item_of) for c in (1, 2, 3, 4, 5)]
    assert keys[:4] == [("story", 1090)] * 4
    assert keys[4] == ("chunk", 5)
    assert sr.dedup(keys) == [("story", 1090), ("chunk", 5)]


def test_top_keys_dedups_before_cutting_at_five():
    item_of = {1: 1090, 2: 1091, 3: 1093, 4: 1094, 5: 10, 6: 11, 7: 12}
    # four copies of the story first: without the dedup, chunks 6 and 7 would never reach the top five
    assert sr.top_keys([1, 2, 3, 4, 5, 6, 7], item_of) == [("story", 1090), ("chunk", 5), ("chunk", 6), ("chunk", 7)]
    assert sr.top_keys([5, 6, 7], item_of, top=2) == [("chunk", 5), ("chunk", 6)]


# ---- the label sheet ------------------------------------------------------------------------------------------------

def _tiny_pool():
    """two questions; q01 has four candidates (two are copies of the story) and q02 is a tool-only question"""
    cands = [{"chunk_id": 1, "item_id": 1090, "chunk_text": "story copy EN"}, {"chunk_id": 2, "item_id": 1091, "chunk_text": "story copy PT"},
             {"chunk_id": 3, "item_id": 5, "chunk_text": "other piece"}, {"chunk_id": 4, "item_id": 6, "chunk_text": "stale piece"}]
    return {"questions": [
        {"qid": "q01", "situation": "player_current_news", "gate_active": True, "candidates": cands,
         "per_variant_ids": {"dense_only": [4, 3, 1], "keyword_only": [4, 2, 1], "hybrid_production": [1, 2, 3], "dense_ungated": [4, 1]}},
        {"qid": "q02", "situation": "no_news", "gate_active": False, "candidates": [],
         "per_variant_ids": {"dense_only": [], "keyword_only": [], "hybrid_production": [], "dense_ungated": None}},
    ]}


def _tiny_workbook(path, pool, labels_by_chunk, tool_label="y", break_text=False):
    """the label sheet's layout: row 1 the rule, row 2 the header, rows 3+ the candidates in the pool's seeded order"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "label"
    ws.append([bp.LABEL_RULE])
    ws.append(["qid", "question", "as_of", "cand#", "source", "published date", "age at as_of", "headline", "full chunk text", "ANSWERS?", "NOTE"])
    for e in pool["questions"]:
        rows = bp.shuffle_candidates(e["candidates"], bp.SHUFFLE_SEED, e["qid"])
        for i, r in enumerate(rows, 1):
            text = r["chunk_text"] + (" CHANGED" if break_text and r["chunk_id"] == 3 else "")
            ws.append([e["qid"], "q?", "2026-10-09T09:00:00Z", str(i), "club", "2026-10-08", "1 day ago", "h", text, labels_by_chunk.get(r["chunk_id"]), None])
        if not rows:
            ws.append([e["qid"], "q?", "2026-10-09T09:00:00Z", "tool", "tool", None, None, bp.OUTCOME_QUESTION, "no_news_for: X", tool_label, None])
    wb.create_sheet("questions").append(["qid"])
    wb.save(path)


def test_read_labels_maps_cand_numbers_through_the_seeded_shuffle(tmp_path):
    pool = _tiny_pool()
    wb = tmp_path / "labels.xlsx"
    _tiny_workbook(wb, pool, {1: "y", 2: "y", 3: "n", 4: "N "})
    lab = sr.read_labels(wb, pool)
    assert lab["labels"]["q01"] == {1: "y", 2: "y", 3: "n", 4: "n"}          # stripped, lower-cased; in chunk-id terms
    assert lab["tool_rows"] == {"q02": "y"}
    assert lab["mismatches"] == [] and lab["blank"] == []
    assert lab["label_counts"] == {"y": 2, "n": 2}


def test_read_labels_reports_a_chunk_text_that_differs_from_the_pool(tmp_path):
    pool = _tiny_pool()
    wb = tmp_path / "labels.xlsx"
    _tiny_workbook(wb, pool, {1: "y", 2: "y", 3: "n", 4: None}, break_text=True)
    lab = sr.read_labels(wb, pool)
    assert len(lab["mismatches"]) == 1 and lab["mismatches"][0][0] == "q01" and lab["mismatches"][0][2] == 3
    assert len(lab["blank"]) == 1 and lab["blank"][0][0] == "q01" and lab["blank"][0][2] == 4   # (qid, cand#, chunk_id)


def test_score_pool_collapses_the_story_and_scores_only_questions_with_a_y(tmp_path):
    pool = _tiny_pool()
    wb = tmp_path / "labels.xlsx"
    _tiny_workbook(wb, pool, {1: "y", 2: "y", 3: "n", 4: "n"})
    res = sr.score_pool(pool, sr.read_labels(wb, pool))
    assert res["scored"] == ["q01"] and res["unscored"] == ["q02"]
    # the two copies are ONE relevant unit: dense_only ranks it third, keyword_only second, production first
    assert res["variants"]["dense_only"]["per"]["q01"] == {"recall": 1.0, "rr": pytest.approx(1 / 3), "hit": 1.0}
    assert res["variants"]["keyword_only"]["per"]["q01"]["rr"] == 0.5
    assert res["variants"]["hybrid_production"]["per"]["q01"]["rr"] == 1.0
    assert res["variants"]["dense_ungated"]["n"] == 1                  # q01 is gated and carries the variant
    assert res["tool_rows"] == {"q02": "y"} and res["tool_correct"] == (1, 1)


# ---- the reproduction (the pool is gitignored: present on the laptop, absent on a clean clone) -----------------------

def test_committed_labels_copy_is_the_users_lock():
    assert LABELS.exists(), "eval/rag_eval/labels/rag_labels_v2.xlsx must be committed"
    assert hashlib.sha256(LABELS.read_bytes()).hexdigest()[:12] == LABELS_SHA12


@pytest.mark.skipif(not POOL.exists(), reason="rag_pool_v2.json is gitignored and not on this machine")
def test_reproduces_rag_retrieval_eval_v1():
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    res = sr.score_pool(pool, sr.read_labels(LABELS, pool))
    assert res["n_scored"] == 22 and res["tool_correct"] == (6, 6)
    got = {v: (round(r["recall@5"], 3), round(r["MRR"], 3), r["hits"], r["n"]) for v, r in res["variants"].items()}
    assert got == {"dense_only": (0.822, 0.932, 21, 22), "keyword_only": (0.808, 0.909, 20, 22),
                   "hybrid_no_recency": (0.906, 0.955, 22, 22), "hybrid_production": (0.908, 1.000, 22, 22),
                   "dense_ungated": (0.845, 0.938, 15, 16)}
