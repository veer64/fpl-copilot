# Season totals index -- every simulated season total, one place

Generated 2026-08-26 by eval/build_season_totals_index.py. Covers ALL simlogs
on disk: data/sweep, data/chips, data/p1 (p1log/wclog/fslog/p3log/p5log),
data/teamnews (oraclelog) and data/arms (armlog -- closed non-adoptions), plus
the pre-canonical reference figures.

**Framing (mandatory):** a season total is ONE draw from a distribution with
path sd ~60 (M1 failed). This index exists so figures can be LOCATED and
grouped by provenance -- comparisons are valid ONLY within a family AND only
between rows differing by exactly the variable under test. Season totals
never decide adoptions; component and windowed metrics do. Standing
illustration (2026-08-26, Logs/instrument_b_log.md): horizon-minutes lever 1,
measurably WORSE where decisions are made, scored +109 / +49 / -84 by season
total; props, slightly better on the component read, scored -56 / -107. Run
the totals first and both calls come out wrong.

**REFERENCE CELLS OF RECORD (moved 2026-08-26).** The system as configured is
`BONUS_MODE = "delete"` (adopted on component metrics, Logs/bonus_delete_prereg.md)
with Triple Captain 2 scheduled IN-SIM on the rule-of-record week (p4 log
section 12c (ii): the earliest second-half double holding no other chip -- GW25 /
GW24 / GW26 -- chosen from the calendar alone; the captain is the MIP's own cap
variable at that deadline, argmax step-0 e_points in the XI from cutoff
predictions; no post-deadline information). Reference cells:
**2023-24 path 2226 / chip-inclusive 2251 (margin +248); 2024-25 path 2249 /
2306 (+298); 2025-26 path 2220 / 2268 (+373)**; chip reads BB1 +17/+17/+12,
BB2 +2/+31/+20, TC1 +6/+9/+16, TC2 +10/+29/+7 (in the path). The path did not
move when TC2 was scheduled (+0 in all three seasons: squads, transfers and
captains identical to the no-TC2 run gameweek by gameweek), so TC2 is cleanly
the extra captain multiple and nothing else. **Any figure quoting 2296 / 2294 /
2206 is on the OLD convention (TC2 scored zero, incumbent bonus term) and is
SUPERSEDED as a reference**; those rows remain indexed and flagged. Standing
framing unchanged: sd ~60 single draw; 2024-25's reference is a
97th-percentile draw that loses on 78% of arms with mean -70
(Logs/season_anticorrelation_check.md); seasons co-move (+0.26). User-facing
figures, not adoption evidence.

**CORRECTION OF RECORD (2026-08-24) -- the TC2/BB2 same-week read.** From
P4 (2026-08-20) through the first regeneration of this index earlier on
2026-08-24, the chip-inclusive convention added BOTH the Bench Boost bench
read and the Triple Captain 2 captain-bonus read on the SAME gameweek: TC2's
rule ("largest double gameweek") and BB2's rule ("second-half week with most
doubling teams") select the same week whenever the season's biggest double
falls in the second half, which it did in all three seasons (GW34 / GW33 /
GW33). FPL permits ONE chip per gameweek. Those figures therefore priced an
ILLEGAL play -- previously described as "optimistic by min(TC2, BB2 bench)",
which understated it: no legal play realises them. The simulated PATHS were
never affected (202 logs checked: zero in-sim collisions, eval/
check_collision.py); the violation lived entirely in the post-hoc read
layer, and the only guard was a total-vs-total drift assert that is circular
for a convention error. What changed: (1) on any gameweek carrying two reads
the Bench Boost read is KEPT and the TC2 read is DROPPED -- shown struck
through in `chip reads`, flagged per row, never silently removed. BB2 has no
legal alternative week in two of the three seasons (no other H2 double
clears its >=4-team floor) and a Triple Captain can always move; dropping is
hindsight-free. Relocating TC2 and reading what the captain happened to score
there (GW37/GW24/GW26 -> 2311/2323/2213) is a single-draw hindsight read and
is NOT adopted. (2) Reference cells: 2299/2301/2219 -> **2296/2294/2206**
(-3/-7/-13); every fslog, p3log, p5log, oraclelog and BB-carrying chips-era
row moved by its own TC2 read. (3) Every row's effective chip schedule is
now checked structurally by squad/chip_legality.py (one chip per gameweek,
one of each chip per half, reads only on played weeks) -- independent of any
total -- before this file is written; tests/test_chip_legality.py proves the
check fails on the old convention. (4) TC2's rule of record is revised (p4
log section 12c; tie-break (ii) adopted 2026-08-24: the EARLIEST second-half
double excluding weeks already holding a chip -- structural, calendar-only);
KNOWN_ISSUES #16 records the failure.

