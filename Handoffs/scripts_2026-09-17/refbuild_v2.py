"""Reference build of one season's canonical with the v2 form (the code as it stands), written to
the scratchpad, plus a per-cutoff log of LAST_FIT (converged, clubs below N, at_bound) and the
fitted parameters' margins to the box, captured by wrapping the fit. Usage: refbuild_v2.py <season>"""
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

season = sys.argv[1]
tag = season.replace("-", "_")
HERE = Path(__file__).resolve().parent
import os
PREFIX = os.environ.get("REF_PREFIX", "ref_v2")
out = HERE / f"{PREFIX}_{tag}.parquet"
fits = []
_orig = dc._fit_dc_decay


def wrapped(train, teams, ref, hl, **kw):
    x, idx, nt = _orig(train, teams, ref, hl, **kw)
    lf = dict(dc.LAST_FIT)
    B = dc.ATK_DFC_BOUND
    lf["ref"] = str(ref)
    fits.append(lf)
    return x, idx, nt


dc._fit_dc_decay = wrapped
print(f"reference build {PREFIX} {season}: tau0 {dc.SHRINK_TAU0} N {dc.SHRINK_N} bound {dc.ATK_DFC_BOUND:.4f} mu {getattr(dc, 'MU_PROMOTED_ATTACK', None)}/{getattr(dc, 'MU_PROMOTED_DEFENCE', None)} -> {out.name}", flush=True)
wfs.walk_forward(season, cutoffs=None, horizon=6, save_path=str(out))
(HERE / f"{PREFIX}_{tag}_fits.json").write_text(json.dumps(fits, indent=1, default=str), encoding="utf-8")
print("DONE", out.name, "fits logged:", len(fits), flush=True)
