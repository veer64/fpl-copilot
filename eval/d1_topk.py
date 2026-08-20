"""Top-k selection quality per gameweek, per position, per variant. Step 0 only.

Variants: baseline, full D1, A (saves+conceded+penalty, no cards), B (A plus
position-prior cards). A and B use the baseline exp_bonus (the _lo bracket,
shown immaterial in d1_variants_ab.py).

Metrics per (gw, position, k in {1,3,5}):
  m1: mean realised points of the top-k by predicted e_points (all rows)
  m2: same, candidate pool restricted to players who actually started
      (realised minutes >= 60), so playing-time selection isn't doing the work
  m3: overlap with the hindsight-optimal top-k (all rows; nlargest with
      deterministic tie-break, same treatment for every variant)
  m4: mean realised-points rank (1 = best, average ranks on ties, whole
      gw-position pool) of the model's top-k picks (all rows)

Aggregation: mean and SD across the 38 gameweeks. Resolution: paired per-gw
deltas vs baseline; a difference is 'resolved' iff |mean delta| > 2*SE.
"""
import numpy as np
import pandas as pd

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
POSITIONS = ["GK", "DEF", "MID", "FWD"]
KS = [1, 3, 5]

def step0(p):
    df = pd.read_parquet(p)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    return d.dropna(subset=["e_points", "actual_points"])

b = step0(BASE + r"\data\walkforward_h6_2526_baseline.parquet")
d = step0(BASE + r"\data\walkforward_h6_2025_26.parquet")
m = b.merge(
    d[["element", "gw", "e_points", "pts_saves", "pts_conceded", "pts_cards",
       "pts_goals", "minutes_frac"]],
    on=["element", "gw"], suffixes=("", "_d1"), how="inner")

hist = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
prior = hist[(hist["season"] < "2025-26") & (hist["position"] != "AM")]
prior = prior[prior["minutes"] > 0]
rate = prior.groupby("position").apply(
    lambda g: pd.Series({"y90": 90.0 * g["yellow_cards"].sum() / g["minutes"].sum(),
                         "r90": 90.0 * g["red_cards"].sum() / g["minutes"].sum()}),
    include_groups=False)
t_cards_prior = -(m["position"].map(rate["y90"])
                  + 3.0 * m["position"].map(rate["r90"])) * m["minutes_frac_d1"]

core = (m["e_points"] + m["pts_saves_d1"] + m["pts_conceded_d1"]
        + (m["pts_goals_d1"] - m["pts_goals"]))
VARIANTS = {
    "baseline": m["e_points"],
    "full_d1":  m["e_points_d1"],
    "A":        core,
    "B":        core + t_cards_prior,
}
for v, s in VARIANTS.items():
    m[f"pred_{v}"] = s

records = []
for (gw, pos), g in m.groupby(["gw", "position"]):
    if pos not in POSITIONS:
        continue
    act_rank = g["actual_points"].rank(ascending=False, method="average")
    started = g[g["minutes"] >= 60]
    for k in KS:
        hind_idx = set(g.nlargest(k, "actual_points").index)
        for v in VARIANTS:
            picks = g.nlargest(k, f"pred_{v}")
            rec = {"gw": gw, "pos": pos, "k": k, "variant": v,
                   "m1": picks["actual_points"].mean(),
                   "m3": len(set(picks.index) & hind_idx),
                   "m4": act_rank.loc[picks.index].mean()}
            sp = started.nlargest(min(k, len(started)), f"pred_{v}")
            rec["m2"] = sp["actual_points"].mean() if len(sp) else np.nan
            records.append(rec)
r = pd.DataFrame(records)

METRICS = {"m1": "Top-k mean realised pts (all rows)",
           "m2": "Top-k mean realised pts (started-only pool)",
           "m3": "Overlap with hindsight top-k (count)",
           "m4": "Mean realised rank of picks (1=best)"}

for mk, mtitle in METRICS.items():
    print(f"\n=== {mtitle} ===  mean (SD across gameweeks)")
    print(f"  {'pos':4s} {'k':>2s} " + " ".join(f"{v:>16s}" for v in VARIANTS))
    for pos in POSITIONS:
        for k in KS:
            row = f"  {pos:4s} {k:2d} "
            for v in VARIANTS:
                s = r[(r["pos"] == pos) & (r["k"] == k) & (r["variant"] == v)][mk]
                row += f" {s.mean():7.3f} ({s.std():5.3f})"
            print(row)

print("\n=== Paired per-gw deltas vs baseline: mean delta [2*SE] "
      "(RESOLVED iff |mean| > 2*SE) ===")
piv = r.pivot_table(index=["pos", "k", "gw"], columns="variant",
                    values=list(METRICS), observed=True)
for mk in METRICS:
    print(f"\n{mk}: {METRICS[mk]}")
    print(f"  {'pos':4s} {'k':>2s} " + " ".join(f"{v:>22s}" for v in VARIANTS if v != "baseline"))
    for pos in POSITIONS:
        for k in KS:
            sub = piv.loc[(pos, k)]
            row = f"  {pos:4s} {k:2d} "
            for v in VARIANTS:
                if v == "baseline":
                    continue
                delta = (sub[(mk, v)] - sub[(mk, "baseline")]).dropna()
                se2 = 2 * delta.std() / np.sqrt(len(delta))
                tag = "RES" if abs(delta.mean()) > se2 else "  ."
                row += f" {delta.mean():+7.3f} [{se2:5.3f}] {tag}"
            print(row)

n_res = 0
n_tot = 0
for mk in METRICS:
    for pos in POSITIONS:
        for k in KS:
            sub = piv.loc[(pos, k)]
            for v in ("full_d1", "A", "B"):
                delta = (sub[(mk, v)] - sub[(mk, "baseline")]).dropna()
                n_tot += 1
                if abs(delta.mean()) > 2 * delta.std() / np.sqrt(len(delta)):
                    n_res += 1
print(f"\nresolved cells: {n_res} of {n_tot}")
