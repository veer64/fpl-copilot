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

## Re-tests after the two added lines (deployed ca3ee00, then c69cb42)

**"Just do it" (ca3ee00):** the agent now calls `set_my_squad(...,
confirm=False)` — the tool's own preview — and reports its result: out
Slater £4.5m, in Ömür £4.9m, free transfers 2 → used 1 → 1 remaining, hits 0,
bank 0.4 → 0.0, "nothing has been changed yet … reply confirm and I'll apply
it." `squad_versions` still one row.

**GW12, first re-test (ca3ee00):** correct headline, then the GW5 XI
delivered "if that's useful" — "you may OFFER … do not deliver it unasked"
was read as permission. Line tightened (c69cb42): the WHOLE reply is the
fact, the timing and a one-sentence offer; nothing from another gameweek in
the same message.

**GW12, second re-test (c69cb42):** "the model currently has no predictions
for GW12. The latest run covers up to GW5 (built Sat 12 Sep 11:01Z), and the
six-gameweek horizon from that point does not reach GW12 … I can give you
the GW5 best XI instead — say so and I will." One tool call, nothing
delivered.

**State at the end (2026-09-13 02:26Z).** Deployed c69cb42 (/health ok, zero
reasons); suite 364 passed, 0 skipped on each push; laptop = server;
squad_versions 1 row (no test wrote a version); the confirm path of a
transfer was not exercised live by design. Residual worth knowing: the
agent once wrote "nightly at 11:01Z", conflating the built time with the
11:00Z slot — a reading slip, not a tool error.

## 2026-09-14 — the false-premise / invented-story / self-contradiction failure, and the presentation pass

**What happened (user report, afternoon).** Asked "why did you captain João Pedro over Haaland?", the agent
accepted the premise, ran a GW5 comparison (Haaland 5.10 v João Pedro 3.64), and — instead of noticing the
premise did not match — invented a paragraph about the optimiser's squad context to reconcile them; it also
quoted João Pedro at 3.64 and at 6.75 in one answer. **What the data actually said:** run 5's free-pick squad
for GW4 (`get_picks`) DID captain João Pedro, 6.75 v Haaland 5.89 for GW4; the user's recorded squad
(`get_my_squad`) has Haaland; the 3.64 and 5.10 were GW5's figures. So both numbers were real and unlabelled,
the premise was true for one "picks" and false for the other, and the right answer needed no story: the GW4
numbers explain the GW4 captaincy on their own.

**Prompt changes (commits 6191e00 and 8f6ffc2; wording shown to the user first):** section 1 gains four rules —
a claim inside the question is not a given (check it, name the tool and the gameweek, say so and ask if it
differs); two things are "the picks" (the optimiser's free-pick squad v the user's squad; check both, name
which); never explain a past choice from inference (only that run's and gameweek's numbers, else "I can't see
why from here"); the gameweek is part of the number, and an answer must not disagree with itself — plus,
after the first re-run, "this week" means the next deadline's gameweek (a tool returning the run's first
gameweek between deadlines is returning the one just played). Section 3: a conditional next run is stated as
its condition, never "check back for the schedule". New section 10, how much of a breakdown to show: verdict
and the carrying terms from the tool's `sentence`, zero lines hidden, one freshness line, no tables or
`rendered` block in any comparison unless asked, labels only where they decide the answer, every "because"
from the tool's inputs, one quantity for "X or Y". Twelve phrases pinned in `Tests/test_agent_prompt.py`.

**One tool change, because the label came from the tool, not the wording:** `compare_players` returned
`next_gw_e_points` for the run's FIRST horizon gameweek — between deadlines the one just played — and its
description said "next-gameweek". The first re-run called GW4's 5.9 v 4.5 "next gameweek" while GW5 was the
next deadline. Now `first_gw` / `first_gw_e_points` / `horizon_gws`, `built` and `next_run_expected` carried,
`note_stale` when `first_gw` is behind the next deadline, `verdict_basis` named; the description steers "X or
Y this week" to `compare_predictions`. `Tests/test_compare_players_gw.py` (2). Structured output of the
explain tools unchanged.

