# Progress notes — 2026-08-17, updated 2026-08-18 (status against the Interim project plan)

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
| **D4** | Synthetic forward odds | **UNSTARTED.** Entry gate (D3) is now satisfied. |

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
