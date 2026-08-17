# availability_features.py
# FPL availability (status / chance_of_playing / news) as minutes-model features.
#
# Source: data/availability_{season}.parquet, built by eval/build_availability.py from the
# fplcache bootstrap-static archive. Adopted 2026-08-13; see Logs/availability_log.md
# for the measurement that justified it and for what it does NOT buy.
#
# WHY FEATURES AND NOT AN OVERRIDE
# --------------------------------
# The obvious move is to zero out flagged players after the fact. That was tried and
# lost: it deletes information rather than adding it, and it can only ever push a
# prediction DOWN. Half the measured gain here is the model raising its estimate for
# players coming BACK -- their recent history is all zeros, so the old model
# under-predicted returning starters by ~16 minutes. An override cannot do that.
#
# LEAK RULE
# ---------
# Everything here reads the availability snapshot taken strictly before THAT
# gameweek's own deadline, and derived columns look only at that deadline and earlier
# ones. Nothing is unreadable 90 minutes before the first kickoff. Production reads
# the identical bootstrap-static fields live, which is the whole point: the backtest
# and the live path consume the same field.
#
# Use the asof_* columns, never the raw snapshot ones. The cache is written 4x/day, so
# the last snapshot before a deadline can be up to ~6h stale and misses late-breaking
# news -- Gvardiol's GW1 injury landed 68 minutes after that snapshot and 3.5h before
# the deadline. The asof_* columns reconstruct the true deadline state from news_added
# without leaking. See eval/build_availability.py.

import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
AVAIL_GLOB = "availability_*.parquet"

# Free text, and the phrasing drifts between seasons -- 2025-26 says "has joined X on
# loan", 2023-24 says "Permanent transfer to X" or "Left the club by mutual consent",
# and there are outright typos ("Loaened to Derby County"). A regex alone was 89%
# accurate across the five seasons we hold, so it is NOT the primary signal: see
# is_departure() below, which anchors on status and uses text only as a supplement.
DEPARTURE = re.compile(
    r"joined|signed (?:by|for)|loan|season long|permanent|transfer|left (?:the )?club|"
    r"mutual|departed the club|released|contract (?:end|cancel|terminat)|"
    r"termination of contract|free agent|retired",
    re.I,
)


def is_departure(status: pd.Series, news: pd.Series) -> pd.Series:
    """Permanent departure: gone for the season, not carrying a temporary knock.

    Anchored on `status == 'u'`, which is a departure by construction -- 6,442 of 6,442
    such rows in 2025-26, and ~98% of them across all five seasons still match the text
    pattern even with the phrasing drift. Text matching then only has to catch the rare
    departure filed under another status, so seasonal wording changes cannot silently
    break the dominant case.
    """
    return ((status == "u") | news.fillna("").str.contains(DEPARTURE)).astype(int)


# `u` is 100% departures (6,442 of 6,442 in 2025-26) -- loan, permanent transfer or
# release. Not one injury. It is a permanent exclusion rather than a temporary state,
# so it gets a level well away from i/d/s.
STATUS_CODE = {"a": 0, "d": 1, "i": 2, "s": 3, "n": 4, "u": 5}
UNKNOWN = -1

FEATURES = [
    "av_status_code",
    "av_cop_this",
    "av_cop_next",
    "av_cop_this_known",
    "av_flag_duration",
    "av_just_flagged",
    "av_just_cleared",
    "av_news_age_days",
    "av_is_departure",
]

_CACHE = {}


def load(data_dir=None) -> pd.DataFrame:
    """All seasons of as-of-deadline availability, one row per (season, element, gw)."""
    d = Path(data_dir) if data_dir else REPO / "data"
    key = str(d)
    if key in _CACHE:
        return _CACHE[key]
    paths = [p for p in sorted(d.glob(AVAIL_GLOB)) if "measurement" not in p.stem]
    if not paths:
        raise FileNotFoundError(
            f"no {AVAIL_GLOB} under {d}. Build them first:\n"
            "    uv run python eval/build_availability.py --season 2024-25"
        )
    av = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    if "season" not in av.columns:
        raise ValueError(
            "availability files predate the season column -- element ids are only "
            "unique within a season, so the join would be wrong. Rebuild them."
        )
    _CACHE[key] = av
    return av


def build(av: pd.DataFrame) -> pd.DataFrame:
    """Derive the feature block, keyed (season, element, GW)."""
    av = av.sort_values(["season", "element", "gw"]).copy()

    status = av["asof_status"]
    av["av_status_code"] = status.map(STATUS_CODE).fillna(UNKNOWN).astype(int)
    av["av_is_flagged"] = (status != "a") & status.notna()

    # NaN is deliberately left in place: LightGBM learns a default direction for
    # missing, and av_cop_this_known lets it use the nullness itself. A null here
    # means "no news on file", which covers a fit nailed starter as readily as a
    # fringe player nobody writes about -- it is emphatically NOT a low score.
    # (Realised P(0 mins) for null is 0.570, between cop=50 and cop=75.)
    av["av_cop_this"] = av["asof_chance_of_playing_this_round"].astype("Float64").astype(float)
    av["av_cop_next"] = av["asof_chance_of_playing_next_round"].astype("Float64").astype(float)
    av["av_cop_this_known"] = av["asof_chance_of_playing_this_round"].notna().astype(int)

    av["av_is_departure"] = is_departure(status, av["asof_news"])

    # How long the flag has been up. A fresh knock and a four-week-old injury look
    # identical to a purely backward-looking model; they should not predict the same.
    flagged = av["av_is_flagged"]
    block = (~flagged).groupby([av["season"], av["element"]]).cumsum()
    av["av_flag_duration"] = (flagged.groupby([av["season"], av["element"], block])
                              .cumsum().where(flagged, 0).astype(int))

    # Transitions. The first week of an absence is the case a backward-looking model
    # cannot see at all; the week a flag clears is the case it over-corrects on.
    g = av.groupby(["season", "element"], sort=False)
    prev_flag = g["av_is_flagged"].shift()
    contiguous = g["gw"].shift() == av["gw"] - 1
    av["av_just_flagged"] = (flagged & contiguous & (prev_flag == False)).astype(int)
    av["av_just_cleared"] = (~flagged & contiguous & (prev_flag == True)).astype(int)

    age = (av["deadline_time"] - av["asof_news_added"]).dt.total_seconds() / 86400.0
    av["av_news_age_days"] = age.where(age >= 0)

    return av.rename(columns={"gw": "GW"})[["season", "element", "GW"] + FEATURES]


def attach(col: pd.DataFrame, data_dir=None) -> pd.DataFrame:
    """Left-join the feature block onto a collapsed player-gameweek frame."""
    n = len(col)
    out = col.merge(build(load(data_dir)), on=["season", "element", "GW"], how="left")
    if len(out) != n:
        raise ValueError(f"availability join changed row count: {n} -> {len(out)}")
    # No availability row means the player was not in the game at that deadline, so
    # there was no news to read. That is distinct from 'a', hence UNKNOWN.
    out["av_status_code"] = out["av_status_code"].fillna(UNKNOWN).astype(int)
    for c in ("av_cop_this_known", "av_just_flagged", "av_just_cleared",
              "av_is_departure", "av_flag_duration"):
        out[c] = out[c].fillna(0).astype(int)
    return out
