"""Checks every decision log on disk for in-simulation chip collisions (any triple-captain week; any two of WC/FH/scheduled-BB sharing a week) -- establishes that the TC2/BB2 same-week collision exists ONLY in the exogenous-read accounting layer, never in a simulated path. Result of record: not yet in a log (reported 2026-08-24, pending the TC2/BB2 correction decision); the convention it audits is documented in Logs/season_totals_index.md (header) and Logs/p4_chip_policy_log.md section 12. Read-only; no simulations."""
# 3a: is the TC2/BB2 collision in the SIMULATIONS or only in the recompute
# layer? Read-only sweep of every decision log on disk.
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parent.parent  # repo root; rescued 2026-08-24 from a hardcoded absolute path
FILES = (sorted((REPO / "data/sweep").glob("simlog_*.parquet"))
         + sorted((REPO / "data/chips").glob("chiplog_*.parquet"))
         + sorted((REPO / "data/p1").glob("*log_*.parquet"))
         + sorted((REPO / "data/teamnews").glob("oraclelog_*.parquet")))

n_tc_in_sim, n_clash, n = 0, 0, 0
for p in FILES:
    d = pd.read_parquet(p)
    n += 1
    # 1) does ANY simulation flag a triple-captain week?
    if "triple_captain" in d.columns and d["triple_captain"].any():
        n_tc_in_sim += 1
        print(f"IN-SIM TC: {p.name}: gws {d.loc[d['triple_captain'], 'gw'].tolist()}")
    # 2) do any two IN-SIM chips share a week? (WC / FH per-gw flags + the
    #    scheduled BB weeks, which shape decisions via BENCH_BOOST_AWARE)
    weeks = []
    for c in ("wildcard", "free_hit"):
        if c in d.columns:
            weeks += [int(g) for g in d.loc[d[c], "gw"]]
    if "bench_boost_gws" in d.columns:
        s = str(d["bench_boost_gws"].iloc[0])
        if s and s not in ("-1", "None", "nan"):
            weeks += [int(x) for x in s.split(",")]
    elif "bench_boost_gw" in d.columns:
        v = int(d["bench_boost_gw"].iloc[0])
        if v > 0:
            weeks += [v]
    if len(weeks) != len(set(weeks)):
        n_clash += 1
        print(f"IN-SIM CLASH: {p.name}: chip weeks {sorted(weeks)}")

print(f"\n{n} logs checked: {n_tc_in_sim} with an in-sim TC week, "
      f"{n_clash} with two in-sim chips sharing a week.")
print("=> if both are 0, every simulated path is chip-legal and the "
      "collision exists ONLY in the exogenous-read (accounting) layer.")
