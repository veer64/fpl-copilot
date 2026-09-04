"""Make the live 2026-27 availability visible to the model. availability_features.load()
globs data/availability_*.parquet (non-recursive), so the two live archives under
data/live/ are invisible and a 2026-27 build would silently run with the whole block at
UNKNOWN(-1)/0/NaN. This merger writes data/availability_2627.parquet -- the data/
naming convention (availability_2526.parquet), the exact schema of the historical files
(read at runtime), season column "2026-27" mandatory in the join key, asof_* columns
carried verbatim from the sources (the as-of discipline is not weakened: the raw
snapshot columns ride along exactly as they do in the historical files, and consumers
keep reading only asof_*).

AUTHORITY RULE, per (season, element, gw): the D6 POLLER wins where it has a row -- it
samples every 10 minutes near the deadline and caught three status flips fplcache
missed on GW2 -- and fplcache (~4x/day snapshots) fills every other key. Disagreements
on overlapping keys are COUNTED per column and recorded in the provenance sidecar,
never silently resolved; asof_source keeps the per-row provenance distinct by design
('live_snapshot'/'live_late_news' = poller, 'snapshot'/'late_news' = fplcache).

The output is DERIVED state: fully regenerated from the two live archives on each run
(idempotent; run after every deadline alongside the poller's --build). The archives
themselves are never modified. Uniqueness on (season, element, gw) is asserted here
and again by availability_features.attach()'s row-count guard.

Usage: uv run python eval/merge_live_availability.py --season 2026-27
"""
import argparse
import json
import os
from _replace_retry import replace_with_retry
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "data" / "live"


def merge(season):
    compact = season.replace("-", "")                    # "2026-27" -> "202627"
    tag_short = compact[2:4] + compact[4:6]              # -> "2627" (the data/ convention)
    assert len(tag_short) == 4 and tag_short.isdigit(), tag_short
    ref = pd.read_parquet(REPO / "data" / "availability_2526.parquet").iloc[0:0]
    poller = pd.read_parquet(LIVE / f"availability_{season.replace('-', '_')}_live.parquet")
    fplc = pd.read_parquet(LIVE / f"availability_{season}_fplcache.parquet")
    for name, d in (("poller", poller), ("fplcache", fplc)):
        assert list(d.columns) == list(ref.columns), f"{name} schema differs from the historical files"
        assert (d["season"] == season).all(), f"{name} carries a season other than {season}"
        assert not d.duplicated(["season", "element", "gw"]).any(), f"{name} has duplicate keys"
    key = ["season", "element", "gw"]
    overlap = poller.merge(fplc, on=key, suffixes=("_p", "_f"))
    disagreements = {}
    for c in ("asof_status", "asof_chance_of_playing_this_round", "asof_news"):
        a, b = overlap[f"{c}_p"], overlap[f"{c}_f"]
        n = int((a.astype(str).fillna("<na>") != b.astype(str).fillna("<na>")).sum())
        if n:
            disagreements[c] = n
    fpl_only = fplc.merge(poller[key], on=key, how="left", indicator=True)
    fpl_only = fpl_only[fpl_only["_merge"] == "left_only"].drop(columns="_merge")
    merged = (pd.concat([poller, fpl_only], ignore_index=True)
              .sort_values(key).reset_index(drop=True))
    assert not merged.duplicated(key).any(), "merged file has duplicate (season, element, gw)"
    for c in ref.columns:
        merged[c] = merged[c].astype(ref[c].dtype)
    merged = merged[list(ref.columns)]
    out = REPO / "data" / f"availability_{tag_short}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    merged.to_parquet(tmp, index=False)
    replace_with_retry(tmp, out)
    prov = dict(season=season, built_at=datetime.now(timezone.utc).isoformat(),
                rows=len(merged), poller_rows=len(poller), fplcache_only_rows=len(fpl_only),
                overlap_keys=len(overlap), overlap_disagreements=disagreements,
                authority="poller wins per (season, element, gw); fplcache fills the rest",
                gws=sorted(int(g) for g in merged["gw"].unique()))
    out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    print(f"-> {out.name}: {len(merged)} rows ({len(poller)} poller-authoritative + "
          f"{len(fpl_only)} fplcache-only); overlap {len(overlap)} keys, "
          f"disagreements {disagreements or 'none'}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026-27")
    a = ap.parse_args()
    merge(a.season)


if __name__ == "__main__":
    main()
