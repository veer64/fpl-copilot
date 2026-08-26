#!/usr/bin/env python
"""Build the top-end calibration walk-forward arms (Logs/topend_calibration_prereg.md section 5).

    uv run python eval/run_topend_cal.py --season 2024-25 --arm cal            # calibration on, penalty off
    uv run python eval/run_topend_cal.py --season 2024-25 --arm cal_penfix     # both on
    uv run python eval/run_topend_cal.py --season 2024-25 --check              # gates OFF, one cutoff, bit-exact

Gamma is read from the LAST '## PRE-REGISTERED VALUE' section of the prereg
log ('GAMMA = x'). 2025-26 REFUSES to build unless that line exists (the
k = 8 / props guard). Gates are flipped in-process and restored; canonicals
are never written; every row is stamped.
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad")); sys.path.insert(0, str(REPO / "eval"))
import assembly  # noqa: E402
import walkforward_season as wfs  # noqa: E402

PREREG = REPO / "Logs" / "topend_calibration_prereg.md"
CMP = ["e_points", "e_goals", "e_assists", "pts_goals", "e_points_core", "exp_bonus", "fixture_scale"]


def registered_gamma():
    txt = PREREG.read_text(encoding="utf-8")
    secs = txt.split("## PRE-REGISTERED VALUE")
    if len(secs) < 2:
        return None
    m = re.search(r"GAMMA\s*=\s*([0-9.]+)", secs[-1])
    return float(m.group(1)) if m else None


def build(season, arm, gamma_override=None):
    tag = season.replace("-", "_")
    out = REPO / "data" / f"walkforward_h6_{tag}_{arm}.parquet"
    if out.exists():
        print(f"exists, skipping: {out}"); return
    g = registered_gamma() if gamma_override is None else gamma_override
    if season == "2025-26" and registered_gamma() is None:
        raise SystemExit("REFUSED: 2025-26 is sealed until 'GAMMA = ...' is written into a "
                         "'## PRE-REGISTERED VALUE' section of Logs/topend_calibration_prereg.md")
    if g is None:
        raise SystemExit("no gamma: pass --gamma for tuning-season builds or pre-register the value")
    old = (assembly.TOPEND_CAL_ACTIVE, assembly.FIXTURE_SCALE_GAMMA, assembly.PENALTY_FIX_ACTIVE)
    assembly.TOPEND_CAL_ACTIVE = True; assembly.FIXTURE_SCALE_GAMMA = float(g)
    assembly.PENALTY_FIX_ACTIVE = (arm == "cal_penfix")
    tmp = out.with_suffix(".tmp.parquet")
    try:
        res = wfs.walk_forward(season, horizon=6, save_path=str(tmp))
        assert bool(res["topend_cal_active"].iloc[0]) and float(res["fixture_scale_gamma"].iloc[0]) == float(g)
        assert bool(res["penalty_fix_active"].iloc[0]) == (arm == "cal_penfix")
    finally:
        assembly.TOPEND_CAL_ACTIVE, assembly.FIXTURE_SCALE_GAMMA, assembly.PENALTY_FIX_ACTIVE = old
    tmp.replace(out); print(f"Saved -> {out}  (gamma {g}, arm {arm})")


def check(season, cutoff):
    tag = season.replace("-", "_")
    canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    assert not assembly.TOPEND_CAL_ACTIVE and not assembly.PENALTY_FIX_ACTIVE
    res = wfs.walk_forward(season, cutoffs=[cutoff], horizon=6, verbose=False)
    c = canon[canon["cutoff"] == cutoff]; key = ["element", "gw"]
    j = c[key + CMP].merge(res[key + CMP], on=key, suffixes=("_c", "_n"), how="outer", indicator=True)
    assert (j["_merge"] == "both").all()
    worst = {k: float(np.nanmax(np.abs(j[f"{k}_c"] - j[f"{k}_n"]))) for k in CMP}
    print(f"{season} cutoff {cutoff}: rows {len(j)}; max |diff|: {worst}")
    assert max(worst.values()) == 0.0
    print("GATE-OFF REPRODUCTION: PASS (bit-exact)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", required=True); ap.add_argument("--arm", choices=["cal", "cal_penfix"])
    ap.add_argument("--check", action="store_true"); ap.add_argument("--cutoff", type=int, default=20)
    ap.add_argument("--gamma", type=float, default=None, help="tuning-season builds only; refused for 2025-26")
    a = ap.parse_args()
    if a.check:
        check(a.season, a.cutoff)
    else:
        if a.season == "2025-26" and a.gamma is not None:
            raise SystemExit("REFUSED: --gamma override is not allowed for the sealed season")
        build(a.season, a.arm, a.gamma)


if __name__ == "__main__":
    main()
