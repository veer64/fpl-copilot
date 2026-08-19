#!/usr/bin/env python
"""
walkforward_season.py -- the walk-forward harness for a season other than 2025-26.

M2, the multi-season port. Reuses squad/assembly.py::assemble_fixtures unchanged,
so there is still exactly ONE master equation; only the season-specific inputs
differ.

ERA-CORRECTNESS
---------------
Defensive contribution is a 2025-26 SCORING RULE. It did not exist earlier and
neither did the stat behind it -- `defensive_contribution` is entirely null before
2025-26, and core_insights matchstats only covers 2024-25 onward. So for every
earlier season the DC term is ZEROED, not defaulted to a base rate: a base rate
would award points under a rule that was not in force.

Verified rather than assumed: reconstructing 2023-24 `total_points` from its
components WITHOUT the DC term reconciles on 29,725 of 29,725 rows.

THE HARD CONSTRAINT ON HOW FAR BACK THIS GOES
---------------------------------------------
`starts` -- the P(start) target -- does not exist before 2022-23:

    2021-22       0 / 25,447 rows      0.0%
    2022-23  18,014 / 26,505 rows     68.0%   (GW1-15 quarantined, KNOWN_ISSUES #4)
    2023-24  29,725 / 29,725 rows    100.0%
    2024-25  27,605 / 27,605 rows    100.0%

So 2023-24 can train on 2022-23, and 2024-25 can train on both. 2022-23 has no
prior season carrying the label, and 2021-22 has no label at all -- neither can be
run without either training on the future or inventing the target from minutes,
and minutes cannot distinguish a subbed-off starter from an early substitute
(that is exactly why 2022-23 GW1-15 was quarantined in the first place).

Usage:
    uv run python eval/walkforward_season.py --season 2023-24 --horizon 6
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import assembly  # noqa: E402
import attacking_rates as rates_mod  # noqa: E402
import bonus as bonus_mod  # noqa: E402
import dixon_coles as dc_mod  # noqa: E402
import minutes as minutes_mod  # noqa: E402

BASE = str(REPO)
AVAILABILITY = True          # matches the 2025-26 canonical config
ODDS_HORIZON_GWS = 0         # fixed project decision; see eval/walkforward.py
ORDER = ["2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
         "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
# Seasons whose scoring includes the defensive-contribution rule.
DC_SEASONS = {"2025-26"}
# Seasons the P(start) label exists for, hence the only ones usable for training.
LABELLED = {"2022-23", "2023-24", "2024-25", "2025-26"}


def train_seasons_for(season):
    """Prior LABELLED seasons only. Never a future season -- that would be a leak
    of exactly the kind the walk-forward harness exists to prevent."""
    return [s for s in ORDER if s < season and s in LABELLED]


def crosswalk_for(season):
    """2025-26 keeps its hand-audited file; every other season uses the per-season
    build from eval/build_crosswalk.py."""
    if season == "2025-26":
        return pd.read_csv(REPO / "data" / "history" / "player_id_crosswalk_final.csv")
    p = REPO / "data" / "history" / f"crosswalk_{season.replace('-', '_')}.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} missing. Build it first:\n"
            f"    uv run python eval/build_crosswalk.py --season {season}")
    return pd.read_csv(p)


def walk_forward(season, cutoffs=None, horizon=6, verbose=True, save_path=None):
    tr = train_seasons_for(season)
    if not tr:
        raise ValueError(
            f"{season} has no prior season carrying the `starts` label, so the "
            "minutes model cannot be trained without using the future. See the "
            "module docstring.")
    dc_enabled = season in DC_SEASONS

    df = pd.read_parquet(BASE + r"\data\history\all_seasons_fixed.parquet")
    cw = crosswalk_for(season)

    v = df[df["season"] == season].copy()
    v["kick"] = pd.to_datetime(v["kickoff_time"])
    gw_start = v.groupby("GW")["kick"].min().sort_index()
    gw_end = v.groupby("GW")["kick"].max().sort_index()
    all_gws = sorted(gw_start.index.astype(int))
    if cutoffs is None:
        cutoffs = all_gws

    if verbose:
        print(f"season {season}: train on {tr}, DC rule {'ON' if dc_enabled else 'OFF'}, "
              f"{len(all_gws)} gameweeks, crosswalk {len(cw)} rows")

    out = []
    for k in cutoffs:
        t0 = time.time()
        # Attacking rates: under the k=8 blend these are CUTOFF-DEPENDENT
        # (current-season form accumulates gameweek by gameweek), so they are
        # fetched per cutoff with up_to_gw=k. Legacy static path ignores
        # up_to_gw, so this call site is correct under either gate setting.
        rates, priors = rates_mod.get_rates(season, up_to_gw=k)
        cutoff_date = gw_start.loc[k].tz_localize(None)
        targets = [g for g in all_gws if k <= g < k + horizon]

        m_k = minutes_mod.get_minutes(
            up_to_gw=k, predict_gws=[k], per_fixture=True,
            availability=AVAILABILITY, train_seasons=tr, predict_season=season)
        bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = bonus_mod.get_bonus_model(
            up_to_gw=k, train_until=tr[-1], predict_season=season)

        last_priced = min(k + ODDS_HORIZON_GWS, max(all_gws))
        odds_until = gw_end.loc[last_priced].tz_localize(None)
        f_k = dc_mod.get_fixtures(predict_season=season, cutoff_date=cutoff_date,
                                  odds_available_until=odds_until)

        if len(targets) > 1:
            frames = []
            for g in targets:
                f = m_k[["element", "name", "position", "p_start", "p60",
                         "e_minutes"]].copy()
                f["gw"] = g
                frames.append(f)
            m_k = pd.concat(frames, ignore_index=True)

        a_k = assembly.collapse_to_gameweek(
            assembly.assemble_fixtures(
                df, cw, m_k, rates, priors, f_k,
                pd.DataFrame(columns=["player_id", "gw", "p_dc_hit"]),
                bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean,
                gws=targets, season=season, dc_enabled=dc_enabled))
        a_k["cutoff"] = k
        a_k["horizon_step"] = a_k["gw"] - k
        out.append(a_k)
        if verbose:
            print(f"  cutoff GW{k:2d}: {len(a_k):5d} rows, {time.time()-t0:.1f}s",
                  flush=True)

    result = pd.concat(out, ignore_index=True)
    # Provenance on every row -- a file must always describe how it was made.
    result["season_label"] = season
    result["minutes_availability"] = bool(AVAILABILITY)
    result["odds_horizon_gws"] = int(ODDS_HORIZON_GWS)
    result["dgw_handling"] = "per_fixture"
    result["dc_rule_active"] = bool(dc_enabled)
    # D1 scoring terms in the equation or not. See KNOWN_ISSUES #13: the terms
    # once entered assembly.py silently and "baseline" measurements were taken on
    # files that carried them. Sourced from the same constant that gates the terms.
    result["d1_terms_active"] = bool(assembly.D1_TERMS_ACTIVE)
    # CS/conceded unified on opp_lambda or not. Equation-changing flag ->
    # stamped (the #13 lesson). See assembly.CS_UNIFIED.
    result["cs_unified"] = bool(assembly.CS_UNIFIED)
    # Attacking-rate source: k=8 blend vs legacy static. See
    # attacking_rates.RATE_BLEND_ACTIVE and Logs/rate_blend_log.md.
    result["rate_blend_active"] = bool(rates_mod.RATE_BLEND_ACTIVE)
    result["rate_blend_k"] = float(rates_mod.RATE_BLEND_K)
    result["train_seasons"] = ",".join(tr)

    if save_path:
        result.to_parquet(save_path, index=False)
        if verbose:
            print(f"\nSaved -> {save_path}")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", required=True)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--cutoffs", type=int, nargs="*", default=None)
    args = ap.parse_args()
    tag = args.season.replace("-", "_")
    out = REPO / "data" / f"walkforward_h{args.horizon}_{tag}.parquet"
    walk_forward(args.season, cutoffs=args.cutoffs, horizon=args.horizon,
                 save_path=str(out))


if __name__ == "__main__":
    main()
