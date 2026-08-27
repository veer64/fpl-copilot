# Idea 5 — teammate-absence conditional rates: read-only feasibility (2026-08-27) — FAIL on the tuning seasons

Read-only. 2023-24 and 2024-25 only; 2025-26 not opened. Nothing built, nothing fitted. Output of record:
`Logs/outputs/idea5_feasibility.txt`. Origin: `Logs/headroom_diagnosis.md` §4 idea 5.

## Pre-registered falsifier (stated before any number)

If fewer than ~50 player-gameweeks per season on the decision partitions show a GENUINE absence-driven role
change, the idea is dead and is recorded as a fail. Not amended after the result.

## Definitions (no hindsight)

- **Absence:** the key player's OWN-CUTOFF step-0 `p_start < 0.25` (the model's availability view at the
  deadline); realised minutes = 0 additionally required for the transfer measurement.
- **Key players, one per club per role, from the prior season or the trailing window only:** penalties = the
  trailing designated taker (2 × pens taken so far this season + prior-season pen goals); top attacker =
  prior-season npxG/90 leader (≥ 900 min); creator/set-piece proxy = prior-season xA/90 leader. True set-piece
  duty is NOT in `understat_matches_*.parquet` (no `situation`); it exists only in the unparsed raw shot records
  (`data/history/understat_raw/EPL_*/match_*.json.gz`).
- Decision partitions: likely starters (p_start ≥ .75) and squad-relevant (top 30 by e_points within gameweek).

## Exposure (opportunity) — large

| | 2023-24 | 2024-25 |
|---|---|---|
| taker expected absent: team-weeks (realised) | 166 (130) | 77 (64) |
| top attacker expected absent: team-weeks (realised) → partition teammate rows | 273 (205) → 2,312 | 237 (183) → 1,868 |
| xA leader expected absent → partition teammate rows | 226 (190) → 1,886 | 154 (119) → 1,206 |
| distinct partition player-gameweeks with an expected key absence (realised) | **3,615 (2,978)** | **2,567 (1,981)** |

A key absence sits behind ~10% of decision-partition rows.

## Transfer measurement — not separable from zero

- **Penalties** (designated successor, realised absence, played 94–97%): 2023-24 7 pens in 116 90s (0.060/90)
  vs own baseline 0.031/90 — ~3.5 excess pens, ≈ 1.3 SE; 2024-25 **0 pens in 55 90s** vs baseline 0.018/90.
  Opposite sign across seasons.
- **Top-attacker absence**, paired within-player (absence − baseline), 213 / 196 players: npxG/90 +0.011
  (SE 0.009) / +0.007 (SE 0.010); xA/90 +0.011 / −0.001 (SE 0.008); shots/90 +0.02 / −0.01 (SE 0.05);
  23% / 20% of players gain ≥ 0.05 npxG/90, 25% / 29% lose ≥ 0.05 — symmetric noise.
- **xA-leader absence**, 211 / 168 players: npxG/90 −0.022 (0.011) / −0.009 (0.012); xA/90 +0.002 / −0.004.
- **Minutes**: +8.2 (SE 1.0) / +6.8 and +6.2 / +6.4 minutes per appearance in absence weeks — the ONE effect
  above noise, and it is a minutes-model quantity (the horizon/rotation channel), not a rate change.

The sd of within-player rate differences (0.13–0.15 npxG/90) is ten times any mean shift.

## Verdict against the falsifier — FAIL

Exposure clears 50 by an order of magnitude, but the number of player-gameweeks with a DEMONSTRATED role
change is not separable from zero on either tuning season. Recorded as a fail. No weaker variant explored.
If ever revisited it is a new pre-registration; the data it would need (raw shot `situation` for set-piece
roles; per-match rosters; deadline availability) is on disk.
