"""Checks whether the proposed TC2 tie-break ("among eligible second-half doubles, the week where the intended captain's predicted points at that week's own cutoff are highest") can be computed at decision time rather than in hindsight: which candidate doubles are visible inside the 6-step horizon from each earlier candidate's deadline, how degraded step-k captain projections are vs the step-0 value, and which week each selector variant (literal own-cutoff argmax; sequential decision-time) picks vs the sweep's best-read week. Result of record: Logs/tc2_valuation_log.md, section "Tie-break computability check" (rendered by this module, called from eval/tc2_valuation_sweep.py). Read-only; no simulations.

Definitions (frozen base_wc2 paths, walkforward_h6 files, H=6 -> steps 0..5):
  * eligible doubles E = second-half doubles minus weeks already holding a
    chip on the path (WC2, FH2, BB2).
  * own-cutoff selector value  own(g)  = e_points at cutoff g of the path's
    captain at g (the sim's captain IS the own-cutoff argmax in the XI).
  * decision-time projection   proj(c, g) = max over the squad held after
    cutoff c (log `elements` at c) of e_points(cutoff=c, gw=g); defined only
    when 1 <= g - c <= 5 (inside the horizon). The XI split is not persisted,
    so the 15-man squad stands in for the projected XI (stated proxy).
  * literal selector: argmax_g own(g) -- requires every candidate's own
    cutoff, i.e. hindsight unless the argmax happens to be the first
    candidate.
  * sequential selector: at each candidate c in order, play TC2 at c if
    own(c) >= every proj(c, g) for later candidates g visible from c;
    candidates beyond the horizon are invisible and cannot be compared.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "data" / "p1"
SEASONS = ["2023-24", "2024-25", "2025-26"]
H2_START, H = 20, 6


def load(season):
    tag = season.replace("-", "_")
    d = pd.read_parquet(P1 / f"fslog_{tag}_base_wc2.parquet").set_index("gw")
    d["elements"] = d["elements"].map(json.loads)
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "name", "e_points",
                                  "team", "n_fixtures"])
    return d, wf


def analyse(season):
    d, wf = load(season)
    own = wf[wf["cutoff"] == wf["gw"]]
    inv = own[own["n_fixtures"] >= 2].groupby("gw")["team"].nunique()
    taken = {int(d[c].iloc[0]) for c in ("wc2", "fh2", "bb2")}
    E = [int(g) for g in inv.index if g >= H2_START and g not in taken]
    own_val, own_cap = {}, {}
    for g in E:
        cap = d.loc[g, "captain"]
        r = own[(own["gw"] == g) & (own["name"] == cap)]
        own_val[g] = float(r["e_points"].iloc[0]) if len(r) else np.nan
        own_cap[g] = cap
    proj = {}
    for c in E:
        squad = set(d.loc[c, "elements"])
        for g in E:
            k = g - c
            if 1 <= k <= H - 1:
                rows = wf[(wf["cutoff"] == c) & (wf["gw"] == g)
                          & wf["element"].isin(squad)]
                if len(rows):
                    best = rows.loc[rows["e_points"].idxmax()]
                    proj[(c, g)] = (float(best["e_points"]), best["name"], k)
    literal = max(E, key=lambda g: own_val[g])
    seq = None
    for c in E:
        later_vis = [proj[(c, g)][0] for g in E if g > c and (c, g) in proj]
        if not later_vis or own_val[c] >= max(later_vis):
            seq = c
            break
    seq = seq if seq is not None else E[-1]
    legal = [g for g in range(H2_START, 39) if g in d.index and g not in taken]
    reads = d.loc[legal, "captain_bonus"].astype(int)
    invisible_from_first = [g for g in E if g > E[0] and (E[0], g) not in proj]
    # degradation of step-k captain projections vs own-cutoff, all legal weeks
    rows = []
    for g in legal:
        cap = d.loc[g, "captain"]
        r0 = own[(own["gw"] == g) & (own["name"] == cap)]
        if not len(r0):
            continue
        v0 = float(r0["e_points"].iloc[0])
        for k in range(1, H):
            c = g - k
            if c not in d.index:
                continue
            squad = set(d.loc[c, "elements"])
            rk = wf[(wf["cutoff"] == c) & (wf["gw"] == g) & wf["element"].isin(squad)]
            if len(rk):
                rows.append(dict(gw=g, k=k, own=v0, proj=float(rk["e_points"].max()),
                                 same=(rk.loc[rk["e_points"].idxmax(), "name"] == cap)))
    deg = pd.DataFrame(rows)
    degrade = []
    for k, g in deg.groupby("k"):
        degrade.append((int(k), len(g), float(g["own"].corr(g["proj"])),
                        float((g["proj"] - g["own"]).abs().mean()),
                        float(g["same"].mean())))
    return dict(season=season, E=E, taken=sorted(taken), own_val=own_val,
                own_cap=own_cap, proj=proj, literal=literal, seq=seq,
                reads=reads, best_read=int(reads.idxmax()),
                read=lambda g: int(d.loc[g, "captain_bonus"]),
                invisible_from_first=invisible_from_first, degrade=degrade)


def analyse_all():
    return [analyse(s) for s in SEASONS]


def render(results):
    out = ["## Tie-break computability check (2026-08-24) -- the proposed rule is NOT computable as written\n",
           "Proposed (user, 2026-08-24): *TC2 = a second-half double, excluding "
           "weeks already holding a chip; among eligible doubles, the week where "
           "the intended captain's predicted points at that week's own cutoff are "
           "highest.* Checked here BEFORE adoption, per instruction: can the "
           "selector be computed at decision time? Method in "
           "`eval/tc2_tiebreak_computability.py` (docstring). Frozen base_wc2 "
           "paths; no simulations.\n"]
    for r in results:
        E = r["E"]
        out.append(f"### {r['season']} -- eligible doubles {E}, chip weeks {r['taken']}\n")
        span = max(E) - min(E)
        out.append(f"- Candidates span GW{min(E)}..GW{max(E)} = {span} gameweeks; the "
                   f"horizon sees {H - 1} ahead. From the first candidate's deadline "
                   f"the later candidates {r['invisible_from_first']} are "
                   f"**invisible** -- their own-cutoff predictions do not exist yet "
                   f"and no horizon projection reaches them.")
        out.append("")
        out.append("| candidate | captain at own cutoff | own-cutoff e_points | realised read | visible from earlier candidates (projection, step) |")
        out.append("|---|---|---|---|---|")
        for g in E:
            vis = [f"from GW{c}: {v:.2f} ({n}, step {k})" for (c, gg), (v, n, k)
                   in sorted(r["proj"].items()) if gg == g]
            out.append(f"| GW{g} | {r['own_cap'][g]} | {r['own_val'][g]:.2f} | "
                       f"{r['read'](g)} | {'; '.join(vis) if vis else 'not visible from any earlier candidate'} |")
        out.append("")
        out.append(f"- literal selector (argmax of own-cutoff values -- needs every "
                   f"cutoff, i.e. hindsight): **GW{r['literal']}** (read {r['read'](r['literal'])})")
        out.append(f"- sequential decision-time approximation (play when own value "
                   f">= every visible later projection): **GW{r['seq']}** "
                   f"(read {r['read'](r['seq'])})")
        out.append(f"- sweep's best-read week over ALL legal weeks (pure hindsight): "
                   f"GW{r['best_read']} (read {int(r['reads'].max())})")
        out.append("- step-k projected captain points vs the eventual own-cutoff value, "
                   "all legal H2 weeks (corr / MAE / same-captain rate): "
                   + "; ".join(f"k={k}: {c:.2f} / {m:.2f} / {s:.0%}"
                               for k, n, c, m, s in r["degrade"]))
        out.append("")
    lit = ", ".join(f"GW{r['literal']}" for r in results)
    seq = ", ".join(f"GW{r['seq']}" for r in results)
    best = ", ".join(f"GW{r['best_read']}" for r in results)
    out.append("**Verdict.** The selector as written -- compare candidates by their "
               "own-cutoff predictions -- is **not computable at decision time**: in "
               "every season the eligible doubles span more than the horizon, so the "
               "comparison can only be made after the last candidate's cutoff has "
               "passed. It is a hindsight rule dressed as a prediction rule. The "
               "computable variant is a sequential stopping rule using horizon "
               "projections for the candidates it can see (invisible ones cannot "
               "enter the comparison); its picks differ from the literal selector "
               f"where a later candidate is invisible (literal {lit}; sequential {seq}; "
               f"sweep best-read {best}). Neither selector simply reproduces the "
               "hindsight winner, which is the right sign; but the projections "
               "degrade with step (same-captain rate falls to 12-62% by step 5 in "
               "two of three seasons) and, decisively, candidates beyond the horizon "
               "are not visible at all. **Not adopted.** The rule of record stays as "
               "in p4 log section 12c (largest double excluding the BB2 week, "
               "with its tie problem open); a decision-time TC2 rule needs a "
               "stopping formulation and a simulation to value it, which this study "
               "deliberately does not run.")
    out.append("")
    return out


if __name__ == "__main__":
    print("\n".join(render(analyse_all())))
