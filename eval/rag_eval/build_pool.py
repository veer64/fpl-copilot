"""RAG eval part 1 (2026-10-14): the candidate pool for questions_v1.json and the blind labelling workbook. NO SCORING.

For each question, at its as_of and with the production player gate, the top TOP_PER_VARIANT chunks of four retrieval
variants are pooled and de-duplicated by chunk id:
  dense_only          the vector ranking alone (news_search._candidates with no terms), no recency multiplier
  keyword_only        the keyword ranking alone (no vector; empty when the question names no player and no club)
  hybrid_no_recency   the production reciprocal-rank fusion without the recency multiplier
  hybrid_production   the production ranking exactly as search_news applies it (fusion, recency, cap, gate)
The two-chunks-per-article cap and the player gate (named players -> only about-results) are production's for every
variant (news_search.search_news, step 4). The pool with the variant and rank of every candidate goes to
eval/reports/rag_pool_v1.json -- the labeller must NOT see it -- and the workbook eval/reports/rag_labels_v1.xlsx shows
the candidates of each question shuffled (SHUFFLE_SEED) with no variant, rank or score.

Production code is not changed: the variants are built from news_search's own pieces (resolve_players, club_terms,
_candidates, date_basis, recency_multiplier, source_label, human_age) and config_roles. Every question is embedded
once, all of them in one embeddings.embed call (purpose "rag_eval"), so the Voyage cost is one request.

Usage (repo root):  python eval/rag_eval/build_pool.py [--questions P] [--pool P] [--workbook P] [--dry-run]
"""
import argparse
import hashlib
import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import config_roles                                        # noqa: E402
import chunking as ch                                      # noqa: E402
import news_search as ns                                   # noqa: E402

UTC = timezone.utc
VARIANTS = ("dense_only", "keyword_only", "hybrid_no_recency", "hybrid_production")
TOP_PER_VARIANT = 5
SHUFFLE_SEED = 20261014
QUESTIONS_PATH = REPO / "eval" / "rag_eval" / "questions_v1.json"
POOL_PATH = REPO / "eval" / "reports" / "rag_pool_v1.json"
WORKBOOK_PATH = REPO / "eval" / "reports" / "rag_labels_v1.xlsx"
OUTCOME_SITUATIONS = ("ambiguous", "no_news")           # one "is the tool's outcome right?" row instead of candidates
LABEL_RULE = ("y = reading this cutting helps answer the question correctly AND it is current as of as_of; "
              "n otherwise (old news replaced by newer = n).")
OUTCOME_QUESTION = "Is the tool's outcome right? y/n"


# ---- pure helpers ---------------------------------------------------------------------------------------------------

