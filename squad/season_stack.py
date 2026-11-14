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
#
# ONE ROW PER (season, element, fixture) -- 2026-11-14, KNOWN_ISSUES #17. The
# archive is "never modified" with ONE exception: it inherited 69 repeated
# fixture rows from vaastav, removed once by eval/fetch_fpl_history.py
# --dedupe-archive; --combine leaves repeated rows out of every stack it
# builds. The rule is dedupe_fixture_rows below. Do not keep a preserved copy
# of a combined stack in data/history under an all_seasons_with_* name: the
# resolver takes the lexically LAST one and "_" sorts after ".".

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


FIXTURE_ROW_KEY = ["season", "element", "fixture"]


def dedupe_fixture_rows(df):
    """One row per (season, element, fixture): the PLAYED row. Returns (clean, removed).

    WHY (KNOWN_ISSUES #17, closed 2026-11-14 by M1; cause located by the X2 review). The
    vaastav-sourced archive carried repeated fixture rows of two kinds, and every consumer
    that sums a player's rows per gameweek summed them:
      * 2025-26 -- ten BYTE-IDENTICAL pairs (element 100, gameweeks 1-9; element 391,
        gameweek 1), already repeated in the public vaastav file. In the frame of record
        they doubled those players' expected minutes and points on ten rows and their
        ACTUAL points on six.
      * 2019-20 -- fifty-nine phantom rows: fixture 275 was postponed from gameweek 29 and
        played in gameweek 39; the archive kept a 0-minute row at the original gameweek
        beside the real row at the replayed one.
    RULE: within a group keep the row with the most minutes; a tie goes to the later
    gameweek (the one the match was played in); exact copies keep the first. Two DIFFERENT
    rows that both carry minutes for one fixture are not a recording duplicate and are
    refused rather than chosen between. The survivors keep their order and dtypes; a frame
    with nothing to remove is returned as the same object.

    Called by the stack builder (eval/fetch_fpl_history.combine), so every rebuilt stack is
    right whatever the archive holds, and once on the archive itself (--dedupe-archive).
    """
    import numpy as np
    key = FIXTURE_ROW_KEY
    dup = df.duplicated(key, keep=False).to_numpy()
    if not dup.any():
        return df, df.iloc[0:0].copy()
    pos = np.flatnonzero(dup)
    d = df.iloc[pos][key + ["minutes", "GW"]].copy()
    d["_pos"] = pos
    d["_minutes"] = d["minutes"].fillna(-1)
    for k, members in d[d["_minutes"] > 0].groupby(key)["_pos"].apply(list).items():
        if len(members) > 1 and len(df.iloc[members].drop_duplicates()) != 1:
            raise ValueError(f"{k}: {len(members)} DIFFERENT rows with minutes > 0 for one fixture -- "
                             "not a recording duplicate; refusing to choose between them")
    d = d.sort_values(key + ["_minutes", "GW", "_pos"],
                      ascending=[True, True, True, False, False, True], kind="stable")
    keep = set(d.drop_duplicates(key, keep="first")["_pos"])
    drop = np.array(sorted(set(pos.tolist()) - keep), dtype=int)
    mask = np.ones(len(df), dtype=bool)
    mask[drop] = False
    return df[mask].reset_index(drop=True), df.iloc[drop].copy()


def describe_removed(removed):
    """One line per season for a log: how many repeated rows went, and which ids."""
    out = []
    for season, g in removed.groupby("season"):
        els = sorted(int(e) for e in g["element"].unique())
        out.append(f"{season}: {len(g)} rows, {len(els)} elements (first {els[0]}, last {els[-1]}), "
                   f"fixtures {sorted(int(f) for f in g['fixture'].unique())}, "
                   f"gameweeks {sorted(int(x) for x in g['GW'].unique())}")
    return out


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
