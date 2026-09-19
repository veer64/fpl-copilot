# `get_fixtures` and `get_price_movements` — design, measurement, build (2026-09-19)

Master plan §5.4 specifies both. Squad State handoff §12.2 item 3 calls them "cheap — the data
is on the volume and in the poller's snapshots already." Both true. What the data actually looks
like was not, and two stated premises turned out to be wrong.

---

## 1. Where the data actually lives (measured on the server, not assumed)

| Thing | Where | Freshness | Read cost |
|---|---|---|---|
| Fixture calendar | `data/history/forward_skeleton_2026_27.parquet` — GW5–38, 659 elements/GW, `opponent_team` (FPL id), `was_home`, `kickoff_time`, all non-null for every future GW | **weekly ingest** (2026-09-15 18:23Z) | 14 ms |
| Team id → name | `teams` block of the newest bootstrap snapshot | per snapshot | negligible |
| Fixture lambdas | `model_predictions.team_lambda/opp_lambda/p_cs`, constant within (team, gw) | per build | 30 ms |
| Price snapshots | `data/live/bootstrap_raw/2026-27/*.json.gz`, 53 files | burst | 41 ms each |
| Purchase price | `squad_versions.squad_json[].purchase_price` | on write | negligible |

Three things the investigation settled that changed the design:

**The E0 calendar is the wrong source.** `odds_fixtures_2026_27.parquet` is fresher (regenerated
every deadline run) but has `dd/mm/yyyy` strings, **no gameweek column**, and football-data
spellings needing `assembly.TEAM_MAP` (`Man United`→`Man Utd`, `Tottenham`→`Spurs`). The forward
skeleton has gameweeks, home/away and FPL spellings already. Verified end to end: **20/20 team
ids resolve, zero unmapped opponents, name sets identical, and every GW6 fixture self-pairs**
(both sides present and mutually consistent, 0 exceptions). No bridging at all.

**`dixon_coles.get_fixtures` — same name as the tool — REFITS Dixon-Coles.** It is the model
path. A chat turn must never trigger it. `fixtures_tool.py` is pure, like `explain.py` and
`quantiles.py`: it imports no part of the model stack.

**The frame carries no opponent and no home/away.** It has `team`, `team_lambda`, `opp_lambda`
per (team, gw). At GW6 Everton reads `team_lambda 0.5014 / opp_lambda 1.1014` and Hull City
reads the mirror image — so the opponent *looks* inferable by pairing lambdas. Measured: **0
collisions across gw5–10**, so it would appear to work. It is still refused, because it fails
exactly when `step_is_degenerate` fires and all 20 clubs sit at the fit's starting point —
i.e. when the model is broken, which is when a reader most needs the fixture list. The opponent
comes from the calendar or it is not named.

---

## 2. Two premises that were wrong, and what replaced them

### 2.1 The snapshots are not daily

Master plan §5.4 says "risers/fallers from your daily snapshots". Measured: **53 files over 30
days, on SIX distinct days** — 08-20 (2), 08-21 (1), 08-28 (11), 09-04 (13), 09-12 (13), 09-18
(13). Gaps of 6–8 days. They are burst-sampled around builds, not polled daily.

Prices change every day, so an *individual* daily move between two snapshots is unobservable,
and a rise followed by a fall cancels to "no change". What rescues the tool is that FPL keeps
cumulative counters: `cost_change_start` (net since season start; 29 risers / 240 fallers / 390
flat, range −3..+4) and `cost_change_start_fall` (falls alone), so net is exact regardless of
sampling and gross up/down is recoverable from the pair.

The unit of the tool is therefore **net change between two observations**, and `observation`
carries both timestamps, `snapshots_in_window`, `largest_gap_hours` and a sentence saying that
"no change" means no NET change, not that the price held.

### 2.2 FPL *does* publish threshold progress — and the constraint survives anyway

