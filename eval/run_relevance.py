"""Standalone relevance runner (2026-09-26): judge the news_items rows that have no verdict
for the current PROMPT_VERSION. See relevance.py for the rules; the two ingestion runners
(fetch_news.py, fetch_club_news.py) call the same function at the end of every run.

Usage:
    uv run python eval/run_relevance.py --dry-run             # stage 1 only: what would go to the LLM, zero calls
    uv run python eval/run_relevance.py --limit 50            # judge the oldest 50 unjudged rows
    uv run python eval/run_relevance.py --max-calls 150       # send at most 150 items to the LLM this run
    uv run python eval/run_relevance.py --model claude-sonnet-5                      # another model, beside production
    uv run python eval/run_relevance.py --model claude-opus-5-5 --prompt-version reference_v1   # the reference labels
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
import relevance as rv  # noqa: E402


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="judge at most this many unjudged rows (oldest first)")
    ap.add_argument("--max-calls", type=int, default=None, help="send at most this many items to the LLM")
    ap.add_argument("--dry-run", action="store_true", help="stage 1 only; print what would go to the LLM; write nothing")
    ap.add_argument("--model", default=None, help="judge under this model instead of config RELEVANCE_MODEL (verdicts sit beside)")
    ap.add_argument("--prompt-version", default=None, help="judge under this prompt version instead of config PROMPT_VERSION")
    ap.add_argument("--ids", default=None, help="comma-separated news_items ids: judge only these (still only if unjudged)")
    a = ap.parse_args()
    conn = None
    try:
        conn = db_write.connect()
        ns.ensure_schema(conn)
        ids = [int(x) for x in a.ids.split(",") if x.strip()] if a.ids else None
        rv.run_relevance(conn, a.limit, dry_run=a.dry_run, max_calls=a.max_calls, log=log, model=a.model, prompt_version=a.prompt_version, ids=ids)
    except Exception:
        log("FAILED:\n" + traceback.format_exc()[-2000:])
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
