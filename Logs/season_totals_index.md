# Season totals index -- every simulated season total, one place

Generated 2026-08-20 by eval/build_season_totals_index.py.

**Framing (mandatory):** a season total is ONE draw from a
distribution with path sd ~60 (M1 failed). This index exists so
figures can be LOCATED and grouped by provenance -- comparisons
are valid ONLY within a family AND only between rows differing
by exactly the variable under test. Season totals never decide
adoptions; component and windowed metrics do.

**Average-manager verification:** claimed averages 2038 / 2154 /
1895 vs fplcache sum of events[].average_entry_score 2003 / 2008
/ 1895. 2025-26 MATCHES; 2023-24 is 35 off; 2024-25 is 146 off.
The statistics differ by definition (sum of per-GW averages !=
average of season totals; late entries and chips break the
equivalence), so BOTH margins are shown.

**Provenance notes:** (1) the 2023-24 sweep sims ran against the
pre-#15-rebuild canonical, proven BIT-IDENTICAL to the rebuilt
file (dc_enabled=False season), so they belong to the post-#15
family. (2) The 2023-24/2024-25 _synth files predate the #15
rebuild but are DC-irrelevant seasons -- same family. (3) All
four REFERENCE rows predate the DC-wiring fix (#15); 1984/1938
also predate D1 and the rate blend; 2028 predates the blend.
They are comparable to NOTHING in this index.
(4) bb_aware=True rows flip transfer_mip.BENCH_BOOST_AWARE --
their baseline (gate off) differs by chips+gate JOINTLY: that
package is the declared variable (p4 log section 8).

| season | H | decay | chips | synth λ | bb-aware | walkforward file | family | built | total | vs avg (claimed) | vs avg (fplcache) | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-26 | 3 | 0.3 | none | off | - | walkforward_h6_2526_prefix.parquet (preserved) | PRE-M3, pre-D1, pre-blend, pre-#15 | 2026-08-11 | **1984** | +89 | +89 | wildcard_and_determinism.md |
| 2023-24 | 3 | 0.3 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2153** | +115 | +150 | sweep/simlog_2023_24_base_H3_d30.parquet |
| 2023-24 | 3 | 0.45 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2068** | +30 | +65 | sweep/simlog_2023_24_base_H3_d45.parquet |
| 2023-24 | 3 | 0.6 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2228** | +190 | +225 | sweep/simlog_2023_24_base_H3_d60.parquet |
| 2023-24 | 4 | 0.3 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2136** | +98 | +133 | sweep/simlog_2023_24_base_H4_d30.parquet |
| 2023-24 | 4 | 0.45 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2168** | +130 | +165 | sweep/simlog_2023_24_base_H4_d45.parquet |
| 2023-24 | 4 | 0.6 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2068** | +30 | +65 | sweep/simlog_2023_24_base_H4_d60.parquet |
| 2023-24 | 6 | 0.3 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2177** | +139 | +174 | sweep/simlog_2023_24_base_H6_d30.parquet |
| 2023-24 | 6 | 0.45 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2204** | +166 | +201 | sweep/simlog_2023_24_base_H6_d45.parquet |
| 2023-24 | 6 | 0.6 | combined_d60 | off | Y | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2218** | +180 | +215 | chips/chiplog_2023_24_combined_d60.parquet |
| 2023-24 | 6 | 0.6 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2175** | +137 | +172 | sweep/simlog_2023_24_base_H6_d60.parquet |
| 2023-24 | 6 | 0.85 | bbaware_wc33_bb34 | off | Y | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2218** | +180 | +215 | chips/chiplog_2023_24_bbaware_wc33_bb34.parquet |
| 2023-24 | 6 | 0.85 | combined_d85 | off | Y | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2295** | +257 | +292 | chips/chiplog_2023_24_combined_d85.parquet |
| 2023-24 | 6 | 0.85 | fh1_gw17 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2098** | +60 | +95 | chips/chiplog_2023_24_fh1_gw17.parquet |
| 2023-24 | 6 | 0.85 | fh2_gw29 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2234** | +196 | +231 | chips/chiplog_2023_24_fh2_gw29.parquet |
| 2023-24 | 6 | 0.85 | none | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2189** | +151 | +186 | chips/chiplog_2023_24_baseline.parquet |
| 2023-24 | 6 | 0.85 | wc1_gw4 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2159** | +121 | +156 | chips/chiplog_2023_24_wc1_gw4.parquet |
| 2023-24 | 6 | 0.85 | wc1_gw5 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2182** | +144 | +179 | chips/chiplog_2023_24_wc1_gw5.parquet |
| 2023-24 | 6 | 0.85 | wc1_gw6 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2211** | +173 | +208 | chips/chiplog_2023_24_wc1_gw6.parquet |
| 2023-24 | 6 | 0.85 | wc2_staged_gw33 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2208** | +170 | +205 | chips/chiplog_2023_24_wc2_staged_gw33.parquet |
| 2023-24 | 6 | 0.85 | wc2_swing_gw32 | off | - | walkforward_h6_2023_24.parquet | post-#15 canonical | 2026-08-19 | **2222** | +184 | +219 | chips/chiplog_2023_24_wc2_swing_gw32.parquet |
| 2024-25 | 3 | 0.3 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2331** | +177 | +323 | sweep/simlog_2024_25_base_H3_d30.parquet |
| 2024-25 | 3 | 0.45 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2391** | +237 | +383 | sweep/simlog_2024_25_base_H3_d45.parquet |
| 2024-25 | 3 | 0.6 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2415** | +261 | +407 | sweep/simlog_2024_25_base_H3_d60.parquet |
| 2024-25 | 4 | 0.3 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2243** | +89 | +235 | sweep/simlog_2024_25_base_H4_d30.parquet |
| 2024-25 | 4 | 0.45 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2393** | +239 | +385 | sweep/simlog_2024_25_base_H4_d45.parquet |
| 2024-25 | 4 | 0.6 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2326** | +172 | +318 | sweep/simlog_2024_25_base_H4_d60.parquet |
| 2024-25 | 6 | 0.3 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2243** | +89 | +235 | sweep/simlog_2024_25_base_H6_d30.parquet |
| 2024-25 | 6 | 0.45 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2362** | +208 | +354 | sweep/simlog_2024_25_base_H6_d45.parquet |
| 2024-25 | 6 | 0.6 | combined_d60 | off | Y | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2168** | +14 | +160 | chips/chiplog_2024_25_combined_d60.parquet |
| 2024-25 | 6 | 0.6 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2381** | +227 | +373 | sweep/simlog_2024_25_base_H6_d60.parquet |
| 2024-25 | 6 | 0.85 | bbaware_wc32_bb33 | off | Y | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2130** | -24 | +122 | chips/chiplog_2024_25_bbaware_wc32_bb33.parquet |
| 2024-25 | 6 | 0.85 | combined_d85 | off | Y | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2129** | -25 | +121 | chips/chiplog_2024_25_combined_d85.parquet |
| 2024-25 | 6 | 0.85 | fh1_gw15 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2115** | -39 | +107 | chips/chiplog_2024_25_fh1_gw15.parquet |
| 2024-25 | 6 | 0.85 | fh2_gw29 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2186** | +32 | +178 | chips/chiplog_2024_25_fh2_gw29.parquet |
| 2024-25 | 6 | 0.85 | none | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2184** | +30 | +176 | chips/chiplog_2024_25_baseline.parquet |
| 2024-25 | 6 | 0.85 | wc1_gw4 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2126** | -28 | +118 | chips/chiplog_2024_25_wc1_gw4.parquet |
| 2024-25 | 6 | 0.85 | wc1_gw5 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2188** | +34 | +180 | chips/chiplog_2024_25_wc1_gw5.parquet |
| 2024-25 | 6 | 0.85 | wc1_gw6 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2058** | -96 | +50 | chips/chiplog_2024_25_wc1_gw6.parquet |
| 2024-25 | 6 | 0.85 | wc2_staged_gw32 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2167** | +13 | +159 | chips/chiplog_2024_25_wc2_staged_gw32.parquet |
| 2024-25 | 6 | 0.85 | wc2_swing_gw31 | off | - | walkforward_h6_2024_25.parquet | post-#15 canonical | 2026-08-19 | **2158** | +4 | +150 | chips/chiplog_2024_25_wc2_swing_gw31.parquet |
| 2025-26 | 3 | 0.3 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2004** | +109 | +109 | sweep/simlog_2025_26_base_H3_d30.parquet |
| 2025-26 | 3 | 0.45 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1929** | +34 | +34 | sweep/simlog_2025_26_base_H3_d45.parquet |
| 2025-26 | 3 | 0.6 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2026** | +131 | +131 | sweep/simlog_2025_26_base_H3_d60.parquet |
| 2025-26 | 4 | 0.3 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1996** | +101 | +101 | sweep/simlog_2025_26_base_H4_d30.parquet |
| 2025-26 | 4 | 0.45 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2032** | +137 | +137 | sweep/simlog_2025_26_base_H4_d45.parquet |
| 2025-26 | 4 | 0.6 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2055** | +160 | +160 | sweep/simlog_2025_26_base_H4_d60.parquet |
| 2025-26 | 6 | 0.3 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1996** | +101 | +101 | sweep/simlog_2025_26_base_H6_d30.parquet |
| 2025-26 | 6 | 0.45 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2032** | +137 | +137 | sweep/simlog_2025_26_base_H6_d45.parquet |
| 2025-26 | 6 | 0.6 | combined_d60 | off | Y | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1965** | +70 | +70 | chips/chiplog_2025_26_combined_d60.parquet |
| 2025-26 | 6 | 0.6 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2081** | +186 | +186 | sweep/simlog_2025_26_base_H6_d60.parquet |
| 2025-26 | 6 | 0.85 | bbaware_wc32_bb33 | off | Y | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1958** | +63 | +63 | chips/chiplog_2025_26_bbaware_wc32_bb33.parquet |
| 2025-26 | 6 | 0.85 | combined_d85 | off | Y | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **2001** | +106 | +106 | chips/chiplog_2025_26_combined_d85.parquet |
| 2025-26 | 6 | 0.85 | fh2_gw34 | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1945** | +50 | +50 | chips/chiplog_2025_26_fh2_gw34.parquet |
| 2025-26 | 6 | 0.85 | none | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1927** | +32 | +32 | chips/chiplog_2025_26_baseline.parquet |
| 2025-26 | 6 | 0.85 | wc1_gw4 | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1939** | +44 | +44 | chips/chiplog_2025_26_wc1_gw4.parquet |
| 2025-26 | 6 | 0.85 | wc1_gw5 | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1980** | +85 | +85 | chips/chiplog_2025_26_wc1_gw5.parquet |
| 2025-26 | 6 | 0.85 | wc1_gw6 | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1963** | +68 | +68 | chips/chiplog_2025_26_wc1_gw6.parquet |
| 2025-26 | 6 | 0.85 | wc2_swing_gw32 | off | - | walkforward_h6_2025_26.parquet | post-#15 canonical | 2026-08-19 | **1956** | +61 | +61 | chips/chiplog_2025_26_wc2_swing_gw32.parquet |
| 2023-24 | 3 | 0.3 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2151** | +113 | +148 | sweep/simlog_2023_24_synth_H3_d30.parquet |
| 2023-24 | 3 | 0.45 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2148** | +110 | +145 | sweep/simlog_2023_24_synth_H3_d45.parquet |
| 2023-24 | 3 | 0.6 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2184** | +146 | +181 | sweep/simlog_2023_24_synth_H3_d60.parquet |
| 2023-24 | 4 | 0.3 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2151** | +113 | +148 | sweep/simlog_2023_24_synth_H4_d30.parquet |
| 2023-24 | 4 | 0.45 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2149** | +111 | +146 | sweep/simlog_2023_24_synth_H4_d45.parquet |
| 2023-24 | 4 | 0.6 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2110** | +72 | +107 | sweep/simlog_2023_24_synth_H4_d60.parquet |
| 2023-24 | 6 | 0.3 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **1975** | -63 | -28 | sweep/simlog_2023_24_synth_H6_d30.parquet |
| 2023-24 | 6 | 0.45 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2138** | +100 | +135 | sweep/simlog_2023_24_synth_H6_d45.parquet |
| 2023-24 | 6 | 0.6 | none | on | - | walkforward_h6_2023_24_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2126** | +88 | +123 | sweep/simlog_2023_24_synth_H6_d60.parquet |
| 2024-25 | 3 | 0.3 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2370** | +216 | +362 | sweep/simlog_2024_25_synth_H3_d30.parquet |
| 2024-25 | 3 | 0.45 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2277** | +123 | +269 | sweep/simlog_2024_25_synth_H3_d45.parquet |
| 2024-25 | 3 | 0.6 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2272** | +118 | +264 | sweep/simlog_2024_25_synth_H3_d60.parquet |
| 2024-25 | 4 | 0.3 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2376** | +222 | +368 | sweep/simlog_2024_25_synth_H4_d30.parquet |
| 2024-25 | 4 | 0.45 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2288** | +134 | +280 | sweep/simlog_2024_25_synth_H4_d45.parquet |
| 2024-25 | 4 | 0.6 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2254** | +100 | +246 | sweep/simlog_2024_25_synth_H4_d60.parquet |
| 2024-25 | 6 | 0.3 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2360** | +206 | +352 | sweep/simlog_2024_25_synth_H6_d30.parquet |
| 2024-25 | 6 | 0.45 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2340** | +186 | +332 | sweep/simlog_2024_25_synth_H6_d45.parquet |
| 2024-25 | 6 | 0.6 | none | on | - | walkforward_h6_2024_25_synth.parquet | post-#15 canonical+synth | 2026-08-18 | **2330** | +176 | +322 | sweep/simlog_2024_25_synth_H6_d60.parquet |
| 2025-26 | 3 | 0.3 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **2065** | +170 | +170 | sweep/simlog_2025_26_synth_H3_d30.parquet |
| 2025-26 | 3 | 0.45 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **2045** | +150 | +150 | sweep/simlog_2025_26_synth_H3_d45.parquet |
| 2025-26 | 3 | 0.6 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **1971** | +76 | +76 | sweep/simlog_2025_26_synth_H3_d60.parquet |
| 2025-26 | 4 | 0.3 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **2033** | +138 | +138 | sweep/simlog_2025_26_synth_H4_d30.parquet |
| 2025-26 | 4 | 0.45 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **2075** | +180 | +180 | sweep/simlog_2025_26_synth_H4_d45.parquet |
| 2025-26 | 4 | 0.6 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **2028** | +133 | +133 | sweep/simlog_2025_26_synth_H4_d60.parquet |
| 2025-26 | 6 | 0.3 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **2102** | +207 | +207 | sweep/simlog_2025_26_synth_H6_d30.parquet |
| 2025-26 | 6 | 0.45 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **1985** | +90 | +90 | sweep/simlog_2025_26_synth_H6_d45.parquet |
| 2025-26 | 6 | 0.6 | none | on | - | walkforward_h6_2025_26_synth.parquet | post-#15 canonical+synth | 2026-08-19 | **1979** | +84 | +84 | sweep/simlog_2025_26_synth_H6_d60.parquet |
| 2025-26 | 6 | 0.85 | none | off | - | (rate blend k=8, pre-#15 DC base rates) | pre-#15 | 2026-08-18 | **2060** | +165 | +165 | rate_blend_log.md section 7 |
| 2025-26 | 3 | 0.3 | none | off | - | (availability=True rebuild, same era) | pre-D1, pre-blend, pre-#15 | 2026-08-13 | **1938** | +43 | +43 | eval/walkforward.py docstring |
| 2025-26 | 6 | 0.85 | none | off | - | (D1 Variant B, static rates) | pre-blend, pre-#15 | 2026-08-17 | **2028** | +133 | +133 | d1_log.md section 9 |

## Valid comparisons (exhaustive)

1. **Chip effects**: any chips/bb-aware row vs the SAME season's
   `baseline` chips row at H=6 decay=0.85 (family post-#15,
   synth off). Variable = the chip package.
2. **combined_d60** vs the same season's sweep `base H6 d60` row.
3. **D4 base-vs-synth**: sweep rows within the same (season, H,
   decay) -- the 27 matched pairs of the sign test.
4. Nothing else. Cross-H, cross-decay, cross-season and every
   REFERENCE row: NOT comparable.

## Explicit flags

- No baseline is missing: every post-#15 config has a same-family
  baseline on disk.
- One historical cross-provenance comparison was ATTEMPTED and
  caught before measurement: D4 Phase 2's first 2025-26 synth
  build used the wrong writer (stamps differed); rebuilt before
  any number was read (overnight log, stage 2).
- The four reference figures are retained for lineage only.