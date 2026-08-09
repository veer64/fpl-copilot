# Simulator v1 — Results Log

**Date:** 2026-08-08
**Status:** v1 complete. Full 2025-26 season simulated end-to-end against four baselines.

---

## Headline

Playing the model for the 2025-26 season scores **1889 points** (49.7/gw).

| Strategy | Total | Per GW | Model's margin |
|---|---:|---:|---:|
| Random legal squads (n=50) | 816 ± 225 | 21.5 | **+1073** |
| Set and forget | 1368 | 36.0 | **+521** |
| **Model (walk-forward, 1 transfer/gw)** | **1889** | **49.7** | — |
| Perfect-hindsight ceiling | 2554 | 67.2 | −665 |

The model sits **4.8 standard deviations** above the random mean.

---

## What each number actually establishes

### +521 over set-and-forget — the transfer machinery works

This is the finding that matters, because it is the only clean isolation in the
table. Set-and-forget starts from the **identical GW1 squad**, uses the
**identical predictions**, and runs through the **identical scoring code**. The
single difference is that one makes 37 transfers and the other makes none.

So +521 points (about 14/gw) is attributable to the weekly transfer loop and
nothing else. No confound.

This also answers a question worth having asked: a squad optimizer that only ever
picked a good team in August would be close to worthless, since squads decay as
players get injured, rotated, or sold. The decay is visible — set-and-forget opens
at roughly 41/gw and finishes well below it.

### +1073 over random — not luck

50 random legal squads averaged 816 with a standard deviation of 225. The model is
4.8 sd above that mean. Beating random by less than its own spread would have been
no evidence at all; this is comfortably outside it.

### −665 against hindsight — the honest cost of not knowing the future

The ceiling squad is chosen knowing every player's final season total. Nobody can
do this; it exists to separate two very different failure modes.

The gap between set-and-forget (1368) and the ceiling (2554) is 1186 points. The
model captures **521 of those 1186, or 44%**. The remaining 665 is what perfect
foresight is worth, and no amount of optimizer sophistication recovers it — only
better prediction can.

---

## The cold-start problem (the clearest weakness found)

Splitting the season at GW7:

| Period | Points | Per GW |
|---|---:|---:|
| GW1–7 | 268 | 38.3 |
| GW8–38 | 1621 | **52.3** |

The model performs respectably once it has in-season data, and badly before that.
Those first seven weeks cost roughly **100 points** measured against its own later
rate.

Two causes, both structural:

1. **The walk-forward has nothing to learn from.** At GW1 the cutoff is the end of
   2024-25, so predictions come purely from prior seasons. Confirmed empirically:
   GW1 walk-forward and static predictions correlate at 1.0000 (mean abs diff
   0.0006), diverging steadily to 0.9950 by GW38.

2. **The minutes model cannot see team news.** Starting lineups are announced in
   press conferences an hour before kickoff. The model has no news feed at all.

### The failure mode, concretely

Worth recording because it is the single most damaging pattern observed:

| Player | GW1 pred | GW1 min | GW2 pred | GW3 pred |
|---|---:|---:|---:|---:|
| Joško Gvardiol | 4.41 (72 e_min) | **0** | 1.22 | 0.75 |
| Nicolas Jackson | 2.86 (49 e_min) | **0** | 0.72 | 0.51 |

The model predicted Gvardiol would play 72 minutes. He played none. It corrects
itself — 4.41 → 1.22 → 0.75 — but **slowly**, and with only one transfer per
gameweek the squad cannot shed dead weight fast enough. Jackson was still in the
squad at GW3, contributing nothing for three consecutive weeks.

This is the strongest argument in the project so far for an injury/availability
data source, and it is a data problem, not a modelling one.

---

## Bugs found and fixed while building

Three, all of which would have silently corrupted the result:

1. **Budget was hard-coded to £100m.** `optimize_squad` enforced the full starting
   budget on every solve, so mid-season it selected squads the manager could not
   afford. Surfaced as `transfer unaffordable: bank 10 + 50 - 63 = -3` at GW8.
   Fixed by adding a `budget` parameter, defaulting to `BUDGET` so every existing
   call is unchanged.

2. **Blank gameweeks made the season unsolvable.** At GW31 five squad players had
   no data row at all (their clubs had no fixture) — the only dip in a pool that
   otherwise grows monotonically from 690 to 841 rows. The MIP cannot lock a player
   who does not exist as a row, so every option came back infeasible. Fixed by
   injecting blanked owned players back into the pool with `e_points = 0` and their
   sell price, keeping them lockable while ensuring they are never chosen to start.

3. **Stale Jupyter imports masked fix #1.** The patched module was correct on disk
   but the kernel held the old version. Diagnosed by checking the chosen squad cost
   (986) against the intended budget (983) — the constraint was demonstrably not the
   one being enforced.

---

## Verification performed

Confidence in the 1889 figure rests on these, not on the number looking plausible:

- **GW1–4 identical between model and set-and-forget** (47, 37, 35, 45). They must
  agree while no transfers have yet been made, and they do exactly.
- **Captain doubled in all 38 gameweeks** for set-and-forget — the vice fallback
  never silently swallowed a captaincy.
- **Only 82 bench points stranded across the whole season** (~2/gw), confirming the
  XI selection is sound. A broken picker would strand hundreds.
- **50 tests across the three new modules**, all passing: 21 in `scoring.py`
  (autosubs, captaincy, hits), 29 in `squad_state.py` (sell-price rule, money
  conservation).
- **Sell prices modelled exactly**, not frozen: 600 of 841 players moved price in
  2025-26, with the largest swing 15 tenths. Freezing would have been wrong for 71%
  of the squad and would have compounded weekly.

---

## Known limitations (v1, deliberate)

- **Single transfers only.** Combination moves ("sell two mid-price defenders to
  afford one premium") are invisible to a one-at-a-time search. Documented in
  `FEATURE_IDEAS.md`; the correct fix is a transfer MIP, not a larger loop.
- **No chips.** No wildcard, bench boost, triple captain or free hit. A wildcard
  alone would likely have addressed much of the cold-start damage.
- **Never takes a hit.** The policy only spends free transfers. The machinery for
  hits exists and is tested; the v1 policy does not use it.
- **No confidence interval yet.** The 1889 is a single path through one season.
  A block bootstrap over gameweek blocks is needed before the number is quoted
  with any precision.
- **Template baseline is a proxy.** This dataset has no ownership percentages, so
  the template team is approximated by season total points, which makes it
  hindsight-informed. It is currently identical to the ceiling and should not be
  presented as an achievable strategy.

---

## Next

1. Block bootstrap for a confidence interval on the 1889.
2. Log simulator runs to MLflow — this is exactly the multi-config experiment the
   tracking server was set up for (bench weights, transfer policies, ablations).
3. Ablations worth running: bench weight sweep, captain-only vs full optimizer,
   static vs walk-forward predictions.
4. Investigate an injury/availability data source. On this evidence it is the
   highest-value addition available to the project.