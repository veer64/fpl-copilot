"""Chunk + embed what news_to_embed lists (2026-09-30): embed_pending() takes every item of the
view that has no news_chunks rows for (chunking.CHUNKER_VERSION, config EMBED_MODEL), chunks it
(chunking.py), embeds all its chunks as "document" vectors (embeddings.py) and inserts the rows
with their vector and their tsv (to_tsvector('fpl_english', ...)). The two ingestion runners call
it at the end of every run, after the relevance filter; eval/run_embed.py runs it by hand.

Rules:
  * Idempotent by selection: an item with chunks for the current (chunker version, model) is
    never chunked or sent again, so a second run makes zero Voyage calls. New versions of a
    chunker or model sit beside the old rows (the unique key carries both).
  * Groups: items are grouped, WHOLE, up to the per-request caps (group_items); one group is one
    transaction. embed() may still split a large group into several requests; if any of them
    fails after its retries, the WHOLE group is rolled back, nothing is written for its items,
    and they are picked up again next run ("FAILED ... written nothing").
  * Three consecutive failed groups with the same signature (HTTP status + error class, or
    (None, "timeout") / (None, "bad_response")) -> "repeated error, run stopped",
    embeddings.EmbedRepeatedError; a success resets the count. A 401 / 403 stops the run at once.
  * GUARD: without the vector extension (news_store.vector_installed) there is no news_chunks
    table; the step logs "pgvector not installed, embedding skipped" and returns; the runners
    exit 0. The server runs this way until the extension is created there.
  * dry_run: chunk only, zero calls, nothing written; the summary carries the counts by source and
    every item's chunks for the CLI to print.
"""
import time

import config_roles
import chunking as ch
import embeddings as em
import news_store as ns

PURPOSE = em.PURPOSE
REPEAT_LIMIT = 3                     # consecutive same-signature group failures that stop a run

_PENDING = ("SELECT e.id, e.source, e.embed_text FROM news_to_embed e "
            "WHERE NOT EXISTS (SELECT 1 FROM news_chunks c WHERE c.news_item_id = e.id "
            "AND c.chunker_version = %s AND c.embed_model = %s) ORDER BY e.id")
_INSERT = ("INSERT INTO news_chunks (news_item_id, chunk_index, chunker_version, embed_model, chunk_text, char_count, embedding, tsv) "
           "VALUES (%s, %s, %s, %s, %s, %s, %s::vector, to_tsvector('fpl_english', %s))")


def pending(conn, limit=None, ids=None):
    """news_to_embed rows without chunks for the current (chunker version, model), oldest id first;
    ids restricts the run to those items (still only if pending)."""
    sql, args = _PENDING, [ch.CHUNKER_VERSION, config_roles.EMBED_MODEL]
    if ids:
        sql = sql.replace(" ORDER BY e.id", " AND e.id = ANY(%s) ORDER BY e.id")
        args = args + [[int(i) for i in ids]]
    if limit is not None:
        sql, args = sql + " LIMIT %s", args + [int(limit)]
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return [{"id": r[0], "source": r[1], "embed_text": r[2]} for r in cur.fetchall()]


def group_items(items):
    """[(item_id, [chunk_text, ...]), ...] -> groups of whole items whose total texts and
    estimated tokens stay within one request's caps; an item over the caps is a group alone."""
    max_texts, budget = config_roles.EMBED_MAX_TEXTS_PER_REQUEST, em.request_token_budget()
    groups, cur, n, toks = [], [], 0, 0
    for item_id, texts in items:
        k, est = len(texts), sum(em.estimate_tokens(t) for t in texts)
        if cur and (n + k > max_texts or toks + est > budget):
            groups.append(cur)
            cur, n, toks = [], 0, 0
        cur.append((item_id, texts))
        n, toks = n + k, toks + est
    if cur:
        groups.append(cur)
    return groups


