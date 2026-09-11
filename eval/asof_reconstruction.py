"""AS-OF RECONSTRUCTION -- the leakage guard the master plan (section 4.2) seeded
and LEAKAGE.md's 2026-09-11 audit specified; built 2026-09-11.

THE CLAIM IT TESTS. A walk-forward frame at cutoff k must be a function of the
information set that exists at gameweek k's deadline. The parity harness
(squad/live_deadline.py) cannot test that: it rebuilds a historical cutoff from
the SAME on-disk inputs the canonical was built from, with gameweek k and every
later gameweek already played, so a term that reads post-cutoff rows reproduces
bit-for-bit and passes. LEAKAGE.md items 6-8 (KNOWN_ISSUES #22) all passed
parity for exactly that reason.

THE MECHANISM. For (season, k): every per-season input is cut to the live
information set, the frame is rebuilt through the SAME code the canonical and
the live path run (walk_forward for baseline; the arm builder's extracted
pipeline for combined -- both via live_deadline.build_deadline_frame), and every
column is compared against the canonical rows for that cutoff. A column that
differs is reading post-cutoff information. The truncation, all in-process and
restored afterwards:

  * season stack   -> rows of `season` with GW < k only (other seasons intact);
                     gameweeks >= k are served as a FORWARD SKELETON built from
                     the master's own rows with every measurement column nulled
                     (identity + fixture geometry + value kept, exactly the
                     columns eval/build_forward_skeleton.CARRIED). Identity is
                     as recorded, not as-of-k: roster churn is a measured
                     information-set limit of the live skeleton (that builder's
                     --backfill mode), NOT the subject here. This test isolates
                     OUTCOME information.
  * core-insights   -> matchstats rows with gw < k (the record's DC source).
  * Understat       -> the current season's per-match rows with gw < k.
  * odds archive    -> results (goals) nulled for fixtures dated >= the cutoff;
                     prices nulled for fixtures after the last kickoff of gw k
                     (ODDS_HORIZON_GWS = 0).
  * availability    -> rows with gw <= k (the deadline's own as-of row is live).
  * defensive._DC_HITS_CACHE cleared before and after (it is keyed without the
    cutoff and would otherwise serve full-season predictions).

  * horizon refit   -> for the combined config the steps-1-5 minutes substitution
                     is RECONSTRUCTED in-process from the truncated stack
                     (horizon_minutes.get_minutes_horizon at the cutoff) and
                     injected through live_deadline.load_hmin_refit, never read
                     from data/horizon/. The refit's cutoff row is built by the
                     same frame code as step 0 (LEAKAGE.md item 9 lived there
                     too); a file read from disk would leave steps 1-5 outside
                     the guard and "zero movement" there would mean nothing.

What is NOT truncated, and why: the props consensus books (pre-deadline boards,
only gw == k is read), the crosswalk (identity), prior-season files. Columns
that ARE outcomes (`minutes`, `actual_points`) are excluded from the comparison
and listed separately. See the residual list in LEAKAGE.md (2026-09-11 audit)
for what this guard cannot see.

Usage:
  uv run python eval/asof_reconstruction.py --season 2025-26 --cutoffs 3 20 24 33 --config baseline
  uv run python eval/asof_reconstruction.py --season 2025-26 --cutoffs 20 --config combined --record-source
--record-source pins defensive.DC_SOURCE = "core_insights" (what the frozen
2025-26 record was built under) so the comparison isolates the leak from the
2026-08-31 source adoption. Tests/test_asof_reconstruction.py runs this against
the current record under the live default.
"""
import argparse
import contextlib
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import season_stack  # noqa: E402
import defensive  # noqa: E402
import attacking_rates  # noqa: E402
import dixon_coles  # noqa: E402
import availability_features as avf  # noqa: E402
from build_forward_skeleton import CARRIED  # noqa: E402

OUTCOME_COLS = {"minutes", "actual_points"}     # realised, carried for scoring only -- never predictions
STAMP_ONLY_LIVE = {"penalty_join_prior_season"}  # stamp the arm record predates (Tests/test_live_deadline.py)


