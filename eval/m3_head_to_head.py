"""M3 B3 -- points, same squad head-to-head: the crowd frames against the frames of record. PROBE CODE: nothing in
production imports it; it writes only under data/m3/h2h/.

THE READ. A season total cannot measure a change that alters which players get picked (path sd ~60). So both
arms are started from the IDENTICAL squad state at every anchor gameweek -- the reference record's own state at
that deadline (data/arms/armlog_*_gap0_tc2_m3a, rebuilt by replaying the log and asserted against it at every
gameweek) -- and run freely for W gameweeks against the same realised outcomes: each arm makes its own
transfers, captain and XI from its own frame, the chip weeks are the record's for both, and every solve plans
against the whole season's calendar (squad/pathcontrol.window_run). Paired delta per anchor = crowd - baseline
realised points net of hits over the window.

  W = 6 (PRIMARY): anchors 1..33.   W = 3 (reported): anchors 1..36 -- the first three gameweeks of the same
  run for anchors 1..33 (the simulator never looks at how long the caller will keep playing), plus three-
  gameweek runs for anchors 34..36.
  Anchor 1 has no state to share: each arm picks its own opening fifteen (an identical start: nothing held).
  Points = the simulator's `points` (XI + captain after autosubs, minus hits; Triple Captain 2 is in-sim).
  Also reported: the same plus the bench in a Bench Boost week that falls inside the window.
  The baseline arm restarted from the record's state must REPRODUCE the record's own gameweeks (the simulator
  is deterministic); that is checked on every anchor and reported, not assumed.

Intervals: block bootstrap over anchors in anchor order (blocks of 4, 2,000 draws) per season; pooled = every
anchor of every season, the seasons' draws stacked (pathcontrol.summarise_head_to_head).

Usage:
    uv run python eval/m3_head_to_head.py run  --season 2025-26 --crowd-dir data/arms_crowd --out-dir data/m3/h2h --workers 8
    uv run python eval/m3_head_to_head.py read --out-dir data/m3/h2h
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

SEASONS = ["2023-24", "2024-25", "2025-26"]
TC2 = {"2023-24": 25, "2024-25": 24, "2025-26": 26}       # the reference configuration's in-sim Triple Captain 2 week
W_PRIMARY, W_SHORT = 6, 3
ARMS = ("base", "crowd")
KEEP = ["gw", "points", "raw_points", "hit", "n_transfers", "all_transfers", "captain", "captain_bonus", "bench_points",
        "wildcard", "free_hit", "triple_captain", "free_transfers", "bank", "elements"]


def tag(season):
    return season.replace("-", "_")


def schedule(season):
    """The reference configuration's chip schedule (eval/run_arms_full_system.py: gap0 + TC2 in-sim)."""
    import run_arms_full_system as rafs
    import run_full_system as rfs
    bb1, bb2 = rfs.BB1[(season, rafs.OPENING)], rfs.BB2[season]
    return dict(wildcard_gws=[rafs.WC1, rfs.WC2[season]], free_hit_gws=rfs.FH2[season],
                bench_boost_gw=[bb1, bb2], triple_captain_gw=TC2[season]), {bb1, bb2}


def frame_path(season, arm, crowd_dir):
    return (REPO / "data" / f"walkforward_h6_{tag(season)}.parquet" if arm == "base"
            else Path(crowd_dir) / f"walkforward_h6_{tag(season)}_crowd.parquet")


def record_path(season):
    return REPO / "data" / "arms" / f"armlog_{tag(season)}_gap0_tc2_m3a.parquet"


def tasks_for(season):
    """(anchor, gameweeks to play): six from anchors 1..33, three from anchors 34..36."""
    return [(k, W_PRIMARY) for k in range(1, 38 - W_PRIMARY + 2)] + [(k, W_SHORT) for k in range(38 - W_PRIMARY + 2, 38 - W_SHORT + 2)]


_CACHE = {}


def _load(season, arm, crowd_dir):
    import simulator
    key = (season, arm, str(crowd_dir))
    if key not in _CACHE:
        _CACHE[key] = simulator.load_season(walkforward_path=str(frame_path(season, arm, crowd_dir)), horizon_aware=True, season=season)
    return _CACHE[key]


