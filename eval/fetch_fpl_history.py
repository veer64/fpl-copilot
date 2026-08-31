"""FPL-API ingestion that replaces vaastav for 2026-27 -- INGESTION ONLY (no modelling change, no DC source change). Pulls ONE completed gameweek from the official API and emits player-FIXTURE rows in the EXACT schema of data/history/all_seasons_fixed.parquet (columns, order and dtypes are read from that file at runtime, never hardcoded). Verified 2026-08-31: the API reproduces every modelling-read column of vaastav's 2026-27 GW1 at 100.00% exact match at both grains.

SOURCES
  bootstrap-static/          name (first + " " + second), position (element_type), team names, event flags
  fixtures/                  fixture id -> (team_h, team_a, event); the player's TEAM is derived from the
                             fixture he appears in (team_h if was_home else team_a), NOT from bootstrap's
                             current-team field -- bootstrap `team` is as-of pull time and goes stale across
                             transfers (measured 98.52% after one window week); the fixture is as-of the match
                             by construction, so retro backfills are safe.
  element-summary/{id}/      the per-FIXTURE rows (one HTTP call per element): every stat column incl.
                             `starts`, `defensive_contribution` + components, and `value` -- the price FPL
                             FIXED for that gameweek (proven == vaastav's), never the live price.
  event/{gw}/live/           cross-check only: per-gameweek sums of the emitted rows are asserted equal to
                             the live endpoint's stats for every element, so a partial fetch cannot pass.

THE data_checked GATE. bps, bonus and occasionally goals/assists are revised until the event carries
`data_checked=True`. A gameweek is written as FINAL only when `finished and data_checked`; otherwise the
pull is refused unless --provisional, which writes to a separate *_PROVISIONAL_gw{n}.parquet (same schema)
plus a sidecar JSON carrying the event flags and pull time -- provisional rows are NEVER merged into the
season file or the combined stack, so downstream code cannot consume them by accident: finality is
represented by which FILE a row lives in, and the season file's sidecar records the flags per gameweek.

APPEND, DO NOT REBUILD. all_seasons_fixed.parquet is never touched. Final gameweeks upsert into
data/history/fpl_api_{tag}.parquet (atomic, deduped on element+fixture+GW). --combine then writes
data/history/all_seasons_with_{tag}.parquet = concat(all_seasons_fixed.parquet, fpl_api_{tag}.parquet)
with the schema asserted equal -- the archive stays the source of truth for the past; the API serves only
the current season. Nothing in modelling reads the combined file yet (deliberately -- season-boundary
constants are unfixed; see the report of 2026-08-31).

Columns with no API source (vaastav's own xP model and the long-dead legacy columns that are all-null in
recent seasons) are emitted as nulls of the correct dtype; none is read by modelling code.

Usage:
  uv run python eval/fetch_fpl_history.py --season 2026-27 --gw 1
  uv run python eval/fetch_fpl_history.py --season 2026-27 --gw 2 --provisional
  uv run python eval/fetch_fpl_history.py --season 2026-27 --combine
  uv run python eval/fetch_fpl_history.py --season 2026-27 --gw 1 --verify-vaastav data/history/vaastav_gw1_2026_27_reference.csv
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
STACK = HIST / "all_seasons_fixed.parquet"
API = "https://fantasy.premierleague.com/api"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot ingestion; weekly; contact: repo owner)"}
SLEEP = 0.4                     # seconds between element-summary calls
RETRIES = 3
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD", 5: "AM"}

# element-summary history fields copied verbatim into the identically-named stack columns
DIRECT = ["assists", "bonus", "bps", "clean_sheets", "clearances_blocks_interceptions", "creativity",
          "element", "fixture", "goals_conceded", "goals_scored", "ict_index", "influence",
          "kickoff_time", "minutes", "modified", "opponent_team", "own_goals", "penalties_missed",
          "penalties_saved", "recoveries", "red_cards", "saves", "selected", "tackles", "team_a_score",
          "team_h_score", "threat", "total_points", "transfers_balance", "transfers_in", "transfers_out",
          "value", "was_home", "yellow_cards", "expected_assists", "expected_goal_involvements",
          "expected_goals", "expected_goals_conceded", "starts", "defensive_contribution"]
# the columns any modelling code reads (investigation of 2026-08-31); the vaastav verifier holds these to 100%
MODELLING_READ = ["season", "element", "GW", "fixture", "name", "position", "team", "opponent_team",
                  "was_home", "kickoff_time", "minutes", "starts", "total_points", "value",
                  "goals_scored", "assists", "clean_sheets", "saves", "yellow_cards", "red_cards",
                  "goals_conceded", "penalties_missed", "own_goals", "bps", "bonus"]


class ProvisionalGameweekError(RuntimeError):
    """The event is not finished+data_checked; writing it as final is refused."""


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] fetch_fpl_history: {msg}", flush=True)


def get_json(path):
    url = f"{API}{path}"
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == RETRIES:
                raise
            wait = 2 ** attempt
            log(f"{path}: {type(e).__name__} ({e}) -- retry {attempt}/{RETRIES - 1} in {wait}s")
            time.sleep(wait)


def stack_schema():
    """The contract: exact columns, order and dtypes of the cross-season stack."""
    empty = pd.read_parquet(STACK).iloc[0:0]
    return list(empty.columns), empty.dtypes


def assert_final(events, gw):
    """The data_checked gate. Raises ProvisionalGameweekError unless the event is
    finished AND data_checked (bps/bonus/goals can be revised until then)."""
    ev = next((e for e in events if int(e["id"]) == int(gw)), None)
    if ev is None:
        raise ValueError(f"GW{gw} not in events[]")
    if not (ev.get("finished") and ev.get("data_checked")):
        raise ProvisionalGameweekError(
            f"GW{gw} is PROVISIONAL (finished={ev.get('finished')}, data_checked={ev.get('data_checked')}) "
            "-- bps/bonus/goals may still be revised. Refusing to write as final; use --provisional for a "
            "side file that is never merged.")
    return ev


def fetch_gw(season, gw, final=True):
    """One gameweek -> (frame in the exact stack schema, provenance dict).
    final=True keeps the event/live cross-check a HARD assert; for a provisional
    pull the two endpoints genuinely disagree while FPL revises the data (measured
    2026-08-31, GW2 pre-data_checked: 31 cells, minutes off by up to 12), so the
    mismatches are RECORDED in provenance instead of raising -- the side file is
    labelled provisional precisely because its numbers are still moving."""
    cols, dtypes = stack_schema()
    bs = get_json("/bootstrap-static/")
    ev = next(e for e in bs["events"] if int(e["id"]) == int(gw))
    season_api = f"{datetime.fromisoformat(bs['events'][0]['deadline_time'].replace('Z', '+00:00')).year}"
    exp_season = f"{season_api}-{str(int(season_api) + 1)[-2:]}"
    assert exp_season == season, f"the API serves {exp_season}, not {season} -- past seasons cannot be pulled"
    teams = {t["id"]: t["name"] for t in bs["teams"]}
    fixtures = {f["id"]: f for f in get_json("/fixtures/")}
    meta = {e["id"]: e for e in bs["elements"]}
    rows, n_calls = [], 0
    t0 = time.time()
    for el_id in sorted(meta):
        n_calls += 1
        es = get_json(f"/element-summary/{el_id}/")
        time.sleep(SLEEP)
        if n_calls % 50 == 0:
            log(f"  element-summary {n_calls}/{len(meta)} ({time.time() - t0:.0f}s)")
        for h in es["history"]:
            if int(h["round"]) != int(gw):
                continue
            fx = fixtures.get(h["fixture"])
            assert fx is not None, f"element {el_id}: fixture {h['fixture']} not in fixtures/"
            assert int(fx["event"]) == int(gw), f"element {el_id}: fixture {h['fixture']} is GW{fx['event']}"
            team_id = fx["team_h"] if h["was_home"] else fx["team_a"]
            m = meta[el_id]
            rows.append({**{c: h[c] for c in DIRECT},
                         "GW": int(h["round"]), "round": int(h["round"]),
                         "season": season,
                         "name": f"{m['first_name']} {m['second_name']}",
                         "position": POS[m["element_type"]],
                         "team": teams[team_id]})
    df = pd.DataFrame(rows)
    assert not df.duplicated(["element", "fixture"]).any(), "duplicate (element, fixture) rows"
    # cross-check: per-gameweek sums must equal event/{gw}/live for EVERY element (partial fetch cannot pass)
    lv = {e["id"]: e["stats"] for e in get_json(f"/event/{gw}/live/")["elements"]}
    sums = df.groupby("element")[["minutes", "total_points", "bps", "bonus", "goals_scored", "starts"]].sum()
    bad = []
    for el_id, st in lv.items():
        got = sums.loc[el_id] if el_id in sums.index else None
        for c in ("minutes", "total_points", "bps", "bonus", "goals_scored", "starts"):
            want = st[c]
            have = int(got[c]) if got is not None else 0
            if int(want) != have:
                bad.append((el_id, c, want, have))
    if final:
        assert not bad, f"element-summary sums disagree with event/live on {len(bad)} cells: {bad[:5]}"
    elif bad:
        log(f"provisional pull: {len(bad)} cells disagree with event/live (FPL is still revising "
            f"this gameweek); recorded in provenance, e.g. {bad[:3]}")
    # exact schema: add API-less columns as nulls, order and cast
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[cols]
    for c in cols:
        try:
            df[c] = df[c].astype(dtypes[c])
        except (TypeError, ValueError):
            # all-null legacy columns: an object column of NA casts to float via to_numeric
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(dtypes[c])
    prov = dict(season=season, gw=int(gw), pulled_at=datetime.now(timezone.utc).isoformat(),
                finished=bool(ev.get("finished")), data_checked=bool(ev.get("data_checked")),
                rows=len(df), elements=int(df["element"].nunique()),
                fixtures=int(df["fixture"].nunique()), api_calls=n_calls + 3,
                live_crosscheck_mismatches=len(bad),
                live_crosscheck_examples=[list(x) for x in bad[:5]])
    check = "PASSED" if not bad else f"{len(bad)} mismatches RECORDED (provisional window)"
    log(f"GW{gw}: {len(df)} player-fixture rows, {prov['fixtures']} fixtures, "
        f"{prov['api_calls']} calls, cross-check vs event/live {check}")
    return df, prov


def write_final(df, prov, season):
    tag = season.replace("-", "_")
    out = HIST / f"fpl_api_{tag}.parquet"
    side = HIST / f"fpl_api_{tag}.provenance.json"
    if out.exists():
        old = pd.read_parquet(out)
        df = (pd.concat([old[old["GW"] != prov["gw"]], df], ignore_index=True)
              .sort_values(["GW", "element", "fixture"]).reset_index(drop=True))
    tmp = out.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    meta[str(prov["gw"])] = prov
    side.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(f"FINAL -> {out.name} ({len(df)} rows, gws {sorted(df['GW'].unique())}); provenance -> {side.name}")
    return out


def write_provisional(df, prov, season):
    tag = season.replace("-", "_")
    out = HIST / f"fpl_api_{tag}_PROVISIONAL_gw{prov['gw']}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    log(f"PROVISIONAL -> {out.name} -- never merged into the season file or the combined stack")
    return out


def combine(season):
    """all_seasons_fixed.parquet (UNTOUCHED) + the API season file -> the combined stack."""
    tag = season.replace("-", "_")
    api = pd.read_parquet(HIST / f"fpl_api_{tag}.parquet")
    base = pd.read_parquet(STACK)
    assert list(api.columns) == list(base.columns), "schema drift between API file and the stack"
    for c in base.columns:
        if api[c].dtype != base[c].dtype:
            # Parquet round-trip artefact, not drift: e.g. `modified` reads from the
            # stack as object only because pre-2017 seasons carry nulls; an all-bool
            # season column reads back as bool. Cast losslessly to the stack dtype --
            # a genuine incompatibility still raises here.
            api[c] = api[c].astype(base[c].dtype)
    assert (api.dtypes == base.dtypes).all(), "dtype drift between API file and the stack"
    assert season not in set(base["season"]), f"{season} already in the stack -- refusing to double-append"
    out = HIST / f"all_seasons_with_{tag}.parquet"
    combined = pd.concat([base, api], ignore_index=True)
    tmp = out.with_suffix(".tmp.parquet")
    combined.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    log(f"COMBINED -> {out.name}: {len(base)} archive rows (source of truth, untouched) + {len(api)} API rows")
    return out


def verify_vaastav(season, gw, csv_path):
    """The deliverable check: column-by-column exact-match vs vaastav's published gw file."""
    tag = season.replace("-", "_")
    api = pd.read_parquet(HIST / f"fpl_api_{tag}.parquet")
    api = api[api["GW"] == gw].copy()
    va = pd.read_csv(csv_path, low_memory=False)
    if "GW" not in va.columns:
        va["GW"] = gw
    j = va.merge(api, on=["element", "fixture"], suffixes=("_va", "_api"), how="outer", indicator=True)
    print(f"\nVERIFY vs vaastav GW{gw}: vaastav {len(va)} rows, api {len(api)} rows, "
          f"matched {(j['_merge'] == 'both').sum()}, vaastav-only {(j['_merge'] == 'left_only').sum()}, "
          f"api-only {(j['_merge'] == 'right_only').sum()}")
    b = j[j["_merge"] == "both"]
    shared = [c for c in va.columns if c not in ("element", "fixture") and f"{c}_api" in b.columns]
    fails = []
    print(f"{'column':34s} {'exact':>8s}   (modelling-read columns must be 100%)")
    for c in sorted(shared, key=lambda c: (c not in MODELLING_READ, c)):
        a, v = b[f"{c}_api"], b[f"{c}_va"]
        try:
            av, vv = pd.to_numeric(a, errors="raise"), pd.to_numeric(v, errors="raise")
            eq = (av.fillna(-9e9).round(6) == vv.fillna(-9e9).round(6))
        except (ValueError, TypeError):
            eq = a.astype(str).fillna("<na>") == v.astype(str).fillna("<na>")
        tagm = "*" if c in MODELLING_READ else " "
        print(f"{tagm}{c:33s} {eq.mean():8.2%}" + ("" if eq.all() else
              f"   e.g. {b.loc[~eq, ['element', f'{c}_va', f'{c}_api']].head(2).to_dict('records')}"))
        if c in MODELLING_READ and not eq.all():
            fails.append(c)
    if fails or (j["_merge"] != "both").any():
        print(f"\nVERIFY: FAIL -- modelling-read mismatches {fails}, row diffs "
              f"{int((j['_merge'] != 'both').sum())}")
        return False
    print("\nVERIFY: PASS -- every modelling-read column 100.00% exact, row sets identical")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--gw", type=int)
    ap.add_argument("--provisional", action="store_true",
                    help="allow a not-data_checked gameweek, into a side file that is never merged")
    ap.add_argument("--combine", action="store_true")
    ap.add_argument("--verify-vaastav", default=None, help="path to vaastav's gw csv to compare against")
    a = ap.parse_args()
    if a.combine:
        combine(a.season)
        return
    if a.verify_vaastav and a.gw:
        ok = verify_vaastav(a.season, a.gw, a.verify_vaastav)
        sys.exit(0 if ok else 1)
    assert a.gw, "--gw required"
    bs_events = get_json("/bootstrap-static/")["events"]
    try:
        assert_final(bs_events, a.gw)
        final = True
    except ProvisionalGameweekError as e:
        if not a.provisional:
            raise
        log(str(e))
        final = False
    df, prov = fetch_gw(a.season, a.gw, final=final)
    if final:
        write_final(df, prov, a.season)
    else:
        write_provisional(df, prov, a.season)


if __name__ == "__main__":
    main()
