# measure_p3.py
# Measurement for the P3 early-hit-tolerance sweep (eval/run_p3.py).
# Read-only; tolerates a partial grid. Bar 4 = the reused full-system
# reference cells (fslog_base_wc{2,6}).
#
# Per (season, wc1, bar):
#   - hits taken in GW2-7 (count, points paid)
#   - per-decision, path-free transfer quality for EARLY transfers (GW2-7,
#     excluding the wildcard week -- those are free and not the object):
#     predicted gain = decayed H-window sum at the transfer's own cutoff
#     (in - out, decay 0.45, the transfer-sweep E1 convention); realized
#     gain = undecayed next-3-gw actual sum (E2). corr(pred, realized),
#     n stated, cells with n < 4 printed but flagged unusable.
#   - full distribution of realized gains (all early transfers, and the
#     hit-week subset separately -- the marginal decisions the discount buys)
#   - points GW1-10 vs the FPL average manager
#   - season total (STANDARD FRAMING: identifies the config, ranks nothing)
#
# The hit-threshold log's selection trap applies in mirror image: at lower
# bars the ADMITTED marginal hits have lower predicted gains, so falling
# survivor correlations are expected mechanically -- the decisive endpoint
# is the realized-gain distribution of what the discount ADDS.
#
# Usage: uv run python eval/measure_p3.py

import json
import lzma
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "data" / "p1"
CACHE = REPO / "fplcache" / "cache"
SEASONS = ["2023-24", "2024-25", "2025-26"]
WCS = [2, 6]
BARS = [4, 3, 2, 1]
DECAY, H = 0.45, 6
SNAP = {"2023-24": (2024, 5, 30), "2024-25": (2025, 5, 30),
        "2025-26": (2026, 5, 30)}
AVG_SUM_EXPECT = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}


def avg_manager(season):
    y, m, d = SNAP[season]
    snap = sorted((CACHE / str(y) / str(m) / str(d)).glob("*.json.xz"))[-1]
    with lzma.open(snap) as f:
        events = json.load(f)["events"]
    assert len(events) == 38 and all(e["finished"] for e in events)
    per_gw = {e["id"]: e["average_entry_score"] for e in events}
    assert sum(per_gw.values()) == AVG_SUM_EXPECT[season]
    return per_gw


def transfer_metrics(log, wf, act, wc1):
    """Early (GW2-7, non-wildcard-week) transfers with predicted and
    realized gains, plus whether their week paid a hit."""
    out = []
    for r in log.itertuples():
        g = int(r.gw)
        if not (2 <= g <= 7) or g == wc1:
            continue
        transfers = json.loads(r.all_transfers) \
            if isinstance(r.all_transfers, str) else r.all_transfers
        cut = wf[wf["cutoff"] == g]
        for out_e, in_e in transfers:
            pred = 0.0
            for k in range(H):
                step = cut[cut["gw"] == g + k]
                ei = step.loc[step["element"] == in_e, "e_points"]
                eo = step.loc[step["element"] == out_e, "e_points"]
                pred += (DECAY ** k) * (float(ei.iloc[0]) if len(ei) else 0.0)
                pred -= (DECAY ** k) * (float(eo.iloc[0]) if len(eo) else 0.0)
            real = 0.0
            for gg in range(g, min(g + 3, 39)):
                a = act[act["gw"] == gg]
                ai = a.loc[a["element"] == in_e, "actual_points"]
                ao = a.loc[a["element"] == out_e, "actual_points"]
                real += (float(ai.iloc[0]) if len(ai) else 0.0) \
                    - (float(ao.iloc[0]) if len(ao) else 0.0)
            out.append({"gw": g, "pred": pred, "real": real,
                        "hit_week": int(r.hit) > 0})
    return pd.DataFrame(out)


def dist_str(x):
    if len(x) == 0:
        return "n=0"
    q = np.percentile(x, [0, 25, 50, 75, 100])
    return (f"n={len(x)}: min {q[0]:+.0f} q25 {q[1]:+.0f} med {q[2]:+.0f} "
            f"q75 {q[3]:+.0f} max {q[4]:+.0f} | pos {np.mean(x > 0):.0%} "
            f"beat4 {np.mean(x > 4):.0%}")


def main():
    pooled = {}
    for season in SEASONS:
        tag = season.replace("-", "_")
        avg = avg_manager(season)
        a10 = sum(avg[g] for g in range(1, 11))
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "e_points",
                                      "actual_points"])
        act = wf.drop_duplicates(subset=["gw", "element"]).copy()
        act["actual_points"] = pd.to_numeric(act["actual_points"],
                                             errors="coerce").fillna(0)
        print("=" * 96)
        print(f"SEASON {season}")
        print("=" * 96)
        for wc1 in WCS:
            print(f"\n-- WC1 @ GW{wc1} --")
            for bar in BARS:
                p = (P1 / f"fslog_{tag}_base_wc{wc1}.parquet" if bar == 4
                     else P1 / f"p3log_{tag}_wc{wc1}_bar{bar}.parquet")
                if not p.exists():
                    print(f"  bar {bar}: MISSING {p.name}")
                    continue
                d = pd.read_parquet(p)
                early = d[(d["gw"] >= 2) & (d["gw"] <= 7)]
                hp = int(early["hit"].sum())
                tm = transfer_metrics(d, wf, act, wc1)
                pooled.setdefault((wc1, bar), []).append(tm)
                n = len(tm)
                corr = (np.corrcoef(tm["pred"], tm["real"])[0, 1]
                        if n >= 4 else float("nan"))
                p10 = int(d.loc[d["gw"] <= 10, "points"].sum())
                total = int(d["final_total"].iloc[0])
                print(f"  bar {bar}: hits GW2-7 {hp // 4} ({hp} pts) | "
                      f"early transfers n={n} corr(pred,real)="
                      f"{corr:.2f}" + ("" if n >= 4 else " [n<4 UNUSABLE]")
                      + f" | GW1-10 vs avg {p10 - a10:+d} | total {total}")
                print(f"         all early:  {dist_str(tm['real'].values)}")
                hits_only = tm[tm["hit_week"]]
                print(f"         hit weeks:  "
                      f"{dist_str(hits_only['real'].values)}")
        print()
    print("=" * 96)
    print("POOLED across seasons (per wc1 x bar): corr over all early "
          "transfers, hit-week realized distribution")
    print("=" * 96)
    for wc1 in WCS:
        for bar in BARS:
            if (wc1, bar) not in pooled:
                continue
            tm = pd.concat(pooled[(wc1, bar)], ignore_index=True)
            corr = np.corrcoef(tm["pred"], tm["real"])[0, 1] if len(tm) >= 4 \
                else float("nan")
            print(f"  wc{wc1} bar {bar}: n={len(tm)} corr {corr:.2f} | "
                  f"hit weeks: {dist_str(tm[tm['hit_week']]['real'].values)}")
    print("\nFraming: totals are single draws (sd ~60), identify only. "
          "Transfer metrics are per-decision and\npath-free WITHIN each arm; "
          "arms diverge from GW2, so cross-arm 'same transfer' comparisons "
          "do not exist\n(the hit-threshold log's caveat). Falling survivor "
          "corr at lower bars is the selection trap in mirror.")


if __name__ == "__main__":
    main()
