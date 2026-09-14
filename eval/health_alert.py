#!/usr/bin/env python3
"""
health_alert.py -- the CONSUMER of /health (Logs/alerting_design_2026-09-13.md, layer B).

On 2026-09-13 /health was `degraded` for 13 hours with two named reasons and nobody read it.
This probe runs on the HOST from cron every 10 minutes -- plain python3, standard library only,
no docker, no repo dependencies, no shared lock -- reads /health, compares it with its own state
file, and pushes a message to an ntfy topic when something a person should know has happened:

  DEGRADED     status != ok on TWO consecutive probes (a single blip is not a page); the reasons
               verbatim; re-pushed every RATE_LIMIT_H hours while it persists ("still degraded")
  changed      the reasons set changed while degraded
  RECOVERED    ok after a pushed degraded, with the duration
  run outcome  a deadline-day slot (t90 / t30 / t10) or post_ingest slot reached a final status
               (SUCCESS / FAILED / GAVE_UP), once per slot
  ACTION       the weekly ingest's tick line says ACTION REQUIRED, once per distinct text per day
  heartbeat    one line a day at HEARTBEAT_UTC ("fpl ok . built ... . next ...") -- the proof that
               the probe, the network, the topic and the phone are alive; its ABSENCE is the alarm
  probe error  /health unreachable on two consecutive probes (the API or the host is gone -- layer
               A, the external monitor, is the real cover for that; this is the best-effort echo)

Config (an env file, default /root/fpl-alert.env; KEY=VALUE lines):
  NTFY_TOPIC   required -- the topic name is the only secret; never in the repo
  NTFY_SERVER  default https://ntfy.sh
  HEALTH_URL   default http://127.0.0.1:8000/health
  STATE_PATH   default /var/lib/fpl-alert/state.json

Cron (host crontab, its own lock only -- it must run when the dispatcher cannot):
  */10 * * * * flock -n /tmp/fpl-alert.lock /usr/bin/python3 /root/fpl-copilot/eval/health_alert.py >> /var/log/fpl-alert.log 2>&1

Usage:  health_alert.py [--env /root/fpl-alert.env] [--dry-run] [--url URL] [--state PATH]
  --dry-run prints what it would push and does not write state (safe on a laptop against the
  live URL). Exit code 0 always except when the state file cannot be written or the topic is
  missing (both are logged on one line -- a probe that cannot alert must say so somewhere).
"""
import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

RATE_LIMIT_H = 6            # one push per (event key) per this many hours
DEBOUNCE_PROBES = 2         # degraded / unreachable must be seen this many probes in a row
HEARTBEAT_UTC = (11, 5)     # daily, after the 11:00Z nightly slot
FINAL_SLOT_STATUSES = ("SUCCESS", "FAILED", "GAVE_UP")
TIMEOUT_S = 15


# ----------------------------------------------------------------- pure core
def empty_state():
    return {"version": 1, "bad_streak": 0, "unreachable_streak": 0, "degraded_since": None,
            "degraded_pushed": False, "last_reasons": [], "last_push": {}, "slots_pushed": {},
            "actions_pushed": {}, "last_heartbeat_date": None}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _rate_ok(state, key, now):
    last = state["last_push"].get(key)
    return last is None or (now - parse_iso(last)) >= timedelta(hours=RATE_LIMIT_H)


def _mark(state, key, now):
    state["last_push"][key] = iso(now)