The stated reason for forbidding forecasting was that FPL's transfer thresholds are unpublished.
On this data they effectively are published: every element carries `price_change_percent`
(−227.3 … +129.7, 422 distinct values, 5 at or above 100, and it **moves between snapshots**),
plus `price_change_hourly_rate`, `price_change_locked_until`, `price_change_calibrating` and
`price_change_projections` — FPL's own forward projection as `{offset, projected_percent,
likelihood}`.

Ruling 2026-09-19, option (a), narrow. The constraint stands, but **on the laundering argument
rather than the unavailability one**: a projection sitting in the payload becomes the agent's own
forecast whatever the prompt says, and a wrong price call attributed to us is worse than no price
call.

- `price_change_percent` **is** carried, always attributed to FPL, never as ours.
- `price_change_projections` and the other three forward fields are **excluded from the payload
  entirely**, so there is nothing to launder.

The exclusion is enforced in code (`prices_tool.FORWARD_FIELDS`, never read out of the snapshot)
and tested by grepping the serialised payload for each name and for the projection's own values.
The exclusion notice deliberately does **not** name the fields — naming them would put the
strings in the payload and defeat that tripwire.

---

## 3. `get_fixtures` — difficulty as two numbers

### The correction that shaped it

The spec described attacking difficulty as "the opponent's defensive lambda". The frame does not
have that. `team_lambda` is `attack_ours × defence_theirs × home_advantage` — the expected goals
in **this fixture**. The factors exist only inside the fit, which is the model path.

Reporting a fixture-level product as an opponent rating would be a **subtler version of the FDR
error** — not collapsing two numbers into one, but mislabelling what one of them measures. So:

- `attacking.value` = `team_lambda`, described as expected goals for this team in this fixture.
- `defensive.value` = `p_cs` (the 0.2·DC / 0.8·market blend — what the model actually uses),
  with `opp_lambda` alongside.
- Both carry `these_are_products`: comparing one club's fixtures across gameweeks is valid;
  comparing defences across *different* clubs' fixtures conflates the attacker.

`p_cs` is also **not** `exp(−opp_lambda)` — at step 0 they differ (sd 0.0211, max 0.0782), the
coupling error the quantile work found. Both are reported so neither hides the other.

No composite score exists anywhere in the payload, and a test asserts no key named `score`,
`fdr`, `difficulty`, `overall` or `composite` sits inside the difficulty block for the agent to
grab.

### Provenance, reused not re-derived

`explain.fixture_provenance(row, step_rows)` was factored out of `breakdown()` — the same move as
`fixture_runaway` yesterday. It returns `(source, constant, notes)` covering degenerate → the
`x0_fixture` constant, neutral → `neutral_fixture`, else `model`, plus `RUNAWAY_NOTE` and the
"beyond the deadline gameweek… not the market" note. `explain.market_priced(row)` is new and
small, and `fixtures_tool` contains **no copy** of the bound or the labels — asserted by a test
that greps the module for `LAMBDA_MIN`, `LAMBDA_MAX`, `0.15`, `6.0` and `x0_fixture`.

**Proof that `breakdown()` is unchanged:** 11 synthetic rows covering every fixture branch
(model at step 0, pure DC at step 3, neutral, opponent-runaway, own-runaway, both, DGW,
DGW+runaway+step 2, GK, no-Understat FWD, step 1 with odds) × 3 `step_rows` states (none,
non-degenerate, degenerate) = **33 comparisons, byte-identical, 0 differences**.

### The two designed refusals

- **Past the horizon.** The skeleton runs to GW38; a run prices six gameweeks. A fixture beyond
  it comes back with `difficulty: null` and `difficulty_unavailable` naming the range and saying
  *"this is a missing CALCULATION, not an easy fixture"*. Never omitted, never fabricated — the
  same rule the quantile block uses for a run that skipped them.
- **Doubles and blanks.** `n_fixtures` is 1 on every row today, and the exploratory query used
  `drop_duplicates(["team","GW"])`, which **would have silently dropped the second leg of a
  double**. The tool groups into a list per (team, gw), sets `double_gameweek`, and reports
  `blank_gameweek: true` for a team with none.

---

## 4. `get_price_movements` — observed, and the selling rule reused

Two blocks: `my_squad` (per-player purchase price, price now, `sells_for`) and `risers`/
`fallers` over the window.

Selling price is **`squad_state.sell_price`**, the function the transfer MIP and
`propose_transfers` already share under a mismatch assertion. Not a third copy of the rule —
`"// 2" not in src` is asserted. `sells_for` is not `price_now` for a risen player, and the
payload says why: quoting the market price overstates the budget, which is how an unaffordable
transfer gets proposed. An unpriced player is valued at what you paid, because assuming a rise
invents money.

Only the two **bracketing** snapshots are parsed — O(1), not O(archive), which matters as 53
files become ~250 by May at 41 ms each. A test counts the parses and fails at three.

---

## 5. Cost, placement, model path

| | measured | placement |
|---|---|---|
| `get_fixtures` | 30 ms SQL + 14 ms parquet + shaping ≈ **60 ms** | on demand |
| `get_price_movements` | **73 ms** (two brackets; 2.45 s to scan all 53) | on demand |

Neither runs inside a build. Neither touches the model path: both read stored outputs and static
artefacts, and `explain.py` imports no part of the model stack, so factoring `fixture_provenance`
out of it is a read-side refactor. **No parity gate applies**, and the byte-identity proof above
is what stands in for one.

Skeleton staleness is **accepted** (ruling 2026-09-19): `calendar_source.age_hours` is stamped on
every answer with the caveat that fixtures get rescheduled. Not refreshed per build — that would
touch the build path for a calendar that rarely changes, and the moved-fixture case already
raises in the strict re-pull.

---

## 6. OPEN ITEM: the tool budget is spent

Master plan §5.4: *"Deliberately small surface (~10) because tool sprawl degrades tool
selection."* The registered surface was **15**. These two make **17**. `search_news` (§5.6, and
the only legitimate origin for an injury claim under the §5.5 grounding contract) would make
**18** — and it is not optional, so the real count is 18 against a stated budget of about 10.

Recorded as its own item rather than a footnote, because the overrun is now structural:

- The budget is **spent**. Every tool on §5.4's own list is either built or committed to.
- **The next tool needs an argument, not just a use case.** A use case is why someone would call
  it. An argument is why the whole surface is better with it than without — which now means
  saying what it displaces, or why selection does not degrade at 19.
- Nothing here is evidence that selection *has* degraded; there is no measurement of tool-choice
  accuracy at any surface size. That absence is the point: the budget was set by judgement and is
  being exceeded by judgement, with no instrument either way. If the surface keeps growing,
  the instrument should come before the growth.

Also noted: `tools.py` is dead code. `agent.py` imports from `model_tools`, and `tools.py`'s five
functions (`resolve_player`, `get_player_card`, `predict_points`, `optimize_squad`,
`list_players`) are reachable from nothing. It is not part of the 15 and should be deleted in its
own change.

---

## 7. Tests

`Tests/test_fixtures_tool.py` (20) and `Tests/test_prices_tool.py` (17). Both drive
`agent.call_tool(...)` — the registered dispatch the model reaches — not the helpers underneath,
per the §14 rule that now has three entries. Both assert schema and dispatch map agree
(17 = 17) and that a tool exception becomes an `{"error": ...}` result rather than a 500.

The properties that carry the weight: difficulty cannot collapse to one number; the lambdas are
labelled as products; market-priced and pure-DC are distinguished; a runaway is flagged in
explain's own words; past-horizon is null-with-a-reason; a double is two fixtures; the forward
price fields never reach the payload; and the selling rule is the shared function.

---

## 8. Three suite failures, diagnosed before being changed

All three passed in isolation and failed in the full run, which is the signature of an
ordering problem rather than a defect. Diagnosed first, per the standing rule that a red
suite stops being read.

**(1) `test_the_prompt_tells_the_agent_to_lead_with_it` — a TEST that was too strict.**
It asserted that *exactly one* line of the system prompt contains `` `runaway` ``. The new
`get_fixtures` rule legitimately mentions one too, so the count became 2. The rule is not
wrong; the assertion was. Now selected by what only the quantiles rule says (`P10 is
unusable`) rather than by a count that any later tool invalidates. **A count is a brittle way
to identify a thing** — it asserts something about the rest of the file, not about the thing.

**(2) and (3) `test_the_agent_entry_point_is_registered_and_dispatches` — a TEST fault from
`importlib.reload`.** Reproduced deliberately with
`test_agent_prompt.py test_backup_b2.py test_fixtures_tool.py test_prices_tool.py`:

```
AssertionError: assert <function get_fixtures at 0x...45C0>
                    is <function get_fixtures at 0x...C460>
