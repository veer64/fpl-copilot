# Player-prop odds and horizon minutes — full-system season figures (2026-08-26)

## The trade, recorded explicitly

2025-26 was pre-registered as the SEALED component holdout for the props feature (`Logs/props_prereg.md` §5;
`Logs/props_conditional_prereg.md` §5). **Decision taken 2026-08-26: spend 2025-26 on the season figures instead
of keeping it sealed.** Reason: four specifications failed condition (1) of the pass rule on the tuning season —
likely-starter Spearman +0.0087, +0.0078, +0.0085 and +0.0094 against a +0.020 bar — so the holdout's value as an
ADOPTION decision was largely spent already; what remains useful is the user-facing season number. Consequences,
stated so they cannot be forgotten later:

- The `--holdout` guards in `eval/measure_props_endpoint.py` stay as built and unrun. **This is a policy
  simulation, not the pre-registered component test; it does not satisfy or replace it.** Any later component read
  of 2025-26 is no longer a sealed read and must be labelled as such.
- The season figures below are **not adoption evidence** for props, for horizon minutes, or for their combination.

## What was run — eight runs

Config: the current adopted config (opening = base, H = 6, decay 0.45, all chips: WC1 @ GW2, WC2 / FH2 / BB1 / BB2
at the rules-of-record weeks of `eval/run_full_system.py`). Chip accounting per the rules of record: path + BB1
bench + BB2 bench + TC1 captain bonus; **TC2 is played but scored ZERO** (the deliberate understatement of the
2026-08-24 collision fix; the read exists in every log and is shown struck, never added). The chip legality guard
(`squad/chip_legality.py`) runs on every arm. Reference (baseline) cells: `fslog_{season}_base_wc2` —
2296 / 2294 / 2206 chip-inclusive — not re-run except the 2024-25 GW8 like-for-like check.

| arm | status | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|---|
| A. props on — `spec = conditional: w = 0.75, m = 1.396` (Logs/props_conditional_prereg.md PRE-REGISTERED VALUE) | candidate; FAILED condition (1) on the tuning season | no props data before 2024-25 GW8 | from GW8 | full |
| B. horizon minutes on — lever 1 refit (`data/horizon/hmin_*_refit.parquet`) | **FAILED its acceptance test** (rank −7…−9% on likely starters, −7…−21% on squad-relevant, every season, every step; `Logs/horizon_minutes_log.md`). `HORIZON_MINUTES_ACTIVE` stays False; applied in-process for measurement only | full | from GW8 | full |
| C. props + horizon minutes | contains a failed component; curiosity only | — | from GW8 | full |
| baseline re-run from GW8 | like-for-like check of the resume mechanism | — | from GW8 | — |

