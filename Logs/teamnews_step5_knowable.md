# Team-news investigation — step 5: the knowable oracle (2026-08-22)

Same instrument as step 4 (`squad/oracle_minutes.py`, gated, stamped
`oracle_minutes_active` + `oracle_mode`), three restrictions, 9 sims, full
adopted system, references and step-4 runs reused. Arm definitions of
record in eval/run_teamnews_knowable.py's header (stated before running):
A = realized minutes at horizon_step 0 only; B = step 0 for structurally
knowable (gw, element) — ≥60 PL minutes within the prior 4 days, or first
gw after a 3+-gw zero-minute absence; European midweeks NOT derivable from
disk, stated; masks ~12.6–15.1k reveals/season; C = step 0 for the 10
verified Guardian cases only (2/6/2 per season).

## Results (chip-inclusive is the reference frame; path shown alongside)

| season | arm | path (Δref) | chip-incl (Δref) | vs avg | % of step-4 Δ |
|---|---|---|---|---|---|
| 2023-24 | full | 2424 (+146) | 2493 (+194) | +490 | 100% |
| 2023-24 | A step0 | 2306 (+28) | 2364 (+65) | +361 | 34% |
| 2023-24 | B knowable | 2222 (−56) | 2253 (−46) | +250 | −24% |
| 2023-24 | C reported | 2270 (−8) | 2299 (+0) | +296 | 0% |
| 2023-24 | reference | 2278 | 2299 | +296 | |
| 2024-25 | full | 2364 (+109) | 2406 (+105) | +398 | 100% |
| 2024-25 | A step0 | 2170 (−85) | 2210 (−91) | +202 | −87% |
| 2024-25 | B knowable | 2115 (−140) | 2181 (−120) | +173 | −114% |
| 2024-25 | C reported | 2133 (−122) | 2194 (−107) | +186 | −102% |
| 2024-25 | reference | 2255 | 2301 | +293 | |
| 2025-26 | full | 2251 (+95) | 2313 (+94) | +418 | 100% |
| 2025-26 | A step0 | 2277 (+121) | 2345 (+126) | +450 | 134% |
| 2025-26 | B knowable | 2180 (+24) | 2249 (+30) | +354 | 32% |
| 2025-26 | C reported | 2154 (−2) | 2218 (−1) | +323 | −1% |
| 2025-26 | reference | 2156 | 2219 | +324 | |

Chip-incl means: full +131, A +33, B −45, C −36. Per-gw distributions and
transfer/captaincy detail in eval/measure_teamnews_knowable.py output.

## The split (the decision)

- **Buyable (C):** ~zero on clean paths. With 2 reveals, 2023-24 and
  2025-26 are near-exact washes (+0 / −1 chip-incl; 3–4 divergent weeks,
  per-gw quartiles 0/0) — matching step 3's ~2.3/season floor. 2024-25's
  −107 from SIX reveals is not "news cost 107": it is the path lottery
  seeded by tiny decision changes in the most reshuffle-sensitive season
  (sixth appearance of that signature). Verdict: the measurable buyable
  channel is a few points a season, and the variance it seeds can dwarf it
  in either direction. On points alone it does not clear even a small
  subscription price.
- **Buildable (B): THIS INSTRUMENT CANNOT PRICE IT — and that is itself
  the finding.** B measured −46/−120/+30: injecting step-0 TRUTH for
  congested/returning players while steps 1–5 keep the model's beliefs
  makes the solver act on INCONSISTENT beliefs (sell a rested starter it
  still rates next week; churn). A real calendar feature would shift
  predictions coherently at every step — a different object entirely. B's
  negative does not condemn the feature; it condemns partial-truth
  injection.
- **Genuinely unknowable/unbuyable — most of it.** Full-horizon (+131
  mean, 3/3 positive) vs one-deadline (+33 mean, signs +65/−91/+126) says
  the oracle's value comes overwhelmingly from MULTI-WEEK FORESIGHT —
  planning transfers into players before their good runs — which no
  service sells and no calendar rule supplies. That is horizon minutes
  PREDICTION quality: the project's standing binding constraint, again.

## Durable findings

1. **Minutes-knowledge value is NOT monotone in coverage.** Step-0-only
   truth (A) can lose (−91); knowable-subset truth (B) averaged negative;
   the full oracle is reliably positive. Partial oracles injected into a
   coherent belief system can subtract. Any future team-news integration
   must update ALL horizon steps consistently, never step 0 alone.
2. **The oracle's edge is planning, not reacting.** Reactive one-week
   knowledge churns; 2024-25 punishes churn (appearances 6 and 7 of its
   signature, arms A and B/C).
3. Buyable news ≈ step-3's floor (a few pts/season) — now confirmed at
   path level in the two clean seasons.

Caveats: one draw per cell, no intervals; A/B/C diverge from GW1 (step-0
reveals change the opening squad); the % column divides small numbers by
~±100 and is quoted for orientation only.

## Where this leaves D5/D6-paid

The purchase decision should NOT be justified by the 52-case/blank-
avoidance story (steps 3+5: a few points) nor by naive oracle headline
(+131: unreachable planning value). The honest target for spend or build
is horizon minutes prediction — rotation/returns modelled consistently
across all six steps. That is model work (possibly aided by data), and the
instrument to test it already exists: any candidate feature should close
part of the full-vs-A gap while staying consistent, and must NOT reproduce
arm B's inconsistency failure.