def parse_as_of(s):
    """'2026-10-09T09:00:00Z' -> an aware UTC datetime; anything else raises ValueError."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def load_questions(path=QUESTIONS_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _is_about(c, ids):
    if c.get("source") == "fpl":
        return c.get("element_id") in ids
    return any(p in ids for p in (c.get("player_ids") or []))


def rank_candidates(cands, as_of, requested_ids, players_given, *, recency=True, max_per_article=None, top=None):
    """news_search.search_news step 4 over a candidate list: boosted = score * recency multiplier (or the raw score
    when recency is False), sort by (-boosted, id), at most max_per_article chunks per article, then the player gate:
    with named players only about-results come back, else the best candidates labelled not-about. Returns copies
    carrying 'boosted' and 'about', at most `top` of them."""
    mpa = max_per_article or config_roles.SEARCH_MAX_PER_ARTICLE
    top = TOP_PER_VARIANT if top is None else top
    ids = set(requested_ids or [])
    out = []
    for c in cands:
        c = dict(c)
        when, _ = ns.date_basis(c)
        age_days = (as_of - ns._utc(when)).total_seconds() / 86400
        c["boosted"] = float(c["score"]) * (ns.recency_multiplier(age_days) if recency else 1.0)
        out.append(c)
    out.sort(key=lambda c: (-c["boosted"], c["id"]))
    per, kept = {}, []
    for c in out:
        n = per.get(c["news_item_id"], 0)
        if n < mpa:
            per[c["news_item_id"]] = n + 1
            c["about"] = bool(ids) and _is_about(c, ids)
            kept.append(c)
    if players_given:
        return [c for c in kept if c["about"]][:top]
    return kept[:top]


def seen_about_ids(ranked):
    """the requested ids that the about-rows of a ranked list cover (news_search's seen_about)"""
    seen = set()
    for c in ranked:
        if not c.get("about"):
            continue
        if c.get("source") == "fpl":
            seen.add(c.get("element_id"))
        else:
            seen.update(c.get("player_ids") or [])
    return seen


_ROW_KEYS = ("news_item_id", "source", "club", "url", "headline", "published_at", "fetched_at", "date_source", "element_id",
             "players", "player_ids", "chunk_text", "about")


def merge_variants(per_variant):
    """One row per distinct chunk across the variants' ranked lists, in first-seen order (VARIANTS order), with
    found_by = {variant: rank}. No score or boosted value survives: the labeller must not see them."""
    rows, by_id = [], {}
    for variant in VARIANTS:
        for rank, c in enumerate(per_variant.get(variant) or [], 1):
            row = by_id.get(c["id"])
            if row is None:
                row = {"chunk_id": c["id"], "item_id": c.get("news_item_id"), "found_by": {}}
                for k in _ROW_KEYS:
                    if k in c and k != "news_item_id":
                        row[k] = c[k]
                by_id[c["id"]] = row
                rows.append(row)
            row["found_by"][variant] = rank
    return rows


def shuffle_candidates(rows, seed, qid):
    """A new list, the rows in an order fixed by (seed, qid); the input list is left alone."""
    out = list(rows)
    random.Random(f"{seed}:{qid}").shuffle(out)
    return out


def check_as_of(cands, as_of):
    """[{chunk_id, fetched_at}] for every candidate fetched AFTER as_of -- must be empty for a valid pool."""
    bad = []
    for c in cands:
        f = ns._utc(c["fetched_at"])
        if f > as_of:
            bad.append({"chunk_id": c.get("chunk_id", c.get("id")), "fetched_at": f.isoformat()})
    return bad


def date_and_age(row, as_of):
    """(the date the age is measured from as YYYY-MM-DD, its basis, the age in words) -- production's date_basis"""
    when, basis = ns.date_basis(row)
    when = ns._utc(when)
    return when.strftime("%Y-%m-%d"), basis, ns.human_age(as_of - when)


def outcome_text(tool_outcome):
    return (f"search_mode: {tool_outcome['search_mode']}; results returned: {tool_outcome['n_results']}; "
            f"no_news_for: {tool_outcome['no_news_for']}; ambiguous_players: {json.dumps(tool_outcome['ambiguous_players'], ensure_ascii=False)}")


# ---- the database-bound part ------------------------------------------------------------------------------------------

def embed_questions(questions, conn, stats=None):
    """{qid: vector}; one embeddings.embed call for every question text (kind 'query', purpose 'rag_eval')."""
    import embeddings as em
    texts = [q["question"] for q in questions]
    vecs = em.embed(texts, "query", conn=conn, purpose="rag_eval", stats=stats)
    return {q["qid"]: v for q, v in zip(questions, vecs)}


def candidates_for(q, qvec, conn, snaps):
    """(per_variant ranked lists, resolution, tool_outcome) for one question at its as_of."""
    as_of = parse_as_of(q["as_of"])
    key, _ = snaps.get(as_of)
    requested, ambiguous, unmapped = ns.resolve_players(q["players"], snaps, as_of)
    ids = [r["id"] for r in requested]
    terms = [f for r in requested for f in r["forms"]] + ns.club_terms(q["clubs"])
    players_given = bool(q["players"])
    dense = ns._candidates(conn, as_of, qvec, [])
    kw = ns._candidates(conn, as_of, None, terms) if terms else []
    hyb = ns._candidates(conn, as_of, qvec, terms) if terms else dense
    per_variant = {
        "dense_only": rank_candidates(dense, as_of, ids, players_given, recency=False),
        "keyword_only": rank_candidates(kw, as_of, ids, players_given, recency=False),
        "hybrid_no_recency": rank_candidates(hyb, as_of, ids, players_given, recency=False),
        "hybrid_production": rank_candidates(hyb, as_of, ids, players_given, recency=True),
    }
    ranked_all = rank_candidates(hyb, as_of, ids, players_given, recency=True, top=max(len(hyb), 1))
    seen = seen_about_ids(ranked_all)
    no_news = [r["name"] for r in requested if r["id"] not in seen] + list(unmapped)
    mode = "hybrid" if terms else "dense_only"
    tool_outcome = {"search_mode": mode, "no_news_for": no_news, "ambiguous_players": ambiguous,
                    "n_results": len(per_variant["hybrid_production"])}
    resolution = {"snapshot_key": key, "requested": [{k: r[k] for k in ("name", "id", "web_name", "forms")} for r in requested],
                  "ambiguous": ambiguous, "unmapped": list(unmapped), "terms": terms,
                  "n_sql_candidates": {"dense": len(dense), "keyword": len(kw), "hybrid": len(hyb)}}
    return per_variant, resolution, tool_outcome


def _jsonable(v):
    if isinstance(v, datetime):
        return ns._utc(v).isoformat()
    return v


def build_pool(doc, conn, snaps, stats=None):
    """The pool document: meta, one entry per question with its de-duplicated candidates and the tool outcome."""
    questions = doc["questions"]
    vectors = embed_questions(questions, conn, stats)
    entries = []
    for q in questions:
        per_variant, resolution, tool_outcome = candidates_for(q, vectors[q["qid"]], conn, snaps)
        merged = merge_variants(per_variant)
        as_of = parse_as_of(q["as_of"])
        bad = check_as_of(merged, as_of)
        if bad:
            raise RuntimeError(f"{q['qid']}: {len(bad)} candidate(s) fetched after as_of: {bad[:3]}")
        entries.append({"qid": q["qid"], "situation": q["situation"], "question": q["question"], "players": q["players"],
                        "clubs": q["clubs"], "as_of": q["as_of"], "expected_outcome": q["expected_outcome"],
                        "resolution": resolution, "tool_outcome": tool_outcome, "n_candidates": len(merged),
                        "per_variant_ids": {v: [c["id"] for c in per_variant[v]] for v in VARIANTS},
                        "candidates": [{k: _jsonable(v) for k, v in row.items()} for row in merged]})
    counts = [e["n_candidates"] for e in entries]
    meta = {"built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "questions_version": doc.get("version"),
            "shuffle_seed": SHUFFLE_SEED, "top_per_variant": TOP_PER_VARIANT, "variants": list(VARIANTS),
            "config": {"EMBED_MODEL": config_roles.EMBED_MODEL, "EMBED_DIM": config_roles.EMBED_DIM,
                       "CHUNKER_VERSION": ch.CHUNKER_VERSION, "SEARCH_CANDIDATES": config_roles.SEARCH_CANDIDATES,
                       "SEARCH_TOP_N": config_roles.SEARCH_TOP_N, "SEARCH_RRF_K": config_roles.SEARCH_RRF_K,
                       "SEARCH_KW_WEIGHT": config_roles.SEARCH_KW_WEIGHT, "SEARCH_MAX_PER_ARTICLE": config_roles.SEARCH_MAX_PER_ARTICLE,
                       "RECENCY_HALF_LIFE_DAYS": config_roles.RECENCY_HALF_LIFE_DAYS},
            "embedding": dict(stats or {}),
            "candidates_per_question": {"min": min(counts), "median": statistics.median(counts), "max": max(counts),
                                        "total": sum(counts)},
            "label_rows": sum(1 if e["situation"] in OUTCOME_SITUATIONS or e["n_candidates"] == 0 else e["n_candidates"]
                              for e in entries)}
    return {"meta": meta, "questions": entries}


def write_workbook(doc, pool, path=WORKBOOK_PATH):
    """The blind labelling workbook: sheet 'questions' first, then 'label' with the candidates shuffled per question
    and no variant, rank or score. Returns the file's sha256[:12]."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "questions"
    head = ["qid", "situation", "question", "as_of", "expected outcome", "right behaviour", "QUESTION OK?", "NOTE"]
    ws.append(head)
    for q in doc["questions"]:
        ws.append([q["qid"], q["situation"], q["question"], q["as_of"], q["expected_outcome"], q["right_behaviour"], None, None])
    dv = DataValidation(type="list", formula1='"y,n"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"G2:G{len(doc['questions']) + 1}")
    for col, w in zip("ABCDEFGH", (6, 20, 44, 22, 60, 60, 14, 30)):
        ws.column_dimensions[col].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"

    wl = wb.create_sheet("label")
    wl.append([LABEL_RULE])
    wl.merge_cells("A1:K1")
    wl["A1"].font = Font(bold=True)
    wl["A1"].alignment = Alignment(wrap_text=True, vertical="top")
    wl.row_dimensions[1].height = 32
    head = ["qid", "question", "as_of", "cand#", "source", "published date", "age at as_of", "headline", "full chunk text",
            "ANSWERS?", "NOTE"]
    wl.append(head)
    for cell in wl[2]:
        cell.font = Font(bold=True)
    by_qid = {e["qid"]: e for e in pool["questions"]}
    for q in doc["questions"]:
        e = by_qid[q["qid"]]
        as_of = parse_as_of(q["as_of"])
        if q["situation"] in OUTCOME_SITUATIONS or e["n_candidates"] == 0:
            wl.append([q["qid"], q["question"], q["as_of"], "tool", "tool outcome", None, None, OUTCOME_QUESTION,
                       outcome_text(e["tool_outcome"]), None, None])
            continue
        for i, row in enumerate(shuffle_candidates(e["candidates"], SHUFFLE_SEED, q["qid"]), 1):
            r = dict(row)
            for k in ("published_at", "fetched_at"):
                if isinstance(r.get(k), str):
                    r[k] = datetime.fromisoformat(r[k])
            date, basis, age = date_and_age(r, as_of)
            wl.append([q["qid"], q["question"], q["as_of"], i, ns.source_label(r.get("source"), r.get("club")),
                       f"{date} ({basis})", age, ns.source_headline(r.get("headline")), r.get("chunk_text"), None, None])
    n = wl.max_row
    dv2 = DataValidation(type="list", formula1='"y,n"', allow_blank=True)
    wl.add_data_validation(dv2)
    dv2.add(f"J3:J{max(n, 3)}")
    for col, w in zip("ABCDEFGHIJK", (6, 34, 21, 6, 24, 24, 14, 44, 90, 10, 30)):
        wl.column_dimensions[col].width = w
    for r in range(3, n + 1):
        wl.cell(row=r, column=9).alignment = Alignment(wrap_text=True, vertical="top")
        wl.cell(row=r, column=8).alignment = Alignment(wrap_text=True, vertical="top")
        wl.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    wl.freeze_panes = "A3"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", default=str(QUESTIONS_PATH))
    ap.add_argument("--pool", default=str(POOL_PATH))
    ap.add_argument("--workbook", default=str(WORKBOOK_PATH))
    ap.add_argument("--dry-run", action="store_true", help="load and validate the questions only; no database, no embedding")
    a = ap.parse_args(argv)
    doc = load_questions(a.questions)
    for q in doc["questions"]:
        parse_as_of(q["as_of"])
    print(f"questions: {len(doc['questions'])} ({a.questions})")
    if a.dry_run:
        return 0
    import db_write
    conn = db_write.connect()
    try:
        snaps = ns._load_snapshots()
        stats = {}
        pool = build_pool(doc, conn, snaps, stats)
    finally:
        conn.close()
    Path(a.pool).parent.mkdir(parents=True, exist_ok=True)
    Path(a.pool).write_text(json.dumps(pool, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    sha = write_workbook(doc, pool, a.workbook)
    m = pool["meta"]
    print(f"pool: {a.pool} | candidates per question min/median/max {m['candidates_per_question']['min']}/"
          f"{m['candidates_per_question']['median']}/{m['candidates_per_question']['max']} | total {m['candidates_per_question']['total']}"
          f" | label rows {m['label_rows']} | embedding {m['embedding']}")
    print(f"workbook: {a.workbook} sha256[:12] {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
