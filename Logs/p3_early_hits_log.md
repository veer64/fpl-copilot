# P3 — early hit tolerance (measured 2026-08-21, NOT ADOPTED)

Interim plan §4 P3. Hypothesis: persistence costs 27.9 pts/gw in GW1–7 vs
12.7 after (coldstart_log), so a −4 hit clearing dead weight EARLY may be
positive-EV. Change: `transfer_mip.EARLY_HIT_DISCOUNT_ACTIVE` /
`EARLY_HIT_BAR` — the SOLVER's hit coefficient in GW2–7 only (scoring still
charges FPL's 4); stamped per row. Gates rest False. This is the mirror of
the hit-threshold grid (raised the bar uniformly, found nothing); prior
result treated as live, as was the P1/P2 substitution.

**Grid:** bars {4=ref, 3, 2, 1} × WC1 {GW2, GW6} × 3 seasons under the full
adopted chip set (18 sims; bar-4 references reused from fslog_base_wc{2,6}).
The WC1@6 arm measures the discount where the wildcard is NOT already
clearing dead weight — the substitution contrast. Endpoints per-decision
and path-free within each arm (E1/E2 conventions); n per cell 7–26, no
intervals. Formulation caveat on record: bar=1 crosses the anti-degeneracy
bound (1 < 4×0.45) at the single GW7→8 boundary solve; bars 2–3 are clean.
Full tables: eval/measure_p3.py output; artefacts data/p1/p3log_*.

## Results (pooled hit-week transfers, realized over next 3 gws)

| wc1 | bar | n hits | median | % pos | % beat 4 |
|---|---|---|---|---|---|
| GW6 | 4 (ref) | 10 | **+12** | 100% | **80%** |
| GW6 | 3 | 23 | +9 | 78% | 61% |
| GW6 | 2 | 31 | +7 | 81% | 68% |
| GW6 | 1 | 56 | +5 | 66% | 52% |
| GW2 | 4 (ref) | 13 | +4 | 77% | 46% |
| GW2 | 3 | 17 | +4 | 71% | 47% |
| GW2 | 2 | 27 | +7 | 70% | 52% |
| GW2 | 1 | 57 | +5 | 67% | 53% |

Hit volume responds strongly (bar 1 triples-to-quintuples early hits, 40–76
pts paid per season). GW1–10 vs the average manager worsens at bar 1 in 5
of 6 arms; bars 2–3 are mixed/flat. corr(pred, realized) per cell swings
0.04–0.77 non-monotonically — the selection trap in mirror (lower bars admit
lower-predicted transfers); not decision-grade. Season totals (identify
only): 2022–2331 across cells.

## The two answers

1. **Does an early hit discount pay?** Only where the wildcard is late, and
   only moderately. Under WC1@6, the solver's own rare bar-4 hits are
   excellent (median +12, 80% beat the charge) and the marginal hits added
   down to bar 2 stay clearly positive against the 4-pt cost (median +7–9,
   61–68% beat 4). At bar 1 the marginal hits fall to ~break-even (52%
   beat 4, tails to −27) and early margins vs the average manager degrade.
2. **Does it still pay with the wildcard at GW2? No.** Under the adopted
   rule the GW2 wildcard (10–13 free transfers) has already cleared the
   dead weight: the bar-4 early hits that remain are already marginal
   (median +4, 46% beat 4) and every discount level hovers at ~50% beat-4 —
   break-even against the charge before path risk. The P1/P2 substitution
   appears a third time, directly measured: early-hit value is a function
   of how much dead weight the opening still carries.

## Verdict

NOT adopted. Under the system as configured (WC1@GW2–3), the early-hit
discount has nothing good left to buy. The one region where it measured
positive (late wildcard, bar 2–3) is a configuration the system no longer
uses — recorded in case the WC1 rule ever moves back. Consistent with the
hit-threshold log's conclusion from the other direction: the bar is best
left at FPL's real charge.

## Files

- `squad/transfer_mip.py` (gate + per-gw bar), `squad/simulator.py` (stamps)
- `eval/run_p3.py`, `eval/measure_p3.py`;
  `data/p1/p3log_{season}_wc{2,6}_bar{3,2,1}.parquet` (gitignored)