def _fmt_dur(td):
    h = int(td.total_seconds() // 3600); m = int((td.total_seconds() % 3600) // 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


def plan(now, health, state):
    """(events, new_state) from the current /health document (None = unreachable) and the
    previous state. Pure: no clock, no network, no files. Each event is a dict
    {key, title, message, priority} -- priority is ntfy's (1 min .. 5 max)."""
    st = json.loads(json.dumps(state))          # never mutate the caller's copy
    events = []

    # --- reachability
    if health is None:
        st["unreachable_streak"] += 1
        if st["unreachable_streak"] >= DEBOUNCE_PROBES and _rate_ok(st, "unreachable", now):
            events.append(dict(key="unreachable", title="fpl: /health UNREACHABLE",
                               message=f"{st['unreachable_streak']} consecutive probes failed -- the API or the host is down (the external monitor is the real cover)",
                               priority=5))
            _mark(st, "unreachable", now)
        return events, st
    if st["unreachable_streak"] >= DEBOUNCE_PROBES and st["last_push"].get("unreachable"):
        events.append(dict(key="reachable", title="fpl: /health reachable again",
                           message=f"after {st['unreachable_streak']} failed probes", priority=3))
    st["unreachable_streak"] = 0

    status = str(health.get("status", "unknown"))
    reasons = [str(r) for r in (health.get("reasons") or [])]
    sha = str(health.get("git_sha") or "?")[:9]

    # --- degraded / changed / recovered
    if status != "ok":
        st["bad_streak"] += 1
        if st["degraded_since"] is None:
            st["degraded_since"] = iso(now)
        if st["bad_streak"] >= DEBOUNCE_PROBES:
            body = "\n".join(f"- {r}" for r in reasons) or "- (no reason given)"
            since = parse_iso(st["degraded_since"])
            if not st["degraded_pushed"]:
                events.append(dict(key="degraded", title=f"fpl DEGRADED ({sha})",
                                   message=f"since {since:%a %H:%M}Z:\n{body}", priority=5))
                st["degraded_pushed"] = True
                _mark(st, "degraded", now)
            elif sorted(reasons) != sorted(st["last_reasons"]):
                events.append(dict(key="changed", title=f"fpl still DEGRADED, reasons changed ({sha})",
                                   message=f"since {since:%a %H:%M}Z:\n{body}", priority=4))
                _mark(st, "degraded", now)
            elif _rate_ok(st, "degraded", now):
                events.append(dict(key="still_degraded", title=f"fpl still DEGRADED ({sha})",
                                   message=f"{_fmt_dur(now - since)} so far:\n{body}", priority=4))
                _mark(st, "degraded", now)
            st["last_reasons"] = reasons
    else:
        if st["degraded_pushed"] and st["degraded_since"]:
            since = parse_iso(st["degraded_since"])
            events.append(dict(key="recovered", title=f"fpl RECOVERED ({sha})",
                               message=f"ok again after {_fmt_dur(now - since)} (was: {'; '.join(st['last_reasons']) or '?'})",
                               priority=3))
        st.update(bad_streak=0, degraded_since=None, degraded_pushed=False, last_reasons=[])

    # --- run outcomes: deadline-day and post-ingest slots reaching a final status
    fresh = health.get("data_freshness_by_source") or {}
    sched = fresh.get("schedule") or {}
    for sid, s in (sched.get("slots_this_gameweek") or {}).items():
        stt = str((s or {}).get("status") or "")
        kind = str((s or {}).get("kind") or sid.split(":")[0])
        if stt in FINAL_SLOT_STATUSES and st["slots_pushed"].get(sid) != stt:
            ok = stt == "SUCCESS"
            run = (s or {}).get("run_id")
            lr = health.get("last_run") or {}
            built = lr.get("freshness") if ok and lr.get("run_id") == run else None
            events.append(dict(key=f"slot:{sid}", title=f"fpl {sid} {stt}",
                               message=(f"run {run}: {built}" if built else
                                        f"{kind} run {stt}" + (f" after {s.get('attempts')} attempt(s)" if s.get('attempts') else "")),
                               priority=3 if ok else 5))
            st["slots_pushed"][sid] = stt

    # --- ACTION REQUIRED from the weekly ingest tick
    wi = fresh.get("weekly_ingest") or {}
    tick_line = str(((wi.get("last_tick") or {}).get("first_line")) or "")
    if "ACTION REQUIRED" in tick_line:
        day = now.strftime("%Y-%m-%d")
        if st["actions_pushed"].get(tick_line) != day:
            events.append(dict(key="action", title="fpl: ACTION REQUIRED (weekly ingest)",
                               message=tick_line + "\nsee INGEST_TICK.txt on the volume for the items", priority=4))
            st["actions_pushed"][tick_line] = day

    # --- daily heartbeat
    hb_h, hb_m = HEARTBEAT_UTC
    today = now.strftime("%Y-%m-%d")
    if (now.hour, now.minute) >= (hb_h, hb_m) and st["last_heartbeat_date"] != today:
        lr = health.get("last_run") or {}
        nxt = (sched.get("expected_next") or {})
        nxt_s = (nxt.get("at") or nxt.get("condition") or "?") if nxt else "?"
        events.append(dict(key="heartbeat", title=f"fpl {status} ({sha})",
                           message=f"{lr.get('freshness') or 'no run recorded'}\nnext: {nxt.get('kind', '?')} {nxt_s}",
                           priority=1 if status == "ok" else 3))
        st["last_heartbeat_date"] = today
    return events, st


# ------------------------------------------------------------------ I/O shell
def read_env(path):
    cfg = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return cfg


def fetch_health(url):
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def push(server, topic, ev, dry_run=False):
    if dry_run:
        print(f"  [dry-run] would push [{ev['priority']}] {ev['title']} :: {ev['message'].replace(chr(10), ' | ')[:300]}")
        return True
    req = urllib.request.Request(f"{server.rstrip('/')}/{topic}", data=ev["message"].encode("utf-8"), method="POST")
    req.add_header("Title", ev["title"].encode("ascii", "replace").decode())
    req.add_header("Priority", str(ev["priority"]))
    req.add_header("Tags", "warning" if ev["priority"] >= 4 else "white_check_mark")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError):
        return False


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
        base = empty_state(); base.update(st)
        return base
    except (OSError, ValueError):
        return empty_state()


