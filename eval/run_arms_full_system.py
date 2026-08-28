"""Full-system season runs for the ARMS (props on / horizon minutes on / both) under the current adopted config -- opening=base, WC1 @ GW2, WC2 / FH2 / BB1 / BB2 at the rules-of-record weeks of eval/run_full_system.py, H = 6, decay 0.45 -- on the arm walk-forward frames from eval/walkforward_arms.py. 2024-25 arms START AT GW8 (no props before GW8) from the reference cell's OWN squad state at the end of GW7, reconstructed by replaying data/p1/fslog_2024_25_base_wc2.parquet and asserted against it at every gameweek (elements, bank, free transfers, total). `baseline8` re-runs the reference config itself from that state on the canonical frame, which must reproduce the reference log's GW8-38 exactly -- the like-for-like check. Chip legality is asserted on every arm's effective schedule. One parquet per run (armlog_*), atomic, skip-if-exists.

Usage: uv run python eval/run_arms_full_system.py --season 2024-25 --arm props
       arms: baseline8 (2024-25 only) | props | hmin | both
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
import simulator  # noqa: E402
from squad_state import SquadState, STARTING_BUDGET  # noqa: E402
from chip_legality import check_chip_schedule  # noqa: E402
import run_full_system as rfs  # noqa: E402  (WC2, FH2, BB2, BB1, H, DECAY)

sys.path.insert(0, str(REPO / "eval"))
ARMS_DIR = REPO / "data" / "arms"
P1 = REPO / "data" / "p1"
OPENING = "base"
WC1 = 2
START_GW = {"2024-25": 8}          # props coverage begins 2024-25 GW8; other seasons run in full


def replay_state(log, df, through_gw):
    """Rebuild the SquadState at the END of `through_gw` from a decision log by
    replaying its transfers on the canonical frame's prices; asserted against
    the log at every gameweek."""
    log = log.set_index("gw")
    els = json.loads(log.loc[1, "elements"]) if isinstance(log.loc[1, "elements"], str) else list(log.loc[1, "elements"])
    pool1 = simulator.gw_slice(df, 1, cutoff=1)
    start = pool1[pool1["element"].isin(els)][["element", "name", "position", "team", "value"]].copy()
    assert len(start) == 15, f"GW1 squad has {len(start)} rows in the pool"
    start["purchase_price"] = start["value"].astype(int)
    state = SquadState(start, bank=STARTING_BUDGET - int(start["purchase_price"].sum()), free_transfers=1)
    for gw in range(1, through_gw + 1):
        row = log.loc[gw]
        pool = simulator.gw_slice(df, gw, cutoff=gw)
        prices = dict(zip(pool["element"], pool["value"]))
        tr = row["all_transfers"]; tr = json.loads(tr) if isinstance(tr, str) else list(tr)
        pairs = [(int(o), int(i)) for o, i in tr]
        assert not bool(row["free_hit"]), f"GW{gw}: replay through a Free Hit week is not supported"
        if pairs:
            in_rows = {b: pool[pool["element"] == b].iloc[0] for _, b in pairs}
            state.make_transfers(pairs, in_rows, prices)
        if not bool(row["wildcard"]):
            state.spend_transfers(len(pairs))
        want = json.loads(row["elements"]) if isinstance(row["elements"], str) else list(row["elements"])
        assert set(state.elements) == set(int(e) for e in want), f"GW{gw}: replayed squad != log"
        assert state.bank == int(row["bank"]), f"GW{gw}: replayed bank {state.bank} != log {row['bank']}"
        state.end_gameweek(int(row["points"]))
        assert state.free_transfers == int(row["free_transfers"]), f"GW{gw}: replayed FT {state.free_transfers} != log {row['free_transfers']}"
        assert state.total_points == int(row["total_points"]), f"GW{gw}: replayed total != log"
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--tc2", type=int, default=None, help="schedule Triple Captain 2 IN-SIM at this gameweek (rule of record: earliest H2 double not already holding a chip; p4 log 12c ii). Captain = the MIP's own cap variable at that deadline (argmax step-0 e_points in the XI); no post-deadline information.")
    ap.add_argument("--arm", required=True, choices=["baseline8", "props", "hmin", "both", "penfix", "cal", "cal_penfix", "bonusow", "bonusdel", "leakfix", "gap0", "props_gap0", "hmin_gap0", "both_gap0", "hold_gap0"])
    ap.add_argument("--hold-eps", type=float, default=None, help="hold_gap0 arm: simulator.HOLD_PREFERENCE_EPS (Logs/hold_preference_prereg.md); required for that arm")
    a = ap.parse_args()
    season, arm, tag = a.season, a.arm, a.season.replace("-", "_")
    ARMS_DIR.mkdir(parents=True, exist_ok=True)
    out = ARMS_DIR / (f"armlog_{tag}_{arm}_tc2.parquet" if a.tc2 else f"armlog_{tag}_{arm}.parquet")
    if arm == "hold_gap0":
        out = ARMS_DIR / f"armlog_{tag}_hold_gap0_eps{a.hold_eps:g}{'_tc2' if a.tc2 else ''}.parquet"
    if out.exists():
        print(f"skip existing {out.name}"); return
    simulator.OPENING_HORIZON_ACTIVE = False
    ref = pd.read_parquet(P1 / f"fslog_{tag}_{OPENING}_wc{WC1}.parquet")
    if arm in ("props_gap0", "hmin_gap0", "both_gap0"):
        # like-for-like base for the exploratory arms is the gap0 reference path (TC2 in-sim; TC flag never changes a decision)
        ref = pd.read_parquet(ARMS_DIR / f"armlog_{tag}_gap0_tc2.parquet")
    if arm == "baseline8":
        wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    elif arm in ("props_gap0", "hmin_gap0", "both_gap0"):
        # EXPLORATORY (2026-08-27; not a pre-registration, no bars, NOT adoptable): the props / horizon-minutes
        # arm frames rebuilt by eval/walkforward_arms.py on the leak-fixed canonical, solved at MIP gap 0.
        # Frames live in data/arms_gap0/ so the record's original arm frames (data/arms/) are untouched.
        # Both arms were previously REJECTED on their pre-registered component tests.
        wf_path = REPO / "data" / "arms_gap0" / f"walkforward_h6_{tag}_{arm.replace('_gap0', '')}.parquet"
    elif arm == "hold_gap0":
        # PRE-REGISTERED TEST (Logs/hold_preference_prereg.md): gap0 reference config + hold preference at
        # near-ties, epsilon from --hold-eps, applied in-process and restored after. Not adopted.
        assert a.hold_eps is not None and a.hold_eps >= 0, "hold_gap0 requires --hold-eps"
        simulator.HOLD_PREFERENCE_EPS = float(a.hold_eps)
        wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    elif arm == "gap0":
        # Leak-fixed canonical + solver MIP gap 0 (commit 37ad782, 2026-08-27). Same frame as
        # `leakfix`; the change is solver-side. Asserted below that the solver in force has gap 0.
        import optimize as _opt
        _s = _opt._default_solver()
        _rel = getattr(_s, "gapRel", None); _rel = _s.optionsDict.get("gapRel") if _rel is None else _rel
        _abs = getattr(_s, "gapAbs", None); _abs = _s.optionsDict.get("gapAbs") if _abs is None else _abs
        assert _rel == 0.0 and _abs == 0.0, f"gap0 arm requires a zero-gap solver, got rel={_rel} abs={_abs}"
        wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    elif arm == "leakfix":
        # Season figures on the CANONICAL rebuilt after the penalty-join leak fix
        # (commit e04fb72, 2026-08-27): bonus_mode=delete, prior-season join in both
        # gate states, stamped penalty_join_prior_season. Full season; run with
        # --tc2 on the 12c(ii) week for the reference cells (leak-fixed convention).
        wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    elif arm in ("bonusow", "bonusdel"):
        # Bonus rebuild / delete arms (Logs/bonus_rebuild_prereg.md). Full season; figure only.
        wf_path = REPO / "data" / f"walkforward_h6_{tag}_{arm}.parquet"
    elif arm in ("cal", "cal_penfix"):
        # Top-end calibration arms (Logs/topend_calibration_prereg.md). Full season; figure only.
        wf_path = REPO / "data" / f"walkforward_h6_{tag}_{arm}.parquet"
    elif arm == "penfix":
        # Penalty-term correctness fix (Logs/penalty_fix_prereg.md): the gated
        # _penfix walk-forward built by eval/run_penalty_fix.py. Full season,
        # every season -- no coverage gap. Season figure only; never evidence.
        wf_path = REPO / "data" / f"walkforward_h6_{tag}_penfix.parquet"
    else:
        wf_path = ARMS_DIR / f"walkforward_h6_{tag}_{arm}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path), horizon_aware=True, season=season)
    if arm in ("leakfix", "gap0", "hold_gap0"):
        assert "penalty_join_prior_season" in df.columns and bool(df["penalty_join_prior_season"].iloc[0]) is True, \
            "leakfix arm requires a canonical rebuilt on the leak fix (stamp penalty_join_prior_season)"
        assert df["bonus_mode"].iloc[0] == "delete" and bool(df["penalty_fix_active"].iloc[0]) is False \
            and bool(df["topend_cal_active"].iloc[0]) is False, "leakfix canonical stamps are not the config of record"
    elif arm in ("bonusow", "bonusdel"):
        assert df["bonus_mode"].iloc[0] == {"bonusow": "outcome", "bonusdel": "delete"}[arm], "bonus arm frame is not stamped"
    elif arm in ("cal", "cal_penfix"):
        assert bool(df["topend_cal_active"].iloc[0]) is True, "cal frame is not stamped topend_cal_active"
        assert bool(df["penalty_fix_active"].iloc[0]) == (arm == "cal_penfix")
    elif arm == "penfix":
        assert bool(df["penalty_fix_active"].iloc[0]) is True, "penfix frame is not stamped penalty_fix_active"
    elif arm in ("props_gap0", "hmin_gap0", "both_gap0"):
        assert df["arm"].unique().tolist() == [arm.replace("_gap0", "")], "arm frame is not stamped with this arm"
        # walkforward_arms.py writes its own stamp set (no penalty_join_prior_season column); provenance is
        # asserted BIT-EXACTLY instead: the arm frame's penalty_share must equal the leak-fixed canonical's
        # on every joined row (the pre-fix canonical differs on thousands of rows).
        _canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet", columns=["element", "gw", "cutoff", "penalty_share"])
        _j = df[["element", "gw", "cutoff", "penalty_share"]].merge(_canon, on=["element", "gw", "cutoff"], suffixes=("", "_canon"))
        assert len(_j) > 0 and float((_j["penalty_share"] - _j["penalty_share_canon"]).abs().max()) == 0.0,             "arm frame's penalty_share is not bit-identical to the leak-fixed canonical -- not built on the fixed code"
    elif arm != "baseline8":
        assert df["arm"].unique().tolist() == [arm], "arm frame is not stamped with this arm"
    start_gw = START_GW.get(season, 1) if arm not in ("penfix", "cal", "cal_penfix", "bonusow", "bonusdel", "leakfix", "gap0", "hold_gap0") else 1
    if arm == "baseline8":
        assert start_gw > 1, "baseline8 is the GW8-start like-for-like check; this season runs in full"
    bb1, bb2 = rfs.BB1[(season, OPENING)], rfs.BB2[season]
    sched = dict(wildcard_gws=[WC1, rfs.WC2[season]], free_hit_gws=rfs.FH2[season], bench_boost_gw=[bb1, bb2])
    if a.tc2:
        assert a.tc2 >= 20 and a.tc2 not in {WC1, rfs.WC2[season], rfs.FH2[season], bb1, bb2}, "TC2 must be a second-half week holding no other chip"
        sched["triple_captain_gw"] = int(a.tc2)
    initial = None; gws = None
    if start_gw > 1:
        canon = simulator.load_season(walkforward_path=str(REPO / "data" / f"walkforward_h6_{tag}.parquet"), horizon_aware=True, season=season)
        initial = replay_state(ref, canon, start_gw - 1)
        gws = list(range(start_gw, 39))
        print(f"{season} {arm}: resuming from the reference cell's state at end of GW{start_gw - 1}: {initial}", flush=True)
    t0 = time.time()
    state, log = simulator.simulate_season(df, policy="mip", horizon=rfs.H, decay=rfs.DECAY, gws=gws, initial_state=initial, verbose=False, **sched)
    simulator.HOLD_PREFERENCE_EPS = None      # gate rests None (hold_gap0 sets it in-process only)
    log = log.copy()
    played = set(int(g) for g in log["gw"])
    if start_gw > 1:
        played |= set(int(g) for g in ref["gw"] if g < start_gw)
    check_chip_schedule({"wildcard": [WC1, rfs.WC2[season]], "free_hit": [rfs.FH2[season]], "bench_boost": [bb1, bb2], "triple_captain": [a.tc2] if a.tc2 else []},
                        played_gws=played, source=out.name)
    if arm == "baseline8":
        r = ref.set_index("gw").loc[start_gw:, "points"].to_numpy(); s = log.set_index("gw")["points"].to_numpy()
        same = (r == s).all()
        print(f"LIKE-FOR-LIKE CHECK: resumed baseline GW{start_gw}-38 {'REPRODUCES' if same else 'DOES NOT reproduce'} the reference log "
              f"(segment {int(s.sum())} vs reference {int(r.sum())}; first divergence GW{next((g for g, (x, y) in zip(range(start_gw, 39), zip(r, s)) if x != y), None)})", flush=True)
        log["reproduces_reference_segment"] = bool(same)
    log["all_transfers"] = log["all_transfers"].map(json.dumps); log["elements"] = log["elements"].map(json.dumps)
    log["season"], log["opening"], log["arm"] = season, OPENING, arm
    log["wc1"], log["wc2"], log["fh2"], log["bb1"], log["bb2"] = WC1, rfs.WC2[season], rfs.FH2[season], bb1, bb2
    log["wf_file"] = wf_path.name; log["start_gw"] = start_gw
    log["resume_from"] = ((f"armlog_{tag}_gap0_tc2.parquet@GW{start_gw - 1}" if arm in ("props_gap0", "hmin_gap0", "both_gap0") else f"fslog_{tag}_{OPENING}_wc{WC1}.parquet@GW{start_gw - 1}") if start_gw > 1 else "none")
    log["props_active"] = arm in ("props", "both", "props_gap0", "both_gap0"); log["horizon_minutes_active"] = arm in ("hmin", "both", "hmin_gap0", "both_gap0"); log["exploratory_not_adoptable"] = arm in ("props_gap0", "hmin_gap0", "both_gap0")
    log["penalty_fix_active"] = arm in ("penfix", "cal_penfix"); log["topend_cal_active"] = arm in ("cal", "cal_penfix"); log["bonus_mode"] = {"bonusow": "outcome", "bonusdel": "delete", "leakfix": "delete", "gap0": "delete", "hold_gap0": "delete"}.get(arm, "incumbent")
    log["penalty_join_prior_season"] = bool(df["penalty_join_prior_season"].iloc[0]) if "penalty_join_prior_season" in df.columns else False
    import optimize as _opt2
    _s2 = _opt2._default_solver(); _r2 = getattr(_s2, "gapRel", None); _r2 = _s2.optionsDict.get("gapRel") if _r2 is None else _r2
    log["solver_gap_zero"] = (_r2 == 0.0)   # stamp: was this path solved at MIP gap 0 (commit 37ad782)?
    log["tc2_gw"] = int(a.tc2) if a.tc2 else -1
    log["segment_total"] = int(log["points"].sum())
    log["final_total"] = int(state.total_points)
    tmp = out.with_suffix(".tmp.parquet"); log.to_parquet(tmp, index=False); tmp.replace(out)
    print(f"DONE {out.name}: segment GW{start_gw}-38 = {int(log['points'].sum())}, season total (incl. common prefix) = {int(state.total_points)} ({(time.time() - t0) / 60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
