# Hold comparison in `propose_transfers` — design, measurement, build (2026-09-18)

Closes the item carried since the proposal-table review and listed in the Squad State handoff
§12.2 as "a design was requested and not delivered".

**The problem.** `propose_transfers` reported a gain but never recorded what doing nothing scores,
so a reader could not tell a clear gain from a near-tie — on a system where roughly 20% of backtest
deadlines were decided by margins under 0.02, with no tie-break principle and two exact ties in
2025-26. `get_my_xi` already reported `expected_gain_vs_recorded`; this is the equivalent against
hold.

---

## 1. What was already there, switched off

`transfer_mip.build_and_solve` has taken `force_hold=True` since the hold-preference pre-registration:
it adds exactly one constraint, `used[0] == 0`. `simulator.decide_gameweek_mip` already ran that
second solve and computed a margin — all of it gated behind `HOLD_PREFERENCE_EPS = None`.

That gate is a **decision rule**, not a disclosure: below the epsilon it silently swapped the move
plan for the hold plan. It was left at None. The comparison added here is a separate, additive path
that computes and reports the margin and **never alters what is recommended**.

## 2. The form

- **Hold THIS gameweek only** — `used[0] == 0`, steps 1-5 free. Not hold-forever: nobody decides to
  stop transferring for six weeks; the question is move now or wait.
- **The rolled free transfer is valued.** `ft[t] <= ft[t-1] - spend[t-1] + hits[t-1] + 1`, so
  `used[0] = 0` gives `ft[1] <= ft[0] + 1` — hold at GW5, enter GW6 with 2. Capped at
  `MAX_FREE_TRANSFERS = 5`, so holding on 5 rolls to 5, not 6. Note this is the MIP's own
  accounting; `squad_store.free_transfers_at` is a different thing — it only sets `ft[0]` from the
  stored version (`min(5, stored + (G - version.gw))`). Both are correct, only the first is
  load-bearing here.
- **The XI is re-solved at every step** in both plans — `start[i,t]` is a decision variable per step
  — so holding is not penalised by a frozen lineup the manager would have fixed anyway. This needed
  no work: freezing it would have required deliberately adding a constraint.
- **No second solve when the move solve already holds.** If the unconstrained optimum makes no
  step-0 transfer, adding `used[0] == 0` cannot change it: same plan, gap exactly zero. The solve is
  skipped (`hold_solved = False`) rather than paying ~15 s to rediscover a known answer.

## 3. Measured cost (droplet, live state: squad version 11, run 15's frame, GW5, H=6)

| | rep 1 | rep 2 | mean |
|---|---|---|---|
| move solve | 19.3 s | 20.6 s | **19.9 s** |
| hold solve (`force_hold=True`) | 13.9 s | 16.8 s | **15.3 s** |

**The hold solve is FASTER — 0.77×.** `used[0] == 0` fixes the step-0 buy variables and prunes the
tree. Combined **35.3 s, 1.77× the previous cost**, inside the 1.6–2.0× estimate. Pools are built
once (0.0 s) and shared by both solves.

**Memory: no pressure.** Peak RSS 459 MB for the whole measuring process — 132 MB after imports,
153 MB after the frame, 441 MB after the first solve, 459 MB after four. The second solve adds
essentially nothing: the pools are shared and PuLP releases each model. Against §1.8's full-build
peak of 1,569 MB with ~1.5 GB headroom, and its 330 MB for the MIP alone, this is consistent and
leaves the headroom untouched.

**Consequence for the wait wording.** Observed combined range 33.2–37.4 s against a band topping out
at 40 s, and §1.8 already records the same MIP at 22.4 s vs 8.7 s on different instances. "Typically
ten to forty seconds" would be true on average and wrong often enough to matter on a tool the user
waits on. Revised to **"typically twenty to sixty seconds, occasionally longer"** in the docstring,
the tool schema and the system prompt.

---

## 4. FINDING: the gap cannot be measured honestly while a lambda has run off

**This is a finding, not an implementation obstacle, and it is new as of this session.**

Holding earns a second free transfer at the next gameweek. If a club with a runaway Dixon-Coles
strength sits inside the horizon, the hold plan can spend that extra transfer on exactly the
fixtures the model has mispriced — buying into a fake bargain the move plan, with one fewer
transfer, cannot reach as far into. The hold's objective is therefore inflated in proportion to the
transfer that holding earns, and:

> **the hold-vs-move gap is biased toward recommending HOLD, by an unknown amount.**

**This is a second, independent consequence of KNOWN_ISSUES #25, distinct from the Botman artefact.**
The Botman problem is that a contaminated fixture inflates a *player's* value at a later step. This
is that a contaminated fixture inflates the value of *having an extra transfer*, which corrupts a
comparison rather than a price. The first is visible in a plan's later steps and can be declined by
a reader; the second is invisible, because it lands inside a single scalar the reader is being asked
to trust.

