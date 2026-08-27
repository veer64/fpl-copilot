# Headroom diagnosis — where the points between ~2265 and 2400–2500 actually are (2026-08-26)

Read-only. No simulation was run. Every number below is either (a) quoted from a log, with the log named, or
(b) a descriptive statistic computed this session on files already on disk — the three canonical walk-forward
files (`data/walkforward_h6_{2023_24,2024_25,2025_26}.parquet`, step 0, single-fixture rows), the three
reference full-system decision logs (`data/p1/fslog_{season}_base_wc2.parquet`) and vaastav
(`data/history/all_seasons_fixed.parquet`). Items marked **[read-only]** are the latter; they are NOT
pre-registered measurements and do not satisfy the house adoption bar on their own. Items marked
**[speculation]** are exactly that.

---

## 0. The single highest-conviction recommendation

> **SUPERSEDED IN PART, 2026-08-26 (same day), by `Logs/penalty_fix_prereg.md`.** When the fix was
> pre-registered, two further faults were found at source that this section did not see: the Understat
> join reads the SAME season as the one predicted (Understat labels 2025-26 as "2025"), i.e. the stored
> `penalty_share` column is a leak of that season's own penalty goals; and the position fallback never
> matches FPL labels, so 28.9% of rows carry a hard-coded 0.05/game. The **[read-only] "penalty fix"
> deltas below were computed from that stored column and are therefore contaminated** — read the
> mechanism, not the numbers. The honest, prior-season, gated measurement is in the pre-registration
> log and its results section. The bonus-term findings are unaffected (they use `exp_bonus` only).

**Fix two defects in the master equation that act precisely on the rows the optimizer picks from — the
penalty term and the bonus term — before buying any data or building any new model.** Both are structural
(a wrong formula and a train/serve skew), both are visible in the code, and on a read-only check their
correction moves the pre-registered decision partitions by as much as the player-props market feature did
for $30 and four specifications — for free, in a day or two of work.

**Defect 1 — the penalty term is ~50× too small.** `squad/assembly.py` lines 440–480 and 556–559:

    penalty_share = (goals − npg) / (games + 1)           # a per-GAME penalty-goal RATE, not a share
    team_pen_rate = Σ penalties_missed / gw_count          # penalties MISSED per gameweek, not awarded
    e_goals      += penalty_share × team_pen_rate × minutes_frac

A per-game pen-goal rate already embeds the team's penalty frequency; multiplying it again by a "team rate" —
and one built from *missed* penalties (mean 0.014–0.020) — collapses the term. Measured **[read-only]**: the
equation predicts **1.3 / 0.9 / 1.4 penalty goals per season league-wide** against ~70–96 realised (the
Understat pull counted 74 / 96 / 69 / 77 converted penalties in 2022-23 → 2025-26). For a designated taker
(prior-season pen rate ≥ 0.1/game) the term is 0.002–0.003 goals/game as built; the honest prior-season rate is
0.08–0.12 goals/game — 0.4–0.6 points per game for a midfielder, before bonus. The D1 log's "penalty share moved
nothing at any position (≤ 0.001)" was this bug, not a finding. `npxg90` excludes penalties by construction,
so **the model currently does not know who takes penalties** — and penalty takers are the premium captain
candidates.

Correcting just the formula (drop the spurious `× team_pen_rate`, i.e. prior-season pen goals per game ×
minutes_frac; nothing else changed) **[read-only]**, Spearman(e_points, realised) on the pre-registered
partitions:

| season | likely starters (p_start ≥ .75) | squad-relevant (top 30) | realised started (≥ 60) |
|---|---|---|---|
| 2023-24 | 0.298 → **0.307** (+0.008) | 0.164 → **0.194** (+0.030) | 0.223 → 0.229 (+0.005) |
| 2024-25 | 0.286 → **0.291** (+0.005) | 0.143 → **0.162** (+0.019) | 0.217 → 0.221 (+0.005) |
| 2025-26 | 0.203 → **0.210** (+0.007) | 0.085 → **0.096** (+0.011) | 0.129 → 0.133 (+0.003) |

For comparison, the props market feature (conditional spec, best of four) moved likely starters +0.009 and
squad-relevant +0.021 on 2024-25. A one-line formula fix matches it on squad-relevant in the same season and
beats it in 2023-24. A fuller construction — team penalty rate (awarded, ~0.10–0.13/match) × taker share ×
conversion (~0.78) × minutes_frac — should do better still, because prior-season pen goals under-count takers
who inherit the duty mid-season (the corrected term still predicts 55 vs 96 in 2024-25).

