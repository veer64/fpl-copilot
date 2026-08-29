# build_season_totals_index.py
# Assemble every season total the project has produced into ONE index with
# provenance, so figures stop being scattered archaeology.
# Writes Logs/season_totals_index.md. Reporting only -- no simulations.
#
# Extended 2026-08-24 to cover the post-2026-08-20 families: data/p1
# (p1log/wclog/fslog/p3log/p5log), data/teamnews (oraclelog) and data/arms
# (armlog -- closed non-adoptions, 2026-08-26), and to show
# PATH and CHIP-INCLUSIVE totals in separate columns everywhere.
#
# CORRECTED 2026-08-24 (same day, later): the chip-inclusive convention
# inherited from P4 added BOTH bench@BB2 and captain_bonus@BB2 (TC2) on the
# same gameweek. FPL allows ONE chip per gameweek, so every such figure
# priced an illegal play (it was described as "optimistic by min(TC2, BB2
# bench)"; that understated it -- no legal play realises those totals).
# Correction of record: on any gameweek carrying two reads the Bench Boost
# read is KEPT and the TC2 read is DROPPED -- shown struck through, never
# silently removed. BB2 has no legal alternative week in two of the three
# seasons (no other H2 double clears its >=4-team floor) while a Triple
# Captain can always move, and dropping is hindsight-free; relocating TC2 to
# its rule-revised week and reading what the captain scored there would be a
# single-draw hindsight read, which is NOT adopted. Reference cells moved
# 2299/2301/2219 -> 2296/2294/2206. Rule of record for TC2 revised in
# Logs/p4_chip_policy_log.md section 12c; KNOWN_ISSUES #16.
#
# TOTALS -- stored vs recomputed (read this before trusting a number):
#   * NO log family stores a chip-inclusive total. The stored per-file figure
#     is `final_total` = the PATH total (the simulator scores no chip points;
#     BB/TC are exogenous reads -- simulator docstring philosophy).
#     Asserted here: final_total == points.sum() for every file.
#   * Every chip-inclusive figure in the index is therefore RECOMPUTED, by the
#     measure-script-of-record convention for its family, minus the illegal
#     read:
#       - fslog  (measure_full_system.py):  path + bench@BB1 + bench@BB2
#         + capbonus@TC1 (predicted-captain peak GW1-19 excl {WC1, BB1},
#         predictions = own-cutoff e_points from the walkforward file).
#         The former capbonus@BB2 (TC2) read is DROPPED (collision).
#       - p5log  (measure_p5.py) and oraclelog (measure_teamnews_knowable.py):
#         identical convention with WC1=2; oracle rows use the BASE model's
#         cap predictions and the reference cell's BB weeks, so the read is
#         uniform across arms (asserted equal to the log's own stamp).
#       - p3log: same standing convention (measure_p3.py quoted windows, not
#         chip-inclusive totals; TC1 exclusion uses the row's own wc1_week).
#       - chips era (measure_chip_d45.py pkg2h / measure_chip_phase2.py):
#         path + bench@BB for configs that scheduled a BB week (pkg_d45,
#         combined_*, bbaware_*); the former capbonus@BB (TC2) read is
#         DROPPED. No TC1/BB1 read: the "all-chips" variant of
#         measure_chip_d45 was a derived report row, not a run.
#       - sweep, p1log, wclog, chip configs without a BB: no exogenous reads
#         exist, chip-inclusive == path by identity (WC/FH change the path
#         itself).
#     Recomputed values are marked (r) and their reads decomposed in the
#     `chip reads` column so an error cannot enter quietly.
#
# LEGALITY (structural, total-independent): every row's EFFECTIVE chip
# schedule -- in-sim WC/FH weeks + BB read weeks + the TC read weeks the
# recompute actually used -- is passed through squad/chip_legality.py before
# the index is written. It fails on the old convention (tests/
# test_chip_legality.py proves it) and would have caught this on day one.
#
# REFERENCE CELLS OF RECORD MOVED 2026-08-26: the system as configured is
# BONUS_MODE="delete" with Triple Captain 2 scheduled IN-SIM on the 12c(ii)
# week (captain = the MIP's own cap variable at that deadline; path identical
# to the no-TC2 run in every gameweek). Reference cells are the
# data/arms/armlog_*_bonusdel_tc2 rows: 2251 / 2306 / 2268. The fslog
# base_wc2 rows (2296 / 2294 / 2206, TC2 scored zero, incumbent bonus term)
# stay indexed and drift-checked but are SUPERSEDED as reference cells.
#
# REFERENCE CELLS OF RECORD MOVED AGAIN 2026-08-28: the reference cells are
# now the HORIZON-MINUTES arm on the gap0 convention (penalty leak fix e04fb72 +
# solver gap 0 37ad782 + fixed crosswalk a758541, BONUS_MODE="delete", all
# chips, WC1 @ GW2, TC2 in-sim): data/arms/armlog_*_hmin_gap0[_tc2] rows
# = 2425 / 2335 / 2266. That arm was REJECTED on its pre-registered component
# test and this adoption cites season totals, which the standing rule forbids;
# the objection is recorded in the HEADER of the generated index, not only in
# the commit message. Superseded, dated: 2251/2306/2268 (bonusdel_tc2, pre-fix,
# 2026-08-26); 2343/2300/2190 (leakfix_tc2, leak fix only, 2026-08-27);
# 2343/2306/2190 (gap0_tc2 pre-crosswalk, 2026-08-27); 2343/2306/2216
# (gap0_tc2 on the fixed crosswalk -- the previous candidate, 2026-08-28; now
# the SHADOW configuration). Configuration roles: reference = horizon;
# production intent = combined (props+horizon, 2459 / 2264, two seasons);
# shadow = baseline gap0 (2343 / 2306 / 2216).
#
# Self-check (drift only -- circular by construction, kept for that purpose):
# the recompute chain is validated against the corrected reference figures
# (fslog base_wc2 chip-inclusive == 2296/2294/2206), the p1 baselines'
# path totals (2204/2362/2032) and every gap0-family arm figure of record
# (EXPECT_ARMS_CHIP / EXPECT_REFERENCE_CHIP) before writing.

import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent

def _ref_wf_path(tag):
    """Predictions the REFERENCE cells were built on. After the 2026-08-26 bonus-term
    adoption the canonical file changed; the pre-adoption canonical is preserved as
    _prebonusdel and is the file the reference logs' TC1 selection must be read from,
    so 2296 / 2294 / 2206 cannot move silently (KNOWN_ISSUES #20)."""
    from pathlib import Path as _P
    p = REPO / "data" / f"walkforward_h6_{tag}_prebonusdel.parquet"
    return p if p.exists() else REPO / "data" / f"walkforward_h6_{tag}.parquet"

sys.path.insert(0, str(REPO / "squad"))
from chip_legality import check_chip_schedule  # noqa: E402

CHIPS, SWEEP = REPO / "data" / "chips", REPO / "data" / "sweep"
P1, TN = REPO / "data" / "p1", REPO / "data" / "teamnews"
ARMS = REPO / "data" / "arms"

# Average manager scores. CLAIMED = the figures supplied for the first report;
# ONDISK = fplcache post-season snapshot, sum of events[].average_entry_score
# (asserted == 2003/2008/1895 by the measure scripts of record).
AVG_CLAIMED = {"2023-24": 2038, "2024-25": 2154, "2025-26": 1895}
AVG_ONDISK = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}

STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling",
          "d1_terms_active", "cs_unified", "rate_blend_active",
          "dc_rule_active", "synthetic_lambda_active"]

