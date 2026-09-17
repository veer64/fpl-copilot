"""A served build whose model is DEGRADED (live_deadline.MODEL_DEGRADED findings) degrades
/health with the club and lambda named -- the loud, non-fatal detector's path to the alert
probe (user decision 2026-09-16). Pure: the run row is a dict."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import model_tools as mt                                   # noqa: E402


def test_model_degraded_findings_become_health_reasons_naming_the_club():
    run = {"run_id": 10, "strict_findings": {"baseline": [
        "note: 269 of 656 rows have no understat_id",
        "MODEL DEGRADED: Dixon-Coles strength EXTREME at horizon step 1: Coventry City lambda=0.0006 (outside [0.15, 6.0]) -- a parameter ran off",
        "MODEL DEGRADED: Dixon-Coles fit did NOT converge (L-BFGS-B success False after 189 iterations; max|attack| 7.39, max|defence| 0.88)"]}}
    r = mt._model_degraded_reasons(run)
    assert len(r) == 2
    assert r[0].startswith("model degraded (run 10, baseline): Dixon-Coles strength EXTREME") and "Coventry City lambda=0.0006" in r[0]
    assert "did NOT converge" in r[1]
    # JSONB arriving as a string, and a run with only notes
    assert len(mt._model_degraded_reasons({"run_id": 11, "strict_findings": json.dumps(run["strict_findings"])})) == 2
    assert mt._model_degraded_reasons({"run_id": 12, "strict_findings": {"baseline": ["note: x"]}}) == []
    assert mt._model_degraded_reasons({"run_id": 13, "strict_findings": None}) == []
    assert mt._model_degraded_reasons({"run_id": 14, "strict_findings": "not json"}) == []


def test_model_notes_reach_health_as_information_not_reasons():
    run = {"run_id": 15, "strict_findings": {"baseline": [
        "MODEL NOTE: hinge prior active (evidence below 10 effective matches): Coventry City (n_eff 4.0, tau 3.36)",
        "MODEL NOTE: Dixon-Coles strength CLAMPED at the plausibility bound (+-ln 4 of the league rate): Hull (defence) -- served",
        "note: 269 of 656 rows have no understat_id"]}}
    notes = mt._model_notes(run)
    assert len(notes) == 2 and notes[0].startswith("run 15, baseline: hinge prior active") and "CLAMPED" in notes[1]
    assert mt._model_degraded_reasons(run) == []          # a note never degrades
    assert mt._model_notes({"run_id": 16, "strict_findings": {"baseline": ["note: x"]}}) == []
