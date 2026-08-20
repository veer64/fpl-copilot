# poll_availability.py
# D6 (free half) -- close the availability blind window with our own polling.
#
# fplcache snapshots bootstrap-static 4x/day, so news breaking in the ~6h gap
# before a deadline is invisible (Gvardiol GW1: stamped 68 min after the last
# snapshot, 3.5h before the deadline; predicted 72 minutes, played 0). This
# poller fetches https://fantasy.premierleague.com/api/bootstrap-static/ on a
# deadline-aware schedule derived from the API's own `events`:
#
#     every 30 min from deadline - 4h
#     every 10 min in the final hour
#     one poll shortly AFTER the deadline (enables the exact asof_* recovery
#     rule eval/build_availability.py uses on fplcache -- same reconstruction,
#     same comparability)
#
# DESIGN
#   raw archive   data/live/bootstrap_raw/<season>/<utc-ts>.json.gz
#                 written temp-then-rename: a failed fetch never lands, a
#                 killed run never leaves a half-written file. Raw first --
#                 every derived table can be rebuilt from these.
#   tick model    `--once` decides for itself whether a poll is DUE (cadence
#                 gating against the newest raw file) and exits quietly
#                 otherwise. Run it every 10 min from any scheduler; sleep,
#                 reboots and double-starts are all safe. `--watch` is a
#                 convenience loop around the same tick.
#   changes       data/live/availability_changes_<season>.parquet -- one row
#                 per (snapshot, element) whose status /
#                 chance_of_playing_this_round / news moved vs the previous
#                 poll. This is the signal the blind window was hiding.
#   build         `--build` derives data/live/availability_<season>_live.parquet
#                 at (gw, element) grain with the SAME columns and the SAME
#                 asof rule as data/availability_{season}.parquet, so the
#                 existing feature code works unchanged. asof_source is
#                 'live_snapshot' / 'live_late_news' -- distinct from
#                 fplcache's 'snapshot' / 'late_news', so the two archives can
#                 NEVER be silently mixed at row level.
#   schema drift  required fields asserted on every fetch, with the missing
#                 field named; an unknown status letter raises. Launch day is
#                 the first drift fire-drill (master plan) -- fail loudly.
#
# NOT integrated into the model. Build, store, verify only.
#
# Usage:
#   uv run python eval/poll_availability.py --status
#   uv run python eval/poll_availability.py --once [--force]
#   uv run python eval/poll_availability.py --watch
#   uv run python eval/poll_availability.py --build

import argparse
import gzip
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "data" / "live"
URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot availability poller)"}

WINDOW_HOURS = 4.0          # polling window opens deadline - 4h
FINAL_HOUR_CADENCE = 600    # seconds, inside the last hour
NORMAL_CADENCE = 1800       # seconds, rest of the window
POST_DEADLINE_GRACE = 30    # minutes: one poll allowed after the deadline

FIELDS = ["status", "chance_of_playing_this_round",
          "chance_of_playing_next_round", "news", "news_added"]
CHANGE_FIELDS = ["status", "chance_of_playing_this_round", "news"]
KNOWN_STATUSES = {"a", "d", "i", "s", "u", "n"}

REQUIRED_EVENT_FIELDS = {"id", "deadline_time", "finished"}
REQUIRED_ELEMENT_FIELDS = {"id"} | set(FIELDS)


def _now():
    return datetime.now(timezone.utc)