It is also **a new argument for closing #25 that did not exist before this session**. The
pre-registrations (v1 falsified, v2 and v3 marginal) were all argued on rank-correlation endpoints.
This is a different kind of cost: a feature built to tell a clear gain from a near-tie cannot do its
job at all while the defect is live. That is worth weighing when #25 is next considered — it is not
covered by "let Coventry score", because the bias persists for as long as any club's strength is
outside the box, whoever that club is.

Today's fixture resolution makes it concrete rather than theoretical: the extra free transfer a hold
earns lands on **GW6, which is Coventry City v Newcastle** (2026-10-12, Newcastle away), the very
fixture where Coventry sits at lambda 0.0006.

### The response: refuse, do not caveat

While the detector fires, the report withholds the gap and gives a refusal naming the condition and
saying when to ask again. Both plans are still **computed and stored** — the record survives, only
the verdict waits. The same rule governs the rolled-transfer offer, which is refused outright rather
than answered with a warning attached, because that exploration is priced on precisely the gameweek
the runaway contaminates.

A caveat was rejected deliberately: a number presented with a warning is still a number the reader
will use.

## 5. FINDING: one observation does not bound the bias

The measurement run produced move 115.662 against hold 113.799 — a gap of **+1.863**, two orders of
magnitude above the ~0.02 near-tie band.

**This does not establish that the bias is small.** It is a single observation, and a weak one: it
comes from a *post-transfer re-solve* at GW5 from squad version 11 with 1 free transfer, not from the
decision that was actually taken. The contamination runs in the direction of hold and did not
overturn the result here; that is one draw, not a bound. Nobody should cite +1.863 as evidence the
gap is usable while the detector fires.

---

## 6. What was built

| file | change |
|---|---|
| `squad/simulator.py` | `decide_gameweek_mip(..., hold_compare=False)`. When on, solves the same pools with `force_hold=True` and attaches `hold_objective` / `hold_margin` / `hold_plan` / `hold_team` / `hold_solved` / `hold_seconds` / `hold_status` to `plan[0]`. `step` is never reassigned, the tuple shape is unchanged, and the default is off. |
| `db_write.py` | `plan_kind` and `paired_proposal_id` as nullable columns via `ADD COLUMN IF NOT EXISTS`; both added to `PLAN_COLS`. |
| `model_tools.py` | `propose_transfers` passes `hold_compare=True`, dry-runs the hold through `plan_change` like any other plan, writes the hold proposal, then the move pointing at it, and reports `hold_comparison` + `rolled_transfer`. |
| `agent.py`, `prompts/system_prompt.md` | the hold-comparison contract, the refusal rule, and the revised wait wording. |

**Storage.** The hold is written **first** so the move can reference it and nothing is ever
`UPDATE`d — the table stays append-only. The link is one-directional by design (move → hold); to go
the other way, `SELECT ... WHERE paired_proposal_id = <the hold's id>`. The hold carries **no step-0
row** and its steps 1-5 as `executable = false`, the same convention the move plan already uses. The
gap is **not** stored: both objectives are on the rows, and a stored difference is one more thing
that can disagree with them.

**Reporting.** `gap_objective` (six-week decayed, the quantity the ~0.02 near-tie threshold refers
to) and `gap_this_gw` (deadline gameweek expected points alone) are separate numbers and must never
be added together.

## 7. Bit-identity of the backtest

`hold_compare` defaults to False and no backtest caller passes it, so `walk_forward` and the arm
builders cannot reach the new block. Proven against the existing guards rather than asserted:

```
Tests/test_live_deadline.py  Tests/test_asof_reconstruction.py
Tests/test_walkforward_provenance.py  Tests/test_transfer_mip.py
Tests/test_transfer_mip_locks.py  Tests/test_hold_preference.py
Tests/test_bench_boost_aware.py
-> 57 passed in 195 s
```

That includes the parity family, the as-of leakage guard, and the record fingerprint
(`EXPECTED_SPEARMAN 0.7453`, `EXPECTED_MAE 1.0510`, `EXPECTED_ROWS 165_401`).

New coverage: `Tests/test_hold_comparison.py`, 11 tests — the gate rests None; default-off leaks no
keys; `hold_compare=True` leaves team, transfers, objective, squad, starters and captain identical;
the hold holds step 0 and frees steps 1-5; the rolled transfer is credited (`ft[1] == 2`); the hold
XI is re-solved; the skip path when the move already holds; the two schema columns; the gap is not a
column; and the wait wording no longer says "ten to forty seconds".
