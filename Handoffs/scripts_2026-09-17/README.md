# Scratch scripts and result files from the 2026-09-13 → 2026-09-17 session (archived 2026-09-17)

These lived in the Claude Code session scratchpad and are copied here verbatim so the next session can rerun or
read them. Paths inside them point at `C:\dev\fpl-copilot` (the repo) and at the old scratchpad directory for
their OUTPUTS (`HERE = Path(__file__).resolve().parent`, so run from this folder and outputs land here). The
reference-build parquet files (~16 MB each) were NOT copied; regenerate them (≈ 12 min for three seasons in
parallel on the laptop, more under CPU contention). Nothing here is on the model path; nothing here is imported
by the app.

## Dixon-Coles cold start: prereg v2 / v3 (branch `hinge-box-v2`)

| file | what it does | log |
|---|---|---|
| `gauge_probe.py` | the record fit's gauge: sum(atk) = sum(dfc), league mean attack ≈ +0.09 (finding 1(a)) | `Logs/dc_shrinkage_v2_log_2026-09-17.md` §1(a) |
| `refbuild_v2.py` | reference build of one season's canonical with the code AS IT STANDS on the checked-out branch; env `REF_PREFIX` (default `ref_v2`; `ref_v3` used for v3); logs one `LAST_FIT` per cutoff to `<prefix>_<tag>_fits.json` | v2 log §2, v3 log §2 |
| `refbuild_v2s.py` | v2 sensitivity rows: `<season> <label> <N> <tau0> <bound|none> [cutoffs...]` (sets `dc.SHRINK_N` etc. in-process) | v2 log §2.3 |
| `refbuild_v3s.py` | v3 sensitivity rows: `<season> <label> <mu_atk> <mu_dfc> [cutoffs...]` (sets `dc.MU_PROMOTED_*`) | v3 log §2.4 |
| `v2_endpoint.py` | THE pre-registered endpoint + gates (affected cells, pooled Δ with SE, per-season own-SE, step-0 p_cs with the calendar-based opponent map, unaffected-cutoff bit-identity, λ bounds, convergence, margins, the v3 FALSIFIED/MARGINAL/PASS rule); env `V2_PREFIX` selects the build; writes `v2_endpoint_<prefix>.json` | v2 log §2, v3 log §2 |
| `v2_summary.py` | one-line summary per endpoint JSON | — |
| `top30_driver.py` | where the top-30 movement comes from: the affected club's players in each cell's top 30 (env `V2_PREFIX`) | v2 log §2.2, v3 log §2.3 |
| `tell_pcs.py` | investigates a step-0 p_cs tell: per-cutoff max on clean rows, the worst row, a refit on/off with parameter diffs | v2 log §1(d), §2.1 |
| `promoted_centre.py`, `promoted_centre.csv` | the v3 centre: every promoted cohort's first-season centred attack/defence (27 clubs, 9 cohorts) | `Logs/dc_shrinkage_v3_prereg_2026-09-17.md` §1 |
| `v3_tables.py` | the v3 design tables: the scoreless-club MAP at n = 1..12 under centre 0 and the promoted centre; the record's three cold starts at cutoffs 1–6 under plain / v2 / v3 (self-contained fit) | v3 prereg §2 |
| `neff_by_cutoff.py`, `param_ranges.py` | the v1/v2 design inputs: n_eff by cutoff for the no-history clubs; the record's fitted parameter ranges by evidence | `Logs/dc_shrinkage_threshold_prereg_2026-09-14.md` §1, v2 prereg §0 |
| `patch_v2_fit.py`, `patch_v2_tests.py`, `patch_v3.py` | the patch scripts that produced the branch's code (kept for the record of what was changed; the branch is the source of truth) | — |
| `log_s2.py`, `log_v3_s3.py`, `docs_v3_status.py` | the scripts that wrote the log sections (text lives in the logs) | — |
| `rebuild_hinge.ps1` | THE adoption rebuild script (never run): preserves every artefact as `*_pre_hinge`, then canonical → gap0 arm frames → record armlogs per season; usage `powershell -File rebuild_hinge.ps1 -Season 2025-26` | v2 prereg §5 step 3 |
| `rebuild_dcfix.ps1`, `guard_dcfix.ps1` | the 2026-09-13 DC-fix rebuild and as-of guard runners (`_pre_dcfix`); the templates for the above | `Logs/dc_fix_log_2026-09-13.md` |
| `v2_endpoint_ref_*.json` | the endpoint results verbatim: `ref_v2` (the v2 form), `ref_v3` (the v3 form), `ref_n6`/`ref_n15`/`ref_tau28`/`ref_box3`/`ref_box6` (v2 sensitivity), `ref_c6coh`/`ref_half`/`ref_atkonly` (v3 sensitivity) | v2 log §2.2–2.3, v3 log §2.2–2.4 |
| `ref_v2_*_fits.json`, `ref_v3_*_fits.json` | one `LAST_FIT` per cutoff of the primary builds (provenance stamps, clubs below N, at_bound, margins, method) | — |

## The k = 4 prior (2026-09-13/14, FALSIFIED)

`refbuild_shrink.py`, `shrink_endpoint.py`, `shrink_endpoint_k{2,4,8}.json` — `Logs/dc_shrinkage_log_2026-09-13.md`.

## The DC cutoff-day fix (2026-09-13)

`rank_endpoint.py` (the fix's rank endpoint), `cutoff_probe.py`, `leak_size_experiment.py` + `leak_size_results.json`
(LEAKAGE item 7 measurement), `direction_check.py`, `bar1_live_proof.py`, `bar1b_probe.py`, `pin_cells.py`,
`patch_index.py` — `Logs/dc_fix_log_2026-09-13.md`.

## Server proofs and checks (run against the deployed image over ssh + `docker compose run`)

`proof_loud.py` (the loud detector on Coventry's real λ), `proof_dispatch_stall.py` (deadline slots under a stalled
FPL with a fake clock), `proof_explain.py`, `proof_terms.py`, `proof_runs.py`, `proof_schedule.py`,
`tuesday_full.py` + `tuesday_full.out`, `tuesday_checks.py`. Pattern:
`ssh -i deploy_key_new root@68.183.131.154 'cd /root/fpl-copilot && docker compose run --rm --no-deps -T fpl-scheduler uv run python -' < script.py`.

## Agent prompt verification transcripts (2026-09-14/15)

`chat_case.py` (drives `/chat` on the server with `/reset` first) and `before_*`, `after_*`, `after2_*` — the four
cases (false premise, plain compare, full breakdown, self-consistency) before and after the prompt edits —
`Logs/agent_system_prompt_log.md`.
