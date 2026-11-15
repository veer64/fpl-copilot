"""M3 B0 -- which FORM of the crowd features ships? The midweek test. PROBE CODE: nothing in production imports
this module and it changes no prediction.

Users ask midweek, not ten minutes before the deadline. The crowd features (squad/crowd_block.py) are built from
the bootstrap snapshot just before each deadline; three days earlier the same fields hold only part of the
week's transfers. Question: fed a MIDWEEK snapshot at prediction time, which form holds up -- the five features
raw, or ownership + the four flow features as within-gameweek percentile ranks?

PROTOCOL (M2's, eval/m2_crowd_probe.py, the P(start) sub-model only):
  MODEL     the production P(start) sub-model (LightGBM 300 / 31 / lr 0.05 / seed 42) on get_minutes's own feature
            list. Arms: base (that list); raw (+ the five); rank (+ ownership + the four ranks).
  TRAINING  rows keep the DEADLINE-snapshot features (the block as built): prior labelled seasons + the season's
            gameweeks < k.
  PREDICTION gameweek k, as one ordinary fixture, twice per crowd arm: with the deadline-snapshot features (as
            M2) and with the features of the last snapshot AT OR BEFORE deadline - 72 h (fplcache for 2024-25 /
            2025-26, the live archive for 2026-27). Midweek ranks are taken within the midweek snapshot.
            The baseline arm has no crowd feature, so it has one prediction.
  SCORING   gameweek 2 onward (gameweek 1 has no transfers). Slices fixed on the baseline arm; deltas against the
            baseline with 95% intervals from 2,000 bootstrap draws over gameweeks; pooled across the three seasons
            by averaging the seasons' deltas draw by draw (M2's pooling).
  RULE      shipping form = RANK, unless RAW has the lower ALL-rows Brier at midweek in all three seasons -> RAW.
            Reported, no rule: whether the chosen form beats the baseline at midweek (pooled ALL-rows Brier delta
            and interval); if it does not: "helps only near the deadline".

Usage (outputs only under data/m3/, never written over):
    uv run python eval/m3_midweek_probe.py build --out data/m3/midweek_crowd.parquet
    uv run python eval/m3_midweek_probe.py fit   --midweek data/m3/midweek_crowd.parquet --out data/m3/b0_rows.parquet
    uv run python eval/m3_midweek_probe.py read  --rows data/m3/b0_rows.parquet [--m2-rows data/m2/probe_rows.parquet]
                                                 [--timing data/m3/midweek_crowd.timing.csv]
"""
import argparse
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import crowd_features as cf  # noqa: E402
import m2_crowd_probe as probe  # noqa: E402

MIDWEEK_HOURS = 72
FIRST_GW = 2                                           # gameweek 1 has no transfers
SEASONS = [("2024-25", ["2022-23", "2023-24"]),
           ("2025-26", ["2022-23", "2023-24", "2024-25"]),
           ("2026-27", ["2022-23", "2023-24", "2024-25", "2025-26"])]
LIVE_SEASON = "2026-27"
ARMS = ("raw", "rank")
LIVE_NAME = re.compile(r"^(\d{8}T\d{6}Z)(?:\.(\w+))?\.json\.gz$")


# ------------------------------------------------------------------ the midweek snapshot
def fplcache_snapshots(cache=None):
    """(utc time, path) of every fplcache snapshot, ascending -- eval/build_availability.list_snapshots."""
    import build_availability as ba
    return ba.list_snapshots(Path(cache) if cache else ba.CACHE)


def live_snapshots(season, root=None):
    """(utc time, path) of every bootstrap snapshot in the live archive of `season`, ascending."""
    d = Path(root) if root else REPO / "data" / "live" / "bootstrap_raw" / season
    out = []
    for p in sorted(d.iterdir()):
        m = LIVE_NAME.match(p.name)
        if m:
            out.append((datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), p))
    return sorted(out)


