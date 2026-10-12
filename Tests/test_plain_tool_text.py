"""Part 2 of v4.2 (2026-10-09): the human-readable tool strings the v4.1 replies copied jargon from are in
plain words -- explain's formulas (npxG/90, xA/90, Poisson, E[floor]), the fixture provenance ("pure
Dixon-Coles"), get_prediction's fidelity captions (P10 / P50 / P90) and the hold refusal. JSON keys are
unchanged. The prompt carries one translation line.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import explain                                             # noqa: E402
import fixtures_tool as ft                                 # noqa: E402
import quantiles as qt                                     # noqa: E402
from test_explain_prediction import _row, _step            # noqa: E402
from test_quantiles import a_row                           # noqa: E402

JARGON = re.compile(r"\bnpxG\b|\bxA(/90)?\b|Poisson|E\[floor|\bP\(|Dixon[- ]Coles|\bP(10|50|90)\b", re.I)


def test_explain_formulas_are_in_plain_words():
    r = _row(gw=6, step=0)
    bd = explain.breakdown(r, _step([r]))
    for line in bd["lines"]:
        assert not JARGON.search(line["formula"]), (line["term"], line["formula"])
        for n in line["notes"]:
            assert not JARGON.search(n), n
    goals = next(l for l in bd["lines"] if l["term"] == "goals")
    assert "expected goals per 90" in goals["formula"]
    assists = next(l for l in bd["lines"] if l["term"] == "assists")
    assert "expected assists per 90" in assists["formula"]
    gk = _row(position="GK", p_dc_hit=0.0, saves_per_90=2.31, pts_saves=0.41, pts_conceded=-0.27, p_cs=0.368)
    bd2 = explain.breakdown(gk, _step([gk]))
    for term in ("saves", "goals_conceded", "appearance", "clean_sheet"):
        f = next(l for l in bd2["lines"] if l["term"] == term)["formula"]
        assert not JARGON.search(f), (term, f)
    assert not JARGON.search(bd2["rendered"].splitlines()[-2]), bd2["rendered"].splitlines()[-2]   # the fixture line
    assert set(bd) == set(explain.breakdown(r, _step([r])))                                          # no key moved


def test_fixture_provenance_is_a_planning_estimate_not_a_model_name(monkeypatch):
    skel = pd.DataFrame([(1, 6, "Newcastle", 7, True, "2026-10-10T14:00:00Z")], columns=ft.SKELETON_COLS)
    monkeypatch.setattr(ft, "_team_names", lambda: {7: "Coventry City", 14: "Newcastle"})
    cal, n = ft.calendar(df=skel)
    row = {"team": "Newcastle", "gw": 6, "team_lambda": 1.6, "opp_lambda": 1.2, "p_cs": 0.3, "horizon_step": 3,
           "odds_horizon_gws": 0, "n_fixtures": 1}
    out = ft.build([row], cal, n, team="Newcastle", gw=6)
    fx = out["fixtures"][0]["fixtures"][0]
    assert "planning estimate based on team strength" in fx["provenance"]["priced_off"]
    assert "LOWER QUALITY" in fx["provenance"]["priced_off"]
    blob = json.dumps(fx)
    assert "Dixon-Coles" not in blob, blob
    assert set(fx["provenance"]) >= {"source", "constant", "priced_off", "market_priced", "how_known", "horizon_step", "notes"}
    r = _row(gw=6, step=3, odds_horizon_gws=0)
    assert any("planning estimate based on team strength" in x for x in explain.fixture_provenance(r)[2])


def test_fidelity_captions_say_low_end_middle_top():
    f = qt.fidelity({**a_row(), **qt.quantiles_for_row(a_row(), 6, n=2000)})
    strings = [f["summary"], f["p90_caveat"], f["p10_caveat"]] + [x["what"] for x in f["fragilities"]] + \
              [z["effect"] for z in f["zero_variance_terms"]] + ([f["degenerate_note"]] if f["degenerate_note"] else [])
    for s in strings:
        assert not re.search(r"\bP(10|50|90)\b|Dixon[- ]Coles", s), s
    assert f["summary"].endswith("bias the top of the range low.")
    assert [x["affects"] for x in f["fragilities"][:3]] == ["P90", "P90", "P90"]       # the data labels are unchanged
    deg = qt.fidelity({**a_row(), "q_degenerate": True})
    assert "low end" in deg["degenerate_note"] and "one-sided" in deg["degenerate_note"] and "P10" not in deg["degenerate_note"]


def test_the_hold_refusal_and_the_wildcard_refusal_name_no_model():
    src = (REPO / "model_tools.py").read_text(encoding="utf-8")
    assert "Dixon-Coles strength has run off" not in src
    assert "team-strength estimate has run off" in src


def test_the_prompt_carries_the_translation_line():
    import agent
    p = agent.SYSTEM_PROMPT
    assert ("When a tool uses a technical label, say it in plain words: npxG -> expected goals, xA -> expected assists, "
            "P10/P50/P90 -> the low end / middle / top of the likely range, p_play_any -> the chance of playing at all") in p   # Part C: the line continues
