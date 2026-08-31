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
COMBINED = ROOT / "data" / "arms_gap0" / f"walkforward_h6_{SEASON.replace('-', '_')}_both.parquet"


@pytest.mark.skipif(not CANON.exists(), reason="canonical 2025-26 frame not on disk")
def test_parity_one_cutoff_bit_identical():
    """The deliverable: a completed gameweek, live path vs canonical, max |delta| 0.0."""
    frame, findings = ld.build_deadline_frame(SEASON, 20, strict=False, verbose=False)
    ok, lines = ld.compare_to_canonical(frame, SEASON, 20)
    assert ok, "live path diverged from the canonical harness:\n" + "\n".join(lines)
    # strict-relevant findings on a healthy backtest gameweek should be notes only
    hard = [f for f in findings if not f.startswith("note:")]
    assert hard == [], f"unexpected hard findings on a healthy cutoff: {hard}"


@pytest.mark.skipif(not COMBINED.exists(), reason="combined arm frame not on disk")
def test_parity_combined_config_bit_identical():
    """The production config: props ON (module gate) + horizon minutes ON (inert at
    step 0 by construction). Must be bit-identical to the arm record file."""
    import assembly
    frame, findings = ld.build_deadline_frame(SEASON, 20, strict=False, config="combined")
    assert assembly.PROPS_HOOK is None, "the props module gate must rest None after a build"
    ok, lines = ld.compare_to_canonical(frame, SEASON, 20, canonical_path=COMBINED,
                                        allow_only_live={"penalty_join_prior_season"})
    assert ok, "combined live path diverged from the arm record:\n" + "\n".join(lines)
    assert any("props overrode" in f for f in findings), "props hook did not fire"
    hard = [f for f in findings if not f.startswith("note:")]
    assert hard == [], f"unexpected hard findings on a healthy cutoff: {hard}"


def test_props_coverage_floor_constant():
    """Historical 2025-26 coverage is 100% every gameweek; the strict floor must sit
    below that but at the pre-registered 80% gate."""
    assert ld.PROPS_MIN_FIXTURE_COVERAGE == 0.80
    priced, total = ld.props_fixture_coverage(SEASON, 20)
    assert total > 0 and priced / total >= ld.PROPS_MIN_FIXTURE_COVERAGE


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
    """The 2026-27 findings list is a LEDGER of what is still open. The ingestion
    session of 2026-08-31 closed the gaps one by one (crosswalk 97927b8; stack /
    ladder / BLEND_PRIOR / ORDER+LABELLED and the consumer repointing in
    963d24c..17426f3), so this test pins BOTH directions: the findings that must
    still fire (their inputs are genuinely open) and the ones that must have
    STOPPED firing (their inputs exist now -- a reappearance means a regression
    in a resolver or a constant). Each future closure updates this test
    deliberately, in the closing commit."""
    findings = ld.preflight("2026-27", 3, strict=False)
    joined = " ".join(findings)
    still_open = ["availability", "DC_SEASONS", "DC_RULE_SEASONS", "odds_all_seasons"]
    for needle in still_open:
        assert needle in joined, f"expected a finding mentioning {needle} (still open)"
    closed = ["vaastav master has NO rows", "BLEND_PRIOR", "ladder", "crosswalk missing"]
    for needle in closed:
        assert needle not in joined, \
            f"finding {needle!r} reappeared although its input was closed on 2026-08-31"


def test_minutes_ladder_parser_finds_current_seasons():
    """The ladder check parses minutes.py source; it must see the seasons that ARE there."""
    ladder = ld._minutes_ladder()
    assert ladder and "2025-26" in ladder and "2022-23" in ladder
