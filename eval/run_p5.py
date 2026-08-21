# run_p5.py
# P5 -- the two small optimizer wins, measured under the FULL adopted system.
#
# Arms per season (gates flipped in-process; both rest False on disk):
#   bench : scoring.BENCH_ORDER_BY_PLAY  (bench order by p_play_any)
#   xi    : optimize.XI_TIEBREAK_P60     (XI tiebreak by p_60plus, eps=0.05)
#   both  : the two together (interaction visible vs the single arms)
#
# Config = the full-system reference cell: base opening (P1 closed), WC1@GW2
# (the better-supported end of the revised GW2-3 rule of record), WC2
# {32,31,32}, FH2 {29,29,34}, BB1+BB2 bench-aware ({7,7,10} base / {34,33,33}),
# H=6 decay=0.45. REFERENCE RUN REUSED: data/p1/fslog_{tag}_base_wc2.parquet.
#
# Both changes are deterministic overlays:
#   bench : changes autosub RESOLUTION only -- squads must be IDENTICAL to
#           the reference all season (asserted); points may differ from the
#           first differently-resolved autosub (reported).
#   xi/both: the eps-weight can flip tied XI (and in principle tied pick)
#           decisions -- first divergent gw for squads and for points is
#           reported, and the pre-divergence prefix is asserted identical.
#
# One parquet per (season, arm), atomic, skip-if-exists.
# Usage: uv run python eval/run_p5.py --season 2025-26

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import optimize  # noqa: E402
import scoring  # noqa: E402
import simulator  # noqa: E402

OUT = REPO / "data" / "p1"
H, DECAY = 6, 0.45
WC1 = 2
WC2 = {"2023-24": 32, "2024-25": 31, "2025-26": 32}
FH2 = {"2023-24": 29, "2024-25": 29, "2025-26": 34}
BB1 = {"2023-24": 7, "2024-25": 7, "2025-26": 10}     # base-opening weeks
BB2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}
ARMS = {"bench": (True, False), "xi": (False, True), "both": (True, True)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    a = ap.parse_args()
    season = a.season
    tag = season.replace("-", "_")

    ref = pd.read_parquet(OUT / f"fslog_{tag}_base_wc2.parquet")
    ref_elems = {int(r.gw): set(json.loads(r.elements))
                 for r in ref.itertuples()}

    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    df = simulator.load_season(walkforward_path=str(wf_path),
                               horizon_aware=True, season=season)

    for arm, (bench_on, xi_on) in ARMS.items():
        out = OUT / f"p5log_{tag}_{arm}.parquet"
        if out.exists():
            print(f"skip existing {out.name}", flush=True)
            continue
        scoring.BENCH_ORDER_BY_PLAY = bench_on
        optimize.XI_TIEBREAK_P60 = xi_on
        t0 = time.time()
        try:
            state, log = simulator.simulate_season(
                df, policy="mip", horizon=H, decay=DECAY,
                wildcard_gws=[WC1, WC2[season]], free_hit_gws=FH2[season],
                bench_boost_gw=[BB1[season], BB2[season]], verbose=False)
            log = log.copy()
            assert log["bench_order_by_play"].unique().tolist() == [bench_on]
            assert log["xi_tiebreak_p60"].unique().tolist() == [xi_on]
            # divergence vs the reference run
            first_sq = first_pt = None
            for r in log.itertuples():
                g = int(r.gw)
                if first_sq is None and set(r.elements) != ref_elems[g]:
                    first_sq = g
                if first_pt is None and int(r.points) != \
                        int(ref.loc[ref["gw"] == g, "points"].iloc[0]):
                    first_pt = g
            if arm == "bench":
                assert first_sq is None, (
                    f"bench arm changed SQUADS (first at GW{first_sq}) -- "
                    "bench order must not feed back into decisions")
            log["all_transfers"] = log["all_transfers"].map(json.dumps)
            log["elements"] = log["elements"].map(json.dumps)
            log["season"], log["arm"] = season, arm
            log["first_squad_divergence"] = first_sq if first_sq else -1
            log["first_points_divergence"] = first_pt if first_pt else -1
            log["wf_file"] = wf_path.name
            log["final_total"] = int(state.total_points)
            tmp = out.with_suffix(".tmp.parquet")
            log.to_parquet(tmp, index=False)
            tmp.replace(out)
            print(f"DONE {out.name}: total={int(state.total_points)} "
                  f"(ref {int(ref['final_total'].iloc[0])}) "
                  f"first_squad_div={first_sq} first_pts_div={first_pt} "
                  f"({(time.time() - t0) / 60:.1f} min)", flush=True)
        except Exception as e:
            print(f"FAILED {out.name}: {type(e).__name__}: {e}", flush=True)
        finally:
            scoring.BENCH_ORDER_BY_PLAY = False
            optimize.XI_TIEBREAK_P60 = False
    print(f"P5 WORKER COMPLETE {season}", flush=True)


if __name__ == "__main__":
    main()
