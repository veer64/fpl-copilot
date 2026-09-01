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
import defensive  # noqa: E402
from contextlib import contextmanager  # noqa: E402

SEASON = "2025-26"


@contextmanager
def _frozen_record_source():
    """The frozen 2025-26 record files were built on the core_insights DC
    source. Since the 2026-08-31 adoption the live default is fpl_official, so
    every record-parity test pins the SOURCE THE RECORD WAS BUILT UNDER -- the
    guarantee these tests keep is that the shared code path reproduces the
    frozen artefacts bit-for-bit through the gate. Live-default behaviour is
    a deliberate model change, quantified in the adoption log, not a parity
    subject."""
    prev = defensive.DC_SOURCE
    defensive.DC_SOURCE = "core_insights"
    try:
        yield
    finally:
        defensive.DC_SOURCE = prev
CANON = ROOT / "data" / f"walkforward_h6_{SEASON.replace('-', '_')}.parquet"
COMBINED = ROOT / "data" / "arms_gap0" / f"walkforward_h6_{SEASON.replace('-', '_')}_both.parquet"


@pytest.mark.skipif(not CANON.exists(), reason="canonical 2025-26 frame not on disk")
def test_parity_one_cutoff_bit_identical():
    """The deliverable: a completed gameweek, live path vs canonical, max |delta| 0.0."""
    with _frozen_record_source():
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
    with _frozen_record_source():
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
    """A season with no data must raise, not degrade silently. 2026-27 GRADUATED
    on 2026-08-31 -- master+skeleton, crosswalk, availability, blend and live
    odds all exist, so a baseline GW3 strict preflight now passes; the pin moves
    to a genuinely nonexistent season."""
    with pytest.raises(ld.LiveStrictError):
        ld.preflight("2027-28", 3, strict=True)


def test_strict_preflight_combined_still_raises_on_open_gaps():
    """The two remaining 2026-27 gaps are combined-config inputs (props book,
    hmin refit): strict must still raise there until they close."""
    with pytest.raises(ld.LiveStrictError):
        ld.preflight("2026-27", 3, strict=True, config="combined", horizon=6)


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
    # The DC hold (#21) CLOSED at the 2026-08-31 adoption (judgement call):
    # DC_SEASONS / DC_RULE_SEASONS moved to the closed direction below.
    closed = ["vaastav master has NO rows", "BLEND_PRIOR", "ladder", "crosswalk missing",
              "no data/availability_", "odds_all_seasons has NO rows",
              "DC_SEASONS", "DC_RULE_SEASONS"]
    for needle in closed:
        assert needle not in joined, \
            f"finding {needle!r} reappeared although its input was closed on 2026-08-31"
    # Still open, pinned at GW1: the odds PRICES (the fixture universe closed on
    # 2026-08-31; live odds pulling is a separate pending job). The prices check
    # derives the GW's kickoff window from the FPL-API master's rows for that GW,
    # so it can only fire for a gameweek the master already covers -- GW1 today.
    joined_gw1 = " ".join(ld.preflight("2026-27", 1, strict=False))
    assert "odds PRICES" in joined_gw1, \
        "expected the all-unpriced-gameweek finding at GW1 (still open until live odds land)"


def test_minutes_ladder_parser_finds_current_seasons():
    """The ladder check parses minutes.py source; it must see the seasons that ARE there."""
    ladder = ld._minutes_ladder()
    assert ladder and "2025-26" in ladder and "2022-23" in ladder


@pytest.mark.skipif(not COMBINED.exists(), reason="combined arm frame not on disk")
def test_extraction_reproduces_arm_record_full_cutoff():
    """EXTRACTION PARITY: the functions lifted out of walkforward_arms.main
    (cutoff_components / minutes_frames / assemble_cutoff / stamp_arm_frame)
    must rebuild a full six-step cutoff of the arm record file bit-identically
    -- every step, every common column. GW5 so this and the GW20 horizon test
    cover two cutoffs. Fails on any future divergence between the extracted
    path and the record."""
    with _frozen_record_source():
        frame, _ = ld.build_deadline_frame(SEASON, 5, strict=False, config="combined", horizon=6)
    for step in range(6):
        ok, lines = ld.compare_to_canonical(frame, SEASON, 5, canonical_path=COMBINED,
                                            allow_only_live={"penalty_join_prior_season"}, step=step)
        assert ok, f"extraction diverged at step {step}:\n" + "\n".join(lines)


@pytest.mark.skipif(not CANON.exists(), reason="canonical 2025-26 frame not on disk")
def test_live_horizon6_baseline_all_steps():
    """LIVE HORIZON-6, baseline: all six steps of a GW20 build must be
    bit-identical to the canonical file's rows at (cutoff=20, step)."""
    with _frozen_record_source():
        frame, findings = ld.build_deadline_frame(SEASON, 20, strict=False, horizon=6)
    for step in range(6):
        ok, lines = ld.compare_to_canonical(frame, SEASON, 20, step=step)
        assert ok, f"baseline step {step} diverged:\n" + "\n".join(lines)
    hard = [f for f in findings if not f.startswith("note:")]
    assert hard == [], f"unexpected hard findings on a healthy horizon-6 cutoff: {hard}"


@pytest.mark.skipif(not COMBINED.exists(), reason="combined arm frame not on disk")
def test_live_horizon6_combined_all_steps():
    """LIVE HORIZON-6, combined: all six steps of a GW20 build (props hook +
    steps-1-5 hmin substitution) must be bit-identical to the arm record."""
    import assembly
    with _frozen_record_source():
        frame, findings = ld.build_deadline_frame(SEASON, 20, strict=False, config="combined", horizon=6)
    assert assembly.PROPS_HOOK is None, "the props module gate must rest None after a build"
    assert any("horizon minutes steps 1-5" in f for f in findings), "the substitution did not report"
    for step in range(6):
        ok, lines = ld.compare_to_canonical(frame, SEASON, 20, canonical_path=COMBINED,
                                            allow_only_live={"penalty_join_prior_season"}, step=step)
        assert ok, f"combined step {step} diverged from the arm record:\n" + "\n".join(lines)
    hard = [f for f in findings if not f.startswith("note:")]
    assert hard == [], f"unexpected hard findings on a healthy horizon-6 cutoff: {hard}"
