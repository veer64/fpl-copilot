"""Guard for the canonical walk-forward file's provenance.

HISTORY, because the fingerprint has been deliberately moved once and the reason
must survive.

Originally this guarded KNOWN_ISSUES.md #10: `minutes.py` defaulted to
`availability=True` from 2026-08-13 while `data/walkforward_h6_2526.parquet` had
been built before that, so regenerating it silently moved the season baseline from
1984 to 1938 with nothing erroring. The guard existed to turn that silent move into
a loud question.

**The migration was made deliberately on 2026-08-14 and the guard now defends the
POST-migration file.** Three things changed together:

  1. availability=True   -- adopted on the minutes model's own component metrics
     (P(start) AUC 0.9491 -> 0.9607, E[min] MAE 12.82 -> 11.24), never on a season
     total. The artefact now matches the code instead of contradicting it.
  2. dgw_handling=per_fixture -- the master equation is evaluated once per
     player-fixture and summed, so a double gameweek carries both opponents. The
     previous build priced a double as a single fixture.
  3. odds_horizon_gws=0 -- fixed project decision, not a tunable. Only the current
     gameweek's market is reliably published at a Friday deadline.

KNOWN_ISSUES #10 is resolved by that decision. The pre-migration artefact is
preserved as `walkforward_h6_2526_prefix.parquet` so every figure that predates
the migration stays reproducible.

The fingerprint is STILL meant to be updated by hand when the baseline is moved
again. A failure here is a question ("did you mean to?"), not a bug. What it must
never do is pass silently through an unintended rebuild.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

CANONICAL = REPO / "data" / "walkforward_h6_2526.parquet"
PREMIGRATION = REPO / "data" / "walkforward_h6_2526_prefix.parquet"

# Post-migration fingerprint (2026-08-14). Season total on these predictions is
# 1940, which is a NEW BASELINE and is not comparable with the pre-migration 1984.
EXPECTED_ROWS = 165_401
EXPECTED_SPEARMAN = 0.745
EXPECTED_MAE = 1.109
TOL_RHO, TOL_MAE = 0.005, 0.02

# Pre-migration fingerprint, for the preserved file. Season total 1984.
PRE_SPEARMAN = 0.715
PRE_MAE = 1.146

WHY = (
    "\n\n*** data/walkforward_h6_2526.parquet no longer matches its post-migration "
    "fingerprint. ***\n"
    "If you just rebuilt it, check eval/walkforward.py's AVAILABILITY and\n"
    "ODDS_HORIZON_GWS constants and squad/assembly.py's grain before assuming a\n"
    "model change. If the move was deliberate, update the constants in this file,\n"
    "state the new baseline explicitly, and do not compare it with 1940 or 1984."
)


@pytest.fixture(scope="module")
def canonical():
    if not CANONICAL.exists():
        pytest.skip(f"{CANONICAL} not present")
    return pd.read_parquet(CANONICAL)


def _step0(df):
    d = df[df.horizon_step == 0].dropna(subset=["e_points", "actual_points"])
    return d.assign(actual_points=pd.to_numeric(d.actual_points, errors="coerce"))


def test_canonical_provenance_stamps(canonical):
    """The file must declare how it was made, on every row."""
    for col in ("minutes_availability", "odds_horizon_gws", "dgw_handling",
                "d1_terms_active", "cs_unified"):
        assert col in canonical.columns, (
            f"canonical file is missing the `{col}` provenance stamp -- it predates "
            "the stamp and its provenance cannot be established." + WHY)

    assert bool(canonical["minutes_availability"].iloc[0]) is True, (
        "canonical file was built WITHOUT availability features." + WHY)
    assert int(canonical["odds_horizon_gws"].iloc[0]) == 0, (
        "canonical file was built with odds beyond the current gameweek. That is a "
        "leak: only the current gameweek's market is reliably published at a Friday "
        "deadline. ODDS_HORIZON_GWS is a fixed decision, not a tunable." + WHY)
    assert canonical["dgw_handling"].iloc[0] == "per_fixture", (
        "canonical file prices double gameweeks as a single fixture. Every "
        "chip-timing conclusion drawn from it would be invalid." + WHY)


def test_d1_stamp_matches_code(canonical):
    """The file's D1 stamp must agree with assembly.D1_TERMS_ACTIVE.

    This guard exists because of the D1 contamination incident (KNOWN_ISSUES #13):
    the D1 scoring terms were implemented into assembly.py BEFORE the
    margin-calibration measurements ran, so every file regenerated afterwards
    carried the terms with no stamp to reveal it, and "baseline" figures were
    measured on D1 files. Same class as the availability footgun (#10): source and
    artefact disagreeing with nothing failing loudly.

    Like the rest of this file, a failure here is a question ("did you mean to
    flip D1 without rebuilding?"), not necessarily a bug.
    """
    assert "d1_terms_active" in canonical.columns, (
        "canonical file is missing the `d1_terms_active` provenance stamp -- it "
        "predates the stamp and may carry D1 terms silently. Establish its status "
        "from the data (pts_saves non-zero on GK rows) before trusting any "
        "comparison built on it. KNOWN_ISSUES #13." + WHY)
    import assembly
    stamped = bool(canonical["d1_terms_active"].iloc[0])
    assert stamped == bool(assembly.D1_TERMS_ACTIVE), (
        f"canonical file is stamped d1_terms_active={stamped} but "
        f"assembly.D1_TERMS_ACTIVE={bool(assembly.D1_TERMS_ACTIVE)}. Source and "
        "artefact disagree about whether the D1 scoring terms are in the equation "
        "-- the exact failure mode of the D1 contamination incident. Either rebuild "
        "the file or flip the constant back, deliberately." + WHY)


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


def test_doubles_are_counted(canonical):
    """The defect this migration closed, asserted directly rather than implied.

    409 player-gameweeks in 2025-26 have two fixtures. If they are priced as one,
    `n_fixtures` is missing or never exceeds 1.
    """
    assert "n_fixtures" in canonical.columns, (
        "canonical file has no `n_fixtures` column, so doubles cannot be "
        "distinguished from singles." + WHY)
    step0 = canonical[canonical.horizon_step == 0]
    n_doubles = int((step0["n_fixtures"] == 2).sum())
    assert n_doubles == 409, (
        f"expected 409 doubled player-gameweeks at horizon 0, found {n_doubles}." + WHY)


def test_premigration_file_preserved():
    """Pre-migration figures must stay reproducible, not just documented."""
    if not PREMIGRATION.exists():
        pytest.skip(f"{PREMIGRATION} not present")
    d = _step0(pd.read_parquet(PREMIGRATION))
    rho = spearmanr(d.e_points, d.actual_points).statistic
    mae = (d.e_points - d.actual_points).abs().mean()
    assert abs(rho - PRE_SPEARMAN) < TOL_RHO, (
        f"the preserved pre-migration file no longer reproduces its own fingerprint "
        f"(Spearman {rho:.4f} != {PRE_SPEARMAN}). Every figure quoting 1984 depends "
        "on this file being intact.")
    assert abs(mae - PRE_MAE) < TOL_MAE, (
        f"preserved pre-migration MAE {mae:.4f} != {PRE_MAE}.")


def test_canonical_and_premigration_are_distinct():
    """The two builds must not be the same artefact under two names."""
    if not (PREMIGRATION.exists() and CANONICAL.exists()):
        pytest.skip("both walk-forward files required")
    a, b = _step0(pd.read_parquet(CANONICAL)), _step0(pd.read_parquet(PREMIGRATION))
    rho_a = spearmanr(a.e_points, a.actual_points).statistic
    rho_b = spearmanr(b.e_points, b.actual_points).statistic
    assert rho_a > rho_b, (
        "the post-migration build should rank better at horizon 0 "
        f"(got {rho_a:.4f} vs {rho_b:.4f}) -- are these the same file?")


def test_availability_default_is_declared():
    """The harness stamps this constant, so it must exist to be stamped."""
    import minutes
    assert isinstance(minutes.AVAILABILITY_DEFAULT, bool)


def test_equation_exists_in_exactly_one_place():
    """The duplicated master equation is what let the DGW defects survive a fix.

    It lived in squad/assembly.py AND eval/walkforward.py; the second copy produced
    the file the simulator reads, so correcting the first changed nothing. Pinned so
    a future 'lift the components out' refactor cannot quietly reintroduce it.
    """
    # Scanned over the production paths only. Tests/ is excluded because this file
    # necessarily contains the marker string itself.
    marker = 'a["pts_appear"] ='
    hits = [p for d in ("squad", "eval") for p in (REPO / d).rglob("*.py")
            if marker in p.read_text(encoding="utf-8", errors="ignore")]
    assert len(hits) == 1, (
        "the master equation must exist in exactly one place; found it in: "
        + ", ".join(str(p.relative_to(REPO)) for p in hits))
    assert hits[0].name == "assembly.py"
