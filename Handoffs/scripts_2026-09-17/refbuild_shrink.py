"""Reference build of one season's canonical with the code as it stands (the prior in),
written to the scratchpad, NOT to data/. Optional: k override (in-process, exploratory,
labelled) and a cutoff subset. Usage: refbuild_shrink.py <season> [k] [cutoffs...]"""
import sys
from pathlib import Path

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc                 # noqa: E402
import walkforward_season as wfs         # noqa: E402

season = sys.argv[1]
k = int(sys.argv[2]) if len(sys.argv) > 2 else dc.SHRINK_K
cutoffs = [int(x) for x in sys.argv[3:]] or None
if k != dc.SHRINK_K:
    dc.SHRINK_K = k
    dc.SHRINK_TAU = 1.40 * k             # exploratory sensitivity row only
out = Path(__file__).resolve().parent / f"ref_shrink_k{k}_{season.replace('-', '_')}.parquet"
print(f"reference build {season} k={k} tau={dc.SHRINK_TAU} cutoffs={cutoffs or 'all'} -> {out.name}", flush=True)
wfs.walk_forward(season, cutoffs=cutoffs, horizon=6, save_path=str(out))
print("DONE", out.name, flush=True)
