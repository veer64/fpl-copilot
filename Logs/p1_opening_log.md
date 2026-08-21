# P1 — opening-squad policy (Steps 1 & 2) — **CLOSED 2026-08-21, NOT ADOPTED**

**Status of record:** both steps built, measured across three seasons and the
full-system grid, and left OFF. `OPENING_HORIZON_ACTIVE` and
`OPENING_ROBUST_ACTIVE` rest False. The code paths, gates and stamps are
retained for reproducibility; no production behaviour changes.

## 0. The closure decision and its reasoning (2026-08-21)

1. **Step 1 (horizon opening) — mechanism works, endpoints mixed.** The
   solver does what was designed: four swaps for ~0.05 predicted GW1 points,
   squad survival up in two seasons and never down. But GW1–7 vs the average
   manager moves +21 / −11 / +21; capture improves only in the season with
   the weakest base opening (2025-26, +3.1pp); and under the full system
   (§8) it is better in 5 of 12 cells, worse in 6, even in 1 — no
   resolvable pattern.
2. **Step 2 (scenario-robust solve) — never produced a new squad.** In all
   three seasons one of the two deterministic squads won the recourse-aware
   cross-evaluation and all 50 scenario candidates lost (§6). The mechanism
   the plan hoped for is neutralised by the recourse it also asks to model:
   if one transfer a week can repair a failure, the failure barely costs
   anything, and the objective collapses back to expectation.
3. **The repeatable finding is SUBSTITUTION, not failure.** A better opening
   leaves the early wildcard less to fix (2023-24: +15 vs +35 at the GW2
   anchor; §7/§8). P1 and the plan's P2 (early wildcard) solve the same
   problem — and the wildcard already does it, inside the adopted chip
   framework.
