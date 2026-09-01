"""FORWARD-GAMEWEEK SKELETON: player-fixture rows for gameweeks the master does
not carry yet -- the last structural input of a live horizon-6 frame. The master
gains a gameweek only after it is played; walk_forward derives its targets and
kickoff windows from the master, minutes.py predicts for the master's rows at the
predict gameweek, and assembly builds its row universe from the master -- so
without forward rows a live 2026-27 horizon-6 build silently collapses to the
played gameweeks (and a live unplayed DEADLINE gameweek has no step 0 at all).

FIXTURES-FIRST -- the load-bearing design choice (Logs/, forward-skeleton
investigation): rows are constructed per FIXTURE from the FPL fixtures/ endpoint,
never per (player, GW) with the calendar joined afterwards. A team with two
fixtures in an event yields two rows per player with distinct fixture ids and
real kickoff times; a team with none yields no rows. Doubles and blanks are
reproduced by construction, exactly as the master represents them.

POSTPONED fixtures (event null / kickoff_time null) belong to no gameweek and are
EXCLUDED, never assigned -- listed in provenance with their ids so their
gameweek's under-count is visible rather than silently read as a blank. They
enter on a later refresh when FPL reschedules them.

WHAT A FORWARD ROW CARRIES: element, name, position, team, opponent_team, GW,
round, fixture, was_home, kickoff_time (identity + fixture geometry) and value
(today's price -- the simulator's budget arithmetic only). Every measurement
column (minutes, starts, total_points, bps, ...) is NaN: those are actuals that
feed diagnostics, never e_points, and NaN is correct. Stat columns that are
int64 in the master are stored float64 here (int64 cannot hold NA);
season_stack.load_stack's concat upcasts uniformly.

INFORMATION-SET LIMITS, recorded in provenance rather than hidden: value is the
price AS OF THE PULL (drift inside the horizon is unknowable); club assignment
is bootstrap's CURRENT squad (a player who moves inside a transfer window is
mis-assigned until the next refresh). Both are the correct information set for a
live decision and differ from what backtest frames carried.

DERIVED STATE: fully regenerated per pull (fixtures get rescheduled); the
archive files are never touched. The provenance sidecar stores the fixture
calendar snapshot (id, event, kickoff_time) the skeleton was built from --
live_deadline's strict re-pull check compares a fresh pull against it at
decision time (the #14 class: a moved kickoff shifts match_date and silently
drops the Dixon-Coles join).

BACKFILL VERIFICATION (--backfill): build a 2025-26 forward skeleton at cutoff k
from the final fixture calendar plus identity-as-of-k, compare against the
master's actual rows for the horizon window. MUST match: row-set on (element,
fixture) up to squad churn, and team/opponent_team/was_home/kickoff_time/position
on the intersection. MEASURED, not failed on: squad churn, value drift, position
reclassifications. RESIDUAL RISK, stated plainly: only the FINAL 2025-26
calendar exists -- what the endpoint showed at cutoff k does not -- so
calendar-as-of-cutoff fidelity (reschedules) is historically untestable; the
strict re-pull check is the live mitigation.

Usage:
  uv run python eval/build_forward_skeleton.py --season 2026-27
  uv run python eval/build_forward_skeleton.py --backfill --season 2025-26 --cutoff 20
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
API = "https://fantasy.premierleague.com/api"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot ingestion; weekly; contact: repo owner)"}
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
H = 6

sys.path.insert(0, str(REPO / "squad"))
from season_stack import stack_path  # noqa: E402

# identity + geometry a forward row carries; everything else is NaN measurement
CARRIED = ["season", "element", "GW", "round", "fixture", "name", "position", "team",
           "opponent_team", "was_home", "kickoff_time", "value"]


def get_json(path):
    req = urllib.request.Request(f"{API}{path}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _master_schema():
    return pd.read_parquet(stack_path()).iloc[0:0]


def skeleton_rows(fixtures, squads, schema, season, known_fixture_ids, opp_ids):
    """The pure construction. fixtures: iterable of dicts with id, event,
    kickoff_time, team_h, team_a (team NAMES). squads: {team_name: [{element,
    name, position, value}, ...]}. opp_ids: team name -> FPL team id (the
    master's opponent_team column is the int id, not the name). Returns
    (DataFrame in the master schema, postponed list, skipped-known count).
    Fixtures-first: iterate FIXTURES, emit one row per squad member per side."""
    rows, postponed, n_known = [], [], 0
    for f in fixtures:
        if f.get("event") is None or f.get("kickoff_time") is None:
            postponed.append(int(f["id"]))       # belongs to NO gameweek -- excluded, not assigned
            continue
        if int(f["id"]) in known_fixture_ids:
            n_known += 1                          # the master already carries it (played)
            continue
        for side, team, opp in (("home", f["team_h"], f["team_a"]),
                                ("away", f["team_a"], f["team_h"])):
            for p in squads.get(team, []):
                rows.append({
                    "season": season, "element": int(p["element"]),
                    "GW": int(f["event"]), "round": int(f["event"]),
                    "fixture": int(f["id"]), "name": p["name"], "position": p["position"],
                    "team": team, "opponent_team": int(opp_ids[opp]), "was_home": side == "home",
                    "kickoff_time": f["kickoff_time"], "value": int(p["value"]),
                })
    df = pd.DataFrame(rows, columns=CARRIED) if rows else pd.DataFrame(columns=CARRIED)
    for c in schema.columns:                      # full master schema; measurement cols NaN
        if c not in df.columns:
            df[c] = pd.NA
    df = df[list(schema.columns)]
    for c in schema.columns:
        want = str(schema[c].dtype)
        if want.startswith("int") and c not in CARRIED:
            want = "float64"                      # int64 cannot hold NA (stated in the docstring)
        try:
            df[c] = df[c].astype(want)
        except (TypeError, ValueError):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(want)
    assert not df.duplicated(["element", "fixture"]).any()
    return df, postponed, n_known


def build_live(season):
    assert season == "2026-27", "the live skeleton is for the season in progress"
    bs = get_json("/bootstrap-static/")
    teams = {t["id"]: t["name"] for t in bs["teams"]}
    squads = {}
    for m in bs["elements"]:
        squads.setdefault(teams[m["team"]], []).append(dict(
            element=m["id"], name=f"{m['first_name']} {m['second_name']}",
            position=POS[m["element_type"]], value=m["now_cost"]))
    fx = get_json("/fixtures/")
    fixtures = [dict(id=f["id"], event=f["event"], kickoff_time=f["kickoff_time"],
                     team_h=teams[f["team_h"]], team_a=teams[f["team_a"]]) for f in fx]
    master = pd.read_parquet(stack_path(), columns=["season", "fixture"])
    known = set(master.loc[master["season"] == season, "fixture"].astype(int))
    opp_ids = {t["name"]: t["id"] for t in bs["teams"]}
    df, postponed, n_known = skeleton_rows(fixtures, squads, _master_schema(), season, known, opp_ids)
    out = HIST / f"forward_skeleton_{season.replace('-', '_')}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    prov = dict(
        season=season, pulled_at=datetime.now(timezone.utc).isoformat(),
        rows=len(df), fixtures_forward=int(df["fixture"].nunique()),
        fixtures_already_in_master=n_known,
        postponed_excluded=postponed,
        gws_covered=sorted(int(g) for g in df["GW"].unique()),
        information_set=dict(
            value="now_cost at pull time -- price drift inside the horizon is unknowable",
            club_assignment="bootstrap current squads -- transfer-window moves mis-assigned until refresh"),
        # the calendar snapshot the strict re-pull check compares against
        calendar={str(f["id"]): [f["event"], f["kickoff_time"]] for f in fixtures},
    )
    out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    print(f"-> {out.name}: {len(df)} forward rows, {prov['fixtures_forward']} fixtures, "
          f"gws {prov['gws_covered'][0]}..{prov['gws_covered'][-1]}; "
          f"{n_known} played fixtures skipped; postponed excluded: {postponed or 'none'}")
    return out


def backfill(season, cutoff):
    """Verification: skeleton from (final calendar + identity-as-of-cutoff) vs the
    master's actual rows for the horizon window. Reports; only construction
    defects fail (as asserts in the comparison the tests reuse)."""
    tag = season.replace("-", "_")
    df = pd.read_parquet(stack_path())
    s = df[df["season"] == season].copy()
    s["GW"] = s["GW"].astype(int)
    window = [g for g in sorted(s["GW"].unique()) if cutoff < g < cutoff + H]

    # calendar from the master's own future rows (the only historical calendar held)
    fut = s[s["GW"].isin(window)]
    cal = {}
    for fid, grp in fut.groupby("fixture"):
        home = grp.loc[grp["was_home"], "team"].iloc[0]
        away = grp.loc[~grp["was_home"], "team"].iloc[0]
        cal[int(fid)] = dict(id=int(fid), event=int(grp["GW"].iloc[0]),
                             kickoff_time=grp["kickoff_time"].iloc[0], team_h=home, team_a=away)

    # identity as of the cutoff: each element's latest appearance <= cutoff
    past = s[s["GW"] <= cutoff].sort_values(["element", "GW"])
    ident = past.groupby("element").tail(1)
    squads = {}
    for _, r in ident.iterrows():
        squads.setdefault(r["team"], []).append(dict(
            element=int(r["element"]), name=r["name"], position=r["position"], value=int(r["value"])))

    # name -> FPL team id, derived from the master's own (team, opponent pair) rows:
    # the id of team X is the opponent_team value on rows whose OPPONENT is X.
    opp_ids = {}
    for fid, grp in fut.groupby("fixture"):
        hrow = grp[grp["was_home"]].iloc[0]
        arow = grp[~grp["was_home"]].iloc[0]
        opp_ids[arow["team"]] = int(hrow["opponent_team"])
        opp_ids[hrow["team"]] = int(arow["opponent_team"])
    skel, postponed, _ = skeleton_rows(list(cal.values()), squads, _master_schema(), season, set(), opp_ids)
    actual = fut.copy()

    key = ["element", "fixture"]
    # mirror assembly's documented dedup: elements 100/391-class rows repeat the
    # SAME fixture id byte-identically (a recording defect, not a double); counted
    n_dupes = int(actual.duplicated(key).sum())
    actual = actual.drop_duplicates(key, keep="first")
    sk = skel.set_index(key)
    ak = actual.set_index(key)
    both = sk.index.intersection(ak.index)
    only_skel = sk.index.difference(ak.index)     # departed / moved players (churn)
    only_master = ak.index.difference(sk.index)   # joiners / promoted-from-nowhere (churn)

    # Club assignment is a MEASURED information-set limit, and its rarest form is a
    # player who moved inside the window whose OLD and NEW clubs then met: the same
    # (element, fixture) key appears on both sides with the club columns differing
    # (2025-26 exhibit: Ward-Prowse, West Ham -> Burnley, fixture 244). Those rows
    # are CHURN, not construction defects -- the construction claim (fixture
    # geometry given a club assignment) is tested where the assignment agrees.
    club_moved = sk.loc[both, "team"].astype(str) != ak.loc[both, "team"].astype(str)
    agreed = both[~club_moved.values]
    n_moved_met = int(club_moved.sum())
    if 0 < n_moved_met <= 5:
        for (el, fid) in both[club_moved.values]:
            print(f"    churn (moved within window, old and new clubs MET): element {el} fixture {fid}: "
                  f"skeleton {sk.loc[(el, fid), 'team']!r} vs master {ak.loc[(el, fid), 'team']!r} "
                  f"({ak.loc[(el, fid), 'name']!r})")

    # THE CONSTRUCTION CLAIMS -- these must hold exactly where the club assignment agrees
    mism = {}
    for c in ["team", "opponent_team", "was_home", "kickoff_time", "position"]:
        a, b = sk.loc[agreed, c], ak.loc[agreed, c]
        bad = a.astype(str) != b.astype(str)
        mism[c] = int(bad.sum())
        if 0 < mism[c] <= 5 and c != "position":     # identify, never hide (position is MEASURED)
            for (el, fid), sv in a[bad].items():
                print(f"    MISMATCH {c} at element {el} fixture {fid}: "
                      f"skeleton {sv!r} vs master {ak.loc[(el, fid), c]!r} "
                      f"(name {ak.loc[(el, fid), 'name']!r})")
    mism.pop("team")                                  # identical on `agreed` by construction of the split
    # doubles/blanks by construction: per-(element, GW) row counts must match on shared players
    d_sk = skel[skel["element"].isin(actual["element"])].groupby(["element", "GW"]).size()
    d_ak = actual[actual["element"].isin(skel["element"])].groupby(["element", "GW"]).size()
    dgw_join = d_sk.to_frame("n_skel").join(d_ak.to_frame("n_actual"), how="inner")
    n_dgw_mismatch = int((dgw_join["n_skel"] != dgw_join["n_actual"]).sum())

    # MEASURED, not failed on
    vd = (sk.loc[agreed, "value"].astype(float) - ak.loc[agreed, "value"].astype(float))
    pos_reclass = mism.pop("position")

    print(f"\nBACKFILL {season} cutoff GW{cutoff} (window GW{window[0]}-GW{window[-1]}, "
          f"{len(cal)} fixtures{' incl. a DOUBLE' if max(actual.groupby('GW')['fixture'].nunique()) > 10 else ''}):")
    print(f"  row set: {len(both)} shared / {len(only_skel)} only-skeleton (departed) / "
          f"{len(only_master)} only-master (joined) -- churn {len(only_skel) + len(only_master)} "
          f"of {len(ak)} actual rows ({(len(only_skel) + len(only_master) + n_moved_met) / len(ak):.1%} "
          f"churn incl. {n_moved_met} moved-within-window-and-met)"
          + (f"; {n_dupes} byte-identical duplicate master row(s) dropped (the 100/391 recording defect)"
             if n_dupes else ""))
    print(f"  construction columns on the intersection -- team/opp/was_home/kickoff mismatches: {mism} "
          f"({'ALL EXACT' if not any(mism.values()) else '*** MISMATCH ***'})")
    print(f"  per-(element, GW) fixture-count identity (doubles/blanks): {n_dgw_mismatch} mismatches "
          f"on {len(dgw_join)} pairs; max fixtures/gw in window: "
          f"{int(actual.groupby(['element', 'GW']).size().max())}")
    print(f"  MEASURED value drift (price-as-of-k minus realised): mean {vd.mean():+.2f}, "
          f"nonzero {(vd != 0).mean():.1%}, p95 |drift| {vd.abs().quantile(0.95):.1f}, max |{vd.abs().max():.0f}|")
    print(f"  MEASURED position reclassifications: {pos_reclass}")
    ok = not any(mism.values()) and n_dgw_mismatch == 0
    print(f"  CONSTRUCTION: {'VERIFIED' if ok else 'FAILED'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--cutoff", type=int, default=None)
    a = ap.parse_args()
    if a.backfill:
        assert a.cutoff is not None
        ok = backfill(a.season, a.cutoff)
        sys.exit(0 if ok else 1)
    build_live(a.season)


if __name__ == "__main__":
    main()
