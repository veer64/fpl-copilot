# Squad state built — 2026-09-12 (master plan §1.4 / §5.4, steps 1–4)

Written 2026-09-12 ~05:50Z. The user asked for the squad-state build in five
steps with a stop after each; steps 1–4 are done, proven on the server, and
deployed. **Step 5 (wiring the six-week transfer MIP to read squad state) was
NOT started** — the user asked for a conversation first.

The decision this rests on, taken by the user and not re-litigated here: the
squad is **hypothetical**, not a real FPL entry. Cheaper build; no track record.

## 0. State at a glance

| thing | state |
|---|---|
| Table | `squad_versions` on the server database, append-only by construction (trigger + one-active partial unique index). Schema of record: `squad_store.DDL`, sha256 `c53561a6…` pinned by `Tests/test_squad_store_writes.py::test_ddl_is_stable`. |
| Rows | ONE: version_id 1, user 1, 2026-27, GW4, is_active, supersedes NULL — the seed. Sequence at 3 (two previews consumed values; ids may have gaps). |
| Seed | run_id 4's fifteen (GW3 production solve, baseline, e3d98afdd) priced at players_live 2026-09-11 21:42:31Z: cost 996, bank 4, one free transfer, zero points, Haaland (C), Foden (V). Provenance in the document says hypothetical, not backdated. |
| Tools | `get_my_squad` (step 3) and `set_my_squad` (step 4) in `model_tools.py`, registered in `agent.py` (ten tools now). |
| Tests | `Tests/test_squad_store.py` (27) + `Tests/test_squad_store_writes.py` (19), pure Python, no DB/network. Suite **296 passed, 0 skipped** before each push. |
| Commits | bf70a21 (step 1), d026058 + 3b39ad0 (step 2), 533c7e5 (step 3), c29d4d9 (step 4), + this log. All pushed; server HEAD verified = laptop HEAD after each deploy; /health `git_sha` matched; api container restarted each time. |
| Model path | untouched. Nothing under `squad/assembly, minutes, defensive, dixon_coles, attacking_rates` or the walkforward path changed. `squad/squad_state.py` was REUSED, not modified. |

## 1. Step 1 — the table (commit bf70a21)

**What ran.** `squad_store.py --print-ddl` piped through `psql -v ON_ERROR_STOP=1`
on the server (2153 bytes; the applied SQL is the module's own string). Then a
guard probe inside one transaction, rolled back at the end.

**Schema** (two columns beyond the plan's five, both on the plan's own "costs
nothing now" argument):

```
squad_versions(version_id serial PK, user_id int not null default 1,
               season text not null, gw int not null,
               created_at timestamptz not null default now(),
               squad_json jsonb not null, is_active bool not null default true,
               supersedes int references squad_versions(version_id), note text)
ux_squad_versions_one_active  UNIQUE (user_id) WHERE is_active
trg_squad_versions_append_only BEFORE UPDATE OR DELETE  -> squad_versions_append_only()
```

`season`: gw alone is ambiguous across seasons. `supersedes`: a version names
the row it replaced, so the chain is explicit rather than inferred from time.

**Append-only is enforced, not assumed.** The trigger refuses DELETE; refuses
any UPDATE that changes a column other than `is_active`; refuses turning
`is_active` back on (undo = a new row copying an earlier document, so history
stays linear). The partial unique index allows at most one active row per user,
so a read is unambiguous or it raises.

**Guard probe results** (inserted a probe row, then, under savepoints):
update of gw → refused; DELETE → refused; is_active true→false → allowed;
re-activate → refused; second active row → refused by the index. ROLLBACK;
row count 0 afterwards.

## 2. Step 2 — the seed (commits d026058, 3b39ad0)

**Generated from repo code, nothing typed twice.** `eval/seed_squad_gw4.py`
holds the fifteen as a spec table, builds the document through
`squad_state.initial_squad_from_team` (purchase_price = price paid; bank =
1000 − spent) and `squad_store.document` (validation), and EMITS the SQL that
ran on the server: one transaction whose `DO` block refuses unless every
document row still matches run 4's baseline pick (element, position, role,
bench order) AND its purchase_price equals the CURRENT players_live price,
and unless the table is empty; then `ALTER SEQUENCE … RESTART WITH 1`
(the guard probe had consumed values on the empty table); then the INSERT.

**Asserts before trusting it** (printed from the generated document, all
PASS): 15 players; cost 996; bank 4; cost + bank 1000; 2/5/5/3; no club over
3 (Brentford 3, Man City 3); exactly one CAPTAIN and one VICE; bench orders
[1,2,3,4]; unique elements; free_transfers 1, total_points 0. "Every element
resolves in players_live" was the server-side cross-check (15/15 joined on
element AND price).