```

Two objects, same function. `test_agent_prompt` reloads `agent` (whose dispatch map then holds
model_tools' functions *as they were*), and `test_backup_b2` and `test_tool_surface_check`
later reload `model_tools` (making new objects). Alphabetically `test_agent_prompt` runs
first, so by the time the new tests run the map is one incarnation behind. Nothing about the
product is wrong — the agent process never reloads modules.

Identity was the obvious assertion and the wrong one. The property worth pinning is that the
map points at the **real tool in `model_tools`**, not a stub or a lambda, and
`(fn.__module__, fn.__qualname__)` says exactly that and survives reloading.

**The pattern, and why it belongs with the §14 entries.** Those say a check can be real,
measured and aimed one layer to the side of the thing that matters. This is the same shape in
a test: `is` over-specifies. It pins an *incidental* property (object identity) that happens
to imply the one I cared about (the map is not stubbed), and the incidental property is the
one the environment breaks. **Assert the property you mean, not a stronger one that implies
it** — the stronger one fails for reasons that have nothing to do with the thing under test,
and a test that fails for unrelated reasons is how a suite stops being read.

---

## 9. The live check caught a real one, first time out

Deployed `e812edd`, ran the dead-on-arrival check against the real server, and the very
first assertion failed:

```
[FAIL] no error -- tool get_fixtures failed:
       UndefinedColumn: column "odds_horizon_gws" does not exist
