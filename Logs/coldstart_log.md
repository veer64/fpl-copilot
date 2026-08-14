# Cold start (GW1-7) — where the 11.3 pts/gw actually goes

Model 43.0 pts/gw in GW1-7 against 54.3 from GW8. Investigated 2026-08-13 before
attempting any fix. **The components are not failing. Squad persistence is.**

## The control first: is the opportunity smaller early?

No — it is flat or slightly better early.

| | GW1-7 | GW8-38 |
|---|---|---|
| best-15 available (per gw) | 174.3 | 180.1 |
| oracle squad within budget + club limits | 136.4 | 140.6 |
| mean points per listed player | 1.25 | 1.16 |
| share of listed players who featured | 0.423 | 0.379 |
| hindsight set-and-forget | 73.9 | 65.7 |
| set-and-forget | 34.4 | 36.4 |

Double gameweeks explain 0.72 of the 11.3 (GW8-38 excluding DGWs is 53.6). The
ceiling is flat, so the deficit is real.

## Where it is NOT

| | GW1-7 | GW8-38 |
|---|---|---|
| captain bonus | 7.86 | 4.94 |
| XI selection efficiency (actual / best XI from own 15) | 0.932 | 0.918 |
| e_minutes vs actual minutes | 27.4 / 27.2 | 24.8 / 24.9 |
| all-rows prediction bias | 0.222 | 0.223 |

Captaincy was BETTER early. XI selection was BETTER early. Minutes are well
calibrated in both eras. Component ranking barely moves (Spearman deltas, cold minus
warm): defensive contribution -0.061, goals -0.019, appearance -0.015, assists
-0.010, clean sheets -0.005, bonus -0.001.

Winner's curse is real but small: bias grows with selection depth (all rows 0.22 ->
top-15 0.85), and is worse cold at top-15 (0.852 vs 0.723). That is ~2 pts/gw of a
17.8 pts/gw squad gap.

## Where it IS

| | GW1-7 | GW8-38 |
|---|---|---|
| top-15 by e_points, re-picked each gameweek | **67.71** | **70.35** |
| actual squad (budget-constrained, persistent) | 39.86 | 57.68 |
| **cost of budget + persistence** | **27.86** | **12.68** |

The predictions are fine: freely re-picking the top 15 every week realises 67.7 early
against 70.4 later, a gap of 2.6. The actual squad gap is 17.8. **The cost of being
stuck with your squad is 27.9 pts/gw in GW1-7 and 12.7 pts/gw afterwards.**

Convergence confirms it. Capture of the best-available 15:

    GW1-7  22.7%     GW8-14  32.5%     GW15-38  31.7%

It jumps at GW8 and then plateaus — it does not keep climbing. GW1 squad members
still held: 8/15 at GW8, 6/15 at GW15, 3/15 at GW38. Roughly seven transfers to
escape the opening squad, after which performance is flat.

## What this means for the planned fix

The logged plan was EB shrinkage blending prior-season attacking rates with
current-season form. **At most ~15% of the cold-start gap is prediction quality**
(2.6 of 17.8), so shrinkage cannot be the main lever. It remains defensible for the
winner's-curse component — shrinking noisy rates reduces the error variance the
optimiser's argmax exploits — but that is ~2 pts/gw, not 11.

The real lever is the opening squad and early transfer policy: at GW1 the optimiser
commits the whole budget on a point estimate with no in-season data, and can then
change one player a week. Nothing in the objective values robustness to being wrong.

This converges with the wildcard result, which was measured independently: early
wildcards are worth far more (GW2-5: +72/+82/+71/+43 at W4), and the path-controlled
harness put GW4 at +62.7 over a 3-gameweek window. An early wildcard is precisely an
escape from the persistence trap, and it is already known to be the biggest local
effect in the system.

## The EB blocker — still holds

`understat_season_aggregates.parquet` is SEASON-level only (5,343 rows, one per
player-season) though it does carry true `npxG`. `all_seasons_fixed.parquet` has
per-gameweek `expected_goals` but it is penalty-inclusive; there is no npxG column
and no penalties-taken column to subtract one.

So blending prior-season npxG with CURRENT-season form still needs a new pull.
Scope: Understat per-match player data (`matchesData` on /player/{id}, or rosters on
/match/{id}) does carry `npxG`. Match-level is fewer requests: 380 matches/season,
~11k player-match rows/season, ~7 min/season at 1 req/s, ~25 min for 2022-23..2025-26.
Join needs `player_id_crosswalk_final.csv`, which has the known duplicate-understat_id
defect (KNOWN_ISSUES #3), and match date -> gameweek mapping via `kickoff_time`.

Worth doing eventually. Not worth doing FIRST, on the evidence above.

## Measurement note

This is a Q3 question — persistence compounds by construction — so the windowed
harness cannot measure a fix, and it has already been shown not to add power for
pervasive small effects. Evaluating an opening-squad change honestly needs the
perturbation loop (Instrument B), because a different GW1 squad is exactly the
intervention that sends the season down a different branch.
