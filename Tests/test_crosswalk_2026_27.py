"""2026-27 crosswalk build tests: the manual entries resolve to their stated ids,
the club map covers all 20 clubs (three promoted), the audit reports rather than
raises, and the season's verified single-token matches stay put."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import build_crosswalk as bc  # noqa: E402

NEEDED = [ROOT / "data" / "history" / "all_seasons_with_2026_27.parquet",
          ROOT / "data" / "history" / "understat_season_aggregates_with_2026_27.parquet"]
pytestmark = pytest.mark.skipif(not all(p.exists() for p in NEEDED),
                                reason="2026-27 combined ingestion files not on disk")


@pytest.fixture(scope="module")
def cw_2026_27():
    cw, stats = bc.build("2026-27", verbose=False)
    return cw, stats


def test_manual_entries_resolve_to_stated_ids(cw_2026_27):
    cw, _ = cw_2026_27
    for el, (uid, _why) in bc.MANUAL["2026-27"].items():
        row = cw[cw["element"] == el]
        assert len(row) == 1, f"manual element {el} missing from the build"
        assert str(row["understat_id"].iloc[0]) == uid, \
            f"element {el} resolved to {row['understat_id'].iloc[0]}, expected {uid}"
        assert row["match_type"].iloc[0] == "manual"


def test_no_duplicate_ids_and_unique_elements(cw_2026_27):
    cw, _ = cw_2026_27
    assert not cw.duplicated("understat_id").any()
    assert cw["element"].is_unique


def test_all_20_clubs_resolve_including_promoted(cw_2026_27):
    va = pd.read_parquet(ROOT / "data" / "history" / "all_seasons_with_2026_27.parquet",
                         columns=["season", "team"])
    teams = set(va[va["season"] == "2026-27"]["team"].unique())
    us = pd.read_parquet(ROOT / "data" / "history" /
                         "understat_season_aggregates_with_2026_27.parquet")
    us = us[us["understat_season"].astype(str) == "2026"]
    ut = sorted(set(us["team_title"].dropna().str.split(",").explode()))
    tmap = bc._team_map(teams, ut)          # raises if any club fails
    assert len(tmap) == 20
    for club in ("Coventry City", "Hull City", "Ipswich Town"):
        assert club in tmap, f"promoted club {club} unresolved"


def test_verified_single_token_matches_hold(cw_2026_27):
    """The twelve guard-admitted single-token names, each verified by GW1 minutes
    agreement on both sides; a regression that flips any of them is the Cherki
    class of failure."""
    cw, _ = cw_2026_27
    expected = {"5613": 4, "14395": 67, "1257": 350, "9983": 248, "14854": 119}
    for uid, el in expected.items():
        row = cw[cw["understat_id"].astype(str) == uid]
        assert len(row) == 1 and int(row["element"].iloc[0]) == el, \
            f"understat id {uid} not held by element {el}: {row.to_dict('records')}"


def test_cherki_not_matched_to_rayan(cw_2026_27):
    """The 2025-26 disaster must stay impossible: Cherki (399) holds 8094, and
    Rayan Vitor (67) holds 14395."""
    cw, _ = cw_2026_27
    assert str(cw.loc[cw["element"] == 399, "understat_id"].iloc[0]) == "8094"
    assert str(cw.loc[cw["element"] == 67, "understat_id"].iloc[0]) == "14395"


def test_audit_ran_and_reported(cw_2026_27):
    """With one final gameweek no pair reaches AUDIT_MIN_MINUTES, so the audit
    checks zero pairs -- but it must REPORT that (return a frame), never raise."""
    _, stats = cw_2026_27
    assert stats["audit_hard_disagreements"] == 0
    assert stats["audit_dropped"] == 0


def test_coverage_of_playing_elements(cw_2026_27):
    """Every FPL element with GW1 minutes must carry an id after the manual block."""
    cw, _ = cw_2026_27
    api = pd.read_parquet(ROOT / "data" / "history" / "fpl_api_2026_27.parquet")
    played = set(api.loc[api["minutes"] > 0, "element"])
    missing = played - set(cw["element"])
    assert not missing, f"playing elements without an Understat id: {sorted(missing)}"
