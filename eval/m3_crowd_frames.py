"""M3 B1 -- walk-forward frames with the crowd block ON, as NEW files, and the gate-OFF rebuild that must
reproduce the frame of record. PROBE DRIVER: it flips minutes.CROWD_FEATURES_ACTIVE in-process only, writes
under data/arms_crowd/ only and never writes over a file.

    build   --mode crowd    the season's frame through eval/walkforward_season.walk_forward (the harness of
                            record, unchanged) with the gate ON in the given form
                            -> data/arms_crowd/walkforward_h6_{tag}_crowd.parquet
            --mode flagoff  the same call with the gate OFF -> data/arms_crowd/walkforward_h6_{tag}_flagoff.parquet
    compare                 the gate-off rebuild against the frame of record, column by column: the exactness
                            check (same rows, same columns, same dtypes, max |diff| 0)

Usage:
    uv run python eval/m3_crowd_frames.py build --season 2025-26 --mode crowd --form rank
    uv run python eval/m3_crowd_frames.py build --season 2025-26 --mode flagoff
    uv run python eval/m3_crowd_frames.py compare --season 2025-26
"""
import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

OUT = REPO / "data" / "arms_crowd"
H = 6


def out_path(season, mode):
    return OUT / f"walkforward_h{H}_{season.replace('-', '_')}_{mode}.parquet"


def record_path(season):
    return REPO / "data" / f"walkforward_h{H}_{season.replace('-', '_')}.parquet"


def cmd_build(a):
    out = out_path(a.season, a.mode + getattr(a, "suffix", ""))
    if out.exists():
        raise FileExistsError(f"{out} exists -- a frame is never written over")
    import minutes as mm
    import walkforward_season as wfs
    OUT.mkdir(parents=True, exist_ok=True)
    assert mm.CROWD_FEATURES_ACTIVE is False, "the gate must rest off"
    if a.mode == "crowd":
        mm.CROWD_FEATURES_ACTIVE, mm.CROWD_FORM = True, a.form
    print(f"{a.season} [{a.mode}]: crowd gate {mm.CROWD_FEATURES_ACTIVE}" + (f", form {mm.CROWD_FORM}" if mm.CROWD_FEATURES_ACTIVE else ""), flush=True)
    try:
        tmp = out.with_suffix(".tmp.parquet")
        res = wfs.walk_forward(a.season, horizon=H, save_path=str(tmp))
    finally:
        mm.CROWD_FEATURES_ACTIVE = False
    if a.mode == "crowd":
        assert bool(res["crowd_features_active"].all()) and (res["crowd_form"] == a.form).all(), "a crowd frame must be stamped"
    else:
        assert "crowd_features_active" not in res.columns, "a gate-off frame carries no crowd stamp"
    tmp.replace(out)
    print(f"rows {len(res):,}, columns {len(res.columns)} -> {out}")


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def frame_diff(a, b):
    """(max |diff| over numeric columns, numeric columns differing, non-numeric columns differing, NaN mismatches)."""
    worst, num_bad, obj_bad, nan_mm = 0.0, [], [], 0
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_numeric_dtype(x) and not pd.api.types.is_bool_dtype(x):
            xv, yv = x.to_numpy(float), y.to_numpy(float)
            mm_ = int((np.isnan(xv) != np.isnan(yv)).sum())
            d = np.abs(np.where(np.isnan(xv) | np.isnan(yv), 0.0, xv - yv))
            m = float(d.max()) if len(d) else 0.0
            worst, nan_mm = max(worst, m), nan_mm + mm_
            if m > 0 or mm_:
                num_bad.append(c)
        elif not (x.astype(str).to_numpy() == y.astype(str).to_numpy()).all():
            obj_bad.append(c)
    return worst, num_bad, obj_bad, nan_mm


def cmd_compare(a):
    rec_p, off_p = record_path(a.season), out_path(a.season, "flagoff" + a.suffix)
    rec, off = pd.read_parquet(rec_p), pd.read_parquet(off_p)
    same_shape = rec.shape == off.shape
    same_cols = list(rec.columns) == list(off.columns)
    same_dtypes = same_cols and [str(t) for t in rec.dtypes] == [str(t) for t in off.dtypes]
    key = ["cutoff", "gw", "element"]
    same_rows = same_shape and (rec[key].to_numpy() == off[key].to_numpy()).all()
    worst, num_bad, obj_bad, nan_mm = frame_diff(rec, off) if (same_rows and same_cols) else (float("nan"), ["?"], ["?"], -1)
    els = sorted(int(e) for e in rec["element"].unique())
    ok = bool(same_shape and same_cols and same_dtypes and same_rows and worst == 0.0 and not num_bad and not obj_bad and nan_mm == 0)
    print(f"[{a.season}] gate-off rebuild {off_p.name} vs the frame of record {rec_p.name}: rows {len(off):,} / {len(rec):,}; columns {len(off.columns)} / {len(rec.columns)} "
          f"(same names and order: {same_cols}; same dtypes: {same_dtypes}); same (cutoff, gw, element) rows in the same order: {bool(same_rows)}; "
          f"element ids count {len(els)} first {els[0]} last {els[-1]}; max |diff| over every numeric column {worst:.3e}; numeric columns differing {num_bad}; "
          f"other columns differing {obj_bad}; NaN on one side only {nan_mm}; file sha256 equal: {_sha(rec_p) == _sha(off_p)}")
    print(f"[{a.season}] EXACTNESS (gate off reproduces the frame of record, max |diff| 0): {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--season", required=True)
    b.add_argument("--mode", required=True, choices=["crowd", "flagoff"])
    b.add_argument("--form", default=None, choices=["rank", "raw"])
    b.add_argument("--suffix", default="", help="appended to the output name (a second attempt gets its own file)")
    c = sub.add_parser("compare")
    c.add_argument("--season", required=True)
    c.add_argument("--suffix", default="", help="compare the gate-off rebuild written with this suffix")
    a = ap.parse_args()
    if a.cmd == "build" and a.mode == "crowd" and a.form is None:
        ap.error("--mode crowd needs --form")
    {"build": cmd_build, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
