"""Why did one cutoff move a lot? Per-team lambda deltas (rebuilt canonical vs _pre_dcfix) at a
given season/cutoff, per horizon step, and the training-set composition at that cutoff: the
current-season matches each club had before the cutoff DAY, and which matches the OLD filter
admitted from the cutoff day. Usage: cutoff_probe.py 2023-24 3"""
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import dixon_coles as dc            # noqa: E402
import season_stack                 # noqa: E402

season, k = sys.argv[1], int(sys.argv[2])
tag = season.replace("-", "_")
new = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
old = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}_pre_dcfix.parquet")
n = new[new["cutoff"] == k]; o = old[old["cutoff"] == k]
key = ["gw", "team"]
ln = n.groupby(key)["team_lambda"].first().rename("new"); lo = o.groupby(key)["team_lambda"].first().rename("old")
lam = pd.concat([lo, ln], axis=1); lam["d"] = lam["new"] - lam["old"]; lam["step"] = lam.index.get_level_values(0) - k
print(f"{season} cutoff {k}: team_lambda deltas (new - old) by step -- the five largest |d| per step")
for st, g in lam.groupby("step"):
    g = g.reindex(g["d"].abs().sort_values(ascending=False).index)
    print(f"  step {st}: " + "; ".join(f"{t} {r.old:.3f}->{r.new:.3f} ({r.d:+.3f})" for (gw, t), r in g.head(5).iterrows()))
print(f"  mean |d| by step: {lam.groupby('step')['d'].apply(lambda s: s.abs().mean()).round(4).to_dict()}")

stack = pd.read_parquet(season_stack.stack_path())
cur = stack[stack["season"] == season]
kick = pd.to_datetime(cur["kickoff_time"])
cutoff = kick[cur["GW"] == k].min().tz_localize(None)
m = dc._load_matches(season); m = m[m["season"] == season]
day = cutoff.normalize()
before = m[dc.knowable_before(m, cutoff)]
adm = m[(m["date_parsed"] < cutoff) & ~dc.knowable_before(m, cutoff)]
print(f"\ncutoff instant {cutoff} (day {day.date()}); current-season matches knowable before the day: {len(before)}; "
      f"admitted by the OLD filter from the cutoff day: {len(adm)}")
print("  admitted:", "; ".join(f"{r.home} {int(r.home_goals)}-{int(r.away_goals)} {r.away} ({r.date_parsed.date()})" for r in adm.itertuples()))
teams = sorted(set(before["home"]) | set(before["away"]) | set(adm["home"]) | set(adm["away"]))
cnt = {t: int((before["home"] == t).sum() + (before["away"] == t).sum()) for t in teams}
print("  current-season matches per club before the cutoff day (clubs with <= 2):",
      {t: c for t, c in cnt.items() if c <= 2})
allm = dc._load_matches(season)
hist = allm[allm["season"] != season]
print("  clubs in the admitted matches with NO prior-season rows in the archive:",
      [t for t in set(adm["home"]) | set(adm["away"]) if not ((hist["home"] == t) | (hist["away"] == t)).any()])
