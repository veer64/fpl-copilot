"""Generalise eval/build_season_totals_index.py's preserved-suffix handling
(preasof: bool -> preserved: str) and add the _pre_dcfix lineage, with pinned-cell
placeholders (__PIN_*__) to fill from the 2026-09-13 armlogs."""
p = r"C:\dev\fpl-copilot\eval\build_season_totals_index.py"
s = open(p, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
Q = "'"


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:90], s.count(old))
    s = s.replace(old, new)


# 1. stale suffix
rep('                  "preasof"]           # every canonical / arm frame before the 2026-09-11 as-of rebuild (LEAKAGE.md items 6-9)',
    '                  "preasof",           # every canonical / arm frame before the 2026-09-11 as-of rebuild (LEAKAGE.md items 6-9)' + nl +
    '                  "pre_dcfix"]         # every canonical / arm frame before the 2026-09-13 Dixon-Coles cutoff-day rebuild (LEAKAGE.md item 7; KNOWN_ISSUES #25)')

# 2. pinned cells
rep('                    ("2023-24", "gap0_tc2"): 2390, ("2024-25", "gap0_tc2"): 2285, ("2025-26", "gap0_tc2"): 2249,',
    '                    # 2026-09-13 DC CUTOFF-DAY REBUILD (Logs/dc_fix_log_2026-09-13.md; LEAKAGE.md item 7; KNOWN_ISSUES #25): the gap0 family' + nl +
    '                    # re-run on frames whose Dixon-Coles fit no longer trains on the cutoff day' + Q + 's results. The 2026-09-11 armlogs are' + nl +
    '                    # preserved as *_pre_dcfix and indexed as SUPERSEDED. Regenerated and labelled; they decide nothing (prereg section 5.7).' + nl +
    '                    ("2023-24", "gap0_tc2"): GAP0_TC2_2324, ("2024-25", "gap0_tc2"): GAP0_TC2_2425, ("2025-26", "gap0_tc2"): GAP0_TC2_2526,' + nl +
    '                    ("2023-24", "gap0_tc2_pre_dcfix"): 2390, ("2024-25", "gap0_tc2_pre_dcfix"): 2285, ("2025-26", "gap0_tc2_pre_dcfix"): 2249,')
rep('                    ("2023-24", "hmin_gap0"): 2302, ("2024-25", "hmin_gap0"): 2275, ("2025-26", "hmin_gap0_tc2"): 2227,',
    '                    ("2023-24", "hmin_gap0"): HMIN_GAP0_2324, ("2024-25", "hmin_gap0"): HMIN_GAP0_2425, ("2025-26", "hmin_gap0_tc2"): HMIN_GAP0_2526,' + nl +
    '                    ("2023-24", "hmin_gap0_pre_dcfix"): 2302, ("2024-25", "hmin_gap0_pre_dcfix"): 2275, ("2025-26", "hmin_gap0_tc2_pre_dcfix"): 2227,')
rep('                    ("2024-25", "both_gap0"): 2335, ("2025-26", "both_gap0_tc2"): 2074,',
    '                    ("2024-25", "both_gap0"): BOTH_GAP0_2425, ("2025-26", "both_gap0_tc2"): BOTH_GAP0_2526,' + nl +
    '                    ("2024-25", "both_gap0_pre_dcfix"): 2335, ("2025-26", "both_gap0_tc2_pre_dcfix"): 2074,')
rep('EXPECT_REFERENCE_CHIP = {"2023-24": 2390, "2024-25": 2285, "2025-26": 2249}',
    'EXPECT_REFERENCE_CHIP = {"2023-24": GAP0_TC2_2324, "2024-25": GAP0_TC2_2425, "2025-26": GAP0_TC2_2526}')
