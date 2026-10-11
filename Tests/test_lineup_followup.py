"""Part 1 of the smoke fixes (2026-10-10): "How's my line-up looking?" ended with "Want me to apply this
XI to your squad?" instead of asking whether to weigh the gain against transfers or against the best
possible squad (prompt section 1, the line-up rule).

The agent repeats what the tools hand it. get_my_xi's result carried an adopt_with payload with
confirm TRUE and a description that ended by saying how to record the XI, so the model's natural
next offer was to apply it. Now the result carries the exact follow-up question (LINEUP_NEXT_QUESTION)
and a next_step that says never to offer to apply; adopt_with previews (confirm false); the
description and the prompt say the same. The numbers are untouched: the XI, the captain and the
gain are compare_roles' own figures on the same solve.

Pure: the squad read, the frame and the XI solve are monkeypatched; nothing reads the database or
the volume.
"""
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402
from test_squad_store import legal_doc, _row               # noqa: E402

QUESTION = ("Would you like me to weigh that against the transfers you could make, "
            "or against the best possible squad?")


def _team(doc):
    """The solve's team frame in the SCORING convention, built from the recorded roles."""
    rows = []
    for p in doc["players"]:
        rows.append({"element": p["element"], "name": p["name"], "position": p["position"],
                     "team": p["team"], "value": p["purchase_price"],
                     "e_points": 2.0 + p["element"] / 10,
                     "role": p["role"],
                     "bench_order": (p["bench_order"] - 1) if p["role"] == "bench" else float("nan"),
                     "p_play_any": 0.9})
    return pd.DataFrame(rows)


@pytest.fixture
def xi_env(monkeypatch):
    doc = legal_doc()
    record = _row(doc, version_id=2, gw=6, user_id=9001)
    team = _team(doc)
    # move the armband so the recorded roles leave points on the table
    team.loc[team["element"] == 13, "role"] = "start"
    team.loc[team["element"] == 15, "role"] = "CAPTAIN"
    monkeypatch.setattr(mt.squad_store, "read_active", lambda user_id=None, conn=None: record)
    monkeypatch.setattr(mt, "_current_gw", lambda: 6)
    monkeypatch.setattr(mt, "_load_pool",
                        lambda gw=None: (pd.DataFrame(), 6, pd.Timestamp("2026-10-10T09:51:00")))
    monkeypatch.setattr(mt, "_q", lambda sql, params=None:
                        [{"element": p["element"], "price_tenths": p["purchase_price"]}
                         for p in doc["players"]])
    monkeypatch.setattr(mt.squad_store, "xi_over_fifteen", lambda pool, state, prices: (team, []))
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False:
                        {"run_id": 37, "gw": 6, "season": "2026-27", "status": "SUCCESS"})
    monkeypatch.setattr(mt, "_version", lambda run, config: "x/baseline")
    monkeypatch.setattr(mt, "_frame_built", lambda c: {"built": "x"})
    monkeypatch.setattr(mt, "_next_deadline", lambda: None)
    return doc, team


def test_the_result_carries_the_follow_up_question_and_never_an_apply_offer(xi_env):
    doc, team = xi_env
    out = mt.get_my_xi()
    assert "error" not in out, out
    assert out["next_question"] == QUESTION
    assert mt.LINEUP_NEXT_QUESTION == QUESTION
    assert "never offer to apply" in out["next_step"].lower()
    assert out["adopt_with"]["confirm"] is False                    # a preview payload, not a write
    assert "apply" not in json.dumps({k: v for k, v in out.items() if k != "next_step"}).lower()


def test_the_numbers_are_compare_roles_own(xi_env):
    doc, team = xi_env
    out = mt.get_my_xi()
    want = squad_store.compare_roles(doc["players"], team)
    assert out["predicted_xi_points"] == want["optimal_xi_points"]
    assert out["recorded_roles"]["expected_gain_vs_recorded"] == want["expected_gain_vs_recorded"]
    assert out["recorded_roles"]["expected_gain_vs_recorded"] > 0
    assert out["captain"] == "P15" and out["vice"] == "P9"
    assert len(out["xi"]) == 11 and len(out["bench_in_order"]) == 4


def test_the_follow_up_text_names_no_tool():
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    names = [t["name"] for t in agent.tools_schema]
    pat = re.compile(r"\b(" + "|".join(names) + r")\b")
    assert not pat.search(mt.LINEUP_NEXT_QUESTION)
    assert not pat.search(mt.LINEUP_NEXT_STEP)


def test_the_description_and_the_prompt_say_ask_then_stop():
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent
    desc = next(t for t in agent.tools_schema if t["name"] == "get_my_xi")["description"]
    assert "never offer to apply" in desc.lower(), desc
    assert "to record this XI, pass adopt_with" not in desc
    assert "next_question" in desc
    p = agent.SYSTEM_PROMPT
    assert QUESTION in p
    assert "Never offer to apply, set or record the line-up in that answer" in p
    # the sentence Tests/test_locks_and_rules.py pins is still there
    assert ("give the gain from rearranging the current squad (`get_my_xi`), then ask whether they want it weighed "
            "against transfers or against the best possible squad, and only then call the matching tool") in p
