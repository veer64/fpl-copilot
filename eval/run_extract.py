"""Standalone availability extraction runner (Piece 9, 2026-10-01): one structured claim per player per
club / bbc article in news_to_embed, under prompt extract_v1 and the production judge model. See
extraction.py for the rules; the two news runners (fetch_news.py, fetch_club_news.py) call the same
function after the relevance filter and before the embedding step. Record and measure only (D9).

Usage:
    uv run python eval/run_extract.py --dry-run             # render only: what would go to the LLM, zero calls
    uv run python eval/run_extract.py --limit 20            # extract the oldest 20 pending items
    uv run python eval/run_extract.py --max-calls 30        # send at most 30 items this run
    uv run python eval/run_extract.py --ids 454,466         # only these items (still only if pending)
"""
import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import db_write  # noqa: E402
import news_store as ns  # noqa: E402
import extraction as ex  # noqa: E402


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="extract at most this many pending items (oldest first)")
    ap.add_argument("--max-calls", type=int, default=None, help="send at most this many items to the LLM")
    ap.add_argument("--dry-run", action="store_true", help="render only; print what would go to the LLM; write nothing")
    ap.add_argument("--ids", default=None, help="comma-separated news_items ids: only these (still only if pending)")
    a = ap.parse_args()
    conn = None
    try:
        conn = db_write.connect()
        ns.ensure_schema(conn)
        ids = [int(x) for x in a.ids.split(",") if x.strip()] if a.ids else None
        ex.run_extract(conn, a.limit, dry_run=a.dry_run, max_calls=a.max_calls, log=log, ids=ids)
    except Exception:
        log("FAILED:\n" + traceback.format_exc()[-2000:])
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
