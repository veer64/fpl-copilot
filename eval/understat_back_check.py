# understat_back_check.py -- Prompt R2 PART 4 (4 Nov 2026): is understat back? If the per-match file carries FALLBACK rows
# (eval/understat_fallback.py: a gameweek ingested from FPL xG while understat was down), probe understat with ONE
# request; when it answers the league JSON again, re-run the understat steps of the weekly ingest in their runbook
# order (understat_matches rewrites the per-match file from understat -- the fallback rows vanish -- then the season
# aggregates, their --combine, and the crosswalk), let the next scheduled build pick the real rows up, and ping the
# phone ONCE per replaced gameweek through eval/health_alert.py's ntfy push (NTFY_TOPIC from the environment; the
# title's tick travels as the ntfy tag, an HTTP header cannot carry it).
#
# No fallback rows -> nothing: no request at all. Understat still down -> WAITING, no steps. A step that fails ->
# FAILED (exit 1), the fallback rows stay, the next tick tries again.
#
# Status: data/live/UNDERSTAT_BACK.txt (first line IDLE / WAITING / REPLACED / FAILED); pings:
# data/live/understat_back_pings.json. Cron (server crontab, hourly, off every other tick, under the dispatcher's lock
# while it may rewrite the volume):
#   49 * * * * cd /root/fpl-copilot && flock -n /tmp/fpl-usback.lock flock -n /tmp/fpl-dispatch.lock \
#       docker compose run --rm fpl-scheduler uv run python eval/understat_back_check.py --season 2026-27 \
#       >> /var/log/fpl-usback.log 2>&1
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import understat_fallback as usf  # noqa: E402

PY = sys.executable
STEP_TIMEOUT = 1800
TITLE = "FPL Copilot: understat is back"
STEPS = [
    ("understat_matches", ["eval/understat_matches.py", "--season", "{season}"]),
    ("build_understat_aggregates", ["eval/build_understat_aggregates.py", "--season", "{season}"]),
    ("build_understat_aggregates --combine", ["eval/build_understat_aggregates.py", "--season", "{season}", "--combine"]),
    ("build_crosswalk", ["eval/build_crosswalk.py", "--season", "{season}"]),
]


def _subprocess(args, timeout):
    r = subprocess.run([PY] + args, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout


def _probe_for(season):
    import understat_matches as um
    return lambda: usf.probe_once(um.SEASONS[season])


def _push(title, message):
    """The repo's ntfy helper (eval/health_alert.push) with the topic from the environment; returns the HTTP status
    (None when no topic is configured, 0 when the push failed)."""
    import health_alert as h
    topic = os.environ.get("NTFY_TOPIC")
    server = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
    if not topic:
        return None
    status = {}
    orig = urllib.request.urlopen

    def rec(req, *a, **k):
        req.add_header("Tags", "white_check_mark")
        r = orig(req, *a, **k)
        status["http"] = r.status
        return r
    h.urllib.request.urlopen = rec
    try:
        ok = h.push(server, topic, dict(key="understat_back", title=title, message=message, priority=3))
    finally:
        h.urllib.request.urlopen = orig
    return status.get("http") if ok else 0


def _write(path, text):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".usb.", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def check(season, data_dir=None, probe=None, run_cmd=None, push=None, now=None):
    data_dir = Path(data_dir) if data_dir else REPO / "data"
    live = data_dir / "live"
    live.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    status_p = live / "UNDERSTAT_BACK.txt"

    def done(first, body="", code=0):
        _write(status_p, f"{first}\nunderstat-back check {season} -- {now:%Y-%m-%d %H:%M:%S}Z -- data {data_dir}\n{body}\n")
        print(f"understat-back -> {status_p.name}: {first}")
        return code

    gws = usf.fallback_gws(data_dir, season)
    if not gws:
        return done(f"IDLE -- no fallback rows for {season} on the volume; no probe made")
    ok, why = (probe or _probe_for(season))()
    if not ok:
        return done(f"WAITING -- understat still down for GW{gws}: {why}")
    run_cmd = run_cmd or _subprocess
    log = []
    for name, args in STEPS:
        args = [a.format(season=season) for a in args]
        code, out = run_cmd(args, STEP_TIMEOUT)
        log.append(f"===== {name} exit {code} =====\n{(out or '')[-2000:]}")
        if code != 0:
            return done(f"FAILED -- understat answered JSON ({why}) but step '{name}' exited {code}; "
                        f"fallback rows for GW{gws} kept, next tick retries", "\n".join(log), code=1)
    remaining = usf.sync_sidecar(data_dir, season, now=now)
    replaced = [g for g in gws if g not in remaining]
    man_p = live / "ingest_manifest_latest.json"
    if man_p.exists():
        try:
            man = json.loads(man_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            man = {}
        man["understat_fallback_gws"] = remaining
        man["understat_restored_at"] = now.isoformat()
        _write(man_p, json.dumps(man, indent=1))
    pings_p = live / "understat_back_pings.json"
    pinged = {}
    if pings_p.exists():
        try:
            pinged = json.loads(pings_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pinged = {}
    push = push or _push
    notes = []
    for g in replaced:
        if str(g) in pinged:
            continue
        st = push(TITLE, f"GW{g} replaced with real xG.")
        pinged[str(g)] = {"at": now.isoformat(), "http": st}
        notes.append(f"GW{g}: ntfy {st}")
    _write(pings_p, json.dumps(pinged, indent=1))
    return done(f"REPLACED GW{replaced} from understat ({why}); fallback still in effect for GW{remaining}; "
                + ("; ".join(notes) or "no new ping"), "\n".join(log))


def main(argv=None):
    ap = argparse.ArgumentParser(description="re-ingest fallback gameweeks from understat once it answers again")
    ap.add_argument("--season", required=True)
    ap.add_argument("--data-dir", default=None, help="(tests) data directory override")
    a = ap.parse_args(argv)
    return check(a.season, data_dir=a.data_dir)


if __name__ == "__main__":
    sys.exit(main())
