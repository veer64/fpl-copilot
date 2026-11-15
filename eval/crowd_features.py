"""As-of crowd features -- written as PROBE CODE for the P(start) probe (M2, model-upgrade plan step 2).
Since M3 (2026-11-15) squad/crowd_block.py imports the formulas, the snapshot reader and the join from here
to offer the features to the minutes model, behind minutes.CROWD_FEATURES_ACTIVE -- which rests False, so
with the gate off nothing in production imports this module and it changes no prediction.

This is Probe A's feature builder (X2 review, PR-6; C:\\dev\\research\\x2\\scripts\\pr6_build_crowd.py) brought
into the repo, the formulas unchanged, extended to read the live season's snapshots (gzip) beside the
fplcache ones (xz).

FIVE FEATURES, from the ONE bootstrap-static snapshot that data/availability_{tag}.parquet already names for
each gameweek -- the last snapshot STRICTLY BEFORE that gameweek's deadline (eval/build_availability.py for the
fplcache seasons; the live archive for 2026-27):
    cs_own_pct            selected_by_percent
    cs_out_ratio          transfers_out_event / owners      owners = own% x total_players, floored at 1
    cs_in_ratio           transfers_in_event / owners
    cs_net_log            sign(net) * log1p(|net|)          net = in - out
    cs_cost_change_event  cost_change_event
A player the snapshot does not carry gets NaN (LightGBM's missing value), never a zero.

LEAK RULE. The availability file is read for WHICH snapshot and nothing else (NAMING_COLUMNS). The features are
the raw fields of that snapshot: never the asof_ late-news patch (it is reconstructed from a later snapshot), and
never the history table's `selected` / `transfers_in` / `transfers_out`, which are the deadline-FINAL counts.

TIMING. The fplcache seasons' snapshot sits a median 3.7-4.7 hours before the deadline (and holds about 85% of
the week's transfers -- X2 evidence 36); the live season's sits about ten minutes before. to_ranks() is the
declared answer to that skew: the four flow features as within-gameweek percentile ranks.

Usage:
    uv run python eval/crowd_features.py --out data/m2/crowd_asof.parquet        # never overwrites
"""
import argparse
import gzip
import json
import lzma
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent

CROWD = ["cs_own_pct", "cs_out_ratio", "cs_in_ratio", "cs_net_log", "cs_cost_change_event"]
FLOW = CROWD[1:]                                  # everything but ownership
RANKED = [c + "_rk" for c in FLOW]                # the secondary arm's columns
AVAIL_TAG = {"2022-23": "2223", "2023-24": "2324", "2024-25": "2425", "2025-26": "2526", "2026-27": "2627"}
NAMING_COLUMNS = ["gw", "snapshot_path", "snapshot_time", "deadline_time", "hours_before_deadline"]
RAW = ["season", "GW", "element", "own_pct", "tin", "tout", "now_cost", "cost_change_event",
       "cost_change_start", "total_players", "hours_before_deadline"]


