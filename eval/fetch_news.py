"""News ingestion v1 runner (2026-09-25): one conditional BBC fetch, one FPL snapshot into
the raw archive, then the versioned store. See news_store.py for every rule.

Usage:
    uv run python eval/fetch_news.py --season 2026-27                 # bbc + fpl (store + derive)
    uv run python eval/fetch_news.py --season 2026-27 --no-bbc         # fpl only
    uv run python eval/fetch_news.py --season 2026-27 --no-fpl-store   # derive from the archive as it is
    uv run python eval/fetch_news.py --season 2026-27 --no-bbc --no-fpl-store --archive <dir>
                                                                        # backfill from a READ-ONLY copy

Each run logs, per source: fetched, new, new versions, skipped, errors (and the HTTP
status for BBC). Exit 1 on any exception; a 304 is a normal, quiet run.

Cron (prepared 2026-09-25, NOT installed): every 4 hours at :37, off every existing tick
(*/10 ticks, :17 ingest, 03:43 backup, 11:00 nightly):
    37 */4 * * * cd /root/fpl-copilot && flock -n /tmp/fpl-news.lock docker compose run --rm fpl-scheduler uv run python eval/fetch_news.py --season 2026-27 >> /var/log/fpl-news.log 2>&1
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

SOURCE_NEWS = "news_fetch"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def run_bbc(conn, now):
    r = ns.fetch_rss(ns.BBC_URL, ns.RAW_DIR / "bbc", now=now)
    if r["status"] == 304:
        log("bbc: http 304 (not modified) -- fetched 0, new 0, new_versions 0, skipped 0, errors 0, no raw file")
        return {"http": 304}
    c = ns.ingest_rss(conn, r["body"], raw_ref=r["raw_ref"], fetched_at=now, source="bbc")
    log(f"bbc: http 200, fetched {c['fetched']}, new {c['new']}, new_versions {c['new_versions']}, "
        f"skipped {c['skipped']}, errors {c['errors']}, raw {r['raw_ref']}")
    return {"http": 200, **c}


def run_fpl(conn, season, store, archive):
    import poll_availability as pa
    if store:
        path, ts = pa.fetch_and_store(season, source=SOURCE_NEWS)
        log(f"fpl: stored {path.name} (origin {SOURCE_NEWS}) at {ts:%Y-%m-%dT%H:%M:%SZ}")
    d = Path(archive) if archive else pa.LIVE / "bootstrap_raw" / season
    c = ns.derive_fpl(conn, d, season)
    log(f"fpl: snapshots {c['snapshots']}, fetched {c['fetched']}, new {c['new']}, new_versions {c['new_versions']}, "
        f"skipped {c['skipped']}, errors {c['errors']}, archive {d}")
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--no-bbc", action="store_true", help="skip the BBC fetch")
    ap.add_argument("--no-fpl", action="store_true", help="skip FPL entirely")
    ap.add_argument("--no-fpl-store", action="store_true", help="do not fetch a new FPL snapshot; derive from the archive as it is")
    ap.add_argument("--archive", default=None, help="derive FPL news from this snapshot directory instead of data/live/bootstrap_raw/<season>")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    try:
        conn = db_write.connect()
        ns.ensure_schema(conn)
        if not a.no_bbc:
            run_bbc(conn, now)
        if not a.no_fpl:
            run_fpl(conn, a.season, store=not a.no_fpl_store and not a.archive, archive=a.archive)
        conn.close()
    except Exception:
        log("FAILED:\n" + traceback.format_exc()[-2000:])
        sys.exit(1)


if __name__ == "__main__":
    main()