rep('EXPECT_ARMS_CHIP = {("2023-24", "hmin"): 2405,',
    '# The gap0-family cells of the 2026-09-13 Dixon-Coles cutoff-day rebuild, pinned from the armlogs (drift check only).' + nl +
    '# Were 2390 / 2285 / 2249 (gap0_tc2), 2302 / 2275 / 2227 (hmin_gap0), 2335 / 2074 (both_gap0) on the 2026-09-11 frames.' + nl +
    'GAP0_TC2_2324, GAP0_TC2_2425, GAP0_TC2_2526 = __PIN_GAP0__' + nl +
    'HMIN_GAP0_2324, HMIN_GAP0_2425, HMIN_GAP0_2526 = __PIN_HMIN__' + nl +
    'BOTH_GAP0_2425, BOTH_GAP0_2526 = __PIN_BOTH__' + nl +
    'EXPECT_ARMS_CHIP = {("2023-24", "hmin"): 2405,')

# 3. labels
rep('             "gap0_tc2": "PRODUCTION = REFERENCE CELL OF RECORD (2026-09-11): baseline gap0 on the as-of-rebuilt frames (leak fix + solver gap 0 + fixed crosswalk; bonus_delete; TC2 in-sim)",',
    '             "gap0_tc2": "PRODUCTION = REFERENCE CELL OF RECORD (2026-09-11; frames rebuilt 2026-09-13 for the DC cutoff-day fix): baseline gap0 on the as-of-rebuilt frames (leak fix + solver gap 0 + fixed crosswalk; bonus_delete; TC2 in-sim)",' + nl +
    '             "gap0_tc2_pre_dcfix": "baseline gap0 on the PRE-DC-FIX as-of frames (SUPERSEDED 2026-09-13; was PRODUCTION = REFERENCE CELL OF RECORD 2026-09-11)",')
rep('             "hmin_gap0_tc2_precrosswalk": "arm=horizon_minutes on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)",',
    '             "hmin_gap0_pre_dcfix": "arm=horizon_minutes on gap0, PRE-DC-FIX as-of frames (SUPERSEDED 2026-09-13; was the superseded reference cell of 2026-09-11)",' + nl +
    '             "hmin_gap0_tc2_pre_dcfix": "arm=horizon_minutes on gap0 + TC2 in-sim, PRE-DC-FIX as-of frames (SUPERSEDED 2026-09-13; was the superseded reference cell of 2026-09-11)",' + nl +
    '             "hmin_gap0_tc2_precrosswalk": "arm=horizon_minutes on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)",')
rep('             "both_gap0_tc2_precrosswalk": "arm=props+horizon_minutes on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)"}',
    '             "both_gap0_pre_dcfix": "arm=props+horizon_minutes on gap0, PRE-DC-FIX as-of frames (SUPERSEDED 2026-09-13; was the superseded production-intent row of 2026-09-11)",' + nl +
    '             "both_gap0_tc2_pre_dcfix": "arm=props+horizon_minutes on gap0 + TC2 in-sim, PRE-DC-FIX as-of frames (SUPERSEDED 2026-09-13; was the superseded production-intent row of 2026-09-11)",' + nl +
    '             "both_gap0_tc2_precrosswalk": "arm=props+horizon_minutes on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)"}')

# 4. preserved-suffix threading
rep('def _gap0_frames(season, base_arm, precrosswalk, preasof=False):', 'def _gap0_frames(season, base_arm, precrosswalk, preserved=""):')
rep('    are read against the _preasof frames they were actually built on."""' + nl + '    tag = season.replace("-", "_")' + nl +
    '    suf = "_precrosswalk" if (precrosswalk and season == "2025-26") else ("_preasof" if preasof else "")',
    '    are read against the _preasof frames they were actually built on. Rows built before the' + nl +
    '    2026-09-13 Dixon-Coles cutoff-day rebuild point at the preserved _pre_dcfix files.' + nl +
    '    `preserved` is that suffix ("" for the current frames)."""' + nl + '    tag = season.replace("-", "_")' + nl +
    '    suf = "_precrosswalk" if (precrosswalk and season == "2025-26") else preserved')
