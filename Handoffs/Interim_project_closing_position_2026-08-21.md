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
`dc_rule_active` per season (per-player DC post-#15),
**`bonus_mode=delete` (ADOPTED 2026-08-26, `Logs/bonus_delete_prereg.md`; the expected-bonus term is
removed from the equation — e_points omits realised bonus, ~0.26 per likely starter per week; the
pre-adoption canonicals are preserved as `*_prebonusdel.parquet` and reference-cell chip reads are
taken from them)**, `penalty_fix_active=False`, `topend_cal_active=False` (both measured and NOT
adopted: `Logs/penalty_fix_prereg.md`, `Logs/topend_calibration_prereg.md`).
Solver/policy: `DEFAULT_HORIZON=6`, `DEFAULT_DECAY=0.45`, hit bar 4, bench
weight 0.2, `BENCH_BOOST_AWARE=True`, one Bench Boost per half supported.
Chips of record: WC1 **GW2–3**; WC2 pre-DGW-cluster swing; FH2 largest
blank, floor ≥4 (never below); BB2 biggest second-half double, bench-aware;
~~TC2 biggest DGW~~ TC2 earliest eligible second-half double (revised 2026-08-24, p4 §12c (ii) — the old rule collided with BB2 and its first revision selected nothing in two of three seasons); TC1 predicted-captain peak; BB1 only at a real H1 double.
Measured-and-off gates (all False): `OPENING_HORIZON_ACTIVE`,
`OPENING_ROBUST_ACTIVE`, `BENCH_ORDER_BY_PLAY`, `XI_TIEBREAK_P60`,
`EARLY_HIT_DISCOUNT_ACTIVE`.

## 3. Reference figures (single draws, sd ≈ 60 — identify, never rank)

> **FIGURES OF RECORD, 2026-08-28 (supersede everything below in this section).** Reference cells re-pointed
> to the **horizon-minutes arm on the gap0 convention** — penalty-join leak fix (e04fb72) + solver MIP gap 0
> (37ad782) + fixed crosswalk (a758541), `bonus_mode=delete`, all chips, WC1 @ GW2, TC2 in-sim (2025-26) or the
> TC2-equivalent captain multiple at the rule week where the arm ran TC2 zero (2023-24, 2024-25):
>
> | Season | Path ex-TC2 | TC2 | BB1 / BB2 / TC1 | **Chip-inclusive** | Avg manager (fplcache) | Margin |
> |---|---|---|---|---|---|---|
> | 2023-24 | 2386 | +10 (GW25 equiv.) | +7 / +16 / +6 (GW6) | **2425** | 2003 | +422 |
> | 2024-25 | 2254 | +29 (GW24 equiv.) | +16 / +27 / +9 (GW18) | **2335** | 2008 | +327 |
> | 2025-26 | 2216 | +7 (GW26 in-sim, Gabriel) | +12 / +15 / +16 (GW17) | **2266** | 1895 | +371 |
>
> **CONFIGURATION ROLES, stated plainly:**
> - **Reference cells: horizon** (2425 / 2335 / 2266; `data/arms/armlog_*_hmin_gap0[_tc2]`).
> - **Production intent: combined** (props + horizon), figures **2459 / 2264** — two seasons only; no 2023-24
>   cell exists because the anytime-scorer market began autumn 2024.
> - **Shadow: baseline gap0** (2343 / 2306 / 2216; `data/arms/armlog_*_gap0_tc2`).
> - **The mismatch is explicit: the figures of record describe horizon, not the production configuration.**
>
> **OBJECTION, on the record:** the horizon arm was REJECTED on its pre-registered component test — minutes rank
> falls on both decision partitions at every step k = 1–5 in all three seasons (−0.014 to −0.049). This adoption
> cites season totals, which the standing rule forbids, and horizon is the specific case the rule was written from
> (+109 / +49 / −84 on totals while worse where decisions are made). The decomposition found four comparable
> decisions across three seasons netting +62 against +224 of path gain; no mechanism was identified. Deliberate
> choice made with that evidence in view. **The standing rule still applies to everything else: no future
> adoption decision may cite season totals.**
>
> **What production = combined requires before it can pick anything:** a live props puller inside each deadline
> window; a per-gameweek crosswalk pass with manual name mapping (162 and 57 manual entries historically, ~150
> unmatched rows per season); an incremental consensus builder; a paid odds plan. None exists. Props degrades
> silently to horizon-only when odds are missing — a coverage flag per deadline is required before combined runs
> live. **The shadow comparison has no statistical power:** paired per-gameweek sd ~13, detectable difference
> 6.8 pts/gw at n = 15 and 4.3 at n = 38, against historical config differences of 0 to +4 pts/gw; the
> 15-gameweek checkpoint is a mechanics review, not a verdict.
>
> Superseded, dated: 2251 / 2306 / 2268 (2026-08-26, pre-fix); 2343 / 2300 / 2190 (2026-08-27, leak fix only);
> 2343 / 2306 / 2190 (2026-08-27, gap0 pre-crosswalk); 2343 / 2306 / 2216 (2026-08-28, gap0 on the fixed
> crosswalk — the previous candidate). 2024-25's 2306 was numerically unchanged across several conventions by
> coincidence, not stability. Index: `Logs/season_totals_index.md` (header carries the same objection).

> **FIGURES OF RECORD, 2026-08-26 (supersede the table below):** system as configured =
> `bonus_mode=delete` + Triple Captain 2 scheduled IN-SIM on the 12c (ii) week (GW25 / GW24 / GW26; captain =
> the MIP's cap variable at that deadline from cutoff predictions; path identical to the no-TC2 run in every
> gameweek, so TC2 is exactly the extra captain multiple).
>
> | Season | Path | Chip-inclusive | Avg manager (fplcache) | Margin | Chip reads BB1 / BB2 / TC1 / TC2 |
> |---|---|---|---|---|---|
> | 2023-24 | **2226** | **2251** | 2003 | **+248** | +17 / +2 / +6 / +10 |
> | 2024-25 | **2249** | **2306** | 2008 | **+298** | +17 / +31 / +9 / +29 |
> | 2025-26 | **2220** | **2268** | 1895 | **+373** | +12 / +20 / +16 / +7 |
>
> Artefacts `data/arms/armlog_{season}_bonusdel_tc2.parquet`; `Logs/p4_chip_policy_log.md` §15;
> `Logs/season_totals_index.md` (reference cells). The rows below (2204 / 2362 / 2032 no-chip; 2296 / 2294 / 2206
> chip-inclusive) are the OLD convention — incumbent bonus term, TC2 scored zero — retained for lineage.
> Standing framing: sd ~60 single draw; 2024-25's reference is a 97th-percentile draw losing on 78% of arms
> (mean −70); seasons co-move (+0.26); user-facing figures, not adoption evidence.

| Season | ~~No-chip baseline~~ | ~~Full system chip-incl (WC1@2)~~ (OLD CONVENTION, superseded 2026-08-26) | Avg manager (fplcache) | Margin |
|---|---|---|---|---|
| 2023-24 | 2204 | 2299 | 2003 | +296 |
| 2024-25 | 2362 | 2301 | 2008 | +293 |
| 2025-26 | 2032 | 2219 | 1895 | +324 |

> **2026-08-26 — canonical moved (bonus term deleted).** The rows above and the corrected 2296 / 2294 / 2206
> were produced on the `bonus_mode=incumbent` canonicals (now `*_prebonusdel.parquet`). The system as
> configured is `bonus_mode=delete`; its full-system figures are in `Logs/bonus_delete_prereg.md` (season
> figures section). Comparisons across that boundary must state it.

All 24 full-system cells cleared the average manager (+99 to +437).

> **Correction 2026-08-24:** the chip-inclusive column above carried a
> Triple Captain 2 read on the Bench Boost 2 week — two chips in one
> gameweek, which FPL does not allow. Corrected figures: **2296 / 2294 /
> 2206**, margins +293 / +286 / +311; all 24 cells still clear the average
> (+92 to +430). Path totals and every windowed delta are unaffected. See
> p4 log §12c, KNOWN_ISSUES #16, and the season_totals_index header.

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