**Defect 2 — the bonus term carries no within-starter rank signal and tilts value from forwards to defenders.**
`bonus.py` trains a LightGBM on REALISED components (goals ∈ {0,1,2}, clean_sheets ∈ {0,1}) and `assembly.py`
lines 584–596 feed it EXPECTATIONS (e_goals mean 0.10–0.12 among starters, p90 0.27). A tree model evaluated
at inputs it never saw in training returns essentially the "no goal, no clean sheet" leaf plus minutes and
position — it cannot represent E[bonus] = Σ P(outcome)·bonus(outcome). Measured **[read-only]**, realised
starters, all three seasons:

- ρ(exp_bonus, realised bonus) = **−0.016 / −0.025 / −0.025**; ρ(pred_bps, realised bps) −0.03 to −0.10.
  On the top-30 partition ρ(exp_bonus, bonus) = **−0.09 / −0.18 / −0.09**.
- The rest of the equation predicts bonus BETTER than the bonus term does: ρ(pts_goals + pts_assists + pts_cs,
  bonus) = +0.16 / +0.17 / +0.13 (top 30: +0.14 / +0.20 / +0.15).
- pred_bps mean 33–39 vs realised 13–19: the per-gameweek renormalisation hides a 2.3× level error but cannot
  repair rank or the position mix.
- Position tilt on the top-30 rows (mean exp_bonus vs realised bonus): **FWD 0.23–0.28 vs 0.68–0.90; MID
  0.28–0.31 vs 0.58–0.74; DEF 0.35–0.41 vs 0.41–0.44; GK 0.33–0.38 vs 0.19–0.32.** Premium attackers are
  under-credited by ~0.4–0.6 points per week and goalkeepers/defenders over-credited by ~0.1–0.15 — a
  systematic ~0.5-point tilt in the relative valuation of a premium forward against a premium defender, on the
  rows where captaincy and premium transfers are decided. Bonus is 8–11% of starter points.
- Deleting the term outright improves rank on likely starters in all three seasons (+0.008 / +0.003 / +0.004)
  and on realised starters (+0.016 / +0.011 / +0.007); squad-relevant +0.012 / +0.007 / −0.003.

Penalty fix + bonus removed together **[read-only]**: likely starters **+0.015 / +0.008 / +0.010**, squad-relevant
**+0.039 / +0.024 / +0.006**, realised started **+0.020 / +0.015 / +0.010**. A proper bonus term should add
rather than subtract: E[bonus] computed by pushing the outcome distribution through the existing BPS model and
curve (K draws of goals ~ Poisson(e_goals), assists ~ Poisson(e_assists), CS ~ Bernoulli conditional on 60+,
minutes from the minutes mixture; average the mapped bonus), or, simpler and probably adequate, a walk-forward
GLM of realised bonus on the predicted components by position. The assembly log flagged "a proper rank-based
bonus model" as future work in Phase 2; the walk-forward log traced the ~10% over-prediction on the 70+ band to
bonus. This is that work.

**Why this is the recommendation and not another data purchase.** The record's own lesson from props and
horizon minutes is that gains outside the decision partition do not reach the optimizer. These two defects sit
INSIDE it: both are largest at the top of the distribution (takers and premium attackers), both are level
errors of ~0.5 points/week on the players the MIP captains and pays hits for, and both are deterministic —
no new information source is needed. They also change the reading of the props result: the market prices
penalties. The +0.02 the market added on squad-relevant may substantially be the penalty term the model was
missing; re-running the props endpoint on top of the corrected equation costs nothing (data on disk) and is
the right way to find out whether any market signal survives (§4, idea 6).

**Protocol.** Same instrument as props: pre-register in a dated log before touching 2025-26; tune nothing
(these are formula fixes, not tunables — the one dial, conversion rate, is a league constant ~0.78 fixed
in advance); pass condition = non-negative on both decision partitions in every season with mean ≥ +0.010,
plus mean predicted pen goals within ±25% of realised league-wide on the tuning seasons, plus the top-30
bonus level by position within ±0.15 of realised; Brier on P(goal ≥ 1) not worse. Rebuild the canonicals,
stamp (`penalty_term_version`, `bonus_model_version`), and ONLY THEN run the season figures, which will be
inside noise and must not adjudicate.

---

## 1. Where the number actually is, and how the band should be read

Reference *(as of writing; superseded 2026-08-26 by 2251 / 2306 / 2268 — bonus term deleted, TC2 priced in-sim, see `Logs/season_totals_index.md`)*: 2296 / 2294 / 2206 chip-inclusive (fslog base_wc2; TC2 scored zero by decision), average manager
2003 / 2008 / 1895. Three draws from a distribution with single-path sd ≈ 60 (instrument_b_log): the system's
**expected** season is ≈ 2265 ± 35 (SE of a three-season mean). The 2024-25 reference cell (2294) is NOT the
97th-percentile no-chip path (2362); it sits mid-distribution, so the three-season mean is a fair EV read.

