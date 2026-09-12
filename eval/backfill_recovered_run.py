"""RECOVERED RUN backfill -- rebuild one deadline gameweek's PRODUCTION frame on the
current code, solve it, stage the frame and prices on the volume, and write it to
Postgres as a RECOVERED run with an explicit note. NOT a live-at-deadline build:
the runner (eval/run_live_deadline.py) is the only thing that writes those.

First use 2026-09-11: the GW3 backfill (run_id 3) had been built on 2026-09-04
with pre-fix code (git 89f6406) on frames carrying LEAKAGE.md items 6-9 and
BOTH configs; the app served it. This regenerates GW3 from the same pre-deadline
inputs on the volume (availability merge, odds, stack) under the deployed code
and config_roles (baseline only) and records the lineage in the note. Every
predictions row is keyed by run_id, so the old row stays as history.

Usage (server, inside the scheduler image):
  uv run python eval/backfill_recovered_run.py --season 2026-27 --gw 3 --note "..."
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "squad"))
import config_roles as cr  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--note", required=True)
    a = ap.parse_args()
    season, gw = a.season, a.gw
    tag = season.replace("-", "_")

    import live_deadline as ld
    import simulator as sim
    from optimize import optimize_squad
    import pulp
    import db_write

    frames, findings_by = {}, {}
    for config in cr.CONFIGS:
        frame, findings = ld.build_deadline_frame(season, gw, strict=True, config=config, horizon=6)
        frames[config] = frame
        findings_by[config] = list(findings)
        print(f"{config}: {len(frame)} rows; findings: {len(findings)}")

    live = REPO / "data" / "live"
    hist = pd.read_parquet(REPO / "data" / "history" / f"fpl_api_{tag}.parquet",
                           columns=["season", "element", "round", "value"])
    skel = pd.read_parquet(REPO / "data" / "history" / f"forward_skeleton_{tag}.parquet",
                           columns=["season", "element", "round", "value"])
    tmp_hist = live / f"_tmp_prices_{tag}.parquet"
    pd.concat([hist, skel], ignore_index=True).to_parquet(tmp_hist, index=False)

    av = pd.read_parquet(REPO / "data" / f"availability_{season[2:4]}{season[5:7]}.parquet")
    av = av[av["gw"] == gw]
    avmap = {int(r["element"]): (r.get("asof_status"), r.get("asof_chance_of_playing_this_round"),
                                 str(r.get("asof_news") or "")) for _, r in av.iterrows()}

    teams = {}
    for config, frame in frames.items():
        fp = live / f"_tmp_frame_{config}.parquet"
        f2 = frame.copy()
        for c in ("actual_points", "minutes"):
            if c not in f2.columns:
                f2[c] = float("nan")
        f2.to_parquet(fp, index=False)
        df = sim.load_season(walkforward_path=str(fp), history_path=str(tmp_hist),
                             horizon_aware=True, season=season)
        pool = sim.gw_slice(df, gw, cutoff=gw)
        prob, sol = optimize_squad(pool)
        assert pulp.LpStatus[prob.status] == "Optimal", pulp.LpStatus[prob.status]
        team = sim.solution_to_squad(pool, sol)
        teams[config] = team
        print(f"{config}: captain {team.loc[team['role'] == 'CAPTAIN', 'name'].iloc[0]}, "
              f"cost {team['value'].sum() / 10:.1f}")

    price_df = pd.read_parquet(tmp_hist)
    price_map = dict(zip(price_df[price_df["round"] == gw]["element"].astype(int),
                         price_df[price_df["round"] == gw]["value"].astype(int)))
    run_id = db_write.write_run(season, gw, frames, teams, findings_by, started_at=None,
                                recovered=True, credits_remaining=None, note=a.note,
                                availability=avmap, prices=price_map,
                                kind="recovered", slot=f"recovered:GW{gw}", attempt=1)
    print(f"Postgres run_id {run_id} written (recovered=True; configs {list(frames)})")


if __name__ == "__main__":
    main()
