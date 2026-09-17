"""v3 sensitivity-row build (informational): refbuild_v3s.py <season> <label> <mu_atk> <mu_dfc> [cutoffs...]"""
import json
import sys
from pathlib import Path

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc                 # noqa: E402
import walkforward_season as wfs         # noqa: E402

season, label = sys.argv[1], sys.argv[2]
dc.MU_PROMOTED_ATTACK = float(sys.argv[3])
dc.MU_PROMOTED_DEFENCE = float(sys.argv[4])
cutoffs = [int(x) for x in sys.argv[5:]] or None
tag = season.replace("-", "_")
HERE = Path(__file__).resolve().parent
out = HERE / f"ref_{label}_{tag}.parquet"
fits = []
_orig = dc._fit_dc_decay


def wrapped(train, teams, ref, hl, **kw):
    x, idx, nt = _orig(train, teams, ref, hl, **kw)
    lf = dict(dc.LAST_FIT)
    lf["ref"] = str(ref)
    fits.append(lf)
    return x, idx, nt


dc._fit_dc_decay = wrapped
print(f"sensitivity build {label} {season}: mu {dc.MU_PROMOTED_ATTACK}/{dc.MU_PROMOTED_DEFENCE} N {dc.SHRINK_N} "
      f"tau0 {dc.SHRINK_TAU0} cutoffs {cutoffs or 'all'} -> {out.name}", flush=True)
wfs.walk_forward(season, cutoffs=cutoffs, horizon=6, save_path=str(out))
(HERE / f"ref_{label}_{tag}_fits.json").write_text(json.dumps(fits, indent=1, default=str), encoding="utf-8")
print("DONE", out.name, "fits logged:", len(fits), flush=True)
