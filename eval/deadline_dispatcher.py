# deadline_dispatcher.py -- the weekly-pipeline trigger that follows the
# deadline instead of hardcoding it.
#
# MECHANISM: host cron runs this every 10 minutes (UTC box, UTC cron -- FPL
# deadlines are UTC, so no timezone conversion exists anywhere in the chain).
# Each tick pulls bootstrap-static (30s timeout), takes the next event whose
# deadline is still ahead, and fires the unattended deadline build
# (eval/run_live_deadline.py) once `now >= deadline - 90min`. Hardcoded
# schedules drift as FPL moves deadlines week to week; deriving the time from
# the API at every tick cannot.
#
# FIRE-ONCE, BOUNDED-RETRY: a success marker (data/live/dispatch_gw{N}.done)
# ends the gameweek's dispatching. A FAILED run writes an attempt count
# instead and the next tick retries -- at most MAX_ATTEMPTS per gameweek, so
# a persistent failure surfaces as a final FAILED status file rather than a
# silent every-10-minutes credit burn. Nothing is swallowed: the child's exit
# code decides, and its own status file (GW{N}_BUILD_STATUS.txt) carries the
# findings either way.
#
# Usage: python eval/deadline_dispatcher.py --season 2026-27 [--lead-min 90]

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "data" / "live"
MAX_ATTEMPTS = 3


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--lead-min", type=int, default=90)
    a = ap.parse_args()

    events = requests.get(
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        timeout=30).json()["events"]
    now = datetime.now(timezone.utc)
    nxt = None
    for e in events:
        dl = datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))
        if dl > now:
            nxt = (e["id"], dl)
            break
    if nxt is None:
        log("no future deadline in bootstrap -- season over, nothing to do")
        return
    gw, dl = nxt
    lead = (dl - now).total_seconds() / 60
    if lead > a.lead_min:
        log(f"GW{gw} deadline {dl:%Y-%m-%dT%H:%M}Z is {lead:.0f} min away -- "
            f"not due (fires at T-{a.lead_min})")
        return

    LIVE.mkdir(parents=True, exist_ok=True)
    done = LIVE / f"dispatch_gw{gw}.done"
    attempts_f = LIVE / f"dispatch_gw{gw}.attempts.json"
    if done.exists():
        log(f"GW{gw}: already built this window ({done.name}) -- nothing to do")
        return
    attempts = json.loads(attempts_f.read_text())["attempts"] if attempts_f.exists() else 0
    if attempts >= MAX_ATTEMPTS:
        log(f"GW{gw}: {attempts} failed attempts -- giving up for this window; "
            f"see GW{gw}_BUILD_STATUS.txt")
        return

    log(f"GW{gw}: T-{lead:.0f} min -- firing the deadline build "
        f"(attempt {attempts + 1}/{MAX_ATTEMPTS})")
    r = subprocess.run([sys.executable, str(REPO / "eval" / "run_live_deadline.py"),
                        "--season", a.season, "--gw", str(gw)],
                       cwd=str(REPO), timeout=3600)
    if r.returncode == 0:
        done.write_text(json.dumps(dict(built_at=f"{now:%Y-%m-%dT%H:%M:%S}Z",
                                        attempts=attempts + 1)), encoding="utf-8")
        log(f"GW{gw}: build SUCCEEDED -- marker written, dispatching done")
    else:
        attempts_f.write_text(json.dumps(dict(attempts=attempts + 1,
                                              last_exit=r.returncode)), encoding="utf-8")
        log(f"GW{gw}: build FAILED (exit {r.returncode}) -- will retry next tick "
            f"({attempts + 1}/{MAX_ATTEMPTS} used)")
        sys.exit(1)


if __name__ == "__main__":
    main()