def run_one(season, anchor, n_gws, arm, crowd_dir, out_dir):
    """One arm, one window. Writes one small parquet; skips if it exists. Returns (path, seconds)."""
    out = Path(out_dir) / f"h2h_{tag(season)}_a{anchor:02d}_{arm}.parquet"
    if out.exists():
        return str(out), 0.0
    import contextlib
    import io
    import pathcontrol as pc
    import run_arms_full_system as rafs
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        df = _load(season, arm, crowd_dir)
        canon = _load(season, "base", crowd_dir)
    sched, _ = schedule(season)
    state = None
    if anchor > 1:
        record = pd.read_parquet(record_path(season))
        state = rafs.replay_state(record, canon, anchor - 1)          # asserted against the record at every gameweek
    window = list(range(anchor, anchor + n_gws))
    log = pc.window_run(df, window, state, schedule=sched)
    d = log[KEEP].copy()
    d["all_transfers"] = d["all_transfers"].map(lambda t: json.dumps([[int(a), int(b)] for a, b in t]))
    d["elements"] = d["elements"].map(lambda e: json.dumps([int(x) for x in e]))
    d.insert(0, "arm", arm); d.insert(0, "anchor", anchor); d.insert(0, "season", season)
    d["frame"] = frame_path(season, arm, crowd_dir).name
    d["solver_threads"] = os.environ.get("FPL_SOLVER_THREADS", "unset")
    tmp = out.with_suffix(".tmp.parquet")
    d.to_parquet(tmp, index=False)
    tmp.replace(out)
    return str(out), time.time() - t0


def cmd_run(a):
    from concurrent.futures import ProcessPoolExecutor, as_completed
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seasons = a.season or SEASONS
    for s in seasons:
        assert record_path(s).exists() and frame_path(s, "crowd", a.crowd_dir).exists(), f"{s}: the record log or the crowd frame is missing"
    todo = [(s, k, n, arm) for s in seasons for k, n in tasks_for(s) for arm in ARMS
            if not (out_dir / f"h2h_{tag(s)}_a{k:02d}_{arm}.parquet").exists()]
    # longest first, so the tail of the run is not one slow window
    todo.sort(key=lambda t: (-t[2], t[0], t[1]))
    print(f"windows to run {len(todo)} (seasons {seasons}; workers {a.workers}; solver threads {os.environ.get('FPL_SOLVER_THREADS', 'unset')})", flush=True)
    t0, done = time.time(), 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, s, k, n, arm, a.crowd_dir, str(out_dir)): (s, k, n, arm) for s, k, n, arm in todo}
        for f in as_completed(futs):
            s, k, n, arm = futs[f]
            path, secs = f.result()
            done += 1
            print(f"[{done}/{len(todo)}] {s} anchor {k:2d} x{n} {arm:5s} {secs:6.0f}s  (elapsed {(time.time() - t0) / 60:.1f} min)", flush=True)
    print(f"done in {(time.time() - t0) / 60:.1f} min")


# ------------------------------------------------------------------ read
def load_windows(out_dir, season):
    files = sorted(Path(out_dir).glob(f"h2h_{tag(season)}_a*_*.parquet"))
    d = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    return d, len(files)


def self_replay(d, record):
    """Baseline windows against the record's own rows: anchors whose every gameweek has the same points, hit,
    transfers and captain as the record."""
    rec = record.set_index("gw")
    ok, bad = [], []
    for k, g in d[d["arm"] == "base"].groupby("anchor"):
        same = True
        for r in g.itertuples():
            x = rec.loc[r.gw]
            xt = x["all_transfers"]; xt = json.loads(xt) if isinstance(xt, str) else [[int(a), int(b)] for a, b in xt]
            if not (int(r.points) == int(x["points"]) and int(r.hit) == int(x["hit"]) and json.loads(r.all_transfers) == [[int(a), int(b)] for a, b in xt]
                    and str(r.captain) == str(x["captain"])):
                same = False
                break
        (ok if same else bad).append(int(k))
    return ok, bad


