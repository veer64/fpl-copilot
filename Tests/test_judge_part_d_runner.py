"""LLM judge Part D J8 (2026-10-12): the eval runner's --judge hook judges the TRUSTED metrics only (M2, M3b from the
fresh-set test), re-judges a FAIL twice, stops at its own cap, and is off by default (llm mocked)."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402
from judge import metrics as M                             # noqa: E402
from judge import number_claims as N                       # noqa: E402
from judge import run_judge as RJ                          # noqa: E402

# ------------------------------------------------------------------ J8
CARD = {"player_id": 26, "name": "Kai Havertz", "status": "d", "chance": 75, "predictions": [{"gw": 7, "e_points": 3.7}]}


def _rec(reply="Havertz is flagged 75% to play; expect about 3.7 points if he plays."):
    calls = [{"tool": "get_player_card", "args": {"player_id": 26}, "error": None, "output": str(CARD)}]
    return {"id": "get_player_card:1", "sheet": "get_player_card", "question": "Is Havertz fit?", "setup": None, "result": "PASS",
            "turns": [{"kind": "question", "message": "Is Havertz fit?", "reply": reply, "calls": calls, "context_block": "CONTEXT BLOCK\n- Now: x"}],
            "calls": calls, "rendered_reply": reply, "raw_reply": reply}


class _Fake:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def complete(self, purpose, system, user, model, max_tokens, **kw):
        self.calls += 1
        return self.answers.pop(0), {"input_tokens": 100, "output_tokens": 20, "attempts": 1, "stop_reason": "end_turn"}


def _m3b_ok(n=2):
    items = [{"id": f"c{i}", "number": v, "about": "Havertz", "type": "DIRECT", "quote": q, "why": ""} for i, (v, q) in enumerate([(75, "'chance': 75"), (3.7, "'e_points': 3.7")][:n], start=1)]
    return json.dumps({"items": items, "reason": "ok", "verdict": "PASS"})


def test_the_runner_judges_trusted_metrics_only_and_rejudges_a_fail_twice(monkeypatch):
    import run_agent_evals as rae
    assert rae.TRUSTED_METRICS == ("M2", "M3b")
    fake = _Fake(['{"reason": "answers it", "verdict": "PASS"}', _m3b_ok()])
    monkeypatch.setattr(llm, "complete", fake.complete)
    cfg = rae.JudgeConfig(model="claude-opus-5-5", max_calls=50, max_usd=5.0)
    rec = _rec()
    out = rae.judge_record(rec, cfg)
    assert set(out) == {"M2", "M3b"} and out["M2"]["verdict"] == "PASS" and out["M3b"]["verdict"] == "PASS"
    assert out["M2"]["verdicts"] == ["PASS"] and fake.calls == 2 and rec["judge_usd"] > 0
    # a FAIL is re-judged twice; it stands only when all three say FAIL
    fake = _Fake(['{"reason": "no", "verdict": "FAIL"}', '{"reason": "no", "verdict": "FAIL"}', '{"reason": "fine", "verdict": "PASS"}', _m3b_ok()])
    monkeypatch.setattr(llm, "complete", fake.complete)
    out = rae.judge_record(_rec(), cfg)
    assert out["M2"]["verdicts"] == ["FAIL", "FAIL", "PASS"] and out["M2"]["verdict"] == "PASS" and out["M2"]["confirmed_fail"] is False
    fake = _Fake(['{"reason": "no", "verdict": "FAIL"}'] * 3 + [_m3b_ok()])
    monkeypatch.setattr(llm, "complete", fake.complete)
    out = rae.judge_record(_rec(), cfg)
    assert out["M2"]["verdict"] == "FAIL" and out["M2"]["confirmed_fail"] is True and len(out["M2"]["verdicts"]) == 3


def test_the_runner_judge_stops_at_its_own_cap_and_marks_the_rest_not_run(monkeypatch):
    import run_agent_evals as rae
    fake = _Fake(['{"reason": "answers it", "verdict": "PASS"}', _m3b_ok()] * 3)
    monkeypatch.setattr(llm, "complete", fake.complete)
    cfg = rae.JudgeConfig(model="claude-opus-5-5", max_calls=1, max_usd=5.0)
    out = rae.judge_record(_rec(), cfg)
    assert out["M2"]["verdict"] == "PASS" and out["M3b"].get("not_run"), out
    assert fake.calls == 1


def test_judge_is_off_by_default_and_the_flag_exists():
    import run_agent_evals as rae
    ap = rae.build_parser()
    a = ap.parse_args([])
    assert a.judge is False and a.judge_max_usd > 0
