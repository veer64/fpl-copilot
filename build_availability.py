#!/usr/bin/env python
"""
Build data/availability_{season}.parquet from the fplcache bootstrap-static archive.

For every gameweek, we take the availability state (status / chance_of_playing_* /
news / news_added) from the LAST cached bootstrap snapshot STRICTLY BEFORE that
gameweek's deadline. Deadlines are read from the `events` array of a late-season
snapshot, so all 38 are final.

fplcache/ is a third-party clone (Randdalf/fplcache, Unlicense) and is gitignored.
Snapshot timestamps come from the cache path {year}/{month}/{day}/{HHMM}.json.xz,
which cache.py writes from the GitHub Actions runner clock (UTC).

Usage:
    uv run python build_availability.py                    # 2025-26
    uv run python build_availability.py --season 2024-25
"""

import argparse
import json
import lzma
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CACHE = Path("fplcache/cache")
OUT_DIR = Path("data")

FIELDS = [
    "status",
    "chance_of_playing_this_round",
    "chance_of_playing_next_round",
    "news",
    "news_added",
]


def list_snapshots(cache: Path) -> list[tuple[datetime, Path]]:
    """All cached snapshots as (utc_time, path), ascending. Time is parsed from the path."""
    snaps = []
    for f in cache.glob("*/*/*/*.json.xz"):
        year, month, day = int(f.parts[-4]), int(f.parts[-3]), int(f.parts[-2])
        hhmm = f.name.split(".")[0]
        ts = datetime(year, month, day, int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc)
        snaps.append((ts, f))
    snaps.sort()
    return snaps


def load(path: Path) -> dict:
    with lzma.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _ts(v) -> datetime | None:
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None


def late_news(snaps, snap_ts: datetime, deadline: datetime) -> dict[int, dict]:
    """Elements whose news broke between the last pre-deadline snapshot and the deadline.

    With four snapshots a day the last one lands up to ~6h before the deadline, so news
    published in that window is invisible to it — Gvardiol's GW1 injury landed 68 minutes
    after our snapshot and 3.5h before the deadline. But `news_added` survives into later
    snapshots, so the first post-deadline snapshot lets us recover exactly what a manager
    (and production, reading the field live) would have seen at the deadline.

    This is a reconstruction, not a leak: we only accept items stamped strictly before the
    deadline, and only when `news_added` moved forward versus the pre-deadline snapshot.
    Every other element is read from the pre-deadline snapshot and never touched here.

    Caveat: FPL does not bump `news_added` when it clears news or silently edits
    `chance_of_playing_*`, so this recovers new news only. That errs toward keeping a stale
    flag rather than inventing a fresh one, which is the safe direction.
    """
    after = [(ts, p) for ts, p in snaps if ts >= deadline]
    if not after:
        return {}
    payload = load(after[0][1])
    return {
        e["id"]: e
        for e in payload["elements"]
        if e.get("news_added") and snap_ts < _ts(e["news_added"]) < deadline
    }


def find_reference(snaps, season_start_year: int) -> tuple[Path, list[dict]]:
    """Latest snapshot still serving the target season, scanning backwards.

    FPL rolls bootstrap-static over to the next season in the summer, so the newest
    snapshots describe a different season. We identify the season by the GW1 deadline.
    """
    prefix = f"{season_start_year}-0"
    # FPL rolls over during the following summer, so start just before that and walk back.
    cutoff = datetime(season_start_year + 1, 8, 1, tzinfo=timezone.utc)
    for ts, path in reversed([s for s in snaps if s[0] < cutoff]):
        events = load(path)["events"]
        if events and events[0]["deadline_time"].startswith(prefix):
            if len(events) != 38:
                continue
            return path, events
    raise RuntimeError(f"no snapshot found serving season starting {season_start_year}")