```

**Every `get_fixtures` call raised.** The tool was completely non-functional in production
while 37 tests passed and the suite was green.

`odds_horizon_gws` is a **frame** column. It is not in `db_write.PRED_INSERT_COLS` and has
therefore never existed on `model_predictions`. I wrote a hardcoded eight-column `SELECT`
without checking it against the insert list — the list I had read earlier in the same
session, on screen, while checking something else.

### Why the tests could not catch it

The same reason as yesterday, which is what makes this a pattern rather than an accident.
The unit tests hand `build()` a dict in the shape the function wants. The live read produces
a different shape, and the gap between those two shapes is precisely where this class of
defect lives. **Testing a pure function with a hand-made input tests the function, not the
read.**

### The fix, on the read side

`FIXTURE_REQUIRED_COLS` / `FIXTURE_OPTIONAL_COLS` with `_table_columns` — the tolerant
pattern the 2026-09-18 incident mandated, which I had already built and then did not use one
file over. An absent optional column is dropped from the SQL; an absent *required* column is
an explicit error naming it, because an empty fixture list reads as "no games" and a broken
schema must not look like that.

The absence is harmless to the meaning: `explain.market_priced` defaults the horizon to 0, so
step 0 reads market-priced and steps 1–5 read pure Dixon-Coles, which is the truth this season
and the same default `breakdown()` already applies. The payload now says `how_known:
"...derived, not read"` rather than implying a column we do not store.

Four tests added, including one asserting every required column is in `PRED_INSERT_COLS` and
one asserting the generated SQL names nothing the live schema lacks.

### Three times in three days, and what that now means

| date | the check that passed | the path that was broken |
|---|---|---|
| 09-17 | curl proved every endpoint answered | the browser UI rendered `undefined` |
| 09-18 | `add_quantiles` measured clean over the frame | `get_prediction` raised on every call |
| 09-19 | 37 tests over pure functions | `get_fixtures` raised on every call |

Yesterday's entry generalised it as *"check that a new signal can SEE its inputs on the live
read path."* That was right and it was not enough, because I then wrote a new read and did
not apply it. The rule needs a mechanical trigger rather than a principle to remember:

**Any new SQL `SELECT` against `model_predictions` must be checked against
`db_write.PRED_INSERT_COLS` in a test, at the time it is written.** Not "verify on the live
path afterwards" — that is what caught it, and catching it after deploy is the expensive way.
A test comparing the two lists costs nothing and fires before the push.

The deploy-then-check discipline is what turned a silent production outage into a ten-minute
fix, so it stays. But it is the second line, not the first.

---

## 10. Live confirmation after the fix (e48c961, 2026-09-19 08:0xZ)

Same check, re-run on the server. **ALL CHECKS PASSED.**

`get_fixtures("Newcastle", horizon=5)`, run 15, calendar age 85.6 h, 20/20 team names:

| gw | | opponent | attacking | clean sheet | priced off | |
|---|---|---|---|---|---|---|
| 5 | H | Hull City | 1.874 easy | 0.377 easy | **MARKET** | |
| 6 | A | Coventry City | 2.237 easy | 0.999 easy | pure-DC | **RUNAWAY** |
| 7 | H | Aston Villa | 1.698 avg | 0.254 avg | pure-DC | |
| 8 | A | Crystal Palace | 1.563 avg | 0.254 avg | pure-DC | |
| 9 | H | Everton | 1.548 avg | 0.338 avg | pure-DC | |

Everything the design claimed, visible in one table: opponents named from the calendar, two
difficulty numbers that move independently, GW5 market-priced against GW6–9 pure Dixon-Coles,
and the Coventry fixture flagged. Across all 20 clubs: **8 runaway fixtures, 92 clean** — the
flag discriminates rather than firing everywhere. The reverse side reads correctly too:
Coventry vs Newcastle shows `opp_lambda 2.23659`, clean sheet 0.1068, flagged for their *own*
attack.

`get_price_movements(window_days=14)`: observed 2026-09-04T17:30Z → 2026-09-18T17:30Z, 27
snapshots, **largest gap 183.0 hours** — 7.6 days, the burst-sampling finding confirmed in
live data rather than inferred from filenames. 201 movers. No forward field in the payload.
Squad paid 99.1, sells for 99.0; every `sells_for` matches `squad_state.sell_price`, and 6
risen players all sell below market (De Cuyper paid 4.7, now 4.9, sells 4.8).

### CORRECTION to §5: the runtime estimate was too low

§5 projected ~60 ms for `get_fixtures` by summing components (30 ms SQL + 14 ms parquet +
"shaping"). Measured end to end through `agent.call_tool`, best of 3:

| | estimated | **measured** |
|---|---|---|
| `get_fixtures`, one club | ~60 ms | **198 ms** |
| `get_fixtures`, all 20 | — | **295 ms** |
| `get_price_movements` | ~73 ms | **103 ms** |

The estimate omitted the shaping it waved at: the read pulls **all** ~3,954 prediction rows
for the run, not the 120 team-gw rows it ends up using, and then builds the full calendar
dict. Summing the parts I had timed undercounted by 3×, which is the ordinary failure of
component estimates — the part nobody times is the part that costs.

The conclusion is unchanged: both stay on demand, neither goes in a build, and 300 ms inside
a chat turn is not felt. If the fixture read ever needs to be faster, the obvious move is to
push the per-(team, gw) collapse into SQL with a `DISTINCT ON` rather than pulling every
player row and deduping in Python.
