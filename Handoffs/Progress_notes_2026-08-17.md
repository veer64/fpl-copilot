# Progress notes — 2026-08-17, updated 2026-08-21 (status against the Interim project plan)

The Interim project plan lives in `Handoffs/Interim project plan.docx`; these
notes record status against its task list as of the close of the D1 work.
(The .docx itself is untouched — it is the plan of record as written; this
file is the running status.)

| Item | Plan definition | Status |
|---|---|---|
| **M1** | EV evaluator ("equity scoring") + both ladders — the gate | **FAILED.** Pre-registered protocol run; did not pass. Season-level evaluation stays infeasible; all evaluation is on component/decision metrics (see `Logs/instrument_b_log.md`, master-plan M1 sections). |
| **M2** | Multi-season replication | **PARTIALLY COMPLETE.** Three seasons live (2023-24, 2024-25, 2025-26), walk-forward capable with full provenance stamps. 2021-22 and 2022-23 are NOT portable — standing decision, KNOWN_ISSUES #11. |
| **M3** | One deliberate baseline migration | **COMPLETE** (2026-08-14): availability=True, per-fixture DGW grain, odds horizon 0 adopted together; pre-migration artefact preserved. |
| **D1** | Four missing scoring terms + penalty share | **COMPLETE — closed 2026-08-17.** Adopted as Variant B (cards as prior-season position rates; per-player rolling cards measured harmful and excluded). Full record: `Logs/d1_log.md`. Final config stamped in every artefact: `d1_terms_active=True`, `cs_unified=False`, 0.2 CS blend retained, availability=True, odds horizon 0, per-fixture DGW, hit bar 4, post-audit crosswalk incl. the Sheffield fix (KNOWN_ISSUES #14). |
| **D2** | Understat per-match npxG pull | **COMPLETE — adopted 2026-08-18** (Phases 1–3). Per-match data pulled and verified for four seasons (`eval/understat_matches.py`, incremental-by-design); k=8 cross-season blend tuned on 2023-24/2024-25, pre-registered, replicated on sealed 2025-26 (npxG ρ 0.461→0.559); integrated as the production rate source (`rate_blend_active=True` stamped). Full record: `Logs/rate_blend_log.md`. OPEN: cold start for the ~32% no-prior players is untouched. |
| **D3** | DGW prediction audit | **COMPLETE.** Per-fixture grain closed the three DGW under-counting defects; doubles counted and guarded by test (`test_doubles_are_counted`, 409 doubled player-gameweeks at horizon 0 in 2025-26). |
| **D4** | Synthetic forward odds | **CLOSED 2026-08-20 — NOT adopted.** Phase 1 succeeded as a modelling result (sealed 2025-26 R² 0.851 vs DC-alone 0.595, +0.10 edge sustained across horizon steps 1–6, pre-registered, independently leakage-audited). Phase 2 found no pipeline benefit on three independent grains: forward-step accuracy flat, top-k at/below chance, per-decision corr(pred gain, real gain) 0.301 base vs 0.264 synth, paired sign test 11–16 (p=0.442). Durable finding: forward-step degradation is minutes/form-driven, not fixture-driven — future horizon work redirects there. One consistent effect: MID/FWD margin β toward 1 and GK/DEF away in 60/60 cells each — the GK-investigation H1 double-count signature from an independent intervention. Code/model retained behind `synthetic_lambda_active=False`; retest if minutes-at-horizon improves. Full record: `Logs/d4_market_lambda_log.md` (§13 closure), `Logs/overnight_2026-08-19_log.md`. |
| **D5** | Player-prop odds evaluation | **UNSTARTED — blocked on the spend decision** (~$100–300 evaluation month; see 2026-08-20 section below). |
| **Phase P** | Policy work | **P4 chips ADOPTED 2026-08-20** (rules of record: p4_chip_policy_log.md §12; standard config now H=6 decay=0.45, §13; bench-aware BB on). **P1 CLOSED 2026-08-21 — NOT adopted** (both steps built and measured; gates rest False; Logs/p1_opening_log.md §0). **P2 adopted via P4** (the early wildcard IS the opening-squad fix — WC1 rule of record GW4–5). P3, P5 unstarted. |

## Open workstream carried past D1

**Goalkeeper investigation — OPEN** (`Logs/gk_investigation_log.md`, §9 for
current status). Three steps run: H3 weakened (baselines stable ~0.8 on
corrected data), H1 refined (the CS/conceded redundancy is a property of the
rules; the market-λ spread across GKs looks wider than realised margins
resolve), CS-unification tested and reverted as a clean negative. Two live
options recorded, with the constraint that any λ-spread shrink is a new
tunable that must be tuned on 2024-25/2023-24 only — 2025-26 is the sealed
test season.

## Incidents recorded this cycle (KNOWN_ISSUES)

- **#13** — D1 entered assembly.py before "baseline" measurements ran;
  margin-calibration and hit-threshold logs retracted; `d1_terms_active`
  stamp + guard added.
- **#14** — "Sheffield United"/"Sheffield Utd" join failure manufactured a
  season of zero predictions in 2023-24; fixed (TEAM_MAP + per-team guard +
  neutral fill), 2023-24 rebuilt, record corrected in place.

Both are the same silent-fallback family as #10; the pattern and lesson are
written up in #14.

## Adopted 2026-08-19/20 (outside the D-item list)

- **DC-wiring fix (KNOWN_ISSUES #15):** walkforward_season.py passed an empty
  defensive-contribution frame even for 2025-26, so every canonical file
  priced the DC rule at position base rates (max 0.136) instead of the
  per-player model (max ~0.80). Fixed at the root: one shared path
  (`defensive.get_dc_hits`) in BOTH writers; guarded by
  `Tests/test_dc_hits_wiring.py`; canonical files rebuilt (pre-fix preserved
  as `*_dcbase.parquet`; 2023-24/2024-25 verified bit-identical — the fix is
  2025-26-only in effect). New 2025-26 step-0 baseline: agg ρ 0.7471 /
  MAE 1.0732; starter-band ρ GK 0.190, DEF 0.285, MID 0.214, FWD 0.157.
  Logs quoting the older 2025-26 figures are superseded (see #15).

## D6 / D5 / D7 status (2026-08-20)

- **D6 free half (live availability poller): BUILT AND PARKED.**
  `eval/poll_availability.py` + `Logs/d6_live_availability_log.md`. One live
  smoke test scheduled: GW1 2026-27 window (2026-08-21, deadline 17:30 UTC),
  run manually via `--watch` from ~13:30 UTC; afterward-checklist in log §8.
  No scheduler, no ongoing operation, no integration — production wiring
  deferred (droplet is the likely home; log §7 records the options and why
  the value cannot be measured retrospectively). Expected magnitude ~47
  rows/season (42 a→not-a flips).
- **D6 paid half (FFS / Rotowire subscriptions): UNSTARTED.**
- **D5 (player-prop odds): still BLOCKED on the spend decision
  (~$100–300 evaluation month).**
- **D7: skip list — no work, by design.**

## 2026-08-21 — P1 closed; full-system reference run complete

- **P1 (opening squad) CLOSED, NOT adopted.** Step 1 (horizon opening) and
  Step 2 (scenario-robust solve, K=50 + one-repair-per-week recourse) both
  built, measured on three seasons and under the full system, and left off —
  `OPENING_HORIZON_ACTIVE` / `OPENING_ROBUST_ACTIVE` rest False. Decision
  and reasoning: `Logs/p1_opening_log.md` §0 (mechanism works / endpoints
  mixed; robust solve collapses to expectation; the repeatable finding is
  substitution — the early wildcard already solves the opening-squad
  problem; simplicity counted as a criterion after five silent-fallback
  incidents). Untried levers recorded there: correlated failure scenarios,
  CVaR objective.
- **Full-system reference run (24 sims):** 2 openings × WC1 {2,4,6,8} × 3
  seasons with all supportable chips (WC2/FH2/TC1/TC2, BB1+BB2 bench-aware —
  the simulator now takes one Bench Boost per half). Every cell clears the
  FPL average manager, chip-inclusive +99 to +437 (`Logs/p1_opening_log.md`
  §8). Standard framing: identifies configs, ranks nothing. BB1 on single
  fixtures measured free-to-slightly-positive (~+10 bench, no detectable
  build-toward cost).
- **OPEN QUESTION carried forward:** the wildcard-week rule of record is
  GW4–5 (p4_chip_policy_log.md §12), but the 42-sim isolated grid AND the
  full-system grid both put the GW2 anchor positive in six of six
  season×opening arms (~+41 mean at W=3), with GW4 negative in most arms.
  Review queued (p4 log §12a); any revision must note that a GW2 wildcard
  partly substitutes for opening-squad quality.
