"""now_context.py -- the "now" block the agent reads before its system prompt, rebuilt every turn.

WHY. The prompt tells the model that "this week" means the next deadline's gameweek, but until
2026-10-08 nothing told the model what today was, which gameweek had finished, when the next
deadline fell or which clubs are in the league this season. "Is Foden available next week?" was
answered with "that depends which gameweek we are in", and a club the model's training data never
saw in the Premier League (Coventry City, promoted for 2026-27) was sometimes called "not a Premier
League club". The block states those facts, from LOCAL data only, at the top of every turn.

WHERE EACH LINE COMES FROM -- nothing here is typed in:
  * the clock            datetime.now(UTC), or the `now` the caller passes (tests freeze it). Since 2026-10-24 the
                         "- Now:" line itself is now_line(), sent as the first text block of the turn's user message
                         (agent.py) rather than inside this block, so the system prompt caches across minutes; the
                         gameweek, schedule and run lines below are still computed from the same `now`.
  * deadlines            the newest bootstrap snapshot on the volume, through
                         model_tools._gw_deadline_times (one reader, cached an hour)
  * finished gameweeks   the season master data/history/fpl_api_<season>.parquet, through
                         model_tools._actuals_master -> actuals_tool.gws_held: a gameweek is in the
                         file only once FPL says finished AND data_checked (eval/fetch_fpl_history.py)
  * the run schedule     eval/dispatch_policy.py's constants (NIGHTLY_HOUR_UTC, DEADLINE_WINDOWS)
                         -- the policy the dispatcher runs, never a copy of its numbers
  * the next run         the dispatcher's own promise in data/live/dispatch_state.json
                         (expected_next) when the volume holds one; otherwise the same policy
                         function the dispatcher calls, dispatch_policy.expected_next, on an empty
                         state and the local data
  * the 20 clubs         the newest bootstrap snapshot's teams block (fixtures_tool._team_names)

A piece that cannot be built is LEFT OUT and the reason is returned (and printed by the agent),
never invented: a block with no deadline line is better than one with a guessed date. The whole
block is capped at MAX_CHARS; the clubs line is the first to be shortened and the only one that
can be, and the cap is asserted by a test.
"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
MAX_CHARS = 1200
TITLE = "CONTEXT BLOCK (rebuilt every turn from local data; today, the gameweek state, the update schedule, the clubs)"
# the dispatcher's kind labels in words (Part C, 2026-10-12): the labels stay in the data, the sentence is plain
KIND_WORDS = {"nightly": "the nightly update", "post_ingest": "the update after FPL confirms the gameweek",
              "t90": "the update 90 minutes before the deadline", "t30": "the update 30 minutes before the deadline",
              "t10": "the update 10 minutes before the deadline", "deadline": "the deadline update"}


def _fmt(dt):
    """'Saturday 2026-10-10 10:00 UTC' -- the weekday is what 'next week' questions turn on."""
    return dt.astimezone(UTC).strftime("%A %Y-%m-%d %H:%M UTC")


def _parse(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


# ---------------------------------------------------------------- the loaders (local data only)
def _load_deadlines():
    import model_tools as mt
    raw = mt._gw_deadline_times() or {}
    return {int(g): _parse(t) for g, t in raw.items()}


def _load_finished():
    import actuals_tool
    import model_tools as mt
    master, _ = mt._actuals_master()
    return list(actuals_tool.gws_held(master))


def _load_clubs():
    import fixtures_tool as ft
    return sorted(ft._team_names().values())


def _load_dispatch_state():
    import model_tools as mt
    return mt._dispatch_state() or {}


def _policy():
    import model_tools as mt
    return mt._dp()


# ---------------------------------------------------------------- the pieces (pure)
def gameweek_state(now, deadlines, finished):
    """(last finished gw, gw in progress or None, (next gw, next deadline) or None), from the deadline
    table and the list of finished gameweeks. A gameweek is IN PROGRESS when its deadline has passed
    and the master does not hold it yet."""
    last = max(finished) if finished else None
    nxt = None
    for g in sorted(deadlines):
        if deadlines[g] > now:
            nxt = (g, deadlines[g])
            break
    in_progress = None
    for g in sorted(deadlines):
        if deadlines[g] <= now and g not in set(finished or []) and (last is None or g > last):
            in_progress = g
            break
    return last, in_progress, nxt


def schedule_words(dp):
    """The schedule in plain words, from the policy's own constants."""
    leads = sorted((hi for _, _, hi in dp.DEADLINE_WINDOWS), reverse=True)
    lead_words = ", ".join(str(x) for x in leads[:-1]) + f" and {leads[-1]}" if len(leads) > 1 else str(leads[0])
    return (f"The model rebuilds nightly at {dp.NIGHTLY_HOUR_UTC:02d}:00 UTC once the previous gameweek is "
            f"confirmed, and on deadline day at {lead_words} minutes before the deadline.")


