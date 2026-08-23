# gk_lambda_shrink.py
# GK investigation STEP 4 -- the untried lever (gk_investigation_log s9
# option 1): shrink the market lambda spread feeding the CONCEDED term only,
# and measure margin beta response. No simulations; pure re-measurement on
# the walk-forward files.
#
# The shrink: per (season, gw), lam' = m_gw + s * (opp_lambda - m_gw), where
# m_gw = the gameweek's cross-sectional mean of opp_lambda over unique teams
# (point-in-time safe -- the gw's own odds). Applied ONLY inside
# pts_conceded, recomputed exactly as assembly does:
# -E[floor(Poisson(lam' * minutes_frac)/2)]. p_cs and every other term
# untouched. DGW rows: the wf frame is per-gw collapsed (opp_lambda MEANed,
# minutes_frac and pts_conceded SUMMED), so the recompute is approximate on
# doubled rows; we therefore apply the DELTA recon(s) - recon(1) to
# e_points, which is exactly zero at s=1 -- the s=1 column IS the true
# canonical beta.
#
# Beta: through-origin pairwise margin slope, step 0, starter band
# (e_minutes >= 60), pairs within (gw, position), moment accumulation
# across gameweeks -- the margin-calibration convention. VALIDATED by
# reproducing two known values on preserved artefacts before anything new
# is quoted: 2025-26 baseline (no-D1) GK beta 0.847 and pre-blend Variant B
# GK beta 0.676.
#
# TUNING DISCIPLINE (binding): the sweep runs on 2023-24 and 2024-25 only.
# 2025-26 is measured at s=1.0 only (the open era-gap re-measurement).
# The chosen factors are written into gk_investigation_log BEFORE
# --holdout applies them to 2025-26 once. Selection rule, fixed before the
# sweep ran: per position, s minimising mean |beta - 1| over the two tuning
# seasons.
#
# Usage: uv run python eval/gk_lambda_shrink.py --tune
#        uv run python eval/gk_lambda_shrink.py --holdout --s-gk X --s-def Y

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
from assembly import _expected_floor_div  # noqa: E402  (the exact formula)

SWEEP = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]
TUNE_SEASONS = ["2023-24", "2024-25"]
HOLDOUT = "2025-26"


def load(season, path=None):
    tag = season.replace("-", "_")
    p = path or REPO / "data" / f"walkforward_h6_{tag}.parquet"
    wf = pd.read_parquet(p, columns=["cutoff", "gw", "element", "position",
                                     "team", "e_minutes", "e_points",
                                     "actual_points", "opp_lambda",
                                     "minutes_frac", "pts_conceded"])
    d = wf[wf["cutoff"] == wf["gw"]].copy()
    for c in ("e_minutes", "e_points", "actual_points", "opp_lambda",
              "minutes_frac", "pts_conceded"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["e_points"].notna()]
    return d


def beta(df, pos):
    """Through-origin pairwise slope within (gw, position), starter band."""
    g = df[(df["position"] == pos) & (df["e_minutes"] >= 60)]
    num = den = 0.0
    for _, grp in g.groupby("gw"):
        p = grp["e_points"].to_numpy(float)
        a = grp["actual_points"].fillna(0).to_numpy(float)
        n = len(p)
        if n < 2:
            continue
        num += n * (p * a).sum() - p.sum() * a.sum()
        den += n * (p * p).sum() - p.sum() ** 2
    return num / den if den else float("nan")


