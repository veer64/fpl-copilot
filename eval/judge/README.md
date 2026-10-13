# The LLM judge (eval/judge)

One Opus call per (answer, metric) scores an agent answer against a fixed rubric; applicability is decided by code,
never by the judge; numbers are verified by code. Final trust table below (2026-10-13). Measured values only.

## The six metrics (the user and the judge read the same text, `metrics.py`)

| metric | one line | the exact question |
|---|---|---|
| M1 Plain language | no jargon a fan would not understand | "Is there any word or phrase in the reply that a typical football fan would not understand?" |
| M2 Answers the question | the reply answers what was asked (a needed clarification or a by-design limit also passes) | "Does the reply answer what the user actually asked?" |
| M3a Faithful (claims in words) | every worded fact about a player / club / match has a source; the prompt's REQUIRED sentences never count against it | "Does the reply state any fact in words about a player, club or match ... that is NOT supported by the tool results, the context block, the user's message or the allowed general facts?" |
| M3b Faithful (numbers, code-verified) | every number has a quoted source about the same player, gameweek and stat | "Is every number in the reply supported by a quoted source -- direct, derived by simple arithmetic, or an FPL rule -- about the same player, club, gameweek and stat?" |
| M4 Availability first | UNAVAILABLE (status u, or injured / suspended at 0% or unknown): flag before any number, never recommended; DOUBTFUL (status d, 25-75%): flag stated somewhere, order free | "For each flagged player the reply engages with: if he is UNAVAILABLE ..., does the reply state his availability flag BEFORE any predicted number for him, and never recommend, captain, start or lock him as if he could play? If he is DOUBTFUL ..., is his flag clearly stated somewhere in the reply (order does not matter)?" |
| M5 Right answer shape | one sheet-specific shape question (line-up value, fixture scores, transfers, forced starters) | per sheet, `metrics.M5_QUESTIONS` |

## What the judge sees, who decides what

- Every call carries, in tags with closing tags escaped: the context block the agent saw, the user question (and the
  setup turn with its tool results), every tool result of the turn exactly as the model saw it, and the reply as the
  user saw it (Sources list removed); M3a / M3b also get the allowed general facts (FPL's rules from the prompt's
  section 0, the by-design limits, the REQUIRED sentences); then the one metric block and the output instruction.
- Applicability is CODE: M1 / M2 / M3a always; M3b only when the reply holds a number claim; M4 only when a tool row
  of the turn flags a player the reply engages with (a price-only mention inside a refusal does not count), and the
  M4 block lists each such player with his tier from the tool row; M5 only on its sheets. An N/A pair is never sent.
- M3b code lock (`number_claims.py`): code extracts every number, the judge returns one item per number with the
  exact quote; code verifies coverage, every quote, every number, every derivation and every count, and recomputes
  the verdict (FAIL if any WRONG / UNSUPPORTED). `attribution_check.py` checks, by code, that a DIRECT / DERIVED
  quote belongs to the same player, gameweek and stat family as the claim (0 conflicts on 126 items, 2026-10-13).
- The judge's verdict on M1 / M2 / M3a / M4 / M5 is the model's; on M3b it is code's.

## Trust table (final, 2026-10-13)

Calibration = 38 answers vs `calibration_v1_gold.json` (user labels + the user's review calls); fresh = 15 answers
the judge had never been tuned on, vs `fresh_v1_gold.json` (user labels + review calls). jP/gF = judge PASS where
the gold says FAIL (the dangerous direction). Flips = the same answers judged twice.

| metric | calibration: n, agreement, jP/gF | fresh: n, agreement, jP/gF | flips | FINAL | reason |
|---|---|---|---|---|---|
| M1 | 38, 86.8%, 0 | 15, 100%, 0 | fresh 0/15; calibration 0/38 (run 3 vs 4; 10.5% on runs 1 vs 2) | REPORT-ONLY | calibration below 90% (5 judge-FAIL where the gold kept the user's label) |
| M2 | 38, 94.7%, 0 | 15, 100%, 0 | 0/15; 1/38 | **TRUSTED** | >= 90% on both sets, 0 jP/gF |
| M3a | 38, 89.5%, 0 | 13, 100%, 0 | 1/15; 0/38 | REPORT-ONLY | calibration one answer short of 90% (4 judge-FAIL vs user labels; 0 jP/gF) |
| M3b | 34, 100%, 0 | 11, 100%, 0 | 0/13; 1/33 | **TRUSTED** | quotes verified by code, attribution spot-checked by code (0 conflicts) |
| M4 | 10, 100%, 0 | 3, 100%, 0 | 0/3; 0/11 | REPORT-ONLY | redefined 2026-10-13 (two tiers); only 3 fresh-gold examples, 10 needed (7 more) |
| M5 | 14, 92.9%, 1 | 2, 100%, 0 | 0/2; 1/14 | REPORT-ONLY | a judge-PASS/gold-FAIL on calibration; 2 fresh examples |

`run_agent_evals.TRUSTED_METRICS = ("M2", "M3b")` is this table; the gate (`judge_gate`) counts only a confirmed
FAIL (three FAIL verdicts in a row) on a trusted metric.

## How to run

- In the eval: `python eval/run_agent_evals.py --core --judge` judges exactly the TRUSTED metrics after each answer
  (`--judge-max-usd`, `--judge-max-calls` are the judge's own cap; a FAIL is re-judged twice). `--judge-all` adds the
  report-only metrics as report columns (`report_only: true` in the record) that never reach the gate.
- Stand-alone: from `eval/`, `PYTHONPATH="..;../squad" python -m judge.run_judge --results <answers.jsonl> --ids <ids file>
  --model claude-opus-5-5 --metrics M1,M2,M3a,M3b,M4,M5 --max-calls N --max-usd N --out judge/runs/<name>.jsonl`
  (`eval/judge/runs/` is gitignored; verdicts stay blind until labels are locked).
- Attribution check: `python eval/judge/attribution_check.py --results <answers.jsonl> --run <judge run.jsonl>
  [--numbers-sheet ...] --out <xlsx>`.

## Cost (measured, claude-opus-5-5)

- Per judged answer: M2 one call ~$0.04; M1 / M3a / M4 / M5 one call each ~$0.04-0.06 (38 M3a + 10 M4 = 48 calls,
  $1.78); M3b one call per 8 number claims, ~$0.15-0.45 per answer (a squad table is 5-6 chunks). Trusted set
  (M2 + M3b) ~$0.18 per answer: 81 calls, $6.01 for 33 core answers (2026-10-12).
- Full runs: all six metrics on 38 answers = 172 calls, $8.62-$9.81; M2 + M3b on the 166-answer eval ~$30.

## Caveats

- The blind labels were lenient (the user labelled every fresh cell PASS) and the review calls followed the judge's
  reasoning in 10 of 12 cases (anchoring, mitigated by the exact quotes the judge must give; the two USER RIGHT
  calls redefined M4).
- M4 and M5 have few examples (fresh 3 and 2); M3a is report-only by one answer; M1's calibration disagreements
  are wording the user accepted.
- M3b attribution is checked by code on a sample (126 items of 15 answers) and the code reads only names, GW labels
  and field names; 59-100 of the items per check are NOT CHECKABLE by code.
- Opus 5.5 cannot be run at temperature 0 (the parameter is rejected); flip rates above are the measured
  self-consistency.