def next_run_words(expected, now=None):
    """'nightly, Friday 2026-10-09 11:00 UTC' or 'once GW6 is confirmed by FPL and ingested' from an
    expected_next promise (dispatch_policy.expected_next's shape). A promise whose time is not after
    `now` is one the policy says is due at this very tick, and is said so rather than as a time."""
    if not expected:
        return None
    kind = KIND_WORDS.get(expected.get("kind"), expected.get("kind"))
    if expected.get("at"):
        at = _parse(expected["at"])
        if now is not None and at <= now:
            return f"{kind}, due now ({_fmt(at)})"
        return f"{kind}, {_fmt(at)}"
    cond = expected.get("condition")
    if not cond:
        return None
    try:
        from dispatch_policy import plain_condition                    # a stored promise may carry pre-2026-10-12 wording
        cond = plain_condition(cond)
    except ImportError:
        pass
    words = f"once {cond}"
    if expected.get("certain_at"):
        words += f"; in any case {_fmt(_parse(expected['certain_at']))} ({KIND_WORDS.get(expected.get('certain_kind'), expected.get('certain_kind'))})"
    return words


def _events_for_policy(deadlines):
    return [{"id": g, "deadline_time": deadlines[g].strftime("%Y-%m-%dT%H:%M:%SZ")} for g in sorted(deadlines)]


def clock():
    """The clock every caller shares; tests monkeypatch it to freeze time (the eval runner's --now does the same)."""
    return datetime.now(UTC)


def now_line(now=None):
    """The clock line, "- Now: Saturday 2026-10-10 10:00 UTC." Until 2026-10-24 it was the block's second line, so the
    system prompt (one cached text block of ~50k characters) changed every minute and was written to the cache fresh
    on most turns. It is no longer part of build()'s text: agent.run_agent sends it, unchanged, as the first text block
    of the turn's user message (agent._messages_for_request), never into the stored history, and every other line of
    the block -- which the same `now` still drives -- stays in the system prompt and caches."""
    return f"- Now: {_fmt(now or clock())}."


def _promise(now, deadlines, finished, state, dp):
    """(expected_next, source): the dispatcher's own promise when the state file holds one (the server),
    else the same policy function the dispatcher calls, on the state it has (or an empty one) and the
    local data (the laptop). (None, None) when there are no deadlines to derive from."""
    expected = (state or {}).get("expected_next")
    if expected:
        return expected, "the dispatcher's promise"
    if deadlines:
        master_gw = max(finished) if finished else None
        return dp.expected_next(now, _events_for_policy(deadlines), state or dp.empty_state(), master_gw), "by the schedule"
    return None, None


def deadline_day_runs(now, deadlines, dp):
    """The deadline-day run times for the NEXT deadline, computed here from the deadline and the policy's
    windows (the deadline minus 90, 30 and 10 minutes): exact UTC times, so the model never computes them.
    None when no deadline remains."""
    nxt = next((g for g in sorted(deadlines) if deadlines[g] > now), None)
    if nxt is None:
        return None
    dl = deadlines[nxt]
    out = {"gw": nxt, "deadline": dl.strftime("%Y-%m-%dT%H:%M:%SZ")}
    clock_words = []
    for kind, _lo, hi in sorted(dp.DEADLINE_WINDOWS, key=lambda w: -w[2]):
        at = dl - timedelta(minutes=hi)
        out[kind] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
        clock_words.append(at.strftime("%H:%M"))
    out["words"] = f"Deadline-day runs for GW{nxt}: " + ", ".join(clock_words[:-1]) + f" and {clock_words[-1]} UTC."
    return out


def next_run(now=None, *, deadlines=None, finished=None, dispatch_state=None, policy=None):
    """ONE source for "when is the next run" (3b, 2026-10-09): the context block and every tool's run
    metadata read this, so they can never disagree. {expected, source, words, deadline_day_runs}; a piece
    that cannot be loaded is None, never guessed. Keywords are seeds for tests."""
    now = now or clock()
    dp = policy or _policy()
    try:
        deadlines = _load_deadlines() if deadlines is None else dict(deadlines)
    except Exception:                                 # noqa: BLE001
        deadlines = {}
    try:
        finished = _load_finished() if finished is None else list(finished)
    except Exception:                                 # noqa: BLE001
        finished = []
    try:
        state = _load_dispatch_state() if dispatch_state is None else (dispatch_state or {})
    except Exception:                                 # noqa: BLE001
        state = {}
    expected, source = _promise(now, deadlines, finished, state, dp)
    return {"expected": expected, "source": source, "words": next_run_words(expected, now),
            "deadline_day_runs": deadline_day_runs(now, deadlines, dp) if deadlines else None}


