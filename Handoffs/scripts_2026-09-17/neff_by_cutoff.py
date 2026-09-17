"""Design input for the threshold-form prereg: the decay-weighted evidence n_eff (sum of the fit's
weights over a club's training matches, half-life 365 d, ref = the cutoff's first kickoff) per club
per cutoff, for the three record seasons and the live one. Read-only. Prints, per season: the
minimum n_eff among clubs WITH prior-season archive rows at cutoffs 1/2/3/5/10, and the n_eff of
clubs WITHOUT prior rows (the promoted, no-history clubs) at cutoffs 1..14."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc            # noqa: E402
import season_stack                 # noqa: E402

HL = dc.HALF_LIFE_DAYS
stack = pd.read_parquet(season_stack.stack_path())
for season in ["2023-24", "2024-25", "2025-26", "2026-27"]:
    try:
        m = dc._load_matches(season)
    except FileNotFoundError:
        continue
    m = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
    cur = stack[stack["season"] == season]
    if len(cur) == 0:
        fwd = pd.read_parquet(season_stack.forward_path()); cur = fwd[fwd["season"] == season]
    kick = pd.to_datetime(cur["kickoff_time"])
    gws = sorted(int(g) for g in cur["GW"].unique())
    hist_clubs = set(m[m["season"] < season]["home"]) | set(m[m["season"] < season]["away"])
    clubs = sorted(set(m[m["season"] == season]["home"]) | set(m[m["season"] == season]["away"]))
    new = [c for c in clubs if c not in hist_clubs]
    est_min, new_rows = {}, {c: {} for c in new}
    for k in gws:
        if k > 14 and k not in (20, 30, 38):
            continue
        cutoff = kick[cur["GW"] == k].min()
        if pd.isna(cutoff):
            continue
        cutoff = cutoff.tz_localize(None)
        tr = m[dc.knowable_before(m, cutoff)]
        age = (cutoff - tr["date_parsed"]).dt.days.values
        w = np.exp(-(np.log(2) / HL) * age)
        neff = {}
        for c in clubs:
            sel = ((tr["home"] == c) | (tr["away"] == c)).values
            neff[c] = float(w[sel].sum())
        est = {c: v for c, v in neff.items() if c in hist_clubs}
        if est:
            cmin = min(est, key=est.get)
            est_min[k] = (round(est[cmin], 1), cmin)
        for c in new:
            new_rows[c][k] = round(neff[c], 1)
    print(f"\n{season}: clubs {len(clubs)}, without prior rows: {new}")
    print("  min n_eff among clubs WITH history, by cutoff:", {k: v for k, v in est_min.items() if k in (1, 2, 3, 5, 10, 20, 30, 38)})
    for c in new:
        print(f"  {c}: n_eff by cutoff {new_rows[c]}")