rep('def cap_pred_gap0(season, base_arm, precrosswalk, preasof=False):', 'def cap_pred_gap0(season, base_arm, precrosswalk, preserved=""):')
rep('    canon, arm_wf = _gap0_frames(season, base_arm, precrosswalk, preasof)' + nl + '    key = ("gap0cp", season, base_arm, precrosswalk, preasof)',
    '    canon, arm_wf = _gap0_frames(season, base_arm, precrosswalk, preserved)' + nl + '    key = ("gap0cp", season, base_arm, precrosswalk, preserved)')
rep('def _prefix_log(resume_from, tag, preasof=False):', 'def _prefix_log(resume_from, tag, preserved=""):')
rep('        if preasof and not name.endswith("_preasof.parquet"):' + nl + '            name = name.replace(".parquet", "_preasof.parquet")',
    '        if preserved and not name.endswith(f"{preserved}.parquet"):' + nl + '            name = name.replace(".parquet", f"{preserved}.parquet")')
rep('        preasof = p.stem.endswith("_preasof")          # pre-2026-09-11 armlogs, preserved and SUPERSEDED' + nl +
    '        # props_gap0 armlogs were not re-run on the as-of frames: read them against the frames they' + nl +
    '        # were built on (the preserved _preasof ones) so their TC1 read reproduces their figure of record.' + nl +
    '        frames_preasof = preasof or (base_arm == "props_gap0")',
    '        preasof = p.stem.endswith("_preasof")          # pre-2026-09-11 armlogs, preserved and SUPERSEDED' + nl +
    '        pre_dcfix = p.stem.endswith("_pre_dcfix")      # 2026-09-11 armlogs before the 2026-09-13 DC cutoff-day rebuild, preserved and SUPERSEDED' + nl +
    '        # props_gap0 armlogs were not re-run on the as-of frames: read them against the frames they' + nl +
    '        # were built on (the preserved _preasof ones) so their TC1 read reproduces their figure of record.' + nl +
    '        # Likewise every preserved armlog is read against the frames of ITS lineage.' + nl +
    '        frames_preserved = "_preasof" if (preasof or base_arm == "props_gap0") else ("_pre_dcfix" if pre_dcfix else "")')
rep('        if preasof:' + nl + '            arm = f"{arm}_preasof"',
    '        if preasof:' + nl + '            arm = f"{arm}_preasof"' + nl + '        if pre_dcfix:' + nl + '            arm = f"{arm}_pre_dcfix"')
rep('                          preasof=frames_preasof)', '                          preserved=frames_preserved)')
rep('            canon_wf, arm_wf = _gap0_frames(season, base_arm, precrosswalk, frames_preasof)' + nl +
    '            cp = cap_pred_gap0(season, base_arm, precrosswalk, frames_preasof)',
    '            canon_wf, arm_wf = _gap0_frames(season, base_arm, precrosswalk, frames_preserved)' + nl +
    '            cp = cap_pred_gap0(season, base_arm, precrosswalk, frames_preserved)')

# 5. flags
rep('                     "(LEAKAGE.md items 6-9 closed; KNOWN_ISSUES #22/#23/#24). Adopted 2026-09-11 as a JUDGEMENT CALL after the leak "',
    '                     "(LEAKAGE.md items 6-9 closed; KNOWN_ISSUES #22/#23/#24), REBUILT AGAIN 2026-09-13 with the Dixon-Coles fit no "' + nl +
    '                     "longer training on the cutoff day' + Q + 's results (LEAKAGE.md item 7; KNOWN_ISSUES #25; the 2026-09-11 cell is the "' + nl +
    '                     "_pre_dcfix row). Adopted 2026-09-11 as a JUDGEMENT CALL after the leak "')