**PATH vs CHIP-INCLUSIVE (stored vs recomputed).** No log family stores a
chip-inclusive total. The stored figure is `final_total` = the PATH total
(the simulator scores no chip points EXCEPT an in-sim Triple Captain, which
triples the captain inside the path -- the bonusdel_tc2 reference cells;
asserted == points.sum() for every file). Every chip-inclusive figure here is RECOMPUTED by the family's
measure-script-of-record convention minus the illegal read (see the
generator's docstring for the exact per-family rules). Recomputed values are
marked **(r)** and decomposed in the `chip reads` column; `= path` means no
exogenous chips were scheduled, so the two totals are identical by
construction. The recompute chain is drift-checked at generation time against
the old-convention fslog base_wc2 figures (2296/2294/2206), the reference
cells of record (arms bonusdel_tc2 -> 2251/2306/2268) and the p1 baselines
(2204/2362/2032); generation FAILS on drift. That check is
circular by construction (same convention both sides) and is kept ONLY for
drift; legality is the structural check above.

**Average-manager verification:** claimed averages 2038 / 2154 / 1895 vs
fplcache sum of events[].average_entry_score 2003 / 2008 / 1895. 2025-26
MATCHES; 2023-24 is 35 off; 2024-25 is 146 off. The statistics differ by
definition (sum of per-GW averages != average of season totals; late entries
and chips break the equivalence), so BOTH margins are shown, computed on the
CHIP-INCLUSIVE total (= path where no reads exist).

**Provenance notes:** (1) the 2023-24 sweep sims ran against the
pre-#15-rebuild canonical, proven BIT-IDENTICAL to the rebuilt file
(dc_enabled=False season), so they belong to the post-#15 family. (2) The
2023-24/2024-25 _synth files predate the #15 rebuild but are DC-irrelevant
seasons -- same family. (3) The REFERENCE rows predate the DC-wiring fix
(#15); 1984/1938 also predate D1 and the rate blend; 2028 predates the
blend. They are comparable to NOTHING in this index. (4) bb_aware=off rows
flip transfer_mip.BENCH_BOOST_AWARE -- their baseline (gate off) differs by
chips+gate JOINTLY: that package is the declared variable (p4 log section
8). (5) `run` is the log file's mtime (the sim run date), not the
walkforward build date. (6) 2024-25 rows: every deviation measured against
the 2362 baseline carries the half-artefact correction
(Logs/why_2024_25_log.md) -- the baseline is a 97th-percentile draw.

**Superseded flags:** rows whose walkforward file carries a stale suffix
(_prefix, _dcbase, _prerateblend, _preunify, _presynth, _synth, _baseline, _d1cards, _av, _odds2, _dgwonly) are marked SUPERSEDED -- retained, never deleted, comparable only
within their own family.

**Walkforward provenance key** (stamps read from the files themselves):

| wf file | minutes_availability | odds_horizon_gws | dgw_handling | d1_terms_active | cs_unified | rate_blend_active | dc_rule_active | synthetic_lambda_active |
|---|---|---|---|---|---|---|---|---|
| arms/walkforward_h6_2023_24_hmin.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| arms/walkforward_h6_2024_25_both.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| arms/walkforward_h6_2024_25_hmin.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| arms/walkforward_h6_2024_25_props.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| arms/walkforward_h6_2025_26_both.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| arms/walkforward_h6_2025_26_hmin.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| arms/walkforward_h6_2025_26_props.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2023_24.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2023_24_bonusdel.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2023_24_bonusow.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2023_24_cal.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2023_24_cal_penfix.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2023_24_penfix.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2023_24_synth.parquet (post-#15 canonical+synth) | True | 0 | per_fixture | True | False | True | False | True |
| walkforward_h6_2024_25.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2024_25_bonusdel.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2024_25_bonusow.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2024_25_cal.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2024_25_cal_penfix.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2024_25_penfix.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | False | False |
| walkforward_h6_2024_25_synth.parquet (post-#15 canonical+synth) | True | 0 | per_fixture | True | False | True | False | True |
| walkforward_h6_2025_26.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2025_26_bonusdel.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2025_26_bonusow.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2025_26_cal.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2025_26_cal_penfix.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2025_26_penfix.parquet (post-#15 canonical) | True | 0 | per_fixture | True | False | True | True | False |
| walkforward_h6_2025_26_synth.parquet (post-#15 canonical+synth) | True | 0 | per_fixture | True | False | True | True | True |
## SWEEP -- H x decay grid, no chips (data/sweep)

54 cells: {base, synth} x 3 seasons x H {3,4,6} x decay {.3,.45,.6}. synth rows ride the _synth walkforward (D4, closed NOT adopted) and are flagged superseded.

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | base | 3 | 0.3 | -- | **2153** | = path 2153 | -- | +115 | +150 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H3_d30.parquet |
| 2023-24 | base | 3 | 0.45 | -- | **2068** | = path 2068 | -- | +30 | +65 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H3_d45.parquet |
| 2023-24 | base | 3 | 0.6 | -- | **2228** | = path 2228 | -- | +190 | +225 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H3_d60.parquet |
| 2023-24 | base | 4 | 0.3 | -- | **2136** | = path 2136 | -- | +98 | +133 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H4_d30.parquet |
| 2023-24 | base | 4 | 0.45 | -- | **2168** | = path 2168 | -- | +130 | +165 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H4_d45.parquet |
| 2023-24 | base | 4 | 0.6 | -- | **2068** | = path 2068 | -- | +30 | +65 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H4_d60.parquet |
| 2023-24 | base | 6 | 0.3 | -- | **2177** | = path 2177 | -- | +139 | +174 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H6_d30.parquet |
| 2023-24 | base | 6 | 0.45 | -- | **2204** | = path 2204 | -- | +166 | +201 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H6_d45.parquet |
| 2023-24 | base | 6 | 0.6 | -- | **2175** | = path 2175 | -- | +137 | +172 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2023_24_base_H6_d60.parquet |
| 2023-24 | synth | 3 | 0.3 | -- | **2151** | = path 2151 | -- | +113 | +148 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H3_d30.parquet |
| 2023-24 | synth | 3 | 0.45 | -- | **2148** | = path 2148 | -- | +110 | +145 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H3_d45.parquet |
| 2023-24 | synth | 3 | 0.6 | -- | **2184** | = path 2184 | -- | +146 | +181 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H3_d60.parquet |
| 2023-24 | synth | 4 | 0.3 | -- | **2151** | = path 2151 | -- | +113 | +148 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H4_d30.parquet |
| 2023-24 | synth | 4 | 0.45 | -- | **2149** | = path 2149 | -- | +111 | +146 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H4_d45.parquet |
| 2023-24 | synth | 4 | 0.6 | -- | **2110** | = path 2110 | -- | +72 | +107 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H4_d60.parquet |
| 2023-24 | synth | 6 | 0.3 | -- | **1975** | = path 1975 | -- | -63 | -28 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H6_d30.parquet |
| 2023-24 | synth | 6 | 0.45 | -- | **2138** | = path 2138 | -- | +100 | +135 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H6_d45.parquet |
| 2023-24 | synth | 6 | 0.6 | -- | **2126** | = path 2126 | -- | +88 | +123 | walkforward_h6_2023_24_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2023_24_synth_H6_d60.parquet |
| 2024-25 | base | 3 | 0.3 | -- | **2331** | = path 2331 | -- | +177 | +323 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H3_d30.parquet |
| 2024-25 | base | 3 | 0.45 | -- | **2391** | = path 2391 | -- | +237 | +383 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H3_d45.parquet |
| 2024-25 | base | 3 | 0.6 | -- | **2415** | = path 2415 | -- | +261 | +407 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H3_d60.parquet |
| 2024-25 | base | 4 | 0.3 | -- | **2243** | = path 2243 | -- | +89 | +235 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H4_d30.parquet |
| 2024-25 | base | 4 | 0.45 | -- | **2393** | = path 2393 | -- | +239 | +385 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H4_d45.parquet |
| 2024-25 | base | 4 | 0.6 | -- | **2326** | = path 2326 | -- | +172 | +318 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H4_d60.parquet |
| 2024-25 | base | 6 | 0.3 | -- | **2243** | = path 2243 | -- | +89 | +235 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H6_d30.parquet |
| 2024-25 | base | 6 | 0.45 | -- | **2362** | = path 2362 | -- | +208 | +354 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H6_d45.parquet |
| 2024-25 | base | 6 | 0.6 | -- | **2381** | = path 2381 | -- | +227 | +373 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2024_25_base_H6_d60.parquet |
| 2024-25 | synth | 3 | 0.3 | -- | **2370** | = path 2370 | -- | +216 | +362 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H3_d30.parquet |
| 2024-25 | synth | 3 | 0.45 | -- | **2277** | = path 2277 | -- | +123 | +269 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H3_d45.parquet |
| 2024-25 | synth | 3 | 0.6 | -- | **2272** | = path 2272 | -- | +118 | +264 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H3_d60.parquet |
| 2024-25 | synth | 4 | 0.3 | -- | **2376** | = path 2376 | -- | +222 | +368 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H4_d30.parquet |
| 2024-25 | synth | 4 | 0.45 | -- | **2288** | = path 2288 | -- | +134 | +280 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H4_d45.parquet |
| 2024-25 | synth | 4 | 0.6 | -- | **2254** | = path 2254 | -- | +100 | +246 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H4_d60.parquet |
| 2024-25 | synth | 6 | 0.3 | -- | **2360** | = path 2360 | -- | +206 | +352 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H6_d30.parquet |
| 2024-25 | synth | 6 | 0.45 | -- | **2340** | = path 2340 | -- | +186 | +332 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H6_d45.parquet |
| 2024-25 | synth | 6 | 0.6 | -- | **2330** | = path 2330 | -- | +176 | +322 | walkforward_h6_2024_25_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2024_25_synth_H6_d60.parquet |
| 2025-26 | base | 3 | 0.3 | -- | **2004** | = path 2004 | -- | +109 | +109 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H3_d30.parquet |
| 2025-26 | base | 3 | 0.45 | -- | **1929** | = path 1929 | -- | +34 | +34 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H3_d45.parquet |
| 2025-26 | base | 3 | 0.6 | -- | **2026** | = path 2026 | -- | +131 | +131 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H3_d60.parquet |
| 2025-26 | base | 4 | 0.3 | -- | **1996** | = path 1996 | -- | +101 | +101 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H4_d30.parquet |
| 2025-26 | base | 4 | 0.45 | -- | **2032** | = path 2032 | -- | +137 | +137 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H4_d45.parquet |
| 2025-26 | base | 4 | 0.6 | -- | **2055** | = path 2055 | -- | +160 | +160 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H4_d60.parquet |
| 2025-26 | base | 6 | 0.3 | -- | **1996** | = path 1996 | -- | +101 | +101 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H6_d30.parquet |
| 2025-26 | base | 6 | 0.45 | -- | **2032** | = path 2032 | -- | +137 | +137 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H6_d45.parquet |
| 2025-26 | base | 6 | 0.6 | -- | **2081** | = path 2081 | -- | +186 | +186 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-19 | -- | sweep/simlog_2025_26_base_H6_d60.parquet |
| 2025-26 | synth | 3 | 0.3 | -- | **2065** | = path 2065 | -- | +170 | +170 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H3_d30.parquet |
| 2025-26 | synth | 3 | 0.45 | -- | **2045** | = path 2045 | -- | +150 | +150 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H3_d45.parquet |
| 2025-26 | synth | 3 | 0.6 | -- | **1971** | = path 1971 | -- | +76 | +76 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H3_d60.parquet |
| 2025-26 | synth | 4 | 0.3 | -- | **2033** | = path 2033 | -- | +138 | +138 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H4_d30.parquet |
| 2025-26 | synth | 4 | 0.45 | -- | **2075** | = path 2075 | -- | +180 | +180 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-19 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H4_d45.parquet |
| 2025-26 | synth | 4 | 0.6 | -- | **2028** | = path 2028 | -- | +133 | +133 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H4_d60.parquet |
| 2025-26 | synth | 6 | 0.3 | -- | **2102** | = path 2102 | -- | +207 | +207 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H6_d30.parquet |
| 2025-26 | synth | 6 | 0.45 | -- | **1985** | = path 1985 | -- | +90 | +90 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H6_d45.parquet |
| 2025-26 | synth | 6 | 0.6 | -- | **1979** | = path 1979 | -- | +84 | +84 | walkforward_h6_2025_26_synth.parquet | av=T d1=T blend=T dgw=per_fixture synth=T | -- | 2026-08-20 | SUPERSEDED (stale wf suffix _synth) | sweep/simlog_2025_26_synth_H6_d60.parquet |

## CHIPS ERA -- P4 structural chip study (data/chips)

H=6; decay 0.85 unless the config name says _d60/_d45. Chip-inclusive = path + bench@BB where a BB was scheduled. The pkg2h / phase-2 convention ALSO read capbonus@BB (TC2) on the same week -- that read is an illegal play (one chip per gameweek) and is DROPPED, shown struck through (corrected 2026-08-24). wc/fh-only configs have no exogenous reads. The 3 pkg_d45 rows are newly indexed (they postdate the old index).

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | baseline | 6 | 0.85 | -- | **2189** | = path 2189 | -- | +151 | +186 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_baseline.parquet |
| 2023-24 | bbaware_wc33_bb34 | 6 | 0.85 | WC@33 BB@34 | **2218** | **2221** (r) | bench@GW34+3 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) | +183 | +218 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2023_24_bbaware_wc33_bb34.parquet |
| 2023-24 | combined_d60 | 6 | 0.6 | WC@4,32 FH@29 BB@34 | **2218** | **2229** (r) | bench@GW34+11 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) | +191 | +226 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2023_24_combined_d60.parquet |
| 2023-24 | combined_d85 | 6 | 0.85 | WC@4,32 FH@29 BB@34 | **2295** | **2298** (r) | bench@GW34+3 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) | +260 | +295 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2023_24_combined_d85.parquet |
| 2023-24 | fh1_gw17 | 6 | 0.85 | FH@17 | **2098** | = path 2098 | -- | +60 | +95 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_fh1_gw17.parquet |
| 2023-24 | fh2_gw29 | 6 | 0.85 | FH@29 | **2234** | = path 2234 | -- | +196 | +231 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_fh2_gw29.parquet |
| 2023-24 | pkg_d45 | 6 | 0.45 | WC@4,32 FH@29 BB@34 | **2233** | **2279** (r) | bench@GW34+46 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) | +241 | +276 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2023_24_pkg_d45.parquet |
| 2023-24 | wc1_gw4 | 6 | 0.85 | WC@4 | **2159** | = path 2159 | -- | +121 | +156 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_wc1_gw4.parquet |
| 2023-24 | wc1_gw5 | 6 | 0.85 | WC@5 | **2182** | = path 2182 | -- | +144 | +179 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_wc1_gw5.parquet |
| 2023-24 | wc1_gw6 | 6 | 0.85 | WC@6 | **2211** | = path 2211 | -- | +173 | +208 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_wc1_gw6.parquet |
| 2023-24 | wc2_staged_gw33 | 6 | 0.85 | WC@33 | **2208** | = path 2208 | -- | +170 | +205 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_wc2_staged_gw33.parquet |
| 2023-24 | wc2_swing_gw32 | 6 | 0.85 | WC@32 | **2222** | = path 2222 | -- | +184 | +219 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2023_24_wc2_swing_gw32.parquet |
| 2024-25 | baseline | 6 | 0.85 | -- | **2184** | = path 2184 | -- | +30 | +176 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_baseline.parquet |
| 2024-25 | bbaware_wc32_bb33 | 6 | 0.85 | WC@32 BB@33 | **2130** | **2147** (r) | bench@GW33+17 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) | -7 | +139 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2024_25_bbaware_wc32_bb33.parquet |
| 2024-25 | combined_d60 | 6 | 0.6 | WC@4,31 FH@29 BB@33 | **2168** | **2197** (r) | bench@GW33+29 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) | +43 | +189 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2024_25_combined_d60.parquet |
| 2024-25 | combined_d85 | 6 | 0.85 | WC@4,31 FH@29 BB@33 | **2129** | **2148** (r) | bench@GW33+19 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) | -6 | +140 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2024_25_combined_d85.parquet |
| 2024-25 | fh1_gw15 | 6 | 0.85 | FH@15 | **2115** | = path 2115 | -- | -39 | +107 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_fh1_gw15.parquet |
| 2024-25 | fh2_gw29 | 6 | 0.85 | FH@29 | **2186** | = path 2186 | -- | +32 | +178 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_fh2_gw29.parquet |
| 2024-25 | pkg_d45 | 6 | 0.45 | WC@4,31 FH@29 BB@33 | **2118** | **2147** (r) | bench@GW33+29 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) | -7 | +139 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2024_25_pkg_d45.parquet |
| 2024-25 | wc1_gw4 | 6 | 0.85 | WC@4 | **2126** | = path 2126 | -- | -28 | +118 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_wc1_gw4.parquet |
| 2024-25 | wc1_gw5 | 6 | 0.85 | WC@5 | **2188** | = path 2188 | -- | +34 | +180 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_wc1_gw5.parquet |
| 2024-25 | wc1_gw6 | 6 | 0.85 | WC@6 | **2058** | = path 2058 | -- | -96 | +50 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_wc1_gw6.parquet |
| 2024-25 | wc2_staged_gw32 | 6 | 0.85 | WC@32 | **2167** | = path 2167 | -- | +13 | +159 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_wc2_staged_gw32.parquet |
| 2024-25 | wc2_swing_gw31 | 6 | 0.85 | WC@31 | **2158** | = path 2158 | -- | +4 | +150 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2024_25_wc2_swing_gw31.parquet |
| 2025-26 | baseline | 6 | 0.85 | -- | **1927** | = path 1927 | -- | +32 | +32 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2025_26_baseline.parquet |
| 2025-26 | bbaware_wc32_bb33 | 6 | 0.85 | WC@32 BB@33 | **1958** | **1969** (r) | bench@GW33+11 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) | +74 | +74 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2025_26_bbaware_wc32_bb33.parquet |
| 2025-26 | combined_d60 | 6 | 0.6 | WC@4,32 FH@34 BB@33 | **1965** | **1991** (r) | bench@GW33+26 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) | +96 | +96 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2025_26_combined_d60.parquet |
| 2025-26 | combined_d85 | 6 | 0.85 | WC@4,32 FH@34 BB@33 | **2001** | **2011** (r) | bench@GW33+10 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) | +116 | +116 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2025_26_combined_d85.parquet |
| 2025-26 | fh2_gw34 | 6 | 0.85 | FH@34 | **1945** | = path 1945 | -- | +50 | +50 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2025_26_fh2_gw34.parquet |
| 2025-26 | pkg_d45 | 6 | 0.45 | WC@4,32 FH@34 BB@33 | **2062** | **2086** (r) | bench@GW33+24 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) | +191 | +191 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | chips/chiplog_2025_26_pkg_d45.parquet |
| 2025-26 | wc1_gw4 | 6 | 0.85 | WC@4 | **1939** | = path 1939 | -- | +44 | +44 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2025_26_wc1_gw4.parquet |
| 2025-26 | wc1_gw5 | 6 | 0.85 | WC@5 | **1980** | = path 1980 | -- | +85 | +85 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2025_26_wc1_gw5.parquet |
| 2025-26 | wc1_gw6 | 6 | 0.85 | WC@6 | **1963** | = path 1963 | -- | +68 | +68 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2025_26_wc1_gw6.parquet |
| 2025-26 | wc2_swing_gw32 | 6 | 0.85 | WC@32 | **1956** | = path 1956 | -- | +61 | +61 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | chips/chiplog_2025_26_wc2_swing_gw32.parquet |