def _skeleton_from_master(cur, k):
    """Forward rows for GW >= k: the master's own rows with every non-CARRIED
    column nulled (float64 for numeric columns, as load_stack's concat upcasts)."""
    fwd = cur[cur["GW"] >= k].copy()
    for c in fwd.columns:
        if c in CARRIED:
            continue
        if pd.api.types.is_numeric_dtype(fwd[c]) or pd.api.types.is_bool_dtype(fwd[c]):
            fwd[c] = np.nan
            fwd[c] = fwd[c].astype("float64")
        else:
            fwd[c] = None
    return fwd


@contextlib.contextmanager
def asof_world(season, k, tmpdir, record_source=False, reconstruct_refit=False, horizon=6):
    """Every per-season input cut to the deadline-k information set; restored on exit.
    reconstruct_refit=True additionally rebuilds the horizon-minutes refit for
    cutoff k INSIDE the truncated world and routes live_deadline.load_hmin_refit
    to it (the combined config's steps 1-5 input)."""
    tmp = Path(tmpdir)
    full = pd.read_parquet(season_stack.stack_path())
    cur = full[full["season"] == season]
    past = pd.concat([full[full["season"] != season], cur[cur["GW"] < k]], ignore_index=True)
    fwd = _skeleton_from_master(cur, k)
    p_past = tmp / f"asof_stack_{season}_{k}.parquet"
    p_fwd = tmp / f"asof_forward_{season}_{k}.parquet"
    past.to_parquet(p_past, index=False)
    fwd.to_parquet(p_fwd, index=False)

    kick = pd.to_datetime(cur["kickoff_time"])
    cutoff_date = kick[cur["GW"] == k].min().tz_localize(None)
    odds_until = kick[cur["GW"] == k].max().tz_localize(None)

    import live_deadline as ld
    saved = dict(stack_path=season_stack.stack_path, forward_path=season_stack.forward_path,
                 raw_core=defensive._raw_rows_core, load_matches=dixon_coles._load_matches,
                 av_load=avf.load, dc_source=defensive.DC_SOURCE,
                 matches_cache=dict(attacking_rates._MATCHES_CACHE),
                 load_hmin=ld.load_hmin_refit)
    defensive._DC_HITS_CACHE.clear()
    try:
        season_stack.stack_path = lambda: p_past
        season_stack.forward_path = lambda: p_fwd
        if record_source:
            defensive.DC_SOURCE = "core_insights"

        _core = saved["raw_core"]
        def raw_core_trunc():
            d = _core()
            return d[d["gw"] < k].copy()
        defensive._raw_rows_core = raw_core_trunc

        # Understat current-season per-match rows: prime the cache with the truncation
        um = attacking_rates._season_sums(season)
        attacking_rates._MATCHES_CACHE[season] = um[um["gw"] < k].copy()

        _lm = saved["load_matches"]
        def load_matches_trunc(predict_season=None):
            m = _lm(predict_season)
            this = m["season"] == season
            m.loc[this & (m["date_parsed"] >= cutoff_date), ["home_goals", "away_goals"]] = np.nan
            m.loc[this & (m["date_parsed"] > odds_until), ["b365h", "b365d", "b365a"]] = np.nan
            return m
        dixon_coles._load_matches = load_matches_trunc

        _av = saved["av_load"]
        def av_load_trunc(data_dir=None):
            a = _av(data_dir)
            return a[(a["season"] != season) | (a["gw"] <= k)].copy()
        avf.load = av_load_trunc

        if reconstruct_refit:
            # The refit for cutoff k, rebuilt from the truncated stack (labels
            # strictly before k by its own mask; the cutoff row from the patched
            # load_stack), stamped as eval/run_horizon_minutes.py stamps it.
            import horizon_minutes as hm
            import walkforward_season as wfs
            refit = hm.get_minutes_horizon(up_to_gw=k, steps=range(0, horizon), availability=wfs.AVAILABILITY,
                                           train_seasons=wfs.train_seasons_for(season),
                                           predict_season=season, levers=("refit",))
            refit["season"] = season
            ld.load_hmin_refit = lambda s, _r=refit: _r if s == season else saved["load_hmin"](s)
        yield dict(cutoff_date=cutoff_date, odds_until=odds_until, n_past=len(past), n_fwd=len(fwd))
    finally:
        season_stack.stack_path = saved["stack_path"]
        season_stack.forward_path = saved["forward_path"]
        defensive._raw_rows_core = saved["raw_core"]
        dixon_coles._load_matches = saved["load_matches"]
        avf.load = saved["av_load"]
        ld.load_hmin_refit = saved["load_hmin"]
        defensive.DC_SOURCE = saved["dc_source"]
        attacking_rates._MATCHES_CACHE.clear()
        attacking_rates._MATCHES_CACHE.update(saved["matches_cache"])
        defensive._DC_HITS_CACHE.clear()


