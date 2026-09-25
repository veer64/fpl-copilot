"""Club-news ingestion runner, v2 (2026-09-25): the nine club sites in
config_roles.CLUB_NEWS_CLUBS, searched only inside the deadline window of the next
gameweek, dated from the page / the URL / a dateline, guarded against old articles, then
extracted into news_items as source 'club'. Every rule is in club_news.py.

Usage:
    uv run python eval/fetch_club_news.py                      # normal run; the gate decides
    uv run python eval/fetch_club_news.py --seed               # undated new items get 'backlog'
    uv run python eval/fetch_club_news.py --clubs Arsenal,Chelsea
    uv run python eval/fetch_club_news.py --now 2026-09-18T17:30:00Z --replay <raw dir>
                                                               # rebuild from saved raw files: zero Tavily
                                                               # calls, zero HTTP requests, no ledger rows

Exit codes: 0 ran, or outside the window (no calls); 2 the credit guard refused; 1 any
other failure. Never prints the key.

Cron (prepared 2026-09-25, NOT installed): daily at 15:07 UTC, the news runner's flock and
`docker compose run` pattern, off every existing tick; the gate decides whether it searches:
    7 15 * * * cd /root/fpl-copilot && flock -n /tmp/fpl-clubnews.lock docker compose run --rm fpl-scheduler uv run python eval/fetch_club_news.py >> /var/log/fpl-clubnews.log 2>&1
"""
import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO / ".env")
import db_write  # noqa: E402
import club_news as cn  # noqa: E402
from config_roles import CLUB_DOMAINS, CLUB_NEWS_CLUBS  # noqa: E402

RAW_DIR = cn.RAW_DIR


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def utcnow():
    return datetime.now(timezone.utc)


def make_tavily():
    return cn.TavilyClient()


def make_http(raw_dir):
    return cn.PageFetcher()


def _newest_snapshot():
    import poll_availability as pa
    seasons = sorted(p.name for p in (pa.LIVE / "bootstrap_raw").glob("*") if p.is_dir())
    if not seasons:
        raise RuntimeError("no raw bootstrap archive: data/live/bootstrap_raw/<season>/ is empty")
    season = seasons[-1]
    snaps = pa.list_raw(season)
    if not snaps:
        raise RuntimeError(f"no raw snapshot under data/live/bootstrap_raw/{season}/")
    return season, pa.load_raw(snaps[-1][1])


def load_events():
    return _newest_snapshot()[1]["events"]


def load_teams():
    return _newest_snapshot()[1]["teams"]


def load_opponents(gw, teams):
    season = _newest_snapshot()[0]
    return cn.opponents_from_rows(cn.fixture_rows_for_gw(gw, season), teams)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", action="store_true", help="undated new items get 'backlog' instead of 'first_seen'")
    ap.add_argument("--clubs", default=None, help="comma-separated FPL team names (default: CLUB_NEWS_CLUBS)")
    ap.add_argument("--replay", default=None, help="rebuild from this raw directory: no Tavily calls, no HTTP requests")
    ap.add_argument("--now", default=None, help="ISO-8601 UTC clock for the gate and the stamps (default: now)")
    a = ap.parse_args()
    now = cn.parse_iso(a.now) if a.now else utcnow()
    if a.now and now is None:
        log(f"unreadable --now {a.now!r}")
        sys.exit(1)
    names = [c.strip() for c in a.clubs.split(",")] if a.clubs else list(CLUB_NEWS_CLUBS)
    unknown = [c for c in names if c not in CLUB_DOMAINS]
    if unknown:
        log(f"unknown club(s): {unknown}; known: {sorted(CLUB_DOMAINS)}")
        sys.exit(1)
    clubs = {c: CLUB_DOMAINS[c] for c in names}

    g = cn.gate(now, load_events())
    if not g["open"]:
        if g["gw"] is None:
            log("outside window, no future deadline in the newest snapshot's events")
        else:
            log(f"outside window, next window opens {g['opens_at']:%Y-%m-%dT%H:%M:%SZ} "
                f"(GW{g['gw']} deadline {g['deadline']:%Y-%m-%dT%H:%M:%SZ}); no calls made")
        sys.exit(0)
    log(f"inside window: GW{g['gw']} deadline {g['deadline']:%Y-%m-%dT%H:%M:%SZ}, window from {g['opens_at']:%Y-%m-%dT%H:%M:%SZ}")
    teams = load_teams()
    aliases = cn.team_aliases(teams)
    opponents = load_opponents(g["gw"], teams)
    if a.replay:
        raw_dir = Path(a.replay)
        tavily, http = cn.ReplayTavily(raw_dir), cn.ReplayHttp(raw_dir)
    else:
        raw_dir = RAW_DIR
        tavily, http = make_tavily(), make_http(raw_dir)

    conn = None
    try:
        conn = db_write.connect()
        summary = cn.run(conn, clubs, tavily, now=now, seed=a.seed, raw_dir=raw_dir, log=log, http=http,
                         window=g["window"], opponents=opponents, aliases=aliases, replay=bool(a.replay))
    except cn.CreditLimit as e:
        log(f"REFUSED by the credit guard: {e}")
        sys.exit(2)
    except Exception:
        log("FAILED:\n" + traceback.format_exc()[-2000:])
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()
    log("per club: " + "; ".join(f"{c}: results {s['results']}, kept {s['kept']}, dropped {len(s['dropped'])} + guard {s['guard_dropped']}, "
                                 f"new {s['new']}, seen {s['already_seen']}, extracted {s['extracted']}"
                                 for c, s in summary["clubs"].items()))


if __name__ == "__main__":
    main()