**Common squad state.** 2024-25 arms start at GW8 from the reference cell's OWN state at the end of GW7
(15 elements, purchase prices, bank 0, one free transfer, 447 points), reconstructed by replaying
`fslog_2024_25_base_wc2` and asserted against it at every gameweek (`eval/run_arms_full_system.py::replay_state`).
2023-24 and 2025-26 arms run the full season from the empty GW1 state, so their opening squads are their own
(built on the arm's predictions). A GW8-start arm is not comparable to a full-season figure: for those cells the
GW8–38 segment delta vs the reference's own GW8–38 is the like-for-like number and the full-season margin is
shown only with that said.

**How the arms were built** (`eval/walkforward_arms.py`): at every cutoff the SAME per-cutoff components as the
canonical file (attacking rates, the step-0 minutes model, the bonus model, Dixon-Coles fixtures, DC hits) are
computed once and the unchanged master equation (`assembly.assemble_fixtures`) is evaluated once per arm; a
no-hook `base` variant is assembled at every cutoff and compared with the canonical walkforward row-for-row
(reproducibility is measured, not assumed — smoke test: max |Δe_points| = 0 on 4,401 rows at 2024-25 cutoff 20).
- Props enter as a gated hook (`squad/props_feature.PropsHook` on `assembly.PROPS_HOOK`, rests None) that blends
  the market's conditional rate into `e_goals` per FIXTURE at step 0 BEFORE the bonus model, so the change reaches
  every downstream term; outfield only; a double priced in one fixture keeps the model on both fixtures and is
  counted (amendment 3); steps 1–5 keep the model (props_prereg.md §6 arm (a)). Verified against the pre-registered
  measurement blend to 1e-16 on the priced outfield singles of the smoke-test cutoff. Because the bonus term is
  normalised per gameweek, unpriced players' e_points move by a hair when priced players' do (mean |Δ| 0.086 over
  711 changed step-0 rows for 415 overridden player-fixtures at that cutoff).
- Horizon minutes enter by replacing the copied step-0 minutes frame at steps 1–5 with the refit's per-step
  p_start / p60 / e_minutes (elements the refit has no row for keep the stale copy; counted); step 0 is the
  canonical frame by construction.
- Every emitted row is stamped `arm`, `props_active`, `props_spec`, `horizon_minutes_active`, `horizon_levers`.

**Instrument A.** Paired W = 3 path deltas at the chip anchors vs the reference cell, as in
`eval/measure_full_system.py` (plus the GW8 entry anchor for the 2024-25 cells). After the first anchor the path
has diverged, so later windows are not path-controlled; windows overlap and are never added. This is the honest
policy read; the season totals are not.

## Caveat, attached to every season figure without exception

Path noise is sd ~60 for a single draw and ~85 paired. The same endpoint could not distinguish a model shrunk 75%
toward the positional mean. 2024-25's baseline is a 97th-percentile draw carrying a ~+169 luck premium
(`Logs/why_2024_25_log.md`). These figures are reported because they are the user-facing number — they are not
adoption evidence and no adoption decision may cite them. If the season totals and the pre-registered component
metrics disagree, the disagreement is stated and is NOT resolved toward whichever is larger.

## Reading (written 2026-08-26 after the eight runs; the generated tables follow below)

**Validation facts first.** (i) The no-hook rebuild reproduced the canonical walk-forward exactly at every one of
the 107 cutoffs built (max |Δe_points| = 0; no row gained or lost). (ii) The 2024-25 baseline re-run from the GW7
state reproduced the reference log's GW8–38 gameweek-for-gameweek (segment 1,808 = 1,808; first divergence: none),
so the GW8-start arms are strictly like-for-like against the reference's own GW8–38. (iii) Every arm's effective
chip schedule passed `check_chip_schedule`; TC2 is scored ZERO in every cell (reads +3 / +7 / +5…+13, struck).
(iv) Amendment 3: partial doubles excluded 24 (2024-25) and 22 (2025-26) in every props arm; player-fixtures
overridden 11,934 (2024-25 GW8–38) and 15,580 (2025-26).

**Summary — chip-inclusive totals (path + BB1 + BB2 + TC1; TC2 zero), Δ vs the reference cell, margin vs average
manager.** 2024-25 arms start at GW8; their like-for-like number is the GW8–38 segment delta and the full-season
margin is not comparable (GW1–7 is the reference's own path).

| | 2023-24 | 2024-25 (GW8–38 segment Δ; stitched chip-inclusive) | 2025-26 |
|---|---|---|---|
| reference | 2296 (+293) | 1,808 segment; 2294 (+286) | 2206 (+311) |
| A. props on | — | **−56** segment (path 1,752); 2243, Δ −51 | **2099**, Δ −107 (path −101); margin +204 |
| B. horizon minutes on (failed component) | **2405**, Δ +109 (path +98); margin +402 | **+49** segment (path 1,857); 2339, Δ +45 | **2122**, Δ −84 (path −86); margin +227 |
| C. both (contains a failed component) | — | **−42** segment (path 1,766); 2257, Δ −37 | **2134**, Δ −72 (path −70); margin +239 |

**Instrument A — paired W = 3 path deltas at anchors, props on vs reference (the honest policy read):**
2024-25: entry@GW8 +6, FH2@29 +16, WC2@31 +1, BB2@33 −38. 2025-26: WC1@2 −11, BB1@10 +18, WC2@32 −27, BB2@33 0,
FH2@34 +32. Windows after the first anchor are not path-controlled and they overlap — they are not summed. Every
window sits inside the paired noise (sd ~85); no anchor shows a consistent sign across the two seasons.

**Season totals and the pre-registered component metrics DISAGREE, and the disagreement is left standing.** On the
tuning season the conditional props spec improved rank on both decision partitions (+0.0094 likely starters,
+0.0206 squad-relevant), improved Brier and log loss on both, and repaired the written-off band — a small, positive
component picture that still failed the +0.020 bar on likely starters. The season figures for the same feature are
−56 (2024-25, GW8–38 like-for-like) and −101 (2025-26) on the path. Sign and size are both inconsistent with the
component read, and both are inside the paired path noise (0.7 and 1.2 sd). Per the rule stated above, this is NOT
resolved toward the larger number in either direction: the component metrics are the pre-registered instrument and
they say "slightly better, below the bar"; the season totals are single draws and they say "worse, within noise".
Neither becomes adoption evidence by the other's failure to agree.

**The horizon-minutes arm is the demonstration of why.** Lever 1 failed its acceptance test on the partitions where
decisions are made, in every season at every step — and its season figures are +109, +45 and −84 chip-inclusive
across the three seasons. A component that is measurably worse where it matters produced the largest single
season gain in this table and the second-largest loss. That spread is the sd ~85 paired noise doing exactly what
the caveat says it does; nothing here revives lever 1, and `HORIZON_MINUTES_ACTIVE` stays False.

**What the props arm did, mechanically.** With w = 0.75 the market replaces three quarters of the model's goals
rate on every priced outfield single at step 0; 2024-25's tuning-season calibration on squad-relevant rows sits
8% under realised (favourite–longshot shape, not corrected), so the arm systematically under-prices the players
the planner most wants, and the BB2@33 window (−38 in 2024-25) is where that shows up in a single draw. The
2025-26 arm also built its own opening squad and its TC1 read fell at GW1 (+8, own prediction) instead of GW17
(+16 for the reference) — a chip-read difference of 8 that is part of the −107, not a path effect.

**Standing caveats carried into every figure above:** US-consensus books (not the live UK books); FanDuel and
1xBet assigned a conditioning rule, unverified; 2024-25's reference is a 97th-percentile draw (+169 luck premium);
one snapshot per fixture; ~1.7 seasons of props data. The `armlog_*` family is not yet in
`Logs/season_totals_index.md` (the index builder enumerates data/p1, data/chips, data/sweep, data/teamnews).

## Results (generated by eval/measure_arms_full_system.py)

### 2023-24

Reference cell `fslog_2023_24_base_wc2`: path **2278**, chip-inclusive **2296** (BB1@GW7 +4, BB2@GW34 +8, TC1@GW6 +6, TC2@GW34 scored ZERO — read ~~+3~~ struck), margin vs average manager +293.

| arm | start | path total | Δ path vs ref | chip reads (BB1 / BB2 / TC1 / ~~TC2~~) | chip-inclusive | Δ vs ref | margin vs avg mgr | segment (GW-start–38) & Δ | partial doubles excluded | legality |
|---|---|---|---|---|---|---|---|---|---|---|
| B. horizon minutes on -- FAILED component test, curiosity only | GW1 | 2376 | +98 | +6 / +17 / +6 (GW6) / ~~+3~~ ZERO | **2405** | +109 | +402 | full season | n/a | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): WC1@GW2 +25; BB1@GW7 -14; FH2@GW29 +10; WC2@GW32 -13; BB2@GW34 -28 |  |  |  |  |  |  |  |  |  |  |

*Caveat (attached without exception):* Path noise is sd ~60 for a single draw and ~85 paired; the same endpoint could not distinguish a model shrunk 75% toward the positional mean; 2024-25's baseline is a 97th-percentile draw carrying a ~+169 luck premium. These figures are the user-facing number -- they are NOT adoption evidence and no adoption decision may cite them.

### 2024-25

Reference cell `fslog_2024_25_base_wc2`: path **2255**, chip-inclusive **2294** (BB1@GW7 +5, BB2@GW33 +25, TC1@GW18 +9, TC2@GW33 scored ZERO — read ~~+7~~ struck), margin vs average manager +286.

| arm | start | path total | Δ path vs ref | chip reads (BB1 / BB2 / TC1 / ~~TC2~~) | chip-inclusive | Δ vs ref | margin vs avg mgr | segment (GW-start–38) & Δ | partial doubles excluded | legality |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline re-run from GW8 (like-for-like check) — **reproduces reference GW8–38: True** | GW8 | 2255 | +0 | +5 / +25 / +9 (GW18) / ~~+7~~ ZERO | **2294** | +0 | +286 (NOT comparable: GW1–7 is the reference's own path) | GW8–38: 1808 vs ref 1808 → **+0**; vs avg mgr over the same weeks +195 | n/a | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): entry@GW8 +0; FH2@GW29 +0; WC2@GW31 +0; BB2@GW33 +0 |  |  |  |  |  |  |  |  |  |  |
| A. props on (candidate; conditional spec) | GW8 | 2199 | -56 | +5 / +30 / +9 (GW18) / ~~+7~~ ZERO | **2243** | -51 | +235 (NOT comparable: GW1–7 is the reference's own path) | GW8–38: 1752 vs ref 1808 → **-56**; vs avg mgr over the same weeks +139 | 24 | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): entry@GW8 +6; FH2@GW29 +16; WC2@GW31 +1; BB2@GW33 -38 |  |  |  |  |  |  |  |  |  |  |
| B. horizon minutes on -- FAILED component test, curiosity only | GW8 | 2304 | +49 | +5 / +21 / +9 (GW18) / ~~+7~~ ZERO | **2339** | +45 | +331 (NOT comparable: GW1–7 is the reference's own path) | GW8–38: 1857 vs ref 1808 → **+49**; vs avg mgr over the same weeks +244 | n/a | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): entry@GW8 -6; FH2@GW29 -4; WC2@GW31 +12; BB2@GW33 +1 |  |  |  |  |  |  |  |  |  |  |
| C. props + horizon minutes -- contains a failed component, curiosity only | GW8 | 2213 | -42 | +5 / +30 / +9 (GW18) / ~~+7~~ ZERO | **2257** | -37 | +249 (NOT comparable: GW1–7 is the reference's own path) | GW8–38: 1766 vs ref 1808 → **-42**; vs avg mgr over the same weeks +153 | 24 | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): entry@GW8 +5; FH2@GW29 +11; WC2@GW31 +10; BB2@GW33 -20 |  |  |  |  |  |  |  |  |  |  |

*Caveat (attached without exception):* Path noise is sd ~60 for a single draw and ~85 paired; the same endpoint could not distinguish a model shrunk 75% toward the positional mean; 2024-25's baseline is a 97th-percentile draw carrying a ~+169 luck premium. These figures are the user-facing number -- they are NOT adoption evidence and no adoption decision may cite them.

### 2025-26

Reference cell `fslog_2025_26_base_wc2`: path **2156**, chip-inclusive **2206** (BB1@GW10 +11, BB2@GW33 +23, TC1@GW17 +16, TC2@GW33 scored ZERO — read ~~+13~~ struck), margin vs average manager +311.

| arm | start | path total | Δ path vs ref | chip reads (BB1 / BB2 / TC1 / ~~TC2~~) | chip-inclusive | Δ vs ref | margin vs avg mgr | segment (GW-start–38) & Δ | partial doubles excluded | legality |
|---|---|---|---|---|---|---|---|---|---|---|
| A. props on (candidate; conditional spec) | GW1 | 2055 | -101 | +10 / +26 / +8 (GW1) / ~~+5~~ ZERO | **2099** | -107 | +204 | full season | 22 | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): WC1@GW2 -11; BB1@GW10 +18; WC2@GW32 -27; BB2@GW33 +0; FH2@GW34 +32 |  |  |  |  |  |  |  |  |  |  |
| B. horizon minutes on -- FAILED component test, curiosity only | GW1 | 2070 | -86 | +12 / +24 / +16 (GW17) / ~~+13~~ ZERO | **2122** | -84 | +227 | full season | n/a | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): WC1@GW2 +0; BB1@GW10 +10; WC2@GW32 -31; BB2@GW33 -4; FH2@GW34 +22 |  |  |  |  |  |  |  |  |  |  |
| C. props + horizon minutes -- contains a failed component, curiosity only | GW1 | 2086 | -70 | +19 / +21 / +8 (GW1) / ~~+8~~ ZERO | **2134** | -72 | +239 | full season | 22 | OK |
| ↳ W=3 paired deltas vs reference (Instrument A): WC1@GW2 +10; BB1@GW10 -15; WC2@GW32 -11; BB2@GW33 +19; FH2@GW34 +41 |  |  |  |  |  |  |  |  |  |  |

*Caveat (attached without exception):* Path noise is sd ~60 for a single draw and ~85 paired; the same endpoint could not distinguish a model shrunk 75% toward the positional mean; 2024-25's baseline is a 97th-percentile draw carrying a ~+169 luck premium. These figures are the user-facing number -- they are NOT adoption evidence and no adoption decision may cite them.
