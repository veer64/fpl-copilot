"""Part 3 of the smoke fixes (2026-10-10): "Captain contributed a 6-point bonus".

get_my_points handed the model a key called captain_bonus for the extra points the captain's
doubled score added, and the model said "bonus" -- which in FPL means the 1/2/3 bonus points, and
which clashes with "Our model doesn't account for bonus points". The tool now says it in plain
words at the source: captain_doubled_added (the number) and captain_note (the sentence), and no
string or key in the result uses the word "bonus" for the captain. Real FPL bonus points in
get_actual_points' breakdowns are untouched.

Pure: the actuals master and the squad versions are built by hand (test_actual_points' helpers).
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import actuals_tool as at                                  # noqa: E402
import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402
from test_actual_points import master, _patch_master       # noqa: E402
from test_squad_store import legal_doc, _row               # noqa: E402

DEADLINE = pd.Timestamp("2026-09-04T17:30:00Z")


def _env(monkeypatch, gws=(3,)):
    v = _row(legal_doc(), version_id=1, gw=3, created_at="2026-09-04 10:00:00+00")
    m = master([(e, g, 100 + e, 90, 2) for g in gws for e in range(1, 16)])
    _patch_master(monkeypatch, m)
    monkeypatch.setattr(mt, "_squad_versions_for", lambda user_id: [v])
    monkeypatch.setattr(mt, "_deadline_at", lambda gw: DEADLINE)
    return v, m


def test_one_gameweek_never_says_bonus_for_the_captains_doubled_points(monkeypatch):
    v, m = _env(monkeypatch)
    out = mt.get_my_points(gw=3)
    assert "error" not in out, out
    assert "bonus" not in json.dumps(out).lower(), out
    want = squad_store.score_gameweek_for([v], 3, DEADLINE, at.actuals_frame(m, 3))
    assert out["captain_doubled_added"] == want["captain_bonus"] == 2
    assert "captain_bonus" not in out
    assert out["captain_note"] == "your captain's doubled score added 2 points"
    assert out["points_net"] == want["points_net"]                  # the numbers are the scorer's


def test_every_gameweek_uses_the_same_words(monkeypatch):
    _env(monkeypatch, gws=(3, 4))
    out = mt.get_my_points()
    assert "error" not in out, out
    assert "bonus" not in json.dumps(out).lower(), out
    assert [w["gw"] for w in out["gameweeks"]] == [3, 4]
    for w in out["gameweeks"]:
        assert "captain_bonus" not in w
        assert w["captain_doubled_added"] == 2
        assert w["captain_note"].startswith("your captain's doubled score added")


def test_the_vice_and_nobody_cases_say_so():
    assert mt._captain_words({"captain_bonus": 6, "doubled_role": "captain"}) == {
        "captain_doubled_added": 6, "captain_note": "your captain's doubled score added 6 points"}
    assert mt._captain_words({"captain_bonus": 4, "doubled_role": "vice"}) == {
        "captain_doubled_added": 4,
        "captain_note": "your vice-captain's doubled score added 4 points (the captain did not play)"}
    assert mt._captain_words({"captain_bonus": 0, "doubled_role": "none"}) == {
        "captain_doubled_added": 0,
        "captain_note": "nobody's score was doubled (neither the captain nor the vice-captain played)"}
    for case in ("captain", "vice", "none"):
        assert "bonus" not in json.dumps(mt._captain_words({"captain_bonus": 1, "doubled_role": case})).lower()


def test_the_scorer_text_the_tool_sends_has_no_bonus_either(monkeypatch):
    _env(monkeypatch)
    out = mt.get_my_points(gw=3)
    for k in ("points_meaning", "chips_note"):
        assert "bonus" not in out[k].lower(), (k, out[k])


def test_the_description_no_longer_names_captain_bonus():
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    desc = next(t for t in agent.tools_schema if t["name"] == "get_my_points")["description"]
    assert "captain_bonus" not in desc
    assert "captain_doubled_added" in desc
    assert "not FPL bonus points" in desc
