"""Measurement for the season-figure arms (eval/run_arms_full_system.py): props on (candidate; conditional spec w = 0.75, m = 1.396), horizon minutes on (lever 1 refit -- FAILED its component test, curiosity only), both. Read-only; tolerates missing runs.

Per (season, arm): PATH total and CHIP-INCLUSIVE total (path + bench@BB1 + bench@BB2 + captain_bonus@TC1; TC2 played but scored ZERO, the deliberate understatement of the 2026-08-24 collision fix -- the read exists in the log and is shown struck, never added); chip legality asserted on the effective schedule; margin over the FPL average manager (2003 / 2008 / 1895); the paired W = 3 path deltas at the chip anchors vs the reference cell (Instrument A -- the honest policy read; post-first-anchor windows are not path-controlled and overlap, never add them); the amendment-3 partial-double count from the arm frame's sidecar. 2024-25 arms start at GW8 from the reference cell's GW7 state: the full-season margin is NOT comparable and the GW8-38 segment delta vs the reference is the like-for-like number; the stitched full-season figure (common GW1-7 prefix + segment) is shown with that said.

Usage: uv run python eval/measure_arms_full_system.py [--append-log]
"""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad")); sys.path.insert(0, str(REPO / "eval"))
from chip_legality import check_chip_schedule  # noqa: E402
import measure_full_system as mfs  # noqa: E402  (avg_manager, load, window, AVG_SUM_EXPECT)

ARMS = REPO / "data" / "arms"
P1 = REPO / "data" / "p1"
SEASONS = ["2023-24", "2024-25", "2025-26"]
ARM_ORDER = ["baseline8", "props", "hmin", "both", "penfix", "cal", "cal_penfix"]
LABEL = {"baseline8": "baseline re-run from GW8 (like-for-like check)",
         "cal": "E. top-end calibration alone (Logs/topend_calibration_prereg.md) -- season figure only",
         "cal_penfix": "F. top-end calibration + penalty fix -- season figure only",
         "penfix": "D. penalty-term correctness fix (Logs/penalty_fix_prereg.md) -- season figure only, adjudicated on the component read",
         "props": "A. props on (candidate; conditional spec)",
         "hmin": "B. horizon minutes on -- FAILED component test, curiosity only",
         "both": "C. props + horizon minutes -- contains a failed component, curiosity only"}
CAVEAT = ("Path noise is sd ~60 for a single draw and ~85 paired; the same endpoint could not distinguish a model shrunk 75% "
          "toward the positional mean; 2024-25's baseline is a 97th-percentile draw carrying a ~+169 luck premium. These figures "
          "are the user-facing number -- they are NOT adoption evidence and no adoption decision may cite them.")


def cap_pred_for(season):
    tag = season.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet", columns=["cutoff", "gw", "element", "name", "e_points"])
    own = wf[wf["cutoff"] == wf["gw"]]
    return {(int(r.gw), r.name): float(r.e_points or 0) for r in own.itertuples()}


def cap_pred_arm(season, arm):
    """TC1 is picked on the ARM's own predictions where the arm changes step 0 (props); the refit does not touch step 0."""
    tag = season.replace("-", "_")
    p = (REPO / "data" / f"walkforward_h6_{tag}_{arm}.parquet") if arm in ("penfix", "cal", "cal_penfix") else (ARMS / f"walkforward_h6_{tag}_{arm}.parquet")
    if arm in ("props", "both", "penfix", "cal", "cal_penfix") and p.exists():
        wf = pd.read_parquet(p, columns=["cutoff", "gw", "element", "name", "e_points"])
        own = wf[wf["cutoff"] == wf["gw"]]
        return {(int(r.gw), r.name): float(r.e_points or 0) for r in own.itertuples()}
    return None


