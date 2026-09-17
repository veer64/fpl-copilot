"""Investigate the gate-(d) tell: step-0 p_cs moved on fixtures with no affected club. Where (cutoff,
fixture), how much, and WHY: refit that cutoff with the form on and off and diff the shared parameters
(home advantage, rho) and every club's centred parameters."""
import json
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

HERE = Path(__file__).resolve().parent
TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs", "Sheffield United": "Sheffield Utd"}
season = sys.argv[1] if len(sys.argv) > 1 else "2023-24"
tag = season.replace("-", "_")
ref = pd.read_parquet(HERE / f"ref_v2_{tag}.parquet")
rec = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
fits = json.loads((HERE / f"ref_v2_{tag}_fits.json").read_text(encoding="utf-8"))
cutoffs = sorted(ref["cutoff"].unique())
fit_by_cut = dict(zip(cutoffs, fits))
affected = {k: sorted(TEAM_MAP.get(c, c) for c in (set(f.get("clubs_below_n") or {}) | set(f.get("at_bound") or {})))
            for k, f in fit_by_cut.items() if (f.get("clubs_below_n") or f.get("at_bound"))}

key = ["cutoff", "gw", "element"]
rec0 = rec[rec["horizon_step"] == 0]; ref0 = ref[ref["horizon_step"] == 0]
opp = {}
for (k, g), grp in rec0[rec0["n_fixtures"] == 1].groupby(["cutoff", "gw"]):
    t = grp.groupby("team")[["team_lambda", "opp_lambda"]].first()
    by_pair = {(row.team_lambda, row.opp_lambda): team for team, row in t.iterrows()}
    for team, row in t.iterrows():
        opp[(k, g, team)] = by_pair.get((row.opp_lambda, row.team_lambda))
m0 = rec0[key + ["team", "n_fixtures", "p_cs", "team_lambda", "opp_lambda"]].merge(ref0[key + ["p_cs", "team_lambda", "opp_lambda"]], on=key, suffixes=("_rec", "_new"))
m0["opp"] = [opp.get((k, g, t)) for k, g, t in zip(m0["cutoff"], m0["gw"], m0["team"])]
m0["involves"] = [(t in affected.get(k, [])) or (o in affected.get(k, [])) for k, t, o in zip(m0["cutoff"], m0["team"], m0["opp"])]
m0["d"] = (m0["p_cs_new"] - m0["p_cs_rec"]).abs()
clean = m0[(~m0["involves"]) & (m0["n_fixtures"] == 1) & m0["opp"].notna()]
per_cut = clean.groupby("cutoff")["d"].max()
print(f"{season}: affected cutoffs {sorted(affected)}")
print("per-cutoff max |d p_cs| on rows with NO affected club (only cutoffs with movement):")
print(per_cut[per_cut > 0].round(5).to_string())
top = clean.sort_values("d", ascending=False).drop_duplicates(["cutoff", "gw", "team"]).head(8)
print(top[["cutoff", "gw", "team", "opp", "p_cs_rec", "p_cs_new", "team_lambda_rec", "team_lambda_new", "opp_lambda_rec", "opp_lambda_new"]].to_string())

# refit the worst cutoff both ways and diff the parameters
k = int(top.iloc[0]["cutoff"])
f = fit_by_cut[k]
print(f"\nworst cutoff {k}: LAST_FIT (form) hadv {f['home_adv']:.5f} rho {f['rho']:.5f} method {f['method']} iters {f['iterations']} below_n {f['clubs_below_n']} at_bound {f['at_bound']}")
m = dc._load_matches(season)
mc = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
teams = sorted(set(mc["home"]) | set(mc["away"]))
cur = mc[mc["season"] == season]
prior_teams = sorted(set(cur["home"]) | set(cur["away"]))
cut = pd.Timestamp(f["ref"])
train = mc[dc.knowable_before(mc, cut)]
x_on, idx, nt = dc._fit_dc_decay(train, teams, cut, dc.HALF_LIFE_DAYS, prior_teams=prior_teams)
on = dict(dc.LAST_FIT)
dc.SHRINK_N = 0; dc.ATK_DFC_BOUND = None
x_off, _, _ = dc._fit_dc_decay(train, teams, cut, dc.HALF_LIFE_DAYS, prior_teams=prior_teams)
off = dict(dc.LAST_FIT)
print(f"refit at cutoff {k} ({cut.date()}), n_train {len(train)}: hadv off {x_off[-2]:.5f} on {x_on[-2]:.5f} (d {x_on[-2]-x_off[-2]:+.5f}); rho off {x_off[-1]:.5f} on {x_on[-1]:.5f} (d {x_on[-1]-x_off[-1]:+.5f})")
print(f"  iterations off {off['iterations']} on {on['iterations']}; converged off {off['converged']} on {on['converged']}; mean atk off {x_off[:nt].mean():+.4f} on {x_on[:nt].mean():+.4f}")
c_on = np.concatenate([x_on[:nt] - x_on[:nt].mean(), x_on[nt:2*nt] - x_on[nt:2*nt].mean()])
c_off = np.concatenate([x_off[:nt] - x_off[:nt].mean(), x_off[nt:2*nt] - x_off[nt:2*nt].mean()])
d = c_on - c_off
rows = sorted(((abs(d[i]) + abs(d[nt+i]), t, d[i], d[nt+i], c_off[i], c_on[i], c_off[nt+i], c_on[nt+i]) for t, i in idx.items()), reverse=True)[:10]
print("largest centred-parameter moves (club, d_atk, d_dfc | atk off->on | dfc off->on):")
for _, t, da, dd, ao, an, do_, dn in rows:
    print(f"  {t:18s} {da:+.4f} {dd:+.4f} | {ao:+.4f} -> {an:+.4f} | {do_:+.4f} -> {dn:+.4f}")
print("raw-gauge check: sum(atk)-sum(dfc) off %.2e on %.2e" % (x_off[:nt].sum() - x_off[nt:2*nt].sum(), x_on[:nt].sum() - x_on[nt:2*nt].sum()))
# how much of a typical unaffected fixture's lambda moves through hadv alone
print(f"exp(d hadv) = {np.exp(x_on[-2]-x_off[-2]):.5f}")
