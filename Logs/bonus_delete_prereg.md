# Adoption of BONUS_MODE = "delete" — PRE-REGISTRATION (written 2026-08-26, before the adoption measurement was run)

This is an ADOPTION pre-registration. It rides on nothing: the three-arm rebuild study
(`Logs/bonus_rebuild_prereg.md`) established the candidate; this document states the bar the adoption must clear
on its own, the cost it knowingly accepts, and the check that could still stop it. Nothing here may be changed
after a result is seen. The DELETE frames (`walkforward_h6_{season}_bonusdel.parquet`) exist on disk from the
rebuild study and are the canonicals with `e_points := e_points_core`, `exp_bonus := 0`, stamped
`bonus_mode = "delete"`; the adoption measurement reads them and the canonicals; nothing is rebuilt before the
measurement.

## 1. What is being adopted, and why

`assembly.BONUS_MODE = "delete"`: the expected-bonus term is removed from the master equation
(`e_points = e_points_core`). The incumbent term is a LightGBM BPS model trained on realised integer components
and evaluated at expectations, then renormalised per gameweek to the historical mean bonus. Measured on the rows
the optimizer picks from (`Logs/bonus_rebuild_prereg.md` RESULTS): ρ(exp_bonus, realised bonus) on realised
starters −0.03 in every season and −0.09 to −0.19 on the top 30; top-30 forwards credited at 0.30–0.48 of their
realised bonus, keepers at 1.2–2.1×. The term's level was right and its information was wrong: the
renormalisation manufactured a plausible aggregate on top of a calculation that could not tell who earns bonus.
Deleting it raised e_points rank on likely starters by +0.008 / +0.003 / +0.004 and on squad-relevant by
+0.012 / +0.007 / −0.003 (three-season means +0.005 / +0.006), and lowered e_points MAE on starters in every
season. The outcome-weighted rebuild carried real signal (ρ +0.13–0.17) at a quarter of the true level and did
not beat DELETE; it stays gated as the starting point for any future term with a fitted level.

**The reasoning for accepting the cost below:** the optimizer consumes an ORDERING (XI, captain, transfers by
predicted margin, all within a gameweek), not a level. A term that adds roughly the same amount to every starter
costs the ordering nothing when removed, while a term that adds the WRONG amounts — more to defenders than to
forwards, against reality — actively misleads it. Deletion trades a known, roughly constant understatement for
the removal of a misleading signal. That trade is only sound if the understatement really is roughly constant
across the players the optimizer compares; §4 tests exactly that, and it can stop the adoption.

## 2. Pass condition — stated now

On the common population (single-fixture step-0 rows of the canonical files joined to vaastav), DELETE vs the
incumbent, per season, all three seasons:

1. **Sliced rank must not fall** on likely starters (own-cutoff `p_start ≥ 0.75`) or squad-relevant (top 30 by
   incumbent `e_points` within gameweek): Δ Spearman(e_points, realised points) ≥ −0.003 in every season on
   both partitions, AND the three-season mean Δ > 0 on both. (Already observed in the rebuild study for the
   same frames — recorded here as the bar, and re-run rather than copied.)
2. **e_points MAE on realised starters (minutes ≥ 60) not worse in any season.**
3. **Position structure must not be distorted (§4).**
4. Level (§3) is reported, not gated — it is the cost, stated in advance.

Any failure of 1–3 → not adopted; the incumbent stays; the result is appended as a negative.

## 3. The cost, stated in advance

Deleting the term removes the only positive term for bonus, so `e_points` will read LOW by roughly the realised
bonus rate: about **0.29 points per realised starter per week** (vaastav, all three seasons; 0.08 over all rows
including non-appearances), i.e. ~3 points per XI per gameweek and ~120 per season of XI expectation.
Incumbent e_points on realised starters is currently 1.06 / 1.07 / 1.02 of realised points (2023-24 / 2024-25 /
2025-26; e_points 3.33–3.48 vs realised 3.04–3.42 on likely starters, `Logs/topend_calibration_prereg.md` §1e);
after deletion it will sit near 0.97–0.99 of realised. **This is recorded so that a low e_points level is read
as this decision, not as a model failure.** Consequences that depend on LEVEL rather than order — the hit bar
(a −4 charge against predicted margins that are now ~0.29/player lower on both sides of a swap, so margins are
unchanged to first order), bench weight (a ratio, unchanged), captaincy (an argmax, unchanged) — are argued to be
neutral to first order; the season figures (§6) are the read on that, under the standing framing.

## 4. The check that can stop it — is the deleted term uniform across positions?