def chip_reads(d, full, cap_pred, wc1, wc2, fh2, bb1, bb2, start_gw):
    """d: this run's rows (indexed by gw); full: stitched full-season rows (prefix + run)."""
    bench_bb1 = int(full.loc[bb1, "bench_points"]); bench_bb2 = int(full.loc[bb2, "bench_points"])
    chipweeks = {wc1, bb1}
    tc1_gw, tc1_pred = None, -1
    for gw in range(1, 20):
        if gw in chipweeks or gw not in full.index:
            continue
        v = cap_pred.get((gw, full.loc[gw, "captain"]), 0)
        if v > tc1_pred:
            tc1_gw, tc1_pred = gw, v
    tc1 = int(full.loc[tc1_gw, "captain_bonus"]) if tc1_gw else 0
    tc2_zero = int(full.loc[bb2, "captain_bonus"])
    check_chip_schedule({"wildcard": [wc1, wc2], "free_hit": [fh2], "bench_boost": [bb1, bb2], "triple_captain": [g for g in (tc1_gw,) if g]},
                        played_gws=set(int(g) for g in full.index), source="arm")
    return bench_bb1, bench_bb2, tc1_gw, tc1, tc2_zero


def main():
    append = "--append-log" in sys.argv
    md = []
    P = md.append
    for season in SEASONS:
        tag = season.replace("-", "_")
        avg = mfs.avg_manager(season)
        ref = mfs.load(P1 / f"fslog_{tag}_base_wc2.parquet")
        wc1, wc2, fh2, bb1, bb2 = 2, int(ref["wc2"].iloc[0]), int(ref["fh2"].iloc[0]), int(ref["bb1"].iloc[0]), int(ref["bb2"].iloc[0])
        cap_ref = cap_pred_for(season)
        rb1, rb2, rtc1_gw, rtc1, rtc2 = chip_reads(ref, ref, cap_ref, wc1, wc2, fh2, bb1, bb2, 1)
        ref_path = int(ref["final_total"].iloc[0]); ref_chip = ref_path + rb1 + rb2 + rtc1
        print("=" * 110); print(f"SEASON {season}   reference cell fslog_{tag}_base_wc2: path {ref_path}, chip-inclusive {ref_chip} "
                                f"(BB1@{bb1} +{rb1}, BB2@{bb2} +{rb2}, TC1@GW{rtc1_gw} +{rtc1}, TC2@{bb2} scored ZERO [read +{rtc2} struck]); "
                                f"margin vs avg manager {ref_chip - mfs.AVG_SUM_EXPECT[season]:+d}"); print("=" * 110)
        P(f"\n### {season}\n")
        P(f"Reference cell `fslog_{tag}_base_wc2`: path **{ref_path}**, chip-inclusive **{ref_chip}** (BB1@GW{bb1} +{rb1}, BB2@GW{bb2} +{rb2}, TC1@GW{rtc1_gw} +{rtc1}, "
          f"TC2@GW{bb2} scored ZERO — read ~~+{rtc2}~~ struck), margin vs average manager {ref_chip - mfs.AVG_SUM_EXPECT[season]:+d}.\n")
        P("| arm | start | path total | Δ path vs ref | chip reads (BB1 / BB2 / TC1 / ~~TC2~~) | chip-inclusive | Δ vs ref | margin vs avg mgr | segment (GW-start–38) & Δ | partial doubles excluded | legality |")
        P("|---|---|---|---|---|---|---|---|---|---|---|")
        for arm in ARM_ORDER:
            p = ARMS / f"armlog_{tag}_{arm}.parquet"
            if not p.exists():
                continue
            d = mfs.load(p)
            start_gw = int(d["start_gw"].iloc[0])
            full = pd.concat([ref.loc[[g for g in ref.index if g < start_gw]], d]) if start_gw > 1 else d
            cap = cap_pred_arm(season, arm) or cap_ref
            b1, b2, tc1_gw, tc1, tc2 = chip_reads(d, full, cap, wc1, wc2, fh2, bb1, bb2, start_gw)
            path = int(full["points"].sum()); chip = path + b1 + b2 + tc1
            assert path == int(d["final_total"].iloc[0]), "stitched path != simulator total"
            seg = int(d["points"].sum()); seg_ref = int(ref.loc[start_gw:, "points"].sum())
            seg_avg = sum(avg[g] for g in range(start_gw, 39))
            side_p = ARMS / f"walkforward_h6_{tag}_{arm}.json"
            side = json.loads(side_p.read_text(encoding="utf-8")) if side_p.exists() else None
            n_partial = side["props"]["partial_doubles_excluded"] if side and side.get("props") else ("n/a" if arm in ("hmin", "baseline8", "penfix", "cal", "cal_penfix") else "?")
            n_over = side["props"]["overridden_player_fixtures"] if side and side.get("props") else None
            anchors = [("WC2", wc2), ("FH2", fh2), ("BB2", bb2)] + ([("BB1", bb1)] if bb1 >= start_gw else []) + ([("entry", start_gw)] if start_gw > 1 else [("WC1", wc1)])
            aw = {lbl: mfs.window(d, ref, a_) for lbl, a_ in sorted(anchors, key=lambda t: t[1])}
            repro = d["reproduces_reference_segment"].iloc[0] if "reproduces_reference_segment" in d.columns else None
            margin_note = (f"{chip - mfs.AVG_SUM_EXPECT[season]:+d} (NOT comparable: GW1–{start_gw - 1} is the reference's own path)" if start_gw > 1
                           else f"{chip - mfs.AVG_SUM_EXPECT[season]:+d}")
            seg_note = (f"GW{start_gw}–38: {seg} vs ref {seg_ref} → **{seg - seg_ref:+d}**; vs avg mgr over the same weeks {seg - seg_avg:+d}" if start_gw > 1 else "full season")
            print(f"\n  [{arm}] {LABEL[arm]}" + (f"  -- resumed baseline {'REPRODUCES' if repro else 'DOES NOT REPRODUCE'} the reference GW{start_gw}-38" if repro is not None else ""))
            print(f"    start GW{start_gw}; path {path} ({path - ref_path:+d} vs ref); chip reads BB1 +{b1} BB2 +{b2} TC1@GW{tc1_gw} +{tc1} TC2@GW{bb2} ZERO [+{tc2} struck] -> chip-inclusive {chip} ({chip - ref_chip:+d} vs ref); "
                  f"margin vs avg manager {margin_note}")
            print(f"    {seg_note}; partial doubles excluded (amendment 3): {n_partial}" + (f"; player-fixtures overridden {n_over:,}" if n_over is not None else ""))
            print(f"    W=3 paired path deltas vs reference at anchors (Instrument A; post-first-anchor windows NOT path-controlled; overlapping -- never add): "
                  + "  ".join(f"{k}@{dict(anchors)[k]} {v:+d}" for k, v in aw.items()))
            P(f"| {LABEL[arm]}{' — **reproduces reference GW8–38: ' + str(bool(repro)) + '**' if repro is not None else ''} | GW{start_gw} | {path} | {path - ref_path:+d} | +{b1} / +{b2} / +{tc1} (GW{tc1_gw}) / ~~+{tc2}~~ ZERO | **{chip}** | {chip - ref_chip:+d} | {margin_note} | {seg_note} | {n_partial} | OK |")
            P(f"| ↳ W=3 paired deltas vs reference (Instrument A): " + "; ".join(f"{k}@GW{dict(anchors)[k]} {v:+d}" for k, v in aw.items()) + " |  |  |  |  |  |  |  |  |  |  |")
        P(f"\n*Caveat (attached without exception):* {CAVEAT}")
    print("\n" + CAVEAT)
    if append:
        log = REPO / "Logs" / "props_season_log.md"
        cur = log.read_text(encoding="utf-8") if log.exists() else ""
        marker = "## Results (generated by eval/measure_arms_full_system.py)"
        if marker in cur:
            cur = cur.split(marker)[0].rstrip("\n")
        log.write_text(cur.rstrip("\n") + "\n\n" + marker + "\n" + "\n".join(md) + "\n", encoding="utf-8")
        print(f"\nresults section written to {log}")


if __name__ == "__main__":
    main()
