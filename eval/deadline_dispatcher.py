# deadline_dispatcher.py -- the model's scheduler: several runs a week, as a
# POLICY (eval/dispatch_policy.py), not as cron lines.
#
# MECHANISM: host cron runs this every 10 minutes (UTC box, UTC cron -- FPL
# deadlines are UTC) under /tmp/fpl-dispatch.lock, the lock the weekly ingest
# also holds while it rewrites the volume, so at most one build runs at a
# time. Each tick pulls bootstrap-static, reads the season file's max
# gameweek and the state file, asks dispatch_policy.plan() for one action,
# runs eval/run_live_deadline.py (a STRICT build, always) if there is one,
# records the outcome, and writes the NEXT EXPECTED RUN -- the promise the
# freshness string makes and /health checks.
#
# Kinds: post_ingest (the master gained a confirmed gameweek), nightly
# (11:00Z, previous gameweek confirmed and ingested), t90 / t30 / t10 on
# deadline day. Attempts per kind and the decisions behind them are in
# dispatch_policy. Since 2026-09-12 (multi-run); before that, one T-90 run per
# gameweek with a dispatch_gw{N}.done marker -- honoured as a completed t90.
#
# State: data/live/dispatch_state.json. Usage:
#   python eval/deadline_dispatcher.py --season 2026-27 [--dry-run] [--now ISO]

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "data" / "live"
sys.path.insert(0, str(REPO / "eval"))
import dispatch_policy as dp  # noqa: E402

STATE = LIVE / "dispatch_state.json"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            log("state file unreadable -- starting fresh (the old file is kept as .corrupt)")
            STATE.replace(STATE.with_suffix(".corrupt"))
    return dp.empty_state()


def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def honour_legacy_marker(state, gw):
    """dispatch_gw{N}.done (the single-run era) = a completed t90 for N."""
    done = LIVE / f"dispatch_gw{gw}.done"
    sid = f"t90:GW{gw}"
    if done.exists() and sid not in state.get("slots", {}):
        try:
            info = json.loads(done.read_text(encoding="utf-8"))
        except ValueError:
            info = {}
        state.setdefault("slots", {})[sid] = dict(
            kind="t90", gw=gw, status="SUCCESS", attempts=info.get("attempts", 1),
            finished_at=info.get("built_at"), note="legacy dispatch_gw.done marker")
        log(f"honoured legacy marker {done.name} as {sid} SUCCESS")


def master_max_gw(season):
    p = REPO / "data" / "history" / f"fpl_api_{season.replace('-', '_')}.parquet"
    try:
        import pandas as pd
        return int(pd.read_parquet(p, columns=["GW"])["GW"].max())
    except Exception as e:  # unreadable -> policy refuses to fire the gated kinds
        log(f"season file unreadable ({type(e).__name__}: {e}) -- gated kinds will not fire")
        return None


def run_build(season, gw, kind, slot, attempt):
    """Run the strict build; returns (exit_code, sidecar dict or None)."""
    r = subprocess.run([sys.executable, str(REPO / "eval" / "run_live_deadline.py"),
                        "--season", season, "--gw", str(gw), "--kind", kind, "--slot", slot,
                        "--attempt", str(attempt)], cwd=str(REPO), timeout=3600)
    side = None
    if r.returncode == 0:
        import config_roles as cr
        p = LIVE / f"_tmp_frame_{cr.PRODUCTION_CONFIG}.provenance.json"
        try:
            side = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            side = None
    return r.returncode, side


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--dry-run", action="store_true", help="print the decision; run nothing, save nothing")
    ap.add_argument("--now", default=None, help="(tests/proofs) pretend the clock says this ISO time")
    a = ap.parse_args()

    now = dp.parse_iso(a.now) if a.now else datetime.now(timezone.utc)
    events = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/",
                          timeout=30).json()["events"]
    LIVE.mkdir(parents=True, exist_ok=True)
    state = load_state()
    nxt = dp.next_deadline(events, now)
    if nxt:
        honour_legacy_marker(state, nxt[0])
    master_gw = master_max_gw(a.season)
    p = dp.plan(now, events, state, master_gw)
    state["last_tick"] = dp.iso(now)
    state["expected_next"] = p["expected_next"]

    d = p["deadline"]
    log(f"deadline GW{d['gw']} at {d['at']} (T-{d['lead_min']:.0f} min); season file through "
        f"GW{master_gw}; decision: {p['action'] or 'none'} -- {p['reason']}")
    log(f"expected next: {json.dumps(p['expected_next'])}")
    if a.dry_run:
        log("dry run -- nothing executed, state not saved")
        return
    if not p["action"]:
        save_state(state)
        return

    kind, sid, attempt = p["action"], p["slot"], p["attempt"]
    s = dict(state.get("slots", {}).get(sid) or {})
    s.update(kind=kind, gw=p["gw"], status="RUNNING", attempts=attempt, started_at=dp.iso(now))
    state.setdefault("slots", {})[sid] = s
    save_state(state)
    log(f"{sid}: firing the strict build (attempt {attempt}/{dp.ATTEMPTS[kind]})")
    code, side = run_build(a.season, p["gw"], kind, sid, attempt)
    finished = dp.iso(datetime.now(timezone.utc))
    ok = code == 0
    status = dp.record_outcome(
        state, p, ok, run_id=(side or {}).get("run_id"),
        history_through_gw=((side or {}).get("knowledge") or {}).get("history_through_gw"),
        exit_code=code, started_at=dp.iso(now), finished_at=finished)
    state["expected_next"] = dp.expected_next(datetime.now(timezone.utc), events, state, master_gw)
    save_state(state)
    if ok:
        log(f"{sid}: build SUCCEEDED (run_id {(side or {}).get('run_id')}); expected next: "
            f"{json.dumps(state['expected_next'])}")
    else:
        log(f"{sid}: build FAILED (exit {code}) -> {status}; consecutive nightly/post-ingest "
            f"give-ups {state.get('consecutive_nightly_failures')}; expected next: "
            f"{json.dumps(state['expected_next'])}")
        sys.exit(1)


if __name__ == "__main__":
    main()
