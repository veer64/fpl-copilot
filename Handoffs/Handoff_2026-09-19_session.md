# Session handoff — 2026-09-18 / 2026-09-19

Covers the whole session: API hardening, alerting, backups, the hold comparison, quantiles,
the runaway flag, and `get_fixtures` / `get_price_movements`. Written so the next session can
act without re-deriving anything.

**Read this first, then verify before acting.** This document is accurate as of
2026-09-19 08:10Z. Two standing rules apply to it as much as to any other document here:
documents in this repo have twice described finished work as open, and *"verify the path the
user touches, not the path you were thinking about."* Check `git log`, the code, and
`/health` before believing any claim below.

---

## 0. Live state, verified 2026-09-19 08:08Z

| | |
|---|---|
| Server | `68.183.131.154`, DigitalOcean, **2 vCPU / 3,916 MB / swap 0** (the hostname `ubuntu-s-1vcpu-2gb-nyc1` is a stale creation-time slug — §1.8's headroom argument holds) |
| Served `git_sha` | `292ef523d` |
| Local + origin | `main` at `292ef52`, clean, `0 0` |
| `/health` | `degraded`, `db_ok: true`, **exactly 6 reasons** (5 × Coventry λ EXTREME at steps 1–5, plus the non-converged fit). Degraded is the *expected persistent* state. |
| `tool_surface` | `ok: true`, element 411, gw 7, ~64–93 ms |
| Latest run | **run 15**, GW5, kind `t10`, SUCCESS, finished 2026-09-18 17:21:29Z, 79 s |
| Next scheduled | `post_ingest:GW5`, conditional on GW5 being confirmed and ingested (ticks 00:17/06:17/12:17/18:17Z) |
| Next deadline | **GW6, 2026-10-10 10:00Z** — three weeks out, so no deadline no-touch window is near |
| Backup | SUCCESS 2026-09-19 03:43:10Z, 8.5 s, dump 2,945,276 bytes |
| Suite | **596 passed, 1 skipped**, ~8m33s on the laptop |

**Run 15 is a `t10`, and `t10` skips quantiles by design.** So no stored row currently carries
both a quantile and a runaway fixture. Anything needing stored quantiles waits for the next
`post_ingest`, `nightly`, `t90` or `t30` run.

A pending reboot has been outstanding since 2026-09-12 (linux-image-6.8.0-139, linux-base,
libc6). Safe to schedule. **Not done — deliberately.**

---

## 1. Commit ledger (newest first)

All on `main`, all pushed, all deployed except where noted.

| SHA | What |
|---|---|
| `292ef52` | verify: both tools confirmed live; runtime estimate corrected (docs only) |
| `e48c961` | **fix**: `get_fixtures` raised on every call — SELECT named a column that is never written |
| `e812edd` | feature: `get_fixtures` and `get_price_movements` |
| `9dc7f2c` | verify: runaway flag confirmed live; **correction** to `7d8081a`'s Coventry-forward claim |
| `7d8081a` | feature: runaway fixture reaches the quantiles |
| `9737ab9` | health: exercise the agent's own tool surface |
| `d534db1` | **fix**: a READ must not depend on a WRITE — every prediction call failed ~35 min |
| `aac04b7` | feature: quantiles (P10/P50/P90) |
| `c2012ef` | design: quantiles — four rulings, and a sampler bug found by closing them |
| `ffde4d0` | design: quantiles — design and measurement, nothing built |
| `2356d8d` | backup: nightly off-site pg_dump to Backblaze B2 |
| `7d3b146` | alerting: layer A live (external uptime monitor) |
| `ef25767` | log: ntfy topic rotation |
| `f25d01a` | KNOWN_ISSUES #25: second consequence (hold-vs-move bias) |
| `e974db1` | test: make the dispatcher end-to-end test hermetic |
| `610b62a` | feature: hold comparison in `propose_transfers` |
| `778a7af` | correct handoff §9.5 — Coventry fixture direction (Newcastle are AWAY) |
| `6fbf1bf` | idea: league table / team form as a tool |
| `ccb7e6d` | tests: HTML-401 branch |
| `c67c16e` | ui: chat page printed literal `undefined` on every failure |
| `acb1c38` | api: browser UI works without the secret in the repo |
| `fa1b233` | api: **close the unauthenticated endpoint** |
| `4115c95` | correct handoff §2.5 and §12.1 — described work already done |
| `8d57b62` | track the Squad State handoff as written; keep the deploy runbook out |
| `64aa116` | log: deadline-slot ungating and push were ALREADY DONE |

33 files, ~6,018 insertions.

---

## 2. The code — what exists now

### 2.1 New pure modules

"Pure" here has a specific meaning in this repo: **imports no part of the model stack**, so the
API process can answer without loading the model. `explain.py` established the pattern.

#### `quantiles.py` (290 lines)
P10/P50/P90 by Monte Carlo over the model's own component probabilities.

```
METHOD_VERSION = "mc-1"
MINUTES_SHAPES  = {"MS-1": (85.0, 35.0, 20.0), "MS-2": (80,30,15), "MS-3": (88,45,25)}
DEFAULT_SHAPE   = "MS-1"
N_DRAWS         = 20_000
TOL_FLOOR, TOL_SIGMA = 0.02, 3.0
QUANTILE_COLS   = 12 columns
```
Functions: `row_rng`, `simulate_row`, `quantiles_for_row`, `add_quantiles`, `reconciles`,
`fidelity`.

Three things to know before touching it:

1. **One minutes draw per iteration drives everything.** Every rate term conditions on the
   *realised* minutes, not `minutes_frac`, so the mean is preserved by construction while the
   variance stops being suppressed.
2. **Clean sheet and conceded are coupled through ONE team-goals draw at `cs_lambda = -ln(p_cs)`
   — NOT at `opp_lambda`.** At steps 1–5 the two are identical; **at step 0 they are different
   quantities** (`opp_lambda` is pure market, `LAM_BLEND_W = 0`; `p_cs` is the 0.2·DC/0.8·market
   blend, `CS_BLEND_W = 0.2`). Coupling on `opp_lambda` cost 0.2958 points on a step-0
   defender's `pts_cs`. This was found because a check verified on GW6 only and was generalised.
   Max residual 0.3265 → 0.1060 after the fix.
3. **MS-1 is a new assumption and is named as one.** The frame carries the *mean* of the minutes
   distribution but not its shape. "Nothing new is modelled" holds for every other component and
   not this one. Shape is scaled per row so the mean reproduces `e_minutes` exactly; the
   reconciliation is insensitive to it, the quantiles are not (P90 moves on ~2.5% of rows by up
   to 2 points across shapes; P10 0.2–0.3%).

**The reconciliation is deliberately two-part and one combined bar would be wrong.** Sampling
error must sit inside `max(0.02, 3·sd/√N)` — a flat 0.05 failed 5.7% of rows, which is a
permanent finding stream, not a tolerance. The structural (Jensen) residual is reported **with
no pass bar**: it is a *bias*, not noise (−0.0155 mean on GK/DEF, identically zero for MID/FWD),
it does not shrink with N, and a noise band can never contain a bias. **Not recentred** —
smoothing it away would delete the one thing the simulation reveals about the model itself.

#### `fixtures_tool.py` (240 lines)
```
SKELETON      = data/history/forward_skeleton_2026_27.parquet
BOOTSTRAP_DIR = data/live/bootstrap_raw/2026-27
SKELETON_COLS = ["element","GW","team","opponent_team","was_home","kickoff_time"]
MAX_HORIZON   = 10
```
Functions: `_team_names`, `calendar(path=None, df=None)`, `_difficulty`, `build`.

#### `prices_tool.py` (236 lines)
```
BOOTSTRAP_DIR  = data/live/bootstrap_raw/2026-27
FORWARD_FIELDS = ("price_change_projections", "price_change_hourly_rate",
                  "price_change_locked_until", "price_change_calibrating")   # NEVER read
DEFAULT_WINDOW_DAYS = 7
MAX_MOVERS          = 25
```
Functions: `snapshot_time`, `snapshots`, `read_snapshot`, `bracket`, `_gaps`, `movements`,
`_squad_block`.

### 2.2 `explain.py` — now the single source for fixture judgements

Four things were factored **out of `breakdown()`** so other modules reuse the *detection*, not
just the vocabulary:

```python
LAMBDA_MIN, LAMBDA_MAX = 0.15, 6.0     # the runaway-strength box (KNOWN_ISSUES #25)
RUNAWAY_NOTE = "a strength parameter ran off (lambda outside [0.15, 6.0]): a club with no
                history and a one-sided record -- KNOWN_ISSUES #25"

fixture_runaway(row)                 -> bool
runaway_side(row)                    -> [{side, club, lambda, effect}]
fixture_provenance(row, step_rows)   -> (source, constant, notes)
market_priced(row)                   -> bool
```

`runaway_side` returns `club=None` for the opponent **on purpose**: the frame carries the
player's own club but not their opponent's, and pairing clubs by matching lambdas is the
recorded mis-pairing trap. It also returns `None` (never the string `"None"` or `"?"`) when the
club is unknown — a caller that prints the club must be able to tell "not known" from a name.

**`breakdown()` output is unchanged**, proved twice:
- `RUNAWAY_NOTE` byte-identical to the sentence previously inlined.
- 11 synthetic rows covering every fixture branch × 3 `step_rows` states = **33 comparisons,
  byte-identical, 0 differences.**

### 2.3 `model_tools.py` — the read layer

New/changed entry points:

```
PRED_BASE_COLS      # always selected
PRED_OPTIONAL_COLS  # selected only if the live schema has them
PRED_INTERNAL_COLS = ("team_lambda","opp_lambda")   # selected, then STRIPPED from `predictions`
_prediction_columns(available) / _table_columns(table, ttl)   COLUMN_CACHE_TTL_S = 60.0
_quantile_block(rows)
_backup_status(reasons)          BACKUP_STALE_HOURS = 30.0
_tool_surface_check(reasons)     CANARY_MAX_MS = 2000.0
FIXTURE_REQUIRED_COLS = ("element","gw","team_lambda","opp_lambda")
FIXTURE_OPTIONAL_COLS = ("horizon_step","p_cs","n_fixtures","odds_horizon_gws")
_resolve_team(name, known) / _team_gw_rows(run_id, skel)
get_fixtures(team=None, gw=None, horizon=5)
get_price_movements(window_days=7, user_id=1, include_squad=True)
```

### 2.4 Agent surface — now **17 tools**

`agent.py` holds `tools_schema` (17) and `available_functions` (17); a test asserts the two sets
are equal. `tools.py` is **dead code** — `agent.py` imports from `model_tools`, and `tools.py`'s
five functions are reachable from nothing. Delete in its own change.

`prompts/system_prompt.md` gained **§2b** (fixtures + prices rules) and a runaway/P10 rule in the
quantiles section. Edit the file, never the code.

---

## 3. Features delivered, and the decisions inside them

### 3.1 API access gate (`fa1b233`, `acb1c38`, `c67c16e`, `ccb7e6d`)
Shared secret on every endpoint except `GET /health`. Fails **closed** (503 if `APP_API_KEY` is
unset). `?key=` on a GET sets an httponly/samesite-strict cookie and 303-redirects. Browser GETs
with `Accept: text/html` get a 401 notice page; everything else gets JSON 401. Rate limit on
`POST /chat`: 30/IP/hour, 60 global/hour. `/docs`, `/redoc`, `/openapi.json` and `POST /reset`
are behind the secret.

**Not fixed, deliberately:** the shared in-memory `conversation_history`. That is LangGraph work
(§12.2 item 7).

### 3.2 Hold comparison (`610b62a`)
`decide_gameweek_mip(..., hold_compare=False)`; when on, a second solve with `force_hold=True`
(`used[0] == 0`) attaches `hold_objective`, `hold_margin`, `hold_plan`, `hold_team`,
`hold_solved`, `hold_status`, `hold_seconds`. Skipped when `step["transfers_made"] == 0`.
`gap_objective` and `gap_this_gw` are reported **separately**. `HOLD_PREFERENCE_EPS` stays
`None` — the comparison MEASURES, it does not decide.

Schema: `plan_kind` and `paired_proposal_id` (nullable) on `model_transfer_plans`; hold written
first, then the move carrying `paired_proposal_id`.

**Finding:** the gap is biased **toward holding** whenever a runaway λ sits in the horizon,
because holding earns a second free transfer that the hold plan can spend on exactly the
mispriced fixtures. `propose_transfers` therefore **refuses** the gap while the detector fires,
rather than reporting a caveated number.

### 3.3 Off-site backup (`2356d8d`)
`eval/backup_b2.py`: `pg_dump -Fc` via `docker exec`, plus the volume minus `live/`, to Backblaze
B2 through `rclone` using `RCLONE_CONFIG_*` env vars only. Credentials live in
`/root/fpl-backup.env` (mode 600, written by the user, never echoed). `endpoint_url()` forces
https. Row-count tripwires, `pg_restore --list` verification, remote size check. Cron 03:43
daily. Alarms on failure **and on silence** (`BACKUP_STALE_HOURS = 30.0`).

**Not done:** a restore rehearsal, and B2 lifecycle/retention rules.

### 3.4 Quantiles (`ffde4d0`, `c2012ef`, `aac04b7`)
Stored in 12 columns on `model_predictions`. `QUANTILES_ACTIVE = True`,
`QUANTILE_SKIP_KINDS = ("t10",)`, seeded by `quantile_seed(season, gw, started_at)` (sha256) so a
stored quantile is reproducible from the run record alone.

**The headline finding, recorded as its own item: the feature's headline use case is its weakest
output.** P90 carries the new information and is the least reliable of the three, fragile in
three independent ways — bonus fixed at 0 (whole upper tail missing), the penalty term measures
penalties *missed* (KNOWN_ISSUES #19, definitional not magnitude), and MS-1 is an assumption the
model does not contain.

### 3.5 The runaway flag in quantiles (`7d8081a`, `9dc7f2c`)
**The finding: reusing a module's vocabulary is not reusing its detection.** `quantiles.py`
imported `CONSTANT_LABELS`, `CS_PTS`, `GOAL_PTS`, `PEN_FALLBACK` from `explain.py` — which made
it look like one source of truth. The bound check was not in the import list because it had never
been exported; it lived inline in `breakdown()`. So the two modules disagreed about the same row,
and the quieter one is the one the agent quotes when asked whether a pick is safe.

Measured before changing anything: **338 of 3,954 rows** have a fixture λ outside [0.15, 6.0] —
**67/77/65/67/62** across gw6–10, **185 own-team / 153 opponent**. `fidelity()` mentioned none of
runaway, lambda, #25, Coventry, degraded or extreme.

Now: `runaway` / `p10_unusable` / `runaway_sides` on **every `per_gw` entry**; a **fourth
fragility** in `fidelity()` naming the club and its λ in explain's words; a **P10 caveat**; and
the answer-level block built from the **earliest affected gameweek** (deterministic,
order-independent) rather than the largest-sampling-residual row, which was arbitrary.

**P10 is what this corrupts, and it outranks the P90 caveat.** The other three fragilities
understate a *ceiling*; this one fabricates a *floor*, and they are not symmetric — an
understated ceiling costs a missed opportunity, but a floor is what a reader trusts when judging
a pick SAFE. Live evidence: **Jordan Pickford, P10 = 1 in each of five clean gameweeks, then
P10 = 6 at GW10** against an attack fit at 0.00047. 21 starting GK/DEF face a runaway attack.

### 3.6 `get_fixtures` and `get_price_movements` (`e812edd`, `e48c961`, `292ef52`)

**Where the data actually lives** (verified on the server, not assumed):

| Thing | Where | Freshness | Cost |
|---|---|---|---|
| Calendar | `data/history/forward_skeleton_2026_27.parquet`, GW5–38, `opponent_team`/`was_home`/`kickoff_time` non-null throughout | **weekly ingest** | 14 ms |
| Team names | `teams` block of the newest bootstrap snapshot | per snapshot | — |
| Lambdas | `model_predictions`, constant within (team, gw) | per build | 30 ms |
| Prices | `data/live/bootstrap_raw/2026-27/*.json.gz`, 53 files | burst | 41 ms each |
| Purchase price | `squad_versions.squad_json[].purchase_price` | on write | — |

Three sources were investigated and rejected:
- **`odds_fixtures_2026_27.parquet`** — fresher (every deadline run) but `dd/mm/yyyy` strings,
  **no gameweek column**, football-data spellings needing `assembly.TEAM_MAP`
  (`Man United`→`Man Utd`, `Tottenham`→`Spurs`).
- **`dixon_coles.get_fixtures`** — same name as the tool, and it **REFITS Dixon-Coles**. Model
  path. A chat turn must never reach it.
- **Inferring the opponent from matching lambdas** — 0 collisions measured across gw5–10, so it
  would appear to work. Refused because it fails exactly when `step_is_degenerate` fires and all
  20 clubs sit at the starting point, i.e. when the model is broken, which is when a reader most
  needs the fixture list.

**Difficulty is two numbers.** `attacking` = `team_lambda`; `defensive` = `p_cs` (the blend the
model actually uses) with `opp_lambda` alongside. No composite exists anywhere in the payload and
a test asserts no key named `score`/`fdr`/`difficulty`/`overall`/`composite` can appear inside
the difficulty block.

**The label correction that shaped it:** the spec called attacking difficulty "the opponent's
defensive lambda". The frame has no such quantity — `team_lambda` is
`attack_ours × defence_theirs × home_advantage`, and the factors live only inside the fit.
Presenting a fixture-level product as an opponent rating would be **a subtler version of the FDR
error**: not collapsing two numbers into one, but mislabelling what one measures. Every payload
carries the cross-team comparison caveat.

**Two designed refusals:** past-horizon returns `difficulty: null` with a reason saying it is a
*missing calculation, not an easy fixture*; doubles and blanks group into a list per (team, gw).
The exploratory query used `drop_duplicates(["team","GW"])`, which **would have silently dropped
the second leg of a double**.

**Prices.** Selling price is `squad_state.sell_price` — the function the MIP and
`propose_transfers` already share under a mismatch assertion. `"// 2" not in src` is asserted so
a third copy cannot appear. Only the **two bracketing snapshots** are parsed (O(1), not
O(archive)); a test counts the parses and fails at three.

---

## 4. Rulings the user made — do not re-litigate

1. **Quantiles**: no recentring of the structural residual; measure runtime before building;
   stored columns plus `quantile_method_version`; revised per-row tolerance accepted; t10 skips
   quantiles; identify the 0.3246 residual before building (it was a sampler bug); minutes-shape
   sensitivity check required.
2. **Hold comparison**: option (a) — hold stores steps 1–5 with `executable=false` and step 0
   empty; `plan_kind`/`paired_proposal_id` nullable; report `gap_objective` and `gap_this_gw`
   separately; `HOLD_PREFERENCE_EPS` stays `None`.
3. **Read-path tolerance**: *"the read path must tolerate absent columns rather than migrations
   being made stricter."*
4. **Price forecasting — option (a), narrow.** Include `price_change_percent`, attributed to FPL
   explicitly, never as ours. Exclude `price_change_projections` and the other forward fields.
   **The user's originally stated reason was wrong** (the thresholds *are* effectively published
   here); the constraint now stands on the **laundering argument** instead.
5. **Skeleton staleness accepted.** Stamp `age_hours` in every answer. **Do not** add a refresh to
   the deadline run — that touches the build path for a calendar that rarely changes, and the
   moved-fixture case already raises in the strict re-pull.
6. **Both tools added**, and the tool-budget overrun recorded as its own item.
7. **DC source**, **baseline adoption**, **bench weight 0.2** — all pre-existing, unchanged.

---

## 5. Corrections to the record made this session

These supersede earlier statements. Anything citing the old versions is stale.

1. **Handoff §2.5 / §12.1** described the deadline-slot ungating and a push as outstanding. Both
   were already done (`c975e26`). The prompts came from a docx saved **~3 h after** the work it
   called unpushed. Recorded permanently as `Logs/multi_run_schedule_design.md` §13.
2. **Handoff §9.5** had the Coventry fixture direction backwards — **Newcastle are AWAY**.
3. **The Coventry-forward quantile claim was misattributed.** `7d8081a`, the design log and
   KNOWN_ISSUES #25 all said *"Coventry forwards at `e_goals 0.0004` get P90 = 1"* as evidence of
   the own-side runaway. The measurement is real; the attribution is wrong. Those rows have
   `p_start 0.00` and `e_points 0.30` — their ceiling is 1 **because they do not play**, the
   ordinary one-sided bar. A *starting* Coventry forward (Awoniyi) is P10/P50/P90 = **0/2/6 at
   GW5 with `team_lambda 0.81` and 0/2/6 at GW6–8 with `team_lambda ≈ 0.0006`** — the runaway
   moves him **not at all**, because `e_goals` comes from `npxg90` and the fixture scaling rather
   than off `team_lambda`.
   **Consequence: the two sides are NOT symmetric.** Opponent-side runaway is real and dangerous
   (it enters through `p_cs` and manufactures a floor). Own-side is correctly flagged but
   numerically inert. **185 of the 338 rows are own-team, so 338 must not be read as 338 corrupted
   floors.** Corrected in `9dc7f2c`.
4. **The `get_fixtures` runtime estimate was 3× too low.** The design log said ~60 ms from summing
   components. Measured end to end through `agent.call_tool`, best of 3:

   | | estimated | measured |
   |---|---|---|
   | `get_fixtures`, one club | ~60 ms | **198 ms** |
   | `get_fixtures`, all 20 | — | **295 ms** |
   | `get_price_movements` | ~73 ms | **103 ms** |

   The estimate omitted the shaping it waved at: the read pulls all ~3,954 prediction rows, not
   the 120 team-gw rows it uses. Conclusion unchanged — both on demand, neither in a build.
5. **The price snapshots are not daily.** Master plan §5.4 says "daily snapshots". Measured: **53
   files over 30 days on SIX distinct days** (2/1/11/13/13/13), gaps of 6–8 days; confirmed live
   at a **183-hour** largest gap. Rescued by FPL's cumulative counters (`cost_change_start`,
   `cost_change_start_fall`), so net change is exact regardless of sampling.

