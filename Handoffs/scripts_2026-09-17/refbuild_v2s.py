"""Sensitivity-row reference build (prereg v2 section 3: informational, never a re-choice).
Usage: refbuild_v2s.py <season> <label> <N> <tau0> <bound-or-none> [cutoffs...]
Writes ref_<label>_<tag>.parquet + ref_<label>_<tag>_fits.json to the scratchpad."""
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc                 # noqa: E402
import walkforward_season as wfs         # noqa: E402

season, label = sys.argv[1], sys.argv[2]
dc.SHRINK_N = int(sys.argv[3])
dc.SHRINK_TAU0 = float(sys.argv[4])
dc.ATK_DFC_BOUND = None if sys.argv[5].lower() == "none" else float(sys.argv[5])
cutoffs = [int(x) for x in sys.argv[6:]] or None
tag = season.replace("-", "_")
HERE = Path(__file__).resolve().parent
out = HERE / f"ref_{label}_{tag}.parquet"
fits = []
_orig = dc._fit_dc_decay


def wrapped(train, teams, ref, hl, **kw):
    x, idx, nt = _orig(train, teams, ref, hl, **kw)
    lf = dict(dc.LAST_FIT); lf["ref"] = str(ref); fits.append(lf)
    return x, idx, nt


dc._fit_dc_decay = wrapped
print(f"sensitivity build {label} {season}: N {dc.SHRINK_N} tau0 {dc.SHRINK_TAU0} bound {dc.ATK_DFC_BOUND} cutoffs {cutoffs or 'all'} -> {out.name}", flush=True)
wfs.walk_forward(season, cutoffs=cutoffs, horizon=6, save_path=str(out))
(HERE / f"ref_{label}_{tag}_fits.json").write_text(json.dumps(fits, indent=1, default=str), encoding="utf-8")
print("DONE", out.name, "fits logged:", len(fits), flush=True)
