"""The promoted-club centre, measured from the archive (design input for prereg v3, computed before any
endpoint number). For every season S with a prior season in the archive, the promoted cohort = clubs in S's
fixtures that were not in S-1's. Their first-season strength = the plain MLE fit (prior OFF, box OFF, the
record's optimiser, half-life 365 d, canonical names) at a cutoff AFTER S's last match, centred over S's
20 clubs: atk_i - mean(atk), dfc_i - mean(dfc). Also at cutoff GW20 (mid-season, informational), and each
club's evidence at S's first kickoff (n_eff) and years since it was last in the archive's league."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc  # noqa: E402

assert getattr(dc, "SHRINK_K", 0) == 0 and not hasattr(dc, "SHRINK_N"), "run on main (plain fit)"
m = dc._load_matches("2025-26")
mc = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
seasons = sorted(mc["season"].unique())
clubs_by_season = {s: sorted(set(mc.loc[mc.season == s, "home"]) | set(mc.loc[mc.season == s, "away"])) for s in seasons}
teams_all = sorted(set(mc["home"]) | set(mc["away"]))
HL = dc.HALF_LIFE_DAYS
rows = []
for i, s in enumerate(seasons[1:], start=1):
    prev = seasons[i - 1]
    league = clubs_by_season[s]
    promoted = [c for c in league if c not in clubs_by_season[prev]]
    cur = mc[mc.season == s].sort_values("date_parsed")
    last = cur["date_parsed"].max() + pd.Timedelta(days=1)
    first = cur["date_parsed"].min()
    # mid-season cutoff: the date of the 190th match of the season (approx GW20 start)
    mid = cur["date_parsed"].iloc[min(189, len(cur) - 1)]
    fits = {}
    for label, cut in (("end", last), ("mid", mid)):
        train = mc[dc.knowable_before(mc, cut)]
        x, idx, nt = dc._fit_dc_decay(train, teams_all, cut, HL)
        pri = [idx[t] for t in league]
        a_bar, d_bar = x[pri].mean(), x[nt + np.array(pri)].mean()
        fits[label] = (x, idx, nt, a_bar, d_bar, dc.LAST_FIT["converged"])
    # evidence at the first kickoff, and years since last seen
    train0 = mc[dc.knowable_before(mc, first)]
    w0 = np.exp(-(np.log(2) / HL) * (first - train0["date_parsed"]).dt.days.values)
    for c in promoted:
        n_eff0 = float(w0[(train0["home"] == c).values].sum() + w0[(train0["away"] == c).values].sum())
        seen = [t for t in seasons[:i] if c in clubs_by_season[t]]
        gap = (int(s[:4]) - int(seen[-1][:4])) if seen else None
        r = dict(season=s, club=c, n_eff_at_kickoff=round(n_eff0, 1), years_since_last=gap)
        for label in ("end", "mid"):
            x, idx, nt, a_bar, d_bar, conv = fits[label]
            r[f"atk_{label}"] = round(float(x[idx[c]] - a_bar), 3)
            r[f"dfc_{label}"] = round(float(x[nt + idx[c]] - d_bar), 3)
            r[f"conv_{label}"] = conv
        # the club's finish: points and goal difference in S, for the reader
        h = cur[cur.home == c]; a = cur[cur.away == c]
        gf = h.home_goals.sum() + a.away_goals.sum(); ga = h.away_goals.sum() + a.home_goals.sum()
        r["gf"] = int(gf); r["ga"] = int(ga)
        rows.append(r)
d = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(d.to_string(index=False))
print()
for label in ("end", "mid"):
    a, f = d[f"atk_{label}"], d[f"dfc_{label}"]
    print(f"[{label}] cohorts {d.season.nunique()} clubs {len(d)}: attack mean {a.mean():+.3f} (sd {a.std(ddof=1):.3f}, se {a.std(ddof=1)/np.sqrt(len(a)):.3f}, "
          f"median {a.median():+.3f}, range [{a.min():+.2f}, {a.max():+.2f}]) | defence mean {f.mean():+.3f} (sd {f.std(ddof=1):.3f}, "
          f"se {f.std(ddof=1)/np.sqrt(len(f)):.3f}, median {f.median():+.3f}, range [{f.min():+.2f}, {f.max():+.2f}]) | multipliers {np.exp(a.mean()):.2f}x / {np.exp(f.mean()):.2f}x")
    print(f"   per-cohort attack means: " + ", ".join(f"{s} {g[f'atk_{label}'].mean():+.2f}" for s, g in d.groupby('season')))
    print(f"   per-cohort defence means: " + ", ".join(f"{s} {g[f'dfc_{label}'].mean():+.2f}" for s, g in d.groupby('season')))
    lo = d[d.n_eff_at_kickoff < 10]; hi = d[d.n_eff_at_kickoff >= 10]
    print(f"   no usable history (n_eff < 10 at kickoff, n={len(lo)}): attack {lo[f'atk_{label}'].mean():+.3f} defence {lo[f'dfc_{label}'].mean():+.3f} | "
          f"returners (n_eff >= 10, n={len(hi)}): attack {hi[f'atk_{label}'].mean():+.3f} defence {hi[f'dfc_{label}'].mean():+.3f}")
    print(f"   attack v defence: paired mean difference (atk + dfc) {float((a + f).mean()):+.3f}; corr {np.corrcoef(a, f)[0, 1]:+.2f}")
d.to_csv(Path(__file__).resolve().parent / "promoted_centre.csv", index=False)
