"""Tests for the Understat ingestion: the per-match extension (eval/understat_matches.py)
and the aggregates builder (eval/build_understat_aggregates.py). Network-free units always
run; artefact tests skip until the files exist."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import understat_matches as um  # noqa: E402

HIST = ROOT / "data" / "history"
PM_FILE = HIST / "understat_matches_2026_27.parquet"
AGG_FILE = HIST / "understat_season_aggregates_2026_27.parquet"
REPRO = HIST / "understat_aggregates_repro_check.json"


def test_unmapped_season_fails_loudly():
    """A season with no kickoff source anywhere must raise, never yield an empty lookup."""
    with pytest.raises(LookupError, match="no kickoff source"):
        um._gw_lookup("2031-32")


def test_season_not_in_map_rejected_by_aggregates_builder():
    import build_understat_aggregates as ba
    with pytest.raises(KeyError, match="SEASONS"):
        ba.fetch_players_block("2031-32")


def _fake_rows(dates):
    return pd.DataFrame({"match_id": [f"m{i}" for i in range(len(dates))],
                         "match_date": dates,
                         "team": ["A"] * len(dates), "opponent": ["B"] * len(dates)})


def test_archive_season_unmapped_match_raises():
    """gw=None can never silently pass through on an archive season."""
    import datetime as dt
    df = _fake_rows([dt.date(2024, 8, 17), dt.date(2024, 12, 25)])
    lookup = {dt.date(2024, 8, 17): (1, False)}          # the Dec date is unmapped
    with pytest.raises(ValueError, match="no gameweek"):
        um.split_final_deferred(df, lookup, {1: 1}, live_season=False)


def test_live_season_unmapped_and_incomplete_are_deferred_not_none():
    import datetime as dt
    d1, d2, d3 = dt.date(2026, 8, 21), dt.date(2026, 8, 28), dt.date(2026, 9, 4)
    df = _fake_rows([d1, d1, d2])                        # two GW1 matches, one unmapped date
    lookup = {d1: (1, False)}                            # only GW1 is final
    final, deferred = um.split_final_deferred(df, lookup, {1: 2}, live_season=True)
    assert len(final) == 2 and (final["gw"] == 1).all()
    assert len(deferred) == 1 and deferred["gw"].isna().all()
    # incomplete gameweek: GW1 expects 3 fixtures but only 2 present -> whole gw deferred
    final2, deferred2 = um.split_final_deferred(df, lookup, {1: 3}, live_season=True)
    assert len(final2) == 0 and len(deferred2) == 3


@pytest.mark.skipif(not PM_FILE.exists(), reason="2026-27 per-match file not on disk")
def test_per_match_schema_matches_2025_26():
    new = pd.read_parquet(PM_FILE)
    ref = pd.read_parquet(HIST / "understat_matches_2025_26.parquet").iloc[0:0]
    assert list(new.columns) == list(ref.columns)
    mism = {c: (str(new[c].dtype), str(ref[c].dtype)) for c in ref.columns if new[c].dtype != ref[c].dtype}
    assert not mism, f"dtype drift vs 2025-26: {mism}"
    assert new["gw"].notna().all(), "gw=None rows in the written season file"


@pytest.mark.skipif(not AGG_FILE.exists(), reason="2026-27 aggregates not on disk")
def test_aggregates_schema_matches_stored():
    new = pd.read_parquet(AGG_FILE)
    ref = pd.read_parquet(HIST / "understat_season_aggregates.parquet").iloc[0:0]
    assert list(new.columns) == list(ref.columns)
    assert (new.dtypes == ref.dtypes).all()
    assert (new["understat_season"] == "2026").all()


@pytest.mark.skipif(not REPRO.exists(), reason="reproduction check not yet run")
def test_aggregates_builder_reproduced_a_stored_season():
    """The trust proof of record: the builder's --reproduce run must have matched a
    stored season exactly (the CLI writes this report; regressions rerun it)."""
    rep = json.loads(REPRO.read_text(encoding="utf-8"))
    assert rep["exact"] is True, f"aggregates reproduction was not exact: {rep}"
    assert rep["rows_stored"] == rep["rows_fresh"]
