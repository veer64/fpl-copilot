# Seal register — which question 2025-26 is sealed for

2025-26 is the project's holdout season. It may be sealed for ONE open question at a time; a sealed season may be
read only by the pre-registered measurement for that question, run once. Season-figure regeneration on an
already-committed bug fix is a re-measurement, not a selection event, and does not break a seal (see entries).

| date | status | question | notes |
|---|---|---|---|
| 2026-08-26 | spent | props conditional spec (goals term) | spent on season figures; `Logs/props_season_log.md`, `Logs/headroom_diagnosis.md` §6 |
| **2026-08-27** | **SEALED** | **GK p_cs-side λ-spread shrink** (`Logs/gk_investigation_log.md` §10 untested remainder; handoff 2026-08-23 §7 item 3) | tune on 2023-24 / 2024-25 only; trades against CS Brier; needs its own pre-registration before any 2025-26 read. **No other analysis may touch 2025-26 while this seal is in force.** Existing GK diagnostics on 2025-26 (β 0.701 at s = 1; conceded-only holdout 0.790) predate the seal and are on record. |
| 2026-08-27 | considered, rejected as the seal question | KNOWN_ISSUES #18 (p_play_any 0.30 floor) | worth ≤ 0.03 e_points per row on the decision partitions (predicted vs realised appearance 0.93 vs 0.95–0.96 there; the floor is a written-off-band defect) and cannot move decisions. **#18 is DEMOTED, not closed**; 2025-26 remains clean for it. |
| 2026-08-27 | permitted read (not a selection event) | season-figure regeneration on the penalty-join leak fix (commit e04fb72) | the equation is fixed, the fix is committed, no adoption / tuning / fit depends on the result; the GK p_cs seal is unaffected and remains in force. Run log: `Logs/season_totals_index.md` (leak-fixed convention). |
