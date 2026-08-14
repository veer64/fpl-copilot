#!/usr/bin/env python
"""
Report the availability measurement: totals, cold-start split, paired bootstrap.

Reads the arm results written by measure_availability.py and pairs every arm against
the baseline gameweek by gameweek, which is the only comparison the block bootstrap
in squad/bootstrap.py can support.

KNOWN LIMITATION, stated because it bounds every interval below: the bootstrap
resamples gameweeks within ONE realised path per arm. It does not sample the path
lottery — the fact that a different transfer early on sends the whole season
somewhere else. Season sd from path divergence at this config is ~52, and a margin
under that is not established by a single run no matter what the interval says.
"""

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "squad"))
from bootstrap import compare_strategies  # noqa: E402

PATH_SD = 52.0  # season sd from path divergence at H=3, decay=0.3, balanced


def load():
    res = pd.concat([pd.read_parquet(p) for p in
                     sorted(REPO.glob("data/availability_measurement_*.parquet"))
                     if "_logs" not in p.stem])
    logs = pd.concat([pd.read_parquet(p) for p in
                      sorted(REPO.glob("data/availability_measurement_logs*.parquet"))])
    return res, logs


def exposure(logs):
    """How often did the baseline squad actually hold a player flagged out?

    This bounds the whole intervention. Zeroing a departed reserve who was never
    going to be bought changes nothing; the gain can only come from squad members
    the manager was about to field.
    """
    from measure_availability import availability_at_cutoff

    print("\n" + "=" * 92)
    print("EXPOSURE — flagged players inside the BASELINE squad")
    print("=" * 92)
    av = availability_at_cutoff()
    out = {(int(c), int(e)) for c, e, o in
           zip(av.cutoff, av.element, av.is_out) if o}
    new = {(int(c), int(e)) for c, e, o in
           zip(av.cutoff, av.element, av.new_absence) if o}

    base = logs[(logs.arm == "baseline") & (logs.rep == 0)]
    rows = []
    for _, r in base.iterrows():
        gw = int(r.gw)
        els = list(r.elements)
        rows.append({
            "gw": gw,
            "in_squad_out": sum((gw, int(e)) in out for e in els),
            "in_squad_new_absence": sum((gw, int(e)) in new for e in els),
        })
    ex = pd.DataFrame(rows)
    print(f"squad-gameweeks holding a flagged-out player : {ex.in_squad_out.sum()} "
          f"of {15 * len(ex)} slots ({100 * ex.in_squad_out.sum() / (15 * len(ex)):.1f}%)")
    print(f"  of which a FIRST-gameweek absence          : {ex.in_squad_new_absence.sum()}")
    print(f"gameweeks with at least one flagged player   : {(ex.in_squad_out > 0).sum()} of {len(ex)}")
    print(f"  GW1-7                                      : "
          f"{ex[ex.gw <= 7].in_squad_out.sum()} slots, "
          f"{ex[ex.gw <= 7].in_squad_new_absence.sum()} of them new")
    print("\nper gameweek (non-zero only):")
    print(ex[ex.in_squad_out > 0].to_string(index=False))


def main():
    res, logs = load()
    res = res.drop_duplicates(["arm", "rep"]).sort_values(["arm", "rep"])

    print("=" * 92)
    print("SEASON TOTALS  (H=3, decay=0.3, balanced, bench_weight=0.2, baseline 1984)")
    print("=" * 92)
    first = res[res.rep == 0].set_index("arm")
    cols = ["total", "vs_baseline", "gw1_7", "gw1_7_per_gw", "gw8_plus_per_gw",
            "transfers", "hits", "rows_zeroed", "rows_scaled"]
    print(first[cols].to_string())

    reps = res.groupby("arm")["total"].agg(["nunique", "min", "max", "count"])
    unstable = reps[(reps["nunique"] > 1)]
    print(f"\ndeterminism: {len(unstable)} of {len(reps)} arms varied across repeats")
    if len(unstable):
        print(unstable.to_string())

    print("\n" + "=" * 92)
    print("PAIRED PER-GAMEWEEK BOOTSTRAP vs BASELINE")
    print("=" * 92)
    base = logs[(logs.arm == "baseline") & (logs.rep == 0)]["points"].values
    rows = []
    for arm in sorted(res.arm.unique()):
        if arm == "baseline":
            continue
        pts = logs[(logs.arm == arm) & (logs.rep == 0)]["points"].values
        if len(pts) != len(base):
            continue
        r = compare_strategies(pts, base, label="baseline")
        rows.append({
            "arm": arm,
            "margin": round(r["observed_margin"], 0),
            "ci_low": round(r["ci_low"], 0),
            "ci_high": round(r["ci_high"], 0),
            "excludes_0": r["ci_excludes_zero"],
            "loses_pct": round(100 * r["share_of_seasons_model_loses"], 1),
            "boot_sd": round(r["bootstrap_sd"], 1),
            "vs_path_sd": f"{r['observed_margin'] / PATH_SD:+.2f}x",
        })
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\npath-divergence sd at this config is ~{PATH_SD:.0f} points. The bootstrap "
          "above does\nnot sample it, so treat |margin| < that as not established.")

    exposure(logs)

    print("\n" + "=" * 92)
    print("PER-GAMEWEEK POINTS, BASELINE vs KEY ARMS")
    print("=" * 92)
    keep = [a for a in ("baseline", "zeros_all", "both", "u_only", "isn_only")
            if a in set(logs.arm)]
    wide = (logs[(logs.arm.isin(keep)) & (logs.rep == 0)]
            .pivot_table(index="gw", columns="arm", values="points"))
    wide = wide[[a for a in keep if a in wide.columns]]
    for a in wide.columns[1:]:
        wide[f"d_{a}"] = wide[a] - wide["baseline"]
    print(wide.head(10).to_string())
    print(f"\nGW1-7 deltas: " + ", ".join(
        f"{a}={wide[f'd_{a}'][:7].sum():+.0f}" for a in wide.columns[1:len(keep)]))


if __name__ == "__main__":
    main()
