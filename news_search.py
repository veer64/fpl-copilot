"""search_news (2026-09-30, Piece 7): the agent's team-news search over news_chunks, hybrid dense +
keyword with reciprocal-rank fusion, a recency multiplier, at most two chunks per article, a soft
player gate, and one search_log row per call. The citation-check helpers the agent runs after each
reply live here too.

Agent-facing signature: search_news(query, players=[], clubs=[]); the server sets as_of = now.
as_of, conn, embed_client and snapshots are keyword-only parameters for tests and replays, NEVER in
the tool schema.

Steps:
  1. players -> element ids through player_names against the bootstrap squad as of as_of. A name
     two players share (Palmer) is not searched; it comes back in "ambiguous_players" with labels.
     An unknown name is not searched either and counts as "no_news_for".
  2. The query is embedded (embeddings.embed, kind "query"). Any failure -> keyword-only.
  3. One SQL statement: live_items = the newest row IN TIME of each (source, guid) fetched at or before
     as_of (fetched_at DESC, then version DESC -- never by version number alone, since 2026-10-01:
     the server's version numbers once ran against time); candidates = their chunks for config
     EMBED_MODEL and chunking.CHUNKER_VERSION that are in
     news_to_embed; dense = top SEARCH_CANDIDATES by cosine distance (skipped without a vector);
     kw = top SEARCH_CANDIDATES by ts_rank_cd over tsv @@ (plainto_tsquery of every name form of the
     resolved players -- web_name, first_name, second_name -- OR the clubs' names and aliases; skipped
     without names or clubs); RRF: score = 1/(k + r_dense) + w_kw/(k + r_kw), a missing rank counts 0
     (config SEARCH_RRF_K, SEARCH_KW_WEIGHT). The top SEARCH_CANDIDATES fused rows come back.
  4. Python: score *= 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS), the age at as_of from published_at
     when date_source is meta / url / page / source_field / feed, else from fetched_at (date_basis);
     at most SEARCH_MAX_PER_ARTICLE chunks per article; the player gate (ruling 2026-09-30): when
     players were given, ONLY about-results come back (the article's production verdict has a
     requested id in player_ids, or an FPL row's element_id is one), by boosted score, never a
     filler, so a player nobody wrote about gets an empty list and a "no_news_for" entry; without
     players (clubs or the query alone) the best candidates come back labelled
     about_requested_player false; SEARCH_TOP_N results either way.
  5. search_mode: "hybrid" (vector and names), "dense_only" (vector, no names or clubs),
     "keyword_only" (no vector; with no names either the result list is empty).
Nothing here reads the wall clock except the as_of default.
"""
import json
import re
import time
from datetime import datetime, timezone

import config_roles
import chunking as ch
import embeddings as em
import player_names as pn

UTC = timezone.utc
DATE_BASIS = {"meta": "publisher", "url": "url", "page": "page", "source_field": "FPL", "feed": "feed"}
FIRST_SEEN = "first seen by us"
_CITE = re.compile(r"\bc\d+\b")
_snapshots = None
_pacer = None


# ---- small pure helpers ------------------------------------------------------------------------------

def source_label(source, club=None):
    if source == "bbc":
        return "BBC Sport"
    if source == "fpl":
        return "FPL official"
    if source == "club":
        return f"{club or 'Club'} official site"
    return str(source)


def date_basis(item):
    """(the datetime the age is measured from, the basis label)"""
    ds = item.get("date_source")
    pub = item.get("published_at")
    if ds in DATE_BASIS and pub is not None:
        return pub, DATE_BASIS[ds]
    return item["fetched_at"], FIRST_SEEN


def recency_multiplier(age_days, half_life_days=None):
    hl = half_life_days or config_roles.RECENCY_HALF_LIFE_DAYS
    return 0.5 ** (max(0.0, float(age_days)) / hl)


def human_age(delta):
    s = max(0, int(delta.total_seconds()))
    if s < 3600:
        m = s // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = s // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _utc(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(dt):
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def cited_ids(text):
    """the result ids a reply cites (c<digits>, case-sensitive), first occurrence order, no repeats"""
    out = []
    for m in _CITE.findall(text or ""):
        if m not in out:
            out.append(m)
    return out


