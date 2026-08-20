# Handoff — 2026-08-20: D4 closed, P4 adopted, standard config changed

**Covers:** the D4 synthetic-odds arc (closed, not adopted), the #15
DC-wiring fix (adopted), the P4 chip policy (ADOPTED, with rules of record),
the new standard config H=6/decay=0.45 (ADOPTED), the D6 live poller (built,
parked), and the read-only analyses that closed the week (season-totals
index, late-news cost, captaincy).

**Read first:** §1 (adopted state), §5 (open threads), §6 (traps).

---

## 1. ADOPTED STATE — what the code does right now

| Constant | Location | Value | Meaning |
|---|---|---|---|
| `D1_TERMS_ACTIVE` | squad/assembly.py | True | D1 scoring terms (since 2026-08-17) |
| `CS_UNIFIED` | squad/assembly.py | False | 0.2-blend CS retained |
| `RATE_BLEND_ACTIVE` / `K` | squad/attacking_rates.py | True / 8.0 | D2 cross-season blend |
| `SYNTHETIC_LAMBDA_ACTIVE` | squad/synthetic_lambda.py | **False** | D4 tested, NOT adopted; serving path retained |
| `BENCH_BOOST_AWARE` | squad/transfer_mip.py | **True** | ADOPTED 2026-08-20; inert unless a BB is scheduled |
| `DEFAULT_HORIZON` / `DEFAULT_DECAY` | squad/transfer_mip.py | 6 / **0.45** | ADOPTED 2026-08-20, mechanism-based (P4 log §13) |

Every walk-forward artefact stamps the equation flags; every simulator
decision log now stamps `horizon`, `decay`, `bench_boost_aware`,
`bench_boost_gw`. Canonical files: `walkforward_h6_{2023_24,2024_25,
2025_26}.parquet`, post-#15 rebuild (per-player defensive contribution).
Test suite: 113 passed, 5 skipped (the dormant 2526-fingerprint guards).

**Chip policy of record (P4 log §12):** WC1 policy-fixed GW4–5; WC2 at the
pre-DGW-cluster swing week; BB2 at the biggest second-half double (floor ≥4
teams), bench-aware; FH2 at the largest blank (floor ≥4 — NEVER below, it
measured −20); TC2 at the biggest DGW; TC1 at the GW1–19
captain-predicted-points peak (+10.3); BB1 only where a real first-half
double exists. Measured at the adopted config: +78 / **loses in 2024-25** /
+67 chip-inclusive vs own baselines.

## 2. What M1's failure means for measurement (unchanged, load-bearing)

Season totals CANNOT rank anything: path noise sd ≈ 60, and the paired-diff
sd between two arms is √2·60 ≈ 85 — pairing cancels nothing (measured again
in the D4 sign test). Everything is decided on component metrics, windowed
paired deltas at the intervention (Instrument A conventions,
squad/pathcontrol.py; no intervals below 8 active anchors), or
pre-registered sealed-season protocols. `Logs/season_totals_index.md` now
holds every season total ever produced, grouped into provenance families
with the exhaustive list of valid comparisons.

## 3. The silent-fallback family — four incidents, and the discipline

#10 (availability default), #13 (D1 stamp), #14 (Sheffield join → zeros),
#15 (empty DC frame → position base rates). The pattern: a legitimate
per-row fallback becomes a silent whole-population default when an input is
empty at the frame grain. The guards now in place: every equation flag is
one constant + a stamp in the artefact; provenance is checked before any
two files are compared (this caught a wrong-writer build before a single
number was read); fallbacks get loud guards at the grain they can fail at;
canonical rebuilds preserve the old file under a descriptive suffix.
Trap: "DC" means BOTH defensive contribution (defensive.py, p_dc_hit) and
Dixon-Coles (dixon_coles.py, team goals). Name the module.

## 4. Adopted vs tested-and-rejected

**Adopted:** D1 Variant B; D2 k=8 blend; #15 fix; P4 chip policy;
bench-aware BB; H=6/decay 0.45; provenance stamps everywhere.
**Tested and rejected (records in the logs):** CS unification (clean
negative); per-player rolling cards (harmful; Variant B instead); D4
synthetic λ in the pipeline (three grains agree: no benefit; the λ-model
itself is GOOD — sealed R² 0.851 vs 0.595 — and the mechanism finding is
that forward-step decay is minutes/form-driven, not fixture-driven);
per-player bench weights (−187, double-counts availability); per-transfer
minimum-gain filter (destroys combination moves); FH below the 4-team floor
(−20); captaincy alternatives (p60-weighted, p_start-filtered,
DGW-restricted — none beats argmax e_points across seasons).
**Built and parked:** D6 free-half live poller (eval/poll_availability.py,
GW1 2026-27 smoke test planned; production wiring deferred — droplet).

## 5. OPEN THREADS

1. **2024-25's reproducible failure.** Third independent appearance:
   chips/reshuffles LOSE in 2024-25 in every family (both decays, the
   bench-aware run) while gaining in the other seasons. Diagnosis of
   record: reshuffle-into-error — that season's late predictions punish any
   forced rebuild. Understanding WHY 2024-25's late-season predictions are
   worse is the concrete next investigation (note: it also has the highest
   baseline anywhere, 2362 — the no-churn path was excellent).
2. **Goalkeeper investigation** (Logs/gk_investigation_log.md §9, two live
   options). New corroboration: D4's margin-β structure (MID/FWD toward 1,
   GK/DEF away, 60/60 cells) is the H1 double-count signature from an
   independent intervention.
3. **Captaincy: the gap is mostly irreducible variance.** Hindsight gap
   ~215/season; captain is best-in-15 ~25% of weeks; NO tested alternative
   beats argmax e_points across seasons; the gap tracks prediction quality
   (2024-25: best predictions, smallest gap). The one theoretical opening —
   variance-seeking captaincy needs distributional predictions — is the
   plan's cut Phase 3 and stays cut absent a pre-registered case.
4. **Late-news cost is NOT the blind window.** All 52
   predicted-60/played-0 cases across three seasons were unknowable at the
   deadline (news post-deadline or pure rotation) — net ~29 pts/season plus
   ~29/season captain counterfactual. D6's poller cannot catch these (the
   backtest already consumes asof = deadline-truth). The route to this cost
   is predicted-lineup data (D6 paid half / D5 props) or rotation
   modelling.
5. Older threads unchanged: D2 cold start (~32% no-prior); M1
   kill-criterion record; live-season freeze decision; d1_log §8 and
   related logs still quote pre-#15 2025-26 figures (KNOWN_ISSUES #15
   lists the surface).

## 6. TRAPS (inherited + new)

All of Handoff_2026-08-18 §12 still applies (stamps, up_to_gw, preserved
suffixes, sealed 2025-26, UTF-16 redirects, cp1252 names, runtimes). New:
- `FPL_SOLVER_THREADS` caps HiGHS per process (unthrottled parallel sims
  hit 78 min vs 11 solo). 4 workers × 2 threads is the recommendation.
- Detached Start-Process + log + monitor for anything >10 min; builders
  save only on completion, so kills never leave half-written artefacts.
- The simulator's decision log does NOT persist the XI split; analyses
  needing it must approximate (stated) or extend the log first.
- pandas `row.name` in iterrows is the INDEX, not the 'name' column.
- fplcache post-season snapshots: pick by date window, or you get the next
  season's zeroed bootstrap.