## P1 OPENING ARMS -- no chips (data/p1/p1log_*)

arm=base is the no-chip baseline of record for the grids below; arm=p1 flips OPENING_HORIZON_ACTIVE, arm=p2 OPENING_ROBUST_ACTIVE (both CLOSED, not adopted).

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | arm=base | 6 | 0.45 | -- | **2204** | = path 2204 | -- | +166 | +201 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/p1log_2023_24_base.parquet |
| 2023-24 | arm=p1 | 6 | 0.45 | -- | **2194** | = path 2194 | -- | +156 | +191 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/p1log_2023_24_p1.parquet |
| 2023-24 | arm=p2 | 6 | 0.45 | -- | **2204** | = path 2204 | -- | +166 | +201 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_robust | 2026-08-20 | -- | p1/p1log_2023_24_p2.parquet |
| 2024-25 | arm=base | 6 | 0.45 | -- | **2362** | = path 2362 | -- | +208 | +354 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/p1log_2024_25_base.parquet |
| 2024-25 | arm=p1 | 6 | 0.45 | -- | **2302** | = path 2302 | -- | +148 | +294 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/p1log_2024_25_p1.parquet |
| 2024-25 | arm=p2 | 6 | 0.45 | -- | **2302** | = path 2302 | -- | +148 | +294 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_robust | 2026-08-20 | -- | p1/p1log_2024_25_p2.parquet |
| 2025-26 | arm=base | 6 | 0.45 | -- | **2032** | = path 2032 | -- | +137 | +137 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/p1log_2025_26_base.parquet |
| 2025-26 | arm=p1 | 6 | 0.45 | -- | **1961** | = path 1961 | -- | +66 | +66 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/p1log_2025_26_p1.parquet |
| 2025-26 | arm=p2 | 6 | 0.45 | -- | **2032** | = path 2032 | -- | +137 | +137 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_robust | 2026-08-20 | -- | p1/p1log_2025_26_p2.parquet |