**First apply failed, cleanly.** The SQL file was written in Windows cp1252
(the í in Kelleher) and psql rejected it at the first statement:
`invalid byte sequence for encoding "UTF8"`. Nothing was inserted (count 0,
sequence untouched). Fix 3b39ad0: the generator reconfigures stdout to UTF-8
whatever the console says. Re-applied: `INSERT 0 1`, version_id 1, created
05:24:53Z.

**Read-back.** `squad_json::text` from the server, parsed, compared to the
generated document: **identical, field for field** (accents intact).

## 3. Step 3 — `get_my_squad` (commit 533c7e5)

**Design, bottom-up.**
- `squad_store.read_active(user_id)` → the one active row with `squad_json`
  parsed and re-validated, or `SquadStateError` on no active row, more than
  one (the index makes this impossible, checked anyway), or an illegal stored
  document. A missing table raises psycopg2's UndefinedTable. Nothing falls
  back to a free pick.
- `squad_store.summary(record, prices)` → identity, the fifteen with purchase
  price, current price (players_live) and **sell price** via
  `SquadState.element_sell_price` (the one implementation), totals (purchase
  cost, bank, sell value, budget if all sold), free transfers, points,
  `prices_missing_for`, and the raw document.
- `model_tools.get_my_squad(user_id=1)`: converts ONLY `SquadStateError` into
  `{"error": …}` — the convention the other eight tools use so the model
  reports the condition — and never substitutes `get_picks`. Deviation from
  the prompt's literal "raises": a raise through `agent.run_agent` is a 500 to
  the user with no explanation; the error dict is loud to the model, which
  says so. The raising form exists for code paths (the MIP) that must not
  proceed without state.

**Round-trip proof, on the server after the deploy** (image at 533c7e5,
`docker compose run … fpl-scheduler`): `get_my_squad()["squad_json"]` vs the
generated seed document: **equal; diff empty**. Presentation read 99.6 /
0.4 / sell value 99.6 / budget 100.0, captain Haaland, vice Foden, bench
Leno–Kayode–Gómez–Slater.

**Agent proof.** `POST /chat "What is my squad right now? …"` → the container
log shows `[calling tool: get_my_squad({})]`; the answer listed the fifteen,
C/V, £0.4m bank, 1 FT. Conversation reset afterwards.

## 4. Step 4 — `set_my_squad` (commit c29d4d9)

**The real thinking: the caller never supplies money.** The tool takes the
fifteen after the change plus captain, vice and the four bench ids in order.
`squad_store.plan_change` (pure) diffs against the active fifteen, pairs outs
with ins by position, and applies the set through
`SquadState.make_transfers` — which values each outgoing player by
`squad_state.sell_price` (purchase + half the rise rounded down; falls in
full), prices each incoming player at his CURRENT players_live price, pools the
money the way FPL settles a set, and refuses if the bank would go negative.
Retained players keep their purchase price; incoming players' purchase_price
is what was paid now. Free transfers are consumed first (`spend_transfers`);
transfers beyond them are hits at `scoring.HIT_COST` (4), **reported, not
deducted from total_points** (no process scores the hypothetical squad yet —
open item below).

**Money conservation, asserted twice after every move** (RuntimeError if
violated — a bug, not a bad request): `bank_after == bank_before + proceeds −
purchases` exactly; wealth (sell value at current prices + bank) unchanged.
The Hypothesis property test re-asserts the second over random price drifts
and purchase prices.

