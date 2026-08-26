#!/usr/bin/env python
"""Build the bonus-rebuild arms (Logs/bonus_rebuild_prereg.md section 6).

    uv run python eval/run_bonus_rebuild.py --season 2024-25 --arm bonusow    # outcome-weighted, gate in-process
    uv run python eval/run_bonus_rebuild.py --season 2024-25 --arm bonusdel   # canonical with exp_bonus := 0 (no rebuild)
    uv run python eval/run_bonus_rebuild.py --season 2024-25 --check          # incumbent mode, one cutoff, bit-exact

Canonicals are never written. assembly.BONUS_MODE rests "incumbent"; the
outcome build flips it in-process and restores it. Every row is stamped.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad")); sys.path.insert(0, str(REPO / "eval"))
import assembly  # noqa: E402
import walkforward_season as wfs  # noqa: E402

CMP = ["e_points", "e_goals", "e_assists", "pts_goals", "e_points_core", "exp_bonus", "pred_bps"]


def build_outcome(season):
    tag = season.replace("-", "_")
    out = REPO / "data" / f"walkforward_h6_{tag}_bonusow.parquet"
    if out.exists():
        print(f"exists, skipping: {out}"); return
    old = assembly.BONUS_MODE
    assembly.BONUS_MODE = "outcome"
    tmp = out.with_suffix(".tmp.parquet")
    try:
        assert not assembly.PENALTY_FIX_ACTIVE and not assembly.TOPEND_CAL_ACTIVE
        res = wfs.walk_forward(season, horizon=6, save_path=str(tmp))
        assert res["bonus_mode"].iloc[0] == "outcome"
    finally:
        assembly.BONUS_MODE = old
    tmp.replace(out); print(f"Saved -> {out}")


def build_delete(season):
    """DELETE arm = canonical with the bonus term removed. e_points = e_points_core
    holds exactly on the canonical file, so this is bit-exactly what
    BONUS_MODE='delete' would build, without a rebuild."""
    tag = season.replace("-", "_")
    out = REPO / "data" / f"walkforward_h6_{tag}_bonusdel.parquet"
    if out.exists():
        print(f"exists, skipping: {out}"); return
    c = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    assert np.allclose(c["e_points"], c["e_points_core"] + c["exp_bonus"]), "identity e_points = core + bonus broken"
    c["e_points"] = c["e_points_core"]; c["exp_bonus"] = 0.0; c["bonus_mode"] = "delete"
    tmp = out.with_suffix(".tmp.parquet"); c.to_parquet(tmp, index=False); tmp.replace(out)
    print(f"Saved -> {out} (delete arm, {len(c)} rows)")


def check(season, cutoff):
    tag = season.replace("-", "_")
    canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    assert assembly.BONUS_MODE == "incumbent"
    res = wfs.walk_forward(season, cutoffs=[cutoff], horizon=6, verbose=False)
    c = canon[canon["cutoff"] == cutoff]; key = ["element", "gw"]
    j = c[key + CMP].merge(res[key + CMP], on=key, suffixes=("_c", "_n"), how="outer", indicator=True)
    assert (j["_merge"] == "both").all()
    worst = {k: float(np.nanmax(np.abs(j[f"{k}_c"] - j[f"{k}_n"]))) for k in CMP}
    print(f"{season} cutoff {cutoff}: rows {len(j)}; max |diff|: {worst}")
    assert max(worst.values()) == 0.0
    print("INCUMBENT-MODE REPRODUCTION: PASS (bit-exact)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", required=True); ap.add_argument("--arm", choices=["bonusow", "bonusdel"])
    ap.add_argument("--check", action="store_true"); ap.add_argument("--cutoff", type=int, default=20)
    a = ap.parse_args()
    if a.check:
        check(a.season, a.cutoff)
    elif a.arm == "bonusow":
        build_outcome(a.season)
    elif a.arm == "bonusdel":
        build_delete(a.season)
    else:
        ap.error("--arm or --check required")


if __name__ == "__main__":
    main()