---

## 6. The three-in-three-days pattern — the most important thing in this handoff

| date | the check that passed | the path that was actually broken |
|---|---|---|
| 09-17 | curl proved every endpoint answered correctly | the browser UI rendered the literal word `undefined` — a cookie jar never runs the page's JavaScript |
| 09-18 | `add_quantiles` measured clean over the frame (24.9 s, 3,954 rows) | `get_prediction` raised `UndefinedColumn` on **every call for ~35 minutes** |
| 09-19 | 37 tests over pure functions, suite green | `get_fixtures` raised `UndefinedColumn` on **every call** in production |

Every one of those verifications was real, measured, and aimed **one layer below the failure** —
which is exactly what made them convincing and useless.

**The 09-18 incident**: a widened SELECT naming 12 quantile columns was deployed at 23:09:40Z.
`ensure_schema` runs on WRITE paths only; the last write was run 15 at 17:21:29Z and the next was
days away. Fixed by running `ensure_schema` live, then making the read tolerate absent columns.

**The 09-19 defect**: `odds_horizon_gws` is a **frame** column, not in `db_write.PRED_INSERT_COLS`,
so it has never existed on `model_predictions`. A hardcoded eight-column SELECT named it. The unit
tests could not catch it because they hand `build()` a dict in the shape the function wants, and
the live read produces a different shape. **Caught by the live dead-on-arrival check on its first
run**, minutes after deploy.

