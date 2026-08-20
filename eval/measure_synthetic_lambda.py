# measure_synthetic_lambda.py
# D4 Phase 2 -- does synthetic lambda move e_points and selection?
#
# Compares the canonical walk-forward files (before: DC fallback at steps 1+)
# against the *_synth builds (after: synthetic-lambda fill at steps 1+,
# stamped synthetic_lambda_active=True). Step 0 uses real odds in both and
# must be BIT-EXACT -- verified, not assumed.
#
# Conventions follow the house standard (handoff 2026-08-18 sec 7) and the
# D1 measurement scripts (eval/d1_topk.py, eval/d1_agreement.py):
#   starter band   = predicted e_minutes >= 60
#   started pool   = realised minutes >= 60 (a different thing, named apart)
#   margin beta    = through-origin pairwise slope within (cutoff, position),
#                    exact moment accumulation, never sampled
#   resolution     = paired per-cutoff deltas, resolved iff |mean| > 2*SE,
#                    always reported against the ~5% chance rate
#
# Usage: uv run python eval/measure_synthetic_lambda.py

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

BASE = Path(r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot")
PAIRS = {
    "2023-24": ("walkforward_h6_2023_24.parquet", "walkforward_h6_2023_24_synth.parquet"),
    "2024-25": ("walkforward_h6_2024_25.parquet", "walkforward_h6_2024_25_synth.parquet"),
    "2025-26": ("walkforward_h6_2025_26.parquet", "walkforward_h6_2025_26_synth.parquet"),
}
POSITIONS = ["GK", "DEF", "MID", "FWD"]
STEPS = [0, 1, 2, 3, 4, 5]
KS = [1, 3, 5]
STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling",
          "d1_terms_active", "cs_unified", "rate_blend_active", "rate_blend_k",
          "dc_rule_active"]


def load(name):
    df = pd.read_parquet(BASE / "data" / name)
    df["actual_points"] = pd.to_numeric(df["actual_points"], errors="coerce")
    return df.dropna(subset=["e_points"])


def provenance(before, after, season):
    """House rule 7: stamps must match on everything except the flag under
    test. Before-files predate the synthetic stamp; absence reads as False."""
    for c in STAMPS:
        if c not in before.columns and c not in after.columns:
            continue
        b = before[c].iloc[0] if c in before.columns else None
        a = after[c].iloc[0] if c in after.columns else None
        assert b == a, f"{season}: stamp {c} differs ({b!r} vs {a!r})"
    sb = bool(before["synthetic_lambda_active"].iloc[0]) \
        if "synthetic_lambda_active" in before.columns else False
    sa = bool(after["synthetic_lambda_active"].iloc[0])
    assert (sb, sa) == (False, True), \
        f"{season}: synthetic stamp pair is ({sb},{sa}), expected (False,True)"
    print(f"  {season}: stamps match, synthetic_lambda_active False->True")


def step0_bitexact(before, after, season):
    cols = [c for c in ["e_points", "e_points_core", "e_goals", "pts_goals",
                        "pts_cs", "pts_conceded", "pts_saves", "exp_bonus"]
            if c in before.columns and c in after.columns]
    b = before[before["horizon_step"] == 0]
    a = after[after["horizon_step"] == 0]
    m = b.merge(a, on=["cutoff", "gw", "element"], suffixes=("_b", "_a"))
    assert len(m) == len(b) == len(a), \
        f"{season}: step-0 row sets differ ({len(b)} vs {len(a)}, merged {len(m)})"
    worst = 0.0
    for c in cols:
        d = (m[f"{c}_b"] - m[f"{c}_a"]).abs().max()
        worst = max(worst, d)
    print(f"  {season}: step-0 rows {len(m)}, max |diff| over {len(cols)} "
          f"prediction columns = {worst:.1e}"
          + ("  [BIT-EXACT]" if worst == 0.0 else "  [NOT EXACT -- FAIL]"))
    return worst == 0.0


def merged(before, after):
    keep = ["cutoff", "gw", "horizon_step", "element", "position",
            "e_points", "actual_points", "minutes", "e_minutes"]
    m = before[keep].merge(
        after[["cutoff", "gw", "element", "e_points"]],
        on=["cutoff", "gw", "element"], suffixes=("_b", "_a"), how="inner")
    return m.dropna(subset=["actual_points"])


def sp(x, y):
    return spearmanr(x, y).correlation if len(x) >= 3 else np.nan