def vector_literal(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _insert(conn, item_id, chunks, vectors):
    with conn.cursor() as cur:
        for c, v in zip(chunks, vectors):
            cur.execute(_INSERT, (item_id, c.index, ch.CHUNKER_VERSION, config_roles.EMBED_MODEL, c.text, c.char_count,
                                  vector_literal(v), c.text))


FIX_KEYS = ("headline_repeat", "ellipsis_headline", "trailing_link_list", "residue_lines")


def embed_pending(conn, limit=None, *, dry_run=False, client=None, log=print, sleep=time.sleep, clock=time.monotonic, pacer=None,
                  ids=None):
    """Chunk and embed every pending news_to_embed item (at most `limit`; only `ids` when given).
    Returns the summary; its "fixes" counts the CLUB items each cleaning rule changed."""
    s = {"items": 0, "chunks": 0, "groups": 0, "failed_groups": 0, "written_items": 0, "written_chunks": 0,
         "calls": 0, "attempts": 0, "tokens": 0, "by_source": {}, "fixes": {k: 0 for k in FIX_KEYS}, "dry_run": dry_run,
         "skipped_no_pgvector": False, "chunker_version": ch.CHUNKER_VERSION, "model": config_roles.EMBED_MODEL, "chunked": []}
    if not ns.vector_installed(conn):
        s["skipped_no_pgvector"] = True
        log("embed: pgvector not installed, embedding skipped")
        return s
    items = pending(conn, limit, ids)
    if not items:
        log(f"embed: nothing to embed for {ch.CHUNKER_VERSION} / {config_roles.EMBED_MODEL}")
        return s
    chunked = []
    for it in items:
        chunks, details = ch.chunk_embed_text_details(it["embed_text"])
        chunked.append((it, chunks))
        if it["source"] == "club":
            for k in FIX_KEYS:
                s["fixes"][k] += int(bool(details[k]))
    s["items"] = len(items)
    for it, chunks in chunked:
        s["chunks"] += len(chunks)
        b = s["by_source"].setdefault(it["source"], {"items": 0, "chunks": 0})
        b["items"] += 1
        b["chunks"] += len(chunks)
    s["chunked"] = chunked
    if dry_run:
        log(f"embed: dry run, {s['items']} items -> {s['chunks']} chunks by source {s['by_source']}, "
            f"club bodies changed by rule {s['fixes']}, zero calls, nothing written")
        return s
    groups = group_items([(it["id"], [c.text for c in chunks]) for it, chunks in chunked])
    by_id = {it["id"]: (it, chunks) for it, chunks in chunked}
    s["groups"] = len(groups)
    if pacer is None:
        pacer = em.Pacer(config_roles.EMBED_RPM, config_roles.EMBED_TPM, clock, sleep)
    stats = {}
    streak = [None, 0]                                   # [signature, consecutive count]
    for g in groups:
        texts = [t for _, ts in g for t in ts]
        try:
            vecs = em.embed(texts, "document", client=client, conn=conn, purpose=PURPOSE, sleep=sleep, clock=clock, pacer=pacer, stats=stats)
        except em.EmbedAuthError as e:
            log(f"embed: group of {len(g)} items ({len(texts)} chunks) -> {e}; auth failed, run stopped: nothing written, no further calls")
            raise
        except em.EmbedError as e:
            conn.rollback()
            s["failed_groups"] += 1
            log(f"embed: group of {len(g)} items ({len(texts)} chunks, ids {[i for i, _ in g]}) FAILED ({e}); "
                f"written nothing for them, retried next run")
            sig = (e.status, e.error_type)
            streak[0], streak[1] = sig, (streak[1] + 1 if streak[0] == sig else 1)
            if streak[1] >= REPEAT_LIMIT:
                status = "-" if sig[0] is None else sig[0]
                log(f"embed: repeated error, run stopped: {status} {sig[1]} ({streak[1]} consecutive groups); no further calls")
                raise em.EmbedRepeatedError(f"repeated error, run stopped: {status} {sig[1]}", sig[0], sig[1]) from e
            continue
        pos = 0
        for item_id, ts in g:
            it, chunks = by_id[item_id]
            _insert(conn, item_id, chunks, vecs[pos:pos + len(ts)])
            pos += len(ts)
            s["written_items"] += 1
            s["written_chunks"] += len(chunks)
        conn.commit()
        streak[:] = [None, 0]
    s.update(calls=stats.get("calls", 0), attempts=stats.get("attempts", 0), tokens=stats.get("tokens", 0))
    log(f"embed: {ch.CHUNKER_VERSION} / {config_roles.EMBED_MODEL}: items {s['items']} -> chunks {s['chunks']} in {s['groups']} groups; "
        f"written {s['written_items']} items / {s['written_chunks']} chunks, failed groups {s['failed_groups']}; "
        f"voyage calls {s['calls']} (attempts {s['attempts']}), tokens {s['tokens']}; by source {s['by_source']}")
    return s