**The rule this produced — it now has a mechanical trigger, not a principle to remember:**

> **Any new SQL `SELECT` against `model_predictions` must be checked against
> `db_write.PRED_INSERT_COLS` in a test, at the time it is written.**

Deploy-then-check stays, as the **second** line. It turned a silent production outage into a
ten-minute fix, but catching it after deploy is the expensive way.

**A near-miss in the same family, caught before deploy:** the runaway flag would have been *dead
on arrival*. `fidelity()` and `_quantile_block()` were correct and 19 tests passed, but
`get_prediction`'s SELECT named neither lambda — so `fixture_runaway` would have read NaN and
answered `False` on all 338 affected rows. **A flag that cannot see its input reads as "checked,
and fine", which is worse than no flag.**

---

## 7. Open items, ranked

### Blocking nothing, but next in line
1. **`squad/live_deadline.py:411` declares its own `LAMBDA_MIN, LAMBDA_MAX = 0.15, 6.0`** — a
   second copy of the bound, on the **build path**, uncovered by the tests written to prevent
   exactly that. They agree today only because the literals were typed twice. Fix:
   `live_deadline.py` imports the constants from `explain.py` and keeps its own series-level
   logic; the test that must come with it asserts the two classify the same λ identically. Needs
   its own change, suite run and deploy. *(KNOWN_ISSUES #25 open item; design log §"Open item,
   dated".)*
2. **Tool budget is spent.** §5.4 specifies ~10 deliberately; we are at **17**, and `search_news`
   is not optional (it is the only legitimate origin for an injury claim under the §5.5 grounding
   contract), so the real figure is **18**. The next tool needs an **argument**, not just a use
   case. **And there is no instrument** — tool-selection accuracy has never been measured at any
   surface size. If the surface keeps growing, the measurement should come first.
   *(`FEATURE_IDEAS.md`, design log §6.)*
3. **`tools.py` is dead code.** Delete in its own change.

### Owed measurements
4. **Real build duration and peak RSS for the first quantile-computing build**, against the 70–86 s
   baseline. Needs the `post_ingest:GW5` run.
5. **MS-1 validation against realised minutes** — dated open item in the quantiles log.
6. **Backup restore rehearsal**, and B2 retention/lifecycle rules.

### Known and accepted
7. **KNOWN_ISSUES #25 cold start remains OPEN.** v2 hinge+box and v3 promoted-club centre both
   MARGINAL (2026-09-17), on branch `hinge-box-v2`, **not adopted**. The centre is not the lever;
   let Coventry score. The loud detector is the live floor. **Three consequences now on the
   record**: the degraded-run detector, the hold-vs-move bias, and the manufactured quantile floor.
8. **`fplcache` unprotected** (laptop-only).
9. **Pending server reboot** since 2026-09-12.
10. **HTTPS and a domain** — still `http://68.183.131.154:8000` (§7.2, §12.3).

### Unresolved, and it carries operational risk
11. **An unattributed `git pull` runs on the server.** `git reflog` shows bare `pull:
    Fast-forward` entries at 00:27:03, 02:51:21 and **08:02:54** on 2026-09-19 — distinct in form
    from my own `pull -q --ff-only origin main` entries. `FETCH_HEAD` mtime matches 08:02:54. The
    08:02:54 pull landed **one second before** the image was built, so the deployed image contains
    both the `e48c961` fix *and* the `292ef52` docs commit, which is why `/health` reports
    `292ef523d`.
    **I could not find the mechanism**: no auto-deploy in root's crontab, no systemd timer, no git
    hooks, no `/etc/cron.d` entry, and nothing listening but sshd and docker-proxy on 8000.
    **Why it matters**: something may pull and rebuild whatever is on `main` at an arbitrary
    moment, which would violate the deadline / ingest no-touch window. It also means
    `/health`'s `git_sha` is read from a **baked `.git`** and reflects the repo at *image build
    time* — so it can silently disagree with the code if the repo moves mid-build.
    **Next step**: identify it (auditd on `/root/fpl-copilot/.git`, or `journalctl` around those
    timestamps) before the next deadline window.

---

## 8. Standing rules in force

Observed throughout; several were re-earned this session.

- Never commit keys. `git check-ignore -v deploy_key_new` before any `git add`.
- **Every push to main is a deploy** — but on this server a deploy is
  `git pull && docker compose build fpl-copilot && docker compose up -d fpl-copilot`.
  **There is no auto-deploy cron** (see open item 11). **Verify every deploy landed** — and
  verify it by checking the *code in the container*, not only `git_sha`.
- No deploys, restarts or lock-holding within **T−2h…T+30min** of a deadline, or near the
  6-hourly ingest ticks (**00:17 / 06:17 / 12:17 / 18:17Z**) or the 11:00Z nightly.
- "Fixed" and "deployed" are different words. So are "detected" and "fatal".
- Parity is the gate for anything touching the model path. **Nothing this session touched it** —
  `explain.py` imports no part of the model stack, so factoring functions out of it is a
  read-side refactor, and the 33-way byte-identity proof stands in for a parity run.
- No model-path changes without pre-registration. Bars stated before numbers, never amended.
- No adoption decision may cite season totals.
- Verify the path the USER touches, not the path you were thinking about.
- A read must never depend on a write having happened.
- Never switch branches during a build — queued builds import whatever is on disk.
- The laptop runs the suite; the server does not. **The laptop's `data/` is stale** — sync down,
  never up. The laptop frame is a 2026-09-14 artefact with every λ inside [0.65, 2.68] and **no
  runaway rows**, so runaway work cannot be verified locally at all.

---

## 9. Practical notes for the next session

**Running the suite** (laptop, Git Bash):
```bash
cd /c/dev/fpl-copilot
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 APP_API_KEY=$(python -c "print('x'*48)") \
  python -m pytest Tests -q
```
~8–10 minutes. `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` is required — the console is cp1252.
`APP_API_KEY` is required or `main.py` fails closed.

**Known environment gotchas**
- **Heredoc mangling**: `\n` inside a bash heredoc becomes a literal newline and breaks
  f-strings. This recurred 4+ times. Use the `Write` tool for Python, not heredocs.
- No `zip` binary on Windows — use a Python `zipfile` script with `[Content_Types].xml` first.
- The container's default `python` lacks numpy. Use **`/app/.venv/bin/python`**, with
  `sys.path.insert(0, "/app")` and `"/app/squad"`.
- Docx editing: unzip → `merge_runs.py` → edit `word/document.xml` → repack → `validate.py` →
  text-node diff. `<w:strike/>` must follow `<w:b/><w:bCs/>` in rPr ordering.

**Test-isolation trap found this session.** Three suite failures appeared only in the full run.
One asserted "exactly one" prompt line mentions a runaway, which a new legitimate rule made two.
Two asserted **object identity** between `agent.available_functions[...]` and
`model_tools....` — broken because `test_agent_prompt` reloads `agent` and `test_backup_b2` /
`test_tool_surface_check` reload `model_tools`, so the map holds an earlier incarnation. Fixed by
asserting `(fn.__module__, fn.__qualname__)`.

> **Assert the property you mean, not a stronger one that implies it.** The stronger property
> fails for reasons unrelated to the thing under test, and a suite that fails for unrelated
> reasons stops being read.

**Suite trajectory**: 532 → 555 (runaway) → 592 (fixtures/prices) → **596** (DOA regressions).

**Test files added this session**: `test_api_gate.py` (25), `test_hold_comparison.py` (11),
`test_backup_b2.py` (16), `test_quantiles.py` (28), `test_tool_surface_check.py` (11),
`test_quantile_runaway.py` (23), `test_fixtures_tool.py` (24), `test_prices_tool.py` (17).

**Design logs written** (read these before touching the matching code):
`Logs/quantiles_design_2026-09-18.md` (689 lines — design, four rulings, the sampler bug, the
build, the read-path incident, the runaway work, the live confirmation, and two dated open items),
`Logs/fixtures_and_prices_design_2026-09-19.md` (363 lines),
`Logs/hold_comparison_log_2026-09-18.md`, `Logs/backup_design_2026-09-18.md`,
`Logs/alerting_design_2026-09-13.md`, `Logs/multi_run_schedule_design.md` §13.

---

## 10. The one-paragraph version

The agent now has 17 tools, an authenticated API, off-site backups, external and on-host
alerting, uncertainty ranges on every prediction, a hold baseline on every transfer proposal, and
fixture/price tools — and, more importantly, it now *says* when its own numbers are not
trustworthy: a runaway Dixon-Coles strength is flagged in the same words in three places, P10 is
declared unusable where it is manufactured, and the hold-vs-move gap is refused rather than
caveated. Three production paths broke in three days in the same way — a real check aimed one
layer to the side of the thing that mattered — and the response is a mechanical trigger
(`SELECT` vs `PRED_INSERT_COLS` in a test) plus a live dead-on-arrival check that already caught
one outage on its first run. The open items that matter are the duplicate λ bound on the build
path, the spent tool budget with no instrument behind it, and an unattributed `git pull` on the
server that nobody has identified.