## WC1 x OPENING GRID -- wildcard only (data/p1/wclog_*)

One WC at the named week, nothing else. Chip-inclusive == path (a wildcard changes the path itself; there is nothing to add).

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | opening=base wc1=2 | 6 | 0.45 | WC@2 | **2113** | = path 2113 | -- | +75 | +110 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/wclog_2023_24_base_wc2.parquet |
| 2023-24 | opening=base wc1=3 | 6 | 0.45 | WC@3 | **2169** | = path 2169 | -- | +131 | +166 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/wclog_2023_24_base_wc3.parquet |
| 2023-24 | opening=base wc1=4 | 6 | 0.45 | WC@4 | **2104** | = path 2104 | -- | +66 | +101 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2023_24_base_wc4.parquet |
| 2023-24 | opening=base wc1=5 | 6 | 0.45 | WC@5 | **2122** | = path 2122 | -- | +84 | +119 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2023_24_base_wc5.parquet |
| 2023-24 | opening=base wc1=6 | 6 | 0.45 | WC@6 | **2075** | = path 2075 | -- | +37 | +72 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2023_24_base_wc6.parquet |
| 2023-24 | opening=base wc1=7 | 6 | 0.45 | WC@7 | **2206** | = path 2206 | -- | +168 | +203 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2023_24_base_wc7.parquet |
| 2023-24 | opening=base wc1=8 | 6 | 0.45 | WC@8 | **2175** | = path 2175 | -- | +137 | +172 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2023_24_base_wc8.parquet |
| 2023-24 | opening=p1 wc1=2 | 6 | 0.45 | WC@2 | **2108** | = path 2108 | -- | +70 | +105 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/wclog_2023_24_p1_wc2.parquet |
| 2023-24 | opening=p1 wc1=3 | 6 | 0.45 | WC@3 | **2164** | = path 2164 | -- | +126 | +161 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/wclog_2023_24_p1_wc3.parquet |
| 2023-24 | opening=p1 wc1=4 | 6 | 0.45 | WC@4 | **2232** | = path 2232 | -- | +194 | +229 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2023_24_p1_wc4.parquet |
| 2023-24 | opening=p1 wc1=5 | 6 | 0.45 | WC@5 | **2240** | = path 2240 | -- | +202 | +237 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2023_24_p1_wc5.parquet |
| 2023-24 | opening=p1 wc1=6 | 6 | 0.45 | WC@6 | **2128** | = path 2128 | -- | +90 | +125 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2023_24_p1_wc6.parquet |
| 2023-24 | opening=p1 wc1=7 | 6 | 0.45 | WC@7 | **2154** | = path 2154 | -- | +116 | +151 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2023_24_p1_wc7.parquet |
| 2023-24 | opening=p1 wc1=8 | 6 | 0.45 | WC@8 | **2115** | = path 2115 | -- | +77 | +112 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2023_24_p1_wc8.parquet |
| 2024-25 | opening=base wc1=2 | 6 | 0.45 | WC@2 | **2183** | = path 2183 | -- | +29 | +175 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/wclog_2024_25_base_wc2.parquet |
| 2024-25 | opening=base wc1=3 | 6 | 0.45 | WC@3 | **2194** | = path 2194 | -- | +40 | +186 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2024_25_base_wc3.parquet |
| 2024-25 | opening=base wc1=4 | 6 | 0.45 | WC@4 | **2173** | = path 2173 | -- | +19 | +165 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2024_25_base_wc4.parquet |
| 2024-25 | opening=base wc1=5 | 6 | 0.45 | WC@5 | **2311** | = path 2311 | -- | +157 | +303 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2024_25_base_wc5.parquet |
| 2024-25 | opening=base wc1=6 | 6 | 0.45 | WC@6 | **2189** | = path 2189 | -- | +35 | +181 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2024_25_base_wc6.parquet |
| 2024-25 | opening=base wc1=7 | 6 | 0.45 | WC@7 | **2148** | = path 2148 | -- | -6 | +140 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2024_25_base_wc7.parquet |
| 2024-25 | opening=base wc1=8 | 6 | 0.45 | WC@8 | **2193** | = path 2193 | -- | +39 | +185 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2024_25_base_wc8.parquet |
| 2024-25 | opening=p1 wc1=2 | 6 | 0.45 | WC@2 | **2268** | = path 2268 | -- | +114 | +260 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/wclog_2024_25_p1_wc2.parquet |
| 2024-25 | opening=p1 wc1=3 | 6 | 0.45 | WC@3 | **2154** | = path 2154 | -- | +0 | +146 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2024_25_p1_wc3.parquet |
| 2024-25 | opening=p1 wc1=4 | 6 | 0.45 | WC@4 | **2158** | = path 2158 | -- | +4 | +150 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2024_25_p1_wc4.parquet |
| 2024-25 | opening=p1 wc1=5 | 6 | 0.45 | WC@5 | **2339** | = path 2339 | -- | +185 | +331 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2024_25_p1_wc5.parquet |
| 2024-25 | opening=p1 wc1=6 | 6 | 0.45 | WC@6 | **2179** | = path 2179 | -- | +25 | +171 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2024_25_p1_wc6.parquet |
| 2024-25 | opening=p1 wc1=7 | 6 | 0.45 | WC@7 | **2223** | = path 2223 | -- | +69 | +215 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2024_25_p1_wc7.parquet |
| 2024-25 | opening=p1 wc1=8 | 6 | 0.45 | WC@8 | **2090** | = path 2090 | -- | -64 | +82 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2024_25_p1_wc8.parquet |
| 2025-26 | opening=base wc1=2 | 6 | 0.45 | WC@2 | **2075** | = path 2075 | -- | +180 | +180 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/wclog_2025_26_base_wc2.parquet |
| 2025-26 | opening=base wc1=3 | 6 | 0.45 | WC@3 | **2078** | = path 2078 | -- | +183 | +183 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-20 | -- | p1/wclog_2025_26_base_wc3.parquet |
| 2025-26 | opening=base wc1=4 | 6 | 0.45 | WC@4 | **2024** | = path 2024 | -- | +129 | +129 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2025_26_base_wc4.parquet |
| 2025-26 | opening=base wc1=5 | 6 | 0.45 | WC@5 | **2004** | = path 2004 | -- | +109 | +109 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2025_26_base_wc5.parquet |
| 2025-26 | opening=base wc1=6 | 6 | 0.45 | WC@6 | **1889** | = path 1889 | -- | -6 | -6 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2025_26_base_wc6.parquet |
| 2025-26 | opening=base wc1=7 | 6 | 0.45 | WC@7 | **1979** | = path 1979 | -- | +84 | +84 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2025_26_base_wc7.parquet |
| 2025-26 | opening=base wc1=8 | 6 | 0.45 | WC@8 | **1977** | = path 1977 | -- | +82 | +82 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | -- | p1/wclog_2025_26_base_wc8.parquet |
| 2025-26 | opening=p1 wc1=2 | 6 | 0.45 | WC@2 | **2080** | = path 2080 | -- | +185 | +185 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/wclog_2025_26_p1_wc2.parquet |
| 2025-26 | opening=p1 wc1=3 | 6 | 0.45 | WC@3 | **2006** | = path 2006 | -- | +111 | +111 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-20 | -- | p1/wclog_2025_26_p1_wc3.parquet |
| 2025-26 | opening=p1 wc1=4 | 6 | 0.45 | WC@4 | **2013** | = path 2013 | -- | +118 | +118 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2025_26_p1_wc4.parquet |
| 2025-26 | opening=p1 wc1=5 | 6 | 0.45 | WC@5 | **2094** | = path 2094 | -- | +199 | +199 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2025_26_p1_wc5.parquet |
| 2025-26 | opening=p1 wc1=6 | 6 | 0.45 | WC@6 | **2037** | = path 2037 | -- | +142 | +142 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2025_26_p1_wc6.parquet |
| 2025-26 | opening=p1 wc1=7 | 6 | 0.45 | WC@7 | **2042** | = path 2042 | -- | +147 | +147 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2025_26_p1_wc7.parquet |
| 2025-26 | opening=p1 wc1=8 | 6 | 0.45 | WC@8 | **2090** | = path 2090 | -- | +195 | +195 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | -- | p1/wclog_2025_26_p1_wc8.parquet |

