"""Parity + strict-mode tests for the live deadline path (squad/live_deadline.py).

The parity test is the contract: the live path must produce BIT-IDENTICAL
step-0 rows to the canonical walk-forward file, because it calls the same
harness (walk_forward, cutoffs=[gw], horizon=1). If anyone later gives the
live path its own logic and it diverges, this test fails.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import live_deadline as ld  # noqa: E402

SEASON = "2025-26"
CANON = ROOT / "data" / f"walkforward_h6_{SEASON.replace('-', '_')}.parquet"


@pytest.mark.skipif(not CANON.exists(), reason="canonical 2025-26 frame not on disk")
def test_parity_one_cutoff_bit_identical():
    """The deliverable: a completed gameweek, live path vs canonical, max |delta| 0.0."""
    frame, findings = ld.build_deadline_frame(SEASON, 20, strict=False, verbose=False)
    ok, lines = ld.compare_to_canonical(frame, SEASON, 20)
    assert ok, "live path diverged from the canonical harness:\n" + "\n".join(lines)
    # strict-relevant findings on a healthy backtest gameweek should be notes only
    hard = [f for f in findings if not f.startswith("note:")]
    assert hard == [], f"unexpected hard findings on a healthy cutoff: {hard}"


def test_compare_detects_divergence():
    """The comparator itself must fail loudly on a perturbed frame."""
    canon = pd.read_parquet(CANON)
    sl = canon[(canon["cutoff"] == 20) & (canon["horizon_step"] == 0)].copy()
    sl.loc[sl.index[0], "e_points"] += 1e-9
    ok, lines = ld.compare_to_canonical(sl, SEASON, 20)
    assert not ok and any("e_points" in ln for ln in lines)


def test_compare_detects_missing_row():
    canon = pd.read_parquet(CANON)
    sl = canon[(canon["cutoff"] == 20) & (canon["horizon_step"] == 0)].iloc[1:]
    ok, lines = ld.compare_to_canonical(sl, SEASON, 20)
    assert not ok and any("ROW SET DIFFERS" in ln for ln in lines)


def test_strict_preflight_passes_for_backtest_season():
    """2025-26 GW20 has every input on disk: strict preflight must not raise."""
    findings = ld.preflight(SEASON, 20, strict=True)
    assert all(f.startswith("note:") for f in findings)


def test_strict_preflight_rejects_missing_season():
    """A season with no data (2026-27 today) must raise, not degrade silently."""
    with pytest.raises(ld.LiveStrictError):
        ld.preflight("2026-27", 3, strict=True)


def test_nonstrict_preflight_reports_instead_of_raising():
    findings = ld.preflight("2026-27", 3, strict=False)
    assert len(findings) >= 5          # vaastav, crosswalk, blend, ladder, DC sets, availability...
    joined = " ".join(findings)
    for needle in ("vaastav", "crosswalk", "BLEND_PRIOR", "ladder", "DC_SEASONS", "availability"):
        assert needle in joined, f"expected a finding mentioning {needle}"


def test_minutes_ladder_parser_finds_current_seasons():
    """The ladder check parses minutes.py source; it must see the seasons that ARE there."""
    ladder = ld._minutes_ladder()
    assert ladder and "2025-26" in ladder and "2022-23" in ladder
