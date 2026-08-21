# Interim project — closing position (2026-08-21)

The "Make The Number Real" interim plan is fully dispositioned. This is the
one-page record of where everything landed. No new runs; every figure below
exists in a log.

## 1. Dispositions

| Item | Disposition |
|---|---|
| M1 EV evaluator (the gate) | **FAILED** the ladders. Season-level evaluation infeasible; all decisions moved to component/paired-window/per-decision endpoints. Per plan §1 this is the recorded negative result. |
| M2 multi-season | **Partial by decision**: 3 clean seasons (2023-24/24-25/25-26); 2021-22/22-23 not portable (KNOWN_ISSUES #11). |
| M3 baseline migration | **Complete** (availability=True, per-fixture DGW, odds horizon 0). |
| D1 scoring terms | **ADOPTED** (Variant B). |
| D2 npxG blend | **ADOPTED** (k=8). Cold start (~32% no-prior) still open. |
| D3 DGW audit | **Complete** (per-fixture grain, test-guarded). |
| D4 synthetic odds | **Closed, NOT adopted** — λ-model good (R² 0.851), no pipeline benefit; forward decay is minutes/form-driven. |
| D5 player props | **Not started** — blocked on the ~$100–300 spend decision. |
| D6 free (live poller) | **Built + parked.** GW1 smoke test MISSED (timezone); mechanics salvaged (schema match, late-news rule fired live on 5 players); full test + blind-window diff retry at GW2. |
| D6 paid (FFS/Rotowire) | **Not started.** |
| D7 skip list | Skipped by design. |
| P1 opening squad (both steps) | **CLOSED, NOT adopted** (p1_opening_log §0): mixed endpoints; robust solve collapses to expectation; substitution with the wildcard. |
| P2 early wildcard | **ADOPTED via P4** — WC1 rule of record revised GW4–5 → **GW2–3** (p4 log §12b). |
| P3 early hit tolerance | **Measured, DECLINED** (p3_early_hits_log): pays only where the wildcard is late — a configuration no longer used. |
| P4 chip policy | **ADOPTED** (p4 log §12, incl. the §12b revision); standard config H=6 d=0.45; bench-aware BB. |
| P5 optimizer wins | **Measured, DECLINED** (p5_optimizer_wins_log): both pieces ~0 to −7/season on noise-free paired paths; the prior +2 superseded. |
| Phase 3 deep learning | Stays **cut**. |
| Phase F freeze/final run | Moot as specified (needs M1); the full-system grid (below) stands as the reference run. |

**The plan's primary criterion (≥2200 EV-scored five-season mean) is
unmeasurable as written** — M1 failed and only three seasons are portable.
The honest substitute: the reference figures below, under the standing
framing.

## 2. Live configuration (the backtest system of record; nothing deployed)

Equation/stamps: `minutes_availability=True`, `odds_horizon_gws=0`,
`dgw_handling=per_fixture`, `d1_terms_active=True`, `cs_unified=False`,
`rate_blend_active=True (k=8)`, `synthetic_lambda_active=False`,
`dc_rule_active` per season (per-player DC post-#15).
Solver/policy: `DEFAULT_HORIZON=6`, `DEFAULT_DECAY=0.45`, hit bar 4, bench
weight 0.2, `BENCH_BOOST_AWARE=True`, one Bench Boost per half supported.
Chips of record: WC1 **GW2–3**; WC2 pre-DGW-cluster swing; FH2 largest
blank, floor ≥4 (never below); BB2 biggest second-half double, bench-aware;
TC2 biggest DGW; TC1 predicted-captain peak; BB1 only at a real H1 double.
Measured-and-off gates (all False): `OPENING_HORIZON_ACTIVE`,
`OPENING_ROBUST_ACTIVE`, `BENCH_ORDER_BY_PLAY`, `XI_TIEBREAK_P60`,
`EARLY_HIT_DISCOUNT_ACTIVE`.

## 3. Reference figures (single draws, sd ≈ 60 — identify, never rank)

| Season | No-chip baseline | Full system chip-incl (WC1@2) | Avg manager (fplcache) | Margin |
|---|---|---|---|---|
| 2023-24 | 2204 | 2299 | 2003 | +296 |
| 2024-25 | 2362 | 2301 | 2008 | +293 |
| 2025-26 | 2032 | 2219 | 1895 | +324 |

All 24 full-system cells cleared the average manager (+99 to +437).

## 4. Open threads

1. **Goalkeeper investigation** (gk_investigation_log §9; D4's β structure
   independently corroborates H1).
2. **2024-25's reproducible failure** — now ~6 independent appearances
   (chips both decays, bench-aware, full system, wildcard grid GW6-8).
   Diagnosis: early-branch divergence + reshuffle-into-error; candidate
   cause rotation-hardness. The concrete next investigation.
3. **D6 GW2 retry**: deadline 2026-08-28 17:30Z — start `--watch` at
   13:30Z = **09:30 LOCAL** (the GW1 miss was a timezone error). The
   blind-window diff vs fplcache is the prize. Scheduler registration is
   the user's call.
4. **Deferred purchases**: D5 props evaluation month (~$100–300, the one
   lever aimed at the binding constraint); D6 paid (FFS £3–4/mo,
   Rotowire $40/yr).
5. **KNOWN_ISSUES #15 queued corrections**: d1_log §8 and GK-log tables
   still quote pre-#15 2025-26 figures.
6. Inherited: D2 cold start (~32% no-prior); M1 kill-criterion record;
   live-freeze decision; decision log does not persist the XI split.

## 5. Durable findings (recur across independent measurements)

1. **The substitution effect — three sightings.** Opening-squad quality and
   the early wildcard solve the SAME problem: P1's horizon opening shrank
   the WC1 payoff (+15 vs +35); the WC1 review recorded the GW2 edge as
   conditional on the cold opening; P3's early hits are worthless once the
   wildcard sits at GW2 (46–53% beat the charge) but good when it is late
   (61–80%). One problem, several levers — the wildcard is the cheapest,
   and it is the one adopted.
2. **Prediction quality at horizon is the binding constraint, not
   selection mechanics.** The optimizer-has-converged conclusion now rests
   on: P5's noise-free paired declines, P1 Step 2's collapse to
   expectation, the captaincy irreducibility result, the hit-bar results
   from BOTH directions, and D4's mechanism finding (forward-step decay is
   minutes/form-driven). The route forward is data (D5 props, lineups),
   not solver work.
3. **Season totals cannot rank arms** (M1; paired-diff sd ≈ 85). The
   discipline held all week: every decision ran on paired windows or
   per-decision endpoints, and the totals-vs-anchors divergence in the
   wildcard grid is the standing illustration.
4. **The silent-fallback family** (#10/#13/#14/#15 + the D4 near-miss):
   every equation flag is one constant + a per-row stamp; provenance is
   checked before any comparison; fallbacks guard at the grain they fail
   at. This discipline caught a wrong-provenance comparison before it
   produced a number, twice.
5. **2024-25 fails reproducibly** under every reshuffle-heavy policy while
   its no-churn baseline is the best path anywhere (2362) — the strongest
   single argument that prediction error at the reshuffle, not policy
   timing, is where the points leak.