def citation_violations(cited, returned):
    ok = set(returned or [])
    return [c for c in cited if c not in ok]


_CITE_TOKEN = re.compile(r"\(?\[?\bc(\d+)\b\]?\)?")


def render_citations(text, results):
    """Part C (2026-10-01): the reply with every c<id> replaced by a numbered marker [1], [2], ... in order
    of first appearance (a repeated id keeps its number) and a "Sources" section appended, every value
    taken from THIS turn's search results, never from the model's text:
        [n] <source label> · "<headline>" · <date> · <url>     (club and bbc items; the url when there is one)
        [n] FPL official notice · <date>                        (FPL rows: no headline, no url)
    An id the turn did not return renders as [unverified] and is not listed (citation_checks records it).
    A reply without citations comes back unchanged."""
    by_id = {str(r.get("id")): r for r in (results or []) if isinstance(r, dict) and r.get("id")}
    order = []

    def repl(m):
        cid = "c" + m.group(1)
        if cid not in by_id:
            return "[unverified]"
        if cid not in order:
            order.append(cid)
        return f"[{order.index(cid) + 1}]"

    rendered = _CITE_TOKEN.sub(repl, text or "")
    if not order:
        return rendered
    lines = []
    for i, cid in enumerate(order, 1):
        r = by_id[cid]
        if r.get("source") == "FPL official":
            lines.append(f"[{i}] FPL official notice · {r.get('date')}")
        else:
            parts = [str(r.get("source")), f"\"{r.get('headline') or ''}\"", str(r.get("date"))]
            if r.get("url"):
                parts.append(str(r["url"]))
            lines.append(f"[{i}] " + " · ".join(parts))
    return rendered.rstrip() + "\n\nSources\n" + "\n".join(lines)


# ---- resolution --------------------------------------------------------------------------------------

def _load_snapshots():
    """the raw bootstrap archive indexed by time (relevance.load_context), loaded once per process;
    poll_availability lives under eval/, which the runners put on sys.path and the agent does not"""
    global _snapshots
    if _snapshots is None:
        import sys
        from pathlib import Path
        eval_dir = str(Path(__file__).resolve().parent / "eval")
        if eval_dir not in sys.path:
            sys.path.insert(0, eval_dir)
        import relevance
        _snapshots, _, _ = relevance.load_context()
    return _snapshots


def resolve_players(players, snapshots, as_of):
    """(requested: [{name, id, forms}], ambiguous: {name: [labels]}, unmapped: [names])"""
    _, boot = snapshots.get(as_of)
    cands = pn.candidates_from_bootstrap(boot)
    requested, ambiguous, unmapped = [], {}, []
    for name in players or []:
        hits = pn.match_players(name, cands)
        if len(hits) == 1:
            c = hits[0]
            forms = [f for f in (c["web_name"], c["first_name"], c["second_name"]) if f and f.strip()]
            requested.append({"name": name, "id": c["id"], "forms": forms, "web_name": c["web_name"]})
        elif not hits:
            unmapped.append(name)
        else:
            ambiguous[name] = [pn.label(c) for c in hits]
    return requested, ambiguous, unmapped


def club_terms(clubs):
    aliases = getattr(config_roles, "TEAM_ALIASES", {}) or {}
    out = []
    for c in clubs or []:
        out.append(str(c))
        for k, v in aliases.items():
            if pn.norm(k) == pn.norm(c):
                out.extend(v)
    return out


# ---- the query -----------------------------------------------------------------------------------------

