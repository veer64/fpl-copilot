#!/usr/bin/env python
"""
Falsification suite for the path-controlled harness. Run this BEFORE trusting any
number it produces.

A variance-reduction instrument is dangerous precisely because it makes everything
look cleaner. These four checks are what stops it becoming a significance machine:

  1. reproduces_simulate_season  — the harness replays the loop itself rather than
     calling simulate_season, because that function always starts at GW1 with no
     squad. That duplication is this module's main risk, so W=38 from GW1 must
     return exactly the known baseline (1984).

  2. selfreplay_matches_reference — the crossover reads each arm's own half off its
     reference log instead of recomputing it, on the grounds that a deterministic
     arm restarted from its own state reproduces itself. Checked, not assumed.

  3. null_treatment — two IDENTICAL arms must give exactly zero at every anchor and
     every W. If a difference appears here, the harness is manufacturing it.

  4. oracle_treatment — an arm with perfect foresight must come back large and
     positive at every W. Calibrates that the instrument can still SEE an effect
     after removing path noise. A harness that reports zero for everything is as
     useless as one that reports significance for everything.

Usage:
    uv run python eval/falsify_pathcontrol.py
    uv run python eval/falsify_pathcontrol.py --quick    # fewer anchors
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

# Lives in eval/, so the repo root is two levels up -- same convention as
# walkforward.py, which has always sat here.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import pathcontrol as pc  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

WALKFWD = REPO / "data" / "walkforward_h6_2526.parquet"
BASELINE_TOTAL = 1984
SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
ARM_KW = dict(mode="balanced", horizon=3, decay=0.3)

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail):
    results.append({"check": name, "result": PASS if ok else FAIL, "detail": detail})
    print(f"  [{PASS if ok else FAIL}] {name}: {detail}", flush=True)
    return ok


def oracle_frame(season):
    """Perfect foresight. This is a DELIBERATE leak — it exists only to prove the
    instrument can see a large effect, and must never be used as a result."""
    d = season.copy()
    d["e_points"] = pd.to_numeric(d["actual_points"], errors="coerce").fillna(0.0)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    season = load_season(walkforward_path=WALKFWD, horizon_aware=True)
    base = pc.Arm("baseline", season, **ARM_KW)

    print("\n=== 1. harness reproduces simulate_season ===", flush=True)
    ref_log, ref_states = pc.trajectory(base)
    harness_total = int(ref_log.points.sum())
    state, sim_log = simulate_season(season, **SIM_KW)
    check("reproduces_simulate_season",
          harness_total == int(state.total_points) == BASELINE_TOTAL,
          f"harness {harness_total}, simulate_season {int(state.total_points)}, "
          f"expected {BASELINE_TOTAL}")
    same_gw = (ref_log.set_index("gw").points == sim_log.set_index("gw").points).all()
    check("reproduces_simulate_season_per_gameweek", bool(same_gw),
          "every gameweek identical" if same_gw else "per-gameweek points differ")

    print("\n=== 2. self-replay identity (the crossover shortcut) ===", flush=True)
    anchors = [1, 5, 12, 20, 30] if args.quick else [1, 5, 9, 14, 20, 26, 30, 34]
    bad = []
    for k in anchors:
        w = [g for g in base.all_gws if k <= g < k + 3]
        rows, _ = pc._replay(base, w, pc._restored(ref_states[k]))
        got = sum(r["points"] for r in rows)
        want = int(ref_log[ref_log.gw.isin(w)].points.sum())
        if got != want:
            bad.append((k, got, want))
    check("selfreplay_matches_reference", not bad,
          f"{len(anchors)} anchors replayed exactly" if not bad
          else f"mismatches at {bad}")

    print("\n=== 3. null treatment (identical arms) ===", flush=True)
    null_arm = pc.Arm("null", season, **ARM_KW)
    nrows = pc.windowed(base, null_arm, W=3,
                        anchors=anchors, ref_log_a=ref_log, states_a=ref_states,
                        ref_log_b=ref_log, states_b=ref_states, verbose=False)
    check("null_treatment_is_exactly_zero", bool((nrows.delta == 0).all()),
          f"max |delta| = {nrows.delta.abs().max()} over {len(nrows)} rows")

    print("\n=== 4. oracle treatment (perfect foresight) ===", flush=True)
    oracle = pc.Arm("oracle", oracle_frame(season), **ARM_KW)
    o_log, o_states = pc.trajectory(oracle)
    print(f"  oracle season total: {int(o_log.points.sum())} "
          f"(baseline {BASELINE_TOTAL})", flush=True)
    orows = pc.windowed(base, oracle, W=3, anchors=anchors,
                        ref_log_a=ref_log, states_a=ref_states,
                        ref_log_b=o_log, states_b=o_states, verbose=False)
    s = pc.summarise(orows)
    mean_delta = float(s.mean_delta_per_window.iloc[0])
    check("oracle_is_large_and_positive", mean_delta > 20,
          f"+{mean_delta:.1f} pts per 3-gameweek window, CI "
          f"[{s.ci_low.iloc[0]:+.1f}, {s.ci_high.iloc[0]:+.1f}]")
    check("oracle_wins_at_nearly_every_anchor",
          s.anchors_b_better.iloc[0] >= len(anchors) - 1,
          f"{s.anchors_b_better.iloc[0]} of {len(anchors)} anchors")

    print("\n" + "=" * 74)
    out = pd.DataFrame(results)
    print(out.to_string(index=False))
    failed = (out.result == FAIL).sum()
    print("=" * 74)
    print(f"{len(out) - failed} passed, {failed} failed")
    if failed:
        print("\nDO NOT USE THE HARNESS UNTIL THESE PASS.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
