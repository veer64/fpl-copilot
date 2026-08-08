## Feature idea: backup-promotion / depth-chart effect (Wave 2+)

A player's P(start) depends on the availability of the player(s) ahead of them
in the position pecking order, not just their own history. Example: Kelleher
averages ~0 minutes (all features say "won't start"), but if Alisson (Liverpool
#1 GK) is flagged injured pre-deadline, Kelleher becomes nailed-on.

Our Wave 1 features are player-in-isolation and cannot see this.

Requires (both not yet built):
1. A depth chart: who is the established starter per team per position.
2. Pre-deadline injury/availability flag (chance_of_playing) for that starter
   — lives in live FPL bootstrap / Core-Insights, NOT in vaastav yet.

Approach when we get there: when the established starter at a position is
flagged unavailable, boost the backup's P(start). Start simple (GK is easiest —
clear #1/#2), then extend to outfield where depth charts are murkier.

Hardest part: defining "the starter ahead of them" reliably from data.
Note: GK is the clean first case (usually an obvious #1 and #2).

## Deferred: cold-start / no-history rows (revisit after baseline)

Wave 1 features (started_last_gw, starts_last3/5, avg_min_last3/5) are computed
from each player's PRIOR gameweeks. A player's first GW(s) in a season have no
prior history, so these features are NaN.

Scale: ~3,300 rows out of 101,777 (~3%) — the earliest 1-2 GWs per player-season,
plus genuinely new players.

DECISION for the baseline model: DROP these NaN rows. Rationale: keeps the first
model clean while we verify the pipeline produces calibrated probabilities. Not
the final answer.

WHY IT MATTERS LATER (must revisit): GW1 and new signings are exactly when the
LIVE model gets asked "who do I pick?" — dropping them is unacceptable in
production. The live model will have no prior-GW history for these players.

Options to handle properly later:
- Fill with sensible defaults + a "has_no_history" flag the model can use.
- Fall back to cross-season history (a player's prior-season minutes) to seed
  features — needs the multi-season crosswalk, which is currently 2025-26 only
  (see handoff §4 / §6: multi-season crosswalk NOT built).
- Position/price-tier priors for brand-new players (a £4.5m new defender vs a
  £9m new signing have very different nailedness priors).

Related: the depth-chart/backup-promotion idea (Kelleher example) also bites
hardest at cold start.


## Feature idea: form / current-role signal for the sub model

### Observation that prompted this
Curtis Jones, 2024-25: as p_start climbed 0.01 -> 0.89 across GW3-GW10 (the
model correctly learning he'd broken into the XI), his p_sub stayed roughly
flat at ~0.65. That is incoherent — a player who is now an established starter
should have a LOW probability of being a bench appearance, not the same rate
he had when he was a fringe player.

### Why it happens
The P(came on | didn't start) model leans on rolling-window features
(avg_min_last3/5, minutes_trend) that describe recent PLAYING TIME but not
recent ROLE. It can't distinguish "fringe player who gets 20-min cameos" from
"regular starter who was rested this week" — both look like a player with
minutes in the bank.

### Practical impact: currently LOW
e_minutes = p*E[min|start] + (1-p)*q*E[min|sub]. When p is high, the (1-p)
factor crushes the sub term regardless of q. Jones GW10: (1-0.89) * 0.65 * 21
= ~1.5 minutes. So a wrong q barely moves the answer today.

BUT it matters more for genuinely marginal players (p ~ 0.4-0.6), which is
exactly the rotation-risk band where FPL decisions are hardest.

### Proposed features
- A "current role" signal: share of available minutes played over last 3-5 GWs,
  or start-rate trend (is their start-rate rising or falling?).
- Explicit form: recent points/xGI per 90, which proxies whether a manager
  currently rates them.
- Interaction: role trend x position (rotation patterns differ by position).

### Note
Related to the depth-chart/backup-promotion idea (Kelleher example) — both are
about modelling a player's ROLE in the squad, not just their raw minutes
history. Worth designing together.


- Per-player bench weight: replace flat bench_weight with each bench player's
  e_minutes/90 (multiplied by the mode weight). Principled version of the
  bench term. Master plan §3.6 ("scaled by autosub probability").
- Full auto-sub modelling (Level 3): model real FPL bench order + position
  legality so a bench player only scores when a compatible starter fails.
  Complex; small slice of objective. Documented future work.


  ## Interpretability — "why this squad?" via component breakdown

**Idea:** when a user asks *"why did you give me this squad / this captain / this transfer?"*,
the agent should answer with the decomposed model's own component breakdown — not a black-box
"the model said so."

**Why this is easy for us (and hard for everyone else):** our points model is already
transparent. Every prediction is a sum of readable terms already sitting in
`predictions_2526.parquet`:

```
e_points = pts_appear + pts_goals + pts_assists + pts_cs + pts_dc + exp_bonus
```

So the explanation is literally the breakdown. No SHAP, no post-hoc explainer needed — the
decomposition IS the explanation. (We confirmed this in the LightGBM benchmark: a black-box
model needs SHAP to explain itself; ours doesn't.)

**What the feature looks like:**
- "Haaland is captain because his 6.3 expected points break down as: 2.9 goals (easy home
  fixture, high npxG), 1.8 appearance (nailed starter), 1.5 clean-sheet-adjacent... — the
  highest ceiling in your XI."
- "This defender is in over a pricier one because his DC points (0.9) plus clean-sheet
  probability (strong fixture) beat the alternative at £1.5m less."
- Squad-level: explain the optimizer's picks by pointing at the enabler logic (cheap
  bench frees budget for a premium) + the component reasons each starter was chosen.

**Two layers of "why":**
1. **Points level** — why does this player score X? → component breakdown (above). Trivial,
   already have the data.
2. **Squad level** — why is this player IN the squad vs an alternative? → the optimizer's
   constraint interactions (budget, position, max-3-per-club). Harder: needs the optimizer
   to surface *why* it made a swap, e.g. shadow prices or a "next-best alternative" diff.

**Implementation notes:**
- Layer 1 powers the agent's `explain_prediction` tool directly (master plan §5.4) — feed the
  component columns to the LLM as structured context, let it phrase them naturally.
- Layer 2 is the genuinely novel bit: run the optimizer with the player forced OUT, diff the
  objective, and report the point cost of dropping them. "Removing Haaland costs 4.1 pts and
  frees £14m — here's what that £14m buys instead." This is the interview-gold version.
- Keep it grounded: numbers come from the components/optimizer only, never invented (ties into
  the grounding contract, master plan §5.5).

**Priority:** Layer 1 is near-free and should ship with the agent. Layer 2 (optimizer
"why-not" via re-solve) is a stretch but is the standout demo moment — nobody else's FPL
agent explains its optimizer's trade-offs with real re-solved numbers.

---

## Leak #4 — Attacking rates used the current (predicted) season — FOUND & FIXED (2026-08)

**What it was:** `attacking_rates.py` built each player's npxG/90 and xA/90 from the
**2025-26 season's own full-season Understat totals** — the very season being predicted.
A season total is computed from all 38 gameweeks, so predicting GW1 used a rate that
already "knew" the player's GW2-38 output. Future information leaking backward into
earlier-gameweek predictions.

**Why it slipped in:** the rate *feels* like a fixed player trait, not a time-sensitive
feature, so using "2025-26's rate for 2025-26" seemed natural when wiring the live
assembly. The shrinkage method itself was always validated CROSS-season
(Shrinkage_log §4.1: last season's rate predicts next season's), so the leak entered
only at the assembly wiring step, not in the method's design.

**Severity:** soft. It leaked *skill level* (a slow-moving quantity), not outcomes, and
only through a secondary feature — SHAP on the LightGBM benchmark showed minutes
dominates (mean|SHAP| 0.665) while attacking features contribute little. Worst-case
impact was early season (GW1-5), where in-season history is thin.

**The fix:** rates for a predicted season are now built from **prior seasons only**,
pooled. For 2025-26 that is 2022+2023+2024 Understat totals, counts summed per player
(more minutes -> steadier prior, Shrinkage_log §8.1). This is the design-correct,
leak-free input the shrinkage method was validated for. Same shrinkage math, same k
(FWD npxG=2, else=10), same return shape — only the source seasons changed.
`get_rates_2526()` kept as a backward-compat shim routing to the leak-free `get_rates()`.

**Measured impact (the honest verdict):**

| metric            | before (leaky) | after (leak-free) |
|-------------------|----------------|-------------------|
| Spearman (rank)   | 0.716          | 0.715             |
| MAE               | 1.13           | 1.14              |
| Mean pred/actual  | 1.36 / 1.17    | 1.38 / 1.17       |
| 70+ band pred/act | 3.54 / 3.54    | 3.85 / 3.54       |

**Reading it:** ranking is essentially unchanged (0.716 -> 0.715, within run-to-run
noise), which *proves the leak was not inflating the headline result* — the rate is a
minor, slow-moving feature and swapping current- for prior-season rates barely moved
the order. Calibration loosened slightly (70+ band now over-predicts 3.85 vs 3.54),
because pooled 2022-24 rates of established players run a touch higher than the
current-season version. Acceptable: ranking is what FPL decisions need, and it held.

**Follow-ups (future work, not blockers):**
- Time-decay across the pooled prior seasons (weight recent seasons higher) — would
  reduce the slight upward calibration drift.
- A GW1 new-signing has no prior-season rate -> falls back to the position-average
  prior (already handled in assembly). Fine, but a finer prior (e.g. from a lower
  league) is a possible enhancement.

  ---

## Blend prior-season attacking rates with current-season form

**The gap:** after the leakage fix, attacking rates come purely from **prior seasons**
(2022-24 pooled). This is leak-free and correct, but it makes the rate *blind to the
current season* in three situations that matter for real FPL decisions:

1. **New signings** — a player arriving from another league has no prior Premier League
   Understat rate at all. They fall back to the position average for the entire season,
   even if they are scoring every week by GW10.
2. **Breakouts** — a player who was mediocre in 2022-24 but is on fire this season keeps
   being rated on their old, worse form. Systematically **under-predicted**.
3. **Decliners** — the mirror image. An ageing or out-of-form player keeps their old good
   rate and is **over-predicted**.

The assembly log already named this: *"Model is 'steady' — rates are season-level, so it
favors proven premiums and won't catch a differential's hot streak."*

**Partially mitigated today:** the minutes model *does* use current-season rolling
features, so a breakout who becomes nailed correctly gets more expected minutes. But the
**rate itself** (npxG/90, xA/90) stays stale — so the model gives them "more minutes at
their old scoring rate." Better than nothing, still wrong.

**The fix (empirical Bayes across seasons, not just within):** blend the prior-season
rate with the **current-season accumulated** rate, weighted by how much current-season
evidence exists:

```
rate_asof(gw) = w · current_season_rate(games 1..gw-1) + (1-w) · prior_season_rate
w = n90_current / (n90_current + k)
```

Early season -> w≈0, so we lean on the prior (correct: 2 games of data proves nothing).
By GW20 -> w is substantial, so a genuine breakout is recognised. Same shrinkage logic
already validated in the component, just applied across the season boundary rather than
within a single season. New signings get w rising from zero as they accumulate minutes,
instead of being stuck on the position average forever.

**Why it's leak-free:** the current-season component uses only gameweeks strictly BEFORE
the one being predicted — the same shift-then-roll discipline used everywhere else. This
is exactly what the `up_to_gw` "time dial" on the other components enables, and it would
give `attacking_rates.py` one too (it currently has none because prior-season rates don't
vary by gameweek).

**Data requirement — the real blocker:** current-season per-gameweek xG must come from
somewhere. Options:
- **vaastav's per-GW `expected_goals` / `expected_assists`** (already on disk, 2022-23+).
  Catch: penalty-INCLUSIVE, whereas the model uses npxG (non-penalty). Would need
  penalties netted out, or accept the imprecision for penalty takers.
- **Match-level Understat** (has true per-match npxG, stable IDs) — requires a new data
  pull; the season-aggregate file currently on disk has no gameweek breakdown.

**Priority:** high for product quality (this is the difference between an agent that spots
a differential and one that only ever recommends proven premiums), but it needs the data
decision resolved first. Tune `k` on the **validation season (2024-25)**, never on the
sealed 2025-26 test.

## Multi-transfer search in the season simulator

**Status:** not implemented — v1 limitation, deliberately scoped out.

### What v1 does
Each gameweek, the simulator evaluates single transfers only. It locks 14 of the
current 15 players, leaves one slot open, and lets the MIP fill it. Repeating that
across all 15 droppable players gives 15 candidate squads; the best one wins.

Cost: ~15 solves per gameweek, ~570 per season, roughly 7 minutes.

### What it cannot find
Any move that only pays off as a **combination**. The clearest example: selling two
mid-price defenders to afford one premium forward. Neither sale is an improvement on
its own, so a one-at-a-time search rejects both and never reaches the better squad.

This is a real blind spot, not a rounding error. Combination moves are exactly the
kind of decision good FPL managers make, and the kind the MIP is theoretically well
suited to — the single-transfer loop is what artificially prevents it.

### Why it is not a formation problem
Worth stating because it looks like one. A dropped MID must be replaced by a MID,
since the 15 is fixed at 2 GK / 5 DEF / 5 MID / 3 FWD by FPL rule. But formation
flexibility does not live in the 15 — the starting XI and captain are re-chosen free
every gameweek from whichever 15 are held. Locking `pick` never touches `start` or
`captain`. So no formation optionality is lost by this approach.

### How to fix it properly
Do not extend the loop to pairs — 15 x 800 x 800 is not searchable. Instead, express
transfers inside the MIP itself: add buy/sell binaries per player, a squad-continuity
constraint linking this gameweek's 15 to last gameweek's, and a -4 point penalty term
for each transfer beyond the free allowance. The solver then chooses how many
transfers to make and which, in one solve, optimally.

This is the same formulation the master plan describes for multi-gameweek transfer
planning (rolling horizon H = 5-8, time-decay weights on future gameweeks). The
single-gameweek transfer MIP is the natural first step toward it, and would replace
the 15-solve loop entirely rather than sitting alongside it.

### When to do it
After the v1 backtest produces a number. The point of v1 is a working end-to-end
season simulation with honest accounting; adding search sophistication before there
is a baseline to compare against makes the improvement unmeasurable.