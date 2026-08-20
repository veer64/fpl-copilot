"""Model-vs-model agreement and against-reality top-k quality.
Final Variant B build vs baseline, three seasons, step 0, both pools.

Part 1 (deterministic, no outcome luck):
  p1_same1   : share of gameweeks where the two models' #1 pick is the same player
  p1_overlap : mean |topk_base & topk_B| (k=3,5)
  p1_ident   : share of gameweeks where the two top-k SETS are identical (k=3,5)
  p1_urho    : Spearman between the two models' predicted orderings on the UNION
               of their top-k sets (k=3,5; k=1 omitted -- union of 1-2 players is
               degenerate)

Part 2 (against reality; paired per-gw deltas B - baseline, RES iff |mean|>2SE):
  p2_hind    : |model topk & hindsight topk| per model
  p2_irho    : Spearman(predicted, realised) WITHIN the model's own top-k
               (k=3,5; 3 or 5 points per gw -- expected not to resolve)
  p2_best1   : share of gameweeks where the model's #1 pick realised the most
               points among its own top-k (ties count as best)
  p2_rank1   : mean realised-points rank (1=best, average ties, whole pool) of
               the model's #1 pick

Pools: 'all' = every step-0 row; 'started' = realised minutes >= 60 (pool
restriction applied before everything, including the hindsight set).
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
POSITIONS = ["GK", "DEF", "MID", "FWD"]
KS = [1, 3, 5]
PAIRS = {
    "2025-26": (r"\data\walkforward_h6_2526_baseline.parquet",
                r"\data\walkforward_h6_2025_26.parquet"),
    "2024-25": (r"\data\walkforward_h6_2024_25_baseline.parquet",
                r"\data\walkforward_h6_2024_25.parquet"),
    "2023-24": (r"\data\walkforward_h6_2023_24_baseline.parquet",
                r"\data\walkforward_h6_2023_24.parquet"),
}

def step0(path):
    df = pd.read_parquet(BASE + path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

rows = []
for season, (p0, pb) in PAIRS.items():
    b0 = step0(p0)[["element", "gw", "position", "e_points", "actual_points", "minutes"]]
    bb = step0(pb)[["element", "gw", "e_points"]]
    m = b0.merge(bb, on=["element", "gw"], suffixes=("_0", "_b"), how="inner")
    for (gw, pos), g in m.groupby(["gw", "position"]):
        if pos not in POSITIONS:
            continue
        for pool in ("all", "started"):
            p = g if pool == "all" else g[g["minutes"] >= 60]
            if len(p) < 2:
                continue
            act_rank = p["actual_points"].rank(ascending=False, method="average")
            for k in KS:
                kk = min(k, len(p))
                t0 = p.nlargest(kk, "e_points_0")
                tb = p.nlargest(kk, "e_points_b")
                hind = set(p.nlargest(kk, "actual_points").index)
                s0, sb = set(t0.index), set(tb.index)
                rec = {"season": season, "gw": gw, "pos": pos, "k": k, "pool": pool,
                       "p1_same1": int(t0.index[0] == tb.index[0]),
                       "p1_overlap": len(s0 & sb),
                       "p1_ident": int(s0 == sb),
                       "p2_hind_0": len(s0 & hind), "p2_hind_b": len(sb & hind),
                       "p2_best1_0": int(t0["actual_points"].iloc[0]
                                         >= t0["actual_points"].max()),
                       "p2_best1_b": int(tb["actual_points"].iloc[0]
                                         >= tb["actual_points"].max()),
                       "p2_rank1_0": act_rank.loc[t0.index[0]],
                       "p2_rank1_b": act_rank.loc[tb.index[0]]}
                if k >= 3:
                    union = list(s0 | sb)
                    u = p.loc[union]
                    if len(u) >= 3:
                        rec["p1_urho"] = spearmanr(u["e_points_0"], u["e_points_b"]).statistic
                    if kk >= 3:
                        rec["p2_irho_0"] = spearmanr(t0["e_points_0"], t0["actual_points"]).statistic
                        rec["p2_irho_b"] = spearmanr(tb["e_points_b"], tb["actual_points"]).statistic
                rows.append(rec)
r = pd.DataFrame(rows)

def agg(s):
    return f"{s.mean():6.3f} ({s.std():5.3f})"

def paired(sub, col0, colb):
    d = (sub[colb] - sub[col0]).dropna()
    if len(d) < 2:
        return "n/a", False
    se2 = 2 * d.std() / np.sqrt(len(d))
    res = abs(d.mean()) > se2
    return f"{d.mean():+6.3f} [{se2:5.3f}]", res

print("=" * 100)
print("PART 1 -- MODEL-VS-MODEL AGREEMENT (deterministic)")
for pool in ("all", "started"):
    print(f"\n--- pool={pool} ---")
    print(f"{'season':8s} {'pos':4s} | {'same#1':>7s} | "
          f"{'ovl k3':>13s} {'ident3':>7s} | {'ovl k5':>13s} {'ident5':>7s} | "
          f"{'urho k3':>14s} {'urho k5':>14s}")
    for season in PAIRS:
        for pos in POSITIONS:
            s1 = r[(r.season == season) & (r.pos == pos) & (r.pool == pool) & (r.k == 1)]
            s3 = r[(r.season == season) & (r.pos == pos) & (r.pool == pool) & (r.k == 3)]
            s5 = r[(r.season == season) & (r.pos == pos) & (r.pool == pool) & (r.k == 5)]
            print(f"{season:8s} {pos:4s} | {s1.p1_same1.mean():7.2%} | "
                  f"{agg(s3.p1_overlap):>13s} {s3.p1_ident.mean():7.2%} | "
                  f"{agg(s5.p1_overlap):>13s} {s5.p1_ident.mean():7.2%} | "
                  f"{agg(s3.p1_urho.dropna()):>14s} {agg(s5.p1_urho.dropna()):>14s}")

print("\n" + "=" * 100)
print("PART 2 -- AGAINST REALITY (side by side; delta = B - baseline, paired)")
n_res, n_tot, res_list = 0, 0, []
for pool in ("all", "started"):
    print(f"\n--- pool={pool} ---")
    print("\nHindsight overlap (mean count of truly best k captured):")
    print(f"{'season':8s} {'pos':4s} {'k':>2s} {'baseline':>14s} {'variant_B':>14s} {'delta [2SE]':>17s}")
    for season in PAIRS:
        for pos in POSITIONS:
            for k in KS:
                sub = r[(r.season == season) & (r.pos == pos) & (r.pool == pool) & (r.k == k)]
                d, res = paired(sub, "p2_hind_0", "p2_hind_b")
                n_tot += 1; n_res += int(res)
                if res: res_list.append(f"hind {season} {pool} {pos} k{k}: {d}")
                print(f"{season:8s} {pos:4s} {k:2d} {agg(sub.p2_hind_0):>14s} "
                      f"{agg(sub.p2_hind_b):>14s} {d:>17s} {'RES' if res else '.'}")
    print("\nWithin-own-top-k Spearman (predicted vs realised order):")
    print(f"{'season':8s} {'pos':4s} {'k':>2s} {'baseline':>14s} {'variant_B':>14s} {'delta [2SE]':>17s}")
    for season in PAIRS:
        for pos in POSITIONS:
            for k in (3, 5):
                sub = r[(r.season == season) & (r.pos == pos) & (r.pool == pool) & (r.k == k)]
                sub = sub.dropna(subset=["p2_irho_0", "p2_irho_b"])
                d, res = paired(sub, "p2_irho_0", "p2_irho_b")
                n_tot += 1; n_res += int(res)
                if res: res_list.append(f"irho {season} {pool} {pos} k{k}: {d}")
                print(f"{season:8s} {pos:4s} {k:2d} {agg(sub.p2_irho_0):>14s} "
                      f"{agg(sub.p2_irho_b):>14s} {d:>17s} {'RES' if res else '.'}")
    print("\n#1 pick: share best-of-own-top-k (k=3), and realised rank of #1:")
    print(f"{'season':8s} {'pos':4s} {'best1_0':>8s} {'best1_B':>8s} {'d[2SE]':>15s} | "
          f"{'rank1_0':>14s} {'rank1_B':>14s} {'d[2SE]':>15s}")
    for season in PAIRS:
        for pos in POSITIONS:
            sub = r[(r.season == season) & (r.pos == pos) & (r.pool == pool) & (r.k == 3)]
            d1s, res1 = paired(sub, "p2_best1_0", "p2_best1_b")
            d2s, res2 = paired(sub, "p2_rank1_0", "p2_rank1_b")
            n_tot += 2; n_res += int(res1) + int(res2)
            if res1: res_list.append(f"best1 {season} {pool} {pos}: {d1s}")
            if res2: res_list.append(f"rank1 {season} {pool} {pos}: {d2s}")
            print(f"{season:8s} {pos:4s} {sub.p2_best1_0.mean():8.2%} "
                  f"{sub.p2_best1_b.mean():8.2%} {d1s:>15s}{'R' if res1 else ' '} | "
                  f"{agg(sub.p2_rank1_0):>14s} {agg(sub.p2_rank1_b):>14s} "
                  f"{d2s:>15s}{'R' if res2 else ' '}")

print(f"\nPART 2 RESOLUTION: {n_res} of {n_tot} paired comparisons resolve (>2SE)")
for line in res_list:
    print("  RES:", line)