## FULL SYSTEM -- all chips (data/p1/fslog_*)

WC1 as named, WC2/FH2 in-sim, BB1+BB2 scheduled (bench-aware), TC1 exogenous read. The P4 TC2 read (captain bonus at the BB2 week) is DROPPED as an illegal play and shown struck through (corrected 2026-08-24; p4 log section 12c). The system-as-configured cells are opening=base wc1=2 (WC1 rule of record GW2-3, p4 log section 12b).

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | opening=base wc1=2 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2278** | **2296** (r) | bench@GW7+4 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24); SUPERSEDED AS REFERENCE CELL (2026-08-26): TC2 scored zero and incumbent bonus term; the reference of record is arms/armlog_2023_24_bonusdel_tc2 (2251) | p1/fslog_2023_24_base_wc2.parquet |
| 2023-24 | opening=base wc1=4 | 6 | 0.45 | WC@4,32 FH@29 BB@7,34 | **2238** | **2296** (r) | bench@GW7+6 bench@GW34+46 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_base_wc4.parquet |
| 2023-24 | opening=base wc1=6 | 6 | 0.45 | WC@6,32 FH@29 BB@7,34 | **2306** | **2345** (r) | bench@GW7+5 bench@GW34+33 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW11+1 | +307 | +342 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_base_wc6.parquet |
| 2023-24 | opening=base wc1=8 | 6 | 0.45 | WC@8,32 FH@29 BB@7,34 | **2259** | **2328** (r) | bench@GW7+19 bench@GW34+44 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +290 | +325 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_base_wc8.parquet |
| 2023-24 | opening=p1 wc1=2 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2273** | **2291** (r) | bench@GW7+4 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +253 | +288 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_p1_wc2.parquet |
| 2023-24 | opening=p1 wc1=4 | 6 | 0.45 | WC@4,32 FH@29 BB@7,34 | **2263** | **2294** (r) | bench@GW7+6 bench@GW34+19 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +256 | +291 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_p1_wc4.parquet |
| 2023-24 | opening=p1 wc1=6 | 6 | 0.45 | WC@6,32 FH@29 BB@7,34 | **2257** | **2271** (r) | bench@GW7+5 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW11+1 | +233 | +268 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_p1_wc6.parquet |
| 2023-24 | opening=p1 wc1=8 | 6 | 0.45 | WC@8,32 FH@29 BB@7,34 | **2176** | **2229** (r) | bench@GW7+3 bench@GW34+44 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +191 | +226 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2023_24_p1_wc8.parquet |
| 2024-25 | opening=base wc1=2 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2255** | **2294** (r) | bench@GW7+5 bench@GW33+25 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +140 | +286 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24); SUPERSEDED AS REFERENCE CELL (2026-08-26): TC2 scored zero and incumbent bonus term; the reference of record is arms/armlog_2024_25_bonusdel_tc2 (2306) | p1/fslog_2024_25_base_wc2.parquet |
| 2024-25 | opening=base wc1=4 | 6 | 0.45 | WC@4,31 FH@29 BB@7,33 | **2385** | **2438** (r) | bench@GW7+19 bench@GW33+25 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +284 | +430 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_base_wc4.parquet |
| 2024-25 | opening=base wc1=6 | 6 | 0.45 | WC@6,31 FH@29 BB@7,33 | **2057** | **2100** (r) | bench@GW7+8 bench@GW33+26 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | -54 | +92 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_base_wc6.parquet |
| 2024-25 | opening=base wc1=8 | 6 | 0.45 | WC@8,31 FH@29 BB@7,33 | **2148** | **2201** (r) | bench@GW7+12 bench@GW33+32 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +47 | +193 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_base_wc8.parquet |
| 2024-25 | opening=p1 wc1=2 | 6 | 0.45 | WC@2,31 FH@29 BB@9,33 | **2324** | **2361** (r) | bench@GW9+5 bench@GW33+23 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +207 | +353 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_p1_wc2.parquet |
| 2024-25 | opening=p1 wc1=4 | 6 | 0.45 | WC@4,31 FH@29 BB@9,33 | **2105** | **2155** (r) | bench@GW9+12 bench@GW33+29 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +1 | +147 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_p1_wc4.parquet |
| 2024-25 | opening=p1 wc1=6 | 6 | 0.45 | WC@6,31 FH@29 BB@9,33 | **2164** | **2196** (r) | bench@GW9+5 bench@GW33+18 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +42 | +188 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_p1_wc6.parquet |
| 2024-25 | opening=p1 wc1=8 | 6 | 0.45 | WC@8,31 FH@29 BB@9,33 | **2100** | **2130** (r) | bench@GW9+9 bench@GW33+12 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | -24 | +122 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2024_25_p1_wc8.parquet |
| 2025-26 | opening=base wc1=2 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2156** | **2206** (r) | bench@GW10+11 bench@GW33+23 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +311 | +311 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24); SUPERSEDED AS REFERENCE CELL (2026-08-26): TC2 scored zero and incumbent bonus term; the reference of record is arms/armlog_2025_26_bonusdel_tc2 (2268) | p1/fslog_2025_26_base_wc2.parquet |
| 2025-26 | opening=base wc1=4 | 6 | 0.45 | WC@4,32 FH@34 BB@10,33 | **2069** | **2120** (r) | bench@GW10+8 bench@GW33+27 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +225 | +225 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_base_wc4.parquet |
| 2025-26 | opening=base wc1=6 | 6 | 0.45 | WC@6,32 FH@34 BB@10,33 | **2031** | **2071** (r) | bench@GW10+7 bench@GW33+17 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +176 | +176 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_base_wc6.parquet |
| 2025-26 | opening=base wc1=8 | 6 | 0.45 | WC@8,32 FH@34 BB@10,33 | **2072** | **2135** (r) | bench@GW10+19 bench@GW33+28 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +240 | +240 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_base_wc8.parquet |
| 2025-26 | opening=p1 wc1=2 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2161** | **2211** (r) | bench@GW10+11 bench@GW33+23 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +316 | +316 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_p1_wc2.parquet |
| 2025-26 | opening=p1 wc1=4 | 6 | 0.45 | WC@4,32 FH@34 BB@10,33 | **2038** | **2091** (r) | bench@GW10+12 bench@GW33+25 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +196 | +196 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_p1_wc4.parquet |
| 2025-26 | opening=p1 wc1=6 | 6 | 0.45 | WC@6,32 FH@34 BB@10,33 | **2035** | **2078** (r) | bench@GW10+13 bench@GW33+14 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +183 | +183 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_p1_wc6.parquet |
| 2025-26 | opening=p1 wc1=8 | 6 | 0.45 | WC@8,32 FH@34 BB@10,33 | **2094** | **2143** (r) | bench@GW10+19 bench@GW33+14 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +248 | +248 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | opening_horizon | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/fslog_2025_26_p1_wc8.parquet |

