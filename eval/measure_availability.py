#!/usr/bin/env python
"""
Measure what the availability signal is worth, as a season simulation.

The intervention rewrites `e_points` (and `e_minutes`, for the prediction metrics)
in the horizon-aware walk-forward frame using the availability state that was
readable at the CUTOFF deadline, then replays the season through the unmodified
simulator.

THE LEAK RULE
-------------
A row is keyed (cutoff, gw, element): the view a manager standing at gameweek
`cutoff` had of gameweek `gw`. The only availability he could read is the state at
the CUTOFF deadline — not at gw's. So the join is always on `gw == cutoff` in the
availability file, and the same adjustment is carried across every horizon step.
Joining on the row's own `gw` would let the planner see next week's injury news,
which is exactly the leak this file exists to avoid.

We use the `asof_*` columns: the deadline-accurate reconstruction. Production reads
bootstrap-static live at the deadline and sees precisely that state.

Usage:
    uv run python eval/measure_availability.py --arms baseline zeros_all both
    uv run python eval/measure_availability.py --metrics-only
    uv run python eval/measure_availability.py --report
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# Lives in eval/, so the repo root is two levels up -- same convention as
# walkforward.py, which has always sat here.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

WALKFWD = REPO / "data" / "walkforward_h6_2526.parquet"
AVAIL = REPO / "data" / "availability_2526.parquet"
RESULTS = REPO / "data" / "availability_measurement.parquet"
LOGS = REPO / "data" / "availability_measurement_logs.parquet"

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
BASELINE_TOTAL = 1984
COLD_START = 7  # GW1-7, the documented cold-start window

OUT_STATUSES = {"i", "s", "n", "u"}
DEPARTURE = re.compile(
    r"joined|signed by|on loan to|loan|permanently|departed the club|transferred", re.I
)


# ---------------------------------------------------------------------------
# Availability state, keyed by the deadline it was readable at
# ---------------------------------------------------------------------------
def availability_at_cutoff() -> pd.DataFrame:
    """One row per (cutoff, element): what the manager could read at that deadline."""
    av = pd.read_parquet(AVAIL)
    av = av[["gw", "element", "asof_status", "asof_chance_of_playing_this_round",
             "asof_news"]].rename(columns={
                 "gw": "cutoff",
                 "asof_status": "status",
                 "asof_chance_of_playing_this_round": "cop",
                 "asof_news": "news"})
    av["is_out"] = av.status.isin(OUT_STATUSES)
    av["departure"] = av.news.fillna("").str.contains(DEPARTURE)

    # Was this absence already visible at the PREVIOUS deadline? Distinguishes the
    # case the model cannot see (news just broke) from the one it has zeros for.
    av = av.sort_values(["element", "cutoff"])
    prev_out = av.groupby("element")["is_out"].shift()
    prev_cut = av.groupby("element")["cutoff"].shift()
    contiguous = prev_cut == av.cutoff - 1
    av["new_absence"] = av.is_out & contiguous & (prev_out == False)
    av["ongoing_absence"] = av.is_out & (~av.new_absence)
    return av


def d_multiplier(cop: pd.Series, kind) -> pd.Series:
    """Survival multiplier for status='d'. `kind` is 'cop' or a constant in [0, 1]."""
    if kind == "cop":
        # FPL's own number, taken at face value. Null means "flagged but no
        # percentage given" — the midpoint is the only non-arbitrary choice.
        return (cop / 100.0).fillna(0.5).astype(float)
    return pd.Series(float(kind), index=cop.index)


# ---------------------------------------------------------------------------
# The arms
# ---------------------------------------------------------------------------
# zero_when : which rows get e_points forced to 0, as a predicate on the joined frame
# d_kind    : None for no doubtful handling, else 'cop' or a constant multiplier
# h0_only   : apply the adjustment only at horizon step 0 (gw == cutoff)
ARMS = {
    "baseline":     dict(zero_when=None, d_kind=None),
    "zeros_all":    dict(zero_when="out", d_kind=None),
    "d_only":       dict(zero_when=None, d_kind="cop"),
    "both":         dict(zero_when="out", d_kind="cop"),
    "u_only":       dict(zero_when="departure_out", d_kind=None),
    "isn_only":     dict(zero_when="injury_out", d_kind=None),
    "first_only":   dict(zero_when="new_absence", d_kind=None),
    "ongoing_only": dict(zero_when="ongoing_absence", d_kind=None),
    "zeros_h0":     dict(zero_when="out", d_kind=None, h0_only=True),
    "d_sweep_0.00": dict(zero_when="out", d_kind=0.00),
    "d_sweep_0.25": dict(zero_when="out", d_kind=0.25),
    "d_sweep_0.50": dict(zero_when="out", d_kind=0.50),
    "d_sweep_0.75": dict(zero_when="out", d_kind=0.75),
    "d_sweep_1.00": dict(zero_when="out", d_kind=1.00),  # == zeros_all, a sanity check
}


def adjusted_frame(arm: str) -> tuple[pd.DataFrame, dict]:
    """The walk-forward frame with e_points/e_minutes rewritten for one arm."""
    spec = ARMS[arm]
    wf = pd.read_parquet(WALKFWD)
    if spec["zero_when"] is None and spec["d_kind"] is None:
        return wf, {"rows_zeroed": 0, "rows_scaled": 0}

    av = availability_at_cutoff()
    df = wf.merge(av, on=["cutoff", "element"], how="left")
    assert len(df) == len(wf), "availability join changed row count"

    mult = pd.Series(1.0, index=df.index)

    # A player with no availability row at that cutoff was not yet in the game, so
    # there was no news to read: no adjustment.
    # `.eq(True)` rather than fillna: the left merge turns these bool columns into
    # object with NaN, and NaN must read as "no flag", not as a downcast surprise.
    flag = lambda col: df[col].eq(True)
    predicates = {
        "out": flag("is_out"),
        "departure_out": flag("is_out") & flag("departure"),
        "injury_out": flag("is_out") & ~flag("departure"),
        "new_absence": flag("new_absence"),
        "ongoing_absence": flag("ongoing_absence"),
    }
    zero_mask = predicates[spec["zero_when"]] if spec["zero_when"] else pd.Series(False, index=df.index)
    mult[zero_mask] = 0.0

    scale_mask = pd.Series(False, index=df.index)
    if spec["d_kind"] is not None:
        scale_mask = (df.status == "d").fillna(False) & ~zero_mask
        mult[scale_mask] = d_multiplier(df.cop, spec["d_kind"])[scale_mask]

    if spec.get("h0_only"):
        # Only the gameweek being played is adjusted; the plan's future legs keep
        # their unadjusted values.
        off = df.gw != df.cutoff
        mult[off] = 1.0
        zero_mask &= ~off
        scale_mask &= ~off

    out = wf.copy()
    out["e_points"] = out["e_points"] * mult.values
    out["e_minutes"] = out["e_minutes"] * mult.values
    return out, {"rows_zeroed": int(zero_mask.sum()), "rows_scaled": int(scale_mask.sum())}


# ---------------------------------------------------------------------------
# Running one arm
# ---------------------------------------------------------------------------
def run_arm(arm: str, tmpdir: Path) -> tuple[dict, pd.DataFrame]:
    from simulator import load_season, simulate_season

    frame, counts = adjusted_frame(arm)
    path = tmpdir / f"wf_{arm}.parquet"
    frame.to_parquet(path, index=False)

    season = load_season(walkforward_path=path, horizon_aware=True)
    state, log = simulate_season(season, **SIM_KW)
    path.unlink(missing_ok=True)

    pts = log["points"].values
    res = {
        "arm": arm,
        "total": int(state.total_points),
        "vs_baseline": int(state.total_points) - BASELINE_TOTAL,
        "gw1_7": float(pts[:COLD_START].sum()),
        "gw1_7_per_gw": float(pts[:COLD_START].mean()),
        "gw8_plus": float(pts[COLD_START:].sum()),
        "gw8_plus_per_gw": float(pts[COLD_START:].mean()),
        "transfers": int(log["transfer_in"].notna().sum()),
        "hits": float(log["hit"].sum()),
        "bench_points_left": float(log["bench_points"].sum()),
        **counts,
    }
    log = log.copy()
    log["arm"] = arm
    return res, log


# ---------------------------------------------------------------------------
# Prediction metrics — does this improve ranking, or only delete obvious zeros?
# ---------------------------------------------------------------------------
def prediction_metrics(arms) -> pd.DataFrame:
    rows = []
    for arm in arms:
        frame, _ = adjusted_frame(arm)
        d = frame[frame.horizon_step == 0].dropna(subset=["e_points"])
        for label, sub in [
            ("all rows", d),
            ("played (mins>0)", d[d.minutes > 0]),
            ("started 60+", d[d.minutes >= 60]),
        ]:
            rho = spearmanr(sub.e_points, sub.actual_points).statistic
            rows.append({
                "arm": arm, "subset": label, "n": len(sub),
                "spearman": round(float(rho), 4),
                "mae": round(float((sub.e_points - sub.actual_points).abs().mean()), 4),
                "bias": round(float((sub.e_points - sub.actual_points).mean()), 4),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arms", nargs="*", default=None, help="arm names, or all")
    ap.add_argument("--repeat", type=int, default=1, help="runs per arm (determinism check)")
    ap.add_argument("--tmpdir", type=Path, default=REPO / ".avtmp")
    ap.add_argument("--tag", default="", help="suffix for output files, for parallel jobs")
    ap.add_argument("--metrics-only", action="store_true")
    args = ap.parse_args()

    arms = args.arms or list(ARMS)
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise SystemExit(f"unknown arms: {sorted(unknown)}")

    if args.metrics_only:
        print(prediction_metrics(arms).to_string(index=False))
        return

    args.tmpdir.mkdir(exist_ok=True)
    results, logs = [], []
    for arm in arms:
        for rep in range(args.repeat):
            res, log = run_arm(arm, args.tmpdir)
            res["rep"] = rep
            log["rep"] = rep
            results.append(res)
            logs.append(log)
            print(f"{arm:15s} rep{rep}  total={res['total']:5d}  "
                  f"vs1984={res['vs_baseline']:+5d}  "
                  f"gw1-7={res['gw1_7_per_gw']:.1f}/gw  "
                  f"gw8+={res['gw8_plus_per_gw']:.1f}/gw  "
                  f"zeroed={res['rows_zeroed']}", flush=True)

    suffix = f"_{args.tag}" if args.tag else ""
    pd.DataFrame(results).to_parquet(RESULTS.with_name(RESULTS.stem + suffix + ".parquet"), index=False)
    pd.concat(logs).to_parquet(LOGS.with_name(LOGS.stem + suffix + ".parquet"), index=False)


if __name__ == "__main__":
    main()
