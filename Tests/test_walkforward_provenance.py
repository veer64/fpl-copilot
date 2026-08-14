"""Guard for KNOWN_ISSUES.md #10 — the canonical walk-forward file's provenance.

`minutes.py` defaults to `availability=True` since 2026-08-13. The canonical file
`data/walkforward_h6_2526.parquet` was built BEFORE that, so regenerating it with
today's default silently moves the season baseline from 1984 to 1938 with nothing
erroring. Every log quoting 1984 would become incomparable, invisibly.

This is the same shape as the stale-odds incident: source read ODDS_HORIZON_GWS = 0
while the parquet on disk had been built at 2, and an hour went into blaming a code
edit. So the artefact gets a fingerprint rather than a comment.

The fingerprint is MEANT to be updated by hand when the baseline is deliberately
moved. A failure here is a question ("did you mean to?"), not a bug.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

CANONICAL = REPO / "data" / "walkforward_h6_2526.parquet"
AVAILABILITY = REPO / "data" / "walkforward_h6_2526_av.parquet"

# Pre-adoption fingerprint. Season total on these predictions is 1984.
EXPECTED_ROWS = 165_401
EXPECTED_SPEARMAN = 0.715
EXPECTED_MAE = 1.15
TOL_RHO, TOL_MAE = 0.005, 0.02

WHY = (
    "\n\n*** data/walkforward_h6_2526.parquet no longer matches its pre-adoption "
    "fingerprint. ***\n"
    "If you just rebuilt it, minutes.py's availability=True default has almost "
    "certainly\nmoved the season baseline from 1984 to 1938. See KNOWN_ISSUES.md #10.\n"
    "If that was deliberate, update the constants in this file AND every log quoting "
    "1984."
)


@pytest.fixture(scope="module")
def canonical():
    if not CANONICAL.exists():
        pytest.skip(f"{CANONICAL} not present")
    return pd.read_parquet(CANONICAL)


def _step0(df):
    d = df[df.horizon_step == 0].dropna(subset=["e_points", "actual_points"])
    return d.assign(actual_points=pd.to_numeric(d.actual_points, errors="coerce"))


def test_canonical_file_is_pre_adoption(canonical):
    """The whole point of the guard: this file must be the availability=False build."""
    if "minutes_availability" in canonical.columns:
        assert not bool(canonical["minutes_availability"].iloc[0]), (
            "canonical walk-forward file was built WITH availability features." + WHY)
    # Files without the column predate the provenance stamp, hence pre-adoption.


def test_canonical_fingerprint_unchanged(canonical):
    assert len(canonical) == EXPECTED_ROWS, (
        f"row count {len(canonical)} != {EXPECTED_ROWS}." + WHY)
    d = _step0(canonical)
    rho = spearmanr(d.e_points, d.actual_points).statistic
    mae = (d.e_points - d.actual_points).abs().mean()
    assert abs(rho - EXPECTED_SPEARMAN) < TOL_RHO, (
        f"horizon-0 Spearman {rho:.4f} != {EXPECTED_SPEARMAN}." + WHY)
    assert abs(mae - EXPECTED_MAE) < TOL_MAE, (
        f"horizon-0 MAE {mae:.4f} != {EXPECTED_MAE}." + WHY)


def test_availability_file_is_distinct_when_present():
    """The two builds must not be the same artefact under two names."""
    if not (AVAILABILITY.exists() and CANONICAL.exists()):
        pytest.skip("both walk-forward files required")
    a, b = _step0(pd.read_parquet(AVAILABILITY)), _step0(pd.read_parquet(CANONICAL))
    rho_a = spearmanr(a.e_points, a.actual_points).statistic
    rho_b = spearmanr(b.e_points, b.actual_points).statistic
    assert rho_a > rho_b, (
        "the availability build should rank better at horizon 0 "
        f"(got {rho_a:.4f} vs {rho_b:.4f}) -- are these the same file?")


def test_availability_default_is_declared():
    """The harness stamps this constant, so it must exist to be stamped."""
    import minutes
    assert isinstance(minutes.AVAILABILITY_DEFAULT, bool)