def read_snapshot(path):
    """One bootstrap-static payload: fplcache writes .json.xz, the live archive .json.gz."""
    p = Path(path)
    if p.name.endswith(".json.xz"):
        opener = lzma.open
    elif p.name.endswith(".json.gz"):
        opener = gzip.open
    else:
        raise ValueError(f"not a bootstrap snapshot this builder reads (.json.xz / .json.gz): {p.name}")
    with opener(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def snapshot_table(av):
    """One row per gameweek: the snapshot the availability file names. Refuses a snapshot at or after the
    deadline, and two snapshots for one gameweek."""
    per = av[NAMING_COLUMNS].drop_duplicates(["gw", "snapshot_path"]).sort_values("gw").reset_index(drop=True)
    assert not per["gw"].duplicated().any(), \
        f"one snapshot per gameweek expected, found several for gameweek(s) {sorted(per.loc[per['gw'].duplicated(), 'gw'].unique())}"
    late = per[per["snapshot_time"] >= per["deadline_time"]]
    assert late.empty, f"a snapshot must be strictly before its deadline; gameweek(s) {late['gw'].tolist()} are not"
    return per


def rows_from_payload(season, gw, payload, hours_before_deadline):
    """The raw fields of one snapshot, one row per player."""
    tp = payload.get("total_players") or np.nan
    rows = [(season, int(gw), int(e["id"]), float(e.get("selected_by_percent") or 0.0),
             e.get("transfers_in_event"), e.get("transfers_out_event"), e.get("now_cost"),
             e.get("cost_change_event"), e.get("cost_change_start"), tp, float(hours_before_deadline))
            for e in payload["elements"]]
    return pd.DataFrame(rows, columns=RAW)


def features(d):
    """Add the five features to raw snapshot rows. Probe A's formulas, unchanged."""
    d = d.copy()
    owners = (d["own_pct"] / 100.0 * d["total_players"]).clip(lower=1.0)
    d["cs_own_pct"] = d["own_pct"]
    d["cs_out_ratio"] = d["tout"] / owners
    d["cs_in_ratio"] = d["tin"] / owners
    net = d["tin"] - d["tout"]
    d["cs_net_log"] = np.sign(net) * np.log1p(net.abs())
    d["cs_cost_change_event"] = d["cost_change_event"]
    return d


def build(seasons, data_dir=None, repo=None, verbose=False):
    """Crowd features for every gameweek of `seasons`, keyed (season, GW, element)."""
    data_dir = Path(data_dir) if data_dir else REPO / "data"
    repo = Path(repo) if repo else REPO
    parts = []
    for season in seasons:
        av = pd.read_parquet(data_dir / f"availability_{AVAIL_TAG[season]}.parquet", columns=NAMING_COLUMNS)
        per = snapshot_table(av)
        for r in per.itertuples():
            p = Path(r.snapshot_path)
            raw = rows_from_payload(season, r.gw, read_snapshot(p if p.is_absolute() else repo / p), r.hours_before_deadline)
            raw["snapshot_path"] = r.snapshot_path
            raw["snapshot_time"] = r.snapshot_time
            raw["deadline_time"] = r.deadline_time
            parts.append(raw)
        if verbose:
            print(f"{season}: gameweeks {len(per)} (first {int(per.gw.iloc[0])}, last {int(per.gw.iloc[-1])}); "
                  f"first / last snapshot {per.snapshot_path.iloc[0]} / {per.snapshot_path.iloc[-1]}", flush=True)
    d = features(pd.concat(parts, ignore_index=True))
    assert not d.duplicated(["season", "GW", "element"]).any()
    return d


def to_ranks(crowd):
    """The secondary arm: each of the four flow features as its percentile rank WITHIN the gameweek (average
    rank over the values present, so 0 < rank <= 1; a missing value stays missing). Ownership is left as it is.
    A rank does not care how much of the week's transfers the snapshot had seen."""
    out = crowd.copy()
    g = out.groupby(["season", "GW"], sort=False)
    for c in FLOW:
        out[c + "_rk"] = g[c].rank(method="average", pct=True)
    return out


def attach(col, crowd, cols=None):
    """Left-join crowd columns onto a collapsed player-gameweek frame. No snapshot row -> NaN."""
    cols = list(CROWD if cols is None else cols)
    n = len(col)
    out = col.merge(crowd[["season", "GW", "element"] + cols], on=["season", "element", "GW"], how="left")
    if len(out) != n:
        raise ValueError(f"crowd join changed the row count: {n} -> {len(out)}")
    return out


def timing_table(crowd):
    """Hours before the deadline of each gameweek's snapshot, per season: the declared skew check."""
    per = crowd.drop_duplicates(["season", "GW"])
    return (per.groupby("season")["hours_before_deadline"]
            .agg(gameweeks="size", median="median", min="min", max="max").round(3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default=",".join(AVAIL_TAG))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.out.exists():
        raise FileExistsError(f"{a.out} exists -- a probe output is never written over")
    d = to_ranks(build(a.seasons.split(","), verbose=True))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(a.out, index=False)
    print(f"rows {len(d):,} | by season {d.groupby('season').size().to_dict()} -> {a.out}")
    print(timing_table(d).to_string())
    print(d[CROWD + ["total_players"]].describe().round(3).to_string())


if __name__ == "__main__":
    main()