def _sql(has_vector, n_terms):
    k, w = "%(k)s", "%(w)s"
    parts = ["WITH live AS (SELECT DISTINCT ON (n.source, n.guid) n.id FROM news_items n WHERE n.fetched_at <= %(as_of)s "
             "ORDER BY n.source, n.guid, n.fetched_at DESC, n.version DESC), "       # newest in TIME, then by number (2026-10-01)
             ]
    parts += [
             "cand AS (SELECT c.id, c.embedding, c.tsv FROM news_chunks c JOIN live ON live.id = c.news_item_id "
             "JOIN news_to_embed e ON e.id = c.news_item_id WHERE c.chunker_version = %(cv)s AND c.embed_model = %(model)s)"]
    lists = []
    if has_vector:
        parts.append(", dense AS (SELECT id, row_number() OVER (ORDER BY embedding <=> %(qvec)s::vector, id) AS r FROM cand "
                     "ORDER BY embedding <=> %(qvec)s::vector, id LIMIT %(n)s)")
        lists.append("dense")
    if n_terms:
        tsq = " || ".join(f"plainto_tsquery('fpl_english', %(t{i})s)" for i in range(n_terms))
        parts.append(f", kw AS (SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, ({tsq})) DESC, id) AS r FROM cand "
                     f"WHERE tsv @@ ({tsq}) ORDER BY ts_rank_cd(tsv, ({tsq})) DESC, id LIMIT %(n)s)")
        lists.append("kw")
    if not lists:
        return None
    if lists == ["dense", "kw"]:
        parts.append(f", fused AS (SELECT COALESCE(d.id, kw.id) AS id, d.r AS r_dense, kw.r AS r_kw, "
                     f"COALESCE(1.0 / ({k} + d.r), 0) + {w} * COALESCE(1.0 / ({k} + kw.r), 0) AS score "
                     f"FROM dense d FULL OUTER JOIN kw ON kw.id = d.id)")
    elif lists == ["dense"]:
        parts.append(f", fused AS (SELECT id, r AS r_dense, NULL::bigint AS r_kw, 1.0 / ({k} + r) AS score FROM dense)")
    else:
        parts.append(f", fused AS (SELECT id, NULL::bigint AS r_dense, r AS r_kw, {w} * (1.0 / ({k} + r)) AS score FROM kw)")
    parts.append(" SELECT f.id, f.score, f.r_dense, f.r_kw, c.news_item_id, n.source, n.club, n.url, n.published_at, n.fetched_at, "
                 "n.date_source, n.headline, n.element_id, c.chunk_text, v.players, v.player_ids "
                 "FROM fused f JOIN news_chunks c ON c.id = f.id JOIN news_items n ON n.id = c.news_item_id "
                 "JOIN relevance_production p ON TRUE "
                 "JOIN news_relevance v ON v.news_item_id = n.id AND v.prompt_version = p.prompt_version AND v.model = p.model "
                 "ORDER BY f.score DESC, f.id LIMIT %(n)s")
    return "".join(parts)


def _vector_literal(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _candidates(conn, as_of, qvec, terms):
    sql = _sql(qvec is not None, len(terms))
    if sql is None:
        return []
    params = {"as_of": as_of, "cv": ch.CHUNKER_VERSION, "model": config_roles.EMBED_MODEL, "n": config_roles.SEARCH_CANDIDATES,
              "k": config_roles.SEARCH_RRF_K, "w": config_roles.SEARCH_KW_WEIGHT}
    if qvec is not None:
        params["qvec"] = _vector_literal(qvec)
    for i, t in enumerate(terms):
        params[f"t{i}"] = t
    cols = ("id", "score", "r_dense", "r_kw", "news_item_id", "source", "club", "url", "published_at", "fetched_at",
            "date_source", "headline", "element_id", "chunk_text", "players", "player_ids")
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---- the tool --------------------------------------------------------------------------------------------

def _result(row, as_of, about):
    when, basis = date_basis(row)
    when = _utc(when)
    players = list(row.get("players") or [])
    if row["source"] == "fpl" and not players:
        players = [str(row.get("headline") or "").split(" (")[0]]
    return {"id": f"c{row['id']}", "source": source_label(row["source"], row.get("club")), "headline": row.get("headline") or "",
            "url": row.get("url"), "date": when.strftime("%Y-%m-%d"), "date_basis": basis, "age": human_age(as_of - when),
            "about_requested_player": bool(about), "players": players, "text": row["chunk_text"]}


def _log(conn, query, players, clubs, resolved_ids, as_of, mode, cands, returned, timings, error):
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO search_log (query, players, clubs, resolved_ids, as_of, search_mode, candidates, returned_ids, "
                        "embed_ms, sql_ms, total_ms, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (query, list(players or []), list(clubs or []), resolved_ids, as_of, mode,
                         json.dumps([{"id": c["id"], "item": c["news_item_id"], "score": float(c["score"]), "boosted": c.get("boosted"),
                                      "r_dense": c["r_dense"], "r_kw": c["r_kw"]} for c in cands]),
                         returned, timings.get("embed_ms"), timings.get("sql_ms"), timings.get("total_ms"), error))
        conn.commit()
    except Exception:                                   # noqa: BLE001 -- the log must never break the answer
        conn.rollback()