def window_deltas(d, W, bb_weeks):
    """One row per anchor whose W-gameweek window fits: both arms' points over anchor..anchor+W-1 and the delta."""
    rows = []
    for k in sorted(d["anchor"].unique()):
        if k + W - 1 > 38:
            continue
        w = d[(d["anchor"] == k) & (d["gw"] < k + W)]
        b, c = w[w["arm"] == "base"].sort_values("gw"), w[w["arm"] == "crowd"].sort_values("gw")
        if len(b) != W or len(c) != W:
            continue
        bench = lambda x: int(x.loc[x["gw"].isin(bb_weeks), "bench_points"].sum())
        tb, tc = [json.loads(t) for t in b["all_transfers"]], [json.loads(t) for t in c["all_transfers"]]
        rows.append(dict(anchor=int(k), W=W, base=int(b["points"].sum()), crowd=int(c["points"].sum()),
                         delta=int(c["points"].sum() - b["points"].sum()),
                         delta_with_bb_bench=int(c["points"].sum() + bench(c) - b["points"].sum() - bench(b)),
                         hits_base=int(b["hit"].sum()), hits_crowd=int(c["hit"].sum()),
                         first_week_transfers_differ=bool(sorted(map(tuple, tb[0])) != sorted(map(tuple, tc[0]))),
                         first_week_captain_differs=bool(b["captain"].iloc[0] != c["captain"].iloc[0]),
                         weeks_transfers_differ=int(sum(sorted(map(tuple, x)) != sorted(map(tuple, y)) for x, y in zip(tb, tc))),
                         weeks_captain_differs=int((b["captain"].to_numpy() != c["captain"].to_numpy()).sum())))
    return pd.DataFrame(rows)


def cmd_read(a):
    import pathcontrol as pc
    out_dir = Path(a.out_dir)
    per = {W_PRIMARY: {}, W_SHORT: {}}
    alt = {W_PRIMARY: {}, W_SHORT: {}}
    for s in SEASONS:
        d, n_files = load_windows(out_dir, s)
        record = pd.read_parquet(record_path(s))
        _, bb = schedule(s)
        ok, bad = self_replay(d, record)
        anchors = sorted(int(k) for k in d["anchor"].unique())
        print(f"[{s}] window files {n_files}; anchors {len(anchors)} (first {anchors[0]}, last {anchors[-1]}); frames {sorted(d['frame'].unique())}; "
              f"solver threads {sorted(d['solver_threads'].unique())} | baseline restarted from the record's state reproduces the record's own gameweeks "
              f"on {len(ok)} of {len(ok) + len(bad)} anchors" + (f" -- NOT on anchors {bad}" if bad else ""))
        for W in (W_PRIMARY, W_SHORT):
            t = window_deltas(d, W, bb)
            per[W][s] = t.set_index("anchor")["delta"]
            alt[W][s] = t.set_index("anchor")["delta_with_bb_bench"]
            print(f"[{s}] W={W}: anchors {len(t)} (first {int(t.anchor.min())}, last {int(t.anchor.max())}) | crowd better on {int((t.delta > 0).sum())}, "
                  f"baseline better on {int((t.delta < 0).sum())}, tied {int((t.delta == 0).sum())} | mean window points baseline {t.base.mean():.2f}, crowd {t.crowd.mean():.2f} | "
                  f"hits per window baseline {t.hits_base.mean():.2f}, crowd {t.hits_crowd.mean():.2f} pts | at the anchor gameweek (identical state): transfers differ on "
                  f"{int(t.first_week_transfers_differ.sum())} of {len(t)} anchors, captain on {int(t.first_week_captain_differs.sum())} of {len(t)} | over all {W} weeks: "
                  f"transfers differ in {int(t.weeks_transfers_differ.sum())} of {W * len(t)} window-weeks, captain in {int(t.weeks_captain_differs.sum())} of {W * len(t)}")
            if a.verbose:
                print(t[["anchor", "base", "crowd", "delta", "delta_with_bb_bench"]].to_string(index=False))
    for W in (W_PRIMARY, W_SHORT):
        for label, src in (("points net of hits (the rule's read)", per), ("the same + the bench in a Bench Boost week", alt)):
            sm = pc.summarise_head_to_head(src[W])
            print(f"\n=== W={W}{' (PRIMARY)' if W == W_PRIMARY else ' (reported)'} -- {label} ===")
            print(sm.to_string(index=False))
    sm = pc.summarise_head_to_head(per[W_PRIMARY]).set_index("season")
    pooled = float(sm.loc["pooled", "mean_delta"])
    positive = int((sm.loc[SEASONS, "mean_delta"] > 0).sum())
    print(f"\nADOPTION RULE clause (2), W=6: pooled mean gain {pooled:+.3f} (> 0: {pooled > 0}); positive in {positive} of 3 seasons (>= 2: {positive >= 2}) "
          f"-> {'HOLDS' if pooled > 0 and positive >= 2 else 'FAILS'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--season", action="append", choices=SEASONS)
    r.add_argument("--crowd-dir", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--workers", type=int, default=6)
    d = sub.add_parser("read")
    d.add_argument("--out-dir", required=True)
    d.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    {"run": cmd_run, "read": cmd_read}[a.cmd](a)


if __name__ == "__main__":
    main()