## P3 EARLY-HIT GRID (data/p1/p3log_*)

Full-system config + EARLY_HIT_DISCOUNT_ACTIVE at the named bar. Measured and DECLINED; bar=4 references are the fslog rows above. Same TC2@BB2 drop as the full system.

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | wc1=2 bar=1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2205** | **2253** (r) | bench@GW7+9 bench@GW34+33 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +215 | +250 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=1 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2023_24_wc2_bar1.parquet |
| 2023-24 | wc1=2 bar=2 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2331** | **2382** (r) | bench@GW7+18 bench@GW34+27 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +344 | +379 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=2 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2023_24_wc2_bar2.parquet |
| 2023-24 | wc1=2 bar=3 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2264** | **2296** (r) | bench@GW7+18 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=3 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2023_24_wc2_bar3.parquet |
| 2023-24 | wc1=6 bar=1 | 6 | 0.45 | WC@6,32 FH@29 BB@7,34 | **2261** | **2304** (r) | bench@GW7+9 bench@GW34+33 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW11+1 | +266 | +301 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=1 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2023_24_wc6_bar1.parquet |
| 2023-24 | wc1=6 bar=2 | 6 | 0.45 | WC@6,32 FH@29 BB@7,34 | **2232** | **2251** (r) | bench@GW7+10 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW11+1 | +213 | +248 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=2 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2023_24_wc6_bar2.parquet |
| 2023-24 | wc1=6 bar=3 | 6 | 0.45 | WC@6,32 FH@29 BB@7,34 | **2196** | **2234** (r) | bench@GW7+6 bench@GW34+31 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW11+1 | +196 | +231 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=3 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2023_24_wc6_bar3.parquet |
| 2024-25 | wc1=2 bar=1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2227** | **2274** (r) | bench@GW7+18 bench@GW33+20 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +120 | +266 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=1 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2024_25_wc2_bar1.parquet |
| 2024-25 | wc1=2 bar=2 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2246** | **2288** (r) | bench@GW7+19 bench@GW33+14 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +134 | +280 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=2 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2024_25_wc2_bar2.parquet |
| 2024-25 | wc1=2 bar=3 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2195** | **2248** (r) | bench@GW7+20 bench@GW33+24 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +94 | +240 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=3 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2024_25_wc2_bar3.parquet |
| 2024-25 | wc1=6 bar=1 | 6 | 0.45 | WC@6,31 FH@29 BB@7,33 | **2067** | **2121** (r) | bench@GW7+19 bench@GW33+26 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | -33 | +113 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=1 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2024_25_wc6_bar1.parquet |
| 2024-25 | wc1=6 bar=2 | 6 | 0.45 | WC@6,31 FH@29 BB@7,33 | **2159** | **2194** (r) | bench@GW7+14 bench@GW33+12 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +40 | +186 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=2 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2024_25_wc6_bar2.parquet |
| 2024-25 | wc1=6 bar=3 | 6 | 0.45 | WC@6,31 FH@29 BB@7,33 | **2160** | **2194** (r) | bench@GW7+13 bench@GW33+12 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +40 | +186 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=3 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2024_25_wc6_bar3.parquet |
| 2025-26 | wc1=2 bar=1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2080** | **2144** (r) | bench@GW10+18 bench@GW33+30 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +249 | +249 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=1 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2025_26_wc2_bar1.parquet |
| 2025-26 | wc1=2 bar=2 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2093** | **2146** (r) | bench@GW10+18 bench@GW33+19 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +251 | +251 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=2 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2025_26_wc2_bar2.parquet |
| 2025-26 | wc1=2 bar=3 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2156** | **2206** (r) | bench@GW10+11 bench@GW33+23 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +311 | +311 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=3 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2025_26_wc2_bar3.parquet |
| 2025-26 | wc1=6 bar=1 | 6 | 0.45 | WC@6,32 FH@34 BB@10,33 | **2075** | **2119** (r) | bench@GW10+15 bench@GW33+13 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +224 | +224 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=1 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2025_26_wc6_bar1.parquet |
| 2025-26 | wc1=6 bar=2 | 6 | 0.45 | WC@6,32 FH@34 BB@10,33 | **2047** | **2093** (r) | bench@GW10+11 bench@GW33+19 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +198 | +198 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=2 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2025_26_wc6_bar2.parquet |
| 2025-26 | wc1=6 bar=3 | 6 | 0.45 | WC@6,32 FH@34 BB@10,33 | **2022** | **2066** (r) | bench@GW10+9 bench@GW33+19 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +171 | +171 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | early_hit_bar=3 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p3log_2025_26_wc6_bar3.parquet |

## P5 OPTIMIZER-WINS ARMS (data/p1/p5log_*)

Full-system wc2 config + bench-order / XI-tiebreak gates. Measured and DECLINED (noise-free paired paths). Same TC2@BB2 drop as the full system.

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | arm=bench | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2271** | **2296** (r) | bench@GW7+4 bench@GW34+15 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | bench_order | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2023_24_bench.parquet |
| 2023-24 | arm=both | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2271** | **2296** (r) | bench@GW7+11 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | bench_order xi_p60 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2023_24_both.parquet |
| 2023-24 | arm=xi | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2271** | **2296** (r) | bench@GW7+11 bench@GW34+8 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | xi_p60 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2023_24_xi.parquet |
| 2024-25 | arm=bench | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2248** | **2287** (r) | bench@GW7+5 bench@GW33+25 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +133 | +279 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | bench_order | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2024_25_bench.parquet |
| 2024-25 | arm=both | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2236** | **2287** (r) | bench@GW7+5 bench@GW33+37 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +133 | +279 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | bench_order xi_p60 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2024_25_both.parquet |
| 2024-25 | arm=xi | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2243** | **2294** (r) | bench@GW7+5 bench@GW33+37 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +140 | +286 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | xi_p60 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2024_25_xi.parquet |
| 2025-26 | arm=bench | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2152** | **2201** (r) | bench@GW10+11 bench@GW33+22 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +306 | +306 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | bench_order | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2025_26_bench.parquet |
| 2025-26 | arm=both | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2154** | **2201** (r) | bench@GW10+5 bench@GW33+26 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +306 | +306 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | bench_order xi_p60 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2025_26_both.parquet |
| 2025-26 | arm=xi | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2159** | **2206** (r) | bench@GW10+5 bench@GW33+26 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +311 | +311 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | xi_p60 | 2026-08-21 | TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | p1/p5log_2025_26_xi.parquet |

## TEAM-NEWS ORACLE -- DELIBERATE LEAKAGE (data/teamnews)

oracle_minutes_active=True: realized minutes injected into predictions. These rows are MEASUREMENTS of an upper bound, never baselines, never adoptable, comparable only to their reference cell (fslog base_wc2). Same TC2@BB2 drop as the full system.

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | A step0-only oracle | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2306** | **2361** (r) | bench@GW7+13 bench@GW34+36 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +323 | +358 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2023_24_A.parquet |
| 2023-24 | B calendar-knowable mask | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2222** | **2250** (r) | bench@GW7+4 bench@GW34+18 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +212 | +247 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2023_24_B.parquet |
| 2023-24 | C Guardian-reported mask | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2270** | **2296** (r) | bench@GW7+4 bench@GW34+16 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +258 | +293 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2023_24_C.parquet |
| 2023-24 | full-horizon oracle | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2424** | **2484** (r) | bench@GW7+15 bench@GW34+39 ~~TC2 cap@GW34+9~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +446 | +481 | walkforward_h6_2023_24.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2023_24.parquet |
| 2024-25 | A step0-only oracle | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2170** | **2207** (r) | bench@GW7+15 bench@GW33+13 ~~TC2 cap@GW33+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +53 | +199 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2024_25_A.parquet |
| 2024-25 | B calendar-knowable mask | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2115** | **2174** (r) | bench@GW7+13 bench@GW33+37 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +20 | +166 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2024_25_B.parquet |
| 2024-25 | C Guardian-reported mask | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2133** | **2187** (r) | bench@GW7+13 bench@GW33+32 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +33 | +179 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2024_25_C.parquet |
| 2024-25 | full-horizon oracle | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2364** | **2403** (r) | bench@GW7+13 bench@GW33+17 ~~TC2 cap@GW33+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +249 | +395 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2024_25.parquet |
| 2025-26 | A step0-only oracle | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2277** | **2332** (r) | bench@GW10+19 bench@GW33+20 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +437 | +437 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2025_26_A.parquet |
| 2025-26 | B calendar-knowable mask | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2180** | **2236** (r) | bench@GW10+15 bench@GW33+25 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +341 | +341 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2025_26_B.parquet |
| 2025-26 | C Guardian-reported mask | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2154** | **2205** (r) | bench@GW10+11 bench@GW33+24 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +310 | +310 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2025_26_C.parquet |
| 2025-26 | full-horizon oracle | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2251** | **2300** (r) | bench@GW10+17 bench@GW33+16 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +405 | +405 | walkforward_h6_2025_26.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | ORACLE | 2026-08-22 | LEAKAGE INSTRUMENT -- never adopt, never a baseline; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | teamnews/oraclelog_2025_26.parquet |

