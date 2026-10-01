"""Backfill news_relevance.player_ids for every verdict that has none (2026-09-30, Piece 7): the
names in each verdict's players list are mapped to FPL element ids by player_names against the
bootstrap squad as of the item's fetched_at, with the article's club as context; FPL rows carry
their element_id. No LLM calls. Prints the counts and up to 10 examples of each failure kind.

Usage:
    uv run python eval/backfill_player_ids.py            # map every verdict without player_ids
    uv run python eval/backfill_player_ids.py --dry-run  # count and show, write nothing
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
    ap.add_argument("--dry-run", action="store_true", help="count and show; write nothing")
    a = ap.parse_args()
    conn = None
    try:
        conn = db_write.connect()
        ns.ensure_schema(conn)
        stats = rv.backfill_player_ids(conn, log=log, dry_run=a.dry_run)
        print(f"verdicts {stats['verdicts']} (fpl {stats['fpl_rows']}); names seen {stats['names_seen']}, mapped {stats['mapped']}, "
              f"unmapped {stats['unmapped']}, ambiguous {stats['ambiguous']}" + (" (dry run, nothing written)" if a.dry_run else ""))
        for kind in ("unmapped", "ambiguous"):
            print(f"--- {kind} examples ({min(10, len(stats['examples'][kind]))} of {stats[kind]}) ---")
            for ex in stats["examples"][kind][:10]:
                print(f"  item {ex['item_id']} ({ex['source']}, club {ex['club']}): {ex['name']!r}"
                      + (f" -> {ex['candidates']}" if ex.get("candidates") else ""))
    except Exception:
        log("FAILED:\n" + traceback.format_exc()[-2000:])
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
