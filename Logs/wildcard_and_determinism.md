# Session log — 2026-08-11/12: chips, determinism, and where the ceiling actually is

## Two bugs found, both in transfer_mip.py

**1. Nondeterministic MIP.** `teams = {attrs[i]["team"] for i in players}` — a set of
STRINGS, iterated to emit club-limit constraints. Python randomises string hashing
per process, so constraint order differed every run. The feasible region is
identical, but which of several EXACTLY TIED optima the solver returns is not.
With a weak ranking signal, ties are everywhere.

Effect: the same season, same data, same config returned 1973 or 1984 depending on
the run (1984 ×10, 1973 ×4 across 14 runs). We spent an hour attributing this to a
code edit; two runs of each version had landed on different attractors.

Fix: `sorted(...)`. Baseline now stable at 1984 across three runs.

**2. Wildcard silently capped at two transfers.** The relief switched off the hit
penalty, but the free-transfer chain still debited every wildcard transfer:
`ft[1] <= ft[0] - used[0] + hits[0] + 1` forces `used[0] <= ft[0]+1 = 2` at zero
hits. The chip gave 11 transfers at T=1 and 2 at T>1 — so it looked correct in the
truncated one-gameweek test we used to validate it, and was broken everywhere else.

Fix: `spend[wildcard_step] = 0`. Wildcard now makes ~10.6 transfers at H=3.

Both bugs were in the file that still has NO TESTS.

## The odds file was stale

`walkforward_h6_2526.parquet` was built with `ODDS_HORIZON_GWS = 2` — odds through
k+2, which bookmakers have not priced at a Friday deadline. The constant read 0 on
disk only because that was the last rebuild's setting; editing it does not
regenerate the file.

Rebuilt at 0. Headline dropped 2075 -> ~1900. Validation reproduced exactly
(step 0: Spearman 0.715, MAE 1.15, 29,338 rows).

**Finding:** without odds beyond the current gameweek, the transfer MIP scores 1984
against the single-transfer search's 1889. Paired bootstrap: +84, 95% CI
[-24, +188]. **The MIP's advantage over the simple search cannot be established on
honest data.** Its edge was borrowed from odds we would not have.

vs set-and-forget the margin holds: +605, CI [+409, +790].

Caveat on both: `block_bootstrap` resamples gameweeks within ONE realized path per
arm, so it never samples the path lottery. It understates uncertainty in exactly
the dimension that matters here.

## Wildcard: what it is worth

Sweep k=1..38, H=3 decay 0.3, baseline 1984.

| window | mean | median | range | negative |
|---|---|---|---|---|
| chip week only | +7.4 | +5.5 | -15..+53 | 8/38 |
| 3 weeks | +13.0 | +9.0 | -18..+80 | 11/38 |
| 4 weeks | +12.3 | +7.0 | -33..+82 | 11/38 |
| whole season | **-26.2** | -22.0 | -159..+95 | 25/38 |

Report +7.4 (uncontaminated) and +13.0 (persistence). Season-total differencing is
the wrong instrument: sd ~52, and it correlates only 0.40 with the local window.

Early wildcards are worth far more (GW2-5: +72/+82/+71/+43 at W4) because the
opening squad comes from a single-gameweek optimizer with no horizon. Model-visible
headroom falls with k (corr -0.528). Squad value, bank and transfer count are flat
all season, so it is not a budget effect.

**The model cannot time the chip:** corr(predicted gain, realized gain) = +0.38
Pearson, +0.21 Spearman.

## Why the season total goes negative

Not a bug. The chip week itself delivers exactly what is promised (predicted +6.94,
realized +7.11, ratio 102%). From offset 3 onward the model still rates the
wildcard squad ahead while it delivers negative value — players selected because
this model overrated them, with the error persisting because features move slowly.
Paired post-chip mean -2.04/gw, t = -2.33 (directional only; 201 non-independent
observations).

**Tested remedy: minimum-gain threshold per wildcard transfer. FAILED.** It destroys
the local gain monotonically (W1 +7.6 -> -1.0 as lambda goes 0 -> 3) and improves
the season at no value of lambda. Low-gain swaps are budget-enabling legs of
combination moves — the entire reason the MIP exists. The overfitting is spread
across all swaps including the profitable ones; cutting the tail removes value
without removing bias.

## The XI selection leak — 176 points, and it is not fixable here

Baseline XI points 1796; perfect autosubs 1811; oracle XI from the same 15, 1972.

- lost to autosubs not firing: **15** (4 gameweeks)
- lost to starting the wrong XI: **161** (29 gameweeks)

But against a random legal XI (1527), the model captures **60.4%** of available
selection value. The wildcard's "bench leak" is the same number (6.92/11.58 =
59.8%) — the chip has no pathology of its own. ~40% of value added to any 15 lands
on the bench because that is this model's XI-selection efficiency.

Within-squad Spearman(e_points, realized): +0.174 over 15, +0.148 among 60+ minute
players, negative in 8/38 gameweeks.

### bench_weight: keep 0.2

Empirical autosub rate is 0.171 overall — the hand-tuned 0.2 is well calibrated on
level. The sweep (0.0 to 1.0) spans 149 points non-monotonically against path sd
~52, so it cannot rank weights; 0.2 topping it is not evidence.

**Per-player derived weight FAILED, -187 points, and necessarily so.** A bench
player contributes P(slot opens) x P(plays) x E[pts|plays], and `e_points` already
equals P(plays) x E[pts|plays]. Multiplying by P(plays) counts availability twice
(corr(e_points, p_play) = 0.963). The correct derived weight is P(slot opens),
which is player-independent — i.e. the right functional form IS a flat weight, and
its right level is ~0.17-0.18. The hand-tuned constant was closer than the
"principled" version.

Per-SLOT calibration is genuinely wrong (bench GK 0.053, first sub 0.395) but bench
order is assigned after the squad is chosen, so fixing it needs bench-slot variables
in the MIP. Unexplored.

### bench ordering by p_play_any: +2 points

`e_points` is near-useless for ranking bench players specifically
(Spearman vs actually-played: p_play +0.383, e_points +0.067). Reordering gives
1986 vs 1984 on an identical squad path — a clean paired measurement against a
ceiling of 15. Requires threading `p_play_any` through gw_slice -> pools ->
plan_to_team.

## Conclusion

**The optimizer has converged. The predictions are the binding constraint.**

Every lever tested at the optimizer level either failed or was worth ~2 points. The
161-point XI leak requires knowing who will score. The wildcard decay is real but
the only remedy tested shrinks the gain proportionally. Without forward odds the
multi-gameweek MIP cannot be shown to beat a one-transfer-a-week search.

Next work should be on prediction quality — injury and team-news data being the
handoff's highest-value item, and this session is the argument for it: the market's
edge over Dixon-Coles is largely knowledge of lineups and fitness.

## Open

- `transfer_mip.py` still has no tests. First two: a wildcard solve must return
  transfers > ft+1 at T>1; the LP hash must be stable across two subprocesses.
- Triple Captain never measured — read `captain_bonus` off the baseline log.
- Bench-slot variables in the MIP: the one unexplored optimizer idea.
- Second season (2024-25). Every conclusion rests on 2025-26 alone.

All figures: H=3, decay=0.3, mode=balanced, bench_weight=0.2,
`load_season(horizon_aware=True)` on `walkforward_h6_2526.parquet` rebuilt at
`ODDS_HORIZON_GWS = 0`, both fixes applied, baseline 1984.