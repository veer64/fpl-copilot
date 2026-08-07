# Optimizer — Testing Log

**Phase:** 2 (optimizer close-out) · **Status:** complete, 5 tests passing
**File:** `test_optimize.py` (repo root) · **Run:** `uv run pytest test_optimize.py -v`
**Master plan:** §7.4 — the optimizer is "exhibit A" for property-based testing.

---

## What this is

Property-based tests for the squad optimizer. Rather than checking a few
hand-picked inputs, we assert one **property that must always hold** — "the
optimizer always returns a legal FPL squad" — and let **Hypothesis** throw many
random player pools at it trying to break that property.

Why this fits the optimizer: the expected-points numbers change every gameweek,
so we can't hand-test every input. But we *can* assert that no set of numbers
should ever produce an illegal team. One property, effectively unlimited cases.

---

## The pieces

- **`make_random_pool(seed)`** — generates a random-but-realistic pool
  (20 clubs, ~70% cheap £4.0–6.0m fodder). Realism matters: see the seed-122
  finding below.
- **`assert_legal_squad(df, sol)`** — the property, encoded as assertions:
  15 players, exact position counts, ≤£100m, ≤3 per club, exactly 11 starters,
  legal formation (1 GK / 3–5 DEF / 2–5 MID / 1–3 FWD), exactly 1 captain who
  is a starter.

## The five tests

1. `test_default_mode_always_legal` — 30 random pools, `balanced` mode, each
   squad legal.
2. `test_all_modes_legal` — 10 pools × all 4 modes, each legal.
3. `test_locking_forces_players_in` — locks the two top scorers, confirms both
   are in the squad and it's still legal.
4. `test_infeasible_pool_reports_infeasible` — an impossible pool (all players
   £14.0m) must report `Infeasible`, not fake an answer.
5. `test_bench_weight_overrides_mode` — raw `bench_weight` overrides a named
   mode; unknown mode raises.

Result: **5 passed in ~54s.**

---

## What the tests caught (the finding worth keeping)

The first Hypothesis run **failed at seed 122**: the optimizer returned
`Infeasible`. Investigation showed it was *not* an optimizer bug — the original
naive pool generator (uniform £4–14m prices, only 10 clubs) could randomly
produce pools where no legal squad fits under £100m once **max-3-per-club** is
also enforced. The cheapest per-position squad cost £99.5m, but forcing club
spread pushed the real cheapest legal squad over budget. The optimizer was
correctly reporting "no legal squad exists."

Fix was on the **generator**, not the optimizer: 20 clubs + mostly cheap fodder,
mirroring real FPL (which always has enough cheap, well-spread players). This is
the intended payoff of property testing — it surfaced a budget/club-spread
interaction we'd never have hand-tested. The optimizer itself came out
unchanged, just proven trustworthy.

---

## Scale / speed note

Each solve rebuilds the MIP from scratch (~0.5–0.8s). Example counts are kept
modest on purpose — structural constraint bugs don't depend on rare values, so
30–40 random solves catch them as well as hundreds would, while keeping the
suite ~1 min and CI-friendly. An early 500×4-mode run took 14 min and was
abandoned as pointless. This is itself a lesson: a test that's too slow to run
isn't a gate (master plan wants the fast subset wired into CI, §6).

## Housekeeping

PuLP emits thousands of `DeprecationWarning`s (LpVariable construction and
`PULP_CBC_CMD` renames coming in PuLP 4.0 — harmless now). Silenced in
`pyproject.toml` via `[tool.pytest.ini_options] filterwarnings` targeting only
`DeprecationWarning:pulp`, so genuine warnings from other libraries still show.