# Walkforward files with these suffixes are non-canonical (preserved
# artefacts of superseded configs). Rows sourced from them are FLAGGED
# superseded, never deleted.
STALE_SUFFIXES = ["prefix", "dcbase", "prerateblend", "preunify", "presynth",
                  "synth", "baseline", "d1cards", "av", "odds2", "dgwonly",
                  "precrosswalk"]      # 2025-26 canonical / arm frames before the crosswalk fix (a758541)
STALE_RE = re.compile(r"_(" + "|".join(STALE_SUFFIXES) + r")\.parquet")

# Known-of-record figures the recompute chain must reproduce exactly.
# CORRECTED 2026-08-24 from 2299/2301/2219 (illegal TC2@BB2 read dropped).
# This is a DRIFT check: it is circular for a convention error (it compares
# a recompute to a figure produced by the same convention). Legality is
# guarded separately and structurally by check_chip_schedule.
EXPECT_FS_WC2_CHIP = {"2023-24": 2296, "2024-25": 2294, "2025-26": 2206}
EXPECT_P1_BASE_PATH = {"2023-24": 2204, "2024-25": 2362, "2025-26": 2032}

TC2_DROP_REASON = "collision with BB2 -- one chip per gameweek"

# ARMS family (data/arms/armlog_*): props / horizon-minutes / both, all CLOSED
# non-adoptions (2026-08-26). Drift check against the measure script of record
# (eval/measure_arms_full_system.py; Logs/props_season_log.md).
EXPECT_ARMS_CHIP = {("2023-24", "hmin"): 2405, ("2024-25", "baseline8"): 2294,
                    ("2024-25", "props"): 2243, ("2024-25", "hmin"): 2339,
                    ("2024-25", "both"): 2257, ("2025-26", "props"): 2099,
                    ("2025-26", "hmin"): 2122, ("2025-26", "both"): 2134,
                    # 2026-08-26 arms (penalty_fix / topend_calibration / bonus_rebuild / bonus_delete preregs; p4 log s.15)
                    ("2023-24", "penfix"): 2291, ("2024-25", "penfix"): 2408, ("2025-26", "penfix"): 2139,
                    ("2023-24", "cal"): 2265, ("2024-25", "cal"): 2298, ("2025-26", "cal"): 2111,
                    ("2023-24", "cal_penfix"): 2286, ("2024-25", "cal_penfix"): 2399, ("2025-26", "cal_penfix"): 2135,
                    ("2023-24", "bonusow"): 2280, ("2024-25", "bonusow"): 2312, ("2025-26", "bonusow"): 2094,
                    ("2023-24", "bonusdel"): 2241, ("2024-25", "bonusdel"): 2277, ("2025-26", "bonusdel"): 2261,
                    ("2023-24", "bonusdel_tc2"): 2251, ("2024-25", "bonusdel_tc2"): 2306, ("2025-26", "bonusdel_tc2"): 2268,
                    # gap0 family (2026-08-27/28; data/leakfix_logs/arms_table_crosswalk.txt, gap0_chip_reads.txt).
                    # Arms that ran TC2 zero carry a TC2-equivalent captain multiple at the rule week (GW25/24/26).
                    ("2023-24", "gap0_tc2"): 2343, ("2024-25", "gap0_tc2"): 2306, ("2025-26", "gap0_tc2"): 2216,
                    ("2025-26", "gap0_tc2_precrosswalk"): 2190,
                    ("2023-24", "hmin_gap0"): 2425, ("2024-25", "hmin_gap0"): 2335, ("2025-26", "hmin_gap0_tc2"): 2266,
                    ("2025-26", "hmin_gap0_tc2_precrosswalk"): 2266,
                    ("2024-25", "props_gap0"): 2328, ("2025-26", "props_gap0_tc2"): 2221, ("2025-26", "props_gap0_tc2_precrosswalk"): 2212,
                    ("2024-25", "both_gap0"): 2459, ("2025-26", "both_gap0_tc2"): 2264, ("2025-26", "both_gap0_tc2_precrosswalk"): 2283}
# THE REFERENCE CELLS OF RECORD (2026-08-28): HORIZON-MINUTES arm on the gap0 convention.
# Was 2251/2306/2268 (bonusdel_tc2, 2026-08-26). See the module docstring and the index HEADER for the
# recorded objection: the horizon arm was REJECTED on its pre-registered component test.
EXPECT_REFERENCE_CHIP = {"2023-24": 2425, "2024-25": 2335, "2025-26": 2266}
REFERENCE_ARM = {"2023-24": "hmin_gap0", "2024-25": "hmin_gap0", "2025-26": "hmin_gap0_tc2"}
GAP0_FAMILY = ("gap0", "props_gap0", "hmin_gap0", "both_gap0", "hold_gap0")
TC2_RULE_WEEK = {"2023-24": 25, "2024-25": 24, "2025-26": 26}      # p4 log 12c (ii)
ARM_LABEL = {"baseline8": "baseline re-run", "props": "arm=props",
             "hmin": "arm=horizon_minutes", "both": "arm=props+horizon_minutes",
             "penfix": "arm=penalty_fix (NOT adopted)", "cal": "arm=topend_cal (NOT adopted)",
             "cal_penfix": "arm=topend_cal+penalty_fix (NOT adopted)",
             "bonusow": "arm=bonus_rebuild_outcome (NOT adopted)",
             "bonusdel": "arm=bonus_delete (ADOPTED; TC2 scored zero)",
             "bonusdel_tc2": "bonus_delete + TC2 in-sim (SUPERSEDED reference cell 2026-08-26, pre-leak-fix canonical)",
             "leakfix": "arm=leak-fixed canonical (bonus_delete; TC2 scored zero)",
             "leakfix_tc2": "leak-fixed canonical + bonus_delete + TC2 in-sim (SUPERSEDED reference cell 2026-08-27; MIP gap 1e-4)",
             "gap0_tc2": "SHADOW: baseline gap0 (leak fix + solver gap 0 + fixed crosswalk; bonus_delete; TC2 in-sim)",
             "gap0_tc2_precrosswalk": "baseline gap0 on the PRE-CROSSWALK 2025-26 canonical (SUPERSEDED candidate 2026-08-27)",
             "hmin_gap0": "REFERENCE CELL OF RECORD (2026-08-28): arm=horizon_minutes on gap0 (TC2 zero; TC2-equivalent read at the rule week)",
             "hmin_gap0_tc2": "REFERENCE CELL OF RECORD (2026-08-28): arm=horizon_minutes on gap0 + TC2 in-sim",
             "hmin_gap0_tc2_precrosswalk": "arm=horizon_minutes on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)",
             "props_gap0": "arm=props on gap0 (EXPLORATORY; TC2 zero; TC2-equivalent read at the rule week)",
             "props_gap0_tc2": "arm=props on gap0 + TC2 in-sim (EXPLORATORY)",
             "props_gap0_tc2_precrosswalk": "arm=props on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)",
             "both_gap0": "PRODUCTION INTENT: arm=props+horizon_minutes on gap0 (TC2 zero; TC2-equivalent read at the rule week)",
             "both_gap0_tc2": "PRODUCTION INTENT: arm=props+horizon_minutes on gap0 + TC2 in-sim",
             "both_gap0_tc2_precrosswalk": "arm=props+horizon_minutes on gap0, PRE-CROSSWALK 2025-26 frame (SUPERSEDED)"}
