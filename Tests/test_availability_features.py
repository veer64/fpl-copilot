"""Tests for the availability feature block.

The properties worth testing here are not "does it compute a number" but "could this
value have been read 90 minutes before the first kickoff". A leak in this block would
be invisible in every downstream metric and would flatter the whole model, so the
as-of guarantees are asserted directly against the source parquets.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import availability_features as avf  # noqa: E402


@pytest.fixture(scope="module")
def raw():
    return avf.load()


@pytest.fixture(scope="module")
def feats(raw):
    return avf.build(raw)


# --- leak guarantees -------------------------------------------------------

def test_no_snapshot_at_or_after_deadline(raw):
    assert (raw["snapshot_time"] < raw["deadline_time"]).all()


def test_no_asof_news_at_or_after_deadline(raw):
    late = raw["asof_news_added"].notna() & (raw["asof_news_added"] >= raw["deadline_time"])
    assert not late.any(), f"{late.sum()} rows carry news stamped at/after the deadline"


def test_news_age_is_never_negative(feats):
    """Negative age would mean the news post-dates the deadline it is attached to."""
    age = feats["av_news_age_days"].dropna()
    assert (age >= 0).all()


def test_transitions_only_look_backwards(raw):
    """just_flagged/just_cleared must be reconstructible from this gameweek and the
    previous one alone -- never from a later one."""
    f = avf.build(raw).rename(columns={"GW": "gw"})
    j = raw[["season", "element", "gw", "asof_status"]].merge(
        f[["season", "element", "gw", "av_just_flagged", "av_just_cleared"]],
        on=["season", "element", "gw"])
    j = j.sort_values(["season", "element", "gw"])
    g = j.groupby(["season", "element"], sort=False)
    is_flagged = (j["asof_status"] != "a") & j["asof_status"].notna()
    prev = g["asof_status"].shift()
    prev_flagged = (prev != "a") & prev.notna()
    contiguous = g["gw"].shift() == j["gw"] - 1

    expected_flagged = (is_flagged & contiguous & ~prev_flagged).astype(int)
    expected_cleared = (~is_flagged & contiguous & prev_flagged).astype(int)
    assert (j["av_just_flagged"].values == expected_flagged.values).all()
    assert (j["av_just_cleared"].values == expected_cleared.values).all()


# --- semantics -------------------------------------------------------------

def test_null_chance_of_playing_stays_null(feats):
    """Null means 'no news on file', not zero. Filling it with 0 would tell the model
    that every unwritten-about player is certainly out."""
    assert feats["av_cop_this"].isna().any()
    assert ((feats["av_cop_this_known"] == 0) == feats["av_cop_this"].isna()).all()


def test_flag_duration_counts_consecutive_flagged_gameweeks(raw, feats):
    j = raw[["season", "element", "gw", "asof_status"]].merge(
        feats.rename(columns={"GW": "gw"}), on=["season", "element", "gw"])
    unflagged = j["asof_status"] == "a"
    assert (j.loc[unflagged, "av_flag_duration"] == 0).all()
    assert (j.loc[~unflagged, "av_flag_duration"] >= 1).all()


def test_status_u_is_always_a_departure(raw):
    """`u` is a permanent exclusion, not a temporary state. Anchoring on status rather
    than on free text is what makes this hold across seasons."""
    u = raw[raw["asof_status"] == "u"]
    assert len(u)
    assert avf.is_departure(u["asof_status"], u["asof_news"]).eq(1).all()


def test_departure_text_still_matches_most_u_news(raw):
    """Data-quality tripwire, deliberately separate from the feature itself. The
    feature no longer depends on this holding, but a sharp drop would mean FPL changed
    its phrasing and the non-`u` departures are being missed."""
    u = raw[raw["asof_status"] == "u"]
    rate = u["asof_news"].fillna("").str.contains(avf.DEPARTURE).mean()
    assert rate > 0.95, f"departure phrasing drifted: only {rate:.3f} of `u` news matches"


def test_departure_does_not_fire_on_available_players(raw):
    a = raw[raw["asof_status"] == "a"]
    assert avf.is_departure(a["asof_status"], a["asof_news"]).mean() < 0.001


# --- join integrity --------------------------------------------------------

def test_attach_preserves_row_count_and_fills_unknown():
    col = pd.DataFrame({
        "season": ["2025-26"] * 3,
        "element": [1, 1, 999999],   # 999999 is not in the game
        "GW": [1, 2, 1],
    })
    out = avf.attach(col)
    assert len(out) == 3
    assert out.loc[2, "av_status_code"] == avf.UNKNOWN
    for c in ("av_flag_duration", "av_just_flagged", "av_just_cleared",
              "av_is_departure", "av_cop_this_known"):
        assert out[c].notna().all()


def test_feature_list_matches_built_columns(feats):
    assert set(avf.FEATURES).issubset(feats.columns)
    assert list(feats.columns[:3]) == ["season", "element", "GW"]
