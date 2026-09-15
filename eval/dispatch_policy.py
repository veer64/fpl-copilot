"""
dispatch_policy.py -- WHEN the model runs, as a pure policy (design:
Logs/multi_run_schedule_design.md, approved 2026-09-12; decisions 1-7 of the
multi-run brief). No I/O here: the dispatcher feeds it the clock, the
bootstrap events, its state file and the master's max gameweek, and gets back
one action (or none) plus the NEXT EXPECTED RUN -- the promise the freshness
string makes to the user, which /health checks against what actually landed.

Kinds, in precedence order at a tick (one run per tick at most):

  t10          lead in [T10_MIN_LEAD_MIN, 10] min   attempts 1  (a RECORDED
               decision, not a default: a T-10 blip falls back to T-30's
               answer, and a retry ten minutes later would land at T-0)
  t30          lead in (10, 30] min                attempts 2  (the decision run)
  t90          lead in (30, 90] min                attempts 3  (the safety net:
               a moved fixture trips the strict calendar re-pull, and T-90
               leaves room for three retries and a hand --force-gw ingest)
  post_ingest  the master gained a newly confirmed gameweek since the last
               successful run (the week's biggest information change)  attempts 2
  nightly      first tick at/after NIGHTLY_HOUR_UTC each day, if the previous
               gameweek is confirmed and ingested, no nightly today, and no
               post_ingest success in the last POST_INGEST_QUIET_H  attempts 2

Deadline-day windows are DISJOINT so each fires once; a window the dispatcher
never saw (it was down) is simply not attempted, and the broken-promise check
reports it. Nightly and post_ingest are gated on the PREVIOUS gameweek being
confirmed and ingested (master_gw >= next_gw - 1), never on a clock alone: a
fixed Monday run would build on data through GW3.

TWO GATES WITH TWO PURPOSES -- do not re-unify them (user decision 2026-09-15):
  * nightly / post_ingest are gated on the previous gameweek being confirmed
    and ingested because their purpose is to avoid a POINTLESS run (a build on
    history the last run already had);
  * the three deadline slots t90 / t30 / t10 are UNCONDITIONAL -- they fire
    whatever the bootstrap says about the previous gameweek and even if the
    season file is unreadable -- because their purpose is to avoid a MISSING
    run: the one thing the user acts on. FPL's confirmation of a gameweek is
    the one input we do not control; if it stalls, a build on history through
    GW3 is worse than one through GW4 and far better than none, and the
    freshness line says exactly which gameweek the history reached. The
    promise (expected_next) carries the deadline run as a CERTAIN fallback
    (`certain_at`) even while a conditional post_ingest is still possible, so
    /health degrades if the safety net does not land.

Every run is a STRICT build (the runner), exactly like the deadline build; a
strict raise for a real reason is still the right outcome.
"""

from datetime import datetime, timedelta, timezone

ATTEMPTS = {"t10": 1, "t30": 2, "t90": 3, "post_ingest": 2, "nightly": 2}
DEADLINE_WINDOWS = (("t10", 0, 10), ("t30", 10, 30), ("t90", 30, 90))   # (kind, lo_excl, hi_incl) minutes
T10_MIN_LEAD_MIN = 4          # build + solve ~45 s; a run landing at T-1 is useless
NIGHTLY_HOUR_UTC = 11         # 07:00 Eastern; clear of the 06:17 and 12:17 ingest ticks
POST_INGEST_QUIET_H = 6       # a nightly within 6 h of a post_ingest success is redundant
# how long after the promised time /health waits before calling the promise broken:
# attempts x 10-minute ticks + a build + slack
GRACE_MIN = {"t10": 15, "t30": 25, "t90": 35, "post_ingest": 25, "nightly": 25}
DISPATCHER_STALE_MIN = 35     # a 10-minute cron that has not ticked for this long is dead
TERMINAL = ("SUCCESS", "GAVE_UP")


def parse_iso(s):
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_deadline(events, now):
    """(gw, deadline) of the first event whose deadline is still ahead."""
    for e in events:
        dl = parse_iso(e["deadline_time"])
        if dl > now:
            return int(e["id"]), dl
    return None


def empty_state():
    return {"version": 1, "last_tick": None, "slots": {}, "consecutive_nightly_failures": 0,
            "last_success": None, "expected_next": None}


def _slot(state, sid):
    return state.get("slots", {}).get(sid) or {}


def _done(state, sid):
    return _slot(state, sid).get("status") in TERMINAL


def _attempts(state, sid):
    return int(_slot(state, sid).get("attempts") or 0)


def deadline_window(lead_min):
    for kind, lo, hi in DEADLINE_WINDOWS:
        if lo < lead_min <= hi:
            return kind
    return None


