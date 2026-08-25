"""Reproduces the team-news Arm B mask (calendar-knowable step-0 reveals) and classifies Arm B's and Arm A's decisions vs the fslog base_wc2 reference -- informative vs redundant reveals, contradictions with the stale step-1 belief, reveal-driven / contradiction-driven transfers and their next-3-gw value, reference-only transfers, pure-divergence weeks -- to test whether the arms lost through INCONSISTENCY or through noise. Result of record: Logs/horizon_minutes_scoping_log.md section 1 (verdict: refuted as a cause; losses are path-divergence lottery). Read-only; no simulations."""
# Task 1: what Arm B knew, which rows it changed, and whether its losses were
# contradiction-driven (step-0 truth vs stale step-1..5 beliefs). Read-only.
import json
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent  # repo root; rescued 2026-08-24 from a hardcoded absolute path
TN, P1 = REPO / "data/teamnews", REPO / "data/p1"
SEASONS = ["2023-24", "2024-25", "2025-26"]


def knowable_mask(season):
    """Verbatim logic of eval/run_teamnews_knowable.knowable_mask."""
    hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet",
                           columns=["season", "element", "round", "kickoff_time", "minutes"])
    hist = hist[hist["season"] == season].copy()
    hist["kickoff_time"] = pd.to_datetime(hist["kickoff_time"], utc=True)
    hist["minutes"] = pd.to_numeric(hist["minutes"], errors="coerce").fillna(0)
    mask = set()
    for e, g in hist.groupby("element"):
        g = g.sort_values("kickoff_time")
        kos, mins, rounds = g["kickoff_time"].tolist(), g["minutes"].tolist(), g["round"].tolist()
        for i in range(len(g)):
            for j in range(i - 1, -1, -1):
                dt = (kos[i] - kos[j]).total_seconds() / 86400
                if dt > 4:
                    break
                if mins[j] >= 60 and rounds[j] != rounds[i]:
                    mask.add((int(rounds[i]), int(e)))
                    break
    pergw = hist.groupby(["element", "round"])["minutes"].sum().unstack(fill_value=float("nan"))
    for e, row in pergw.iterrows():
        zero_run = 0
        for gw in sorted(pergw.columns):
            v = row.get(gw)
            if pd.isna(v):
                continue
            if zero_run >= 3:
                mask.add((int(gw), int(e)))
            zero_run = zero_run + 1 if v == 0 else 0
    return mask


def load_log(p):
    d = pd.read_parquet(p)
    d["all_transfers"] = d["all_transfers"].map(lambda x: json.loads(x) if isinstance(x, str) else x)
    d["elements"] = d["elements"].map(json.loads)
    return d.set_index("gw")


