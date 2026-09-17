from pathlib import Path

p = Path(r"C:\dev\fpl-copilot\Logs\dc_shrinkage_v3_log_2026-09-17.md")
s = p.read_text(encoding="utf-8")
assert "### 2.3" not in s
s = s.rstrip("\n") + r"""

### 2.3 Where the top-30 movement comes from under v3 (scratch `top30_driver.py`, `V2_PREFIX=ref_v3`)

| season | affected club's top-30 slots: record → v2 → v3 | cells with the club in v3's top 30: n, Δ | cells with it in neither: n, Δ | its players' mean points when in v3's top 30 v the top 30's |
|---|---|---|---|---|
| 2023-24 | Luton 13 → 34 → **23** | 7, −0.076 | 48, +0.005 | 3.19 v 3.92 |
| 2024-25 | Ipswich 2 → 4 → 3 | 3, −0.010 | 57, +0.003 | 2.00 v 3.96 |
| 2025-26 | Sunderland 121 → 69 → **51** | 24, −0.029 | 20, −0.003 | 2.93 v 4.04 |

The centre did what it was built to do — a third fewer Luton entries, a quarter fewer Sunderland entries than v2 —
and the slice still loses in the cells where a promoted club's players remain in the top 30 (they still underperform
it: 3.2 v 3.9, 2.9 v 4.0). The worst 2025-26 cells are unchanged from v2: cutoff 2 (10 → 1 Sunderland players, cell
Spearman +0.06 → −0.28), the record's clean-sheet runaway having been lucky. The 2023-24 net did not move because
the seven cells Luton still enters lose as much as the nine did under v2.

### 2.4 Sensitivity rows (prereg §4: informational, never a re-choice) — cutoffs 1–13, the same 170 affected cells

| centre (attack / defence) | Δ starters (SE) | Δ top-30 (SE) | per season top-30, own-SE | rule |
|---|---|---|---|---|
| **v3: −0.31 / +0.20** | +0.0018 (0.0008), +2.1 | −0.0075 (0.0055), **−1.35** | −0.0049 (−0.5) / +0.0022 (+0.4) / −0.0205 (−1.7) | MARGINAL |
| six non-endpoint cohorts: −0.31 / +0.16 | +0.0018 (0.0008), +2.2 | −0.0058 (0.0052), −1.1 | −0.0007 (−0.1) / +0.0041 (+0.7) / −0.0215 (−1.8) | MARGINAL |
| halved: −0.155 / +0.10 | +0.0022 (0.0009), +2.5 | −0.0064 (0.0057), −1.1 | +0.0029 (+0.3) / +0.0064 (+1.0) / −0.0295 (−2.5) | MARGINAL (2025-26 own-SE too) |
| attack only: −0.31 / 0 | +0.0018 (0.0008), +2.2 | −0.0082 (0.0055), −1.5 | −0.0004 (0.0) / +0.0007 (+0.1) / −0.0259 (−2.1) | MARGINAL (2025-26 own-SE too) |
| v2: 0 / 0 (for the reader) | +0.0022 (0.0011), +2.1 | −0.0093 (0.0062), −1.5 | −0.0042 / +0.0016 / −0.0264 | MARGINAL |

Every centre on the table converges, keeps every λ inside the box, never needs the box on the record, and leaves the
unaffected cutoffs bit-identical. Every one is MARGINAL by the same clause: the pooled top-30 slice sits between −1.1
and −1.5 SE, and it is 2025-26 that puts it there at every centre (−0.02 to −0.03), while 2023-24 and 2024-25 hover
about zero. The stamps (`mu_promoted`) were checked on every sensitivity file before its endpoint was read.

## 3. The decision at the stop point (prereg §5 step 2)

**MARGINAL by the rule fixed before the number: not adopted.** Not falsified (no pooled slice below −2 SE; every
structural gate held: unaffected cutoffs bit-identical, 114 of 114 fits converged, every λ inside [0.15, 6.0] with
the 2024-25 Ipswich cells 0.0007 → 0.805, nearest established club 0.66 from a bound, step-0 movement 0.071 at most
with an affected club and 0.0013 without). Marginal on the pooled top-30 slice, −1.35 SE. The rule is applied as
written; the bar is not amended; no sensitivity row is a re-choice.

**What the result says.** The centre is not the problem. Against v2 it did what the prereg said it would — promoted
clubs' early λ down a quarter, fewer of their players in the top 30, the top-30 slice better, starters unchanged —
and the slice is still marginal, because what is left is the component the prereg said would not go away: in
2025-26 the record's Sunderland runaway put a block of one club's players into the top 30 in weeks they scored, and
removing a runaway that paid off reads as a loss on a 30-item rank correlation. No centre on the sensitivity table
moves 2025-26 out of [−0.02, −0.03]. The 2023-24 "Luton flaw" reading of prereg §0 was not borne out: Luton's cells
did not respond to the centre. Starters — the broad slice, where most decisions are made — are up about 2 SE under
every form tried (v2, v3, every sensitivity row).

**Consequence, as the prereg says:** no fourth form without a new argument about what is wrong, and there is none
here — the hinge and the box do their job (the runaway is gone, every fit converges, the floor is 0.25× the league
rate), and the endpoint's residual is the reference's luck, not the form's error. The sensible answer is the user's:
stop changing the prior and let Coventry score. The loud detector keeps carrying the artefact to `/health` and the
phone; Friday's GW5 runs ship exactly as today.

What is in the tree: v3's code and tests on branch `hinge-box-v2` (commits f41a0fe v2, adddc17 v3; suite 433
passed, 1 skipped; unpushed — the model path cannot go to main without the rebuild, and the GW5 extraction-parity
test diverges against the old record by design). main carries the logs, the prereg status lines and KNOWN_ISSUES
#25's note; nothing pushed, nothing deployed, the record untouched. If the user ever wants the form in despite the
rule, the path is scripted (`rebuild_hinge.ps1`, `*_pre_hinge`) — but it would be a judgement call and must be
named as one, never as a passed pre-registration.
"""
p.write_text(s, encoding="utf-8")
print("log complete")
