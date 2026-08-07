# Optimizer — Build Log

**Phase:** 2 (Week 6, second half) · **Status:** complete, validated, in `optimize.py`
**Consumes:** `data/predictions_2526.parquet` (from `assembly.py`)
**Prices from:** `data/history/all_seasons_fixed.parquet` (`value` column)
**Test gameweek:** GW1, 2025-26 (sealed test season — predicted, never tuned against)

---

## 0. What this is

A mixed-integer program (MIP) that picks the provably-optimal FPL squad for a
single gameweek. It chooses the 15, the starting XI (in a legal formation), and
the captain **all at once**, maximizing expected points under the real FPL rules.

Built with **PuLP** (readable formulation) solved by **CBC** (PuLP's default
solver). Solves in ~1 second on ~690 players.

One command reproduces the result:

```
uv run python optimize.py
```

---

## 1. Why MIP and not greedy (the core lesson)

The naive approach — "just pick the highest-scoring players per position" —
fails because the constraints **interact**. A worked example that makes it
concrete:

- Greedy fills the 2 GK slots with the two highest-scoring keepers.
- But you only ever play ONE keeper; the second sits on the bench scoring ~0.
- So greedy wastes money on a backup keeper that a smart pick spends elsewhere
  (e.g. saving £1.0m on the bench keeper is exactly what affords a premium
  midfielder who scores +3 in the starting XI).

Greedy optimizes each slot in isolation and is blind to these cross-position
trade-offs. MIP considers all picks simultaneously and finds the combination
that is **provably** best across every constraint at once. This is the whole
reason the optimizer exists, and it's the interview centrepiece (master plan §3.6).

Confirmation the machine reasons this way: it independently discovered "don't
overspend on the backup keeper" — it was never told to.

---

## 2. Data prep

Input predictions file (`predictions_2526.parquet`): 29,338 rows × 16 cols,
per player-GW `e_points` plus a component breakdown. Has `element`, `position`
(GK/DEF/MID/FWD), `team` (club names) — but **no price**.

Price (`value`) lives in `all_seasons_fixed.parquet`, keyed on `element` +
`round` (round == gameweek). Prices are in FPL tenths (55 = £5.5m).

Steps in `load_gw_data(gw)`:
1. Filter predictions to the chosen GW → 690 players for GW1.
2. Pull `(element, value)` for that GW from the history file.
3. **Dedupe:** 2 players (elements 391, 100) had duplicate price rows. The
   duplicates were *identical* on value (harmless double-recording, likely a
   double-fixture week), but left in they'd let the optimizer "pick" a player
   twice. `drop_duplicates(subset="element", keep="first")` fixes it → 690/690.
4. Merge price on; **guard**: raise if any player is missing a price (fail loud
   rather than optimize on bad data).

**Verification that the prices are real** (internal sanity, better than a web
lookup for last-season data): cheapest = £4.0m (FPL floor ✅), most expensive =
£14.5m (Salah ✅), top-8 by price are all genuine premiums (Salah, Haaland,
Palmer, Isak, Saka, Watkins, Bruno, Gyökeres ✅). Scale and content both correct.

---

## 3. The MIP formulation

### 3.1 Decision variables (three switches per player)

- `pick[i]`    — is player i in the 15?
- `start[i]`   — is player i in the starting XI?
- `captain[i]` — does player i wear the armband (2x)?

690 of each.

### 3.2 Objective

```
maximize:  Σ start[i]·pts[i]                    # starting XI scores full points
         + Σ captain[i]·pts[i]                  # captain scores AGAIN (the 2x)
         + w · Σ (pick[i] - start[i])·pts[i]    # bench, weighted by w
```

Two modelling tricks worth recording:
- **Captain doubling without a ×2 variable:** a captain is counted once as a
  starter and once more as captain, so the two sums naturally add to 2× for
  whoever gets the armband. No special variable needed.
- **"On the bench" = `(pick - start)`:** picked-and-starting → 1-1=0 (no bench
  points); picked-not-starting → 1-0=1 (gets bench weight); not picked → 0.
  Cleanly isolates bench players in the objective.

### 3.3 Constraints (1416 total for GW1)

Squad-level (on `pick`):
- exactly 15 picked
- position counts: exactly 2 GK / 5 DEF / 5 MID / 3 FWD
- budget: Σ price·pick ≤ 1000 (£100.0m) — note `<=`, you needn't spend it all
- max 3 per club (20 constraints, one per team)

Starting XI:
- exactly 11 start
- **`start[i] <= pick[i]`** for every player — can only start someone you picked.
  This `<=` linking pattern is the standard MIP idiom for "if you do X you must
  also have done Y", and it recurs below for the captain.
- legal formation, as min/max ranges (not fixed counts): GK exactly 1,
  DEF 3–5, MID 2–5, FWD 1–3.

Captain:
- exactly 1 captain
- **`captain[i] <= start[i]`** — captain must be a starter.

Locking (optional):
- for each locked element: `pick[idx] == 1` (force into squad).

---

## 4. The bench weight — the key design decision

"Bench = 0" (pure XI) is too extreme: the solver buys four £4.0m ghosts who'd be
useless if a starter drops out. But the bench isn't worthless either — FPL
auto-subs bench players in when a starter doesn't play. So a bench player's real
expected value ≈ their points × P(they get auto-subbed in), which is **low but
not zero**.

We model this with a single `bench_weight` dial:

| weight | behaviour |
|--------|-----------|
| 0.0    | ghost bench (max XI, throwaway bench) |
| ~0.2   | real, usable bench with minimal XI sacrifice |
| 1.0    | all 15 equal (the original "best 15" behaviour) |

