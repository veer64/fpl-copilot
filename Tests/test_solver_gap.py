"""The transfer/XI MIP must be solved to the EXACT optimum of its stated objective.

2026-08-27: optimize._default_solver constructed HiGHS / CBC with no gap set, so the
solver stopped at its default relative MIP gap (HiGHS mip_rel_gap 1e-4, abs 1e-6).
On this ~100-170 objective that is ~0.01-0.017 -- larger than the runner-up margin
at ~11% of transfer deadlines. Measured at 2024-25 GW3: production returned
132.4125 (action 453->129), the exact optimum is 132.4190 (action 491->9). The
returned "decision" was the solver's stopping rule. Both gaps must be 0, explicitly,
for whichever backend is chosen. These tests fail against the pre-fix code
(gapRel/gapAbs were None -> inherited defaults).
"""
import sys
from pathlib import Path

import pulp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "squad"))
import optimize  # noqa: E402
import transfer_mip  # noqa: E402


def _gaps(solver):
    """(gapRel, gapAbs) as pulp stores them: attributes on HiGHS, optionsDict on CBC."""
    rel = getattr(solver, "gapRel", None)
    absg = getattr(solver, "gapAbs", None)
    if rel is None:
        rel = solver.optionsDict.get("gapRel")
    if absg is None:
        absg = solver.optionsDict.get("gapAbs")
    return rel, absg


def test_default_solver_has_zero_relative_and_absolute_gap():
    s = optimize._default_solver()
    rel, absg = _gaps(s)
    assert rel == 0.0, f"{type(s).__name__} constructed with gapRel={rel!r}; must be 0.0 (explicit), not inherited"
    assert absg == 0.0, f"{type(s).__name__} constructed with gapAbs={absg!r}; must be 0.0 (explicit), not inherited"


def test_transfer_mip_uses_the_same_default_solver():
    """transfer_mip imports _default_solver from optimize; the fix must reach the transfer MIP."""
    assert transfer_mip._default_solver is optimize._default_solver
    rel, absg = _gaps(transfer_mip._default_solver())
    assert rel == 0.0 and absg == 0.0


def test_both_backends_accept_zero_gap():
    """Whichever backend is available, an explicit zero gap must be constructible and forwarded."""
    h = pulp.HiGHS(msg=False, gapRel=0.0, gapAbs=0.0)
    assert _gaps(h) == (0.0, 0.0)
    c = pulp.PULP_CBC_CMD(msg=False, gapRel=0.0, gapAbs=0.0)
    assert _gaps(c) == (0.0, 0.0)
