"""Quantifies the TC2/BB2 same-week collision on the frozen fslog paths: doubles inventory per season (walkforward n_fixtures), the drop-smaller-read cost per cell (3/7/13), and where the displaced chip would go under a corrected rule (keep BB2; TC2 -> largest remaining double). Result of record: not yet in a log (reported 2026-08-24, pending the TC2/BB2 correction decision); provenance for the proposed chip-set legality assert in eval/build_season_totals_index.py. Read-only; no simulations."""
# 3c/3d: doubles inventory per season + cost of the TC2/BB2 same-week
# collision + where the displaced chip would go. READ-ONLY, no simulations.
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parent.parent  # repo root; rescued 2026-08-24 from a hardcoded absolute path
P1 = REPO / "data" / "p1"
SEASONS = ["2023-24", "2024-25", "2025-26"]

for season in SEASONS:
    tag = season.replace("-", "_")
    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    wf = pd.read_parquet(wf_path,
                         columns=["cutoff", "gw", "team", "n_fixtures"])
    own = wf[wf["cutoff"] == wf["gw"]]
    dbl = own[own["n_fixtures"] >= 2]
    inv = dbl.groupby("gw")["team"].nunique()
    print(f"\n=== {season} (doubles via n_fixtures >= 2, own cutoff) ===")
    print("doubles inventory (gw -> doubling teams):")
    print("  " + "  ".join(f"GW{g}:{int(v)}" for g, v in inv.items()))
    h2 = inv[inv.index >= 20]
    print(f"  largest overall: GW{inv.idxmax()} ({int(inv.max())}) | "
          f"largest H2: GW{h2.idxmax()} ({int(h2.max())})"
          + ("  <-- SAME WEEK (collision by construction)"
             if inv.idxmax() == h2.idxmax() else "  <-- DIFFERENT"))

    # reads off the reference cell's own frozen path
    d = pd.read_parquet(P1 / f"fslog_{tag}_base_wc2.parquet").set_index("gw")
    bb1, bb2 = int(d["bb1"].iloc[0]), int(d["bb2"].iloc[0])
    wc2, fh2 = int(d["wc2"].iloc[0]), int(d["fh2"].iloc[0])
    bench, cap = d["bench_points"], d["captain_bonus"]
    print(f"  scheduled: wc1=2 wc2={wc2} fh2={fh2} bb1={bb1} bb2={bb2}")
    print(f"  shared week GW{bb2}: bench {int(bench.loc[bb2])}, "
          f"TC2 cap {int(cap.loc[bb2])}  -> drop-smaller cost "
          f"{min(int(bench.loc[bb2]), int(cap.loc[bb2]))}")

    # option A: keep BB2 there; TC2 -> largest double EXCLUDING bb2 (and any
    # other chip week); if no other double, best realized captain week in H2
    # excluding chip weeks (upper bound for a predicted-peak rule).
    used = {2, wc2, fh2, bb1, bb2}
    alts = inv.drop(index=[g for g in used if g in inv.index])
    if len(alts):
        best_dbl = alts.idxmax()
        print(f"  option A (keep BB2@{bb2}): TC2 -> GW{best_dbl} "
              f"({int(alts.max())} doubling teams), realized cap there "
              f"{int(cap.loc[best_dbl])}")
        a_total = int(bench.loc[bb2]) + int(cap.loc[best_dbl])
    else:
        h2caps = cap[(cap.index >= 20) & ~cap.index.isin(used)]
        print(f"  option A (keep BB2@{bb2}): no other double all season; "
              f"best realized H2 cap week GW{h2caps.idxmax()} "
              f"(+{int(h2caps.max())}) [upper bound for a predicted rule]")
        a_total = int(bench.loc[bb2]) + int(h2caps.max())

    # option B: keep TC2 there; BB2 -> next-most-doubling H2 week with >=4
    # floor, excluding chip weeks. Bench read there is a LOWER bound: the
    # bench-aware solver targeted the original bb2, not this week.
    h2alts = inv[(inv.index >= 20) & (inv >= 4) & ~inv.index.isin(used)]
    if len(h2alts):
        b_wk = h2alts.idxmax()
        print(f"  option B (keep TC2@{bb2}): BB2 -> GW{b_wk} "
              f"({int(h2alts.max())} doubling teams), realized bench there "
              f"{int(bench.loc[b_wk])} [lower bound -- solver not aimed at it]")
        b_total = int(cap.loc[bb2]) + int(bench.loc[b_wk])
    else:
        print(f"  option B (keep TC2@{bb2}): NO other H2 double meets the "
              f">=4 floor -- BB2 has nowhere legal to go")
        b_total = None
    print(f"  legal-total comparison on this frozen path: "
          f"A={a_total}" + (f"  B={b_total}" if b_total is not None else "  B=n/a")
          + f"  (illegal convention counted {int(bench.loc[bb2]) + int(cap.loc[bb2])})")

# cost across ALL fslog cells (what the index's chip-incl overstates per cell)
print("\n=== drop-smaller cost per fslog cell (min(TC2 cap, bench@bb2)) ===")
for p in sorted(P1.glob("fslog_*.parquet")):
    d = pd.read_parquet(p).set_index("gw")
    bb2 = int(d["bb2"].iloc[0])
    c = min(int(d.loc[bb2, "bench_points"]), int(d.loc[bb2, "captain_bonus"]))
    print(f"  {p.name}: {c}")