for season in SEASONS:
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "e_minutes", "minutes",
                                  "horizon_step", "actual_points"])
    own = wf[wf["horizon_step"] == 0].set_index(["gw", "element"])
    step1 = wf[wf["horizon_step"] == 1].set_index(["gw", "element"])   # cutoff = gw-1
    # stale belief about gw g held at cutoff g-... we need: belief at cutoff g about g+1
    nxt = wf[wf["horizon_step"] == 1].copy(); nxt["belief_at"] = nxt["cutoff"]
    nxt = nxt.set_index(["belief_at", "element"])["e_minutes"]         # (cutoff g, e) -> e_min for g+1
    truth = own["minutes"]; model0 = own["e_minutes"]
    pts = pd.to_numeric(own["actual_points"], errors="coerce").fillna(0)
    mask = knowable_mask(season)
    ref, B, A = (load_log(P1 / f"fslog_{tag}_base_wc2.parquet"),
                 load_log(TN / f"oraclelog_{tag}_B.parquet"),
                 load_log(TN / f"oraclelog_{tag}_A.parquet"))
    assert int(B["mask_size"].iloc[0]) == len(mask), "mask does not reproduce"

    print(f"\n================ {season} ================")
    print(f"Arm B mask reproduced: {len(mask):,} (gw, element) reveals; rows changed = step-0 only.")
    # --- 1. what the reveals contained
    keys = [k for k in mask if k in own.index]
    t = truth.loc[keys]; m = model0.loc[keys]
    informative = (t - m).abs() >= 30
    absent = (t < 15) & (m >= 60); present = (t >= 60) & (m < 30)
    print(f"  reveals with a walkforward row: {len(keys):,}; informative (|truth-model0| >= 30): "
          f"{int(informative.sum()):,} ({informative.mean():.1%}); of which absent-surprise "
          f"(truth<15, model>=60) {int(absent.sum()):,}, present-surprise (truth>=60, model<30) {int(present.sum()):,}")
    # --- 2. contradiction with the stale step-1 belief
    s1 = pd.Series({(g, e): nxt.get((g, e), np.nan) for g, e in keys})
    contra_abs = absent & (s1 >= 60); contra_pres = present & (s1 < 30)
    # what actually happened next week for absent-surprises the model still rated
    nxt_truth = pd.Series({(g, e): truth.get((g + 1, e), np.nan) for g, e in keys})
    played_next = (nxt_truth >= 60)
    print(f"  contradictions (step-0 truth vs stale step-1 belief): absent-but-rated-next-week "
          f"{int(contra_abs.sum()):,}, present-but-written-off-next-week {int(contra_pres.sum()):,}")
    print(f"  of absent-surprise reveals, share who actually played >=60 the NEXT gw: "
          f"{played_next[absent].mean():.1%} (n={int(absent.sum())}) -> the stale belief was RIGHT "
          f"about next week that often; step-0 truth said nothing about it")
    # --- 3. B's decisions vs the reference, classified
    def extra(arm):
        rows = []
        for g in arm.index:
            if g not in ref.index:
                continue
            for out_, in_ in ({tuple(x) for x in arm.loc[g, "all_transfers"]}
                              - {tuple(x) for x in ref.loc[g, "all_transfers"]}):
                e2 = sum(float(pts.get((gg, in_), 0)) - float(pts.get((gg, out_), 0))
                         for gg in range(g, min(g + 3, 39)))
                rd = (g, out_) in mask or (g, in_) in mask
                cd = ((g, out_) in mask and bool(contra_abs.get((g, out_), False))) or \
                     ((g, in_) in mask and bool(contra_pres.get((g, in_), False)))
                sold_absent = (g, out_) in mask and bool(absent.get((g, out_), False))
                rows.append(dict(gw=g, out=out_, inn=in_, e2=e2, reveal=rd, contra=cd,
                                 sold_absent=sold_absent))
        return pd.DataFrame(rows)
    for name, arm in (("B", B), ("A", A)):
        x = extra(arm)
        delta = int(arm["final_total"].iloc[0]) - int(ref["final_total"].iloc[0])
        print(f"  arm {name}: path delta {delta:+d}; transfers not in reference: {len(x)} "
              f"(reference-only transfers: "
              f"{sum(len({tuple(t) for t in ref.loc[g, 'all_transfers']} - {tuple(t) for t in arm.loc[g, 'all_transfers']}) for g in arm.index if g in ref.index)})")
        if len(x):
            for lab, sel in (("reveal-driven", x["reveal"]), ("  of which contradiction-driven", x["contra"]),
                             ("  of which sold an absent-surprise", x["sold_absent"]),
                             ("not reveal-driven (divergence follow-on)", ~x["reveal"])):
                s = x[sel]
                print(f"    {lab:42s} n={len(s):3d}  mean E2(next-3-gw, in-out) {s['e2'].mean() if len(s) else float('nan'):+6.2f}  "
                      f"sum {s['e2'].sum():+7.1f}")
        # the reference's transfers that this arm did NOT make -- their value
        ro = []
        for g in arm.index:
            if g not in ref.index:
                continue
            for out_, in_ in ({tuple(t) for t in ref.loc[g, "all_transfers"]}
                              - {tuple(t) for t in arm.loc[g, "all_transfers"]}):
                ro.append(sum(float(pts.get((gg, in_), 0)) - float(pts.get((gg, out_), 0))
                              for gg in range(g, min(g + 3, 39))))
        print(f"    reference-only transfers: n={len(ro)}  mean E2 {np.mean(ro) if ro else float('nan'):+6.2f}  "
              f"sum {sum(ro):+7.1f}   -> arm-extra minus reference-only E2 sum: {x['e2'].sum() - sum(ro):+.1f}")
        # pure-divergence weeks: identical transfers, different squads
        same_tr = [g for g in arm.index if g in ref.index
                   and {tuple(t) for t in arm.loc[g, "all_transfers"]} == {tuple(t) for t in ref.loc[g, "all_transfers"]}
                   and set(arm.loc[g, "elements"]) != set(ref.loc[g, "elements"])]
        dd_pure = pd.Series({g: int(arm.loc[g, "points"]) - int(ref.loc[g, "points"]) for g in same_tr})
        print(f"    pure-divergence weeks (identical transfers, different squads): n={len(same_tr)}  "
              f"mean delta {dd_pure.mean() if len(same_tr) else float('nan'):+5.2f}/gw  sum {dd_pure.sum():+d}")
        # per-gw path delta split by whether that gw had a reveal-driven transfer
        gws_rd = set(x.loc[x["reveal"], "gw"]) if len(x) else set()
        dd = pd.Series({g: int(arm.loc[g, "points"]) - int(ref.loc[g, "points"]) for g in arm.index if g in ref.index})
        print(f"    per-gw delta: reveal-transfer weeks mean {dd.loc[[g for g in dd.index if g in gws_rd]].mean() if gws_rd else float('nan'):+5.2f} "
              f"(n={len(gws_rd)}); other weeks mean {dd.loc[[g for g in dd.index if g not in gws_rd]].mean():+5.2f}; "
              f"first divergent gw {min([g for g in dd.index if dd.loc[g] != 0] or [-1])}")