The honest auto-sub probability sits around **0.1–0.25**, which is the whole
meaningful playground. Below 0.1 the bench barely matters; above ~0.3 you
overpay for players who mostly won't play and weaken the XI.

### 4.1 Named modes (with a raw override)

```python
MODES = {
    "best_11":      0.0,   # ghost bench
    "balanced":     0.2,   # default — real, useful bench
    "strong_bench": 0.35,  # trade a little XI ceiling for a safer bench
    "best_15":      1.0,   # all 15 equal
}
```

- `mode="balanced"` etc. for the common cases.
- Raw `bench_weight=0.5` **overrides** the mode — the escape hatch for
  "I want an even stronger bench". Presets for humans, raw number for tuning.
- `balanced = 0.2` chosen as the midpoint of the honest auto-sub range: enough
  to buy a playing backup keeper + one decent outfield sub (the positions that
  actually auto-sub), without meaningfully weakening the XI.
- `strong_bench = 0.35` is deliberately *past* the true auto-sub range — it's a
  legitimate preference (valuing insurance over ceiling), not a mistake. Worth
  stating plainly if asked.

### 4.2 Observed effect (GW1)

- **weight 0.0:** bench = four £4.0–4.5m ghosts scoring ~0.4 each. XI maximal.
- **weight 0.15:** bench upgraded to Hermansen (GK, 3.17) + van Hecke (DEF,
  3.07) + two cheap FWD fillers — solver spends the bench budget where auto-sub
  value is highest (keeper + one outfielder), not blindly across all four.
- **weight 0.2 (default, final):** bench = Sels (GK 3.6), van Hecke (3.07),
  Sarr (2.39), Delap (3.22); £21.0m of real bench value; XI + captain = 52.19.

---

## 5. Locking ("give me these players, optimize the rest")

Locking a player is just one more constraint: `pick[that_player] == 1`. The same
machine solves the other slots around it, respecting all budget/position/club
rules automatically.

- Accepts **any number** of players, by element ID or by name.
- Name resolution (`resolve_names`) is substring, case-insensitive, and
  **safe**: warns and skips on no-match or multi-match rather than silently
  locking the wrong player (the "Gabriel = 3 Arsenal players" disambiguation
  problem, master plan §5.4).
- Consequence to remember: locking can only make the objective **worse or
  equal**, never better (it removes freedom), and can make the problem
  **infeasible** (e.g. lock 3 players you can't afford the rest around). Status
  will show `Infeasible` in that case.

Validated: locking Salah (absent from the free optimum) forced him in and points
dropped 58.18 → 56.94, with Haaland dropped to afford his £14.5m — a real,
legible re-solve. Locking 5 players at once (by full name, first name, and
surname) also worked cleanly.

---

## 6. Validation & results (GW1, mode=balanced)

Status: **Optimal**. All constraints provably satisfied:
- 11 starters + 4 bench = 15 ✅
- Formation 5-4-1 (1 GK, 5 DEF, 4 MID, 1 FWD) — legal; note the solver chose a
  5th defender over a 2nd striker for the 11th slot, since Haaland is captained
  and the other forwards are weak — a real tactical trade-off ✅
- £100.0m spent exactly, ≤ budget ✅
- Max-3-per-club held (Liverpool, Man City, Chelsea each at 3) ✅
- Captain = Haaland (highest e_points at 6.29 — correct, doubling wants the
  top scorer) ✅
- Bench = real players (£21.0m of value), not ghosts ✅

**On the headline number:** "XI + captain = 52.19" is *lower* than the original
all-15 optimizer's 58.18 — this is correct, not a regression. The two numbers
measure different things. The old 58.18 summed all 15 (flattering itself by
counting bench points that rarely happen). 52.19 is the honest "what this team
actually scores on the day": 11 starters + a doubled captain, bench = 0 in real
scoring. The new optimizer answers the *right* question ("what will actually
score?"), redirects wasted bench money into the XI, and is genuinely stronger
despite the smaller headline.

---

## 7. Known limitations / parked for later

- **Flat bench weight, not per-player auto-sub probability.** The principled
  version weights each bench player by their *actual* P(auto-sub in), which the
  minutes model already estimates (P(start)). A flat 0.2 captures ~90% of the
  benefit for far less complexity. Upgrade later.
- **Single gameweek only.** No transfers, no free-transfer banking, no −4 hits,
  no chips, no multi-GW horizon. That's the next big optimizer layer
  (master plan §3.6).
- **Not wired into the live app.** Runs locally only; production still serves
  Phase 1 naive predictions. Wiring + MLflow lineage is later Phase 2 / Phase 3.
- **No property-based tests yet.** Master plan §7.4 flags the optimizer as
  "exhibit A" for Hypothesis testing (random inputs → always a legal squad).
  High-value next add; genuine interview artifact.
- **Sell-price / purchase-price accounting** (FPL gives back only half of price
  rises, rounded down) is irrelevant for a from-scratch GW1 squad but will
  matter once transfers exist.

---

## 8. File map

- `optimize.py` — the production module. Key functions:
  - `load_gw_data(gw)` — load predictions + attach prices (any gameweek)
  - `optimize_squad(df, mode=, bench_weight=, locked_elements=)` — the MIP
  - `optimize_by_names(df, lock_names=, mode=, bench_weight=)` — lock by name
  - `resolve_bench_weight`, `resolve_names` — helpers
  - `get_team`, `team_points`, `show_team` — output
- Return shape: `(prob, sol)` where `sol = {"pick","start","captain"}`.
- `explore_predictions.ipynb` — the experiment notebook this was distilled from.