def plan(now, events, state, master_gw):
    """One tick's decision. Returns
        {action: kind|None, slot, gw, attempt, reason, deadline: {gw, at, lead_min}|None,
         expected_next: {...}}
    master_gw: the max gameweek in the ingested season file (None if unreadable)."""
    nxt = next_deadline(events, now)
    out = {"action": None, "slot": None, "gw": None, "attempt": None, "reason": None,
           "deadline": None, "expected_next": None}
    if nxt is None:
        out["reason"] = "no future deadline in bootstrap -- season over"
        return out
    gw, dl = nxt
    lead = (dl - now).total_seconds() / 60
    out["deadline"] = {"gw": gw, "at": iso(dl), "lead_min": round(lead, 1)}
    out["gw"] = gw
    slots = state.get("slots", {})

    # ---- deadline day: disjoint windows, most urgent first. UNCONDITIONAL: this
    # branch comes before, and never consults, the previous-gameweek gate below --
    # the safety net exists to avoid a MISSING run, not a pointless one (see the
    # module docstring). master_gw is only used here to say what the build will know.
    if lead <= 90:
        kind = deadline_window(lead)
        gap = history_gap(gw, master_gw)
        if kind is None or (kind == "t10" and lead < T10_MIN_LEAD_MIN):
            out["reason"] = (f"GW{gw}: T-{lead:.0f} -- inside the deadline but below the "
                             f"{T10_MIN_LEAD_MIN}-minute minimum lead; nothing fires")
        else:
            sid = f"{kind}:GW{gw}"
            if _done(state, sid):
                out["reason"] = f"GW{gw}: {sid} already {_slot(state, sid)['status']}"
            elif _attempts(state, sid) >= ATTEMPTS[kind]:
                out["reason"] = f"GW{gw}: {sid} used its {ATTEMPTS[kind]} attempt(s)"
            else:
                out.update(action=kind, slot=sid, attempt=_attempts(state, sid) + 1,
                           reason=f"GW{gw}: T-{lead:.0f} -- {kind} window" + (f" ({gap})" if gap else ""))
        out["expected_next"] = expected_next(now, events, state, master_gw)
        return out

    # ---- between deadlines: nightly / post_ingest need the previous gameweek
    # confirmed AND ingested (a pointless run otherwise). The deadline slots above
    # do NOT wait for this. ----
    prev_gw = gw - 1
    if master_gw is None:
        out["reason"] = "season file unreadable -- cannot tell which gameweeks are ingested; nothing fires"
        out["expected_next"] = expected_next(now, events, state, master_gw)
        return out
    if master_gw < prev_gw:
        out["reason"] = (f"GW{gw} deadline in {lead / 60:.1f} h; GW{prev_gw} not yet confirmed and "
                         f"ingested (season file through GW{master_gw}) -- no nightly or post-ingest run "
                         f"until it is; the deadline-day runs fire regardless from T-90")
        out["expected_next"] = expected_next(now, events, state, master_gw)
        return out

    last = state.get("last_success") or {}
    known = int(last.get("history_through_gw") or 0)
    sid_pi = f"post_ingest:GW{master_gw}"
    if master_gw > known and not _done(state, sid_pi) and _attempts(state, sid_pi) < ATTEMPTS["post_ingest"]:
        out.update(action="post_ingest", slot=sid_pi, attempt=_attempts(state, sid_pi) + 1,
                   reason=f"season file now through GW{master_gw}; last successful run knew "
                          f"through GW{known} -- post-ingest run")
        out["expected_next"] = expected_next(now, events, state, master_gw)
        return out

    sid_n = f"nightly:{now:%Y-%m-%d}"
    if now.hour >= NIGHTLY_HOUR_UTC and not _done(state, sid_n) and _attempts(state, sid_n) < ATTEMPTS["nightly"]:
        recent_pi = [s for s in slots.values()
                     if s.get("kind") == "post_ingest" and s.get("status") == "SUCCESS" and s.get("finished_at")
                     and (now - parse_iso(s["finished_at"])) < timedelta(hours=POST_INGEST_QUIET_H)]
        if recent_pi:
            out["reason"] = (f"nightly {now:%Y-%m-%d} skipped: a post_ingest run succeeded within "
                             f"{POST_INGEST_QUIET_H} h")
        else:
            out.update(action="nightly", slot=sid_n, attempt=_attempts(state, sid_n) + 1,
                       reason=f"nightly slot {now:%Y-%m-%d} ({NIGHTLY_HOUR_UTC:02d}:00Z), "
                              f"season file through GW{master_gw}")
        out["expected_next"] = expected_next(now, events, state, master_gw)
        return out

    if _done(state, sid_n) or _attempts(state, sid_n) >= ATTEMPTS["nightly"]:
        out["reason"] = f"nightly {now:%Y-%m-%d} already {_slot(state, sid_n).get('status')}"
    else:
        out["reason"] = f"before {NIGHTLY_HOUR_UTC:02d}:00Z; nightly {now:%Y-%m-%d} not yet due"
    out["expected_next"] = expected_next(now, events, state, master_gw)
    return out


