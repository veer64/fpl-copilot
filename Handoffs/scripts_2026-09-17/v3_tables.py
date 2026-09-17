"""Design tables for prereg v3 (a promoted-club centre for the hinge), computed BEFORE any endpoint number.
(1) A club with no history, zero goals in n matches, at the league rate 1.4 v average opposition: the MAP attack
    under the hinge (tau_n = 5.6 * max(0, 1 - n/10)) with centre 0 (v2) and with the promoted centre mu; then the
    box at -ln 4 about the league mean. Symmetric for a club conceding nothing (Hull): the MAP defence.
(2) The record's cold-start cases at cutoffs 1-6 (Luton 2023-24, Ipswich 2024-25, Sunderland 2025-26): the
    club's centred attack / defence and its mean fixture lambda under the plain fit (record), v2 (centre 0) and
    v3 (promoted centre). Self-contained fit (a copy of the branch's hinge objective + the centre), main's helpers.
Usage: v3_tables.py <mu_atk> <mu_dfc>"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize
from scipy.stats import poisson

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc  # noqa: E402

MU_A, MU_D = float(sys.argv[1]), float(sys.argv[2])
TAU0, N, B, RATE = 5.6, 10, float(np.log(4)), 1.40

print(f"=== (1) zero goals in n matches, no history, league rate {RATE}: MAP attack; box at {-B:.3f}")
print(" n  tau   | centre 0: a    x    lam(avg) | promoted centre: a    x    lam(avg)  lam(v strongest 0.50x)")
for n in [1, 2, 3, 4, 5, 6, 8, 10, 12]:
    tau = TAU0 * max(0.0, 1 - n / N)
    out = []
    for mu in (0.0, MU_A):
        if tau > 0:
            a = brentq(lambda a: RATE * n * np.exp(a) + tau * (a - mu), -30, 5)
        else:
            a = -np.inf
        a_box = max(a, -B)
        out.append((a, a_box))
    (a0, b0), (a1, b1) = out
    print(f"{n:2d} {tau:5.2f} | {a0:+7.2f} {np.exp(b0):5.2f} {RATE*np.exp(b0):5.2f}    | {a1:+7.2f} {np.exp(b1):5.2f} {RATE*np.exp(b1):5.2f}   {RATE*np.exp(b1)*0.5:5.2f}"
          + ("   <- box" if a1 < -B else ""))
print(f"\n=== zero conceded in n matches (Hull-type), no history: MAP defence; box at {-B:.3f}; opponents' lam = {RATE} * exp(d)")
print(" n  tau   | centre 0: d    opp lam | promoted centre (+{:.2f}): d    opp lam".format(MU_D))
for n in [1, 2, 3, 4, 6, 8, 10]:
    tau = TAU0 * max(0.0, 1 - n / N)
    out = []
    for mu in (0.0, MU_D):
        d = brentq(lambda d: RATE * n * np.exp(d) + tau * (d - mu), -30, 5) if tau > 0 else -np.inf
        out.append(max(d, -B))
    print(f"{n:2d} {tau:5.2f} | {out[0]:+6.2f} {RATE*np.exp(out[0]):5.2f}    | {out[1]:+6.2f} {RATE*np.exp(out[1]):5.2f}")


def fit(train, teams, ref, hl, prior_teams, promoted, mu_a, mu_d, form):
    """form: 'plain' | 'v2' | 'v3' -- the branch's hinge objective (centred over prior_teams) with centre 0 (v2)
    or the promoted centre for promoted clubs (v3). No box (it never binds on these cases: asserted)."""
    idx = {t: i for i, t in enumerate(teams)}; nt = len(teams)
    h = train["home"].map(idx).values; a = train["away"].map(idx).values
    hg = train["home_goals"].values.astype(float); ag = train["away_goals"].values.astype(float)
    age = (ref - train["date_parsed"]).dt.days.values
    w = np.exp(-(np.log(2) / hl) * age)
    n_eff = np.zeros(nt); np.add.at(n_eff, h, w); np.add.at(n_eff, a, w)
    pri = np.array([idx[t] for t in prior_teams])
    tau_i = np.zeros(nt)
    if form != "plain":
        tau_i[pri] = TAU0 * np.clip(1.0 - n_eff[pri] / N, 0.0, None)
    ma = np.zeros(nt); md = np.zeros(nt)
    if form == "v3":
        for t in promoted:
            ma[idx[t]] = mu_a; md[idx[t]] = mu_d
    hinge = bool((tau_i > 0).any())

    def nll(p):
        atk, dfc = p[:nt], p[nt:2 * nt]; hadv, rho = p[-2], p[-1]
        lh = np.exp(atk[h] + dfc[a] + hadv); la = np.exp(atk[a] + dfc[h])
        lp = poisson.logpmf(hg, lh) + poisson.logpmf(ag, la)
        tau = np.ones(len(hg))
        m00 = (hg == 0) & (ag == 0); m01 = (hg == 0) & (ag == 1); m10 = (hg == 1) & (ag == 0); m11 = (hg == 1) & (ag == 1)
        tau[m00] = (1 - lh * la * rho)[m00]; tau[m01] = (1 + lh * rho)[m01]; tau[m10] = (1 + la * rho)[m10]; tau[m11] = 1 - rho
        val = -(w * (lp + np.log(np.clip(tau, 1e-10, None)))).sum()
        if hinge:
            ca = atk - atk[pri].mean() - ma; cd = dfc - dfc[pri].mean() - md
            val += 0.5 * float(np.sum(tau_i * (ca ** 2 + cd ** 2)))
        return val

    x0 = np.zeros(2 * nt + 2); x0[-2] = 0.25
    res = minimize(nll, x0, method="L-BFGS-B")
    x = res.x
    c_a = x[:nt] - x[pri].mean(); c_d = x[nt:2 * nt] - x[nt + pri].mean()
    assert np.abs(c_a[pri]).max() <= B and np.abs(c_d[pri]).max() <= B or form == "plain", "box would bind"
    return x, idx, nt, c_a, c_d, n_eff, res.success


print("\n=== (2) the record's cold-start cases at cutoffs 1-6 -- centred attack / defence, and the club's mean fixture lambda (its own attack) over the 6-gw horizon")
m = dc._load_matches("2025-26")
mc = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
teams = sorted(set(mc["home"]) | set(mc["away"]))
seasons = sorted(mc["season"].unique())
cases = {"2023-24": "Luton", "2024-25": "Ipswich", "2025-26": "Sunderland"}
for season, club in cases.items():
    cur = mc[mc.season == season].sort_values("date_parsed")
    league = sorted(set(cur["home"]) | set(cur["away"]))
    prev = seasons[seasons.index(season) - 1]
    prev_clubs = set(mc.loc[mc.season == prev, "home"]) | set(mc.loc[mc.season == prev, "away"])
    promoted = [c for c in league if c not in prev_clubs]
    # cutoff k = the date of the k-th round's first match: approximate by the (10*(k-1))-th match of the season
    dates = cur["date_parsed"].values
    print(f"--- {season} {club}; promoted this season: {promoted}")
    print(" cutoff n_eff | plain: atk   dfc   lam | v2 (centre 0): atk   dfc   lam | v3 (promoted centre): atk   dfc   lam | v3 conv")
    for k in range(1, 7):
        cut = pd.Timestamp(dates[min(10 * (k - 1), len(dates) - 1)])
        train = mc[dc.knowable_before(mc, cut)]
        upcoming = cur[(cur["date_parsed"] >= cut)].head(60)   # the club's next ~6 fixtures
        row = f"{k:6d}"
        for form in ("plain", "v2", "v3"):
            x, idx, nt, c_a, c_d, n_eff, ok = fit(train, teams, cut, dc.HALF_LIFE_DAYS, league, promoted, MU_A, MU_D, form)
            atk, dfc, hadv = x[:nt], x[nt:2 * nt], x[-2]
            fx = upcoming[(upcoming.home == club) | (upcoming.away == club)].head(6)
            lam = [np.exp(atk[idx[club]] + dfc[idx[r.away]] + hadv) if r.home == club else np.exp(atk[idx[club]] + dfc[idx[r.home]])
                   for r in fx.itertuples()]
            if form == "plain":
                row += f" {n_eff[idx[club]]:5.1f} |"
            row += f" {c_a[idx[club]]:+6.2f} {c_d[idx[club]]:+6.2f} {np.mean(lam):5.2f} |"
            if form == "v3":
                row += f" {ok}"
        print(row)