def accuracy_tables(m, season):
    print(f"\n--- {season}: Spearman / MAE by step (before -> after) ---")
    print(f"{'step':<5} {'pool':<9} {'n':>7} {'rho b':>8} {'rho a':>8} "
          f"{'d_rho':>7} {'mae b':>7} {'mae a':>7}")
    for s in STEPS:
        g = m[m["horizon_step"] == s]
        for pool, gg in [("all", g), ("starter", g[g["e_minutes"] >= 60])]:
            rb, ra = sp(gg["e_points_b"], gg["actual_points"]), \
                     sp(gg["e_points_a"], gg["actual_points"])
            mb = (gg["e_points_b"] - gg["actual_points"]).abs().mean()
            ma = (gg["e_points_a"] - gg["actual_points"]).abs().mean()
            print(f"{s:<5} {pool:<9} {len(gg):>7} {rb:>8.4f} {ra:>8.4f} "
                  f"{ra - rb:>+7.4f} {mb:>7.4f} {ma:>7.4f}")


def position_rho(m, season):
    print(f"\n--- {season}: starter-band Spearman by position "
          f"(before -> after) ---")
    band = m[m["e_minutes"] >= 60]
    print(f"{'step':<5}" + "".join(f"{p:>20}" for p in POSITIONS))
    for s in STEPS:
        row = f"{s:<5}"
        g = band[band["horizon_step"] == s]
        for p in POSITIONS:
            gg = g[g["position"] == p]
            row += f"  {sp(gg['e_points_b'], gg['actual_points']):>7.3f}->" \
                   f"{sp(gg['e_points_a'], gg['actual_points']):<8.3f}"
        print(row)


def margin_beta(m, season):
    """Through-origin pairwise slope, exact moment accumulation within
    (cutoff, position) -- at a fixed step each cutoff maps to one gw."""
    print(f"\n--- {season}: margin beta by position (before -> after) ---")
    print(f"{'step':<5}" + "".join(f"{p:>20}" for p in POSITIONS))
    for s in STEPS:
        g = m[m["horizon_step"] == s]
        row = f"{s:<5}"
        for p in POSITIONS:
            gg = g[g["position"] == p]
            betas = []
            for col in ("e_points_b", "e_points_a"):
                num = den = 0.0
                for _, grp in gg.groupby("cutoff"):
                    n = len(grp)
                    if n < 2:
                        continue
                    x, y = grp[col].values, grp["actual_points"].values
                    num += n * (x * y).sum() - x.sum() * y.sum()
                    den += n * (x * x).sum() - x.sum() ** 2
                betas.append(num / den if den else np.nan)
            row += f"  {betas[0]:>7.3f}->{betas[1]:<8.3f}"
        print(row)


def topk(m, season):
    """Per-step top-k by predicted e_points within (cutoff, position);
    realised points of the picks; paired per-cutoff deltas, RES iff
    |mean| > 2*SE. Pools per d1_topk: all rows / started (minutes >= 60)."""
    recs = []
    for s in [x for x in STEPS if x >= 1]:
        g = m[m["horizon_step"] == s]
        for (cut, pos), grp in g.groupby(["cutoff", "position"]):
            if pos not in POSITIONS:
                continue
            for pool_name, pool in [("all", grp),
                                    ("started", grp[grp["minutes"] >= 60])]:
                if len(pool) < 2:
                    continue
                for k in KS:
                    kk = min(k, len(pool))
                    pb = pool.nlargest(kk, "e_points_b")["actual_points"].mean()
                    pa = pool.nlargest(kk, "e_points_a")["actual_points"].mean()
                    recs.append({"step": s, "cutoff": cut, "pos": pos, "k": k,
                                 "pool": pool_name, "b": pb, "a": pa})
    r = pd.DataFrame(recs)

    n_res = n_tot = 0
    res_rows = []
    for (s, pos, k, pool), grp in r.groupby(["step", "pos", "k", "pool"]):
        d = grp["a"] - grp["b"]
        if len(d) < 3:
            continue
        se2 = 2 * d.std() / np.sqrt(len(d))
        n_tot += 1
        if abs(d.mean()) > se2:
            n_res += 1
            res_rows.append((s, pos, k, pool, d.mean(), se2))
    print(f"\n--- {season}: top-k resolution over (step 1-5 x pos x k x pool) "
          f"cells ---")
    print(f"  resolved {n_res} of {n_tot} (chance ~{0.05 * n_tot:.1f})")
    for s, pos, k, pool, dm, se2 in sorted(res_rows):
        print(f"    RES step {s} {pos} k={k} {pool}: {dm:+.3f} [2SE {se2:.3f}]")

    # step-3 exemplar with per-cutoff spread (mean (SD)), house format
    print(f"  step-3 detail, mean realised pts of top-k (SD across cutoffs):")
    print(f"  {'pos':<5}{'k':>3} {'pool':<9} {'before':>14} {'after':>14} "
          f"{'delta [2SE]':>16}")
    g3 = r[r["step"] == 3]
    for pos in POSITIONS:
        for k in KS:
            for pool in ("all", "started"):
                grp = g3[(g3["pos"] == pos) & (g3["k"] == k)
                         & (g3["pool"] == pool)]
                if len(grp) < 3:
                    continue
                d = grp["a"] - grp["b"]
                se2 = 2 * d.std() / np.sqrt(len(d))
                tag = " RES" if abs(d.mean()) > se2 else ""
                print(f"  {pos:<5}{k:>3} {pool:<9} "
                      f"{grp['b'].mean():>7.3f} ({grp['b'].std():5.3f}) "
                      f"{grp['a'].mean():>7.3f} ({grp['a'].std():5.3f}) "
                      f"{d.mean():>+8.3f} [{se2:.3f}]{tag}")
    return r