# arms whose walk-forward frame lives in data/ (not data/arms/); bonusdel_tc2 shares bonusdel's frame
ARM_WF_IN_DATA = {"penfix": "penfix", "cal": "cal", "cal_penfix": "cal_penfix", "bonusow": "bonusow",
                  "bonusdel": "bonusdel", "bonusdel_tc2": "bonusdel",
                  # leak-fixed arms read the CANONICAL itself (no suffix): walkforward_h6_{tag}.parquet
                  "leakfix": "", "leakfix_tc2": ""}

_wf_cache, _cap_cache = {}, {}


def wf_stamps(wf_name):
    """Family label + compact stamp string, read from the walkforward file."""
    if wf_name in _wf_cache:
        return _wf_cache[wf_name]
    path = REPO / "data" / wf_name
    cols = pq.read_schema(path).names
    have = [c for c in STAMPS if c in cols]
    row = pd.read_parquet(path, columns=have).iloc[0]
    synth = bool(row.get("synthetic_lambda_active", False))
    fam = "post-#15 canonical" + ("+synth" if synth else "")

    def b(c):
        return {True: "T", False: "F"}.get(row.get(c), "?") \
            if c in row.index else "?"
    compact = (f"av={b('minutes_availability')} d1={b('d1_terms_active')} "
               f"blend={b('rate_blend_active')} "
               f"dgw={row.get('dgw_handling', '?')} "
               f"synth={b('synthetic_lambda_active')}")
    full = {c: row.get(c) for c in have}
    _wf_cache[wf_name] = (fam, compact, full)
    return _wf_cache[wf_name]


def cap_pred(season):
    """(gw, captain name) -> own-cutoff predicted points. Exactly the
    measure_full_system / measure_p5 / measure_teamnews construction."""
    if season in _cap_cache:
        return _cap_cache[season]
    tag = season.replace("-", "_")
    wf = pd.read_parquet(_ref_wf_path(tag),
                         columns=["cutoff", "gw", "name", "e_points"])
    own = wf[wf["cutoff"] == wf["gw"]]
    _cap_cache[season] = {(int(g), n): float(p or 0) for g, n, p in
                          zip(own["gw"], own["name"], own["e_points"])}
    return _cap_cache[season]


def load_log(path):
    d = pd.read_parquet(path)
    assert int(d["final_total"].iloc[0]) == int(d["points"].sum()), \
        f"{path.name}: final_total != points.sum() -- path-total invariant broken"
    return d.set_index("gw")


def chip_weeks(d):
    """Scheduled chip weeks read off the log itself (the artefact of record):
    per-gw wildcard/free_hit flags + the bench-boost stamps."""
    wc = [int(g) for g in d.index[d["wildcard"]]] if "wildcard" in d else []
    fh = [int(g) for g in d.index[d["free_hit"]]] if "free_hit" in d else []
    bb = []
    if "bench_boost_gws" in d.columns:
        s = str(d["bench_boost_gws"].iloc[0])
        if s and s not in ("-1", "None", "nan"):
            bb = [int(x) for x in s.split(",")]
    elif "bench_boost_gw" in d.columns:
        v = int(d["bench_boost_gw"].iloc[0])
        if v > 0:
            bb = [v]
    return wc, fh, bb


def tc_weeks_insim(d):
    """In-sim Triple Captain weeks: allowed since 2026-08-26 for the bonusdel_tc2
    reference cells only; every other family asserts none."""
    if "triple_captain" in d.columns:
        return [int(g) for g in d.index[d["triple_captain"].astype(bool)]]
    return []


def played_weeks(d):
    return {int(g) for g in d.index}


def sched_str(wc, fh, bb):
    parts = []
    if wc:
        parts.append("WC@" + ",".join(map(str, wc)))
    if fh:
        parts.append("FH@" + ",".join(map(str, fh)))
    if bb:
        parts.append("BB@" + ",".join(map(str, bb)))
    return " ".join(parts) if parts else "--"


def tc1_read(d, excl, cp):
    """TC1 = argmax over GW1-19 (minus chip weeks) of the played captain's
    own-cutoff predicted points; the read is his realized captain_bonus.
    Mirrors measure_full_system exactly (strict >, first max wins)."""
    tc1_gw, best = None, -1
    for gw in range(1, 20):
        if gw in excl or gw not in d.index:
            continue
        v = cp.get((gw, d.loc[gw, "captain"]), 0)
        if v > best:
            tc1_gw, best = gw, v
    return tc1_gw, (int(d.loc[tc1_gw, "captain_bonus"]) if tc1_gw else 0)


def standing_reads(d, wc1, bb, cp):
    """The full-system convention as P4 defined it: bench@BB1 + bench@BB2
    + capbonus@BB2 (TC2) + capbonus@TC1. The TC2 read is still LISTED so the
    correction is visible; row() drops it as a collision."""
    bb1, bb2 = bb
    reads = [("bench", bb1, int(d.loc[bb1, "bench_points"])),
             ("bench", bb2, int(d.loc[bb2, "bench_points"])),
             ("TC2 cap", bb2, int(d.loc[bb2, "captain_bonus"]))]
    tc1_gw, tc1 = tc1_read(d, {wc1, bb1}, cp)
    reads.append(("TC1 cap", tc1_gw, tc1))
    return reads


def drop_colliding_tc(reads, bb):
    """Correction of record (2026-08-24): a Triple Captain read on a Bench
    Boost week is an illegal play. Keep the BB read, DROP the TC read, and
    keep it in the list with its reason so the artefact shows the change."""
    out = []
    for lbl, gw, v in reads:
        dropped = TC2_DROP_REASON if (lbl.startswith("TC") and gw in bb) else ""
        out.append((lbl, gw, v, dropped))
    return out


def row(section, season, config, H, decay, sched, wf, gates, path_total,
        reads, source, flags="", run=None, wc=(), fh=(), bb=(), played=None,
        tc_insim=()):
    reads = drop_colliding_tc(reads, list(bb))
    kept = [r for r in reads if not r[3]]
    tc_weeks = [gw for lbl, gw, _, _ in kept
                if lbl.startswith("TC") and gw and not lbl.startswith("TC2 in-sim")]
    tc_weeks += list(tc_insim)
    # STRUCTURAL legality check on the effective schedule -- independent of
    # any total. This is what the old convention never had.
    check_chip_schedule({"wildcard": list(wc), "free_hit": list(fh),
                         "bench_boost": list(bb), "triple_captain": tc_weeks},
                        played_gws=played, source=source)
    if any(r[3] for r in reads):
        flags = (flags + "; " if flags else "") + \
            "TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24)"
    add = sum(v for lbl, _, v, _ in kept if not lbl.startswith("TC2 in-sim"))
    return dict(section=section, season=season, config=config, H=H,
                decay=decay, sched=sched, wf=wf, gates=gates,
                path=path_total, reads=reads, chip=path_total + add,
                recomputed=bool(reads), source=source, flags=flags, run=run,
                wc=list(wc), fh=list(fh), bb=list(bb), played=played)


def gates_str(d, extra=""):
    """Row-level sim gates that deviate from the live default config."""
    out = []

    def on(c):
        return c in d.columns and bool(d[c].iloc[0])
    if "bench_boost_aware" in d.columns and not bool(
            d["bench_boost_aware"].iloc[0]):
        out.append("bb_aware=off")
    if on("opening_horizon_active"):
        out.append("opening_horizon")
    if on("opening_robust_active"):
        out.append("opening_robust")
    if on("bench_order_by_play"):
        out.append("bench_order")
    if on("xi_tiebreak_p60"):
        out.append("xi_p60")
    if on("early_hit_discount_active"):
        out.append(f"early_hit_bar={int(d['early_hit_bar'].iloc[0])}")
    if on("oracle_minutes_active"):
        out.append("ORACLE")
    if extra:
        out.append(extra)
    return " ".join(out) if out else "--"