def save_state(path, st):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="the consumer of /health: push what a person should know")
    ap.add_argument("--env", default="/root/fpl-alert.env")
    ap.add_argument("--url", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print, push nothing, write no state")
    a = ap.parse_args(argv)
    cfg = read_env(a.env)
    url = a.url or cfg.get("HEALTH_URL") or "http://127.0.0.1:8000/health"
    state_path = a.state or cfg.get("STATE_PATH") or "/var/lib/fpl-alert/state.json"
    server = cfg.get("NTFY_SERVER") or "https://ntfy.sh"
    topic = cfg.get("NTFY_TOPIC")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if not topic and not a.dry_run:
        print(f"[{iso(now)}] NO NTFY_TOPIC in {a.env} -- the probe cannot alert anyone; fix the env file")
        return 2
    health = fetch_health(url)
    st = load_state(state_path)
    events, new_state = plan(now, health, st)
    sent = []
    for ev in events:
        ok = push(server, topic or "(dry-run)", ev, dry_run=a.dry_run)
        sent.append(f"{ev['key']}{'' if ok else ' (PUSH FAILED)'}")
        if not ok:
            # do not record a failed push as done: the rate limit would swallow the retry
            for k in ("degraded", "unreachable"):
                if ev["key"] in (k, "still_degraded", "changed") and k in new_state["last_push"]:
                    new_state["last_push"][k] = st["last_push"].get(k)
    status = "unreachable" if health is None else str(health.get("status"))
    print(f"[{iso(now)}] health={status} reasons={len((health or {}).get('reasons') or [])} "
          f"events={sent or 'none'}{' (dry-run)' if a.dry_run else ''}")
    if not a.dry_run:
        try:
            save_state(state_path, new_state)
        except OSError as e:
            print(f"[{iso(now)}] CANNOT WRITE STATE {state_path}: {e}")
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
