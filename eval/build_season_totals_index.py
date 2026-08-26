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
# Self-check (drift only -- circular by construction, kept for that purpose):
# the recompute chain is validated against the corrected reference figures
# (fslog base_wc2 chip-inclusive == 2296/2294/2206) and the p1 baselines'
# path totals (2204/2362/2032) before writing.

import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
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
                  "synth", "baseline", "d1cards", "av", "odds2", "dgwonly"]
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
                    ("2025-26", "hmin"): 2122, ("2025-26", "both"): 2134}
ARM_LABEL = {"baseline8": "baseline re-run", "props": "arm=props",
             "hmin": "arm=horizon_minutes", "both": "arm=props+horizon_minutes"}

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
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
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
    if "triple_captain" in d.columns:
        assert not d["triple_captain"].any(), \
            "in-sim TC week found -- TC is exogenous by convention"
    return wc, fh, bb


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
        reads, source, flags="", run=None, wc=(), fh=(), bb=(), played=None):
    reads = drop_colliding_tc(reads, list(bb))
    kept = [r for r in reads if not r[3]]
    tc_weeks = [gw for lbl, gw, _, _ in kept if lbl.startswith("TC") and gw]
    # STRUCTURAL legality check on the effective schedule -- independent of
    # any total. This is what the old convention never had.
    check_chip_schedule({"wildcard": list(wc), "free_hit": list(fh),
                         "bench_boost": list(bb), "triple_captain": tc_weeks},
                        played_gws=played, source=source)
    if any(r[3] for r in reads):
        flags = (flags + "; " if flags else "") + \
            "TC2@BB2 read DROPPED (illegal play; corrected 2026-08-24)"
    add = sum(v for _, _, v, _ in kept)
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
        reads = standing_reads(d, wc1, [bb1, bb2], cap_pred(season))
        r = row("fullsystem", season,
                f"opening={d['opening'].iloc[0]} wc1={wc1}", 6, 0.45,
                sched_str(wc, fh, bb), d["wf_file"].iloc[0], gates_str(d),
                int(d["final_total"].iloc[0]), reads,
                f"p1/{p.name}", run=mtime(p),
                wc=wc, fh=fh, bb=bb, played=played_weeks(d))
        if d["opening"].iloc[0] == "base" and wc1 == 2:
            fs_chip[season] = r["chip"]
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
    p = ARMS / f"walkforward_h6_{tag}_{arm}.parquet"
    if arm in ("props", "both") and p.exists():
        wf = pd.read_parquet(p, columns=["cutoff", "gw", "name", "e_points"])
        own = wf[wf["cutoff"] == wf["gw"]]
        return {(int(g), n): float(v or 0) for g, n, v in
                zip(own["gw"], own["name"], own["e_points"])}
    return cap_pred(season)


def rows_arms():
    """Closed non-adoptions. 2024-25 arms start at GW8 from the reference
    cell's GW7 state: the reference's GW1-7 rows are stitched in front so the
    chip reads (BB1@7) and the legality check see the full played season; the
    like-for-like number is the GW8-38 segment delta (props_season_log.md)."""
    out, got = [], {}
    for p in sorted(ARMS.glob("armlog_*.parquet")):
        d = pd.read_parquet(p)
        season, arm = d["season"].iloc[0], d["arm"].iloc[0]
        tag = season.replace("-", "_")
        start_gw = int(d["start_gw"].iloc[0])
        ref = pd.read_parquet(P1 / f"fslog_{tag}_base_wc2.parquet")
        full = (pd.concat([ref[ref["gw"] < start_gw], d], ignore_index=True)
                if start_gw > 1 else d)
        assert int(d["final_total"].iloc[0]) == int(full["points"].sum()), \
            f"{p.name}: final_total != stitched points.sum()"
        full = full.set_index("gw")
        bb1, bb2 = int(d["bb1"].iloc[0]), int(d["bb2"].iloc[0])
        wc, fh, bb = chip_weeks(full)
        assert set(bb) == {bb1, bb2} and 2 in wc, f"{p.name}: not the reference chip schedule"
        reads = standing_reads(full, 2, [bb1, bb2], cap_pred_arm(season, arm))
        wf = d["wf_file"].iloc[0] if arm == "baseline8" else "arms/" + d["wf_file"].iloc[0]
        extra = " ".join(x for x, c in (("PROPS", "props_active"),
                                        ("HORIZON_MINUTES", "horizon_minutes_active"))
                         if c in d.columns and bool(d[c].iloc[0]))
        if arm == "baseline8":
            flags = "like-for-like check of the resume mechanism -- reproduces the reference GW8-38 exactly"
        else:
            flags = "NOT ADOPTED -- failed its pre-registered component test; season figure only, never evidence"
        if start_gw > 1:
            flags += (f"; starts GW{start_gw} from the reference cell's GW{start_gw - 1} state "
                      f"(GW1-{start_gw - 1} stitched = reference); like-for-like = GW{start_gw}-38 "
                      f"segment vs reference")
        r = row("arms", season, f"{ARM_LABEL[arm]} start=GW{start_gw}", 6, 0.45,
                sched_str(wc, fh, bb), wf, gates_str(d, extra),
                int(full["points"].sum()), reads, f"arms/{p.name}", flags=flags,
                run=mtime(p), wc=wc, fh=fh, bb=bb, played=played_weeks(full))
        got[(season, arm)] = r["chip"]
        out.append(r)
    for k, v in EXPECT_ARMS_CHIP.items():
        if k in got:
            assert got[k] == v, f"arms recompute drifted for {k}: {got[k]} != {v}"
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
    ("arms", "ARMS -- props / horizon minutes, CLOSED NON-ADOPTIONS (data/arms/armlog_*)",
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
     "full system."),
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
(the simulator scores no chip points; asserted == points.sum() for every
file). Every chip-inclusive figure here is RECOMPUTED by the family's
measure-script-of-record convention minus the illegal read (see the
generator's docstring for the exact per-family rules). Recomputed values are
marked **(r)** and decomposed in the `chip reads` column; `= path` means no
exogenous chips were scheduled, so the two totals are identical by
construction. The recompute chain is drift-checked at generation time against
the corrected reference figures (fslog base_wc2 -> 2296/2294/2206) and the
p1 baselines (2204/2362/2032); generation FAILS on drift. That check is
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
9. **Arms rows**: comparable ONLY to fslog base_wc2 (their reference); the
   2024-25 rows by their GW8-38 segment (props_season_log.md), never by the
   stitched total's margin. Closed non-adoptions; never baselines.
10. Nothing else. Cross-H, cross-decay, cross-season, cross-family and every
   REFERENCE row: NOT comparable.

## Explicit flags

- Every chip-inclusive figure in this index is recomputed (marked (r)); no
  log family stores one. The reads are decomposed per row so a recompute
  error is visible, not quiet.
- CORRECTED 2026-08-24: the TC2 read at the BB2 week was an illegal play and
  is dropped on every affected row (struck through, flagged). Figures quoted
  from this index before that date carry the illegal read; the p4 log,
  the closing position and the 2026-08-23 handoff quote 2299/2301/2219 --
  read those as 2296/2294/2206.
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
