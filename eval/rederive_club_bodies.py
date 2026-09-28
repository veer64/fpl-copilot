"""Re-derive club bodies from the pages we already fetched (2026-09-28, KNOWN_ISSUES #27). Zero Tavily
credits, zero requests: for every club row whose stored body fails club_news.looks_like_link_list(),
read the saved page (data/news/raw/tavily/pages/<sha1(guid)>.json.gz, plus any --pages dir) and, if
club_news.page_article_body() yields real text, store it as a NEW VERSION of the item (the versioning
rule: a different content hash is a new version) with body_source set. Rows whose page yields
nothing are left as they are and listed.

    uv run python eval/rederive_club_bodies.py --club "Man Utd" [--pages <dir> ...] [--dry-run]
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import club_news as cn  # noqa: E402
import db_write  # noqa: E402
import news_store as ns  # noqa: E402


def load_page(guid, dirs):
    name = hashlib.sha1(guid.encode()).hexdigest() + ".json.gz"
    for d in dirs:
        p = Path(d) / name
        if p.exists():
            return p, json.loads(gzip.decompress(p.read_bytes()))
    return None, None


def rederive(conn, club=None, ids=None, page_dirs=(), dry_run=False, log=print):
    dirs = [cn.RAW_DIR / "pages"] + [Path(d) for d in page_dirs]
    with conn.cursor() as cur:
        sql = ("SELECT DISTINCT ON (guid) id, guid, url, headline, body, published_at, fetched_at, club, date_source, raw_ref "
               "FROM news_items WHERE source = 'club'")
        params = []
        if club:
            sql += " AND club = %s"; params.append(club)
        if ids:
            sql += " AND id = ANY(%s)"; params.append(list(ids))
        cur.execute(sql + " ORDER BY guid, version DESC", params)
        rows = cur.fetchall()
    out = {"checked": 0, "clean": 0, "no_page": [], "no_body": [], "rederived": []}
    for iid, guid, url, headline, body, published_at, fetched_at, club_name, date_source, raw_ref in rows:
        out["checked"] += 1
        bad, why = cn.looks_like_link_list(body)
        if not bad:
            out["clean"] += 1
            continue
        path, page = load_page(guid, dirs)
        if page is None:
            out["no_page"].append(iid)
            log(f"  #{iid} {club_name}: extract is a link list ({why}); no saved page")
            continue
        text, source = cn.page_article_body(page.get("html") or "")
        if not text:
            out["no_body"].append(iid)
            log(f"  #{iid} {club_name}: extract is a link list ({why}); the saved page yields no article text")
            continue
        out["rederived"].append((iid, len(body or ""), len(text), source))
        log(f"  #{iid} {club_name}: {len(body or '')} -> {len(text)} chars from {source} ({path.parent.name}/{path.name[:12]}...)")
        if not dry_run:
            ns.upsert_versions(conn, "club", [{
                "guid": guid, "url": url, "headline": headline, "body": text, "published_at": published_at,
                "fetched_at": fetched_at, "raw_ref": f"rederived:{path.name}", "content_hash": ns.content_hash(headline, text),
                "club": club_name, "date_source": date_source, "body_source": source}])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--club", default=None)
    ap.add_argument("--ids", default=None, help="comma-separated news_items ids")
    ap.add_argument("--pages", action="append", default=[], help="extra directories of saved pages (searched after the raw dir)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ids = [int(x) for x in a.ids.split(",") if x.strip()] if a.ids else None
    conn = db_write.connect()
    try:
        ns.ensure_schema(conn)
        r = rederive(conn, club=a.club, ids=ids, page_dirs=a.pages, dry_run=a.dry_run)
    finally:
        conn.close()
    print(f"checked {r['checked']}, clean {r['clean']}, rederived {len(r['rederived'])}, no page {r['no_page']}, no body on page {r['no_body']}"
          + (" (dry run, nothing written)" if a.dry_run else ""))


if __name__ == "__main__":
    main()