def pick_midweek(deadlines, snaps, hours=MIDWEEK_HOURS):
    """For each gameweek: the last snapshot AT OR BEFORE deadline - `hours`. `deadlines` = {gw: utc deadline};
    `snaps` = ascending (utc time, path). A gameweek with no such snapshot is left out. Also says whether the
    snapshot predates the PREVIOUS gameweek's deadline (its transfer counters then belong to that earlier week)."""
    rows = []
    for gw in sorted(deadlines):
        cut = deadlines[gw] - timedelta(hours=hours)
        before = [(t, p) for t, p in snaps if t <= cut]
        if not before:
            continue
        t, p = before[-1]
        prev = deadlines.get(gw - 1)
        rows.append(dict(gw=int(gw), deadline_time=deadlines[gw], snapshot_time=t, snapshot_path=str(p),
                         hours_before_deadline=(deadlines[gw] - t).total_seconds() / 3600.0,
                         before_previous_deadline=bool(prev is not None and t < prev)))
    return pd.DataFrame(rows, columns=["gw", "deadline_time", "snapshot_time", "snapshot_path", "hours_before_deadline",
                                       "before_previous_deadline"])


def deadlines_of(season, data_dir=None):
    """{gw: deadline} as the availability file of the season records them."""
    data_dir = Path(data_dir) if data_dir else REPO / "data"
    av = pd.read_parquet(data_dir / f"availability_{cf.AVAIL_TAG[season]}.parquet", columns=["gw", "deadline_time"]).drop_duplicates("gw")
    return {int(g): t.to_pydatetime() for g, t in zip(av["gw"], av["deadline_time"])}


def midweek_features(season, table):
    """The five features and the four within-snapshot ranks from each gameweek's midweek snapshot."""
    parts = [cf.rows_from_payload(season, r.gw, cf.read_snapshot(r.snapshot_path), r.hours_before_deadline)
             for r in table.itertuples()]
    d = cf.to_ranks(cf.features(pd.concat(parts, ignore_index=True)))
    assert not d.duplicated(["season", "GW", "element"]).any()
    return d


