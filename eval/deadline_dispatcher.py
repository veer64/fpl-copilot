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
sys.path.insert(0, str(REPO))          # config_roles, db_write live at the repo root
import dispatch_policy as dp  # noqa: E402
# Imported HERE, not inside run_build: on 2026-09-15 the first four live multi-run
# builds all SUCCEEDED and the dispatcher then crashed on `import config_roles`
# (the root was not on sys.path), before it could record the outcome -- each slot
# stayed RUNNING, re-fired on the next tick, and /health said ok throughout.
# An import that can fail must fail at the first tick, not after a build.
import config_roles as cr  # noqa: E402

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
        p = LIVE / f"_tmp_frame_{cr.PRODUCTION_CONFIG}.provenance.json"
        try:
            side = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            side = None
    return r.returncode, side


def reconcile_from_db(state, rows=None):
    """A slot left RUNNING by a tick that died after its build (the 2026-09-15 crash) is
    settled from the database, the one record the runner always writes: a SUCCESS
    model_runs row for that slot marks the slot SUCCESS (and last_success), a FAILED row
    marks it FAILED. `rows` may be passed by tests; otherwise model_runs is read through
    db_write.connect(); an unreachable database logs and leaves the state alone."""
    running = [sid for sid, s in (state.get("slots") or {}).items() if s.get("status") == "RUNNING"]
    if not running:
        return []
    if rows is None:
        try:
            import db_write
            conn = db_write.connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT run_id, slot, status, finished_at, knowledge FROM model_runs "
                                "WHERE slot = ANY(%s) ORDER BY run_id", (running,))
                    rows = [dict(run_id=r[0], slot=r[1], status=r[2], finished_at=r[3], knowledge=r[4])
                            for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 -- reconciliation is best effort; the tick goes on
            log(f"reconcile: database unreadable ({type(e).__name__}: {e}) -- RUNNING slots left as they are")
            return []
    settled = []
    for sid in running:
        mine = [r for r in rows if r.get("slot") == sid]
        ok = [r for r in mine if r.get("status") == "SUCCESS"]
        if ok:
            r = ok[-1]
            k = r.get("knowledge")
            if isinstance(k, str):
                try:
                    k = json.loads(k)
                except ValueError:
                    k = None
            s = state["slots"][sid]
            s.update(status="SUCCESS", run_id=r["run_id"], finished_at=dp.iso(dp.parse_iso(r["finished_at"])) if r.get("finished_at") else None,
                     history_through_gw=(k or {}).get("history_through_gw"), note="settled from model_runs after a tick died post-build")
            state["last_success"] = {"slot": sid, "run_id": r["run_id"], "finished_at": s["finished_at"],
                                     "history_through_gw": s["history_through_gw"]}
            settled.append(f"{sid} -> SUCCESS (run {r['run_id']})")
        elif mine:
            state["slots"][sid]["status"] = "FAILED"
            settled.append(f"{sid} -> FAILED (model_runs)")
    for line in settled:
        log(f"reconcile: {line}")
    return settled


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--dry-run", action="store_true", help="print the decision; run nothing, save nothing")
    ap.add_argument("--now", default=None, help="(tests/proofs) pretend the clock says this ISO time")
    a = ap.parse_args(argv)

    now = dp.parse_iso(a.now) if a.now else datetime.now(timezone.utc)
    events = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/",
                          timeout=30).json()["events"]
    LIVE.mkdir(parents=True, exist_ok=True)
    state = load_state()
    if not a.dry_run:
        reconcile_from_db(state)
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


def _hard_exit(code):
    """Exit WITHOUT interpreter finalisation. 2026-09-13 03:20Z the tick saved its
    state, logged its decision and then hung for 13 hours at interpreter shutdown
    (every thread in futex wait, no sockets, nothing left to write -- the
    pyarrow/jemalloc worker threads that the parquet read starts are the suspect).
    Its container stayed up, the host-side `flock -n` on /tmp/fpl-dispatch.lock
    stayed held, and BOTH the dispatcher and the weekly ingest (which takes the
    same lock) were silently skipped until it was killed by hand. Every artefact
    this process writes is written atomically before main returns, so skipping
    finalisation loses nothing; a tick must never outlive its work."""
    import os
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    try:
        main()
        _code = 0
    except SystemExit as e:                      # sys.exit(1) on a failed build; argparse's 2
        _code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    _hard_exit(_code)
