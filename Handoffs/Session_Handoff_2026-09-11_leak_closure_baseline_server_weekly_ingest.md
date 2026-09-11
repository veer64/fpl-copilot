# Session handoff — 2026-09-11: leak closure, baseline adoption, server close-out, weekly ingest automated

Written 2026-09-11 ~23:20Z at the end of one long session (it was compacted once
mid-way; everything before the compaction is reconstructed from the logs it wrote,
which are the records of record and are named at every step). Read this top to
bottom once; then use §0 as the map.

Machine facts you will need immediately:

- Repo: `C:\dev\fpl-copilot`, branch `main`, HEAD **07a7266**. Working tree clean
  except the tracked `__pycache__/main.cpython-314.pyc` (always dirty, ignore it)
  and the untracked `Handoffs/Server deploy handoff.docx` (the user's file; leave it).
- Server: DigitalOcean droplet **68.183.131.154**, Ubuntu 24.04, Etc/UTC, root.
  **SSH is key-only.** The private key is the repo-root file `deploy_key_new`
  (gitignored by the `*_key`/`deploy_key_new` rules). `~/.ssh` holds NO private
  key, so plain `ssh root@…` fails with `Permission denied (publickey)` — always
  `ssh -i deploy_key_new -o BatchMode=yes root@68.183.131.154 '…'` from the repo
  root (works from Git Bash and Windows OpenSSH). Fallback: the DigitalOcean web
  console (hypervisor console, unaffected by sshd) — the user must hold the root
  password for it; never tested by me.
- Deploy: push to `main` → GitHub Actions (`.github/workflows/*.yml`,
  appleboy/ssh-action) → `git pull && docker compose up -d --build
  --remove-orphans` on the server. Lands in ~2 minutes; verify with
  `curl http://68.183.131.154:8000/health` (`git_sha`) and `git rev-parse --short
  HEAD` in `/root/fpl-copilot`.
- Data on the server lives on the named Docker volume
  `fpl-copilot_fpl_model_data` mounted at `/app/data` in both containers, NOT in the
  checkout. Host path: `docker volume inspect fpl-copilot_fpl_model_data -f
  '{{.Mountpoint}}'` → `/var/lib/docker/volumes/fpl-copilot_fpl_model_data/_data`.
- Secrets: `/root/fpl-copilot/.env` (mode 600): ANTHROPIC_API_KEY, ODDS_API_KEY,
  DB_HOST/PORT/NAME/USER/PASSWORD. Never print values.
- Suite: `uv run pytest Tests -q -p no:cacheprovider` → **249 passed, 0 skipped**
  (~4 min). The server never runs the suite (the parity family reads research
  artefacts that stay laptop-side).

---

## 0. State at a glance

| thing | state |
|---|---|
| Production configuration | **baseline** (`config_roles.py`: `PRODUCTION_CONFIG="baseline"`, `SHADOW_CONFIG=None`, `CONFIGS=("baseline",)`, `LEVER_INPUTS_ACTIVE=False`). Adopted 2026-09-11 as a judgement call, NOT on season totals (Logs/baseline_adoption_log.md). |
| Leaks | KNOWN_ISSUES #22 (DC), #23 (saves/aggregates), #24 (p60 starter history) CLOSED as MODEL CHANGES under one rebuild (commit 553772a; Logs/asof_rebuild_log.md; LEAKAGE.md items 6–9). |
| Standing leakage test | `eval/asof_reconstruction.py` + `Tests/test_asof_reconstruction.py` (4 tests, cutoffs 20/24 × baseline/combined). Bit-identical at all 38 cutoffs of 2025-26 both configs, plus 2023-24 and 2024-25 samples with doubles. |
| Reference cells | `EXPECT_REFERENCE_CHIP = {"2023-24": 2390, "2024-25": 2285, "2025-26": 2249}` (gap0_tc2 = baseline with TC2 in-sim). Old 2425/2335/2266 flagged SUPERSEDED in Logs/season_totals_index.md (260 rows, 57 arm rows). |
| Fingerprint test | `Tests/test_walkforward_provenance.py`: `EXPECTED_SPEARMAN = 0.7454`, `EXPECTED_MAE = 1.0506` (post-as-of values, dated note). |
| Server code | HEAD **07a7266** deployed; /health `status: ok`, `git_sha: 07a7266fa`, `model_versions {"baseline": "e3d98afdd/baseline"}`, `last_run run_id 4 (GW3, recovered)`, `db_ok true`, `reasons []`. |
| Server security | sshd password auth OFF (`/etc/ssh/sshd_config.d/00-hardening.conf`); Postgres 5432 NOT published (compose 2551d7e); .env 600; Anthropic key, odds key (earlier) and DB password rotated. |
| Postgres | run_id 3 = GW3 built 2026-09-04 on pre-fix code 89f6406, both configs — kept as history. run_id 4 = GW3 REGENERATED 2026-09-11 on e3d98af, baseline only, recovered=True (captain Haaland, vice Foden, cost 99.6, 3,934 prediction rows gw 3–8). The app serves run 4. |
| GW3 ingested | fpl_api_2026_27: gws [1,2,3], 1,890 rows; Understat 30 matches; crosswalk_2026_27.csv 387 ids, 100.0% of played minutes covered (Sávio 403 → 11735 MANUAL). |
| **Weekly ingest** | **AUTOMATED** (commit ad056de): `eval/run_weekly_ingest.py`, server cron `17 */6 * * *` inside the scheduler image against the volume, both locks, status files + /health. Proven end to end on laptop and server (`--force-gw 3`). **The laptop is no longer the producer.** |
| Next deadline | GW4 Sat 2026-09-12 **12:30Z** (dispatcher fires at T-90 = 11:00Z). GW5 Fri 2026-09-18 17:30Z. |
| Odds credits | paid pool, **19,326 remaining** (2026-09-24 cancellation question unresolved; see §5.5). |

---

## 1. The session's sequence (what was asked, what was delivered, where it is recorded)

The user's tasks, in order. Each was explicit; none was inferred.

1. **Read-only model inventory** → `Logs/model_inventory_log.md` (687 lines): every
   model in the live path, features, outputs, training, gates, config
   differences, inactive models, constants standing in for models. Section 15
   item 1 flagged that the DC model never scores the live deadline gameweek.
2. **Verify the DC finding on frames** (read-only) → KNOWN_ISSUES **#22** written:
   every live row priced at `DC_BASE` while the backtest of record used the
   per-player model; cost quantified.
3. **Read-only leakage audit of the backtest side** against LEAKAGE.md's definition
   ("selection conditioned on the outcome with clean shift(1) features inside")
   → LEAKAGE.md items **6** (DC rows exist only for players who PLAYED gw k), **7**
   (D1 saves not frozen at the cutoff — steps 1–5 read post-cutoff saves), **8**
   (full-season aggregates in the D1 block); term-by-term table; the parity
   harness cannot see shared-input leaks.
4. **Quote the combined arm's figures** from the index (no recompute) — done in chat.
5. **Build the as-of reconstruction guard FIRST, run it on the unfixed code, stop
   at a third leak.** It found the third leak on its first run (p60 — LEAKAGE.md
   item **9**, KNOWN_ISSUES **#24**): at cutoff 20, 214/214 rows that moved were
   realised starters; p60 fell 0.936 → 0.892 on the moved rows. Stopped and
   reported as instructed.
6. **"Proceed. Fix all three leaks under the one as-of test, rebuild once,
   report"** — with the guard extended to RECONSTRUCT the hmin refit in-process
   (reading it from disk had hidden the combined config's steps 1–5 movement).
   Delivered: fixes as MODEL CHANGES (not repairs), full record rebuild (three
   seasons' canonicals, arms_gap0 frames, hmin refits incl. 2026-27, armlogs)
   with `*_preasof` artefacts preserved, report in rank-first order →
   `Logs/asof_rebuild_log.md` §0–10. Commit **553772a**.
7. **Adopt BASELINE as production, re-point the reference cells, regenerate the
   index, gate off the lever inputs, no shadow, record levers as UNSETTLED** →
   `Logs/baseline_adoption_log.md`, `config_roles.py`, commit **58614b1**
   (committed separately from everything else, as asked).
8. **Full audit** ("read-only unless a fix is named") — exhaustive as-of over all
   38 cutoffs × both configs, guard coverage, shape audit, totals reconcile,
   independent recompute of the baseline cells from the armlogs, server
   reproduction, Postgres contents, /health, strict preflight, GW4 walkthrough,
   secrets/ports/ufw, suite skips, uncommitted work — reported in the requested
   A/C/B/D order. Its four actionable items became task 9.
9. **Close the four actionable items in order: security → deploy → ingest**
   (details §5): key rotation + stray-file deletion, Postgres un-publish, sshd
   hardening, .env 600, DB password rotation; suite + push + server quotes;
   server-vs-laptop reproduction; GW3 ingest in runbook order with crosswalk
   gains; GW4 dispatcher walkthrough; GW3 backfill regenerated. Commits
   **2551d7e**, **e3d98af**. The named handoff file
   `Handoffs/Session_Handoff_2026-09-10_prod_switch_and_leak_audit.md` does NOT
   exist on disk — the docx `Handoffs/Server deploy handoff.docx` was used for
   its §8.10 and §10 (extract with a zipfile/regex one-liner; python-docx is not
   installed).
10. **Automate the weekly ingest before GW5** (details §6) → commit **ad056de**
    (+ log **07a7266**), cron installed, proven on both machines.

Standing instruction throughout: **"Do not start modelling work. Modelling is
closed."** Nothing in this session changed a model after 553772a.

---

## 2. The leak closure (commit 553772a) — code detail

Read `Logs/asof_rebuild_log.md` for the numbers; this is the code map.

### 2.1 The guard — `eval/asof_reconstruction.py`

- `asof_world(season, k, tmpdir, record_source, reconstruct_refit, horizon)` —
  a context manager that builds a world in which gameweek k has NOT been played:
  - truncates the stack to `gw < k` and serves k onward as a **nulled forward
    skeleton** (identity + fixture geometry, measurement columns NaN), patching
    `season_stack.stack_path` / `forward_path`;
  - truncates core-insights (`defensive._raw_rows_core`), Understat
    (`attacking_rates._MATCHES_CACHE`), odds results and prices
    (`dixon_coles._load_matches` — goals nulled at ≥ cutoff, prices nulled beyond
    `odds_until`), availability (`availability_features.load` → gw ≤ k);
  - clears `defensive._DC_HITS_CACHE`;
  - for the combined config **reconstructs the hmin refit in-process** via
    `horizon_minutes.get_minutes_horizon(...)` injected through
    `live_deadline.load_hmin_refit` (reading the refit from disk is exactly what
    made steps 1–5 look clean before).
- `build_asof(...)` builds through the same entry point the record used;
  `build_reference(...)` is the in-process full-information build;
  `canonical_path(...)` finds the record file; `compare(...)` reports per
  column/step `n_diff` / `max_abs`, excluding `OUTCOME_COLS = {minutes,
  actual_points}`.
- `run(season, cutoffs, config, record_source, reference="record"|"inprocess")`
  and a CLI: `uv run python eval/asof_reconstruction.py --season 2025-26
  --cutoffs 20 24 --config baseline --record-source fpl_official --reference record`.
- `Tests/test_asof_reconstruction.py`: parametrised cutoffs [20, 24] × configs
  [baseline, combined] against the record files; asserts row_ok, no column-set
  diff, empty diff table.
- **What it does not cover** (Logs/asof_rebuild_log.md §10, LEAKAGE.md "residual"):
  shared-input leaks common to both sides; the exhibit-B train/serve-skew test
  is trivially satisfied because research and production are one path; anything
  whose reconstruction the guard does not perform (it reconstructs every input it
  knows about — add new inputs to it when they appear).

### 2.2 The three fixes — MODEL CHANGES, not repairs

**#22 DC — `squad/defensive.py`.** New `_asof_rows(hist)` builds tail(3)/tail(5)
aggregates per player with a stable sort on (player_id, gw, fixture); new
`_score_cutoff(d, cutoff_gw, recency_weight=False)` trains per position on rows
`gw < cutoff` (<150 rows → mean hit rate or 0.13; FWD 0.005); `get_dc_hits`
rewritten with caches keyed `("features", DC_SOURCE, season)` /
`("hits", DC_SOURCE, season, cutoff)`. The live gameweek is now scored by the
model instead of `DC_BASE`. Docstring states MODEL CHANGE, NOT A REPAIR.

**#23 saves/aggregates — `squad/assembly.py`.** `assemble_fixtures(...,
cutoff_gw=None)`. With a cutoff: `hist_rows = v_full[minutes.notna() & gw <
cutoff_gw]`; saves = mean of the last ≤5 rows per element (stable sort
element/gw/fixture); `saves_prior_shrunk =
hist_rows.groupby("position")["saves_per_90"].mean() * 0.3`; `team_pen_rate`
from `_played[_played["gw"] < cutoff_gw]`. `cutoff_gw=None` keeps the legacy
path for the static `python assembly.py` only. `eval/walkforward_season.py`,
`eval/walkforward_arms.py`, `eval/walkforward.py` pass `cutoff_gw=k`.

**#24 p60 — `squad/minutes.py` + `squad/horizon_minutes.py`.** Added
`STARTER_HISTORY = ["past60_rate_3", "past60_rate_5", "last_start_minutes"]`;
in `_build_frames` the starter history is computed as-of on EVERY row:

```python
is_start = col["starts"] == 1
st = col.loc[is_start, ["season","element","minutes_capped"]].copy()
st["played_60"] = (st["minutes_capped"] >= 60).astype(float)
gs = st.groupby(["season","element"], sort=False)
st["_r3"] = gs["played_60"].transform(lambda s: s.rolling(3, min_periods=1).mean())
st["_r5"] = gs["played_60"].transform(lambda s: s.rolling(5, min_periods=1).mean())
st["_lm"] = st["minutes_capped"].astype(float)
g_all = col.groupby(["season","element"], sort=False)
for src, dst in (("_r3","past60_rate_3"),("_r5","past60_rate_5"),("_lm","last_start_minutes")):
    col[dst] = np.nan; col.loc[st.index, dst] = st[src]
    col[dst] = g_all[dst].transform(lambda s: s.shift(1).ffill())
cs[STARTER_HISTORY] = cs[STARTER_HISTORY].fillna(0)
```

`get_minutes`: `csx = cs` (the merge from the starts==1 frame removed).
`horizon_minutes._frames`: `csx = cs`; `S2 = mm.S1 + mm.STARTER_HISTORY`. The
start-row values were proven bit-identical (30,162 rows), so the fitted p60 model
itself did not move — only which rows carry real history at prediction time.

**`squad/live_deadline.py`**: new `load_hmin_refit(season)` (single read of the
hmin file, used by preflight and the combined build); header comment says
production = baseline since 2026-09-11.

**Tests moved**: `Tests/test_live_deadline.py::_frozen_record_source` is now a
no-op asserting `defensive.DC_SOURCE == "fpl_official"` (the record was rebuilt
under the live default). `Tests/test_walkforward_provenance.py` fingerprint →
0.7454 / 1.0506.

### 2.3 The rebuild and what it did to the record

- Whole record rebuilt: canonicals `data/walkforward_h6_{tag}.parquet`, arm frames
  under `data/arms_gap0/`, hmin refits (incl. 2026-27), armlogs under
  `data/arms/`. Pre-fix artefacts preserved with the `_preasof` suffix
  (`STALE_SUFFIXES` in the index builder includes `"preasof"`).
- Totals after the rebuild (chip-inclusive, TC2 in-sim): baseline `gap0_tc2`
  **2390 / 2285 / 2249**; `hmin_gap0` 2302 / 2275, `hmin_gap0_tc2` 2227;
  `both_gap0` 2335, `both_gap0_tc2` 2074; `props_gap0` 2328 / 2221 NOT re-run
  (read against `_preasof` frames — flagged in the index). Deadlines changed on
  13–36 of 38 per season. Hindsight removal has a sign: totals fall where the
  leak exposure was largest — not a regression.
- `eval/build_season_totals_index.py`: docstring 2026-09-11 paragraph;
  `EXPECT_ARMS_CHIP` gap0 family post-fix; `EXPECT_REFERENCE_CHIP` re-pointed;
  `REFERENCE_ARM` = gap0_tc2 everywhere; `_gap0_frames/cap_pred_gap0(...,
  preasof)`; `_prefix_log(resume_from, tag, preasof)` stitches `_preasof` arms
  with the `_preasof` gap0 prefix (GW8-start arms); `frames_preasof = preasof or
  base_arm == "props_gap0"`; flag branches for reference / preasof / hmin+both
  superseded / props not re-run; HEADER framing block (grounds 1–4, cost, levers
  UNSETTLED, roles, superseded list); FOOTER "MOVED 2026-09-11". Drift assert
  passes; index regenerated → `Logs/season_totals_index.md`.

---

## 3. Baseline adoption (commit 58614b1) — the position

`Logs/baseline_adoption_log.md` §1–7 is the record. The short form, which must
not be shortened further when quoted:

- Production = **baseline**. Grounds: the leak fix invalidated the comparison the
  2026-08-28 "combined = production intent" choice rested on; the shadow
  comparison has no statistical power (paired-path sd ~85; one near-tie flip
  moves a season ~90); the combined config's inputs are exactly the paid and
  weekly steps production no longer needs; the levers are **UNSETTLED**, not
  rejected — re-opening either is a NEW pre-registration on clean frames.
  **Not taken on the season totals.**
- No shadow. `config_roles.py` is the ONE source read by
  `eval/run_live_deadline.py` (`for config in cr.CONFIGS`; the props pull,
  props crosswalk, props consensus and `run_horizon_minutes` run only `if
  cr.LEVER_INPUTS_ACTIVE`; the Jackson check and the disagreement section are
  gated the same way; production squad = `teams[cr.PRODUCTION_CONFIG]`),
  `db_write.py` (`players_live` source = `frames[PRODUCTION_CONFIG]`),
  `model_tools.py` (`PROD_FRAME = data/live/_tmp_frame_{PRODUCTION_CONFIG}.parquet`;
  `get_picks(shadow=True)` returns an explicit "no shadow configuration" error;
  health `model_versions` over `CONFIGS`), `agent.py` wording. Nothing deleted:
  flipping `SHADOW_CONFIG = "combined"` re-enables the whole combined path.
- Superseded cells carry the date and the convention in the index. Odds
  subscription statement recorded (§5.5 below). Verified: drift assert, index,
  suite, live strict build for GW3 baseline.

---

## 4. The full audit — what it established (2026-09-11, read-only)

Delivered in chat in the requested order; the durable facts:

- As-of guard: bit-identical at **all 38 cutoffs of 2025-26 for both configs**,
  and at 2023-24 (2, 5, 20, 25, 33) and 2024-25 (2, 5, 20, 24, 31 baseline; 8,
  20, 24, 31 combined) including doubles. Guard covers the hmin refit by
  reconstruction; props inputs are not reconstructed (lever off in production).
- Independent recompute of the baseline cells from the armlogs with the index's
  own functions confirmed 2390 / 2285 / 2249.
- `EXPECT_REFERENCE_CHIP` matched the recompute; superseded flags present.
- Server: builds and serves **baseline only** (quoted from the image: runner
  loops `cr.CONFIGS`; `model_tools` has 0 `'combined'` literals;
  `config_roles.py` present).
- The three unknowns it named: (1) whether the guard would catch a refit-side
  leak — argued from construction only; (2) /health degradation states not
  re-exercised; (3) server reproduction on current code — **closed** in task 9
  (see §5.7).
- Four actionable items (security: compromised Anthropic key + stray file,
  Postgres reachable from the internet, sshd password auth on, .env mode; deploy
  gate; ingest GW3; GW3 backfill built on leaked frames) → task 9.

---

## 5. Closing the four actionable items (commits 2551d7e, e3d98af) — with evidence

Order was mandated: security first, then deploy, then ingest. Everything below
was verified on the server, not assumed.

### 5.1 Anthropic key rotation and the stray file
- User supplied the new key in chat (value never repeated anywhere). Written into
  `/root/fpl-copilot/.env` in place; api container recreated; a live call with
  the container's key → 200, with the previous key → 401.
- The stray file whose NAME contained the key was deleted **by inode**
  (`find -inum … -delete`), never by glob (its name contains `=` and `-`).
  Disagreement with the premise recorded: it was NOT a second occurrence — mtime
  2026-07-09 14:32; bash history line 27 was the generator (a first-setup
  redirect typo); the key in its name was the July key, which already differed
  from the key in .env after the user's 2026-09-04 edit. Nothing generates such
  files. The old key value sat in four history lines; scrubbed; no file under
  /root outside .env holds either key.

### 5.2 Postgres — un-published, in compose (2551d7e)
- Chose removing the `ports: - "5432:5432"` publish entirely (not binding
  localhost): both containers reach it as `DB_HOST=fpl-postgres` over the compose
  network; localhost binding would still expose it to any local process. Applied
  on the running server first (container recreated, zero listeners on 5432),
  then committed with an explanatory comment so a rebuild keeps it. Proof: a TCP
  connect from the laptop now times out where it succeeded during the audit;
  /health `db_ok true`; the scheduler image connects. Debug access: `docker exec
  fpl-postgres psql -U postgres -d fpl`.

### 5.3 sshd
- Root cause: cloud-init's `50-cloud-init.conf` sets `PasswordAuthentication yes`
  and wins over `60-cloudimg-settings.conf`. Added
  `/etc/ssh/sshd_config.d/00-hardening.conf` (`PasswordAuthentication no`,
  `PermitRootLogin prohibit-password`, `KbdInteractiveAuthentication no`) — wins
  by lexical order; `sshd -t` validated; reloaded; a fresh key login proven
  BEFORE cancelling a timed auto-revert; a password-only probe now returns
  `Permission denied (publickey)`. Backup `/root/50-cloud-init.conf.bak-2026-09-11`;
  marker `/root/.sshd-hardening-confirmed`. Caveat: if cloud-init ever rewrites
  its drop-in, the hardening file still wins only by name order — re-check after
  any image-level change.

### 5.4 .env → 600. Done.

### 5.5 DB password rotated (after 5.2)
- `ALTER USER` inside the container; .env updated; both containers recreated;
  old password rejected over the network from the api container; new one
  connects from both images; /health `db_ok true`; the one history line with
  the old password scrubbed.
- Odds subscription: the key is the **paid pool** (19,326 credits remaining at
  the end of the session), NOT free-tier as my adoption log first said — noted as
  a correction. h2h alone would fit the free tier ~40× over; the 2026-09-24
  cancellation decision is the user's.

### 5.6 Deploy gate
- Suite before the push: 233 passed, zero skips, as-of and parity families ran.
  Pushed 553772a, 58614b1, 2551d7e; Actions succeeded; quoted from the image on
  the server: `PRODUCTION_CONFIG = "baseline"`, `SHADOW_CONFIG = None`, runner
  loops `cr.CONFIGS`, model_tools has zero `'combined'` literals,
  `config_roles.py` present, image sha = HEAD.

### 5.7 Server-vs-laptop reproduction (the audit's unknown 3 — closed)
- First comparison differed on **138 rows / 23 players** because the server
  volume held a newer forward skeleton (2026-09-04) and availability merge than
  the laptop (2026-09-01); everything else hashed identical. After syncing those
  two files DOWN to the laptop and rebuilding: row sets identical (3,912 rows),
  residual ≤ **4.4e-16 on 12 rows**, and both frames solve to the same fifteen,
  XI, captain, vice and bench order at objective 71.764011. The epsilon is
  presumed platform arithmetic, not proven. **Lesson baked into task 10: hash
  the inputs before any reproduction claim.**

### 5.8 GW3 ingest (laptop, runbook order, then synced to the volume)
- `fetch_fpl_history --gw 3` → 654 rows, cross-check vs event/live PASSED;
  `--combine`; `understat_matches` (30 matches); `build_understat_aggregates`
  (+combine); `build_crosswalk` → 386 then **387** ids: gained 22 (Danso,
  Gudmundsson, Timber, …), lost 0, changed 0, 99.9% → 100.0% of played minutes.
  One element with real minutes and no id: **Sávio (403)**, Man City → Spurs in
  the window, 60 min GW3, unambiguous on Understat as **11735** → added to
  `MANUAL["2026-27"]` in `eval/build_crosswalk.py` with evidence
  (`403: ("11735", "Savio Moreira de Oliveira = Understat 'Savio' … 60v62 min GW3 …")`).
  `Tests/test_crosswalk_2026_27.py::test_coverage_of_playing_elements` holds the
  invariant (every playing element has an id).
- Two data-loss traps found:
  1. **`fetch_fixtures` nulled every price column on each weekly rebuild** and
     `fetch_live_odds` refills only the provider's UPCOMING events, so played
     gameweeks' pre-deadline prices were discarded weekly. GW3's prices were
     restored from the OneDrive copy (md5 c28f1dcabe…, the only surviving
     pre-ingest file); **GW1 and GW2's are gone for good.** Fixed in e3d98af:
     `fetch_fixtures.build_slice` carries forward any B365H/D/A triple the
     existing slice holds where the fresh slice is null, keyed on (Date,
     HomeTeam, AwayTeam); provenance `prices_preserved_from_previous_slice` (30
     on first run). This also fixed the milestone test
     `test_strict_preflight_combined_clean_at_live_deadline`, which the price
     loss had broken.
  2. `tar` treated a `C:/…` path as a remote host — create tarballs from a
     colon-free relative path.
- Artefacts synced to the volume with md5 verified both sides; GW4 strict
  baseline build on the server: OK, 3,936 rows, 37 s, notes only.

### 5.9 GW4 walkthrough on the deployed code
- Dispatcher (`eval/deadline_dispatcher.py`, host cron every 10 min) fires at
  the first tick inside T-90 (11:00Z on 2026-09-12): `merge_live_availability` →
  `fetch_live_odds` (1 credit) → the four lever steps SKIPPED with a logged line →
  strict baseline build at horizon 6 → free-pick fifteen solve → status file
  `GW4_BUILD_STATUS.txt`, volume frame `_tmp_frame_baseline.parquet` and prices
  `_tmp_prices_2026_27.parquet` → Postgres run; /health then reports GW4 at
  e3d98af/baseline (well, 07a7266 now). Cost ~1 credit per attempt (the audit
  had predicted ~90 for the failure mode of the combined path). Remaining
  failure mode: a fixture FPL moves before 11:00Z trips the strict calendar
  re-pull → three failed attempts at 1 credit each, no prediction; the skeleton
  rebuild that clears it is a hand step (or `run_weekly_ingest.py --force-gw 3`
  now, outside the window).

### 5.10 GW3 backfill regenerated (recommended over amending)
- New `eval/backfill_recovered_run.py` (committed in e3d98af): builds
  `cr.CONFIGS` frames via `ld.build_deadline_frame(season, gw, strict=True,
  config, horizon=6)`, stages `_tmp_prices_{tag}.parquet` and
  `_tmp_frame_{config}.parquet`, solves via `sim.load_season / gw_slice /
  optimize_squad / solution_to_squad`, writes `db_write.write_run(...,
  recovered=True, note=...)`. Usage on the server:
  `docker compose run --rm --no-deps fpl-scheduler uv run python
  eval/backfill_recovered_run.py --season 2026-27 --gw 3 --note "…"`.
- Result: run_id 4, recovered, baseline, 3,934 prediction rows gw 3–8, Haaland
  (C) / Foden (V), cost 99.6; `get_picks` → run 4; `get_picks(shadow=True)` →
  the explicit error; `optimise()` solves from the new baseline frame in 1.0 s.
  Run 3 stays as history (every predictions row is keyed by run_id).

### 5.11 Off-list findings from task 9
- The two machines' volumes had drifted for a week (the 138-row diff).
- A stale `_tmp_frame_combined.parquet` (09-04) remains on the volume; nothing
  reads it.
- Postgres was recreated during the deploy (compose change) — expected.
- The DO console could not be tested by me.

---

## 6. The weekly ingest automation (commit ad056de) — complete code detail

Record: `Logs/weekly_ingest_automation_log.md` (numbers, schedule, evidence).
This section is the code map so the next chat can modify it without re-reading.

### 6.1 Why
The weekly ingest ran on the laptop by hand and was synced by tar/docker cp;
nothing on the server performed it. GW4 nearly built on history through GW2. A
weekly manual step nothing performs is the same class of problem as an unread
status file.

### 6.2 `eval/run_weekly_ingest.py` (758 lines) — structure

Constants:
```python
API = "https://fantasy.premierleague.com/api"
MAX_ATTEMPTS = 8       # 6-hourly cron -> two days of retries, then a standing FAILED
WINDOW_BEFORE_H = 3.0  # refuse to start inside deadline-3h ..
WINDOW_AFTER_H = 1.0   # .. deadline+1h (build + Postgres write are done by then)
STEP_TIMEOUT = 1800    # fetch_fpl_history: ~630 element-summary calls at 0.4 s
TICK_STALE_H = 13.0    # (documentary; model_tools uses the literal 13.0)
VOLATILE_COLS = ("pulled_at", "built_at")
```

Helpers: `utc_now()`, `stamp(dt)` → `YYYY-MM-DD HH:MM:SSZ`, `git_sha()` (reads
`.git/HEAD` + ref, no git binary in the image), `_fetch_json(path)` (delegates
to `fetch_fpl_history.get_json`: 3 tries, backoff, real UA),
`_atomic_write_text(path, text)` (tmp + `replace_with_retry`).

**Manifest (input hashes):**
- `live_inputs(data_dir, season)` — the 22 live-path inputs a deadline build
  reads: `history/all_seasons_fixed.parquet`, `fpl_api_{tag}`,
  `all_seasons_with_{tag}`, `forward_skeleton_{tag}` (+ `.provenance.json`),
  `understat_matches_{tag}`, `understat_season_aggregates` (+`_{tag}`,
  `_with_{tag}`), `crosswalk_{tag}.csv`, `odds_all_seasons`,
  `odds_fixtures_{tag}`, `odds_all_seasons_with_{tag}`,
  `availability_{short}.parquet` (2627), `live/availability_{tag}_live.parquet`,
  `live/availability_{season}_fplcache.parquet`, the prior season's
  `understat_matches_2025_26.parquet`, and the historical
  `availability_NNNN.parquet` files (regex `availability_\d{4}\.parquet` — the
  `availability_measurement_*` research files are excluded on purpose).
- `content_digest(path)` — parquet/csv only: drop `VOLATILE_COLS`, sort columns,
  `pd.util.hash_pandas_object(df, index=False)`, sort the row hashes, sha256 →
  `{digest, rows, cols}`. Order-independent and byte-independent (two pyarrow
  builds can write different bytes for the same rows).
- `manifest(data_dir, season, content=True)` → `{rel_path: None | {size, mtime,
  sha256, content}}`.
- `compare_manifests(a, b)` → `[(path, "present on one side only" | "bytes
  differ, content identical" | "content differs")]`.

**Checks:**
- `played_priced(slice_path)` → `{(Date, HomeTeam, AwayTeam): (H, D, A)}` for
  rows with `FTHG.notna() & B365H.notna()`; `prices_lost(before, after)` → list
  of missing/changed keys (tolerance 1e-9).
- `stack_collision(data_dir, season)` → sorted list of fixture ids present in
  both `all_seasons_with_{tag}` (this season) and `forward_skeleton_{tag}` — the
  same assert `season_stack.load_stack` makes, evaluated on the files.
- `crosswalk_map(path)` → `{element: understat_id(str)}`.
- `unmatched_with_minutes(data_dir, season, top=3)` → for every element with
  `minutes > 0` in `fpl_api_{tag}` and no crosswalk id: `{element, name, team,
  position, minutes, candidates:[{id, name, team, games, minutes, score,
  claimed_by}]}`; candidates by `rapidfuzz.fuzz.token_set_ratio` over
  `build_crosswalk._norm(name)` against the season's rows of
  `understat_season_aggregates_with_{tag}` (understat_season == season[:4]).
- `format_unmatched(items)` → the ACTION REQUIRED text (element line + candidate
  lines + the MANUAL-entry instruction; `[already claimed by element N]` tag).

**The plan — `plan(events, fixtures, have_gws, partial_gws, now, force_gw=None)`
→ `(decision, todo, detail)`:**
- `final` = event ids with `finished and data_checked`; `todo` = final gws not
  in `have_gws` OR in `partial_gws`; `force_gw` overrides todo.
- no todo → `"NOTHING-NEW"`.
- any event deadline with `dl-3h <= now <= dl+1h` → `"DEFERRED"` (reason text
  names the gameweek and window) — checked over ALL events, past and future.
- any fixture with `kickoff < now` and not (`finished` or
  (`finished_provisional` and `team_h_score is not None`)) → `"DEFERRED"`
  (in play / abandoned; `fetch_fixtures` would refuse anyway).
- else `"RUN"`. `detail` carries `final_gws, have_gws, partial_gws,
  next_deadline, next_unfinal, reason`.

**`class Runner(season, data_dir=None, run_cmd=None, fetch_json=None)`** —
`data_dir` defaults to `REPO/data`; `run_cmd(args, timeout) -> (code, output)`
defaults to `subprocess.run([sys.executable] + args, cwd=REPO, stdout=PIPE,
stderr=STDOUT, text, errors="replace", timeout)`; `fetch_json` defaults to the
API. Both injectable so the tests need no network and no real steps.
- Paths: `live = data_dir/live`; `INGEST_STATUS.txt`, `INGEST_TICK.txt`,
  `INGEST_RUN.log`; markers `ingest_gw{N}.partial.json` (written at chain start,
  removed on success) and `ingest_gw{N}.attempts.json` (`{attempts, last_failed,
  last_error}`; removed on success); manifests `ingest_manifest_gw{N}.json` and
  `ingest_manifest_latest.json`; per-gameweek copies `INGEST_GW{N}_STATUS.txt`,
  `INGEST_GW{N}_RUN.log`.
- `run_step(name, args, timeout)` — logs `===== name @ time =====`, the command
  line, the output, `===== name exit code N =====`; appends to `steps_run`;
  raises `RuntimeError("step '…' exited N. Last output: …")` on non-zero.
- `have_gws()` — GW set of `fpl_api_{tag}.parquet`; `partial_gws()` — from the
  marker files.
- `decide(now=None, force_gw=None)` — fetches `/bootstrap-static/` and
  `/fixtures/`, runs `plan`, stores `decision/todo/detail`.
- `outstanding_actions()` — recomputes `unmatched_with_minutes` and adds the
  ACTION REQUIRED block; called on every tick and at the end of every run.
- `run_chain()` — the work:
  1. attempt budget check (≥ MAX_ATTEMPTS → `failed = "GW{n}: … giving up …"`,
     return); write partial markers.
  2. BEFORE snapshot: `manifest`, `played_priced`, `crosswalk_map`.
  3. steps, in order: `fetch_fpl_history --gw N` (per todo gw) →
     `fetch_fpl_history --combine` → `understat_matches` →
     `build_understat_aggregates` → `… --combine` → `build_crosswalk` →
     `fetch_fixtures` → `fetch_fixtures --combine` → `fetch_live_odds` →
     `build_forward_skeleton` (LAST).
  4. strict post-checks: `prices_lost` → `failed = "PRICES LOST …"`;
     `stack_collision` → `failed = "SKELETON STALE …"`.
  5. sections: PRICES (before/after counts, provenance
     `prices_preserved_from_previous_slice`, the odds line parsed with
     `r"(\d+)/(\d+) events priced.*credits remaining (\d+)"`, upcoming priced),
     FORWARD SKELETON (from the provenance sidecar), MASTER INGEST (rows,
     fixtures, cross-check mismatches, data_checked from
     `fpl_api_{tag}.provenance.json`), UNDERSTAT (matches per gw vs fixtures per
     gw → WARNING for lagging gws; deferred list from the provenance), CROSSWALK
     (ids before → after, gained/lost/CHANGED, the builder's stats lines);
     ACTION REQUIRED "id CHANGED or LOST for a playing element" when applicable;
     `outstanding_actions()`.
  6. AFTER manifest; `changed` = paths differing before→after; manifest written
     (`{season, gws_ingested, written, git, host, before, after, changed}`);
     INPUT HASHES section.
  7. success: remove partial + attempts markers.
- `finish()` — on failure increments the attempts sidecar (partial marker kept).
- `execute()` — `try: run_chain() except Exception: failed = traceback[-3000:]
  finally: finish(); write_status()`; returns the status first line.
- `write_status()` — first line `FAILED` | `SUCCESS -- ACTION REQUIRED (n items,
  see below)` | `SUCCESS`; header line `weekly ingest {season} -- written {utc}
  -- git {sha} -- data {dir}`; `gameweek(s) ingested this run: [...]`; on failure
  a `FAILURE:` block and a spelled-out CONSEQUENCE paragraph (skeleton may be
  stale → the next deadline build FAILS on the collision assert, by design);
  then every `== ACTION REQUIRED: … ==` block, then the ordinary `== … ==`
  sections, then `Full step output: INGEST_RUN.log`. Copies to the per-gw files.
- `write_tick(first, body)` — the tick file: first line, header, the plan
  detail lines, and (for NOTHING-NEW/DEFERRED) the outstanding ACTION REQUIRED
  blocks; ends with `Last run with work: INGEST_STATUS.txt (exists|none yet)`.

**`main(argv)`** — `--season` (required), `--force-gw N`, `--hash-only`,
`--data-dir` (tests). `--hash-only` prints `{season, host, git, written,
manifest}` and exits 0. Otherwise: `decide()` (an exception here → tick file
`FAILED -- could not decide (API unreachable?)`, exit 1, volume untouched);
NOTHING-NEW/DEFERRED → tick file (with outstanding actions), exit 0; RUN → tick
`RUNNING gameweek(s) [..] -- see INGEST_STATUS.txt`, `execute()`, tick `RAN
gameweek(s) [..] -> {first}`, exit 1 iff failed.

**Status first-line contract (machine-readable first token):** `SUCCESS`,
`FAILED`, `NOTHING-NEW`, `DEFERRED`, `RUNNING`, `RAN` (tick only).

### 6.3 `/health` hook — `model_tools.py`
New `_weekly_ingest_status(reasons)` returns `{"last_run": {first_line,
age_hours} | None, "last_tick": {...} | None}` from `data/live/INGEST_STATUS.txt`
/ `INGEST_TICK.txt` and appends reasons: `weekly ingest FAILED -- …` (first line
starts with FAILED); `weekly ingest needs a human: …` (ACTION REQUIRED in either
first line); `weekly ingest has never ticked on this volume (cron not
installed?)`; `weekly ingest cron has not ticked for Nh (every 6h expected)`
(tick older than 13 h). Wired as
`freshness["weekly_ingest"] = _weekly_ingest_status(reasons)` inside `health()`
(before the next-deadline block). Any reason → `status: degraded`.

### 6.4 Tests — `Tests/test_weekly_ingest.py` (17, no network, ~2 s)
`_events(final_through, next_gw, deadline)` fakes bootstrap events; `_fixtures(in_play)`
fakes `/fixtures/`; `_seed(tmp_path, gws, priced_played, crosswalk_missing)`
writes a tiny schema-faithful data dir (fpl_api + provenance, all_seasons_with,
crosswalk csv, aggregates_with, understat_matches, odds slice + provenance,
skeleton + provenance); `FakeSteps(h, fail_at, drop_prices, collide, new_gw)` is
a `run_cmd` that records the step names (`fetch_fpl_history`,
`fetch_fpl_history_combine`, …) and writes the files a real step would.
Tests: nothing-new / final-uningested todo / not-yet-data_checked not todo /
deadline window defers (T-95, +30 min, +2 h) / in-play defers / success runs the
exact runbook order and writes the sections / step failure stops, counts the
attempt, keeps the partial marker, next tick re-runs GW4 / attempt budget gives
up loudly / PRICES LOST strict stop / SKELETON STALE strict stop / unmatched
element is an ACTION REQUIRED block ABOVE `== PRICES` with Savio's candidate
11735 / unmatched re-listed on a no-work tick / changed id is the alarm /
manifest hashes every input before and after / content digest is order- and
byte-independent / first-line contract via `plan()` / content digest ignores
`pulled_at`.

### 6.5 `docker-compose.yml`
Comment only (scheduler block): three cron jobs use the scheduler service; the
weekly ingest holds the dispatcher's lock and refuses to start inside a deadline
window. No service change.

### 6.6 Server cron (root crontab, UTC) — installed 2026-09-11 22:15Z
```
17 */6 * * * cd /root/fpl-copilot && flock -n /tmp/fpl-ingest.lock flock -n /tmp/fpl-dispatch.lock docker compose run --rm fpl-scheduler uv run python eval/run_weekly_ingest.py --season 2026-27 >> /var/log/fpl-ingest.log 2>&1
```
(Verbatim from `crontab -l`; the comment block above it in the crontab explains
the gates.) Backup of the previous crontab: `/root/crontab.bak-2026-09-11`. Existing lines unchanged: poller
`*/10` under `/tmp/fpl-poller.lock`, dispatcher `*/10` under
`/tmp/fpl-dispatch.lock`, logs `/var/log/fpl-poller.log`, `/var/log/fpl-dispatch.log`.
- Fires 00:17 / 06:17 / 12:17 / 18:17Z. `:17` is off the :00/:10 ticks.
- **Collision avoidance**: (a) the ingest takes the DISPATCHER's lock, so a
  build tick during the ~6-minute rewrite fails `flock -n` and fires 10 minutes
  later — observed: the forced run held it 22:15–22:21Z and the 22:20 dispatcher
  tick left no log line; (b) the runner's own window gate (deadline−3h..+1h)
  makes the overlap impossible even without the lock; (c) the poller touches only
  `live/bootstrap_raw` and the changes file, no lock needed.
- GW5 (Fri 17:30Z): window 14:30–18:30Z; the 12:17 and 18:17 ticks are outside it.

### 6.7 Evidence
- **Laptop `--force-gw 3`** (22:02:49–22:09:21Z): 10 steps exit 0; GW3 654 rows,
  0 cross-check mismatches; Understat 30 matches 10/10/10, 0 deferred; crosswalk
  387→387, 0 gained/lost/changed; prices 10/10 played identical,
  `prices_preserved_from_previous_slice=30`, 20/20 upcoming, credits 19,327;
  skeleton 22,960 rows gws 4..38, 0 collisions; no ACTION REQUIRED; the
  `fpl_api_2026_27` content digest was UNCHANGED by the re-pull (idempotent).
- **Suite 249 passed** (233 + 16 then 17).
- Pushed ad056de; deploy landed (server HEAD ad056de, image contains the script,
  /health ok at ad056de6a with the `weekly_ingest` block).
- **Volume backup before the first server ingest**:
  `/root/backups/model_data_live_subset_2026-09-11_pre_ingest.tgz` (18.1 MB,
  sha256 55020fdf4ad732a4…) — history/*2026_27*, the archives, availability_2627,
  live/*.txt|parquet|json.
- **Server `--force-gw 3`** (22:15:24–22:21:41Z) inside the scheduler image
  under both locks: SUCCESS, same figures, credits 19,326; the 10 GW3 Understat
  matches were fetched from the droplet IP at 1 req/s (the server's raw cache
  had only GW1–2) — Understat did not block it.
- **GW4 strict baseline build on the server after the ingest**: PASSED, 3,936
  rows, gws 4–9, 32 s, notes only (calendar re-pull matches the new snapshot).
- **Cron command string run once under `sh` as root**: exit 0, NOTHING-NEW tick,
  one line in `/var/log/fpl-ingest.log`. **The 00:17Z firing itself was not
  observed** (the session ended before it).
- **Hash check laptop vs server after both runs**: 19/22 content-identical
  (archive, fpl_api, all_seasons_with, skeleton parquet, Understat matches and
  aggregates, crosswalk, odds archive, every availability file; crosswalk csv
  and understat_matches differ in bytes only); 3 differ in content and must:
  `odds_fixtures_2026_27` + its combined file (two pulls 12 min apart) and the
  skeleton provenance sidecar (pull time + calendar snapshot).
- Final /health (23:15Z): `ok`, `git_sha 07a7266fa`, `weekly_ingest {last_run:
  SUCCESS 0.9h, last_tick: NOTHING-NEW 0.9h}`, `reasons []`.

### 6.8 What a maintainer sees each week / on failure
Normal: `/health` ok; tick file NOTHING-NEW three times a day until FPL flags the
gameweek (roughly a day after its last match), then `RAN gameweek(s) [N] ->
SUCCESS`; `INGEST_STATUS.txt` with the sections; the next deadline builds on a
master that includes GW N.
Human needed: first line `SUCCESS -- ACTION REQUIRED (n items)`, /health
degraded with the same line; the block names element, club, position, minutes,
candidates. Fix = evidenced `MANUAL["2026-27"]` entry in
`eval/build_crosswalk.py`, pushed; the next tick's rebuild clears it. Until then
the element rides the positional prior (strict raises only if it reaches the top
30 by e_points).
Step fails: chain stops; FAILED status with step/exit/last output + the
consequence; /health degraded; attempts +1; partial marker kept; next 6-hourly
tick retries the idempotent chain; after 8 attempts a standing FAILED "giving
up" — re-arm by deleting `ingest_gwN.attempts.json` or running `--force-gw N`.
API unreachable at decide time: tick `FAILED -- could not decide`, volume
untouched, retry next tick.

### 6.9 Not done / unknowns (weekly ingest)
- First real cron firing unobserved (00:17Z 2026-09-12). Check
  `/var/log/fpl-ingest.log` and `/health … weekly_ingest.last_tick` the next day.
- Out of the six-step scope: `merge_live_availability` (the deadline runner does
  it at T-90) and the fplcache availability file (laptop-built from the fplcache
  clone, last 2026-08-29; the poller is authoritative for every live gameweek).
- A fixture moved between an ingest and a deadline still fails the T-90 build by
  design (three attempts, 1 credit each). `--force-gw <last gw>` outside the
  window refreshes the skeleton by hand.
- **The laptop's 2026-27 files are stale from the first server ingest.** Sync
  DOWN (docker cp / tar from the volume) before laptop-side tests that read them;
  compare `--hash-only` manifests first. Never sync UP again.
- Understat from the droplet worked (11 requests). A 403/429 is a hard stop in
  the fetcher, surfaces as FAILED, retries 6 h later.

---

## 7. Server inventory at the end of the session

- Containers: `fpl-copilot` (api, port 8000, image `fpl-copilot`),
  `fpl-postgres` (postgres:16-alpine, healthy, no host port), `fpl-scheduler`
  (profile-gated, `docker compose run --rm`). Disk 44% used; Docker build cache
  25.9 GB reclaimable (unguarded item: no prune scheduled).
- Cron (root): poller `*/10`, dispatcher `*/10`, ingest `17 */6`. Locks in `/tmp`.
- Volume `live/`: `GW3_BUILD_STATUS.txt` (the 2026-09-04 FAILED-then-recovered
  run), `GW3_RECOVERY_provenance.json`, `INGEST_STATUS.txt`/`INGEST_TICK.txt`/
  `INGEST_RUN.log`/`INGEST_GW3_*`, `ingest_manifest_gw3.json`/`_latest.json`,
  `_tmp_frame_baseline.parquet` (needed by `optimise()`), `_tmp_prices_2026_27.parquet`,
  stale `_tmp_frame_combined.parquet` (09-04, harmless), `gw3_frame_*` and
  `gw4_frame_baseline_SERVER_precheck.parquet` verification copies,
  `availability_2026_27_live.parquet` (poller build), `availability_2026-27_fplcache.parquet`,
  `bootstrap_raw/`, `shadow_2026_27.jsonl`.
- Backups: `/root/backups/fpl_backup_2026-08-31.dump` (pgdata),
  `/root/backups/model_data_live_subset_2026-09-11_pre_ingest.tgz`,
  `/root/crontab.bak-2026-09-11`, `/root/50-cloud-init.conf.bak-2026-09-11`.
- The unguarded list from Logs/server_pipeline_migration_log.md §6 still stands
  except item 1 (nobody reads the status file) is now partially covered by
  /health degrading on ingest FAILED/ACTION REQUIRED/dead cron: no alerting; no
  deploy smoke gate; image accumulation; .env baked into the image (`COPY . .`,
  no .dockerignore); unbounded `/var/log/fpl-*.log`; no volume backup schedule.

---

## 8. Gotchas learned this session (cheap to keep)

- **SSH**: only `deploy_key_new` in the repo root works; `~/.ssh` has no key.
  The Claude Code auto-mode classifier refused a transcript grep for the key
  variable ("credential exploration") — find the key via `.gitignore` +
  `ls`, never by grepping secrets.
- Background long runs from the tool get killed at ~10 min: launch detached via
  a PowerShell `Start-Process` launcher script writing to a log, then poll.
- `docker compose run` inside an `ssh … 'nohup … &'` keeps the ssh session
  open; launch it and let the tool background it, then poll a log file.
- `docker compose run --rm --no-deps fpl-scheduler uv run python -c "…"` is the
  way to run one-off Python against the volume with the image's dependencies
  (`sys.path.insert(0, "squad")` first).
- Cron `17 */6` fires at hours 0/6/12/18 — not "six hours from install".
- `tar` with a `C:/…` path thinks it is a remote host.
- `pd.util.hash_pandas_object` fails on array-valued object columns (the
  research `availability_measurement_logs_*` files) — that is why they are
  excluded from the manifest.
- The runner's subprocess output is captured with `PIPE` and only lands in the
  run log when the step ends — no live progress inside a step.
- Heredocs that are too long hit ENAMETOOLONG in the Bash tool; use the Write tool.

---

## 9. Rules that must not be quietly dropped (unchanged; restated)

No adoption decision may cite season totals. Bars are stated before any number
is seen. Parity (three cutoffs, both configs, bit-identical) is the gate for
anything touching the model path, and it cannot see shared-input leaks — the
as-of guard is the other gate and must reconstruct every input. Silent fallbacks
are the enemy; strict mode raises. The laptop runs the suite; the server does
not. data_checked gating stays. No holdout exists from 2026-08-27 onward. A
backtest figure is not a live expectation. **Modelling is closed** — the levers
are UNSETTLED, and re-opening either is a new pre-registration on clean frames.
New this session: **no reproduction claim without hashing the inputs first**
(`run_weekly_ingest.py --hash-only` on both machines, compare content digests).

---

## 10. Next steps, in order

1. **GW4, Sat 2026-09-12**: check `/health` after 11:00Z — strict raised?,
   `last_run.gw == 4`, `started_at` filled, squad sane. Read
   `data/live/GW4_BUILD_STATUS.txt` on the volume. This is the first solo run on
   baseline. Also confirm the ingest cron ticked at 00:17Z and 06:17Z
   (`/var/log/fpl-ingest.log`, `weekly_ingest.last_tick.age_hours < 13`).
2. **GW4 ingest** will happen automatically once FPL flags it data_checked
   (~Tue 2026-09-15). Read `INGEST_STATUS.txt`: expect `SUCCESS`, possibly
   `ACTION REQUIRED` for a debutant without an Understat id — add the evidenced
   MANUAL entry and push.
3. Decide the odds subscription before 2026-09-24 (paid pool; only h2h is used).
4. Retire the laptop's scheduled tasks once the server has earned it (the
   2026-09-10 handoff said keep them armed for one gameweek as a comparison).
5. The standing unguarded items (§7): a deploy smoke gate on /health, docker
   prune, logrotate, .dockerignore for .env, a volume backup schedule.
6. Squad state (the biggest unlock per the previous handoff §9.3) — a NEW task,
   not modelling.