def build(now=None, *, deadlines=None, finished=None, clubs=None, dispatch_state=None, policy=None):
    """The block and a report of what was left out: (text, omitted) where omitted is {piece: reason}.

    Every keyword is a seed for tests; None means 'load it from the local data'. A loader that
    raises or returns nothing drops its line and records why. The text is always <= MAX_CHARS."""
    now = now or clock()
    omitted = {}
    lines = [TITLE]                                   # the clock line is now_line(), sent on the user message (2026-10-24)

    # deadlines + finished gameweeks -> the gameweek line
    try:
        deadlines = _load_deadlines() if deadlines is None else dict(deadlines)
        if not deadlines:
            raise ValueError("no deadlines in the newest bootstrap snapshot")
    except Exception as e:                            # noqa: BLE001 -- the line is dropped, never guessed
        omitted["deadlines"] = f"{type(e).__name__}: {e}"
        deadlines = {}
    try:
        finished = _load_finished() if finished is None else list(finished)
    except Exception as e:                            # noqa: BLE001
        omitted["finished_gameweeks"] = f"{type(e).__name__}: {e}"
        finished = None
    parts = []
    if finished is not None:
        last, in_progress, nxt = gameweek_state(now, deadlines, finished)
        parts.append(f"GW{last} is the last finished gameweek" if last else "no gameweek has finished yet")
        if deadlines:
            parts.append(f"GW{in_progress} is in progress (deadline passed, not yet final)" if in_progress
                         else "no gameweek is in progress")
    elif deadlines:
        _, _, nxt = gameweek_state(now, deadlines, [])
    else:
        nxt = None
    if deadlines:
        parts.append(f"next deadline GW{nxt[0]}, {_fmt(nxt[1])}" if nxt else "no deadline remains this season")
    if parts:
        lines.append("- Gameweeks: " + "; ".join(parts) + ".")

    # the run schedule, and the next expected run
    try:
        dp = policy or _policy()
        sched = schedule_words(dp)
        state = {}
        try:
            state = _load_dispatch_state() if dispatch_state is None else (dispatch_state or {})
        except Exception as e:                        # noqa: BLE001
            omitted["dispatch_state"] = f"{type(e).__name__}: {e}"
        # the ONE source the tools' run metadata reads too (next_run / _promise), so they agree
        expected, source = _promise(now, deadlines, finished or [], state, dp)
        nr = next_run_words(expected, now)
        ddr = deadline_day_runs(now, deadlines, dp) if deadlines else None
        lines.append("- Model updates: " + sched + (f" Next expected update ({source}): {nr}." if nr else "")
                     + (f" {ddr['words']}" if ddr else ""))
        if not nr:
            omitted["next_run"] = "no promise in the dispatch state and none derivable from the local data"
    except Exception as e:                            # noqa: BLE001
        omitted["schedule"] = f"{type(e).__name__}: {e}"

    # the clubs
    try:
        clubs = _load_clubs() if clubs is None else sorted(clubs)
        if not clubs:
            raise ValueError("no teams in the newest bootstrap snapshot")
        club_line = f"- Premier League clubs this season ({len(clubs)}): " + ", ".join(clubs) + "."
    except Exception as e:                            # noqa: BLE001
        omitted["clubs"] = f"{type(e).__name__}: {e}"
        club_line = None

    text = "\n".join(lines)
    if club_line:
        room = MAX_CHARS - len(text) - 1
        if len(club_line) > room:
            club_line = club_line[:max(room - 1, 0)].rstrip(", ") + "."    # the only line that may be cut
            omitted["clubs_truncated"] = "the clubs line was shortened to fit MAX_CHARS"
        text = text + "\n" + club_line
    assert len(text) <= MAX_CHARS, len(text)
    return text, omitted


def context_block(now=None):
    """The agent's entry: the block text, with every omission printed to the log (never to the user)."""
    text, omitted = build(now)
    for piece, why in omitted.items():
        print(f"  [context block: {piece} left out: {why}]")
    return text
