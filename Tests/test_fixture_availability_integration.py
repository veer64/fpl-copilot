"""Tests for the 2026-27 fixture-universe and live-availability integrations."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

FIX = ROOT / "data" / "history" / "odds_all_seasons_with_2026_27.parquet"
AV = ROOT / "data" / "availability_2627.parquet"


def test_unmapped_club_fails_loudly():
    import fetch_fixtures as ff
    # ambiguity: two archive spellings round-tripping to one FPL name must raise,
    # never guess -- a wrong club name silently drops that club's fixture joins
    import assembly
    assert assembly.TEAM_MAP.get("Man United") == "Man Utd"
    with pytest.raises(ff.ClubNameError):
        ff.resolve_club_names({"Man Utd"}, ["Man United", "Man Utd"])
    # clean cases: E0 spelling reused where it round-trips; FPL name otherwise
    m = ff.resolve_club_names({"Man Utd", "Spurs", "Coventry City"},
                              ["Man United", "Tottenham", "Liverpool"])
    assert m == {"Man Utd": "Man United", "Spurs": "Tottenham",
                 "Coventry City": "Coventry City"}


@pytest.mark.skipif(not FIX.exists(), reason="combined fixture file not on disk")
def test_fixture_universe_reaches_dixon_coles_priced_and_counted():
    """get_fixtures('2026-27'): every fixture priced by the live pull flips
    lambda_source to 'odds'; every unpriced fixture takes the counted pure-DC
    fallback -- and BOTH are visible per fixture, never silent. (Until
    2026-08-31's live pull this asserted all-dc; the pull is the change.)"""
    import dixon_coles as dc
    out = dc.get_fixtures(predict_season="2026-27", cutoff_date="2026-08-21",
                          odds_available_until=None)
    assert len(out) == 380
    src = out["lambda_source"].value_counts().to_dict()
    assert set(src) <= {"dc", "odds", "synthetic"}
    assert src.get("odds", 0) >= 1, "the live pull priced fixtures but none flipped to market"
    assert (out.loc[out["lambda_source"] == "odds", "odds_used"]).all()
    assert (~out.loc[out["lambda_source"] == "dc", "odds_used"]).all()
    assert out["lam_home"].notna().all() and out["p_home_cs"].notna().all()


@pytest.mark.skipif(not FIX.exists(), reason="combined fixture file not on disk")
def test_historical_seasons_still_read_the_frozen_archive():
    """Per-season resolution: a 2025-26 build must read the original file (parity
    by construction), and its matches must be byte-identical to the archive's."""
    import dixon_coles as dc
    m_new = dc._load_matches("2025-26")
    m_old = dc._load_matches(None)
    pd.testing.assert_frame_equal(m_new, m_old)


@pytest.mark.skipif(not AV.exists(), reason="merged availability not on disk")
def test_availability_join_no_duplicates_and_real_values():
    import availability_features as avf
    avf._CACHE.clear()
    col = pd.read_parquet(AV, columns=["season", "element", "gw"]).rename(columns={"gw": "GW"})
    col = col.drop_duplicates(["season", "element", "GW"]).head(500)
    out = avf.attach(col)                     # raises if the join changes row count
    assert len(out) == len(col)
    # a 2026-27 lookup returns REAL values, not the -1/0/NaN missing-season fill
    assert (out["av_status_code"] != avf.UNKNOWN).any(), \
        "every 2026-27 row came back UNKNOWN -- the live files are still invisible"
    assert (out["av_status_code"] == avf.UNKNOWN).mean() < 0.05


@pytest.mark.skipif(not AV.exists(), reason="merged availability not on disk")
def test_merged_availability_unique_keys_and_schema():
    av = pd.read_parquet(AV)
    ref = pd.read_parquet(ROOT / "data" / "availability_2526.parquet").iloc[0:0]
    assert list(av.columns) == list(ref.columns)
    assert (av.dtypes == ref.dtypes).all()
    assert not av.duplicated(["season", "element", "gw"]).any()
    assert (av["season"] == "2026-27").all()
    assert set(av["asof_source"].unique()) <= {"live_snapshot", "live_late_news",
                                               "snapshot", "late_news"}
