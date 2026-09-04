"""PRE-DEADLINE LIVE PROPS PULL: the anytime-goalscorer board for an upcoming
deadline gameweek, from the LIVE endpoint (markets x regions = 3 credits per
fixture at eu,us,us2 -- not the historical endpoint's 10x surcharge). The last
input between the combined config and a live prediction.

REUSE, not a parallel path: this feeds the SAME three-step pipeline
(pull -> build_props_crosswalk -> build_props_consensus) by writing the SAME raw
layout the historical pull writes -- data/odds_props/raw/scale/{season}/
gw{gw:02d}_{event_id}_{regions}.json wrapped as {"data": ...} plus manifest.csv
rows -- and it imports the historical module's own helpers (fixtures, deadlines,
token matching, atomic writes). NEW here: the live endpoints, snapshot-replace
semantics, and the timestamp provenance.

TIMING, the load-bearing decision: the historical convention was the last board
strictly before the deadline (deadline - 60s), which cannot run that late
unattended and safely. Cadence implemented: run in the pre-deadline build
sequence (recommended T-90..T-30 min before the deadline), and RE-PULLS REPLACE
the gameweek's rows -- the latest pre-deadline snapshot is the snapshot of
record. The investigation's position (the pre-deadline snapshot IS the
decision-relevant information set) HOLDS for props, with one strengthening fact:
the FPL deadline sits ~90 min before first kickoff, so confirmed lineups are out
NEITHER at deadline-60s NOR at T-90 -- both snapshots are the same pre-lineup
information class, differing only by up to ~an hour of drift. The per-fixture
pull timestamp goes into the manifest's snapshot column: WHICH board produced a
price is provenance that matters.

The book panel gate is untouched: the consensus builder drops rule-less books
counted, the hook asserts at construction. A board that is unavailable or thin
produces no/partial consensus rows and the strict coverage floor RAISES at the
deadline gameweek -- the combined config can never silently become horizon-only.

Usage: uv run python eval/pull_live_props.py --season 2026-27 --gw 3
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "squad"))

import pull_player_props_history as hist  # noqa: E402  (fixtures, deadlines, tok, atomic_write, REGIONS)
import probe_player_props_coverage as p   # noqa: E402  (get, load_key, SPORT, MARKET)

MIN_REMAINING = 1500


def pull_gw(season, gw):
    key = p.load_key()
    dl = hist.fpl_deadlines(season)
    assert gw in dl, f"GW{gw} has no FPL deadline in the events array"
    deadline = dl[gw]
    d0 = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if now >= d0:
        print(f"WARNING: GW{gw} deadline {deadline} has PASSED -- this board is post-deadline "
              f"information and must not feed a decision for GW{gw}")
    fx = hist.fixtures(season)
    ffx = fx[fx["gw"] == gw]
    assert len(ffx), f"no GW{gw} fixtures on the stack"

    out_dir = hist.RAW / season
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.csv"

    # events list: FREE on the live API
    ev, q = p.get(f"/sports/{p.SPORT}/events", {}, key)
    if ev is None:
        raise RuntimeError("live events call failed -- the board is unavailable; the strict "
                           "coverage floor will raise; retry closer to the deadline or run baseline")
    remaining = int(q["x-requests-remaining"]); spent = 0
    events = ev if isinstance(ev, list) else ev.get("data", ev)

    rows, unmatched = [], []
    for r in ffx.itertuples():
        cands = [e for e in events if hist.tok(r.home) in e["home_team"].lower()
                 and hist.tok(r.away) in e["away_team"].lower()]
        if len(cands) != 1:
            unmatched.append((r.home, r.away, len(cands)))
            rows.append([season, gw, r.fixture, r.home, r.away, r.kickoff.isoformat(), deadline,
                         "", now.strftime("%Y-%m-%dT%H:%M:%SZ"), "", "", "",
                         f"UNMATCHED({len(cands)})", "", 0, remaining])
            continue
        e = cands[0]
        if remaining < MIN_REMAINING:
            raise RuntimeError(f"remaining {remaining} < {MIN_REMAINING}: refusing to spend further")
        od, q = p.get(f"/sports/{p.SPORT}/events/{e['id']}/odds",
                      {"regions": hist.REGIONS, "markets": p.MARKET, "oddsFormat": "decimal"}, key)
        pulled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if od is None:
            rows.append([season, gw, r.fixture, r.home, r.away, r.kickoff.isoformat(), deadline,
                         e["id"], pulled_at, "", "", "", "CALL_FAILED", "", 0, remaining])
            print(f"  {r.home} v {r.away}: odds call FAILED -- recorded; this fixture stays "
                  f"unpriced (counted; the floor sees it)")
            continue
        cost = int(q["x-requests-last"] or 0); remaining = int(q["x-requests-remaining"]); spent += cost
        payload = od if isinstance(od, dict) and "data" in od else {"data": od}
        od_path = out_dir / f"gw{gw:02d}_{e['id']}_{hist.REGIONS.replace(',', '')}.json"
        hist.atomic_write(od_path, payload)          # REPLACES any earlier snapshot -- latest wins
        bks = payload["data"].get("bookmakers", [])
        books = "|".join(sorted(b["key"] for b in bks))
        nplayers = {b["key"]: sum(len(m.get("outcomes", [])) for m in b.get("markets", [])) for b in bks}
        gap_min = round((d0 - datetime.now(timezone.utc)).total_seconds() / 60, 1)
        rows.append([season, gw, r.fixture, r.home, r.away, r.kickoff.isoformat(), deadline,
                     e["id"], pulled_at, pulled_at, "LIVE", gap_min, books, json.dumps(nplayers),
                     cost, remaining])
        print(f"  {r.home} v {r.away}: {len(bks)} books, snapshot {pulled_at} "
              f"({gap_min:+.0f} min to deadline), cost {cost}")
        time.sleep(0.4)

    # manifest: REPLACE this gameweek's rows (re-pulls supersede; latest pre-deadline
    # snapshot is the record), keep every other gameweek's rows untouched
    header = ["season", "gw", "fixture", "home", "away", "kickoff", "deadline", "event_id",
              "query_date", "snapshot", "next_snapshot", "gap_min", "books", "players_by_book",
              "cost", "remaining"]
    kept = []
    if manifest.exists():
        with open(manifest, newline="", encoding="utf-8") as f:
            kept = [r for r in csv.DictReader(f) if int(r["gw"]) != gw]
    tmp = manifest.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in kept:
            w.writerow([r.get(h, "") for h in header])
        for r in rows:
            w.writerow(r)
    import os
    from _replace_retry import replace_with_retry
    replace_with_retry(tmp, manifest)
    n_ok = sum(1 for r in rows if r[12] not in ("CALL_FAILED",) and not str(r[12]).startswith("UNMATCHED"))
    print(f"GW{gw}: {n_ok}/{len(ffx)} fixtures pulled ({spent} credits, remaining {remaining}); "
          f"unmatched {unmatched or 'none'}")
    print("next: uv run python eval/build_props_crosswalk.py && "
          f"uv run python eval/build_props_consensus.py --seasons {season}")
    return n_ok, len(ffx), spent, remaining


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--gw", type=int, required=True)
    a = ap.parse_args()
    pull_gw(a.season, a.gw)


if __name__ == "__main__":
    main()
