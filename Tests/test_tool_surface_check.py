"""The /health check that exercises the agent's own TOOL SURFACE (model_tools._tool_surface_check).

On 2026-09-18 reachability was green and the model-degraded reasons were green while every
get_prediction call raised UndefinedColumn for ~35 minutes. /health never called a tool, so
nothing said anything; the outage was found by a person asking a question. This check calls
get_prediction on a canary row -- the same entry point the agent uses, not a query that
resembles it.

These tests hold it to the one property that matters: EVERY way the call can fail must become
a REASON, and no failure may escape as an exception, because a probe that crashes the endpoint
it probes is worse than no probe.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.fixture()
def mt(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools
    return importlib.reload(model_tools)


def _run(mt_mod):
    return {"run_id": 15, "gw": 5, "kind": "t10", "slot": "t10:GW5", "status": "SUCCESS"}


def _wire(mt_mod, monkeypatch, canary=(411, 5), prediction=None, raises=None):
    monkeypatch.setattr(mt_mod, "_latest_run", lambda gw=None, any_status=False: _run(mt_mod))
    monkeypatch.setattr(mt_mod, "_q", lambda sql, params=(): (
        [{"element": canary[0], "gw": canary[1]}] if canary else []))
    if raises is not None:
        def boom(*a, **k):
            raise raises
        monkeypatch.setattr(mt_mod, "get_prediction", boom)
    else:
        monkeypatch.setattr(mt_mod, "get_prediction", lambda *a, **k: prediction)


def test_a_healthy_tool_surface_adds_no_reason(mt, monkeypatch):
    _wire(mt, monkeypatch, prediction={"predictions": [{"e_points": 5.1}],
                                       "quantiles": {"computed": False}})
    reasons = []
    out = mt._tool_surface_check(reasons)
    assert reasons == []
    assert out["ok"] is True and out["element"] == 411 and out["e_points"] == 5.1
    assert "get_prediction only" in out["covers"], "the check must state what it does NOT cover"


def test_an_exception_becomes_a_reason_and_never_escapes(mt, monkeypatch):
    """THE case of 2026-09-18: UndefinedColumn on every call."""
    import psycopg2
    _wire(mt, monkeypatch, raises=psycopg2.errors.UndefinedColumn('column "q_p10" does not exist'))
    reasons = []
    out = mt._tool_surface_check(reasons)          # must NOT raise
    assert out["ok"] is False
    assert any("tool surface" in r and "RAISED" in r for r in reasons), reasons
    assert any("q_p10" in r for r in reasons), reasons


def test_any_exception_type_is_contained(mt, monkeypatch):
    for exc in (RuntimeError("boom"), ValueError("bad"), KeyError("missing")):
        _wire(mt, monkeypatch, raises=exc)
        reasons = []
        assert mt._tool_surface_check(reasons)["ok"] is False
        assert reasons, exc


def test_an_error_dict_becomes_a_reason(mt, monkeypatch):
    _wire(mt, monkeypatch, prediction={"error": "no prediction rows for player 411"})
    reasons = []
    assert mt._tool_surface_check(reasons)["ok"] is False
    assert any("returned an error" in r for r in reasons), reasons


def test_an_empty_prediction_list_becomes_a_reason(mt, monkeypatch):
    """The row exists in the table but the tool hands back nothing."""
    _wire(mt, monkeypatch, prediction={"predictions": []})
    reasons = []
    assert mt._tool_surface_check(reasons)["ok"] is False
    assert any("no prediction row" in r for r in reasons), reasons


def test_a_non_numeric_e_points_becomes_a_reason(mt, monkeypatch):
    for bad in (None, float("nan")):
        _wire(mt, monkeypatch, prediction={"predictions": [{"e_points": bad}]})
        reasons = []
        assert mt._tool_surface_check(reasons)["ok"] is False
        assert any("not a number" in r for r in reasons), (bad, reasons)


def test_no_canary_row_is_its_own_reason(mt, monkeypatch):
    """An empty predictions table: the agent can answer nothing."""
    _wire(mt, monkeypatch, canary=None)
    reasons = []
    assert mt._tool_surface_check(reasons)["ok"] is False
    assert any("NO usable prediction rows" in r for r in reasons), reasons


def test_no_run_yet_is_not_a_new_reason(mt, monkeypatch):
    """last_run already says this; a second voice saying it is noise, not signal."""
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    reasons = []
    out = mt._tool_surface_check(reasons)
    assert out["ok"] is None and reasons == []


def test_a_slow_read_is_a_finding(mt, monkeypatch):
    import time as _t
    slow = mt.CANARY_MAX_MS / 1000.0 + 0.05

    def slow_call(*a, **k):
        _t.sleep(slow)
        return {"predictions": [{"e_points": 5.1}]}
    _wire(mt, monkeypatch, prediction=None)
    monkeypatch.setattr(mt, "get_prediction", slow_call)
    reasons = []
    out = mt._tool_surface_check(reasons)
    assert out["ok"] is True                       # it worked...
    assert any("degrading" in r for r in reasons)  # ...but slowly, which is itself a finding


def test_health_wires_it_in_so_the_probe_and_the_monitor_see_it():
    src = (REPO / "model_tools.py").read_text(encoding="utf-8")
    assert 'freshness["tool_surface"] = _tool_surface_check(reasons)' in src
    # and it must call the TOOL, not a lookalike query
    fn = src.split("def _tool_surface_check")[1].split("\ndef ")[0]
    assert "get_prediction(el, gw=gw)" in fn, "the check must call the entry point the agent uses"


def test_the_check_documents_what_it_cannot_see():
    """The standing question, answered in the design rather than after: the docstring must
    name the failures that would leave THIS saying ok."""
    import model_tools
    doc = model_tools._tool_surface_check.__doc__
    for needed in ("agent", "/chat", "propose_transfers", "Correctness", "circular"):
        assert needed in doc, needed