It is not, and that is known before measuring: the incumbent's mean `exp_bonus` on likely starters is FWD 0.25 /
MID 0.29 / DEF 0.36 / GK 0.35 (2023-24; the other seasons within ±0.03), while realised bonus on the same rows is
FWD 0.40–0.64 / MID 0.27–0.29 / DEF 0.18–0.20 / GK 0.19–0.27. So deletion removes MORE predicted points from
keepers and defenders than from forwards — which is the direction reality says it should go (the incumbent
over-credits DEF/GK and under-credits FWD), but the size of the post-deletion understatement then differs by
position: forwards will be understated by ~0.4–0.6 per week, defenders by ~0.2. A position-dependent
understatement can distort SQUAD STRUCTURE (how much budget goes to forwards vs defenders) even when rank within
a position is intact, because the MIP compares e_points across positions when it allocates money.

**Test, stated now.** On likely starters and on the top 30, per season, per position: (predicted − realised)
e_points, incumbent and DELETE. The adoption holds on this condition if the SPREAD of the position errors — the
max − min across FWD / MID / DEF of (mean e_points − mean realised points) — is **no larger under DELETE than
under the incumbent** in every season on likely starters. If DELETE widens the spread (i.e. the incumbent's
wrong-signed bonus tilt happened to compensate a tilt elsewhere in the equation), the adoption is stopped and the
finding is that the equation needs a position-level correction before the bonus term can go.
GK is reported and not gated (its level is dominated by saves/conceded, not bonus).

Also reported: cross-position rank — Spearman(e_points, points) on the top 30 pooled across positions is
already condition 1; within-position Spearman on likely starters is added so a pooled gain cannot hide a
within-position loss.

## 5. Provenance

`assembly.BONUS_MODE` is stamped per row as `bonus_mode` by all three walk-forward writers. The measurement
asserts `bonus_mode == "delete"` on every row of the DELETE frames and absent-or-`"incumbent"` on the canonicals.
On adoption: `BONUS_MODE = "delete"` becomes the resting value; the canonical files are REBUILT under it (not
merely promoted) and the rebuilt files are asserted equal to the `_bonusdel` frames on `e_points`,
`e_points_core`, `exp_bonus` (bit-exact — the identity `e_points = core + 0` leaves no room for drift); the
previous canonicals are preserved as `walkforward_h6_{season}_prebonusdel.parquet`; a provenance test asserts the
canonicals' `bonus_mode` stamp equals the code constant (the `d1_terms_active` pattern); the rules of record and
the closing position are updated so the new canonical is unambiguous.

## 6. Season figures

Full-system season, all three seasons, reference config (base opening, WC1 @ GW2, WC2 / FH2 / BB1 / BB2 rules of
record, H = 6, decay 0.45, TC2 scored zero), on the DELETE frames — the `bonusdel` arm already queued by the
rebuild study (`eval/run_arms_full_system.py --arm bonusdel`); nothing on disk is re-run; reference cells read
from the existing `fslog_*_base_wc2` logs. Reported last, path and chip-inclusive against 2296 / 2294 / 2206,
with the 2024-25 Salah-held count. Standing framing: sd ~60 single draw; 2024-25's reference is a 97th-percentile
draw that loses on 78% of arms with mean −70; seasons co-move (+0.26). User-facing number, not adoption evidence.
Adoption rests on §2–§4.

---

## RESULTS (2026-08-26; `eval/measure_bonus_delete.py`, output of record `data/penfix_logs/measure_bonus_delete.txt`). VERDICT UNDER §2: **PASS — ADOPT `BONUS_MODE = "delete"`.**

Stamps: every row of the three DELETE frames carries `bonus_mode = "delete"` (162,604 / 152,003 / 165,401 rows);
`e_points_del == e_points_core` asserted on every paired row.

| season | Δρ likely starters | Δρ squad-relevant | Δρ realised started | MAE starters inc → del | position-error spread, likely starters (FWD/MID/DEF) inc → del | cond 1 / 2 / 3 |
|---|---|---|---|---|---|---|
| 2023-24 | **+0.0077** | **+0.0124** | +0.0157 | 2.283 → 2.223 | 0.568 → **0.467** | PASS / PASS / PASS |
| 2024-25 | **+0.0034** | **+0.0068** | +0.0106 | 2.202 → 2.158 | 0.738 → **0.649** | PASS / PASS / PASS |
| 2025-26 | **+0.0040** | −0.0028 | +0.0069 | 2.342 → 2.327 | 0.532 → **0.438** | PASS / PASS / PASS |

