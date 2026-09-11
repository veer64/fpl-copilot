"""THE AS-OF RECONSTRUCTION GUARD (eval/asof_reconstruction.py) -- the standing
test that a walk-forward frame reads nothing from after its cutoff.

Why it exists: three leaks (LEAKAGE.md items 6, 7-8 and 9; KNOWN_ISSUES #22)
passed the parity suite bit-for-bit, because parity rebuilds a historical
cutoff from the SAME on-disk inputs the record was built from, with the target
gameweek already played. This test rebuilds the cutoff from inputs TRUNCATED to
the deadline's information set (stack, core-insights, Understat, odds results
and prices, availability -- and, for the combined config, the horizon-minutes
refit reconstructed in-process rather than read from disk) and asserts every
non-outcome column is bit-identical to the record file. A column that moves is
reading post-cutoff information.

Cutoffs: 20 (the parity gameweek) and 24 (its horizon spans the GW26 double
gameweek). Both configs. Slow (each combined cutoff refits the five horizon
sub-models for five steps); that is the price of the guarantee.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import asof_reconstruction as ar  # noqa: E402

SEASON = "2025-26"
CUTOFFS = [20, 24]


@pytest.mark.parametrize("config", ["baseline", "combined"])
@pytest.mark.parametrize("k", CUTOFFS)
def test_frame_reads_nothing_after_the_cutoff(config, k):
    path = ar.canonical_path(SEASON, config)
    if not path.exists():
        pytest.skip(f"{path.name} not on disk")
    import pandas as pd
    canon = pd.read_parquet(path)
    if not (canon["cutoff"] == k).any():
        pytest.skip(f"{path.name} has no rows at cutoff {k}")
    frame, _ = ar.build_asof(SEASON, k, config=config, horizon=6)
    table, row_ok, only_canon, only_live = ar.compare(frame, canon, k)
    assert row_ok, f"row set differs from the record at cutoff {k} [{config}]"
    assert not only_canon and not only_live, (
        f"column sets differ: only-record {only_canon}, only-as-of {only_live}")
    assert len(table) == 0, (
        f"[{config}] cutoff {k}: these columns read post-cutoff information "
        f"(rows differing per step, max |delta|):\n"
        + table.to_string(index=False))
