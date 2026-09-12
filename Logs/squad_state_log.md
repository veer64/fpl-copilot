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