def build_asof(season, k, config="baseline", horizon=6, record_source=False, tmpdir=None,
               reconstruct_refit=None):
    """reconstruct_refit defaults to True for the combined config (its steps 1-5
    input) and is meaningless for baseline."""
    import live_deadline as ld
    if reconstruct_refit is None:
        reconstruct_refit = (config == "combined" and horizon > 1)
    with tempfile.TemporaryDirectory() as td:
        with asof_world(season, k, tmpdir or td, record_source=record_source,
                        reconstruct_refit=reconstruct_refit, horizon=horizon):
            frame, findings = ld.build_deadline_frame(season, k, strict=False, verbose=False,
                                                      config=config, horizon=horizon)
    return frame, findings


def build_reference(season, k, config="baseline", horizon=6):
    """The full-information build for cutoff k -- what the record file carries --
    computed IN-PROCESS with the current code. For combined, the refit is also
    rebuilt in-process from the full stack (so the comparison does not depend on
    data/horizon/ being up to date with the code). Used to verify the guard
    before record files exist; the suite compares against the record files."""
    import live_deadline as ld
    saved = ld.load_hmin_refit
    try:
        if config == "combined" and horizon > 1:
            import horizon_minutes as hm
            import walkforward_season as wfs
            refit = hm.get_minutes_horizon(up_to_gw=k, steps=range(0, horizon), availability=wfs.AVAILABILITY,
                                           train_seasons=wfs.train_seasons_for(season),
                                           predict_season=season, levers=("refit",))
            refit["season"] = season
            ld.load_hmin_refit = lambda s, _r=refit: _r if s == season else saved(s)
        defensive._DC_HITS_CACHE.clear()
        frame, findings = ld.build_deadline_frame(season, k, strict=False, verbose=False,
                                                  config=config, horizon=horizon)
    finally:
        ld.load_hmin_refit = saved
        defensive._DC_HITS_CACHE.clear()
    frame = frame.copy()
    frame["cutoff"] = k
    return frame


def canonical_path(season, config):
    tag = season.replace("-", "_")
    if config == "combined":
        return REPO / "data" / "arms_gap0" / f"walkforward_h6_{tag}_both.parquet"
    return REPO / "data" / f"walkforward_h6_{tag}.parquet"