Three-season mean Δρ: likely **+0.0050**, squad-relevant **+0.0055** (both > 0). Within-position rank on likely
starters moves by ≤ ±0.007 in every cell (FWD +0.005–0.007, MID/DEF/GK ±0.002): the gain is cross-position
ordering, which is where the deleted term was wrong. Written-off band −0.002 (the term's only membership signal),
uncertain +0.004 / +0.003 / −0.004.

**The cost, as measured (§3):** e_points on likely starters 3.33 / 3.32 / 3.48 → **3.02 / 3.04 / 3.18** against
realised 3.04 / 3.05 / 3.42 (ratio 1.10 / 1.09 / 1.02 → 0.99 / 1.00 / 0.93); on the top 30 ratio 1.11 / 1.19 / 1.08
→ 1.04 / 1.12 / 1.01; all rows 1.18 / 1.17 / 1.12 → 1.08 / 1.08 / 1.03. Realised bonus on likely starters is 0.26
per week in every season and 0.40–0.48 on the top 30; e_points now omits it. **Read a low e_points level as
this decision, not as a model failure.** (The incumbent's level was not honest either — it was ~9% over on
likely starters because the renormalised term over-credited most starters.)

**Position structure (§4):** deletion removes 0.22–0.25 from forwards, 0.26–0.29 from midfielders, 0.30–0.36 from
defenders and 0.31–0.35 from keepers on likely starters — non-uniform, in the direction reality demands (realised
bonus FWD 0.40–0.64, MID 0.27–0.29, DEF 0.18–0.20, GK 0.19–0.27). The post-deletion position errors are FWD
−0.28 / −0.59 / −0.59, MID −0.29 / −0.07 / −0.39, DEF +0.18 / +0.06 / −0.15, GK +0.49 / +0.38 / +0.26: forwards are now
the most UNDER-stated position (by ~0.3–0.6 per week) and keepers remain the most over-stated. The spread across
FWD/MID/DEF narrows in every season (0.57 → 0.47, 0.74 → 0.65, 0.53 → 0.44) — condition 3 passes — so deletion
reduces the structural distortion rather than adding to it; on the top 30 the spread narrows in 2024-25 and widens
slightly in 2023-24 (0.95 → 0.97) and 2025-26 (0.42 → 0.50), reported and not gated. **Standing consequence,
recorded for the next equation change:** with the bonus term gone the equation systematically understates
forwards relative to defenders by ~0.3–0.5 per week on the rows the optimizer picks from. Any future bonus term
must be judged first on whether it closes THAT gap (the outcome-weighted rebuild moved FWD from 0.30–0.48 to
0.66–1.04 of realised bonus and is the starting point); until then the squad-structure tilt is a known cost of a
term that ranked worse than nothing.

Adoption steps (§5) follow: constant flipped, canonicals rebuilt under the gate and asserted equal to the DELETE
frames, previous canonicals preserved as `_prebonusdel`, provenance test added, rules of record and closing
position updated. Season figures are appended below from the `bonusdel` arm already running.

### Season figures (2026-08-26; `eval/run_arms_full_system.py --arm bonusdel`, reference config, reference cells NOT re-run; reads via `eval/measure_arms_full_system.py`, each arm's OWN bench/captain reads; TC2 scored ZERO in both arms; `check_chip_schedule` PASS on every delete-arm schedule)

> *Note added 2026-08-26 (later): the reference 2296 / 2294 / 2206 quoted in this table is the OLD convention (TC2 scored zero, incumbent bonus term). The figures of record are now 2251 / 2306 / 2268 (`bonus_mode=delete` + TC2 in-sim; p4 log §15). This table stands as the comparison that was made at the time.*

| season | reference path | reference chip-incl | delete path | delete chip-incl | Δ |
|---|---|---|---|---|---|
| 2023-24 | 2278 | 2296 | 2216 | **2241** | **−55** |
| 2024-25 | 2255 | 2294 | 2220 | **2277** | **−17** |
| 2025-26 | 2156 | 2206 | 2213 | **2261** | **+55** |

Chip reads itemised (BB1 bench / BB2 bench / TC1 captain bonus; struck TC2 read in brackets):
- 2023-24 — reference +4 (GW7) / +8 (GW34) / +6 (GW6) [+3]; delete +17 (GW7) / +2 (GW34) / +6 (GW6) [+3]
- 2024-25 — reference +5 (GW7) / +25 (GW33) / +9 (GW18) [+7]; delete +17 (GW7) / +31 (GW33) / +9 (GW18) [+7]
- 2025-26 — reference +11 (GW10) / +23 (GW33) / +16 (GW17) [+13]; delete +12 (GW10) / +20 (GW33) / +16 (GW17) [+13]

Chip weeks are IDENTICAL in both arms (policy-fixed WC1@2, WC2@32/31/32, FH2@29/29/34, BB1@7/7/10, BB2@34/33/33;
TC1 selected on each arm's own predictions landed on the same week in every season), so timing is like-for-like and
the differences are the squads each arm built toward those weeks. 2024-25 Salah held 34 weeks / captained 25
(reference 34 / 26) — no concentration difference; the −35 path there is not a Salah effect. Mean Δ chip-inclusive
−6 over three single draws spanning −55 to +55: inside the paired noise (sd ~85) in every season, seasons co-moving
as `Logs/season_anticorrelation_check.md` describes. Standing framing: user-facing number, not adoption evidence;
the adoption rests on §2–§4.
