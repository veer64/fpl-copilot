"""Walk-forward frames for the season-figure ARMS (props / horizon minutes / both), built at every cutoff from the SAME per-cutoff components as the canonical file (eval/walkforward_season.py): attacking rates, the step-0 minutes model, the bonus model, Dixon-Coles fixtures and DC hits are computed ONCE per cutoff and the master equation (assembly.assemble_fixtures, unchanged) is evaluated once per arm. A `base` variant with no hook is assembled at every cutoff and compared with the canonical walkforward row-for-row, so the rebuild's own reproducibility is measured rather than assumed.

Arms:
  props  -- squad/props_feature.PropsHook installed on assembly.PROPS_HOOK: the conditional-rate market blend at step 0 (w = 0.75, m = 1.396), outfield only, partial doubles kept on the model and counted. FAILED its pre-registered component test; season figures only.
  hmin   -- horizon minutes lever 1 (data/horizon/hmin_{season}_refit.parquet): steps 1-5 take the per-step refit's p_start / p60 / e_minutes instead of the cutoff's step-0 copy; step 0 is the canonical minutes frame; elements the refit has no row for keep the stale copy (counted). FAILED its acceptance test (rank fell on likely starters and squad-relevant rows); horizon_minutes.HORIZON_MINUTES_ACTIVE stays False -- the lever is applied here in-process for measurement only.
  both   -- both hooks.

Every emitted row is stamped: arm, props_active, props_spec, horizon_minutes_active, horizon_levers (the #13 lesson). Output: data/arms/walkforward_h6_{tag}_{arm}.parquet (atomic) plus a sidecar JSON with the reproducibility check and the amendment-3 counts.

Usage: uv run python eval/walkforward_arms.py --season 2024-25 --from-cutoff 8 --arms props,hmin,both
"""
import argparse
import json
import os
from _replace_retry import replace_with_retry
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import assembly  # noqa: E402
import attacking_rates as rates_mod  # noqa: E402
import bonus as bonus_mod  # noqa: E402
import defensive as def_mod  # noqa: E402
import dixon_coles as dc_mod  # noqa: E402
import minutes as minutes_mod  # noqa: E402
import props_feature  # noqa: E402
import walkforward_season as wfs  # noqa: E402

OUT = REPO / "data" / "arms"
H = 6
MIN_COLS = ["element", "name", "position", "p_start", "p60", "e_minutes"]


def minutes_frames(m_k, k, targets, hmin):
    """Step 0: the cutoff's own frame. Steps >= 1: the canonical STALE copy, or the
    lever-1 refit rows where `hmin` is given (elements without a refit row keep
    the stale copy; counted)."""
    frames, n_refit, n_stale = [], 0, 0
    for g in targets:
        f = m_k[MIN_COLS].copy(); f["gw"] = g
        if hmin is not None and g > k:
            h = hmin[(hmin["cutoff"] == k) & (hmin["horizon_step"] == g - k)][["element", "p_start", "p60", "e_minutes"]]
            h = h.drop_duplicates("element")
            f = f.merge(h, on="element", how="left", suffixes=("", "_h"))
            has = f["e_minutes_h"].notna()
            for c in ("p_start", "p60", "e_minutes"):
                f.loc[has, c] = f.loc[has, c + "_h"]
            f = f.drop(columns=["p_start_h", "p60_h", "e_minutes_h"])
            n_refit += int(has.sum()); n_stale += int((~has).sum())
        frames.append(f)
    return pd.concat(frames, ignore_index=True), n_refit, n_stale


def cutoff_components(season, k, targets, tr, gw_start, gw_end, all_gws):
    """The five per-cutoff component getters, computed ONCE per cutoff and shared by
    every arm (and by the no-hook repro build). Extracted verbatim from main()'s loop
    body so the LIVE path (squad/live_deadline.py) calls the same code: what the old
    closure captured from the enclosing scope is now an explicit signature."""
    rates, priors = rates_mod.get_rates(season, up_to_gw=k)
    cutoff_date = gw_start.loc[k].tz_localize(None)
    m_k = minutes_mod.get_minutes(up_to_gw=k, predict_gws=[k], per_fixture=True, availability=wfs.AVAILABILITY,
                                  train_seasons=tr, predict_season=season)
    bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = bonus_mod.get_bonus_model(up_to_gw=k, train_until=tr[-1], predict_season=season)
    odds_until = gw_end.loc[min(k + wfs.ODDS_HORIZON_GWS, max(all_gws))].tz_localize(None)
    f_k = dc_mod.get_fixtures(predict_season=season, cutoff_date=cutoff_date, odds_available_until=odds_until)
    dc_k = def_mod.get_dc_hits(season, k, targets)
    return dict(m_k=m_k, rates=rates, priors=priors, f_k=f_k, dc_k=dc_k, bps_model=bps_model,
                bps_to_bonus=bps_to_bonus, BPS_FEATURES=BPS_FEATURES, bonus_mean=bonus_mean)