def cmd_build(a):
    if a.out.exists():
        raise FileExistsError(f"{a.out} exists -- a probe output is never written over")
    out, tables = [], []
    for season, _ in SEASONS:
        snaps = live_snapshots(season) if season == LIVE_SEASON else fplcache_snapshots()
        t = pick_midweek(deadlines_of(season), snaps)
        t.insert(0, "season", season)
        tables.append(t)
        out.append(midweek_features(season, t))
        print(f"[{season}] source {'live archive' if season == LIVE_SEASON else 'fplcache'}: snapshots {len(snaps)}; gameweeks with a midweek snapshot "
              f"{len(t)} (first {int(t.gw.min())}, last {int(t.gw.max())}); hours before the deadline median {t.hours_before_deadline.median():.2f}, "
              f"min {t.hours_before_deadline.min():.2f}, max {t.hours_before_deadline.max():.2f}; snapshot before the PREVIOUS deadline in "
              f"{int(t.before_previous_deadline.sum())} gameweek(s): {t.loc[t.before_previous_deadline, 'gw'].tolist()}", flush=True)
    d = pd.concat(out, ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(a.out, index=False)
    tt = pd.concat(tables, ignore_index=True)
    tt.to_csv(a.out.with_suffix(".timing.csv"), index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 200, "display.max_colwidth", 60):
        print(tt.assign(snapshot_path=tt.snapshot_path.map(lambda s: Path(s).name)).round(2).to_string(index=False))
    print(f"rows {len(d):,} | by season {d.groupby('season').size().to_dict()} -> {a.out}")


# ------------------------------------------------------------------ fit
def swap_in(pf, mw, cols):
    """Prediction rows with the crowd columns `cols` replaced by the midweek snapshot's (NaN where it has no row)."""
    m = mw[["season", "GW", "element"] + cols].rename(columns={c: c + "__mw" for c in cols})
    out = pf.merge(m, on=["season", "GW", "element"], how="left")
    assert len(out) == len(pf), "midweek join changed the row count"
    for c in cols:
        out[c] = out[c + "__mw"].to_numpy()
    out.index = pf.index
    return out.drop(columns=[c + "__mw" for c in cols])


def walk_forward(cs, season, train_seasons, gws, fp, mw, make_model, keep, on_fit=None):
    """For each gameweek k: fit base / raw / rank on the training rows (deadline features), predict gameweek k as
    one ordinary fixture -- the crowd arms twice, on the deadline features and on the midweek ones."""
    import minutes as mm
    lists = {"base": fp, "raw": fp + cf.CROWD, "rank": fp + ["cs_own_pct"] + cf.RANKED}
    crowd_cols = {"raw": cf.CROWD, "rank": ["cs_own_pct"] + cf.RANKED}
    outs = []
    for k in gws:
        trc = cs[mm._train_mask(cs, k, train_seasons, season)]
        trc = trc[trc["starts"].notna()]
        pf = cs[(cs["season"] == season) & (cs["GW"] == k)].dropna(subset=mm.SUBF + mm.S1).copy()
        if pf.empty:
            continue
        pf["is_double_gw_orig"] = pf["is_double_gw"]
        pf["is_double_gw"] = 0
        rec = pf[[c for c in keep if c in pf.columns] + ["is_double_gw_orig"]].copy()
        for arm, X in lists.items():
            m = make_model().fit(trc[X], trc["starts"])
            if arm == "base":
                rec["p_base"] = m.predict_proba(pf[X])[:, 1]
            else:
                rec[f"p_{arm}_dl"] = m.predict_proba(pf[X])[:, 1]
                pm = swap_in(pf, mw, crowd_cols[arm])
                rec[f"p_{arm}_mw"] = m.predict_proba(pm[X])[:, 1]
                rec[f"mw_present_{arm}"] = pm["cs_own_pct"].notna().to_numpy()
            if on_fit is not None:
                on_fit(season, k, arm, len(trc))
        outs.append(rec)
    return pd.concat(outs, ignore_index=True)


def cmd_fit(a):
    import crowd_block as cb
    if a.out.exists():
        raise FileExistsError(f"{a.out} exists -- a probe output is never written over")
    mw = pd.read_parquet(a.midweek)
    cs, fp = probe.build_frame(cb.build())               # the deadline-snapshot block, as the production code builds it
    keep = ["season", "element", "GW", "name", "position", "team", "starts", "minutes", "av_status_code"] + cf.CROWD + cf.RANKED
    outs, t0 = [], time.time()
    for season, tr in SEASONS:
        labelled = sorted(int(g) for g in cs.loc[(cs.season == season) & cs.starts.notna(), "GW"].unique())
        gws = [g for g in labelled if g >= FIRST_GW]
        res = walk_forward(cs, season, tr, gws, fp, mw, probe.m_ps, keep)
        outs.append(res)
        print(f"[{season}] gameweeks predicted {len(gws)} (first {gws[0]}, last {gws[-1]}); rows {len(res):,}; "
              f"rows with a midweek snapshot row {int(res.mw_present_raw.sum()):,}; done {time.time() - t0:.0f}s", flush=True)
    res = pd.concat(outs, ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(a.out, index=False)
    print(f"rows {len(res):,} -> {a.out}; total {time.time() - t0:.0f}s")


# ------------------------------------------------------------------ read
NB = 2000
LABELS = {"raw@midweek": "p_raw_mw", "rank@midweek": "p_rank_mw", "raw@deadline": "p_raw_dl", "rank@deadline": "p_rank_dl"}
TRUE_MIDWEEK_MAX_HOURS = 96.0


def shipping_form(brier_raw_mw, brier_rank_mw):
    """The pre-registered rule: RANK, unless RAW has the lower ALL-rows Brier at midweek in ALL the seasons."""
    seasons = sorted(brier_raw_mw)
    assert seasons == sorted(brier_rank_mw) and len(seasons) >= 1
    return "raw" if all(brier_raw_mw[s] < brier_rank_mw[s] for s in seasons) else "rank"


def true_midweek_gameweeks(timing):
    """{season: gameweeks whose 'midweek' snapshot really is one}: taken no more than 96 h before the deadline
    and after the previous gameweek's deadline. The side read of the report uses only these."""
    ok = timing[(timing["hours_before_deadline"] <= TRUE_MIDWEEK_MAX_HOURS) & (~timing["before_previous_deadline"].astype(bool))]
    return {s: sorted(int(g) for g in x["gw"]) for s, x in ok.groupby("season")}


def brier_parts(d, col):
    """Per gameweek (sorted): the sum of squared errors of `col` and the row count. A Brier score over any set of
    gameweeks is sum / count, so a bootstrap over gameweeks needs nothing else. Probabilities clipped as in
    m2_crowd_probe.metrics."""
    p = np.clip(d[col].to_numpy(float), 1e-6, 1 - 1e-6)
    g = pd.DataFrame({"GW": d["GW"].to_numpy(), "se": (p - d["starts"].to_numpy(float)) ** 2}).groupby("GW")["se"].agg(["sum", "size"])
    return g["sum"].to_numpy(float), g["size"].to_numpy(float)


def brier_delta_draws(d, col, picks):
    """ALL-rows Brier delta (`col` - baseline) on each bootstrap draw of whole gameweeks; `picks` is an
    (n draws, n gameweeks) array of positions into the season's sorted gameweeks."""
    (a, n), (b, _) = brier_parts(d, col), brier_parts(d, "p_base")
    return (a[picks].sum(axis=1) - b[picks].sum(axis=1)) / n[picks].sum(axis=1)


def read_block(res, seasons, title, nb=NB, seed=0):
    """Point metrics per season and slice for the baseline and the four crowd predictions; ALL-rows Brier
    deltas against the baseline with bootstrap intervals, per season and pooled; the rule's read."""
    print(f"\n=== {title} ===")
    rng = np.random.default_rng(seed)
    draws, brier = {k: {} for k in LABELS}, {k: {} for k in ("base", *LABELS)}
    for season in seasons:
        d = probe.scored(res, season)
        gws = sorted(int(g) for g in d["GW"].unique())
        for sn, sl in probe.slices(d).items():
            b = probe.metrics(sl, "p_base")
            line = f"[{season}] {sn:13s} n={len(sl):6d} | baseline Brier {b['brier']:.5f} logloss {b['logloss']:.5f} AUC {b['auc']:.4f}"
            for label, c in LABELS.items():
                m = probe.metrics(sl, c)
                line += f" | {label} Brier {m['brier']:.5f} ({m['brier'] - b['brier']:+.5f}) logloss {m['logloss']:.5f} AUC {m['auc']:.4f} ({m['auc'] - b['auc']:+.4f})"
                if sn == "ALL":
                    brier[label][season] = m["brier"]
            if sn == "ALL":
                brier["base"][season] = b["brier"]
            print(line, flush=True)
        picks = rng.integers(0, len(gws), (nb, len(gws)))
        for label, c in LABELS.items():
            dr = brier_delta_draws(d, c, picks)
            draws[label][season] = dr
            lo, hi = probe.interval(dr)
            print(f"[{season}] ALL-rows Brier delta, {label} - baseline: {brier[label][season] - brier['base'][season]:+.5f} [{lo:+.5f}, {hi:+.5f}] "
                  f"(gameweeks {len(gws)}, first {gws[0]}, last {gws[-1]})")
    pooled = {}
    for label in LABELS:
        p = probe.pooled([draws[label][s] for s in seasons])
        lo, hi = probe.interval(p)
        point = float(np.mean([brier[label][s] - brier["base"][s] for s in seasons]))
        pooled[label] = (point, lo, hi)
        print(f"[pooled {len(seasons)} seasons] ALL-rows Brier delta, {label} - baseline: {point:+.5f} [{lo:+.5f}, {hi:+.5f}]")
    print("--- the rule's read: ALL-rows Brier at midweek, raw against rank, by season ---")
    for s in seasons:
        print(f"[{s}] baseline {brier['base'][s]:.5f} | raw@midweek {brier['raw@midweek'][s]:.5f} | rank@midweek {brier['rank@midweek'][s]:.5f} | "
              f"raw lower than rank: {brier['raw@midweek'][s] < brier['rank@midweek'][s]}")
    form = shipping_form(brier["raw@midweek"], brier["rank@midweek"])
    point, lo, hi = pooled[f"{form}@midweek"]
    print(f"form by the rule on these gameweeks: {form.upper()} | that form against the baseline AT MIDWEEK, pooled ALL-rows Brier delta {point:+.5f} "
          f"[{lo:+.5f}, {hi:+.5f}] -> {'beats the baseline at midweek (interval entirely below 0)' if hi < 0 else 'HELPS ONLY NEAR THE DEADLINE (the interval is not entirely below 0)'}")
    return form, pooled


def cmd_read(a):
    res = pd.read_parquet(a.rows)
    seasons = [s for s, _ in SEASONS]
    print(f"rows {len(res):,} | by season {res.groupby('season').size().to_dict()} | gameweeks from {int(res.GW.min())} | "
          f"rows without a midweek snapshot row {int((~res.mw_present_raw).sum()):,}")
    if a.m2_rows is not None and Path(a.m2_rows).exists():
        m2 = pd.read_parquet(a.m2_rows)
        j = res.merge(m2[["season", "element", "GW", "p_base", "p_crowd", "p_rank"]], on=["season", "element", "GW"], how="left", suffixes=("", "_m2"))
        print("=== EXACTNESS: this run's deadline predictions against M2's saved rows (same data; the block built by the production code) ===")
        for mine, theirs in (("p_base", "p_base_m2"), ("p_raw_dl", "p_crowd"), ("p_rank_dl", "p_rank")):
            d = (j[mine] - j[theirs]).abs()
            print(f"   {mine} vs M2's {theirs.replace('_m2', '')}: rows joined {int(j[theirs].notna().sum()):,} of {len(j):,}; max |diff| {float(d.max()):.3e}")
    form, _ = read_block(res, seasons, "PRIMARY (the rule as written): every gameweek from GW2")
    print(f"\nSHIPPING FORM BY THE RULE: {form.upper()}")
    if a.timing is not None:
        ok = true_midweek_gameweeks(pd.read_csv(a.timing))
        keep = pd.concat([res[(res.season == s) & res.GW.isin(ok.get(s, []))] for s in seasons], ignore_index=True)
        kept = {s: sorted(int(g) for g in keep.loc[keep.season == s, "GW"].unique()) for s in seasons}
        print("\nside read -- gameweeks kept (midweek snapshot 72-96 h before the deadline and after the previous deadline): "
              + "; ".join(f"{s}: {len(kept[s])} (first {kept[s][0]}, last {kept[s][-1]})" for s in seasons))
        side, _ = read_block(keep, seasons, "SIDE READ (no rule): gameweeks with a true midweek snapshot only", seed=1)
        print(f"\nside read's form: {side.upper()} ({'the same as' if side == form else 'DIFFERENT FROM'} the rule's)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("fit"); f.add_argument("--midweek", type=Path, required=True); f.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("read"); r.add_argument("--rows", type=Path, required=True); r.add_argument("--m2-rows", type=Path, default=None)
    r.add_argument("--timing", type=Path, default=None, help="the timing table the build step wrote (for the true-midweek side read)")
    a = ap.parse_args()
    {"build": cmd_build, "fit": cmd_fit, "read": cmd_read}[a.cmd](a)


if __name__ == "__main__":
    main()