rep('        elif preasof:' + nl + '            flags = ("SUPERSEDED (2026-09-11): built on frames carrying the three outcome-selection leaks (DC conditioned on realised "',
    '        elif pre_dcfix:' + nl +
    '            flags = ("SUPERSEDED (2026-09-13): built on the 2026-09-11 as-of frames, whose Dixon-Coles fit still trained on the cutoff "' + nl +
    '                     "day' + Q + 's RESULTS (LEAKAGE.md item 7 -- the date-boundary blind spot shared by the record' + Q + 's filter and the guard; "' + nl +
    '                     "KNOWN_ISSUES #25); preserved as *_pre_dcfix, never deleted. Its figure of record " + (' + nl +
    '                     "was PRODUCTION AND THE REFERENCE CELL OF RECORD (2026-09-11)" if base_arm == "gap0" else' + nl +
    '                     "was the superseded reference cell (2026-09-11, horizon; lever UNSETTLED)" if base_arm == "hmin_gap0" else' + nl +
    '                     "was the superseded production-intent row (2026-09-11, combined; levers UNSETTLED)" if base_arm == "both_gap0" else "was exploratory")' + nl +
    '                     + f"; the cell of record is arms/armlog_{tag}_{REFERENCE_ARM[season]} ({EXPECT_REFERENCE_CHIP[season]})")' + nl +
    '        elif preasof:' + nl + '            flags = ("SUPERSEDED (2026-09-11): built on frames carrying the three outcome-selection leaks (DC conditioned on realised "')
rep('                     "as-of-rebuilt frames. The lever" + ("" if base_arm == "hmin_gap0" else "s") + " are UNSETTLED, not settled: the "',
    '                     "as-of-rebuilt frames (rebuilt again 2026-09-13, DC cutoff-day fix). The lever" + ("" if base_arm == "hmin_gap0" else "s") + " are UNSETTLED, not settled: the "')

# 6. header prose
rep('     "*_preasof and listed here as SUPERSEDED, read against the _preasof frames it was built on."),',
    '     "*_preasof and listed here as SUPERSEDED, read against the _preasof frames it was built on. "' + nl +
    '     "RE-RUN AGAIN 2026-09-13 on frames whose Dixon-Coles fit no longer trains on the cutoff day' + Q + 's "' + nl +
    '     "results (LEAKAGE.md item 7; KNOWN_ISSUES #25; Logs/dc_fix_log_2026-09-13.md): gap0_tc2 stays "' + nl +
    '     "PRODUCTION AND THE REFERENCE CELLS OF RECORD on the rebuilt frames; the 2026-09-11 armlogs are kept "' + nl +
    '     "as *_pre_dcfix and listed as SUPERSEDED, read against the _pre_dcfix frames they were built on."),')
rep('NOT re-run on the as-of frames, read against the preserved _preasof frames). Every' + nl +
    'pre-rebuild artefact is preserved as `*_preasof` and indexed as SUPERSEDED.',
    'NOT re-run on the as-of frames, read against the preserved _preasof frames). Every' + nl +
    'pre-rebuild artefact is preserved as `*_preasof` and indexed as SUPERSEDED. 2026-09-13: the' + nl +
    'gap0 family re-run once more after the Dixon-Coles cutoff-day fix (LEAKAGE.md item 7,' + nl +
    'KNOWN_ISSUES #25); the 2026-09-11 cells 2390 / 2285 / 2249, 2302 / 2275 / 2227 and 2335 / 2074' + nl +
    'are preserved as `*_pre_dcfix` and indexed as SUPERSEDED; the regenerated cells decide nothing.')
rep('   superseded lineage. A _preasof row may be compared ONLY to another _preasof row.',
    '   superseded lineage. A _preasof row may be compared ONLY to another _preasof row, and a' + nl +
    '   _pre_dcfix row (the 2026-09-11 lineage, before the DC cutoff-day rebuild) ONLY to another _pre_dcfix row.')
open(p, "w", encoding="utf-8", newline="").write(s)
print("edited; placeholders:", s.count("__PIN_"))
