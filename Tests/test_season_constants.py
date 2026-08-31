"""Season-constant guards: these fail the moment the data outgrows a hardcoded
season list, so next August's boundary cannot silently recur. The minutes
ladder is the dangerous one -- one season short and the whole league gets
prev_* = 0 / transfer_status = 2 (all-cold-start) with no error anywhere."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import live_deadline as ld  # noqa: E402
import season_stack  # noqa: E402
import attacking_rates as ar  # noqa: E402
import walkforward_season as wfs  # noqa: E402


def _stack_seasons():
    s = pd.read_parquet(season_stack.stack_path(), columns=["season"])
    return sorted(s["season"].unique())


def test_minutes_ladder_covers_every_stack_season():
    """The ladder (minutes.py ~:90, parsed from source so this cannot drift)
    must include every season from 2022-23 on that exists in the stack."""
    ladder = ld._minutes_ladder()
    assert ladder, "could not parse the minutes ladder"
    missing = [s for s in _stack_seasons() if s >= "2022-23" and s not in ladder]
    assert not missing, (
        f"minutes.py's prev-season ladder is missing {missing} -- every player in "
        f"those seasons silently becomes an all-cold-start new signing. Extend the "
        f"`order` list in squad/minutes.py.")


def test_blend_prior_covers_latest_stack_season():
    latest = _stack_seasons()[-1]
    if latest >= "2023-24":
        assert latest in ar.BLEND_PRIOR, \
            f"attacking_rates.BLEND_PRIOR has no entry for {latest} -- get_rates raises"


def test_walkforward_order_and_labelled_cover_latest():
    latest = _stack_seasons()[-1]
    assert latest in wfs.ORDER, f"{latest} missing from walkforward_season.ORDER"
    assert latest in wfs.LABELLED, f"{latest} missing from walkforward_season.LABELLED"


def test_stack_path_resolves_and_contains_archive():
    p = season_stack.stack_path()
    assert p.exists()
    seasons = _stack_seasons()
    assert "2025-26" in seasons and "2016-17" in seasons, \
        "the resolved stack must always contain the frozen archive seasons"


def test_dc_source_gate_defaults_to_core_insights():
    """KNOWN_ISSUES #21 / Logs/dc_source_swap_prereg.md: the DC count source is
    gated and MUST default to the current source until the swap is adopted in
    its own commit (which must also season-key _DC_HITS_CACHE). A change here
    without that adoption commit is a regression."""
    import defensive
    assert defensive.DC_SOURCE == "core_insights"


def test_dc_seasons_deliberately_held_back():
    """KNOWN_ISSUES #21: the DC source is unmeasured; DC_SEASONS stays at 2025-26
    until that pre-registration. This test DOCUMENTS the hold -- when the swap is
    measured and adopted, update this test alongside the constant."""
    assert wfs.DC_SEASONS == {"2025-26"}
