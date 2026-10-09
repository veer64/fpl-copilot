"""Part 1 of v4.2 (2026-10-09): nothing volunteers the penalty limitation any more.

The prompt's quantiles line told the model to say, with every ceiling, that "regular penalty takers'
ceilings are understated", and get_prediction's fidelity block said the same in three places -- all in
conflict with the one-sentence rule that penalties are mentioned only when the user asks. The range
caveat is now plain and cause-free: "the top of the range is the least certain figure." The only
penalty note left is explain's detail-level floor sentence.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import explain                                             # noqa: E402
import quantiles as qt                                     # noqa: E402
from test_quantiles import a_row                           # noqa: E402

CAVEAT = "the top of the range is the least certain figure"


def _fid():
    return qt.fidelity({**a_row(), **qt.quantiles_for_row(a_row(), 6, n=2000)})


def _strings(obj, key=None):
    """Every human-readable string in the block; the `term` values are data labels and are not strings about anything."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k != "term":
                yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, key)
    elif isinstance(obj, str):
        yield obj


def test_the_fidelity_block_never_mentions_penalties():
    f = _fid()
    offenders = [s for s in _strings(f) if "penalt" in s.lower()]
    assert offenders == [], offenders
    assert [x["term"] for x in f["fragilities"][:3]] == ["bonus", "penalties", "minutes shape"]   # the data labels stay


def test_the_range_caveat_is_plain_and_gives_no_cause():
    f = _fid()
    c = f["p90_caveat"]
    assert c.startswith("The top of the range is the least certain figure.")
    for cause in ("bonus", "penalt", "minutes shape", "upper tail", "P90", "P50"):
        assert cause not in c, cause
    assert "comparable in quality to the middle" in c


def test_the_fragility_entries_name_no_cause_for_penalties():
    f = _fid()
    pen = next(x for x in f["fragilities"] if x["term"] == "penalties")
    assert "MISSED" not in pen["what"] and "KNOWN_ISSUES" not in pen["what"] and "penalt" not in pen["what"].lower()
    zv = next(z for z in f["zero_variance_terms"] if z["term"] == "penalties")
    assert "penalt" not in zv["effect"].lower() and "KNOWN_ISSUES" not in zv["effect"]


def test_the_detail_level_penalty_note_is_the_only_one_left():
    assert explain.PEN_NOTE == "penalty upside is not fully counted; for regular takers treat the figure as a floor."
    src = (REPO / "quantiles.py").read_text(encoding="utf-8")
    assert "penalties MISSED" not in src and "takers' ceilings" not in src


def test_the_prompt_no_longer_volunteers_penalties_with_the_range():
    import agent
    p = agent.SYSTEM_PROMPT
    assert "regular penalty takers' ceilings are understated" not in p
    assert CAVEAT in p
    # the one place penalties may be mentioned: when the user asks (the rule from v4.1)
    assert "Never volunteer the penalty limitation." in p
    line = next(l for l in p.splitlines() if "`quantiles` block" in l)
    assert "penalt" not in line.lower() and "bonus" not in line.lower()