def horizon_sum_topk(m, season):
    """Planner-grain: per cutoff, rank by SUMMED e_points over steps 1-5 (the
    forward horizon the synthetic changes), realised sum over the same gws.
    All-rows pool -- a per-gw started restriction has no clean sum analogue."""
    fwd = m[m["horizon_step"] >= 1]
    agg = (fwd.groupby(["cutoff", "position", "element"])
           .agg(eb=("e_points_b", "sum"), ea=("e_points_a", "sum"),
                act=("actual_points", "sum"), n=("gw", "size")).reset_index())
    full = agg[agg["n"] == agg.groupby("cutoff")["n"].transform("max")]
    print(f"\n--- {season}: horizon-sum top-k (steps 1-5 summed, all pool) ---")
    print(f"  {'pos':<5}{'k':>3} {'before':>14} {'after':>14} {'delta [2SE]':>16}")
    for pos in POSITIONS:
        for k in KS:
            rows = []
            for cut, grp in full[full["position"] == pos].groupby("cutoff"):
                if len(grp) < k:
                    continue
                rows.append((grp.nlargest(k, "eb")["act"].mean(),
                             grp.nlargest(k, "ea")["act"].mean()))
            if len(rows) < 3:
                continue
            b = np.array([x for x, _ in rows]); a = np.array([y for _, y in rows])
            d = a - b
            se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
            tag = " RES" if abs(d.mean()) > se2 else ""
            print(f"  {pos:<5}{k:>3} {b.mean():>7.3f} ({b.std():5.3f}) "
                  f"{a.mean():>7.3f} ({a.std():5.3f}) "
                  f"{d.mean():>+8.3f} [{se2:.3f}]{tag}")


def agreement(m, season):
    """Model-vs-model, deterministic: same-#1 share and mean top-5 overlap
    within (cutoff, position), per step, all-rows pool (d1_agreement part 1)."""
    print(f"\n--- {season}: agreement (same-#1 / mean top-5 overlap of 5) ---")
    print(f"{'step':<5}" + "".join(f"{p:>18}" for p in POSITIONS))
    for s in [x for x in STEPS if x >= 1]:
        g = m[m["horizon_step"] == s]
        row = f"{s:<5}"
        for pos in POSITIONS:
            gg = g[g["position"] == pos]
            same1, ovl = [], []
            for _, grp in gg.groupby("cutoff"):
                if len(grp) < 5:
                    continue
                tb = grp.nlargest(5, "e_points_b")
                ta = grp.nlargest(5, "e_points_a")
                same1.append(int(tb.index[0] == ta.index[0]))
                ovl.append(len(set(tb.index) & set(ta.index)))
            row += f"  {np.mean(same1):>6.0%}/{np.mean(ovl):<8.2f}"
        print(row)


def main():
    import sys
    wanted = sys.argv[1:] or list(PAIRS)
    print("=== provenance ===")
    frames = {}
    for season, (pb, pa) in {s: PAIRS[s] for s in wanted}.items():
        b, a = load(pb), load(pa)
        provenance(b, a, season)
        frames[season] = (b, a)

    print("\n=== step-0 bit-exactness ===")
    all_exact = all(step0_bitexact(b, a, s) for s, (b, a) in frames.items())
    print(f"  ALL SEASONS BIT-EXACT: {all_exact}")

    for season, (b, a) in frames.items():
        m = merged(b, a)
        accuracy_tables(m, season)
        position_rho(m, season)
        margin_beta(m, season)
        topk(m, season)
        horizon_sum_topk(m, season)
        agreement(m, season)


if __name__ == "__main__":
    main()
