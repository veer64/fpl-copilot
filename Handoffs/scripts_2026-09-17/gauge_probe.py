"""What gauge does the record's fit sit in? On the real archive at a mid-season 2025-26 cutoff,
with the form OFF (SHRINK_N 0, no box): mean attack, mean defence, sum(atk) - sum(dfc)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc  # noqa: E402

dc.SHRINK_N = 0
dc.ATK_DFC_BOUND = None
m = dc._load_matches("2025-26")
if m is None:
    import inspect
    print([n for n, _ in inspect.getmembers(dc, inspect.isfunction)])
    sys.exit()
mc = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
for cutoff in ["2025-08-15", "2025-11-01", "2026-03-01"]:
    cut = pd.Timestamp(cutoff)
    train = mc[dc.knowable_before(mc, cut)]
    teams = sorted(set(train["home"]) | set(train["away"]))
    x, idx, nt = dc._fit_dc_decay(train, teams, cut, dc.HALF_LIFE_DAYS)
    atk, dfc = x[:nt], x[nt:2 * nt]
    print(f"{cutoff}: n_train {len(train)} nt {nt} conv {dc.LAST_FIT['converged']} mean_atk {atk.mean():+.4f} "
          f"mean_dfc {dfc.mean():+.4f} sum(atk)-sum(dfc) {atk.sum() - dfc.sum():+.2e} hadv {x[-2]:+.3f} "
          f"centred atk [{(atk - atk.mean()).min():+.3f}, {(atk - atk.mean()).max():+.3f}] "
          f"dfc [{(dfc - dfc.mean()).min():+.3f}, {(dfc - dfc.mean()).max():+.3f}]")