**Before / after, each case from a reset conversation, on the deployed container (before = 2a8a70c;
after = 8f6ffc2).**

### 1. "why did you captain João Pedro over Haaland?"
BEFORE (fresh conversation):
```
There's a misconception here worth clearing up straight away: **the recorded captain on your squad is Erling Haaland, not João Pedro.** João Pedro isn't even in your squad.

A couple of important caveats though:

1. **The recorded roles are STALE.** They were set when the squad was seeded on 2026-09-12 at 05:24, but a newer model run (run 5) was built at 11:01 on the same day — after the roles were recorded. So the captain recorded (Haaland) is a snapshot from the earlier run, not a recommendation from the current one.

2. **For this week's captaincy advice**, I should run `get_my_xi` which uses the latest model run to solve the optimal XI and captain from your squad. Want me to do that?
```
(The afternoon exchange, with history, went the other way — it explained the premise with an invented
optimiser story. Both wrong: neither named which "picks" nor the gameweek.)

AFTER:
```
The premise doesn't match what the tools show. Let me be specific about both:

**Your squad** (recorded at GW4 seed, 12 Sep 05:24Z): captain is **Haaland**, vice is **Phil Foden**. João Pedro is not even in your squad.

**The optimiser's free-pick squad** (run 5, GW4, built 12 Sep 11:01Z): that one captains **João Pedro**, with Haaland as vice, at expected points of 6.75 vs 5.89 for GW4. But that is the optimiser's own team — not your team.

So "I" didn't captain João Pedro over Haaland on your squad — your recorded captain is Haaland. Note also that those recorded roles are **stale**: they were written before run 5 was built, so I'd recommend calling up your best XI to get the current advice. Want me to do that?
```
Both sources named with their gameweek, the GW4 numbers given as the reason, no story, and a question back.

### 2. "Haaland or Isak?"
BEFORE:
```
**Haaland**, and it's not particularly close.

*Model built 2026-09-12 11:01 UTC. Next run expected: check back for the scheduled update.*

| | Haaland (£15.5m) | Isak (£9.1m) |
|---|---|---|
| Next GW expected pts | **5.9** | 4.5 |
| Start probability | **99%** | 89% |
| 6-GW horizon total | **29.9** | 20.6 |

Haaland leads on every metric — nearly a full point more next gameweek, a higher start probability, and a 9-point edge over the six-week horizon. The model's verdict is clearly **Haaland**.

The obvious caveat is price: Haaland costs £6.4m more than Isak. If you're working within a tight budget, that differential matters for the rest of your squad. Want me to run the optimiser to see how each fits into the best possible squad at your budget?
```
(A grid, a six-week total, a price caveat, "check back for the scheduled update", and GW4's figures called
"next gameweek".)

AFTER:
```
**Haaland, by 2.1 points for GW5.** (5.10 vs 3.00)

⚠️ *These predictions are one gameweek stale — built from the GW4 cutoff on Sat 12 Sep. The next fresh run lands once GW4 is confirmed by FPL and ingested (checks at 00:17 / 06:17 / 12:17 / 18:17 UTC), then nightly at 11:00 UTC.*

The gap is almost entirely **goals** (73% of the difference): Haaland's model has him at 0.79 npxG/90 vs Isak's 0.53, and crucially Haaland is playing at home (fixture scale 0.92) while Isak is away (scale 0.71). The expected minutes gap adds another 15% via assists, with Haaland at a 99% start probability versus Isak's 89%.

Worth noting: at this step the fixture scale only captures home/away — it does not yet reflect opponent quality. A fresh run may shift things once the full fixture strength is known. Check back after GW4 is ingested.
```
Verdict with the gameweek, one freshness line stated as its condition, the carrying term with its share and
its inputs, the home/away caveat from the tool's own flag. Still one line more than the target (start
probabilities), noted.

