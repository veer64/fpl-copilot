"""Tests for the FPL-API ingestion (eval/fetch_fpl_history.py): exact schema
contract, the data_checked gate, and GW1 parity against vaastav's published
file. The data-dependent tests skip when the artefacts are not on disk; the
gate test always runs (no network)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import fetch_fpl_history as ff  # noqa: E402

API_FILE = ROOT / "data" / "history" / "fpl_api_2026_27.parquet"
VA_REF = ROOT / "data" / "history" / "vaastav_gw1_2026_27_reference.csv"
STACK = ROOT / "data" / "history" / "all_seasons_fixed.parquet"


def test_data_checked_gate_refuses_provisional():
    events = [{"id": 1, "finished": True, "data_checked": True},
              {"id": 2, "finished": True, "data_checked": False},
              {"id": 3, "finished": False, "data_checked": False}]
    assert ff.assert_final(events, 1)["id"] == 1
    with pytest.raises(ff.ProvisionalGameweekError):
        ff.assert_final(events, 2)
    with pytest.raises(ff.ProvisionalGameweekError):
        ff.assert_final(events, 3)
    with pytest.raises(ValueError):
        ff.assert_final(events, 9)


@pytest.mark.skipif(not (API_FILE.exists() and STACK.exists()), reason="API season file not on disk")
def test_schema_matches_stack_exactly():
    api = pd.read_parquet(API_FILE)
    base = pd.read_parquet(STACK).iloc[0:0]
    assert list(api.columns) == list(base.columns), "column names/order differ from all_seasons_fixed"
    # `modified` reads from the stack as object only because pre-2017 seasons carry
    # nulls; a single-season all-bool column reads back as bool -- a parquet
    # round-trip artefact, castable losslessly (combine() does exactly that).
    ROUND_TRIP_OBJECT = {"modified"}
    mism = {c: (str(api[c].dtype), str(base[c].dtype)) for c in base.columns
            if api[c].dtype != base[c].dtype and c not in ROUND_TRIP_OBJECT}
    assert not mism, f"dtype drift vs the stack: {mism}"
    for c in ROUND_TRIP_OBJECT:
        api[c].astype(base[c].dtype)          # must cast losslessly
    assert (api["season"] == "2026-27").all()
    assert not api.duplicated(["element", "fixture", "GW"]).any()


@pytest.mark.skipif(not (API_FILE.exists() and VA_REF.exists()), reason="artefacts not on disk")
def test_gw1_parity_with_vaastav():
    """Fails if a change to the fetcher stops reproducing vaastav exactly on the
    modelling-read columns."""
    api = pd.read_parquet(API_FILE)
    api = api[api["GW"] == 1]
    va = pd.read_csv(VA_REF, low_memory=False)
    j = va.merge(api, on=["element", "fixture"], suffixes=("_va", "_api"), how="outer", indicator=True)
    assert (j["_merge"] == "both").all(), "row sets differ from vaastav GW1"
    b = j
    for c in ff.MODELLING_READ:
        if c in ("season", "element", "fixture", "GW"):
            continue
        a, v = b[f"{c}_api"], b[f"{c}_va"]
        try:
            eq = (pd.to_numeric(a).fillna(-9e9) == pd.to_numeric(v).fillna(-9e9))
        except (ValueError, TypeError):
            eq = a.astype(str) == v.astype(str)
        assert eq.all(), f"{c}: {int((~eq).sum())} mismatches vs vaastav"


@pytest.mark.skipif(not API_FILE.exists(), reason="API season file not on disk")
def test_no_provisional_rows_in_season_file():
    """Finality is represented by the file a row lives in; the season file's
    provenance sidecar must say data_checked for every gameweek present."""
    import json
    side = API_FILE.with_suffix("").with_suffix("")  # noop guard for name building below
    prov = json.loads((ROOT / "data" / "history" / "fpl_api_2026_27.provenance.json").read_text())
    api = pd.read_parquet(API_FILE)
    for gw in sorted(int(g) for g in api["GW"].unique()):
        assert str(gw) in prov and prov[str(gw)]["data_checked"] is True, \
            f"GW{gw} present in the season file without a data_checked provenance entry"
