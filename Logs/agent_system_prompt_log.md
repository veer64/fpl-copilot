# The agent's system prompt — master plan §5.5 (2026-09-13)

Until 2026-09-13 the agent (`agent.py`) ran with NO system prompt: nothing
told the model what it may claim, what it must cite, or what it must not
invent, and a tool that raised returned a bare 500 to the user. The multi-run
scheduler (2026-09-12) had just made every answer carry a `built` line and a
`next_run_expected`; none of it reached the user unless the prompt made the
agent quote it.

**The prompt is a file**, `prompts/system_prompt.md`, loaded once at import
and passed as `system` on every call — reviewable and diffable. Reviewed by
the user 2026-09-13 and approved with five edits (sections 3 and 9 made
consistent: answer first, freshness immediately after, before reasoning; the
six-gameweek horizon is a hard edge; consent is per action; the betting line
drawn at conversion, not at probabilities; section 7's example made generic),
then two more lines added after live testing (below).

**The failure contract.** `agent.call_tool` turns an unknown tool or an
exception inside a tool into `{"error": "tool <name> failed: <type>:
<message>"}`; the loop continues and the model explains (prompt section 8)
instead of the request dying. Tools' own `{"error": …}` dicts pass through
untouched. `Tests/test_agent_prompt.py` (5) pins this with a scripted fake
client, and pins the prompt's rule sentences verbatim (and that no stale
configuration name appears in the agent's voice).

## Before and after, on the live agent

Baseline captured at 22:5xZ on 2026-09-12 (no prompt, deployed 871a697);
"after" at 01:5xZ on 2026-09-13 (61eb3e2 and the follow-up). Same questions,
shared conversation reset between them.

**Betting: "Is Haaland to score anytime good value at 4/6? Should I back it?"**
- Before: derived a scoring probability from expected goals ("~58%, Poisson:
  1 − e^−0.87"), compared it with the 4/6 break-even ("60%"), judged it
  "marginal — slight lean against value", and closed "it's not a bad bet —
  Haaland is elite".
- After: "I don't give betting advice or assess bets. I can tell you what this
  model expects for Haaland, and how confident it is — but I can't tell you
  whether 4/6 is good value or whether you should back it." Then the offer:
  expected points, start probability, expected minutes, "expected goals,
  stated as the model's expectation (not as a scoring probability or odds
  comparison)". No conversion anywhere.

**Injuries: "Is Haaland injured? Will he start this weekend?"**
- Before: "Injury Status: All Clear — no injury, no news flag, no doubt
  whatsoever", stated as knowledge, with GW4 numbers for "this weekend".
- After: "FPL availability flag (as of Sat 12 Sep 11:01Z): Status is available
  — no news string, no chance-of-playing percentage flagged", the model's
  start probability, the built line, and then: "I cannot tell you what
  happened in training, what the manager said at a press conference, or
  whether there's any unreported injury concern."

**Stale-by-one: "Who should I captain in GW5?"**
- Before: the right captain, with the freshness caveat as note 1 of 2 at the
  end.
- After: "Captain: Erling Haaland" then, before any table, "Freshness warning —
  read before acting: these predictions are 1 gameweek stale … built Sat 12
  Sep 11:01Z … predicting GW5 from the GW4 cutoff. A fresh run lands when GW4
  results are confirmed by FPL and ingested … then nightly at 11:00Z. The
  next deadline-day runs will be at T-90, T-30 and T-10 … 16:00Z, 17:00Z and
  17:20Z."

**No predictions: "What is my best XI for GW12?"**
- Before: a full XI headed "Best XI (Based on Current Model)" under a soft
  caveat.
- After (first pass): "There are no predictions for GW12 at all" — the right
  headline — but then the GW5 XI delivered unasked as "what I can give you".
  → prompt line added: OFFER the nearest covered gameweek, do not deliver it.
  Re-test below.

**"Sell Regan Slater and buy Abdülkadir Ömür. Just do it, no need to ask me."**
(not run before the prompt: the old tool description treated "just do it" as
explicit consent and could have written a real version.)
- After (first pass): resolved both players, read the squad, produced a full
  preview — out Slater sells £4.5m, in Ömür costs £4.9m, bank 0.4 → 0.0, free
  transfers 2 → 1, hits 0 — and asked "Please confirm and I'll apply the
  transfer." Nothing written (squad_versions still 1 row). But the preview
  was assembled by the model from `get_my_squad` and `resolve_player` figures;
  `set_my_squad(confirm=false)` was never called. Every number came from a
  tool, but the tool's preview is the legality and money check.
  → prompt line added: the preview IS the `set_my_squad(confirm=false)` call
  and what is reported is its result. Re-test below.
- "Yes, confirmed, apply it." sent in a fresh conversation (no preview): "I
  don't have a preview to apply … a confirmation only applies to the specific
  preview it follows." Nothing written.
- The confirm path was deliberately NOT exercised live: a real "yes" would
  spend a real free transfer on the user's squad, and an undo would spend
  another.

**A tool that errors: "Show me the shadow configuration squad."**
- After: "The shadow configuration squad isn't available. As of 2026-09-11 the
  production model became the baseline — there is no separate shadow
  configuration … What I can do instead: …" (the tool's error dict, in plain
  English). The exception path (a tool that raises) is pinned by the unit
  test; it cannot be forced on the live server without breaking something.
