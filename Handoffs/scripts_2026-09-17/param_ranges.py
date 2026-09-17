"""Design input for the revised threshold prereg: the fitted attack/defence parameter ranges on
the record (prior off, canonical names, knowable_before) at sample cutoffs of the three seasons and
the live season -- among clubs with n_eff >= 10 (would a plausibility box ever bind on them?) and
among clubs below 10 (the cold-start region). Read-only."""
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

assert dc.SHRINK_TAU == 0.0
stack = pd.read_parquet(season_stack.stack_path())
rows = []
for season in ["2023-24", "2024-25", "2025-26", "2026-27"]:
    m = dc._load_matches(season)
    mc = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
    cur = stack[stack["season"] == season]
    if len(cur) == 0:
        fwd = pd.read_parquet(season_stack.forward_path()); cur = fwd[fwd["season"] == season]
    kick = pd.to_datetime(cur["kickoff_time"])
    cutoffs = [2, 3, 5, 10, 20, 30, 38] if season != "2026-27" else [5]
    for k in cutoffs:
        c = kick[cur["GW"] == k].min()
        if pd.isna(c):
            continue
        cutoff = c.tz_localize(None)
        tr = mc[dc.knowable_before(mc, cutoff)]
        teams = sorted(set(tr["home"]) | set(tr["away"]))
        params, idx, nt = dc._fit_dc_decay(tr, teams, cutoff, dc.HALF_LIFE_DAYS)
        age = (cutoff - tr["date_parsed"]).dt.days.values
        w = np.exp(-(np.log(2) / dc.HALF_LIFE_DAYS) * age)
        neff = {t: float(w[((tr["home"] == t) | (tr["away"] == t)).values].sum()) for t in teams}
        season_clubs = set(mc[mc["season"] == season]["home"]) | set(mc[mc["season"] == season]["away"])
        atk = {t: params[idx[t]] for t in teams if t in season_clubs}
        dfc = {t: params[nt + idx[t]] for t in teams if t in season_clubs}
        rich = [t for t in atk if neff[t] >= 10]; poor = [t for t in atk if neff[t] < 10]
        r = dict(season=season, cutoff=k, converged=dc.LAST_FIT["converged"],
                 atk_rich_min=min(atk[t] for t in rich), atk_rich_max=max(atk[t] for t in rich),
                 dfc_rich_min=min(dfc[t] for t in rich), dfc_rich_max=max(dfc[t] for t in rich),
                 poor={t: (round(neff[t], 1), round(atk[t], 2), round(dfc[t], 2)) for t in poor})
        rows.append(r)
        print(f"{season} cutoff {k:2d} conv={r['converged']} | rich (n_eff>=10, {len(rich)} clubs): attack [{r['atk_rich_min']:+.2f}, {r['atk_rich_max']:+.2f}] "
              f"defence [{r['dfc_rich_min']:+.2f}, {r['dfc_rich_max']:+.2f}] | poor: {r['poor']}")
df = pd.DataFrame(rows)
print("\nOVERALL among clubs with n_eff >= 10: attack in [%.2f, %.2f], defence in [%.2f, %.2f]" % (
    df["atk_rich_min"].min(), df["atk_rich_max"].max(), df["dfc_rich_min"].min(), df["dfc_rich_max"].max()))
print("multipliers: attack e^min %.2fx .. e^max %.2fx; defence e^min %.2fx .. e^max %.2fx" % (
    np.exp(df["atk_rich_min"].min()), np.exp(df["atk_rich_max"].max()), np.exp(df["dfc_rich_min"].min()), np.exp(df["dfc_rich_max"].max())))
