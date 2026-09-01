# season_stack.py
# ONE resolver for the cross-season player-fixture stack.
#
# The frozen archive (all_seasons_fixed.parquet, vaastav-sourced, 2016-17..
# 2025-26) is never modified; live seasons are appended by
# eval/fetch_fpl_history.py --combine as all_seasons_with_{tag}.parquet
# (archive rows byte-identical, order- and dtype-preserved -- proven by the
# 2025-26 live-parity suite staying bit-identical through the repointing).
# Every vaastav-shaped consumer (minutes, bonus, the walk-forward skeleton and
# penalty-rate path, live_deadline's detectors) resolves the file through
# stack_path() so a new season lands in ONE place.
#
# Resolution: the newest all_seasons_with_*.parquet if any exists (lexically
# newest -- season tags sort chronologically), else the frozen archive.
# Repo-relative, portable (no drive-letter constants; this code also runs on
# the Linux droplet).

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HISTORY = REPO / "data" / "history"


def stack_path():
    combined = sorted(HISTORY.glob("all_seasons_with_*.parquet"))
    return combined[-1] if combined else HISTORY / "all_seasons_fixed.parquet"


def forward_path():
    """The forward-gameweek skeleton (eval/build_forward_skeleton.py): SYNTHETIC
    player-fixture rows for gameweeks the master does not carry yet, measurement
    columns NaN. None if no skeleton has been built."""
    fwd = sorted(HISTORY.glob("forward_skeleton_*.parquet"))
    return fwd[-1] if fwd else None


def load_stack(columns=None):
    """The stack PLUS the forward skeleton -- what a LIVE build must see: the
    calendar, the minutes-prediction universe and the assembly row universe for
    unplayed gameweeks all derive from these rows. Consumers that must NOT see
    synthetic rows (actuals semantics -- e.g. live_deadline's postflight
    penalty-aggregate check, the ingestion verifiers) keep reading stack_path()
    directly. NOTE: concat upcasts the master's int64 stat columns to float64
    where the skeleton carries NaN (minutes, total_points, bps, ...) -- the
    2025-26 parity suite proves this bit-identical for historical builds.
    Asserts the skeleton never collides with a fixture the master carries."""
    import pandas as pd
    df = pd.read_parquet(stack_path(), columns=columns)
    fp = forward_path()
    if fp is None:
        return df
    fwd = pd.read_parquet(fp, columns=columns)
    if not len(fwd):
        return df
    if columns is None or {"season", "fixture"} <= set(fwd.columns):
        seasons = set(fwd["season"].unique())
        in_master = df[df["season"].isin(seasons)]
        dup = (set(zip(in_master["season"], in_master["fixture"].astype(int)))
               & set(zip(fwd["season"], fwd["fixture"].astype(int))))
        assert not dup, f"forward skeleton collides with master fixtures (stale skeleton): {sorted(dup)[:5]}"
    return pd.concat([df, fwd], ignore_index=True)