def build(season: str, cache: Path = CACHE) -> pd.DataFrame:
    season_start_year = int(season.split("-")[0])
    snaps = list_snapshots(cache)
    if not snaps:
        raise RuntimeError(f"no snapshots under {cache}")

    ref_path, events = find_reference(snaps, season_start_year)
    unfinished = [e["id"] for e in events if not e["finished"]]
    print(f"deadlines from {ref_path} ({len(events)} events, unfinished: {unfinished or 'none'})")

    deadlines = {
        e["id"]: datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))
        for e in events
    }

    rows = []
    for gw in sorted(deadlines):
        deadline = deadlines[gw]
        # Last snapshot STRICTLY before the deadline. `<` not `<=` — a snapshot taken
        # at the deadline is already post-deadline information.
        prior = [(ts, p) for ts, p in snaps if ts < deadline]
        if not prior:
            raise RuntimeError(f"GW{gw}: no snapshot before deadline {deadline}")
        snap_ts, snap_path = prior[-1]
        assert snap_ts < deadline, f"GW{gw}: leak — snapshot {snap_ts} >= deadline {deadline}"

        payload = load(snap_path)
        hours_before = (deadline - snap_ts).total_seconds() / 3600.0

        # Cross-check the path-derived timestamp against the payload: FPL cannot have
        # stamped a news item after the moment we fetched the file.
        stamps = [_ts(e.get("news_added")) for e in payload["elements"] if e.get("news_added")]
        if stamps:
            latest = max(stamps)
            assert latest <= snap_ts, (
                f"GW{gw}: snapshot {snap_path} has news_added {latest} after its "
                f"path timestamp {snap_ts} — path time is not trustworthy"
            )

        late = late_news(snaps, snap_ts, deadline)

        for el in payload["elements"]:
            row = {"gw": gw, "element": el["id"]}
            row.update({f: el.get(f) for f in FIELDS})
            row["snapshot_time"] = snap_ts
            row["deadline_time"] = deadline
            row["hours_before_deadline"] = hours_before
            row["snapshot_path"] = str(snap_path.as_posix())

            # As-of-deadline reconstruction (see late_news()).
            patch = late.get(el["id"])
            fresh = patch is not None and _ts(patch.get("news_added")) > (
                _ts(el.get("news_added")) or datetime.min.replace(tzinfo=timezone.utc)
            )
            src = patch if fresh else el
            row.update({f"asof_{f}": src.get(f) for f in FIELDS})
            row["asof_source"] = "late_news" if fresh else "snapshot"
            rows.append(row)

    df = pd.DataFrame(rows)
    # Element IDs are only unique WITHIN a season, so every downstream join needs
    # the season alongside them.
    df["season"] = season
    for c in ("news_added", "asof_news_added"):
        df[c] = pd.to_datetime(df[c], format="ISO8601", utc=True)
    df["snapshot_time"] = pd.to_datetime(df["snapshot_time"], utc=True)
    df["deadline_time"] = pd.to_datetime(df["deadline_time"], utc=True)
    for c in ("chance_of_playing_this_round", "chance_of_playing_next_round"):
        # nullable — null means "no news", not 0
        df[c] = df[c].astype("Float64")
        df[f"asof_{c}"] = df[f"asof_{c}"].astype("Float64")
    df["element"] = df["element"].astype("int32")
    df["gw"] = df["gw"].astype("int8")

    # Final leak assertions over the built frame.
    assert (df["snapshot_time"] < df["deadline_time"]).all(), "leak: snapshot at/after deadline"
    stale = df["news_added"].notna() & (df["news_added"] > df["snapshot_time"])
    assert not stale.any(), f"leak: {stale.sum()} rows with news_added after snapshot_time"
    ahead = df["asof_news_added"].notna() & (df["asof_news_added"] >= df["deadline_time"])
    assert not ahead.any(), f"leak: {ahead.sum()} rows with asof_news_added at/after deadline"
    assert not df.duplicated(["gw", "element"]).any(), "duplicate (gw, element)"

    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    df = build(args.season, args.cache)
    # 2025-26 -> availability_2526.parquet, matching the project's naming elsewhere.
    tag = args.season[2:4] + args.season[5:7]
    out = args.out or OUT_DIR / f"availability_{tag}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    h = df.groupby("gw")["hours_before_deadline"].first()
    print(f"\nwrote {out}: {len(df):,} rows, {df.gw.nunique()} gameweeks, "
          f"{df.element.nunique()} elements")
    print(f"hours_before_deadline: min={h.min():.2f} median={h.median():.2f} max={h.max():.2f}")
    worst = h.sort_values(ascending=False).head(5)
    print("largest gaps: " + ", ".join(f"GW{gw}={v:.2f}h" for gw, v in worst.items()))
    n_late = (df["asof_source"] == "late_news").sum()
    flipped = ((df["asof_source"] == "late_news") & (df["status"] == "a")
               & (df["asof_status"] != "a")).sum()
    print(f"as-of-deadline reconstruction: {n_late} rows recovered from post-deadline "
          f"news_added, {flipped} of them flipping status a -> not-a")


if __name__ == "__main__":
    main()
