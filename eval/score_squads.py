"""
Score the user's hypothetical squad against realised points -- the tick-level
scoring step of the weekly ingest (Decision 2, 2026-09-12; squad_store's
module header carries the contract and the RULE 1 warning: squad_scores is
operational evidence, never a configuration argument).

Called by eval/run_weekly_ingest.py on EVERY tick (after a successful chain
and on NOTHING-NEW ticks) with a request file naming every ingested gameweek
and its deadline:

    {"season": "2026-27", "deadlines": {"1": "2026-08-15T17:30:00Z", ...}}

For each gameweek in the request, in order:
  * no version existed before that deadline  -> "no squad at deadline" (skipped;
    earlier gameweeks are never backfilled -- the squad did not exist for them)
  * a row with the same master_rows_hash exists -> "already scored"
  * otherwise score it with squad_store.score_gameweek_for (autosubs, armband,
    hits deducted) and INSERT one append-only row; a different hash for a
    gameweek already scored means FPL corrected the data -> a NEW row, and the
    line says so.

Exit 0 when every gameweek was handled (scored, already scored, or no squad).
Exit 1 on any failure (master unreadable, database unreachable, inconsistent
versions) -- the runner turns that into an ACTION REQUIRED line and retries on
the next tick; nothing else is affected.

    uv run python eval/score_squads.py --season 2026-27 --request data/live/_scoring_request.json
    ... --dry-run          # everything except the INSERT (rolled back)
    ... --demo-gw 3        # MECHANICS DEMO: score the ACTIVE squad against GW3's
                           # rows regardless of when it was created; never written
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import db_write                                            # noqa: E402
import squad_store                                         # noqa: E402


def master_path(data_dir, season):
    return Path(data_dir) / "history" / f"fpl_api_{season.replace('-', '_')}.parquet"


def score_request(conn, master, season, deadlines, user_id=1, dry_run=False, git=None, out=print):
    """The per-gameweek loop, testable with a fake connection. Returns the
    number of rows written (0 under dry_run)."""
    versions = squad_store.read_versions(conn, user_id, season)
    with conn.cursor() as cur:
        cur.execute(squad_store.SCORE_HASHES_SQL, (user_id, season))
        existing = {}
        for gw, h, sid, pts in cur.fetchall():
            existing.setdefault(int(gw), []).append((h, sid, pts))
    written = 0
    failed = 0
    names = {}
    for v in versions:
        for p in v["squad_json"]["players"]:
            names[int(p["element"])] = p["name"]

    def nm(e):
        return f"{names.get(e, 'element')} ({e})" if e is not None else "nobody"

    # Per-gameweek outcome lines are the runner's contract (it parses the
    # first token after "GWn:"): scored | DRY RUN would write | already scored |
    # no squad | FAILED [class] ...  A failure in one gameweek never stops the
    # others; the exit code says whether any failed.
    for gw in sorted(int(g) for g in deadlines):
        deadline = deadlines[str(gw)] if str(gw) in deadlines else deadlines[gw]
        try:
            try:
                actuals = squad_store.actuals_from_master(master, gw)
            except ValueError as e:
                out(f"GW{gw}: FAILED [master_missing] {e} (the season file lists GW{gw} as ingested)")
                failed += 1
                continue
            h = squad_store.master_rows_hash(master, gw)
            seen = existing.get(gw, [])
            if any(h == s[0] for s in seen):
                sid, pts = next((s[1], s[2]) for s in seen if s[0] == h)
                out(f"GW{gw}: already scored (score_id {sid}, {pts} pts, inputs unchanged)")
                continue
            try:
                row = squad_store.score_gameweek_for(versions, gw, deadline, actuals)
            except RuntimeError as e:
                out(f"GW{gw}: FAILED [inconsistent_versions] {e}")
                failed += 1
                continue
            if row is None:
                first = min((v["created_at"] for v in versions), default=None)
                out(f"GW{gw}: no squad at deadline {deadline} (first version {first}) -- nothing to score")
                continue
            corrected = (f" [FPL CORRECTION: supersedes score_id {seen[-1][1]} ({seen[-1][2]} pts)]"
                         if seen else "")
            note = ("scored by eval/score_squads.py" + (" (correction)" if seen else ""))
            sid = squad_store.write_score(conn, user_id, season, row, h, git=git, note=note,
                                          confirm=not dry_run)
            subs = ", ".join(f"{nm(o)} -> {nm(i)}" for o, i in row["subs_made"]) or "none"
            out(f"GW{gw}: {'DRY RUN would write' if dry_run else 'scored'} {row['points_net']} pts "
                f"(raw {row['points_raw']}, hit {row['hit']}; armband {row['doubled_role']} "
                f"{nm(row['doubled'])} +{row['captain_bonus']}; autosubs {subs}; bench "
                f"{row['bench_points']}) for version {row['version_id']}, transfers "
                f"{row['transfers_made']} vs allowance {row['free_transfers']}{corrected}"
                + ("" if dry_run else f" -> score_id {sid}"))
            if not dry_run and sid is not None:
                written += 1
        except Exception as e:                                   # anything else: loud, classified
            out(f"GW{gw}: FAILED [error] {type(e).__name__}: {e}")
            failed += 1
    if failed:
        raise ScoringFailed(f"{failed} gameweek(s) failed (see the GWn: FAILED lines)", written)
    return written


class ScoringFailed(RuntimeError):
    def __init__(self, msg, written):
        super().__init__(msg)
        self.written = written


def demo(conn, master, season, gw, user_id=1, out=print):
    """Mechanics demonstration: score the ACTIVE version against gameweek
    `gw`'s realised rows regardless of when the version was created. Written
    nowhere. Labelled loudly so it cannot be read as a result."""
    from scoring import score_gameweek
    rec = squad_store.read_active(user_id, conn=conn)
    actuals = squad_store.actuals_from_master(master, gw)
    res = score_gameweek(squad_store.scoring_frame(rec["squad_json"]), actuals,
                         transfers_made=0, free_transfers=1)
    names = {p["element"]: p["name"] for p in rec["squad_json"]["players"]}
    pts = dict(zip(actuals["element"], actuals["total_points"]))
    mins = dict(zip(actuals["element"], actuals["minutes"]))
    out(f"MECHANICS DEMO ONLY -- version {rec['version_id']} (created {rec['created_at']}) against "
        f"GW{gw}'s rows; NOT written, NOT a result (the squad did not exist at that deadline)")
    out(f"  final XI: " + ", ".join(f"{names.get(e, e)} {pts.get(e, 0)}p/{mins.get(e, 0)}m" for e in res["final_xi"]))
    out(f"  armband: {res['doubled_role']} {names.get(res['doubled'], res['doubled'])} +{res['captain_bonus']}")
    out(f"  autosubs: " + (", ".join(f"{names.get(o, o)} -> {names.get(i, i)}" for o, i in res["subs_made"]) or "none"))
    out(f"  raw {res['raw_points']}, hit {res['hit']}, net {res['points']}, bench {res['bench_points']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--request", default=None, help="JSON {season, deadlines: {gw: iso}}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--demo-gw", type=int, default=None)
    ap.add_argument("--user", type=int, default=1)
    ap.add_argument("--data-dir", default=str(REPO / "data"))
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        master = pd.read_parquet(master_path(a.data_dir, a.season),
                                 columns=["element", "GW", "fixture", "minutes", "total_points"])
    except Exception as e:
        print(f"score_squads FAILED [master_unreadable] {type(e).__name__}: {e}")
        return 1
    try:
        conn = db_write.connect()
    except Exception as e:
        print(f"score_squads FAILED [db_unreachable] {type(e).__name__}: {e}")
        return 1
    try:
        if a.demo_gw is not None:
            demo(conn, master, a.season, a.demo_gw, user_id=a.user)
            return 0
        if not a.request:
            print("--request or --demo-gw required", file=sys.stderr)
            return 2
        req = json.loads(Path(a.request).read_text(encoding="utf-8"))
        try:
            n = score_request(conn, master, a.season, req["deadlines"], user_id=a.user,
                              dry_run=a.dry_run, git=db_write.git_sha())
        except ScoringFailed as e:
            print(f"score_squads: {e.written} row(s) written; {e}")
            return 1
        print(f"score_squads: {n} row(s) written{' (dry run)' if a.dry_run else ''}")
        return 0
    except Exception:
        print("score_squads FAILED [error]:\n" + traceback.format_exc()[-3000:])
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