The "good human 2300–2500" band is also EV ± luck: a manager with EV 2350 lands 2290–2410 in most seasons.
So "meaningfully inside the band" is a statement about EV, and the target is **EV ≈ 2400**, i.e. +130–140 over
the current EV. Anything under ~+50/season cannot be seen in a season total (M1; paired sd ~85); every lever
below has to be adjudicated on component/windowed instruments, exactly as the logs already require.

One correction to the brief's premise: "five model families land at ~0.099 among started players" is a
2025-26, pre-D1/pre-blend figure. On the CURRENT canonicals **[read-only]** Spearman(e_points, realised)
among realised starters is **0.223 / 0.217 / 0.129** (2023-24 / 2024-25 / 2025-26) and on the pre-registered
likely-starter partition **0.298 / 0.286 / 0.203**. 2025-26 is the hard season (§3), not the representative one.

---

## 2. The ledger — attributing the gap

All per season. "Pot" = the most the channel could ever be worth (an oracle or hindsight bound).
"Recoverable" = my central estimate of what a good, feasible change could take; **[speculation]** unless stated.

| channel | pot (bound) | evidence for the bound | current position | recoverable | how to measure cheaply |
|---|---|---|---|---|---|
| **Luck** | — | path sd 60 single, ~85 paired (instrument_b) | EV ≈ 2265 ± 35 | **0** | already measured |
| **Prediction among starters — level & role defects** | see §0 | penalty term ~50× under; bonus term rank ≈ 0, FWD/MID under-credited 0.4–0.6/wk at the top **[read-only]** | Spearman on decision partitions +0.01–0.04 available from fixes alone | **+20–40** | the props instrument (`eval/measure_props_endpoint.py` partitions), pre-registered |
| **Prediction among starters — genuine rank gain beyond defects** | within-squad hindsight (best legal XI + best captain from own 15 − realised raw) = **419 / 393 / 500**, of which captaincy 246 / 218 / 253 **[read-only]**; transfer channel separate | ceiling on within-starter ρ ≈ 0.31–0.33 (2023-24/24-25) and ≈ 0.20 (2025-26) from split-half reliability (§3); we are at ~70–75% of it | ρ 0.22–0.30 on the decision partitions | **+10–30** beyond the defects | split-half ceiling per season (this session's method); teammate-absence conditional rates (idea 5) |
| **Minutes / horizon (who plays, weeks ahead)** | full-horizon minutes oracle **+146 / +109 / +95 path, +131 chip-incl mean**; one-deadline-only +33 mean but signs +65/−91/+126 (teamnews step 4–5) | 60–75% of the oracle is transfer TIMING; buyable news ≈ 2.3/season; lever 1 (refit) worse where decisions are made; return dates never touch the top 30; suspensions reach k=1 only | stale gap +2.3 … +7.0 min at k = 1 … 5 (scoping log) | **+10–30** via congestion/European-calendar rotation modelling (lever 4, never reached); honest range 0–50 | `eval/measure_horizon_minutes.py` on the pre-registered partitions — the instrument exists |
| **Captaincy** | hindsight gap ~230 (handoff 08-20 §5.4; **[read-only]** 246/218/253) | no alternative rule beats argmax e_points (handoff 08-20); our captain beats the most-owned player each week by **+44 / +53 / +32** **[read-only]** | captain = argmax e_points | **+5–15**, mostly via §0 (pen/bonus tilt on premiums) | paired captain reads on frozen paths (tc2_valuation method) |
| **XI / bench selection within the squad** | XI leak (non-captain part) ≈ 170–250 **[read-only]**; bench points left 303 / 284 / 430 | P5: bench order by p_play −4…−7, XI tiebreak −12…+3; 60% selection efficiency vs random XI (wildcard log) | e_points argmax | **0–5**; per-slot bench weights (0.395/0.184/0.053) need bench-slot variables — untested, small | noise-free paired paths (the P5 method) |
| **Chips** | package ≈ +70–100 at anchors (p4 §12, §11); FH2 +28.7 mean, WC2 +21, WC1@2 +35/+26/+58 at W3 | TC2 is **scored ZERO** in the headline; legal TC2 hindsight reads 10 / 29 / 7 on the adopted rule; BB2 bench 8 / 25 / 23; BB1 4 / 5 / 11; TC1 6 / 9 / 16 | rules of record adopted | **+10–25**: book TC2 (≈ +7–15 EV), TC2 rule that requires the captain's club to double (calendar-only), BB2/TC2 allocation across the two largest doubles | in-sim TC2 on the rule's week (p4 says deliberately not run) — one sim per season, windowed read |
| **Optimizer mechanics** | — | hit bar (blocked transfers mostly good), per-transfer min-gain (fails), early-hit discount (~0 under WC1@2), opening squad (mixed/0), robust solve (collapses to expectation), bench order/XI tiebreak (≤ 0) | converged | **≈ 0** | — |
| **Price / team value** | squad value **995→982, 1000→967, 1000→968**; price moves on players WHILE held **+64 / +31 / +61** tenths, so the loss is the sell-rule and buying after rises; template-15 by ownership +13 / +32 / −9 **[read-only]** | the planner has zero price foresight; vaastav carries `transfers_in/out`, `transfers_balance`, `selected` per GW | not modelled | **+5–15** | predictability of next-GW price moves from transfer momentum (read-only, one afternoon); then a bank-value term in the MIP objective |
| **Cold start / the no-prior third** | GW1–7 capture 31.7 / 37.1 / 27.5% of best-15 vs ~32% later; 32–34% of rate rows have no prior (rate_blend §9) | WC1@GW2 already absorbs most of the opening cost (substitution finding, three sightings) | position-mean rate for new signings | **+5–20**, concentrated in GW1–7, and it shrinks the WC1 edge by construction | rate endpoint on no-prior rows only (`eval/measure_rate_blend.py` protocol) |
| **Hits** | 84 / 48 / 12 points paid | hit_threshold: blocked transfers mostly good; P3: nothing to buy under WC1@2 | bar = 4 | **≈ 0** | — |
| **Top-end level calibration (winner's curse)** | top-30 rows: e_goals **0.31 / 0.33 / 0.22 vs realised 0.22 / 0.21 / 0.15** goals **[read-only]**; props log: incumbent P(≥1) 0.306 vs realised 0.227 on squad-relevant; margin β < 1 on the started band (retracted magnitudes, replicated sign) | the market at m = 1.396 sat 8% UNDER on the same rows — better calibrated at the top | uncorrected | **+0–10** (acts on hit decisions and captain margins, not rank) | isotonic/shrinkage of e_goals on prior seasons, pre-registered; measured on Brier + β, rank must not fall |

Central sum of "recoverable": **+65 to +170 per season**, i.e. an EV of roughly 2330–2430. Reaching EV 2400
requires the §0 fixes AND one of {a real horizon-minutes gain, the chip booking, the cold-start prior} to land.
**EV 2500 is not on the table for this architecture on the evidence**: the perfect six-week minutes oracle is
worth +131, the within-starter ceiling caps the rank channel, and the two together would be needed in full.

Where the attribution is unmeasured: the conversion of Δρ on a partition into season points. My heuristic
**[speculation]**: the within-squad hindsight leak (~420 at ρ = 1 against ρ ≈ 0.25 now) suggests ~5 points per
+0.01 of ρ on XI + captaincy if value is roughly linear in correlation, with a comparable amount on transfers.
The cheap way to measure it properly is the existing Instrument A on a frozen path with the corrected
predictions substituted at step 0 only (the P5 noise-free-pair design): identical squads, XI/captain re-picked.
That is one afternoon and gives the XI + captaincy half of the conversion without a season total.

---

## 3. The 0.099 question — property of the problem, or of us?

**Both, and the split is measurable.** Three facts from this session **[read-only]**:

1. **Split-half reliability of a starter's points-per-start.** Correlating each player's mean points in
   odd gameweeks with even gameweeks (≥ 6 starts each): **0.52 / 0.60 / 0.30** across 266–276 players.
   The implied true sd of a player's per-start mean is **1.03 / 1.07 / 0.64** points against a realised
   per-start sd of 3.2–3.4. A forecaster who knew every player's TRUE season rate exactly — and nothing about
   fixtures — would achieve Pearson ≈ **0.31 / 0.33 / 0.20** among starters. Fixture variation adds some
   (team λ moves ±25–30% for attackers): perhaps **0.35–0.40** in the two normal seasons, ~0.25 in 2025-26.
   That is the ceiling for a one-week-ahead per-player forecast with any data whatsoever.
2. **We sit at 0.22 / 0.22 / 0.13 among realised starters** (0.30 / 0.29 / 0.20 on likely starters). Roughly
   70–75% of the attainable rank correlation is already captured; the remaining quarter is worth having but
   is bounded.
3. **A hindsight leave-one-out season mean (the player's own realised rate) scores 0.26 / 0.26 / 0.12** among
   starters — barely above the model in two seasons and BELOW it in 2025-26. Even perfect knowledge of the
   player's realised rate does not rank single weeks much better than we do. The problem is genuinely
   noise-dominated: 70% of starter variance is goals (30%), CS (15%), assists (10%) and bonus (6%) events
   with per-match Poisson noise the rate cannot remove.

2025-26 is the outlier: reliability 0.30, true sd 0.64 — a season with no Salah/Haaland-scale concentration,
where scoring was spread thinly. The wall there is the season, not the model (why_2024_25_log makes the mirror
point for 2024-25's baseline).

**So: mostly a property of the problem — but not entirely, and the "us" part is specific.** The gap between
0.22 and ~0.35 decomposes into (i) defects in what the model believes about players it rates highly (§0 —
penalties, bonus, the top-end level), (ii) role facts the model does not carry (who takes set pieces, who
inherits the penalty when the taker is absent, who is the striker when the striker is out), and (iii) residual
rate-estimation noise that no data source fixes because a half-season is 19 matches.

**What a system that beat 0.22 would look like, item by item against the brief's list:**

- *Shot-level / possession-value data (Opta, StatsBomb):* **no.** The per-match-signals log showed xGOT,
  box touches and chances created do not beat plain xG for next-period goals; the binding constraint on a
  rate is the ~19-match sample (reliability 0.52), not the xG model's resolution. A better xG model moves the
  rate estimate by less than the sampling noise does. Paid event data would buy set-piece ROLE facts, which are
  obtainable free (below).
- *Set-piece and penalty-taker modelling:* **yes — this is §0.** Penalties are the single largest
  deterministic role effect in FPL (0.4–0.6 pts/game for a taker) and the model currently cannot see them.
  Corner/free-kick takers are the assist-and-bonus analogue; Understat shot records carry `situation`
  (FromCorner / SetPiece / DirectFreekick) and the assisting player per shot, so a per-player set-piece xA
  share is derivable from the pull already on disk.
- *Opponent-specific matchups:* **second order.** D4 established fixture pricing is second-order at horizon
  and team λ already enters at step 0 from the market. Player-vs-opponent-type effects (aerial threat vs weak
  aerial defence) are real but small and need event data to estimate; not before the above.
- *In-form vs baseline regime detection:* **already done, and it plateaus.** k = 8 is on a plateau (5–12
  identical); form/role features added nothing to the minutes model (minutes log §6.8). A walk-forward
  realised-points-per-start blend **[read-only]** raised broad-starter ρ (+0.04 in two seasons) but LOWERED
  it on the top 30 in all three (−0.05 / −0.01 / −0.07): the same partition trap as lever 1. Do not pursue.
- *Teammate interaction effects:* **the one genuinely new information source among starters, and free.**
  A player's rate is conditional on who else is on the pitch (the pen-taker cascade; a winger's shot share
  when the striker is out). Understat rosters give per-match co-appearance; a conditional rate
  (npxG/90 with teammate X absent vs present, shrunk) is computable on disk. Untested; the availability block
  already knows at the deadline who is out. Measure before building (idea 5).
- *Tactical context (formation, role changes, new signings):* partially — the no-prior third is a cold-start
  data gap (idea 4, cross-league priors); in-season role change is what k = 8 handles.
- *Referee and game-state:* **no** — unpredictable at the deadline and already inside the market λ.
- *Ownership and price as signal:* price is already the top feature in P(came on) and matters for the
  value channel (idea 7); ownership matters for RANK objectives, not for total points, and the goal here is
  points.

**Verdict on the wall:** a one-week-ahead forecast will not exceed ρ ≈ 0.35–0.40 among starters with any data.
The system is at ~0.22–0.30; the reachable increment from fixing what it believes about its own top picks is
+0.02–0.04, and from new role/teammate information perhaps another +0.02–0.05. That is a wall with a door in
it, not a wall.

---

## 4. Ideas, ranked by expected gain per unit of effort

Scored on three seasons of evidence where it exists; expected points are my estimates and are labelled.

### 1. Penalty term — rebuild (≈ 1 day; free) — **do first**
**Mechanism:** the model knows npxG but not who takes penalties; takers are the premium captains. **Why it
beats what we have:** it corrects a 50× under-count on a 0.4–0.6 pt/game quantity on the decision partition.
**Falsifier (fast):** if the corrected term does not lift squad-relevant Spearman by ≥ +0.010 in every season
on the existing props instrument — the read-only check says +0.030 / +0.019 / +0.011 — or if the bonus model,
fed the larger e_goals, degrades rank, stop and report. Also assert the league-wide predicted penalty-goal
total lands within ±25% of realised (the as-built total is 1%). **Expected:** +0.01–0.03 on squad-relevant;
+10–20 points/season **[speculation]**. **Cost:** formula change, one canonical rebuild (~30 min), one
pre-registered measurement. Better construction: team penalties AWARDED per match (vaastav has
`penalties_missed`, Understat has converted pens; awarded ≈ converted/0.78) × taker share (prior season, then
current-season pens taken as they accrue) × conversion × minutes_frac.

### 2. Bonus term — rebuild as an expectation over outcomes (1–2 days; free)
**Mechanism:** Jensen/train-serve skew — a tree trained on {0,1,2} goals is evaluated at 0.1. **Why it beats
what we have:** the current term has ρ ≈ 0 to −0.18 with realised bonus on the decision rows and mis-allocates
~0.5 pts/week between premium attackers and defenders. **Falsifier:** after the rebuild, ρ(exp_bonus, bonus) on
the top 30 must be ≥ +0.10 in every season (the crude goals+assists+CS proxy already reaches +0.14–0.20), and
top-30 mean predicted bonus by position within ±0.15 of realised. If a Monte-Carlo-through-the-existing-model
version cannot beat the proxy, use the proxy (a GLM on predicted components, walk-forward). **Expected:**
+0.005–0.015 on the partitions, plus the level fix on premiums; +5–15 points **[speculation]**. Note the
current per-gameweek renormalisation should be dropped once the level is calibrated, or made per position.

### 3. Book Triple Captain 2 and fix its rule (½ day; free) — a headline you already own
The chip-inclusive headline scores TC2 as zero by decision (p4 §12c). The adopted "earliest second-half double"
rule read 10 / 29 / 7 in hindsight and can select a week where the captain's own club does not double
(2025-26 GW26: Gabriel, read 7). A calendar-only refinement — "earliest second-half double in which the club of
the current intended captain (argmax step-0 e_points at that deadline) doubles; if none by GW36, the last
double" — is computable at decision time (it looks only at the current captain, not at future cutoffs) and
removes the tie-break of ignorance. **Falsifier:** one in-sim run per season with TC2 scheduled by the rule;
windowed read at the anchor; must be non-negative in all three seasons vs the same path without the chip.
**Expected:** +7–15 EV/season **[speculation, bounded by the 10/29/7 reads]**. Also worth one read-only pass:
allocate BB2 and TC2 across the two largest doubles by predicted bench vs predicted captain at the FIRST of the
two deadlines (a sequential rule), since the log already found the bench-aware BB week is a poor TC week.

### 4. Cross-league priors for the no-prior third (2–3 days; free — Understat covers six leagues)
**Mechanism:** 32–34% of rate rows fall to a position-mean prior; the biggest of them are the premium summer
signings the crowd buys at GW1 and the system cannot rate until n90/(n90+8) grows. Understat's other five
leagues carry the same npxG/xA per match; a single league-strength scalar per source league (fitted on the
movers of prior seasons) converts them. **Why it beats what we have:** it is new information on exactly the
rows where the prior is weakest, in the weeks (GW1–7) where persistence costs most. **Falsifier:** the
rate_blend protocol restricted to no-prior rows — npxG/xA Spearman over the next three GWs must rise on both
tuning seasons; the 2026-27 opening (Wirtz/Gyökeres-class signings) is the live test. **Expected:** +5–20
points, front-loaded; it will SHRINK the measured WC1@GW2 edge (substitution — expected, not a failure).
**Cost:** one Understat pull (the pull code exists; ~30 min per league-season), a crosswalk pass (the risky
step — apply the KNOWN_ISSUES #12 audit).

### 5. Teammate-absence conditional rates (measure first: 1 day; build: 3–4 days; free)
**Mechanism:** rates are conditional on the XI; the availability block already knows at the deadline which
teammates are out. The largest instances are deterministic (second penalty taker when the taker is out; the
striker's replacement) and currently invisible. **Falsifier:** read-only — from Understat rosters, compute
each player's npxG/90 and xA/90 with vs without each of his three highest-npxG teammates over the pooled
seasons; if fewer than ~50 player-teammate pairs show a shrunk difference ≥ 0.05/90 with ≥ 300 minutes on
both sides, the effect is too thin to build. **Expected:** +0.01–0.03 on likely starters in absence weeks only
**[speculation]**; small in season points (absences of a top-3 teammate happen in ~15% of player-weeks).

### 6. Re-test player props on top of the corrected equation (½ day; $0 — data on disk)
The record says do not revive a killed idea without a reason the earlier test was wrong. The reason: the
incumbent the market was measured against could not see penalties, and the market prices them. The props
gain on squad-relevant (+0.021) may be mostly the penalty term. Re-run `measure_props_endpoint.py --spec
conditional` with the corrected e_goals as the incumbent, same partitions, same bar. Either outcome is
informative: if the gain vanishes, the market's information among starters is fully explained and the
workstream is closed for good; if +0.02 survives on both partitions, it now clears the pre-registered bar and
is adoptable live (UK books at ~£0 via the free tier inside the deadline week; the backtest caveats stand).

### 7. Price-change anticipation → a bank-value term (1 day to measure; 2 days to build; free)
**Mechanism:** the system ends every season £1.3–3.3m below its start while the players it held rose in
price (+£3–6m) — the sell-rule keeps half of rises, and the planner buys after rises and sells after falls
because it has no price model. Next-GW price rises/falls are highly predictable from `transfers_balance`
momentum (vaastav, per GW; the FPL price algorithm is threshold-driven). **Falsifier:** read-only — precision
of a simple momentum rule for next-GW ±0.1 moves; if < 70% on rises, stop. **Build:** an expected
sell-value gain per player per step in the MIP objective at a small weight (points per £0.1m), or simply
prefer risers among near-tied buys. **Expected:** +5–15 points **[speculation]**; team value converts to points
slowly, so the gain is back-loaded and modest — ranked here for cost, not size.

### 8. Rotation from the full calendar — cups and Europe (data: 1 day, free; model: 1 week)
**Mechanism:** the only lever of the horizon-minutes design never reached (lever 4). The stale gap at k = 3–5
is +5–7 minutes and lever 1 showed the cutoff features cannot close it — the missing input is the schedule
the club faces between now and step k (Champions League midweeks, cup rounds), which is public a month ahead
and not on disk (schedule features in D4 were EPL-only and scored exactly zero, which is a statement about
EPL-only congestion). **Falsifier:** the pre-registered horizon instrument — Spearman on likely starters and
squad-relevant must not fall at any step (lever 1 fell 7–21%), MAE gap closed ≥ 15% at k ≥ 3. **Expected:**
0–30 points; the honest prior after lever 1 is low, but this is the one input that reaches steps 3–5 and
targets rotation rather than membership. **Cost:** a fixtures feed (football-data.org, free tier) and a
minutes-model feature block (days to next fixture, fixtures in the next 7/14 days, European tie flag).

### 9. Top-end level calibration (½ day; free)
Isotonic recalibration of e_goals (or e_points) by position on prior seasons, applied walk-forward; the
market's calibration at m = 1.396 (squad-relevant 0.93 vs the incumbent's 1.35) is the reference. Acts on hit
decisions and captain margins, not on rank. **Falsifier:** Brier on P(≥1 goal) and margin β on the started band
improve on both tuning seasons with rank unchanged. **Expected:** 0–10 points **[speculation]**. Do after 1–2,
since both change the level.

### 10. Not recommended, with reasons
- **Opta / StatsBomb event data:** rate estimation is sample-limited, not model-limited (§3); ~£1–5k/season
  buys role facts obtainable free. No.
- **Lineup / team-news subscriptions (FFS, Rotowire):** measured at ~2.3 points/season bench-bounded, and the
  one-deadline oracle is noise-dominated (+65/−91/+126). No.
- **FPL Review / Fantasy Football Hub projections:** not as an input — as a BENCHMARK. £5–10 for one month
  of their per-player projections scored on OUR partitions would tell you where the best public models sit on
  the same ceiling; the record has no external reference point for "good human" prediction quality. Worth
  it once, for calibration of ambition, not for points. (vaastav's `xP` column is NOT usable for this: it
  correlates 0.5–0.55 with realised points among starters — far above any honest forecast — and is almost
  certainly post-hoc; treat it as leaky.)
- **Betting exchanges for team λ:** already have Bet365 1X2 at step 0; D4 proved forward λ is second-order.
- **Deep learning, robust/CVaR objectives, per-player bench weights, hit-bar changes, opening-squad
  solvers:** all measured ≤ 0 or collapse to expectation; the optimizer has converged for an EV objective.
  For a TOTAL-POINTS goal, EV-maximisation is the right objective; a rank goal (top-10k) would justify a
  variance-seeking objective, and that is the only reason to revisit robustness.

### What a different architecture would look like, if the ceiling is reached
It would not be a different predictor — the wall is the problem. It would be a different OBJECTIVE: if the
goal ever becomes rank rather than points, the MIP should maximise P(score > field) using effective ownership
(vaastav `selected`) and a covariance model of the squad's points (shared clean sheets, shared team λ), which
is where a robust/scenario solve stops collapsing to expectation because the payoff is no longer linear.
For the stated goal — points — the current architecture is right and is near its ceiling on rank; the
remaining headroom is in what the equation believes about its top picks (§0), the chip booking, and minutes
at horizon.

---

## 5. Sequence for the next two weeks

1. Pre-register and fix the penalty term (idea 1). Rebuild canonicals, stamp, measure on the partitions.
2. Pre-register and rebuild the bonus term (idea 2). Same.
3. Re-run the props endpoint against the corrected incumbent (idea 6). Close or adopt on the existing bar.
4. Book TC2 with the refined rule (idea 3): one sim per season, windowed read.
5. Read-only feasibility passes for ideas 4, 5, 7 (one day total); build whichever clears its falsifier.
6. Only then the full-system season figures — reported under the standing framing, never as evidence.

If 1–4 land as the read-only numbers suggest, the EV moves from ≈ 2265 to ≈ 2320–2350 — inside the band,
not at its floor. Reaching ≈ 2400 EV additionally needs one of {8, 4} to deliver at the top of its range,
and that is genuinely uncertain.

---

## 6. Caveats on everything above

- Every **[read-only]** figure was computed on single-fixture step-0 rows of the current canonicals joined to
  vaastav by (element, gw); Spearman deltas are in-sample descriptive statistics with no pre-registration and
  no holdout. They are grounds for a pre-registered test, not adoption evidence. Several cells are below the
  +0.020 bar the props workstream set; the case for §0 rests on the mechanism being a verified defect, the
  sign being consistent across three seasons and both partitions, and the cost being ~zero.
- The ρ-to-points conversion in §2 is a heuristic. The proper instrument (frozen path, corrected step-0
  predictions, XI/captain re-pick; the P5 design) is named and cheap.
- 2025-26 is no longer a sealed season for anything touching the goals term (spent on the props season
  figures, 2026-08-26); the next pre-registration should tune on 2023-24 + 2024-25 and treat 2025-26 as a
  third tuning season or re-seal it explicitly for the new question.
- The three seasons disagree on ceilings (2025-26 reliability 0.30 vs 0.52–0.60); any three-season claim is a
  three-season claim.

---

## 7. OUTCOMES OF THE RANKED IDEAS (2026-08-27) — the record, with failures as failures

All on the tuning seasons 2023-24 + 2024-25 only; 2025-26 not opened for any of them.

| idea | status | where |
|---|---|---|
| 1. Penalty term rebuild | measured 2026-08-26, **NOT adopted** (rank up, Brier/movers failed); the same-season JOIN LEAK closed in production 2026-08-27 (magnitude unchanged) | `Logs/penalty_fix_prereg.md`; KNOWN_ISSUES #19 |
| 2. Bonus term rebuild | outcome-weighted rebuild **FAILED**; DELETE **ADOPTED** 2026-08-26 | `Logs/bonus_rebuild_prereg.md`, `Logs/bonus_delete_prereg.md` |
| 3. TC2 rule refinement (captain's club must double) | **FAIL** — pre-registered falsifier not cleared: selects the same week as the rule of record in both tuning seasons; cannot bind because the argmax captain on a double gameweek is a doubling player by construction | `Logs/p4_chip_policy_log.md` §16 |
| 4. Cross-league priors | not started | — |
| 5. Teammate-absence conditional rates | **FAIL** — exposure large (~10% of decision-partition rows behind a key absence) but no role transfer separable from zero; penalties flip sign across seasons; shot/creation shifts ±0.01 (SE 0.01); only minutes (+6–8 per appearance) is above noise, a minutes-model quantity | `Logs/teammate_absence_log.md` |
| 6. Props re-test on the corrected equation | not run (the corrected equation is not adopted) | — |
| 7. Price-change anticipation → bank-value term | **DECLINED ON EXPECTED VALUE, NOT TESTED** (no measurement made; not a fail): a price change is 0.1m against a 100m squad, and the daily transfer-flow history a backtest needs may not exist on disk. The price-momentum sub-check falls with it | this entry |
| 8. Rotation from the full calendar | not started | — |
| 9. Top-end level calibration (fixture_scale^γ) | **FAIL** 2026-08-26 | `Logs/topend_calibration_prereg.md` |
| 9b. Selection-based calibration (rank-within-gameweek shrink of e_goals toward the position prior; the successor to 9) | **FAIL** 2026-08-27 — rank fell on both partitions in both seasons (max −0.018), squad-relevant spread collapsed to 0.57–0.58 of baseline vs the 0.85 floor; compresses ranks 1–10 into 11–30 (rank-1 mean −3 points) — the idea-9 trade reached via rank | `Logs/selection_calibration_prereg.md` |

**Structural finding (constrains every future calibration):** goals-only calibration is coupled to the bonus
deletion. Bringing the top-10 goals ratio to 1.0 pushed the points ratio to 0.93, because the deleted bonus term
already offsets the top-30 level by ≈ −0.48. Any level calibration must target realised points INCLUDING bonus,
or address bonus first (`Logs/selection_calibration_prereg.md` §5).

**Fallback finding:** the 0.05 penalty fallback (gate off) covers ~52–55% of step-0 rows after the join fix and is
40–90× the realised pen rate of those rows; currently worth ≈ 0.002–0.004 e_points per affected decision-partition
row only because the ~50× team_pen_rate undersizing cancels it (KNOWN_ISSUES #19, 2026-08-27 addition;
`Logs/outputs/fallback_characterisation.txt`).

The §5 sequence is therefore closed at items 1–4 as written; what remains open is unchanged from the 2026-08-26
handoff §7 (penalty magnitude + fallback together, top-end over-prediction with §5's constraint, bonus level).