4. **Simplicity as a decision criterion, stated explicitly.** P1 adds a
   gate, a second GW1 solve path, and the fodder-bench behaviour, for no
   measurable return. Five silent-fallback defects surfaced this week
   (#10/#13/#14/#15 and the near-miss D4 wrong-writer build); fewer moving
   parts is a real benefit when the instrument cannot adjudicate small
   gains (M1 failed; path sd ~60).

**Untried levers, recorded for anyone revisiting:** correlated failure
scenarios (team-level or price-tier-level, rather than independent per-player
draws), and a risk-averse objective (CVaR rather than the mean). Neither is
licensed by current evidence — they are the two ways Step 2's collapse to
expectation could in principle be broken.

**Reference figures:** the full-system grid (§8) is the project's current
"system as configured" reference — every one of the 24 cells clears the FPL
average manager, chip-inclusive margins +99 to +437. Standard framing
applies in full: those figures identify configurations; they rank nothing.

---

# Step 1 record — opening squad with a horizon (measured 2026-08-20)

Interim plan §4 item P1, Step 1. The structural bug: `simulate_season` seeded
GW1 from the single-gameweek `optimize_squad`, so the one decision with an
eight-week persistence horizon (coldstart_log: being stuck costs 27.9 pts/gw
in GW1–7 vs 12.7 after) was the only decision made with no horizon at all.

**The change:** when `simulator.OPENING_HORIZON_ACTIVE` is on (under
policy="mip" on a horizon-aware frame), GW1 is built by `build_and_solve`'s
free-pick path over the standard H=6 / decay=0.45 window, reading every
future gameweek from GW1's own cutoff — the same objective, solver and cutoff
discipline as every later transfer decision. Objective change only; no new
data. Gated (False on disk) and stamped per decision-log row as
`opening_horizon_active` — the stamp records what the run DID (gate AND mip
policy AND horizon-aware frame), not the raw constant.

**Status: measured, report-only. NOT adopted.** The constant rests False.

## 1. Provenance (verified before any run)

All three canonicals (`data/walkforward_h6_{2023_24,2024_25,2025_26}.parquet`)
carry single-valued stamps: minutes_availability=True, odds_horizon_gws=0,
dgw_handling=per_fixture, d1_terms_active=True, rate_blend_active=True,
rate_blend_k=8.0, cs_unified=False, synthetic_lambda_active=False;
dc_rule_active False/False/True per season; 2025-26 p_dc_hit max 0.798 with
7,913 distinct values (#15 guard passes). No preserved-suffix variant read.

Leakage check (direct, not asserted-by-construction only): every pool handed
to the opening solve was compared row-for-row against the raw file's
cutoff==1 slice — elements and e_points identical for gw 1–6. Only
horizon-step 0–5 predictions from GW1's cutoff can reach the objective.

Inertness check: with the gate off, the GW1 squad is bit-identical to the
sweep's verified `base_H6_d45` run's GW1 squad (2025-26, element-for-element).
Test suite after the change: 113 passed, 5 skipped — unchanged.

Arms: `eval/run_p1_opening.py` (in-process flip, the run_chip_study pattern),
one log per (season, arm) under `data/p1/`. `eval/measure_p1_opening.py`
asserts per season that the arms agree on horizon/decay/bench_boost_aware/
wf_file and differ exactly on the `opening_horizon_active` stamp. All passed.

## 2. Capture-metric calibration (the original script is lost)

Recovered against coldstart_log's own figures: best-available 15 = raw top-15
by actual points per gw (reproduces 174.3 / 180.1 exactly); capture =
era sum of the owned 15's actual points / era sum of the best-15's (the log's
39.86/174.3 = 22.9% ≈ "22.7%"). The overlap-count variant gives ~7% and is
not the recorded metric. NOTE: the 22.7% reference was measured on the
H=3/decay=0.3, pre-D1/pre-blend/pre-#15 config. On today's standard config
the BASE arm already sits at 27.5–37.1% in GW1–7 — the plan's "target ~30%"
was framed against a baseline that no longer exists.

Average manager per gw: fplcache post-season snapshot (date-window picked),
events[].average_entry_score; season sums assert-match the index's
fplcache-derived 2003 / 2008 / 1895.

## 3. Results (six sims: 3 seasons × {base, p1}, no chips, H=6 d=0.45)

**GW1 fifteen.** 4 of 15 change in every season, and the shape is the same
each time: the horizon objective downgrades bench/fringe bodies to near-fodder
(Woodrow h6-sum 3.3, Lankshear 5.4, Wheatley 5.4) to fund horizon-strong
starters (2023-24: Alexander-Arnold 27.0 + Núñez 27.9 for Wilson 21.3 +
Welbeck 15.3; 2024-25: Gabriel 20.9 + Ederson 22.1 for Maguire 16.5 + Raya
22.3; 2025-26: Gabriel 21.0 + Leno 19.0 for van Hecke 14.0 + Hermansen 15.1).
GW1-only predicted cost of the swap is tiny (e.g. 0.05 pts in 2025-26).

**Capture of the best-available 15 (GW1–7):**
| season | base | p1 | Δ |
|---|---|---|---|
| 2023-24 | 31.7% | 30.9% | −0.8pp |
| 2024-25 | 37.1% | 36.8% | −0.3pp |
| 2025-26 | 27.5% | 30.6% | +3.1pp |

**Realized points GW1–7 vs the FPL average manager (7-gw sums):**
| season | base − avg | p1 − avg | p1 − base |
|---|---|---|---|
| 2023-24 | −15 | +6 | +21 |
| 2024-25 | +74 | +63 | −11 |
| 2025-26 | −14 | +7 | +21 |

**GW1 fifteen surviving:**
| season | base GW8/GW15 | p1 GW8/GW15 |
|---|---|---|
| 2023-24 | 6 / 4 | 6 / 6 |
| 2024-25 | 10 / 6 | 11 / 8 |
| 2025-26 | 6 / 4 | 6 / 4 |

Early transfer activity barely moves (GW2–7: 11→10, 7→8, 10→10).

**Season totals (STANDARD FRAMING — identify the runs, never evidence; path
sd ≈ 60, paired-diff sd ≈ 85):** base 2204 / 2362 / 2032, p1 2194 / 2302 /
1961. Logs: `data/p1/p1log_*.parquet`.

## 4. Honest reading

- The mechanism behaves as designed: same-cost GW1 squads whose members the
  solver still wants later (survival up in two seasons, never down), bought
  for ~zero GW1 predicted cost.
- The designed endpoints are MIXED, not a win: GW1–7 vs the average manager
  improves +21 in 2023-24 and 2025-26 and worsens −11 in 2024-25; capture
  moves +3.1pp only in the season with the weakest base opening (2025-26)
  and is flat-to-slightly-negative elsewhere. A 7-gw realized sum still
  carries meaningful path noise, and the arms share 11/15 players at GW1.
- The cold-start premise has partly aged out: at the current standard config
  the opening block is far less broken than the 22.7% / 27.9-pts/gw era
  measurements that motivated P1 (base GW1–7 capture 27.5–37.1%). 2024-25's
  opening was already horizon-good (10/15 alive at GW8); it had the least to
  gain and is the one season that got worse.
- A behavioural risk to watch if this is ever revisited: the fodder-bench
  pattern (a ~£4.5m never-plays striker in two seasons) weakens autosubs —
  the flat 0.2 bench weight prices this, but the horizon objective leans on
  it harder than the single-GW seed did.
- No adoption case from this alone. If pursued, the honest next step is the
  plan's own Step 2 (scenario-robust opening solve) measured on EV endpoints
  once M1-class instrumentation exists — not more realized-total draws.

## 5. Reversal analysis (read-only, 2026-08-20): the fodder-bench mechanism
## is real but SMALL; the season-total reversal is path divergence

Question: P1 gains GW1-7 (+21/−11/+21 vs avg) but season totals reverse
(−10/−60/−71). Fodder-bench/autosub cost, or path divergence?

Method: the log does not persist the XI split, so each week's XI was
reconstructed (formation-legal argmax of own-cutoff step-0 e_points — the
MIP's separable step-0 rule) and replayed through production score_gameweek.
Fidelity verified per week against raw_points / bench_points / n_subs /
captain: **38/38 on all four, both arms, all seasons** — the replay is exact.

- **Cumulative shape:** peaks +41@GW9 / +3@GW9 / +37@GW10; the P1 lead
  SURVIVES to GW25 in 2023-24 (+33) and GW13 in 2025-26; the losses are
  CONCENTRATED: 2023-24 GW27−28 (−43 of the −51 swing), 2024-25 GW16−20
  (−57), 2025-26 GW11+14 (−45) then slow bleed.
- **Autosubs:** fired 14/20/11 (base) vs 8/19/8 (p1); points gained 32/60/49
  vs 25/52/23 — p1 −7/−8/−26 per season, −41 total. Final-XI zero-minute
  slots (the named failure mode): base 5, p1 7 across THREE seasons — near
  identical, a few points at most.
- **Fodder exposure** (squad-gameweeks holding an e_minutes<10 player, all on
  the bench): 21→50, 14→47, 16→20. Real — but it ANTI-correlates with the
  autosub loss: the biggest exposure gap (2023-24, +29 sgw) cost 7 autosub
  points; the biggest autosub gap (2025-26, −26) has the SMALLEST exposure
  gap (+4). The causal chain GW1-fodder → autosub loss does not hold.
- **Worst-week decomposition:** in all nine collapse weeks the captains are
  IDENTICAL and the entire weekly difference is XI-differential players
  (shared squads 6–11/15): base-side differentials hauling (White 13/11,
  Palmer 18, Porro 14, O'Reilly 11, Merino 13, Beto 16) against p1-side
  differentials scoring 1–3. Mostly mid-season buys neither arm held at GW1.
- **Bench points left** (not scored): 334/267/341 vs 235/196/303 — p1's
  bench is genuinely weaker, but unscored bench points are not a cost except
  via the autosub channel counted above.

**Verdict:** the evidence supports PATH DIVERGENCE, not the fodder mechanism.
The fodder bench is a real but minor tax — bounded by the −41 total autosub
gap (~14 pts/season on average, and even that is partly noise given the
anti-correlation). The reversal itself is a handful of differential-haul
weeks on diverged squads — exactly the ~52-sd path lottery. What this CANNOT
distinguish: whether the diverged picks (incl. 2024-25's GW1 differentials
Porro/Raya outscoring Gabriel/Ederson) were worse ex-ante or merely unlucky —
that is precisely the M1 instrument gap, and realized points cannot answer it.

## 6. Step 2 — scenario-robust opening solve (measured 2026-08-20,
## NOT ADOPTED): robustness pricing never changes the opening decision

Interim plan §4 P1 Step 2. Implementation: `squad/opening_robust.py` (full
sampling scheme and recourse approximation in its docstring), gated by
`simulator.OPENING_ROBUST_ACTIVE` (False on disk), stamped per row as
`opening_robust_active` alongside `opening_horizon_active`. Arm p2 in
data/p1/; base and p1 arms REUSED from Step 1, not re-simulated. Stamp
discipline asserted at measurement: p2 vs base differ only on the robust
stamp; every shared config stamp identical across all three arms.

Design (stated before implementation): K=50 scenarios from cutoff-1 rows
only (verified row-for-row against the raw file's cutoff==1 slice — pools
AND probability frames, element sets and every column value). Participation
via ONE shared uniform per (player, scenario) against p_play_any / p_60plus
(persistent availability regimes); mean-preserving component draws
(Poisson goals/assists from pts_goals/pts_assists, Bernoulli CS/DC from
pts_cs/pts_dc, small terms at conditional expectation). Sampler calibration:
mean of 200 draws reproduces e_points (sum ratio 1.001, corr 0.992).
Candidates: one deterministic MIP per scenario + both deterministic squads.
Selection: recourse-aware cross-evaluation, XI re-picked per scenario-week,
ONE repair per week (sell low-remaining-value member, best affordable
same-position buy, club limit + bank enforced). Runtime: 6.5 min per season
solo (~18 min for the scenario stage under 3 parallel workers).

**Result: the robust objective never produced a new squad.** In every season
one of the two deterministic strategies won the cross-evaluation and ALL 50
scenario-specific candidates lost (each overfits its own draw — 50/50
distinct squads, none survives averaging):

| season | p2 picks | GW1 15 shared | season path |
|---|---|---|---|
| 2023-24 | the BASE squad (rank 1 of 52; p1 rank 2) | 15/15 with base | identical to base, 2204 |
| 2024-25 | the STEP-1 squad | 15/15 with p1 | identical to p1, 2302 |
| 2025-26 | the BASE squad (rank 1 of 52; p1 rank 2) | 15/15 with base | identical to base, 2032 |

Every endpoint (capture, GW1-7 vs avg, survival, bench, fodder, total)
therefore equals the copied arm's — no new numbers exist to quote.

**The fodder question:** scenario sampling does NOT decisively penalise a
worthless-in-every-draw player. In 2024-25 the robust evaluation PREFERRED
the fodder-carrying Step-1 squad (Lankshear, 47 fodder squad-gameweeks
downstream); in 2025-26 it preferred the no-fodder base squad. Mechanism:
the evaluator scores XI-only, so fodder costs only through lost cover in
failure draws — and the one-repair-per-week recourse patches exactly those
draws, neutralising the penalty. Consistent with §5: the realized fodder
tax was small.

**Reading:** with mean-preserving sampling, independent returns, and
repair-capable recourse, expectation dominates — the robust objective
collapses onto the deterministic answer, choosing between the two existing
strategies rather than finding a third. The mechanism the plan hoped for
("prices being wrong") is mostly neutralised by the same recourse it asks to
model: squads at this budget are similar enough that one repair per week
covers their failure modes. A materially different answer would need
correlated failure scenarios (team-level, price-tier-level) or a
risk-averse objective (CVaR rather than mean) — neither is licensed by
current evidence, and season totals cannot rank the arms anyway (M1).
NOT adopted; both gates rest False.

## 7. WC1 × opening grid (overnight 2026-08-20→21, 42 sims, NOT ADOPTED):
## the earlier the wildcard the better — GW2 is positive in all six arms,
## and GW4 (the adopted anchor) is the weakest of GW2–5

2 openings (base / OPENING_HORIZON_ACTIVE) × WC1 at GW2–8 × 3 seasons,
H=6 d=0.45, no other chips. The six no-wildcard baselines REUSED from
data/p1/ (not re-run). Provenance re-verified before launch (canonical
stamps identical, files untouched since the P1 runs); every run asserted
pre-chip prefix identity vs its own opening's baseline and the correct
opening stamp — all 42 passed. Scripts: eval/run_p1_wc_grid.py,
eval/measure_p1_wc_grid.py (full per-cell tables in its output; per-cell
artefacts data/p1/wclog_*.parquet). n ≤ 3 per cell — no intervals (≥8 rule).

**W=3 paired deltas at the anchor (the P4 §4 convention):**

| WC week | base 23-24/24-25/25-26 | p1 23-24/24-25/25-26 | cross-season mean (base | p1) |
|---|---|---|---|
| GW2 | +35 / +32 / +58 | +15 / +63 / +45 | **+42 | +41** |
| GW3 | +29 / +15 / +20 | +16 / +8 / +11 | +21 | +12 |
| GW4 | −11 / −5 / +45 | −24 / −19 / +6 | +10 | −12 |
| GW5 | +34 / +19 / −10 | +28 / +12 / +9 | +14 | +16 |
| GW6 | +1 / −42 / −22 | −18 / −28 / −25 | −21 | −24 |
| GW7 | +4 / −68 / +21 | −5 / −65 / +20 | −14 | −17 |
| GW8 | +24 / −51 / +47 | −6 / −63 / +30 | +7 | −13 |

**Q1 — consistency:** the old "GW4–6, exact week unresolvable" framing is
SUPERSEDED. GW2 is positive in ALL SIX season×opening arms at W=1, 2 and 3
(and 5/6 at W=5) and is the W=3 argmax in 5 of 6; no other week comes
close (GW3 is also 6/6 positive at W=3 but at half the magnitude). GW4 —
inside the adopted "GW4–5" rule — is NEGATIVE in 4 of 6 arms at W=3, the
weakest week of GW2–5. GW6–8 are broadly negative, catastrophically so in
2024-25 (−42/−68/−51 base; −28/−65/−63 p1) — that season's
reshuffle-into-error signature appears as early as GW6. Mechanism reading:
the WC1 gradient is monotone-ish toward "as early as possible", consistent
with coldstart_log — the wildcard's value is escaping the opening squad,
and every week of delay pays the ~28 pts/gw persistence cost.

**Q2 — interaction with the opening:** mostly NO. Both openings agree on
GW2 in 2024-25 and 2025-26 (and their GW2 cross-season means are equal,
+42 vs +41). The one flip is 2023-24: base argmax GW2 (+35), p1 argmax GW5
(+28) — and p1's early-WC gains there are visibly smaller (+15 vs +35 at
GW2; −24 vs −11 at GW4), which is the direction the interaction hypothesis
predicts (the horizon squad has less to escape from). One season out of
three, no intervals: suggestive, not established.

**GW1–10 vs the average manager:** most positive-anchor cells also lift the
early margin (e.g. 2025-26 base wc2: +87 vs baseline's +5; 2024-25 wc5
cells reach +129/+112). Survival at GW8/GW15 is mechanically low after any
early wildcard (the chip rebuilds the squad) — reported per cell in the
measurement output, not meaningful as a quality signal here.

**Season totals** (identify only; sd ~60): full 42-cell table in the
measurement output; range 1889–2339.

**Not adopted.** The WC1 rule of record stays GW4–5 (P4 log §12) until a
deliberate revision; this grid is the evidence a revision would cite, and a
cross-reference note now sits in the P4 log (§14). Caveat of record: a GW2
wildcard is close to "re-pick the opening squad after one week of
information" — its gain partly measures the opening squad's own weakness,
so P1-family fixes and early-WC policy substitute for each other (the
interim plan's §4 warning to measure them jointly, which this grid does).

## 8. FULL-SYSTEM grid (overnight 2026-08-21, 24 sims, NOT ADOPTED): all six
## chips + both openings + WC1 {2,4,6,8}; GW2's wildcard edge survives, the
## opening does nothing resolvable, BB1 is free-to-slightly-positive

2 openings × WC1 {2,4,6,8} × 3 seasons with the complete configured system:
WC2 swing {32,31,32}, FH2 {29,29,34} (all pass the ≥4 floor), BB1 AND BB2
both scheduled bench-aware (simulate_season now takes one boost per half —
backward-compatible; suite green), TC1/TC2 + BB bench values as exogenous
reads (P4 convention; TC2 and BB2 share the biggest-DGW week in all three
seasons — both reads added, chip-inclusive figures optimistic by
min(TC2, BB2 bench), stated). FH1 excluded (−20). BB1 weeks by stated rule:
2023-24 GW7 (the only first-half double); else predicted-bench argmax from
each opening's own baseline → 2024-25 base GW7 / p1 GW9, 2025-26 GW10.
Baselines and the isolated-wildcard cells REUSED. Prefix identity asserted
per cell to min(wc1, bb1−5); all 24 passed. Scripts:
eval/run_full_system.py, eval/measure_full_system.py (full per-cell output
there; artefacts data/p1/fslog_*).

**"The system as configured" (WC1@4 per the adopted GW4–5 rule),
chip-inclusive totals / margin vs fplcache average:**
2023-24 base 2299 (+296), p1 2297 (+294); 2024-25 base 2445 (+437), p1
2162 (+154); 2025-26 base 2133 (+238), p1 2104 (+209). Single draws —
identify only. Chip-inclusive range over all 24 cells: 2084–2445; margin
vs average +99 to +437, positive in every cell.

**Q1 — the WC1 pattern survives.** W=3 anchor deltas with everything on:
GW2 = base +35/+26/+58, p1 +15/+63/+45 — positive in all six arms again,
argmax or within 3 pts of argmax in every arm (2025-26 base GW8 +61 pips
GW2 +58). GW4 remains negative in half the arms; GW6 negative in 4/6;
2024-25's late-WC1 collapse reproduces (−47/−51 base, −28/−63 p1). The
isolated grid's anchors reproduce almost exactly in the full system where
prefixes align — the chips at GW28+ do not disturb the WC1 signal.

**Q2 — the horizon opening does nothing resolvable with everything on.**
GW1–10 vs the average manager: p1 better in 5 of 12 cells, worse in 6,
even in 1 — no consistent direction. The one repeatable signature is the
Step-1 substitution: p1's WC1 anchors are smaller than base's in 2023-24
(+15 vs +35 at GW2; −24 vs −11 at GW4) — a better opening leaves the
wildcard less to fix. Chip-inclusive totals: base ahead in all four
2023-24 cells, p1 ahead in 5 of 8 elsewhere — path noise, not signal.

**The BB1 question — genuinely free?** Clean instrument: each fs cell vs
the SAME (season, opening, wc1) isolated-wildcard cell differs only by BB
scheduling before GW28 (asserted prefix-identical, 24/24). BB1 net =
path delta over [bb1−5, bb1+5] + bench@bb1:
nets −6/+11/+2/+2, −6/+11/−1/−3 (2023-24 base/p1), −4/+147*/−15/+7,
+31/+14/+6/+32 (2024-25), +37/0/0/+49, +37/+28/+2/−18 (2025-26).
*the +147 is a diverged-path windfall (path +128 over 11 gws), not a BB1
effect. Bench gains are modest (+3..+19, mean ~+10); path costs are small
and SIGN-MIXED (median ≈ 0). Verdict: **no systematic XI cost from
building toward a single-fixture boost is detectable — BB1 is roughly
free-to-slightly-positive (~+10 bench, ±path noise)** — but the window
noise on diverged paths is the same size as the effect, so this is "no
detectable cost", not "proven free". The earlier +37 read was a fluke, as
suspected: typical single-fixture BB1 bench is ~10.

**2024-25 again:** path deltas −107..−305 in 7 of 8 cells (the exception,
base wc4 +23, rides the same +128 windfall) — fifth independent appearance
of its reshuffle failure mode; yet every 2024-25 cell still clears the
average manager by +99..+437 chip-inclusive.

NOT adopted. Gates rest False; chip rules of record unchanged (P4 §12,
review note §12a).

## 9. Files

- `squad/simulator.py` — both gates + stamps (constants rest False)
- `squad/opening_robust.py` — Step 2 sampler/candidates/recourse evaluator
- `eval/run_p1_opening.py`, `eval/measure_p1_opening.py`,
  `eval/run_p1_robust.py`, `eval/measure_p1_robust.py`,
  `eval/run_p1_wc_grid.py`, `eval/measure_p1_wc_grid.py`,
  `eval/run_full_system.py`, `eval/measure_full_system.py`
- `data/p1/p1log_*.parquet`, `data/p1/wclog_*.parquet`,
  `data/p1/fslog_*.parquet` (gitignored)
- simulate_season now accepts one Bench Boost per half (int stays legacy
  single-boost; stamps `bench_boost_gws` alongside the legacy
  `bench_boost_gw`)
- Nothing canonical was regenerated or overwritten; no preserved-suffix
  files were needed.
