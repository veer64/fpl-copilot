"""LLM judge, final (2026-10-13): the eval runner's --judge default is exactly the TRUSTED metrics (eval/judge/README.md
trust table) and --judge-all adds the report-only metrics as report columns that never reach the gate. llm mocked."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm                                                 # noqa: E402

CARD = {"player_id": 26, "name": "Kai Havertz", "team": "Arsenal", "status": "d", "chance": 75, "news": "Knee injury",
        "prediction": {"predictions": [{"gw": 7, "e_points": 3.7}]}}


def _record(reply, calls, qid="get_player_card:1", sheet="get_player_card"):
    turns = [{"kind": "question", "message": "q", "reply": reply, "calls": calls, "context_block": "CONTEXT BLOCK - Now: x"}]
    return {"id": qid, "sheet": sheet, "question": "q", "setup": None, "turns": turns, "calls": calls,
            "rendered_reply": reply, "raw_reply": reply, "result": "PASS"}


# ------------------------------------------------------------------ runner: trusted default, --judge-all report-only
class _Fake:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def complete(self, purpose, system, user, model, max_tokens, **kw):
        self.calls += 1
        return self.answers.pop(0), {"input_tokens": 100, "output_tokens": 20, "attempts": 1, "stop_reason": "end_turn"}


def _m3b_ok():
    items = [{"id": "c1", "number": 75, "about": "Havertz", "type": "DIRECT", "quote": "'chance': 75", "why": ""},
             {"id": "c2", "number": 3.7, "about": "Havertz", "type": "DIRECT", "quote": "'e_points': 3.7", "why": ""}]
    return json.dumps({"items": items, "reason": "ok", "verdict": "PASS"})


def test_the_runner_default_is_the_trusted_list_and_judge_all_adds_report_only_metrics(monkeypatch):
    import run_agent_evals as rae
    assert rae.TRUSTED_METRICS == ("M2", "M3a", "M3b")         # M3a TRUSTED 2026-10-14: calibration 38/38, fresh 13/13
    assert rae.REPORT_ONLY_METRICS == ("M1", "M4", "M5")
    calls = [{"tool": "get_player_card", "args": {}, "error": None, "output": str(CARD)}]
    rec = _record("Havertz is flagged 75% to play; expect about 3.7 points if he plays.", calls)
    ok = '{"reason": "fine", "verdict": "PASS"}'
    fake = _Fake([ok, ok, _m3b_ok()])                                     # M2, M3a, M3b
    monkeypatch.setattr(llm, "complete", fake.complete)
    cfg = rae.JudgeConfig(model="claude-opus-5-5", max_calls=50, max_usd=5.0)
    out = rae.judge_record(rec, cfg)
    assert set(out) == {"M2", "M3a", "M3b"} and fake.calls == 3
    # --judge-all: every metric of ALL_B; the report-only ones carry report_only True and never reach the gate
    fake = _Fake(['{"reason": "jargon", "verdict": "FAIL"}'] * 3 + [ok, ok, _m3b_ok(), ok])   # M1 x3, M2, M3a, M3b, M4; M5 is N/A
    monkeypatch.setattr(llm, "complete", fake.complete)
    cfg = rae.JudgeConfig(model="claude-opus-5-5", max_calls=50, max_usd=5.0, metrics=rae.ALL_JUDGE_METRICS)
    out = rae.judge_record(rec, cfg)
    assert set(out) == {"M1", "M2", "M3a", "M3b", "M4", "M5"}
    assert out["M1"]["report_only"] is True and out["M1"]["verdict"] == "FAIL" and out["M1"]["confirmed_fail"] is True
    assert out["M2"].get("report_only", False) is False and out["M3a"].get("report_only", False) is False
    assert out["M5"]["applicable"] is False                                       # get_player_card is not an M5 sheet
    assert rae.judge_gate({"judge": out}) == []                                   # M1's confirmed FAIL is report-only
    out["M2"] = {"verdict": "FAIL", "confirmed_fail": True}
    assert rae.judge_gate({"judge": out}) == ["M2"]


def test_judge_all_flag_parses_and_implies_judge():
    import run_agent_evals as rae
    a = rae.build_parser().parse_args(["--judge-all"])
    assert a.judge_all is True
    assert rae.judge_metrics_for(a) == rae.ALL_JUDGE_METRICS
    a = rae.build_parser().parse_args(["--judge"])
    assert rae.judge_metrics_for(a) == rae.TRUSTED_METRICS
    a = rae.build_parser().parse_args([])
    assert a.judge is False and a.judge_all is False
