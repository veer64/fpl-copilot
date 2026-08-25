"""Training-data scope for a horizon minutes model: `starts` label availability per season on disk (2022-23 GW1-15 quarantine), walkforward_season.LABELLED and minutes.TRAIN_SEASONS. Result of record: Logs/horizon_minutes_scoping_log.md section 4 (four labelled seasons, three simulable; KNOWN_ISSUES #11 blocks simulation, not training). Read-only."""
# Task 4: training-data scope -- starts label per season on disk. Read-only.
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parent.parent  # repo root; rescued 2026-08-24 from a hardcoded absolute path
h = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet",
                    columns=["season", "GW", "starts", "minutes"])
h["starts"] = pd.to_numeric(h["starts"], errors="coerce")
print(f"{'season':8s} {'rows':>7s} {'starts non-null':>15s} {'%':>6s}  quarantine (GW1-15 null)")
for s, g in h.groupby("season"):
    q = g[(g["GW"] <= 15)]
    print(f"{s:8s} {len(g):7,d} {int(g['starts'].notna().sum()):15,d} {g['starts'].notna().mean():6.1%}  "
          f"{int(q['starts'].isna().sum()):,} of {len(q):,} GW1-15 rows null")
import re
src = (REPO / "eval/walkforward_season.py").read_text(encoding="utf-8")
for name in ("ORDER", "LABELLED"):
    m = re.search(rf"^{name}\s*=\s*(.+)$", src, re.M)
    print(f"walkforward_season.{name} = {m.group(1) if m else '?'}")
src2 = (REPO / "squad/minutes.py").read_text(encoding="utf-8")
m = re.search(r"^TRAIN_SEASONS\s*=\s*(.+)$", src2, re.M)
print(f"minutes.TRAIN_SEASONS = {m.group(1)}")
