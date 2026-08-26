#!/usr/bin/env python
"""Build the penalty-fix walk-forward arms (Logs/penalty_fix_prereg.md section 5).

    uv run python eval/run_penalty_fix.py --season 2024-25          # _penfix build, gate flipped in-process
    uv run python eval/run_penalty_fix.py --season 2024-25 --check  # gate OFF, one cutoff, bit-exact vs canonical

NOTE (2026-08-27, same-season leak fix): the Understat penalty join now reads the
PRIOR season in both gate states (assembly._penalty_join_year). --check therefore
FAILS against any canonical built before 2026-08-27 (max |diff| on penalty_share
/ e_pen_goals / e_goals / pts_goals / e_points_core / e_points / pred_bps; ~0.03
e_points, 2024-25 cutoff 20) and passes only against a post-fix rebuild. No
reproduction mode for the leaked join remains -- by design.

The canonical files are never written. The gate rests False on disk; this
script flips assembly.PENALTY_FIX_ACTIVE in-process (the run_chip_study
pattern) and restores it in `finally`. Output stamps `penalty_fix_active=True`.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import assembly  # noqa: E402
import walkforward_season as wfs  # noqa: E402

CMP = ["e_points", "e_goals", "pts_goals", "e_points_core", "exp_bonus",
       "p_start", "e_minutes", "penalty_share", "team_pen_rate"]


def build(season):
    tag = season.replace("-", "_")
    out = REPO / "data" / f"walkforward_h6_{tag}_penfix.parquet"
    if out.exists():
        print(f"exists, skipping: {out}")
        return
    tmp = out.with_suffix(".tmp.parquet")
    old = assembly.PENALTY_FIX_ACTIVE
    assembly.PENALTY_FIX_ACTIVE = True
    try:
        res = wfs.walk_forward(season, horizon=6, save_path=str(tmp))
        assert bool(res["penalty_fix_active"].iloc[0]) is True
    finally:
        assembly.PENALTY_FIX_ACTIVE = old
    tmp.replace(out)
    print(f"Saved -> {out}")


def check(season, cutoff):
    """Gate OFF, one cutoff: must reproduce the canonical rows bit-exactly."""
    tag = season.replace("-", "_")
    canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    assert assembly.PENALTY_FIX_ACTIVE is False
    res = wfs.walk_forward(season, cutoffs=[cutoff], horizon=6, verbose=False)
    c = canon[canon["cutoff"] == cutoff]
    key = ["element", "gw"]
    j = c[key + CMP].merge(res[key + CMP], on=key, suffixes=("_c", "_n"), how="outer",
                           indicator=True)
    assert (j["_merge"] == "both").all(), j["_merge"].value_counts()
    worst = {k: float(np.nanmax(np.abs(j[f"{k}_c"] - j[f"{k}_n"]))) for k in CMP}
    print(f"{season} cutoff {cutoff}: rows {len(j)}; max |diff| per column: {worst}")
    assert max(worst.values()) == 0.0, ("gate-off rebuild differs from canonical -- expected if the canonical "
        "predates the 2026-08-27 penalty-join leak fix (see module docstring)")
    print("GATE-OFF REPRODUCTION: PASS (bit-exact)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cutoff", type=int, default=20)
    a = ap.parse_args()
    if a.check:
        check(a.season, a.cutoff)
    else:
        build(a.season)


if __name__ == "__main__":
    main()