def _ts(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None


def fetch():
    req = Request(URL, headers=UA)
    with urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    assert_schema(data)
    return data


def assert_schema(data):
    """KNOWN drift risk: FPL changes fields between seasons. Name the field."""
    for key in ("events", "elements"):
        if key not in data or not data[key]:
            raise AssertionError(f"SCHEMA DRIFT: bootstrap-static has no '{key}'")
    miss_e = REQUIRED_EVENT_FIELDS - set(data["events"][0])
    if miss_e:
        raise AssertionError(f"SCHEMA DRIFT: events missing {sorted(miss_e)}")
    miss_p = REQUIRED_ELEMENT_FIELDS - set(data["elements"][0])
    if miss_p:
        raise AssertionError(f"SCHEMA DRIFT: elements missing {sorted(miss_p)}")
    bad = {e["status"] for e in data["elements"]} - KNOWN_STATUSES
    if bad:
        raise AssertionError(
            f"SCHEMA DRIFT: unknown status letter(s) {sorted(bad)} -- the "
            f"availability characterisation (a/d/i/s/u/n) no longer covers "
            f"the data. Characterise before trusting.")


def season_of(data):
    """FPL does not name the season; derive it from the GW1 deadline year."""
    d = _ts(data["events"][0]["deadline_time"])
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


def next_deadline(data, now=None):
    """(gw, deadline) of the next event whose deadline is not yet past the
    post-deadline grace. Deadlines come from the API, never hard-coded."""
    now = now or _now()
    for e in data["events"]:
        d = _ts(e["deadline_time"])
        if d + timedelta(minutes=POST_DEADLINE_GRACE) > now:
            return int(e["id"]), d
    return None, None


def raw_dir(season):
    p = LIVE / "bootstrap_raw" / season
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_raw(data, season, ts):
    """Temp-then-rename: never a half-written archive file."""
    out = raw_dir(season) / f"{ts.strftime('%Y%m%dT%H%M%SZ')}.json.gz"
    if out.exists():
        return out
    fd, tmp = tempfile.mkstemp(dir=out.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(gzip.compress(json.dumps(data).encode("utf-8")))
        os.replace(tmp, out)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return out


def list_raw(season):
    d = LIVE / "bootstrap_raw" / season
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json.gz")):
        out.append((datetime.strptime(p.stem.split(".")[0], "%Y%m%dT%H%M%SZ")
                    .replace(tzinfo=timezone.utc), p))
    return out


def load_raw(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def elements_map(data):
    return {e["id"]: {f: e.get(f) for f in FIELDS} for e in data["elements"]}


def detect_changes(prev_data, cur_data, cur_ts, season, gw, deadline):
    """Rows for players whose status / cop_this_round / news moved between
    consecutive polls. Appended (deduped) to the changes parquet."""
    prev, cur = elements_map(prev_data), elements_map(cur_data)
    rows = []
    for el, c in cur.items():
        p = prev.get(el)
        if p is None:
            continue
        moved = {f: (p[f], c[f]) for f in CHANGE_FIELDS if p[f] != c[f]}
        if moved:
            rows.append({"season": season, "gw": gw, "element": el,
                         "snapshot_time": cur_ts, "deadline_time": deadline,
                         "minutes_to_deadline":
                             (deadline - cur_ts).total_seconds() / 60.0
                             if deadline else None,
                         **{f"old_{f}": p[f] for f in CHANGE_FIELDS},
                         **{f"new_{f}": c[f] for f in CHANGE_FIELDS},
                         "news_added": c["news_added"]})
    if not rows:
        return 0
    new = pd.DataFrame(rows)
    out = LIVE / f"availability_changes_{season.replace('-', '_')}.parquet"
    if out.exists():
        old = pd.read_parquet(out)
        new = (pd.concat([old, new], ignore_index=True)
               .drop_duplicates(["snapshot_time", "element"]))
    tmp = out.with_suffix(".tmp.parquet")
    new.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    return len(rows)


def due(season, deadline, now=None):
    """Is a poll due now? Cadence gating against the newest raw file, so any
    external scheduler frequency is safe and double-starts are idempotent."""
    now = now or _now()
    to_deadline = (deadline - now).total_seconds()
    if to_deadline > WINDOW_HOURS * 3600:
        return False, f"window opens at deadline-{WINDOW_HOURS:.0f}h"
    snaps = list_raw(season)
    if to_deadline <= 0:      # one post-deadline poll for the asof recovery
        have_post = any(ts >= deadline for ts, _ in snaps)
        return (not have_post), "post-deadline recovery poll" \
            if not have_post else "post-deadline poll already taken"
    cadence = FINAL_HOUR_CADENCE if to_deadline <= 3600 else NORMAL_CADENCE
    last = max((ts for ts, _ in snaps), default=None)
    if last is None or (now - last).total_seconds() >= cadence:
        return True, f"cadence {cadence // 60} min"
    wait = cadence - (now - last).total_seconds()
    return False, f"next poll in {wait / 60:.0f} min"


def tick(force=False):
    """One scheduling decision + at most one poll. Safe at any frequency."""
    data = fetch()                      # also the deadline source
    season = season_of(data)
    gw, deadline = next_deadline(data)
    if deadline is None:
        print("no upcoming deadline in events -- season over?")
        return
    now = _now()
    is_due, why = due(season, deadline, now)
    label = "FORCED" if (force and not is_due) else \
        ("DUE" if is_due else "not due")
    print(f"GW{gw} deadline {deadline:%Y-%m-%d %H:%M}Z "
          f"({(deadline - now).total_seconds() / 3600:+.1f}h) -- "
          f"{label} ({why})")
    if not (is_due or force):
        return
    snaps = list_raw(season)
    path = store_raw(data, season, now)
    print(f"stored {path.name} ({len(data['elements'])} elements)")
    if snaps:                           # diff against the previous poll
        n = detect_changes(load_raw(snaps[-1][1]), data, now, season, gw,
                           deadline)
        flagged = f"{n} player(s) CHANGED since {snaps[-1][0]:%H:%M}Z" if n \
            else "no changes since previous poll"
        print(f"change detection: {flagged}")


def build(season=None):
    """(gw, element) table with the SAME columns and asof rule as
    data/availability_{season}.parquet. Only gameweeks whose deadline has
    passed AND that have at least one pre-deadline live poll are built."""
    seasons = [season] if season else \
        [p.name for p in (LIVE / "bootstrap_raw").glob("*") if p.is_dir()]
    for s in seasons:
        snaps = list_raw(s)
        if not snaps:
            print(f"{s}: no raw polls")
            continue
        ref = load_raw(snaps[-1][1])
        deadlines = {int(e["id"]): _ts(e["deadline_time"])
                     for e in ref["events"]}
        rows = []
        for gw, deadline in sorted(deadlines.items()):
            prior = [(ts, p) for ts, p in snaps if ts < deadline]
            after = [(ts, p) for ts, p in snaps if ts >= deadline]
            if not prior or deadline > _now():
                continue
            snap_ts, snap_path = prior[-1]
            cur = elements_map(load_raw(snap_path))
            # asof recovery -- identical rule to build_availability.late_news:
            # first post-deadline poll, accept only news stamped inside the gap
            late = {}
            if after:
                for el, e in elements_map(load_raw(after[0][1])).items():
                    na = _ts(e["news_added"]) if e["news_added"] else None
                    if na and snap_ts < na < deadline:
                        late[el] = e
            for el, e in cur.items():
                row = {"gw": gw, "element": el, **e,
                       "snapshot_time": snap_ts, "deadline_time": deadline,
                       "hours_before_deadline":
                           (deadline - snap_ts).total_seconds() / 3600.0,
                       "snapshot_path": str(snap_path.relative_to(REPO))}
                src = late.get(el, e)
                row.update({f"asof_{f}": src.get(f) for f in FIELDS})
                row["asof_source"] = ("live_late_news" if el in late
                                      else "live_snapshot")
                row["season"] = s
                rows.append(row)
        if not rows:
            print(f"{s}: no completed deadlines with pre-deadline polls yet")
            continue
        df = pd.DataFrame(rows)
        for c in ("news_added", "asof_news_added", "snapshot_time",
                  "deadline_time"):
            df[c] = pd.to_datetime(df[c], utc=True)
        for c in ("chance_of_playing_this_round",
                  "chance_of_playing_next_round"):
            df[c] = df[c].astype("Float64")
            df[f"asof_{c}"] = df[f"asof_{c}"].astype("Float64")
        df["gw"] = df["gw"].astype("int8")        # match the historical file's
        df["element"] = df["element"].astype("int32")   # dtypes exactly
        assert (df["snapshot_time"] < df["deadline_time"]).all(), \
            "leak: snapshot at/after deadline"
        out = LIVE / f"availability_{s.replace('-', '_')}_live.parquet"
        tmp = out.with_suffix(".tmp.parquet")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, out)
        print(f"{s}: {len(df)} rows, {df['gw'].nunique()} gameweek(s) -> {out}")


def watch():
    print("watch mode: ticking every 60s (the tick gates itself)")
    while True:
        try:
            tick()
        except Exception as e:          # a failed fetch must not kill the loop
            print(f"tick failed: {type(e).__name__}: {e}")
        time.sleep(60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--season", default=None)
    a = ap.parse_args()
    if a.watch:
        watch()
    elif a.build:
        build(a.season)
    elif a.once or a.force:
        tick(force=a.force)
    else:                               # --status (default)
        d = fetch()
        s = season_of(d)
        gw, dl = next_deadline(d)
        n = len(list_raw(s))
        print(f"season {s}, next: GW{gw} deadline {dl:%Y-%m-%d %H:%M}Z, "
              f"{n} raw poll(s) archived")
        print(f"due: {due(s, dl)}")