def expected_next(now, events, state, master_gw):
    """The next run the schedule PROMISES: {kind, slot, gw, at (iso or None),
    condition, grace_min}. Timed promises are checked by /health
    (broken_promise); a conditional one (post_ingest) names its condition."""
    nxt = next_deadline(events, now)
    if nxt is None:
        return None
    gw, dl = nxt
    lead = (dl - now).total_seconds() / 60

    def timed(kind, sid, at, condition=None):
        return {"kind": kind, "slot": sid, "gw": gw, "at": iso(at), "condition": condition,
                "grace_min": GRACE_MIN[kind]}

    # deadline-day windows still ahead or open
    if lead <= 90:
        for kind, lo, hi in (("t90", 30, 90), ("t30", 10, 30), ("t10", 0, 10)):
            sid = f"{kind}:GW{gw}"
            if _done(state, sid) or _attempts(state, sid) >= ATTEMPTS[kind]:
                continue
            at = dl - timedelta(minutes=hi)
            if now <= at or lo < lead <= hi:
                return timed(kind, sid, max(at, now) if lo < lead <= hi else at)
        return {"kind": "post_ingest", "slot": f"post_ingest:GW{gw}", "gw": gw + 1, "at": None,
                "condition": f"GW{gw} confirmed by FPL and ingested (ticks 00:17/06:17/12:17/18:17Z)",
                "grace_min": None}

    prev_gw = gw - 1
    t90_at = dl - timedelta(minutes=90)
    if master_gw is None or master_gw < prev_gw:
        # conditional on FPL, which we do not control -- but the deadline run is
        # CERTAIN: promise it too, so /health can see it missed (the stalled-FPL case)
        return {"kind": "post_ingest", "slot": f"post_ingest:GW{prev_gw}", "gw": gw, "at": None,
                "condition": f"GW{prev_gw} confirmed by FPL and ingested (ticks 00:17/06:17/12:17/18:17Z), "
                             f"then nightly at {NIGHTLY_HOUR_UTC:02d}:00Z",
                "grace_min": None,
                "certain_kind": "t90", "certain_slot": f"t90:GW{gw}", "certain_at": iso(t90_at),
                "certain_grace_min": GRACE_MIN["t90"]}
    # the next nightly slot that is not done and lands before T-90
    day = now.replace(hour=NIGHTLY_HOUR_UTC, minute=0, second=0, microsecond=0)
    for k in range(0, 8):
        at = day + timedelta(days=k)
        sid = f"nightly:{at:%Y-%m-%d}"
        if at < now and k == 0:
            if not (_done(state, sid) or _attempts(state, sid) >= ATTEMPTS["nightly"]):
                return timed("nightly", sid, now)          # due now, this tick
            continue
        if at >= t90_at:
            break
        if _done(state, sid) or _attempts(state, sid) >= ATTEMPTS["nightly"]:
            continue
        return timed("nightly", sid, at)
    return timed("t90", f"t90:GW{gw}", t90_at)


def record_outcome(state, p, ok, run_id=None, history_through_gw=None, exit_code=None,
                   started_at=None, finished_at=None):
    """Update the state after a run; returns the new slot status."""
    kind, sid = p["action"], p["slot"]
    s = dict(_slot(state, sid))
    s.update(kind=kind, gw=p["gw"], attempts=p["attempt"], started_at=started_at, finished_at=finished_at,
             last_exit=exit_code)
    if ok:
        s["status"] = "SUCCESS"
        s["run_id"] = run_id
        s["history_through_gw"] = history_through_gw
        state["last_success"] = {"slot": sid, "kind": kind, "run_id": run_id, "finished_at": finished_at,
                                 "history_through_gw": history_through_gw}
        if kind in ("nightly", "post_ingest"):
            state["consecutive_nightly_failures"] = 0
    else:
        gave_up = p["attempt"] >= ATTEMPTS[kind]
        s["status"] = "GAVE_UP" if gave_up else "FAILED"
        if gave_up and kind in ("nightly", "post_ingest"):
            state["consecutive_nightly_failures"] = int(state.get("consecutive_nightly_failures") or 0) + 1
    state.setdefault("slots", {})[sid] = s
    return s["status"]


