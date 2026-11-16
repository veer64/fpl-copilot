"""Prompt R1 (2026-11-14), brought over by Prompt R3 (2026-11-16): normal chat replies are no longer cut off.

The reply cap is 2,048 tokens on EVERY turn (was 1,024 on non-draft turns; a draft turn was already 2,048). If a reply still
stops at the cap (stop_reason max_tokens), the safety net:
- trims the text to its last complete paragraph / list item / table row -- never half-written markdown: the unfinished last
  line goes, an unclosed code fence goes with everything after it, a heading / table header / lead-in line whose content was
  lost goes too; with no complete line left, the last complete sentence; with nothing at all, the round-cap reply;
- adds on its own line: (I had to stop there. Reply "continue" for the rest.)
- the same for a send-back rewrite that stops at the cap;
- a tool call cut by the cap is never run -- and (R3) the turn does NOT end there: R1 ended it with the trimmed lead-in or the
  round-cap reply, two non-answers in its own eval (digest C3, C4). None of the cut round's calls is run, ONE app note goes
  back in place of the results and the model continues (Tests/test_r3_direct.py pins the note and the round count);
- the history ends on exactly what the user was shown (never a tool call without its result);
- the turn's trace metadata and agent.LAST_TURN carry stop_reason and truncated.
Both engines, through test_agent_graph's harness (fake model, tracing on the fake backend, DB writes captured)."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_agent_graph import h, _both, ROUND, ANSWER          # noqa: E402,F401  (h: the harness fixture)
from test_tracing import _Block, _Resp, _text, _tool, XI, RIGHT, WRONG   # noqa: E402
import turn_context                                           # noqa: E402

LINE = '(I had to stop there. Reply "continue" for the rest.)'
NOTE = "Your last request was cut off — ask for fewer players at once, or use rank_players"
AFTER = "Ask me about fewer players at once and I will go through them."
CAPPED_REPLY = "I couldn't finish that answer within the step limit. Please ask a narrower question."
CUT = "Here is your squad:\n\n- **Raya** keeps goal.\n- **Saliba** starts at the back.\n- **Gabr"
KEPT = "Here is your squad:\n\n- **Raya** keeps goal.\n- **Saliba** starts at the back."


def _cut(text, *extra):
    return _Resp([_Block("text", text=text), *extra], "max_tokens")


def _root(s):
    return [o for o in s["trace"]["observations"] if o["parent"] is None][0]


# ---- C1 the trim (pure) ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,kept", [
    ("Para one.\n\nPara two is cut mid", "Para one."),
    ("Intro.\n\n- a done\n- b done\n- c cu", "Intro.\n\n- a done\n- b done"),
    ("| P | Pts |\n|---|---|\n| A | 1 |\n| B | 2 |\n| C | ", "| P | Pts |\n|---|---|\n| A | 1 |\n| B | 2 |"),
    ("Intro.\n\n| P | Pts |\n|---|---|\n| A ", "Intro."),                      # a table with no complete row goes
    ("Text.\n\n```\ncode line\nmore", "Text."),                                  # an unclosed code fence goes
    ("Text.\n\n## Next steps\n\nSome", "Text."),                                 # a heading whose section was lost goes
    ("Text.\n\n**A few highlights:**\n- one", "Text."),                          # a lead-in whose list was lost goes
    ("Para one.\n\nPara two.\n", "Para one.\n\nPara two."),                      # cut exactly at a line end: nothing lost
    ("One long paragraph. Second sentence is cu", "One long paragraph."),        # no complete line: the last sentence
    ("no sentence at all", ""),
    ("", ""),
])
def test_c1_the_trim_keeps_only_complete_markdown(text, kept):
    import agent
    assert agent.trim_cut_reply(text) == kept


def test_c1_the_fixed_line():
    import agent
    assert agent.CUT_OFF_LINE == LINE


# ---- C2-C6 the turn (both engines) ----------------------------------------------------------------------------------------

def test_c2_a_reply_stopped_at_the_cap_is_trimmed_and_ends_with_the_line(h):
    s = _both(h, lambda: [_cut(CUT)], ANSWER)
    assert s["answer"] == f"{KEPT}\n\n{LINE}"
    assert s["history"][-1] == {"role": "assistant", "content": [{"type": "text", "text": f"{KEPT}\n\n{LINE}"}]}
    assert s["last_turn"]["stop_reason"] == "max_tokens" and s["last_turn"]["truncated"] is True
    meta = _root(s)["metadata"]
    assert meta["stop_reason"] == "max_tokens" and meta["truncated"] is True
    assert s["last_fact_check"]["original"] == KEPT                              # the check reads the trimmed text
    assert len(s["requests"]) == 1


def test_c3_a_tool_call_cut_by_the_cap_is_never_run_and_the_turn_goes_on(h):
    """R3 (was: "... and no text means the round-cap reply"): the cut call is answered with the app note and the model's next
    response is the reply -- never the step-limit sentence."""
    ran = []
    h.mp.setitem(h.ag.available_functions, "get_my_xi", lambda **kw: ran.append(1) or XI)
    cut_call = _Resp([_Block("tool_use", name="get_my_xi", input={"gw": 1}, id="toolu_cut")], "max_tokens")
    s = _both(h, lambda: [cut_call, _text(AFTER)], ROUND + ANSWER)
    assert s["answer"] == AFTER and s["answer"] != CAPPED_REPLY and ran == [] and len(s["requests"]) == 2
    assert s["history"][-2]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_cut", "content": NOTE}]
    assert s["last_turn"]["skipped_rounds"] == [{"why": "cut", "calls": 1, "tools": ["get_my_xi"]}]
    assert s["last_turn"]["stop_reason"] == "end_turn" and s["last_turn"]["truncated"] is False   # the delivered reply is whole
    meta = _root(s)["metadata"]
    assert meta["truncated"] is False and meta["stop_reason"] == "end_turn"


def test_c4_text_and_a_cut_tool_call_are_a_cut_tool_round_not_an_answer(h):
    """R3 (was: "... deliver the trimmed text"): a lead-in written before a cut tool call ("Now let me pull ...") is not the
    reply; the tool is not run, the note goes back, the model continues."""
    ran = []
    h.mp.setitem(h.ag.available_functions, "get_my_xi", lambda **kw: ran.append(1) or XI)
    s = _both(h, lambda: [_cut(CUT, _Block("tool_use", name="get_my_xi", input={}, id="toolu_cut")), _text(AFTER)], ROUND + ANSWER)
    assert s["answer"] == AFTER and LINE not in s["answer"] and ran == [] and len(s["requests"]) == 2
    uses = [b for m in s["history"] if m["role"] == "assistant" and isinstance(m["content"], list) for b in m["content"]
            if (b.get("type") if isinstance(b, dict) else getattr(b, "type", None)) == "tool_use"]
    results = [b for m in s["history"] if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]
               if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert len(uses) == len(results) == 1 and results[0]["content"] == NOTE      # never a tool call without its result


def test_c5_a_send_back_rewrite_stopped_at_the_cap_is_trimmed_too(h):
    rewrite = _cut(RIGHT + "\n- **Saka** is next on the li")
    s = _both(h, lambda: [_tool("get_my_xi"), _text(WRONG), rewrite],
              ROUND + ["call_model", "fact_check", "send_back", "recheck", "finalize"])
    assert s["last_fact_check"]["outcome"] == "fixed"
    assert s["answer"] == f"{RIGHT}\n\n{LINE}"
    assert s["history"][-1] == {"role": "assistant", "content": [{"type": "text", "text": f"{RIGHT}\n\n{LINE}"}]}
    assert s["last_turn"]["truncated"] is True


def test_c6_a_complete_reply_is_unchanged(h):
    s = _both(h, lambda: [_tool("get_my_xi"), _text(RIGHT)], ROUND + ANSWER)
    assert s["answer"] == RIGHT and LINE not in s["answer"]
    assert s["last_turn"]["stop_reason"] == "end_turn" and s["last_turn"]["truncated"] is False
    meta = _root(s)["metadata"]
    assert meta["stop_reason"] == "end_turn" and meta["truncated"] is False


def test_c7_nothing_complete_left_means_the_round_cap_reply_without_the_line(h):
    s = _both(h, lambda: [_cut("Your best squad for the next three game")], ANSWER)
    assert s["answer"] == CAPPED_REPLY and LINE not in s["answer"]
    assert s["last_turn"]["truncated"] is True


# ---- C8 the reply cap ---------------------------------------------------------------------------------------------------------

def test_c8_the_reply_cap_is_2048_on_every_turn(h):
    ag = h.ag
    assert ag.MAX_TOKENS == 2048 and ag.DRAFT_MAX_TOKENS == 2048 and ag._max_tokens() == 2048
    turn_context.begin("t" * 32, thread_id="th_draft", draft={"user_id": 10001, "draft_key": 800_000_001})
    try:
        assert ag._max_tokens() == 2048
    finally:
        turn_context.end()
    s = _both(h, lambda: [_text(RIGHT)], ANSWER)
    import json
    assert [json.loads(r)["max_tokens"] if isinstance(r, str) else r["max_tokens"] for r in s["requests"]] == [2048]
