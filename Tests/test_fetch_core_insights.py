"""Tests for the core-insights ingestion (eval/fetch_core_insights.py): exact
schema contract, the finality gate, and loud failure on layout changes."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import fetch_core_insights as fc  # noqa: E402

MS_FILE = ROOT / "data" / "history" / "core_insights_matchstats_2026_27.parquet"
GS_FILE = ROOT / "data" / "history" / "core_insights_gameweek_stats_2026_27.parquet"


def test_unmapped_season_fails_loudly():
    """A season without an explicit layout entry must raise, never guess paths."""
    with pytest.raises(fc.LayoutError, match="SEASON_LAYOUT"):
        fc._layout("2027-28")


def test_incomplete_gameweek_refused(monkeypatch):
    """Each leg of the finality rule must independently refuse a final write."""
    monkeypatch.setattr(fc, "get_fpl_fixture_count", lambda gw: 2)
    ok_matches = pd.DataFrame({"match_id": ["m1", "m2"], "finished": [True, True]})
    ok_pms = pd.DataFrame({"match_id": ["m1", "m1", "m2"]})
    assert fc.check_final("2026-27", 1, ok_matches, ok_pms) == 2
    with pytest.raises(fc.ProvisionalGameweekError, match="not finished"):
        fc.check_final("2026-27", 1, ok_matches.assign(finished=[True, False]), ok_pms)
    with pytest.raises(fc.ProvisionalGameweekError, match="without playermatchstats"):
        fc.check_final("2026-27", 1, ok_matches, ok_pms[ok_pms["match_id"] == "m1"])
    monkeypatch.setattr(fc, "get_fpl_fixture_count", lambda gw: 10)
    with pytest.raises(fc.ProvisionalGameweekError, match="FPL fixtures"):
        fc.check_final("2026-27", 1, ok_matches, ok_pms)


def test_column_map_applies_and_guards_ambiguity():
    """2026-27 publishes the tackles semantic as tackles_won (measured 1.000 vs the FPL
    API); the map must apply when the schema column is dead and REFUSE when both live."""
    dead = pd.DataFrame({"tackles": [None, None], "tackles_won": [3, 1]})
    out = fc.apply_column_map(dead, {"tackles": "tackles_won"})
    assert out["tackles"].tolist() == [3, 1]
    both = pd.DataFrame({"tackles": [2, None], "tackles_won": [3, 1]})
    with pytest.raises(fc.LayoutError, match="ambiguous"):
        fc.apply_column_map(both, {"tackles": "tackles_won"})
    with pytest.raises(fc.LayoutError, match="absent"):
        fc.apply_column_map(pd.DataFrame({"tackles": [None]}), {"tackles": "tackles_won"})


def test_missing_finished_column_is_layout_error():
    with pytest.raises(fc.LayoutError, match="finished"):
        fc.check_final("2026-27", 1, pd.DataFrame({"match_id": ["m1"]}), pd.DataFrame({"match_id": ["m1"]}))


@pytest.mark.skipif(not MS_FILE.exists(), reason="season matchstats file not on disk")
def test_matchstats_schema_matches_parquet_exactly():
    api = pd.read_parquet(MS_FILE)
    base = pd.read_parquet(fc.MS_PARQUET).iloc[0:0]
    assert list(api.columns) == list(base.columns)
    mism = {c: (str(api[c].dtype), str(base[c].dtype)) for c in base.columns if api[c].dtype != base[c].dtype}
    assert not mism, f"dtype drift: {mism}"
    assert (api["season"] == "2026-2027").all()
    assert not api.duplicated(["player_id", "match_id"]).any()


@pytest.mark.skipif(not GS_FILE.exists(), reason="season gameweek_stats file not on disk")
def test_gameweek_stats_schema_and_positions():
    gs = pd.read_parquet(GS_FILE)
    base = pd.read_parquet(fc.GS_PARQUET).iloc[0:0]
    assert list(gs.columns) == list(base.columns)
    assert set(gs["position"].dropna().unique()) <= {"Goalkeeper", "Defender", "Midfielder", "Forward"}
    assert gs["position"].notna().all()
