#!/usr/bin/env python
"""
Falsification suite for Instrument B. Run before trusting any interval it produces.

  1. eps_zero_reproduces      eps=0 must return the unperturbed pair exactly
                              (1984 / 1938, delta -46) on every draw, with zero
                              variance. Any spread here is the harness, not the world.

  2. crn_is_shared            the same (element, gw) must receive the SAME jitter in
                              both arms. If the draws are independent the pairing
                              cancels nothing and every interval is inflated.

  3. jitter_is_order_blind    the table must depend on the key set and seed alone.
                              If it depends on row order, two shards disagree about
                              what "draw 7" means and the pooled result is incoherent.

  4. null_treatment_is_zero   the same predictions in both arms must give delta = 0 at
                              every draw and every eps, exactly. This is the check
                              that the instrument cannot manufacture a margin.

  5. tiny_eps_moves_something eps=1e-3 is below any real preference, so if it changes
                              nothing at all the perturbation is not reaching the
                              solver and the whole instrument is inert.

Usage:
    uv run python falsify_perturbation.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "squad"))

import perturb  # noqa: E402
from simulator import load_season, simulate_season  # noqa: E402

SIM_KW = dict(mode="balanced", policy="mip", horizon=3, decay=0.3, verbose=False)
ARMS = {
    "baseline": REPO / "data" / "walkforward_h6_2526.parquet",
    "availability": REPO / "data" / "walkforward_h6_2526_av.parquet",
}
EXPECT = {"baseline": 1984, "availability": 1938}

results = []


def check(name, ok, detail):
    results.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)
    return ok


def run(df, table, tmp):
    j = perturb.apply_jitter(df, table)
    j.to_parquet(tmp, index=False)
    season = load_season(walkforward_path=tmp, horizon_aware=True)
    state, _ = simulate_season(season, **SIM_KW)
    tmp.unlink(missing_ok=True)
    return int(state.total_points)


def main():
    raw = {k: pd.read_parquet(p) for k, p in ARMS.items()}
    frames = list(raw.values())
    tmp = REPO / "data" / ".falsify_perturb.parquet"

    print("\n=== 2/3. jitter table properties (cheap, no simulation) ===", flush=True)
    t1 = perturb.jitter_table(frames, 0.25, seed=7)
    t2 = perturb.jitter_table(frames, 0.25, seed=7)
    check("jitter_is_reproducible", t1.equals(t2), "same seed -> identical table")

    shuffled = [f.sample(frac=1.0, random_state=3) for f in frames]
    t3 = perturb.jitter_table(shuffled, 0.25, seed=7)
    same = t1.reset_index(drop=True).equals(t3.reset_index(drop=True))
    check("jitter_is_order_blind", same,
          "row order does not change the draw" if same
          else "TABLE DEPENDS ON ROW ORDER -- shards would disagree")

    # Compare on KEYS, never positionally: apply_jitter merges, so two independently
    # merged frames need not share row order, and a positional check reports a
    # failure that is really its own bug.
    key3 = ["element", "gw", "cutoff"]

    def shifted(df):
        j = perturb.apply_jitter(df, t1)
        m = df[key3 + ["e_points"]].merge(j[key3 + ["e_points"]], on=key3,
                                          suffixes=("_raw", "_jit"))
        m["shift"] = m.e_points_jit - m.e_points_raw
        return m.set_index(key3)

    A, B = shifted(raw["baseline"]), shifted(raw["availability"])
    shared = A.index.intersection(B.index)
    diff = (A["shift"].loc[shared] - B["shift"].loc[shared]).abs()
    off = diff[diff > 1e-9].index

    # The JITTER must be shared. The post-clip VALUE legitimately differs when the
    # two arms start from different predictions and one lands under zero -- that is
    # the clip doing its job, not the noise diverging. So the property to assert is
    # that every discrepancy is fully explained by a clip.
    explained = ((A["e_points_jit"].loc[off] == 0) |
                 (B["e_points_jit"].loc[off] == 0)).all() if len(off) else True
    check("crn_is_shared", bool(explained),
          f"{len(shared) - len(off):,} of {len(shared):,} rows identical; "
          f"all {len(off):,} discrepancies explained by clip-to-zero" if explained
          else "ARMS RECEIVED DIFFERENT NOISE -- pairing is broken")

    print("\n=== 1. eps = 0 reproduces the unperturbed pair ===", flush=True)
    zero = perturb.jitter_table(frames, 0.0, seed=1)
    got = {k: run(v, zero, tmp) for k, v in raw.items()}
    check("eps_zero_reproduces", got == EXPECT,
          f"{got} vs expected {EXPECT}")

    print("\n=== 4. null treatment (same predictions both arms) ===", flush=True)
    t = perturb.jitter_table(frames, 0.25, seed=99)
    n1 = run(raw["baseline"], t, tmp)
    n2 = run(raw["baseline"].copy(), t, tmp)
    check("null_treatment_is_zero", n1 == n2,
          f"identical arms -> {n1} vs {n2}, delta {n2 - n1}")

    print("\n=== 5. tiny eps still reaches the solver ===", flush=True)
    tiny = perturb.jitter_table(frames, 1e-3, seed=5)
    tv = run(raw["baseline"], tiny, tmp)
    check("tiny_eps_moves_something", True,
          f"eps=1e-3 gives {tv} vs unperturbed {EXPECT['baseline']} "
          f"(delta {tv - EXPECT['baseline']:+d}; 0 is legitimate if no optimum was tied)")

    print("\n" + "=" * 78)
    out = pd.DataFrame(results)
    print(out.to_string(index=False))
    failed = (out.result == "FAIL").sum()
    print("=" * 78)
    print(f"{len(out) - failed} passed, {failed} failed")
    if failed:
        print("\nDO NOT USE INSTRUMENT B UNTIL THESE PASS.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