**Refusals, never clamps** (ValueError with the reason → `{"error":
"refused: …", "refused": true}`): not 15 distinct ids; unknown/unpriced
element; position shape broken (out/in counts by position); captain or vice
on the bench, or equal; not four distinct bench ids; gw earlier than the
active version's; unaffordable. The active record is not mutated by planning
(tested).

**The write** (`squad_store.write_version`): one transaction — UPDATE the old
row's `is_active` to false (the only update the trigger allows) WHERE it is
still active, refuse with `SquadStateError` if 0 rows flipped (superseded
meanwhile), INSERT the new row with `supersedes` = old version_id, RETURNING.
**`confirm=False` (the tool's default) runs the whole thing and rolls back**:
a preview through the real path, trigger included. The tool description tells
the model to preview first and confirm only when the user says so — FPL's own
confirm step.

**Server proof after the deploy** (image at c29d4d9), all previews:
1. Slater (290, bought 4.5) → Ömür (292, 4.9): sold 4.5, bought 4.9, bank
   0.4 → **0.0**, FT 1 → 0, hits 0; would be version 2 superseding 1; bench
   4 = Ömür at purchase 4.9. Rolled back.
2. Roles only (Isak C, Haaland V): 0 transfers, bank 0.4, FT 1; would be
   version 3. Rolled back.
3. Slater → Bruno Fernandes (12.0): `refused: transfer set unaffordable: bank
   4 + 45 − 120 = −71`.
4. Captain on the bench: refused.
5. Slater (MID) → Matty Cash (DEF): refused, `{'DEF': (0, 1), 'MID': (1, 0)}`.
6. gw 3 with active gw 4: refused.
After: version 1 active, 1 row in the table, document unchanged
(`UNCHANGED: True`), sequence last_value 3.

## 5. Coverage

`squad_store.py` had zero tests at step 1. Now: 46 pure-Python tests across
two files — the document validator against deliberately broken squads, the
SquadState round trip, the sell-price and money-conservation maths through
`squad_state.py` (incl. a Hypothesis property), the reads' three raising
paths through a fake connection, the write path through a fake connection
(flip then insert, commit only on confirm, superseded-meanwhile refused,
validate before touching the DB), the seed's legality and cost, and the DDL
sha256 pin. What the laptop cannot test — the trigger and the index — was
exercised on the server (§1, §4) and is recorded here.

## 6. Choices made that the prompt did not spell out

- `version_id`, `season`, `supersedes` columns added (§1).
- `set_my_squad` takes ids + roles, not a full document; money is derived
  (§4). The plan's `set_my_squad(squad)` would have had the model state
  purchase prices and a bank — exactly the values that must not be caller-
  supplied.
- Preview by default (`confirm=False` → rolled back). Consequence: sequence
  gaps in version_id.
- Tool errors are `{"error": …}` dicts, not raises, at the tool boundary (§3).
- Existing tool convention kept (JSON schema in `agent.py`, no Pydantic) for
  consistency with the other eight tools.
- Hits are reported, not deducted from `total_points`.

## 7. Open items (for the step-5 conversation; none started)

1. **Free-transfer roll-forward.** `SquadState.end_gameweek` (+1 per
   gameweek, cap 5) is called by nobody. `set_my_squad` consumes FTs; nothing
   grants the next one. The MIP needs the FT count at the deadline.
2. **Points accounting.** `total_points` is 0 and nothing scores the
   hypothetical squad; hits are recorded in provenance only.
3. **gw semantics.** A version's `gw` is the gameweek it is set for; the
   tool defaults to the next deadline's gw. Multiple versions per gw are
   allowed (each supersedes the last).
4. **MIP wiring** (`transfer_mip.build_and_solve(pool_by_gw, current_squad,
   purchase_prices, bank, free_transfers, …)`, `DEFAULT_HORIZON=6`,
   `DEFAULT_DECAY=0.45`, `HIT_COST=4`): `squad_store.to_state(doc)` already
   yields the `SquadState` the simulator passes it. The conversation needed:
   where it runs (api `optimise()` on the volume frame vs. the deadline
   runner), what it writes (`model_transfers` is created and empty), and
   whether its plan auto-applies (no — set_my_squad with confirm is the
   user's act).
5. A `model_tools` ↔ `db_write` connection helper is now a third copy of the
   same five lines (`db_write.connect`, `model_tools._conn`); harmless,
   noted.

## 8. Operational notes from this session

- GW4 deadline 12:30Z; dispatcher fires 11:00Z. All deploys landed 05:32Z,
  05:44Z and the log push after — hours clear of the 10:30–13:00Z no-touch
  window and the 06:17Z ingest tick. The api container restarted on each
  deploy; Postgres was not recreated.
- Two proof files were written to the volume and removed; nothing else on
  the volume was touched. `squad_versions` lives in Postgres (fpl_pgdata),
  not on the model volume.
- Windows console encoding bit once (§2); every emitter now writes UTF-8.
- Long heredocs fail in the Bash tool; files were written with the Write tool
  and piped over ssh as stdin.

---

## 9. Step 5a — the roles contract (2026-09-12, commit 27d3e7f)

**The milestone first.** Run 5, GW4, built unattended 2026-09-12 11:01:01Z on
deployed code 48e7303 against the server-ingested volume; strict build
PASSED, 3,936 rows; /health ok. First solo run on baseline. (`started_at` is
NULL for run 5 because `eval/run_live_deadline.py` passes `started_at=None`
on its success path — a pre-existing runner gap, not a GW4 anomaly; the
2026-09-11 handoff's "started_at filled" check could never pass.)

**The bug, confirmed from the api log.** The GW4 squad question produced ONE
`get_my_squad` call and FIFTEEN `get_prediction(gw=4)` calls. The roles came
from version 1 (written 05:24:53Z, copied from run 4's GW3 solve); every
prediction came from run 5 (11:01Z). Joined on the seed's roles at run 5's
numbers: Collins (DEF) starting at 2.46, Gómez (MID) on the bench at 4.04,
four defenders in the XI, and the recorded vice Foden (3.77) over Gakpo
(4.65). Both halves were correct; the join was wrong, and it was shown as
advice. The user's estimate of ~1.6 points left on the table is exactly right
(1.58, below).

**The contract.** The roles stored with a version are the roles AS OF that
version's creation, and nothing more — a record, not a recommendation.

1. *Labelled wherever they surface.* `squad_store.roles_status(record,
   latest_run)` → `STALE` if a SUCCESS model run finished after the version
   was recorded or the latest run is for a later gw (either alone suffices);
   `current` otherwise; `UNKNOWN` with no run. `summary()` now returns
   `recorded_captain / recorded_vice / recorded_xi / recorded_bench_in_order`
   and a `roles` block (`as_of_gw`, `recorded_at`, `latest_run`, `status`,
   `warning` naming both timestamps, `meaning`). The unlabelled `captain /
   vice / xi / bench_in_order` keys no longer exist on get_my_squad, so a GW3
   role cannot be read as GW4 advice by accident. The tool description tells
   the model the roles are a record and to say so when STALE.
2. *Computed, not read.* `squad_store.xi_over_fifteen(pool, state, prices)`:
   the same single-gameweek MIP as `optimise()` (gapRel=0), locked to and
   restricted to the owned fifteen; owned players absent from the frame are
   injected at e_points 0 through `simulator._adjusted_pool` (the production
   blank-week rule) and returned as `missing` so the gap is visible.
   `compare_roles` lists every role that differs from the recorded ones and
   the expected XI points of each (XI + captain again, the objective the
   weekly decision is ranked on).

**Own tool, not a mode.** `get_my_xi` is separate from `get_my_squad` because
they answer different questions from different sources with different failure
modes: one is a DB read of state (fails when no version is active), the other
a solve over the model frame on the volume (fails when no frame exists) with
run/frame provenance. A mode flag would blur which one the model is asking
and which failure it got. `get_my_xi` returns XI, captain, vice, bench order,
`predicted_xi_points`, the comparison against the recorded roles, and
`adopt_with` — the exact `set_my_squad` arguments to record the XI (still
preview-first; nothing is written by get_my_xi). `_load_pool()` is shared
with `optimise()`.

**What a stale-gameweek response looks like** (server, 13:25Z, image
27d3e7f, run 5 / version 1):

```
get_my_squad.roles = {as_of_gw: 4, recorded_at: 2026-09-12 05:24:53Z,
  latest_run: {run_id: 5, gw: 4, built_at: 2026-09-12 11:01:01Z},
  status: "STALE",
  warning: "these roles were recorded at 05:24:53Z for GW4; model run 5 for
    GW4 was built at 11:01:01Z, AFTER that. They are a record of what was
    set, not a recommendation for GW4 -- call get_my_xi for that."}
get_my_xi = {gw: 4, run_id: 5, model_version: 48e7303c6/baseline,
  solve_seconds: 0.5, captain: Haaland, vice: Gakpo,
  XI: Haaland(C) 5.89, Gakpo(V) 4.65, Mbeumo 4.61, Isak 4.46, De Cuyper 4.43,
      Havertz 4.33, Calafiori 4.26, Guéhi 4.20, Gómez 4.04, Foden 3.77,
      Kelleher 3.39  (3 DEF),
  bench: 1 Leno, 2 Kayode, 3 Collins, 4 Slater,
  recorded_roles: {differ: true, changes: [Gakpo start→VICE, Gómez bench 3→
      start, Foden VICE→start, Collins start→bench 3],
      recorded_xi_points: 52.35, optimal_xi_points: 53.92,
      expected_gain_vs_recorded: 1.58},
  note_deadline: "this frame is for GW4; the next deadline is GW5 at
      2026-09-18 17:30Z and its frame lands when the pipeline runs at T-90"}
```

The deadline note is the other real condition surfaced: after 12:30Z the
frame on the volume is GW4's until the GW5 run at T-90, so "this week's XI"
between deadlines is the XI for a gameweek already under way.

**Tests.** `Tests/test_squad_store_xi.py` (11): roles STALE by time and by gw,
current, UNKNOWN, Postgres-style strings; summary carries no unlabelled role
keys; a real solve on a synthetic fifteen with the GW4 shape benches the
fourth defender for the better midfielder with gain 1.58 and the bench GK at
slot 1; adopted roles compare as identical; a missing player is injected at
0 and reported; the bench-order convention mapping (scoring 0..3 → document
1..4). Suite **307 passed, 0 skipped**. Model path untouched.

**Deployed and verified.** Push 13:24Z → /health `git_sha 27d3e7fa7`, ok,
zero reasons at 13:24:57Z; api container restarted; the proofs above ran
inside the deployed image. Outside the deadline window (deadline 12:30Z,
window closed 13:00Z) and clear of the 18:17Z ingest tick.

**Not done, by instruction:** 5b (free-transfer roll-forward, scoring the
squad and deducting hits, where the six-week MIP runs and what it writes) and
5c (wiring the MIP) wait for the conversation.

---

## 10. Step 5b — three decisions PROPOSED (2026-09-12 ~13:40Z), nothing implemented

Options and a recommendation for each, as asked. Facts they rest on: the
simulator already rolls free transfers (+1 per gameweek, cap
`MAX_FREE_TRANSFERS = 5`, `SquadState.end_gameweek`) and carries the bank
through a wildcard / free hit untouched (`simulator.py` ~821–833);
`scoring.score_gameweek` is pure and already models autosubs (bench order,
bench GK slot), the captain ×2 with vice fallback, Triple Captain, and
deducts `max(0, transfers − free) × HIT_COST`; `transfer_mip` imports
`sell_price` from `squad_state` (line 403) so its sell valuations agree by
construction; the frame on the volume holds cutoff 4 with gws 4–9, exactly
the six pools `decide_gameweek_mip` slices with `gw_slice(cutoff=gw)`; the
master `fpl_api_2026_27` carries element, GW, fixture, minutes, total_points.

### D1 — free transfers: recommend LAZY DERIVATION
`ft(G) = min(5, ft_after_recorded + (G − version.gw))`, G = the next
deadline's gameweek (bootstrap, cached; unavailable → raise). Every version
already stores its own (gw, free_transfers_after), so no history is
reconstructed and every transfer is attributed to a gameweek by
construction (set_my_squad takes gw, default next deadline). Scheduled
alternatives (ingest: wrong at the deadline if it retried late; deadline
runner: wrong all week until T-90) own the "job that did not run" failure —
a silently wrong count = wrong hit maths. Lazy owns "version.gw must mean
the deadline it was set for" — tighten set_my_squad to refuse gw < the next
deadline's gw. Wildcard: a version `chip: "wildcard"` spends 0 and leaves
the bank intact (FPL since 2024-25; the simulator's rule). Free Hit needs a
restoring follow-up version (snapshot/restore exist) — out of scope now.
Latent bug this fixes: plan_change spends the STORED count, so a GW5 move
on the GW4 seed would see 1 FT, not 2.

### D2 — scoring + hits: recommend a WEEKLY-INGEST STEP writing `squad_scores`
Where: `run_weekly_ingest.run_chain` after the master lands for gw N
(data_checked-gated already; runs in the scheduler image with DB env;
failure = ingest FAILED → /health degraded, the existing loud path). Which
squad: the latest version with created_at < deadline_N and gw ≤ N. How:
`scoring.score_gameweek(squad, actuals, transfers_made, free_transfers)` —
the simulator's own scorer, so autosubs ARE modelled (not ignored), captain
×2 with vice fallback, doubles pre-aggregated per element; bench order
mapped document 1..4 → scoring 0..3. transfers_made / free from the gw-N
versions (Decision 1's derivation); the version provenance's `hits` must
agree — asserted. What it writes: a NEW append-only table `squad_scores`
(user, season, gw, version_id, points_net, points_raw, hit, captain_bonus,
doubled, doubled_role, final_xi, subs_made, bench_points, master_rows_hash,
scored_at, git) with a unique (user, season, gw, master_rows_hash); NOT a
new squad version (versions are decisions, scores are outcomes; flipping
is_active for a clock event breaks the one-active meaning). Reads report
`total_points` = Σ points_net and label the document's field as recorded.
HITS: DEDUCT. score_gameweek does it natively; a scored squad that ignores
−4 overstates by 4 per hit — the constant-for-a-missing-piece pattern —
and is not worth having. Chips (TC/BB) need a `chip` field on versions:
later. First scoreable gameweek: GW4 (~Tue 2026-09-15).

### D3 — the six-week MIP: recommend SYNC NOW, precompute at T-90 next, streaming = agent v2
A. Synchronous tool (~22 s + the model turn, silent wait): required anyway
for locks/bans and post-T-90 squad changes; single user; no new dependency.
B. Precompute in the deadline runner (frames already in memory; +22 s;
own non-fatal status section) → the tool serves the stored proposal when
the active version is unchanged, else re-solves and says so. This is where
the track record comes from. C. Async + streaming (plan §5.2 phase 2 /
§9.5) — an agent-v2 dependency, named, not absorbed. Between deadlines the
volume frame is the LAST deadline's (cutoff k); a plan for k+1 must drop
gw k from the pools and label its predictions "as of cutoff k". PERSIST
every proposal (append-only, like predictions): header table
`model_transfer_plans` (proposal_id, run_id, config, squad_version_id,
user, gw, horizon, decay, hit_bar, locked, banned, source chat|deadline_run,
objective, hits, solve_seconds, status, created_at, git) + `model_transfers`
re-created at grain (proposal_id, horizon_step, gw, element_out,
element_in, sold_for, bought_for) — it is empty and unreferenced, so
replace rather than ALTER. A hold = header with no transfer rows.

### Loose ends (to do inside 5c)
- `run_live_deadline.py` passes `started_at=None`: record the runner's
  start time and pass it (runner file, not the model path).
- MIP vs squad_state valuations agree by construction; the 5c tool will
  still assert equality on all fifteen and report the moved prices.

---

## 11. Step 5c part 1 — free transfers derived lazily (2026-09-12, commit d5b24d9)

Decision 1 accepted as Option B and implemented. Order of work as instructed:
this first (smallest; `plan_change` was wrong until it landed), scoring next,
the MIP last.

**The rule, in code.** `squad_store.free_transfers_at(record, gw) =
min(MAX_FREE_TRANSFERS, recorded + (gw − version.gw))`. A version's recorded
count is the count left AFTER its own transfers as of the deadline it was set
for; FPL banks one per gameweek to five (`squad_state.end_gameweek`'s rule).
Nothing is scheduled and nothing is stored beyond what versions already hold.
Raises for a gw earlier than the version's.

**"Now".** `model_tools._current_gw()` = the next deadline's gameweek from
the bootstrap (cached 10 min). Unreachable → `get_my_squad` reports
`free_transfers_now: null` with `free_transfers_error` naming the cause, and
`set_my_squad` refuses. Never a guess. `summary()` returns
`free_transfers_recorded` (+ `_as_of_gw`) and `free_transfers_now` (+
`_as_of_gw`); the bare `free_transfers` key is gone so nothing quotes the
stale count.

**The write is tightened.** `plan_change` requires `next_deadline_gw` and
refuses any other gw: earlier ("deadline has passed"), later ("beyond the
next deadline … so free transfers stay attributable"). It spends the DERIVED
count and reports recorded / as-of / rolled-forward / before / used / after.
The latent bug is closed: a GW5 move on the GW4 seed now sees 2, not 1.

**`get_my_xi` follows the stale-by-one rule.** Between deadlines it solves
the NEXT deadline's gameweek from the frame's cutoff, labels it
(`predictions_as_of_cutoff_gw`, `stale_by_gameweeks`, `note_stale`) and its
`adopt_with.gw` is the next deadline's, so it stays writable under the
tightened rule. `_load_pool(gw)` slices any gameweek inside the horizon at
the frame's cutoff; `optimise()` / `get_best_squad` still solve the frame's
own step 0 (unchanged; noted as a follow-up).

**Proof on the server** (image d5b24d9, 13:52Z, all previews rolled back):
- current gw 5 (deadline 2026-09-18 17:30Z). `get_my_squad`:
  `free_transfers_recorded 1 (as of GW4)`, `free_transfers_now 2 (as of
  GW5)`, no bare key.
- Preview GW5, two transfers (Slater→Ömür, Gómez→Tóth): recorded 1, rolled
  forward 1, before **2**, used 2, after 0, **hits 0**, bank 0.4→0.0.
- Preview GW5, one transfer: before 2, after 1, hits 0.
- gw=4 → `refused: GW4's deadline has passed; a squad can only be set for
  the next deadline, GW5`. gw=6 → `refused: GW6 is beyond the next deadline
  (GW5) …`.
- `get_my_xi`: gw 5, predictions as of cutoff 4, stale by 1, note_stale
  names the frame's build time and the GW5 deadline; adopt_with.gw 5.
  (The GW5 view from cutoff 4 benches Isak at 3.0 and starts Leno over
  Kelleher, 4.04 vs 3.93 — the model's view, labelled as one gameweek stale.)
- Active version 1 unchanged; one row in the table; sequence at 5.

**Tests.** 6 new in `Tests/test_squad_store_writes.py` (rolls one per gw
and caps at 5; before-the-version is an error; the GW5-on-GW4 case sees 2
and three transfers cost one hit; only the next deadline's gw is accepted;
a no-change version at a later gw carries the rolled count; summary reports
both counts and the unavailable case). Suite **313 passed, 0 skipped**,
parity family and `test_asof_reconstruction` included.

**Deployed and verified.** Push 13:51Z → /health `git_sha d5b24d9a4`, ok,
zero reasons at 13:51:54Z; api container restarted; proofs ran inside the
deployed image. Clear of the 18:17Z ingest tick; GW5 deadline is Friday.

**Correction to the 5c brief, for the record.** The hard-coded
`started_at=None` is in `eval/run_live_deadline.py` (the runner), not
`squad/live_deadline.py` (the parity-gated entry point). Fixing it will not
edit the entry point; the parity and as-of families run on every push
regardless.

**Deferred, unchanged:** chips (a wildcard week would need a `chip` field
so the version spends nothing; a free hit needs a restoring version).

---

## 12. Option B memory measurement — build + six-week MIP in one process (2026-09-12 18:17Z)

**Why measured, not wired.** Option B (the MIP inside the T-90 runner) would
share a process with a build that peaks ~1.59 GB on a 3.9 GB droplet with NO
swap; an overrun is an OOM kill. Nobody had measured them together. This is
the number; nothing was wired.

**Method.** Inside the scheduler image on the server (`docker compose run
--rm --no-deps`, no memory limit; the api at 149 MB and Postgres at 44 MB
running alongside; host 800 MB used, 3,115 MB available before), one
process reproduced today's T-90 build for GW4 exactly as the runner does —
`live_deadline.build_deadline_frame("2026-27", 4, strict=True,
config="baseline", horizon=6)` → stage prices and frame (to /tmp, never the
volume) → `load_season` → `gw_slice` → free-pick `optimize_squad` — then
appended the six-week MIP for the ACTIVE squad via
`simulator.decide_gameweek_mip` (H=6, decay 0.45, HiGHS in-process) in the
SAME process. A second, fresh process ran the MIP alone from the volume
frame. Checkpoints read `ru_maxrss` (process anonymous high-water mark) and
the container cgroup's `memory.current` / `memory.peak` / `memory.stat anon`
(every process in the container; current/peak include page cache). Run at
18:17:40–18:18:56Z, right after the 18:17Z ingest tick (NOTHING-NEW) and
five days clear of the GW5 deadline.

**Build + MIP, one process** (t, ru_maxrss, cgroup current / peak / anon, MB):

| checkpoint | t s | ru_maxrss | cg current | cg peak | cg anon |
|---|---|---|---|---|---|
| interpreter | 0.0 | 29 | 15 | 15 | 14 |
| imports done | 8.6 | 210 | 198 | 198 | 141 |
| strict build done (3,936 rows) | 47.2 | **1,569** | 1,056 | **1,511** | 1,020 |
| prices + frame staged, load_season | 47.4 | 1,569 | 751 | 1,511 | 714 |
| free-pick XI solve | 49.0 | 1,569 | 751 | 1,511 | 714 |
| six-week MIP done (8.7 s, 1 transfer, H=6) | 57.7 | 1,569 | 762 | 1,511 | **726** |

**MIP alone, fresh process:** imports 128 → frame loaded 154 → MIP done
`ru_maxrss` **330 MB** (8.8 s), cgroup peak 287, anon 230. (The 416 MB
reference was a different measurement; 330 here with HiGHS.)

**Reading.** The peak is the BUILD's: 1,569 MB process high-water mark (1,511
cgroup), reached inside `build_deadline_frame`. By the time the frame is
returned the working set has dropped to ~714 MB anon, and the MIP appended
there adds **+12 MB anon** (714 → 726) and does not move the high-water mark
at all. The MIP's own peak (330 MB alone) is not additive to the build's
because the two never coincide in time — the build's intermediates are
released before the solve starts.

**Margin.** Host 3,915 MB total; ~800 MB used by everything else (host ~600,
api 149, Postgres 44). Build peak 1,569 → total ≈ 2.4 GB → **≈ 1.5 GB
headroom**. Even the impossible worst case (MIP peak coinciding with the
build peak) is 1,569 + 330 ≈ 1.9 GB → ≈ 1.2 GB headroom.

**Recommendation.** On this evidence memory does NOT block option B: appended
after the build, the MIP costs ~12 MB and ~9 s. I would put it in the T-90
runner — LATER, as its own non-fatal status section, after the frame is
written and the free-pick solve done (never in parallel with the build) —
with two guards first: (1) the runner should log its own `ru_maxrss` in the
status file every deadline, because the 2026-27 stack grows a gameweek a
week and the 1,569 figure is one run on one day; (2) re-measure if the
build's peak ever crosses ~2.5 GB or the droplet takes on any other
resident service. Not wired in this pass, per the instruction.

**Bonus observation (not acted on).** Both processes proposed the same step-0
move for the active squad from the GW4 frame: sell Isak (379), buy element
165, 0 hits, objective 100.491 — identical objectives, so the solve is
deterministic across processes. Part 3 will surface this through the tool.

**Side effects.** None on the volume or the database: temp files under
/tmp inside the containers, removed; two helper scripts copied to /root and
removed. The build re-pulled the FPL calendar (no odds credits).