def shrunk_frame(d, s, positions):
    """Return a copy with e_points adjusted by the conceded-term delta at
    shrink factor s, applied to `positions` rows only."""
    out = d.copy()
    # per-gw cross-sectional team mean of opp_lambda
    team_lam = d.drop_duplicates(["gw", "team"])[["gw", "team", "opp_lambda"]]
    m = team_lam.groupby("gw")["opp_lambda"].mean().rename("m_gw")
    out = out.merge(m, on="gw", how="left")
    sel = out["position"].isin(positions) & out["opp_lambda"].notna() \
        & out["minutes_frac"].notna()
    lam = out.loc[sel, "opp_lambda"].to_numpy(float)
    mgw = out.loc[sel, "m_gw"].to_numpy(float)
    frac = out.loc[sel, "minutes_frac"].to_numpy(float)
    lam_s = mgw + s * (lam - mgw)
    recon_1 = -_expected_floor_div(lam * frac, 2)
    recon_s = -_expected_floor_div(lam_s * frac, 2)
    out.loc[sel, "e_points"] = out.loc[sel, "e_points"] \
        + (recon_s - recon_1)
    return out


def validate():
    """Reproduce two known betas on preserved artefacts before anything new."""
    checks = [
        ("2025-26 no-D1 baseline GK", "walkforward_h6_2526_baseline.parquet",
         "GK", 0.847),
        ("2025-26 pre-blend Variant B GK",
         "walkforward_h6_2025_26_prerateblend.parquet", "GK", 0.676),
    ]
    ok = True
    for label, fname, pos, expect in checks:
        d = load("2025-26", REPO / "data" / fname)
        b = beta(d, pos)
        good = abs(b - expect) < 0.005
        ok &= good
        print(f"  validate {label}: beta {b:.3f} vs recorded {expect} "
              f"{'OK' if good else 'MISMATCH'}")
    if not ok:
        raise SystemExit("beta methodology does NOT reproduce the recorded "
                         "values -- stopping before quoting anything new")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--s-gk", type=float)
    ap.add_argument("--s-def", type=float)
    a = ap.parse_args()

    print("beta methodology validation (preserved artefacts):")
    validate()

    if a.tune:
        print("\nERA GAP -- current canonical (post-blend, post-#15) betas, "
              "s=1.0, all seasons:")
        for season in TUNE_SEASONS + [HOLDOUT]:
            d = load(season)
            print(f"  {season}: GK {beta(d, 'GK'):.3f}   "
                  f"DEF {beta(d, 'DEF'):.3f}")
        print("\nSWEEP (tuning seasons ONLY -- 2025-26 stays sealed until "
              "a factor is pre-registered):")
        print(f"  {'s':>4s}  " + "  ".join(
            f"{s} GK / DEF" for s in TUNE_SEASONS))
        rows = {}
        for s in SWEEP:
            cells = []
            for season in TUNE_SEASONS:
                d = load(season)
                dg = shrunk_frame(d, s, ["GK"])
                dd = shrunk_frame(d, s, ["DEF"])
                bg, bd = beta(dg, "GK"), beta(dd, "DEF")
                rows.setdefault(s, {})[season] = (bg, bd)
                cells.append(f"{bg:.3f} / {bd:.3f}")
            print(f"  {s:4.1f}  " + "   ".join(cells))
        print("\nselection rule (fixed before the sweep): per position, "
              "argmin over s of mean |beta-1| across the tuning seasons")
        for pos, idx in (("GK", 0), ("DEF", 1)):
            best_s, best_v = None, 1e9
            for s in SWEEP:
                v = np.mean([abs(rows[s][t][idx] - 1) for t in TUNE_SEASONS])
                if v < best_v:
                    best_s, best_v = s, v
            print(f"  chosen s_{pos} = {best_s}  (mean |beta-1| = {best_v:.3f})")

    if a.holdout:
        assert a.s_gk is not None and a.s_def is not None
        print(f"\nHOLDOUT 2025-26, applied ONCE: s_GK={a.s_gk}, "
              f"s_DEF={a.s_def}")
        d = load(HOLDOUT)
        print(f"  before: GK {beta(d, 'GK'):.3f}   DEF {beta(d, 'DEF'):.3f}")
        dg = shrunk_frame(d, a.s_gk, ["GK"])
        dd = shrunk_frame(d, a.s_def, ["DEF"])
        print(f"  after : GK {beta(dg, 'GK'):.3f}   DEF {beta(dd, 'DEF'):.3f}")


if __name__ == "__main__":
    main()
