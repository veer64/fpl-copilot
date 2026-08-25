# Player-prop odds — step 1, free-tier coverage check (2026-08-24)

Scope of this step, as instructed: coverage only. No parser, no feature, no
crosswalk, no payment, no purchase decision. Script:
`eval/probe_player_props_coverage.py` (historical mode as specified; `--live`
mode as the free substitute). Key read from `.env` (`ODDS_API_KEY`), never
printed, written or logged; raw JSON stored under `data/odds_props/raw/`
(gitignored) before any parsing. Source: the-odds-api.com, v4.

## 1. The go/no-go question and the kill condition (stated before the pull)

Is anytime-goalscorer (`player_goal_scorer_anytime`) priced for EPL by UK/EU
bookmakers, historically, across a full board of players? Kill condition: if
UK/EU coverage is thin or favourites-only, stop — a board of the six likeliest
scorers cannot substitute for npxg90 across ~800 players.

## 2. Historical pull, as specified: NOT AVAILABLE ON THE FREE TIER

Five ordinary Saturday fixtures were selected offline (no big-six clashes):
2023-24 GW13 Luton v Crystal Palace and GW27 Everton v West Ham; 2024-25
GW16 Wolves v Ipswich and GW15 Brentford v Newcastle; 2025-26 GW15 Everton v
Nott'm Forest — each queried at deadline − 1 h. Every historical events call
returned **HTTP 401 `HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN`** ("Historical
odds are only available on paid usage plans"). No credit was consumed and no
raw historical data exists on disk. So the premise "historical player props
from 2023-05-03 on the free tier" does not hold: the free tier carries 500
credits for CURRENT odds only; historical access is a paid plan feature.

Consequences for the four report questions: Q3 (does coverage degrade back
to 2023-24) and Q4 (is there a snapshot strictly before each FPL deadline)
**cannot be answered without paying.** Q1 and Q2 can be answered on the live
market, which is what follows.

## 3. Live probe (free substitute for Q1/Q2), this weekend's ordinary fixtures

Events list is free; each odds call cost 1 credit per region. Four fixtures
within the week, uk and eu regions, plus one fixture 12 days out.

| fixture (commence UTC) | uk books: players priced | eu books: players priced |
|---|---|---|
| Bournemouth v Everton (29 Aug 14:00) | Paddy Power 40, Sky Bet 40, William Hill 40 | 1xBet 41, William Hill 40 |
| Coventry City v Hull City (29 Aug 14:00) | William Hill 41, Paddy Power 40, Sky Bet 40 | 1xBet 43, William Hill 41 |
| Leeds United v Brentford (30 Aug 13:00) | Sky Bet 37, Paddy Power 37, William Hill 36 | MyBookie.ag 40, 1xBet 36, William Hill 36 |
| Sunderland v Fulham (30 Aug 13:00) | William Hill 37, Sky Bet 37, Paddy Power 37 | MyBookie.ag 38, 1xBet 37, William Hill 37 |
| Newcastle United v Bournemouth (5 Sep 11:30) | no bookmaker returned the market | no bookmaker returned the market |

- **Q1, which bookmakers:** UK — Paddy Power, Sky Bet, William Hill (all
  UK-licensed); EU region — 1xBet (Curaçao-licensed, EU-facing), William Hill
  again, and MyBookie.ag, which is a US-facing offshore book despite sitting
  in the `eu` region response. No bet365 or Betfair in the returned set.
- **Q2, board depth:** 36–43 players per fixture, i.e. both full matchday
  squads including defenders and goalkeepers — a full board, not favourites.
  The three UK books agree within ±1 player.
- **Timing:** the market exists for fixtures inside the coming week; a
  fixture 12 days out had no player market yet at any book. Live pulls
  therefore need to happen inside the deadline week, which is when they are
  needed anyway.
- **Payload structure (from the stored raw):** one outcome per player,
  `name` = "Yes", `description` = player, `price` decimal; market
  `last_update` present (e.g. 2026-08-25T00:57Z). Bournemouth v Everton at
  Paddy Power: 40 players from 2.75 (Evanilson) to 26.0 (Elijah Campbell),
  including defenders and goalkeepers. Names are full legal names
  ("Francisco Evanilson de Lima Barbosa", "Norberto Bercique Gomes
  Betuncal") — a name-matching crosswalk to FPL/vaastav would be needed
  before any use; noted, not built.
- Credits: 8 of 500 used (492 remaining).

## 4. What this step establishes and what it does not

Established (free): for the current season, UK/EU books price anytime
goalscorer across a full board for ordinary fixtures inside the deadline
week. The kill condition ("thin or favourites-only") is NOT triggered on the
live market.

Not established (needs a paid plan): whether the same depth holds
historically back to 2023-24 (the backtest years), and whether the
historical snapshot cadence puts a snapshot strictly before each FPL
deadline — the two facts that decide whether the market can be BACKTESTED
rather than only used live. The-odds-api's documentation states historical
player props from 2023-05-03; that is a vendor claim, unverified here.

No purchase decision is made in this step.

---

## 5. Step 2 — the two historical unknowns (paid tier, 2026-08-24). Small pull, 84 credits.

**Questions, stated before the pull.** (1) Does board depth hold
historically across three seasons? (2) Is there a snapshot strictly before
each FPL deadline? Kill conditions: boards materially thinner than live
(under ~20 players), or snapshots not reliably before deadlines.

**Method.** Seven ordinary fixtures (no big-six clashes), three with
congestion; every deadline read from the FPL `events[]` array in fplcache
and cross-checked against the availability parquet (all seven agree). Each
queried at deadline − 60 s so the returned snapshot is the last one strictly
before the deadline; the response's `previous_timestamp` / `next_timestamp`
give the cadence. Raw JSON stored before parsing (`step2_*`, `diag_*`,
`step2b_*`, `step2c_*` under `data/odds_props/raw/`). `probe_player_props_coverage.py --step2`
plus three inline follow-ups (recorded below).

### Unknown 2 — snapshots before the deadline: YES, in every case

| season / gw | fixture | type | FPL deadline (Z) | last snapshot before it | gap | next snapshot |
|---|---|---|---|---|---|---|
| 2023-24 GW13 | Luton v Crystal Palace | ordinary Sat | 2023-11-25 11:00 | 10:55:39 | 4 min | 11:00:40 |
| 2023-24 GW34 | Wolves v Bournemouth | DOUBLE, midweek 2nd fixture (Wed, +4 days) | 2024-04-20 12:30 | 12:25:39 | 4 min | 12:30:39 |
| 2024-25 GW16 | Wolves v Ipswich | ordinary Sat | 2024-12-14 13:30 | 13:25:38 | 4 min | 13:30:38 |
| 2024-25 GW28 | Brighton v Fulham | ordinary Sat | 2025-03-08 11:00 | 10:55:39 | 4 min | 11:00:38 |
| 2024-25 GW33 | Crystal Palace v Bournemouth | DOUBLE week | 2025-04-19 12:30 | 12:25:39 | 4 min | 12:30:38 |
| 2025-26 GW15 | Everton v Nott'm Forest | ordinary Sat | 2025-12-06 11:00 | 10:55:37 | 4 min | 11:00:37 |
| 2025-26 GW21 | Everton v Wolves | MIDWEEK round (Wed) | 2026-01-06 18:30 | 18:25:37 | 4 min | 18:30:37 |

Five-minute cadence throughout, a snapshot four minutes before every
deadline, doubles and midweek included. **Not the limiting factor.**

### Unknown 1 — board depth historically: uk NEVER; eu one book; us 4–5 books; nothing before autumn 2024

The uk region returned an **empty market at every one of the seven
snapshots**. Isolation on 2024-25 GW16 (Wolves v Ipswich, same snapshot,
13:25:38 Z):

| probe | result |
|---|---|
| uk, h2h (control) | 22 books priced — the snapshot exists and uk odds are captured |
| uk, anytime scorer, big-six fixture same week (Arsenal v Everton) | EMPTY |
| uk, anytime scorer, 1 h AFTER the deadline | EMPTY |
| **eu, anytime scorer** | **1xBet: 37 players** |
| **us, anytime scorer** | **FanDuel 35, BetMGM 36, Bovada 35, BetRivers 26** |

So uk player props are simply not captured historically — not for ordinary
fixtures, not for a big-six fixture, not after the deadline — although uk
match odds are. Historically the market lives in the eu and us regions.

Depth by season and fixture for the regions that carry it:

| season / gw | fixture | eu (1xBet) | us books (players) |
|---|---|---|---|
| 2023-24 GW13 (Nov 2023) | Luton v Crystal Palace | EMPTY | EMPTY |
| 2023-24 GW34 (Apr 2024, double) | Wolves v Bournemouth | EMPTY | — |
| 2024-25 GW3 (31 Aug 2024) | Brentford v Southampton | EMPTY | — |
| 2024-25 GW8 (19 Oct 2024) | Fulham v Aston Villa | **28** | — |
| 2024-25 GW16 (Dec 2024) | Wolves v Ipswich | **37** | FanDuel 35, BetMGM 36, Bovada 35, BetRivers 26 |
| 2024-25 GW33 (Apr 2025, double) | Brentford v Brighton | **33** | — |
| 2025-26 GW21 (Jan 2026, midweek) | Everton v Wolves | **40** | Bovada 39, DraftKings 35, BetMGM 35, FanDuel 33, BetRivers 29 |

- **2023-24 is empty in every region**, at an ordinary November fixture and
  at the April double. The vendor's "historical player props from
  2023-05-03" does not hold for EPL anytime scorer.
- **Coverage begins in autumn 2024**: absent at 2024-25 GW3 (31 Aug 2024),
  present at GW8 (19 Oct 2024). Present at every later snapshot tried,
  including the 2024-25 double week and the 2025-26 midweek round.
- Where it exists the boards are **full**: 1xBet 28–40, US books 26–39,
  against the live benchmark of 36–43 (BetRivers is the thin one at 26–29).
- The bookmaker set changes by season only in the sense that before autumn
  2024 there is none; from then on 1xBet plus FanDuel / BetMGM / Bovada /
  BetRivers (DraftKings appears by 2025-26).

### Kill conditions, evaluated

- "Boards materially thinner than live (< ~20)": **not triggered where the
  market exists** — but the market does not exist for uk books at all
  historically, and the eu region is a single book (1xBet).
- "Snapshots not reliably before deadlines": **not triggered** — 5-minute
  cadence, 7/7.

### What this establishes (report, no decision)

The go/no-go question as posed — *priced by UK/EU bookmakers, historically,
across a full board* — is answered **no for UK books** (live-only) and
**yes for one EU book from October 2024**, with US books as the only
multi-book historical source. The leak-free timing is fine. The binding
constraint is the calendar: a backtestable props feature covers roughly
2024-25 GW8 onward plus 2025-26 — about 1.7 of the three simulable seasons,
and none of 2023-24. Any props-based claim would be a ~1.7-season claim,
and its "market view" would be 1xBet's or a US-book consensus, not the UK
books the live system would read. Credits used in this step: 84
(19,915 remaining). No crosswalk, feature or scale pull was built.

---

## 6. Book-agreement check on the live market (2026-08-24; one request per fixture for uk+eu+us, so one instant per fixture)

Vig: anytime-scorer outcomes are not mutually exclusive, so implied probabilities cannot be normalised to 1. Each book is scaled proportionally so its total matches the cross-book mean total for that fixture (removes the book-level margin difference, keeps the shape); raw 1/price agreement is reported alongside. UK consensus = mean over UK books pricing the player; US consensus likewise. Favourites / longshots = top / bottom tercile by UK consensus probability.

| fixture | comparison | basis | n shared | Pearson | Spearman | MAD | MAD favourites | MAD longshots | longshot rel. diff | bias UK−other | UK-only / other-only |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bournemouth v Everton | UK consensus vs 1xBet | adjusted | 40 | 0.980 | 0.975 | 0.016 | 0.020 | 0.010 | 13% | +0.006 | 0 / 1 |
| Bournemouth v Everton | UK consensus vs US consensus | adjusted | 40 | 0.985 | 0.977 | 0.013 | 0.011 | 0.008 | 13% | +0.002 | 0 / 7 |
| Bournemouth v Everton | UK consensus vs 1xBet | raw | 40 | 0.980 | 0.976 | 0.016 | 0.017 | 0.012 | 14% | -0.003 | 0 / 1 |
| Bournemouth v Everton | UK consensus vs US consensus | raw | 40 | 0.990 | 0.984 | 0.010 | 0.007 | 0.006 | 9% | +0.002 | 0 / 7 |
| Bournemouth v Everton | paddypower vs skybet (UK floor) | adjusted | 40 | 0.998 | 0.997 | 0.005 | 0.007 | 0.003 | 4% | +0.000 | 0 / 0 |
| Coventry City v Hull City | UK consensus vs 1xBet | adjusted | 41 | 0.981 | 0.978 | 0.015 | 0.024 | 0.011 | 16% | +0.007 | 0 / 2 |
| Coventry City v Hull City | UK consensus vs US consensus | adjusted | 40 | 0.989 | 0.984 | 0.012 | 0.014 | 0.006 | 9% | -0.003 | 1 / 6 |
| Coventry City v Hull City | UK consensus vs 1xBet | raw | 41 | 0.981 | 0.978 | 0.017 | 0.025 | 0.012 | 16% | +0.000 | 0 / 2 |
| Coventry City v Hull City | UK consensus vs US consensus | raw | 40 | 0.990 | 0.988 | 0.014 | 0.021 | 0.006 | 9% | +0.007 | 1 / 6 |
| Coventry City v Hull City | paddypower vs skybet (UK floor) | adjusted | 40 | 0.998 | 0.998 | 0.006 | 0.008 | 0.003 | 4% | +0.000 | 0 / 0 |
| Leeds United v Brentford | UK consensus vs 1xBet | adjusted | 36 | 0.971 | 0.973 | 0.017 | 0.030 | 0.005 | 8% | -0.001 | 1 / 0 |
| Leeds United v Brentford | UK consensus vs US consensus | adjusted | 37 | 0.993 | 0.985 | 0.010 | 0.017 | 0.006 | 8% | -0.005 | 0 / 3 |
| Leeds United v Brentford | UK consensus vs 1xBet | raw | 36 | 0.970 | 0.970 | 0.017 | 0.032 | 0.004 | 6% | +0.004 | 1 / 0 |
| Leeds United v Brentford | UK consensus vs US consensus | raw | 37 | 0.993 | 0.987 | 0.012 | 0.017 | 0.005 | 8% | +0.009 | 0 / 3 |
| Leeds United v Brentford | skybet vs paddypower (UK floor) | adjusted | 37 | 0.998 | 0.997 | 0.005 | 0.007 | 0.003 | 4% | -0.000 | 0 / 0 |

**Pooled (mean over fixtures, adjusted basis):**

| comparison | Pearson | Spearman | MAD | MAD favourites | MAD longshots | longshot rel. diff | bias UK−other |
|---|---|---|---|---|---|---|---|
| UK consensus vs 1xBet | 0.977 | 0.975 | 0.016 | 0.025 | 0.009 | 12% | +0.004 |
| UK consensus vs US consensus | 0.989 | 0.982 | 0.012 | 0.014 | 0.006 | 10% | -0.002 |
| paddypower vs skybet (UK floor) | 0.998 | 0.997 | 0.005 | 0.007 | 0.003 | 4% | +0.000 |
| skybet vs paddypower (UK floor) | 0.998 | 0.997 | 0.005 | 0.007 | 0.003 | 4% | -0.000 |

**Reading (book agreement).** Three ordinary fixtures, one instant each (per-book
market updates within a 90-second window of a single request), 36-41 shared
players, five days before kickoff. Against the within-UK noise floor (Paddy
Power vs Sky Bet: Pearson 0.998, Spearman 0.997, MAD 0.005, longshot relative
difference 4%):

- UK consensus vs 1xBet: Pearson 0.977, Spearman 0.975, MAD 0.016 -- about 3x
  the floor. Favourites carry the larger ABSOLUTE gaps (0.025, i.e. roughly
  0.40 vs 0.375 for a top striker); longshots the larger RELATIVE gaps (12% of
  an implied ~0.08).
- UK consensus vs US consensus: Pearson 0.989, Spearman 0.982, MAD 0.012 --
  about 2.5x the floor; longshot relative difference 10%.
- Bias after the proportional margin adjustment is within +-0.005 either way;
  raw margins differ a lot between books (board totals 4.8 at BetRivers vs
  8.0 at Bovada on the same fixture), so the adjustment is not optional.
- Board membership: the UK boards are the near-subset. 1xBet and the US
  books price 1-7 extra fringe players per fixture (youth / backup keepers);
  UK-only players are 0-1 per fixture. Name forms differ across books
  ("Eli Junior Kroupi", "MIguel Angel Brau"), which is a crosswalk cost, not
  a signal difference.

What that means, stated as fact rather than decision: the books agree on
ORDER to 0.975-0.982 across the full board and to within ~1-2.5 percentage
points of implied probability per player, with the disagreement concentrated
at the top in absolute terms and at the bottom in relative terms. That is a
caveat on precision -- a floor of roughly 1-2 pp per player on anything a
props feature validated on 1xBet or a US consensus could claim about what the
UK books would say live -- not a different signal. Single snapshot, early in
the week; agreement typically tightens toward kickoff, so this is likely the
loose end of the range. Nine credits used; no feature, no crosswalk.