def assemble_cutoff(comp, df, cw, mins, k, targets, season, dc_enabled, hook=None):
    """ONE master-equation evaluation for one cutoff: the `assemble` closure from
    main(), lifted with an explicit signature. The props gate is the SAME module
    global with the SAME finally restore; the steps-1-5 horizon-minutes substitution
    enters through `mins` (built by minutes_frames). No behaviour change."""
    assembly.PROPS_HOOK = hook
    if hook is not None:
        hook.cutoff = k
    try:
        a_k = assembly.collapse_to_gameweek(assembly.assemble_fixtures(
            df, cw, mins, comp["rates"], comp["priors"], comp["f_k"].copy(), comp["dc_k"],
            comp["bps_model"], comp["bps_to_bonus"], comp["BPS_FEATURES"], comp["bonus_mean"],
            gws=targets, season=season, dc_enabled=dc_enabled, cutoff_gw=k))
    finally:
        assembly.PROPS_HOOK = None
    a_k["cutoff"] = k; a_k["horizon_step"] = a_k["gw"] - k
    return a_k


def stamp_arm_frame(res, season, tr, arm, dc_enabled):
    """The arm builder's provenance stamps (the #13 lesson), extracted so the live
    path stamps a frame IDENTICALLY to the record files. Returns res, stamped."""
    res["season_label"] = season
    res["minutes_availability"] = bool(wfs.AVAILABILITY); res["odds_horizon_gws"] = int(wfs.ODDS_HORIZON_GWS)
    res["dgw_handling"] = "per_fixture"; res["dc_rule_active"] = bool(dc_enabled)
    res["d1_terms_active"] = bool(assembly.D1_TERMS_ACTIVE); res["cs_unified"] = bool(assembly.CS_UNIFIED)
    res["penalty_fix_active"] = bool(assembly.PENALTY_FIX_ACTIVE)
    res["topend_cal_active"] = bool(assembly.TOPEND_CAL_ACTIVE); res["fixture_scale_gamma"] = float(assembly.FIXTURE_SCALE_GAMMA)
    res["bonus_mode"] = str(assembly.BONUS_MODE)
    res["rate_blend_active"] = bool(rates_mod.RATE_BLEND_ACTIVE); res["rate_blend_k"] = float(rates_mod.RATE_BLEND_K)
    import synthetic_lambda as synth_mod
    res["synthetic_lambda_active"] = bool(synth_mod.SYNTHETIC_LAMBDA_ACTIVE)
    res["train_seasons"] = ",".join(tr)
    res["arm"] = arm
    res["props_active"] = arm in ("props", "both"); res["props_spec"] = props_feature.PROPS_SPEC if arm in ("props", "both") else "off"
    res["horizon_minutes_active"] = arm in ("hmin", "both"); res["horizon_levers"] = "refit" if arm in ("hmin", "both") else "off"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--from-cutoff", type=int, default=1)
    ap.add_argument("--to-cutoff", type=int, default=38)
    ap.add_argument("--arms", default="props,hmin,both")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()
    season, tag = a.season, a.season.replace("-", "_")
    arms = a.arms.split(",")
    out_dir = Path(a.out_dir) if a.out_dir else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    tr = wfs.train_seasons_for(season)
    dc_enabled = season in wfs.DC_SEASONS
    df = pd.read_parquet(wfs.BASE + "/data/history/all_seasons_fixed.parquet")
    cw = wfs.crosswalk_for(season)
    v = df[df["season"] == season].copy()
    v["kick"] = pd.to_datetime(v["kickoff_time"])
    gw_start = v.groupby("GW")["kick"].min().sort_index(); gw_end = v.groupby("GW")["kick"].max().sort_index()
    all_gws = sorted(gw_start.index.astype(int))
    cutoffs = [g for g in all_gws if a.from_cutoff <= g <= a.to_cutoff]
    canon = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet")
    hmin = pd.read_parquet(REPO / "data" / "horizon" / f"hmin_{tag}_refit.parquet") if any(x in arms for x in ("hmin", "both")) else None
    hooks = {arm: (props_feature.PropsHook(season) if arm in ("props", "both") else None) for arm in arms}
    print(f"{season}: arms {arms}, cutoffs {cutoffs[0]}..{cutoffs[-1]} ({len(cutoffs)}), train {tr}, DC {'ON' if dc_enabled else 'OFF'}", flush=True)
    out = {arm: [] for arm in arms}
    repro = []; stale_counts = {arm: [0, 0] for arm in arms}
    t_all = time.time()
    for k in cutoffs:
        t0 = time.time()
        targets = [g for g in all_gws if k <= g < k + H]
        comp = cutoff_components(season, k, targets, tr, gw_start, gw_end, all_gws)

        # reproducibility: the no-hook rebuild against the canonical rows of this cutoff
        stale_m, _, _ = minutes_frames(comp["m_k"], k, targets, None)
        base = assemble_cutoff(comp, df, cw, stale_m, k, targets, season, dc_enabled, None)
        c = canon[canon["cutoff"] == k][["gw", "element", "e_points"]]
        j = base[["gw", "element", "e_points"]].merge(c, on=["gw", "element"], how="outer", suffixes=("_re", "_can"), indicator=True)
        both = j[j["_merge"] == "both"]
        d = (both["e_points_re"] - both["e_points_can"]).abs()
        repro.append(dict(cutoff=k, n_canon=len(c), n_rebuilt=len(base), n_both=len(both), max_abs_diff=float(d.max()) if len(d) else None,
                          n_diff_gt_1e6=int((d > 1e-6).sum()), only_canon=int((j["_merge"] == "right_only").sum()), only_rebuilt=int((j["_merge"] == "left_only").sum())))
        for arm in arms:
            mins, n_r, n_s = minutes_frames(comp["m_k"], k, targets, hmin if arm in ("hmin", "both") else None)
            stale_counts[arm][0] += n_r; stale_counts[arm][1] += n_s
            out[arm].append(assemble_cutoff(comp, df, cw, mins, k, targets, season, dc_enabled, hooks[arm]))
        r = repro[-1]
        print(f"  cutoff GW{k:2d}: {len(base):5d} rows; repro max|d e_points| {r['max_abs_diff']:.2e} on {r['n_both']} rows "
              f"(only-canon {r['only_canon']}, only-rebuilt {r['only_rebuilt']}); {time.time() - t0:.0f}s", flush=True)
    for arm in arms:
        res = stamp_arm_frame(pd.concat(out[arm], ignore_index=True), season, tr, arm, dc_enabled)
        path = out_dir / f"walkforward_h6_{tag}_{arm}.parquet"
        tmp = path.with_suffix(".tmp.parquet"); res.to_parquet(tmp, index=False); replace_with_retry(tmp, path)
        hook = hooks[arm]
        side = dict(season=season, arm=arm, cutoffs=[cutoffs[0], cutoffs[-1]], rows=len(res),
                    props=(dict(overridden_player_fixtures=hook.n_override, partial_doubles_excluded=hook.n_partial_excluded,
                                gk_skipped=hook.n_gk_skipped, by_cutoff=hook.by_gw) if hook else None),
                    hmin=(dict(refit_rows=stale_counts[arm][0], stale_fallback_rows=stale_counts[arm][1]) if arm in ("hmin", "both") else None),
                    reproducibility=repro)
        (out_dir / f"walkforward_h6_{tag}_{arm}.json").write_text(json.dumps(side, indent=1), encoding="utf-8")
        print(f"DONE {path.name}: {len(res):,} rows" + (f"; props overridden {hook.n_override:,} player-fixtures, partial doubles excluded {hook.n_partial_excluded}, GK skipped {hook.n_gk_skipped}" if hook else "")
              + (f"; hmin refit rows {stale_counts[arm][0]:,}, stale fallback {stale_counts[arm][1]:,}" if arm in ("hmin", "both") else ""), flush=True)
    mx = max(r["max_abs_diff"] or 0 for r in repro)
    print(f"REPRODUCIBILITY of the no-hook rebuild vs canonical over {len(repro)} cutoffs: max |d e_points| {mx:.2e}; "
          f"rows only in canonical {sum(r['only_canon'] for r in repro)}, only in rebuild {sum(r['only_rebuilt'] for r in repro)}; {(time.time() - t_all) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