def search_news(query, players=None, clubs=None, *, as_of=None, conn=None, embed_client=None, snapshots=None):
    """See the module docstring. Returns the JSON-ready dict the agent receives."""
    global _pacer
    t0 = time.perf_counter()
    as_of = _utc(as_of) if as_of is not None else datetime.now(UTC)
    players, clubs = list(players or []), list(clubs or [])
    own_conn = conn is None
    if own_conn:
        import db_write
        conn = db_write.connect()
    try:
        snaps = snapshots or _load_snapshots()
        requested, ambiguous, unmapped = resolve_players(players, snaps, as_of)
        requested_ids = [r["id"] for r in requested]
        terms = [f for r in requested for f in r["forms"]] + club_terms(clubs)
        timings, error, qvec = {}, None, None
        if _pacer is None:
            _pacer = em.Pacer(config_roles.EMBED_RPM, config_roles.EMBED_TPM)
        t1 = time.perf_counter()
        try:
            [qvec] = em.embed([query], "query", client=embed_client, conn=conn, purpose="search_news", pacer=_pacer)
        except Exception as e:                          # noqa: BLE001 -- any failure -> keyword-only
            qvec, error = None, f"embed failed: {type(e).__name__}: {str(e)[:300]}"
            conn.rollback()
        timings["embed_ms"] = int((time.perf_counter() - t1) * 1000)
        mode = "hybrid" if qvec is not None and terms else ("dense_only" if qvec is not None else "keyword_only")
        t2 = time.perf_counter()
        cands = _candidates(conn, as_of, qvec, terms)
        timings["sql_ms"] = int((time.perf_counter() - t2) * 1000)
        for c in cands:
            when, _ = date_basis(c)
            age_days = (as_of - _utc(when)).total_seconds() / 86400
            c["boosted"] = float(c["score"]) * recency_multiplier(age_days)
        cands.sort(key=lambda c: (-c["boosted"], c["id"]))
        per_article, kept = {}, []
        for c in cands:
            n = per_article.get(c["news_item_id"], 0)
            if n < config_roles.SEARCH_MAX_PER_ARTICLE:
                per_article[c["news_item_id"]] = n + 1
                kept.append(c)
        ids = set(requested_ids)

        def about(c):
            if c["source"] == "fpl":
                return c.get("element_id") in ids
            return any(p in ids for p in (c.get("player_ids") or []))
        about_rows = [c for c in kept if ids and about(c)]
        top = config_roles.SEARCH_TOP_N
        if players:                                   # named players: ONLY about-results, never fillers (ruling 2026-09-30)
            chosen = about_rows[:top]
        else:                                         # clubs or query only: the best candidates, labelled not-about
            chosen = kept[:top]
        seen_about = {p for c in about_rows for p in ((c.get("player_ids") or []) if c["source"] != "fpl" else [c.get("element_id")])}
        no_news = [r["name"] for r in requested if r["id"] not in seen_about] + unmapped
        results = [_result(c, as_of, about(c) if ids else False) for c in chosen]
        timings["total_ms"] = int((time.perf_counter() - t0) * 1000)
        _log(conn, query, players, clubs, requested_ids, as_of, mode, cands, [int(r["id"][1:]) for r in results], timings, error)
        return {"as_of": _iso(as_of), "search_mode": mode, "no_news_for": no_news, "ambiguous_players": ambiguous, "results": results}
    finally:
        if own_conn:
            conn.close()


# ---- the citation check (Part 5, log only) -------------------------------------------------------------------

def record_citation_check(turn_id, cited, returned, violations, conn=None):
    own = conn is None
    if own:
        import db_write
        conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO citation_checks (turn_id, cited, returned, violations) VALUES (%s, %s, %s, %s)",
                        (turn_id, list(cited), list(returned), list(violations)))
        conn.commit()
    finally:
        if own:
            conn.close()