### 3. "give me the full breakdown of Haaland's expected points this week"
BEFORE and AFTER both produce the full block — every term, the zeros, the labels, the fixture line — with one
freshness note. AFTER:
```
Here is the full breakdown for **Erling Haaland (FWD, Man City) — GW5: 5.10 expected points**.

**⚠️ Freshness note:** This is one gameweek stale — the frame was built on **Sat 12 Sep 11:01Z** and predicts from the GW4 cutoff. A fresh run lands once GW4 is confirmed by FPL and ingested (ticks at 00:17 / 06:17 / 12:17 / 18:17Z), then nightly at 11:00Z. Check back after that for up-to-date GW5 numbers.

---

```
Erling Haaland (FWD, Man City) — GW5: 5.10 expected points
(reconciles: yes)

  goals                  +2.80   e_goals 0.700
                                 (npxG/90 0.79 × 0.97 of 90 min × fixture 0.92
                                  + pens 0.000) × 4 pts                        [model]
    of which penalties   +0.00   penalty_share 0.083 × team_pen_rate 0.000
                                 × 0.97 min × 4 pts                            [model]
  appearance             +1.96   P(60+) 0.97 × 2 + P(play <60) 0.02 × 1      [model]
  assists                +0.47   e_assists 0.158
                                 (xA/90 0.18 × 0.97 of 90 min × fixture 0.92)
                                 × 3 pts                                        [model]
  cards                  -0.15   -(yellow 0.143/90 × 1 + red 0.005/90 × 3)
                                 × 0.97 min                                     [constant: position rates]
  defensive contribution +0.01   p_dc_hit 0.005 × 2 × 0.97 min               [constant: flat by design]
  clean sheet            +0.00   FWD: 0 pts                                    [rule]
  saves                  +0.00   not a GK                                       [rule]
  goals conceded         +0.00   not GK/DEF                                    [rule]
  bonus                  +0.00   bonus model switched off                       [constant: 0 by decision]

  Fixture: team λ 1.284 / opp λ 1.0 → scale 0.9172
           [constant: the fit's starting point — no team-strength differentiation at this step]
```

---

**Key things to note:**

- **Goals (+2.80)** is the dominant term, driven by a high npxG/90 of 0.79, a 97% minutes fraction, and a fixture scale of 0.92. **The penalty sub-line is zero** — this is a known issue (#19): the team penalty rate is built from penalties *missed*, so it reads 0.000. Haaland's actual penalty threat is not captured here.
- **Appearance (+1.96)** reflects a 98.8% start probability and 97.2% chance of 60+ minutes.
- **Assists (+0.47)** from xA/90 of 0.18.
- **Cards (−0.15)** is a constant using position-average rates, not a Haaland-specific model.
- **Bonus is switched off** — the model notes this understates by ~0.3 pts/week on average.
- **Fixture scale** is also a constant at this step (home/away only, no team-strength differentiation), which is flagged as a known limitation of this run.
```

### 4. "how many points is João Pedro expected to get, and how does that compare to Haaland?"
BEFORE and AFTER both ask which João Pedro (Chelsea FWD or Brighton DEF) via `resolve_player` before quoting
any number — the self-contradiction of the afternoon came from the conversation's history naming the Chelsea
one and the two gameweeks going unlabelled; the gameweek rule now covers it.

Deployed: 6191e00 (16:09Z) and 8f6ffc2 (16:17Z), container SHA confirmed each time, no slot running, the
18:17Z ingest tick untouched.

**Two lines added 2026-09-14 evening (approved as written):** section 10 -- the model does not calculate bonus
points; that changes the level, not comparisons (real scores run higher by ~0.3 a week for a regular starter,
~0.4 for the top predicted players -- measured on 2023-24 to 2025-26: mean realised bonus 0.29 per player-gw
at 60+ minutes, 0.39 for the top 30 by e_points); said once per conversation the first time an absolute
figure is given, never as a zero line. Section 9 -- round a figure the same way every time it appears in a
conversation (the 98.8% / 99% pair was one 0.9875 rounded two ways, not two figures). The penalty check that
prompted this pass is recorded in KNOWN_ISSUES #19 (correction of the reading) and the penalty prereg's
addendum; the term is not reopened.
