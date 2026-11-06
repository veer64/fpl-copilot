# refresh_team_scores.py -- Prompt W3 (5 Nov 2026): the weekly score refresh of every imported FPL team (user_fpl_teams).
# USER DECISION (5 Nov): "Team scores from FPL's public history (total from GW1), refreshed weekly; squads refresh only when
# the user taps Refresh." So this job touches the SUMMARY columns only (fpl_teams.write_summary: total points, overall rank,
# the last finished gameweek and its points, updated_after_gw) -- never squad_versions.
#
# One bootstrap request (FPL's finished flags), then ONE request per DISTINCT imported team (entry/{id}/history/), through
# fpl_import.fetch_json so they are MIN_INTERVAL_S (1 s) apart; every user's row of that team is updated. A team whose
# summary already covers FPL's latest finished gameweek is skipped with no request, so the hourly-ish tick is a single
# bootstrap request until a gameweek finishes ("after each confirmed gameweek"); --force refreshes every team regardless.
# A team FPL refuses (404: deleted; 5xx / timeout) is reported and the others still run; exit 1 when any failed.
#
# Cron (server root crontab; NOT installed by Prompt W3 -- the line to add, 10 min after each weekly-ingest tick, its own
# lock, no dispatcher lock: it never touches the data volume):
#   27 */6 * * * cd /root/fpl-copilot && flock -n /tmp/fpl-teamscores.lock \
#       docker compose run --rm fpl-scheduler uv run python eval/refresh_team_scores.py \
#       >> /var/log/fpl-teamscores.log 2>&1
# By hand: `uv run python eval/refresh_team_scores.py [--force]` from the repo root (DB_* from the environment / .env).
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fpl_import   # noqa: E402
import fpl_teams    # noqa: E402


def run(force=False, get=None, conn=None, log=None):
    """The job's body. Returns {"teams", "latest_finished_gw", "refreshed": [(fpl_team_id, rows)], "skipped": [ids],
    "failed": [(fpl_team_id, reason)], "requests"}."""
    log = log or (lambda *a: None)
    before = fpl_import._STATE["requests"]
    teams = fpl_teams.all_team_ids(conn=conn)
    out = {"teams": len(teams), "latest_finished_gw": None, "refreshed": [], "skipped": [], "failed": [], "requests": 0}
    if not teams:
        log("no imported teams: nothing to refresh")
        return out
    boot = fpl_import.bootstrap(get=get)
    latest = fpl_import.latest_finished_gw(boot)
    out["latest_finished_gw"] = latest
    for fid, have_gw in teams:
        if not force and latest is not None and have_gw is not None and have_gw >= latest:
            out["skipped"].append(fid)
            continue
        try:
            summary = fpl_import.fetch_summary(fid, get=get)
        except (fpl_import.FplNotFound, fpl_import.FplUnavailable) as e:
            out["failed"].append((fid, f"{type(e).__name__}: {e}"))
            log(f"team {fid}: FAILED {type(e).__name__}: {e}")
            continue
        n = fpl_teams.write_summary(fid, summary, conn=conn)
        out["refreshed"].append((fid, n))
        log(f"team {fid}: {n} row(s) -> total {summary['total_points']}, rank {summary['overall_rank']}, "
            f"GW{summary['last_gw']} {summary['last_gw_points']} pts, after GW{summary['updated_after_gw']}")
    out["requests"] = fpl_import._STATE["requests"] - before
    return out


def exit_code(out):
    return 1 if out.get("failed") else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="refresh the score summary of every imported FPL team (never the squad)")
    ap.add_argument("--force", action="store_true", help="refresh every team, even one already after the latest finished gameweek")
    args = ap.parse_args(argv)
    t0 = datetime.now(timezone.utc)
    print(f"[{t0.strftime('%Y-%m-%dT%H:%M:%SZ')}] refresh_team_scores start (force={args.force})", flush=True)
    out = run(force=args.force, log=lambda m: print("  " + m, flush=True))
    t1 = datetime.now(timezone.utc)
    print(f"[{t1.strftime('%Y-%m-%dT%H:%M:%SZ')}] {'FAILED' if out['failed'] else 'SUCCESS'} -- teams {out['teams']}, "
          f"latest finished GW {out['latest_finished_gw']}, refreshed {len(out['refreshed'])}, skipped {len(out['skipped'])}, "
          f"failed {len(out['failed'])}, FPL requests {out['requests']}, {(t1 - t0).total_seconds():.1f} s", flush=True)
    return exit_code(out)


if __name__ == "__main__":
    sys.exit(main())