def mtime(p):
    return dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")


def rows_sweep():
    out = []
    for p in sorted(SWEEP.glob("simlog_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        tag = season.replace("-", "_")
        synth = d["variant"].iloc[0] == "synth"
        wf = f"walkforward_h6_{tag}{'_synth' if synth else ''}.parquet"
        out.append(row("sweep", season, d["variant"].iloc[0],
                       int(d["horizon"].iloc[0]), float(d["decay"].iloc[0]),
                       "--", wf, "--", int(d["final_total"].iloc[0]), [],
                       f"sweep/{p.name}", run=mtime(p), played=played_weeks(d)))
    return out


def rows_chips():
    out = []
    for p in sorted(CHIPS.glob("chiplog_*.parquet")):
        d = load_log(p)
        season, config = d["season"].iloc[0], d["config"].iloc[0]
        tag = season.replace("-", "_")
        decay = 0.45 if config.endswith("_d45") else \
            0.6 if config.endswith("_d60") else 0.85
        wc, fh, bb = chip_weeks(d)
        reads = []
        if bb:               # pkg2h / phase-2 convention: bench + TC2 at BB;
            assert len(bb) == 1, f"{p.name}: chips-era log with two BB weeks"
            reads = [("bench", bb[0], int(d.loc[bb[0], "bench_points"])),
                     ("TC2 cap", bb[0], int(d.loc[bb[0], "captain_bonus"]))]
        out.append(row("chips", season, config, 6, decay, sched_str(wc, fh, bb),
                       f"walkforward_h6_{tag}.parquet", gates_str(d),
                       int(d["final_total"].iloc[0]), reads,
                       f"chips/{p.name}", run=mtime(p),
                       wc=wc, fh=fh, bb=bb, played=played_weeks(d)))
    return out


def rows_p1():
    out = []
    for p in sorted(P1.glob("p1log_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        assert int(d["horizon"].iloc[0]) == 6 and \
            float(d["decay"].iloc[0]) == 0.45
        wc, fh, bb = chip_weeks(d)
        assert not (wc or fh or bb), f"{p.name}: p1 arm scheduled chips"
        out.append(row("p1", season, f"arm={d['arm'].iloc[0]}", 6, 0.45, "--",
                       d["wf_file"].iloc[0], gates_str(d),
                       int(d["final_total"].iloc[0]), [],
                       f"p1/{p.name}", run=mtime(p), played=played_weeks(d)))
    return out


def rows_wcgrid():
    out = []
    for p in sorted(P1.glob("wclog_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        wc, fh, bb = chip_weeks(d)
        assert wc == [int(d["wc_gw"].iloc[0])] and not fh and not bb, \
            f"{p.name}: unexpected chip schedule for a WC1-grid cell"
        out.append(row("wcgrid", season,
                       f"opening={d['opening'].iloc[0]} wc1={wc[0]}",
                       6, 0.45, sched_str(wc, fh, bb), d["wf_file"].iloc[0],
                       gates_str(d), int(d["final_total"].iloc[0]), [],
                       f"p1/{p.name}", run=mtime(p),
                       wc=wc, played=played_weeks(d)))
    return out


def rows_fullsystem():
    out, fs_chip = [], {}
    for p in sorted(P1.glob("fslog_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        wc1, bb1, bb2 = (int(d[c].iloc[0]) for c in ("wc1", "bb1", "bb2"))
        assert str(d["bench_boost_gws"].iloc[0]) == f"{bb1},{bb2}"
        wc, fh, bb = chip_weeks(d)
        assert set(bb) == {bb1, bb2} and wc1 in wc
        assert not tc_weeks_insim(d), f"{p.name}: in-sim TC in a fslog"
        reads = standing_reads(d, wc1, [bb1, bb2], cap_pred(season))
        r = row("fullsystem", season,
                f"opening={d['opening'].iloc[0]} wc1={wc1}", 6, 0.45,
                sched_str(wc, fh, bb), d["wf_file"].iloc[0], gates_str(d),
                int(d["final_total"].iloc[0]), reads,
                f"p1/{p.name}", run=mtime(p),
                wc=wc, fh=fh, bb=bb, played=played_weeks(d))
        if d["opening"].iloc[0] == "base" and wc1 == 2:
            fs_chip[season] = r["chip"]
            r["flags"] = (r["flags"] + "; " if r["flags"] else "") + (
                "SUPERSEDED AS REFERENCE CELL (2026-08-26): TC2 scored zero and incumbent bonus term; "
                f"the reference of record is arms/armlog_{season.replace('-', '_')}_{REFERENCE_ARM[season]} "
                f"({EXPECT_REFERENCE_CHIP[season]}, horizon arm on the gap0 convention, 2026-08-28)")
        out.append(r)
    assert fs_chip == EXPECT_FS_WC2_CHIP, (
        f"chip-inclusive recompute drifted from the corrected reference "
        f"figures: {fs_chip} != {EXPECT_FS_WC2_CHIP}")
    return out


def rows_p3():
    out = []
    for p in sorted(P1.glob("p3log_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        wc1, bar = int(d["wc1_week"].iloc[0]), int(d["bar"].iloc[0])
        wc, fh, bb = chip_weeks(d)
        assert len(bb) == 2 and wc1 in wc
        reads = standing_reads(d, wc1, bb, cap_pred(season))
        out.append(row("p3", season, f"wc1={wc1} bar={bar}", 6, 0.45,
                       sched_str(wc, fh, bb), d["wf_file"].iloc[0],
                       gates_str(d), int(d["final_total"].iloc[0]), reads,
                       f"p1/{p.name}", run=mtime(p),
                       wc=wc, fh=fh, bb=bb, played=played_weeks(d)))
    return out


def rows_p5():
    out = []
    for p in sorted(P1.glob("p5log_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        wc, fh, bb = chip_weeks(d)
        assert len(bb) == 2 and 2 in wc, f"{p.name}: not the full-system wc2 config"
        reads = standing_reads(d, 2, bb, cap_pred(season))
        out.append(row("p5", season, f"arm={d['arm'].iloc[0]}", 6, 0.45,
                       sched_str(wc, fh, bb), d["wf_file"].iloc[0],
                       gates_str(d), int(d["final_total"].iloc[0]), reads,
                       f"p1/{p.name}", run=mtime(p),
                       wc=wc, fh=fh, bb=bb, played=played_weeks(d)))
    return out


ORACLE_ARMS = {None: "full-horizon oracle", "A": "A step0-only oracle",
               "B": "B calendar-knowable mask", "C": "C Guardian-reported mask"}


def rows_oracle():
    out = []
    for p in sorted(TN.glob("oraclelog_*.parquet")):
        d = load_log(p)
        season = d["season"].iloc[0]
        tag = season.replace("-", "_")
        arm = d["arm"].iloc[0] if "arm" in d.columns else None
        assert bool(d["oracle_minutes_active"].iloc[0]), \
            f"{p.name}: oracle log without the oracle stamp"
        # BB weeks must match the reference cell (the uniform read convention
        # of measure_teamnews_knowable.py)
        ref = pd.read_parquet(P1 / f"fslog_{tag}_base_wc2.parquet",
                              columns=["bb1", "bb2"])
        bb1, bb2 = int(ref["bb1"].iloc[0]), int(ref["bb2"].iloc[0])
        wc, fh, bb = chip_weeks(d)
        assert bb == [bb1, bb2] and 2 in wc, \
            f"{p.name}: chip schedule differs from the reference cell"
        reads = standing_reads(d, 2, bb, cap_pred(season))
        out.append(row("oracle", season, ORACLE_ARMS[arm], 6, 0.45,
                       sched_str(wc, fh, bb), d["wf_file"].iloc[0],
                       gates_str(d), int(d["final_total"].iloc[0]), reads,
                       f"teamnews/{p.name}",
                       flags="LEAKAGE INSTRUMENT -- never adopt, "
                             "never a baseline", run=mtime(p),
                       wc=wc, fh=fh, bb=bb, played=played_weeks(d)))
    return out


def cap_pred_arm(season, arm):
    """TC1 on the ARM's own step-0 predictions where the arm changes step 0
    (props); the refit does not touch step 0. Mirrors measure_arms_full_system."""
    tag = season.replace("-", "_")
    if arm in ARM_WF_IN_DATA:
        suffix = ARM_WF_IN_DATA[arm]
        p = REPO / "data" / (f"walkforward_h6_{tag}_{suffix}.parquet" if suffix else f"walkforward_h6_{tag}.parquet")
    else:
        p = ARMS / f"walkforward_h6_{tag}_{arm}.parquet"
    if (arm in ("props", "both") or arm in ARM_WF_IN_DATA) and p.exists():
        wf = pd.read_parquet(p, columns=["cutoff", "gw", "name", "e_points"])
        own = wf[wf["cutoff"] == wf["gw"]]
        return {(int(g), n): float(v or 0) for g, n, v in
                zip(own["gw"], own["name"], own["e_points"])}
    return cap_pred(season)


def _gap0_frames(season, base_arm, precrosswalk):
    """(canonical frame name, arm frame name or None) for a gap0-family arm, as the
    strings the index uses for wf provenance (relative to data/). 2025-26 rows built
    before the crosswalk fix point at the preserved _precrosswalk files."""
    tag = season.replace("-", "_")
    suf = "_precrosswalk" if (precrosswalk and season == "2025-26") else ""
    canon = f"walkforward_h6_{tag}{suf}.parquet"
    a = base_arm.replace("_gap0", "")
    arm_wf = None if base_arm in ("gap0", "hold_gap0") else f"arms_gap0/walkforward_h6_{tag}_{a}{suf}.parquet"
    return canon, arm_wf


def cap_pred_gap0(season, base_arm, precrosswalk):
    """TC1 captain predictions for the gap0 family, mirroring data/leakfix_logs/arms_table.py
    exactly: the canonical's own-cutoff e_points, overridden by the arm frame's where the arm
    touches step 0 (props / both). hmin leaves step 0 untouched."""
    canon, arm_wf = _gap0_frames(season, base_arm, precrosswalk)
    key = ("gap0cp", season, base_arm, precrosswalk)
    if key in _cap_cache:
        return _cap_cache[key]
    wf = pd.read_parquet(REPO / "data" / canon, columns=["cutoff", "gw", "name", "e_points"])
    own = wf[wf["cutoff"] == wf["gw"]]
    cp = {(int(g), n): float(v or 0) for g, n, v in zip(own["gw"], own["name"], own["e_points"])}
    if base_arm in ("props_gap0", "both_gap0"):
        a = pd.read_parquet(REPO / "data" / arm_wf, columns=["cutoff", "gw", "name", "e_points"])
        ao = a[a["cutoff"] == a["gw"]]
        cp.update({(int(g), n): float(v or 0) for g, n, v in zip(ao["gw"], ao["name"], ao["e_points"])})
    _cap_cache[key] = cp
    return cp


def _prefix_log(resume_from, tag):
    """Log whose GW1..k rows are stitched in front of an arm that starts at GW k+1.
    Pre-gap0 arms resumed from the fslog reference; gap0 arms resume from armlog_*_gap0_tc2
    (the runner stamps `resume_from`)."""
    name = str(resume_from).split("@")[0] if resume_from not in (None, "none", "") else ""
    if name.startswith("armlog_"):
        return pd.read_parquet(ARMS / name)
    if name.startswith("fslog_"):
        return pd.read_parquet(P1 / name)
    return pd.read_parquet(P1 / f"fslog_{tag}_base_wc2.parquet")


def rows_arms():
    """Arms, incl. THE REFERENCE CELLS OF RECORD (hmin_gap0, 2026-08-28). 2024-25 arms
    start at GW8 from their baseline's GW7 state (fslog base_wc2 for the 2026-08-26 arms;
    armlog gap0_tc2 for the gap0 family, per the log's `resume_from` stamp): the prefix rows
    are stitched in front so the chip reads (BB1@7) and the legality check see the full
    played season; the like-for-like number is the GW8-38 segment delta.
    gap0-family arms that ran TC2 ZERO carry a TC2-equivalent captain multiple at the rule
    week (GW25 / GW24 / GW26) instead of the old BB2-week read, exactly as
    data/leakfix_logs/arms_table.py (the source of record for the four-config table)."""
    out, got = [], {}
    for p in sorted(ARMS.glob("armlog_*.parquet")):
        d = pd.read_parquet(p)
        season, base_arm = d["season"].iloc[0], d["arm"].iloc[0]
        precrosswalk = p.stem.endswith("_precrosswalk")
        arm = base_arm
        if "tc2_gw" in d.columns and int(d["tc2_gw"].iloc[0]) > 0:
            arm = f"{arm}_tc2"          # in-sim TC2 variant (armlog_*_tc2.parquet; the log's arm column is the base arm)
        if precrosswalk:
            arm = f"{arm}_precrosswalk"
        gap0 = base_arm in GAP0_FAMILY
        tag = season.replace("-", "_")
        start_gw = int(d["start_gw"].iloc[0])
        ref = _prefix_log(d["resume_from"].iloc[0] if "resume_from" in d.columns else None, tag)
        full = (pd.concat([ref[ref["gw"] < start_gw], d], ignore_index=True)
                if start_gw > 1 else d)
        assert int(d["final_total"].iloc[0]) == int(full["points"].sum()), \
            f"{p.name}: final_total != stitched points.sum()"
        full = full.set_index("gw")
        bb1, bb2 = int(d["bb1"].iloc[0]), int(d["bb2"].iloc[0])
        wc, fh, bb = chip_weeks(full)
        assert set(bb) == {bb1, bb2} and 2 in wc, f"{p.name}: not the reference chip schedule"
        tc_in = tc_weeks_insim(full)
        assert (tc_in == [] or arm.endswith("_tc2") or "_tc2_" in arm or arm in ("bonusdel_tc2", "leakfix_tc2")), \
            f"{p.name}: in-sim TC on a non-TC2 arm"
        if gap0:
            canon_wf, arm_wf = _gap0_frames(season, base_arm, precrosswalk)
            cp = cap_pred_gap0(season, base_arm, precrosswalk)
            reads = [("bench", bb1, int(full.loc[bb1, "bench_points"])),
                     ("bench", bb2, int(full.loc[bb2, "bench_points"]))]
            tc1_gw, tc1 = tc1_read(full, {2, bb1}, cp)
            reads.append(("TC1 cap", tc1_gw, tc1))
            if not tc_in:
                w = TC2_RULE_WEEK[season]
                reads.append(("TC2 cap (rule week; arm ran TC2 zero)", w, int(full.loc[w, "captain_bonus"])))
            wf = arm_wf or canon_wf
        else:
            reads = standing_reads(full, 2, [bb1, bb2], cap_pred_arm(season, arm))
            wf = (d["wf_file"].iloc[0] if (arm == "baseline8" or arm in ARM_WF_IN_DATA)
                  else "arms/" + d["wf_file"].iloc[0])
            if base_arm == "leakfix" and season == "2025-26":
                # built on the 2025-26 canonical BEFORE the crosswalk fix; that file is preserved as _precrosswalk
                wf = "walkforward_h6_2025_26_precrosswalk.parquet"
        if tc_in:
            # TC2 is IN the path (the simulator tripled the captain); listed for the record, never added.
            g = tc_in[0]
            reads.append(("TC2 in-sim", g, int(full.loc[g, "captain_bonus"]) // 2))
        extra = " ".join(x for x, c in (("PROPS", "props_active"),
                                        ("HORIZON_MINUTES", "horizon_minutes_active"))
                         if c in d.columns and bool(d[c].iloc[0]))
        if arm == "baseline8":
            flags = "like-for-like check of the resume mechanism -- reproduces the reference GW8-38 exactly"
        elif arm == "leakfix_tc2":
            flags = ("SUPERSEDED AS REFERENCE CELL (2026-08-27 -> 2026-08-28): leak fix only (e04fb72), MIP gap still 1e-4, "
                     "2025-26 on the pre-crosswalk canonical; figures 2343 / 2300 / 2190. Was the leak-fixed re-measurement of "
                     f"a committed fix. The reference of record is arms/armlog_{tag}_{REFERENCE_ARM[season]} ({EXPECT_REFERENCE_CHIP[season]})")
        elif arm == "leakfix":
            flags = "leak-fixed canonical, TC2 scored zero -- see the leakfix_tc2 row"
        elif arm == "bonusdel_tc2":
            flags = ("SUPERSEDED AS REFERENCE CELL (2026-08-27): built on the pre-leak-fix canonical (same-season "
                     f"Understat penalty join, KNOWN_ISSUES #19); the reference of record is arms/armlog_{tag}_{REFERENCE_ARM[season]} "
                     f"({EXPECT_REFERENCE_CHIP[season]}, 2026-08-28). Was: REFERENCE CELL OF RECORD 2026-08-26 (2251/2306/2268): "
                     "BONUS_MODE=delete + TC2 in-sim (p4 log section 15); path identical to arm=bonus_delete in all 38 gws")
        elif arm == "bonusdel":
            flags = "ADOPTED on component metrics (Logs/bonus_delete_prereg.md); TC2 scored zero here -- see the bonusdel_tc2 row"
        elif arm == REFERENCE_ARM.get(season) and gap0:
            flags = ("REFERENCE CELL OF RECORD (2026-08-28): horizon-minutes lever 1 on the gap0 convention (leak fix e04fb72, "
                     "solver gap 0 37ad782, fixed crosswalk a758541, BONUS_MODE=delete, TC2 " + ("in-sim" if tc_in else
                     "scored zero -> TC2-equivalent captain multiple at the rule week") + "). OBJECTION ON RECORD: this arm was "
                     "REJECTED on its pre-registered component test (minutes rank falls on both decision partitions at every step "
                     "k=1-5 in all three seasons, -0.014 to -0.049); this adoption cites season totals, which the standing rule "
                     "forbids, and horizon is the case that rule was written from (+109/+49/-84 on totals while worse where "
                     "decisions are made). Deliberate choice made with that evidence in view; see the index header")
        elif base_arm == "gap0" and not precrosswalk:
            flags = ("SHADOW configuration (2026-08-28). Was the reference candidate 2343 / 2306 / 2216 (gap0 baseline on the fixed "
                     "crosswalk) -- SUPERSEDED as reference by the horizon arm the same day, before any re-pointing; never the cell of record")
        elif precrosswalk:
            flags = ("SUPERSEDED (2026-08-28): 2025-26 built on the pre-crosswalk canonical / arm frame (Cherki 417 without an "
                     "Understat id); the gap0_tc2 pre-crosswalk candidate 2343 / 2306 / 2190 was never adopted")
        elif base_arm == "both_gap0":
            flags = ("PRODUCTION INTENT (2026-08-28): combined props + horizon minutes. EXPLORATORY figure; both levers failed "
                     "their pre-registered component tests; no 2023-24 cell (anytime-scorer market began autumn 2024)")
        elif base_arm == "props_gap0":
            flags = "EXPLORATORY -- props conditional spec on gap0; FAILED its pre-registered test (conditions 1-2); never evidence"
        else:
            flags = "NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence"
        if start_gw > 1:
            prefix = "arms/" + str(d["resume_from"].iloc[0]).split("@")[0] if gap0 else "the fslog reference cell"
            flags += (f"; starts GW{start_gw} from {prefix}'s GW{start_gw - 1} state "
                      f"(GW1-{start_gw - 1} stitched); like-for-like = GW{start_gw}-38 segment vs that baseline")
        sched = sched_str(wc, fh, bb) + (f" TC@{tc_in[0]} (in-sim)" if tc_in else "")
        r = row("arms", season, f"{ARM_LABEL[arm]} start=GW{start_gw}", 6, 0.45,
                sched, wf, gates_str(d, extra),
                int(full["points"].sum()), reads, f"arms/{p.name}", flags=flags,
                run=mtime(p), wc=wc, fh=fh, bb=bb, played=played_weeks(full), tc_insim=tc_in)
        got[(season, arm)] = r["chip"]
        out.append(r)
    for k, v in EXPECT_ARMS_CHIP.items():
        if k in got:
            assert got[k] == v, f"arms recompute drifted for {k}: {got[k]} != {v}"
    ref = {s_: got[(s_, a_)] for s_, a_ in REFERENCE_ARM.items() if (s_, a_) in got}
    assert ref == EXPECT_REFERENCE_CHIP, f"REFERENCE cells drifted: {ref} != {EXPECT_REFERENCE_CHIP}"
    print("gap0-family recompute:", {k: v for k, v in sorted(got.items()) if k[1].split('_')[0] in ("gap0", "hmin", "props", "both", "leakfix")})
    return out


def rows_references():
    refs = [
        ("2025-26", 3, 0.3, "walkforward_h6_2526_prefix.parquet (preserved)",
         "PRE-M3, pre-D1, pre-blend, pre-#15", "2026-08-11", 1984,
         "wildcard_and_determinism.md"),
        ("2025-26", 3, 0.3, "(availability=True rebuild, same era)",
         "pre-D1, pre-blend, pre-#15", "2026-08-13", 1938,
         "eval/walkforward.py docstring"),
        ("2025-26", 6, 0.85, "(D1 Variant B, static rates)",
         "pre-blend, pre-#15", "2026-08-17", 2028, "d1_log.md section 9"),
        ("2025-26", 6, 0.85, "(rate blend k=8, pre-#15 DC base rates)",
         "pre-#15", "2026-08-18", 2060, "rate_blend_log.md section 7"),
    ]
    out = []
    for season, H, decay, wf, fam, built, total, src in refs:
        r = row("references", season, fam, H, decay, "--", wf, "--", total,
                [], src, flags="lineage only -- comparable to NOTHING",
                run=built)
        out.append(r)
    return out


SECTIONS = [
    ("sweep", "SWEEP -- H x decay grid, no chips (data/sweep)",
     "54 cells: {base, synth} x 3 seasons x H {3,4,6} x decay {.3,.45,.6}. "
     "synth rows ride the _synth walkforward (D4, closed NOT adopted) and "
     "are flagged superseded."),
    ("chips", "CHIPS ERA -- P4 structural chip study (data/chips)",
     "H=6; decay 0.85 unless the config name says _d60/_d45. Chip-inclusive "
     "= path + bench@BB where a BB was scheduled. The pkg2h / phase-2 "
     "convention ALSO read capbonus@BB (TC2) on the same week -- that read "
     "is an illegal play (one chip per gameweek) and is DROPPED, shown "
     "struck through (corrected 2026-08-24). wc/fh-only configs have no "
     "exogenous reads. The 3 pkg_d45 rows are newly indexed (they postdate "
     "the old index)."),
    ("p1", "P1 OPENING ARMS -- no chips (data/p1/p1log_*)",
     "arm=base is the no-chip baseline of record for the grids below; "
     "arm=p1 flips OPENING_HORIZON_ACTIVE, arm=p2 OPENING_ROBUST_ACTIVE "
     "(both CLOSED, not adopted)."),
    ("wcgrid", "WC1 x OPENING GRID -- wildcard only (data/p1/wclog_*)",
     "One WC at the named week, nothing else. Chip-inclusive == path "
     "(a wildcard changes the path itself; there is nothing to add)."),
    ("fullsystem", "FULL SYSTEM -- all chips (data/p1/fslog_*)",
     "WC1 as named, WC2/FH2 in-sim, BB1+BB2 scheduled (bench-aware), TC1 "
     "exogenous read. The P4 TC2 read (captain bonus at the BB2 week) is "
     "DROPPED as an illegal play and shown struck through (corrected "
     "2026-08-24; p4 log section 12c). The system-as-configured cells are "
     "opening=base wc1=2 (WC1 rule of record GW2-3, p4 log section 12b)."),
    ("p3", "P3 EARLY-HIT GRID (data/p1/p3log_*)",
     "Full-system config + EARLY_HIT_DISCOUNT_ACTIVE at the named bar. "
     "Measured and DECLINED; bar=4 references are the fslog rows above. "
     "Same TC2@BB2 drop as the full system."),
    ("p5", "P5 OPTIMIZER-WINS ARMS (data/p1/p5log_*)",
     "Full-system wc2 config + bench-order / XI-tiebreak gates. Measured "
     "and DECLINED (noise-free paired paths). Same TC2@BB2 drop as the full "
     "system."),
    ("oracle", "TEAM-NEWS ORACLE -- DELIBERATE LEAKAGE (data/teamnews)",
     "oracle_minutes_active=True: realized minutes injected into "
     "predictions. These rows are MEASUREMENTS of an upper bound, never "
     "baselines, never adoptable, comparable only to their reference cell "
     "(fslog base_wc2). Same TC2@BB2 drop as the full system."),
    ("arms", "ARMS -- 2026-08-26/27/28 arms incl. THE REFERENCE CELLS OF RECORD = hmin_gap0 (data/arms/armlog_*)",
     "Full-system wc2 config with a feature applied in-process for the season "
     "figure only: props (conditional spec, w=0.75 m=1.396; PROPS_HOOK rests "
     "None) and/or horizon minutes lever 1 (HORIZON_MINUTES_ACTIVE rests "
     "False). BOTH FAILED their pre-registered component tests "
     "(Logs/props_prereg.md CLOSE-OUT; Logs/horizon_minutes_log.md section 5); "
     "these totals were never permitted to overturn that, and they disagree "
     "with the component read in sign (Logs/instrument_b_log.md, the standing "
     "illustration). 2024-25 rows start at GW8 from the reference cell's GW7 "
     "state (prefix stitched); their like-for-like number is the GW8-38 "
     "segment delta in Logs/props_season_log.md. Same TC2@BB2 drop as the "
     "full system. ALSO HERE (2026-08-26): penfix / cal / cal_penfix / bonusow "
     "(all NOT adopted), bonusdel (ADOPTED, TC2 scored zero) and "
     "**bonusdel_tc2 -- THE REFERENCE CELLS OF RECORD** (bonus deleted, TC2 "
     "scheduled in-sim on the 12c(ii) week: GW25 / GW24 / GW26; captain = the "
     "MIP's cap at that deadline; path identical to bonusdel in every gameweek, "
     "so the TC2 read is exactly the extra captain multiple, +10 / +29 / +7). "
     "Their `TC2 in-sim` read is listed for the record and NOT added -- it is "
     "already inside the path total. ALSO HERE (2026-08-27/28), the gap0 family: "
     "leakfix / leakfix_tc2 (leak fix only, SUPERSEDED), gap0_tc2 (leak fix + solver "
     "gap 0 + fixed crosswalk = the SHADOW configuration), hmin_gap0 / hmin_gap0_tc2 "
     "(**THE REFERENCE CELLS OF RECORD 2026-08-28 -- with the objection recorded in the "
     "header**), props_gap0 (exploratory), both_gap0 (PRODUCTION INTENT), and the "
     "2025-26 _precrosswalk rows (SUPERSEDED). gap0-family arms that ran TC2 zero carry "
     "a TC2-equivalent captain multiple at the rule week (GW25/24/26) instead of the "
     "old BB2-week read, exactly as data/leakfix_logs/arms_table.py."),
    ("references", "REFERENCES -- pre-canonical lineage figures",
     "Retained for lineage only."),
]

HEADER = """# Season totals index -- every simulated season total, one place

Generated {today} by eval/build_season_totals_index.py. Covers ALL simlogs
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

**REFERENCE CELLS OF RECORD (moved 2026-08-28) -- and the objection, on the record.**
The reference cells are now the **horizon-minutes arm on the gap0 convention**:
penalty-join leak fix (e04fb72) + solver MIP gap 0 (37ad782) + fixed crosswalk
(a758541), `BONUS_MODE = "delete"`, all chips, WC1 @ GW2, TC2 in-sim on the 12c(ii)
week (2025-26) or the TC2-equivalent captain multiple at that week where the arm ran
TC2 zero (2023-24, 2024-25). **Reference cells: 2023-24 2425 / 2024-25 2335 /
2025-26 2266** (paths ex-TC2 2386 / 2254 / 2216; `data/arms/armlog_*_hmin_gap0[_tc2]`).

*Objection, recorded here and not only in the commit message:* the horizon-minutes
arm was **REJECTED on its pre-registered component test** -- its minutes rank falls on
both decision partitions at every step k = 1-5 in all three seasons (-0.014 to -0.049;
`Logs/horizon_minutes_log.md` section 5). This adoption **cites season totals, which the
standing rule forbids**, and horizon is the specific case that rule was written from
(+109 / +49 / -84 on totals while measurably worse where decisions are made;
`Logs/instrument_b_log.md`). The decomposition (`data/leakfix_logs/decomp_all_cells.txt`)
found four comparable (independent) decisions across three seasons netting +62 against
+224 of path gain; no mechanism was identified -- the remainder is path divergence.
This was a deliberate choice made with that evidence in view. **The standing rule still
applies to everything else: no future adoption decision may cite season totals.**

*Superseded as reference cells, dated, retained and flagged, never deleted:*
2251 / 2306 / 2268 (bonusdel_tc2, pre-fix canonicals, 2026-08-26);
2343 / 2300 / 2190 (leakfix_tc2, leak fix only, MIP gap 1e-4, 2026-08-27);
2343 / 2306 / 2190 (gap0_tc2 on the pre-crosswalk 2025-26 canonical, 2026-08-27);
2343 / 2306 / 2216 (gap0_tc2 on the fixed crosswalk -- the previous candidate,
2026-08-28, never adopted; now the SHADOW row). Note that 2024-25's 2306 was
numerically unchanged from bonusdel_tc2 through gap0_tc2 **by coincidence, not
stability**: the leak fix moved its path (2249 -> 2233, leakfix_tc2 read 2300) and the
zero-gap solver moved it back through a single GW3 action (2248 -> 2306); the
crosswalk fix did not touch 2024-25 at all.

*Configuration roles (2026-08-28):* **reference cells = horizon** (2425 / 2335 / 2266);
**production intent = combined** (props + horizon), figures 2459 / 2264 -- two seasons
only, no 2023-24 cell because the anytime-scorer market began autumn 2024;
**shadow = baseline gap0** (2343 / 2306 / 2216). The mismatch is explicit: **the figures
of record describe horizon, not the production configuration.** Before combined can pick
anything live it needs a live props puller inside each deadline window, a per-gameweek
crosswalk pass with manual name mapping (162 and 57 manual entries historically, ~150
unmatched rows per season), an incremental consensus builder and a paid odds plan --
none of which exists; props degrades SILENTLY to horizon-only when odds are missing, so
a per-deadline coverage flag is required before combined runs live. The shadow
comparison has no statistical power: paired per-gameweek sd ~13, detectable difference
6.8 pts/gw at n = 15 and 4.3 at n = 38, against historical config differences of 0 to
+4 pts/gw; the 15-gameweek checkpoint is a mechanics review, not a verdict.

**REFERENCE CELLS OF RECORD (moved 2026-08-26; SUPERSEDED 2026-08-28, kept for lineage).** The system as configured was
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
cells of record (arms hmin_gap0 -> 2425/2335/2266, plus every gap0-family and
superseded arm figure) and the p1 baselines (2204/2362/2032); generation FAILS on drift. That check is
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
({stale}) are marked SUPERSEDED -- retained, never deleted, comparable only
within their own family.

**Walkforward provenance key** (stamps read from the files themselves):

{wfkey}
"""

FOOTER = """
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
10. **gap0 family** (gap0_tc2 / props_gap0 / hmin_gap0 / both_gap0, 2026-08-27/28):
   comparable only to each other within a season -- the four-config table of
   `data/leakfix_logs/arms_table_crosswalk.txt`; 2024-25 arms by their GW8-38
   segment vs gap0_tc2. hmin_gap0 rows are THE REFERENCE CELLS OF RECORD
   (2026-08-28, objection in the header); gap0_tc2 is the SHADOW row; both_gap0 the
   PRODUCTION-INTENT row. The bonusdel_tc2 / leakfix_tc2 / _precrosswalk rows are
   superseded lineage.
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
- MOVED 2026-08-28: the reference cells are the arms hmin_gap0 rows
  (2425/2335/2266) -- the horizon-minutes arm, REJECTED on its component test;
  adopted on season totals against the standing rule, deliberately, objection
  recorded in the header. Superseded, dated: 2251/2306/2268 (2026-08-26),
  2343/2300/2190 (2026-08-27, leak fix only), 2343/2306/2190 (2026-08-27,
  gap0 pre-crosswalk), 2343/2306/2216 (2026-08-28, gap0 on the fixed crosswalk,
  the previous candidate -- now the SHADOW row). The standing rule still applies
  to everything else.
- Oracle rows are deliberate-leakage instruments (oracle_minutes_active
  stamp). NEVER adopt, never baseline.
- The four reference figures are retained for lineage only.
- One historical cross-provenance comparison was ATTEMPTED and caught before
  measurement: D4 Phase 2's first 2025-26 synth build used the wrong writer
  (stamps differed); rebuilt before any number was read (overnight log,
  stage 2).
- The 3 chips-era pkg_d45 rows are newly indexed here; the pre-2026-08-24
  generator would have mislabelled their decay as 0.85.
"""


def render(rows):
    lines = []
    counts = {}
    for sec_key, title, note in SECTIONS:
        sec = [r for r in rows if r["section"] == sec_key]
        counts[sec_key] = len(sec)
        if not sec:
            continue
        sec.sort(key=lambda r: (r["season"], r["config"], r["H"], r["decay"]))
        lines += [f"## {title}", "", note, "",
                  "| season | config | H | decay | chips scheduled | "
                  "path total | chip-incl total | chip reads | vs avg "
                  "(claimed) | vs avg (fplcache) | wf file | wf stamps | "
                  "sim gates | run | flags | source |",
                  "|" + "---|" * 16]
        for r in sec:
            stale = STALE_RE.search(r["wf"])
            flags = r["flags"]
            if stale:
                flags = (flags + "; " if flags else "") + \
                    f"SUPERSEDED (stale wf suffix _{stale.group(1)})"
            try:
                fam, compact, _ = wf_stamps(r["wf"])
            except FileNotFoundError:
                fam, compact = "(file not on disk)", "?"
            if r["wf"].startswith("("):        # reference pseudo-entries
                fam, compact = r["config"], "?"
            if r["recomputed"]:
                parts = []
                for lbl, gw, v, dropped in r["reads"]:
                    s = f"{lbl}@GW{gw}{v:+d}"
                    parts.append(f"~~{s}~~ DROPPED ({dropped})" if dropped
                                 else s)
                reads = " ".join(parts)
                chip = f"**{r['chip']}** (r)"
            else:
                reads = "--"
                chip = f"= path {r['chip']}"
            lines.append(
                f"| {r['season']} | {r['config']} | {r['H']} | {r['decay']} "
                f"| {r['sched']} | **{r['path']}** | {chip} | {reads} | "
                f"{r['chip'] - AVG_CLAIMED[r['season']]:+d} | "
                f"{r['chip'] - AVG_ONDISK[r['season']]:+d} | {r['wf']} | "
                f"{compact} | {r['gates']} | {r['run']} | {flags or '--'} | "
                f"{r['source']} |")
        lines.append("")
    return lines, counts


def main():
    rows = (rows_sweep() + rows_chips() + rows_p1() + rows_wcgrid()
            + rows_fullsystem() + rows_p3() + rows_p5() + rows_oracle()
            + rows_arms() + rows_references())

    # validation: p1 baselines' PATH totals are the figures of record
    p1_base = {r["season"]: r["path"] for r in rows
               if r["section"] == "p1" and r["config"] == "arm=base"}
    assert p1_base == EXPECT_P1_BASE_PATH, \
        f"p1 baseline path totals drifted: {p1_base} != {EXPECT_P1_BASE_PATH}"

    body, counts = render(rows)

    wfkey = ["| wf file | " + " | ".join(STAMPS) + " |",
             "|" + "---|" * (len(STAMPS) + 1)]
    for name, (fam, _, full) in sorted(_wf_cache.items()):
        wfkey.append(f"| {name} ({fam}) | " + " | ".join(
            str(full.get(c, "?")) for c in STAMPS) + " |")

    text = HEADER.format(today=dt.date.today(),
                         stale=", ".join("_" + s for s in STALE_SUFFIXES),
                         wfkey="\n".join(wfkey)) \
        + "\n".join(body) + FOOTER
    out = REPO / "Logs" / "season_totals_index.md"
    out.write_text(text, encoding="utf-8")
    total = sum(counts.values())
    n_drop = sum(1 for r in rows if any(x[3] for x in r["reads"]))
    print(f"{total} rows -> {out}   (TC2@BB2 read dropped on {n_drop} rows; "
          f"every row passed check_chip_schedule)")
    for k, v in counts.items():
        print(f"  {k:12s} {v}")


if __name__ == "__main__":
    main()
