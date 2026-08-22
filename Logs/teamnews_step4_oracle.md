# Team-news investigation — step 4: the oracle-minutes upper bound
# (2026-08-22)

Instrument: `squad/oracle_minutes.py` — realized minutes injected into the
prediction frame (appearance/CS/DC recomputed exactly; attacking/bonus/small
terms scaled by actual-vs-expected minutes, stated approximation), gated
`ORACLE_MINUTES_ACTIVE` (False on disk), stamped `oracle_minutes_active`
per decision-log row, prominent never-adopt warning in the module.
DELIBERATE LEAKAGE — a measuring instrument. Runs: 3 sims under the full
adopted system (base opening, WC1@2, all chips), references REUSED
(fslog_base_wc2). Suite green with the gate off. Artefacts:
data/teamnews/oraclelog_*.parquet; measurement eval/measure_teamnews_oracle.py.

**Scope caveat, prominent:** the oracle knows minutes across the WHOLE H=6
horizon — deliberately stronger than any lineup service, which sells
imperfect knowledge of the NEXT deadline only. Every figure below is an
upper bound on all minutes-knowledge channels combined, not a subscription
estimate.

## Results

| season | oracle | ref | path Δ | chip-incl (margin vs avg) | per-gw Δ med / +wks | capt. changed / value | 52-case avoided |
|---|---|---|---|---|---|---|---|
| 2023-24 | 2424 | 2278 | **+146** | 2493 (+490) vs 2299 (+296) | +5 / 21 of 38 | 15 wks / +31 | 13/13 (12 unowned, 1 benched) |
| 2024-25 | 2364 | 2255 | **+109** | 2406 (+398) vs 2301 (+293) | +4 / 23 of 38 | 11 wks / +25 | 24/24 (20, 4) |
| 2025-26 | 2251 | 2156 | **+95** | 2313 (+418) vs 2219 (+324) | +5 / 20 of 38 | 19 wks / +10 | 15/15 (10, 5) |

Mean +117/season. All three seasons positive, each delta > one path-noise
sd; per-gw distributions (q25 ≈ −7..−11, q75 ≈ +12..+15, extremes ±38) are
the evidence base per the standing rule — the totals are unusually likely
to be real here, but the per-gw spread shows the gain is broad, not a few
lottery weeks. The oracle NEVER started any of the 52 case players (full
avoidance: mostly by not owning them, the rest benched).

## The decomposition — and what it says about step 3

- **52-case channel: +27 / +11 / +18 (step-3 per-case values of the avoided
  cases) ≈ the step-3 ceiling — about 16% of the oracle's total gain.**
- **Captaincy hygiene: +31 / +25 / +10** (realized value of 11–19 changed
  armbands/season).
- **The rest — roughly 60–75% of the gain — is the transfer/rotation-timing
  channel:** ~75 transfers/season differ from the reference (E2 sums
  +457/+553/+312, gross and overlapping — not additive with the path
  delta), and the biggest single moves are minutes-driven timing plays
  (Isak→Haaland +35, Nkunku→Barnes +38, Díaz→Havertz +30), i.e. being on
  players in the weeks they actually start — not avoiding blank-ups.
- The identical-squad-weeks cut of the decomposition came back DEGENERATE
  (zero such weeks — the oracle diverges at GW1), so selection hygiene is
  evidenced by the captaincy line only; XI/bench hygiene beyond captaincy
  is folded into the residual. Channels interact; the split is honest
  approximation, not accounting.

## Verdict

**Step 3 measured the smallest channel.** Perfect minutes knowledge is
worth ~+95..+146/season, of which the 52-case blank-avoidance frame
explains only about a sixth; the dominant value is week-by-week rotation timing
of transfers, with captaincy hygiene second. A lineup subscription
therefore attacks a channel worth (at the oracle bound) ~100+ pts/season —
but a real service delivers ONE gameweek of imperfect knowledge, not six of
perfect. The honest subscription range stays wide: above step 3's ~5–15
(that floor ignored the dominant channels entirely) and far below +117.
Narrowing it needs a one-gameweek-only oracle (knowledge at step 0 only) —
the natural step 5, one flag away in the same instrument.