## ARMS -- 2026-08-26 arms incl. THE REFERENCE CELLS OF RECORD (data/arms/armlog_*)

Full-system wc2 config with a feature applied in-process for the season figure only: props (conditional spec, w=0.75 m=1.396; PROPS_HOOK rests None) and/or horizon minutes lever 1 (HORIZON_MINUTES_ACTIVE rests False). BOTH FAILED their pre-registered component tests (Logs/props_prereg.md CLOSE-OUT; Logs/horizon_minutes_log.md section 5); these totals were never permitted to overturn that, and they disagree with the component read in sign (Logs/instrument_b_log.md, the standing illustration). 2024-25 rows start at GW8 from the reference cell's GW7 state (prefix stitched); their like-for-like number is the GW8-38 segment delta in Logs/props_season_log.md. Same TC2@BB2 drop as the full system. ALSO HERE (2026-08-26): penfix / cal / cal_penfix / bonusow (all NOT adopted), bonusdel (ADOPTED, TC2 scored zero) and **bonusdel_tc2 -- THE REFERENCE CELLS OF RECORD** (bonus deleted, TC2 scheduled in-sim on the 12c(ii) week: GW25 / GW24 / GW26; captain = the MIP's cap at that deadline; path identical to bonusdel in every gameweek, so the TC2 read is exactly the extra captain multiple, +10 / +29 / +7). Their `TC2 in-sim` read is listed for the record and NOT added -- it is already inside the path total.

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-24 | REFERENCE CELL OF RECORD: bonus_delete + TC2 in-sim start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 TC@25 (in-sim) | **2226** | **2251** (r) | bench@GW7+17 bench@GW34+2 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 TC2 in-sim@GW25+10 | +213 | +248 | walkforward_h6_2023_24_bonusdel.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | REFERENCE CELL OF RECORD (2026-08-26): BONUS_MODE=delete (adopted on component metrics, Logs/bonus_delete_prereg.md) + Triple Captain 2 IN-SIM on the 12c(ii) week (p4 log section 15); captain = the MIP cap variable at that deadline; path identical to arm=bonus_delete in all 38 gws; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_bonusdel_tc2.parquet |
| 2023-24 | arm=bonus_delete (ADOPTED; TC2 scored zero) start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2216** | **2241** (r) | bench@GW7+17 bench@GW34+2 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +203 | +238 | walkforward_h6_2023_24_bonusdel.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | ADOPTED on component metrics (Logs/bonus_delete_prereg.md); TC2 scored zero here -- see the bonusdel_tc2 row; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_bonusdel.parquet |
| 2023-24 | arm=bonus_rebuild_outcome (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2243** | **2280** (r) | bench@GW7+16 bench@GW34+15 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +242 | +277 | walkforward_h6_2023_24_bonusow.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_bonusow.parquet |
| 2023-24 | arm=horizon_minutes start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2376** | **2405** (r) | bench@GW7+6 bench@GW34+17 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +367 | +402 | arms/walkforward_h6_2023_24_hmin.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | HORIZON_MINUTES | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_hmin.parquet |
| 2023-24 | arm=penalty_fix (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2256** | **2291** (r) | bench@GW7+13 bench@GW34+16 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +253 | +288 | walkforward_h6_2023_24_penfix.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_penfix.parquet |
| 2023-24 | arm=topend_cal (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2215** | **2265** (r) | bench@GW7+11 bench@GW34+33 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +227 | +262 | walkforward_h6_2023_24_cal.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_cal.parquet |
| 2023-24 | arm=topend_cal+penalty_fix (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@29 BB@7,34 | **2221** | **2286** (r) | bench@GW7+29 bench@GW34+30 ~~TC2 cap@GW34+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW6+6 | +248 | +283 | walkforward_h6_2023_24_cal_penfix.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2023_24_cal_penfix.parquet |
| 2024-25 | REFERENCE CELL OF RECORD: bonus_delete + TC2 in-sim start=GW1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 TC@24 (in-sim) | **2249** | **2306** (r) | bench@GW7+17 bench@GW33+31 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 TC2 in-sim@GW24+29 | +152 | +298 | walkforward_h6_2024_25_bonusdel.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | REFERENCE CELL OF RECORD (2026-08-26): BONUS_MODE=delete (adopted on component metrics, Logs/bonus_delete_prereg.md) + Triple Captain 2 IN-SIM on the 12c(ii) week (p4 log section 15); captain = the MIP cap variable at that deadline; path identical to arm=bonus_delete in all 38 gws; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_bonusdel_tc2.parquet |
| 2024-25 | arm=bonus_delete (ADOPTED; TC2 scored zero) start=GW1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2220** | **2277** (r) | bench@GW7+17 bench@GW33+31 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +123 | +269 | walkforward_h6_2024_25_bonusdel.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | ADOPTED on component metrics (Logs/bonus_delete_prereg.md); TC2 scored zero here -- see the bonusdel_tc2 row; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_bonusdel.parquet |
| 2024-25 | arm=bonus_rebuild_outcome (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2268** | **2312** (r) | bench@GW7+5 bench@GW33+30 ~~TC2 cap@GW33+3~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +158 | +304 | walkforward_h6_2024_25_bonusow.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_bonusow.parquet |
| 2024-25 | arm=horizon_minutes start=GW8 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2304** | **2339** (r) | bench@GW7+5 bench@GW33+21 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +185 | +331 | arms/walkforward_h6_2024_25_hmin.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | HORIZON_MINUTES | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; starts GW8 from the reference cell's GW7 state (GW1-7 stitched = reference); like-for-like = GW8-38 segment vs reference; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_hmin.parquet |
| 2024-25 | arm=penalty_fix (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2347** | **2408** (r) | bench@GW7+6 bench@GW33+46 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +254 | +400 | walkforward_h6_2024_25_penfix.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_penfix.parquet |
| 2024-25 | arm=props start=GW8 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2199** | **2243** (r) | bench@GW7+5 bench@GW33+30 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +89 | +235 | arms/walkforward_h6_2024_25_props.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | PROPS | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; starts GW8 from the reference cell's GW7 state (GW1-7 stitched = reference); like-for-like = GW8-38 segment vs reference; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_props.parquet |
| 2024-25 | arm=props+horizon_minutes start=GW8 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2213** | **2257** (r) | bench@GW7+5 bench@GW33+30 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +103 | +249 | arms/walkforward_h6_2024_25_both.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | PROPS HORIZON_MINUTES | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; starts GW8 from the reference cell's GW7 state (GW1-7 stitched = reference); like-for-like = GW8-38 segment vs reference; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_both.parquet |
| 2024-25 | arm=topend_cal (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2247** | **2298** (r) | bench@GW7+15 bench@GW33+34 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW4+2 | +144 | +290 | walkforward_h6_2024_25_cal.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_cal.parquet |
| 2024-25 | arm=topend_cal+penalty_fix (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2366** | **2399** (r) | bench@GW7+6 bench@GW33+18 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +245 | +391 | walkforward_h6_2024_25_cal_penfix.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_cal_penfix.parquet |
| 2024-25 | baseline re-run start=GW8 | 6 | 0.45 | WC@2,31 FH@29 BB@7,33 | **2255** | **2294** (r) | bench@GW7+5 bench@GW33+25 ~~TC2 cap@GW33+7~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW18+9 | +140 | +286 | walkforward_h6_2024_25.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | like-for-like check of the resume mechanism -- reproduces the reference GW8-38 exactly; starts GW8 from the reference cell's GW7 state (GW1-7 stitched = reference); like-for-like = GW8-38 segment vs reference; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2024_25_baseline8.parquet |
| 2025-26 | REFERENCE CELL OF RECORD: bonus_delete + TC2 in-sim start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 TC@26 (in-sim) | **2220** | **2268** (r) | bench@GW10+12 bench@GW33+20 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 TC2 in-sim@GW26+7 | +373 | +373 | walkforward_h6_2025_26_bonusdel.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | REFERENCE CELL OF RECORD (2026-08-26): BONUS_MODE=delete (adopted on component metrics, Logs/bonus_delete_prereg.md) + Triple Captain 2 IN-SIM on the 12c(ii) week (p4 log section 15); captain = the MIP cap variable at that deadline; path identical to arm=bonus_delete in all 38 gws; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_bonusdel_tc2.parquet |
| 2025-26 | arm=bonus_delete (ADOPTED; TC2 scored zero) start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2213** | **2261** (r) | bench@GW10+12 bench@GW33+20 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +366 | +366 | walkforward_h6_2025_26_bonusdel.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | ADOPTED on component metrics (Logs/bonus_delete_prereg.md); TC2 scored zero here -- see the bonusdel_tc2 row; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_bonusdel.parquet |
| 2025-26 | arm=bonus_rebuild_outcome (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2044** | **2094** (r) | bench@GW10+8 bench@GW33+26 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +199 | +199 | walkforward_h6_2025_26_bonusow.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_bonusow.parquet |
| 2025-26 | arm=horizon_minutes start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2070** | **2122** (r) | bench@GW10+12 bench@GW33+24 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +227 | +227 | arms/walkforward_h6_2025_26_hmin.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | HORIZON_MINUTES | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_hmin.parquet |
| 2025-26 | arm=penalty_fix (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2085** | **2139** (r) | bench@GW10+19 bench@GW33+19 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW17+16 | +244 | +244 | walkforward_h6_2025_26_penfix.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_penfix.parquet |
| 2025-26 | arm=props start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2055** | **2099** (r) | bench@GW10+10 bench@GW33+26 ~~TC2 cap@GW33+5~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW1+8 | +204 | +204 | arms/walkforward_h6_2025_26_props.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | PROPS | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_props.parquet |
| 2025-26 | arm=props+horizon_minutes start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2086** | **2134** (r) | bench@GW10+19 bench@GW33+21 ~~TC2 cap@GW33+8~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW1+8 | +239 | +239 | arms/walkforward_h6_2025_26_both.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | PROPS HORIZON_MINUTES | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_both.parquet |
| 2025-26 | arm=topend_cal (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2058** | **2111** (r) | bench@GW10+26 bench@GW33+19 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW1+8 | +216 | +216 | walkforward_h6_2025_26_cal.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_cal.parquet |
| 2025-26 | arm=topend_cal+penalty_fix (NOT adopted) start=GW1 | 6 | 0.45 | WC@2,32 FH@34 BB@10,33 | **2100** | **2135** (r) | bench@GW10+11 bench@GW33+15 ~~TC2 cap@GW33+13~~ DROPPED (collision with BB2 -- one chip per gameweek) TC1 cap@GW4+9 | +240 | +240 | walkforward_h6_2025_26_cal_penfix.parquet | av=T d1=T blend=T dgw=per_fixture synth=F | -- | 2026-08-26 | NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence; TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24) | arms/armlog_2025_26_cal_penfix.parquet |

## REFERENCES -- pre-canonical lineage figures

Retained for lineage only.

| season | config | H | decay | chips scheduled | path total | chip-incl total | chip reads | vs avg (claimed) | vs avg (fplcache) | wf file | wf stamps | sim gates | run | flags | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-26 | PRE-M3, pre-D1, pre-blend, pre-#15 | 3 | 0.3 | -- | **1984** | = path 1984 | -- | +89 | +89 | walkforward_h6_2526_prefix.parquet (preserved) | ? | -- | 2026-08-11 | lineage only -- comparable to NOTHING; SUPERSEDED (stale wf suffix _prefix) | wildcard_and_determinism.md |
| 2025-26 | pre-#15 | 6 | 0.85 | -- | **2060** | = path 2060 | -- | +165 | +165 | (rate blend k=8, pre-#15 DC base rates) | ? | -- | 2026-08-18 | lineage only -- comparable to NOTHING | rate_blend_log.md section 7 |
| 2025-26 | pre-D1, pre-blend, pre-#15 | 3 | 0.3 | -- | **1938** | = path 1938 | -- | +43 | +43 | (availability=True rebuild, same era) | ? | -- | 2026-08-13 | lineage only -- comparable to NOTHING | eval/walkforward.py docstring |
| 2025-26 | pre-blend, pre-#15 | 6 | 0.85 | -- | **2028** | = path 2028 | -- | +133 | +133 | (D1 Variant B, static rates) | ? | -- | 2026-08-17 | lineage only -- comparable to NOTHING | d1_log.md section 9 |

## Valid comparisons (exhaustive)

1. **Chip effects**: any chips/bb-aware row vs the SAME season's `baseline`
   chips row at H=6 decay=0.85 (family post-#15, synth off). Variable = the
   chip package. combined_d60 pairs with the sweep `base H6 d60` row;
   pkg_d45 pairs with the sweep `base H6 d45` row (prefix identity asserted
   by its measure script).
2. **D4 base-vs-synth**: sweep rows within the same (season, H, decay) --
   the 27 matched pairs of the sign test.
3. **P1 arms**: p1log rows within a season (base vs p1 vs p2) -- same
   config, opening gate is the only variable.
4. **WC1 grid**: wclog rows within (season, opening) vs the same opening's
   p1log baseline -- the anchor-window deltas are the evidence of record
   (p1_opening_log section 7), NOT the totals.
5. **Full system**: fslog rows within (season, opening) across wc1; the BB1
   question pairs fslog vs wclog at the same (season, opening, wc1)
   (prefix-verified 24/24). Margins vs the average manager identify the
   system; they rank nothing.
6. **P3**: p3log rows vs the fslog cell at the same (season, wc1) -- bar is
   the variable (bar=4 == the fslog reference itself).
7. **P5**: p5log arms vs fslog base_wc2 -- noise-free paired paths.
8. **Oracle rows**: comparable ONLY to fslog base_wc2 (their reference), as
   an upper-bound measurement. Never to each other across seasons, never as
   baselines.
9. **Arms rows** (props/hmin/both/penfix/cal/bonusow/bonusdel): comparable ONLY to fslog
   base_wc2 (the reference they were measured against, old convention); the
   2024-25 rows by their GW8-38 segment (props_season_log.md), never by the
   stitched total's margin. Closed non-adoptions; never baselines.
10. **Reference cells of record** (arms bonusdel_tc2) vs arms bonusdel: differ by
   the in-sim TC2 alone (path identical); future arms should be run with TC2
   in-sim and compared to bonusdel_tc2 directly.
11. Nothing else. Cross-H, cross-decay, cross-season, cross-family and every
   REFERENCE row: NOT comparable.

## Explicit flags

- Every chip-inclusive figure in this index is recomputed (marked (r)); no
  log family stores one. The reads are decomposed per row so a recompute
  error is visible, not quiet.
- CORRECTED 2026-08-24: the TC2 read at the BB2 week was an illegal play and
  is dropped on every affected row (struck through, flagged). Figures quoted
  from this index before that date carry the illegal read; the p4 log,
  the closing position and the 2026-08-23 handoff quote 2299/2301/2219 --
  read those as 2296/2294/2206 (old convention).
- MOVED 2026-08-26: the reference cells are the arms bonusdel_tc2 rows
  (2251/2306/2268). 2296/2294/2206 (fslog base_wc2) are SUPERSEDED as
  reference cells: TC2 scored zero and the incumbent bonus term; retained,
  flagged, never deleted.
- Oracle rows are deliberate-leakage instruments (oracle_minutes_active
  stamp). NEVER adopt, never baseline.
- The four reference figures are retained for lineage only.
- One historical cross-provenance comparison was ATTEMPTED and caught before
  measurement: D4 Phase 2's first 2025-26 synth build used the wrong writer
  (stamps differed); rebuilt before any number was read (overnight log,
  stage 2).
- The 3 chips-era pkg_d45 rows are newly indexed here; the pre-2026-08-24
  generator would have mislabelled their decay as 0.85.