# --------------------------------------------------------------- /health
def health_reasons(now, state, next_gw=None):
    """Decision 5 + the promise check. Reasons that degrade /health:
    - a promised timed run did not land within its grace (or the dispatcher
      stopped ticking, which leaves the promise standing);
    - two consecutive nightly/post_ingest slots gave up;
    - any deadline-day slot for the next (or current) gameweek gave up."""
    reasons = []
    if not state:
        return reasons
    lt = state.get("last_tick")
    if lt and (now - parse_iso(lt)) > timedelta(minutes=DISPATCHER_STALE_MIN):
        reasons.append(f"dispatcher has not ticked since {lt} (every 10 min expected)")
    exp = state.get("expected_next") or {}
    if exp.get("at"):
        at = parse_iso(exp["at"])
        if now > at + timedelta(minutes=exp.get("grace_min") or 25):
            st = _slot(state, exp["slot"]).get("status") or "never attempted"
            if st != "SUCCESS":
                reasons.append(f"promised run {exp['slot']} at {exp['at']} did not land ({st})")
    elif exp.get("certain_at"):
        # a conditional promise (post_ingest waiting on FPL) with a certain fallback:
        # the deadline run must land whatever FPL does
        at = parse_iso(exp["certain_at"])
        if now > at + timedelta(minutes=exp.get("certain_grace_min") or 35):
            st = _slot(state, exp["certain_slot"]).get("status") or "never attempted"
            if st != "SUCCESS":
                reasons.append(f"promised run {exp['certain_slot']} at {exp['certain_at']} did not land ({st}) "
                               f"-- the deadline safety net, due regardless of {exp.get('condition', 'FPL')}")
    n = int(state.get("consecutive_nightly_failures") or 0)
    if n >= 2:
        reasons.append(f"{n} consecutive nightly/post-ingest slots gave up -- no model since "
                       f"{(state.get('last_success') or {}).get('finished_at')}")
    for sid, s in (state.get("slots") or {}).items():
        if s.get("kind") in ("t90", "t30", "t10") and s.get("status") == "GAVE_UP" \
                and (next_gw is None or int(s.get("gw") or 0) >= int(next_gw)):
            reasons.append(f"deadline-day run {sid} FAILED after {s.get('attempts')} attempt(s)")
    return reasons


# ------------------------------------------------------------- freshness
def _fmt(ts):
    if not ts:
        return "?"
    try:
        return parse_iso(ts).strftime("%a %d %b %H:%M") + "Z"
    except (TypeError, ValueError):
        return str(ts)


def freshness(run, expected=None):
    """The one sentence every answer carries: when it was built, what it knew,
    what it predicts, and when the next run is promised. `run` is a
    model_runs row (dict) whose `knowledge` may be None for pre-multi-run
    rows; `expected` is the state's expected_next."""
    k = run.get("knowledge") or {}
    kind = run.get("kind") or "deadline"
    built = _fmt(run.get("finished_at"))
    dur = k.get("duration_s")
    head = f"built {built} ({kind}, run {run.get('run_id')}" + (f", {dur:.0f} s" if dur else "") + ")"
    if not k:
        knows = "knowledge not recorded (a pre-multi-run row)"
    else:
        knows = (f"knows results through GW{k.get('history_through_gw')} "
                 f"(ingested {_fmt(k.get('history_ingested_at'))}), team news to "
                 f"{_fmt(k.get('availability_asof'))}, odds pulled {_fmt(k.get('odds_pulled_at'))}")
        gap = history_gap(run.get("gw"), k.get("history_through_gw"))
        if gap:
            knows += f" -- {gap}"
    pred = f"predicting GW{run.get('gw')}"
    if k.get("deadline_at"):
        pred += f" (deadline {_fmt(k['deadline_at'])})"
    if expected:
        if expected.get("at"):
            nxt = f"next run {_fmt(expected['at'])} ({expected['kind']})"
        else:
            nxt = f"next run when {expected.get('condition')} ({expected['kind']})"
            if expected.get("certain_at"):
                nxt += f"; in any case {_fmt(expected['certain_at'])} ({expected.get('certain_kind')}), whatever FPL confirms"
    else:
        nxt = "next run not scheduled"
    return " -- ".join([head, knows, pred, nxt])


def history_gap(gw, history_through_gw):
    """The plain sentence for a build whose history stops short of the previous
    gameweek -- or None when it does not. Used in the dispatcher's reason and in
    the freshness line, so a build on unconfirmed history says so wherever it is quoted."""
    try:
        gw = int(gw)
    except (TypeError, ValueError):
        return None
    if history_through_gw is None:
        return f"season file unreadable at build time -- which gameweek the history reaches is not known"
    try:
        h = int(history_through_gw)
    except (TypeError, ValueError):
        return None
    if h < gw - 1:
        missing = f"GW{h + 1}" if h + 1 == gw - 1 else f"GW{h + 1}-GW{gw - 1}"
        return f"{missing} not yet confirmed and ingested when this was built: history stops at GW{h}"
    return None
