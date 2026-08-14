#!/usr/bin/env python
"""
Is the hit threshold miscalibrated?

Hypothesis: sharper predictions make the MIP over-trade. It pays a 4-point hit to
chase an edge that is inside its own error, so a better minutes model buys worse
season points. Availability hits went 20 -> 32 while the season fell 46.

METHOD, AND ONE THING IT DELIBERATELY DOES NOT DO
-------------------------------------------------
It does NOT try to identify "the 12 extra hits". By the time the arms differ on hits
they share 4 of 15 players, so a hit present in one arm and absent in the other is a
different season, not a different decision. That is the exact confound the
path-controlled harness exists to avoid, and pooling across arms sidesteps it: the
calibration of predicted-vs-realised transfer gain is a property of the POLICY, not
of the path either arm happened to take.

Predicted gain is reconstructed the way the MIP saw it -- decayed over the planning
horizon, from the cutoff's own predictions. Realised gain is the same window scored
on actuals. A transfer sold again inside the window keeps its full window credit,
which slightly flatters both arms equally.

Usage:
    uv run python analyse_hits.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "squad"))

HORIZON, DECAY = 3, 0.3
HIT_COST = 4

ARMS = {
    "baseline": REPO / "data" / "walkforward_h6_2526.parquet",
    "availability": REPO / "data" / "walkforward_h6_2526_av.parquet",
}
LOGS = REPO / "data" / "minutes_av_measurement_logs.parquet"


def transfer_table():
    logs = pd.read_parquet(LOGS)
    logs = logs[logs.rep == 0]
    rows = []
    for arm, path in ARMS.items():
        wf = pd.read_parquet(path)
        pred = wf.set_index(["cutoff", "gw", "element"])["e_points"]
        act = (wf[wf.horizon_step == 0]
               .set_index(["gw", "element"])["actual_points"].astype(float))
        arm_log = logs[logs.arm == arm]
        # A hit is charged on the transfers BEYOND the free allowance, so it is a
        # property of the gameweek's move as a whole, not of any single swap.
        for _, r in arm_log.iterrows():
            k = int(r.gw)
            pairs = list(r.all_transfers)
            paid_hit = float(r.hit) > 0
            for out_e, in_e in pairs:
                p_gain = r_gain = 0.0
                for h in range(HORIZON):
                    t, d = k + h, DECAY ** h
                    try:
                        p_gain += d * (pred.loc[(k, t, in_e)] - pred.loc[(k, t, out_e)])
                    except KeyError:
                        pass
                    try:
                        r_gain += float(act.get((t, in_e), np.nan)) - \
                                  float(act.get((t, out_e), np.nan))
                    except (TypeError, ValueError):
                        pass
                rows.append({
                    "arm": arm, "gw": k, "out": int(out_e), "in": int(in_e),
                    "n_in_move": len(pairs), "gw_hit_points": float(r.hit),
                    "paid_hit": paid_hit,
                    "pred_gain": p_gain, "real_gain": r_gain,
                })
    return pd.DataFrame(rows).dropna(subset=["pred_gain", "real_gain"])


def calibration(df, label):
    """Regress realised on predicted. Slope < 1 means predicted edges are inflated,
    and the break-even hit threshold is 4 / slope, not 4."""
    x, y = df.pred_gain.values, df.real_gain.values
    if len(x) < 3:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]
    return {
        "subset": label, "n": len(x),
        "mean_pred": round(float(x.mean()), 2),
        "mean_real": round(float(y.mean()), 2),
        "slope": round(float(slope), 3),
        "intercept": round(float(intercept), 2),
        "corr": round(float(r), 3),
        "breakeven_at_4": round(HIT_COST / slope, 2) if slope > 0.05 else np.inf,
    }


def main():
    df = transfer_table()
    df.to_parquet(REPO / "data" / "hit_analysis.parquet", index=False)

    print("=" * 92)
    print("EVERY TRANSFER, PREDICTED vs REALISED GAIN (H=3, decay=0.3 window)")
    print("=" * 92)
    rows = [calibration(df, "all transfers, both arms")]
    for arm in ARMS:
        rows.append(calibration(df[df.arm == arm], f"  {arm}"))
    rows.append(calibration(df[df.paid_hit], "moves that PAID a hit"))
    rows.append(calibration(df[~df.paid_hit], "moves within free allowance"))
    for arm in ARMS:
        sub = df[(df.arm == arm) & df.paid_hit]
        rows.append(calibration(sub, f"  {arm}, paid a hit"))
    print(pd.DataFrame([r for r in rows if r]).to_string(index=False))

    print("\n" + "=" * 92)
    print("THE HIT DECISION ITSELF — per gameweek that paid a hit")
    print("=" * 92)
    per_move = (df[df.paid_hit].groupby(["arm", "gw"])
                .agg(n=("in", "size"), hit_pts=("gw_hit_points", "first"),
                     pred=("pred_gain", "sum"), real=("real_gain", "sum"))
                .reset_index())
    per_move["pred_net"] = (per_move.pred - per_move.hit_pts).round(2)
    per_move["real_net"] = (per_move.real - per_move.hit_pts).round(2)
    per_move["pred"] = per_move.pred.round(2)
    per_move["real"] = per_move.real.round(2)
    print(per_move.to_string(index=False))
    print(f"\nmoves that paid a hit: {len(per_move)}")
    print(f"  predicted net of the hit : {per_move.pred_net.sum():+.1f} total, "
          f"{per_move.pred_net.mean():+.2f} mean")
    print(f"  realised  net of the hit : {per_move.real_net.sum():+.1f} total, "
          f"{per_move.real_net.mean():+.2f} mean")
    print(f"  realised net positive in : {(per_move.real_net > 0).sum()} of {len(per_move)}")

    print("\n" + "=" * 92)
    print("DOES THE THRESHOLD BITE? distribution of predicted gain near the 4-pt line")
    print("=" * 92)
    hits = df[df.paid_hit].groupby(["arm", "gw"]).pred_gain.sum()
    free = df[~df.paid_hit].groupby(["arm", "gw"]).pred_gain.sum()
    for label, s in [("hit moves", hits), ("free moves", free)]:
        print(f"{label:12s} n={len(s):3d}  "
              f"min {s.min():6.2f}  p25 {s.quantile(.25):6.2f}  "
              f"median {s.median():6.2f}  p75 {s.quantile(.75):6.2f}  max {s.max():6.2f}")
    near = hits[(hits > HIT_COST) & (hits < HIT_COST + 4)]
    print(f"\nhit moves with predicted gain in (4, 8]: {len(near)} of {len(hits)} "
          f"-- these are the ones a margin would flip")


if __name__ == "__main__":
    main()
