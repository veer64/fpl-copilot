"""Standalone chunk + embed runner (2026-09-30): every news_to_embed item without news_chunks
rows for the current (chunker version, model) is chunked and embedded. See embed_pipeline.py for
the rules; the two ingestion runners (fetch_news.py, fetch_club_news.py) call the same function at
the end of every run, after the relevance filter.

Usage:
    uv run python eval/run_embed.py --dry-run                 # chunk only: counts and samples, zero Voyage calls, nothing written
    uv run python eval/run_embed.py --dry-run --show 3        # ... and print 3 club articles fully chunked, 2 FPL chunks, the BBC chunks
    uv run python eval/run_embed.py --limit 50                # embed the 50 oldest pending items
    uv run python eval/run_embed.py                           # embed everything pending

Without the vector extension the step logs "pgvector not installed, embedding skipped" and exits 0.
"""
import argparse
import statistics
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import db_write  # noqa: E402
import news_store as ns  # noqa: E402
import embed_pipeline as ep  # noqa: E402


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def _mmm(values):
    return f"min {min(values)} / median {int(statistics.median(values))} / max {max(values)}" if values else "none"


def print_dry_run(summary, show):
    """counts by source, chunks per club article, char_count per chunk; then `show` club articles
    in full, 2 FPL chunks and every BBC chunk"""
    chunked = summary.get("chunked") or []
    print(f"chunker {summary.get('chunker_version')} / model {summary.get('model')}")
    print(f"items by source: {', '.join(f'{k} {v['items']}' for k, v in sorted(summary['by_source'].items()))}")
    print(f"chunks by source: {', '.join(f'{k} {v['chunks']}' for k, v in sorted(summary['by_source'].items()))}")
    print(f"club bodies changed by rule: {', '.join(f'{k} {v}' for k, v in (summary.get('fixes') or {}).items())}")
    club_counts = [len(c) for it, c in chunked if it["source"] == "club"]
    print(f"chunks per club article: {_mmm(club_counts)} (n = {len(club_counts)})")
    chars = [k.char_count for _, c in chunked for k in c]
    print(f"char_count per chunk: {_mmm(chars)} (n = {len(chars)})")
    for src in ("club", "fpl", "bbc"):
        print(f"char_count per chunk, {src}: {_mmm([k.char_count for it, c in chunked if it['source'] == src for k in c])}")
    if not show:
        return
    shown = {"club": 0, "fpl": 0}
    for it, chunks in chunked:
        src = it["source"]
        if src == "club" and shown["club"] >= show:
            continue
        if src == "fpl" and shown["fpl"] >= 2:
            continue
        if src in shown:
            shown[src] += 1
        print(f"\n===== item {it['id']} ({src}): {len(chunks)} chunk(s), embed_text {len(it['embed_text'])} chars =====")
        for c in chunks:
            print(f"--- chunk {c.index} ({c.char_count} chars) ---")
            print(c.text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="embed at most this many pending items (oldest first)")
    ap.add_argument("--dry-run", action="store_true", help="chunk only; print counts and samples; zero Voyage calls; write nothing")
    ap.add_argument("--show", type=int, default=0, help="with --dry-run: print this many club articles fully chunked (plus 2 FPL, all BBC)")
    ap.add_argument("--ids", default=None, help="comma-separated news_items ids: only these (still only if pending)")
    a = ap.parse_args()
    conn = None
    try:
        conn = db_write.connect()
        ns.ensure_schema(conn)
        ids = [int(x) for x in a.ids.split(",") if x.strip()] if a.ids else None
        summary = ep.embed_pending(conn, a.limit, dry_run=a.dry_run, log=log, ids=ids)
        if a.dry_run and summary.get("items"):
            print_dry_run(summary, a.show)
    except Exception:
        log("FAILED:\n" + traceback.format_exc()[-2000:])
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
