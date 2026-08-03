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