def compare(frame, canon, k):
    """Per (column, step): rows differing and |delta| stats. Returns (table, row_set_ok)."""
    c = canon[canon["cutoff"] == k]
    rows = []
    row_ok = True
    for step in sorted(int(s) for s in frame["horizon_step"].unique()):
        l = frame[frame["horizon_step"] == step].sort_values("element").reset_index(drop=True)
        r = c[c["horizon_step"] == step].sort_values("element").reset_index(drop=True)
        if len(l) != len(r) or not (l["element"].values == r["element"].values).all():
            row_ok = False
            keep = sorted(set(l["element"]) & set(r["element"]))
            rows.append(dict(step=step, column="<ROW SET>", n_diff=abs(len(l) - len(r)),
                             max_abs=np.nan, mean_abs=np.nan))
            l = l[l["element"].isin(keep)].reset_index(drop=True)
            r = r[r["element"].isin(keep)].reset_index(drop=True)
        for col in r.columns:
            if col not in l.columns or col in OUTCOME_COLS:
                continue
            a, b = l[col], r[col]
            if pd.api.types.is_numeric_dtype(b) and not pd.api.types.is_bool_dtype(b):
                av, bv = a.astype(float).values, b.astype(float).values
                both_nan = np.isnan(av) & np.isnan(bv)
                d = np.abs(np.where(both_nan, 0.0, av - bv))
                nan_mm = (np.isnan(av) != np.isnan(bv))
                d = np.where(nan_mm, np.inf, d)
                n = int((d > 0).sum())
                if n:
                    fin = d[np.isfinite(d) & (d > 0)]
                    rows.append(dict(step=step, column=col, n_diff=n,
                                     max_abs=float(fin.max()) if len(fin) else np.inf,
                                     mean_abs=float(fin.mean()) if len(fin) else np.inf,
                                     nan_mismatch=int(nan_mm.sum())))
            else:
                eq = a.astype(str) == b.astype(str)
                if not eq.all():
                    rows.append(dict(step=step, column=col, n_diff=int((~eq).sum()),
                                     max_abs=np.nan, mean_abs=np.nan))
    only_canon = sorted(set(canon.columns) - set(frame.columns))
    only_live = sorted(set(frame.columns) - set(canon.columns) - STAMP_ONLY_LIVE)
    t = pd.DataFrame(rows, columns=["step", "column", "n_diff", "max_abs", "mean_abs", "nan_mismatch"])
    return t, row_ok, only_canon, only_live


def run(season, cutoffs, config, record_source=False, horizon=6, verbose=True, reference="record"):
    """reference="record": compare the as-of rebuild against the record file on disk
    (the standing guard). reference="inprocess": compare against a full-information
    build made now with the same code (verifies the CODE before a record exists)."""
    canon = pd.read_parquet(canonical_path(season, config)) if reference == "record" else None
    results = {}
    for k in cutoffs:
        frame, _ = build_asof(season, k, config=config, horizon=horizon, record_source=record_source)
        ref = canon if reference == "record" else build_reference(season, k, config=config, horizon=horizon)
        t, row_ok, only_canon, only_live = compare(frame, ref, k)
        results[k] = dict(table=t, row_ok=row_ok, only_canon=only_canon, only_live=only_live)
        if verbose:
            moved = sorted(t["column"].unique())
            print(f"\n=== {season} cutoff GW{k} [{config}{', record source' if record_source else ''}]: "
                  f"{len(frame)} as-of rows; row set {'identical' if row_ok else 'DIFFERS'}; "
                  f"columns moving: {len(moved)}")
            if only_canon or only_live:
                print(f"  column sets differ: only-canonical {only_canon}, only-as-of {only_live}")
            if len(t):
                piv = t.pivot_table(index="column", columns="step", values="n_diff", aggfunc="sum").fillna(0).astype(int)
                mx = t.groupby("column")["max_abs"].max()
                mn = t.groupby("column")["mean_abs"].mean()
                out = piv.copy(); out["max|d|"] = mx.round(4); out["mean|d|"] = mn.round(4)
                print(out.to_string())
            else:
                print("  EVERY COLUMN BIT-IDENTICAL to the canonical rows at this cutoff")
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--cutoffs", type=int, nargs="+", default=[3, 20, 24, 33])
    ap.add_argument("--config", choices=["baseline", "combined"], default="baseline")
    ap.add_argument("--record-source", action="store_true")
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--reference", choices=["record", "inprocess"], default="record",
                    help="record = the file on disk (the standing guard); inprocess = a full-information build made now")
    a = ap.parse_args()
    res = run(a.season, a.cutoffs, a.config, record_source=a.record_source, horizon=a.horizon,
              reference=a.reference)
    any_move = any(len(r["table"]) or not r["row_ok"] for r in res.values())
    print(f"\nAS-OF RECONSTRUCTION [{a.config}]: {'COLUMNS MOVE -- post-cutoff information is being read' if any_move else 'PASS -- no column reads post-cutoff information'}")
    sys.exit(1 if any_move else 0)


if __name__ == "__main__":
    main()
