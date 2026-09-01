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


def test_dc_source_adopted_fpl_official():
    """ADOPTED 2026-08-31 as a JUDGEMENT CALL (the pre-registered test FAILED;
    the exploratory re-measurement is not a pass -- both logs say so): the DC
    count source defaults to the native FPL count. core_insights remains a
    valid gate value so the frozen 2025-26 records stay reproducible."""
    import defensive
    assert defensive.DC_SOURCE == "fpl_official"


def test_dc_seasons_extended_at_adoption():
    """The #21 hold on these sets was released by the 2026-08-31 adoption (this
    test's predecessor documented the hold and required updating in the closing
    commit -- this is that update). Both sets carry 2026-27; the same commit
    made the official source season-parametric and season-keyed the cache."""
    import defensive
    assert wfs.DC_SEASONS == {"2025-26", "2026-27"}
    assert defensive.DC_RULE_SEASONS == {"2025-26", "2026-27"}
